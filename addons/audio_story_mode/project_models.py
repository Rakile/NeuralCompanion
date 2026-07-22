from __future__ import annotations

import copy
import time
import uuid
from collections.abc import Mapping
from typing import Any


PROJECT_SCHEMA_VERSION = 1
CHECKPOINT_STATUSES = frozenset(
    {"pending", "running", "completed", "failed", "interrupted", "stale", "missing_audio"}
)
STAGES = (
    "audio_validation",
    "transcription",
    "transcript_combination",
    "story_analysis",
    "scene_planning",
    "image_generation",
)


def checkpoint(stage: str, unit_id: str, *, status: str = "pending") -> dict:
    if stage not in STAGES:
        raise ValueError(f"Unknown Audio Story stage: {stage}")
    if status not in CHECKPOINT_STATUSES:
        raise ValueError(f"Unknown Audio Story checkpoint status: {status}")
    return {
        "stage": stage,
        "unit_id": str(unit_id),
        "status": status,
        "input_fingerprint": "",
        "output_fingerprint": "",
        "output_ref": "",
        "attempt_count": 0,
        "started_at": None,
        "completed_at": None,
        "error": "",
        "provider": "",
        "model": "",
    }


def new_project_manifest(
    name: str,
    *,
    project_id: str | None = None,
    now: float | None = None,
) -> dict:
    normalized_name = _required_name(name, "project")
    timestamp = _timestamp(now)
    return normalize_project_manifest(
        {
            "schema_version": PROJECT_SCHEMA_VERSION,
            "project_id": _identifier(project_id),
            "name": normalized_name,
            "created_at": timestamp,
            "updated_at": timestamp,
            "story_bible_revision": 0,
            "autosave_revision": 0,
            "chapter_order": [],
            "chapters": {},
            "archived_chapter_ids": [],
        }
    )


def new_chapter_manifest(
    display_name: str,
    audio_reference: dict,
    *,
    chapter_id: str | None = None,
    now: float | None = None,
) -> dict:
    normalized_name = _required_name(display_name, "chapter")
    timestamp = _timestamp(now)
    identifier = _identifier(chapter_id)
    return normalize_chapter_manifest(
        {
            "schema_version": PROJECT_SCHEMA_VERSION,
            "chapter_id": identifier,
            "display_name": normalized_name,
            "audio_reference": _copy_mapping(audio_reference),
            "created_at": timestamp,
            "updated_at": timestamp,
            "stages": {stage: checkpoint(stage, identifier) for stage in STAGES},
        }
    )


def normalize_project_manifest(value: Mapping) -> dict:
    source = _copy_mapping(value)
    result = source
    result["schema_version"] = PROJECT_SCHEMA_VERSION
    result["project_id"] = _identifier(source.get("project_id"))
    result["name"] = _normalized_name(source.get("name"), "Untitled Project")
    result["created_at"] = _timestamp_or_default(source.get("created_at"), 0.0)
    result["updated_at"] = _timestamp_or_default(source.get("updated_at"), result["created_at"])
    result["story_bible_revision"] = _nonnegative_int(source.get("story_bible_revision"))
    result["autosave_revision"] = _nonnegative_int(source.get("autosave_revision"))
    result["chapter_order"] = _identifier_list(source.get("chapter_order"))
    result["chapters"] = _normalize_chapters(source.get("chapters"))
    result["archived_chapter_ids"] = _identifier_list(source.get("archived_chapter_ids"))
    return result


def normalize_chapter_manifest(value: Mapping) -> dict:
    source = _copy_mapping(value)
    result = source
    identifier = _identifier(source.get("chapter_id"))
    stages = _copy_mapping(source.get("stages"))
    result["schema_version"] = PROJECT_SCHEMA_VERSION
    result["chapter_id"] = identifier
    result["display_name"] = _normalized_name(source.get("display_name"), "Untitled Chapter")
    result["audio_reference"] = _copy_mapping(source.get("audio_reference"))
    result["created_at"] = _timestamp_or_default(source.get("created_at"), 0.0)
    result["updated_at"] = _timestamp_or_default(source.get("updated_at"), result["created_at"])
    normalized_stages = stages
    normalized_stages.update(
        {
            stage: normalize_checkpoint(stages.get(stage, {}), stage=stage, unit_id=identifier)
            for stage in STAGES
        }
    )
    result["stages"] = normalized_stages
    return result


def normalize_checkpoint(value: Mapping, *, stage: str, unit_id: str) -> dict:
    source = _copy_mapping(value)
    status = source.get("status")
    normalized_status = status if _is_checkpoint_status(status) else "pending"
    result = checkpoint(stage, unit_id, status=normalized_status)
    result.update(source)
    result["stage"] = stage
    result["unit_id"] = str(unit_id)
    result["status"] = normalized_status
    result["input_fingerprint"] = _text(source.get("input_fingerprint"))
    result["output_fingerprint"] = _text(source.get("output_fingerprint"))
    result["output_ref"] = _text(source.get("output_ref"))
    result["attempt_count"] = _nonnegative_int(source.get("attempt_count"))
    result["started_at"] = _optional_timestamp(source.get("started_at"))
    result["completed_at"] = _optional_timestamp(source.get("completed_at"))
    result["error"] = _text(source.get("error"))
    result["provider"] = _text(source.get("provider"))
    result["model"] = _text(source.get("model"))
    return result


def _copy_mapping(value: Any) -> dict:
    if not isinstance(value, Mapping):
        return {}
    return copy.deepcopy(dict(value))


def _identifier(value: Any) -> str:
    candidate = _text(value).strip()
    return candidate or str(uuid.uuid4())


def _is_checkpoint_status(value: Any) -> bool:
    return isinstance(value, str) and value in CHECKPOINT_STATUSES


def _identifier_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [candidate for item in value if (candidate := _text(item).strip())]


def _normalize_chapters(value: Any) -> dict:
    if not isinstance(value, Mapping):
        return {}
    chapters = {}
    for chapter_id, chapter in value.items():
        identifier = _text(chapter_id).strip()
        if not identifier or not isinstance(chapter, Mapping):
            continue
        chapter_source = _copy_mapping(chapter)
        chapter_source["chapter_id"] = identifier
        chapters[identifier] = normalize_chapter_manifest(chapter_source)
    return chapters


def _required_name(value: Any, kind: str) -> str:
    normalized = _text(value).strip()
    if not normalized:
        raise ValueError(f"Audio Story {kind} name cannot be empty")
    return normalized


def _normalized_name(value: Any, default: str) -> str:
    normalized = _text(value).strip()
    return normalized or default


def _text(value: Any) -> str:
    return value if isinstance(value, str) else "" if value is None else str(value)


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _optional_timestamp(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _timestamp_or_default(value: Any, default: float) -> float:
    timestamp = _optional_timestamp(value)
    return default if timestamp is None else timestamp


def _timestamp(value: float | None) -> float:
    return time.time() if value is None else float(value)
