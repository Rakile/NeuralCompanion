"""Bounded, content-free lifecycle evidence; file I/O stays on a worker thread."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import threading
import sys
import uuid


class StopDiagnostics:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._queue: queue.Queue[dict[str, object]] = queue.Queue(maxsize=256)
        self._recent: deque[dict[str, object]] = deque(maxlen=40)
        self._lifecycle: deque[dict[str, object]] = deque(maxlen=16)
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._session = uuid.uuid4().hex
        self._sequence = 0
        self._dropped = 0
        self._write_errors = 0

    def record(self, event: str, *, reason: str = "", accepted: bool | None = None,
               error: BaseException | None = None, caller: bool = False) -> None:
        # No messages, configuration, payloads, locals, or exception strings.
        frames: list[dict[str, object]] = []
        if error is not None:
            tb = error.__traceback__
            while tb is not None and len(frames) < 12:
                frames.append({"file": Path(tb.tb_frame.f_code.co_filename).name,
                    "function": tb.tb_frame.f_code.co_name, "line": tb.tb_lineno})
                tb = tb.tb_next
        elif caller:
            frame = sys._getframe(1)
            try:
                while frame is not None and len(frames) < 10:
                    frames.append({"file": Path(frame.f_code.co_filename).name,
                        "function": frame.f_code.co_name, "line": frame.f_lineno})
                    frame = frame.f_back
            finally:
                del frame
        row: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event, "reason": reason, "accepted": accepted,
            "error_type": type(error).__name__ if error is not None else "",
            "frames": frames,
            "pid": os.getpid(), "session": self._session,
        }
        with self._lock:
            self._sequence += 1
            row["sequence"] = self._sequence
            self._recent.append(row)
            if not event.startswith("phone_"):
                self._lifecycle.append(row)
            if self._worker is None:
                self._worker = threading.Thread(target=self._write, name="nc-stop-diagnostics", daemon=True)
                self._worker.start()
            try:
                self._queue.put_nowait(row)
            except queue.Full:
                self._dropped += 1

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            # Detach records from callers, including their frame dictionaries.
            return json.loads(json.dumps({"events": list(self._recent),
                "lifecycle_events": list(self._lifecycle),
                "dropped": self._dropped, "write_errors": self._write_errors}))

    def _write(self) -> None:
        while True:
            row = self._queue.get()
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.exists() and self.path.stat().st_size >= 1024 * 1024:
                    self.path.replace(self.path.with_suffix(self.path.suffix + ".1"))
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(row, ensure_ascii=True) + "\n")
            except Exception:
                with self._lock:
                    self._write_errors += 1
            finally:
                self._queue.task_done()


_diagnostics = StopDiagnostics(Path(__file__).resolve().parents[2] /
    "runtime/main_chat_remote/phone_debug/runtime_lifecycle.jsonl")


def record_runtime_event(event: str, *, reason: str = "", accepted: bool | None = None,
                         error: BaseException | None = None, caller: bool = False) -> None:
    """Best effort only: diagnostics must never change runtime control flow."""
    try:
        _diagnostics.record(event, reason=reason, accepted=accepted, error=error, caller=caller)
    except Exception:
        pass


def runtime_diagnostic_snapshot() -> dict[str, object]:
    return _diagnostics.snapshot()
