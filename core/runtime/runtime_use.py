from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from threading import RLock
from uuid import uuid4


@dataclass(frozen=True)
class RuntimeUseSnapshot:
    owner: str
    phase: str
    reason: str
    ready: bool = False


class RuntimeUseBusy(RuntimeError):
    pass


class RuntimeUseGate:
    _OWNERS = frozenset(("chat", "creator"))

    def __init__(self) -> None:
        self._lock = RLock()
        self._token = ""
        self._owner = ""
        self._phase = "free"
        self._reason = ""
        self._ready = False
        self._startup_cancelled = False
        self._resource_maintenance_active = False

    def reserve(self, owner: str) -> str:
        if owner not in self._OWNERS:
            raise ValueError(f"unknown runtime-use owner: {owner!r}")

        with self._lock:
            if self._phase != "free" or self._resource_maintenance_active:
                raise RuntimeUseBusy(
                    f"runtime is reserved by {self._owner!r} in phase {self._phase!r}"
                )
            token = uuid4().hex
            self._token = token
            self._owner = owner
            self._phase = "starting"
            self._reason = ""
            self._ready = False
            self._startup_cancelled = False
            return token

    def claim(self, token: str, owner: str) -> None:
        if owner not in self._OWNERS:
            raise ValueError(f"unknown runtime-use owner: {owner!r}")

        with self._lock:
            self._require_token(token)
            if owner != self._owner or self._phase != "starting":
                raise RuntimeUseBusy("runtime reservation cannot be claimed")
            self._phase = "active"

    def cancel_startup(self) -> bool:
        """Latch cancellation on this chat reservation, independently of run reset."""
        with self._lock:
            if self._owner != "chat" or self._phase not in ("starting", "active") or self._ready:
                return False
            self._startup_cancelled = True
            return True

    def startup_cancelled(self, token: str) -> bool:
        with self._lock:
            self._require_token(token)
            return self._startup_cancelled

    def mark_ready(self, token: str) -> bool:
        """Publish backend readiness without changing admission ownership."""
        with self._lock:
            self._require_token(token)
            if self._owner != "chat" or self._phase != "active":
                raise RuntimeUseBusy("only an active chat runtime can become ready")
            if self._startup_cancelled:
                return False
            self._ready = True
            return True

    def begin_cleanup(self, token: str) -> None:
        with self._lock:
            self._require_token(token)
            if self._phase not in ("starting", "active", "cleanup_failed"):
                raise RuntimeUseBusy("runtime reservation cannot begin cleanup")
            self._phase = "stopping"
            self._reason = ""
            self._ready = False

    def finish(self, token: str, *, cleanup_ok: bool, reason: str = "") -> None:
        with self._lock:
            self._require_token(token)
            if cleanup_ok:
                if self._phase not in ("starting", "stopping", "cleanup_failed"):
                    raise RuntimeUseBusy("runtime reservation cannot finish")
                self._token = ""
                self._owner = ""
                self._phase = "free"
                self._reason = ""
                self._ready = False
                return

            if self._phase not in ("stopping", "cleanup_failed"):
                raise RuntimeUseBusy("runtime cleanup failure cannot be recorded")
            self._phase = "cleanup_failed"
            self._reason = reason

    def snapshot(self) -> RuntimeUseSnapshot:
        with self._lock:
            return RuntimeUseSnapshot(
                owner=self._owner,
                phase=self._phase,
                reason=self._reason,
                ready=self._ready,
            )

    @contextmanager
    def resource_maintenance(self):
        """Reserve startup admission without blocking runtime status readers."""
        with self._lock:
            if (self._resource_maintenance_active or self._owner == 'chat'
                    or self._phase in ('starting', 'stopping')):
                raise RuntimeUseBusy('Stop the active runtime before unloading its resources.')
            free = self._phase == 'free'
            self._resource_maintenance_active = True
            if free:
                self._owner, self._phase = 'resources', 'maintenance'
        try:
            yield
        finally:
            with self._lock:
                self._resource_maintenance_active = False
                if free:
                    self._owner, self._phase = '', 'free'

    def _require_token(self, token: str) -> None:
        if not token or token != self._token:
            raise RuntimeUseBusy("runtime reservation token is not current")
