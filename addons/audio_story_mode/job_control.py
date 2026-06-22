from __future__ import annotations

import threading
import time


class CancellationToken:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancelled = False
        self._reason = ""

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return bool(self._cancelled)

    @property
    def reason(self) -> str:
        with self._lock:
            return str(self._reason or "")

    def cancel(self, reason: str = "") -> None:
        with self._lock:
            self._cancelled = True
            self._reason = str(reason or "").strip()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            reason = self.reason or "cancelled"
            raise TimeoutError(f"Audio Story job {reason}.")


class JobDeadline:
    def __init__(self, *, timeout_seconds: float) -> None:
        self.timeout_seconds = max(0.0, float(timeout_seconds or 0.0))
        self.started_at = time.monotonic()
        self.deadline_at = self.started_at + self.timeout_seconds if self.timeout_seconds > 0 else 0.0

    @property
    def expired(self) -> bool:
        return bool(self.deadline_at and time.monotonic() >= self.deadline_at)

    def remaining_seconds(self, *, default: float = 0.0, minimum: float = 0.0) -> float:
        if not self.deadline_at:
            return max(float(minimum or 0.0), float(default or 0.0))
        remaining = self.deadline_at - time.monotonic()
        return max(float(minimum or 0.0), float(remaining))
