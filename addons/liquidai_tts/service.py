"""Lazy, isolated LiquidAI TTS process with exact ownership and cancellable Stop."""
from __future__ import annotations

import base64
import binascii
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
import json
import logging
import os
from pathlib import Path
import queue
import secrets
import subprocess
import tempfile
import threading
import time
import uuid
import wave

from .config import DEFAULTS, managed_paths, normalize_settings, validate_model_folder

if TYPE_CHECKING:
    from core.incremental_audio import PCMBlock


class _ProtocolError(RuntimeError):
    pass


@dataclass(frozen=True)
class _CancellationWake:
    request_id: str


class _RequestLock:
    """Serialize worker requests, with a signalled wakeup for queued cancellation."""
    def __init__(self):
        self._condition = threading.Condition()
        self._locked = False

    def acquire(self, cancelled=None):
        with self._condition:
            self._condition.wait_for(lambda: not self._locked or cancelled is not None and cancelled())
            if cancelled is not None and cancelled():
                raise InterruptedError('LiquidAI speech request cancelled.')
            self._locked = True
        return True

    def release(self):
        with self._condition:
            self._locked = False
            self._condition.notify_all()

    def wake(self):
        with self._condition:
            self._condition.notify_all()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_args):
        self.release()


@dataclass
class _Worker:
    process: object
    temporary: object
    fingerprint: tuple
    device: str
    instance_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    messages: queue.Queue = field(default_factory=queue.Queue)
    readers: list = field(default_factory=list)
    loaded: bool = False
    busy: bool = True
    stopping: bool = False
    error: str = ''
    dead: threading.Event = field(default_factory=threading.Event)
    tree: object = None
    active_request: str | None = None
    cooperative_cancel: bool = False
    cancel_sent: str | None = None
    cancel_event: object | None = None

    @property
    def directory(self):
        return Path(self.temporary.name)


class LiquidAITTSService:
    """Construction is inert; model libraries live only in the private interpreter."""
    _REQUEST_TIMEOUT = 600.0
    _START_TIMEOUT = 30.0
    _STOP_TIMEOUT = 2.0
    _CANCEL_TIMEOUT = 2.0

    def __init__(self, context):
        self._context = context
        self._paths = managed_paths(context.paths.app_root)
        self._state_lock = threading.RLock()
        self._request_lock = _RequestLock()
        self._close_lock = threading.Lock()
        self._worker = None
        self._epoch = 0
        self._closing = False
        self._setup = False
        self._admitted = 0
        self.sr = 24000

    def _settings(self, overrides=None):
        runtime = self._context.capabilities.runtime_config
        snapshot = getattr(runtime, 'snapshot', None)
        values = snapshot() if callable(snapshot) else None
        getter = values.get if isinstance(values, dict) else runtime.get
        values = {key: getter(key, default) for key, default in DEFAULTS.items()}
        # Captured speech-turn generation settings are authoritative. Paths are
        # installation controls and always come from the active runtime config.
        for key, value in (overrides or {}).items():
            if key in DEFAULTS and key not in ('liquidai_tts_python', 'liquidai_tts_model_dir'):
                values[key] = value
        return normalize_settings(values), str(runtime.tts_device())

    def _environment(self):
        environment = os.environ.copy()
        # Never inherit the host interpreter's package/venv overrides.
        for key in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV'):
            environment.pop(key, None)
        environment.update({
            'PYTHONNOUSERSITE': '1', 'PYTHONUTF8': '1',
            'HF_HOME': str(self._paths.cache / 'huggingface'),
            'HF_HUB_CACHE': str(self._paths.cache / 'huggingface' / 'hub'),
            'HF_MODULES_CACHE': str(self._paths.cache / 'modules'),
            'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
            'HF_HUB_DISABLE_TELEMETRY': '1', 'TOKENIZERS_PARALLELISM': 'false',
            'TORCH_HOME': str(self._paths.cache / 'torch'),
            'TORCH_EXTENSIONS_DIR': str(self._paths.cache / 'torch_extensions'),
            'NC_LIQUIDAI_PARENT_PID': str(os.getpid()),
        })
        return environment

    def _check_epoch(self, epoch):
        if self._closing or epoch != self._epoch:
            raise InterruptedError('LiquidAI request cancelled during shutdown.')

    def _start(self, epoch, fingerprint, on_worker=None):
        python, model_dir, device = fingerprint
        with self._state_lock:
            self._check_epoch(epoch)
            if self._worker is not None:
                if on_worker is not None:
                    on_worker(self._worker)
                return self._worker
            self._paths.work.mkdir(parents=True, exist_ok=True)
            temporary = tempfile.TemporaryDirectory(prefix='worker-', dir=self._paths.work)
            try:
                process = subprocess.Popen(
                    [python, '-B', '-u', str(Path(__file__).with_name('worker.py')), temporary.name],
                    cwd=self._paths.root, env=self._environment(),
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding='utf-8', errors='replace', bufsize=1,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except BaseException:
                temporary.cleanup()
                raise
            worker = _Worker(process, temporary, fingerprint, device)
            self._worker = worker
            if on_worker is not None:
                on_worker(worker)
            if os.name == 'nt':
                from .windows_worker import WindowsWorkerTree
                worker.tree = WindowsWorkerTree(process.pid)

        def receive():
            try:
                for line in process.stdout:
                    message = json.loads(line)
                    if not isinstance(message, dict):
                        raise ValueError('Invalid worker packet')
                    worker.messages.put(message)
            except (OSError, ValueError, TypeError):
                pass
            finally:
                worker.dead.set()
                worker.messages.put(None)

        def logs():
            try:
                for line in process.stderr:
                    if line.strip():
                        logging.getLogger(__name__).info('LiquidAI worker: %s', line.rstrip())
            except (OSError, ValueError):
                pass

        with self._state_lock:
            self._check_epoch(epoch)
            for target in (receive, logs):
                thread = threading.Thread(target=target, name='nc-liquidai-pipe', daemon=True)
                worker.readers.append(thread)
                thread.start()
        ready = self._read(worker, epoch, self._START_TIMEOUT)
        if ready.get('kind') != 'ready' or not isinstance(ready.get('pid'), int):
            raise _ProtocolError('LiquidAI worker did not become ready.')
        with self._state_lock:
            self._check_epoch(epoch)
            if worker.tree is not None:
                # A Windows venv launcher PID can differ from the actual Python.
                worker.tree.capture()
                if ready['pid'] not in worker.tree.handles:
                    raise _ProtocolError('LiquidAI worker PID is not an owned process.')
            worker.cooperative_cancel = ready.get('cooperative_cancel') is True
            if os.name == 'nt' and ready.get('cancel_transport') == 'windows_event':
                from .native_cancel import NamedCancellation
                worker.cancel_event = NamedCancellation.create()
        return worker

    def _read(self, worker, epoch, timeout, request_id=None):
        deadline = time.monotonic() + timeout
        while True:
            try:
                message = worker.messages.get(timeout=max(0., deadline-time.monotonic()))
            except queue.Empty as error:
                raise TimeoutError('LiquidAI worker response timed out.') from error
            with self._state_lock:
                self._check_epoch(epoch)
                if worker.stopping:
                    raise InterruptedError('LiquidAI worker was stopped.')
            if isinstance(message, _CancellationWake):
                if message.request_id == request_id:
                    raise InterruptedError('LiquidAI speech request cancelled.')
                continue  # A late local wake cannot cancel a subsequent request.
            if message is None:
                raise _ProtocolError('LiquidAI worker exited before responding.')
            if request_id is not None and message.get('id') != request_id:
                raise _ProtocolError('LiquidAI worker response does not match its request.')
            return message

    def _signal_request_cancel(self, worker, request_id):
        with self._state_lock:
            if (self._worker is not worker or worker.active_request != request_id
                    or not worker.cooperative_cancel or worker.stopping or worker.error):
                return False
            if worker.cancel_sent != request_id:
                worker.cancel_sent = request_id
                try:
                    if worker.cancel_event is not None:
                        worker.cancel_event.set()
                    else:
                        worker.process.stdin.write(json.dumps({'action':'cancel', 'id':request_id}) + '\n')
                        worker.process.stdin.flush()
                except (OSError, ValueError):
                    return False
                worker.messages.put(_CancellationWake(request_id))
            return True

    def _drain_cancelled_request(self, worker, epoch, request_id):
        # Keep the request lock until the exact inference owner has unwound.
        # No normal speech, PCM or retries escape this cancelled request.
        deadline = time.monotonic() + self._CANCEL_TIMEOUT
        while True:
            with self._state_lock:
                self._check_epoch(epoch)
            try:
                message = worker.messages.get(timeout=max(0., deadline-time.monotonic()))
            except queue.Empty as error:
                raise TimeoutError('LiquidAI cancellation acknowledgement timed out.') from error
            if isinstance(message, _CancellationWake):
                continue
            if not isinstance(message, dict) or message.get('id') != request_id:
                raise _ProtocolError('LiquidAI cancellation response does not match its request.')
            if message.get('kind') == 'done' and type(message.get('ok')) is bool:
                return
            if message.get('kind') != 'pcm':
                raise _ProtocolError('LiquidAI cancellation returned an invalid packet.')

    def _dispose(self, worker):
        """Caller owns close_lock; retain failed cleanup as an unloadable resource."""
        with self._state_lock:
            worker.stopping = True
            worker.busy = False
            worker.messages.put(None)  # Wake the active request without polling.
        try:
            process = worker.process
            if worker.tree is not None:
                worker.tree.terminate()
            elif process.poll() is None:
                process.kill()
            process.wait(timeout=self._STOP_TIMEOUT)
            for thread in worker.readers:
                thread.join(self._STOP_TIMEOUT)
                if thread.is_alive():
                    raise RuntimeError('LiquidAI worker pipe did not stop.')
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
            if worker.cancel_event is not None:
                worker.cancel_event.close()
                worker.cancel_event = None
            worker.temporary.cleanup()
            if worker.tree is not None:
                worker.tree.close()
            with self._state_lock:
                if self._worker is worker:
                    self._worker = None
        except Exception as error:
            with self._state_lock:
                worker.error = 'LiquidAI worker cleanup is incomplete; Stop or unload again to retry.'
            raise RuntimeError(worker.error) from error

    def _call(self, action, text='', overrides=None):
        with self._state_lock:
            if self._setup:
                raise RuntimeError('LiquidAI setup is running; wait for installation to finish.')
            epoch = self._epoch
            self._check_epoch(epoch)
            self._admitted += 1
        try:
            return self._perform_call(action, text, overrides, epoch)
        finally:
            with self._state_lock:
                self._admitted -= 1

    def _perform_call(self, action, text, overrides, epoch):
        settings, device = self._settings(overrides)
        python = Path(settings['liquidai_tts_python'] or self._paths.python).expanduser().resolve()
        model_dir = Path(settings['liquidai_tts_model_dir'] or self._paths.model_dir).expanduser().resolve()
        if not python.is_file():
            raise RuntimeError('LiquidAI Python is missing; use Install / Repair or select its Python executable.')
        validate_model_folder(model_dir)
        fingerprint = (str(python), str(model_dir), device)
        configured_seed = settings['liquidai_tts_seed']
        seed = (overrides or {}).get('seed', configured_seed)
        seed = int(seed or 0)
        if not 0 <= seed <= 2**32 - 1:
            raise ValueError('LiquidAI seed must be between 0 and 4294967295.')
        seed = seed if seed else secrets.randbits(32)
        worker = None
        with self._request_lock:
            try:
                with self._state_lock:
                    self._check_epoch(epoch)
                    old = self._worker
                    if old is not None and old.error:
                        raise RuntimeError(old.error)
                    replace = old is not None and (old.stopping or old.dead.is_set() or old.process.poll() is not None
                                                   or old.fingerprint != fingerprint)
                if replace:
                    with self._close_lock:
                        with self._state_lock:
                            self._check_epoch(epoch)
                            if self._worker is old and old.error:
                                raise RuntimeError(old.error)
                            still_owned = self._worker is old
                        if still_owned:
                            self._dispose(old)
                worker = self._start(epoch, fingerprint)
                request_id = uuid.uuid4().hex
                request = {'id':request_id, 'action':action, 'text':text,
                    'model_dir':str(model_dir), 'models_dir':str(self._paths.root/'models'),
                    'device':device, 'settings':settings, 'seed':seed}
                with self._state_lock:
                    self._check_epoch(epoch)
                    worker.busy = True
                    worker.process.stdin.write(json.dumps(request, allow_nan=False) + '\n')
                    worker.process.stdin.flush()
                response = self._read(worker, epoch, self._REQUEST_TIMEOUT, request_id)
                if not response.get('ok'):
                    raise RuntimeError(str(response.get('error') or 'LiquidAI speech synthesis failed.'))
                with self._state_lock:
                    self._check_epoch(epoch)
                    worker.loaded = True
                    if action != 'generate':
                        return bool(response.get('result'))
                    path = worker.directory / (request_id + '.wav')
                    try:
                        with wave.open(str(path), 'rb') as audio:
                            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 24000):
                                raise _ProtocolError('LiquidAI worker returned invalid audio format.')
                            frames = audio.getnframes()
                            data = audio.readframes(frames)
                        if not frames or len(data) != frames * 2:
                            raise _ProtocolError('LiquidAI worker returned empty or incomplete audio.')
                        import numpy as np
                        waveform = np.frombuffer(data, dtype='<i2').astype('float32').reshape(1, -1) / 32768.
                        return {'wav':waveform, 'sample_rate':24000}
                    except (wave.Error, EOFError) as error:
                        raise _ProtocolError('LiquidAI worker returned malformed audio.') from error
                    finally:
                        path.unlink(missing_ok=True)
            except (_ProtocolError, TimeoutError, OSError):
                with self._close_lock:
                    with self._state_lock:
                        failed = self._worker if epoch == self._epoch else None
                    if failed is not None:
                        self._dispose(failed)
                raise
            finally:
                with self._state_lock:
                    if worker is not None:
                        worker.busy = False

    def generate(self, text, audio_prompt_path=None, **kwargs):
        text = str(text or '').strip()
        if not text or len(text) > 12000:
            raise ValueError('LiquidAI speech requires 1 to 12,000 characters.')
        # Voice adapters are selected through provider settings, not reference audio.
        return self._call('generate', text=text, overrides=kwargs)

    def supports_incremental_audio(self, overrides=None) -> bool:
        settings, _ = self._settings(overrides)
        return settings['liquidai_tts_stream_audio']

    def incremental_audio_options(self, overrides=None) -> dict[str, float]:
        settings, _ = self._settings(overrides)
        return {'startup_buffer_seconds':settings['liquidai_tts_startup_buffer_seconds']}

    def _dispose_exact_request(self, worker, request_id):
        if worker is None:
            return
        with self._close_lock:
            with self._state_lock:
                owned = self._worker is worker and worker.active_request == request_id
            if owned:
                self._dispose(worker)

    def generate_stream(self, text, audio_prompt_path=None, *, stop_event=None, **kwargs) -> Iterator[PCMBlock]:
        """Yield opt-in native PCM; cancellation retires only this worker request."""
        from core.incremental_audio import PCMBlock
        text = str(text or '').strip()
        if not text or len(text) > 12000:
            raise ValueError('LiquidAI speech requires 1 to 12,000 characters.')
        with self._state_lock:
            if self._setup:
                raise RuntimeError('LiquidAI setup is running; wait for installation to finish.')
            epoch = self._epoch
            self._check_epoch(epoch)
            self._admitted += 1
        cancelled = threading.Event()
        captured = [None]
        request_id = uuid.uuid4().hex
        unsubscribe = None
        acquired = False
        completed = False
        protocol_failed = False
        sent = False
        worker = None
        def stopped():
            is_set = getattr(stop_event, 'is_set', None)
            return (cancelled.is_set() or bool(getattr(stop_event, 'cancelled', False))
                    or callable(is_set) and is_set())
        def cancel():
            cancelled.set()
            self._request_lock.wake()
            if completed:
                return
            with self._state_lock:
                target = captured[0]
                owned = self._worker is target and target is not None and target.active_request == request_id
                cooperative = owned and target.cooperative_cancel
                if cooperative and not sent:
                    return  # Cancelled after ready, before a request was sent.
            if cooperative and self._signal_request_cancel(target, request_id):
                return
            with self._state_lock:
                if self._worker is target and target is not None and target.active_request == request_id:
                    target.stopping = True
                    target.messages.put(None)
            self._dispose_exact_request(target, request_id)
        def capture(target):
            captured[0] = target
            target.active_request = request_id
            target.cancel_sent = None
            target.busy = True
            if stopped() and not target.cooperative_cancel:
                # Let startup capture the Windows launcher/child tree before
                # unwinding; killing only the launcher can orphan its Python.
                target.stopping = True
                target.messages.put(None)
        try:
            settings, device = self._settings(kwargs)
            if not settings['liquidai_tts_stream_audio']:
                raise RuntimeError('LiquidAI experimental progressive audio is disabled; opt in before streaming.')
            python = Path(settings['liquidai_tts_python'] or self._paths.python).expanduser().resolve()
            model_dir = Path(settings['liquidai_tts_model_dir'] or self._paths.model_dir).expanduser().resolve()
            if not python.is_file():
                raise RuntimeError('LiquidAI Python is missing; use Install / Repair or select its Python executable.')
            validate_model_folder(model_dir)
            fingerprint = (str(python), str(model_dir), device)
            seed = int(kwargs.get('seed', settings['liquidai_tts_seed']) or 0)
            if not 0 <= seed <= 2**32 - 1:
                raise ValueError('LiquidAI seed must be between 0 and 4294967295.')
            seed = seed if seed else secrets.randbits(32)
            subscribe = getattr(stop_event, 'subscribe', None)
            if callable(subscribe):
                unsubscribe = subscribe(cancel)
            if stopped():
                raise InterruptedError('LiquidAI speech request cancelled.')
            self._request_lock.acquire(cancelled=stopped)
            acquired = True
            with self._state_lock:
                self._check_epoch(epoch)
                old = self._worker
                if old is not None and old.error:
                    raise RuntimeError(old.error)
                replace = old is not None and (old.stopping or old.dead.is_set() or old.process.poll() is not None
                                               or old.fingerprint != fingerprint)
            if replace:
                with self._close_lock:
                    with self._state_lock:
                        self._check_epoch(epoch)
                        if self._worker is old and old.error:
                            raise RuntimeError(old.error)
                        still_owned = self._worker is old
                    if still_owned:
                        self._dispose(old)
            worker = self._start(epoch, fingerprint, on_worker=capture)
            request = {'id':request_id, 'action':'generate_stream', 'text':text,
                       'model_dir':str(model_dir), 'models_dir':str(self._paths.root/'models'),
                       'device':device, 'settings':settings, 'seed':seed}
            with self._state_lock:
                self._check_epoch(epoch)
                if stopped() or worker.stopping:
                    raise InterruptedError('LiquidAI speech request cancelled.')
                if worker.cancel_event is not None:
                    worker.cancel_event.reset()
                    request['cancel_event'] = worker.cancel_event.name
                worker.process.stdin.write(json.dumps(request, allow_nan=False) + '\n')
                worker.process.stdin.flush()
                sent = True
            sequence = 0
            while True:
                if stopped():
                    raise InterruptedError('LiquidAI speech request cancelled.')
                response = self._read(worker, epoch, self._REQUEST_TIMEOUT, request_id)
                kind = response.get('kind')
                if kind == 'done':
                    if type(response.get('ok')) is not bool:
                        raise _ProtocolError('LiquidAI stream returned an invalid terminal packet.')
                    completed = True  # Terminal failures are healthy protocol replies, never retried.
                    with self._state_lock:
                        worker.loaded = True
                    if stopped() or worker.stopping:
                        raise InterruptedError('LiquidAI speech request cancelled.')
                    if not response['ok']:
                        raise RuntimeError(str(response.get('error') or 'LiquidAI speech synthesis failed.'))
                    if not sequence:
                        completed = False
                        raise _ProtocolError('LiquidAI stream returned no speech audio.')
                    return
                if stopped() or worker.stopping:
                    raise InterruptedError('LiquidAI speech request cancelled.')
                if (kind != 'pcm' or type(response.get('sequence')) is not int
                        or response['sequence'] != sequence
                        or type(response.get('sample_rate')) is not int or response['sample_rate'] != 24000
                        or type(response.get('channels')) is not int or response['channels'] != 1
                        or not isinstance(response.get('data'), str)):
                    raise _ProtocolError('LiquidAI stream returned invalid PCM format or sequence.')
                try:
                    data = base64.b64decode(response['data'], validate=True)
                except (ValueError, binascii.Error) as error:
                    raise _ProtocolError('LiquidAI stream returned invalid base64 PCM.') from error
                if not data or len(data) % 2:
                    raise _ProtocolError('LiquidAI stream returned empty or incomplete PCM.')
                with self._state_lock:
                    worker.loaded = True
                yield PCMBlock(data=data, sample_rate=24000, channels=1, sequence=sequence)
                sequence += 1
        except InterruptedError:
            raise
        except (_ProtocolError, TimeoutError, OSError):
            protocol_failed = True
            raise
        finally:
            try:
                if acquired and not completed:
                    target = captured[0]
                    if protocol_failed:
                        self._dispose_exact_request(target, request_id)
                    elif target is not None and sent and self._signal_request_cancel(target, request_id):
                        try:
                            self._drain_cancelled_request(target, epoch, request_id)
                        except Exception:
                            self._dispose_exact_request(target, request_id)
                    elif target is not None and (sent or not target.cooperative_cancel):
                        self._dispose_exact_request(target, request_id)
            finally:
                with self._state_lock:
                    target = captured[0]
                    if target is not None and target.active_request == request_id:
                        target.active_request = None
                        target.busy = False
                    self._admitted -= 1
                if callable(unsubscribe):
                    unsubscribe()
                if acquired:
                    self._request_lock.release()

    def warm_up(self):
        with self._state_lock:
            if self._setup:
                raise RuntimeError('LiquidAI setup is running; wait for installation to finish.')
        settings, _ = self._settings()
        if not settings['liquidai_tts_prewarm_on_start']:
            return False
        # Match the active Persona without changing the provider defaults.
        from core.persona_overrides import read_persona_overrides
        persona = read_persona_overrides(self._paths.root, active=True)
        overrides = {key: persona[key] for key in
                     ('liquidai_tts_voice', 'liquidai_tts_language') if key in persona}
        return self._call('warm_up', overrides=overrides)

    def begin_setup(self):
        """Reserve model/environment changes only while all speech jobs are idle."""
        with self._close_lock:
            with self._state_lock:
                if self._setup:
                    raise RuntimeError('LiquidAI setup is already running.')
                if self._admitted or self._closing or self._worker is not None and self._worker.busy:
                    raise RuntimeError('LiquidAI speech is active or queued; stop speech before setup.')
                self._setup = True
                self._epoch += 1
                worker = self._worker
            try:
                if worker is not None:
                    self._dispose(worker)
                return True
            except BaseException:
                with self._state_lock:
                    self._setup = False
                raise

    def end_setup(self):
        with self._state_lock:
            self._setup = False

    def resources_snapshot(self):
        with self._state_lock:
            worker = self._worker
            if worker is None:
                return []
            alive = not worker.tree.exited() if worker.tree is not None else worker.process.poll() is None
            if not alive and not worker.error:
                return []
            busy = worker.busy or bool(self._admitted)
            return [{'id':worker.instance_id, 'name':'LiquidAI', 'model':'LFM3-Audio-2B',
                'owner':'NC · text-to-speech', 'device':worker.device,
                'processId':worker.process.pid, 'processIncludeChildren':True,
                'processLabel':'LiquidAI TTS worker', 'error':worker.error,
                'canUnload':not busy and not self._closing,
                'status':'cleanup_failed' if worker.error else
                         'loading' if busy and not worker.loaded else 'in_use' if busy else 'idle'}]

    def unload_resource(self, instance_id):
        with self._close_lock:
            with self._state_lock:
                worker = self._worker
                if worker is None or worker.instance_id != str(instance_id) or worker.busy or self._admitted or self._closing:
                    return False
                self._epoch += 1
                self._closing = True
            try:
                self._dispose(worker)
                return True
            finally:
                with self._state_lock:
                    self._closing = False

    def close_strict(self):
        with self._close_lock:
            with self._state_lock:
                self._epoch += 1
                self._closing = True
                worker = self._worker
            try:
                if worker is not None:
                    self._dispose(worker)
            finally:
                with self._state_lock:
                    self._closing = False

    def close(self):
        self.close_strict()
