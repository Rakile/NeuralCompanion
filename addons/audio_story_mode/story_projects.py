from __future__ import annotations

import copy
import json
import os
import secrets
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from addons.audio_story_mode import (
    audio_fingerprint,
    checkpointing,
    project_models,
    project_store,
    session_schema,
    story_memory,
)


ProgressCallback = Callable[[int, str], None]

_ROOT_LOCKS_GUARD = threading.Lock()
_ROOT_LOCKS: dict[str, threading.RLock] = {}


class StoryProjectError(RuntimeError):
    """Base error for Audio Story project lifecycle operations."""


class NoProjectSelectedError(StoryProjectError):
    """Raised when an operation requires an explicitly selected project."""


class ImportReviewError(StoryProjectError):
    """Raised when an import review cannot be committed safely."""


class ImportConfirmationRequired(ImportReviewError):
    """Raised when committing only valid candidates was not confirmed."""


class ImportConflictError(ImportReviewError):
    """Raised when an import contains duplicate or externally owned audio."""


class RelinkMismatchError(StoryProjectError):
    """Raised when a relink candidate is not the chapter's original audio."""


class ChapterOrderError(StoryProjectError):
    """Raised when a reorder request is not an exact active-chapter permutation."""


class StoryProjectManager:
    """Coordinates explicit, non-destructive Audio Story project lifecycle changes."""

    def __init__(
        self,
        store: project_store.StoryProjectStore,
        duration_reader: Callable[[str], float],
        fingerprint_reader: Callable[..., dict] = audio_fingerprint.compute_audio_fingerprint,
    ) -> None:
        self.store = store
        self.duration_reader = duration_reader
        self.fingerprint_reader = fingerprint_reader
        self._transaction_lock = _root_transaction_lock(store.root)
        self._legacy_previews: dict[str, dict] = {}
        self.current_project_id: str = ""
        self._current_project: dict | None = None

    @property
    def current_project(self) -> dict | None:
        return copy.deepcopy(self._current_project)

    def create(self, name: str) -> dict:
        project = self.store.create_project(name)
        return self._select(project)

    def open(self, project_id: str) -> dict:
        return self._select(self.store.load_project(project_id))

    def open_with_recovery(self, project_id: str) -> tuple[dict, bool]:
        project, used_backup = self.store.load_project_with_recovery(project_id)
        return self._select(project), bool(used_backup)

    def close(self) -> None:
        self.current_project_id = ""
        self._current_project = None

    def delete(self, project_id: str | None = None) -> dict:
        selected_id = str(project_id or self.current_project_id or "").strip()
        if not selected_id:
            raise NoProjectSelectedError("Select an Audio Story project first")
        deleted = self.store.delete_project(selected_id)
        if selected_id == self.current_project_id:
            self.close()
        return deleted

    def rename(self, name: str) -> dict:
        project = self._load_selected()
        project["name"] = str(name).strip()
        if not project["name"]:
            raise ValueError("Audio Story project name cannot be empty")
        return self._select(self.store.save_project(project))

    def rename_chapter(self, chapter_id: str, name: str) -> dict:
        project = self._load_selected()
        normalized_id = str(chapter_id)
        chapter = self._require_chapter(project, normalized_id)
        normalized_name = str(name).strip()
        if not normalized_name:
            raise ValueError("Audio Story chapter name cannot be empty")
        chapter["display_name"] = normalized_name
        project["chapters"][normalized_id] = chapter
        return self._select(self.store.save_project(project))

    def review_import(
        self,
        paths: Sequence[str],
        progress: ProgressCallback | None = None,
    ) -> dict:
        project = self._load_selected()
        review = {
            "project_id": project["project_id"],
            "manifest_revision": project.get("manifest_revision", 0),
            "valid": [],
            "invalid": [],
            "conflicts": [],
        }
        reviewed_fingerprints: list[dict] = []
        for path_value in paths:
            path = str(path_value)
            try:
                fingerprint = self.fingerprint_reader(
                    path,
                    self.duration_reader,
                    progress=progress,
                )
            except Exception as exc:
                review["invalid"].append({"path": path, "error": str(exc)})
                continue
            candidate = {
                "path": path,
                "display_name": Path(path).stem or Path(path).name,
                "fingerprint": copy.deepcopy(fingerprint),
            }
            if any(
                audio_fingerprint.fingerprint_matches(fingerprint, previous)
                for previous in reviewed_fingerprints
            ):
                review["conflicts"].append({**candidate, "reason": "duplicate_in_selection"})
                continue
            owner = self._audio_owner(fingerprint)
            if owner is not None:
                reason = (
                    "already_in_project"
                    if owner["project_id"] == project["project_id"]
                    else "owned_by_another_project"
                )
                review["conflicts"].append({**candidate, "reason": reason, "owner": owner})
                continue
            reviewed_fingerprints.append(copy.deepcopy(fingerprint))
            review["valid"].append(candidate)
        return review

    def commit_import(self, review: Mapping, *, valid_only: bool) -> dict:
        if not self.current_project_id:
            raise NoProjectSelectedError("Select an Audio Story project first")
        with self._transaction_lock:
            project = self._load_selected()
            if review.get("project_id") != project["project_id"]:
                raise ImportReviewError("Import review belongs to a different project")
            persisted = self.store.load_project(project["project_id"])
            if int(review.get("manifest_revision", 0)) != int(
                persisted.get("manifest_revision", 0)
            ):
                raise ImportReviewError("Import review is stale; review the files again")
            conflicts = _mapping_list(review.get("conflicts"))
            invalid = _mapping_list(review.get("invalid"))
            valid = _mapping_list(review.get("valid"))
            if conflicts:
                raise ImportConflictError("Import conflicts must be resolved before committing")
            if invalid and not valid_only:
                raise ImportConfirmationRequired(
                    "Some files are invalid; confirm importing only the valid files"
                )
            valid = self._validated_import_candidates(valid)
            if not valid:
                return self._select(persisted)

            chapters: list[tuple[dict, dict]] = []
            for candidate in valid:
                audio = {
                    "path": str(candidate.get("path", "")),
                    "fingerprint": copy.deepcopy(candidate.get("fingerprint", {})),
                }
                chapter = project_models.new_chapter_manifest(
                    str(candidate.get("display_name", "")),
                    audio,
                )
                chapter["audio"] = copy.deepcopy(audio)
                chapters.append(
                    (chapter, copy.deepcopy(candidate["current_fingerprint"]))
                )

            transaction_states: list[dict] = []
            expected_owners: list[tuple[dict, dict]] = []
            pre_transaction_index = self._read_persisted_index()
            try:
                staged = copy.deepcopy(persisted)
                memberships = staged.get("audio_memberships")
                if not isinstance(memberships, Mapping):
                    memberships = {}
                staged["audio_memberships"] = copy.deepcopy(dict(memberships))
                for chapter, current_fingerprint in chapters:
                    reviewed_fingerprint = chapter["audio_reference"]["fingerprint"]
                    owner = self._audio_owner(current_fingerprint)
                    if owner is None:
                        owner = self._audio_owner(reviewed_fingerprint)
                    if owner is not None:
                        raise ImportConflictError("Audio ownership changed; review the files again")
                    chapter_id = chapter["chapter_id"]
                    expected_owner = {
                        "project_id": persisted["project_id"],
                        "chapter_id": chapter_id,
                    }
                    expected_owners.append(
                        (copy.deepcopy(current_fingerprint), expected_owner)
                    )
                    staged["audio_memberships"][
                        project_store._fingerprint_key(reviewed_fingerprint)
                    ] = {
                        "chapter_id": chapter_id,
                        "fingerprint": copy.deepcopy(reviewed_fingerprint),
                    }
                transaction_states.append(_expected_saved_project(staged))
                proposed = self.store.save_project(staged)
                for chapter, _current_fingerprint in chapters:
                    chapter_id = chapter["chapter_id"]
                    proposed["chapters"][chapter_id] = chapter
                    proposed["chapter_order"].append(chapter_id)
                transaction_states.append(_expected_saved_project(proposed))
                committed = self.store.save_project(proposed)
                self._write_backup_snapshot(persisted)
            except Exception:
                rolled_back = self._rollback_import_if_owned(
                    persisted,
                    transaction_states,
                    expected_owners,
                    pre_transaction_index,
                )
                if rolled_back:
                    self._select(persisted)
                else:
                    try:
                        self._select(self.store.load_project(persisted["project_id"]))
                    except project_store.ProjectStoreError:
                        pass
                raise
            return self._select(committed)

    def _validated_import_candidates(self, candidates: Sequence[Mapping]) -> list[dict]:
        validated: list[dict] = []
        reviewed_fingerprints: list[dict] = []
        current_fingerprints: list[dict] = []
        for candidate in candidates:
            path = candidate.get("path")
            display_name = candidate.get("display_name")
            reviewed_fingerprint = candidate.get("fingerprint")
            if not isinstance(path, str) or not path.strip():
                raise ImportReviewError("Import candidate path is missing")
            if not isinstance(display_name, str) or not display_name.strip():
                raise ImportReviewError("Import candidate display name is missing")
            if not isinstance(reviewed_fingerprint, Mapping):
                raise ImportReviewError("Import candidate fingerprint is missing")
            try:
                project_store._fingerprint_key(reviewed_fingerprint)
                current_fingerprint = self.fingerprint_reader(path, self.duration_reader)
                project_store._fingerprint_key(current_fingerprint)
            except Exception as exc:
                raise ImportReviewError(f"Import candidate is no longer valid: {path}") from exc
            if not audio_fingerprint.fingerprint_matches(
                reviewed_fingerprint,
                current_fingerprint,
            ):
                raise ImportReviewError(f"Import candidate changed after review: {path}")
            if any(
                audio_fingerprint.fingerprint_matches(reviewed_fingerprint, previous)
                for previous in reviewed_fingerprints
            ) or any(
                audio_fingerprint.fingerprint_matches(current_fingerprint, previous)
                for previous in current_fingerprints
            ):
                raise ImportConflictError("Import candidates contain duplicate audio")
            normalized_fingerprint = copy.deepcopy(dict(reviewed_fingerprint))
            reviewed_fingerprints.append(normalized_fingerprint)
            current_fingerprints.append(copy.deepcopy(dict(current_fingerprint)))
            validated.append(
                {
                    "path": path,
                    "display_name": display_name.strip(),
                    "fingerprint": copy.deepcopy(normalized_fingerprint),
                    "current_fingerprint": copy.deepcopy(dict(current_fingerprint)),
                }
            )
        return validated

    def archive_chapter(self, chapter_id: str) -> dict:
        project = self._load_selected()
        normalized_id = str(chapter_id)
        self._require_chapter(project, normalized_id)
        if normalized_id not in project["chapter_order"]:
            return self._select(project)
        old_order = list(project["chapter_order"])
        affected_index = old_order.index(normalized_id)
        project["chapter_order"] = [
            existing for existing in project["chapter_order"] if existing != normalized_id
        ]
        if normalized_id not in project["archived_chapter_ids"]:
            project["archived_chapter_ids"].append(normalized_id)
        project = self._invalidate_active_continuity_from_index(project, affected_index)
        return self._select(project)

    def restore_chapter(self, chapter_id: str) -> dict:
        project = self._load_selected()
        normalized_id = str(chapter_id)
        self._require_chapter(project, normalized_id)
        if normalized_id not in project["archived_chapter_ids"]:
            return self._select(project)
        project["archived_chapter_ids"] = [
            existing
            for existing in project["archived_chapter_ids"]
            if existing != normalized_id
        ]
        if normalized_id not in project["chapter_order"]:
            project["chapter_order"].append(normalized_id)
        project = self._invalidate_active_continuity_from_index(
            project, max(0, len(project["chapter_order"]) - 1)
        )
        return self._select(project)

    def reorder_chapters(self, ids: Sequence[str]) -> dict:
        project = self._load_selected()
        requested = [str(chapter_id) for chapter_id in ids]
        active = list(project["chapter_order"])
        if len(requested) != len(set(requested)) or set(requested) != set(active):
            raise ChapterOrderError("Chapter order must contain every active chapter exactly once")
        first_changed = next(
            (index for index, pair in enumerate(zip(active, requested)) if pair[0] != pair[1]),
            None,
        )
        project["chapter_order"] = requested
        if first_changed is not None:
            project = self._invalidate_active_continuity_from_index(project, first_changed)
            return self._select(project)
        return self._select(self.store.save_project(project))

    def _invalidate_active_continuity_from_index(self, project: dict, index: int) -> dict:
        active = [
            chapter_id
            for chapter_id in list(project.get("chapter_order") or [])
            if chapter_id in dict(project.get("chapters") or {})
            and chapter_id not in set(project.get("archived_chapter_ids") or [])
        ]
        affected_index = min(max(0, int(index)), len(active))
        rebuilt_bible = story_memory.empty_story_memory()
        for prefix_index, chapter_id in enumerate(active[:affected_index]):
            checkpoint = project["chapters"][chapter_id]["stages"]["story_analysis"]
            expected_input = str(
                checkpoint.get("expected_input_fingerprint")
                or checkpoint.get("current_input_fingerprint")
                or ""
            ).strip()
            if (
                checkpoint.get("status") != "completed"
                or not expected_input
                or str(checkpoint.get("input_fingerprint") or "") != expected_input
                or not str(checkpoint.get("output_fingerprint") or "").strip()
                or not str(checkpoint.get("output_ref") or "").strip()
            ):
                affected_index = prefix_index
                break
            try:
                analysis = self.store.load_chapter_document(
                    project["project_id"], chapter_id, "analysis"
                )
                if not isinstance(analysis, Mapping):
                    raise TypeError("Chapter analysis document must be an object")
                chapter_memory = analysis.get("project_story_memory")
                if chapter_memory is None:
                    chapter_memory = analysis.get("story_bible")
                if not isinstance(chapter_memory, Mapping):
                    raise TypeError("Chapter analysis has no Story Bible payload")
                rebuilt_bible = story_memory.merge_committed_story_bible(
                    rebuilt_bible, chapter_memory
                )
            except (
                KeyError,
                OSError,
                TypeError,
                ValueError,
                project_store.ProjectStoreError,
            ):
                affected_index = prefix_index
                break
        if affected_index < len(active):
            project = checkpointing.invalidate_project(
                project,
                chapter_id=active[affected_index],
                from_stage="story_analysis",
                include_later_chapters=True,
            )
        return self.store.commit_story_bible_rebuild(
            project,
            rebuilt_bible,
        )

    def relink_chapter(
        self,
        chapter_id: str,
        candidate_path: str,
        progress: ProgressCallback | None = None,
    ) -> dict:
        project = self._load_selected()
        normalized_id = str(chapter_id)
        chapter = self._require_chapter(project, normalized_id)
        audio = chapter.get("audio_reference")
        if not isinstance(audio, Mapping):
            audio = chapter.get("audio")
        if not isinstance(audio, Mapping) or not isinstance(audio.get("fingerprint"), Mapping):
            raise RelinkMismatchError("Chapter has no original audio fingerprint")
        candidate_fingerprint = self.fingerprint_reader(
            str(candidate_path),
            self.duration_reader,
            progress=progress,
        )
        if not audio_fingerprint.fingerprint_matches(audio["fingerprint"], candidate_fingerprint):
            raise RelinkMismatchError("Relink candidate does not match the chapter audio")
        owner = self._audio_owner(candidate_fingerprint)
        expected_owner = {"project_id": project["project_id"], "chapter_id": normalized_id}
        if owner is not None and owner != expected_owner:
            raise ImportConflictError("Relink candidate belongs to another chapter")
        updated_audio = copy.deepcopy(dict(audio))
        updated_audio["path"] = str(candidate_path)
        chapter["audio_reference"] = copy.deepcopy(updated_audio)
        chapter["audio"] = copy.deepcopy(updated_audio)
        project["chapters"][normalized_id] = chapter
        committed = self.store.save_project(project)
        return self._select(committed)

    def prepare_legacy_migration(self, session_payload: Mapping, project_name: str) -> dict:
        if not isinstance(session_payload, Mapping):
            raise TypeError("Legacy Audio Story session must be a mapping")
        source = copy.deepcopy(dict(session_payload))
        project = project_models.new_project_manifest(project_name)
        project["legacy_session_payload"] = copy.deepcopy(source)
        preview = {
            "kind": "audio_story_legacy_migration",
            "preview_token": secrets.token_urlsafe(24),
            "project": project,
            "valid": [],
            "invalid": [],
            "conflicts": [],
        }
        reviewed_fingerprints: list[dict] = []
        for path in _legacy_audio_paths(source):
            chapter = project_models.new_chapter_manifest(
                Path(path).stem or Path(path).name,
                {"path": path, "fingerprint": {}},
            )
            chapter_id = chapter["chapter_id"]
            try:
                fingerprint = self.fingerprint_reader(path, self.duration_reader)
            except Exception as exc:
                chapter["stages"]["audio_validation"]["status"] = "missing_audio"
                chapter["stages"]["audio_validation"]["error"] = str(exc)
                preview["invalid"].append(
                    {"path": path, "chapter_id": chapter_id, "error": str(exc)}
                )
            else:
                chapter["audio_reference"]["fingerprint"] = copy.deepcopy(fingerprint)
                validation_fingerprint = checkpointing.settings_fingerprint(
                    dict(fingerprint)
                )
                chapter["stages"]["audio_validation"].update(
                    {
                        "status": "completed",
                        "input_fingerprint": validation_fingerprint,
                        "expected_input_fingerprint": validation_fingerprint,
                        "output_fingerprint": validation_fingerprint,
                        "output_ref": path,
                        "completed_at": 0.0,
                        "error": "",
                    }
                )
                duplicate = any(
                    audio_fingerprint.fingerprint_matches(fingerprint, previous)
                    for previous in reviewed_fingerprints
                )
                owner = self._audio_owner(fingerprint)
                if duplicate or owner is not None:
                    conflict = {
                        "path": path,
                        "chapter_id": chapter_id,
                        "fingerprint": copy.deepcopy(fingerprint),
                        "reason": (
                            "duplicate_in_session" if duplicate else "owned_by_another_project"
                        ),
                    }
                    if owner is not None:
                        conflict["owner"] = owner
                    preview["conflicts"].append(conflict)
                else:
                    reviewed_fingerprints.append(copy.deepcopy(fingerprint))
                    preview["valid"].append(
                        {
                            "path": path,
                            "chapter_id": chapter_id,
                            "fingerprint": copy.deepcopy(fingerprint),
                        }
                    )
            chapter["audio"] = copy.deepcopy(chapter["audio_reference"])
            project["chapters"][chapter_id] = chapter
            project["chapter_order"].append(chapter_id)
        token = preview["preview_token"]
        self._legacy_previews[token] = copy.deepcopy(preview)
        return copy.deepcopy(preview)

    def commit_legacy_migration(self, preview: Mapping) -> dict:
        """Create and select a named project without requiring a preselected destination.

        This is the intentional create-like exception for the legacy "Save Current
        Story as Project" flow. Only an unchanged preview issued by this manager may
        be committed.
        """
        if not isinstance(preview, Mapping):
            raise ImportReviewError("Invalid legacy migration preview")
        submitted = copy.deepcopy(dict(preview))
        token = submitted.get("preview_token")
        if not isinstance(token, str) or not token:
            raise ImportReviewError("Legacy migration preview token is missing")
        with self._transaction_lock:
            bound = self._legacy_previews.get(token)
            if bound is None or submitted != bound:
                raise ImportReviewError("Legacy migration preview is unknown or changed")
            if bound.get("kind") != "audio_story_legacy_migration":
                raise ImportReviewError("Invalid legacy migration preview")
            conflicts = _mapping_list(bound.get("conflicts"))
            if conflicts:
                raise ImportConflictError("Legacy migration conflicts must be resolved first")
            project_value = bound.get("project")
            if not isinstance(project_value, Mapping):
                raise ImportReviewError("Legacy migration preview has no project")
            project = project_models.normalize_project_manifest(project_value)
            project_path = self.store.project_path(project["project_id"])
            backup_path = project_path.with_suffix(project_path.suffix + ".bak")
            if project_path.exists() or backup_path.exists():
                raise ImportReviewError("Legacy migration preview was already committed")
            current_fingerprints = self._validated_legacy_current_fingerprints(
                _mapping_list(bound.get("valid"))
            )
            for fingerprint in current_fingerprints:
                owner = self._audio_owner(fingerprint)
                if owner is not None:
                    raise ImportConflictError("Legacy audio belongs to an existing project")
            project = self._materialize_legacy_artifacts(project)
            committed = self.store.save_project(project)
            self._legacy_previews.pop(token, None)
            return self._select(committed)

    def _materialize_legacy_artifacts(self, project: dict) -> dict:
        source = project.get("legacy_session_payload")
        if not isinstance(source, Mapping):
            return project
        flat = session_schema.flatten_audio_story_mode_settings(source)
        order = list(project.get("chapter_order") or [])
        if not order:
            chapter = project_models.new_chapter_manifest(
                "Migrated Story", {"path": "", "fingerprint": {}}
            )
            chapter["audio"] = copy.deepcopy(chapter["audio_reference"])
            chapter["stages"]["audio_validation"]["status"] = "missing_audio"
            chapter["stages"]["audio_validation"]["error"] = (
                "Original audio was not present in the legacy session."
            )
            project["chapters"][chapter["chapter_id"]] = chapter
            project["chapter_order"].append(chapter["chapter_id"])
            order = [chapter["chapter_id"]]
        chapter_id = str(order[0])
        chapter = project["chapters"][chapter_id]
        transcript_payload = {
            "transcript_chunks": copy.deepcopy(
                list(flat.get("audio_story_mode_transcript_chunks") or [])
            ),
            "full_text": str(
                flat.get("audio_story_mode_full_transcript_text") or ""
            ).strip(),
            "raw_segments": copy.deepcopy(
                list(flat.get("audio_story_mode_raw_transcript_segments") or [])
            ),
        }
        has_transcript = bool(
            transcript_payload["transcript_chunks"]
            or transcript_payload["full_text"]
            or transcript_payload["raw_segments"]
        )
        if has_transcript:
            transcript_ref = self.store.save_chapter_document(
                project["project_id"], chapter_id, "transcript", 1, transcript_payload
            )
            transcript_fingerprint = checkpointing.settings_fingerprint(transcript_payload)
            for stage in ("transcription", "transcript_combination"):
                checkpoint = chapter["stages"][stage]
                checkpoint.update(
                    {
                        "status": "completed",
                        "input_fingerprint": "legacy-session-v1",
                        "expected_input_fingerprint": "legacy-session-v1",
                        "output_fingerprint": transcript_fingerprint,
                        "output_ref": transcript_ref,
                        "completed_at": 0.0,
                        "error": "",
                    }
                )
        analysis_payload = {
            "story_bible": copy.deepcopy(
                dict(flat.get("audio_story_mode_story_bible") or {})
            ),
            "scene_plan": copy.deepcopy(
                list(flat.get("audio_story_mode_scene_plan") or [])
            ),
            "scene_overrides": copy.deepcopy(
                dict(flat.get("audio_story_mode_scene_overrides") or {})
            ),
            "continuity_memory": copy.deepcopy(
                dict(flat.get("audio_story_mode_continuity_memory") or {})
            ),
            "character_anchors": copy.deepcopy(
                dict(flat.get("audio_story_mode_character_anchors") or {})
            ),
            "location_anchors": copy.deepcopy(
                dict(flat.get("audio_story_mode_location_anchors") or {})
            ),
        }
        has_analysis = any(bool(value) for value in analysis_payload.values())
        if has_analysis:
            analysis_ref = self.store.save_chapter_document(
                project["project_id"], chapter_id, "analysis", 1, analysis_payload
            )
            analysis_fingerprint = checkpointing.settings_fingerprint(analysis_payload)
            for stage in ("story_analysis", "scene_planning"):
                checkpoint = chapter["stages"][stage]
                checkpoint.update(
                    {
                        "status": "completed",
                        "input_fingerprint": "legacy-session-v1",
                        "expected_input_fingerprint": "legacy-session-v1",
                        "output_fingerprint": analysis_fingerprint,
                        "output_ref": analysis_ref,
                        "completed_at": 0.0,
                        "error": "",
                    }
                )
        story_bible = analysis_payload["story_bible"]
        if story_bible:
            story_bible_ref = project_store._story_bible_reference(1)
            project_store._atomic_write_json(
                self.store._project_directory(project["project_id"]) / story_bible_ref,
                story_bible,
            )
            project["story_bible_revision"] = 1
            project["story_bible_ref"] = story_bible_ref
        project["legacy_artifact_chapter_id"] = chapter_id
        project["chapters"][chapter_id] = chapter
        return project

    def _validated_legacy_current_fingerprints(
        self,
        candidates: Sequence[Mapping],
    ) -> list[dict]:
        current_fingerprints: list[dict] = []
        for candidate in candidates:
            path = candidate.get("path")
            reviewed_fingerprint = candidate.get("fingerprint")
            if not isinstance(path, str) or not path.strip():
                raise ImportReviewError("Legacy migration source path is missing")
            if not isinstance(reviewed_fingerprint, Mapping):
                raise ImportReviewError("Legacy migration source fingerprint is missing")
            try:
                project_store._fingerprint_key(reviewed_fingerprint)
                current_fingerprint = self.fingerprint_reader(path, self.duration_reader)
                project_store._fingerprint_key(current_fingerprint)
            except Exception as exc:
                raise ImportReviewError(
                    f"Legacy migration source is no longer valid: {path}"
                ) from exc
            if not audio_fingerprint.fingerprint_matches(
                reviewed_fingerprint,
                current_fingerprint,
            ):
                raise ImportReviewError(
                    f"Legacy migration source changed after preview: {path}"
                )
            if any(
                audio_fingerprint.fingerprint_matches(current_fingerprint, previous)
                for previous in current_fingerprints
            ):
                raise ImportConflictError("Legacy migration sources contain duplicate audio")
            current_fingerprints.append(copy.deepcopy(dict(current_fingerprint)))
        return current_fingerprints

    def _load_selected(self) -> dict:
        if not self.current_project_id:
            raise NoProjectSelectedError("Select an Audio Story project first")
        project = self.store.load_project(self.current_project_id)
        self._current_project = copy.deepcopy(project)
        return project

    def _select(self, project: Mapping) -> dict:
        selected = copy.deepcopy(dict(project))
        self.current_project_id = str(selected["project_id"])
        self._current_project = selected
        return copy.deepcopy(selected)

    def _audio_owner(self, fingerprint: Mapping) -> dict | None:
        owners = self._audio_owners(fingerprint)
        return owners[0] if owners else None

    def _audio_owners(self, fingerprint: Mapping) -> list[dict]:
        root = self.store.root
        if not root.is_dir():
            return []
        owners: list[dict] = []
        for directory in sorted(root.iterdir(), key=lambda item: item.name):
            if not directory.is_dir():
                continue
            try:
                project = self.store.load_project(directory.name)
            except project_store.ProjectStoreError:
                continue
            project_id = project["project_id"]
            memberships = project.get("audio_memberships")
            if isinstance(memberships, Mapping):
                for membership in memberships.values():
                    if not isinstance(membership, Mapping):
                        continue
                    stored = membership.get("fingerprint")
                    if audio_fingerprint.fingerprint_matches(fingerprint, stored):
                        owner = {
                            "project_id": project_id,
                            "chapter_id": str(membership.get("chapter_id", "")),
                        }
                        if owner not in owners:
                            owners.append(owner)
            chapters = project.get("chapters")
            if not isinstance(chapters, Mapping):
                continue
            for chapter_id, chapter in chapters.items():
                if not isinstance(chapter, Mapping):
                    continue
                audio = chapter.get("audio_reference")
                stored = audio.get("fingerprint") if isinstance(audio, Mapping) else None
                if audio_fingerprint.fingerprint_matches(fingerprint, stored):
                    owner = {"project_id": project_id, "chapter_id": str(chapter_id)}
                    if owner not in owners:
                        owners.append(owner)
        return owners

    def _rollback_import_if_owned(
        self,
        original: Mapping,
        transaction_states: Sequence[Mapping],
        expected_owners: Sequence[tuple[dict, dict]],
        pre_transaction_index: Mapping | None,
    ) -> bool:
        if not transaction_states:
            return False
        try:
            current = self.store.load_project(str(original["project_id"]))
        except project_store.ProjectStoreError:
            return False
        if not any(
            _same_saved_project_state(current, expected) for expected in transaction_states
        ):
            return False
        current_index = self._read_persisted_index()
        index_is_pre_transaction = (
            pre_transaction_index is not None
            and current_index == dict(pre_transaction_index)
        )
        if not index_is_pre_transaction and not self._persisted_index_matches_manifests():
            return False
        for fingerprint, expected_owner in expected_owners:
            if any(owner != expected_owner for owner in self._audio_owners(fingerprint)):
                return False
            if any(owner != expected_owner for owner in self._indexed_owners(fingerprint)):
                return False
        self._restore_project_snapshot(original, index_snapshot=pre_transaction_index)
        return True

    def _read_persisted_index(self) -> dict | None:
        path = self.store.root / "project_index.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        return copy.deepcopy(dict(payload)) if isinstance(payload, Mapping) else None

    def _persisted_index_matches_manifests(self) -> bool:
        path = self.store.root / "project_index.json"
        try:
            persisted_index = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return False
        projects: dict[str, dict] = {}
        audio_owners: dict[str, dict] = {}
        if self.store.root.is_dir():
            for directory in sorted(self.store.root.iterdir(), key=lambda item: item.name):
                if not directory.is_dir():
                    continue
                try:
                    project = self.store.load_project(directory.name)
                except project_store.ProjectStoreError:
                    continue
                project_id = project["project_id"]
                projects[project_id] = {
                    "name": project["name"],
                    "updated_at": project["updated_at"],
                }
                for key, membership in project_store._project_audio_memberships(project).items():
                    audio_owners.setdefault(
                        key,
                        {
                            "project_id": project_id,
                            "chapter_id": membership["chapter_id"],
                            "fingerprint": membership["fingerprint"],
                        },
                    )
        return persisted_index == {"projects": projects, "audio_owners": audio_owners}

    def _indexed_owners(self, fingerprint: Mapping) -> list[dict]:
        path = self.store.root / "project_index.json"
        if not path.is_file():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return []
        stored = payload.get("audio_owners") if isinstance(payload, Mapping) else None
        if not isinstance(stored, Mapping):
            return []
        owners: list[dict] = []
        for value in stored.values():
            if not isinstance(value, Mapping):
                continue
            if not audio_fingerprint.fingerprint_matches(fingerprint, value.get("fingerprint")):
                continue
            owner = {
                "project_id": str(value.get("project_id", "")),
                "chapter_id": str(value.get("chapter_id", "")),
            }
            if owner not in owners:
                owners.append(owner)
        return owners

    def _restore_project_snapshot(
        self,
        project: Mapping,
        *,
        index_snapshot: Mapping | None = None,
    ) -> None:
        project_directory = self.store._project_directory(str(project["project_id"]))
        with project_store._project_lock(project_directory):
            project_store._atomic_write_json(
                self.store.project_path(str(project["project_id"])),
                copy.deepcopy(dict(project)),
                backup_validator=lambda _payload: False,
            )
            self._write_backup_snapshot(project)
            if index_snapshot is None:
                self.store.rebuild_index()
            else:
                project_store._atomic_write_json(
                    self.store.root / "project_index.json",
                    copy.deepcopy(dict(index_snapshot)),
                    backup_validator=lambda _payload: False,
                )

    def _write_backup_snapshot(self, project: Mapping) -> None:
        primary = self.store.project_path(str(project["project_id"]))
        project_store._atomic_write_json(
            primary.with_suffix(primary.suffix + ".bak"),
            copy.deepcopy(dict(project)),
            backup_validator=lambda _payload: False,
        )

    @staticmethod
    def _require_chapter(project: Mapping, chapter_id: str) -> dict:
        chapters = project.get("chapters")
        if not isinstance(chapters, Mapping) or chapter_id not in chapters:
            raise KeyError(f"Unknown chapter: {chapter_id}")
        return copy.deepcopy(dict(chapters[chapter_id]))


def _mapping_list(value: Any) -> list[dict]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ImportReviewError("Import review entries must be a sequence")
    if not all(isinstance(item, Mapping) for item in value):
        raise ImportReviewError("Import review entries must be mappings")
    return [copy.deepcopy(dict(item)) for item in value]


def _legacy_audio_paths(session_payload: Mapping) -> list[str]:
    grouped = session_schema.normalize_audio_story_mode_settings(session_payload)
    audio = grouped.get("audio")
    if not isinstance(audio, Mapping):
        return []
    candidates: list[Any] = []
    sources = audio.get("audio_sources")
    if isinstance(sources, Sequence) and not isinstance(sources, (str, bytes, bytearray)):
        for source in sources:
            candidates.append(source.get("path") if isinstance(source, Mapping) else source)
    paths = audio.get("audio_paths")
    if isinstance(paths, Sequence) and not isinstance(paths, (str, bytes, bytearray)):
        candidates.extend(paths)
    candidates.append(audio.get("audio_path"))
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        path = str(candidate or "").strip()
        if not path:
            continue
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _root_transaction_lock(root: str | Path) -> threading.RLock:
    key = os.path.normcase(str(Path(root).resolve()))
    with _ROOT_LOCKS_GUARD:
        return _ROOT_LOCKS.setdefault(key, threading.RLock())


def _expected_saved_project(project: Mapping) -> dict:
    expected = project_models.normalize_project_manifest(project)
    try:
        revision = max(0, int(expected.get("manifest_revision", 0)))
    except (TypeError, ValueError):
        revision = 0
    expected["manifest_revision"] = revision + 1
    expected.pop("updated_at", None)
    return expected


def _same_saved_project_state(current: Mapping, expected: Mapping) -> bool:
    normalized = project_models.normalize_project_manifest(current)
    normalized.pop("updated_at", None)
    return normalized == dict(expected)
