from __future__ import annotations

import copy
import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from typing import Any


GENERATION_STATE_SCHEMA_VERSION = 1
GENERATION_STATUSES = frozenset(
    {"pending", "running", "complete", "stale", "failed", "cancelled"}
)


def artifact_signature(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def generation_checkpoint(status: str = "pending") -> dict[str, Any]:
    normalized = status if status in GENERATION_STATUSES else "pending"
    return {
        "status": normalized,
        "input_signature": "",
        "output_signature": "",
        "artifact_ref": "",
        "attempt_count": 0,
        "started_at": None,
        "completed_at": None,
        "updated_at": time.time(),
        "error": "",
        "provider": "",
        "model": "",
    }


def new_generation_state() -> dict[str, Any]:
    return {
        "schema_version": GENERATION_STATE_SCHEMA_VERSION,
        "import": generation_checkpoint(),
        "story_map": generation_checkpoint(),
        "outline": generation_checkpoint(),
        "scenes": {},
        "chapters": {},
        "assembly": generation_checkpoint(),
    }


def _stale(checkpoint: Mapping | None) -> dict[str, Any]:
    result = copy.deepcopy(dict(checkpoint or generation_checkpoint()))
    result["status"] = "stale"
    result["updated_at"] = time.time()
    result["error"] = ""
    return result


def invalidate_generation_state(
    state: Mapping,
    changed_kind: str,
    changed_ids: Sequence[str] = (),
) -> dict[str, Any]:
    result = copy.deepcopy(dict(state or new_generation_state()))
    scenes = result.get("scenes")
    if not isinstance(scenes, Mapping):
        scenes = {}
    result["scenes"] = copy.deepcopy(dict(scenes))
    chapters = result.get("chapters")
    if not isinstance(chapters, Mapping):
        chapters = {}
    result["chapters"] = copy.deepcopy(dict(chapters))
    selected = {str(item) for item in changed_ids if str(item)}
    affected_scenes = selected or set(result["scenes"])
    affected_chapters: set[str] = set()

    if changed_kind == "source":
        result["story_map"] = _stale(result.get("story_map"))
        result["outline"] = _stale(result.get("outline"))
    elif changed_kind == "story_map":
        result["outline"] = _stale(result.get("outline"))
    elif changed_kind not in {"outline", "scene_plan", "scene_prose"}:
        raise ValueError(f"Unknown novel dependency kind: {changed_kind}")

    for scene_id, raw_scene in list(result["scenes"].items()):
        if scene_id not in affected_scenes:
            continue
        scene = copy.deepcopy(dict(raw_scene or {}))
        chapter_id = str(scene.get("chapter_id") or "")
        if chapter_id:
            affected_chapters.add(chapter_id)
        if changed_kind in {"source", "story_map", "outline"}:
            scene["plan"] = _stale(scene.get("plan"))
            scene["prose"] = _stale(scene.get("prose"))
        elif changed_kind == "scene_plan":
            scene["prose"] = _stale(scene.get("prose"))
        result["scenes"][scene_id] = scene

    if changed_kind == "scene_prose" and selected:
        for scene_id in selected:
            scene = result["scenes"].get(scene_id)
            if isinstance(scene, Mapping):
                chapter_id = str(scene.get("chapter_id") or "")
                if chapter_id:
                    affected_chapters.add(chapter_id)

    if changed_kind in {"source", "story_map"} and not selected:
        affected_chapters.update(str(item) for item in result["chapters"])
    for chapter_id in affected_chapters:
        if chapter_id in result["chapters"]:
            result["chapters"][chapter_id] = _stale(
                result["chapters"].get(chapter_id)
            )
    result["assembly"] = _stale(result.get("assembly"))
    return result


def merge_partial_story_maps(partials: Sequence[Mapping]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": 1,
        "characters": [],
        "relationships": [],
        "events": [],
        "locations": [],
        "objects": [],
        "themes": [],
        "candidate_scenes": [],
        "contradictions": [],
    }
    characters: dict[str, dict[str, Any]] = {}
    character_aliases: dict[str, str] = {}
    for partial in partials:
        source = dict(partial or {})
        for raw_character in source.get("characters") or ():
            if not isinstance(raw_character, Mapping):
                continue
            character = copy.deepcopy(dict(raw_character))
            name = str(
                character.get("name")
                or character.get("display_name")
                or character.get("id")
                or ""
            ).strip()
            if not name:
                continue
            raw_aliases = _unique_text(character.get("aliases") or ())
            identity_keys = [
                _entity_key(value) for value in (name, *raw_aliases) if value
            ]
            key = next(
                (
                    character_aliases[identity_key]
                    for identity_key in identity_keys
                    if identity_key in character_aliases
                ),
                _entity_key(name),
            )
            existing = characters.get(key)
            if existing is None:
                existing = {
                    "character_id": str(character.get("character_id") or f"character-{key}"),
                    "name": name,
                    "aliases": [],
                    "summary": str(character.get("summary") or ""),
                    "source_record_ids": [],
                }
                characters[key] = existing
            merged_aliases = list(existing.get("aliases") or ()) + raw_aliases
            if _entity_key(name) != _entity_key(existing.get("name")):
                merged_aliases.append(name)
            existing["aliases"] = _unique_text(
                merged_aliases
            )
            existing["source_record_ids"] = _unique_text(
                list(existing.get("source_record_ids") or ())
                + list(character.get("source_record_ids") or ())
            )
            if not existing.get("summary") and character.get("summary"):
                existing["summary"] = str(character.get("summary"))
            for identity in (
                str(existing.get("name") or ""),
                *list(existing.get("aliases") or ()),
            ):
                normalized_identity = _entity_key(identity)
                if normalized_identity:
                    character_aliases[normalized_identity] = key
        for key in (
            "relationships",
            "events",
            "locations",
            "objects",
            "themes",
            "candidate_scenes",
            "contradictions",
        ):
            result[key] = _unique_json_items(
                list(result[key]) + list(source.get(key) or ())
            )
    result["characters"] = list(characters.values())
    return result


def normalize_outline(value: Mapping, *, revision: int = 0) -> dict[str, Any]:
    source = dict(value or {})
    normalized_chapters: list[dict[str, Any]] = []
    used_chapter_ids: set[str] = set()
    used_scene_ids: set[str] = set()
    raw_chapters = source.get("chapters")
    for chapter_index, raw_chapter in enumerate(
        raw_chapters if isinstance(raw_chapters, (list, tuple)) else (), 1
    ):
        if not isinstance(raw_chapter, Mapping):
            continue
        chapter = dict(raw_chapter)
        title = str(chapter.get("title") or f"Chapter {chapter_index}").strip()
        chapter_id = _stable_outline_id(
            "chapter",
            str(chapter.get("chapter_id") or ""),
            f"{chapter_index}:{title}:{chapter.get('summary', '')}",
            used_chapter_ids,
        )
        scenes: list[dict[str, Any]] = []
        raw_scenes = chapter.get("scenes")
        for scene_index, raw_scene in enumerate(
            raw_scenes if isinstance(raw_scenes, (list, tuple)) else (), 1
        ):
            if not isinstance(raw_scene, Mapping):
                continue
            scene = dict(raw_scene)
            scene_title = str(
                scene.get("title") or f"Scene {scene_index}"
            ).strip()
            scene_id = _stable_outline_id(
                "scene",
                str(scene.get("scene_id") or ""),
                f"{chapter_id}:{scene_index}:{scene_title}:{scene.get('summary', '')}",
                used_scene_ids,
            )
            scenes.append(
                {
                    "scene_id": scene_id,
                    "title": scene_title,
                    "summary": str(scene.get("summary") or "").strip(),
                    "purpose": str(scene.get("purpose") or "").strip(),
                    "pov": str(scene.get("pov") or source.get("pov") or "").strip(),
                    "tense": str(
                        scene.get("tense") or source.get("tense") or ""
                    ).strip(),
                    "characters": _unique_text(scene.get("characters") or ()),
                    "location": str(scene.get("location") or "").strip(),
                    "source_record_ids": _unique_text(
                        scene.get("source_record_ids") or ()
                    ),
                    "continuity_notes": str(
                        scene.get("continuity_notes") or ""
                    ).strip(),
                    "enabled": bool(scene.get("enabled", True)),
                }
            )
        normalized_chapters.append(
            {
                "chapter_id": chapter_id,
                "title": title,
                "summary": str(chapter.get("summary") or "").strip(),
                "enabled": bool(chapter.get("enabled", True)),
                "scenes": scenes,
            }
        )
    approval = str(source.get("approval_status") or "draft").strip().lower()
    if approval not in {"draft", "approved"}:
        approval = "draft"
    return {
        "schema_version": 1,
        "revision": max(0, int(revision)),
        "approval_status": approval,
        "title": str(source.get("title") or "Untitled Novel").strip(),
        "pov": str(source.get("pov") or "").strip(),
        "tense": str(source.get("tense") or "").strip(),
        "chapters": normalized_chapters,
    }


def normalize_scene_plan(
    value: Mapping,
    *,
    chapter_id: str,
    scene: Mapping,
    previous_continuity: Mapping,
    next_intent: str,
) -> dict[str, Any]:
    source = dict(value or {})
    outline_scene = dict(scene or {})
    scene_id = str(outline_scene.get("scene_id") or source.get("scene_id") or "").strip()
    if not scene_id:
        raise ValueError("Scene plan is missing scene_id")
    beats = _unique_text(source.get("beats") or ())
    if not beats:
        raise ValueError(f"Scene plan {scene_id} has no beats")
    return {
        "schema_version": 1,
        "scene_id": scene_id,
        "chapter_id": str(chapter_id),
        "title": str(source.get("title") or outline_scene.get("title") or "Untitled Scene").strip(),
        "purpose": str(source.get("purpose") or outline_scene.get("purpose") or "").strip(),
        "pov": str(source.get("pov") or outline_scene.get("pov") or "").strip(),
        "tense": str(source.get("tense") or outline_scene.get("tense") or "").strip(),
        "characters": _unique_text(
            source.get("characters") or outline_scene.get("characters") or ()
        ),
        "location": str(source.get("location") or outline_scene.get("location") or "").strip(),
        "beats": beats,
        "source_record_ids": _unique_text(
            source.get("source_record_ids")
            or outline_scene.get("source_record_ids")
            or ()
        ),
        "locked_canon": _unique_text(source.get("locked_canon") or ()),
        "previous_continuity": copy.deepcopy(dict(previous_continuity or {})),
        "next_scene_intent": str(next_intent or ""),
        "continuity_updates": copy.deepcopy(
            dict(source.get("continuity_updates") or {})
        ),
    }


def new_continuity_ledger() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "current_locations": {},
        "character_knowledge": {},
        "relationships": {},
        "unresolved_threads": [],
        "important_objects": [],
        "recent_scenes": [],
    }


def update_continuity_ledger(
    ledger: Mapping,
    scene_plan: Mapping,
    prose_summary: str,
) -> dict[str, Any]:
    result = copy.deepcopy(dict(ledger or new_continuity_ledger()))
    updates = dict(scene_plan.get("continuity_updates") or {})
    for key in ("current_locations", "character_knowledge", "relationships"):
        current = result.get(key)
        current = copy.deepcopy(dict(current)) if isinstance(current, Mapping) else {}
        incoming = updates.get(key)
        if isinstance(incoming, Mapping):
            current.update(copy.deepcopy(dict(incoming)))
        result[key] = current
    for key in ("unresolved_threads", "important_objects"):
        result[key] = _unique_text(
            list(result.get(key) or ()) + list(updates.get(key) or ())
        )[-40:]
    recent = list(result.get("recent_scenes") or ())
    recent.append(
        {
            "scene_id": str(scene_plan.get("scene_id") or ""),
            "chapter_id": str(scene_plan.get("chapter_id") or ""),
            "summary": str(prose_summary or "")[:600],
        }
    )
    result["recent_scenes"] = recent[-12:]
    return result


def _entity_key(value: str) -> str:
    normalized = "-".join(str(value).casefold().split())
    safe = "".join(character for character in normalized if character.isalnum() or character == "-")
    return safe or hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]


def _unique_text(values) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _unique_json_items(values) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, (Mapping, str, int, float, bool)):
            continue
        copied = copy.deepcopy(dict(value) if isinstance(value, Mapping) else value)
        signature = artifact_signature(copied)
        if signature not in seen:
            seen.add(signature)
            result.append(copied)
    return result


def _stable_outline_id(
    prefix: str,
    requested: str,
    material: str,
    used: set[str],
) -> str:
    requested_base = _entity_key(requested) if requested.strip() else ""
    base = requested_base or f"{prefix}-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:12]}"
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate
