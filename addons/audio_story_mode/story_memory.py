from __future__ import annotations

import json
import time
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any


MEMORY_VERSION = 1
NEEDS_CLARIFICATION = "Needs clarification"


def empty_story_memory() -> dict[str, Any]:
    return {
        "version": MEMORY_VERSION,
        "characters": {},
        "locations": {},
        "props": {},
        "style": {
            "global_visual_style": "",
            "camera_language": "",
            "color_palette": "",
            "negative_style_rules": [],
        },
        "last_updated": None,
        "recent_scenes": [],
    }


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value) -> list:
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if value:
        return [value]
    return []


def normalize_story_memory(memory: dict | None) -> dict[str, Any]:
    normalized = empty_story_memory()
    source = _as_dict(memory)
    normalized["version"] = MEMORY_VERSION
    normalized["characters"] = _as_dict(source.get("characters"))
    normalized["locations"] = _as_dict(source.get("locations"))
    normalized["props"] = _as_dict(source.get("props"))
    style = _as_dict(source.get("style"))
    normalized["style"].update(
        {
            "global_visual_style": str(style.get("global_visual_style", "") or "").strip(),
            "camera_language": str(style.get("camera_language", "") or "").strip(),
            "color_palette": str(style.get("color_palette", "") or "").strip(),
            "negative_style_rules": [str(item or "").strip() for item in _as_list(style.get("negative_style_rules")) if str(item or "").strip()],
        }
    )
    normalized["last_updated"] = source.get("last_updated")
    normalized["recent_scenes"] = [dict(item) for item in _as_list(source.get("recent_scenes")) if isinstance(item, dict)][-24:]
    return normalized


class StoryMemoryStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return empty_story_memory()
        try:
            return normalize_story_memory(json.loads(self.path.read_text(encoding="utf-8")))
        except Exception:
            return empty_story_memory()

    def save(self, memory: dict[str, Any]) -> None:
        payload = normalize_story_memory(memory)
        payload["last_updated"] = time.time()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _is_clear_value(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text and text.lower() not in {"needs clarification", "unknown", "unclear", "n/a", "none"})


def _merge_text_field(existing: str, incoming: str, *, existing_confidence: float, incoming_confidence: float) -> str:
    existing = str(existing or "").strip()
    incoming = str(incoming or "").strip()
    if not _is_clear_value(incoming):
        return existing or incoming
    if not _is_clear_value(existing):
        return incoming
    if incoming == existing:
        return existing
    if incoming_confidence > existing_confidence + 0.15 and len(incoming) >= max(8, int(len(existing) * 0.6)):
        return incoming
    return existing


def _merge_unique_list(existing, incoming) -> list[str]:
    result = []
    seen = set()
    for item in [*_as_list(existing), *_as_list(incoming)]:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result


def merge_story_memory(memory: dict[str, Any], update: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    merged = normalize_story_memory(deepcopy(memory))
    update = _as_dict(update)
    changed = False

    for section, fields in (
        (
            "characters",
            [
                "display_name",
                "visual_identity",
                "face",
                "hair",
                "eyes",
                "body",
                "clothing",
                "unique_markers",
                "personality_impression",
            ],
        ),
        ("locations", ["display_name", "visual_description", "mood"]),
        ("props", ["display_name", "visual_description", "mood"]),
    ):
        target = merged.setdefault(section, {})
        for key, incoming_entry in _as_dict(update.get(section)).items():
            key = str(key or "").strip()
            if not key:
                continue
            incoming_entry = _as_dict(incoming_entry)
            existing = dict(target.get(key) or {})
            before = deepcopy(existing)
            existing_conf = float(existing.get("confidence", 0.0) or 0.0)
            incoming_conf = float(incoming_entry.get("confidence", 0.0) or 0.0)
            for field in fields:
                existing[field] = _merge_text_field(
                    existing.get(field, ""),
                    incoming_entry.get(field, ""),
                    existing_confidence=existing_conf,
                    incoming_confidence=incoming_conf,
                )
            if section == "characters":
                existing["aliases"] = _merge_unique_list(existing.get("aliases"), incoming_entry.get("aliases"))
                existing["do_not_change"] = _merge_unique_list(existing.get("do_not_change"), incoming_entry.get("do_not_change"))
                if incoming_entry.get("first_seen_chunk") is not None and existing.get("first_seen_chunk") is None:
                    existing["first_seen_chunk"] = incoming_entry.get("first_seen_chunk")
                if incoming_entry.get("last_seen_chunk") is not None:
                    existing["last_seen_chunk"] = incoming_entry.get("last_seen_chunk")
            if section == "locations":
                existing["recurring_details"] = _merge_unique_list(existing.get("recurring_details"), incoming_entry.get("recurring_details"))
            existing["confidence"] = max(existing_conf, incoming_conf)
            target[key] = existing
            changed = changed or existing != before

    style_update = _as_dict(update.get("style"))
    style = dict(merged.get("style") or {})
    before_style = deepcopy(style)
    style_conf = float(style.get("confidence", 0.0) or 0.0)
    incoming_style_conf = float(style_update.get("confidence", 0.0) or 0.0)
    for field in ("global_visual_style", "camera_language", "color_palette"):
        style[field] = _merge_text_field(
            style.get(field, ""),
            style_update.get(field, ""),
            existing_confidence=style_conf,
            incoming_confidence=incoming_style_conf,
        )
    style["negative_style_rules"] = _merge_unique_list(style.get("negative_style_rules"), style_update.get("negative_style_rules"))
    merged["style"] = style
    changed = changed or style != before_style

    scenes = [dict(item) for item in _as_list(merged.get("recent_scenes")) if isinstance(item, dict)]
    for scene in _as_list(update.get("recent_scenes")):
        if isinstance(scene, dict):
            scenes.append(dict(scene))
            changed = True
    merged["recent_scenes"] = scenes[-24:]
    if changed:
        merged["last_updated"] = time.time()
    return merged, changed


def merge_committed_story_bible(
    existing: Mapping,
    chapter_update: Mapping,
) -> dict[str, Any]:
    """Return a defensively merged project Story Bible without mutating inputs."""
    if not isinstance(existing, Mapping):
        raise TypeError("Existing Story Bible must be a mapping")
    if not isinstance(chapter_update, Mapping):
        raise TypeError("Chapter Story Bible update must be a mapping")
    existing_copy = deepcopy(dict(existing))
    update_copy = deepcopy(dict(chapter_update))
    merged, _changed = merge_story_memory(existing_copy, update_copy)
    incoming_updated = update_copy.get("last_updated")
    merged["last_updated"] = (
        incoming_updated
        if incoming_updated is not None
        else normalize_story_memory(existing_copy).get("last_updated")
    )
    return merged
