from __future__ import annotations

import copy
import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from typing import Any

from addons.audio_story_mode import project_models


STAGE_ORDER = (
    "audio_validation",
    "transcription",
    "transcript_combination",
    "story_analysis",
    "scene_planning",
    "image_generation",
)

_STARTABLE_STATUSES = frozenset({"pending", "failed", "interrupted", "stale"})
_STAGE_INDEX = {stage: index for index, stage in enumerate(STAGE_ORDER)}


class CheckpointTransitionError(ValueError):
    """Raised when a checkpoint is asked to make an illegal state transition."""


def settings_fingerprint(payload: Mapping) -> str:
    """Return the stable SHA-256 fingerprint for JSON-compatible settings."""
    if not isinstance(payload, Mapping):
        raise TypeError("Checkpoint settings must be a mapping")
    encoded = json.dumps(
        dict(payload), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def start_checkpoint(
    checkpoint: Mapping,
    *,
    input_fingerprint: str,
    now: float | None = None,
    provider: str = "",
    model: str = "",
) -> dict:
    """Start a retryable checkpoint and retain the input identity used for this attempt."""
    updated = _transition(checkpoint, _STARTABLE_STATUSES, "running")
    updated["input_fingerprint"] = _text(input_fingerprint)
    updated["output_fingerprint"] = ""
    updated["output_ref"] = ""
    updated["attempt_count"] = _attempt_count(updated.get("attempt_count")) + 1
    updated["started_at"] = _timestamp(now)
    updated["completed_at"] = None
    updated["error"] = ""
    updated["provider"] = _text(provider)
    updated["model"] = _text(model)
    return updated


def complete_checkpoint(
    checkpoint: Mapping,
    *,
    output_ref: str,
    output_fingerprint: str,
    now: float | None = None,
) -> dict:
    """Record successful output for a checkpoint that is currently running."""
    updated = _transition(checkpoint, {"running"}, "completed")
    updated["output_ref"] = _text(output_ref)
    updated["output_fingerprint"] = _text(output_fingerprint)
    updated["completed_at"] = _timestamp(now)
    updated["error"] = ""
    return updated


def fail_checkpoint(checkpoint: Mapping, *, error: str, now: float | None = None) -> dict:
    """Record a recoverable failure for a checkpoint that is currently running."""
    updated = _transition(checkpoint, {"running"}, "failed")
    updated["completed_at"] = _timestamp(now)
    updated["error"] = _text(error)
    return updated


def recover_interrupted(project: Mapping) -> tuple[dict, bool]:
    """Copy a project and convert checkpoints left running by a prior session."""
    normalized = _normalized_project(project)
    changed = False
    for chapter in normalized["chapters"].values():
        for stage in STAGE_ORDER:
            checkpoint = chapter["stages"][stage]
            if checkpoint.get("status") == "running":
                checkpoint["status"] = "interrupted"
                changed = True
        for _scene_id, checkpoint in _scene_checkpoints(chapter):
            if checkpoint.get("status") == "running":
                checkpoint["status"] = "interrupted"
                changed = True
    return normalized, changed


def invalidate_project(
    project: Mapping,
    *,
    chapter_id: str,
    from_stage: str,
    include_later_chapters: bool = False,
) -> dict:
    """Mark dependent checkpoints stale without changing the supplied project."""
    normalized = _normalized_project(project)
    requested_chapter_id = _required_chapter_id(chapter_id)
    if requested_chapter_id not in normalized["chapters"]:
        raise KeyError(f"Unknown chapter: {requested_chapter_id}")
    if from_stage not in _STAGE_INDEX:
        raise ValueError(f"Unknown Audio Story stage: {from_stage}")

    active_order = _active_chapter_order(normalized)
    selected_chapters = [requested_chapter_id]
    if include_later_chapters and requested_chapter_id in active_order:
        selected_chapters = active_order[active_order.index(requested_chapter_id) :]

    for selected_chapter_id in selected_chapters:
        stage_index = _STAGE_INDEX[from_stage]
        if selected_chapter_id != requested_chapter_id:
            stage_index = max(stage_index, _STAGE_INDEX["story_analysis"])
        chapter = normalized["chapters"][selected_chapter_id]
        for stage in STAGE_ORDER[stage_index:]:
            _mark_stale(chapter["stages"][stage])
        if stage_index <= _STAGE_INDEX["image_generation"]:
            for _scene_id, checkpoint in _scene_checkpoints(chapter):
                _mark_stale(checkpoint)
    return normalized


def build_resume_plan(project: Mapping) -> list[dict]:
    """Return deterministic next units, keeping each chapter behind its prerequisites."""
    normalized = _normalized_project(project)
    plan: list[dict] = []
    for chapter_id in _active_chapter_order(normalized):
        chapter = normalized["chapters"][chapter_id]
        if _chapter_is_blocked(chapter):
            continue
        for stage in STAGE_ORDER:
            checkpoint = chapter["stages"][stage]
            if _checkpoint_is_reusable(checkpoint):
                if stage == "image_generation":
                    plan.extend(_incomplete_scene_plan(chapter_id, chapter))
                continue
            if stage == "image_generation":
                scene_plan = _incomplete_scene_plan(chapter_id, chapter)
                if scene_plan:
                    plan.extend(scene_plan)
                else:
                    plan.append(_plan_item(chapter_id, stage, checkpoint.get("unit_id")))
            else:
                plan.append(_plan_item(chapter_id, stage, checkpoint.get("unit_id")))
            break
    return plan


def _chapter_is_blocked(chapter: Mapping) -> bool:
    return any(
        chapter["stages"][stage].get("status") == "missing_audio"
        for stage in STAGE_ORDER
    )


def _transition(checkpoint: Mapping, allowed_statuses: set[str] | frozenset[str], target: str) -> dict:
    updated = _validated_checkpoint_copy(checkpoint)
    current = updated["status"]
    if current not in allowed_statuses:
        raise CheckpointTransitionError(f"Cannot transition checkpoint from {current!r} to {target!r}")
    updated["status"] = target
    return updated


def _validated_checkpoint_copy(checkpoint: Mapping) -> dict:
    if not isinstance(checkpoint, Mapping):
        raise TypeError("Checkpoint must be a mapping")
    updated = copy.deepcopy(dict(checkpoint))
    stage = updated.get("stage")
    if stage not in _STAGE_INDEX:
        raise CheckpointTransitionError(f"Unknown Audio Story stage: {stage!r}")
    status = updated.get("status")
    if status not in project_models.CHECKPOINT_STATUSES:
        raise CheckpointTransitionError(f"Unknown Audio Story checkpoint status: {status!r}")
    return updated


def _normalized_project(project: Mapping) -> dict:
    if not isinstance(project, Mapping):
        raise TypeError("Project must be a mapping")
    return project_models.normalize_project_manifest(project)


def _active_chapter_order(project: Mapping) -> list[str]:
    archived = set(project.get("archived_chapter_ids", ()))
    chapters = project["chapters"]
    return [chapter_id for chapter_id in project["chapter_order"] if chapter_id in chapters and chapter_id not in archived]


def _scene_checkpoints(chapter: dict) -> list[tuple[str, dict]]:
    source = chapter.get("scene_checkpoints")
    if isinstance(source, Mapping):
        checkpoints: list[tuple[str, dict]] = []
        for scene_id, checkpoint in source.items():
            if isinstance(checkpoint, Mapping):
                copied = copy.deepcopy(dict(checkpoint))
                copied.setdefault("unit_id", str(scene_id))
                source[scene_id] = copied
                checkpoints.append((str(scene_id), copied))
        return checkpoints
    if isinstance(source, Sequence) and not isinstance(source, (str, bytes, bytearray)):
        checkpoints = []
        for index, checkpoint in enumerate(source):
            if isinstance(checkpoint, Mapping):
                copied = copy.deepcopy(dict(checkpoint))
                scene_id = _text(copied.get("scene_id") or copied.get("unit_id") or index)
                copied.setdefault("unit_id", scene_id)
                source[index] = copied
                checkpoints.append((scene_id, copied))
        return checkpoints
    return []


def _mark_stale(checkpoint: dict) -> None:
    checkpoint["status"] = "stale"
    checkpoint["output_ref"] = ""
    checkpoint["output_fingerprint"] = ""
    checkpoint["completed_at"] = None
    checkpoint["error"] = ""


def _checkpoint_is_reusable(checkpoint: Mapping) -> bool:
    if checkpoint.get("status") != "completed":
        return False
    expected = _text(checkpoint.get("expected_input_fingerprint")).strip()
    if not expected:
        expected = _text(checkpoint.get("current_input_fingerprint")).strip()
    return bool(expected) and _text(checkpoint.get("input_fingerprint")) == expected


def _incomplete_scene_plan(chapter_id: str, chapter: dict) -> list[dict]:
    return [
        _plan_item(chapter_id, "image_generation", checkpoint.get("unit_id") or scene_id)
        for scene_id, checkpoint in _scene_checkpoints(chapter)
        if not _checkpoint_is_reusable(checkpoint)
    ]


def _plan_item(chapter_id: str, stage: str, unit_id: Any) -> dict:
    return {
        "chapter_id": chapter_id,
        "stage": stage,
        "unit_id": _text(unit_id) or chapter_id,
    }


def _required_chapter_id(value: object) -> str:
    chapter_id = _text(value).strip()
    if not chapter_id:
        raise ValueError("Chapter id cannot be empty")
    return chapter_id


def _attempt_count(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _timestamp(value: float | None) -> float:
    return time.time() if value is None else float(value)


def _text(value: object) -> str:
    return value if isinstance(value, str) else "" if value is None else str(value)
