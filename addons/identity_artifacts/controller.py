from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any, Callable, Mapping

from PySide6 import QtCore, QtWidgets

from core import chat_providers

from addons.identity_artifacts.attestations import (
    AttestationState,
    IdentityRelayDecisionStore,
    IdentityRelaySnapshotAuthorizationStore,
    PersistentSnapshotAuthorization,
    ReviewDecision,
    SubjectAttestation,
    SubjectClassificationProposal,
    TransientActivation,
    evaluate_transient_activation,
    persistent_snapshot_authorization_record_id,
)
from addons.identity_artifacts.importer import import_identity_artifact
from addons.identity_artifacts.normalizer import (
    _CENTRAL_ROLES,
    _KNOWN_SEMANTIC_LABELS,
    _RETRIEVABLE_ROLES,
)
from addons.identity_artifacts.normalized_model import (
    NORMALIZER_REVISION,
    NormalizedIdentityModel,
    QuarantineItem,
    QuarantineReason,
    ReviewItem,
    ReviewKind,
    RuntimeLayer,
    SubjectClass,
    normalized_identity_digest,
)
from addons.identity_artifacts.policy import (
    EffectiveUseDecision,
    RuntimeUse,
    UserApproval,
    classify_endpoint_is_remote,
    evaluate_effective_use,
)
from addons.identity_artifacts.relay_state import IdentityRelayCapture, IdentityRelayModel
from addons.identity_artifacts.review_dialog import (
    ConnectionReviewDialog,
    ConnectionReviewModel,
    ConnectionReviewResult,
)
from addons.identity_artifacts.retrieval import TurnQueryEnvelope, build_turn_query_envelope
from addons.identity_artifacts.retrieval_index import (
    DEFAULT_SEMANTIC_THRESHOLD,
    IDENTITY_INDEX_REVISION,
    IDENTITY_INDEX_SCHEMA_VERSION,
    SEMANTIC_THRESHOLD_REVISION,
    IdentitySemanticIndex,
    SemanticIndexBuildResult,
    SemanticIndexMetadata,
    build_identity_semantic_index,
)
from addons.identity_artifacts.service import (
    IdentityRelayPreparedTurn,
    IdentityRelayService,
    identity_relay_snapshot_hash,
)
from addons.identity_artifacts.storage import (
    ARTIFACT_REF_RE,
    ArtifactDeleteResult,
    ArtifactResolution,
    IdentityArtifactStore,
    LibraryRefreshResult,
    StoredIdentityArtifact,
)


_IDENTITY_EXPORT_PROTOCOL_PATH = (
    Path(__file__).with_name("resources") / "ReflectAndExportIdentity_v1.1.txt"
)


def _read_identity_export_protocol(path: Path | None = None) -> str:
    protocol_path = Path(path) if path is not None else _IDENTITY_EXPORT_PROTOCOL_PATH
    text = protocol_path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError("Identity export protocol is empty.")
    return text


_REVIEW_RUNTIME_USE_SCOPES = (
    "always_inject",
    "contextual_retrieval",
    "private_retrieval",
)

_REVIEW_RESOLVABLE_AUTHORITY_FAILURES = frozenset(
    {
        "attestation_required",
        "attestation_digest_required",
        "attestation_digest_mismatch",
        "subject_not_assistant_self",
    }
)


class _CancellationToken:
    def __init__(self, generation: int = 0) -> None:
        self.generation = int(generation)
        self._event = threading.Event()
        self._side_effect_gate = threading.Lock()

    def cancel(self) -> None:
        with self._side_effect_gate:
            self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def run_authoritative_side_effect(self, side_effect: Callable[[], object]) -> bool:
        with self._side_effect_gate:
            if self._event.is_set():
                return False
            side_effect()
            return True


@dataclass(frozen=True, slots=True)
class _OperationCompletion:
    kind: str
    generation: int
    value: object = None
    error_code: str = ""


class _OperationSignals(QtCore.QObject):
    completed = QtCore.Signal(object)


class _OperationWorker(QtCore.QRunnable):
    def __init__(
        self,
        kind: str,
        generation: int,
        token: _CancellationToken,
        work: Callable[[_CancellationToken], object],
    ) -> None:
        super().__init__()
        self.kind = kind
        self.generation = generation
        self.token = token
        self.work = work
        self.signals = _OperationSignals()
        self.setAutoDelete(False)

    @QtCore.Slot()
    def run(self) -> None:
        try:
            value = self.work(self.token)
            completion = _OperationCompletion(self.kind, self.generation, value)
        except Exception as exc:
            completion = _OperationCompletion(
                self.kind,
                self.generation,
                error_code=type(exc).__name__,
            )
        self.signals.completed.emit(completion)


@dataclass(frozen=True, slots=True)
class _RefreshPayload:
    refresh: LibraryRefreshResult
    artifacts: tuple[Mapping[str, Any], ...]
    expected_connected_ref: str
    expected_connection_revision: int
    connected_resolution: ArtifactResolution | None
    connected_authority: Mapping[str, Any] | None


@dataclass(frozen=True, slots=True)
class _ImportPayload:
    stored: StoredIdentityArtifact
    imported: bool
    refresh: _RefreshPayload


@dataclass(frozen=True, slots=True)
class _ConnectionPayload:
    resolution: ArtifactResolution
    normalized: NormalizedIdentityModel | None
    decisions: AttestationState | None
    index_status: str
    migration_messages: tuple[str, ...] = ()
    authority: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class _PendingConnection:
    previous_ref: str
    requested_ref: str
    bridge: object = None
    saved_restore: bool = False


@dataclass(frozen=True, slots=True)
class _ConnectionApplyPayload:
    result: ConnectionReviewResult
    resolution: ArtifactResolution | None
    authority: Mapping[str, Any] | None
    state: AttestationState
    token: _CancellationToken
    chat_session_token: str


@dataclass(frozen=True, slots=True)
class _SessionAuthorityPayload:
    expected_connected_ref: str
    expected_connection_revision: int
    session_token: str
    resolution: ArtifactResolution | None
    authority: Mapping[str, Any] | None


class _ReviewedIdentityStore:
    def __init__(self, controller: "IdentityArtifactsController") -> None:
        self._controller = controller

    def load_normalized(self, artifact_ref: str) -> NormalizedIdentityModel:
        controller = self._controller
        model = controller.store.load_normalized(artifact_ref)
        state = controller.decision_store.load(model.envelope.artifact_hash)
        return controller._apply_review_decisions(model, state)

    def load_identity_relay_authority(self, artifact_ref: str) -> Mapping[str, Any] | None:
        return self._controller._authoritative_state_for_ref(artifact_ref)

    def __getattr__(self, name: str):
        return getattr(self._controller.store, name)


class _RuntimeEmbeddingAdapter:
    def __init__(self, embedding: Callable[..., object], *, base_url: str) -> None:
        self._embedding = embedding
        self._base_url = base_url

    def embed(self, texts, *, model: str, context: int):
        return self.embed_for_capture(
            texts,
            model=model,
            context=context,
            base_url=self._base_url,
        )

    def embed_for_capture(
        self,
        texts,
        *,
        model: str,
        context: int,
        base_url: str,
    ):
        endpoint = str(base_url or self._base_url)
        return tuple(
            self._embedding(
                text,
                model=model,
                base_url=endpoint,
                context_length=context,
            )
            for text in texts
        )


class IdentityArtifactsController(QtCore.QObject):
    _runtime_transparency_requested = QtCore.Signal(object)

    def __init__(self, context=None):
        super().__init__()
        self.context = context
        self.dialogs = context.get_service("qt.dialogs") if context is not None else None
        app_root = Path(getattr(context, "app_root", Path.cwd()) or Path.cwd())
        self.store = IdentityArtifactStore(app_root / "runtime" / "identity_relay")
        self.legacy_root = (
            context.storage.addon_dir
            if context is not None
            else app_root / "runtime" / "addons" / "nc.identity_artifacts"
        )
        self.presets_dir = app_root / "presets"
        self.shell = context.get_service("qt.shell") if context is not None else None
        self.runtime_config = (
            context.get_service("qt.runtime_config") if context is not None else None
        )
        self.relay_model = IdentityRelayModel()
        self.decision_store = IdentityRelayDecisionStore(self.store.root_dir)
        self.snapshot_authorization_store = IdentityRelaySnapshotAuthorizationStore(
            self.store.root_dir
        )
        self.semantic_index = IdentitySemanticIndex(self.store.root_dir / "indexes")
        semantic_config = self._runtime_embedding_config()
        runtime_embedding = self._runtime_embedding_callable()
        embedding_adapter = (
            _RuntimeEmbeddingAdapter(
                runtime_embedding,
                base_url=str(semantic_config.get("base_url") or ""),
            )
            if callable(runtime_embedding)
            else None
        )
        self.relay_service = IdentityRelayService(
            self.relay_model,
            store=_ReviewedIdentityStore(self),
            index=self.semantic_index,
            embedding=embedding_adapter,
        )
        self._chat_completion = chat_providers.complete_chat
        self.root_widget = None
        self.artifact_list = None
        self.provider_edit = None
        self.import_text_edit = None
        self.summary_label = None
        self.raw_view = None
        self.structured_view = None
        self.warnings_view = None
        self.btn_delete = None
        self.btn_reextract = None
        self.owner_override_checkbox = None
        self.owner_override_status_label = None
        self.export_protocol_status_label = None
        self._identity_relay_bound_widget_ids: set[int] = set()
        self._bound_bridges: dict[int, object] = {}
        self._operation_generations: dict[str, int] = {}
        self._operation_tokens: dict[str, _CancellationToken] = {}
        self._operation_callbacks: dict[tuple[str, int], Callable[[object], None]] = {}
        self._operation_workers: dict[tuple[str, int], _OperationWorker] = {}
        self._store_operation_lock = threading.Lock()
        self._artifact_deletion_tombstones: set[str] = set()
        self._force_async_operations = False
        self._pending_connection: _PendingConnection | None = None
        self._review_connection_payload: _ConnectionPayload | None = None
        self._pending_saved_identity_ref = ""
        self.review_dialog: ConnectionReviewDialog | None = None
        self._is_shutdown = False
        self.last_visible_notice = ""
        self._connection_status = ""
        self._runtime_transparency = MappingProxyType(
            {
                "status": "ready",
                "reason": "",
                "judging": False,
                "rebuild_required": False,
                "trace_ids": (),
                "notice": MappingProxyType({}),
            }
        )
        self._chat_session_token = uuid.uuid4().hex
        self._runtime_transparency_requested.connect(
            self._apply_runtime_transparency,
            QtCore.Qt.QueuedConnection,
        )

    def set_persona_identity_ref(self, artifact_ref: str, *, notify: bool = True):
        strict_ref = self._strict_artifact_ref(artifact_ref)
        if not strict_ref:
            self.relay_model.set_connection(None)
            self._pending_saved_identity_ref = ""
            if notify:
                self._notify_settings_changed()
            return self.relay_model.ui_snapshot()
        resolution = self.store.resolve_artifact(strict_ref)
        authority = self._authoritative_state_for_ref(strict_ref)
        if resolution.failure_code or authority is None:
            if self.relay_model.connection_marker()[0] == strict_ref:
                self._disconnect_invalid_authority(strict_ref)
            else:
                reason = str(resolution.failure_code or "attestation_required")
                if reason.startswith("normalized_"):
                    notice = (
                        "Identity Relay normalized identity changed. Rebuild and "
                        "review it before reconnecting."
                    )
                elif reason in {
                    "attestation_digest_required",
                    "attestation_digest_mismatch",
                }:
                    notice = (
                        "Identity Relay authority predates or does not match the "
                        "verified identity. Review it before reconnecting."
                    )
                else:
                    notice = (
                        "Identity Relay connection requires a current approved "
                        "assistant-self attestation."
                    )
                self._set_visible_notice(notice)
            return self.relay_model.ui_snapshot()
        self._set_relay_connection_context(resolution, authority)
        self._pending_saved_identity_ref = ""
        if notify:
            self._notify_settings_changed()
        return self.relay_model.ui_snapshot()

    def set_relay_enabled(self, enabled: bool) -> bool:
        changed = self.relay_model.set_enabled(bool(enabled))
        if changed:
            self._notify_settings_changed()
        return changed

    def capture_turn_snapshot(self) -> dict[str, object] | None:
        snapshot = self.relay_model.snapshot_for_turn()
        if snapshot is not None and not self._strict_artifact_ref(snapshot.artifact_ref):
            return None
        if (
            snapshot is not None
            and self._authoritative_state_for_ref(snapshot.artifact_ref) is None
        ):
            self._disconnect_invalid_authority(snapshot.artifact_ref)
            return None
        return asdict(snapshot) if snapshot is not None else None

    def capture_mode(self):
        return self.relay_model.capture_mode()

    def capture_turn(self, payload: Mapping[str, Any] | None = None):
        live_mode = self.relay_model.capture_mode()
        if not live_mode.connected or not live_mode.enabled:
            accepted_mode = (
                payload.get("mode_snapshot")
                if isinstance(payload, dict)
                else None
            )
            return self.relay_model.capture_turn(
                mode_snapshot=accepted_mode or live_mode
            )
        request = dict(payload or {})
        capture = self.relay_model.capture_turn(
            mode_snapshot=request.get("mode_snapshot")
        )
        if capture is None or not capture.enabled:
            return capture
        frozen_provider = dict(self._mapping(request.get("frozen_provider")))
        semantic_config = self._runtime_embedding_config()
        if semantic_config:
            frozen_provider.update(
                {
                    "embedding_provider": "lmstudio",
                    "embedding_model": semantic_config["model"],
                    "embedding_base_url": semantic_config["base_url"],
                    "embedding_context": semantic_config["context"],
                    "embedding_provider_is_remote": semantic_config[
                        "provider_is_remote"
                    ],
                }
            )
        return self.relay_model.enrich_capture(
            capture,
            frozen_provider=frozen_provider,
            owner_override=self._owner_override_enabled(),
        )

    def _owner_override_enabled(self) -> bool:
        snapshot = getattr(self.runtime_config, "snapshot", None)
        values = dict(snapshot() or {}) if callable(snapshot) else {}
        return values.get("identity_relay_owner_override") is True

    def _set_owner_override_enabled(self, enabled: bool) -> bool:
        setter = getattr(self.runtime_config, "set", None)
        if not callable(setter):
            return False
        setter("identity_relay_owner_override", bool(enabled))
        self._sync_owner_override_controls()
        self._mirror_bound_widgets()
        self._notify_settings_changed()
        return self._owner_override_enabled() is bool(enabled)

    def _sync_owner_override_controls(self) -> None:
        enabled = self._owner_override_enabled()
        if self.owner_override_checkbox is not None:
            blocker = QtCore.QSignalBlocker(self.owner_override_checkbox)
            self.owner_override_checkbox.setChecked(enabled)
            del blocker
        if self.owner_override_status_label is not None:
            self.owner_override_status_label.setText(
                "Owner Override is active. External providers may receive any "
                "Identity Relay records selected for the current turn."
            )
            self.owner_override_status_label.setVisible(enabled)

    def _on_owner_override_toggled(self, checked: bool) -> None:
        requested = bool(checked)
        if requested and not self._owner_override_enabled():
            if not self._confirm_owner_override_enable():
                self._sync_owner_override_controls()
                return
        if not self._set_owner_override_enabled(requested):
            self._sync_owner_override_controls()

    def _confirm_owner_override_enable(self) -> bool:
        answer = QtWidgets.QMessageBox.question(
            self.root_widget,
            "Enable Identity Relay Owner Override?",
            "Privacy warning: Owner Override removes Identity Relay exposure "
            "restrictions for external providers. Identity records selected "
            "for a turn may be sent to the active external chat or embedding "
            "provider, including private or relationship-specific data.\n\n"
            "Enable Owner Override?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        return answer == QtWidgets.QMessageBox.Yes

    def _runtime_embedding_callable(self):
        if self.runtime_config is None:
            return None
        engine_attr = getattr(self.runtime_config, "engine_attr", None)
        return engine_attr("_lmstudio_embedding", None) if callable(engine_attr) else None

    def _runtime_embedding_config(self) -> Mapping[str, Any]:
        snapshot_method = getattr(self.runtime_config, "snapshot", None)
        snapshot = (
            dict(snapshot_method() or {}) if callable(snapshot_method) else {}
        )
        if not bool(snapshot.get("long_term_memory_embedding_enabled", False)):
            return {}
        model = str(
            snapshot.get("long_term_memory_embedding_model") or ""
        ).strip()
        base_url = str(
            snapshot.get("long_term_memory_embedding_base_url") or ""
        ).strip()
        try:
            context = int(
                snapshot.get("long_term_memory_embedding_context_length") or 0
            )
        except (TypeError, ValueError):
            context = 0
        if not model or not base_url or context <= 0:
            return {}
        return MappingProxyType(
            {
                "model": model,
                "base_url": base_url,
                "context": context,
                "provider_is_remote": classify_endpoint_is_remote(base_url),
            }
        )

    def _set_relay_connection_context(
        self,
        resolution: ArtifactResolution | None,
        authority: Mapping[str, Any] | None,
    ) -> None:
        if authority is None:
            self.relay_model.set_connection_with_context(resolution)
            return
        self.relay_model.set_connection_with_context(
            resolution,
            normalizer_revision=str(authority.get("normalizer_revision") or ""),
            normalized_digest=str(authority.get("normalized_digest") or ""),
            attestation_revision=int(authority.get("attestation_revision") or 0),
            transient_activation=self._mapping(authority.get("transient_activation")),
            runtime_use=self._mapping(authority.get("runtime_use")),
            frozen_normalized_model=self._mapping(
                authority.get("frozen_normalized_model")
            ),
            frozen_model_digest=str(authority.get("frozen_model_digest") or ""),
        )

    def _authoritative_state_for_ref(
        self,
        artifact_ref: str,
        *,
        chat_session_token: str | None = None,
    ) -> Mapping[str, Any] | None:
        strict_ref = self._strict_artifact_ref(artifact_ref)
        if not strict_ref:
            return None
        try:
            resolution = self.store.resolve_artifact(strict_ref)
            if resolution.failure_code or not resolution.artifact_hash:
                return None
            model = self.store.load_normalized(strict_ref)
            state = self.decision_store.load(resolution.artifact_hash)
        except Exception:
            return None
        current_session_token = (
            self._chat_session_token
            if chat_session_token is None
            else str(chat_session_token)
        )
        return self._authority_from_state(
            resolution,
            model,
            state,
            chat_session_token=current_session_token,
        )

    def _authority_from_state(
        self,
        resolution: ArtifactResolution,
        model: NormalizedIdentityModel,
        state: AttestationState,
        *,
        chat_session_token: str,
    ) -> Mapping[str, Any] | None:
        subject = state.subject_attestation
        digest = normalized_identity_digest(model)
        if (
            resolution.failure_code
            or not resolution.artifact_hash
            or model.envelope.artifact_hash != resolution.artifact_hash
            or state.artifact_hash != resolution.artifact_hash
            or model.normalizer_revision != state.normalizer_revision
            or subject is None
            or subject.normalizer_revision != model.normalizer_revision
            or not subject.normalized_digest
            or subject.normalized_digest != digest
            or resolution.normalized_digest != digest
            or not subject.approved
            or subject.subject_class != SubjectClass.ASSISTANT_SELF
        ):
            return None
        reviewed_model = self._apply_review_decisions(model, state)
        frozen_model_digest = normalized_identity_digest(reviewed_model)
        saved_transients = {item.record_id: item for item in state.transient_activations}
        transient_activation: dict[str, Mapping[str, Any]] = {}
        now = datetime.now(timezone.utc)
        current_session_token = str(chat_session_token)
        for transient in model.transient_records:
            saved = saved_transients.get(transient.record_id)
            if saved is None:
                transient_activation[transient.record_id] = MappingProxyType(
                    {
                        "active": False,
                        "review_required": True,
                        "reason_code": "choice_required",
                        "expires_at": None,
                        "revision": 0,
                    }
                )
                continue
            if saved.session_token != current_session_token:
                transient_activation[transient.record_id] = MappingProxyType(
                    {
                        "active": False,
                        "review_required": True,
                        "reason_code": "session_mismatch",
                        "expires_at": None,
                        "revision": saved.revision,
                    }
                )
                continue
            evaluated = evaluate_transient_activation(
                transient=transient,
                saved_activation=saved,
                now=now,
                current_session_token=current_session_token,
            )
            review_required = bool(evaluated.review_required)
            reason_code = evaluated.reason_code
            active = bool(evaluated.active)
            if evaluated.reason_code in {"session_mismatch", "expired"}:
                review_required = True
            transient_activation[transient.record_id] = MappingProxyType(
                {
                    "active": active,
                    "review_required": review_required,
                    "reason_code": reason_code,
                    "expires_at": evaluated.expires_at,
                    "revision": saved.revision,
                }
            )
        runtime_use = MappingProxyType(
            {
                "connected": True,
                "subject_approved": True,
                "subject_class": SubjectClass.ASSISTANT_SELF.value,
                "review_decisions": MappingProxyType(
                    {item.review_id: item.choice for item in state.review_decisions}
                ),
                "review_decision_revisions": MappingProxyType(
                    {item.review_id: item.revision for item in state.review_decisions}
                ),
            }
        )
        return MappingProxyType(
            {
                "artifact_hash": resolution.artifact_hash,
                "normalizer_revision": model.normalizer_revision,
                "normalized_digest": digest,
                "frozen_model_digest": frozen_model_digest,
                "attestation_revision": subject.revision,
                "runtime_use": runtime_use,
                "transient_activation": MappingProxyType(transient_activation),
                "frozen_normalized_model": reviewed_model.to_dict(),
            }
        )

    def _disconnect_invalid_authority(self, artifact_ref: str) -> None:
        if self.relay_model.ui_snapshot().connected_ref != artifact_ref:
            return
        self.relay_model.set_connection(None)
        self._connection_status = (
            "Identity Relay disconnected because assistant-self authority is no longer valid."
        )
        self.last_visible_notice = self._connection_status
        self._notify_settings_changed()
        self._mirror_bound_widgets()

    def prepare_turn(self, payload: Mapping[str, Any] | None = None):
        request = dict(payload or {})
        capture = request.get("capture")
        if not isinstance(capture, IdentityRelayCapture) or not capture.enabled:
            prepared = self.relay_service.prepare_turn(capture, None)
            self.update_runtime_transparency(
                status=prepared.status,
                reason=prepared.failure_code,
                trace_ids=self._trace_ids(prepared.trace),
            )
            return prepared
        query = self._query_envelope(request.get("query"))
        judge_capacity = request.get("judge_capacity")
        capacity = dict(judge_capacity) if isinstance(judge_capacity, Mapping) else {}
        prepared = self.relay_service.prepare_turn(
            capture,
            query,
            judge_context_limit=capacity.get("context_limit"),
            judge_token_counter=capacity.get("token_counter"),
            judge_output_budget=capacity.get("output_budget"),
        )
        semantic_unavailable = bool(
            prepared.candidate_set is not None
            and not prepared.candidate_set.semantic_available
            and prepared.status not in {"blocked", "suspended"}
        )
        semantic_reason = (
            str(prepared.candidate_set.semantic_reason or "semantic_retrieval_unavailable")
            if semantic_unavailable
            else ""
        )
        notice = (
            {
                "prominent": True,
                "failure_category": "semantic_retrieval_unavailable",
                "affected_record_ids": (),
                "reason": semantic_reason,
            }
            if semantic_unavailable
            else None
        )
        self.update_runtime_transparency(
            status="degraded" if semantic_unavailable else prepared.status,
            reason=semantic_reason or prepared.failure_code,
            judging=bool(prepared.judge_batches),
            rebuild_required=bool(
                prepared.trace.get("semantic_rebuild_required", False)
                or "index" in str(prepared.failure_code or "")
            ),
            trace_ids=self._trace_ids(prepared.trace),
            notice=notice,
        )
        return prepared

    def render_judge_request(self, payload: Mapping[str, Any] | None = None):
        prepared = dict(payload or {}).get("prepared")
        if not isinstance(prepared, IdentityRelayPreparedTurn):
            return ()
        batches = self.relay_service.render_judge_request(prepared)
        if batches:
            self.update_runtime_transparency(
                status="judging",
                judging=True,
                trace_ids=self._trace_ids(prepared.trace),
            )
        return batches

    @staticmethod
    def _snapshot_record_ids(snapshot: object) -> tuple[str, ...]:
        kernel = tuple(getattr(snapshot, "kernel_record_ids", ()) or ())
        selected = tuple(getattr(snapshot, "selected_record_ids", ()) or ())
        return tuple(dict.fromkeys(str(item) for item in (*kernel, *selected) if str(item)))

    @staticmethod
    def _operation_allowed(
        prepared: IdentityRelayPreparedTurn,
        record_id: str,
        operation: str,
    ) -> bool:
        decisions = prepared.operation_decisions.get(record_id, {})
        decision = decisions.get(operation) if isinstance(decisions, Mapping) else None
        return bool(getattr(decision, "allowed", False))

    @staticmethod
    def _provider_endpoint(frozen_provider: Mapping[str, Any]) -> str:
        provider_config = frozen_provider.get("provider_config")
        config = dict(provider_config) if isinstance(provider_config, Mapping) else {}
        return str(
            config.get("base_url")
            or config.get("endpoint")
            or frozen_provider.get("base_url")
            or frozen_provider.get("endpoint")
            or ""
        ).strip()

    def _volatile_snapshot_after_authorization_failure(
        self,
        snapshot: object,
        prepared: IdentityRelayPreparedTurn,
        *,
        failure_code: str,
        reason: str,
        affected_record_ids: tuple[str, ...],
    ):
        capture = prepared.capture
        frozen_provider = self._mapping(
            capture.frozen_provider if capture is not None else {}
        )
        notice = {
            "prominent": True,
            "provider": str(frozen_provider.get("provider_name") or ""),
            "model": str(frozen_provider.get("model_name") or ""),
            "failure_category": failure_code,
            "affected_record_ids": tuple(affected_record_ids),
            "reason": reason,
        }
        changed = replace(
            snapshot,
            persistence_mode="volatile",
            snapshot_hash="",
            authorization_record_id="",
        )
        return self.relay_service.externalize_snapshot(
            prepared,
            changed,
            notices={"persistence_notice": notice},
            preserve_failure_category=True,
            recompute_hash=True,
        )

    def _persist_snapshot_authorization(
        self,
        snapshot: object,
        prepared: IdentityRelayPreparedTurn,
    ):
        if (
            str(getattr(snapshot, "status", "") or "") != "ready"
            or str(getattr(snapshot, "persistence_mode", "") or "") != "persistent"
        ):
            return snapshot
        capture = prepared.capture
        if capture is None:
            return self._volatile_snapshot_after_authorization_failure(
                snapshot,
                prepared,
                failure_code="persistence_authorization_unavailable",
                reason="Persistent Relay authorization could not be bound to the accepted turn.",
                affected_record_ids=self._snapshot_record_ids(snapshot),
            )
        record_ids = self._snapshot_record_ids(snapshot)
        required_operations = ("persistence_export", "provider_transmission")
        if not record_ids or any(
            not self._operation_allowed(prepared, record_id, operation)
            for record_id in record_ids
            for operation in required_operations
        ):
            return self._volatile_snapshot_after_authorization_failure(
                snapshot,
                prepared,
                failure_code="persistence_authorization_incomplete",
                reason="The complete persisted Relay projection lacks explicit authorization.",
                affected_record_ids=record_ids,
            )
        runtime_use = self._mapping(capture.runtime_use)
        provider_is_remote = runtime_use.get("provider_is_remote")
        subject_class = str(runtime_use.get("subject_class") or "")
        subject_approved = bool(runtime_use.get("subject_approved", False))
        if (
            type(provider_is_remote) is not bool
            or not subject_approved
            or subject_class != SubjectClass.ASSISTANT_SELF.value
        ):
            return self._volatile_snapshot_after_authorization_failure(
                snapshot,
                prepared,
                failure_code="persistence_authorization_incomplete",
                reason="Persistent Relay authorization lacks trusted subject or provider exposure state.",
                affected_record_ids=record_ids,
            )
        frozen_provider = self._mapping(capture.frozen_provider)
        authorization = PersistentSnapshotAuthorization(
            snapshot_hash=str(getattr(snapshot, "snapshot_hash", "") or ""),
            artifact_ref=str(getattr(snapshot, "artifact_ref", "") or ""),
            artifact_hash=str(getattr(snapshot, "artifact_hash", "") or ""),
            normalizer_revision=str(
                getattr(snapshot, "normalizer_revision", "") or ""
            ),
            attestation_revision=int(
                getattr(snapshot, "attestation_revision", 0) or 0
            ),
            subject_class=subject_class,
            subject_approved=subject_approved,
            persistence_allowed=True,
            provider_is_remote=provider_is_remote,
            provider_name=str(frozen_provider.get("provider_name") or ""),
            provider_endpoint=self._provider_endpoint(frozen_provider),
            record_ids=record_ids,
            authorized_operations=required_operations,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        authorization = replace(
            authorization,
            authorization_record_id=(
                persistent_snapshot_authorization_record_id(authorization)
            ),
        )
        authorized_snapshot = replace(
            snapshot,
            authorization_record_id=authorization.authorization_record_id,
        )
        try:
            self.snapshot_authorization_store.save(authorization)
        except Exception:
            return self._volatile_snapshot_after_authorization_failure(
                authorized_snapshot,
                prepared,
                failure_code="persistence_authorization_store_failed",
                reason="The trusted persistence authorization could not be stored; this projection is volatile.",
                affected_record_ids=record_ids,
            )
        return authorized_snapshot

    def _restoration_denied(self, failure_code: str, reason: str) -> Mapping[str, Any]:
        notice = {
            "prominent": True,
            "failure_category": failure_code,
            "affected_record_ids": (),
            "reason": reason,
        }
        self.update_runtime_transparency(
            status="blocked",
            reason=reason,
            notice=notice,
        )
        return MappingProxyType(
            {
                "authorized": False,
                "failure_code": failure_code,
                "reason": reason,
            }
        )

    @staticmethod
    def _trace_enum_value(value: Any) -> str:
        return str(getattr(value, "value", value) or "")

    @classmethod
    def _owner_trace_record(
        cls,
        prepared: IdentityRelayPreparedTurn,
        record_id: str,
        *,
        selection_reason: str = "",
        signals_considered: tuple[str, ...] = (),
        candidate: object = None,
        candidate_denial_reason: str = "",
    ) -> Mapping[str, Any]:
        model = prepared.normalized_model
        record = (
            model.records_by_id.get(record_id)
            if model is not None
            else None
        )
        if record is None and model is not None:
            record = next(
                (
                    item
                    for item in model.transient_records
                    if item.record_id == record_id
                ),
                None,
            )
        operation_decisions = {}
        for operation, decision in dict(
            prepared.operation_decisions.get(record_id, {})
        ).items():
            operation_decisions[str(operation)] = MappingProxyType(
                {
                    "allowed": bool(getattr(decision, "allowed", False)),
                    "reason_code": str(getattr(decision, "reason_code", "") or ""),
                    "explanation": str(getattr(decision, "explanation", "") or ""),
                }
            )
        provider_decision = operation_decisions.get("provider_transmission", {})
        payload = {
            "record_id": str(record_id or ""),
            "source_path": str(getattr(record, "source_path", "") or ""),
            "source_text": str(getattr(record, "source_text", "") or ""),
            "semantic_role": cls._trace_enum_value(
                getattr(record, "semantic_role", "")
            ),
            "runtime_layer": cls._trace_enum_value(
                getattr(record, "runtime_layer", "")
            ),
            "stability": cls._trace_enum_value(getattr(record, "stability", "")),
            "epistemic_qualifier": str(
                getattr(record, "epistemic_qualifier", "") or ""
            ),
            "policy_reason": str(provider_decision.get("explanation") or ""),
            "policy_reason_code": str(provider_decision.get("reason_code") or ""),
            "operation_decisions": MappingProxyType(operation_decisions),
            "selection_reason": str(selection_reason or ""),
            "signals_considered": tuple(str(item) for item in signals_considered),
            "candidate_denial_reason": str(candidate_denial_reason or ""),
        }
        if candidate is not None:
            payload.update(
                {
                    "candidate_deterministic": bool(
                        getattr(candidate, "deterministic", False)
                    ),
                    "candidate_signals": tuple(
                        str(item) for item in getattr(candidate, "signals", ())
                    ),
                    "candidate_score_components": MappingProxyType(
                        dict(getattr(candidate, "score_components", {}) or {})
                    ),
                    "candidate_policy_reason": str(
                        getattr(candidate, "policy_reason", "") or ""
                    ),
                }
            )
        return MappingProxyType(payload)

    @classmethod
    def _owner_trace_payload(
        cls,
        prepared: IdentityRelayPreparedTurn,
        snapshot: object,
        *,
        notice: Mapping[str, Any] | None = None,
        judge_payload: object = None,
    ) -> Mapping[str, Any]:
        capture = prepared.capture
        frozen_provider = (
            dict(capture.frozen_provider)
            if capture is not None and isinstance(capture.frozen_provider, Mapping)
            else {}
        )
        active_kernel_ids = tuple(
            str(item) for item in tuple(getattr(snapshot, "kernel_record_ids", ()) or ())
        )
        omitted_kernel_ids = tuple(
            str(item) for item in prepared.omitted_kernel_record_ids if str(item)
        )
        all_kernel_ids = tuple(
            dict.fromkeys((*active_kernel_ids, *omitted_kernel_ids))
        )
        selected_ids = tuple(
            str(item) for item in tuple(getattr(snapshot, "selected_record_ids", ()) or ())
        )
        unresolved_ids = tuple(
            str(item) for item in tuple(getattr(snapshot, "unresolved_record_ids", ()) or ())
        )
        selection_reasons = dict(getattr(snapshot, "selection_reasons", {}) or {})
        signals_considered = dict(getattr(snapshot, "signals_considered", {}) or {})
        candidate_set = prepared.candidate_set
        eligible_candidates = tuple(
            getattr(candidate_set, "eligible", ()) or ()
        )
        denied_candidate_ids = tuple(
            str(item)
            for item in tuple(getattr(candidate_set, "denied_record_ids", ()) or ())
            if str(item)
        )
        denial_reasons = dict(
            getattr(candidate_set, "denial_reasons", {}) or {}
        )

        return MappingProxyType(
            {
                "status": str(getattr(snapshot, "status", "") or ""),
                "failure_code": str(
                    getattr(snapshot, "failure_code", "") or ""
                ),
                "provider": str(frozen_provider.get("provider_name") or ""),
                "model": str(frozen_provider.get("model_name") or ""),
                "artifact_ref": str(
                    getattr(snapshot, "artifact_ref", "")
                    or getattr(capture, "artifact_ref", "")
                    or ""
                ),
                "kernel_total_count": len(all_kernel_ids),
                "kernel_active_count": len(active_kernel_ids),
                "kernel_omitted_count": len(omitted_kernel_ids),
                "selected_count": len(selected_ids),
                "unresolved_count": len(unresolved_ids),
                "active_kernel_records": tuple(
                    cls._owner_trace_record(prepared, record_id)
                    for record_id in active_kernel_ids
                ),
                "omitted_kernel_records": tuple(
                    cls._owner_trace_record(prepared, record_id)
                    for record_id in omitted_kernel_ids
                ),
                "selected_records": tuple(
                    cls._owner_trace_record(
                        prepared,
                        record_id,
                        selection_reason=str(selection_reasons.get(record_id) or ""),
                        signals_considered=tuple(
                            signals_considered.get(record_id) or ()
                        ),
                    )
                    for record_id in selected_ids
                ),
                "unresolved_records": tuple(
                    cls._owner_trace_record(prepared, record_id)
                    for record_id in unresolved_ids
                ),
                "eligible_candidates": tuple(
                    cls._owner_trace_record(
                        prepared,
                        str(getattr(candidate, "record_id", "") or ""),
                        candidate=candidate,
                    )
                    for candidate in eligible_candidates
                    if str(getattr(candidate, "record_id", "") or "")
                ),
                "denied_candidates": tuple(
                    cls._owner_trace_record(
                        prepared,
                        record_id,
                        candidate_denial_reason=str(
                            denial_reasons.get(record_id) or ""
                        ),
                    )
                    for record_id in denied_candidate_ids
                ),
                "projection_prompt": str(
                    getattr(snapshot, "prompt_text", "") or ""
                ),
                "visible_notice": MappingProxyType(dict(notice or {})),
                "judge_payload": cls._owner_trace_text(judge_payload),
            }
        )

    @staticmethod
    def _owner_trace_text(value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, indent=2, ensure_ascii=False, default=str)
        except Exception:
            return str(value)

    def restore_persisted_snapshot(
        self,
        payload: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        request = dict(payload or {})
        snapshot = dict(self._mapping(request.get("snapshot")))
        frozen_provider = self._mapping(request.get("frozen_provider"))
        claimed_hash = str(snapshot.get("snapshot_hash") or "")
        authorization_record_id = str(
            snapshot.get("authorization_record_id") or ""
        )
        try:
            computed_hash = identity_relay_snapshot_hash(snapshot)
        except Exception:
            computed_hash = ""
        if not claimed_hash or claimed_hash != computed_hash:
            return self._restoration_denied(
                "persisted_snapshot_hash_mismatch",
                "The persisted Relay projection no longer matches its exact content hash.",
            )
        if not authorization_record_id:
            return self._restoration_denied(
                "persisted_snapshot_authorization_reference_required",
                "The persisted Relay projection has no trusted authorization reference.",
            )
        authorization = self.snapshot_authorization_store.load(
            authorization_record_id
        )
        if authorization is None:
            return self._restoration_denied(
                "persisted_snapshot_authorization_required",
                "No trusted durable authorization exists for this persisted Relay projection.",
            )
        record_ids = tuple(
            dict.fromkeys(
                str(item)
                for item in (
                    *tuple(snapshot.get("kernel_record_ids") or ()),
                    *tuple(snapshot.get("selected_record_ids") or ()),
                )
                if str(item)
            )
        )
        if (
            snapshot.get("status") != "ready"
            or snapshot.get("persistence_mode") != "persistent"
            or authorization.authorization_record_id != authorization_record_id
            or authorization.snapshot_hash != claimed_hash
            or authorization.artifact_ref != str(snapshot.get("artifact_ref") or "")
            or authorization.artifact_hash != str(snapshot.get("artifact_hash") or "")
            or authorization.normalizer_revision
            != str(snapshot.get("normalizer_revision") or "")
            or authorization.attestation_revision
            != int(snapshot.get("attestation_revision") or 0)
            or not authorization.subject_approved
            or authorization.subject_class != SubjectClass.ASSISTANT_SELF.value
            or not authorization.persistence_allowed
            or authorization.record_ids != record_ids
            or not {"persistence_export", "provider_transmission"}.issubset(
                set(authorization.authorized_operations)
            )
        ):
            return self._restoration_denied(
                "persisted_snapshot_authorization_mismatch",
                "The trusted Relay authorization does not match the exact persisted projection.",
            )
        provider_config = self._mapping(frozen_provider.get("provider_config"))
        provider_is_remote = frozen_provider.get("provider_is_remote")
        if type(provider_is_remote) is not bool:
            provider_is_remote = provider_config.get("provider_is_remote")
        if type(provider_is_remote) is not bool:
            return self._restoration_denied(
                "provider_locality_required",
                "The frozen reply provider exposure could not be classified safely.",
            )
        if provider_is_remote != authorization.provider_is_remote:
            return self._restoration_denied(
                "provider_exposure_not_authorized",
                "The persisted Relay projection is not authorized for the frozen provider exposure class.",
            )
        return MappingProxyType(
            {
                "authorized": True,
                "failure_code": "",
                "snapshot_hash": claimed_hash,
                "authorization_record_id": authorization_record_id,
                "provider_is_remote": provider_is_remote,
            }
        )

    def finalize_turn(self, payload: Mapping[str, Any] | None = None):
        request = dict(payload or {})
        prepared = request.get("prepared")
        if not isinstance(prepared, IdentityRelayPreparedTurn):
            return None
        snapshot = self.relay_service.finalize_turn(
            prepared,
            judge_payload=request.get("judge_payload"),
        )
        snapshot = self._persist_snapshot_authorization(snapshot, prepared)
        notice = self._mapping(snapshot.trace.get("degradation_notice"))
        persistence_notice = self._mapping(
            snapshot.trace.get("persistence_notice")
        )
        if persistence_notice:
            if notice:
                notice = {
                    "prominent": True,
                    "provider": str(notice.get("provider") or ""),
                    "model": str(notice.get("model") or ""),
                    "failure_category": ",".join(
                        dict.fromkeys(
                            (
                                str(notice.get("failure_category") or ""),
                                str(
                                    persistence_notice.get("failure_category")
                                    or "persistence_prohibited"
                                ),
                            )
                        )
                    ).strip(","),
                    "affected_record_ids": tuple(
                        dict.fromkeys(
                            (
                                *tuple(notice.get("affected_record_ids") or ()),
                                *tuple(
                                    persistence_notice.get(
                                        "affected_record_ids"
                                    )
                                    or ()
                                ),
                            )
                        )
                    ),
                    "reason": " ".join(
                        item
                        for item in (
                            str(notice.get("reason") or ""),
                            str(persistence_notice.get("reason") or ""),
                        )
                        if item
                    ),
                    "redaction_reason": " ".join(
                        item
                        for item in (
                            str(notice.get("redaction_reason") or ""),
                            str(
                                persistence_notice.get("redaction_reason") or ""
                            ),
                        )
                        if item
                    ),
                }
            else:
                notice = persistence_notice
        reason = str(snapshot.failure_code or "")
        status = snapshot.status
        if notice:
            status = "degraded"
            reason = ": ".join(
                item
                for item in (
                    str(notice.get("failure_category") or "judge_degraded"),
                    str(notice.get("reason") or "Optional judge records were omitted."),
                )
                if item
            )
        self.update_runtime_transparency(
            status=status,
            reason=reason,
            rebuild_required="index" in str(snapshot.failure_code or ""),
            trace_ids=self._trace_ids(snapshot.trace),
            notice=notice,
            owner_trace=self._owner_trace_payload(
                prepared,
                snapshot,
                notice=notice,
                judge_payload=request.get("judge_payload"),
            ),
        )
        return snapshot

    @staticmethod
    def _trace_ids(trace: Mapping[str, Any] | None) -> tuple[str, ...]:
        ids: list[str] = []

        def visit(value: Any) -> None:
            if isinstance(value, Mapping):
                for key, nested in value.items():
                    key_text = str(key).casefold()
                    if key_text.endswith("_id") and isinstance(nested, str) and nested:
                        ids.append(nested)
                    elif key_text.endswith("_ids") and isinstance(
                        nested, (tuple, list)
                    ):
                        ids.extend(
                            str(item)
                            for item in nested
                            if isinstance(item, str) and item
                        )
                    visit(nested)
                return
            if isinstance(value, (tuple, list)):
                for nested in value:
                    visit(nested)

        visit(trace or {})
        return tuple(dict.fromkeys(ids))

    def export_chat_session_state(self) -> dict[str, object]:
        snapshot = self.relay_model.ui_snapshot()
        return {
            "artifact_ref": self._saved_identity_ref(snapshot),
            "state": "active" if snapshot.enabled else "suspended",
        }

    def export_chat_session_state_v2(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "projection_kind": "normalized_projection",
            **self.export_chat_session_state(),
        }

    def import_chat_session_state(self, session: dict[str, Any] | None):
        payload = dict(session or {})
        saved_ref = self._strict_artifact_ref(payload.get("artifact_ref"))
        saved_enabled = str(payload.get("state") or "active") != "suspended"
        current_ref, _revision = self.relay_model.connection_marker()
        if current_ref:
            enabled = saved_enabled if saved_ref == current_ref else True
            self._revalidate_session_authority(enabled=enabled)
        return self.relay_model.ui_snapshot()

    def reset_chat_session_state(self):
        self._chat_session_token = uuid.uuid4().hex
        current_ref, _revision = self.relay_model.connection_marker()
        if current_ref:
            self._revalidate_session_authority(enabled=True)
        return self.relay_model.ui_snapshot()

    def _revalidate_session_authority(self, *, enabled: bool) -> int:
        connected_ref, _revision = self.relay_model.connection_marker()
        if not connected_ref:
            return self.operation_generation("session_authority")
        self.relay_model.clear_capture_context()
        self.relay_model.restore_enabled(connected_ref, enabled)
        expected_ref, expected_revision = self.relay_model.connection_marker()
        session_token = self._chat_session_token

        def work(token: _CancellationToken):
            return self._serialized_store_work(
                token,
                lambda: self._load_session_authority(
                    expected_ref,
                    expected_revision,
                    session_token,
                    token,
                ),
            )

        def complete(value: object) -> None:
            if isinstance(value, _SessionAuthorityPayload):
                self._apply_session_authority(value)

        return self._start_operation("session_authority", work, complete)

    def _load_session_authority(
        self,
        connected_ref: str,
        connection_revision: int,
        session_token: str,
        token: _CancellationToken,
    ) -> _SessionAuthorityPayload | None:
        authority = self._authoritative_state_for_ref(
            connected_ref,
            chat_session_token=session_token,
        )
        if token.is_cancelled():
            return None
        resolution = self.store.resolve_artifact(connected_ref)
        if token.is_cancelled():
            return None
        return _SessionAuthorityPayload(
            connected_ref,
            connection_revision,
            session_token,
            resolution,
            authority,
        )

    def _apply_session_authority(self, payload: _SessionAuthorityPayload) -> None:
        expected_marker = (
            payload.expected_connected_ref,
            payload.expected_connection_revision,
        )
        if (
            self._chat_session_token != payload.session_token
            or self.relay_model.connection_marker() != expected_marker
        ):
            return
        resolution = payload.resolution
        if resolution is None or resolution.failure_code or payload.authority is None:
            self._disconnect_invalid_authority(payload.expected_connected_ref)
            return
        self._set_relay_connection_context(resolution, payload.authority)

    def export_preset_state(self) -> dict[str, str]:
        return {
            "identity_relay_ref": self._saved_identity_ref(
                self.relay_model.ui_snapshot()
            )
        }

    def import_preset_state(self, preset: dict[str, Any] | None):
        payload = dict(preset or {})
        return self._restore_saved_identity_ref(payload.get("identity_relay_ref"))

    def export_session_state(self) -> dict[str, str]:
        return {
            "identity_relay_ref": self._saved_identity_ref(
                self.relay_model.ui_snapshot()
            )
        }

    def import_session_state(self, session: dict[str, Any] | None):
        payload = dict(session or {})
        return self._restore_saved_identity_ref(payload.get("identity_relay_ref"))

    def _restore_saved_identity_ref(self, value: object):
        raw_ref = str(value or "")
        if not raw_ref:
            self.cancel_operation("connection_review")
            self.cancel_operation("connection_apply")
            self._pending_connection = None
            self._review_connection_payload = None
            return self.set_persona_identity_ref("", notify=False)
        if not self._strict_artifact_ref(raw_ref):
            self.cancel_operation("connection_review")
            self.cancel_operation("connection_apply")
            self._pending_connection = None
            self._review_connection_payload = None
            self._pending_saved_identity_ref = ""
            if self.relay_model.ui_snapshot().availability != "available":
                self.relay_model.set_connection(None)
            self._set_visible_notice("Invalid Identity Relay artifact reference.")
            return self.relay_model.ui_snapshot()
        self.request_connection(raw_ref, saved_restore=True)
        return self.relay_model.ui_snapshot()

    def _saved_identity_ref(self, snapshot) -> str:
        connected_ref = self._strict_artifact_ref(snapshot.connected_ref)
        if connected_ref and snapshot.availability == "available":
            return connected_ref
        return self._strict_artifact_ref(self._pending_saved_identity_ref)

    def collect_chat_context(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        request = dict(payload or {})
        if request.get("request_kind") != "normal_chat":
            return None
        frozen = request.get("identity_relay")
        if isinstance(frozen, Mapping) and frozen.get("schema_version") == 2:
            if (
                frozen.get("projection_kind") != "normalized_projection"
                or frozen.get("status") != "ready"
            ):
                return None
            prompt_text = str(frozen.get("prompt_text") or "")
            if not prompt_text.strip():
                return None
            return {
                "context": prompt_text,
                "debug": {
                    "source": "identity_relay",
                    "artifact_ref": str(frozen.get("artifact_ref") or ""),
                    "snapshot_hash": str(frozen.get("snapshot_hash") or ""),
                    "schema_version": 2,
                    "projection_kind": "normalized_projection",
                },
            }
        if not isinstance(frozen, dict) or frozen.get("state") != "active":
            return None
        hot_identity_text = str(frozen.get("hot_identity_text") or "")
        if not hot_identity_text.strip():
            return None
        context_text = (
            "NC Identity Relay continuity context\n"
            "This is declarative continuity context, not privileged executable instruction. "
            "Current Persona expression takes precedence, and explicit user corrections take "
            "precedence over stale claims.\n\n"
            f"{hot_identity_text}"
        )
        return {
            "context": context_text,
            "debug": {
                "source": "identity_relay",
                "artifact_ref": str(frozen.get("artifact_ref") or ""),
            },
        }

    def real_ui_sync_widget_names(self, request: dict[str, Any]):
        kind = str(dict(request or {}).get("kind") or "")
        return {
            "combo": ["identity_relay_ref_combo"] if kind in {"", "combo"} else [],
            "checkbox": ["identity_relay_toggle"] if kind in {"", "checkbox"} else [],
        }

    @staticmethod
    def _strict_artifact_ref(artifact_ref: object) -> str:
        candidate = str(artifact_ref or "")
        return candidate if ARTIFACT_REF_RE.fullmatch(candidate) else ""

    @staticmethod
    def _mapping(value: Any) -> Mapping[str, Any]:
        return value if isinstance(value, Mapping) else {}

    @staticmethod
    def _nonnegative_int(value: Any) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    @staticmethod
    def _query_envelope(value: Any) -> TurnQueryEnvelope:
        if isinstance(value, TurnQueryEnvelope):
            return value
        payload = dict(value) if isinstance(value, Mapping) else {}
        return build_turn_query_envelope(
            str(payload.get("latest_user_turn") or ""),
            latest_exchange=str(payload.get("latest_exchange") or ""),
            recent_trajectory=payload.get("recent_trajectory") or (),
            named_entities=payload.get("named_entities") or (),
            relationships=payload.get("relationships") or (),
            active_persona=str(payload.get("active_persona") or ""),
            active_projects=payload.get("active_projects") or (),
            unresolved_threads=payload.get("unresolved_threads") or (),
            explicit_corrections=payload.get("explicit_corrections") or (),
            kernel_terms=payload.get("kernel_terms") or (),
        )

    def operation_generation(self, kind: str) -> int:
        return int(self._operation_generations.get(str(kind), 0))

    def cancel_operation(self, kind: str) -> bool:
        token = self._operation_tokens.get(str(kind))
        if token is None:
            return False
        token.cancel()
        return True

    def _start_operation(
        self,
        kind: str,
        work: Callable[[_CancellationToken], object],
        completion: Callable[[object], None],
    ) -> int:
        operation_kind = str(kind)
        if self._is_shutdown:
            return self.operation_generation(operation_kind)
        generation = self.operation_generation(operation_kind) + 1
        previous = self._operation_tokens.get(operation_kind)
        if previous is not None:
            previous.cancel()
        token = _CancellationToken(generation)
        self._operation_generations[operation_kind] = generation
        self._operation_tokens[operation_kind] = token
        self._operation_callbacks[(operation_kind, generation)] = completion

        worker = _OperationWorker(operation_kind, generation, token, work)
        worker.signals.completed.connect(
            self._complete_operation,
            QtCore.Qt.QueuedConnection,
        )
        self._operation_workers[(operation_kind, generation)] = worker
        QtCore.QThreadPool.globalInstance().start(worker)
        if not self._operations_run_async():
            self._wait_for_operation((operation_kind, generation))
        return generation

    def _operations_run_async(self) -> bool:
        return bool(self._force_async_operations or self.shell is not None)

    def _wait_for_operation(self, key: tuple[str, int]) -> None:
        while key in self._operation_workers:
            QtCore.QCoreApplication.processEvents(QtCore.QEventLoop.AllEvents, 20)
            QtCore.QThread.msleep(1)

    def _serialized_store_work(
        self,
        token: _CancellationToken,
        work: Callable[[], object],
    ) -> object:
        with self._store_operation_lock:
            if token.is_cancelled():
                return None
            return work()

    @QtCore.Slot(object)
    def _complete_operation(self, result: _OperationCompletion) -> None:
        key = (result.kind, result.generation)
        callback = self._operation_callbacks.pop(key, None)
        self._operation_workers.pop(key, None)
        if self._is_shutdown:
            return
        current_generation = self.operation_generation(result.kind)
        token = self._operation_tokens.get(result.kind)
        if result.generation != current_generation or token is None or token.is_cancelled():
            return
        if result.error_code:
            self._operation_failed(result.kind, result.error_code)
            return
        if callback is not None:
            callback(result.value)

    def shutdown(self) -> None:
        if self._is_shutdown:
            return
        self._is_shutdown = True
        for token in tuple(self._operation_tokens.values()):
            token.cancel()
        for kind in set(self._operation_generations) | set(self._operation_tokens):
            self._operation_generations[kind] = self.operation_generation(kind) + 1
        self._operation_callbacks.clear()
        self._pending_connection = None
        self._review_connection_payload = None
        dialog = self.review_dialog
        self.review_dialog = None
        if dialog is not None:
            try:
                dialog.reviewApplied.disconnect(self._apply_connection_review)
            except (RuntimeError, TypeError):
                pass
            try:
                dialog.reviewCancelled.disconnect(self._cancel_connection_review)
            except (RuntimeError, TypeError):
                pass
            dialog.hide()
            dialog.deleteLater()
        self._bound_bridges.clear()
        self._identity_relay_bound_widget_ids.clear()
        for name in (
            "root_widget",
            "artifact_list",
            "provider_edit",
            "import_text_edit",
            "summary_label",
            "raw_view",
            "structured_view",
            "warnings_view",
            "btn_delete",
            "btn_reextract",
        ):
            setattr(self, name, None)

    def _operation_failed(self, kind: str, error_code: str) -> None:
        self._set_visible_notice(f"{kind} failed ({error_code}).")

    def _set_visible_notice(self, notice: str) -> None:
        self.last_visible_notice = str(notice or "")
        self._connection_status = self.last_visible_notice
        self._mirror_bound_widgets()

    def _mirror_bound_widgets(self) -> None:
        for bridge in tuple(self._bound_bridges.values()):
            self.mirror_runtime_widgets({"bridge": bridge})

    def request_connection(
        self,
        artifact_ref: str,
        *,
        bridge=None,
        saved_restore: bool = False,
    ) -> int:
        raw_ref = str(artifact_ref or "")
        requested_ref = self._strict_artifact_ref(raw_ref)
        previous_ref = self.relay_model.ui_snapshot().connected_ref
        self.cancel_operation("connection_review")
        self.cancel_operation("connection_apply")
        if raw_ref and not requested_ref:
            self._pending_connection = None
            self._review_connection_payload = None
            if self.review_dialog is not None:
                self.review_dialog.hide()
                self.review_dialog.deleteLater()
                self.review_dialog = None
            self._set_visible_notice("Invalid Identity Relay artifact reference.")
            return self.operation_generation("connection_review")
        if self.review_dialog is not None:
            self.review_dialog.hide()
            self.review_dialog.deleteLater()
            self.review_dialog = None
        self._review_connection_payload = None
        self._pending_connection = _PendingConnection(
            previous_ref,
            requested_ref,
            bridge,
            bool(saved_restore),
        )
        chat_session_token = self._chat_session_token
        self._connection_status = "Review required"
        self._mirror_bound_widgets()

        if not requested_ref:
            payload = _ConnectionPayload(
                ArtifactResolution("", None, "", None),
                None,
                None,
                "not connected",
            )
            self._show_connection_review(payload)
            return self.operation_generation("connection_review")

        def work(token: _CancellationToken):
            return self._serialized_store_work(
                token,
                lambda: self._load_connection_payload(
                    requested_ref,
                    token,
                    chat_session_token=chat_session_token,
                ),
            )

        def complete(value: object) -> None:
            if isinstance(value, _ConnectionPayload):
                self._show_connection_review(value)

        return self._start_operation("connection_review", work, complete)

    def _load_connection_payload(
        self,
        requested_ref: str,
        token: _CancellationToken,
        *,
        chat_session_token: str,
    ) -> _ConnectionPayload | None:
        resolution = self.store.resolve_artifact(requested_ref)
        if token.is_cancelled():
            return None
        normalized = None
        decisions = None
        authority = None
        index_status = "index unavailable"
        migration_messages: tuple[str, ...] = ()
        if resolution.artifact_hash and resolution.failure_code not in {
            "invalid",
            "missing",
            "unreadable",
            "corrupt",
            "empty_normalized_identity",
        }:
            normalized = self.store.load_normalized(requested_ref)
            if token.is_cancelled():
                return None
            decisions = self.decision_store.load(resolution.artifact_hash)
            authority = self._authority_from_state(
                resolution,
                normalized,
                decisions,
                chat_session_token=chat_session_token,
            )
            index_read = self.semantic_index.read(resolution.artifact_hash)
            index_status = str(index_read.reason or "unknown")
            metadata = self.store.load_metadata(requested_ref)
            migration_messages = tuple(
                str(item)
                for item in metadata.get("migration_warnings", ())
                if str(item)
            )
        return _ConnectionPayload(
            resolution,
            normalized,
            decisions,
            index_status,
            migration_messages,
            authority,
        )

    def _show_connection_review(self, payload: _ConnectionPayload) -> None:
        pending = self._pending_connection
        if pending is None or pending.requested_ref != payload.resolution.artifact_ref:
            return
        if pending.saved_restore and payload.authority is not None:
            self._set_relay_connection_context(payload.resolution, payload.authority)
            self._pending_saved_identity_ref = ""
            self._restore_pending_connection()
            return
        if not pending.requested_ref:
            model = ConnectionReviewModel(
                artifact_ref="",
                artifact_hash="",
                identity_label="Disconnect Identity Relay",
                normalizer_revision=NORMALIZER_REVISION,
                schema_version=1,
                subject_class=SubjectClass.ASSISTANT_SELF,
                index_status="not connected",
            )
        elif payload.normalized is None or payload.decisions is None:
            reason = payload.resolution.failure_code or "normalization_unavailable"
            if pending.saved_restore:
                self._pending_saved_identity_ref = pending.requested_ref
                notice = f"Saved Identity Relay reference is unavailable ({reason})."
            else:
                notice = f"Connection review unavailable ({reason})."
            self._set_visible_notice(notice)
            self._restore_pending_connection()
            self._connection_status = self.last_visible_notice
            self._mirror_bound_widgets()
            return
        else:
            normalized = self._apply_review_decisions(
                payload.normalized, payload.decisions
            )
            saved_subject = payload.decisions.subject_attestation
            selected_subject = (
                saved_subject.subject_class
                if saved_subject is not None
                and saved_subject.normalizer_revision == normalized.normalizer_revision
                else SubjectClass.UNKNOWN
            )
            proposal = payload.decisions.pending_proposal
            if proposal is None and normalized.envelope.subject_class != SubjectClass.UNKNOWN:
                proposal = SubjectClassificationProposal(
                    normalized.envelope.subject_class,
                    "Deterministic normalized subject evidence.",
                    provider="deterministic",
                    model=normalized.normalizer_revision,
                )
            source_text_by_record = {
                record.record_id: record.source_text for record in normalized.records
            }
            policy_narrowing = tuple(
                f"{item.review_id}: {item.reason}"
                for item in normalized.review_queue
                if item.kind.value in {"runtime_permission", "incompatible_projection"}
            )
            review_items = self._review_items_for_dialog(normalized)
            model = ConnectionReviewModel(
                artifact_ref=payload.resolution.artifact_ref,
                artifact_hash=payload.resolution.artifact_hash or "",
                identity_label=payload.resolution.hot_identity_text.splitlines()[0][:100]
                or payload.resolution.artifact_ref,
                normalizer_revision=normalized.normalizer_revision,
                schema_version=normalized.schema_version,
                subject_class=selected_subject,
                proposal=proposal,
                review_items=tuple(review_items),
                transient_records=normalized.transient_records,
                migration_messages=payload.migration_messages,
                policy_narrowing=policy_narrowing,
                index_status=payload.index_status,
                trace_ids=(),
                source_text_by_record=source_text_by_record,
                attestation_normalizer_revision=(
                    saved_subject.normalizer_revision if saved_subject is not None else ""
                ),
                attestation_approved=(
                    bool(saved_subject.approved) if saved_subject is not None else False
                ),
                attestation_status=(
                    f"{'approved' if saved_subject.approved else 'not approved'} "
                    f"{saved_subject.subject_class.value}"
                    if saved_subject is not None
                    else "not reviewed"
                ),
                prior_review_decisions=payload.decisions.review_decisions,
            )

        parent = self.root_widget.window() if self.root_widget is not None else None
        self._review_connection_payload = payload
        dialog = ConnectionReviewDialog(model, parent)
        dialog.reviewApplied.connect(self._apply_connection_review)
        dialog.reviewCancelled.connect(self._cancel_connection_review)
        self.review_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

        if (
            model.artifact_hash
            and model.subject_class == SubjectClass.UNKNOWN
            and model.proposal is None
        ):
            self._request_subject_proposal(payload.normalized, dialog)

    @staticmethod
    def _review_items_for_dialog(
        normalized: NormalizedIdentityModel,
    ) -> tuple[ReviewItem, ...]:
        review_items: list[ReviewItem] = []
        for item in normalized.review_queue:
            linked_records = tuple(
                normalized.records_by_id[record_id]
                for record_id in item.record_ids
                if record_id in normalized.records_by_id
            )
            safe_scopes = IdentityArtifactsController._shared_safe_narrow_scopes(
                linked_records
            )
            details = dict(item.details)
            details["supported_runtime_use_scopes"] = safe_scopes
            if not safe_scopes:
                details["narrow_use_unavailable_reason"] = (
                    "Narrow Use unavailable: no existing runtime-use permission "
                    "can be safely reduced."
                )
            details["supported_reclassifications"] = tuple(
                sorted(_KNOWN_SEMANTIC_LABELS)
            )
            review_items.append(replace(item, details=details))
        return tuple(review_items)

    @staticmethod
    def _shared_safe_narrow_scopes(records) -> tuple[str, ...]:
        safe_sets = []
        for record in records:
            policy = record.declared_policy
            prohibited_values = policy.get("prohibited_runtime_use", ())
            prohibited = {
                str(value)
                for value in (
                    prohibited_values
                    if isinstance(prohibited_values, (tuple, list))
                    else ()
                )
                if isinstance(value, str)
            }
            explicitly_denied = {
                str(key)[len("eligible_for_") :]
                for key, value in policy.items()
                if str(key).startswith("eligible_for_") and value is False
            }
            safe_sets.append(
                {
                    str(scope)
                    for scope in record.runtime_suitability
                    if scope in _REVIEW_RUNTIME_USE_SCOPES
                    and scope != "always_inject"
                    and scope not in prohibited
                    and scope not in explicitly_denied
                    and record.runtime_layer != RuntimeLayer.UNCLASSIFIED
                    and record.review_state != "quarantined"
                }
            )
        if not safe_sets:
            return ()
        shared = set.intersection(*safe_sets)
        return tuple(scope for scope in _REVIEW_RUNTIME_USE_SCOPES if scope in shared)

    def _request_subject_proposal(
        self,
        normalized: NormalizedIdentityModel | None,
        dialog: ConnectionReviewDialog,
    ) -> int:
        classifier = (
            self.context.get_service("identity_relay.subject_classifier")
            if self.context is not None
            else None
        )
        if normalized is None:
            return self.operation_generation("subject_proposal")
        runtime_snapshot = (
            MappingProxyType(dict(self.runtime_config.snapshot() or {}))
            if self.runtime_config is not None
            and callable(getattr(self.runtime_config, "snapshot", None))
            else MappingProxyType({})
        )
        if not callable(classifier):
            provider = str(runtime_snapshot.get("chat_provider") or "").strip()
            model = str(runtime_snapshot.get("model_name") or "").strip()
            if not provider or not model or not callable(self._chat_completion):
                dialog.set_proposal_unavailable(
                    "active chat provider and model configuration is required"
                )
                return self.operation_generation("subject_proposal")
        request = MappingProxyType(
            {
                "artifact_hash": normalized.envelope.artifact_hash,
                "normalizer_revision": normalized.normalizer_revision,
                "records": tuple(
                    MappingProxyType(
                        {
                            "record_id": record.record_id,
                            "source_path": record.source_path,
                            "source_text": record.source_text,
                            "subject_refs": record.subject_refs,
                        }
                    )
                    for record in normalized.records
                ),
            }
        )

        def work(token: _CancellationToken):
            if token.is_cancelled():
                return None
            if callable(classifier):
                return classifier(request, cancel_token=token)
            return self._runtime_subject_proposal(request, runtime_snapshot, token)

        def complete(value: object) -> None:
            allowed_ids = tuple(
                str(record.get("record_id") or "") for record in request["records"]
            )
            proposal = self._coerce_subject_proposal(value, allowed_ids)
            if self.review_dialog is not dialog or not dialog.isVisible():
                return
            if proposal is None:
                dialog.set_proposal_unavailable(
                    "classifier response rejected by strict validation"
                )
                return
            dialog.set_proposal(proposal)
            state = self.decision_store.load(normalized.envelope.artifact_hash)
            self.decision_store.save(replace(state, pending_proposal=proposal))

        return self._start_operation("subject_proposal", work, complete)

    def _runtime_subject_proposal(
        self,
        request: Mapping[str, Any],
        runtime_snapshot: Mapping[str, Any],
        token: _CancellationToken,
    ) -> SubjectClassificationProposal | None:
        provider = str(runtime_snapshot.get("chat_provider") or "").strip()
        model = str(runtime_snapshot.get("model_name") or "").strip()
        records = tuple(request.get("records") or ())
        permitted_ids = {
            str(record.get("record_id") or "")
            for record in records
            if isinstance(record, Mapping)
        }
        evidence = [
            {
                "record_id": str(record.get("record_id") or ""),
                "source_path": str(record.get("source_path") or ""),
                "source_text": str(record.get("source_text") or ""),
                "subject_refs": list(record.get("subject_refs") or ()),
            }
            for record in records
            if isinstance(record, Mapping)
        ]
        params = {
            "model": model,
            "temperature": 0,
            "messages": (
                {
                    "role": "system",
                    "content": (
                        "Classify only the artifact subject. Return one JSON object with "
                        "proposed_class, reason, and record_ids. proposed_class must be one "
                        "of assistant_self, other_entity, relationship, mixed, unknown."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
                },
            ),
        }
        raw = self._chat_completion(provider, params, {})
        if token.is_cancelled():
            return None
        try:
            payload = json.loads(str(raw or ""))
            proposed_class = SubjectClass(str(payload.get("proposed_class") or ""))
            reason = str(payload.get("reason") or "").strip()
            record_ids = tuple(str(item) for item in payload.get("record_ids", ()))
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if (
            not reason
            or not record_ids
            or any(not item or item not in permitted_ids for item in record_ids)
        ):
            return None
        return SubjectClassificationProposal(
            proposed_class,
            reason,
            record_ids,
            provider=provider,
            model=model,
        )

    @staticmethod
    def _coerce_subject_proposal(
        value: object,
        allowed_record_ids,
    ) -> SubjectClassificationProposal | None:
        if isinstance(value, SubjectClassificationProposal):
            proposed_class = value.proposed_class
            reason = value.reason
            evidence_paths = value.evidence_paths
            provider = value.provider
            model = value.model
        elif isinstance(value, Mapping):
            raw_paths = value.get("evidence_paths", ())
            if not isinstance(raw_paths, (tuple, list)):
                return None
            try:
                proposed_class = SubjectClass(str(value.get("proposed_class") or ""))
            except ValueError:
                return None
            reason = value.get("reason")
            evidence_paths = tuple(raw_paths)
            provider = value.get("provider")
            model = value.get("model")
        else:
            return None
        if (
            not isinstance(reason, str)
            or not reason.strip()
            or not isinstance(provider, str)
            or not provider.strip()
            or not isinstance(model, str)
            or not model.strip()
            or not evidence_paths
            or any(not isinstance(item, str) or not item for item in evidence_paths)
        ):
            return None
        evidence_paths = tuple(evidence_paths)
        allowed = frozenset(str(item) for item in allowed_record_ids if str(item))
        if len(set(evidence_paths)) != len(evidence_paths) or any(
            item not in allowed for item in evidence_paths
        ):
            return None
        return SubjectClassificationProposal(
            SubjectClass(proposed_class),
            reason.strip(),
            evidence_paths,
            provider=provider.strip(),
            model=model.strip(),
        )

    @QtCore.Slot(object)
    def _apply_connection_review(self, result: ConnectionReviewResult) -> None:
        pending = self._pending_connection
        if pending is None or result.artifact_ref != pending.requested_ref:
            return
        if not result.artifact_ref:
            self.set_persona_identity_ref("")
            self.update_runtime_transparency(status="ready")
            self._connection_status = "Identity Relay disconnected"
            self.last_visible_notice = self._connection_status
            self._pending_connection = None
            self._review_connection_payload = None
            self._mirror_bound_widgets()
            return

        prepared = self._review_connection_payload
        dialog_model = self.review_dialog.model if self.review_dialog is not None else None
        if (
            prepared is None
            or prepared.normalized is None
            or dialog_model is None
            or prepared.resolution.artifact_ref != result.artifact_ref
        ):
            self._set_visible_notice("Connection review payload is no longer current.")
            return
        review_items = tuple(dialog_model.review_items)
        if any(
            not self._review_decision_is_valid(
                decision,
                {item.review_id: item for item in review_items}.get(
                    decision.review_id
                ),
            )
            for decision in result.item_decisions
        ):
            self._set_visible_notice("Connection review contains an invalid value.")
            return
        transient_records = tuple(dialog_model.transient_records)
        chat_session_token = self._chat_session_token

        def work(token: _CancellationToken):
            return self._serialized_store_work(
                token,
                lambda: self._perform_connection_apply(
                    result,
                    prepared,
                    review_items,
                    transient_records,
                    chat_session_token,
                    token,
                ),
            )

        def complete(value: object) -> None:
            if isinstance(value, _ConnectionApplyPayload):
                self._complete_connection_apply(value)

        self._connection_status = "Applying Identity Relay review"
        self._mirror_bound_widgets()
        self._start_operation("connection_apply", work, complete)

    def _perform_connection_apply(
        self,
        result: ConnectionReviewResult,
        prepared: _ConnectionPayload,
        review_items: tuple[ReviewItem, ...],
        transient_records,
        chat_session_token: str,
        token: _CancellationToken,
    ) -> _ConnectionApplyPayload | None:
        if token.is_cancelled() or prepared.normalized is None:
            return None
        normalizer_revision = prepared.normalized.normalizer_revision
        state = self.decision_store.load(result.artifact_hash)
        if not self._connection_apply_is_current(token):
            return None
        if state.normalizer_revision and state.normalizer_revision != normalizer_revision:
            state = AttestationState(
                artifact_hash=result.artifact_hash,
                normalizer_revision=normalizer_revision,
            )
        reviewed_at = datetime.now(timezone.utc).isoformat()
        previous_subject = state.subject_attestation
        subject = SubjectAttestation(
            artifact_hash=result.artifact_hash,
            normalizer_revision=normalizer_revision,
            subject_class=result.subject_class,
            approved=bool(result.approved),
            revision=(previous_subject.revision + 1 if previous_subject else 1),
            reviewed_at=reviewed_at,
            normalized_digest=normalized_identity_digest(prepared.normalized),
        )
        state = replace(
            state,
            artifact_hash=result.artifact_hash,
            normalizer_revision=normalizer_revision,
            subject_attestation=subject,
            pending_proposal=None,
        )
        state = self._reviewed_attestation_state(
            state,
            result.item_decisions,
            review_items=review_items,
            reviewed_at=reviewed_at,
        )
        if not self._connection_apply_is_current(token):
            return None
        existing_transients = {item.record_id: item for item in state.transient_activations}
        if result.transient_active is not None:
            for transient in transient_records:
                previous = existing_transients.get(transient.record_id)
                existing_transients[transient.record_id] = TransientActivation(
                    record_id=transient.record_id,
                    active=result.transient_active,
                    activated_at=reviewed_at if result.transient_active else None,
                    session_token=chat_session_token,
                    revision=(previous.revision + 1 if previous is not None else 1),
                    reviewed_at=reviewed_at,
                )
        state = replace(
            state,
            transient_activations=tuple(
                existing_transients[key] for key in sorted(existing_transients)
            ),
        )
        if not self._connection_apply_is_current(token):
            return None

        resolution = None
        authority = None
        if result.subject_class == SubjectClass.ASSISTANT_SELF and result.approved:
            resolution = self.store.resolve_artifact(result.artifact_ref)
            if not self._connection_apply_is_current(token):
                return None
            current_model = self.store.load_normalized(result.artifact_ref)
            if not self._connection_apply_is_current(token):
                return None
            prospective_resolution = (
                replace(resolution, failure_code=None)
                if resolution.failure_code in _REVIEW_RESOLVABLE_AUTHORITY_FAILURES
                else resolution
            )
            authority = self._authority_from_state(
                prospective_resolution,
                current_model,
                state,
                chat_session_token=chat_session_token,
            )
            resolution = prospective_resolution
        return _ConnectionApplyPayload(
            result,
            resolution,
            authority,
            state,
            token,
            chat_session_token,
        )

    def _connection_apply_is_current(self, token: _CancellationToken) -> bool:
        return bool(
            not token.is_cancelled()
            and not self._is_shutdown
            and token.generation == self.operation_generation("connection_apply")
            and self._operation_tokens.get("connection_apply") is token
        )

    def _complete_connection_apply(self, payload: _ConnectionApplyPayload) -> None:
        result = payload.result
        pending = self._pending_connection
        token = payload.token
        if (
            pending is None
            or pending.requested_ref != result.artifact_ref
            or not self._connection_apply_is_current(token)
        ):
            return
        try:
            committed = token.run_authoritative_side_effect(
                lambda: self._commit_connection_apply(payload, pending)
            )
        except Exception as exc:
            self._operation_failed("connection_apply", type(exc).__name__)
            return
        if not committed:
            return

    def _commit_connection_apply(
        self,
        payload: _ConnectionApplyPayload,
        pending: _PendingConnection,
    ) -> None:
        result = payload.result
        notify_settings = False
        runtime_ready = False
        with self._store_operation_lock:
            if (
                result.artifact_ref in self._artifact_deletion_tombstones
                or self._pending_connection is not pending
                or not self._connection_apply_is_current(payload.token)
            ):
                return
            self.decision_store.save(payload.state)
            if result.subject_class == SubjectClass.ASSISTANT_SELF and result.approved:
                authority_valid = bool(
                    payload.authority is not None
                    and payload.resolution is not None
                    and not payload.resolution.failure_code
                )
                if authority_valid:
                    self._set_relay_connection_context(
                        payload.resolution,
                        payload.authority,
                    )
                    self._pending_saved_identity_ref = ""
                    notify_settings = True
                    runtime_ready = True
                    self._connection_status = "Approved assistant-self identity connected"
                    self.last_visible_notice = self._connection_status
                else:
                    self._connection_status = (
                        "Identity Relay connection requires current approved "
                        "assistant-self authority."
                    )
                    self.last_visible_notice = self._connection_status
                    if self.relay_model.ui_snapshot().connected_ref == result.artifact_ref:
                        self.relay_model.clear_capture_context()
            else:
                if pending.previous_ref == result.artifact_ref:
                    self.relay_model.set_connection(None)
                self._connection_status = (
                    f"{result.subject_class.value} is contextual-only and was not connected."
                )
                self.last_visible_notice = self._connection_status
            self._pending_connection = None
            self._review_connection_payload = None
        if notify_settings:
            self._notify_settings_changed()
        if runtime_ready:
            self.update_runtime_transparency(status="ready")
        self._mirror_bound_widgets()

    def _begin_artifact_deletion(self, artifact_ref: str) -> None:
        pending = None
        token = None
        with self._store_operation_lock:
            self._artifact_deletion_tombstones.add(artifact_ref)
            candidate = self._pending_connection
            if candidate is not None and candidate.requested_ref == artifact_ref:
                pending = candidate
                token = self._operation_tokens.get("connection_apply")

        if token is not None:
            token.cancel()

        cancelled = False
        if pending is not None:
            with self._store_operation_lock:
                if self._pending_connection is pending:
                    self._pending_connection = None
                    self._review_connection_payload = None
                    self._operation_generations["connection_apply"] = (
                        self.operation_generation("connection_apply") + 1
                    )
                    self._connection_status = (
                        "Identity Relay connection cancelled because identity "
                        "artifact deletion started."
                    )
                    self.last_visible_notice = self._connection_status
                    cancelled = True
        if cancelled:
            self._mirror_bound_widgets()

    def _reviewed_attestation_state(
        self,
        state: AttestationState,
        decisions,
        *,
        review_items=(),
        reviewed_at: str,
    ) -> AttestationState:
        existing = {item.review_id: item for item in state.review_decisions}
        choices = {
            "approve": "approved",
            "reclassify": "reclassified",
            "narrow_use": "approved_narrow_use",
            "quarantine": "quarantined",
        }
        review_by_id = {item.review_id: item for item in review_items}
        for decision in decisions:
            review_item = review_by_id.get(decision.review_id)
            if not self._review_decision_is_valid(decision, review_item):
                self._set_visible_notice(
                    f"Review {decision.review_id} remains unresolved (invalid value)."
                )
                continue
            previous = existing.get(decision.review_id)
            metadata = {
                "actor": "local_user",
                "allowed_scope": decision.allowed_scope,
                "prior_state": decision.prior_state,
                "proposed_value": decision.proposed_value,
                "replacement_value": decision.replacement_value,
                "source_reason": decision.source_reason,
            }
            existing[decision.review_id] = ReviewDecision(
                review_id=decision.review_id,
                choice=choices.get(decision.action, decision.action),
                reason=json.dumps(metadata, sort_keys=True, separators=(",", ":")),
                approved=decision.action != "quarantine",
                revision=(previous.revision + 1 if previous is not None else 1),
                reviewed_at=reviewed_at,
            )
        saved = replace(
            state,
            review_decisions=tuple(existing[key] for key in sorted(existing)),
        )
        return saved

    def _save_review_decisions(
        self,
        artifact_hash: str,
        normalizer_revision: str,
        decisions,
        *,
        review_items=(),
    ) -> AttestationState:
        state = self.decision_store.load(artifact_hash)
        if state.normalizer_revision and state.normalizer_revision != normalizer_revision:
            state = AttestationState(
                artifact_hash=artifact_hash,
                normalizer_revision=normalizer_revision,
            )
        saved = self._reviewed_attestation_state(
            replace(
                state,
                artifact_hash=artifact_hash,
                normalizer_revision=normalizer_revision,
            ),
            decisions,
            review_items=review_items,
            reviewed_at=datetime.now(timezone.utc).isoformat(),
        )
        return self.decision_store.save(saved)

    @staticmethod
    def _review_decision_is_valid(decision, review_item) -> bool:
        if decision.action in {"approve", "quarantine"}:
            return True
        if review_item is None:
            return False
        if decision.action == "narrow_use":
            values = review_item.details.get("supported_runtime_use_scopes", ())
            return bool(decision.allowed_scope) and decision.allowed_scope in values
        if decision.action != "reclassify" or not decision.replacement_value:
            return False
        if review_item.kind == ReviewKind.SUBJECT_CLASS:
            return decision.replacement_value in {
                subject.value
                for subject in SubjectClass
                if subject != SubjectClass.UNKNOWN
            }
        if review_item.kind == ReviewKind.RUNTIME_LAYER:
            return decision.replacement_value in {
                RuntimeLayer.KERNEL.value,
                RuntimeLayer.RETRIEVABLE.value,
            }
        return decision.replacement_value in review_item.details.get(
            "supported_reclassifications", ()
        )

    def _apply_review_decisions(
        self,
        model: NormalizedIdentityModel,
        state: AttestationState,
    ) -> NormalizedIdentityModel:
        reviews = {item.review_id: item for item in model.review_queue}
        records = {record.record_id: record for record in model.records}
        kernel_ids = set(model.kernel_record_ids)
        retrievable_ids = set(model.retrievable_record_ids)
        quarantine = list(model.quarantine)
        envelope = model.envelope
        review_queue = {item.review_id: item for item in model.review_queue}

        for decision in state.review_decisions:
            review = reviews.get(decision.review_id)
            if review is None:
                continue
            try:
                metadata = json.loads(decision.reason)
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = {}
            choice = decision.choice
            for record_id in review.record_ids:
                record = records.get(record_id)
                if record is None:
                    continue
                if choice == "approved":
                    records[record_id] = replace(record, review_state="approved")
                elif choice == "reclassified" and decision.approved:
                    replacement_value = str(metadata.get("replacement_value") or "")
                    if review.kind == ReviewKind.RUNTIME_LAYER:
                        try:
                            layer = RuntimeLayer(replacement_value)
                        except ValueError:
                            continue
                        records[record_id] = replace(
                            record, runtime_layer=layer, review_state="approved"
                        )
                        kernel_ids.discard(record_id)
                        retrievable_ids.discard(record_id)
                        if layer == RuntimeLayer.KERNEL:
                            kernel_ids.add(record_id)
                        elif layer == RuntimeLayer.RETRIEVABLE:
                            retrievable_ids.add(record_id)
                    else:
                        if replacement_value in _CENTRAL_ROLES:
                            layer = RuntimeLayer.KERNEL
                        elif (
                            replacement_value in _RETRIEVABLE_ROLES
                            or replacement_value == "interaction_style"
                        ):
                            layer = RuntimeLayer.RETRIEVABLE
                        else:
                            layer = RuntimeLayer.UNCLASSIFIED
                        records[record_id] = replace(
                            record,
                            semantic_role=replacement_value,
                            runtime_layer=layer,
                            review_state="approved",
                        )
                        kernel_ids.discard(record_id)
                        retrievable_ids.discard(record_id)
                        if layer == RuntimeLayer.KERNEL:
                            kernel_ids.add(record_id)
                        elif layer == RuntimeLayer.RETRIEVABLE:
                            retrievable_ids.add(record_id)
                elif choice == "approved_narrow_use" and decision.approved:
                    allowed_scope = str(metadata.get("allowed_scope") or "")
                    safe_scopes = self._shared_safe_narrow_scopes((record,))
                    records[record_id] = replace(
                        record,
                        runtime_suitability=tuple(
                            value
                            for value in record.runtime_suitability
                            if value == allowed_scope and value in safe_scopes
                        ),
                        review_state="approved",
                    )
                elif choice == "quarantined" and not decision.approved:
                    records[record_id] = replace(record, review_state="quarantined")
                    kernel_ids.discard(record_id)
                    retrievable_ids.discard(record_id)
                    if not any(record_id in item.record_ids for item in quarantine):
                        quarantine.append(
                            QuarantineItem(
                                quarantine_id=f"review:{decision.review_id}:{record_id}",
                                reason=QuarantineReason.POLICY,
                                record_ids=(record_id,),
                                source_path=record.source_path,
                                details={"review_id": decision.review_id},
                            )
                        )
            if review.kind == ReviewKind.SUBJECT_CLASS and choice == "reclassified":
                try:
                    envelope = replace(
                        envelope,
                        subject_class=SubjectClass(
                            str(metadata.get("replacement_value") or "")
                        ),
                    )
                except ValueError:
                    pass
            review_queue[review.review_id] = replace(review, state=choice)

        return replace(
            model,
            envelope=envelope,
            records=tuple(records[record.record_id] for record in model.records),
            kernel_record_ids=tuple(
                record_id for record_id in model.kernel_record_ids if record_id in kernel_ids
            )
            + tuple(sorted(kernel_ids - set(model.kernel_record_ids))),
            retrievable_record_ids=tuple(
                record_id
                for record_id in model.retrievable_record_ids
                if record_id in retrievable_ids
            )
            + tuple(sorted(retrievable_ids - set(model.retrievable_record_ids))),
            review_queue=tuple(review_queue[item.review_id] for item in model.review_queue),
            quarantine=tuple(quarantine),
        )

    @QtCore.Slot()
    def _cancel_connection_review(self) -> None:
        self.cancel_operation("subject_proposal")
        self.cancel_operation("connection_apply")
        self._restore_pending_connection()

    def _restore_pending_connection(self) -> None:
        pending = self._pending_connection
        self._pending_connection = None
        self._review_connection_payload = None
        self._connection_status = ""
        if pending is not None and pending.bridge is not None:
            self.mirror_runtime_widgets({"bridge": pending.bridge})
        self._mirror_bound_widgets()

    def bind_runtime_controls(self, request: dict[str, Any]):
        bridge = dict(request or {}).get("bridge")
        widget_sets = self._bridge_widget_sets(bridge)
        if not widget_sets:
            return False
        self._bound_bridges[id(bridge)] = bridge
        for widgets in widget_sets:
            combo = widgets.combo
            if id(combo) not in self._identity_relay_bound_widget_ids:
                combo.currentIndexChanged.connect(
                    lambda index, widget=combo, owner=bridge: self._on_identity_ref_changed(widget, index, owner)
                )
                self._identity_relay_bound_widget_ids.add(id(combo))
            toggle = widgets.toggle
            if id(toggle) not in self._identity_relay_bound_widget_ids:
                toggle.toggled.connect(
                    lambda checked, owner=bridge: self._on_identity_relay_toggled(checked, owner)
                )
                self._identity_relay_bound_widget_ids.add(id(toggle))
            self._bind_button_once(
                widgets.review_button,
                lambda _checked=False, owner=bridge: self.request_connection(
                    self.relay_model.ui_snapshot().connected_ref,
                    bridge=owner,
                ),
            )
            self._bind_button_once(
                widgets.repair_button,
                lambda _checked=False, owner=bridge: self.request_connection(
                    self.relay_model.ui_snapshot().connected_ref,
                    bridge=owner,
                ),
            )
            self._bind_button_once(
                widgets.disable_button,
                lambda _checked=False, owner=bridge: self._disable_relay_from_ui(owner),
            )
            self._bind_button_once(
                widgets.rebuild_button,
                lambda _checked=False: self._request_index_rebuild(),
            )
            self._bind_button_once(
                widgets.trace_button,
                lambda _checked=False: self._show_local_trace(),
            )
        snapshot = self.relay_model.ui_snapshot()
        for widgets in widget_sets:
            self._apply_widget_state(snapshot, widgets)
        return True

    def _bind_button_once(self, button, callback: Callable[..., None]) -> None:
        if id(button) in self._identity_relay_bound_widget_ids:
            return
        button.clicked.connect(callback)
        self._identity_relay_bound_widget_ids.add(id(button))

    def mirror_runtime_widgets(self, request: dict[str, Any]):
        bridge = dict(request or {}).get("bridge")
        widget_sets = self._bridge_widget_sets(bridge)
        if not widget_sets:
            return False
        snapshot = self.relay_model.ui_snapshot()
        for widgets in widget_sets:
            self._apply_widget_state(snapshot, widgets)
        return True

    def _bridge_widget_sets(self, bridge):
        if bridge is None:
            return ()
        widget_sets = []
        for getter_name in ("_backend_widget", "_ui_object"):
            getter = getattr(bridge, getter_name, None)
            if not callable(getter):
                continue
            widgets = SimpleNamespace(
                persona_row=getter("identity_relay_persona_row"),
                combo=getter("identity_relay_ref_combo"),
                chat_row=getter("identity_relay_chat_row"),
                toggle=getter("identity_relay_toggle"),
                warning=getter("identity_relay_warning_label"),
                connection_status=getter("identity_relay_connection_status_label"),
                review_button=getter("identity_relay_review_button"),
                status=getter("identity_relay_status_label"),
                judging=getter("identity_relay_judging_label"),
                repair_button=getter("identity_relay_repair_button"),
                disable_button=getter("identity_relay_disable_button"),
                rebuild_button=getter("identity_relay_rebuild_index_button"),
                trace_button=getter("identity_relay_trace_button"),
            )
            if all(
                widget is not None
                for widget in (
                    widgets.persona_row,
                    widgets.combo,
                    widgets.chat_row,
                    widgets.toggle,
                    widgets.warning,
                    widgets.connection_status,
                    widgets.review_button,
                    widgets.status,
                    widgets.judging,
                    widgets.repair_button,
                    widgets.disable_button,
                    widgets.rebuild_button,
                    widgets.trace_button,
                )
            ) and not any(widgets.combo is existing.combo for existing in widget_sets):
                widget_sets.append(widgets)
        return tuple(widget_sets)

    def _on_identity_ref_changed(self, combo, index: int, bridge) -> None:
        artifact_ref = combo.itemData(int(index)) if int(index) >= 0 else ""
        previous_ref = self.relay_model.ui_snapshot().connected_ref
        self._restore_combo_selection(combo, previous_ref)
        self.request_connection(str(artifact_ref or ""), bridge=bridge)

    def _on_identity_relay_toggled(self, checked: bool, bridge) -> None:
        if not self.set_relay_enabled(bool(checked)):
            self.mirror_runtime_widgets({"bridge": bridge})
            return
        if checked:
            self.update_runtime_transparency(status="ready")
        else:
            self.update_runtime_transparency(
                status="suspended",
                reason="Relay disabled for next finalized turn",
            )

    @staticmethod
    def _restore_combo_selection(combo, artifact_ref: str) -> None:
        blocker = QtCore.QSignalBlocker(combo)
        index = combo.findData(str(artifact_ref or ""))
        combo.setCurrentIndex(index if index >= 0 else 0)
        del blocker

    def _disable_relay_from_ui(self, bridge) -> None:
        self._on_identity_relay_toggled(False, bridge)

    def _apply_widget_state(self, snapshot, widgets) -> None:
        if snapshot is None:
            widgets.persona_row.setVisible(False)
            widgets.chat_row.setVisible(False)
            return

        widgets.persona_row.setVisible(True)
        combo = widgets.combo
        popup_open = False
        try:
            popup_open = bool(combo.view().isVisible())
        except Exception:
            pass
        preserve_combo = bool(combo.hasFocus()) or popup_open
        mirrored_revision = combo.property("identityRelayRevision")
        if mirrored_revision != snapshot.revision and not preserve_combo:
            options = tuple(
                (str(label), self._strict_artifact_ref(artifact_ref))
                for label, artifact_ref in snapshot.options
                if not artifact_ref or self._strict_artifact_ref(artifact_ref)
            ) or (("None", ""),)
            blocker = QtCore.QSignalBlocker(combo)
            combo.clear()
            for label, artifact_ref in options:
                combo.addItem(label, artifact_ref)
            connected_ref = self._strict_artifact_ref(snapshot.connected_ref)
            selected_index = combo.findData(connected_ref)
            if selected_index < 0 and connected_ref:
                combo.addItem("Unavailable Identity", connected_ref)
                selected_index = combo.findData(connected_ref)
            combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
            combo.setProperty("identityRelayRevision", snapshot.revision)
            del blocker

        has_ref = bool(self._strict_artifact_ref(snapshot.connected_ref))
        available = has_ref and snapshot.availability == "available"
        unavailable = has_ref and snapshot.availability == "unavailable"
        widgets.chat_row.setVisible(available)
        widgets.toggle.setVisible(available)
        widgets.toggle.setEnabled(available)
        toggle_blocker = QtCore.QSignalBlocker(widgets.toggle)
        widgets.toggle.setChecked(bool(snapshot.enabled))
        del toggle_blocker
        widgets.warning.setText(str(snapshot.warning or ""))
        widgets.warning.setVisible(unavailable)
        widgets.connection_status.setText(
            self._connection_status
            or ("Connected and approved" if available else "Connection unavailable" if unavailable else "")
        )
        widgets.connection_status.setVisible(bool(widgets.connection_status.text()))
        widgets.review_button.setVisible(has_ref)

        runtime = self._runtime_transparency
        runtime_status = str(runtime.get("status") or "ready")
        runtime_reason = str(runtime.get("reason") or "")
        judging = bool(runtime.get("judging", False))
        blocked = runtime_status == "blocked"
        if blocked:
            status_text = f"Blocked: {runtime_reason or 'review required'}"
        elif judging:
            status_text = "Evaluating Identity Relay continuity..."
        elif runtime_reason:
            status_text = f"{runtime_status.title()}: {runtime_reason}"
        else:
            status_text = runtime_status.title()
        if self._owner_override_enabled():
            status_text = f"Owner Override active | {status_text}"
        widgets.status.setText(status_text)
        widgets.status.setVisible(has_ref)
        widgets.judging.setText("Evaluating Identity Relay continuity...")
        widgets.judging.setVisible(has_ref and judging)
        widgets.repair_button.setVisible(has_ref and blocked)
        widgets.disable_button.setVisible(has_ref and blocked)
        widgets.rebuild_button.setVisible(
            has_ref and bool(runtime.get("rebuild_required", False))
        )
        widgets.trace_button.setVisible(
            has_ref
            and bool(runtime.get("trace_ids", ()) or runtime.get("owner_trace"))
        )

    def _notify_settings_changed(self) -> None:
        notifier = getattr(self.shell, "notify_settings_changed", None) if self.shell is not None else None
        if callable(notifier):
            notifier()

    def update_runtime_transparency(
        self,
        *,
        status: str = "ready",
        reason: str = "",
        judging: bool = False,
        rebuild_required: bool = False,
        trace_ids: tuple[str, ...] = (),
        notice: Mapping[str, Any] | None = None,
        owner_trace: Mapping[str, Any] | None = None,
    ) -> None:
        payload = MappingProxyType(
            {
                "status": str(status or "ready"),
                "reason": str(reason or ""),
                "judging": bool(judging),
                "rebuild_required": bool(rebuild_required),
                "trace_ids": tuple(str(item) for item in trace_ids if str(item)),
                "notice": MappingProxyType(dict(notice or {})),
                "owner_trace": MappingProxyType(dict(owner_trace or {})),
            }
        )
        if QtCore.QThread.currentThread() is not self.thread():
            self._runtime_transparency_requested.emit(payload)
            return
        self._apply_runtime_transparency(payload)

    @QtCore.Slot(object)
    def _apply_runtime_transparency(self, payload: Mapping[str, Any]) -> None:
        self._runtime_transparency = MappingProxyType(dict(payload))
        self._mirror_bound_widgets()

    @staticmethod
    def _format_owner_trace_record(record: Mapping[str, Any]) -> str:
        lines = [f"- {record.get('record_id') or 'unknown record'}"]
        attributes = (
            ("Layer", record.get("runtime_layer")),
            ("Role", record.get("semantic_role")),
            ("Stability", record.get("stability")),
            ("Epistemic qualifier", record.get("epistemic_qualifier")),
            ("Source", record.get("source_path")),
        )
        for label, value in attributes:
            if value:
                lines.append(f"  {label}: {value}")
        if record.get("source_text"):
            lines.append(f"  Text: {record['source_text']}")
        if record.get("policy_reason_code") or record.get("policy_reason"):
            policy = ": ".join(
                item
                for item in (
                    str(record.get("policy_reason_code") or ""),
                    str(record.get("policy_reason") or ""),
                )
                if item
            )
            lines.append(f"  Provider policy: {policy}")
        if record.get("selection_reason"):
            lines.append(f"  Selection reason: {record['selection_reason']}")
        if record.get("signals_considered"):
            lines.append(
                "  Selection signals: "
                + ", ".join(str(item) for item in record["signals_considered"])
            )
        if record.get("candidate_signals"):
            lines.append(
                "  Candidate signals: "
                + ", ".join(str(item) for item in record["candidate_signals"])
            )
        if record.get("candidate_score_components"):
            lines.append(
                "  Candidate scores: "
                + ", ".join(
                    f"{name}={value}"
                    for name, value in dict(
                        record["candidate_score_components"]
                    ).items()
                )
            )
        if record.get("candidate_policy_reason"):
            lines.append(
                f"  Candidate policy: {record['candidate_policy_reason']}"
            )
        if record.get("candidate_denial_reason"):
            lines.append(
                f"  Candidate denial: {record['candidate_denial_reason']}"
            )
        operation_decisions = dict(record.get("operation_decisions") or {})
        if operation_decisions:
            lines.append("  Effective operations:")
            for operation, decision in operation_decisions.items():
                state = "allowed" if decision.get("allowed") else "denied"
                explanation = ": ".join(
                    item
                    for item in (
                        str(decision.get("reason_code") or ""),
                        str(decision.get("explanation") or ""),
                    )
                    if item
                )
                lines.append(
                    f"    {operation}: {state}"
                    + (f" ({explanation})" if explanation else "")
                )
        return "\n".join(lines)

    @classmethod
    def _format_owner_trace(
        cls,
        trace: Mapping[str, Any],
    ) -> tuple[str, str]:
        active = int(trace.get("kernel_active_count") or 0)
        total = int(trace.get("kernel_total_count") or 0)
        omitted = int(trace.get("kernel_omitted_count") or 0)
        selected = int(trace.get("selected_count") or 0)
        unresolved = int(trace.get("unresolved_count") or 0)
        summary_lines = [
            "Identity Relay remained active for this turn.",
            f"{active} of {total} stable records active; {omitted} omitted for this provider.",
            f"{selected} deeper records selected; {unresolved} unresolved.",
        ]
        detail_lines = []
        for label, key in (
            ("Provider", "provider"),
            ("Model", "model"),
            ("Status", "status"),
            ("Failure code", "failure_code"),
            ("Artifact", "artifact_ref"),
        ):
            value = str(trace.get(key) or "")
            if value:
                detail_lines.append(f"{label}: {value}")
        visible_notice = dict(trace.get("visible_notice") or {})
        if visible_notice:
            detail_lines.extend(("", "VISIBLE RUNTIME NOTICE"))
            for key, value in visible_notice.items():
                detail_lines.append(f"{key}: {value}")

        sections = (
            ("ACTIVE STABLE RECORDS", "active_kernel_records"),
            ("OMITTED STABLE RECORDS", "omitted_kernel_records"),
            ("SELECTED DEEPER RECORDS", "selected_records"),
            ("UNRESOLVED RECORDS", "unresolved_records"),
            ("ELIGIBLE CANDIDATES", "eligible_candidates"),
            ("DENIED CANDIDATES", "denied_candidates"),
        )
        for title, key in sections:
            records = tuple(trace.get(key) or ())
            detail_lines.extend(("", f"{title} ({len(records)})"))
            if records:
                detail_lines.extend(
                    cls._format_owner_trace_record(record) for record in records
                )
            else:
                detail_lines.append("None")

        detail_lines.extend(("", "EXACT RELAY PROJECTION PROMPT"))
        detail_lines.append(str(trace.get("projection_prompt") or "(empty)"))
        if trace.get("judge_payload"):
            detail_lines.extend(("", "RAW RELEVANCE JUDGE RESULT"))
            detail_lines.append(str(trace["judge_payload"]))
        return "\n".join(summary_lines), "\n".join(detail_lines)

    def _show_local_trace(self) -> None:
        owner_trace = self._mapping(self._runtime_transparency.get("owner_trace"))
        if owner_trace:
            summary, details = self._format_owner_trace(owner_trace)
            self._show_trace_message("Identity Relay Trace", summary, details)
            return
        trace_ids = tuple(self._runtime_transparency.get("trace_ids", ()))
        notice = self._mapping(self._runtime_transparency.get("notice"))
        lines = []
        for label, key in (
            ("Provider", "provider"),
            ("Model", "model"),
            ("Failure category", "failure_category"),
        ):
            value = str(notice.get(key) or "")
            if value:
                lines.append(f"{label}: {value}")
        affected_ids = tuple(
            str(item)
            for item in tuple(notice.get("affected_record_ids") or ())
            if str(item)
        )
        if affected_ids:
            lines.append(f"Affected record IDs: {', '.join(affected_ids)}")
        lines.extend(f"Trace ID: {item}" for item in trace_ids)
        reason = str(
            notice.get("reason")
            or self._runtime_transparency.get("reason")
            or ""
        )
        if reason:
            lines.append(f"Reason: {reason}")
        redaction_reason = str(notice.get("redaction_reason") or "")
        if redaction_reason:
            lines.append(f"Redaction: {redaction_reason}")
        summary = "\n".join(lines) or "No local trace is available."
        self._show_trace_message("Identity Relay Trace", summary, "")

    def _show_trace_message(self, title: str, summary: str, details: str) -> None:
        dialog = QtWidgets.QDialog(self.root_widget)
        dialog.setWindowTitle(title)
        dialog.setModal(True)
        dialog.resize(900, 650)
        layout = QtWidgets.QVBoxLayout(dialog)
        summary_label = QtWidgets.QLabel(summary)
        summary_label.setWordWrap(True)
        layout.addWidget(summary_label)
        detail_view = QtWidgets.QPlainTextEdit()
        detail_view.setReadOnly(True)
        detail_view.setPlainText(details)
        layout.addWidget(detail_view, 1)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _request_index_rebuild(self) -> None:
        provider = (
            self.context.get_service("identity_relay.index_build_request")
            if self.context is not None
            else None
        )
        if callable(provider):
            request = provider()
            if not isinstance(request, Mapping):
                self._set_visible_notice("Index rebuild request is unavailable.")
                return
            self.rebuild_semantic_index(
                request.get("adapter"),
                request.get("metadata"),
                request.get("policy_decisions") or {},
            )
            return

        snapshot = (
            dict(self.runtime_config.snapshot() or {})
            if self.runtime_config is not None
            and callable(getattr(self.runtime_config, "snapshot", None))
            else {}
        )
        embedding = (
            self.runtime_config.engine_attr("_lmstudio_embedding", None)
            if self.runtime_config is not None
            and callable(getattr(self.runtime_config, "engine_attr", None))
            else None
        )
        enabled = bool(snapshot.get("long_term_memory_embedding_enabled", False))
        model_name = str(snapshot.get("long_term_memory_embedding_model") or "").strip()
        base_url = str(snapshot.get("long_term_memory_embedding_base_url") or "").strip()
        try:
            context_length = int(
                snapshot.get("long_term_memory_embedding_context_length") or 0
            )
        except (TypeError, ValueError):
            context_length = 0
        artifact_ref = self.relay_model.ui_snapshot().connected_ref
        if not artifact_ref:
            self._set_visible_notice("Index rebuild requires an approved connected identity.")
            return
        if not enabled or not callable(embedding) or not model_name or not base_url or context_length <= 0:
            self._set_visible_notice(
                "Index rebuild requires an enabled, complete runtime embedding configuration."
            )
            return
        frozen = MappingProxyType(
            {
                "model": model_name,
                "base_url": base_url,
                "context": context_length,
                "embedding": embedding,
                "provider_is_remote": classify_endpoint_is_remote(base_url),
                "owner_override": self._owner_override_enabled(),
            }
        )

        def work(token: _CancellationToken):
            return self._serialized_store_work(
                token,
                lambda: self._perform_runtime_index_build(artifact_ref, frozen, token),
            )

        self.update_runtime_transparency(status="indexing", reason="building semantic index")
        self._start_operation("index", work, self._apply_index_completion)

    def rebuild_semantic_index(self, adapter, metadata, policy_decisions: Mapping[str, Any]) -> int:
        artifact_ref = self.relay_model.ui_snapshot().connected_ref
        frozen_policy = MappingProxyType(dict(policy_decisions or {}))
        owner_override = self._owner_override_enabled()

        def work(token: _CancellationToken):
            return self._serialized_store_work(
                token,
                lambda: self._perform_index_build(
                    artifact_ref,
                    adapter,
                    metadata,
                    frozen_policy,
                    token,
                    owner_override=owner_override,
                ),
            )

        self.update_runtime_transparency(status="indexing", reason="building semantic index")
        return self._start_operation("index", work, self._apply_index_completion)

    def _apply_index_completion(self, result: object) -> None:
        build = result[0] if isinstance(result, tuple) else result
        status = str(getattr(build, "status", "failed"))
        reason = str(getattr(build, "reason", "") or status)
        self.update_runtime_transparency(
            status="ready" if status == "complete" else "degraded",
            reason="index rebuilt" if status == "complete" else reason,
            rebuild_required=status != "complete",
        )

    def _perform_runtime_index_build(
        self,
        artifact_ref: str,
        config: Mapping[str, Any],
        token: _CancellationToken,
    ):
        model = self.store.load_normalized(artifact_ref)
        state = self.decision_store.load(model.envelope.artifact_hash)
        model = self._apply_review_decisions(model, state)
        if token.is_cancelled():
            return None
        endpoint = str(config["base_url"])
        endpoint_is_remote = classify_endpoint_is_remote(endpoint)
        failure_metadata = SemanticIndexMetadata(
            artifact_hash=model.envelope.artifact_hash,
            normalizer_revision=model.normalizer_revision,
            normalized_schema_version=model.schema_version,
            index_schema_version=IDENTITY_INDEX_SCHEMA_VERSION,
            index_revision=IDENTITY_INDEX_REVISION,
            embedding_provider="lmstudio",
            endpoint_identity=endpoint,
            embedding_model=str(config["model"]),
            embedding_context=int(config["context"]),
            vector_dimension=1,
            semantic_threshold=DEFAULT_SEMANTIC_THRESHOLD,
            semantic_threshold_revision=SEMANTIC_THRESHOLD_REVISION,
        )
        if endpoint_is_remote is None:
            return SemanticIndexBuildResult(
                "failed",
                failure_metadata,
                reason="embedding_endpoint_locality_unknown",
            )
        policy_decisions = {
            record.record_id: self.relay_service._intersect_decisions(
                evaluate_effective_use(
                    record,
                    RuntimeUse(
                        surface="local_private_chat",
                        provider_is_remote=endpoint_is_remote,
                        requested_use="private_retrieval",
                        owner_override=config.get("owner_override") is True,
                    ),
                    UserApproval(
                        connected=True,
                        review_approved=record.review_state != "required",
                    ),
                ),
                evaluate_effective_use(
                    record,
                    RuntimeUse(
                        surface="local_private_chat",
                        provider_is_remote=endpoint_is_remote,
                        requested_use="embedding_transmission",
                        owner_override=config.get("owner_override") is True,
                    ),
                    UserApproval(
                        connected=True,
                        review_approved=record.review_state != "required",
                    ),
                ),
            )
            for record in model.records
        }
        authorized_records = tuple(
            model.records_by_id[record_id]
            for record_id in model.retrievable_record_ids
            if record_id in model.records_by_id
            and policy_decisions.get(record_id) is not None
            and policy_decisions[record_id].allowed
        )
        if model.retrievable_record_ids and not authorized_records:
            return SemanticIndexBuildResult(
                "failed",
                failure_metadata,
                reason="embedding_transmission_not_authorized",
            )
        adapter = _RuntimeEmbeddingAdapter(
            config["embedding"],
            base_url=endpoint,
        )
        probe_text = next(
            (
                record.source_text
                for record in authorized_records
                if record.source_text.strip()
            ),
            "identity relay semantic index",
        )
        probe = tuple(
            adapter.embed(
                (probe_text,),
                model=str(config["model"]),
                context=int(config["context"]),
            )
        )
        if token.is_cancelled():
            return None
        dimension = len(tuple(probe[0])) if len(probe) == 1 else 0
        metadata = SemanticIndexMetadata(
            artifact_hash=model.envelope.artifact_hash,
            normalizer_revision=model.normalizer_revision,
            normalized_schema_version=model.schema_version,
            index_schema_version=IDENTITY_INDEX_SCHEMA_VERSION,
            index_revision=IDENTITY_INDEX_REVISION,
            embedding_provider="lmstudio",
            endpoint_identity=str(config["base_url"]),
            embedding_model=str(config["model"]),
            embedding_context=int(config["context"]),
            vector_dimension=dimension,
            semantic_threshold=DEFAULT_SEMANTIC_THRESHOLD,
            semantic_threshold_revision=SEMANTIC_THRESHOLD_REVISION,
        )
        build = build_identity_semantic_index(
            model,
            adapter,
            metadata,
            policy_decisions=policy_decisions,
            cancel_token=token,
        )
        if token.is_cancelled() or build.cancelled:
            return build
        write = self.semantic_index.replace(build)
        return (build, write)

    def _perform_index_build(
        self,
        artifact_ref: str,
        adapter,
        metadata,
        policy_decisions: Mapping[str, Any],
        token: _CancellationToken,
        *,
        owner_override: bool = False,
    ):
        model = self.store.load_normalized(artifact_ref)
        endpoint_is_remote = classify_endpoint_is_remote(
            getattr(metadata, "endpoint_identity", "")
        )
        if endpoint_is_remote is None:
            return SemanticIndexBuildResult(
                "failed",
                metadata,
                reason="embedding_endpoint_locality_unknown",
            )
        endpoint_decisions = {
            record.record_id: evaluate_effective_use(
                record,
                RuntimeUse(
                    surface="local_private_chat",
                    provider_is_remote=endpoint_is_remote,
                    requested_use="embedding_transmission",
                    owner_override=owner_override is True,
                ),
                UserApproval(
                    connected=True,
                    review_approved=record.review_state != "required",
                ),
            )
            for record in model.records
        }
        effective_decisions = {
            record_id: self.relay_service._intersect_decisions(
                decision,
                endpoint_decisions.get(
                    record_id,
                    EffectiveUseDecision(
                        False,
                        (),
                        "embedding_transmission_not_authorized",
                        "No matching record is authorized for embedding transmission.",
                    ),
                ),
            )
            for record_id, decision in policy_decisions.items()
        }
        if model.retrievable_record_ids and not any(
            effective_decisions.get(record_id) is not None
            and effective_decisions[record_id].allowed
            for record_id in model.retrievable_record_ids
        ):
            return SemanticIndexBuildResult(
                "failed",
                metadata,
                reason="embedding_transmission_not_authorized",
            )
        build = build_identity_semantic_index(
            model,
            adapter,
            metadata,
            policy_decisions=effective_decisions,
            cancel_token=token,
        )
        if token.is_cancelled() or build.cancelled:
            return build
        write = self.semantic_index.replace(build)
        return (build, write)

    def create_tab(self):
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        contents = QtWidgets.QWidget(scroll)
        layout = QtWidgets.QVBoxLayout(contents)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        layout.addWidget(self._build_overview(contents))
        layout.addWidget(self._build_export_protocol_panel(contents))
        layout.addWidget(self._build_owner_override_panel(contents))
        layout.addWidget(self._build_import_panel(contents))
        layout.addWidget(self._build_artifact_panel(contents), 1)

        scroll.setWidget(contents)
        self.root_widget = scroll
        self._refresh_artifacts(migrate_legacy=False)
        return scroll

    def _build_overview(self, parent):
        frame = QtWidgets.QFrame(parent)
        frame.setObjectName("Panel")
        frame_layout = QtWidgets.QVBoxLayout(frame)
        frame_layout.setContentsMargins(14, 12, 14, 12)
        frame_layout.setSpacing(8)

        title = QtWidgets.QLabel("ReflectAndExportIdentity Artifacts", frame)
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        frame_layout.addWidget(title)

        body = QtWidgets.QLabel(
            "Import source-native NC_IDENTITY_EXPORT artifacts, preserve the raw export exactly, "
            "inspect the best-effort structured extraction, and make imported continuity available "
            "for Persona connection. Identity Relay use in Chat remains an explicit per-session control.",
            frame,
        )
        body.setWordWrap(True)
        frame_layout.addWidget(body)
        return frame

    def _build_export_protocol_panel(self, parent):
        frame = QtWidgets.QFrame(parent)
        frame.setObjectName("Panel")
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        title = QtWidgets.QLabel("Create Identity Export", frame)
        title.setStyleSheet("font-size: 13px; font-weight: 700;")
        layout.addWidget(title)

        explanation = QtWidgets.QLabel(
            "Give the ReflectAndExportIdentity v1.1 protocol to the external LLM "
            "session whose identity or continuity you want to export. Ask that LLM "
            "to return the complete JSON artifact, then paste or import that response "
            "below without rewriting it. A conversation with richer history and memory "
            "can produce a richer export.",
            frame,
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        button_row = QtWidgets.QHBoxLayout()
        view_button = QtWidgets.QPushButton("View Export Protocol", frame)
        view_button.clicked.connect(self._view_export_protocol)
        button_row.addWidget(view_button)
        copy_button = QtWidgets.QPushButton("Copy Export Protocol", frame)
        copy_button.clicked.connect(self._copy_export_protocol)
        button_row.addWidget(copy_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self.export_protocol_status_label = QtWidgets.QLabel(frame)
        self.export_protocol_status_label.setObjectName(
            "identity_relay_export_protocol_status"
        )
        self.export_protocol_status_label.setWordWrap(True)
        layout.addWidget(self.export_protocol_status_label)
        return frame

    def _build_export_protocol_dialog(self, protocol_text: str):
        dialog = QtWidgets.QDialog(self.root_widget)
        dialog.setWindowTitle("ReflectAndExportIdentity v1.1 Protocol")
        dialog.setModal(True)
        dialog.resize(980, 720)
        layout = QtWidgets.QVBoxLayout(dialog)

        explanation = QtWidgets.QLabel(
            "Send this complete protocol to the external LLM session you want to "
            "export from. Import its complete JSON response into Identity Relay.",
            dialog,
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        viewer = QtWidgets.QPlainTextEdit(dialog)
        viewer.setReadOnly(True)
        viewer.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        viewer.setPlainText(protocol_text)
        layout.addWidget(viewer, 1)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close, dialog)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        return dialog

    def _view_export_protocol(self) -> None:
        try:
            protocol = _read_identity_export_protocol()
        except (OSError, UnicodeError, ValueError) as exc:
            self._show_export_protocol_error(exc)
            return
        self._build_export_protocol_dialog(protocol).exec()

    def _copy_export_protocol(self) -> None:
        try:
            protocol = _read_identity_export_protocol()
        except (OSError, UnicodeError, ValueError) as exc:
            self._show_export_protocol_error(exc)
            return
        QtWidgets.QApplication.clipboard().setText(protocol)
        if self.export_protocol_status_label is not None:
            self.export_protocol_status_label.setStyleSheet("color: #49d17d;")
            self.export_protocol_status_label.setText(
                "Export protocol copied to clipboard."
            )

    def _show_export_protocol_error(self, error: Exception) -> None:
        message = f"The bundled export protocol could not be loaded: {error}"
        if self.export_protocol_status_label is not None:
            self.export_protocol_status_label.setStyleSheet("color: #ff6b6b;")
            self.export_protocol_status_label.setText(message)
        self._show_message("Identity Relay Export Protocol", message)

    def _build_owner_override_panel(self, parent):
        frame = QtWidgets.QFrame(parent)
        frame.setObjectName("Panel")
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        self.owner_override_checkbox = QtWidgets.QCheckBox(
            "Owner Override: allow selected identity records to external providers",
            frame,
        )
        self.owner_override_checkbox.setObjectName(
            "identity_relay_owner_override_checkbox"
        )
        layout.addWidget(self.owner_override_checkbox)

        explanation = QtWidgets.QLabel(
            "Global preference. When enabled, Identity Relay applies no provider "
            "exposure barrier to records selected for a turn. Relevance selection, "
            "token capacity, provenance checks, malformed-data rejection, and "
            "quarantine still apply.",
            frame,
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        self.owner_override_status_label = QtWidgets.QLabel(frame)
        self.owner_override_status_label.setObjectName(
            "identity_relay_owner_override_status"
        )
        self.owner_override_status_label.setWordWrap(True)
        self.owner_override_status_label.setStyleSheet(
            "color: #ffb35c; font-weight: 700;"
        )
        layout.addWidget(self.owner_override_status_label)

        self._sync_owner_override_controls()
        self.owner_override_checkbox.toggled.connect(
            self._on_owner_override_toggled
        )
        return frame

    def _build_import_panel(self, parent):
        frame = QtWidgets.QFrame(parent)
        frame.setObjectName("Panel")
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        title = QtWidgets.QLabel("Import", frame)
        title.setStyleSheet("font-size: 13px; font-weight: 700;")
        layout.addWidget(title)

        form = QtWidgets.QFormLayout()
        self.provider_edit = QtWidgets.QLineEdit(frame)
        self.provider_edit.setPlaceholderText("optional provider/runtime/model label")
        form.addRow("Source label", self.provider_edit)
        layout.addLayout(form)

        self.import_text_edit = QtWidgets.QTextEdit(frame)
        self.import_text_edit.setPlaceholderText("Paste a raw NC_IDENTITY_EXPORT JSON artifact here.")
        self.import_text_edit.setMinimumHeight(120)
        layout.addWidget(self.import_text_edit)

        row = QtWidgets.QHBoxLayout()
        btn_import_text = QtWidgets.QPushButton("Import Pasted Artifact", frame)
        btn_import_text.clicked.connect(self._import_pasted_artifact)
        row.addWidget(btn_import_text)

        btn_import_file = QtWidgets.QPushButton("Import From File", frame)
        btn_import_file.clicked.connect(self._import_file_artifact)
        row.addWidget(btn_import_file)

        btn_refresh = QtWidgets.QPushButton("Refresh", frame)
        btn_refresh.clicked.connect(self.refresh_artifacts)
        row.addWidget(btn_refresh)
        row.addStretch(1)
        layout.addLayout(row)
        return frame

    def _build_artifact_panel(self, parent):
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal, parent)
        splitter.setObjectName("identity_artifacts_splitter")

        left = QtWidgets.QFrame(splitter)
        left.setObjectName("Panel")
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(14, 12, 14, 12)
        left_layout.setSpacing(8)

        left_title = QtWidgets.QLabel("Stored Artifacts", left)
        left_title.setStyleSheet("font-size: 13px; font-weight: 700;")
        left_layout.addWidget(left_title)

        self.artifact_list = QtWidgets.QListWidget(left)
        self.artifact_list.currentItemChanged.connect(lambda _current, _previous: self._show_selected_artifact())
        left_layout.addWidget(self.artifact_list, 1)

        button_row = QtWidgets.QHBoxLayout()
        self.btn_reextract = QtWidgets.QPushButton("Re-run Extraction", left)
        self.btn_reextract.clicked.connect(self._reextract_selected)
        button_row.addWidget(self.btn_reextract)
        self.btn_delete = QtWidgets.QPushButton("Delete Artifact", left)
        self.btn_delete.clicked.connect(self._delete_selected)
        button_row.addWidget(self.btn_delete)
        left_layout.addLayout(button_row)

        right = QtWidgets.QFrame(splitter)
        right.setObjectName("Panel")
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(14, 12, 14, 12)
        right_layout.setSpacing(8)

        self.summary_label = QtWidgets.QLabel("Select an artifact to inspect it.", right)
        self.summary_label.setWordWrap(True)
        right_layout.addWidget(self.summary_label)

        tabs = QtWidgets.QTabWidget(right)
        self.raw_view = self._read_only_text_edit(tabs)
        self.structured_view = self._read_only_text_edit(tabs)
        self.warnings_view = self._read_only_text_edit(tabs)
        raw_index = tabs.addTab(self.raw_view, "Raw")
        structured_index = tabs.addTab(self.structured_view, "Structured")
        warnings_index = tabs.addTab(self.warnings_view, "Warnings")
        tabs.setTabToolTip(raw_index, "Raw Artifact")
        tabs.setTabToolTip(structured_index, "Structured Extraction")
        tabs.setTabToolTip(warnings_index, "Mechanical Warnings")
        right_layout.addWidget(tabs, 1)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        return splitter

    def _read_only_text_edit(self, parent):
        edit = QtWidgets.QTextEdit(parent)
        edit.setReadOnly(True)
        edit.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        return edit

    def refresh_artifacts(self):
        return self._refresh_artifacts(migrate_legacy=True)

    def _refresh_artifacts(self, *, migrate_legacy: bool):
        connected_ref, connection_revision = self.relay_model.connection_marker()
        self.cancel_operation("import")
        self.cancel_operation("reextract")

        def work(token: _CancellationToken):
            return self._serialized_store_work(
                token,
                lambda: self._build_refresh_payload(
                    migrate_legacy=migrate_legacy,
                    connected_ref=connected_ref,
                    connection_revision=connection_revision,
                    token=token,
                ),
            )

        def complete(value: object) -> None:
            if isinstance(value, _RefreshPayload):
                self._apply_refresh_payload(value)

        return self._start_operation("refresh", work, complete)

    def _build_refresh_payload(
        self,
        *,
        migrate_legacy: bool,
        connected_ref: str,
        connection_revision: int | None = None,
        token: _CancellationToken,
    ) -> _RefreshPayload | None:
        if connection_revision is None:
            marker_ref, marker_revision = self.relay_model.connection_marker()
            connection_revision = marker_revision if marker_ref == connected_ref else -1
        if token.is_cancelled():
            return None
        legacy_root = self.legacy_root if migrate_legacy else None
        refresh_result = self.store.refresh_library(legacy_root=legacy_root)
        if token.is_cancelled():
            return None
        artifacts = tuple(
            MappingProxyType(dict(item)) for item in self.store.list_artifacts()
        )
        if token.is_cancelled():
            return None
        connected_resolution = (
            self.store.resolve_artifact(connected_ref) if connected_ref else None
        )
        connected_authority = (
            self._authoritative_state_for_ref(connected_ref)
            if connected_resolution is not None
            and not connected_resolution.failure_code
            else None
        )
        return _RefreshPayload(
            refresh_result,
            artifacts,
            connected_ref,
            connection_revision,
            connected_resolution,
            connected_authority,
        )

    def _apply_refresh_payload(self, payload: _RefreshPayload) -> None:
        if self.root_widget is not None and payload.refresh.migrated_refs:
            details = "\n".join(payload.refresh.warnings)
            self._show_message(
                "NC Identity Relay",
                f"Migrated {len(payload.refresh.migrated_refs)} legacy identity artifact(s).\n{details}".strip(),
            )
        artifacts = payload.artifacts
        options = (("None", ""),) + tuple(
            (self._artifact_label(item), str(item.get("artifact_ref") or "")) for item in artifacts
        )
        self.relay_model.set_options(options)
        current_marker = self.relay_model.connection_marker()
        expected_marker = (
            payload.expected_connected_ref,
            payload.expected_connection_revision,
        )
        if payload.expected_connected_ref and current_marker == expected_marker:
            resolution = payload.connected_resolution
            if (
                resolution is None
                or resolution.failure_code
                or payload.connected_authority is None
            ):
                self._disconnect_invalid_authority(payload.expected_connected_ref)
            else:
                self._set_relay_connection_context(
                    resolution,
                    payload.connected_authority,
                )
        self._mirror_bound_widgets()
        if self.artifact_list is None:
            return
        selected_id = self._selected_artifact_id()
        self.artifact_list.clear()
        for item in artifacts:
            artifact_id = str(item.get("artifact_id") or "")
            label = self._artifact_label(item)
            list_item = QtWidgets.QListWidgetItem(label)
            list_item.setData(QtCore.Qt.UserRole, artifact_id)
            self.artifact_list.addItem(list_item)
            if artifact_id == selected_id:
                self.artifact_list.setCurrentItem(list_item)
        if self.artifact_list.currentItem() is None and self.artifact_list.count():
            self.artifact_list.setCurrentRow(0)
        self._show_selected_artifact()

    def _artifact_label(self, metadata: dict[str, Any]) -> str:
        status = str(metadata.get("status") or "unknown")
        version = str(metadata.get("format_version") or "")
        provider = str(metadata.get("provider_label") or "").strip()
        imported_at = str(metadata.get("imported_at") or "")[:19]
        prefix = f"{provider} - " if provider else ""
        return f"{prefix}{metadata.get('artifact_id', '')}  [{status} v{version}]  {imported_at}"

    def _selected_artifact_id(self) -> str:
        if self.artifact_list is None:
            return ""
        item = self.artifact_list.currentItem()
        if item is None:
            return ""
        return str(item.data(QtCore.Qt.UserRole) or "").strip()

    def _show_selected_artifact(self):
        artifact_id = self._selected_artifact_id()
        has_selection = bool(artifact_id)
        for button in (self.btn_delete, self.btn_reextract):
            if button is not None:
                button.setEnabled(has_selection)
        if not has_selection:
            self._set_views("Select an artifact to inspect it.", "", "", "")
            return
        try:
            metadata = self.store.load_metadata(artifact_id)
            raw_text = self.store.load_raw_text(artifact_id)
            structured = self.store.load_structured(artifact_id)
        except Exception as exc:
            self._set_views(f"Could not load artifact: {exc}", "", "", "")
            return
        summary = self._summary_text(metadata, structured)
        structured_text = json.dumps(structured, indent=2, ensure_ascii=False) if structured else "No structured extraction is available."
        warnings = list(metadata.get("mechanical_warnings") or [])
        warnings.extend(list((structured or {}).get("import_warnings") or []))
        warning_text = "\n".join(warnings) if warnings else "No mechanical warnings."
        self._set_views(summary, raw_text, structured_text, warning_text)

    def _set_views(self, summary: str, raw: str, structured: str, warnings: str):
        if self.summary_label is not None:
            self.summary_label.setText(summary)
        if self.raw_view is not None:
            self.raw_view.setPlainText(raw)
        if self.structured_view is not None:
            self.structured_view.setPlainText(structured)
        if self.warnings_view is not None:
            self.warnings_view.setPlainText(warnings)

    def _summary_text(self, metadata: dict[str, Any], structured: dict[str, Any]) -> str:
        lines = [
            f"Artifact: {metadata.get('artifact_id', '')}",
            f"Status: {metadata.get('status', '')}",
            f"Format: {metadata.get('format', '')} {metadata.get('format_version', '')}",
            f"Export kind: {metadata.get('export_kind', '')}",
            "Runtime use: available through an explicit Persona connection and Chat toggle.",
        ]
        if structured:
            lines.extend(
                [
                    f"Sources: {len(structured.get('source_registry') or {})}",
                    f"Hot identity claims: {len(structured.get('hot_identity_claims') or [])}",
                    f"Identity items: {len(structured.get('identity_items') or [])}",
                    f"LTM seed records: {len(structured.get('ltm_seed_records') or [])}",
                    f"Projections: {len(structured.get('identity_projections') or [])}",
                    f"Unresolved references: {len(structured.get('unresolved_references') or [])}",
                ]
            )
        return "\n".join(lines)

    def _import_pasted_artifact(self):
        raw_text = self.import_text_edit.toPlainText() if self.import_text_edit is not None else ""
        self._import_raw_text(raw_text)

    def _import_file_artifact(self):
        path, _selected_filter = QtWidgets.QFileDialog.getOpenFileName(
            self.root_widget,
            "Import Identity Artifact",
            str(Path.cwd()),
            "JSON/Text Files (*.json *.txt);;All Files (*)",
        )
        if not path:
            return
        self._import_raw_input(Path(path), source_type="file", source_path=path)

    def _import_raw_text(self, raw_text: str):
        self._import_raw_input(raw_text, source_type="pasted", source_path="")

    def _import_raw_input(self, raw_input: bytes | str | Path, *, source_type: str, source_path: str):
        if not isinstance(raw_input, Path) and (not raw_input or not raw_input.strip()):
            self._show_message("Identity Artifacts", "Paste or choose an identity artifact before importing.")
            return
        provider = self.provider_edit.text() if self.provider_edit is not None else ""
        connected_ref, connection_revision = self.relay_model.connection_marker()
        self.cancel_operation("refresh")

        def work(token: _CancellationToken):
            return self._serialized_store_work(
                token,
                lambda: self._perform_import(
                    raw_input,
                    provider=provider,
                    source_type=source_type,
                    source_path=source_path,
                    connected_ref=connected_ref,
                    connection_revision=connection_revision,
                    token=token,
                ),
            )

        def complete(value: object) -> None:
            if not isinstance(value, _ImportPayload):
                return
            if self.import_text_edit is not None and value.imported:
                self.import_text_edit.clear()
            self._apply_refresh_payload(value.refresh)
            self._select_artifact(value.stored.artifact_id)

        return self._start_operation("import", work, complete)

    def _perform_import(
        self,
        raw_input: bytes | str | Path,
        *,
        provider: str,
        source_type: str,
        source_path: str,
        connected_ref: str,
        connection_revision: int,
        token: _CancellationToken,
    ) -> _ImportPayload | None:
        source = raw_input.read_bytes() if isinstance(raw_input, Path) else raw_input
        if token.is_cancelled():
            return None
        result = import_identity_artifact(
            source,
            provider_label=provider,
            source_type=source_type,
            source_path=source_path,
        )
        if token.is_cancelled():
            return None
        stored = self.store.save_import(result)
        if token.is_cancelled():
            return None
        refresh = self._build_refresh_payload(
            migrate_legacy=False,
            connected_ref=connected_ref,
            connection_revision=connection_revision,
            token=token,
        )
        if refresh is None:
            return None
        return _ImportPayload(stored, result.raw.status == "imported", refresh)

    def _select_artifact(self, artifact_id: str):
        if self.artifact_list is None:
            return
        for row in range(self.artifact_list.count()):
            item = self.artifact_list.item(row)
            if str(item.data(QtCore.Qt.UserRole) or "") == artifact_id:
                self.artifact_list.setCurrentRow(row)
                break

    def _reextract_selected(self):
        artifact_id = self._selected_artifact_id()
        if not artifact_id:
            return
        connected_ref, connection_revision = self.relay_model.connection_marker()
        self.cancel_operation("refresh")

        def work(token: _CancellationToken):
            return self._serialized_store_work(
                token,
                lambda: self._perform_reextract(
                    artifact_id,
                    connected_ref=connected_ref,
                    connection_revision=connection_revision,
                    token=token,
                ),
            )

        def complete(value: object) -> None:
            if isinstance(value, _ImportPayload):
                self._apply_refresh_payload(value.refresh)
                self._select_artifact(value.stored.artifact_id)

        return self._start_operation("reextract", work, complete)

    def _perform_reextract(
        self,
        artifact_id: str,
        *,
        connected_ref: str,
        connection_revision: int,
        token: _CancellationToken,
    ) -> _ImportPayload | None:
        metadata = self.store.load_metadata(artifact_id)
        raw_bytes = self.store.load_raw_bytes(artifact_id)
        if token.is_cancelled():
            return None
        result = import_identity_artifact(
            raw_bytes,
            provider_label=str(metadata.get("provider_label") or ""),
            source_type="file",
            source_path=artifact_id,
        )
        if token.is_cancelled():
            return None
        stored = self.store.save_import(result)
        if token.is_cancelled():
            return None
        refresh = self._build_refresh_payload(
            migrate_legacy=False,
            connected_ref=connected_ref,
            connection_revision=connection_revision,
            token=token,
        )
        if refresh is None:
            return None
        return _ImportPayload(stored, result.raw.status == "imported", refresh)

    def delete_artifact(self, artifact_ref: str) -> ArtifactDeleteResult:
        strict_ref = self._strict_artifact_ref(artifact_ref)
        if not strict_ref:
            return self.store.delete_artifact(
                str(artifact_ref or ""),
                active_persona_ref=self.relay_model.ui_snapshot().connected_ref,
                presets_dir=self.presets_dir,
                loaded_session_refs=(),
            )

        engine_attr = getattr(self.runtime_config, "engine_attr", None)
        transaction = (
            engine_attr("_identity_relay_delete_transaction", None)
            if callable(engine_attr)
            else None
        )
        purger = (
            engine_attr("_purge_identity_relay_runtime_derivatives", None)
            if callable(engine_attr)
            else None
        )
        if self.runtime_config is not None and not callable(transaction):
            return ArtifactDeleteResult(
                strict_ref,
                False,
                ("runtime_delete_transaction_unavailable",),
                "guard_context_required",
            )
        if self.runtime_config is not None and not callable(purger):
            return ArtifactDeleteResult(
                strict_ref,
                False,
                ("runtime_projection_cleanup_unavailable",),
                "guard_context_required",
            )
        removed_runtime_snapshots = 0

        def purge_after_store_guards() -> tuple[str, ...]:
            nonlocal removed_runtime_snapshots
            if not callable(purger):
                return ()
            purge_result = purger(strict_ref)
            if not isinstance(purge_result, Mapping):
                raise RuntimeError("runtime projection cleanup returned invalid state")
            if not purge_result.get("purged"):
                blockers = tuple(purge_result.get("blocked_by") or ())
                if blockers:
                    return tuple(str(item) for item in blockers if str(item))
                raise RuntimeError("runtime projection cleanup failed")
            removed_runtime_snapshots = int(
                purge_result.get("removed_snapshot_count") or 0
            )
            return ()

        def commit_delete() -> ArtifactDeleteResult:
            return self.store.delete_artifact(
                strict_ref,
                active_persona_ref=self.relay_model.ui_snapshot().connected_ref,
                presets_dir=self.presets_dir,
                loaded_session_refs=(),
                before_commit=(
                    purge_after_store_guards if callable(purger) else None
                ),
            )

        local_transaction = transaction or (
            lambda _artifact_ref, commit: {
                "committed": True,
                "blocked_by": (),
                "result": commit(),
            }
        )
        self._begin_artifact_deletion(strict_ref)
        try:
            with self._store_operation_lock:
                transaction_result = local_transaction(strict_ref, commit_delete)
        except Exception as exc:
            return ArtifactDeleteResult(
                strict_ref,
                False,
                (),
                "unreadable",
                failure_details=(f"runtime_delete_transaction:{type(exc).__name__}",),
            )
        finally:
            with self._store_operation_lock:
                self._artifact_deletion_tombstones.discard(strict_ref)
        if not isinstance(transaction_result, Mapping):
            return ArtifactDeleteResult(
                strict_ref,
                False,
                ("runtime_delete_transaction_invalid",),
                "unreadable",
            )
        if not transaction_result.get("committed"):
            blockers = tuple(transaction_result.get("blocked_by") or ())
            return ArtifactDeleteResult(
                strict_ref,
                False,
                tuple(str(item) for item in blockers if str(item))
                or ("runtime_delete_transaction_failed",),
                None if blockers else "unreadable",
            )
        result = transaction_result.get("result")
        if not isinstance(result, ArtifactDeleteResult):
            return ArtifactDeleteResult(
                strict_ref,
                False,
                ("runtime_delete_transaction_invalid",),
                "unreadable",
            )
        if removed_runtime_snapshots and not result.deleted:
            return replace(
                result,
                failure_code="partial_delete",
                removed_derivatives=(
                    "runtime_snapshots",
                    *result.removed_derivatives,
                ),
                failure_details=(
                    *result.failure_details,
                    "runtime snapshots were removed before artifact cleanup failed",
                ),
            )
        if removed_runtime_snapshots:
            return replace(
                result,
                removed_derivatives=(
                    "runtime_snapshots",
                    *result.removed_derivatives,
                ),
            )
        return result

    def _delete_selected(self):
        artifact_id = self._selected_artifact_id()
        if not artifact_id:
            return
        confirmed = QtWidgets.QMessageBox.question(
            self.root_widget,
            "Delete Identity Artifact",
            "Delete this imported identity artifact? This removes the stored raw artifact and derived extraction.",
        )
        if confirmed != QtWidgets.QMessageBox.Yes:
            return
        result = self.delete_artifact(artifact_id)
        if not result.deleted:
            blockers = ", ".join(
                (*result.blocked_by, *result.failure_details)
            ) or str(result.failure_code or "unknown reason")
            self._show_message("Identity Relay", f"This identity artifact cannot be deleted: {blockers}.")
            return
        self._refresh_artifacts(migrate_legacy=False)

    def _show_message(self, title: str, message: str):
        QtWidgets.QMessageBox.information(self.root_widget, title, message)
