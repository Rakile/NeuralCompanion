"""Explicit production ownership for external shutdown requests."""

from __future__ import annotations

from typing import Protocol
from core.runtime.stop_diagnostics import record_runtime_event


class StopSignal(Protocol):
    def set(self) -> None: ...


class AvatarShutdown(Protocol):
    def stop(self) -> object: ...


class ProductionShutdownOwner:
    """Publish stop intent once and preserve the legacy idle-avatar behavior."""

    __slots__ = ("_avatar", "_playback_stop", "_stop")

    def __init__(
        self,
        *,
        stop: StopSignal,
        playback_stop: StopSignal,
        avatar: AvatarShutdown,
    ) -> None:
        self._stop = stop
        self._playback_stop = playback_stop
        self._avatar = avatar

    def request_stop(self, reason: str = "user") -> None:
        record_runtime_event("stop_signal_requested", reason=reason if reason in
            {"user", "ui", "shutdown", "exit", "hotkey"} else "other", caller=True)
        self._stop.set()
        self._playback_stop.set()

    def request_stop_for_ui(self, *, engine_running: bool) -> None:
        self.request_stop("ui")
        if not engine_running:
            self._avatar.stop()


__all__ = ["AvatarShutdown", "ProductionShutdownOwner", "StopSignal"]
