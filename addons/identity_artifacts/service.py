from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, fields, is_dataclass, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from addons.identity_artifacts.attestations import TransientActivationState
from addons.identity_artifacts.judge import (
    JUDGE_OUTPUT_KEYS,
    JudgeBatch,
    JudgeDecision,
    build_judge_batches,
    parse_judge_decision,
)
from addons.identity_artifacts.normalized_model import (
    NormalizedIdentityModel,
    SubjectClass,
    normalized_identity_from_dict,
    normalized_identity_digest,
)
from addons.identity_artifacts.policy import (
    EffectiveUseDecision,
    RuntimeUse,
    UserApproval,
    classify_endpoint_is_remote,
    evaluate_effective_use,
)
from addons.identity_artifacts.projection import (
    CapacityDecision,
    ProjectionResult,
    ProjectionRuntimeState,
    check_projection_capacity,
    render_projection,
)
from addons.identity_artifacts.relay_state import IdentityRelayCapture, IdentityRelayModel
from addons.identity_artifacts.retrieval import (
    CandidateSet,
    TurnQueryEnvelope,
    generate_identity_candidates,
)
from addons.identity_artifacts.retrieval_index import (
    DEFAULT_SEMANTIC_THRESHOLD,
    IDENTITY_INDEX_REVISION,
    IDENTITY_INDEX_SCHEMA_VERSION,
    SEMANTIC_THRESHOLD_REVISION,
    SemanticIndexMetadata,
    SemanticSearchResult,
)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _plain(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(_plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def identity_relay_snapshot_hash(snapshot_payload: Mapping[str, Any]) -> str:
    payload = _plain(snapshot_payload)
    if not isinstance(payload, dict):
        raise TypeError("snapshot payload must be a mapping")
    payload.pop("snapshot_hash", None)
    # The durable authorization reference is derived from this hash.
    payload.pop("authorization_record_id", None)
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class IdentityRelayPreparedTurn:
    schema_version: int
    projection_kind: str
    status: str
    capture: IdentityRelayCapture | None
    query: TurnQueryEnvelope | None = None
    normalized_model: NormalizedIdentityModel | None = None
    candidate_set: CandidateSet | None = None
    runtime_state: ProjectionRuntimeState | None = None
    operation_decisions: Mapping[str, Mapping[str, EffectiveUseDecision]] = field(
        default_factory=dict
    )
    authorized_kernel_record_ids: tuple[str, ...] = ()
    omitted_kernel_record_ids: tuple[str, ...] = ()
    deterministic_record_ids: tuple[str, ...] = ()
    judge_batches: tuple[JudgeBatch, ...] = ()
    base_messages: tuple[Mapping[str, Any], ...] = ()
    model_context_limit: int | None = None
    reserved_output_tokens: int | None = None
    persistence_mode: str = "policy"
    trace: Mapping[str, Any] = field(default_factory=dict)
    failure_code: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "authorized_kernel_record_ids",
            tuple(self.authorized_kernel_record_ids),
        )
        object.__setattr__(
            self,
            "omitted_kernel_record_ids",
            tuple(self.omitted_kernel_record_ids),
        )
        object.__setattr__(self, "deterministic_record_ids", tuple(self.deterministic_record_ids))
        object.__setattr__(self, "judge_batches", tuple(self.judge_batches))
        object.__setattr__(self, "operation_decisions", _freeze(self.operation_decisions))
        object.__setattr__(
            self,
            "base_messages",
            tuple(_freeze(dict(message)) for message in self.base_messages),
        )
        object.__setattr__(self, "trace", _freeze(self.trace))


@dataclass(frozen=True, slots=True)
class IdentityRelaySnapshot:
    schema_version: int
    projection_kind: str
    status: str
    artifact_ref: str
    artifact_hash: str
    normalizer_revision: str
    attestation_revision: int
    transient_state: Mapping[str, Any]
    effective_use_decisions: Mapping[str, Any]
    kernel_record_ids: tuple[str, ...]
    prompt_text: str
    selected_record_ids: tuple[str, ...]
    selection_reasons: Mapping[str, str]
    signals_considered: Mapping[str, tuple[str, ...]]
    unresolved_record_ids: tuple[str, ...]
    trace: Mapping[str, Any]
    snapshot_hash: str
    persistence_mode: str
    failure_code: str = ""
    authorization_record_id: str = ""

    def __post_init__(self) -> None:
        for name in ("transient_state", "effective_use_decisions", "selection_reasons", "signals_considered", "trace"):
            object.__setattr__(self, name, _freeze(getattr(self, name)))
        for name in ("kernel_record_ids", "selected_record_ids", "unresolved_record_ids"):
            object.__setattr__(self, name, tuple(getattr(self, name)))


class IdentityRelayService:
    def __init__(
        self,
        relay_model: IdentityRelayModel,
        *,
        store: Any,
        index: Any = None,
        embedding: Any = None,
        candidate_retriever: Any = None,
        judge_renderer: Any = None,
        projection_renderer: Any = None,
        token_counter: Any = None,
    ) -> None:
        self._relay_model = relay_model
        self._store = store
        self._index = index
        self._embedding = embedding
        self._candidate_retriever = candidate_retriever or self._generate_candidates
        self._judge_renderer = judge_renderer or build_judge_batches
        self._projection_renderer = projection_renderer or render_projection
        self._token_counter = token_counter

    def capture_turn(self) -> IdentityRelayCapture | None:
        return self._relay_model.capture_turn()

    def prepare_turn(
        self,
        capture: Any,
        query: TurnQueryEnvelope | None,
        *,
        judge_context_limit: int | None = None,
        judge_token_counter: Any = None,
        judge_output_budget: Any = None,
    ) -> IdentityRelayPreparedTurn:
        if capture is None:
            return IdentityRelayPreparedTurn(
                2,
                "normalized_projection",
                "blocked",
                None,
                failure_code="identity_not_connected",
            )
        if not isinstance(capture, IdentityRelayCapture):
            return self._blocked(None, "invalid_capture")
        if not capture.enabled:
            return IdentityRelayPreparedTurn(
                2,
                "normalized_projection",
                "suspended",
                capture,
            )
        if not isinstance(query, TurnQueryEnvelope):
            return self._blocked(capture, "invalid_query_envelope")
        if not capture.artifact_ref or not capture.artifact_hash:
            return self._blocked(capture, "invalid_artifact_capture", query=query)

        try:
            model = normalized_identity_from_dict(capture.frozen_normalized_model)
        except Exception:
            return self._blocked(capture, "normalized_model_unavailable", query=query)
        if model.envelope.artifact_hash != capture.artifact_hash:
            return self._blocked(capture, "artifact_hash_mismatch", query=query)
        if model.normalizer_revision != capture.normalizer_revision:
            return self._blocked(capture, "normalizer_revision_mismatch", query=query)
        if (
            not capture.normalized_digest
            or not capture.frozen_model_digest
            or normalized_identity_digest(model) != capture.frozen_model_digest
        ):
            return self._blocked(capture, "normalized_digest_mismatch", query=query)
        runtime_payload = capture.runtime_use
        transient_payload = capture.transient_activation
        if type(runtime_payload.get("provider_is_remote")) is not bool:
            return self._blocked(
                capture,
                "provider_locality_required",
                query=query,
                model=model,
            )
        if (
            capture.attestation_revision <= 0
            or not bool(runtime_payload.get("subject_approved", False))
            or self._subject_class(runtime_payload.get("subject_class"))
            != SubjectClass.ASSISTANT_SELF
        ):
            return self._blocked(
                capture,
                "assistant_self_attestation_required",
                query=query,
                model=model,
            )

        review_decisions = self._review_decisions(runtime_payload)
        operation_names = (
            "always_inject",
            "private_retrieval",
            "provider_transmission",
            "persistence_export",
            "debug_trace",
        )
        operation_decisions = {}
        policy_decisions = {}
        semantic_policy_decisions = {}
        transient_states = self._transient_states(transient_payload)
        embedding_endpoint_is_remote = classify_endpoint_is_remote(
            capture.frozen_provider.get("embedding_base_url")
        )
        for record in model.records:
            approval = UserApproval(
                connected=bool(runtime_payload.get("connected", True)),
                review_approved=self._record_review_approved(
                    model,
                    record.record_id,
                    review_decisions,
                ),
                approved_operations=tuple(
                    str(item)
                    for item in runtime_payload.get("approved_operations", ())
                    if str(item)
                ),
            )
            decisions = {
                operation: evaluate_effective_use(
                    record,
                    self._runtime_use(runtime_payload, requested_use=operation),
                    approval,
                )
                for operation in operation_names
            }
            if embedding_endpoint_is_remote is None:
                embedding_decision = EffectiveUseDecision(
                    False,
                    (),
                    "embedding_endpoint_locality_unknown",
                    "Embedding transmission requires a valid endpoint with provable locality.",
                )
            else:
                embedding_decision = evaluate_effective_use(
                    record,
                    RuntimeUse(
                        surface=str(
                            runtime_payload.get("surface") or "local_private_chat"
                        ),
                        provider_is_remote=embedding_endpoint_is_remote,
                        requested_use="embedding_transmission",
                        transient=bool(runtime_payload.get("transient", False)),
                        owner_override=runtime_payload.get("owner_override") is True,
                    ),
                    approval,
                )
            decisions["embedding_transmission"] = embedding_decision
            operation_decisions[record.record_id] = decisions
            required_operations = (
                ("always_inject", "provider_transmission")
                if record.record_id in model.kernel_record_ids
                else ("private_retrieval", "provider_transmission")
            )
            policy_decisions[record.record_id] = self._intersect_decisions(
                *(decisions[operation] for operation in required_operations)
            )
            semantic_policy_decisions[record.record_id] = self._intersect_decisions(
                decisions["private_retrieval"],
                decisions["embedding_transmission"],
            )
        for transient in model.transient_records:
            state = transient_states.get(transient.record_id)
            activation_allowed = bool(
                state is not None and state.active and not state.review_required
            )
            approval = UserApproval(
                connected=bool(runtime_payload.get("connected", True)),
                transient_active=activation_allowed,
                review_approved=self._record_review_approved(
                    model,
                    transient.record_id,
                    review_decisions,
                ),
                approved_operations=tuple(
                    str(item)
                    for item in runtime_payload.get("approved_operations", ())
                    if str(item)
                ),
            )
            decisions = {
                operation: evaluate_effective_use(
                    transient,
                    self._runtime_use(
                        runtime_payload,
                        requested_use=operation,
                        transient=True,
                    ),
                    approval,
                )
                for operation in operation_names
            }
            if embedding_endpoint_is_remote is None:
                embedding_decision = EffectiveUseDecision(
                    False,
                    (),
                    "embedding_endpoint_locality_unknown",
                    "Embedding transmission requires a valid endpoint with provable locality.",
                )
            else:
                embedding_decision = evaluate_effective_use(
                    transient,
                    RuntimeUse(
                        surface=str(
                            runtime_payload.get("surface") or "local_private_chat"
                        ),
                        provider_is_remote=embedding_endpoint_is_remote,
                        requested_use="embedding_transmission",
                        transient=True,
                        owner_override=runtime_payload.get("owner_override") is True,
                    ),
                    approval,
                )
            decisions["embedding_transmission"] = embedding_decision
            operation_decisions[transient.record_id] = decisions
            policy_decisions[transient.record_id] = self._intersect_decisions(
                decisions["private_retrieval"],
                decisions["provider_transmission"],
            )
            semantic_policy_decisions[transient.record_id] = self._intersect_decisions(
                decisions["private_retrieval"],
                decisions["embedding_transmission"],
            )
        authorized_kernel_ids = tuple(
            record_id
            for record_id in model.kernel_record_ids
            if record_id in policy_decisions and policy_decisions[record_id].allowed
        )
        blocked_kernel_ids = tuple(
            record_id
            for record_id in model.kernel_record_ids
            if record_id not in policy_decisions or not policy_decisions[record_id].allowed
        )
        if not authorized_kernel_ids:
            return self._blocked(
                capture,
                "kernel_use_not_authorized",
                query=query,
                model=model,
            )

        try:
            semantic_hits = self._semantic_hits(
                model,
                query,
                semantic_policy_decisions,
                capture,
            )
        except Exception:
            semantic_hits = SemanticSearchResult(
                (),
                False,
                "semantic_lookup_failed",
                False,
                DEFAULT_SEMANTIC_THRESHOLD,
                SEMANTIC_THRESHOLD_REVISION,
            )
        try:
            candidate_set = self._candidate_retriever(
                model,
                query,
                policy_decisions,
                transient_states,
                semantic_hits,
            )
        except Exception:
            return self._blocked(
                capture,
                "candidate_retrieval_failed",
                query=query,
                model=model,
            )
        if not isinstance(candidate_set, CandidateSet):
            return self._blocked(
                capture,
                "candidate_retrieval_failed",
                query=query,
                model=model,
            )
        candidate_set = self._authorized_candidates(
            model,
            candidate_set,
            policy_decisions,
            transient_states,
        )

        max_batch_chars = capture.frozen_provider.get("max_batch_chars", 32_000)
        deterministic_ids = tuple(
            candidate.record_id
            for candidate in candidate_set.eligible
            if candidate.deterministic
        )
        try:
            max_batch_chars = int(max_batch_chars)
            judge_options = {"query": query}
            if (
                type(judge_context_limit) is int
                and judge_context_limit > 0
                and callable(judge_token_counter)
                and callable(judge_output_budget)
            ):
                judge_options.update(
                    {
                        "context_limit": judge_context_limit,
                        "token_counter": judge_token_counter,
                        "output_budget": judge_output_budget,
                    }
                )
            judge_batches = (
                tuple(
                    self._judge_renderer(
                        candidate_set,
                        model,
                        max_batch_chars,
                        **judge_options,
                    )
                )
                if any(not candidate.deterministic for candidate in candidate_set.eligible)
                else ()
            )
            if not all(isinstance(batch, JudgeBatch) for batch in judge_batches):
                raise TypeError("judge renderer returned an invalid batch")
        except Exception:
            return self._blocked(
                capture,
                "judge_request_render_failed",
                query=query,
                model=model,
            )

        runtime_state = ProjectionRuntimeState(
            artifact_ref=capture.artifact_ref,
            subject_attestation_revision=capture.attestation_revision,
            subject_class=self._subject_class(capture.runtime_use.get("subject_class")),
            subject_approved=bool(capture.runtime_use.get("subject_approved", False)),
            candidate_set=candidate_set,
            policy_decisions=policy_decisions,
            transient_states=transient_states,
            review_decisions=review_decisions,
            judge_provider=str(capture.frozen_provider.get("provider_name") or ""),
            judge_model=str(capture.frozen_provider.get("model_name") or ""),
            judge_batch_ids=tuple(batch.candidate_ids for batch in judge_batches),
        )
        base_messages = capture.frozen_provider.get("base_messages", ())
        if not isinstance(base_messages, (list, tuple)):
            base_messages = ()
        semantic_trace = {
            "semantic_available": candidate_set.semantic_available,
            "semantic_reason": candidate_set.semantic_reason,
            "semantic_rebuild_required": semantic_hits.rebuild_required,
            "kernel_policy_narrowed": bool(blocked_kernel_ids),
        }
        if not candidate_set.semantic_available:
            semantic_trace.update(
                {
                    "degradation_state": "degraded",
                    "degradation_reasons": (candidate_set.semantic_reason,),
                }
            )
        return IdentityRelayPreparedTurn(
            schema_version=2,
            projection_kind="normalized_projection",
            status="judge_required" if judge_batches else "ready_without_judge",
            capture=capture,
            query=query,
            normalized_model=model,
            candidate_set=candidate_set,
            runtime_state=runtime_state,
            operation_decisions=operation_decisions,
            authorized_kernel_record_ids=authorized_kernel_ids,
            omitted_kernel_record_ids=blocked_kernel_ids,
            deterministic_record_ids=deterministic_ids,
            judge_batches=judge_batches,
            base_messages=tuple(
                message for message in base_messages if isinstance(message, Mapping)
            ),
            model_context_limit=self._optional_int(
                capture.frozen_provider.get("model_context_limit")
            ),
            reserved_output_tokens=self._optional_int(
                capture.frozen_provider.get("reserved_output_tokens")
            ),
            persistence_mode=str(
                capture.frozen_provider.get("persistence_mode") or "policy"
            ),
            trace=semantic_trace,
        )

    def render_judge_request(
        self,
        prepared: IdentityRelayPreparedTurn,
    ) -> tuple[JudgeBatch, ...]:
        if not isinstance(prepared, IdentityRelayPreparedTurn):
            return ()
        return tuple(prepared.judge_batches)

    def finalize_turn(
        self,
        prepared: IdentityRelayPreparedTurn,
        *,
        judge_payload: Any = None,
    ) -> IdentityRelaySnapshot:
        if not isinstance(prepared, IdentityRelayPreparedTurn):
            raise TypeError("prepared must be an IdentityRelayPreparedTurn")
        if prepared.status in {"suspended", "blocked"}:
            return self._empty_snapshot(prepared)
        if (
            prepared.capture is None
            or prepared.normalized_model is None
            or prepared.runtime_state is None
        ):
            return self._empty_snapshot(
                self._blocked(
                    prepared.capture,
                    "prepared_turn_incomplete",
                    query=prepared.query,
                )
            )
        try:
            decisions = self._judge_decisions(prepared.judge_batches, judge_payload)
        except Exception:
            decisions = tuple(
                self._judge_conversion_failure(batch.candidate_ids)
                for batch in prepared.judge_batches
            )
        try:
            projection_model = replace(
                prepared.normalized_model,
                kernel_record_ids=prepared.authorized_kernel_record_ids,
            )
            projection = self._projection_renderer(
                projection_model,
                prepared.deterministic_record_ids,
                decisions,
                prepared.runtime_state,
            )
            if not isinstance(projection, ProjectionResult):
                raise TypeError("projection renderer returned an invalid result")
        except Exception:
            return self._failure_snapshot(prepared, "projection_render_failed")
        trace = projection.trace
        status = projection.status
        failure_code = projection.failure_code
        prompt_text = projection.prompt_text
        if (
            status == "ready"
            and self._token_counter is not None
            and prepared.model_context_limit is not None
            and prepared.reserved_output_tokens is not None
        ):
            try:
                capacity = check_projection_capacity(
                    prepared.base_messages,
                    projection,
                    model_context_limit=prepared.model_context_limit,
                    reserved_output_tokens=prepared.reserved_output_tokens,
                    token_counter=self._token_counter,
                )
                if not isinstance(capacity, CapacityDecision):
                    raise TypeError("capacity checker returned an invalid result")
            except Exception:
                return self._failure_snapshot(
                    prepared,
                    "capacity_check_failed",
                    base_trace=projection.trace,
                )
            trace = capacity.trace
            if not capacity.allowed:
                return self._failure_snapshot(
                    prepared,
                    capacity.failure_code or "capacity_denied",
                    base_trace=capacity.trace,
                )

        capture = prepared.capture
        raw_trace_payload = _plain(trace)
        judge_notice = self._judge_degradation_notice(prepared, decisions)
        if status == "blocked" and failure_code:
            raw_trace_payload = self._degradation_trace(
                capture,
                failure_code,
                base_trace=raw_trace_payload,
            )
        (
            debug_mode,
            trace_payload,
            external_operation_decisions,
        ) = self._external_debug_payload(prepared, raw_trace_payload)
        visible_notices = []
        policy_notice = self._visible_policy_narrowing_notice(
            prepared,
            debug_mode=debug_mode,
        )
        if policy_notice:
            visible_notices.append(policy_notice)
        if judge_notice:
            visible_notices.append(
                self._visible_judge_notice(
                    prepared,
                    judge_notice,
                    debug_mode=debug_mode,
                )
            )
        if visible_notices:
            trace_payload["degradation_notice"] = self._merge_visible_notices(
                *visible_notices
            )
        external_transient_state = self._external_transient_state(
            prepared,
            capture.transient_activation,
            debug_mode=debug_mode,
        )
        persistence_mode, persistence_notice = self._projection_persistence(
            prepared,
            projection,
            trace_payload=trace_payload,
            effective_use_decisions=external_operation_decisions,
            transient_state=external_transient_state,
        )
        if persistence_notice:
            trace_payload["persistence_notice"] = self._visible_notice(
                prepared,
                persistence_notice,
                debug_mode=debug_mode,
            )
        snapshot_payload = {
            "schema_version": 2,
            "projection_kind": "normalized_projection",
            "status": status,
            "artifact_ref": capture.artifact_ref,
            "artifact_hash": capture.artifact_hash,
            "normalizer_revision": capture.normalizer_revision,
            "attestation_revision": capture.attestation_revision,
            "transient_state": external_transient_state,
            "effective_use_decisions": external_operation_decisions,
            "kernel_record_ids": prepared.authorized_kernel_record_ids,
            "prompt_text": prompt_text,
            "selected_record_ids": projection.selected_record_ids,
            "selection_reasons": projection.selection_reasons,
            "signals_considered": projection.signals_considered,
            "unresolved_record_ids": projection.unresolved_record_ids,
            "trace": trace_payload,
            "persistence_mode": persistence_mode,
            "failure_code": failure_code,
        }
        snapshot_hash = identity_relay_snapshot_hash(snapshot_payload)
        return IdentityRelaySnapshot(
            **snapshot_payload,
            snapshot_hash=snapshot_hash,
        )

    @staticmethod
    def _generate_candidates(
        model: NormalizedIdentityModel,
        query: TurnQueryEnvelope,
        policy_decisions: Mapping[str, EffectiveUseDecision],
        transient_states: Mapping[str, TransientActivationState],
        semantic_hits: SemanticSearchResult,
    ) -> CandidateSet:
        return generate_identity_candidates(
            model,
            query,
            policy_decisions,
            semantic_hits,
            transient_states=transient_states,
        )

    @staticmethod
    def _authorized_candidates(
        model: NormalizedIdentityModel,
        candidate_set: CandidateSet,
        policy_decisions: Mapping[str, EffectiveUseDecision],
        transient_states: Mapping[str, TransientActivationState],
    ) -> CandidateSet:
        record_ids = set(model.records_by_id)
        transient_ids = {record.record_id for record in model.transient_records}
        quarantined_ids = {
            record_id for item in model.quarantine for record_id in item.record_ids
        }
        eligible = []
        denied_reasons = dict(candidate_set.denial_reasons)
        for candidate in candidate_set.eligible:
            record_id = candidate.record_id
            if record_id in quarantined_ids:
                denied_reasons[record_id] = "quarantined"
                continue
            if record_id in record_ids:
                decision = policy_decisions.get(record_id)
                if decision is None or not decision.allowed:
                    denied_reasons[record_id] = (
                        decision.reason_code if decision is not None else "authorization_required"
                    )
                    continue
            elif record_id in transient_ids:
                decision = policy_decisions.get(record_id)
                state = transient_states.get(record_id)
                if decision is None or not decision.allowed:
                    denied_reasons[record_id] = (
                        decision.reason_code
                        if decision is not None
                        else "authorization_required"
                    )
                    continue
                if state is None or not state.active or state.review_required:
                    denied_reasons[record_id] = (
                        state.reason_code if state is not None else "transient_activation_required"
                    )
                    continue
            else:
                denied_reasons[record_id] = "candidate_record_missing"
                continue
            eligible.append(candidate)
        return CandidateSet(
            eligible=tuple(eligible),
            denied_record_ids=tuple(sorted(denied_reasons)),
            semantic_available=candidate_set.semantic_available,
            semantic_reason=candidate_set.semantic_reason,
            semantic_threshold=candidate_set.semantic_threshold,
            semantic_threshold_revision=candidate_set.semantic_threshold_revision,
            denial_reasons=denied_reasons,
        )

    def _semantic_hits(
        self,
        model: NormalizedIdentityModel,
        query: TurnQueryEnvelope,
        policy_decisions: Mapping[str, EffectiveUseDecision],
        capture: IdentityRelayCapture,
    ) -> SemanticSearchResult:
        unavailable = SemanticSearchResult(
            (),
            False,
            "semantic_dependencies_unavailable",
            False,
            DEFAULT_SEMANTIC_THRESHOLD,
            SEMANTIC_THRESHOLD_REVISION,
        )
        if self._index is None or self._embedding is None:
            return unavailable
        query_text = "\n".join(
            (
                query.latest_user_turn,
                query.latest_exchange,
                *query.recent_trajectory,
                *query.named_entities,
                *query.relationships,
                query.active_persona,
                *query.active_projects,
                *query.unresolved_threads,
                *query.explicit_corrections,
                *query.kernel_terms,
            )
        )
        embedding_model = str(
            capture.frozen_provider.get("embedding_model") or ""
        ).strip()
        embedding_endpoint = str(
            capture.frozen_provider.get("embedding_base_url") or ""
        ).strip()
        try:
            embedding_context = int(
                capture.frozen_provider.get("embedding_context") or 0
            )
        except (TypeError, ValueError):
            embedding_context = 0
        if not embedding_model or not embedding_endpoint or embedding_context <= 0:
            return SemanticSearchResult(
                (),
                False,
                "semantic_configuration_unavailable",
                False,
                DEFAULT_SEMANTIC_THRESHOLD,
                SEMANTIC_THRESHOLD_REVISION,
            )
        if classify_endpoint_is_remote(embedding_endpoint) is None:
            return SemanticSearchResult(
                (),
                False,
                "embedding_endpoint_locality_unknown",
                False,
                DEFAULT_SEMANTIC_THRESHOLD,
                SEMANTIC_THRESHOLD_REVISION,
            )
        authorized_ids = {
            record_id
            for record_id, decision in policy_decisions.items()
            if decision.allowed
        }
        if not authorized_ids:
            return SemanticSearchResult(
                (),
                False,
                "embedding_transmission_not_authorized",
                False,
                DEFAULT_SEMANTIC_THRESHOLD,
                SEMANTIC_THRESHOLD_REVISION,
            )
        try:
            embed = getattr(self._embedding, "embed", self._embedding)
            embed_for_capture = getattr(self._embedding, "embed_for_capture", None)
            if callable(embed_for_capture):
                embed = embed_for_capture
                embed_kwargs = {
                    "model": embedding_model,
                    "context": embedding_context,
                    "base_url": str(
                        capture.frozen_provider.get("embedding_base_url") or ""
                    ),
                }
            else:
                embed_kwargs = {
                    "model": embedding_model,
                    "context": embedding_context,
                }
            vectors = tuple(
                embed(
                    (query_text,),
                    **embed_kwargs,
                )
            )
            if len(vectors) != 1:
                return unavailable
            query_vector = tuple(vectors[0])
            expected_metadata = SemanticIndexMetadata(
                artifact_hash=model.envelope.artifact_hash,
                normalizer_revision=model.normalizer_revision,
                normalized_schema_version=model.schema_version,
                index_schema_version=IDENTITY_INDEX_SCHEMA_VERSION,
                index_revision=IDENTITY_INDEX_REVISION,
                embedding_provider=str(
                    capture.frozen_provider.get("embedding_provider") or "lmstudio"
                ),
                endpoint_identity=embedding_endpoint,
                embedding_model=embedding_model,
                embedding_context=embedding_context,
                vector_dimension=len(query_vector),
            )
            search = getattr(self._index, "search", self._index)
            result = search(
                model.envelope.artifact_hash,
                query_vector,
                expected_metadata=expected_metadata,
                authorized_record_ids=authorized_ids,
            )
        except Exception:
            return SemanticSearchResult(
                (),
                False,
                "semantic_lookup_failed",
                False,
                DEFAULT_SEMANTIC_THRESHOLD,
                SEMANTIC_THRESHOLD_REVISION,
            )
        if not isinstance(result, SemanticSearchResult):
            return SemanticSearchResult(
                (),
                False,
                "semantic_lookup_failed",
                False,
                DEFAULT_SEMANTIC_THRESHOLD,
                SEMANTIC_THRESHOLD_REVISION,
            )
        return result

    @staticmethod
    def _runtime_use(
        value: Mapping[str, Any], *, requested_use: str, transient: bool = False
    ) -> RuntimeUse:
        return RuntimeUse(
            surface=str(value.get("surface") or "local_private_chat"),
            provider_is_remote=bool(value.get("provider_is_remote", False)),
            requested_use=str(requested_use or ""),
            transient=bool(transient),
            owner_override=value.get("owner_override") is True,
        )

    @staticmethod
    def _intersect_decisions(
        *decisions: EffectiveUseDecision,
    ) -> EffectiveUseDecision:
        denied = next((decision for decision in decisions if not decision.allowed), None)
        if denied is not None:
            return denied
        effective_uses = tuple(
            dict.fromkeys(
                use for decision in decisions for use in decision.effective_uses
            )
        )
        narrowed = tuple(
            decision.explanation
            for decision in decisions
            if decision.reason_code == "allowed_narrowed"
        )
        if narrowed:
            return EffectiveUseDecision(
                True,
                effective_uses,
                "allowed_narrowed",
                " ".join(narrowed),
            )
        return EffectiveUseDecision(
            True,
            effective_uses,
            "allowed",
            "Every required runtime operation is authorized.",
        )

    @staticmethod
    def _review_decisions(value: Mapping[str, Any]) -> Mapping[str, str]:
        decisions = value.get("review_decisions", {})
        if not isinstance(decisions, Mapping):
            return MappingProxyType({})
        return MappingProxyType(
            {str(key): str(item) for key, item in decisions.items()}
        )

    @staticmethod
    def _record_review_approved(
        model: NormalizedIdentityModel,
        record_id: str,
        review_decisions: Mapping[str, str],
    ) -> bool:
        linked = tuple(
            item.review_id for item in model.review_queue if record_id in item.record_ids
        )
        return bool(linked) and all(
            str(review_decisions.get(review_id, "")).casefold().startswith("approved")
            for review_id in linked
        )

    @staticmethod
    def _transient_states(
        value: Mapping[str, Any],
    ) -> Mapping[str, TransientActivationState]:
        states: dict[str, TransientActivationState] = {}
        for record_id, item in value.items():
            if isinstance(item, TransientActivationState):
                states[str(record_id)] = item
            elif isinstance(item, Mapping):
                states[str(record_id)] = TransientActivationState(
                    active=bool(item.get("active", False)),
                    review_required=bool(item.get("review_required", False)),
                    reason_code=str(item.get("reason_code") or "inactive"),
                    expires_at=item.get("expires_at"),
                )
        return MappingProxyType(states)

    @staticmethod
    def _subject_class(value: Any) -> SubjectClass:
        try:
            return SubjectClass(str(value or SubjectClass.UNKNOWN.value))
        except ValueError:
            return SubjectClass.UNKNOWN

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @staticmethod
    def _judge_decisions(
        batches: Sequence[JudgeBatch],
        payload: Any,
    ) -> tuple[JudgeDecision, ...]:
        if not batches:
            return ()
        if isinstance(payload, JudgeDecision):
            return (payload,)
        if isinstance(payload, Mapping):
            try:
                is_complete_payload = set(payload) == set(JUDGE_OUTPUT_KEYS)
            except Exception:
                return tuple(
                    IdentityRelayService._judge_conversion_failure(batch.candidate_ids)
                    for batch in batches
                )
            if is_complete_payload:
                allowed_ids = tuple(
                    record_id for batch in batches for record_id in batch.candidate_ids
                )
                try:
                    decision = parse_judge_decision(
                        json.dumps(dict(payload), ensure_ascii=False),
                        allowed_ids,
                    )
                except Exception:
                    return tuple(
                        IdentityRelayService._judge_conversion_failure(
                            batch.candidate_ids
                        )
                        for batch in batches
                    )
                return (IdentityRelayService._complete_judge_decision(
                    decision,
                    allowed_ids,
                    raw_value=payload,
                ),)
            decisions = []
            for batch in batches:
                try:
                    value = payload.get(batch.batch_id)
                except Exception:
                    decisions.append(
                        IdentityRelayService._judge_conversion_failure(
                            batch.candidate_ids
                        )
                    )
                    continue
                decisions.append(
                    IdentityRelayService._judge_decision_for_batch(batch, value)
                )
            return tuple(decisions)
        if isinstance(payload, (list, tuple)):
            values = tuple(payload)
            return tuple(
                item
                if isinstance(item, JudgeDecision)
                else IdentityRelayService._judge_decision_for_batch(
                    batches[index],
                    item,
                )
                for index, item in enumerate(values[: len(batches)])
            ) + tuple(
                IdentityRelayService._judge_decision_for_batch(batch, "")
                for batch in batches[len(values) :]
            )
        allowed_ids = tuple(
            record_id for batch in batches for record_id in batch.candidate_ids
        )
        try:
            decision = parse_judge_decision(str(payload or ""), allowed_ids)
            return (IdentityRelayService._complete_judge_decision(
                decision,
                allowed_ids,
                raw_value=payload,
            ),)
        except Exception:
            return tuple(
                IdentityRelayService._judge_conversion_failure(batch.candidate_ids)
                for batch in batches
            )

    @staticmethod
    def _judge_decision_for_batch(
        batch: JudgeBatch,
        value: Any,
    ) -> JudgeDecision:
        try:
            if isinstance(value, Mapping) and value.get("failure_category"):
                category = str(value.get("failure_category") or "provider_exception").strip()
                reason = str(value.get("reason") or category).strip()
                return JudgeDecision(
                    unresolved_record_ids=batch.candidate_ids,
                    valid=False,
                    failure_reason=category,
                    failure_detail=reason,
                )
            decision = parse_judge_decision(str(value or ""), batch.candidate_ids)
            return IdentityRelayService._complete_judge_decision(
                decision,
                batch.candidate_ids,
                raw_value=value,
            )
        except Exception:
            return IdentityRelayService._judge_conversion_failure(
                batch.candidate_ids
            )

    @staticmethod
    def _judge_conversion_failure(
        candidate_ids: Sequence[str],
    ) -> JudgeDecision:
        return JudgeDecision(
            unresolved_record_ids=tuple(str(item) for item in candidate_ids if str(item)),
            valid=False,
            failure_reason="payload_conversion_failed",
            failure_detail=(
                "Judge output conversion failed for this optional relevance batch."
            ),
        )

    @staticmethod
    def _complete_judge_decision(
        decision: JudgeDecision,
        allowed_ids: Sequence[str],
        *,
        raw_value: Any,
    ) -> JudgeDecision:
        if decision.valid:
            return decision
        detail = f"Judge output was rejected: {decision.failure_reason or 'invalid_output'}."
        if isinstance(raw_value, Mapping) and raw_value.get("reason"):
            detail = str(raw_value.get("reason") or detail)
        return replace(
            decision,
            unresolved_record_ids=tuple(str(item) for item in allowed_ids if str(item)),
            failure_detail=detail,
        )

    @staticmethod
    def _judge_degradation_notice(
        prepared: IdentityRelayPreparedTurn,
        decisions: Sequence[JudgeDecision],
    ) -> Mapping[str, Any]:
        categories: list[str] = []
        affected_ids: list[str] = []
        reasons: list[str] = []
        for decision in decisions:
            if not decision.valid:
                categories.append(decision.failure_reason or "invalid_output")
                reasons.append(
                    decision.failure_detail
                    or f"Judge output was rejected: {decision.failure_reason or 'invalid_output'}."
                )
            if decision.invalid_record_ids:
                categories.append("unknown_record_ids")
                reasons.append("Judge output referred to record IDs outside the authorized batch.")
            affected_ids.extend(decision.unresolved_record_ids)
            affected_ids.extend(decision.invalid_record_ids)
        if not categories:
            return MappingProxyType({})
        runtime_state = prepared.runtime_state
        return MappingProxyType(
            {
                "prominent": True,
                "provider": runtime_state.judge_provider if runtime_state is not None else "",
                "model": runtime_state.judge_model if runtime_state is not None else "",
                "failure_category": ",".join(dict.fromkeys(categories)),
                "affected_record_ids": tuple(dict.fromkeys(affected_ids)),
                "reason": " ".join(dict.fromkeys(reason for reason in reasons if reason)),
            }
        )

    @classmethod
    def _visible_policy_narrowing_notice(
        cls,
        prepared: IdentityRelayPreparedTurn,
        *,
        debug_mode: str,
    ) -> Mapping[str, Any]:
        affected_ids = tuple(prepared.omitted_kernel_record_ids)
        if not affected_ids:
            return MappingProxyType({})
        capture = prepared.capture
        frozen_provider = (
            dict(capture.frozen_provider)
            if capture is not None and isinstance(capture.frozen_provider, Mapping)
            else {}
        )
        exact_debug_ids = cls._exact_debug_record_ids(prepared)
        exact_allowed = debug_mode == "allow" and all(
            record_id in exact_debug_ids for record_id in affected_ids
        )
        active_count = len(prepared.authorized_kernel_record_ids)
        omitted_count = len(affected_ids)
        total_count = len(
            tuple(
                dict.fromkeys(
                    (*prepared.authorized_kernel_record_ids, *affected_ids)
                )
            )
        )
        visible = {
            "prominent": True,
            "provider": cls._safe_notice_label(
                frozen_provider.get("provider_name"), "unknown-provider"
            ),
            "model": cls._safe_notice_label(
                frozen_provider.get("model_name"), "unknown-model"
            ),
            "failure_category": "kernel_policy_narrowing",
            "affected_record_ids": (
                affected_ids if exact_allowed else ("[redacted]",)
            ),
            "kernel_active_count": active_count,
            "kernel_total_count": total_count,
            "kernel_omitted_count": omitted_count,
            "reason": (
                f"Identity Relay remains active: {active_count} of {total_count} "
                f"stable records are authorized for this provider; {omitted_count} "
                "not authorized for this provider exposure were omitted."
            ),
        }
        if not exact_allowed:
            visible["record_ids_redacted"] = True
            visible["redaction_reason"] = (
                "Affected record IDs are redacted by effective debug exposure policy."
            )
        return MappingProxyType(visible)

    @staticmethod
    def _merge_visible_notices(*notices: Mapping[str, Any]) -> Mapping[str, Any]:
        values = tuple(notice for notice in notices if notice)
        if not values:
            return MappingProxyType({})
        if len(values) == 1:
            return MappingProxyType(dict(values[0]))
        return MappingProxyType(
            {
                "prominent": any(bool(item.get("prominent", True)) for item in values),
                "provider": next(
                    (str(item.get("provider") or "") for item in values if item.get("provider")),
                    "",
                ),
                "model": next(
                    (str(item.get("model") or "") for item in values if item.get("model")),
                    "",
                ),
                "failure_category": ",".join(
                    dict.fromkeys(
                        str(item.get("failure_category") or "")
                        for item in values
                        if item.get("failure_category")
                    )
                ),
                "affected_record_ids": tuple(
                    dict.fromkeys(
                        record_id
                        for item in values
                        for record_id in tuple(item.get("affected_record_ids") or ())
                        if str(record_id)
                    )
                ),
                "reason": " ".join(
                    dict.fromkeys(
                        str(item.get("reason") or "")
                        for item in values
                        if item.get("reason")
                    )
                ),
                "redaction_reason": " ".join(
                    dict.fromkeys(
                        str(item.get("redaction_reason") or "")
                        for item in values
                        if item.get("redaction_reason")
                    )
                ),
                "kernel_active_count": next(
                    (
                        int(item.get("kernel_active_count") or 0)
                        for item in values
                        if "kernel_active_count" in item
                    ),
                    0,
                ),
                "kernel_total_count": next(
                    (
                        int(item.get("kernel_total_count") or 0)
                        for item in values
                        if "kernel_total_count" in item
                    ),
                    0,
                ),
                "kernel_omitted_count": next(
                    (
                        int(item.get("kernel_omitted_count") or 0)
                        for item in values
                        if "kernel_omitted_count" in item
                    ),
                    0,
                ),
            }
        )

    @staticmethod
    def _known_record_ids(prepared: IdentityRelayPreparedTurn) -> frozenset[str]:
        model = prepared.normalized_model
        if model is None:
            return frozenset(prepared.operation_decisions)
        return frozenset(
            (
                *(record.record_id for record in model.records),
                *(record.record_id for record in model.transient_records),
            )
        )

    @staticmethod
    def _exact_debug_record_ids(
        prepared: IdentityRelayPreparedTurn,
    ) -> frozenset[str]:
        allowed = []
        for record_id, decisions in prepared.operation_decisions.items():
            decision = (
                decisions.get("debug_trace")
                if isinstance(decisions, Mapping)
                else None
            )
            if (
                decision is not None
                and decision.allowed
                and decision.reason_code != "allowed_narrowed"
            ):
                allowed.append(str(record_id))
        return frozenset(allowed)

    @staticmethod
    def _debug_trace_mode(
        prepared: IdentityRelayPreparedTurn,
    ) -> tuple[str, str]:
        decisions = []
        for operation_map in prepared.operation_decisions.values():
            decision = (
                operation_map.get("debug_trace")
                if isinstance(operation_map, Mapping)
                else None
            )
            decisions.append(decision)
        if not decisions or any(
            decision is None or not decision.allowed for decision in decisions
        ):
            return (
                "deny",
                "Debug trace details are redacted because effective debug exposure is denied.",
            )
        if any(
            decision.reason_code == "allowed_narrowed" for decision in decisions
        ):
            return (
                "redact",
                "Debug trace details are redacted by the effective exposure policy.",
            )
        return "allow", ""

    @classmethod
    def _filter_debug_value(
        cls,
        value: Any,
        *,
        allowed_record_ids: frozenset[str],
        known_record_ids: frozenset[str],
    ) -> Any:
        def protected_record_id(item: object) -> bool:
            text = str(item or "")
            return text in known_record_ids or text.startswith(("record:", "transient:"))

        if isinstance(value, Mapping):
            filtered: dict[str, Any] = {}
            redacted_record_count = 0
            for key, item in value.items():
                if protected_record_id(key) and str(key) not in allowed_record_ids:
                    redacted_record_count += 1
                    continue
                filtered[str(key)] = cls._filter_debug_value(
                    item,
                    allowed_record_ids=allowed_record_ids,
                    known_record_ids=known_record_ids,
                )
            if redacted_record_count:
                filtered["[redacted_records]"] = redacted_record_count
            return filtered
        if isinstance(value, (list, tuple)):
            return tuple(
                (
                    "[redacted]"
                    if protected_record_id(item) and str(item) not in allowed_record_ids
                    else cls._filter_debug_value(
                        item,
                        allowed_record_ids=allowed_record_ids,
                        known_record_ids=known_record_ids,
                    )
                )
                for item in value
            )
        if protected_record_id(value) and str(value) not in allowed_record_ids:
            return "[redacted]"
        return _plain(value)

    @classmethod
    def _external_debug_payload(
        cls,
        prepared: IdentityRelayPreparedTurn,
        trace_payload: Mapping[str, Any],
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        mode, reason = cls._debug_trace_mode(prepared)
        if mode != "allow":
            return (
                mode,
                {
                    "debug_trace_mode": mode,
                    "redaction_reason": reason,
                },
                {},
            )
        allowed_ids = cls._exact_debug_record_ids(prepared)
        filtered_trace = cls._filter_debug_value(
            trace_payload,
            allowed_record_ids=allowed_ids,
            known_record_ids=cls._known_record_ids(prepared),
        )
        filtered_trace["debug_trace_mode"] = "allow"
        return (
            "allow",
            filtered_trace,
            _plain(prepared.operation_decisions),
        )

    @classmethod
    def _external_transient_state(
        cls,
        prepared: IdentityRelayPreparedTurn,
        transient_state: Mapping[str, Any],
        *,
        debug_mode: str,
    ) -> Mapping[str, Any]:
        if debug_mode != "allow":
            return MappingProxyType({})
        filtered = cls._filter_debug_value(
            transient_state,
            allowed_record_ids=cls._exact_debug_record_ids(prepared),
            known_record_ids=cls._known_record_ids(prepared),
        )
        return MappingProxyType(dict(filtered))

    @classmethod
    def _visible_notice(
        cls,
        prepared: IdentityRelayPreparedTurn,
        notice: Mapping[str, Any],
        *,
        debug_mode: str,
        preserve_failure_category: bool = False,
    ) -> Mapping[str, Any]:
        affected_ids = tuple(
            str(item)
            for item in tuple(notice.get("affected_record_ids") or ())
            if str(item)
        )
        exact_debug_ids = cls._exact_debug_record_ids(prepared)
        exact_allowed = debug_mode == "allow" and all(
            record_id in exact_debug_ids for record_id in affected_ids
        )
        if exact_allowed:
            return MappingProxyType(dict(_plain(notice)))
        return MappingProxyType(
            {
                "prominent": bool(notice.get("prominent", True)),
                "provider": "[redacted]",
                "model": "[redacted]",
                "failure_category": (
                    str(notice.get("failure_category") or "unknown_failure")
                    if preserve_failure_category
                    else "[redacted]"
                ),
                "affected_record_ids": (("[redacted]",) if affected_ids else ()),
                "reason": (
                    "Details redacted because effective debug/exposure policy does not "
                    "authorize this notice payload."
                ),
                "redaction_reason": (
                    "provider, model, record IDs, and source reason are redacted"
                    if preserve_failure_category
                    else "provider, model, category, record IDs, and source reason are redacted"
                ),
            }
        )

    @staticmethod
    def _safe_notice_label(value: Any, fallback: str) -> str:
        try:
            text = " ".join(str(value or "").split())
        except Exception:
            text = ""
        return (text[:120] or fallback)

    @staticmethod
    def _safe_failure_category(value: Any) -> str:
        try:
            text = str(value or "unknown_failure")
        except Exception:
            text = "unknown_failure"
        safe = "".join(
            character
            if character.isalnum() or character in {"_", "-", ".", ",", ":"}
            else "_"
            for character in text[:160]
        ).strip("_,")
        return safe or "unknown_failure"

    @staticmethod
    def _safe_judge_reason(failure_category: str) -> str:
        categories = frozenset(
            item for item in str(failure_category or "").split(",") if item
        )
        if categories == {"provider_exception"}:
            return (
                "Optional identity relevance judging failed at the configured "
                "provider; affected optional records were omitted."
            )
        if categories == {"payload_conversion_failed"}:
            return (
                "Judge output could not be converted safely; affected optional "
                "records were omitted."
            )
        if categories and categories.issubset(
            {
                "invalid_json",
                "invalid_output_contract",
                "invalid_record_id_list",
                "invalid_reason_or_signal_mapping",
                "selection_reason_or_signal_missing",
            }
        ):
            return "Judge output was invalid; affected optional records were omitted."
        if categories == {"unknown_record_ids"}:
            return (
                "Judge output referenced unauthorized record IDs; those references "
                "were ignored."
            )
        return (
            "Optional identity relevance judging degraded; affected optional records "
            "were omitted."
        )

    @classmethod
    def _visible_judge_notice(
        cls,
        prepared: IdentityRelayPreparedTurn,
        notice: Mapping[str, Any],
        *,
        debug_mode: str,
    ) -> Mapping[str, Any]:
        affected_ids = tuple(
            dict.fromkeys(
                str(item)
                for item in tuple(notice.get("affected_record_ids") or ())
                if str(item)
            )
        )
        exact_debug_ids = cls._exact_debug_record_ids(prepared)
        exact_allowed = debug_mode == "allow" and all(
            record_id in exact_debug_ids for record_id in affected_ids
        )
        category = cls._safe_failure_category(notice.get("failure_category"))
        visible = {
            "prominent": bool(notice.get("prominent", True)),
            "provider": cls._safe_notice_label(
                notice.get("provider"), "unknown-provider"
            ),
            "model": cls._safe_notice_label(notice.get("model"), "unknown-model"),
            "failure_category": category,
            "affected_record_ids": (
                affected_ids if exact_allowed else (("[redacted]",) if affected_ids else ())
            ),
            "reason": cls._safe_judge_reason(category),
        }
        if affected_ids and not exact_allowed:
            if debug_mode == "deny":
                reason = (
                    "Affected record IDs are redacted because effective debug "
                    "exposure is denied."
                )
            elif debug_mode == "redact":
                reason = (
                    "Affected record IDs are redacted because effective policy "
                    "permits only redacted debug exposure."
                )
            else:
                reason = (
                    "Affected record IDs are redacted because one or more IDs are "
                    "outside authorized debug exposure."
                )
            visible["record_ids_redacted"] = True
            visible["redaction_reason"] = reason
        return MappingProxyType(visible)

    @classmethod
    def _metadata_record_ids(
        cls,
        value: Any,
        *,
        known_record_ids: frozenset[str],
    ) -> tuple[str, ...]:
        found: list[str] = []

        def visit(item: Any) -> None:
            if isinstance(item, Mapping):
                for key, nested in item.items():
                    key_text = str(key)
                    if key_text in known_record_ids or key_text.startswith(
                        ("record:", "transient:")
                    ):
                        found.append(key_text)
                    visit(nested)
                return
            if isinstance(item, (list, tuple)):
                for nested in item:
                    visit(nested)
                return
            text = str(item or "")
            if text in known_record_ids or text.startswith(("record:", "transient:")):
                found.append(text)

        visit(value)
        return tuple(dict.fromkeys(found))

    @classmethod
    def externalize_snapshot(
        cls,
        prepared: IdentityRelayPreparedTurn,
        snapshot: IdentityRelaySnapshot,
        *,
        notices: Mapping[str, Mapping[str, Any]] | None = None,
        preserve_failure_category: bool = False,
        recompute_hash: bool = False,
    ) -> IdentityRelaySnapshot:
        raw_trace = _plain(snapshot.trace)
        if not isinstance(raw_trace, dict):
            raw_trace = {}
        debug_mode, trace, decisions = cls._external_debug_payload(
            prepared,
            raw_trace,
        )
        for name, notice in dict(notices or {}).items():
            trace[str(name)] = cls._visible_notice(
                prepared,
                notice,
                debug_mode=debug_mode,
                preserve_failure_category=preserve_failure_category,
            )
        exact_metadata_allowed = debug_mode == "allow"
        changed = replace(
            snapshot,
            transient_state=cls._external_transient_state(
                prepared,
                snapshot.transient_state,
                debug_mode=debug_mode,
            ),
            effective_use_decisions=decisions,
            kernel_record_ids=(
                snapshot.kernel_record_ids if exact_metadata_allowed else ()
            ),
            selected_record_ids=(
                snapshot.selected_record_ids if exact_metadata_allowed else ()
            ),
            selection_reasons=(
                snapshot.selection_reasons if exact_metadata_allowed else {}
            ),
            signals_considered=(
                snapshot.signals_considered if exact_metadata_allowed else {}
            ),
            unresolved_record_ids=(
                snapshot.unresolved_record_ids if exact_metadata_allowed else ()
            ),
            trace=trace,
            snapshot_hash=("" if recompute_hash else snapshot.snapshot_hash),
        )
        if not recompute_hash:
            return changed
        payload = {
            name: getattr(changed, name)
            for name in changed.__dataclass_fields__
        }
        return replace(
            changed,
            snapshot_hash=identity_relay_snapshot_hash(payload),
        )

    @classmethod
    def _projection_persistence(
        cls,
        prepared: IdentityRelayPreparedTurn,
        projection: ProjectionResult,
        *,
        trace_payload: Mapping[str, Any],
        effective_use_decisions: Mapping[str, Any],
        transient_state: Mapping[str, Any],
    ) -> tuple[str, Mapping[str, Any]]:
        affected_ids: list[str] = []
        reasons: list[str] = []
        rendered_ids = tuple(
            dict.fromkeys(
                (
                    *prepared.authorized_kernel_record_ids,
                    *projection.selected_record_ids,
                )
            )
        )
        if not str(projection.prompt_text or "").strip() or not rendered_ids:
            reasons.append(
                "An empty Relay projection has no persistable exact projection envelope."
            )
        known_ids = cls._known_record_ids(prepared)
        metadata_ids = cls._metadata_record_ids(
            (trace_payload, effective_use_decisions, transient_state),
            known_record_ids=known_ids,
        )
        persisted_ids = tuple(dict.fromkeys((*rendered_ids, *metadata_ids)))
        for record_id in persisted_ids:
            decision = (
                prepared.operation_decisions.get(record_id, {}).get(
                    "persistence_export"
                )
            )
            if decision is not None and decision.allowed:
                continue
            affected_ids.append(record_id)
            reasons.append(
                (
                    decision.explanation
                    if decision is not None and decision.explanation
                    else "No explicit persistence/export authorization exists."
                )
            )
        if str(prepared.persistence_mode or "").strip().casefold() == "volatile":
            reasons.append("The accepted turn requested volatile projection handling.")
        if not affected_ids and not reasons:
            return "persistent", MappingProxyType({})
        return "volatile", MappingProxyType(
            {
                "prominent": True,
                "failure_category": "persistence_prohibited",
                "affected_record_ids": tuple(dict.fromkeys(affected_ids)),
                "reason": " ".join(dict.fromkeys(reasons)),
            }
        )

    @staticmethod
    def _blocked(
        capture: IdentityRelayCapture | None,
        failure_code: str,
        *,
        query: TurnQueryEnvelope | None = None,
        model: NormalizedIdentityModel | None = None,
    ) -> IdentityRelayPreparedTurn:
        return IdentityRelayPreparedTurn(
            schema_version=2,
            projection_kind="normalized_projection",
            status="blocked",
            capture=capture,
            query=query,
            normalized_model=model,
            trace=IdentityRelayService._degradation_trace(capture, failure_code),
            failure_code=failure_code,
        )

    @staticmethod
    def _degradation_trace(
        capture: IdentityRelayCapture | None,
        failure_code: str,
        *,
        base_trace: Any = None,
    ) -> Mapping[str, Any]:
        trace = _plain(base_trace) if base_trace is not None else {}
        if not isinstance(trace, dict):
            trace = {}
        reasons = list(trace.get("degradation_reasons") or ())
        if failure_code not in reasons:
            reasons.append(failure_code)
        trace.update(
            {
                "artifact_ref": capture.artifact_ref if capture is not None else "",
                "artifact_hash": capture.artifact_hash if capture is not None else "",
                "normalizer_revision": (
                    capture.normalizer_revision if capture is not None else ""
                ),
                "subject_attestation_revision": (
                    capture.attestation_revision if capture is not None else 0
                ),
                "degradation_state": "blocked",
                "degradation_reasons": tuple(reasons),
                "failure_code": failure_code,
            }
        )
        return trace

    @classmethod
    def _failure_snapshot(
        cls,
        prepared: IdentityRelayPreparedTurn,
        failure_code: str,
        *,
        base_trace: Any = None,
    ) -> IdentityRelaySnapshot:
        capture = prepared.capture
        runtime_state = prepared.runtime_state
        model = prepared.normalized_model
        snapshot = IdentityRelaySnapshot(
            schema_version=2,
            projection_kind="normalized_projection",
            status="blocked",
            artifact_ref=capture.artifact_ref if capture is not None else "",
            artifact_hash=capture.artifact_hash if capture is not None else "",
            normalizer_revision=(capture.normalizer_revision if capture is not None else ""),
            attestation_revision=(capture.attestation_revision if capture is not None else 0),
            transient_state=(capture.transient_activation if capture is not None else {}),
            effective_use_decisions=(
                _plain(runtime_state.policy_decisions) if runtime_state is not None else {}
            ),
            kernel_record_ids=prepared.authorized_kernel_record_ids,
            prompt_text="",
            selected_record_ids=(),
            selection_reasons={},
            signals_considered={},
            unresolved_record_ids=(),
            trace=IdentityRelayService._degradation_trace(
                capture,
                failure_code,
                base_trace=base_trace,
            ),
            snapshot_hash="",
            persistence_mode="volatile",
            failure_code=failure_code,
        )
        frozen_provider = (
            dict(capture.frozen_provider)
            if capture is not None and isinstance(capture.frozen_provider, Mapping)
            else {}
        )
        known_record_ids = cls._known_record_ids(prepared)
        affected_ids = tuple(
            record_id
            for record_id in cls._metadata_record_ids(
                (_plain(base_trace), snapshot.kernel_record_ids),
                known_record_ids=known_record_ids,
            )
            if record_id in known_record_ids
        )
        notice = {
            "prominent": True,
            "provider": str(frozen_provider.get("provider_name") or ""),
            "model": str(frozen_provider.get("model_name") or ""),
            "failure_category": failure_code,
            "affected_record_ids": affected_ids,
            "reason": f"Identity Relay was blocked because {failure_code}.",
        }
        return cls.externalize_snapshot(
            prepared,
            snapshot,
            notices={"degradation_notice": notice},
            preserve_failure_category=True,
        )

    @classmethod
    def _empty_snapshot(
        cls,
        prepared: IdentityRelayPreparedTurn,
    ) -> IdentityRelaySnapshot:
        capture = prepared.capture
        status = prepared.status if prepared.status in {"suspended", "blocked"} else "blocked"
        snapshot = IdentityRelaySnapshot(
            schema_version=2,
            projection_kind="normalized_projection",
            status=status,
            artifact_ref=capture.artifact_ref if capture is not None else "",
            artifact_hash=capture.artifact_hash if capture is not None else "",
            normalizer_revision=(capture.normalizer_revision if capture is not None else ""),
            attestation_revision=(capture.attestation_revision if capture is not None else 0),
            transient_state=(capture.transient_activation if capture is not None else {}),
            effective_use_decisions={},
            kernel_record_ids=(),
            prompt_text="",
            selected_record_ids=(),
            selection_reasons={},
            signals_considered={},
            unresolved_record_ids=(),
            trace=(
                prepared.trace
                if prepared.trace
                else {
                    "artifact_ref": capture.artifact_ref if capture is not None else "",
                    "artifact_hash": capture.artifact_hash if capture is not None else "",
                    "status": status,
                    "failure_code": prepared.failure_code,
                }
            ),
            snapshot_hash="",
            persistence_mode="volatile",
            failure_code=prepared.failure_code,
        )
        notices = {}
        if status == "blocked" and prepared.failure_code:
            frozen_provider = (
                dict(capture.frozen_provider)
                if capture is not None
                and isinstance(capture.frozen_provider, Mapping)
                else {}
            )
            notices["degradation_notice"] = {
                "prominent": True,
                "provider": str(frozen_provider.get("provider_name") or ""),
                "model": str(frozen_provider.get("model_name") or ""),
                "failure_category": prepared.failure_code,
                "affected_record_ids": (),
                "reason": (
                    f"Identity Relay was blocked because {prepared.failure_code}."
                ),
            }
        return cls.externalize_snapshot(
            prepared,
            snapshot,
            notices=notices,
            preserve_failure_category=True,
        )
