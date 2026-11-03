"""Private pipe worker for Chatterbox; use NC's interpreter and synthesis service."""
from __future__ import annotations

from contextlib import redirect_stdout
import json
import logging
import os
from pathlib import Path
import queue
import sys
import threading
import warnings
from types import SimpleNamespace


class _UnsupportedRedirectNoticeFilter(logging.Filter):
    def filter(self, record):
        return not (
            record.levelno == logging.WARNING
            and record.getMessage() == 'NOTE: Redirects are currently not supported in Windows or MacOs.'
        )


def _configure_worker_logging():
    """Hide only known dependency notices in this private worker."""
    warnings.filterwarnings(
        'ignore', category=UserWarning,
        message=r'^pkg_resources is deprecated as an API\.',
        module=r'^perth\.perth_net$',
    )
    warnings.filterwarnings(
        'ignore', category=FutureWarning,
        message=r'^`LoRACompatibleLinear` is deprecated and will be removed in version 1\.0\.0\.',
        module=r'^diffusers\.models\.lora$',
    )
    logger = logging.getLogger('torch.distributed.elastic.multiprocessing.redirects')
    if not any(isinstance(item, _UnsupportedRedirectNoticeFilter) for item in logger.filters):
        logger.addFilter(_UnsupportedRedirectNoticeFilter())


class WorkerConfig:
    def __init__(self):
        self.values = {}
        self.device = 'cpu'

    def get(self, key, default=None):
        return self.values.get(key, default)

    def tts_device(self):
        return self.device


class _RequestAbort(threading.Event):
    """Native service clear() must not undo a concurrent control cancellation."""
    def __init__(self):
        super().__init__()
        self._guard = threading.Lock()
        self._cancelled = False

    def begin(self):
        with self._guard:
            self._cancelled = False
            super().clear()

    def cancel(self):
        with self._guard:
            self._cancelled = True
            super().set()

    def clear(self):
        with self._guard:
            if not self._cancelled:
                super().clear()


def _save_audio(value, path, sample_rate):
    import numpy as np
    import soundfile as sf
    if callable(getattr(value, 'detach', None)):
        value = value.detach().cpu().numpy()
    audio = np.asarray(value, dtype=np.float32)
    if audio.ndim == 2 and audio.shape[0] == 1:
        audio = audio[0]
    if audio.ndim != 1 or not audio.size or not np.isfinite(audio).all():
        raise ValueError('Chatterbox returned invalid mono audio.')
    # FLOAT WAV preserves the original float32 samples; no PCM quantization.
    sf.write(path, audio, int(sample_rate), subtype='FLOAT')


def serve(service, runtime, directory, input_stream, output_stream):
    """One inference lane plus an independent blocking control reader."""
    directory = Path(directory).resolve()
    output_lock = threading.Lock()
    control_lock = threading.Lock()
    requests = queue.Queue(maxsize=2)
    stopping = threading.Event()
    abort = _RequestAbort()
    service._abort_event = abort
    cancelled = set()
    queued = set()
    active_id = None

    def emit(message):
        with output_lock:
            output_stream.write(json.dumps(message, allow_nan=False) + '\n')
            output_stream.flush()

    def state():
        model = getattr(service, '_model', None)
        emit({'kind': 'state', 'loaded': model is not None,
              'device': str(getattr(model, 'device', 'Unavailable'))})

    def diagnose(event, **fields):
        emit({'kind': 'event', 'event': str(event), 'fields': fields})
    capabilities = getattr(getattr(service, '_context', None), 'capabilities', None)
    if capabilities is not None:
        capabilities.diagnostics = diagnose

    def inference():
        nonlocal active_id
        thread_limits_set = False
        while True:
            request = requests.get()
            if request is None:
                break
            rid = request.get('id')
            with control_lock:
                queued.discard(rid)
                if stopping.is_set() or rid in cancelled:
                    cancelled.discard(rid)
                    emit({'kind': 'result', 'id': rid, 'ok': False, 'cancelled': True})
                    continue
                active_id = rid
                abort.begin()
            result = {'kind': 'result', 'id': rid}
            path = directory / (rid + '.wav')
            try:
                runtime.values = dict(request.get('settings') or {})
                runtime.device = str(request.get('device') or 'cpu')
                limits = request.get('threads')
                if limits and not thread_limits_set:
                    import torch
                    if torch.get_num_threads() != limits[0]:
                        torch.set_num_threads(int(limits[0]))
                    if torch.get_num_interop_threads() != limits[1]:
                        torch.set_num_interop_threads(int(limits[1]))
                    thread_limits_set = True
                seed = request.get('seed')
                if seed is not None:
                    import random
                    import numpy as np
                    import torch
                    random.seed(seed)
                    np.random.seed(seed % 2**32)
                    torch.manual_seed(seed)
                action = request['action']
                kwargs = dict(request.get('kwargs') or {})
                with redirect_stdout(sys.stderr):
                    if action == 'warm_up':
                        value = service.warm_up()
                    elif action == 'prepare_voice':
                        value = service.prepare_voice(request.get('audio_prompt_path'), **kwargs)
                    elif action == 'generate_reference':
                        value = service.generate_reference(request['text'], request['audio_prompt_path'], abort)
                    elif action == 'generate':
                        value = service.generate(request['text'], audio_prompt_path=request.get('audio_prompt_path'), **kwargs)
                    else:
                        raise ValueError('Unknown Chatterbox operation.')
                    if action in {'generate', 'generate_reference'}:
                        _save_audio(value, path, service.sr)
                        result['audio'] = True
                    else:
                        result['result'] = bool(value)
                result['ok'] = True
            except Exception as error:
                result.update(ok=False, error=str(error) or type(error).__name__)
            finally:
                with control_lock:
                    result['cancelled'] = abort.is_set() or rid in cancelled or stopping.is_set()
                    cancelled.discard(rid)
                    active_id = None
                if result['cancelled'] or not result.get('ok'):
                    path.unlink(missing_ok=True)
                state()
                emit(result)
        with redirect_stdout(sys.stderr):
            service.close_strict()

    def read_control():
        try:
            for line in input_stream:
                request = json.loads(line)
                action = request.get('action')
                if action == 'close':
                    break
                if action == 'cancel':
                    with control_lock:
                        rid = request.get('id')
                        if rid == active_id:
                            abort.cancel()
                        elif rid in queued:
                            cancelled.add(rid)
                    continue
                rid = request.get('id')
                if not isinstance(rid, str) or len(rid) != 32 or any(c not in '0123456789abcdef' for c in rid):
                    raise ValueError('Invalid Chatterbox request id.')
                with control_lock:
                    queued.add(rid)
                    requests.put_nowait(request)
        finally:
            with control_lock:
                stopping.set()
                abort.cancel()
            requests.put(None)

    # Keep inference on main; the control lane can independently cancel or stop.
    # Native libraries must already be initialized before stdin is read here.
    thread = threading.Thread(target=read_control, name='chatterbox-control', daemon=True)
    emit({'kind': 'ready', 'pid': os.getpid()})
    thread.start()
    inference()


def main():
    # Match the parent's UTF-8 pipe decoding even when NC was started with a
    # legacy Windows encoding. Configure before native-library status output.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if callable(reconfigure):
            reconfigure(encoding='utf-8')
    _configure_worker_logging()
    # Preserve stdout exclusively for protocol frames, including import-time
    # library messages. Models and CUDA only exist inside this process.
    output = sys.stdout
    with redirect_stdout(sys.stderr):
        # OpenBLAS/libgfortran DLL initialization can deadlock against a pending
        # stdin pipe read on Windows (numpy/numpy#24290). Load both NumPy's and
        # SciPy's native stacks before starting the independent control reader.
        import numpy
        import scipy.linalg
        import scipy.sparse.linalg
        import torch
        from addons.chatterbox_tts.service import (
            ChatterboxTTSService, _disable_transformers_torchvision_probe,
        )
        _disable_transformers_torchvision_probe()
        from chatterbox import tts_turbo
        runtime = WorkerConfig()
        context = SimpleNamespace(capabilities=SimpleNamespace(runtime_config=runtime, diagnostics=None))
        service = ChatterboxTTSService(context)
    serve(service, runtime, Path(sys.argv[1]), sys.stdin, output)


if __name__ == '__main__':
    main()
