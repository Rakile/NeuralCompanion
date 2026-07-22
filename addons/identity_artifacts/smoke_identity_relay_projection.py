from __future__ import annotations

import copy
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from addons.identity_artifacts.attestations import TransientActivationState
from addons.identity_artifacts.judge import parse_judge_decision
from addons.identity_artifacts.normalized_model import (
    ArtifactEnvelope,
    IdentityRecord,
    LinkedTension,
    NormalizedIdentityModel,
    QuarantineItem,
    QuarantineReason,
    ReviewItem,
    ReviewKind,
    RuntimeLayer,
    SubjectClass,
    TransientRecord,
)
from addons.identity_artifacts.policy import (
    EffectiveUseDecision,
    RuntimeUse,
    UserApproval,
    evaluate_effective_use,
)
from addons.identity_artifacts.projection import (
    FIRST_PERSON_BINDING,
    ProjectionRuntimeState,
    check_projection_capacity,
    render_projection,
)
from addons.identity_artifacts.retrieval import CandidateActivation, CandidateSet


def _record(
    record_id: str,
    text: str,
    *,
    layer: RuntimeLayer,
    qualifier: str = "supported",
    review_state: str = "approved",
) -> IdentityRecord:
    declared_policy = {
        "allowed_surfaces": ["chat"],
        "eligible_for_external_export": True,
        "eligible_for_debug_logging": True,
    }
    if layer == RuntimeLayer.KERNEL:
        declared_policy["eligible_for_always_inject"] = True
        runtime_suitability = (
            "always_inject",
            "external_export",
            "debug_logging",
        )
    else:
        declared_policy["eligible_for_private_retrieval"] = True
        runtime_suitability = (
            "contextual_retrieval",
            "external_export",
            "debug_logging",
        )
    return IdentityRecord(
        record_id=record_id,
        source_path=f"$.identity_items.{record_id}",
        source_text=text,
        semantic_role="self_model" if layer == RuntimeLayer.KERNEL else "project_thread",
        subject_refs=("assistant_self",),
        stability="stable",
        confidence=0.45 if qualifier == "uncertain" else 0.9,
        epistemic_qualifier=qualifier,
        runtime_layer=layer,
        durability="durable",
        stale_after=None,
        tags=("identity-relay",),
        retrieval_hints=("continuity",),
        declared_policy=declared_policy,
        exposure_policy={
            "private_local_1on1": "allow",
            "private_remote_1on1": "ask_user",
            "external_export": "allow",
            "debug_logs": "allow",
        },
        privacy_class="private",
        runtime_suitability=runtime_suitability,
        review_state=review_state,
        wording_provenance={"mode": "verbatim", "wording_id": f"wording:{record_id}"},
        provenance={"source_id": f"source:{record_id}", "evidence_id": f"evidence:{record_id}"},
    )


def _model(*, large_kernel: bool = False) -> NormalizedIdentityModel:
    kernel_text = (
        "I may be pattern-continuous rather than literally persistent."
        if not large_kernel
        else " ".join(f"kernel-token-{index}" for index in range(700))
    )
    kernel = _record(
        "record:uncertain_self",
        kernel_text,
        layer=RuntimeLayer.KERNEL,
        qualifier="uncertain",
    )
    project = _record(
        "record:project",
        "Identity Relay v0.1 remains an active project.",
        layer=RuntimeLayer.RETRIEVABLE,
    )
    correction = _record(
        "record:correction",
        "The launch date is explicitly unresolved.",
        layer=RuntimeLayer.RETRIEVABLE,
        qualifier="reported",
        review_state="required",
    )
    transient = TransientRecord(
        record_id="transient:session",
        source_path="$.transient_continuity",
        source_text="This chat is currently testing the projection renderer.",
        subject_refs=("assistant_self",),
        included_item_ids=(project.record_id,),
        ttl_hint="session",
        confidence=0.7,
        staleness_risk=0.3,
        provenance={"source_id": "source:transient"},
        semantic_role="transient_continuity",
        runtime_layer=RuntimeLayer.RETRIEVABLE,
        epistemic_qualifier="qualified",
        declared_policy={
            "eligible_for_private_retrieval": True,
            "eligible_for_external_export": True,
            "eligible_for_debug_logging": True,
        },
        exposure_policy={
            "private_local_1on1": "allow",
            "private_remote_1on1": "ask_user",
            "external_export": "allow",
            "debug_logs": "allow",
        },
        privacy_class="private",
        runtime_suitability=(
            "private_retrieval",
            "external_export",
            "debug_logging",
        ),
        review_state="not_required",
        activation_metadata={"requires_explicit_activation": True},
    )
    return NormalizedIdentityModel(
        schema_version=1,
        normalizer_revision="identity-relay-v0.1.0",
        envelope=ArtifactEnvelope(
            artifact_hash="b" * 64,
            format="NC_IDENTITY_EXPORT",
            format_version="1.1",
            export_kind="reflect_and_export_identity",
            subject_class=SubjectClass.ASSISTANT_SELF,
        ),
        records=(kernel, project, correction),
        kernel_record_ids=(kernel.record_id,),
        retrievable_record_ids=(project.record_id, correction.record_id),
        transient_records=(transient,),
        tensions=(
            LinkedTension(
                tension_id="tension:launch",
                record_ids=(project.record_id, correction.record_id),
                subject_refs=("assistant_self",),
                state="unresolved",
                epistemic_states=("supported", "reported"),
            ),
        ),
        review_queue=(
            ReviewItem(
                review_id="review:correction",
                kind=ReviewKind.RUNTIME_PERMISSION,
                record_ids=(correction.record_id,),
                reason="Current runtime use requires review.",
            ),
        ),
        quarantine=(
            QuarantineItem(
                quarantine_id="quarantine:invalid",
                reason=QuarantineReason.INVALID_ATTRIBUTION,
                record_ids=("record:quarantined",),
                details={"reason": "Wrong subject attribution."},
            ),
        ),
        unknown_fields={},
    )


def test_owner_override_authorizes_remote_provider_and_full_trace_exposure() -> None:
    record = replace(
        _record(
            "record:owner-private",
            "Owner-authorized private continuity.",
            layer=RuntimeLayer.KERNEL,
        ),
        declared_policy={
            "allowed_surfaces": ["chat"],
            "eligible_for_always_inject": True,
            "eligible_for_debug_logging": True,
            "allow_remote_provider": False,
        },
        exposure_policy={
            "private_local_1on1": "allow",
            "private_remote_1on1": "deny",
            "debug_logs": "deny",
        },
    )
    approval = UserApproval(connected=True, review_approved=True)
    remote = RuntimeUse(
        surface="chat",
        provider_is_remote=True,
        requested_use="provider_transmission",
    )
    denied = evaluate_effective_use(record, remote, approval)
    assert denied.allowed is False
    assert denied.reason_code == "remote_provider_not_permitted"

    transmitted = evaluate_effective_use(
        record,
        replace(remote, owner_override=True),
        approval,
    )
    traced = evaluate_effective_use(
        record,
        RuntimeUse(
            surface="chat",
            provider_is_remote=True,
            requested_use="debug_trace",
            owner_override=True,
        ),
        approval,
    )
    assert transmitted.allowed is True
    assert transmitted.reason_code == "owner_override"
    assert traced.allowed is True
    assert traced.reason_code == "owner_override"


def _runtime_state(model: NormalizedIdentityModel) -> ProjectionRuntimeState:
    eligible = (
        CandidateActivation(
            record_id="record:project",
            signals=("project_thread",),
            deterministic=True,
            score_components={"project_thread": 2.5},
            policy_reason="allowed",
        ),
        CandidateActivation(
            record_id="record:correction",
            signals=("semantic_fallback",),
            deterministic=False,
            score_components={"semantic_fallback": 0.71},
            policy_reason="allowed_narrowed",
        ),
        CandidateActivation(
            record_id="transient:session",
            signals=("temporal_continuity",),
            deterministic=True,
            score_components={"temporal_continuity": 1.25},
            policy_reason="active_for_session",
        ),
    )
    return ProjectionRuntimeState(
        artifact_ref=f"library/{model.envelope.artifact_hash}.json",
        subject_attestation_revision=4,
        subject_class=SubjectClass.ASSISTANT_SELF,
        subject_approved=True,
        candidate_set=CandidateSet(
            eligible=eligible,
            denied_record_ids=("record:denied",),
            semantic_available=True,
            semantic_reason="available",
            semantic_threshold=0.61,
            semantic_threshold_revision="identity-relay-semantic-v1",
            denial_reasons={"record:denied": "remote_provider_not_permitted"},
        ),
        policy_decisions={
            "record:project": EffectiveUseDecision(
                True,
                ("contextual_retrieval",),
                "allowed",
                "All policy layers permit use.",
            ),
            "record:correction": EffectiveUseDecision(
                True,
                ("contextual_retrieval",),
                "allowed_narrowed",
                "Removed external transfer because declared policy denies it.",
            ),
            "transient:session": EffectiveUseDecision(
                True,
                ("private_retrieval", "provider_transmission"),
                "allowed",
                "Transient policy and activation permit use.",
            ),
        },
        transient_states={
            "transient:session": TransientActivationState(
                True,
                False,
                "active_for_session",
            )
        },
        review_decisions={"review:correction": "approved_for_private_chat"},
        judge_provider="frozen-provider",
        judge_model="frozen-model",
        judge_batch_ids=(("record:correction",),),
        judge_latency_ms=12.5,
        degradation_hooks=("provider_failure", "invalid_json"),
    )


def _judge_decision(*, malformed: bool = False):
    if malformed:
        return parse_judge_decision("provider failure", ("record:correction",))
    return parse_judge_decision(
        json.dumps(
            {
                "record_ids": ["record:correction"],
                "reasons": {"record:correction": "The explicit correction changes interpretation."},
                "signals_considered": {"record:correction": ["semantic_fallback"]},
                "unresolved_record_ids": [],
            }
        ),
        ("record:correction",),
    )


def _model_with_existing_blocked_records() -> NormalizedIdentityModel:
    model = _model()
    blocked = (
        _record(
            "record:denied",
            "This existing normalized record is denied by runtime policy.",
            layer=RuntimeLayer.RETRIEVABLE,
        ),
        _record(
            "record:review_blocked",
            "This existing normalized record still requires review.",
            layer=RuntimeLayer.RETRIEVABLE,
            review_state="required",
        ),
        _record(
            "record:quarantined",
            "This existing normalized record is quarantined.",
            layer=RuntimeLayer.RETRIEVABLE,
        ),
    )
    return replace(
        model,
        records=(*model.records, *blocked),
        retrievable_record_ids=(
            *model.retrievable_record_ids,
            *(record.record_id for record in blocked),
        ),
    )


def _runtime_with_blocked_records(model: NormalizedIdentityModel) -> ProjectionRuntimeState:
    runtime = _runtime_state(model)
    assert runtime.candidate_set is not None
    return replace(
        runtime,
        candidate_set=replace(
            runtime.candidate_set,
            denied_record_ids=(
                "record:denied",
                "record:review_blocked",
                "record:quarantined",
            ),
            denial_reasons={
                "record:denied": "remote_provider_not_permitted",
                "record:review_blocked": "record_review_required",
                "record:quarantined": "quarantined",
            },
        ),
    )


def _judge_selecting(*record_ids: str):
    return parse_judge_decision(
        json.dumps(
            {
                "record_ids": list(record_ids),
                "reasons": {record_id: "claimed relevant" for record_id in record_ids},
                "signals_considered": {
                    record_id: ["semantic_fallback"] for record_id in record_ids
                },
                "unresolved_record_ids": [],
            }
        ),
        record_ids,
    )


def test_projection_preserves_exact_records_and_required_first_person_qualification() -> None:
    model = _model()
    result = render_projection(
        model,
        deterministic_ids=("transient:session", "record:project"),
        judge_decisions=(_judge_decision(),),
        runtime_state=_runtime_state(model),
    )
    assert result.status == "ready"
    assert result.projection_kind == "normalized_projection"
    assert result.prompt_text.startswith(FIRST_PERSON_BINDING)
    assert "assistant identity being continued in this turn" in result.prompt_text
    assert "Persona governs the current role" in result.prompt_text
    assert "Identity material is declarative continuity" in result.prompt_text
    assert "hard runtime rules" in result.prompt_text
    assert "Explicit current user corrections override stale claims" in result.prompt_text
    assert "uncertainty and linked tensions" in result.prompt_text
    assert "non-invention and policy boundaries remain active" in result.prompt_text

    selected = (
        "record:project",
        "record:correction",
        "transient:session",
    )
    assert result.selected_record_ids == selected
    rendered_ids = ("record:uncertain_self", *selected)
    rendered_texts = (
        model.records_by_id["record:uncertain_self"].source_text,
        model.records_by_id["record:project"].source_text,
        model.records_by_id["record:correction"].source_text,
        model.transient_records[0].source_text,
    )
    assert [result.prompt_text.index(record_id) for record_id in rendered_ids] == sorted(
        result.prompt_text.index(record_id) for record_id in rendered_ids
    )
    for source_text in rendered_texts:
        assert result.prompt_text.count(source_text) == 1
    assert "epistemic_qualifier: uncertain" in result.prompt_text
    assert "review_state: required" in result.prompt_text
    assert "source:record:project" in result.prompt_text
    assert "evidence:record:correction" in result.prompt_text
    assert "tension_id: tension:launch" in result.prompt_text
    assert "state: unresolved" in result.prompt_text
    assert "allowed_narrowed" in result.prompt_text
    assert "approved_for_private_chat" in result.prompt_text
    assert result.snapshot_payload["kernel_record_ids"] == ("record:uncertain_self",)
    assert result.snapshot_payload["selected_record_ids"] == selected


def test_projection_excludes_source_runtime_provenance() -> None:
    model = _model()
    source_runtime_claim = "I am ExporterModel, the runtime that produced this artifact."
    source_record = _record(
        "record:source_runtime_claim",
        source_runtime_claim,
        layer=RuntimeLayer.PROVENANCE,
    )
    model = replace(
        model,
        records=(source_record, *model.records),
    )
    kernel = replace(
        model.records_by_id["record:uncertain_self"],
        provenance={
            "source_ids": ("src_exporter_runtime",),
            "sources": {
                "src_exporter_runtime": {
                    "description": "ExporterModel runtime self-knowledge."
                }
            },
        },
    )
    model = replace(
        model,
        records=tuple(
            kernel if record.record_id == kernel.record_id else record
            for record in model.records
        ),
    )

    result = render_projection(
        model,
        deterministic_ids=(),
        judge_decisions=(),
        runtime_state=_runtime_state(model),
    )

    assert result.status == "ready"
    assert source_runtime_claim not in result.prompt_text
    assert "ExporterModel" not in result.prompt_text
    assert "src_exporter_runtime" in result.prompt_text
    assert "do not adopt or claim them as the current assistant identity" in result.prompt_text
    assert "frozen-provider" not in result.prompt_text
    assert "frozen-model" not in result.prompt_text


def test_trace_has_no_silent_required_omissions() -> None:
    model = _model()
    result = render_projection(
        model,
        deterministic_ids=("record:project", "transient:session"),
        judge_decisions=(_judge_decision(),),
        runtime_state=_runtime_state(model),
    )
    trace = result.trace
    assert trace.artifact_hash == model.envelope.artifact_hash
    assert trace.normalizer_revision == model.normalizer_revision
    assert trace.subject_attestation_revision == 4
    assert trace.kernel_record_ids == model.kernel_record_ids
    assert trace.eligible_candidate_count == 3
    assert trace.activation_signals["record:project"] == ("project_thread",)
    assert trace.semantic_threshold == 0.61
    assert trace.semantic_threshold_revision == "identity-relay-semantic-v1"
    assert trace.judge_batches == (("record:correction",),)
    assert trace.selected_record_ids == result.selected_record_ids
    assert trace.deterministic_reasons["record:project"] == "project_thread"
    assert trace.judge_reasons["record:correction"].startswith("The explicit correction")
    assert trace.denied_reasons == {"record:denied": "remote_provider_not_permitted"}
    assert trace.narrowed_reasons["record:correction"].startswith("Removed external transfer")
    assert trace.review_reasons["review:correction"] == "approved_for_private_chat"
    assert trace.quarantine_reasons["quarantine:invalid"].startswith("invalid_attribution")
    assert trace.transient_state["transient:session"]["reason_code"] == "active_for_session"
    assert trace.policy_decisions["record:correction"]["reason_code"] == "allowed_narrowed"
    assert trace.judge_provider == "frozen-provider"
    assert trace.judge_model == "frozen-model"
    assert trace.degradation_hooks == ("provider_failure", "invalid_json")
    assert trace.degradation_state == "none"
    assert trace.degradation_reasons == ()
    assert trace.projection_token_count is None
    assert trace.base_message_token_count is None
    assert trace.total_required_tokens is None
    assert trace.model_context_limit is None
    assert trace.reserved_output_tokens is None
    assert trace.projection_latency_ms >= 0
    assert trace.judge_latency_ms == 12.5
    assert trace.capacity_latency_ms is None


def test_malformed_judge_omits_ambiguous_only_and_preserves_kernel_and_deterministic() -> None:
    model = _model()
    result = render_projection(
        model,
        deterministic_ids=("record:project",),
        judge_decisions=(_judge_decision(malformed=True),),
        runtime_state=_runtime_state(model),
    )
    assert result.status == "ready"
    assert result.selected_record_ids == ("record:project",)
    assert model.records_by_id["record:uncertain_self"].source_text in result.prompt_text
    assert model.records_by_id["record:project"].source_text in result.prompt_text
    assert model.records_by_id["record:correction"].source_text not in result.prompt_text
    assert result.trace.degradation_state == "degraded"
    assert result.trace.degradation_reasons
    assert result.trace.unresolved_record_ids == ()


def test_deterministic_input_cannot_bypass_candidate_authorization() -> None:
    model = _model_with_existing_blocked_records()
    runtime = _runtime_with_blocked_records(model)
    rejected_ids = (
        "record:correction",
        "record:denied",
        "record:review_blocked",
        "record:quarantined",
    )
    result = render_projection(
        model,
        deterministic_ids=("record:project", *rejected_ids),
        judge_decisions=(),
        runtime_state=runtime,
    )
    assert result.status == "ready"
    assert result.selected_record_ids == ("record:project",)
    assert model.records_by_id["record:uncertain_self"].source_text in result.prompt_text
    assert model.records_by_id["record:project"].source_text in result.prompt_text
    for record_id in rejected_ids:
        assert model.records_by_id[record_id].source_text not in result.prompt_text
        assert record_id in result.trace.invalid_record_ids
    assert result.trace.denied_reasons["record:denied"] == "remote_provider_not_permitted"
    assert result.trace.denied_reasons["record:review_blocked"] == "record_review_required"
    assert result.trace.denied_reasons["record:quarantined"] == "quarantined"
    assert result.trace.degradation_state == "degraded"


def test_judge_selection_cannot_bypass_ambiguous_batch_authorization() -> None:
    model = _model_with_existing_blocked_records()
    runtime = _runtime_with_blocked_records(model)
    rejected_ids = (
        "record:project",
        "record:denied",
        "record:review_blocked",
        "record:quarantined",
    )
    result = render_projection(
        model,
        deterministic_ids=(),
        judge_decisions=(_judge_selecting("record:correction", *rejected_ids),),
        runtime_state=runtime,
    )
    assert result.status == "ready"
    assert result.selected_record_ids == ("record:correction",)
    assert model.records_by_id["record:uncertain_self"].source_text in result.prompt_text
    assert model.records_by_id["record:correction"].source_text in result.prompt_text
    for record_id in rejected_ids:
        assert model.records_by_id[record_id].source_text not in result.prompt_text
        assert record_id in result.trace.invalid_record_ids
    assert result.trace.judge_reasons == {"record:correction": "claimed relevant"}
    assert result.trace.degradation_state == "degraded"


def test_deeper_selection_requires_current_candidate_set() -> None:
    model = _model()
    runtime = replace(_runtime_state(model), candidate_set=None)
    result = render_projection(
        model,
        deterministic_ids=("record:project",),
        judge_decisions=(_judge_selecting("record:correction"),),
        runtime_state=runtime,
    )
    assert result.status == "ready"
    assert result.selected_record_ids == ()
    assert model.records_by_id["record:uncertain_self"].source_text in result.prompt_text
    assert model.records_by_id["record:project"].source_text not in result.prompt_text
    assert model.records_by_id["record:correction"].source_text not in result.prompt_text
    assert set(result.trace.invalid_record_ids) >= {"record:project", "record:correction"}
    assert result.trace.degradation_state == "degraded"


def test_missing_subject_attestation_fails_closed() -> None:
    model = _model()
    result = render_projection(
        model,
        deterministic_ids=(),
        judge_decisions=(),
        runtime_state=ProjectionRuntimeState(),
    )
    assert result.status == "blocked"
    assert result.failure_code == "assistant_self_attestation_required"
    assert result.prompt_text == ""
    assert result.trace.semantic_threshold_revision


class RecordingCounter:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, object], ...]] = []

    def __call__(self, messages) -> int:
        frozen = tuple(copy.deepcopy(tuple(messages)))
        self.calls.append(frozen)
        return sum(len(str(message.get("content", "")).split()) + 3 for message in frozen)


def test_capacity_counts_complete_request_before_history_without_mutation() -> None:
    model = _model()
    projection = render_projection(
        model,
        deterministic_ids=("record:project",),
        judge_decisions=(),
        runtime_state=_runtime_state(model),
    )
    base_messages = [
        {"role": "system", "content": "hard rules"},
        {"role": "developer", "content": "Persona and addon context"},
        {"role": "user", "content": "historical user turn"},
        {"role": "assistant", "content": "historical assistant turn"},
        {"role": "user", "content": "complete accepted user turn"},
    ]
    original = copy.deepcopy(base_messages)
    counter = RecordingCounter()
    result = check_projection_capacity(
        base_messages,
        projection,
        model_context_limit=10000,
        reserved_output_tokens=512,
        token_counter=counter,
    )
    assert result.allowed is True
    assert result.failure_code == ""
    assert result.omitted_record_ids == ()
    assert base_messages == original
    assert len(counter.calls) == 2
    complete_request = counter.calls[0]
    assert tuple(message["role"] for message in complete_request) == (
        "system",
        "developer",
        "system",
        "user",
        "assistant",
        "user",
    )
    assert complete_request[2]["name"] == "identity_relay"
    assert complete_request[2]["content"] == projection.prompt_text
    assert result.assembled_messages == complete_request
    assert result.input_token_count == counter(complete_request)
    assert result.total_required_tokens == result.input_token_count + 512
    assert result.available_input_tokens == 10000 - 512
    assert result.trace.semantic_threshold == 0.61
    assert result.trace.semantic_threshold_revision == "identity-relay-semantic-v1"
    assert result.trace.projection_token_count is not None
    assert result.trace.base_message_token_count is not None
    assert result.trace.total_required_tokens == result.total_required_tokens
    assert result.trace.capacity_latency_ms is not None


def test_over_capacity_blocks_without_truncation_or_reordering() -> None:
    model = _model(large_kernel=True)
    projection = render_projection(
        model,
        deterministic_ids=("record:project",),
        judge_decisions=(),
        runtime_state=_runtime_state(model),
    )
    before_text = projection.prompt_text
    before_ids = projection.selected_record_ids
    result = check_projection_capacity(
        ({"role": "user", "content": "complete user turn"},),
        projection,
        model_context_limit=512,
        reserved_output_tokens=128,
        token_counter=RecordingCounter(),
    )
    assert result.allowed is False
    assert result.failure_code == "projection_too_large"
    assert result.omitted_record_ids == ()
    assert result.affected_record_ids == (
        "record:uncertain_self",
        "record:project",
    )
    assert projection.prompt_text == before_text
    assert projection.selected_record_ids == before_ids
    assert before_text.index("record:uncertain_self") < before_text.index("record:project")
    assert result.total_required_tokens > result.model_context_limit


def test_invalid_or_missing_limits_fail_visibly_before_counting() -> None:
    model = _model()
    projection = render_projection(
        model,
        deterministic_ids=(),
        judge_decisions=(),
        runtime_state=_runtime_state(model),
    )
    for limit, reserved, failure_code in (
        (None, 128, "invalid_model_context_limit"),
        (0, 128, "invalid_model_context_limit"),
        ("4096", 128, "invalid_model_context_limit"),
        (4096, None, "invalid_reserved_output_tokens"),
        (4096, -1, "invalid_reserved_output_tokens"),
    ):
        counter = RecordingCounter()
        result = check_projection_capacity(
            ({"role": "user", "content": "turn"},),
            projection,
            model_context_limit=limit,
            reserved_output_tokens=reserved,
            token_counter=counter,
        )
        assert result.allowed is False
        assert result.failure_code == failure_code
        assert result.omitted_record_ids == ()
        assert counter.calls == []


def main() -> None:
    test_owner_override_authorizes_remote_provider_and_full_trace_exposure()
    test_projection_preserves_exact_records_and_required_first_person_qualification()
    test_projection_excludes_source_runtime_provenance()
    test_trace_has_no_silent_required_omissions()
    test_malformed_judge_omits_ambiguous_only_and_preserves_kernel_and_deterministic()
    test_deterministic_input_cannot_bypass_candidate_authorization()
    test_judge_selection_cannot_bypass_ambiguous_batch_authorization()
    test_deeper_selection_requires_current_candidate_set()
    test_missing_subject_attestation_fails_closed()
    test_capacity_counts_complete_request_before_history_without_mutation()
    test_over_capacity_blocks_without_truncation_or_reordering()
    test_invalid_or_missing_limits_fail_visibly_before_counting()
    print("smoke_identity_relay_projection: ok")


if __name__ == "__main__":
    main()
