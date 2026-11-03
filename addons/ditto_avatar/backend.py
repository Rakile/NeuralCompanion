"""Standard-library-only IPC client. Ditto/CUDA imports occur only in the child process."""
from collections import deque
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import uuid


class DittoWorkerClient:
    def __init__(self, repo_path, python_path='', cache_root='', progress_callback=None,
                 frame_callback=None):
        self.repo_path = Path(repo_path).expanduser().resolve()
        default_python = self.repo_path / ('.venv/Scripts/python.exe' if os.name == 'nt' else '.venv/bin/python')
        self.python_path = str(python_path or default_python)
        self.cache_root = str(cache_root or self.repo_path / 'tmp/neural-companion')
        self.worker_path = Path(__file__).with_name('worker.py')
        self.progress_callback = progress_callback
        self.frame_callback = frame_callback
        self.process = None
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._controls = None
        self.logs = deque(maxlen=1000)
        self._events = queue.Queue()

    def _start(self):
        if self.process is not None and self.process.poll() is None:
            return
        self._events = queue.Queue()
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        env = dict(os.environ, PYTHONUNBUFFERED='1')
        # NC and Ditto both have a top-level `core` package. Keep the host's
        # PYTHONPATH/user-site modules outside this dedicated worker runtime.
        env['PYTHONPATH'] = str(self.repo_path)
        env['PYTHONNOUSERSITE'] = '1'
        env['PATH'] = str(Path(self.python_path).parent) + os.pathsep + env.get('PATH', '')
        self.process = subprocess.Popen(
            [self.python_path, '-u', str(self.worker_path), '--repo', str(self.repo_path),
             '--cache-root', self.cache_root], cwd=str(self.repo_path), env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace', bufsize=1, creationflags=flags,
            start_new_session=os.name != 'nt')
        process, events = self.process, self._events
        controls = self._controls = queue.Queue()
        def write_controls():
            while True:
                payload = controls.get()
                if payload is None or self.process is not process:
                    return
                try:
                    self._send(process, payload)
                except (OSError, ValueError):
                    return
        threading.Thread(target=write_controls, name='ditto-frame-releases', daemon=True).start()

        def read_events():
            try:
                for line in process.stdout:
                    try:
                        event = json.loads(line)
                        if str(event.get('event', '')).startswith('stream_'):
                            # Frames continue arriving between RPCs. Never route
                            # these by the last synchronous request's identity.
                            if self.frame_callback and self.process is process:
                                try:
                                    self.frame_callback(event)
                                except Exception as exc:
                                    self.logs.append(f'Worker callback failed: {exc}')
                        else:
                            events.put(event)
                    except json.JSONDecodeError:
                        self.logs.append('Unexpected worker stdout: ' + line.rstrip())
            finally:
                try:
                    if self.frame_callback and self.process is process:
                        self.frame_callback({'event': 'stream_failed', 'message': 'Ditto worker exited.'})
                except Exception as exc:
                    self.logs.append(f'Worker callback failed: {exc}')
                finally:
                    events.put(None)

        def read_logs():
            for line in process.stderr:
                self.logs.append(line.rstrip())

        threading.Thread(target=read_events, daemon=True).start()
        threading.Thread(target=read_logs, daemon=True).start()

    def request(self, action, cancel_check=None, **payload):
        """Serialize commands; callbacks receive progress/frame record dictionaries on this thread."""
        with self._lock:
            if cancel_check and cancel_check():
                raise RuntimeError('Ditto request cancelled.')
            self._start()
            process, events = self.process, self._events
            request_id = uuid.uuid4().hex
            try:
                self._send(process, {'id': request_id, 'action': action, **payload})
            except (OSError, ValueError) as exc:
                raise RuntimeError(f'Ditto worker is unavailable: {exc}') from exc
            while True:
                if cancel_check and cancel_check():
                    self.close()
                    raise RuntimeError('Ditto request cancelled.')
                try:
                    event = events.get(timeout=.1)
                except queue.Empty:
                    continue
                if event is None:
                    detail = '\n'.join(list(self.logs)[-8:])
                    raise RuntimeError('Ditto worker exited or was cancelled.\n' + detail)
                if event.get('id') != request_id:
                    continue
                kind = event.get('event')
                if kind == 'result':
                    return event.get('result', {})
                if kind == 'error':
                    raise RuntimeError(event.get('message', 'Ditto worker request failed.'))
                callback = self.frame_callback if kind == 'frame' else self.progress_callback
                if callback:
                    try:
                        callback(event)
                    except Exception as exc:
                        self.logs.append(f'Worker callback failed: {exc}')

    def _send(self, process, payload):
        with self._write_lock:
            process.stdin.write(json.dumps(payload, allow_nan=False) + '\n')
            process.stdin.flush()

    def release_frame(self, event):
        # Called under service/buffer locks: enqueue only, never wait on pipe I/O.
        controls = self._controls
        if controls is not None:
            controls.put(dict(action='stream_release', session_id=event['session_id'],
                              slot=event['slot'], generation=event['generation'], chunk_id=event.get('chunk_id')))

    def close_strict(self):
        """Keep an unconfirmed worker visible to resource inspection/cleanup."""
        process = self.process
        try:
            self.close()
        finally:
            if process is not None and process.poll() is None:
                self.process = process
                raise RuntimeError('Ditto worker did not exit; GPU memory release is unconfirmed.')

    def close(self):
        """Cancellation is deliberately independent of the request lock. Closing releases CUDA."""
        process = self.process
        self.process = None
        if self._controls is not None:
            self._controls.put(None)
            self._controls = None
        if process is None:
            return
        if process.poll() is None:
            if os.name == 'nt':
                try:
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW, timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            else:
                import signal
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        for stream in (process.stdin, process.stdout, process.stderr):
            try:
                stream.close()
            except OSError:
                pass
