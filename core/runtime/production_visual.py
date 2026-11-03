from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol


class EventState(Protocol):
    def is_set(self) -> bool: ...


class VisualPublicationNotices(Protocol):
    def publish(self, message: str) -> None: ...


@dataclass(frozen=True, slots=True)
class ConsoleVisualPublicationNotices:
    def publish(self, message: str) -> None:
        print(message)


class ProductionVisualReplyPublicationGate:
    """Reject stale Visual Reply publication without delaying it behind speech."""

    __slots__ = (
        "_notices",
        "_stop_requested",
    )

    def __init__(
        self,
        *,
        stop_requested: EventState,
        audio_playing: EventState,
        environ: Mapping[str, str] | None = None,
        notices: VisualPublicationNotices | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        # Retain these constructor parameters while existing composition callers
        # migrate away from the former speech-idle publication policy.
        del audio_playing, environ, clock, sleep
        self._stop_requested = stop_requested
        self._notices = notices or ConsoleVisualPublicationNotices()

    def allow(self, payload: Mapping[str, Any] | None = None) -> bool:
        request = dict(payload or {})
        cancelled = request.get("cancelled")
        if callable(cancelled) and cancelled():
            self._notices.publish(
                "[VisualReply] Generation cancelled before publication."
            )
            return False
        if self._stop_requested.is_set():
            self._notices.publish(
                "[VisualReply] Generation cancelled during shutdown."
            )
            return False
        # A completed image is independent of the speech playback route. Publish
        # it immediately so it can appear while the associated reply is spoken.
        return True


__all__ = [
    "ConsoleVisualPublicationNotices",
    "EventState",
    "ProductionVisualReplyPublicationGate",
    "VisualPublicationNotices",
]
