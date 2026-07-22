from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from addons.identity_artifacts.judge import (
    JUDGE_OUTPUT_KEYS,
    SUBJECT_CLASSIFICATION_OUTPUT_KEYS,
    build_judge_batches,
    build_subject_classification_request,
    parse_judge_decision,
    parse_subject_classification_proposal,
)
from addons.identity_artifacts.normalized_model import (
    ArtifactEnvelope,
    IdentityRecord,
    NormalizedIdentityModel,
    RuntimeLayer,
    SubjectClass,
)
from addons.identity_artifacts.retrieval import (
    CandidateActivation,
    CandidateSet,
    TurnQueryEnvelope,
)


def _record(record_id: str, text: str, *, layer: RuntimeLayer) -> IdentityRecord:
    return IdentityRecord(
        record_id=record_id,
        source_path=f"$.identity_items.{record_id}",
        source_text=text,
        semantic_role="project_thread" if layer == RuntimeLayer.RETRIEVABLE else "self_model",
        subject_refs=("assistant_self",),
        stability="stable",
        confidence=0.65,
        epistemic_qualifier="reported",
        runtime_layer=layer,
        durability="durable",
        stale_after=None,
        tags=("relay",),
        retrieval_hints=("continuity",),
        declared_policy={"allowed_surfaces": ["chat"]},
        exposure_policy={"private": True},
        privacy_class="private",
        runtime_suitability=("contextual_retrieval",),
        review_state="approved",
        wording_provenance={"mode": "verbatim"},
        provenance={"source_id": f"source:{record_id}"},
    )


def _model(retrievable_count: int = 5) -> NormalizedIdentityModel:
    kernel = _record("record:kernel", "I preserve exact continuity.", layer=RuntimeLayer.KERNEL)
    records = tuple(
        _record(
            f"record:ambiguous:{index:02d}",
            f"Exact ambiguous source {index}: " + ("identity context " * 18),
            layer=RuntimeLayer.RETRIEVABLE,
        )
        for index in range(retrievable_count)
    )
    return NormalizedIdentityModel(
        schema_version=1,
        normalizer_revision="identity-relay-v0.1.0",
        envelope=ArtifactEnvelope(
            artifact_hash="a" * 64,
            format="NC_IDENTITY_EXPORT",
            format_version="1.1",
            export_kind="reflect_and_export_identity",
            subject_class=SubjectClass.ASSISTANT_SELF,
        ),
        records=(kernel, *records),
        kernel_record_ids=(kernel.record_id,),
        retrievable_record_ids=tuple(record.record_id for record in records),
        transient_records=(),
        tensions=(),
        review_queue=(),
        quarantine=(),
        unknown_fields={},
    )


def _candidate(record_id: str, *, deterministic: bool) -> CandidateActivation:
    return CandidateActivation(
        record_id=record_id,
        signals=("project_thread", "semantic_fallback") if not deterministic else ("project_thread",),
        deterministic=deterministic,
        score_components={"project_thread": 2.5, "semantic_fallback": 0.72},
        policy_reason="allowed_narrowed",
    )


def _candidate_set(model: NormalizedIdentityModel, *, deterministic_ids: tuple[str, ...] = ()) -> CandidateSet:
    return CandidateSet(
        eligible=tuple(
            _candidate(record_id, deterministic=record_id in deterministic_ids)
            for record_id in model.retrievable_record_ids
        ),
        denied_record_ids=(),
        semantic_available=True,
        semantic_reason="available",
        semantic_threshold=0.61,
        semantic_threshold_revision="identity-relay-semantic-v1",
    )


def _query() -> TurnQueryEnvelope:
    return TurnQueryEnvelope(
        latest_user_turn="Jesper corrected the Identity Relay launch plan.",
        latest_exchange="The launch date is unresolved.",
        recent_trajectory=("Identity Relay v0.1", "projection review"),
        named_entities=("Jesper",),
        relationships=("collaborator:Jesper",),
        active_persona="Echo",
        active_projects=("Identity Relay",),
        unresolved_threads=("launch date",),
        explicit_corrections=("date corrected",),
        kernel_terms=("non-invention", "continuity"),
    )


def test_clear_deterministic_matches_bypass_judge() -> None:
    model = _model(3)
    result = build_judge_batches(
        _candidate_set(model, deterministic_ids=model.retrievable_record_ids),
        model,
        4096,
        query=_query(),
    )
    assert result == ()


def test_every_ambiguous_candidate_is_batched_deterministically_without_cap() -> None:
    model = _model(19)
    deterministic_id = model.retrievable_record_ids[3]
    candidate_set = _candidate_set(model, deterministic_ids=(deterministic_id,))
    first = build_judge_batches(candidate_set, model, 2600, query=_query())
    second = build_judge_batches(candidate_set, model, 2600, query=_query())

    expected_ids = tuple(
        item.record_id for item in candidate_set.eligible if not item.deterministic
    )
    assert tuple(record_id for batch in first for record_id in batch.candidate_ids) == expected_ids
    assert tuple(record_id for batch in second for record_id in batch.candidate_ids) == expected_ids
    assert tuple(batch.prompt_text for batch in first) == tuple(batch.prompt_text for batch in second)
    assert deterministic_id not in expected_ids
    assert len(first) > 1
    assert tuple(batch.batch_id for batch in first) == tuple(
        f"judge-batch:{index:04d}" for index in range(1, len(first) + 1)
    )

    expected_envelope = {
        "latest_user_turn": _query().latest_user_turn,
        "latest_exchange": _query().latest_exchange,
        "recent_trajectory": _query().recent_trajectory,
        "named_entities": _query().named_entities,
        "relationships": _query().relationships,
        "active_persona": _query().active_persona,
        "active_projects": _query().active_projects,
        "unresolved_threads": _query().unresolved_threads,
        "explicit_corrections": _query().explicit_corrections,
        "kernel_terms": _query().kernel_terms,
    }
    for batch in first:
        assert batch.query_envelope == expected_envelope
        assert tuple(batch.output_keys) == JUDGE_OUTPUT_KEYS
        assert "reasons MUST be a JSON object" in batch.prompt_text
        assert "do not return reasons as an array" in batch.prompt_text
        assert "signals_considered MUST be a JSON object" in batch.prompt_text
        assert "do not return signals_considered as a flat array" in batch.prompt_text
        assert "never select IDs from stable_kernel" in batch.prompt_text
        assert "Default to omission" in batch.prompt_text
        assert "directly supplies evidence needed" in batch.prompt_text
        assert "artifact_limit records" in batch.prompt_text
        assert "active_thread and project_relationship records" in batch.prompt_text
        assert "merely generally true" in batch.prompt_text
        assert set(batch.payload) == {"query_envelope", "stable_kernel", "candidates"}
        assert batch.payload["query_envelope"] == expected_envelope
        for candidate in batch.payload["candidates"]:
            record = model.records_by_id[candidate["record_id"]]
            assert candidate["source_text"] == record.source_text
            assert candidate["activation_signals"]
            assert candidate["signal_reasons"] == {
                "policy_reason": "allowed_narrowed",
                "score_components": {"project_thread": 2.5, "semantic_fallback": 0.72},
            }
            assert record.source_text in batch.prompt_text
            assert record.record_id in batch.prompt_text
        assert json.dumps(expected_envelope, sort_keys=True, separators=(",", ":")) in batch.prompt_text


def test_exact_context_capacity_consolidates_high_context_judge_batches() -> None:
    model = _model(18)
    candidate_set = _candidate_set(model)
    legacy = build_judge_batches(candidate_set, model, 2600, query=_query())
    counted_messages = []

    def exact_token_counter(messages) -> int:
        frozen = tuple(dict(message) for message in messages)
        counted_messages.append(frozen)
        return sum(len(str(message.get("content") or "")) for message in frozen) // 3

    def output_budget(candidate_count: int) -> int:
        return max(1200, 512 + (320 * int(candidate_count)))

    exact = build_judge_batches(
        candidate_set,
        model,
        2600,
        query=_query(),
        context_limit=131_072,
        token_counter=exact_token_counter,
        output_budget=output_budget,
    )

    assert len(legacy) > 1
    assert len(exact) == 1
    assert exact[0].candidate_ids == model.retrievable_record_ids
    assert exact[0].context_limit == 131_072
    assert exact[0].input_tokens is not None
    assert exact[0].output_tokens == output_budget(18)
    assert exact[0].input_tokens + exact[0].output_tokens <= exact[0].context_limit
    assert counted_messages
    assert [message["role"] for message in counted_messages[-1]] == ["system", "user"]


def test_exact_context_capacity_splits_only_when_required() -> None:
    model = _model(18)
    batches = build_judge_batches(
        _candidate_set(model),
        model,
        2600,
        query=_query(),
        context_limit=8000,
        token_counter=lambda messages: sum(
            len(str(message.get("content") or "")) for message in messages
        )
        // 3,
        output_budget=lambda count: max(1200, 512 + (320 * int(count))),
    )

    assert len(batches) == 2
    assert tuple(
        record_id for batch in batches for record_id in batch.candidate_ids
    ) == model.retrievable_record_ids
    assert all(
        batch.input_tokens is not None
        and batch.output_tokens is not None
        and batch.input_tokens + batch.output_tokens <= 8000
        for batch in batches
    )


def test_judge_parser_allowlists_ids_and_records_invalid_ids() -> None:
    decision = parse_judge_decision(
        json.dumps(
            {
                "record_ids": ["record:allowed:b", "record:invented", "record:allowed:a"],
                "reasons": {
                    "record:allowed:a": "changes interpretation",
                    "record:allowed:b": "continues the project",
                    "record:invented": "invented reason",
                },
                "signals_considered": {
                    "record:allowed:a": ["project_thread"],
                    "record:allowed:b": ["semantic_fallback"],
                    "record:invented": ["topic"],
                },
                "unresolved_record_ids": ["record:unresolved", "record:invented:two"],
            }
        ),
        allowed_record_ids=("record:allowed:a", "record:allowed:b", "record:unresolved"),
    )
    assert decision.valid is True
    assert decision.selected_record_ids == ("record:allowed:a", "record:allowed:b")
    assert decision.reasons == {
        "record:allowed:a": "changes interpretation",
        "record:allowed:b": "continues the project",
    }
    assert decision.signals_considered == {
        "record:allowed:a": ("project_thread",),
        "record:allowed:b": ("semantic_fallback",),
    }
    assert decision.unresolved_record_ids == ("record:unresolved",)
    assert decision.invalid_record_ids == ("record:invented", "record:invented:two")


def test_judge_parser_accepts_fenced_aligned_reason_and_signal_lists() -> None:
    decision = parse_judge_decision(
        """```json
{
  "record_ids": ["record:a", "record:b"],
  "reasons": ["continues the project", "preserves the correction"],
  "signals_considered": [["project_thread"], ["explicit_correction"]],
  "unresolved_record_ids": []
}
```""",
        allowed_record_ids=("record:a", "record:b"),
    )

    assert decision.valid is True
    assert decision.selected_record_ids == ("record:a", "record:b")
    assert decision.reasons == {
        "record:a": "continues the project",
        "record:b": "preserves the correction",
    }
    assert decision.signals_considered == {
        "record:a": ("project_thread",),
        "record:b": ("explicit_correction",),
    }

    single = parse_judge_decision(
        """```json
{
  "record_ids": ["record:a"],
  "reasons": ["directly continues the active project"],
  "signals_considered": ["query_intent", "contextual_relevance"],
  "unresolved_record_ids": []
}
```""",
        allowed_record_ids=("record:a",),
    )
    assert single.valid is True
    assert single.reasons == {"record:a": "directly continues the active project"}
    assert single.signals_considered == {
        "record:a": ("query_intent", "contextual_relevance"),
    }


def test_malformed_judge_output_selects_no_ambiguous_ids() -> None:
    malformed_payloads = (
        "provider failed",
        "[]",
        json.dumps({"record_ids": ["record:a"]}),
        json.dumps(
            {
                "record_ids": ["record:a"],
                "reasons": {"record:a": "relevant"},
                "signals_considered": {"record:a": ["topic"]},
                "unresolved_record_ids": [],
                "rewritten_record": "I am now more certain.",
            }
        ),
        json.dumps(
            {
                "record_ids": "record:a",
                "reasons": {},
                "signals_considered": {},
                "unresolved_record_ids": [],
            }
        ),
        json.dumps(
            {
                "record_ids": ["record:a"],
                "reasons": {"record:a": "relevant", "record:b": "not selected"},
                "signals_considered": {"record:a": ["topic"], "record:b": ["topic"]},
                "unresolved_record_ids": [],
            }
        ),
    )
    for raw_text in malformed_payloads:
        decision = parse_judge_decision(raw_text, allowed_record_ids=("record:a", "record:b"))
        assert decision.valid is False, raw_text
        assert decision.selected_record_ids == (), raw_text
        assert decision.unresolved_record_ids == (), raw_text
        assert decision.failure_reason, raw_text


def test_subject_classification_is_a_separate_pending_non_authoritative_contract() -> None:
    model = _model(2)
    request = build_subject_classification_request(model)
    assert request.output_keys == SUBJECT_CLASSIFICATION_OUTPUT_KEYS
    assert request.authoritative is False
    assert request.status == "pending"
    assert set(request.payload) == {"artifact", "records"}
    assert all("source_text" in record for record in request.payload["records"])
    assert "record_ids" not in request.output_keys

    proposal = parse_subject_classification_proposal(
        json.dumps(
            {
                "proposed_class": "assistant_self",
                "reason": "The records explicitly use assistant_self attribution.",
                "evidence_paths": ["$.identity_items.record:kernel", "$.invented"],
            }
        ),
        allowed_evidence_paths=tuple(record.source_path for record in model.records),
        provider="frozen-provider",
        model="frozen-model",
    )
    assert proposal.valid is True
    assert proposal.proposed_class == SubjectClass.ASSISTANT_SELF
    assert proposal.evidence_paths == ("$.identity_items.record:kernel",)
    assert proposal.invalid_evidence_paths == ("$.invented",)
    assert proposal.status == "pending"
    assert proposal.authoritative is False
    assert proposal.provider == "frozen-provider"
    assert proposal.model == "frozen-model"

    malformed = parse_subject_classification_proposal(
        json.dumps(
            {
                "proposed_class": "assistant_self",
                "reason": "Looks right.",
                "evidence_paths": [],
                "approved": True,
            }
        )
    )
    assert malformed.valid is False
    assert malformed.proposed_class == SubjectClass.UNKNOWN
    assert malformed.status == "pending"
    assert malformed.authoritative is False


def main() -> None:
    test_clear_deterministic_matches_bypass_judge()
    test_every_ambiguous_candidate_is_batched_deterministically_without_cap()
    test_exact_context_capacity_consolidates_high_context_judge_batches()
    test_exact_context_capacity_splits_only_when_required()
    test_judge_parser_allowlists_ids_and_records_invalid_ids()
    test_judge_parser_accepts_fenced_aligned_reason_and_signal_lists()
    test_malformed_judge_output_selects_no_ambiguous_ids()
    test_subject_classification_is_a_separate_pending_non_authoritative_contract()
    print("smoke_identity_relay_judge: ok")


if __name__ == "__main__":
    main()
