"""Lazy same-environment Chatterbox Multilingual worker; audio/rendering contracts stay local."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import uuid


class _WorkerProtocolError(RuntimeError):
    pass


@dataclass
class _Worker:
    process: object
    temporary: object
    messages: queue.Queue = field(default_factory=queue.Queue)
    loaded: bool = False
    device: str = 'Unavailable'
    busy: bool = True
    error: str = ''
    readers: list = field(default_factory=list)
    dead: threading.Event = field(default_factory=threading.Event)
    tree: object = None

    @property
    def directory(self):
        return Path(self.temporary.name)


class ChatterboxMultilingualProcessService:
    """Serialize speech calls while allowing Stop to close an active request."""
    _STOP_TIMEOUT = 6.0
    _REQUEST_TIMEOUT = 600.0
    _SETTING_DEFAULTS = {
        'chatterbox_multilingual_language': 'en',
        'chatterbox_multilingual_seed': 0,
        'chatterbox_multilingual_temperature': 0.8,
        'chatterbox_multilingual_top_p': 1.0,
        'chatterbox_multilingual_exaggeration': 0.5,
        'chatterbox_multilingual_cfg_weight': 0.5,
        'chatterbox_multilingual_min_p': 0.05,
        'chatterbox_multilingual_repeat_penalty': 2.0,
        'chatterbox_multilingual_prewarm_on_start': True,
        'chatterbox_multilingual_use_cloned_voice': True,
        'chatterbox_multilingual_apply_watermark': False,
        'voice_path': '',
    }

    def __init__(self, context):
        self._context = context
        self._state_lock = threading.RLock()
        self._request_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._worker = None
        self._epoch = 0
        self._closing = False
        from core.tts_seed_context import seed_event_for
        self._seed_serial = seed_event_for('chatterbox_multilingual')[0]
        self.sr = 24000

    def _settings(self):
        runtime = self._context.capabilities.runtime_config if self._context else None
        snapshot = getattr(runtime, 'snapshot', None)
        values = snapshot() if callable(snapshot) else None
        getter = values.get if isinstance(values, dict) else runtime.get if runtime else lambda key, default=None: default
        values = {key: getter(key, default) for key, default in self._SETTING_DEFAULTS.items()}
        device = runtime.tts_device() if runtime else 'cpu'
        return values, str(device)

    @staticmethod
    def _boolean(value):
        return str(value).strip().lower() not in {'0', 'false', 'no', 'off', ''} if isinstance(value, str) else bool(value)

    def _diagnostic(self, event, fields):
        callback = getattr(getattr(self._context, 'capabilities', None), 'diagnostics', None)
        if callable(callback):
            try:
                callback(event, **fields)
            except Exception:
                pass

    def _start(self, epoch):
        with self._state_lock:
            if epoch != self._epoch or self._closing:
                raise InterruptedError('Chatterbox Multilingual request cancelled during shutdown.')
            if self._worker is not None:
                return self._worker
            temporary = tempfile.TemporaryDirectory(prefix='nc-chatterbox-multilingual-')
            _, requested_device = self._settings()
            environment = os.environ.copy()
            environment['PYTHONIOENCODING'] = 'utf-8'
            if requested_device.lower().startswith('cuda'):
                # Avoid CPU busy-waiting between GPU operations. Scope this to
                # the child before Torch/OpenMP load; do not change NC or Turbo.
                environment['KMP_BLOCKTIME'] = '0'
                environment['OMP_WAIT_POLICY'] = 'PASSIVE'
            try:
                process = subprocess.Popen(
                    [sys.executable, '-B', '-u', '-m', 'addons.chatterbox_multilingual_tts.worker', temporary.name],
                    cwd=Path(__file__).resolve().parents[2], stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    encoding='utf-8', errors='replace', bufsize=1,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), env=environment)
            except BaseException:
                temporary.cleanup()
                raise
            worker = _Worker(process, temporary)
            self._worker = worker
            if sys.platform == 'win32':
                from .windows_worker import WindowsWorkerTree
                worker.tree = WindowsWorkerTree(process.pid)

        def receive():
            try:
                for line in process.stdout:
                    message = json.loads(line)
                    kind = message.get('kind')
                    if kind == 'event':
                        self._diagnostic(message['event'], message.get('fields') or {})
                    elif kind == 'state':
                        with self._state_lock:
                            worker.loaded = bool(message.get('loaded'))
                            worker.device = str(message.get('device') or 'Unavailable')
                    else:
                        worker.messages.put(message)
            except (OSError, ValueError, TypeError, KeyError):
                pass
            finally:
                worker.dead.set()
                worker.messages.put(None)

        def logs():
            try:
                for line in process.stderr:
                    line = line.rstrip()
                    if line:
                        print('[Chatterbox Multilingual worker] ' + line)
            except (OSError, ValueError):
                pass
        for target in (receive, logs):
            thread = threading.Thread(target=target, name='nc-chatterbox-multilingual-pipe', daemon=True)
            worker.readers.append(thread)
            thread.start()
        ready = self._read(worker, deadline=time.monotonic() + 120)
        if ready.get('kind') != 'ready':
            raise _WorkerProtocolError('Chatterbox Multilingual worker did not become ready.')
        with self._state_lock:
            if epoch != self._epoch or self._closing:
                raise InterruptedError('Chatterbox Multilingual startup cancelled.')
            if worker.tree is not None:
                worker.tree.track(ready['pid'])
        return worker

    def _write(self, worker, message):
        with self._write_lock:
            worker.process.stdin.write(json.dumps(message, allow_nan=False) + '\n')
            worker.process.stdin.flush()

    def _read(self, worker, *, deadline, stop_event=None, request_id=None):
        cancelled_at = None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Chatterbox Multilingual worker response timed out.')
            if stop_event is not None and stop_event.is_set():
                if cancelled_at is None:
                    cancelled_at = time.monotonic()
                    self._write(worker, {'action': 'cancel', 'id': request_id})
                elif time.monotonic() - cancelled_at > self._STOP_TIMEOUT:
                    raise TimeoutError('Chatterbox Multilingual audition did not cancel.')
            try:
                # Ordinary calls block on pipe events. Only an active cancellable
                # audition needs the existing stop-event check interval.
                message = worker.messages.get(timeout=min(remaining, .05) if stop_event is not None else remaining)
            except queue.Empty:
                if stop_event is not None:
                    continue
                raise TimeoutError('Chatterbox Multilingual worker response timed out.')
            if message is None:
                raise _WorkerProtocolError('Chatterbox Multilingual worker stopped before responding.')
            if request_id is not None and message.get('id') != request_id:
                raise _WorkerProtocolError('Chatterbox Multilingual worker response does not match its request.')
            return message

    def _call(self, action, *, stop_event=None, **arguments):
        with self._state_lock:
            epoch = self._epoch
        if stop_event is None:
            self._request_lock.acquire()
        else:
            while not stop_event.is_set():
                if self._request_lock.acquire(timeout=.05):
                    break
            else:
                raise InterruptedError('Voice audition cancelled.')
        worker = None
        request_id = None
        try:
            with self._state_lock:
                if self._closing or epoch != self._epoch:
                    raise InterruptedError('Chatterbox Multilingual request cancelled during shutdown.')
                stale = self._worker is not None and (self._worker.dead.is_set() or self._worker.process.poll() is not None)
                if self._worker is not None and self._worker.error:
                    raise RuntimeError(self._worker.error)
                if action == 'generate_reference' and not self.audition_ready:
                    raise RuntimeError('Load Chatterbox Multilingual in NC before testing a voice.')
            if stale:
                self.close_strict()
                epoch += 1
            worker = self._start(epoch)
            settings, device = self._settings()
            request_id = uuid.uuid4().hex
            # Core seeds the caller before synthesis. Preserve its effective
            # fixed seed across the process boundary; random mode stays random.
            from core.tts_seed_context import seed_event_for
            import torch
            serial, explicit_seed = seed_event_for('chatterbox_multilingual')
            seed = explicit_seed if serial != self._seed_serial else None
            requested_seed = (arguments.get('kwargs') or {}).get('seed')
            if requested_seed is not None:
                # Explicit zero keeps the existing random sequence (or the
                # fresh core-seeded sequence), even if live settings are fixed.
                if int(requested_seed):
                    seed = int(requested_seed)
            elif seed is None and action in {'generate', 'generate_reference'}:
                configured = int(settings.get('chatterbox_multilingual_seed') or 0)
                seed = configured if configured > 0 else None
            with self._state_lock:
                if self._closing or epoch != self._epoch:
                    raise InterruptedError('Chatterbox Multilingual request cancelled during shutdown.')
                worker.busy = True
                self._write(worker, {'action': action, 'id': request_id,
                    'settings': settings, 'device': device, 'seed': seed,
                    'threads': [torch.get_num_threads(), torch.get_num_interop_threads()], **arguments})
                self._seed_serial = serial
            response = self._read(worker, deadline=time.monotonic() + self._REQUEST_TIMEOUT,
                                  stop_event=stop_event, request_id=request_id)
            if response.get('cancelled') or stop_event is not None and stop_event.is_set():
                raise InterruptedError('Voice audition cancelled.')
            if not response.get('ok'):
                raise RuntimeError(str(response.get('error') or 'Chatterbox Multilingual generation failed.'))
            with self._state_lock:
                if epoch != self._epoch or self._closing:
                    raise InterruptedError('Chatterbox Multilingual response cancelled during shutdown.')
            if not response.get('audio'):
                return response.get('result')
            import numpy as np
            import soundfile as sf
            import torch
            path = worker.directory / (request_id + '.wav')
            with self._state_lock:
                if epoch != self._epoch or self._closing:
                    raise InterruptedError('Chatterbox Multilingual audio cancelled during shutdown.')
                audio, rate = sf.read(path, dtype='float32', always_2d=True)
                path.unlink()
                if audio.shape[1] != 1 or rate <= 0 or not np.isfinite(audio).all():
                    raise RuntimeError('Chatterbox Multilingual worker returned invalid audio.')
                self.sr = int(rate)
            return torch.from_numpy(audio.T.copy())
        except InterruptedError:
            raise
        except (_WorkerProtocolError, TimeoutError, BrokenPipeError, OSError):
            with self._close_lock:
                with self._state_lock:
                    owns_failure = epoch == self._epoch and self._worker is not None
                if owns_failure:
                    self._close()
            if stop_event is not None and stop_event.is_set():
                raise InterruptedError('Voice audition cancelled.') from None
            raise
        finally:
            if worker is not None:
                if request_id is not None:
                    try:
                        (worker.directory / (request_id + '.wav')).unlink(missing_ok=True)
                    except OSError:
                        pass
                with self._state_lock:
                    worker.busy = False
            self._request_lock.release()

    def generate(self, text, audio_prompt_path=None, **kwargs):
        return self._call('generate', text=str(text), audio_prompt_path=audio_prompt_path, kwargs=kwargs)

    def warm_up(self):
        values, _ = self._settings()
        if not self._boolean(values['chatterbox_multilingual_prewarm_on_start']):
            return False
        return bool(self._call('warm_up'))

    def generate_reference(self, text, audio_prompt_path, stop_event):
        return self._call('generate_reference', text=str(text), audio_prompt_path=str(audio_prompt_path), stop_event=stop_event)

    @property
    def audition_ready(self):
        with self._state_lock:
            worker = self._worker
            return bool(worker is not None and worker.loaded and not self._closing
                        and not worker.error and worker.process.poll() is None)

    def resources_snapshot(self):
        with self._state_lock:
            worker = self._worker
            if worker is None:
                return []
            alive = not worker.tree.exited() if worker.tree is not None else worker.process.poll() is None
            if not alive and not worker.error:
                return []
            return [{'id': str(worker.process.pid), 'name': 'Chatterbox Multilingual', 'model': 'Chatterbox Multilingual',
                'owner': 'NC · text-to-speech', 'device': worker.device,
                'canUnload': True, 'processId': worker.process.pid, 'processIncludeChildren': True,
                'processLabel': 'Chatterbox Multilingual worker', 'error': worker.error,
                'status': 'cleanup_failed' if worker.error else 'loading' if worker.busy and not worker.loaded else 'in_use' if worker.busy else 'idle'}]

    def unload_resource(self, instance_id):
        # Reserve cleanup under the same ownership check used by close; an old
        # resource row can never close a later chat's replacement worker.
        with self._close_lock:
            with self._state_lock:
                if self._worker is None or str(self._worker.process.pid) != str(instance_id):
                    return False
            self._close()
            return True

    def _close(self):
        with self._state_lock:
            self._epoch += 1
            self._closing = True
            worker = self._worker
        try:
            if worker is None:
                return
            process = worker.process
            if worker.tree is not None:
                worker.tree.capture()
            try:
                if process.poll() is None:
                    self._write(worker, {'action': 'close'})
                    process.wait(timeout=self._STOP_TIMEOUT)
            except (OSError, ValueError, subprocess.SubprocessError):
                pass  # Positive exit checks below own forced cleanup and retry.
            if worker.tree is not None:
                worker.tree.capture()
                if not worker.tree.exited():
                    worker.tree.terminate()
            elif process.poll() is None:
                process.kill()
            process.wait(timeout=2)
            for thread in worker.readers:
                thread.join(1)
            for stream in (process.stdin, process.stdout, process.stderr):
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass
            worker.temporary.cleanup()
            if worker.tree is not None:
                worker.tree.close()
            with self._state_lock:
                if self._worker is worker:
                    self._worker = None
        except (OSError, subprocess.SubprocessError) as error:
            with self._state_lock:
                worker.error = 'Chatterbox Multilingual worker cleanup is incomplete. Stop or unload again to retry.'
            raise RuntimeError(worker.error) from error
        finally:
            with self._state_lock:
                self._closing = False

    def close_strict(self):
        with self._close_lock:
            self._close()

    def close(self):
        self.close_strict()
