from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from addons.identity_artifacts.attestations import (
    IdentityRelayDecisionStore,
    IdentityRelaySnapshotAuthorizationStore,
)
from addons.identity_artifacts.importer import IdentityImportResult, import_identity_artifact
from addons.identity_artifacts.normalized_model import (
    NORMALIZED_SCHEMA_VERSION,
    NORMALIZER_REVISION,
    NormalizedIdentityModel,
    RuntimeLayer,
    SubjectClass,
    normalized_identity_digest,
    normalized_identity_from_dict,
)
from addons.identity_artifacts.normalizer import normalize_identity_artifact
from addons.identity_artifacts.retrieval_index import IdentitySemanticIndex


ARTIFACT_REF_RE = re.compile(r"library/([0-9a-f]{64})\.json\Z")
_GUARD_CONTEXT_UNSET = object()
_PROVENANCE_FIELDS = ("source_type", "source_path", "provider_label", "imported_at")
_SOURCE_TYPES = {"file", "pasted", "legacy"}
_NORMALIZED_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")


class NormalizedDerivativeError(ValueError):
    def __init__(self, failure_code: str, message: str):
        super().__init__(message)
        self.failure_code = failure_code


@dataclass(frozen=True, slots=True)
class StoredIdentityArtifact:
    artifact_ref: str
    artifact_hash: str
    canonical_path: Path
    derived_path: Path
    canonical_created: bool

    @property
    def artifact_id(self) -> str:
        """Temporary inspection-UI alias; values remain strict artifact refs."""
        return self.artifact_ref


@dataclass(frozen=True, slots=True)
class LibraryRefreshResult:
    migrated_refs: tuple[str, ...]
    reused_refs: tuple[str, ...]
    rebuilt_refs: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ArtifactResolution:
    artifact_ref: str
    artifact_hash: str | None
    hot_identity_text: str
    failure_code: str | None
    normalized_digest: str = ""


@dataclass(frozen=True, slots=True)
class ArtifactDeleteResult:
    artifact_ref: str
    deleted: bool
    blocked_by: tuple[str, ...]
    failure_code: str | None
    removed_derivatives: tuple[str, ...] = ()
    failure_details: tuple[str, ...] = ()


class IdentityArtifactStore:
    def __init__(self, root_dir: str | Path):
        self.root_dir = Path(root_dir)
        self.library_dir = self.root_dir / "library"
        self.derived_dir = self.root_dir / "derived"
        self.index_path = self.root_dir / "index.json"
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self.derived_dir.mkdir(parents=True, exist_ok=True)

    def save_import(self, result: IdentityImportResult) -> StoredIdentityArtifact:
        artifact_hash = hashlib.sha256(result.raw.raw_bytes).hexdigest()
        if result.raw.artifact_hash != artifact_hash:
            raise ValueError("Import artifact hash does not match raw bytes.")
        artifact_ref = f"library/{artifact_hash}.json"
        _verified_hash, canonical_path = self._canonical_path(artifact_ref)
        canonical_created = False
        try:
            with canonical_path.open("xb") as handle:
                handle.write(result.raw.raw_bytes)
            canonical_created = True
        except FileExistsError:
            if canonical_path.read_bytes() != result.raw.raw_bytes:
                raise RuntimeError("Canonical artifact hash collision.")

        existing_record = self._read_derived(artifact_hash)
        indexed_metadata = self._read_index_metadata().get(artifact_hash)
        provenance_candidates = (
            (result.raw.metadata_dict(),)
            if canonical_created
            else (self._record_metadata(existing_record), indexed_metadata, result.raw.metadata_dict())
        )
        authoritative_result = self._import_canonical_result(
            result.raw.raw_bytes,
            artifact_ref,
            *provenance_candidates,
        )
        derived_path = self._derived_path(artifact_hash)
        if canonical_created or not self._derived_matches_canonical(
            existing_record, authoritative_result
        ):
            self._write_derived(authoritative_result)
        self._write_index()
        return StoredIdentityArtifact(
            artifact_ref=artifact_ref,
            artifact_hash=artifact_hash,
            canonical_path=canonical_path,
            derived_path=derived_path,
            canonical_created=canonical_created,
        )

    def refresh_library(self, *, legacy_root: str | Path | None = None) -> LibraryRefreshResult:
        migrated_refs: list[str] = []
        reused_refs: list[str] = []
        rebuilt_refs: list[str] = []
        warnings: list[str] = []
        indexed_metadata = self._read_index_metadata()

        if legacy_root is not None:
            legacy_paths = self._legacy_raw_paths(Path(legacy_root))
            if legacy_paths:
                warnings.append(
                    "Legacy artifacts may have already lost original byte normalization; "
                    "migration preserves the legacy raw.txt bytes exactly."
                )
            for raw_path in legacy_paths:
                try:
                    result = import_identity_artifact(
                        raw_path.read_bytes(), source_type="legacy", source_path=str(raw_path)
                    )
                    stored = self.save_import(result)
                except OSError as exc:
                    warnings.append(f"Could not migrate legacy artifact {raw_path.name}: {exc}")
                    continue
                if stored.canonical_created:
                    migrated_refs.append(stored.artifact_ref)
                else:
                    reused_refs.append(stored.artifact_ref)

        for canonical_path in sorted(self.library_dir.glob("*.json")):
            artifact_ref = f"library/{canonical_path.name}"
            try:
                artifact_hash, safe_path = self._canonical_path(artifact_ref)
            except ValueError:
                continue
            try:
                raw_bytes = safe_path.read_bytes()
            except OSError as exc:
                warnings.append(f"Could not read canonical artifact {canonical_path.name}: {exc}")
                continue
            if hashlib.sha256(raw_bytes).hexdigest() != artifact_hash:
                warnings.append(f"Canonical artifact hash mismatch: {artifact_ref}")
                continue
            record = self._read_derived(artifact_hash)
            result = self._import_canonical_result(
                raw_bytes,
                artifact_ref,
                self._record_metadata(record),
                indexed_metadata.get(artifact_hash),
            )
            if not self._derived_matches_canonical(record, result):
                self._write_derived(result)
                rebuilt_refs.append(artifact_ref)

        self._write_index()
        return LibraryRefreshResult(
            migrated_refs=tuple(migrated_refs),
            reused_refs=tuple(reused_refs),
            rebuilt_refs=tuple(rebuilt_refs),
            warnings=tuple(warnings),
        )

    def resolve_artifact(self, artifact_ref: str) -> ArtifactResolution:
        try:
            artifact_hash, canonical_path = self._canonical_path(artifact_ref)
        except ValueError:
            return ArtifactResolution(str(artifact_ref or ""), None, "", "invalid")
        if not canonical_path.is_file():
            return ArtifactResolution(artifact_ref, artifact_hash, "", "missing")
        try:
            raw_bytes = canonical_path.read_bytes()
        except OSError:
            return ArtifactResolution(artifact_ref, artifact_hash, "", "unreadable")
        if hashlib.sha256(raw_bytes).hexdigest() != artifact_hash:
            return ArtifactResolution(artifact_ref, artifact_hash, "", "corrupt")

        result = import_identity_artifact(raw_bytes, source_type="file", source_path=artifact_ref)
        if result.structured is None:
            return ArtifactResolution(artifact_ref, artifact_hash, "", "invalid")
        hot_identity_text = result.structured.hot_identity_text
        try:
            model = self.load_normalized(artifact_ref)
        except NormalizedDerivativeError as exc:
            return ArtifactResolution(
                artifact_ref,
                artifact_hash,
                hot_identity_text,
                exc.failure_code,
            )
        digest = normalized_identity_digest(model)
        if not self._has_usable_normalized_identity(model):
            return ArtifactResolution(
                artifact_ref,
                artifact_hash,
                hot_identity_text,
                "empty_normalized_identity",
                digest,
            )
        attestation = IdentityRelayDecisionStore(self.root_dir).load(
            artifact_hash
        ).subject_attestation
        if (
            attestation is None
            or not attestation.approved
            or attestation.artifact_hash != artifact_hash
            or attestation.normalizer_revision != NORMALIZER_REVISION
        ):
            failure_code = "attestation_required"
        elif not attestation.normalized_digest:
            failure_code = "attestation_digest_required"
        elif attestation.normalized_digest != digest:
            failure_code = "attestation_digest_mismatch"
        elif attestation.subject_class != SubjectClass.ASSISTANT_SELF:
            failure_code = "subject_not_assistant_self"
        else:
            failure_code = None
        return ArtifactResolution(
            artifact_ref,
            artifact_hash,
            hot_identity_text,
            failure_code,
            digest,
        )

    @staticmethod
    def _has_usable_normalized_identity(model: NormalizedIdentityModel) -> bool:
        runtime_ids = set(model.kernel_record_ids) | set(model.retrievable_record_ids)
        return any(
            record.record_id in runtime_ids
            and record.runtime_layer in {RuntimeLayer.KERNEL, RuntimeLayer.RETRIEVABLE}
            and bool(record.source_text.strip())
            and record.review_state != "quarantined"
            for record in model.records
        )

    def load_normalized(self, artifact_ref: str) -> NormalizedIdentityModel:
        artifact_hash, _canonical_path = self._canonical_path(artifact_ref)
        self.load_raw_bytes(artifact_ref)
        path = self._normalized_path(artifact_hash)
        invalid_path = self._normalized_invalid_path(artifact_hash)
        if invalid_path.exists():
            raise NormalizedDerivativeError(
                "normalized_rebuild_review_required",
                "Normalized derivative is quarantined pending explicit rebuild and review.",
            )
        if not path.exists():
            return self.rebuild_normalized(artifact_ref)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            model_payload = payload["normalized_model"]
            declared_digest = payload.get("normalized_digest")
            if (
                payload.get("artifact_hash") != artifact_hash
                or payload.get("normalizer_revision") != NORMALIZER_REVISION
                or payload.get("schema_version") != NORMALIZED_SCHEMA_VERSION
                or not isinstance(payload.get("created_at"), str)
                or not isinstance(payload.get("review_state"), str)
                or not isinstance(model_payload, dict)
                or not isinstance(declared_digest, str)
                or _NORMALIZED_DIGEST_RE.fullmatch(declared_digest) is None
            ):
                raise ValueError("Normalized derivative metadata mismatch")
            model = normalized_identity_from_dict(model_payload)
            if (
                model.envelope.artifact_hash != artifact_hash
                or model.normalizer_revision != NORMALIZER_REVISION
                or model.schema_version != NORMALIZED_SCHEMA_VERSION
            ):
                raise ValueError("Normalized model metadata mismatch")
            actual_digest = normalized_identity_digest(model)
            if actual_digest != declared_digest:
                raise ValueError("Normalized derivative digest mismatch")
            canonical_model = self._normalize_canonical(artifact_ref)
            if normalized_identity_digest(canonical_model) != actual_digest:
                raise ValueError("Normalized derivative differs from canonical identity")
            return model
        except (
            OSError,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ) as exc:
            self._invalidate_normalized_derivative(artifact_hash)
            raise NormalizedDerivativeError(
                "normalized_derivative_mismatch",
                "Normalized derivative does not match canonical identity; rebuild and review required.",
            ) from exc

    def _invalidate_normalized_derivative(self, artifact_hash: str) -> None:
        self._atomic_write_json(
            self._normalized_invalid_path(artifact_hash),
            {
                "artifact_hash": artifact_hash,
                "normalizer_revision": NORMALIZER_REVISION,
                "failure_code": "normalized_derivative_mismatch",
                "invalidated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        IdentityRelayDecisionStore(self.root_dir).delete(artifact_hash)

    def rebuild_normalized(self, artifact_ref: str) -> NormalizedIdentityModel:
        artifact_hash, _canonical_path = self._canonical_path(artifact_ref)
        model = self._normalize_canonical(artifact_ref)
        payload = {
            "artifact_hash": artifact_hash,
            "normalizer_revision": NORMALIZER_REVISION,
            "schema_version": NORMALIZED_SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "review_state": "pending_attestation",
            "normalized_digest": normalized_identity_digest(model),
            "normalized_model": model.to_dict(),
        }
        self._atomic_write_json(self._normalized_path(artifact_hash), payload)
        self._normalized_invalid_path(artifact_hash).unlink(missing_ok=True)
        return model

    def _normalize_canonical(self, artifact_ref: str) -> NormalizedIdentityModel:
        artifact_hash, _canonical_path = self._canonical_path(artifact_ref)
        raw_bytes = self.load_raw_bytes(artifact_ref)
        legacy_record = self._read_derived(artifact_hash)
        result = self._import_canonical_result(
            raw_bytes,
            artifact_ref,
            self._record_metadata(legacy_record),
            self._read_index_metadata().get(artifact_hash),
        )
        return normalize_identity_artifact(result)

    def list_artifacts(self) -> list[dict[str, Any]]:
        """Compatibility adapter for the existing inspection tab, using strict refs."""
        self.refresh_library()
        artifacts: list[dict[str, Any]] = []
        for canonical_path in sorted(self.library_dir.glob("*.json")):
            artifact_hash = canonical_path.stem
            artifact_ref = f"library/{canonical_path.name}"
            if not self._is_verified_canonical(artifact_ref):
                continue
            record = self._read_derived(artifact_hash)
            if record is None:
                continue
            metadata = dict(record["metadata"])
            metadata["artifact_id"] = metadata["artifact_ref"]
            artifacts.append(metadata)
        return sorted(artifacts, key=lambda item: str(item.get("imported_at") or ""), reverse=True)

    def load_metadata(self, artifact_ref: str) -> dict[str, Any]:
        metadata = dict(self._current_derived_record(artifact_ref)["metadata"])
        metadata["artifact_id"] = metadata["artifact_ref"]
        return metadata

    def load_raw_text(self, artifact_ref: str) -> str:
        raw_bytes = self.load_raw_bytes(artifact_ref)
        return import_identity_artifact(raw_bytes, source_type="file", source_path=artifact_ref).raw.raw_text

    def load_structured(self, artifact_ref: str) -> dict[str, Any]:
        structured = self._current_derived_record(artifact_ref).get("structured")
        return dict(structured) if isinstance(structured, dict) else {}

    def delete_artifact(
        self,
        artifact_ref: str,
        *,
        active_persona_ref: str | None | object = _GUARD_CONTEXT_UNSET,
        presets_dir: str | Path | None | object = _GUARD_CONTEXT_UNSET,
        loaded_session_refs: object = _GUARD_CONTEXT_UNSET,
        before_commit: Callable[[], object] | None = None,
    ) -> ArtifactDeleteResult:
        try:
            artifact_hash, canonical_path = self._canonical_path(artifact_ref)
        except ValueError:
            return ArtifactDeleteResult(str(artifact_ref or ""), False, (), "invalid")
        if not canonical_path.is_file():
            return ArtifactDeleteResult(artifact_ref, False, (), "missing")
        if (
            active_persona_ref is _GUARD_CONTEXT_UNSET
            or presets_dir is _GUARD_CONTEXT_UNSET
            or loaded_session_refs is _GUARD_CONTEXT_UNSET
        ):
            return ArtifactDeleteResult(
                artifact_ref,
                False,
                ("guard_context_required",),
                "guard_context_required",
            )

        blocked_by: list[str] = []
        if active_persona_ref == artifact_ref:
            blocked_by.append("active_persona")
        if not isinstance(loaded_session_refs, (list, tuple, set, frozenset)):
            return ArtifactDeleteResult(
                artifact_ref,
                False,
                ("loaded_session_context_invalid",),
                "guard_context_required",
            )
        if artifact_ref in {
            str(item or "") for item in loaded_session_refs if str(item or "")
        }:
            blocked_by.append("loaded_session")
        if presets_dir is not None:
            for preset_path in sorted(Path(presets_dir).glob("*.json")):
                try:
                    preset = json.loads(preset_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                    blocked_by.append(f"preset:{preset_path.name}")
                    continue
                if isinstance(preset, dict) and preset.get("identity_relay_ref") == artifact_ref:
                    blocked_by.append(f"preset:{preset_path.name}")
        if blocked_by:
            return ArtifactDeleteResult(artifact_ref, False, tuple(blocked_by), None)
        if before_commit is not None:
            if not callable(before_commit):
                return ArtifactDeleteResult(
                    artifact_ref,
                    False,
                    ("delete_commit_boundary_invalid",),
                    "guard_context_required",
                )
            try:
                precommit_blockers = before_commit()
            except Exception as exc:
                return ArtifactDeleteResult(
                    artifact_ref,
                    False,
                    (),
                    "unreadable",
                    failure_details=(
                        f"delete_commit_boundary:{type(exc).__name__}",
                    ),
                )
            if not isinstance(
                precommit_blockers,
                (list, tuple, set, frozenset),
            ):
                return ArtifactDeleteResult(
                    artifact_ref,
                    False,
                    ("delete_commit_boundary_invalid",),
                    "guard_context_required",
                )
            precommit_blockers = tuple(
                str(item) for item in precommit_blockers if str(item)
            )
            if precommit_blockers:
                return ArtifactDeleteResult(
                    artifact_ref,
                    False,
                    precommit_blockers,
                    None,
                )

        removed: list[str] = []
        cleanup_target = ""
        try:
            cleanup_target = "derived_record"
            derived_path = self._derived_path(artifact_hash)
            if derived_path.exists():
                derived_path.unlink()
                removed.append(cleanup_target)

            cleanup_target = "normalized_versions"
            normalized_versions = self.derived_dir / artifact_hash
            if normalized_versions.exists():
                shutil.rmtree(normalized_versions)
                removed.append(cleanup_target)

            cleanup_target = "attestation_review_state"
            if IdentityRelayDecisionStore(self.root_dir).delete(artifact_hash):
                removed.append(cleanup_target)

            cleanup_target = "snapshot_authorizations"
            authorization_cleanup = IdentityRelaySnapshotAuthorizationStore(
                self.root_dir
            ).delete_for_artifact_with_report(artifact_hash)
            if authorization_cleanup.removed_count:
                removed.append(cleanup_target)
            if authorization_cleanup.failure_details:
                failure_code = "partial_delete" if removed else "unreadable"
                return ArtifactDeleteResult(
                    artifact_ref,
                    False,
                    (),
                    failure_code,
                    tuple(removed),
                    tuple(
                        f"{cleanup_target}:{detail}"
                        for detail in authorization_cleanup.failure_details
                    ),
                )

            cleanup_target = "semantic_index"
            if IdentitySemanticIndex(self.root_dir / "indexes").delete(artifact_hash):
                removed.append(cleanup_target)

            cleanup_target = "library_index"
            self._write_index()

            cleanup_target = "canonical_artifact"
            canonical_path.unlink()
        except OSError as exc:
            failure_code = "partial_delete" if removed else "unreadable"
            return ArtifactDeleteResult(
                artifact_ref,
                False,
                (),
                failure_code,
                tuple(removed),
                (f"{cleanup_target}:{type(exc).__name__}",),
            )
        return ArtifactDeleteResult(
            artifact_ref,
            True,
            (),
            None,
            tuple(removed),
            (),
        )

    def load_raw_bytes(self, artifact_ref: str) -> bytes:
        artifact_hash, canonical_path = self._canonical_path(artifact_ref)
        raw_bytes = canonical_path.read_bytes()
        if hashlib.sha256(raw_bytes).hexdigest() != artifact_hash:
            raise ValueError("Canonical artifact hash mismatch.")
        return raw_bytes

    def _hash_for_ref(self, artifact_ref: str) -> str:
        match = ARTIFACT_REF_RE.fullmatch(str(artifact_ref or ""))
        return match.group(1) if match else ""

    def _canonical_path(self, artifact_ref: str) -> tuple[str, Path]:
        artifact_hash = self._hash_for_ref(artifact_ref)
        if not artifact_hash:
            raise ValueError("invalid")
        path = (self.root_dir / artifact_ref).resolve()
        if path.parent != self.library_dir.resolve():
            raise ValueError("invalid")
        return artifact_hash, path

    def _derived_path(self, artifact_hash: str) -> Path:
        return self.derived_dir / f"{artifact_hash}.json"

    def _normalized_path(self, artifact_hash: str) -> Path:
        if _NORMALIZED_DIGEST_RE.fullmatch(str(artifact_hash or "")) is None:
            raise ValueError("artifact_hash must be a full lowercase SHA-256 hash")
        return self.derived_dir / artifact_hash / f"{NORMALIZER_REVISION}.json"

    def _normalized_invalid_path(self, artifact_hash: str) -> Path:
        if _NORMALIZED_DIGEST_RE.fullmatch(str(artifact_hash or "")) is None:
            raise ValueError("artifact_hash must be a full lowercase SHA-256 hash")
        return self.derived_dir / artifact_hash / f"{NORMALIZER_REVISION}.invalid.json"

    def _is_verified_canonical(self, artifact_ref: str) -> bool:
        try:
            artifact_hash, canonical_path = self._canonical_path(artifact_ref)
            raw_bytes = canonical_path.read_bytes()
        except (OSError, ValueError):
            return False
        return hashlib.sha256(raw_bytes).hexdigest() == artifact_hash

    def _current_derived_record(self, artifact_ref: str) -> dict[str, Any]:
        artifact_hash, _canonical_path = self._canonical_path(artifact_ref)
        raw_bytes = self.load_raw_bytes(artifact_ref)
        record = self._read_derived(artifact_hash)
        result = self._import_canonical_result(
            raw_bytes,
            artifact_ref,
            self._record_metadata(record),
            self._read_index_metadata().get(artifact_hash),
        )
        if not self._derived_matches_canonical(record, result):
            self._write_derived(result)
            self._write_index()
            record = self._read_derived(artifact_hash)
        if record is None:
            raise FileNotFoundError(f"Derived artifact record is unavailable: {artifact_ref}")
        return record

    def _write_derived(self, result: IdentityImportResult) -> None:
        record = {
            "artifact_ref": f"library/{result.raw.artifact_hash}.json",
            "projection_kind": "legacy_projection",
            "metadata": result.raw.metadata_dict(),
            "structured": result.structured.to_dict() if result.structured is not None else None,
        }
        self._atomic_write_json(self._derived_path(result.raw.artifact_hash), record)

    def _read_derived(self, artifact_hash: str) -> dict[str, Any] | None:
        path = self._derived_path(artifact_hash)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not isinstance(record, dict):
            return None
        artifact_ref = f"library/{artifact_hash}.json"
        metadata = record.get("metadata")
        if record.get("artifact_ref") != artifact_ref or not isinstance(metadata, dict):
            return None
        if metadata.get("artifact_hash") != artifact_hash or metadata.get("artifact_ref") != artifact_ref:
            return None
        return record

    def _read_index_metadata(self) -> dict[str, dict[str, Any]]:
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return {}
        artifacts = payload.get("artifacts") if isinstance(payload, dict) else None
        if not isinstance(artifacts, list):
            return {}
        indexed: dict[str, dict[str, Any]] = {}
        for metadata in artifacts:
            if not isinstance(metadata, dict):
                continue
            artifact_hash = str(metadata.get("artifact_hash") or "")
            artifact_ref = f"library/{artifact_hash}.json"
            if (
                re.fullmatch(r"[0-9a-f]{64}", artifact_hash)
                and metadata.get("artifact_ref") == artifact_ref
            ):
                indexed[artifact_hash] = dict(metadata)
        return indexed

    @staticmethod
    def _record_metadata(record: dict[str, Any] | None) -> dict[str, Any] | None:
        metadata = record.get("metadata") if isinstance(record, dict) else None
        return dict(metadata) if isinstance(metadata, dict) else None

    def _import_canonical_result(
        self,
        raw_bytes: bytes,
        artifact_ref: str,
        *metadata_candidates: dict[str, Any] | None,
    ) -> IdentityImportResult:
        artifact_hash = self._hash_for_ref(artifact_ref)
        provenance = None
        for metadata in metadata_candidates:
            provenance = self._provenance_from_metadata(metadata, artifact_ref, artifact_hash)
            if provenance is not None:
                break
        if provenance is None:
            return import_identity_artifact(raw_bytes, source_type="file", source_path=artifact_ref)
        rebuilt = import_identity_artifact(
            raw_bytes,
            provider_label=provenance["provider_label"],
            source_type=provenance["source_type"],
            source_path=provenance["source_path"],
        )
        rebuilt.raw.imported_at = provenance["imported_at"]
        return rebuilt

    @staticmethod
    def _provenance_from_metadata(
        metadata: dict[str, Any] | None,
        artifact_ref: str,
        artifact_hash: str,
    ) -> dict[str, str] | None:
        if not isinstance(metadata, dict):
            return None
        if metadata.get("artifact_ref") != artifact_ref or metadata.get("artifact_hash") != artifact_hash:
            return None
        if metadata.get("source_type") not in _SOURCE_TYPES:
            return None
        if any(not isinstance(metadata.get(field_name), str) for field_name in _PROVENANCE_FIELDS):
            return None
        return {field_name: metadata[field_name] for field_name in _PROVENANCE_FIELDS}

    @staticmethod
    def _derived_matches_canonical(record: dict[str, Any] | None, result: IdentityImportResult) -> bool:
        if record is None:
            return False
        metadata = record["metadata"]
        expected_metadata = result.raw.metadata_dict()
        semantic_fields = (
            "artifact_hash",
            "artifact_ref",
            "source_type",
            "source_path",
            "provider_label",
            "imported_at",
            "format",
            "format_version",
            "export_kind",
            "source_scope_summary",
            "status",
            "mechanical_warnings",
        )
        if any(metadata.get(field_name) != expected_metadata[field_name] for field_name in semantic_fields):
            return False
        expected_structured = result.structured.to_dict() if result.structured is not None else None
        return record.get("structured") == expected_structured

    def _write_index(self) -> None:
        artifacts: list[dict[str, Any]] = []
        for canonical_path in sorted(self.library_dir.glob("*.json")):
            artifact_hash = canonical_path.stem
            if not re.fullmatch(r"[0-9a-f]{64}", artifact_hash):
                continue
            if not self._is_verified_canonical(f"library/{canonical_path.name}"):
                continue
            record = self._read_derived(artifact_hash)
            if record is None:
                continue
            metadata = dict(record["metadata"])
            artifacts.append(metadata)
        artifacts.sort(key=lambda item: str(item.get("imported_at") or ""), reverse=True)
        self._atomic_write_json(self.index_path, {"version": 1, "artifacts": artifacts})

    def _legacy_raw_paths(self, legacy_root: Path) -> list[Path]:
        artifacts_dir = legacy_root / "artifacts"
        if not artifacts_dir.is_dir():
            return []
        return sorted(path for path in artifacts_dir.glob("*/raw.txt") if path.is_file())

    @staticmethod
    def _atomic_write_json(path: Path, value: Any) -> None:
        serialized = json.dumps(value, indent=2, ensure_ascii=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f"{path.name}.tmp")
        temporary_path.write_text(serialized, encoding="utf-8", newline="\n")
        os.replace(temporary_path, path)
