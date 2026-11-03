"""Content-free peer traces; bounded queue and rotating disk writes off the event loop."""
from collections import deque
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import queue
import re
import threading
import time

_queue = queue.Queue(maxsize=512)
_start_lock = threading.Lock()
_started = False


def safe_fields(values):
    result = {}
    for key in ('request_id', 'reply_id', 'operation', 'route', 'method', 'outcome', 'session_id', 'reason'):
        value = values.get(key)
        if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_/-]{1,128}', value):
            result[key] = value
    for key in ('elapsed_ms', 'status', 'pending', 'buffered_bytes', 'response_bytes'):
        value = values.get(key)
        if type(value) in (int, float) and 0 <= value <= 10**12:
            result[key] = value
    error_type = values.get('error_type')
    if isinstance(error_type, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', error_type):
        result['error_type'] = error_type
    return result


def _writer():
    handlers = {}
    while True:
        path, row = _queue.get()
        try:
            handler = handlers.get(path)
            if handler is None:
                if len(handlers) >= 4:
                    handlers.pop(next(iter(handlers))).close()
                path.parent.mkdir(parents=True, exist_ok=True)
                handler = RotatingFileHandler(path, maxBytes=1024*1024, backupCount=2, encoding='utf-8')
                handlers[path] = handler
            handler.emit(logging.LogRecord('nc.peer', logging.INFO, '', 0,
                json.dumps(row, separators=(',', ':')), (), None))
        except Exception:
            pass  # Diagnostics must never change transport behavior.
        finally:
            _queue.task_done()


def disk_sink(path: Path):
    global _started
    with _start_lock:
        if not _started:
            threading.Thread(target=_writer, name='nc-peer-diagnostics', daemon=True).start()
            _started = True
    def emit(row):
        try:
            _queue.put_nowait((path, row))
        except queue.Full:
            pass
    return emit


class PeerTrace:
    def __init__(self, sink, *, session_id=''):
        self.sink = sink
        self.session_id = session_id
        self.recent = deque(maxlen=32)
        self.last_snapshot = float('-inf')
        self.lock = threading.Lock()

    def event(self, event, *, failure=False, **values):
        try:
            now = time.monotonic()
            row = dict(timestamp=datetime.now(timezone.utc).isoformat(), monotonic_ms=round(now*1000),
                       event=event, **safe_fields({'session_id': self.session_id, **values}))
            with self.lock:
                self.recent.append(row)
                self.sink(row)
                if failure and now-self.last_snapshot >= 10:
                    self.last_snapshot = now
                    self.sink(dict(timestamp=row['timestamp'], event='peer_failure_snapshot', recent=list(self.recent)))
        except Exception:
            pass
