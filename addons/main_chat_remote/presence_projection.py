"""Addon-local projection of NeuralCompanion state for phone clients.

This module deliberately depends only on plain snapshots supplied by the Main
Chat Remote addon.  It does not import or mutate NC core/runtime components.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import secrets
import time
from typing import Any, Callable, Mapping


_IMAGE_EXTENSIONS = {".jpeg", ".jpg", ".png", ".webp"}
_MOOD_TAG_PATTERN = re.compile(r"\[([A-Za-z][A-Za-z0-9_-]{0,31})\]")
_HEALTHY_MUSETALK_STATES = {
    "active",
    "idle",
    "planned",
    "ready",
    "rendering",
    "streaming",
    "transition",
}


@dataclass(frozen=True, slots=True)
class PresenceProjection:
    """Public Presence payload plus its validated still-image fallback."""

    payload: dict[str, Any]
    avatar_path: Path | None


@dataclass(frozen=True, slots=True)
class MessagePersonaProjection:
    """Stable identity attached to one assistant chat turn."""

    display_name: str
    initials: str
    mood: str
    avatar_path: Path | None
    neutral_avatar_path: Path | None
    mood_avatar_paths: dict[str, Path]


class PhonePresenceProjector:
    """Build a compact, revisioned Presence contract for the phone remote."""

    def __init__(self, app_root: Path, *, clock: Callable[[], float] = time.time) -> None:
        self._app_root = Path(app_root).resolve()
        self._persona_catalog_path = self._app_root / "runtime" / "quick_personas.json"
        self._persona_asset_root = (self._app_root / "runtime" / "quick_personas").resolve()
        self._clock = clock
        self._stream_id = secrets.token_hex(8)
        self._revision = 0
        self._semantic_state = ""
        self._catalog_mtime_ns: int | None = None
        self._catalog_checked_mtime_ns: int | None = None
        self._catalog: dict[str, Any] = {}

    def project(
        self,
        *,
        runtime_status: Mapping[str, Any] | None,
        visual_presence: Mapping[str, Any] | None,
        media: Mapping[str, Any] | None,
        musetalk: Mapping[str, Any] | None,
        portrait_playback: Mapping[str, str] | None = None,
    ) -> PresenceProjection:
        """Project existing addon snapshots without changing their producers."""

        runtime = _mapping(runtime_status)
        visual = _mapping(visual_presence)
        media_snapshot = _mapping(media)
        musetalk_snapshot = _mapping(musetalk)
        self._refresh_catalog()

        persona = self._active_persona()
        mood = self._live_mood(visual, media_snapshot)
        avatar_path, still_kind = self._persona_avatar(persona, mood)
        activity = self._activity(runtime, visual)
        musetalk_available = bool(musetalk_snapshot.get("available", False))
        musetalk_healthy = self._musetalk_healthy(musetalk_snapshot)
        avatar_kind = "musetalk" if musetalk_healthy else still_kind

        semantic_payload: dict[str, Any] = {
            "schema_version": 1,
            "stream_id": self._stream_id,
            "activity": activity,
            "state_label": self._state_label(activity, runtime),
            "audio_level": _clamp_unit(visual.get("audio_level", 0.0)),
            "mood": mood,
            "persona": {
                "id": persona["id"],
                "name": persona["name"],
                "initials": persona["initials"],
            },
            "avatar": {"kind": avatar_kind, "mood": mood},
            "musetalk": {
                "available": musetalk_available,
                "healthy": musetalk_healthy,
            },
        }
        if portrait_playback:
            semantic_payload["portrait_playback"] = dict(portrait_playback)
        semantic_state = json.dumps(semantic_payload, sort_keys=True, separators=(",", ":"))
        if semantic_state != self._semantic_state:
            self._semantic_state = semantic_state
            self._revision += 1

        payload = dict(semantic_payload)
        payload["revision"] = self._revision
        payload["updated_at"] = float(self._clock())
        return PresenceProjection(payload=payload, avatar_path=avatar_path)

    def message_persona(self, turn: Mapping[str, Any] | None) -> MessagePersonaProjection:
        """Resolve the persona and first supported portrait tag for a chat turn."""

        self._refresh_catalog()
        turn_snapshot = _mapping(turn)
        attribution = _mapping(turn_snapshot.get("quick_persona"))
        persona = self._find_persona(attribution) or self._active_persona()
        mood_paths = {
            _normalize_mood(name): path
            for name, value in _mapping(persona.get("mood_images")).items()
            if (path := self._resolve_avatar_path(value)) is not None
        }
        mood = _first_mood_tag(str(turn_snapshot.get("content") or ""), mood_paths) or "neutral"
        avatar_path, _kind = self._persona_avatar(persona, mood)
        neutral_avatar_path = self._resolve_avatar_path(persona.get("avatar_path"))
        return MessagePersonaProjection(
            display_name=persona["name"],
            initials=persona["initials"],
            mood=mood,
            avatar_path=avatar_path,
            neutral_avatar_path=neutral_avatar_path,
            mood_avatar_paths=mood_paths,
        )

    def _refresh_catalog(self) -> None:
        try:
            modified_ns = self._persona_catalog_path.stat().st_mtime_ns
        except OSError:
            return
        if modified_ns == self._catalog_checked_mtime_ns:
            return
        self._catalog_checked_mtime_ns = modified_ns
        try:
            loaded = json.loads(self._persona_catalog_path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict) or not isinstance(loaded.get("personas"), dict):
                return
        except (OSError, UnicodeError, json.JSONDecodeError):
            return
        self._catalog = loaded
        self._catalog_mtime_ns = modified_ns

    def _active_persona(self) -> dict[str, Any]:
        personas = _mapping(self._catalog.get("personas"))
        active_slot = str(self._catalog.get("active_slot", 0))
        raw = _mapping(personas.get(active_slot))
        if not raw and personas:
            raw = _mapping(next(iter(personas.values())))
        return self._normalize_persona(raw)

    def _find_persona(self, attribution: Mapping[str, Any]) -> dict[str, Any] | None:
        if not attribution:
            return None
        target_id = str(attribution.get("id") or "").strip().casefold()
        target_name = str(attribution.get("name") or "").strip().casefold()
        target_avatar = str(attribution.get("avatar_path") or "").strip().replace("\\", "/").casefold()
        for raw in _mapping(self._catalog.get("personas")).values():
            candidate = _mapping(raw)
            if target_id and str(candidate.get("id") or "").strip().casefold() == target_id:
                return self._normalize_persona(candidate)
            if target_avatar and str(candidate.get("avatar_path") or "").strip().replace("\\", "/").casefold() == target_avatar:
                return self._normalize_persona(candidate)
            if target_name and str(candidate.get("name") or "").strip().casefold() == target_name:
                return self._normalize_persona(candidate)
        return None

    @staticmethod
    def _normalize_persona(raw: Mapping[str, Any]) -> dict[str, Any]:
        persona_id = str(raw.get("id") or "companion").strip() or "companion"
        name = str(raw.get("name") or "Companion").strip() or "Companion"
        words = [word for word in name.split() if word]
        initials = "".join(word[0].upper() for word in words[:2]) or "C"
        return {
            "id": persona_id,
            "name": name,
            "initials": initials,
            "avatar_path": raw.get("avatar_path"),
            "mood_images": dict(_mapping(raw.get("mood_images"))),
        }

    def _persona_avatar(self, persona: Mapping[str, Any], mood: str) -> tuple[Path | None, str]:
        mood_path = _mapping(persona.get("mood_images")).get(mood)
        resolved_mood = self._resolve_avatar_path(mood_path)
        if resolved_mood is not None:
            return resolved_mood, "mood"
        resolved_neutral = self._resolve_avatar_path(persona.get("avatar_path"))
        if resolved_neutral is not None:
            return resolved_neutral, "neutral"
        return None, "initials"

    def _resolve_avatar_path(self, candidate: Any) -> Path | None:
        raw = str(candidate or "").strip()
        if not raw:
            return None
        path = Path(raw)
        resolved = (path if path.is_absolute() else self._app_root / path).resolve()
        try:
            resolved.relative_to(self._persona_asset_root)
        except ValueError:
            return None
        if resolved.suffix.casefold() not in _IMAGE_EXTENSIONS or not resolved.is_file():
            return None
        return resolved

    @staticmethod
    def _live_mood(visual: Mapping[str, Any], media: Mapping[str, Any]) -> str:
        mood = _normalize_mood(visual.get("mood"))
        if mood != "neutral" or visual.get("mood"):
            return mood
        items = media.get("items")
        if isinstance(items, list):
            for item in reversed(items):
                emotion = _normalize_mood(_mapping(item).get("emotion"))
                if emotion != "neutral":
                    return emotion
        return "neutral"

    @staticmethod
    def _activity(runtime: Mapping[str, Any], visual: Mapping[str, Any]) -> str:
        lifecycle = str(runtime.get("lifecycle_state") or runtime.get("status") or "").strip().casefold()
        if runtime.get("provider_failure") or lifecycle in {"error", "failed", "failure"}:
            return "failure"
        if not bool(runtime.get("running", False)):
            return "stopped"
        ai_state = str(visual.get("ai_state") or "").strip().casefold()
        runtime_activity = str(runtime.get("activity") or "").strip().casefold()
        combined = {ai_state, runtime_activity}
        if "speaking" in combined:
            return "speaking"
        if "thinking" in combined or "generating" in combined:
            return "thinking"
        if combined.intersection({"listening", "recording", "transcribing"}):
            return "listening"
        return "ready"

    def _musetalk_healthy(self, musetalk: Mapping[str, Any]) -> bool:
        if not bool(musetalk.get("available", False)):
            return False
        state = _mapping(musetalk.get("state"))
        status = str(state.get("status") or "").strip().casefold()
        if status in {"error", "failed", "stopped", "unavailable"}:
            return False
        frames = musetalk.get("frames")
        pipeline = _mapping(musetalk.get("pipeline"))
        renderable = bool(
            musetalk.get("renderable")
            or
            (isinstance(frames, list) and frames)
            or state.get("frame_url_path")
            or state.get("frame_path")
            or state.get("frame_paths")
            or status in {"active", "rendering", "streaming"}
        )
        timestamps: list[float] = []
        for value in (state.get("updated_at"), state.get("sync_time"), pipeline.get("updated_at")):
            try:
                numeric = float(value or 0.0)
            except (TypeError, ValueError):
                continue
            if numeric > 0:
                timestamps.append(numeric)
        updated_at = max(timestamps, default=0.0)
        age = max(0.0, float(self._clock()) - updated_at)
        active = bool(pipeline.get("active")) or status in _HEALTHY_MUSETALK_STATES
        return renderable and active and updated_at > 0 and age <= 3.0

    @staticmethod
    def _state_label(activity: str, runtime: Mapping[str, Any]) -> str:
        labels = {
            "stopped": "Runtime stopped",
            "listening": "Listening",
            "thinking": "Thinking",
            "speaking": "Speaking",
            "failure": "Runtime failure",
            "ready": "Ready",
        }
        if runtime.get("provider_failure"):
            return "Provider failure"
        return labels.get(activity, "Ready")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _normalize_mood(value: Any) -> str:
    normalized = str(value or "").strip().casefold().replace(" ", "_")
    if not normalized or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", normalized):
        return "neutral"
    return normalized


def _first_mood_tag(content: str, mood_paths: Mapping[str, Path]) -> str | None:
    for tag in _MOOD_TAG_PATTERN.findall(content):
        mood = _normalize_mood(tag)
        if mood == "neutral" or mood in mood_paths:
            return mood
    return None


def _clamp_unit(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))
