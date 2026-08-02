"""Read-only loading of checkpoint-pinned Audio Story project artifacts."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from dataclasses import dataclass

from addons.audio_story_mode import checkpointing


@dataclass(frozen=True)
class RestoreIssue:
    chapter_id: str
    stage: str
    message: str


@dataclass(frozen=True)
class RestoredChapterArtifacts:
    chapter_id: str
    global_offset_seconds: float
    transcript: Mapping[str, object] | None
    analysis: Mapping[str, object] | None


@dataclass(frozen=True)
class ProjectArtifactRestore:
    project_id: str
    chapters: tuple[RestoredChapterArtifacts, ...]
    issues: tuple[RestoreIssue, ...]


class _ArtifactRestoreError(ValueError):
    """A safe, user-facing failure while loading one stored artifact."""


def _revision_from_ref(chapter_id: str, kind: str, output_ref: str) -> int:
    """Return the exact revision named by a checkpoint-owned document reference."""
    chapter_component = _safe_component(chapter_id, "chapter id")
    kind_component = _safe_component(kind, "document kind")
    if not isinstance(output_ref, str) or not output_ref or "\\" in output_ref:
        raise ValueError("Invalid project document reference")
    expression = re.compile(
        rf"chapters/{re.escape(chapter_component)}/{re.escape(kind_component)}\.([1-9][0-9]*)\.json"
    )
    match = expression.fullmatch(output_ref)
    if match is None:
        raise ValueError("Invalid project document reference")
    return int(match.group(1))


def _validated_document(
    store: object,
    project_id: str,
    chapter_id: str,
    kind: str,
    checkpoint: Mapping[str, object],
) -> dict:
    """Load and fingerprint-check the exact immutable document named by a checkpoint."""
    output_ref = checkpoint.get("output_ref")
    if not isinstance(output_ref, str):
        raise _ArtifactRestoreError("Invalid project document reference")
    try:
        revision = _revision_from_ref(chapter_id, kind, output_ref)
    except ValueError as exc:
        raise _ArtifactRestoreError("Invalid project document reference") from exc
    expected_fingerprint = str(checkpoint.get("output_fingerprint") or "").strip()
    if not expected_fingerprint:
        raise _ArtifactRestoreError(f"{kind} document fingerprint is missing")
    try:
        document = store.load_chapter_document(project_id, chapter_id, kind, revision)
    except (FileNotFoundError, ValueError):
        raise _ArtifactRestoreError(f"{kind} document not found: {output_ref}") from None
    except Exception:
        raise _ArtifactRestoreError(f"{kind} document could not be loaded: {output_ref}") from None
    if not isinstance(document, Mapping):
        raise _ArtifactRestoreError(f"{kind} document is not an object: {output_ref}")
    copied = copy.deepcopy(dict(document))
    document_project_id = str(copied.get("project_id") or "").strip()
    if document_project_id and document_project_id != str(project_id):
        raise _ArtifactRestoreError(
            f"{kind} document project id does not match the requested project"
        )
    document_chapter_id = str(copied.get("chapter_id") or "").strip()
    if document_chapter_id and document_chapter_id != str(chapter_id):
        raise _ArtifactRestoreError(
            f"{kind} document chapter id does not match the requested chapter"
        )
    if checkpointing.settings_fingerprint(copied) != expected_fingerprint:
        raise _ArtifactRestoreError(f"{kind} document fingerprint does not match checkpoint")
    return copied


def load_project_artifacts(store: object, project: Mapping[str, object]) -> ProjectArtifactRestore:
    """Load checkpoint-pinned transcript and analysis documents without modifying storage."""
    project_id = str(project.get("project_id") or "")
    chapters_by_id = project.get("chapters")
    chapters_by_id = chapters_by_id if isinstance(chapters_by_id, Mapping) else {}
    chapter_order = project.get("chapter_order")
    chapter_order = chapter_order if isinstance(chapter_order, (list, tuple)) else ()
    archived_ids = {
        str(value).strip()
        for value in (project.get("archived_chapter_ids") or ())
        if str(value).strip()
    }
    restored: list[RestoredChapterArtifacts] = []
    issues: list[RestoreIssue] = []
    offset_seconds = 0.0

    for value in chapter_order:
        chapter_id = str(value or "").strip()
        chapter = chapters_by_id.get(chapter_id)
        if chapter_id in archived_ids or not chapter_id or not isinstance(chapter, Mapping):
            continue
        transcript = _load_stage_document(
            store, project_id, chapter_id, chapter, "transcription", "transcript", issues
        )
        analysis = _load_stage_document(
            store, project_id, chapter_id, chapter, "story_analysis", "analysis", issues
        )
        restored.append(
            RestoredChapterArtifacts(
                chapter_id=chapter_id,
                global_offset_seconds=offset_seconds,
                transcript=transcript,
                analysis=analysis,
            )
        )
        offset_seconds += _chapter_duration_seconds(chapter)

    return ProjectArtifactRestore(project_id, tuple(restored), tuple(issues))


def load_chapter_artifacts(
    store: object,
    project: Mapping[str, object],
    chapter_id: str,
) -> ProjectArtifactRestore:
    """Load one active chapter's checkpoint-pinned artifacts."""
    project_id = str(project.get("project_id") or "").strip()
    selected_id = str(chapter_id or "").strip()
    chapters = project.get("chapters")
    chapters = chapters if isinstance(chapters, Mapping) else {}
    archived = {
        str(value or "").strip()
        for value in (project.get("archived_chapter_ids") or ())
        if str(value or "").strip()
    }
    chapter = chapters.get(selected_id)
    if not project_id:
        raise ValueError("Audio Story project has no project ID")
    if (
        not selected_id
        or selected_id in archived
        or not isinstance(chapter, Mapping)
    ):
        raise ValueError("Audio Story chapter is missing, archived, or unknown")

    offset_seconds = 0.0
    found = False
    order = project.get("chapter_order")
    order = order if isinstance(order, (list, tuple)) else ()
    for value in order:
        ordered_id = str(value or "").strip()
        if ordered_id in archived:
            continue
        if ordered_id == selected_id:
            found = True
            break
        ordered_chapter = chapters.get(ordered_id)
        if isinstance(ordered_chapter, Mapping):
            offset_seconds += _chapter_duration_seconds(ordered_chapter)
    if not found:
        raise ValueError("Audio Story chapter is not active in project order")

    issues: list[RestoreIssue] = []
    transcript = _load_stage_document(
        store,
        project_id,
        selected_id,
        chapter,
        "transcription",
        "transcript",
        issues,
    )
    analysis = _load_stage_document(
        store,
        project_id,
        selected_id,
        chapter,
        "story_analysis",
        "analysis",
        issues,
    )
    restored = RestoredChapterArtifacts(
        chapter_id=selected_id,
        global_offset_seconds=offset_seconds,
        transcript=transcript,
        analysis=analysis,
    )
    return ProjectArtifactRestore(project_id, (restored,), tuple(issues))


def _load_stage_document(
    store: object,
    project_id: str,
    chapter_id: str,
    chapter: Mapping[str, object],
    stage: str,
    kind: str,
    issues: list[RestoreIssue],
) -> Mapping[str, object] | None:
    stages = chapter.get("stages")
    checkpoint = stages.get(stage) if isinstance(stages, Mapping) else None
    if not isinstance(checkpoint, Mapping) or checkpoint.get("status") != "completed":
        return None
    try:
        return _validated_document(store, project_id, chapter_id, kind, checkpoint)
    except _ArtifactRestoreError as exc:
        issues.append(RestoreIssue(chapter_id, stage, str(exc)))
        return None


def _chapter_duration_seconds(chapter: Mapping[str, object]) -> float:
    audio_reference = chapter.get("audio_reference")
    fingerprint = audio_reference.get("fingerprint") if isinstance(audio_reference, Mapping) else None
    try:
        return max(0.0, float(fingerprint.get("duration_ms", 0) or 0) / 1000.0)
    except (AttributeError, TypeError, ValueError):
        return 0.0


def _safe_component(value: object, label: str) -> str:
    component = str(value or "").strip()
    if not component or component in {".", ".."} or "/" in component or "\\" in component:
        raise ValueError(f"Invalid {label}")
    return component
