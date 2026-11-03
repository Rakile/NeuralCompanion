from __future__ import annotations

import threading
import time
from typing import Final


PIPELINE_STEPS: Final[tuple[tuple[str, str], ...]] = (
    ("capture", "Capture"),
    ("lfm", "Vision analysis"),
    ("main_chat", "Main Chat"),
    ("tts", "TTS / Orb"),
)

_STAGE_COLORS: Final[dict[str, str]] = {
    "idle": "#64748b",
    "capture": "#38bdf8",
    "lfm_analysis": "#22d3ee",
    "main_chat": "#a78bfa",
    "tts": "#34d399",
    "complete": "#34d399",
    "error": "#fb7185",
}


class VisionPipelineTracker:
    """Thread-safe, sanitized presentation state for one Orb visual action."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._revision = 0
        self._stage = "idle"
        self._scope = ""
        self._route = ""
        self._cache = ""
        self._updated_at = 0.0

    def transition(
        self,
        stage: str,
        *,
        scope: str = "",
        route: str = "",
        cache: str = "",
        error: str = "",
    ) -> dict[str, object]:
        del error  # Never retain provider errors or private guidance in UI state.
        normalized = str(stage or "idle").strip().lower()
        if normalized not in _STAGE_COLORS:
            normalized = "error"
        with self._lock:
            if normalized == "capture":
                self._scope = str(scope or "").strip().lower()
                self._route = str(route or "").strip().lower()
                self._cache = ""
            else:
                if scope:
                    self._scope = str(scope).strip().lower()
                if route:
                    self._route = str(route).strip().lower()
                if cache:
                    self._cache = str(cache).strip().lower()
            self._stage = normalized
            self._revision += 1
            self._updated_at = time.monotonic()
            return self._snapshot_locked()

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return self._snapshot_locked()

    def observe_ai_state(self, state: str) -> dict[str, object]:
        """Advance only an already-active visual response through speech."""

        normalized = str(state or "idle").strip().lower()
        with self._lock:
            if self._stage == "main_chat" and normalized == "speaking":
                self._stage = "tts"
                self._revision += 1
                self._updated_at = time.monotonic()
            elif self._stage == "tts" and normalized == "idle":
                self._stage = "complete"
                self._revision += 1
                self._updated_at = time.monotonic()
            return self._snapshot_locked()

    def _snapshot_locked(self) -> dict[str, object]:
        route = self._route
        stage = self._stage
        return {
            "revision": self._revision,
            "stage": stage,
            "scope": self._scope,
            "route": route,
            "cache": self._cache,
            "status": self._status_text(stage, route, self._cache),
            "color": _STAGE_COLORS[stage],
            "updated_at": self._updated_at,
            "steps": self._step_states(stage, route),
        }

    @staticmethod
    def _status_text(stage: str, route: str, cache: str) -> str:
        if stage == "idle":
            return "Waiting for a Companion Orb visual action"
        if stage == "capture":
            return "Capturing the selected screen area"
        if stage == "lfm_analysis":
            return "Auxiliary vision is analyzing the selected crop"
        if stage == "main_chat":
            if route == "main_chat_image":
                return "Auxiliary vision bypassed — Main Chat is analyzing the image"
            if route == "main_chat_fallback":
                return "Auxiliary vision unavailable — Main Chat fallback is responding"
            cached = " (cached vision observation)" if cache == "hit" else ""
            return f"Private visual evidence sent — Main Chat is responding{cached}"
        if stage == "tts":
            return "Main Chat response ready — TTS is speaking"
        if stage == "complete":
            return "Orb visual response completed"
        return "Vision guidance failed — Main Chat remains available"

    @staticmethod
    def _step_states(stage: str, route: str) -> tuple[dict[str, str], ...]:
        index = {
            "idle": -1,
            "capture": 0,
            "lfm_analysis": 1,
            "main_chat": 2,
            "tts": 3,
            "complete": 4,
            "error": -1,
        }[stage]
        result: list[dict[str, str]] = []
        for step_index, (step_id, label) in enumerate(PIPELINE_STEPS):
            if step_id == "lfm" and route == "main_chat_fallback":
                state = "error"
            elif step_id == "lfm" and route == "main_chat_image":
                state = "bypassed"
            elif stage == "error":
                state = "error" if step_index == 1 else "pending"
            elif stage == "complete" or step_index < index:
                state = "complete"
            elif step_index == index:
                state = "active"
            else:
                state = "pending"
            result.append({"id": step_id, "label": label, "state": state})
        return tuple(result)
