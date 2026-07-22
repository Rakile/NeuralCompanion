from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from addons.audio_story_mode import audio_fingerprint, project_models


_PROJECT_LOCKS_GUARD = threading.Lock()
_PROJECT_LOCKS: dict[str, threading.RLock] = {}


class ProjectStoreError(RuntimeError):
    """Base error for Audio Story project persistence failures."""


class ProjectNotFoundError(ProjectStoreError):
    """Raised when a requested project does not exist."""


class ProjectCorruptError(ProjectStoreError):
    """Raised when neither a project primary nor its backup is readable."""


class ProjectConflictError(ProjectStoreError):
    """Raised when a transaction is based on a stale project manifest."""


class AudioOwnershipConflict(ProjectStoreError):
    """Raised when an audio fingerprint already belongs to another chapter."""


def _atomic_write_json(
    path: Path,
    payload: Any,
    *,
    backup_validator: Callable[[Any], bool] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        backup = path.with_suffix(path.suffix + ".bak")
        validator = backup_validator or _is_valid_document_payload
        if path.exists() and _is_valid_backup_source(path, validator):
            shutil.copy2(path, backup)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class StoryProjectStore:
    """Filesystem-backed storage for normalized Audio Story project manifests."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._index_path = self.root / "project_index.json"
        self.index_rebuild_pending: bool = False
        self.last_index_error: str = ""

    def create_project(self, name: str) -> dict:
        return self.save_project(project_models.new_project_manifest(name))

    def list_projects(self) -> list[dict]:
        index = self.rebuild_index()
        projects: list[dict] = []
        for project_id in index["projects"]:
            try:
                projects.append(self.load_project(project_id))
            except (ProjectNotFoundError, ProjectCorruptError):
                continue
        return sorted(projects, key=lambda project: (project["name"].casefold(), project["project_id"]))

    def load_project(self, project_id: str) -> dict:
        project, _used_backup = self.load_project_with_recovery(project_id)
        return project

    def load_project_with_recovery(self, project_id: str) -> tuple[dict, bool]:
        """Load without repairing disk and report whether the backup was selected."""
        path = self.project_path(project_id)
        if not path.exists() and not _backup_path(path).exists():
            raise ProjectNotFoundError(f"Audio Story project not found: {project_id}")
        for used_backup, candidate in ((False, path), (True, _backup_path(path))):
            try:
                with candidate.open("r", encoding="utf-8") as stream:
                    payload = json.load(stream)
                if not isinstance(payload, Mapping):
                    continue
                return project_models.normalize_project_manifest(payload), used_backup
            except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError, TypeError):
                continue
        raise ProjectCorruptError(f"Audio Story project is corrupt: {project_id}")

    def repair_project_primary(self, project_id: str, expected_revision: int) -> bool:
        """Explicitly republish a validated backup after a successful visible open."""
        path = self.project_path(project_id)
        with _project_lock(path.parent):
            try:
                with path.open("r", encoding="utf-8") as stream:
                    primary = json.load(stream)
                if _is_valid_project_manifest(primary):
                    return False
            except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError, TypeError):
                pass
            try:
                with _backup_path(path).open("r", encoding="utf-8") as stream:
                    backup = project_models.normalize_project_manifest(json.load(stream))
            except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
                raise ProjectCorruptError(
                    f"Audio Story project backup is corrupt: {project_id}"
                ) from exc
            if _manifest_revision(backup) != _manifest_revision(
                {"manifest_revision": expected_revision}
            ):
                raise ProjectConflictError(
                    "Audio Story recovery snapshot changed before repair"
                )
            _atomic_write_json(
                path,
                backup,
                backup_validator=lambda _payload: False,
            )
            return True

    def save_project(self, project: Mapping) -> dict:
        requested = project_models.normalize_project_manifest(project)
        project_id = requested["project_id"]
        with _project_lock(self._project_directory(project_id)):
            path = self.project_path(project_id)
            if path.exists() or _backup_path(path).exists():
                current = self.load_project(project_id)
                if _manifest_revision(requested) != _manifest_revision(current):
                    raise ProjectConflictError(
                        "Audio Story project changed; reload before saving"
                    )
            elif _manifest_revision(requested) != 0:
                raise ProjectConflictError(
                    "Audio Story project is missing; reload before saving"
                )
            normalized = self._save_project_manifest(requested)
            self.rebuild_index()
            return normalized

    def _save_project_manifest(self, project: Mapping) -> dict:
        normalized = project_models.normalize_project_manifest(project)
        normalized["manifest_revision"] = _manifest_revision(normalized) + 1
        normalized["updated_at"] = time.time()
        _atomic_write_json(
            self.project_path(normalized["project_id"]),
            normalized,
            backup_validator=_is_valid_project_manifest,
        )
        return normalized

    def _matching_published_manifest(self, project: Mapping) -> dict | None:
        expected = project_models.normalize_project_manifest(project)
        expected["manifest_revision"] = _manifest_revision(expected) + 1
        expected.pop("updated_at", None)
        try:
            published = self.load_project(expected["project_id"])
        except (ProjectNotFoundError, ProjectCorruptError):
            return None
        comparable = copy.deepcopy(published)
        comparable.pop("updated_at", None)
        return published if comparable == expected else None

    def project_path(self, project_id: str) -> Path:
        return self.root / _safe_component(project_id, "project id") / "project.json"

    def delete_project(self, project_id: str) -> dict:
        """Permanently remove one stored project without touching source audio files."""
        normalized_id = _safe_component(project_id, "project id")
        directory = self.root / normalized_id
        root = self.root.resolve()
        resolved_directory = directory.resolve()
        if (
            resolved_directory == root
            or not resolved_directory.is_relative_to(root)
            or directory.is_symlink()
        ):
            raise ProjectStoreError("Refusing to delete outside Audio Story project storage")
        with _project_lock(directory):
            project = self.load_project(normalized_id)
            if not directory.is_dir():
                raise ProjectNotFoundError(
                    f"Audio Story project not found: {normalized_id}"
                )
            shutil.rmtree(directory)
            self.rebuild_index()
            return project

    def load_story_bible(self, project_id: str, revision: int | None = None) -> dict:
        project = self.load_project(project_id)
        selected_revision = project["story_bible_revision"] if revision is None else _revision(revision)
        reference = (
            project.get("story_bible_ref")
            if revision is None
            else _story_bible_reference(selected_revision)
        )
        if not isinstance(reference, str) or not reference:
            raise FileNotFoundError(f"Story Bible revision {selected_revision} is unavailable")
        payload = _load_json_with_backup(
            _story_bible_path(self._project_directory(project_id), reference, selected_revision),
            require_mapping=True,
        )
        return copy.deepcopy(dict(payload))

    def register_audio(self, project_id: str, chapter_id: str, fingerprint: Mapping) -> None:
        owner = self.audio_owner(fingerprint)
        requested_owner = {"project_id": str(project_id), "chapter_id": str(chapter_id)}
        if owner is not None and owner != requested_owner:
            raise AudioOwnershipConflict(
                f"Audio already belongs to {owner['project_id']}/{owner['chapter_id']}"
            )
        project = self.load_project(project_id)
        memberships = project.get("audio_memberships")
        if not isinstance(memberships, Mapping):
            memberships = {}
        updated_memberships = copy.deepcopy(dict(memberships))
        updated_memberships[_fingerprint_key(fingerprint)] = {
            "chapter_id": _safe_component(chapter_id, "chapter id"),
            "fingerprint": copy.deepcopy(dict(fingerprint)),
        }
        project["audio_memberships"] = updated_memberships
        self.save_project(project)

    def audio_owner(self, fingerprint: Mapping) -> dict | None:
        _fingerprint_key(fingerprint)
        for owner in self.rebuild_index()["audio_owners"].values():
            if (
                isinstance(owner, Mapping)
                and isinstance(owner.get("fingerprint"), Mapping)
                and audio_fingerprint.fingerprint_matches(fingerprint, owner["fingerprint"])
            ):
                return {"project_id": owner["project_id"], "chapter_id": owner["chapter_id"]}
        return None

    def rebuild_index(self) -> dict:
        projects: dict[str, dict] = {}
        audio_owners: dict[str, dict] = {}
        if self.root.is_dir():
            for directory in sorted(self.root.iterdir(), key=lambda item: item.name):
                if not directory.is_dir():
                    continue
                path = directory / "project.json"
                try:
                    project = project_models.normalize_project_manifest(
                        _load_json_with_backup(path, require_mapping=True)
                    )
                except (OSError, ValueError, json.JSONDecodeError, TypeError):
                    continue
                project_id = project["project_id"]
                projects[project_id] = {
                    "name": project["name"],
                    "updated_at": project["updated_at"],
                }
                for key, membership in _project_audio_memberships(project).items():
                    audio_owners.setdefault(
                        key,
                        {
                            "project_id": project_id,
                            "chapter_id": membership["chapter_id"],
                            "fingerprint": membership["fingerprint"],
                        },
                    )
        index = {"projects": projects, "audio_owners": audio_owners}
        _atomic_write_json(self._index_path, index)
        self.index_rebuild_pending = False
        self.last_index_error = ""
        return index

    def load_chapter_document(
        self,
        project_id: str,
        chapter_id: str,
        kind: str,
        revision: int | None = None,
    ) -> dict | list:
        normalized_kind = _safe_component(kind, "document kind")
        if revision is None and normalized_kind == "analysis":
            project = self.load_project(project_id)
            chapter = project["chapters"].get(str(chapter_id), {})
            reference = chapter.get("stages", {}).get("story_analysis", {}).get("output_ref")
            if not isinstance(reference, str) or not reference:
                raise FileNotFoundError(f"No current analysis for chapter {chapter_id}")
            path = _analysis_path(self._project_directory(project_id), chapter_id, reference)
        else:
            selected_revision = _latest_revision(
                self._chapter_directory(project_id, chapter_id), normalized_kind
            ) if revision is None else _revision(revision)
            path = self._chapter_document_path(project_id, chapter_id, normalized_kind, selected_revision)
        payload = _load_json_with_backup(path)
        if not isinstance(payload, (Mapping, list)):
            raise ProjectCorruptError(f"Chapter document is not an object or list: {path}")
        return copy.deepcopy(dict(payload) if isinstance(payload, Mapping) else payload)

    def save_chapter_document(
        self,
        project_id: str,
        chapter_id: str,
        kind: str,
        revision: int,
        payload: Mapping | Sequence,
    ) -> str:
        if isinstance(payload, (str, bytes, bytearray)) or not isinstance(payload, (Mapping, Sequence)):
            raise TypeError("Chapter document payload must be a mapping or sequence")
        normalized_kind = _safe_component(kind, "document kind")
        selected_revision = _revision(revision)
        _atomic_write_json(
            self._chapter_document_path(project_id, chapter_id, normalized_kind, selected_revision),
            payload,
            backup_validator=_is_valid_document_payload,
        )
        return _chapter_document_reference(chapter_id, normalized_kind, selected_revision)

    def commit_analysis_transaction(
        self,
        project: Mapping,
        chapter_id: str,
        analysis: Mapping,
        story_bible: Mapping,
    ) -> dict:
        requested = project_models.normalize_project_manifest(project)
        with _project_lock(self._project_directory(requested["project_id"])):
            current = self.load_project(requested["project_id"])
            if _manifest_revision(requested) != _manifest_revision(current):
                raise ProjectConflictError("Audio Story project changed; reload before committing analysis")
            normalized_chapter_id = _safe_component(chapter_id, "chapter id")
            if normalized_chapter_id not in current["chapters"]:
                raise KeyError(f"Unknown chapter: {chapter_id}")
            normalized = copy.deepcopy(requested)
            revision = self._next_transaction_revision(
                normalized["project_id"], normalized_chapter_id, current
            )
            analysis_ref = self.save_chapter_document(
                normalized["project_id"], normalized_chapter_id, "analysis", revision, analysis
            )
            story_bible_ref = _story_bible_reference(revision)
            _atomic_write_json(
                self._project_directory(normalized["project_id"]) / story_bible_ref, story_bible
            )
            normalized["story_bible_revision"] = revision
            normalized["story_bible_ref"] = story_bible_ref
            normalized["chapters"][normalized_chapter_id]["stages"]["story_analysis"]["output_ref"] = (
                analysis_ref
            )
            scene_checkpoint = normalized["chapters"][normalized_chapter_id]["stages"][
                "scene_planning"
            ]
            if scene_checkpoint.get("status") == "completed":
                scene_checkpoint["output_ref"] = analysis_ref
            try:
                return self.save_project(normalized)
            except Exception as exc:
                committed = self._matching_published_manifest(normalized)
                if committed is None:
                    raise
                self.index_rebuild_pending = True
                self.last_index_error = str(exc or type(exc).__name__)
            return committed

    def commit_story_bible_rebuild(
        self,
        project: Mapping,
        story_bible: Mapping,
    ) -> dict:
        """Publish a rebuilt Story Bible and its manifest pointer atomically."""
        if not isinstance(story_bible, Mapping):
            raise TypeError("Rebuilt Story Bible must be a mapping")
        requested = project_models.normalize_project_manifest(project)
        project_id = requested["project_id"]
        with _project_lock(self._project_directory(project_id)):
            current = self.load_project(project_id)
            if _manifest_revision(requested) != _manifest_revision(current):
                raise ProjectConflictError(
                    "Audio Story project changed; reload before rebuilding continuity"
                )
            revision = int(current.get("story_bible_revision", 0) or 0) + 1
            story_bible_path = self._project_directory(project_id) / _story_bible_reference(
                revision
            )
            while _version_exists(story_bible_path):
                revision += 1
                story_bible_path = self._project_directory(
                    project_id
                ) / _story_bible_reference(revision)
            story_bible_ref = _story_bible_reference(revision)
            _atomic_write_json(story_bible_path, copy.deepcopy(dict(story_bible)))
            requested["story_bible_revision"] = revision
            requested["story_bible_ref"] = story_bible_ref
            return self.save_project(requested)

    def persist_project_image(
        self,
        project_id: str,
        chapter_id: str,
        scene_id: str,
        source_path: str | Path,
    ) -> str:
        source = Path(source_path)
        if not source.is_file():
            raise FileNotFoundError(str(source))
        suffix = source.suffix or ".bin"
        filename = f"{_safe_component(scene_id, 'scene id')}{suffix}"
        destination = self._chapter_directory(project_id, chapter_id) / "images" / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            with source.open("rb") as input_stream, temporary.open("wb") as output_stream:
                shutil.copyfileobj(input_stream, output_stream)
                output_stream.flush()
                os.fsync(output_stream.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return f"chapters/{_safe_component(chapter_id, 'chapter id')}/images/{filename}"

    def persist_project_image_attempt(
        self,
        project_id: str,
        chapter_id: str,
        scene_id: str,
        source_path: str | Path,
        attempt_id: str,
    ) -> dict:
        """Copy one provider result to a unique immutable attempt artifact."""
        source = Path(source_path)
        if not source.is_file():
            raise FileNotFoundError(str(source))
        scene_component = _safe_component(scene_id, "scene id")
        attempt_component = _safe_component(attempt_id, "image attempt id")
        suffix = source.suffix or ".bin"
        filename = f"{scene_component}.{attempt_component}{suffix}"
        destination = self._chapter_directory(project_id, chapter_id) / "images" / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(str(destination))
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        digest = hashlib.sha256()
        try:
            with source.open("rb") as input_stream, temporary.open("xb") as output_stream:
                for block in iter(lambda: input_stream.read(1024 * 1024), b""):
                    output_stream.write(block)
                    digest.update(block)
                output_stream.flush()
                os.fsync(output_stream.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return {
            "output_ref": (
                f"chapters/{_safe_component(chapter_id, 'chapter id')}/images/{filename}"
            ),
            "output_fingerprint": digest.hexdigest(),
            "image_path": str(destination),
        }

    def resolve_project_image(
        self, project_id: str, chapter_id: str, reference: str
    ) -> Path:
        chapter_component = _safe_component(chapter_id, "chapter id")
        prefix = f"chapters/{chapter_component}/images/"
        if (
            not isinstance(reference, str)
            or not reference.startswith(prefix)
            or "\\" in reference
        ):
            raise ProjectCorruptError("Invalid project image reference")
        path = _validated_reference_path(
            self._project_directory(project_id), reference, reference
        )
        if not path.is_file():
            raise FileNotFoundError(str(path))
        return path

    def _project_directory(self, project_id: str) -> Path:
        return self.project_path(project_id).parent

    def _chapter_directory(self, project_id: str, chapter_id: str) -> Path:
        return self._project_directory(project_id) / "chapters" / _safe_component(chapter_id, "chapter id")

    def _chapter_document_path(self, project_id: str, chapter_id: str, kind: str, revision: int) -> Path:
        return self._chapter_directory(project_id, chapter_id) / f"{kind}.{revision}.json"

    def _next_transaction_revision(self, project_id: str, chapter_id: str, project: Mapping) -> int:
        revision = project["story_bible_revision"] + 1
        while any(
            _version_exists(path)
            for path in (
                self._chapter_document_path(project_id, chapter_id, "analysis", revision),
                self._project_directory(project_id) / _story_bible_reference(revision),
            )
        ):
            revision += 1
        return revision


def _backup_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".bak")


def _is_valid_backup_source(path: Path, validator: Callable[[Any], bool] | None) -> bool:
    if validator is None:
        return True
    try:
        with path.open("r", encoding="utf-8") as stream:
            return validator(json.load(stream))
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def _is_valid_project_manifest(payload: Any) -> bool:
    if not isinstance(payload, Mapping):
        return False
    required = {
        "schema_version",
        "project_id",
        "name",
        "created_at",
        "updated_at",
        "story_bible_revision",
        "autosave_revision",
        "chapter_order",
        "chapters",
        "archived_chapter_ids",
    }
    return required.issubset(payload) and isinstance(payload.get("project_id"), str)


def _is_valid_document_payload(payload: Any) -> bool:
    return isinstance(payload, (Mapping, list))


def _manifest_revision(project: Mapping) -> int:
    try:
        return max(0, int(project.get("manifest_revision", 0)))
    except (TypeError, ValueError):
        return 0


def _version_exists(path: Path) -> bool:
    return path.exists() or _backup_path(path).exists()


def _project_lock(project_directory: Path) -> threading.RLock:
    key = str(project_directory.resolve())
    with _PROJECT_LOCKS_GUARD:
        lock = _PROJECT_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PROJECT_LOCKS[key] = lock
        return lock


def _load_json_with_backup(path: Path, *, require_mapping: bool = False) -> Any:
    for candidate in (path, _backup_path(path)):
        try:
            with candidate.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
            if require_mapping and not isinstance(payload, Mapping):
                continue
            return payload
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            continue
    raise ValueError(f"No valid JSON primary or backup for {path}")


def _safe_component(value: object, label: str) -> str:
    component = str(value).strip()
    if not component or component in {".", ".."} or Path(component).name != component:
        raise ValueError(f"Invalid {label}: {value!r}")
    return component


def _revision(value: int) -> int:
    revision = int(value)
    if revision < 1:
        raise ValueError("Document revision must be at least 1")
    return revision


def _story_bible_reference(revision: int) -> str:
    return f"story_bible.{_revision(revision)}.json"


def _story_bible_path(project_directory: Path, reference: str, revision: int) -> Path:
    return _validated_reference_path(project_directory, reference, _story_bible_reference(revision))


def _analysis_path(project_directory: Path, chapter_id: str, reference: str) -> Path:
    chapter_component = _safe_component(chapter_id, "chapter id")
    prefix = f"chapters/{chapter_component}/analysis."
    if not isinstance(reference, str) or not reference.startswith(prefix) or not reference.endswith(".json"):
        raise ProjectCorruptError("Invalid chapter analysis reference")
    revision_text = reference[len(prefix):-len(".json")]
    try:
        expected = _chapter_document_reference(chapter_component, "analysis", _revision(int(revision_text)))
    except ValueError as exc:
        raise ProjectCorruptError("Invalid chapter analysis reference") from exc
    return _validated_reference_path(project_directory, reference, expected)


def _validated_reference_path(project_directory: Path, reference: str, expected: str) -> Path:
    if not isinstance(reference, str) or reference != expected or "\\" in reference:
        raise ProjectCorruptError("Invalid project document reference")
    relative = Path(reference)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ProjectCorruptError("Invalid project document reference")
    root = project_directory.resolve()
    resolved = (project_directory / relative).resolve()
    if not resolved.is_relative_to(root):
        raise ProjectCorruptError("Project document reference escapes its project")
    return resolved


def _chapter_document_reference(chapter_id: str, kind: str, revision: int) -> str:
    return f"chapters/{_safe_component(chapter_id, 'chapter id')}/{kind}.{_revision(revision)}.json"


def _latest_revision(directory: Path, kind: str) -> int:
    revisions: list[int] = []
    if directory.is_dir():
        for path in directory.glob(f"{kind}.*.json"):
            parts = path.stem.rsplit(".", 1)
            if len(parts) == 2:
                try:
                    revisions.append(_revision(int(parts[1])))
                except ValueError:
                    continue
    if not revisions:
        raise FileNotFoundError(f"No {kind} document revisions are available")
    return max(revisions)


def _fingerprint_key(fingerprint: Mapping) -> str:
    if not isinstance(fingerprint, Mapping):
        raise TypeError("Audio fingerprint must be a mapping")
    try:
        algorithm = str(fingerprint["algorithm"])
        digest = str(fingerprint["digest"])
        size_bytes = int(fingerprint["size_bytes"])
        duration_ms = int(fingerprint["duration_ms"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Audio fingerprint is incomplete") from exc
    if not algorithm or not digest or size_bytes < 0 or duration_ms <= 0:
        raise ValueError("Audio fingerprint is invalid")
    return f"{algorithm}:{digest}:{size_bytes}:{duration_ms}"


def _project_audio_memberships(project: Mapping) -> dict[str, dict]:
    memberships: dict[str, dict] = {}
    stored = project.get("audio_memberships")
    if isinstance(stored, Mapping):
        for key, value in stored.items():
            if isinstance(value, Mapping):
                chapter_id = value.get("chapter_id")
                fingerprint = value.get("fingerprint")
                try:
                    memberships[_fingerprint_key(fingerprint)] = {
                        "chapter_id": _safe_component(chapter_id, "chapter id"),
                        "fingerprint": copy.deepcopy(dict(fingerprint)),
                    }
                except (TypeError, ValueError):
                    continue
    for chapter_id, chapter in project.get("chapters", {}).items():
        if not isinstance(chapter, Mapping):
            continue
        fingerprint = chapter.get("audio_reference", {}).get("fingerprint")
        try:
            memberships.setdefault(
                _fingerprint_key(fingerprint),
                {
                    "chapter_id": _safe_component(chapter_id, "chapter id"),
                    "fingerprint": copy.deepcopy(dict(fingerprint)),
                },
            )
        except (AttributeError, TypeError, ValueError):
            continue
    return memberships
