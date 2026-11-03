"""Bounded private-pipe supervisor, called only from LAN HTTP request threads."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import queue
import secrets
import subprocess
import sys
import threading
from pathlib import Path

MAX_FRAME = 100_000


class MediaSetupRequired(RuntimeError):
    pass


class LocalAVService:
    def __init__(self, bridge_info: Path | None, *, app_root: Path | None = None):
        self.info = bridge_info
        self.root = app_root or Path(__file__).resolve().parents[2]
        self.lock = threading.Lock()
        self.lifecycle = threading.RLock()
        self.process = None
        self.responses = None
        self.binding = ''
        self.stopped = False
        self.instance = secrets.token_hex(16)

    def _terminate(self):
        process, self.process = self.process, None
        if process:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            for pipe in (process.stdin, process.stdout):
                if pipe:
                    pipe.close()

    def close(self):
        with self.lifecycle:
            self.stopped = True
            self._terminate()

    def _launch(self, binding):
        with self.lifecycle:
            if os.environ.get('NC_REMOTE_AV_TRACKS') == '0':
                raise MediaSetupRequired('Desktop streamed media is explicitly disabled')
            if self.stopped or not self.info or not self.info.is_file():
                raise RuntimeError('Local media unavailable')
            if self.process and self.process.poll() is None and binding == self.binding:
                return
            self._terminate()
            python = self.root / '.venvs/nc_relay' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
            if not python.is_file():
                # Explicit setup owns dependencies. Never install at connect time.
                if importlib.util.find_spec('aiortc') is None:
                    raise MediaSetupRequired('Prepare the NC media runtime before connecting')
                python = Path(sys.executable)
            if self.binding and binding != self.binding:
                self.instance = secrets.token_hex(16)
            process = subprocess.Popen(
                [str(python), '-B', '-u', '-m', 'addons.main_chat_remote.local_av_worker', str(self.info)],
                cwd=self.root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            replies = queue.Queue(maxsize=1)
            self.process, self.responses, self.binding = process, replies, binding

            def read():
                try:
                    while True:
                        raw = process.stdout.readline(MAX_FRAME + 1)
                        if not raw or len(raw) > MAX_FRAME:
                            break
                        replies.put_nowait(json.loads(raw))
                except (OSError, ValueError, queue.Full):
                    pass
                finally:
                    try:
                        replies.put_nowait(None)
                    except queue.Full:
                        pass
            threading.Thread(target=read, name='nc-local-av-pipe', daemon=True).start()

    def request(self, action, body, *, pairing_code, address):
        if action not in {'offer', 'candidate', 'status', 'close'}:
            return 404, {'error': 'Unknown local media route.'}
        if not self.lock.acquire(timeout=.25):
            return 429, {'error': 'Local media setup busy. Retry shortly.'}
        try:
            self._launch(pairing_code)
            owner = hashlib.sha256((pairing_code + '\0' + address).encode()).hexdigest()
            message = json.dumps({'action': action, 'body': body, 'owner': owner}, separators=(',', ':')).encode() + b'\n'
            if len(message) > MAX_FRAME:
                return 413, {'error': 'Local media request too large.'}
            process, responses = self.process, self.responses
            if process is None or responses is None:
                raise RuntimeError('Local media closed')
            process.stdin.write(message)
            process.stdin.flush()
            result = responses.get(timeout=12)
            if not isinstance(result, dict) or not isinstance(result.get('body'), dict):
                raise RuntimeError('Local media worker ended')
            if action == 'offer' and result['status'] == 200:
                result['body']['desktop_instance'] = self.instance
            return int(result['status']), result['body']
        except MediaSetupRequired:
            return 503, {'error_code': 'MEDIA_SETUP_REQUIRED',
                         'error': 'Prepare the desktop media runtime before connecting.'}
        except (OSError, RuntimeError, ValueError, KeyError, queue.Empty):
            with self.lifecycle:
                self._terminate()
            return 503, {'error': 'Local media unavailable. Prepare the desktop media runtime and reconnect.'}
        finally:
            self.lock.release()
