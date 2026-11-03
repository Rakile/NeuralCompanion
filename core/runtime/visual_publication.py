"""Cancellation-aware publication gating for generated Visual Reply assets."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import time


class VisualPublicationGate:
    """Delay image publication during speech without losing cancellation authority."""

    def __init__(
        self,
        *,
        audio_active: Callable[[], bool],
        shutdown_requested: Callable[[], bool],
        max_wait_seconds: float = 300.0,
        poll_seconds: float = 0.1,
        clock=time.monotonic,
        sleep=time.sleep,
        logger: Callable[[str], object] | None = None,
    ) -> None:
        self._audio_active = audio_active
        self._shutdown_requested = shutdown_requested
        self._max_wait_seconds = max(0.0, float(max_wait_seconds))
        self._poll_seconds = max(0.001, float(poll_seconds))
        self._clock = clock
        self._sleep = sleep
        self._logger = logger

    def allow(self, payload: Mapping[str, object] | None = None) -> bool:
        request = dict(payload or {})
        cancelled = request.get("cancelled")
        started_at: float | None = None
        logged_wait = False
        while True:
            if callable(cancelled) and cancelled():
                self._log("[VisualReply] Generation cancelled before publication.")
                return False
            if self._shutdown_requested():
                self._log("[VisualReply] Generation cancelled during shutdown.")
                return False
            if not self._audio_active():
                if logged_wait and started_at is not None:
                    self._log(
                        "[VisualReply] Publish gate released after "
                        f"{self._clock() - started_at:.1f}s."
                    )
                return True
            if started_at is None:
                started_at = float(self._clock())
            if not logged_wait:
                self._log(
                    "[VisualReply] Waiting for current vocalization to finish before "
                    "publishing generated image."
                )
                logged_wait = True
            if (
                self._max_wait_seconds
                and float(self._clock()) - started_at >= self._max_wait_seconds
            ):
                self._log(
                    "[VisualReply] Publish gate timed out; publishing generated image "
                    "anyway."
                )
                return True
            self._sleep(self._poll_seconds)

    def _log(self, message: str) -> None:
        if self._logger is not None:
            self._logger(message)


__all__ = ["VisualPublicationGate"]
