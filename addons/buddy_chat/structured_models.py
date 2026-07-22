from __future__ import annotations

import re
from typing import Any

from .models import BuddyPersona, normalize_persona_id


INSTRUCTOR_SETTING_DEFAULTS: dict[str, bool] = {
    "buddy_chat_instructor_structured_outputs_enabled": False,
}


try:
    from pydantic import BaseModel, Field

    try:
        from pydantic import ConfigDict
    except Exception:  # pragma: no cover - pydantic v1 compatibility
        ConfigDict = None  # type: ignore[assignment]

    PYDANTIC_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency fallback
    BaseModel = object  # type: ignore[assignment,misc]
    Field = None  # type: ignore[assignment]
    ConfigDict = None  # type: ignore[assignment]
    PYDANTIC_AVAILABLE = False


if PYDANTIC_AVAILABLE:
    if ConfigDict is not None:

        class _BuddyStructuredModel(BaseModel):  # type: ignore[misc]
            model_config = ConfigDict(extra="ignore")

    else:

        class _BuddyStructuredModel(BaseModel):  # type: ignore[misc]
            class Config:
                extra = "ignore"


    class BuddyReplySegment(_BuddyStructuredModel):
        persona_id: str = ""
        display_name: str = ""
        text: str = ""
        emotion: str = ""


    class StructuredBuddyReply(_BuddyStructuredModel):
        schema_version: str = "buddy_chat.reply.v1"
        segments: list[BuddyReplySegment] = Field(default_factory=list)  # type: ignore[misc]

else:
    BuddyReplySegment = None  # type: ignore[assignment]
    StructuredBuddyReply = None  # type: ignore[assignment]


def structured_feature_enabled(settings: Any, feature_key: str = "buddy_chat_instructor_structured_outputs_enabled") -> bool:
    key = str(feature_key or "").strip()
    if not key:
        return False
    if isinstance(settings, dict):
        value = settings.get(key, INSTRUCTOR_SETTING_DEFAULTS.get(key, False))
    else:
        attr = "instructor_structured_outputs_enabled" if key == "buddy_chat_instructor_structured_outputs_enabled" else key
        value = getattr(settings, attr, INSTRUCTOR_SETTING_DEFAULTS.get(key, False))
    return bool(value)


def model_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    dumper = getattr(value, "model_dump", None)
    if callable(dumper):
        dumped = dumper(exclude_none=True)
        return dict(dumped or {}) if isinstance(dumped, dict) else {}
    dumper = getattr(value, "dict", None)
    if callable(dumper):
        dumped = dumper(exclude_none=True)
        return dict(dumped or {}) if isinstance(dumped, dict) else {}
    return {}


def sanitize_structured_buddy_reply(
    payload: dict[str, Any] | None,
    *,
    personas: list[BuddyPersona],
    max_speakers: int = 1,
    allowed_persona_ids: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"schema_version": "buddy_chat.reply.v1", "segments": []}
    lookup = _persona_lookup(personas)
    allowed = {normalize_persona_id(item) for item in set(allowed_persona_ids or set()) if str(item or "").strip()}
    speaker_limit = max(1, min(4, int(max_speakers or 1)))
    segments: list[dict[str, str]] = []
    seen_speakers: set[str] = set()
    for item in _segment_values(payload):
        if not isinstance(item, dict):
            continue
        persona = _resolve_persona(item, lookup)
        if persona is None:
            continue
        persona_id = normalize_persona_id(persona.id)
        if allowed and persona_id not in allowed:
            continue
        text = _clean_segment_text(item, persona, lookup)
        if not text:
            continue
        if persona_id not in seen_speakers:
            if len(seen_speakers) >= speaker_limit:
                continue
            seen_speakers.add(persona_id)
        segments.append(
            {
                "persona_id": persona_id,
                "display_name": str(persona.display_name or persona.id or "Buddy").strip() or "Buddy",
                "text": text,
            }
        )
        if len(segments) >= 8:
            break
    schema_version = _compact(payload.get("schema_version") or "buddy_chat.reply.v1", 60) or "buddy_chat.reply.v1"
    return {"schema_version": schema_version, "segments": segments}


def structured_buddy_reply_to_text(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    lines: list[str] = []
    for item in list(payload.get("segments") or []):
        if not isinstance(item, dict):
            continue
        name = _compact(item.get("display_name"), 80)
        text = _compact(item.get("text"), 1200)
        if name and text:
            lines.append(f"[{name}] {text}")
    return "\n\n".join(lines).strip()


def _persona_lookup(personas: list[BuddyPersona]) -> dict[str, BuddyPersona]:
    lookup: dict[str, BuddyPersona] = {}
    for persona in list(personas or []):
        if not bool(getattr(persona, "enabled", True)):
            continue
        display_name = str(getattr(persona, "display_name", "") or "").strip()
        keys = {
            normalize_persona_id(getattr(persona, "id", "")),
            _label_key(display_name),
            _label_key(display_name.split(",", 1)[0]),
        }
        for key in keys:
            if key:
                lookup[key] = persona
    return lookup


def _resolve_persona(item: dict[str, Any], lookup: dict[str, BuddyPersona]) -> BuddyPersona | None:
    for key in ("persona_id", "speaker_id", "id", "display_name", "name", "speaker"):
        value = str(item.get(key) or "").strip()
        if not value:
            continue
        candidate = lookup.get(normalize_persona_id(value)) or lookup.get(_label_key(value))
        if candidate is not None:
            return candidate
    return None


def _clean_segment_text(item: dict[str, Any], persona: BuddyPersona, lookup: dict[str, BuddyPersona]) -> str:
    text = _compact(item.get("text") or item.get("content") or item.get("spoken_text") or item.get("message"), 1200)
    if not text:
        return ""
    for _index in range(3):
        stripped = _strip_known_speaker_prefix(text, persona, lookup)
        if stripped == text:
            break
        if not stripped:
            return ""
        text = stripped
    return text


def _strip_known_speaker_prefix(text: str, persona: BuddyPersona, lookup: dict[str, BuddyPersona]) -> str:
    bracket = re.match(r"^\s*\[([^\]]{1,80})\]\s*(.+?)\s*$", text, flags=re.DOTALL)
    if bracket:
        return _strip_if_matching_persona(bracket.group(1), bracket.group(2), persona, lookup)
    colon = re.match(r"^\s*([A-Za-z][A-Za-z0-9 _',.-]{1,80})\s*:\s*(.+?)\s*$", text, flags=re.DOTALL)
    if colon:
        return _strip_if_matching_persona(colon.group(1), colon.group(2), persona, lookup)
    return text


def _strip_if_matching_persona(label: str, body: str, persona: BuddyPersona, lookup: dict[str, BuddyPersona]) -> str:
    matched = lookup.get(normalize_persona_id(label)) or lookup.get(_label_key(label))
    if matched is None:
        return ""
    if normalize_persona_id(matched.id) != normalize_persona_id(persona.id):
        return ""
    return _compact(body, 1200)


def _segment_values(payload: dict[str, Any]) -> list[Any]:
    for key in ("segments", "replies", "messages", "lines"):
        value = payload.get(key)
        if isinstance(value, list):
            return list(value)
    return []


def _label_key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _compact(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    maximum = max(0, int(limit or 0))
    if len(text) <= maximum:
        return text
    if maximum <= 3:
        return text[:maximum]
    return text[: maximum - 3].rstrip() + "..."


__all__ = [
    "BuddyReplySegment",
    "INSTRUCTOR_SETTING_DEFAULTS",
    "PYDANTIC_AVAILABLE",
    "StructuredBuddyReply",
    "model_to_dict",
    "sanitize_structured_buddy_reply",
    "structured_buddy_reply_to_text",
    "structured_feature_enabled",
]
