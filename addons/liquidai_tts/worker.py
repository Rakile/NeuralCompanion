"""Private LiquidAI model process. JSON-only stdout; no NC imports/dependencies."""
from __future__ import annotations

import base64
import contextlib
import json
import os
import queue
from pathlib import Path
import secrets
import sys
import threading
import time
import traceback
import warnings

# Script execution deliberately avoids importing NC's addon/package graph.
if __package__:
    from .config import REVISION, normalize_settings, validate_model_folder, voice_prompt
    from .voices import resolve_voice_adapter
    from .streaming_codec import StreamingAudioCodec
else:
    from config import REVISION, normalize_settings, validate_model_folder, voice_prompt
    from voices import resolve_voice_adapter
    from streaming_codec import StreamingAudioCodec


class _RequestCancelled(InterruptedError):
    """An ordinary utterance interruption; the loaded model remains reusable."""


def _check_cancel(event):
    if event is not None and event.is_set():
        raise _RequestCancelled('LiquidAI speech request cancelled.')


class _CancellationStreamer:
    # The pinned model rejects stopping_criteria, but invokes these callbacks
    # at audio-frame and text/control-token boundaries. Cache state is local
    # to that generate() call and unwinds with the cancelled request.
    def __init__(self, event, delegate=None):
        self.event, self.delegate = event, delegate

    def put(self, value):
        _check_cancel(self.event)
        if self.delegate is not None:
            self.delegate.put(value)

    def end(self):
        _check_cancel(self.event)
        if self.delegate is not None:
            self.delegate.end()


class Engine:
    def __init__(self):
        self.model = self.processor = self.codec = None
        self.device = None
        self.model_dir = None
        self._adapter_fingerprint = None

    def load(self, model_dir, device='cpu'):
        if self.model is not None:
            if self.device != device or self.model_dir is not None and self.model_dir != str(Path(model_dir).resolve()):
                raise ValueError('Unload the LiquidAI worker before changing device or model.')
            return {'device':self.device, 'already_loaded':True}
        model_dir = validate_model_folder(model_dir)
        import torch
        from transformers import AutoModelForMultimodalLM, AutoProcessor
        if device != 'cpu' and device != 'cuda' and not (device.startswith('cuda:') and device[5:].isdigit()):
            raise ValueError('LiquidAI supports CPU or CUDA devices (including cuda:N).')
        cuda = device.startswith('cuda')
        if cuda:
            index = int(device.split(':')[1]) if ':' in device else 0
            if not torch.cuda.is_available() or index >= torch.cuda.device_count():
                raise RuntimeError('Selected LiquidAI CUDA device is unavailable; check the private environment and NVIDIA driver.')
        started = time.perf_counter()
        model = AutoModelForMultimodalLM.from_pretrained(
            model_dir, dtype=torch.bfloat16 if cuda else torch.float32,
            device_map=device, trust_remote_code=True, local_files_only=True).eval()
        processor = AutoProcessor.from_pretrained(model_dir, trust_remote_code=True,
            local_files_only=True, fix_mistral_regex=False)
        codec = processor.audio_tokenizer.to(device=device).eval()
        self.model, self.processor, self.codec = model, processor, codec
        self.device, self.model_dir = device, str(model_dir)
        if cuda:
            torch.cuda.synchronize(device)
        return {'device':device, 'revision':REVISION, 'load_seconds':round(time.perf_counter()-started, 3)}

    @contextlib.contextmanager
    def _voice(self, adapter):
        # Inference is serial; the request owns adapter state until generation
        # completes or cancellation/error unwinds the context.
        if adapter is not None:
            if adapter['fingerprint'] != self._adapter_fingerprint:
                folder = adapter['path']
                try:
                    from peft import PeftModel
                except ImportError as error:
                    raise RuntimeError(f"{adapter['name']} needs PEFT in the LiquidAI environment. Use Install / Repair, or repair the Python override. ({error})") from error
                try:
                    if self._adapter_fingerprint is not None:
                        self.model = self.model.unload().eval()
                        self._adapter_fingerprint = None
                    with warnings.catch_warnings():
                        warnings.filterwarnings('error', message=r'Found missing adapter keys while loading the checkpoint:', category=UserWarning)
                        self.model = PeftModel.from_pretrained(self.model, str(folder), local_files_only=True).eval()
                except Exception as error:
                    # Failed PEFT loading can leave injected layers behind.
                    # A later request must reload a clean base model.
                    self.model = self.processor = self.codec = None
                    self.device = self.model_dir = None
                    self._adapter_fingerprint = None
                    if isinstance(error, UserWarning):
                        raise ValueError(f"{adapter['name']} voice adapter is incomplete or incompatible: {folder}.") from error
                    raise
                self._adapter_fingerprint = adapter['fingerprint']
            yield
        elif self._adapter_fingerprint is not None:
            with self.model.disable_adapter():
                yield
        else:
            yield

    def run(self, request, directory):
        import torch
        import soundfile as sf
        import numpy as np
        settings = normalize_settings(request.get('settings'))
        adapter = resolve_voice_adapter(settings['liquidai_tts_voice'],
            request.get('models_dir') or Path(request['model_dir']).parent, request['model_dir'])
        text = str(request.get('text') or '').strip()
        if not text or len(text) > 12000:
            raise ValueError('LiquidAI speech requires 1 to 12,000 characters.')
        # There is deliberately no native audio-to-audio, voice reference,
        # browser sentence splitter, or browser playback buffer in NC's worker.
        messages = [
            {'role':'system', 'content':voice_prompt(settings, adapter)},
            {'role':'user', 'content':text},
            {'role':'assistant', 'content':'<|audio_start|>'},
        ]
        budget = settings['liquidai_tts_max_tokens']
        seed = request.get('seed')
        seed = int(seed) if seed is not None else secrets.randbits(32)
        if not 0 <= seed <= 2**32 - 1:
            raise ValueError('LiquidAI seed must be between 0 and 4294967295.')
        self.load(request['model_dir'], str(request.get('device', 'cpu')))
        started = time.perf_counter()
        inputs = self.processor.apply_chat_template(messages, tokenize=True, return_dict=True,
            return_tensors='pt', continue_final_message=True).to(self.device)
        prompt_slots = int(inputs['input_ids'].shape[1])
        if prompt_slots + budget > self.model.config.text_config.max_position_embeddings:
            raise ValueError('LiquidAI speech chunk exceeds the model context limit; reduce the speech chunk size.')
        cuda = self.device.startswith('cuda')
        if cuda:
            torch.cuda.synchronize(self.device)
        prepared = time.perf_counter()
        with self._voice(adapter), torch.inference_mode():
            torch.manual_seed(seed)
            result = self.model.generate(**inputs, max_new_tokens=budget,
                return_dict_in_generate=True,
                audio_temperature=settings['liquidai_tts_temperature'],
                audio_top_k=settings['liquidai_tts_top_k'],
                audio_repetition_penalty=settings['liquidai_tts_repetition_penalty'],
                audio_repetition_window=4096)
            if cuda:
                torch.cuda.synchronize(self.device)
            generated = time.perf_counter()
            slots = int(result.sequences.shape[1]) - prompt_slots
            # Never expose a truncated speech chunk as successful completed TTS.
            if slots >= budget:
                raise RuntimeError('LiquidAI generation budget exhausted; increase Max tokens or reduce the speech chunk size.')
            lengths = getattr(result, 'audio_lengths', None)
            frames = int(lengths[0]) if lengths is not None else 0
            if frames <= 0:
                raise RuntimeError('LiquidAI generated no speech audio for this chunk.')
            decoded = self.codec.decode(result.audio_codes[:1, :, :frames]).audio_values[0]
            samples = decoded.float().cpu().numpy()
            if samples.ndim > 1 and any(size != 1 for size in samples.shape[:-1]):
                raise RuntimeError('LiquidAI codec returned audio with unexpected channels.')
            samples = samples.reshape(-1)
            if not samples.size or not np.isfinite(samples).all():
                raise RuntimeError('LiquidAI codec returned empty or invalid speech audio.')
            request_id = str(request['id'])
            if not request_id or not all(char.isalnum() or char in '-_' for char in request_id):
                raise ValueError('Invalid LiquidAI request identifier.')
            output = Path(directory) / (request_id + '.wav')
            sf.write(str(output), samples, 24000, subtype='PCM_16')
        return {'audio_path':str(output), 'sample_rate':24000, 'metrics':{
            'seed':seed, 'device':self.device, 'revision':REVISION,
            'generated_slots':slots, 'generation_budget':budget,
            'prepare_seconds':round(prepared-started, 3),
            'generation_seconds':round(generated-prepared, 3),
            'total_seconds':round(time.perf_counter()-started, 3),
            'audio_seconds':round(len(samples)/24000, 3)}}


    def run_stream(self, request, emit):
        """Publish ordered s16le pieces; completion is sent by the protocol owner."""
        cancel_event = request.get('_cancel_event')
        _check_cancel(cancel_event)
        import torch
        settings = normalize_settings(request.get('settings'))
        adapter = resolve_voice_adapter(settings['liquidai_tts_voice'],
            request.get('models_dir') or Path(request['model_dir']).parent, request['model_dir'])
        text = str(request.get('text') or '').strip()
        if not text or len(text) > 12000:
            raise ValueError('LiquidAI speech requires 1 to 12,000 characters.')
        request_id = str(request['id'])
        if not request_id or not all(char.isalnum() or char in '-_' for char in request_id):
            raise ValueError('Invalid LiquidAI request identifier.')
        seed = request.get('seed')
        seed = int(seed) if seed is not None else secrets.randbits(32)
        if not 0 <= seed <= 2**32 - 1:
            raise ValueError('LiquidAI seed must be between 0 and 4294967295.')
        self.load(request['model_dir'], str(request.get('device', 'cpu')))
        _check_cancel(cancel_event)
        started = time.perf_counter()
        messages = [
            {'role':'system', 'content':voice_prompt(settings, adapter)},
            {'role':'user', 'content':text},
            {'role':'assistant', 'content':'<|audio_start|>'},
        ]
        inputs = self.processor.apply_chat_template(messages, tokenize=True, return_dict=True,
            return_tensors='pt', continue_final_message=True).to(self.device)
        prompt_slots = int(inputs['input_ids'].shape[1])
        budget = settings['liquidai_tts_max_tokens']
        if prompt_slots + budget > self.model.config.text_config.max_position_embeddings:
            raise ValueError('LiquidAI speech chunk exceeds the model context limit; reduce the speech chunk size.')
        sequence = 0
        def send(pcm):
            nonlocal sequence
            emit({'id':request_id, 'kind':'pcm', 'sequence':sequence,
                  'sample_rate':24000, 'channels':1,
                  'data':base64.b64encode(pcm).decode('ascii')})
            sequence += 1
        streamer = StreamingAudioCodec(self.codec, send)
        cancellation_options = ({'streamer': _CancellationStreamer(cancel_event)}
                                if cancel_event is not None else {})
        audio_streamer = (_CancellationStreamer(cancel_event, streamer)
                          if cancel_event is not None else streamer)
        with self._voice(adapter), torch.inference_mode():
            torch.manual_seed(seed)
            result = self.model.generate(**inputs, max_new_tokens=budget,
                return_dict_in_generate=True, audio_streamer=audio_streamer,
                **cancellation_options,
                audio_temperature=settings['liquidai_tts_temperature'],
                audio_top_k=settings['liquidai_tts_top_k'],
                audio_repetition_penalty=settings['liquidai_tts_repetition_penalty'],
                audio_repetition_window=4096)
            _check_cancel(cancel_event)
            streamer.end()
        slots = int(result.sequences.shape[1]) - prompt_slots
        # Emitted pieces cannot be rolled back: report terminal failure, never retry.
        if slots >= budget:
            raise RuntimeError('LiquidAI generation budget exhausted; increase Max tokens or reduce the speech chunk size.')
        if not streamer.samples:
            raise RuntimeError('LiquidAI generated no speech audio for this chunk.')
        return {'sample_rate':24000, 'metrics':{
            'seed':seed, 'device':self.device, 'revision':REVISION,
            'generated_slots':slots, 'generation_budget':budget,
            'total_seconds':round(time.perf_counter()-started, 3),
            'audio_seconds':round(streamer.samples/24000, 3)}}

    def warm_up(self, request, directory):
        """Exercise real generation/codec paths, discard output, keep owned model hot."""
        settings = normalize_settings(request.get('settings'))
        if not settings['liquidai_tts_prewarm_on_start']:
            return False
        warm = dict(request, text='Hello.')
        result = self.run(warm, directory)
        Path(result['audio_path']).unlink(missing_ok=True)
        if settings['liquidai_tts_stream_audio']:
            self.run_stream(warm, lambda _packet: None)
        return True


def watch_parent():
    """Wait on a process handle, never on stdin or a native-library CRT lock."""
    parent_pid = os.environ.get('NC_LIQUIDAI_PARENT_PID')
    if os.name != 'nt' or not parent_pid:
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateProcess.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    handle = kernel.OpenProcess(0x00100000, False, int(parent_pid))
    if not handle:
        os._exit(0)
    def wait():
        kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
        kernel.TerminateProcess(kernel.GetCurrentProcess(), 0)
    threading.Thread(target=wait, name='nc-liquidai-parent', daemon=True).start()


def _execute_request(engine, directory, request, cancelled, emit):
    identifier = request.get('id')
    internal = dict(request, _cancel_event=cancelled)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            _check_cancel(cancelled)
            if request.get('action') == 'generate':
                result = engine.run(internal, directory)
            elif request.get('action') == 'generate_stream':
                result = engine.run_stream(internal, emit)
            elif request.get('action') == 'warm_up':
                result = engine.warm_up(internal, directory)
            else:
                raise ValueError('Unknown LiquidAI worker action.')
            _check_cancel(cancelled)
        response = {'id':identifier, 'ok':True, 'result':result}
    except _RequestCancelled:
        response = {'id':identifier, 'ok':False, 'cancelled':True,
                    'error':'LiquidAI speech request cancelled.'}
    except Exception as error:
        traceback.print_exc(file=sys.stderr)
        response = {'id':identifier, 'ok':False, 'error':str(error)}
    if request.get('action') == 'generate_stream':
        response['kind'] = 'done'
    return response


def serve_windows(engine, directory, input_stream, emit):
    if __package__:
        from .native_cancel import NamedCancellation
    else:
        from native_cancel import NamedCancellation
    emit({'kind':'ready', 'pid':os.getpid(), 'cooperative_cancel':True,
          'cancel_transport':'windows_event'})
    for line in input_stream:
        request = {};owned_event = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError('LiquidAI request must be an object.')
            if request.get('action') == 'cancel':
                continue  # Legacy hosts dispose the worker; modern hosts signal its event.
            event_name = request.get('cancel_event')
            if event_name:
                owned_event = NamedCancellation.open(event_name)
            event = owned_event if owned_event is not None else threading.Event()
            emit(_execute_request(engine, directory, request, event, emit))
        except Exception as error:
            traceback.print_exc(file=sys.stderr)
            response = {'id':request.get('id') if isinstance(request, dict) else None,
                        'ok':False, 'error':str(error)}
            if isinstance(request, dict) and request.get('action') == 'generate_stream':
                response['kind'] = 'done'
            emit(response)
        finally:
            if owned_event is not None:
                owned_event.close()


def serve(engine, directory, input_stream, output):
    """A joined control reader signals serial inference on the main thread."""
    jobs = queue.Queue()
    active = {}
    active_lock = threading.Lock()
    output_lock = threading.Lock()

    def emit(packet):
        with output_lock:
            output(packet)

    def infer():
        while True:
            job = jobs.get()
            if job is None:
                return
            request, cancelled = job
            identifier = request.get('id')
            try:
                response = _execute_request(engine, directory, request, cancelled, emit)
            finally:
                with active_lock:
                    if active.get(identifier) is cancelled:
                        active.pop(identifier, None)
            emit(response)

    emit({'kind':'ready', 'pid':os.getpid(), 'cooperative_cancel':True})
    def read_controls():
        try:
            for line in input_stream:
                request = {}
                try:
                    request = json.loads(line)
                    if not isinstance(request, dict):
                        raise ValueError('LiquidAI request must be an object.')
                    identifier = request.get('id')
                    if request.get('action') == 'cancel':
                        with active_lock:
                            event = active.get(identifier) if isinstance(identifier, str) else None
                            if event is not None:
                                event.set()
                        continue  # Only the cancelled request emits its terminal packet.
                    event = threading.Event()
                    with active_lock:
                        if identifier in active:
                            raise ValueError('Duplicate LiquidAI request identifier.')
                        active[identifier] = event
                    jobs.put((request, event))
                except Exception as error:
                    traceback.print_exc(file=sys.stderr)
                    emit({'id':request.get('id') if isinstance(request, dict) else None,
                          'ok':False, 'error':str(error)})
        finally:
            jobs.put(None)

    # Non-Windows control reader: no daemon stdio thread survives shutdown.
    # The reader is non-daemon, consumes EOF, and is joined before interpreter
    # shutdown; no live stdio reader can race Python's stream finalization.
    reader = threading.Thread(target=read_controls, name='nc-liquidai-controls', daemon=False)
    reader.start()
    try:
        infer()
    finally:
        reader.join()



def main():
    directory = Path(sys.argv[1]).resolve()
    if not directory.is_dir():
        raise ValueError('LiquidAI worker output directory is missing.')
    watch_parent()
    protocol = sys.stdout
    def emit(packet):
        protocol.write(json.dumps(packet, ensure_ascii=True, allow_nan=False) + '\n')
        protocol.flush()
    serve_loop = serve_windows if os.name == 'nt' else serve
    serve_loop(Engine(), directory, sys.stdin, emit)


if __name__ == '__main__':
    main()
