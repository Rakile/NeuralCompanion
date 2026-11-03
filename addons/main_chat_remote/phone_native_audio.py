"""Addon-local, exact ownership of phone-native normal chat requests."""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
import threading
import time
from typing import Any


class NativeDispatchGuard:
    """Atomically choose between starting a queued effect and cancelling it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started = False
        self._cancelled = False

    def commit(self, effect: Callable[[], Any]) -> Any:
        with self._lock:
            if self._cancelled:
                return None
            self._started = True
        # Never hold the admission lock while invoking the host or waiting on UI.
        return effect()

    def cancel_before_start(self) -> bool:
        with self._lock:
            if self._started:
                return False
            self._cancelled = True
            return True


@dataclass
class _NativeRequest:
    transaction_id: str = ""
    completed_at: float | None = None


class NativeRequestRegistry:
    """Pending requests never expire or get evicted to admit another request."""

    def __init__(self, *, capacity: int = 512, retention_seconds: float = 86400,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._capacity = capacity
        self._retention = retention_seconds
        self._clock = clock
        self._lock = threading.RLock()
        self._requests: dict[str, _NativeRequest] = {}

    def _expire_completed(self) -> None:
        now = self._clock()
        for request_id, entry in list(self._requests.items()):
            if entry.completed_at is not None and now - entry.completed_at >= self._retention:
                del self._requests[request_id]

    def register(self, request_id: str) -> bool:
        with self._lock:
            self._expire_completed()
            if not request_id or request_id in self._requests or len(self._requests) >= self._capacity:
                return False
            self._requests[request_id] = _NativeRequest()
            return True

    def discard(self, request_id: str) -> None:
        with self._lock:
            self._requests.pop(request_id, None)

    def owns(self, request_id: str) -> bool:
        with self._lock:
            return bool(request_id) and request_id in self._requests

    def correlate(self, history: Iterable[object]) -> dict[str, str]:
        """Join user capture IDs to completed assistants across the entire feed."""
        turns = [turn for turn in history if isinstance(turn, Mapping)]
        with self._lock:
            self._expire_completed()
            for turn in turns:
                if turn.get("role") != "user":
                    continue
                entry = self._requests.get(str(turn.get("remote_capture_id") or ""))
                transaction_id = str(turn.get("normal_chat_transaction_id") or "")
                if entry is not None and transaction_id:
                    entry.transaction_id = transaction_id
            by_transaction = {entry.transaction_id: request_id for request_id, entry in self._requests.items()
                              if entry.transaction_id}
            result = {}
            for turn in turns:
                transaction_id = str(turn.get("normal_chat_transaction_id") or "")
                request_id = by_transaction.get(transaction_id)
                if (request_id and turn.get("role") == "assistant" and str(turn.get("content") or "").strip()
                        and not turn.get("interrupted") and not turn.get("hidden_proactive")):
                    entry = self._requests[request_id]
                    if entry.completed_at is None:
                        entry.completed_at = self._clock()
                    result[transaction_id] = request_id
            return result
