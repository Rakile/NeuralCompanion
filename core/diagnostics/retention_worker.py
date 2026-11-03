"""Coalesced archive maintenance, independent of the ordinary journal writer."""
from concurrent.futures import Future
import json
import os
from pathlib import Path
import sys
import threading
import time

from core.diagnostics.failure_archive import archive_completed, _plain

_lock = threading.Lock()
_pending = {}


def request_archive(root, *, keep_latest=0):
    root = Path(root).absolute()
    key = os.path.normcase(str(root))
    with _lock:
        if key in _pending:
            return _pending[key]
        future = Future()
        future.set_running_or_notify_cancel()
        _pending[key] = future
        before_ns = time.time_ns()

        def run():
            try:
                report = archive_completed(root, keep_latest=keep_latest, before_ns=before_ns)
                report['checked_at_ns'] = time.time_ns()
                if root.exists() and report['status'] != 'archive_busy':
                    _plain(root, directory=True)
                    # Another process can maintain the same store; health is advisory,
                    # atomic, and last-writer-wins. Unique temp avoids writer collisions.
                    temporary = root / f'archive-health-{os.getpid()}.tmp'
                    if temporary.exists():
                        _plain(temporary)
                    with temporary.open('w', encoding='utf-8') as handle:
                        json.dump(report, handle, separators=(',', ':'))
                        handle.flush()
                        os.fsync(handle.fileno())
                    temporary.replace(root / 'archive-health.json')
                if report['status'] not in ('ready', 'archive_busy'):
                    sys.stderr.write('[NC diagnostics] '+report['status']+'; protected evidence retained\n')
            except Exception as error:
                report = dict(status='archive_worker_failed', error_type=type(error).__name__)
                try:
                    sys.stderr.write('[NC diagnostics] archive_worker_failed; protected evidence retained\n')
                except Exception:
                    pass
            with _lock:
                _pending.pop(key, None)
            future.set_result(report)

        worker = threading.Thread(target=run, name='nc-diagnostic-archive', daemon=True)
        try:
            worker.start()
        except Exception:
            _pending.pop(key, None)
            raise
        return future
