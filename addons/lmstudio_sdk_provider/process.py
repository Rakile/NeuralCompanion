"""Isolated SDK requests; cancellation closes the owning helper process."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

def cancelled(token):
    if token is None:
        return False
    value = getattr(token, 'cancelled', False)
    if isinstance(value, bool) and value:
        return True
    for name in ('is_set', 'is_cancelled'):
        check = getattr(token, name, None)
        if callable(check) and check():
            return True
    return False


def _yield_ui():
    try:
        from PySide6.QtCore import QCoreApplication, QThread
        app = QCoreApplication.instance()
        if app is not None and QThread.currentThread() == app.thread():
            app.processEvents()
    except ImportError:
        pass


class SDKProcessRunner:
    def __init__(self, command=None):
        self.command = command or [sys.executable, '-u', str(Path(__file__).with_name('worker.py'))]
        self._lock = threading.Lock()
        self._active = set()
        self._closed = False

    @property
    def active_processes(self):
        with self._lock:
            return tuple(self._active)

    def close(self):
        with self._lock:
            self._closed = True
            active = tuple(self._active)
        for process in active:
            if process.poll() is None:
                process.terminate()

    def _events(self, request, *, timeout=None, cancel_token=None):
        if cancelled(cancel_token):
            raise RuntimeError('LM Studio SDK request cancelled.')
        deadline = None
        if timeout is not None:
            duration = float(timeout)
            if not math.isfinite(duration) or duration <= 0:
                raise TimeoutError('LM Studio SDK request deadline expired.')
            deadline = time.monotonic() + duration
        # Temporary settings/usage tracing is retired for ordinary requests.
        payload = json.dumps(dict(request, diagnostics=False), ensure_ascii=False, allow_nan=False).encode('utf-8')
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        with self._lock:
            if self._closed:
                raise RuntimeError('LM Studio SDK provider is closed.')
            process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, **options)
            self._active.add(process)
        messages, errors = queue.Queue(), []

        def read_stdout():
            try:
                for line in process.stdout:
                    messages.put(line)
            finally:
                messages.put(None)

        def read_stderr():
            errors.append(process.stderr.read().decode('utf-8', errors='replace'))

        def write_stdin():
            try:
                process.stdin.write(payload)
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass  # The child result/exit supplies the actual helper error.

        stdout = threading.Thread(target=read_stdout, daemon=True)
        stderr = threading.Thread(target=read_stderr, daemon=True)
        stdin = threading.Thread(target=write_stdin, daemon=True)
        stdout.start(); stderr.start(); stdin.start()
        try:
            terminal = None
            failure_category, failure_status = 'unknown', None
            while True:
                if cancelled(cancel_token):
                    raise RuntimeError('LM Studio SDK request cancelled.')
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError('LM Studio SDK request deadline expired.')
                with self._lock:
                    if self._closed:
                        raise RuntimeError('LM Studio SDK provider closed during request.')
                _yield_ui()
                try:
                    raw = messages.get(timeout=0.05)  # UI/cancellation polling, not a request deadline.
                except queue.Empty:
                    continue
                if raw is None:
                    break
                try:
                    frame = json.loads(raw.decode('utf-8'))
                except (ValueError, UnicodeError) as exc:
                    raise RuntimeError('Invalid LM Studio SDK helper JSON protocol.') from exc
                if not isinstance(frame, dict) or terminal is not None:
                    raise RuntimeError('Invalid LM Studio SDK helper protocol or duplicate result.')
                if set(frame) == {'chunk'} and isinstance(frame['chunk'], str):
                    yield frame
                elif set(frame) == {'diagnostic'} and isinstance(frame['diagnostic'], dict):
                    facts = frame['diagnostic']
                    if facts.get('phase') == 'provider_error':
                        from core.chat_providers import FROZEN_FAILURE_CATEGORIES
                        category, status = facts.get('category'), facts.get('http_status')
                        failure_category = category if isinstance(category, str) and category in FROZEN_FAILURE_CATEGORIES else 'unknown'
                        failure_status = status if type(status) is int and 400 <= status <= 599 else None
                    continue  # Failure metadata stays private; legacy tracing is ignored.
                elif set(frame) == {'ok', 'value'} and frame['ok'] is True:
                    terminal = frame
                elif set(frame) == {'ok', 'error'} and frame['ok'] is False and isinstance(frame['error'], str):
                    from core.chat_providers import FrozenChatProviderExecutionError, chat_provider_error_message, _classify_frozen_provider_failure
                    if failure_category == 'unknown':
                        failure_category, failure_status = _classify_frozen_provider_failure(RuntimeError(frame['error']))
                    raise FrozenChatProviderExecutionError(
                        chat_provider_error_message('lmstudio_sdk', failure_category, failure_status),
                        diagnostic_category=failure_category, diagnostic_http_status=failure_status)
                else:
                    raise RuntimeError('Invalid LM Studio SDK helper result protocol.')
            while process.poll() is None:
                if cancelled(cancel_token):
                    raise RuntimeError('LM Studio SDK request cancelled.')
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError('LM Studio SDK request deadline expired.')
                _yield_ui()
                time.sleep(0.05)
            stderr.join()
            if process.returncode:
                raise RuntimeError('LM Studio SDK helper failed: ' + (''.join(errors).strip() or str(process.returncode)))
            if terminal is None:
                raise RuntimeError('LM Studio SDK helper exited without a complete result.')
            yield terminal
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            stdin.join(); stdout.join(); stderr.join()
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()
            with self._lock:
                self._active.discard(process)

    def call(self, request, *, timeout=None, cancel_token=None):
        events = self._events(dict(request, stream=False), timeout=timeout, cancel_token=cancel_token)
        try:
            for frame in events:
                if frame.get('ok') is True:
                    return frame['value']
        finally:
            events.close()
        raise RuntimeError('LM Studio SDK helper returned no result.')

    def stream(self, request, *, timeout=None, cancel_token=None):
        events = self._events(dict(request, stream=True), timeout=timeout, cancel_token=cancel_token)
        try:
            for frame in events:
                if 'chunk' in frame:
                    yield frame['chunk']
        finally:
            events.close()
