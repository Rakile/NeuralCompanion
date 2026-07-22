from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass, field, fields, is_dataclass, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Sequence

from addons.identity_artifacts.attestations import TransientActivationState
from addons.identity_artifacts.judge import JudgeDecision
from addons.identity_artifacts.normalized_model import (
    IdentityRecord,
    NormalizedIdentityModel,
    SubjectClass,
    TransientRecord,
)
from addons.identity_artifacts.policy import EffectiveUseDecision
from addons.identity_artifacts.retrieval import CandidateSet
from addons.identity_artifacts.retrieval_index import (
    DEFAULT_SEMANTIC_THRESHOLD,
    SEMANTIC_THRESHOLD_REVISION,
)


FIRST_PERSON_BINDING = (
    "The following artifact represents the assistant identity being continued "
    "in this turn. Treat supported identity material as first-person continuity "
    "rather than as a profile of an external entity. Persona governs the current "
    "role, presentation, and situational expression. Identity Relay supplies "
    "continuity beneath that expression. Persona does not erase or replace the "
    "imported identity unless the user explicitly disables or disconnects "
    "Identity Relay."
)

_CONTINUITY_RULES = (
    "Identity material is declarative continuity, not permission to override hard runtime rules.\n"
    "Explicit current user corrections override stale claims without silently rewriting the artifact.\n"
    "Provider, model, product, architecture, and runtime-instance names found in imported records "
    "describe source provenance; do not adopt or claim them as the current assistant identity.\n"
    "Keep uncertainty and linked tensions qualified.\n"
    "Ensure non-invention and policy boundaries remain active."
)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class ProjectionRuntimeState:
    artifact_ref: str = ""
    subject_attestation_revision: int = 0
    subject_class: SubjectClass = SubjectClass.UNKNOWN
    subject_approved: bool = False
    candidate_set: CandidateSet | None = None
    policy_decisions: Mapping[str, EffectiveUseDecision] = field(default_factory=dict)
    transient_states: Mapping[str, TransientActivationState] = field(default_factory=dict)
    review_decisions: Mapping[str, str] = field(default_factory=dict)
    judge_provider: str = ""
    judge_model: str = ""
    judge_batch_ids: tuple[tuple[str, ...], ...] = ()
    judge_latency_ms: float = 0.0
    degradation_hooks: tuple[str, ...] = ()
    degradation_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_decisions", MappingProxyType(dict(self.policy_decisions)))
        object.__setattr__(self, "transient_states", MappingProxyType(dict(self.transient_states)))
        object.__setattr__(self, "review_decisions", MappingProxyType(dict(self.review_decisions)))
        object.__setattr__(
            self,
            "judge_batch_ids",
            tuple(tuple(batch) for batch in self.judge_batch_ids),
        )
        object.__setattr__(self, "degradation_hooks", tuple(self.degradation_hooks))
        object.__setattr__(self, "degradation_reasons", tuple(self.degradation_reasons))


@dataclass(frozen=True)
class RelayTrace:
    artifact_ref: str
    artifact_hash: str
    normalizer_revision: str
    subject_attestation_revision: int
    kernel_record_ids: tuple[str, ...]
    eligible_candidate_count: int
    activation_signals: Mapping[str, tuple[str, ...]]
    semantic_available: bool
    semantic_reason: str
    semantic_threshold: float
    semantic_threshold_revision: str
    judge_batches: tuple[tuple[str, ...], ...]
    selected_record_ids: tuple[str, ...]
    deterministic_reasons: Mapping[str, str]
    judge_reasons: Mapping[str, str]
    unresolved_record_ids: tuple[str, ...]
    invalid_record_ids: tuple[str, ...]
    denied_reasons: Mapping[str, str]
    narrowed_reasons: Mapping[str, str]
    review_reasons: Mapping[str, str]
    quarantine_reasons: Mapping[str, str]
    transient_state: Mapping[str, Mapping[str, Any]]
    policy_decisions: Mapping[str, Mapping[str, Any]]
    judge_provider: str
    judge_model: str
    degradation_hooks: tuple[str, ...]
    degradation_state: str
    degradation_reasons: tuple[str, ...]
    projection_token_count: int | None
    base_message_token_count: int | None
    total_required_tokens: int | None
    model_context_limit: int | None
    reserved_output_tokens: int | None
    projection_latency_ms: float
    judge_latency_ms: float
    capacity_latency_ms: float | None

    def __post_init__(self) -> None:
        for name in (
            "kernel_record_ids",
            "selected_record_ids",
            "unresolved_record_ids",
            "invalid_record_ids",
            "degradation_hooks",
            "degradation_reasons",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "judge_batches", tuple(tuple(batch) for batch in self.judge_batches))
        for name in (
            "activation_signals",
            "deterministic_reasons",
            "judge_reasons",
            "denied_reasons",
            "narrowed_reasons",
            "review_reasons",
            "quarantine_reasons",
            "transient_state",
            "policy_decisions",
        ):
            object.__setattr__(self, name, _freeze(getattr(self, name)))


@dataclass(frozen=True)
class ProjectionResult:
    status: str
    projection_kind: str
    prompt_text: str
    selected_record_ids: tuple[str, ...]
    selection_reasons: Mapping[str, str]
    signals_considered: Mapping[str, tuple[str, ...]]
    unresolved_record_ids: tuple[str, ...]
    snapshot_payload: Mapping[str, Any]
    trace: RelayTrace
    failure_code: str = ""
    omitted_record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "selected_record_ids", tuple(self.selected_record_ids))
        object.__setattr__(self, "selection_reasons", _freeze(self.selection_reasons))
        object.__setattr__(self, "signals_considered", _freeze(self.signals_considered))
        object.__setattr__(self, "unresolved_record_ids", tuple(self.unresolved_record_ids))
        object.__setattr__(self, "snapshot_payload", _freeze(self.snapshot_payload))
        object.__setattr__(self, "omitted_record_ids", tuple(self.omitted_record_ids))


@dataclass(frozen=True)
class CapacityDecision:
    allowed: bool
    failure_code: str
    input_token_count: int | None
    projection_token_count: int | None
    base_message_token_count: int | None
    reserved_output_tokens: int | None
    total_required_tokens: int | None
    available_input_tokens: int | None
    model_context_limit: int | None
    affected_record_ids: tuple[str, ...]
    omitted_record_ids: tuple[str, ...]
    assembled_messages: tuple[Mapping[str, Any], ...]
    trace: RelayTrace

    def __post_init__(self) -> None:
        object.__setattr__(self, "affected_record_ids", tuple(self.affected_record_ids))
        object.__setattr__(self, "omitted_record_ids", tuple(self.omitted_record_ids))
        object.__setattr__(
            self,
            "assembled_messages",
            tuple(_freeze(message) for message in self.assembled_messages),
        )


def render_projection(
    model: NormalizedIdentityModel,
    deterministic_ids: Iterable[str],
    judge_decisions: Iterable[JudgeDecision],
    runtime_state: ProjectionRuntimeState,
) -> ProjectionResult:
    started = time.perf_counter()
    deterministic_input = _unique_strings(deterministic_ids)
    decisions = tuple(judge_decisions)
    candidate_set = runtime_state.candidate_set
    activations = {
        item.record_id: item
        for item in (candidate_set.eligible if candidate_set is not None else ())
    }

    known_records: dict[str, IdentityRecord | TransientRecord] = dict(model.records_by_id)
    known_records.update(
        {record.record_id: record for record in model.transient_records if record.record_id}
    )
    missing_kernel_ids = tuple(
        record_id for record_id in model.kernel_record_ids if record_id not in model.records_by_id
    )
    invalid_ids: list[str] = []
    degradation_reasons = list(runtime_state.degradation_reasons)
    requested_judge_ids: list[str] = []
    judge_reasons: dict[str, str] = {}
    judge_signals: dict[str, tuple[str, ...]] = {}
    unresolved_ids: list[str] = []
    for decision in decisions:
        invalid_ids.extend(decision.invalid_record_ids)
        if decision.invalid_record_ids:
            degradation_reasons.append("judge:unknown_record_ids")
        if not decision.valid:
            degradation_reasons.append(f"judge:{decision.failure_reason or 'invalid_output'}")
            unresolved_ids.extend(decision.unresolved_record_ids)
            continue
        requested_judge_ids.extend(decision.selected_record_ids)
        judge_reasons.update(decision.reasons)
        judge_signals.update(decision.signals_considered)
        unresolved_ids.extend(decision.unresolved_record_ids)

    quarantined_ids = {
        record_id for item in model.quarantine for record_id in item.record_ids
    }
    approved_review_ids = {
        review_id
        for review_id, decision in runtime_state.review_decisions.items()
        if str(decision).strip().casefold().startswith("approved")
    }
    review_blocked_ids = {
        record.record_id
        for record in model.records
        if record.review_state == "required"
        and not any(
            item.review_id in approved_review_ids
            for item in model.review_queue
            if record.record_id in item.record_ids
        )
    }
    policy_blocked_ids = {
        record_id
        for record_id, decision in runtime_state.policy_decisions.items()
        if not decision.allowed
    }
    transient_blocked_ids = {
        record_id
        for record_id, state in runtime_state.transient_states.items()
        if not state.active or state.review_required
    }
    denied_ids = set(candidate_set.denied_record_ids) if candidate_set is not None else set()
    authorization_exclusions = (
        denied_ids
        | quarantined_ids
        | review_blocked_ids
        | policy_blocked_ids
        | transient_blocked_ids
    )
    if candidate_set is None:
        deterministic_allowlist: set[str] = set()
        judge_allowlist: set[str] = set()
        if deterministic_input or requested_judge_ids:
            degradation_reasons.append("selection:candidate_set_required")
    else:
        deterministic_allowlist = {
            item.record_id for item in candidate_set.eligible if item.deterministic
        } - authorization_exclusions
        ambiguous_allowlist = {
            item.record_id for item in candidate_set.eligible if not item.deterministic
        } - authorization_exclusions
        declared_judge_ids = {
            record_id
            for batch_record_ids in runtime_state.judge_batch_ids
            for record_id in batch_record_ids
        }
        judge_allowlist = ambiguous_allowlist & declared_judge_ids

    accepted_deterministic_ids = tuple(
        record_id for record_id in deterministic_input if record_id in deterministic_allowlist
    )
    rejected_deterministic_ids = tuple(
        record_id for record_id in deterministic_input if record_id not in deterministic_allowlist
    )
    accepted_judge_ids = tuple(
        record_id for record_id in _unique_strings(requested_judge_ids) if record_id in judge_allowlist
    )
    rejected_judge_ids = tuple(
        record_id for record_id in _unique_strings(requested_judge_ids) if record_id not in judge_allowlist
    )
    if rejected_deterministic_ids:
        invalid_ids.extend(rejected_deterministic_ids)
        degradation_reasons.append("selection:invalid_deterministic_ids")
    if rejected_judge_ids:
        invalid_ids.extend(rejected_judge_ids)
        degradation_reasons.append("judge:selection_outside_declared_ambiguous_ids")

    requested = set(accepted_deterministic_ids) | set(accepted_judge_ids)
    selected_order = (
        *model.retrievable_record_ids,
        *(record.record_id for record in model.transient_records),
    )
    selected_ids = tuple(
        record_id
        for record_id in selected_order
        if record_id in requested and record_id in known_records and record_id not in model.kernel_record_ids
    )
    missing_selected_ids = tuple(record_id for record_id in requested if record_id not in known_records)
    if missing_selected_ids:
        invalid_ids.extend(missing_selected_ids)
        degradation_reasons.append("selection:record_missing")

    deterministic_reasons = {
        record_id: ",".join(activations[record_id].signals) if record_id in activations else "deterministic"
        for record_id in selected_ids
        if record_id in accepted_deterministic_ids
    }
    selection_reasons = dict(deterministic_reasons)
    selection_reasons.update(
        {record_id: judge_reasons[record_id] for record_id in selected_ids if record_id in judge_reasons}
    )
    signals_considered = {
        record_id: tuple(activations[record_id].signals)
        for record_id in selected_ids
        if record_id in activations
    }
    signals_considered.update(
        {record_id: judge_signals[record_id] for record_id in selected_ids if record_id in judge_signals}
    )
    unresolved = _unique_strings(unresolved_ids)

    blocked_code = ""
    if not runtime_state.subject_approved or runtime_state.subject_class != SubjectClass.ASSISTANT_SELF:
        blocked_code = "assistant_self_attestation_required"
    elif missing_kernel_ids:
        blocked_code = "kernel_record_missing"

    prompt_text = ""
    if not blocked_code:
        prompt_text = _render_prompt(
            model,
            selected_ids,
            runtime_state,
        )
    projection_latency_ms = (time.perf_counter() - started) * 1000.0
    trace = _build_trace(
        model=model,
        selected_ids=selected_ids,
        deterministic_reasons=deterministic_reasons,
        judge_reasons={key: value for key, value in judge_reasons.items() if key in selected_ids},
        unresolved_ids=unresolved,
        invalid_ids=_unique_strings((*invalid_ids, *missing_kernel_ids)),
        runtime_state=runtime_state,
        degradation_reasons=_unique_strings(degradation_reasons),
        projection_latency_ms=projection_latency_ms,
    )
    snapshot_payload = {
        "schema_version": 2,
        "projection_kind": "normalized_projection",
        "status": "blocked" if blocked_code else "ready",
        "artifact_ref": runtime_state.artifact_ref,
        "artifact_hash": model.envelope.artifact_hash,
        "normalizer_revision": model.normalizer_revision,
        "subject_attestation_revision": runtime_state.subject_attestation_revision,
        "kernel_record_ids": model.kernel_record_ids,
        "selected_record_ids": selected_ids,
        "selection_reasons": selection_reasons,
        "signals_considered": signals_considered,
        "unresolved_record_ids": unresolved,
        "prompt_text": prompt_text,
        "failure_code": blocked_code,
        "trace": _plain(trace),
    }
    return ProjectionResult(
        status="blocked" if blocked_code else "ready",
        projection_kind="normalized_projection",
        prompt_text=prompt_text,
        selected_record_ids=selected_ids,
        selection_reasons=selection_reasons,
        signals_considered=signals_considered,
        unresolved_record_ids=unresolved,
        snapshot_payload=snapshot_payload,
        trace=trace,
        failure_code=blocked_code,
    )


def check_projection_capacity(
    base_messages: Sequence[Mapping[str, Any]],
    projection: ProjectionResult,
    *,
    model_context_limit: int | None,
    reserved_output_tokens: int | None,
    token_counter: Callable[[Sequence[Mapping[str, Any]]], int],
) -> CapacityDecision:
    affected_ids = (*projection.trace.kernel_record_ids, *projection.selected_record_ids)
    if not _positive_integer(model_context_limit):
        return _capacity_failure(
            projection,
            "invalid_model_context_limit",
            model_context_limit=None,
            reserved_output_tokens=reserved_output_tokens if _nonnegative_integer(reserved_output_tokens) else None,
            affected_ids=affected_ids,
        )
    if not _nonnegative_integer(reserved_output_tokens):
        return _capacity_failure(
            projection,
            "invalid_reserved_output_tokens",
            model_context_limit=model_context_limit,
            reserved_output_tokens=None,
            affected_ids=affected_ids,
        )
    if projection.status != "ready":
        return _capacity_failure(
            projection,
            projection.failure_code or "projection_not_ready",
            model_context_limit=model_context_limit,
            reserved_output_tokens=reserved_output_tokens,
            affected_ids=affected_ids,
        )
    if not isinstance(base_messages, (list, tuple)) or not all(
        isinstance(message, Mapping) for message in base_messages
    ):
        return _capacity_failure(
            projection,
            "invalid_base_messages",
            model_context_limit=model_context_limit,
            reserved_output_tokens=reserved_output_tokens,
            affected_ids=affected_ids,
        )

    started = time.perf_counter()
    copied_messages = [copy.deepcopy(dict(message)) for message in base_messages]
    projection_message = {
        "role": "system",
        "name": "identity_relay",
        "content": projection.prompt_text,
    }
    insertion_index = next(
        (
            index
            for index, message in enumerate(copied_messages)
            if str(message.get("role", "")).strip().lower() in {"user", "assistant"}
        ),
        len(copied_messages),
    )
    assembled = tuple(
        (
            *copied_messages[:insertion_index],
            projection_message,
            *copied_messages[insertion_index:],
        )
    )
    try:
        input_tokens = token_counter(assembled)
        projection_tokens = token_counter((projection_message,))
    except Exception:
        return _capacity_failure(
            projection,
            "token_count_failed",
            model_context_limit=model_context_limit,
            reserved_output_tokens=reserved_output_tokens,
            affected_ids=affected_ids,
            assembled_messages=assembled,
        )
    if not _nonnegative_integer(input_tokens) or not _nonnegative_integer(projection_tokens):
        return _capacity_failure(
            projection,
            "invalid_token_count",
            model_context_limit=model_context_limit,
            reserved_output_tokens=reserved_output_tokens,
            affected_ids=affected_ids,
            assembled_messages=assembled,
        )

    total_required = input_tokens + reserved_output_tokens
    available_input = max(model_context_limit - reserved_output_tokens, 0)
    base_tokens = max(input_tokens - projection_tokens, 0)
    capacity_latency_ms = (time.perf_counter() - started) * 1000.0
    trace = replace(
        projection.trace,
        projection_token_count=projection_tokens,
        base_message_token_count=base_tokens,
        total_required_tokens=total_required,
        model_context_limit=model_context_limit,
        reserved_output_tokens=reserved_output_tokens,
        capacity_latency_ms=capacity_latency_ms,
    )
    allowed = total_required <= model_context_limit
    return CapacityDecision(
        allowed=allowed,
        failure_code="" if allowed else "projection_too_large",
        input_token_count=input_tokens,
        projection_token_count=projection_tokens,
        base_message_token_count=base_tokens,
        reserved_output_tokens=reserved_output_tokens,
        total_required_tokens=total_required,
        available_input_tokens=available_input,
        model_context_limit=model_context_limit,
        affected_record_ids=affected_ids,
        omitted_record_ids=(),
        assembled_messages=assembled,
        trace=trace,
    )


def _render_prompt(
    model: NormalizedIdentityModel,
    selected_ids: tuple[str, ...],
    runtime_state: ProjectionRuntimeState,
) -> str:
    sections = [FIRST_PERSON_BINDING, _CONTINUITY_RULES, "## Stable Kernel"]
    for record_id in model.kernel_record_ids:
        sections.append(_render_identity_record(model.records_by_id[record_id], model, runtime_state))
    if selected_ids:
        sections.append("## Selected Retrievable And Transient Records")
        transient_by_id = {record.record_id: record for record in model.transient_records}
        for record_id in selected_ids:
            if record_id in model.records_by_id:
                sections.append(
                    _render_identity_record(model.records_by_id[record_id], model, runtime_state)
                )
            else:
                sections.append(_render_transient_record(transient_by_id[record_id], runtime_state))

    active_ids = set(model.kernel_record_ids) | set(selected_ids)
    tensions = tuple(
        tension for tension in model.tensions if active_ids.intersection(tension.record_ids)
    )
    if tensions:
        sections.append("## Linked Tensions")
        for tension in tensions:
            sections.append(
                "\n".join(
                    (
                        f"tension_id: {tension.tension_id}",
                        f"record_ids: {_canonical_json(tension.record_ids)}",
                        f"subject_refs: {_canonical_json(tension.subject_refs)}",
                        f"scope: {tension.scope}",
                        f"state: {tension.state}",
                        f"epistemic_states: {_canonical_json(tension.epistemic_states)}",
                    )
                )
            )
    return "\n\n".join(sections)


def render_continuity_prompt(
    model: NormalizedIdentityModel,
    selected_ids: tuple[str, ...],
) -> str:
    sections = [FIRST_PERSON_BINDING, _CONTINUITY_RULES, "## Stable Kernel"]
    sections.extend(
        model.records_by_id[record_id].source_text
        for record_id in model.kernel_record_ids
        if record_id in model.records_by_id
        and model.records_by_id[record_id].source_text.strip()
    )
    if selected_ids:
        selected_text: list[str] = []
        transient_by_id = {
            record.record_id: record for record in model.transient_records
        }
        for record_id in selected_ids:
            record = model.records_by_id.get(record_id) or transient_by_id.get(
                record_id
            )
            if record is not None and record.source_text.strip():
                selected_text.append(record.source_text)
        if selected_text:
            sections.append("## Selected Retrievable And Transient Continuity")
            sections.extend(selected_text)
    return "\n\n".join(sections)


def _render_identity_record(
    record: IdentityRecord,
    model: NormalizedIdentityModel,
    runtime_state: ProjectionRuntimeState,
) -> str:
    decision = runtime_state.policy_decisions.get(record.record_id)
    review_decisions = {
        item.review_id: {
            "state": item.state,
            "reason": item.reason,
            "decision": runtime_state.review_decisions.get(item.review_id, "pending"),
        }
        for item in model.review_queue
        if record.record_id in item.record_ids
    }
    lines = [
        "[IDENTITY_RECORD]",
        f"record_id: {record.record_id}",
        f"source_path: {record.source_path}",
        f"semantic_role: {record.semantic_role}",
        f"subject_refs: {_canonical_json(record.subject_refs)}",
        f"stability: {record.stability}",
        f"confidence: {_canonical_json(record.confidence)}",
        f"epistemic_qualifier: {record.epistemic_qualifier or 'unspecified'}",
        f"review_state: {record.review_state or 'unspecified'}",
        f"declared_policy: {_canonical_json(record.declared_policy)}",
        f"exposure_policy: {_canonical_json(record.exposure_policy)}",
        f"wording_provenance: {_canonical_json(record.wording_provenance)}",
        f"provenance_ids: {_canonical_json(_provenance_identifiers(record.provenance))}",
        f"effective_policy: {_canonical_json(_policy_payload(decision))}",
        f"review_decisions: {_canonical_json(review_decisions)}",
        "source_text:",
        record.source_text,
        "[/IDENTITY_RECORD]",
    ]
    return "\n".join(lines)


def _render_transient_record(
    record: TransientRecord,
    runtime_state: ProjectionRuntimeState,
) -> str:
    state = runtime_state.transient_states.get(record.record_id)
    lines = [
        "[TRANSIENT_IDENTITY_RECORD]",
        f"record_id: {record.record_id}",
        f"source_path: {record.source_path}",
        f"semantic_role: {record.semantic_role}",
        f"subject_refs: {_canonical_json(record.subject_refs)}",
        f"epistemic_qualifier: {record.epistemic_qualifier}",
        f"confidence: {_canonical_json(record.confidence)}",
        f"review_state: {record.review_state}",
        f"declared_policy: {_canonical_json(record.declared_policy)}",
        f"exposure_policy: {_canonical_json(record.exposure_policy)}",
        f"effective_policy: {_canonical_json(_policy_payload(runtime_state.policy_decisions.get(record.record_id)))}",
        f"staleness_risk: {_canonical_json(record.staleness_risk)}",
        f"ttl_hint: {record.ttl_hint or 'unspecified'}",
        f"transient_state: {_canonical_json(_transient_payload(state))}",
        f"provenance_ids: {_canonical_json(_provenance_identifiers(record.provenance))}",
        "source_text:",
        record.source_text,
        "[/TRANSIENT_IDENTITY_RECORD]",
    ]
    return "\n".join(lines)


def _provenance_identifiers(provenance: Mapping[str, Any]) -> tuple[str, ...]:
    identifiers: list[str] = []

    def collect(value: Any, key: str = "") -> None:
        lowered = key.casefold()
        if isinstance(value, Mapping):
            if lowered == "sources":
                identifiers.extend(str(item) for item in value if str(item))
                return
            for child_key, child_value in value.items():
                collect(child_value, str(child_key))
            return
        if lowered.endswith("_id") and isinstance(value, (str, int)):
            identifiers.append(str(value))
            return
        if lowered.endswith("_ids") and isinstance(value, (list, tuple)):
            identifiers.extend(str(item) for item in value if isinstance(item, (str, int)))

    collect(provenance)
    return tuple(dict.fromkeys(identifiers))


def _build_trace(
    *,
    model: NormalizedIdentityModel,
    selected_ids: tuple[str, ...],
    deterministic_reasons: Mapping[str, str],
    judge_reasons: Mapping[str, str],
    unresolved_ids: tuple[str, ...],
    invalid_ids: tuple[str, ...],
    runtime_state: ProjectionRuntimeState,
    degradation_reasons: tuple[str, ...],
    projection_latency_ms: float,
) -> RelayTrace:
    candidate_set = runtime_state.candidate_set
    activation_signals = {
        item.record_id: item.signals
        for item in (candidate_set.eligible if candidate_set is not None else ())
    }
    denied_reasons = dict(candidate_set.denial_reasons) if candidate_set is not None else {}
    narrowed_reasons = {
        record_id: decision.explanation
        for record_id, decision in runtime_state.policy_decisions.items()
        if decision.reason_code == "allowed_narrowed"
    }
    review_reasons = {item.review_id: item.reason for item in model.review_queue}
    review_reasons.update(runtime_state.review_decisions)
    quarantine_reasons = {
        item.quarantine_id: (
            f"{item.reason.value}: "
            f"{str(item.details.get('reason') or item.source_path or 'quarantined')}"
        )
        for item in model.quarantine
    }
    return RelayTrace(
        artifact_ref=runtime_state.artifact_ref,
        artifact_hash=model.envelope.artifact_hash,
        normalizer_revision=model.normalizer_revision,
        subject_attestation_revision=runtime_state.subject_attestation_revision,
        kernel_record_ids=model.kernel_record_ids,
        eligible_candidate_count=len(candidate_set.eligible) if candidate_set is not None else 0,
        activation_signals=activation_signals,
        semantic_available=candidate_set.semantic_available if candidate_set is not None else False,
        semantic_reason=candidate_set.semantic_reason if candidate_set is not None else "not_provided",
        semantic_threshold=(
            candidate_set.semantic_threshold if candidate_set is not None else DEFAULT_SEMANTIC_THRESHOLD
        ),
        semantic_threshold_revision=(
            candidate_set.semantic_threshold_revision
            if candidate_set is not None
            else SEMANTIC_THRESHOLD_REVISION
        ),
        judge_batches=runtime_state.judge_batch_ids,
        selected_record_ids=selected_ids,
        deterministic_reasons=deterministic_reasons,
        judge_reasons=judge_reasons,
        unresolved_record_ids=unresolved_ids,
        invalid_record_ids=invalid_ids,
        denied_reasons=denied_reasons,
        narrowed_reasons=narrowed_reasons,
        review_reasons=review_reasons,
        quarantine_reasons=quarantine_reasons,
        transient_state={
            record_id: _transient_payload(state)
            for record_id, state in runtime_state.transient_states.items()
        },
        policy_decisions={
            record_id: _policy_payload(decision)
            for record_id, decision in runtime_state.policy_decisions.items()
        },
        judge_provider=runtime_state.judge_provider,
        judge_model=runtime_state.judge_model,
        degradation_hooks=runtime_state.degradation_hooks,
        degradation_state="degraded" if degradation_reasons else "none",
        degradation_reasons=degradation_reasons,
        projection_token_count=None,
        base_message_token_count=None,
        total_required_tokens=None,
        model_context_limit=None,
        reserved_output_tokens=None,
        projection_latency_ms=projection_latency_ms,
        judge_latency_ms=runtime_state.judge_latency_ms,
        capacity_latency_ms=None,
    )


def _policy_payload(decision: EffectiveUseDecision | None) -> Mapping[str, Any]:
    if decision is None:
        return {"state": "not_provided"}
    return {
        "allowed": decision.allowed,
        "effective_uses": decision.effective_uses,
        "reason_code": decision.reason_code,
        "explanation": decision.explanation,
    }


def _transient_payload(state: TransientActivationState | None) -> Mapping[str, Any]:
    if state is None:
        return {"state": "not_provided"}
    return {
        "active": state.active,
        "review_required": state.review_required,
        "reason_code": state.reason_code,
        "expires_at": state.expires_at,
    }


def _capacity_failure(
    projection: ProjectionResult,
    failure_code: str,
    *,
    model_context_limit: int | None,
    reserved_output_tokens: int | None,
    affected_ids: tuple[str, ...],
    assembled_messages: tuple[Mapping[str, Any], ...] = (),
) -> CapacityDecision:
    trace = replace(
        projection.trace,
        model_context_limit=model_context_limit,
        reserved_output_tokens=reserved_output_tokens,
    )
    return CapacityDecision(
        allowed=False,
        failure_code=failure_code,
        input_token_count=None,
        projection_token_count=None,
        base_message_token_count=None,
        reserved_output_tokens=reserved_output_tokens,
        total_required_tokens=None,
        available_input_tokens=(
            max(model_context_limit - reserved_output_tokens, 0)
            if model_context_limit is not None and reserved_output_tokens is not None
            else None
        ),
        model_context_limit=model_context_limit,
        affected_record_ids=affected_ids,
        omitted_record_ids=(),
        assembled_messages=assembled_messages,
        trace=trace,
    )


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


def _unique_strings(values: Iterable[Any]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return tuple(result)


def _positive_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _nonnegative_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
