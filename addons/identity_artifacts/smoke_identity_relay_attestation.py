from __future__ import annotations

import tempfile
import sys
from dataclasses import replace
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from addons.identity_artifacts.attestations import (
    AttestationState,
    IdentityRelayDecisionStore,
    ReviewDecision,
    SubjectClassificationProposal,
    TransientActivation,
    apply_classification_proposal,
    empty_attestation_state,
    evaluate_transient_activation,
)
from addons.identity_artifacts.importer import import_identity_artifact
from addons.identity_artifacts.normalized_model import (
    NORMALIZER_REVISION,
    IdentityRecord,
    RuntimeLayer,
    SubjectClass,
    TransientRecord,
)
from addons.identity_artifacts.policy import RuntimeUse, UserApproval, evaluate_effective_use
from addons.identity_artifacts.storage import IdentityArtifactStore


FIXTURES_DIR = Path(__file__).with_name("fixtures")


def make_store_with_fixture(name: str) -> tuple[IdentityArtifactStore, object]:
    root = Path(tempfile.mkdtemp()) / "identity_relay"
    store = IdentityArtifactStore(root)
    raw_bytes = (FIXTURES_DIR / name).read_bytes()
    artifact = store.save_import(import_identity_artifact(raw_bytes, source_type="file"))
    return store, artifact


def make_record(
    *,
    declared_policy: dict,
    exposure_policy: dict | None = None,
    confidence: float | None = 0.9,
    runtime_suitability: tuple[str, ...] = ("always_inject",),
) -> IdentityRecord:
    return IdentityRecord(
        record_id="record:policy",
        source_path="$.identity_items[0]",
        source_text="Preserved source text.",
        semantic_role="self_model",
        subject_refs=("assistant_self",),
        stability="stable",
        confidence=confidence,
        epistemic_qualifier="uncertain" if confidence is not None and confidence < 0.5 else "supported",
        runtime_layer=RuntimeLayer.KERNEL,
        durability="durable",
        stale_after=None,
        tags=(),
        retrieval_hints=(),
        declared_policy=declared_policy,
        exposure_policy=exposure_policy or {},
        privacy_class="private",
        runtime_suitability=runtime_suitability,
        review_state="not_required",
        wording_provenance={"kind": "source_wording"},
        provenance={"source_path": "$.identity_items[0]"},
    )


def test_only_approved_assistant_self_can_bind_first_person() -> None:
    store, artifact = make_store_with_fixture("chatgpt_assistant_identity_export_v1_1.json")
    decisions = IdentityRelayDecisionStore(store.root_dir)

    assert store.resolve_artifact(artifact.artifact_ref).failure_code == "attestation_required"
    decisions.save_subject_attestation(
        artifact_hash=artifact.artifact_hash,
        normalizer_revision=NORMALIZER_REVISION,
        subject_class=SubjectClass.ASSISTANT_SELF,
        approved=True,
    )

    assert store.resolve_artifact(artifact.artifact_ref).failure_code is None


def test_approved_non_self_subject_remains_runtime_inactive() -> None:
    store, artifact = make_store_with_fixture("chatgpt_assistant_identity_export_v1_1.json")
    IdentityRelayDecisionStore(store.root_dir).save_subject_attestation(
        artifact_hash=artifact.artifact_hash,
        normalizer_revision=NORMALIZER_REVISION,
        subject_class=SubjectClass.RELATIONSHIP,
        approved=True,
    )

    assert store.resolve_artifact(artifact.artifact_ref).failure_code == "subject_not_assistant_self"


def test_revision_change_invalidates_subject_attestation_and_local_decisions() -> None:
    store, artifact = make_store_with_fixture("chatgpt_assistant_identity_export_v1_1.json")
    decisions = IdentityRelayDecisionStore(store.root_dir)
    attestation = decisions.save_subject_attestation(
        artifact_hash=artifact.artifact_hash,
        normalizer_revision=NORMALIZER_REVISION,
        subject_class=SubjectClass.ASSISTANT_SELF,
        approved=True,
    )
    state = decisions.load(artifact.artifact_hash)
    decisions.save(
        replace(
            state,
            review_decisions=(
                ReviewDecision(
                    review_id="review:runtime-layer",
                    choice="retrievable",
                    reason="Narrowed from always-inject after review.",
                ),
            ),
            transient_activations=(
                TransientActivation(record_id="transient:session", active=True, activated_at=100.0),
            ),
        )
    )

    invalidated = decisions.invalidate_for_revision(artifact.artifact_hash, "identity-relay-v0.2.0")

    assert attestation.revision == 1
    assert invalidated.normalizer_revision == "identity-relay-v0.2.0"
    assert invalidated.subject_attestation is None
    assert invalidated.review_decisions == ()
    assert invalidated.transient_activations == ()


def test_review_choices_and_narrowing_reasons_round_trip_outside_canonical() -> None:
    store, artifact = make_store_with_fixture("chatgpt_assistant_identity_export_v1_1.json")
    decisions = IdentityRelayDecisionStore(store.root_dir)
    state = AttestationState(
        artifact_hash=artifact.artifact_hash,
        normalizer_revision=NORMALIZER_REVISION,
        review_decisions=(
            ReviewDecision(
                review_id="review:policy",
                choice="keep_retrievable",
                reason="Private retrieval only; do not always inject.",
            ),
        ),
        transient_activations=(
            TransientActivation(record_id="transient:session", active=False),
        ),
    )

    decisions.save(state)
    loaded = decisions.load(artifact.artifact_hash)

    assert loaded == state
    assert artifact.canonical_path.read_bytes() == (FIXTURES_DIR / "chatgpt_assistant_identity_export_v1_1.json").read_bytes()


def test_ambiguous_subject_proposal_never_approves_itself() -> None:
    proposal = SubjectClassificationProposal(
        proposed_class=SubjectClass.MIXED,
        reason="Both assistant-self and user records are present.",
        evidence_paths=("$.identity_items[0]", "$.relationships[0]"),
        provider="lmstudio",
        model="model-a",
    )

    state = apply_classification_proposal(empty_attestation_state(), proposal)

    assert state.subject_attestation is None
    assert state.pending_proposal == proposal


def test_policy_intersection_never_broadens_remote_use() -> None:
    record = make_record(
        declared_policy={
            "allowed_surfaces": ["local_private_chat"],
            "allow_remote_provider": False,
        }
    )

    decision = evaluate_effective_use(
        record,
        runtime_use=RuntimeUse(
            surface="local_private_chat",
            provider_is_remote=True,
            requested_use="provider_transmission",
        ),
        approval=UserApproval(connected=True, transient_active=False),
    )

    assert decision.allowed is False
    assert decision.reason_code == "remote_provider_not_permitted"


def test_explicit_remote_prohibition_is_a_hard_exposure_ceiling() -> None:
    for exposure_mode in ("allow", "redact", "deny"):
        decision = evaluate_effective_use(
            make_record(
                declared_policy={"allow_remote_provider": False},
                exposure_policy={"private_remote_1on1": exposure_mode},
            ),
            runtime_use=RuntimeUse(
                surface="local_private_chat",
                provider_is_remote=True,
                requested_use="provider_transmission",
            ),
            approval=UserApproval(connected=True),
        )

        assert decision.allowed is False
        assert decision.reason_code == "remote_provider_not_permitted"
        assert "explicit" in decision.explanation.lower()
        if exposure_mode != "deny":
            assert "conflict" in decision.explanation.lower()
            assert "narrow" in decision.explanation.lower()

    for declared_policy in ({"allow_remote_provider": True}, {}):
        decision = evaluate_effective_use(
            make_record(
                declared_policy=declared_policy,
                exposure_policy={"private_remote_1on1": "allow"},
            ),
            runtime_use=RuntimeUse(
                surface="local_private_chat",
                provider_is_remote=True,
                requested_use="provider_transmission",
            ),
            approval=UserApproval(connected=True),
        )

        assert decision.allowed is True
        assert decision.reason_code == "allowed"


def test_policy_requires_an_explicit_runtime_operation() -> None:
    record = make_record(
        declared_policy={"preferred_runtime_use": "always_inject"},
    )

    decision = evaluate_effective_use(
        record,
        runtime_use=RuntimeUse(
            surface="local_private_chat",
            provider_is_remote=False,
        ),
        approval=UserApproval(connected=True),
    )

    assert decision.allowed is False
    assert decision.reason_code == "runtime_operation_required"


def test_prohibited_runtime_use_handles_null_missing_list_and_scalar() -> None:
    runtime_use = RuntimeUse(
        surface="local_private_chat",
        provider_is_remote=False,
        requested_use="always_inject",
    )
    approval = UserApproval(connected=True)

    for prohibited in ("missing", None, ()):
        policy = {"preferred_runtime_use": "always_inject"}
        if prohibited != "missing":
            policy["prohibited_runtime_use"] = prohibited
        decision = evaluate_effective_use(
            make_record(declared_policy=policy),
            runtime_use,
            approval,
        )
        assert decision.allowed is True, prohibited

    prohibited = evaluate_effective_use(
        make_record(
            declared_policy={
                "preferred_runtime_use": "always_inject",
                "prohibited_runtime_use": ["always_inject"],
            }
        ),
        runtime_use,
        approval,
    )
    assert prohibited.allowed is False
    assert prohibited.reason_code == "runtime_use_prohibited"

    malformed = evaluate_effective_use(
        make_record(
            declared_policy={
                "preferred_runtime_use": "always_inject",
                "prohibited_runtime_use": "always_inject",
            }
        ),
        runtime_use,
        approval,
    )
    assert malformed.allowed is False
    assert malformed.reason_code == "policy_review_required"


def test_runtime_operations_require_independent_declared_and_exposure_authority() -> None:
    record = make_record(
        declared_policy={
            "eligible_for_always_inject": True,
            "eligible_for_private_retrieval": False,
            "eligible_for_external_export": True,
            "eligible_for_debug_logging": True,
        },
        exposure_policy={
            "private_local_1on1": "allow",
            "private_remote_1on1": "ask_user",
            "external_export": "allow",
            "debug_logs": "redact",
        },
        runtime_suitability=(
            "always_inject",
            "private_retrieval",
            "external_export",
            "debug_logging",
        ),
    )
    approval = UserApproval(connected=True)

    stable = evaluate_effective_use(
        record,
        RuntimeUse("local_private_chat", False, requested_use="always_inject"),
        approval,
    )
    retrieval = evaluate_effective_use(
        record,
        RuntimeUse("local_private_chat", False, requested_use="private_retrieval"),
        approval,
    )
    local_transmission = evaluate_effective_use(
        record,
        RuntimeUse("local_private_chat", False, requested_use="provider_transmission"),
        approval,
    )
    remote_transmission = evaluate_effective_use(
        record,
        RuntimeUse("local_private_chat", True, requested_use="provider_transmission"),
        approval,
    )
    persistence = evaluate_effective_use(
        record,
        RuntimeUse("local_private_chat", False, requested_use="persistence_export"),
        approval,
    )
    debug_trace = evaluate_effective_use(
        record,
        RuntimeUse("local_private_chat", False, requested_use="debug_trace"),
        approval,
    )

    assert stable.allowed is True
    assert retrieval.reason_code == "runtime_use_not_permitted"
    assert local_transmission.allowed is True
    assert remote_transmission.reason_code == "operation_user_approval_required"
    assert persistence.allowed is True
    assert debug_trace.allowed is True
    assert debug_trace.reason_code == "allowed_narrowed"
    assert "redact" in debug_trace.explanation.lower()


def test_missing_exposure_authority_fails_closed_for_each_exposure_operation() -> None:
    record = make_record(
        declared_policy={
            "eligible_for_external_export": True,
            "eligible_for_debug_logging": True,
        },
        runtime_suitability=("external_export", "debug_logging"),
    )

    for requested_use in (
        "provider_transmission",
        "persistence_export",
        "debug_trace",
    ):
        decision = evaluate_effective_use(
            record,
            RuntimeUse(
                "local_private_chat",
                False,
                requested_use=requested_use,
            ),
            UserApproval(connected=True),
        )
        assert decision.allowed is False
        assert decision.reason_code == "exposure_authorization_required"


def test_policy_surface_and_user_approval_are_both_required() -> None:
    record = make_record(
        declared_policy={
            "allowed_surfaces": ["local_private_chat"],
            "allow_remote_provider": True,
            "preferred_runtime_use": "always_inject",
        }
    )

    disconnected = evaluate_effective_use(
        record,
        runtime_use=RuntimeUse(
            surface="local_private_chat",
            provider_is_remote=False,
            requested_use="always_inject",
        ),
        approval=UserApproval(connected=False),
    )
    wrong_surface = evaluate_effective_use(
        record,
        runtime_use=RuntimeUse(
            surface="shared_room",
            provider_is_remote=False,
            requested_use="always_inject",
        ),
        approval=UserApproval(connected=True),
    )

    assert disconnected.reason_code == "user_approval_required"
    assert wrong_surface.reason_code == "surface_not_permitted"


def test_uncertainty_alone_does_not_quarantine_or_deny_an_allowed_record() -> None:
    record = make_record(
        confidence=0.2,
        declared_policy={
            "allowed_surfaces": ["local_private_chat"],
            "allow_remote_provider": False,
            "preferred_runtime_use": "always_inject",
        },
    )

    decision = evaluate_effective_use(
        record,
        runtime_use=RuntimeUse(
            surface="local_private_chat",
            provider_is_remote=False,
            requested_use="always_inject",
        ),
        approval=UserApproval(connected=True),
    )

    assert decision.allowed is True
    assert decision.reason_code == "allowed"
    assert record.runtime_layer == RuntimeLayer.KERNEL


def test_declared_always_inject_cannot_bypass_retrievable_only_suitability() -> None:
    record = make_record(
        declared_policy={"preferred_runtime_use": "always_inject"},
        runtime_suitability=("private_retrieval",),
    )

    decision = evaluate_effective_use(
        record,
        runtime_use=RuntimeUse(
            surface="local_private_chat",
            provider_is_remote=False,
            requested_use="always_inject",
        ),
        approval=UserApproval(connected=True),
    )

    assert decision.allowed is False
    assert decision.effective_uses == ()
    assert decision.reason_code == "no_effective_use"


def test_empty_runtime_suitability_fails_closed() -> None:
    record = make_record(
        declared_policy={"preferred_runtime_use": "always_inject"},
        runtime_suitability=(),
    )

    decision = evaluate_effective_use(
        record,
        runtime_use=RuntimeUse(
            surface="local_private_chat",
            provider_is_remote=False,
            requested_use="always_inject",
        ),
        approval=UserApproval(connected=True),
    )

    assert decision.allowed is False
    assert decision.effective_uses == ()
    assert decision.reason_code == "no_runtime_suitable_use"


def test_allowed_policy_narrowing_names_removed_use_and_reason() -> None:
    record = make_record(
        declared_policy={
            "preferred_runtime_use": "always_inject",
            "eligible_for_private_retrieval": True,
        },
        runtime_suitability=("private_retrieval",),
    )

    decision = evaluate_effective_use(
        record,
        runtime_use=RuntimeUse(
            surface="local_private_chat",
            provider_is_remote=False,
            requested_use="private_retrieval",
        ),
        approval=UserApproval(connected=True),
    )

    assert decision.allowed is True
    assert decision.effective_uses == ("private_retrieval",)
    assert decision.reason_code == "allowed_narrowed"
    assert "always_inject" in decision.explanation
    assert "runtime suitability" in decision.explanation.lower()


def test_aggregate_policy_honors_explicit_ineligible_use() -> None:
    record = make_record(
        declared_policy={"eligible_for_always_inject": False},
        runtime_suitability=("always_inject",),
    )

    decision = evaluate_effective_use(
        record,
        runtime_use=RuntimeUse(
            surface="local_private_chat",
            provider_is_remote=False,
            requested_use="always_inject",
        ),
        approval=UserApproval(connected=True),
    )

    assert decision.allowed is False
    assert decision.effective_uses == ()
    assert decision.reason_code == "no_effective_use"
    assert "always_inject" in decision.explanation
    assert "explicit" in decision.explanation.lower()


def test_aggregate_explicit_ineligible_use_is_visible_when_other_use_remains() -> None:
    record = make_record(
        declared_policy={
            "eligible_for_always_inject": False,
            "eligible_for_private_retrieval": True,
        },
        runtime_suitability=("always_inject", "private_retrieval"),
    )

    decision = evaluate_effective_use(
        record,
        runtime_use=RuntimeUse(
            surface="local_private_chat",
            provider_is_remote=False,
            requested_use="private_retrieval",
        ),
        approval=UserApproval(connected=True),
    )

    assert decision.allowed is True
    assert decision.effective_uses == ("private_retrieval",)
    assert decision.reason_code == "allowed_narrowed"
    assert "always_inject" in decision.explanation
    assert "explicit" in decision.explanation.lower()


def test_exact_private_retrieval_permission_is_not_vetoed_by_ltm_denial() -> None:
    record = make_record(
        declared_policy={
            "preferred_runtime_use": "inject_when_relevant",
            "eligible_for_private_retrieval": True,
            "eligible_for_ltm_retrieval": False,
        },
        runtime_suitability=("private_retrieval",),
    )

    decision = evaluate_effective_use(
        record,
        runtime_use=RuntimeUse(
            surface="local_private_chat",
            provider_is_remote=False,
            requested_use="private_retrieval",
        ),
        approval=UserApproval(connected=True),
    )

    assert decision.allowed is True
    assert decision.effective_uses == ("private_retrieval",)


def test_aggregate_malformed_eligibility_values_require_policy_review() -> None:
    for malformed_value in ("false", None, 0):
        record = make_record(
            declared_policy={"eligible_for_always_inject": malformed_value},
            runtime_suitability=("always_inject",),
        )

        decision = evaluate_effective_use(
            record,
            runtime_use=RuntimeUse(surface="local_private_chat", provider_is_remote=False),
            approval=UserApproval(connected=True),
        )

        assert decision.allowed is False
        assert decision.effective_uses == ()
        assert decision.reason_code == "policy_review_required"
        assert "eligible_for_always_inject" in decision.explanation
        assert "malformed" in decision.explanation.lower()


def test_direct_use_preserves_denial_for_malformed_eligibility_values() -> None:
    for malformed_value in ("false", None, 0):
        record = make_record(
            declared_policy={"eligible_for_always_inject": malformed_value},
            runtime_suitability=("always_inject",),
        )

        decision = evaluate_effective_use(
            record,
            runtime_use=RuntimeUse(
                surface="local_private_chat",
                provider_is_remote=False,
                requested_use="always_inject",
            ),
            approval=UserApproval(connected=True),
        )

        assert decision.allowed is False
        assert decision.effective_uses == ()
        assert decision.reason_code == "runtime_use_not_permitted"


def test_transient_expiry_with_ambiguous_origin_requires_review() -> None:
    state = evaluate_transient_activation(
        transient=TransientRecord(ttl_seconds=3600, origin_timestamp=None),
        saved_activation=TransientActivation(active=True, activated_at=None),
        now=10000,
    )

    assert state.active is False
    assert state.review_required is True


def test_transient_expiry_uses_explicit_activation_origin_without_promoting_record() -> None:
    transient = TransientRecord(
        record_id="transient:session",
        ttl_seconds=60,
        origin_timestamp=None,
        confidence=0.3,
    )

    state = evaluate_transient_activation(
        transient=transient,
        saved_activation=TransientActivation(
            record_id=transient.record_id,
            active=True,
            activated_at=100.0,
        ),
        now=161.0,
    )

    assert state.active is False
    assert state.review_required is False
    assert state.reason_code == "expired"
    assert transient.confidence == 0.3


def test_session_transient_activation_persists_and_matches_session_token() -> None:
    store, artifact = make_store_with_fixture("chatgpt_assistant_identity_export_v1_1.json")
    decisions = IdentityRelayDecisionStore(store.root_dir)
    activation = TransientActivation(
        record_id="transient:session",
        active=True,
        session_token="chat-a",
    )
    decisions.save(
        AttestationState(
            artifact_hash=artifact.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            transient_activations=(activation,),
        )
    )
    loaded_activation = decisions.load(artifact.artifact_hash).transient_activations[0]

    state = evaluate_transient_activation(
        transient=TransientRecord(record_id=activation.record_id, ttl_hint="session"),
        saved_activation=loaded_activation,
        now=10000,
        current_session_token="chat-a",
    )

    assert loaded_activation.session_token == "chat-a"
    assert state.active is True
    assert state.review_required is False
    assert state.reason_code == "active_for_session"


def test_session_transient_activation_rejects_different_session_token() -> None:
    state = evaluate_transient_activation(
        transient=TransientRecord(record_id="transient:session", ttl_hint="session"),
        saved_activation=TransientActivation(
            record_id="transient:session",
            active=True,
            session_token="chat-a",
        ),
        now=10000,
        current_session_token="chat-b",
    )

    assert state.active is False
    assert state.review_required is False
    assert state.reason_code == "session_mismatch"


def test_session_transient_activation_fails_closed_without_both_tokens() -> None:
    transient = TransientRecord(record_id="transient:session", ttl_hint="session")
    for saved_token, current_token in (("", "chat-a"), ("chat-a", "")):
        state = evaluate_transient_activation(
            transient=transient,
            saved_activation=TransientActivation(
                record_id=transient.record_id,
                active=True,
                session_token=saved_token,
            ),
            now=10000,
            current_session_token=current_token,
        )

        assert state.active is False
        assert state.review_required is True
        assert state.reason_code == "session_scope_required"


def main() -> int:
    test_only_approved_assistant_self_can_bind_first_person()
    test_approved_non_self_subject_remains_runtime_inactive()
    test_revision_change_invalidates_subject_attestation_and_local_decisions()
    test_review_choices_and_narrowing_reasons_round_trip_outside_canonical()
    test_ambiguous_subject_proposal_never_approves_itself()
    test_policy_intersection_never_broadens_remote_use()
    test_explicit_remote_prohibition_is_a_hard_exposure_ceiling()
    test_policy_requires_an_explicit_runtime_operation()
    test_prohibited_runtime_use_handles_null_missing_list_and_scalar()
    test_runtime_operations_require_independent_declared_and_exposure_authority()
    test_missing_exposure_authority_fails_closed_for_each_exposure_operation()
    test_policy_surface_and_user_approval_are_both_required()
    test_uncertainty_alone_does_not_quarantine_or_deny_an_allowed_record()
    test_declared_always_inject_cannot_bypass_retrievable_only_suitability()
    test_empty_runtime_suitability_fails_closed()
    test_allowed_policy_narrowing_names_removed_use_and_reason()
    test_aggregate_policy_honors_explicit_ineligible_use()
    test_aggregate_explicit_ineligible_use_is_visible_when_other_use_remains()
    test_exact_private_retrieval_permission_is_not_vetoed_by_ltm_denial()
    test_aggregate_malformed_eligibility_values_require_policy_review()
    test_direct_use_preserves_denial_for_malformed_eligibility_values()
    test_transient_expiry_with_ambiguous_origin_requires_review()
    test_transient_expiry_uses_explicit_activation_origin_without_promoting_record()
    test_session_transient_activation_persists_and_matches_session_token()
    test_session_transient_activation_rejects_different_session_token()
    test_session_transient_activation_fails_closed_without_both_tokens()
    print("smoke_identity_relay_attestation: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
