from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from typing import Any

from addons.audio_story_mode import novel_models


PROMPT_SCHEMA_VERSION = 1
MAX_PROMPT_CHARACTERS = 24_000

STORY_MAP_CONTRACT = {
    "response_type": "json_object",
    "required_arrays": [
        "characters",
        "relationships",
        "events",
        "locations",
        "objects",
        "themes",
        "candidate_scenes",
        "contradictions",
    ],
    "evidence_rule": "Every material fact must include source_record_ids.",
}

OUTLINE_CONTRACT = {
    "response_type": "json_object",
    "required": ["title", "chapters"],
    "chapter_required": ["title", "summary", "scenes"],
    "scene_required": [
        "title",
        "summary",
        "purpose",
        "characters",
        "source_record_ids",
    ],
}

SCENE_PLAN_CONTRACT = {
    "response_type": "json_object",
    "required": [
        "scene_id",
        "chapter_id",
        "title",
        "purpose",
        "pov",
        "tense",
        "characters",
        "location",
        "beats",
        "source_record_ids",
        "locked_canon",
        "continuity_updates",
    ],
}


def adaptation_policy(style: str) -> str:
    normalized = novel_models.normalize_adaptation_style(style)
    if normalized == novel_models.ADAPTATION_STYLE_LIGHTLY_NOVELIZED:
        return (
            "Descriptions and transitions may be added, but material facts, "
            "relationships, and outcomes must remain source-supported."
        )
    if normalized == novel_models.ADAPTATION_STYLE_CREATIVE_FICTION:
        return (
            "Connective events may be invented, but source-supported facts and "
            "explicitly locked canon must not be contradicted."
        )
    return (
        "Use only source-supported material events. Preserve uncertainty and "
        "contradictions instead of inventing resolutions."
    )


def build_story_map_batch_payload(
    *,
    records: Sequence[Mapping[str, Any]],
    continuity: Mapping[str, Any],
    settings: novel_models.FrozenNovelSettings,
) -> dict[str, Any]:
    payload = {
        "schema_version": PROMPT_SCHEMA_VERSION,
        "contract": copy.deepcopy(STORY_MAP_CONTRACT),
        "task": "Extract source-supported story facts and candidate scenes.",
        "adaptation_policy": adaptation_policy(settings.adaptation_style),
        "continuity_context": compact_story_context(continuity),
        "source_records": [bounded_source_record(record) for record in records],
        "novel_instructions": settings.novel_instructions,
        "user_guidance": settings.prompt_additions.get("story_map", ""),
    }
    _require_bounded(payload)
    return payload


def build_outline_payload(
    *,
    story_map: Mapping[str, Any],
    settings: novel_models.FrozenNovelSettings,
) -> dict[str, Any]:
    payload = {
        "schema_version": PROMPT_SCHEMA_VERSION,
        "contract": copy.deepcopy(OUTLINE_CONTRACT),
        "task": "Propose an editable chapter and scene outline. Do not write prose.",
        "adaptation_policy": adaptation_policy(settings.adaptation_style),
        "story_map": compact_story_context(story_map, for_outline=True),
        "novel_instructions": settings.novel_instructions,
        "user_guidance": settings.prompt_additions.get("outline", ""),
    }
    _require_bounded(payload)
    return payload


def build_scene_plan_payload(
    *,
    scene: Mapping[str, Any],
    source_records: Sequence[Mapping[str, Any]],
    story_map: Mapping[str, Any],
    continuity: Mapping[str, Any],
    next_intent: str,
    settings: novel_models.FrozenNovelSettings,
) -> dict[str, Any]:
    payload = {
        "schema_version": PROMPT_SCHEMA_VERSION,
        "contract": copy.deepcopy(SCENE_PLAN_CONTRACT),
        "task": "Create a structured scene plan. Do not write prose.",
        "adaptation_policy": adaptation_policy(settings.adaptation_style),
        "scene": copy.deepcopy(dict(scene)),
        "source_records": [bounded_source_record(item) for item in source_records],
        "story_context": compact_story_context(story_map),
        "continuity_context": copy.deepcopy(dict(continuity or {})),
        "next_scene_intent": str(next_intent or ""),
        "novel_instructions": settings.novel_instructions,
        "user_guidance": settings.prompt_additions.get("scene_plan", ""),
    }
    _require_bounded(payload)
    return payload


def build_prose_payload(
    *,
    scene_plan: Mapping[str, Any],
    settings: novel_models.FrozenNovelSettings,
) -> dict[str, Any]:
    payload = {
        "schema_version": PROMPT_SCHEMA_VERSION,
        "contract": {
            "response_type": "plain_text",
            "rule": "Return scene prose only, without JSON or commentary.",
        },
        "task": "Write polished prose from the approved structured scene plan.",
        "adaptation_policy": adaptation_policy(settings.adaptation_style),
        "scene_plan": copy.deepcopy(dict(scene_plan)),
        "novel_instructions": settings.novel_instructions,
        "user_guidance": settings.prompt_additions.get("prose", ""),
    }
    _require_bounded(payload)
    return payload


def build_json_repair_payload(
    *,
    raw_response: Any,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    payload = {
        "schema_version": PROMPT_SCHEMA_VERSION,
        "contract": copy.deepcopy(dict(contract)),
        "task": "Repair the response into one valid JSON object without adding facts.",
        "raw_response": str(raw_response or "")[:12_000],
    }
    _require_bounded(payload)
    return payload


def bounded_source_record(record: Mapping[str, Any]) -> dict[str, Any]:
    source = dict(record or {})
    text = str(source.get("text") or "")
    if len(text) > 9_000:
        text = text[:9_000]
    return {
        "source_record_id": str(source.get("source_record_id") or ""),
        "sequence": int(source.get("sequence", 0) or 0),
        "speaker": str(source.get("speaker") or ""),
        "role": str(source.get("role") or ""),
        "timestamp": str(source.get("timestamp") or ""),
        "thread_id": str(source.get("thread_id") or ""),
        "reply_to": str(source.get("reply_to") or ""),
        "text": text,
    }


def compact_story_context(
    value: Mapping[str, Any],
    *,
    for_outline: bool = False,
) -> dict[str, Any]:
    source = dict(value or {})
    limits = {
        "characters": 20 if for_outline else 12,
        "relationships": 20 if for_outline else 10,
        "events": 40 if for_outline else 12,
        "locations": 16 if for_outline else 8,
        "objects": 16 if for_outline else 8,
        "themes": 12 if for_outline else 8,
        "candidate_scenes": 30 if for_outline else 6,
        "contradictions": 12 if for_outline else 6,
    }
    compact: dict[str, Any] = {}
    for key, limit in limits.items():
        items = source.get(key)
        if isinstance(items, (list, tuple)):
            compact[key] = [copy.deepcopy(item) for item in items[-limit:]]
        else:
            compact[key] = []
    return compact


def _require_bounded(payload: Mapping[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if len(serialized) >= MAX_PROMPT_CHARACTERS:
        raise ValueError(
            f"Novel prompt payload exceeds {MAX_PROMPT_CHARACTERS:,} characters."
        )
