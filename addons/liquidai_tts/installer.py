"""Explicit, addon-owned LiquidAI runtime setup. Discovery performs no writes."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import sys
import threading

from .config import REVISION, managed_paths, validate_model_folder

READY_FILE = 'liquidai-runtime.json'
READY_STATE = {'python': '3.12', 'torch': '2.11.0', 'transformers': '5.22.1', 'peft': '0.21.2', 'revision': REVISION}


def child_environment(paths):
    """Return private child caches; never alter NC's environment."""
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith(('PIP_', 'UV_')) or key in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV', '__PYVENV_LAUNCHER__'):
            env.pop(key, None)
    env.update({
        'PYTHONNOUSERSITE': '1', 'PYTHONUNBUFFERED': '1', 'PYTHONIOENCODING': 'utf-8',
        'HF_HOME': str(paths.cache / 'huggingface'),
        'HF_HUB_CACHE': str(paths.cache / 'huggingface' / 'hub'),
        'HF_MODULES_CACHE': str(paths.cache / 'huggingface' / 'modules'),
        'UV_CACHE_DIR': str(paths.cache / 'uv'), 'PIP_CACHE_DIR': str(paths.cache / 'pip'),
        'UV_PYTHON_DOWNLOADS': 'never', 'PIP_CONFIG_FILE': os.devnull,
    })
    return env


class LiquidAIInstaller:
    def __init__(self, app_root):
        self.paths = managed_paths(app_root)
        self._install_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._cancel = threading.Event()
        self._process = None
        self._status = 'Install / Repair LiquidAI runtime'
        self._error = ''

    def snapshot(self):
        installed = False
        try:
            marker = self.paths.environment / READY_FILE
            if self.paths.python.is_file() and json.loads(marker.read_text(encoding='utf-8')) == READY_STATE:
                validate_model_folder(self.paths.model_dir)
                installed = True
        except (OSError, ValueError, TypeError):
            pass
        with self._state_lock:
            busy = self._install_lock.locked()
            return {'installed': installed, 'busy': busy,
                    'status': self._status if busy or self._error or not installed else 'LiquidAI runtime ready',
                    'python': str(self.paths.python), 'model_dir': str(self.paths.model_dir), 'error': self._error}

    def _find_python312(self):
        """Probe installed interpreters only, on explicit setup; never bootstrap Python."""
        from .python_bootstrap import private_python312
        candidates = [str(private_python312(self.paths.root)), sys.executable,
                      shutil.which('python3.12'), shutil.which('python312'), shutil.which('python')]
        if os.name == 'nt':
            local = os.environ.get('LOCALAPPDATA')
            if local:
                candidates.append(str(Path(local) / 'Programs' / 'Python' / 'Python312' / 'python.exe'))
            try:
                import winreg
                for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                    for access in (winreg.KEY_READ | winreg.KEY_WOW64_64KEY, winreg.KEY_READ | winreg.KEY_WOW64_32KEY):
                        try:
                            with winreg.OpenKey(hive, r'Software\Python\PythonCore\3.12\InstallPath', 0, access) as key:
                                candidates.append(str(Path(winreg.QueryValue(key, None)) / 'python.exe'))
                        except OSError:
                            pass
            except ImportError:
                pass
        for candidate in dict.fromkeys(value for value in candidates if value):
            try:
                result = subprocess.run([candidate, '-I', '-c', 'import sys; print(sys.executable if sys.version_info[:2] == (3,12) else "")'],
                    capture_output=True, text=True, timeout=10, env=child_environment(self.paths),
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
            except (OSError, subprocess.SubprocessError):
                pass
        return None

    def install(self, cancel_event, progress_callback, *, install_python: bool = False):
        if not self._install_lock.acquire(blocking=False):
            return self.snapshot()
        try:
            self._cancel.clear()
            with self._state_lock:
                self._error = ''
                self._status = 'Preparing LiquidAI setup'
            def progress(message):
                with self._state_lock:
                    self._status = str(message)
                if progress_callback:
                    progress_callback(str(message))
            if cancel_event.is_set():
                self._cancel.set()
            if not self._cancel.is_set():
                python = self._find_python312()
                if not python and install_python:
                    from .python_bootstrap import ensure_python312
                    python = ensure_python312(self.paths.root,
                        lambda: cancel_event.is_set() or self._cancel.is_set(), progress,
                        environment=child_environment(self.paths))
                if not python:
                    raise RuntimeError('Python 3.12 is required. Install Python 3.12, then run Install / Repair again. Setup does not install system Python.')
                if cancel_event.is_set() or self._cancel.is_set():
                    self._cancel.set()
                else:
                    progress('Setting up the private LiquidAI environment and pinned model')
                    command = [python, '-u', str(Path(__file__).with_name('setup_worker.py')), str(self.paths.root)]
                    code, tail = self._run(command, cancel_event, progress)
                    if code and not (self._cancel.is_set() or cancel_event.is_set()):
                        raise RuntimeError(tail or f'LiquidAI setup failed (exit {code}).')
                    if not self._cancel.is_set() and not cancel_event.is_set() and not self.snapshot()['installed']:
                        raise RuntimeError('Setup exited without a verified runtime; run Install / Repair again.')
            if self._cancel.is_set() or cancel_event.is_set():
                progress('LiquidAI setup cancelled; Install / Repair can resume downloads')
            else:
                progress('LiquidAI runtime ready')
        except Exception as exc:
            with self._state_lock:
                self._error = str(exc)
                self._status = 'LiquidAI setup failed'
        finally:
            self._install_lock.release()
        return self.snapshot()

    def cancel(self):
        self._cancel.set()
        with self._state_lock:
            process = self._process
        if process is not None:
            self._stop_process(process)

    @staticmethod
    def _stop_process(process):
        # setup_worker owns a kill-on-close Windows Job Object before any child
        # starts. Terminating it also retires the actual venv Python descendants.
        if process.poll() is not None:
            return
        try:
            if os.name == 'nt':
                process.terminate()
            else:
                os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                if os.name == 'nt':
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            except (OSError, subprocess.SubprocessError):
                pass

    def _run(self, command, cancel, progress):
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace', bufsize=1,
            env=child_environment(self.paths), cwd=str(self.paths.root),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            start_new_session=os.name != 'nt')
        with self._state_lock:
            self._process = process
        messages = queue.Queue(maxsize=256)
        finished = threading.Event()
        def read_output():
            try:
                for line in process.stdout:
                    messages.put(line.rstrip())
            finally:
                messages.put(None)
        def watch_cancel():
            while not finished.is_set():
                if cancel.wait(.1) or self._cancel.is_set():
                    self._cancel.set()
                    self._stop_process(process)
                    return
        reader = threading.Thread(target=read_output, name='LiquidAI-setup-output', daemon=True)
        watcher = threading.Thread(target=watch_cancel, name='LiquidAI-setup-cancel', daemon=True)
        reader.start()
        watcher.start()
        tail = []
        try:
            while True:
                line = messages.get()
                if line is None:
                    break
                tail.append(line)
                tail = tail[-60:]
                progress(line)
            return process.wait(), '\n'.join(tail)[-12000:]
        finally:
            finished.set()
            self._stop_process(process)
            # Drain queued lines if a progress callback raised, allowing reader
            # retirement even when output filled its bounded queue.
            while reader.is_alive():
                try:
                    messages.get(timeout=.1)
                except queue.Empty:
                    pass
            reader.join()
            watcher.join()
            process.stdout.close()
            with self._state_lock:
                if self._process is process:
                    self._process = None
