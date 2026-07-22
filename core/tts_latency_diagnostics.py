"""Low-overhead diagnostics for addon calls on the TTS critical path."""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any


TRACE_FILENAME = "tts_addon_latency.jsonl"
TRACE_MAX_BYTES = 2_000_000
TRACE_QUEUE_SIZE = 512
CRITICAL_CAPABILITIES = frozenset(
    {
        "buddy_chat.assistant_reply",
        "roleplay.assistant_reply",
        "tts.audio_chunk_ready",
        "tts.duck.end",
        "tts.duck.start",
        "tts.segment_started",
        "tts.voice_route",
        "tts.voice_segments",
        "tts.voice_segments.requires_full_text",
    }
)
_BLOCKED_FIELD_MARKERS = ("content", "key", "password", "prompt", "secret", "text", "token")


def runtime_diagnostic_fields() -> dict[str, Any]:
    """Return a cheap process snapshot without importing optional runtimes."""
    fields: dict[str, Any] = {
        "python_threads": int(threading.active_count()),
        "process_cpu_ms": round(time.process_time() * 1000.0, 3),
        "torch_loaded": False,
    }
    torch_module = sys.modules.get("torch")
    if torch_module is None:
        return fields

    fields["torch_loaded"] = True
    try:
        fields["torch_threads"] = int(torch_module.get_num_threads())
    except Exception:
        pass
    try:
        fields["torch_interop_threads"] = int(torch_module.get_num_interop_threads())
    except Exception:
        pass

    cuda = getattr(torch_module, "cuda", None)
    if cuda is None:
        fields["cuda_available"] = False
        return fields
    try:
        cuda_available = bool(cuda.is_available())
    except Exception:
        cuda_available = False
    fields["cuda_available"] = cuda_available
    if not cuda_available:
        return fields
    try:
        device_index = int(cuda.current_device())
        fields["cuda_device"] = device_index
        fields["cuda_allocated_mb"] = round(float(cuda.memory_allocated(device_index)) / (1024.0 * 1024.0), 3)
        fields["cuda_reserved_mb"] = round(float(cuda.memory_reserved(device_index)) / (1024.0 * 1024.0), 3)
    except Exception:
        pass
    return fields


class TtsLatencyDiagnostics:
    """Write bounded JSONL traces without performing file I/O in the caller."""

    def __init__(
        self,
        app_root: str | Path,
        *,
        max_bytes: int = TRACE_MAX_BYTES,
        queue_size: int = TRACE_QUEUE_SIZE,
    ) -> None:
        self.path = Path(app_root) / "runtime" / "logs" / TRACE_FILENAME
        self._max_bytes = max(64_000, int(max_bytes or TRACE_MAX_BYTES))
        self._queue: queue.Queue[dict[str, Any] | tuple[str, threading.Event]] = queue.Queue(
            maxsize=max(16, int(queue_size or TRACE_QUEUE_SIZE))
        )
        self._closed = False
        self._dropped = 0
        self._thread = threading.Thread(
            target=self._writer_loop,
            name="NCTtsLatencyTrace",
            daemon=True,
        )
        self._thread.start()

    @staticmethod
    def should_trace(capability: str, duration_ms: float) -> bool:
        name = str(capability or "").strip().lower()
        return name in CRITICAL_CAPABILITIES or float(duration_ms or 0.0) >= 100.0

    def record_addon_capability(
        self,
        *,
        addon_id: str,
        capability: str,
        duration_ms: float,
        handled: bool,
        error_type: str = "",
    ) -> None:
        if self._closed or not self.should_trace(capability, duration_ms):
            return
        row = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "monotonic_ms": round(time.perf_counter() * 1000.0, 3),
            "event": "addon_capability",
            "addon_id": str(addon_id or ""),
            "capability": str(capability or ""),
            "duration_ms": round(max(0.0, float(duration_ms or 0.0)), 3),
            "handled": bool(handled),
            "error_type": str(error_type or "")[:120],
            "thread": threading.current_thread().name,
            "pid": os.getpid(),
        }
        self._enqueue(row)

    def record_event(self, event: str, **fields: Any) -> None:
        if self._closed:
            return
        event_name = "".join(char for char in str(event or "") if char.isalnum() or char in {"_", "-"})[:80]
        if not event_name:
            return
        row: dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "monotonic_ms": round(time.perf_counter() * 1000.0, 3),
            "event": event_name,
            "thread": threading.current_thread().name,
            "pid": os.getpid(),
        }
        for raw_key, value in dict(fields or {}).items():
            key = str(raw_key or "").strip()[:80]
            lowered = key.lower()
            if not key or any(marker in lowered for marker in _BLOCKED_FIELD_MARKERS):
                continue
            if value is None or isinstance(value, (bool, int, float)):
                row[key] = value
            elif isinstance(value, str):
                row[key] = value[:160]
        self._enqueue(row)

    def _enqueue(self, row: dict[str, Any]) -> None:
        try:
            self._queue.put_nowait(row)
        except queue.Full:
            self._dropped += 1

    def flush(self, timeout: float = 1.0) -> bool:
        if self._closed:
            return True
        completed = threading.Event()
        try:
            self._queue.put(("flush", completed), timeout=max(0.01, min(float(timeout), 0.25)))
        except queue.Full:
            return False
        return completed.wait(max(0.01, float(timeout)))

    def close(self, timeout: float = 1.0) -> None:
        if self._closed:
            return
        self.flush(timeout=timeout)
        self._closed = True
        completed = threading.Event()
        try:
            self._queue.put(("close", completed), timeout=0.25)
        except queue.Full:
            return
        completed.wait(max(0.01, float(timeout)))

    def _writer_loop(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if isinstance(item, tuple):
                    command, completed = item
                    if command == "flush":
                        completed.set()
                        continue
                    completed.set()
                    return
                self._write_row(item)
            finally:
                self._queue.task_done()

    def _write_row(self, row: dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed()
            payload = dict(row)
            if self._dropped:
                payload["dropped_before"] = int(self._dropped)
                self._dropped = 0
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
        except Exception:
            return

    def _rotate_if_needed(self) -> None:
        try:
            if not self.path.exists() or self.path.stat().st_size < self._max_bytes:
                return
            rotated = self.path.with_suffix(self.path.suffix + ".1")
            if rotated.exists():
                rotated.unlink()
            self.path.replace(rotated)
        except Exception:
            return
