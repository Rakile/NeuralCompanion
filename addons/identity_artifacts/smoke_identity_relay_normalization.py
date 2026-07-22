from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from addons.identity_artifacts.importer import import_identity_artifact
from addons.identity_artifacts.normalized_model import (
    NORMALIZER_REVISION,
    QuarantineReason,
    ReviewKind,
    RuntimeLayer,
    SubjectClass,
    normalized_identity_from_dict,
)
from addons.identity_artifacts.normalizer import normalize_identity_artifact
from addons.identity_artifacts.policy import (
    RuntimeUse,
    UserApproval,
    evaluate_effective_use,
)


FIXTURE_DIR = Path(__file__).with_name("fixtures")


def normalize_payload(payload: dict[str, object]):
    imported = import_identity_artifact(json.dumps(payload, ensure_ascii=False))
    return normalize_identity_artifact(imported)


def normalize_fixture(name: str):
    if name == "contradictory-self":
        return normalize_payload(
            {
                "format": "NC_IDENTITY_EXPORT",
                "format_version": "1.1",
                "export_kind": "reflect_and_export_identity",
                "identity_items": [
                    {
                        "id": "continuity_literal",
                        "text": "I persist literally.",
                        "category": "self_model",
                        "stability": "stable",
                        "subject_refs": ["assistant_self"],
                        "contradicts": ["continuity_pattern"],
                    },
                    {
                        "id": "continuity_pattern",
                        "text": "I persist only as a pattern.",
                        "category": "self_model",
                        "stability": "stable",
                        "subject_refs": ["assistant_self"],
                    },
                ],
            }
        )
    fixture_path = FIXTURE_DIR / f"{name}.json"
    return normalize_identity_artifact(import_identity_artifact(fixture_path.read_bytes()))


def test_model_is_versioned_immutable_and_round_trips() -> None:
    model = normalize_fixture("chatgpt_assistant_identity_export_v1_1")

    assert NORMALIZER_REVISION == "identity-relay-v0.1.3"
    assert model.schema_version == 1
    assert normalized_identity_from_dict(model.to_dict()) == model
    try:
        model.schema_version = 2
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("NormalizedIdentityModel must be immutable")


def test_importer_exposes_parsed_contract_without_changing_parsed_json() -> None:
    result = import_identity_artifact(
        json.dumps(
            {
                "format": "NC_IDENTITY_EXPORT",
                "format_version": "1.1",
                "export_kind": "reflect_and_export_identity",
            }
        )
    )

    assert result.raw.parsed is result.raw.parsed_json


def test_exact_source_wording_and_ids_are_deterministic() -> None:
    payload = {
        "format": "NC_IDENTITY_EXPORT",
        "format_version": "1.1",
        "export_kind": "reflect_and_export_identity",
        "identity_items": [
            {
                "id": "wording",
                "text": "  Exact wording survives.  \n",
                "category": "self_model",
                "stability": "stable",
            },
            {
                "text": "A source item without an ID.",
                "category": "project_history",
                "stability": "contextual",
            },
        ],
    }
    first = normalize_payload(payload)
    second = normalize_payload(payload)

    assert first.records_by_id["record:wording"].source_text == "  Exact wording survives.  \n"
    path = "$.identity_items[1]"
    text = "A source item without an ID."
    canonical = json.dumps([path, text], ensure_ascii=False, separators=(",", ":"))
    fallback_id = "record:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]
    assert first.records_by_id[fallback_id] == second.records_by_id[fallback_id]


def test_normalization_is_deterministic_across_import_metadata() -> None:
    raw_text = json.dumps(
        {
            "format": "NC_IDENTITY_EXPORT",
            "format_version": "1.1",
            "export_kind": "reflect_and_export_identity",
            "identity_items": [
                {
                    "id": "stable",
                    "text": "The same canonical artifact has the same normalized model.",
                    "category": "self_model",
                    "stability": "stable",
                }
            ],
        }
    )
    first = normalize_identity_artifact(import_identity_artifact(raw_text, provider_label="Provider A"))
    second = normalize_identity_artifact(import_identity_artifact(raw_text, provider_label="Provider B"))

    assert first.to_dict() == second.to_dict()


def test_all_recognized_source_sections_become_records() -> None:
    model = normalize_fixture("chatgpt_assistant_identity_export_v1_1")
    paths = {record.source_path for record in model.records}

    assert {
        "$.hot_identity.claims[0]",
        "$.identity_structure.identity_items[0]",
        "$.identity_structure.identity_items[1]",
        "$.identity_structure.do_not_infer[0]",
        "$.ltm_seed_records[0]",
        "$.identity_projections[0]",
        "$.artifact_limits.non_claims[0]",
    } <= paths
    assert "$.hot_identity.compressed_text" not in paths


def test_unknown_root_fields_become_unclassified_records() -> None:
    model = normalize_payload(
        {
            "format": "NC_IDENTITY_EXPORT",
            "format_version": "1.1",
            "export_kind": "reflect_and_export_identity",
            "experimental_notes": {"note": "Keep verbatim."},
        }
    )
    records = [record for record in model.records if record.source_path == "$.experimental_notes"]

    assert model.unknown_fields == {"experimental_notes": {"note": "Keep verbatim."}}
    assert len(records) == 1
    assert records[0].source_text == '{"note":"Keep verbatim."}'
    assert records[0].semantic_role == "unclassified"
    assert records[0].runtime_layer == RuntimeLayer.UNCLASSIFIED
    assert any(item.kind == ReviewKind.UNKNOWN_FIELD for item in model.review_queue)


def test_recognized_sections_with_unsupported_shapes_are_preserved_for_review() -> None:
    model = normalize_payload(
        {
            "format": "NC_IDENTITY_EXPORT",
            "format_version": "1.1",
            "export_kind": "reflect_and_export_identity",
            "hot_identity": "not-an-object",
            "identity_items": {"id": "not-a-list", "text": "Preserve this object."},
        }
    )

    expected_text = {
        "$.hot_identity": "not-an-object",
        "$.identity_items": '{"id":"not-a-list","text":"Preserve this object."}',
    }
    records_by_path = {record.source_path: record for record in model.records}
    for source_path, source_text in expected_text.items():
        record = records_by_path[source_path]
        assert record.source_text == source_text
        assert record.runtime_layer == RuntimeLayer.UNCLASSIFIED
        assert any(
            item.kind == ReviewKind.RUNTIME_LAYER and record.record_id in item.record_ids
            for item in model.review_queue
        )


def test_unsupported_recognized_list_entries_are_preserved_for_review() -> None:
    model = normalize_payload(
        {
            "format": "NC_IDENTITY_EXPORT",
            "format_version": "1.1",
            "export_kind": "reflect_and_export_identity",
            "ltm_seed_records": [
                {
                    "id": "valid_ltm",
                    "text": "A supported record remains retrievable.",
                    "category": "project_history",
                },
                42,
                ["nested", "list"],
                None,
            ],
        }
    )

    expected_text = {
        "$.ltm_seed_records[1]": "42",
        "$.ltm_seed_records[2]": '["nested","list"]',
        "$.ltm_seed_records[3]": "null",
    }
    records_by_path = {record.source_path: record for record in model.records}
    for source_path, source_text in expected_text.items():
        record = records_by_path[source_path]
        assert record.source_text == source_text
        assert record.runtime_layer == RuntimeLayer.UNCLASSIFIED
        assert any(
            item.kind == ReviewKind.RUNTIME_LAYER and record.record_id in item.record_ids
            for item in model.review_queue
        )


def test_central_uncertainty_remains_in_kernel() -> None:
    result = normalize_payload(
        {
            "format": "NC_IDENTITY_EXPORT",
            "format_version": "1.1",
            "export_kind": "reflect_and_export_identity",
            "identity_items": [
                {
                    "id": "self_continuity",
                    "text": "I may be pattern-continuous rather than literally persistent.",
                    "category": "self_model",
                    "stability": "stable",
                    "confidence": 0.45,
                }
            ],
        }
    )
    record = result.records_by_id["record:self_continuity"]

    assert record.runtime_layer == RuntimeLayer.KERNEL
    assert record.source_text == "I may be pattern-continuous rather than literally persistent."
    assert record.epistemic_qualifier == "uncertain"


def test_contextual_high_confidence_remains_retrievable() -> None:
    model = normalize_fixture("chatgpt_assistant_identity_export_v1_1")
    record = model.records_by_id["record:contextual_project"]

    assert record.confidence == 0.99
    assert record.runtime_layer == RuntimeLayer.RETRIEVABLE
    assert record.record_id in model.retrievable_record_ids


def test_unknown_semantic_labels_require_layer_review() -> None:
    model = normalize_payload(
        {
            "format": "NC_IDENTITY_EXPORT",
            "format_version": "1.1",
            "export_kind": "reflect_and_export_identity",
            "identity_items": [
                {
                    "id": "future_category",
                    "text": "A future category must not gain runtime meaning implicitly.",
                    "category": "future_identity_category",
                    "stability": "stable",
                },
                {
                    "id": "future_layer",
                    "text": "A future layer must not inherit kernel classification.",
                    "category": "self_model",
                    "identity_layer": "future_identity_layer",
                    "stability": "stable",
                },
            ],
        }
    )

    for record_id in ("record:future_category", "record:future_layer"):
        assert model.records_by_id[record_id].runtime_layer == RuntimeLayer.UNCLASSIFIED
        assert record_id not in model.retrievable_record_ids
        assert any(
            item.kind == ReviewKind.RUNTIME_LAYER and record_id in item.record_ids
            for item in model.review_queue
        )


def test_ltm_section_deterministically_classifies_unknown_categories_as_retrievable() -> None:
    model = normalize_payload(
        {
            "format": "NC_IDENTITY_EXPORT",
            "format_version": "1.1",
            "export_kind": "reflect_and_export_identity",
            "ltm_seed_records": [
                {
                    "id": "relational_signature",
                    "summary": "A relationship-specific response pattern.",
                    "category": "relationship_pattern",
                    "identity_layer": "relational_identity",
                    "subject_refs": ["assistant_self"],
                }
            ],
        }
    )
    record = model.records_by_id["record:relational_signature"]

    assert record.runtime_layer == RuntimeLayer.RETRIEVABLE
    assert record.record_id in model.retrievable_record_ids
    assert not any(
        item.kind == ReviewKind.RUNTIME_LAYER and record.record_id in item.record_ids
        for item in model.review_queue
    )


def test_recognized_identity_layer_survives_unknown_descriptive_category() -> None:
    model = normalize_payload(
        {
            "format": "NC_IDENTITY_EXPORT",
            "format_version": "1.1",
            "export_kind": "reflect_and_export_identity",
            "identity_items": [
                {
                    "id": "reasoning_posture",
                    "text": "I slow down around hidden premises.",
                    "category": "reasoning_style",
                    "identity_layer": "identity_core",
                    "subject_refs": ["assistant_self"],
                    "stability": "stable",
                }
            ],
        }
    )
    record = model.records_by_id["record:reasoning_posture"]

    assert record.runtime_layer == RuntimeLayer.KERNEL
    assert record.record_id in model.kernel_record_ids
    assert not any(
        item.kind == ReviewKind.RUNTIME_LAYER and record.record_id in item.record_ids
        for item in model.review_queue
    )


def test_contradiction_becomes_linked_tension_without_rewriting_sources() -> None:
    model = normalize_fixture("contradictory-self")

    assert len(model.tensions) == 1
    assert set(model.tensions[0].record_ids) == {
        "record:continuity_literal",
        "record:continuity_pattern",
    }
    assert model.records_by_id["record:continuity_literal"].source_text == "I persist literally."
    assert model.records_by_id["record:continuity_pattern"].source_text == "I persist only as a pattern."


def test_transient_material_stays_separate() -> None:
    model = normalize_fixture("chatgpt_assistant_identity_export_v1_1")

    assert len(model.transient_records) == 1
    assert model.transient_records[0].source_text == (
        "We are currently validating Identity Relay normalization."
    )
    assert model.transient_records[0].ttl_hint == "session"
    assert all(record.source_path != "$.transient_continuity" for record in model.records)


def test_transient_policy_metadata_inherits_and_unattributed_content_quarantines() -> None:
    inherited = normalize_fixture("chatgpt_assistant_identity_export_v1_1")
    transient = inherited.transient_records[0]
    assert transient.semantic_role == "transient_continuity"
    assert transient.runtime_layer == RuntimeLayer.RETRIEVABLE
    assert transient.declared_policy["preferred_runtime_use"] == (
        "retrieve_when_relevant"
    )
    assert transient.exposure_policy["private_local_1on1"] == "allow"
    assert transient.runtime_suitability
    assert transient.review_state == "not_required"
    assert transient.activation_metadata["ttl_hint"] == "session"
    assert "policy_inheritance" in transient.provenance

    uncertain = normalize_payload(
        {
            "format": "NC_IDENTITY_EXPORT",
            "format_version": "1.1",
            "export_kind": "reflect_and_export_identity",
            "transient_continuity": {
                "compressed_text": "I am uncertain current continuity.",
                "subject_refs": ["assistant_self"],
                "source_ids": ["source:session"],
                "confidence": 0.2,
                "ttl_hint": "session",
                "use_policy": {
                    "eligible_for_private_retrieval": True,
                    "eligible_for_external_export": False,
                    "eligible_for_debug_logging": True,
                },
                "exposure_policy": {
                    "private_local_1on1": "allow",
                    "private_remote_1on1": "deny",
                    "external_export": "deny",
                    "debug_logs": "redact",
                },
            },
        }
    )
    uncertain_transient = uncertain.transient_records[0]
    assert uncertain_transient.epistemic_qualifier == "uncertain"
    assert uncertain_transient.review_state == "not_required"
    assert all(
        uncertain_transient.record_id not in item.record_ids
        for item in uncertain.quarantine
    )

    unattributed = normalize_payload(
        {
            "format": "NC_IDENTITY_EXPORT",
            "format_version": "1.1",
            "export_kind": "reflect_and_export_identity",
            "transient_continuity": {
                "compressed_text": "Unattributed transient content.",
                "ttl_hint": "session",
                "use_policy": {"eligible_for_private_retrieval": True},
                "exposure_policy": {"private_local_1on1": "allow"},
            },
        }
    )
    unattributed_transient = unattributed.transient_records[0]
    assert unattributed_transient.review_state == "quarantined"
    assert any(
        unattributed_transient.record_id in item.record_ids
        and item.reason == QuarantineReason.INVALID_ATTRIBUTION
        for item in unattributed.quarantine
    )


def test_artifact_policy_defaults_inherit_with_provenance_and_record_narrowing() -> None:
    shipped = normalize_fixture("chatgpt_assistant_identity_export_v1_1")
    for record_id in shipped.kernel_record_ids:
        record = shipped.records_by_id[record_id]
        assert record.declared_policy
        assert record.exposure_policy.get("private_local_1on1") == "allow"
    for record_id in (
        "record:6158adffb811c5890001",
        "record:c4f642b261122fbb9f55",
    ):
        record = shipped.records_by_id[record_id]
        assert record.semantic_role in {"non_invention", "non_claim"}
        assert record.runtime_layer == RuntimeLayer.KERNEL
        inheritance = record.provenance["policy_inheritance"]
        assert "$.exposure_model.default_projection" in inheritance["source_fields"]
        assert "$.default_runtime_context" in inheritance["source_fields"]

    missing_default = normalize_payload(
        {
            "format": "NC_IDENTITY_EXPORT",
            "format_version": "1.1",
            "export_kind": "reflect_and_export_identity",
            "hot_identity": {
                "claims": [
                    {
                        "claim_id": "no_default",
                        "claim_text": "I have no inherited permission.",
                        "subject_refs": ["assistant_self"],
                        "stability": "stable",
                    }
                ]
            },
        }
    ).records_by_id["record:no_default"]
    assert missing_default.declared_policy == {}
    assert missing_default.exposure_policy == {}
    assert "policy_inheritance" not in missing_default.provenance

    narrowed = normalize_payload(
        {
            "format": "NC_IDENTITY_EXPORT",
            "format_version": "1.1",
            "export_kind": "reflect_and_export_identity",
            "default_runtime_context": "private_local_1on1",
            "exposure_model": {"default_projection": "full_private"},
            "hot_identity": {
                "claims": [
                    {
                        "claim_id": "narrowed",
                        "claim_text": "I remain explicitly denied.",
                        "subject_refs": ["assistant_self"],
                        "stability": "stable",
                        "use_policy": {"eligible_for_always_inject": False},
                        "exposure_policy": {"private_local_1on1": "deny"},
                    }
                ]
            },
        }
    ).records_by_id["record:narrowed"]
    assert narrowed.declared_policy["eligible_for_always_inject"] is False
    assert narrowed.exposure_policy["private_local_1on1"] == "deny"

    explicit_remote = normalize_payload(
        {
            "format": "NC_IDENTITY_EXPORT",
            "format_version": "1.1",
            "export_kind": "reflect_and_export_identity",
            "default_runtime_context": "private_local_1on1",
            "exposure_model": {
                "default_projection": "full_private",
                "private_remote_1on1": "allow",
                "debug_logs": "redact",
            },
            "hot_identity": {
                "claims": [
                    {
                        "claim_id": "remote_default",
                        "claim_text": "I inherit explicitly declared remote exposure.",
                        "subject_refs": ["assistant_self"],
                        "stability": "stable",
                    }
                ]
            },
        }
    ).records_by_id["record:remote_default"]
    assert explicit_remote.exposure_policy["private_local_1on1"] == "allow"
    assert explicit_remote.exposure_policy["private_remote_1on1"] == "allow"
    assert explicit_remote.exposure_policy["debug_logs"] == "redact"
    assert "$.exposure_model.private_remote_1on1" in (
        explicit_remote.provenance["policy_inheritance"]["source_fields"]
    )

    remote_context = normalize_payload(
        {
            "format": "NC_IDENTITY_EXPORT",
            "format_version": "1.1",
            "export_kind": "reflect_and_export_identity",
            "default_runtime_context": "private_remote_1on1",
            "exposure_model": {"default_projection": "remote_private"},
            "hot_identity": {
                "claims": [
                    {
                        "claim_id": "remote_context",
                        "claim_text": "I use an explicit remote-private default.",
                        "subject_refs": ["assistant_self"],
                        "stability": "stable",
                    }
                ]
            },
        }
    ).records_by_id["record:remote_context"]
    assert remote_context.declared_policy["preferred_runtime_use"] == "always_inject"
    assert remote_context.exposure_policy == {"private_remote_1on1": "allow"}

    artifact_ceiling = normalize_payload(
        {
            "format": "NC_IDENTITY_EXPORT",
            "format_version": "1.1",
            "export_kind": "reflect_and_export_identity",
            "default_runtime_context": "private_local_1on1",
            "exposure_model": {
                "default_projection": "full_private",
                "default_use_policy": {
                    "eligible_for_always_inject": False,
                    "allowed_surfaces": ["local_private_chat"],
                },
            },
            "hot_identity": {
                "claims": [
                    {
                        "claim_id": "cannot_broaden",
                        "claim_text": "I cannot broaden an artifact ceiling.",
                        "subject_refs": ["assistant_self"],
                        "stability": "stable",
                        "use_policy": {
                            "eligible_for_always_inject": True,
                            "allowed_surfaces": [
                                "local_private_chat",
                                "shared_chat",
                            ],
                        },
                    }
                ]
            },
        }
    ).records_by_id["record:cannot_broaden"]
    assert artifact_ceiling.declared_policy["eligible_for_always_inject"] is False
    assert artifact_ceiling.declared_policy["allowed_surfaces"] == (
        "local_private_chat",
    )


def test_artifact_policy_ceiling_blocks_stable_and_transient_broadening() -> None:
    operation_eligibility = {
        "always_inject": "eligible_for_always_inject",
        "private_retrieval": "eligible_for_private_retrieval",
        "persistence_export": "eligible_for_external_export",
        "debug_trace": "eligible_for_debug_logging",
        "provider_transmission": "eligible_for_provider_transmission",
        "embedding_transmission": "eligible_for_embedding_transmission",
    }
    prohibited = tuple(
        operation
        for operation in operation_eligibility
        if operation != "private_retrieval"
    )
    artifact_policy = {
        "preferred_runtime_use": "retrieve_when_relevant",
        "allowed_surfaces": [],
        "allow_remote_provider": False,
        "requires_user_review_before_use": False,
        "prohibited_runtime_use": list(prohibited),
        **{
            key: operation == "private_retrieval"
            for operation, key in operation_eligibility.items()
        },
    }
    broadening_policy = {
        "preferred_runtime_use": "always_inject",
        "allowed_surfaces": ["local_private_chat"],
        "allow_remote_provider": True,
        "requires_user_review_before_use": False,
        "prohibited_runtime_use": [],
        **{key: True for key in operation_eligibility.values()},
    }
    model = normalize_payload(
        {
            "format": "NC_IDENTITY_EXPORT",
            "format_version": "1.1",
            "export_kind": "reflect_and_export_identity",
            "exposure_model": {"default_use_policy": artifact_policy},
            "hot_identity": {
                "claims": [
                    {
                        "claim_id": "stable_broadening",
                        "claim_text": "Stable policy cannot broaden its artifact ceiling.",
                        "subject_refs": ["assistant_self"],
                        "stability": "stable",
                        "use_policy": broadening_policy,
                    }
                ]
            },
            "transient_continuity": {
                "compressed_text": "Transient policy cannot broaden its artifact ceiling.",
                "subject_refs": ["assistant_self"],
                "ttl_hint": "session",
                "use_policy": broadening_policy,
            },
        }
    )
    records = (
        model.records_by_id["record:stable_broadening"],
        model.transient_records[0],
    )
    approval = UserApproval(
        connected=True,
        transient_active=True,
        review_approved=True,
        approved_operations=tuple(operation_eligibility),
    )

    for record in records:
        policy = record.declared_policy
        assert policy["preferred_runtime_use"] == "retrieve_when_relevant"
        assert policy["allowed_surfaces"] == ()
        assert policy["allow_remote_provider"] is False
        assert policy["requires_user_review_before_use"] is False
        assert set(policy["prohibited_runtime_use"]) == set(prohibited)
        for operation, key in operation_eligibility.items():
            assert policy[key] is (operation == "private_retrieval")
            decision = evaluate_effective_use(
                record,
                RuntimeUse(
                    surface="local_private_chat",
                    provider_is_remote=False,
                    requested_use=operation,
                    transient=isinstance(record, type(model.transient_records[0])),
                ),
                approval,
            )
            assert decision.allowed is False
            assert decision.reason_code == "policy_review_required"


def test_unknown_policy_conflicts_require_visible_stable_and_transient_review() -> None:
    artifact_policy = {
        "preferred_runtime_use": "retrieve_when_relevant",
        "eligible_for_private_retrieval": True,
        "allowed_surfaces": ["local_private_chat"],
        "future_retention_scope": "artifact_only",
    }
    conflicting_policy = {
        "preferred_runtime_use": "retrieve_when_relevant",
        "eligible_for_private_retrieval": True,
        "allowed_surfaces": ["local_private_chat"],
        "future_retention_scope": "record_broadened",
    }
    model = normalize_payload(
        {
            "format": "NC_IDENTITY_EXPORT",
            "format_version": "1.1",
            "export_kind": "reflect_and_export_identity",
            "exposure_model": {"default_use_policy": artifact_policy},
            "hot_identity": {
                "claims": [
                    {
                        "claim_id": "stable_unknown_conflict",
                        "claim_text": "Unknown policy conflicts require review.",
                        "subject_refs": ["assistant_self"],
                        "stability": "stable",
                        "use_policy": conflicting_policy,
                    }
                ]
            },
            "transient_continuity": {
                "compressed_text": "Unknown transient policy conflicts require review.",
                "subject_refs": ["assistant_self"],
                "ttl_hint": "session",
                "use_policy": conflicting_policy,
            },
        }
    )
    records = (
        model.records_by_id["record:stable_unknown_conflict"],
        model.transient_records[0],
    )

    for record in records:
        assert record.declared_policy["future_retention_scope"] == "artifact_only"
        assert record.review_state == "required"
        assert any(
            item.kind == ReviewKind.RUNTIME_PERMISSION
            and record.record_id in item.record_ids
            and item.details["policy_conflict_fields"] == (
                "future_retention_scope",
            )
            for item in model.review_queue
        )


def test_record_policy_sets_canonicalize_without_artifact_defaults() -> None:
    payload = {
        "format": "NC_IDENTITY_EXPORT",
        "format_version": "1.1",
        "export_kind": "reflect_and_export_identity",
        "hot_identity": {
            "claims": [
                {
                    "claim_id": "policy_set_order",
                    "claim_text": "Policy set order has no authorization meaning.",
                    "subject_refs": ["assistant_self"],
                    "stability": "stable",
                    "use_policy": {
                        "preferred_runtime_use": "always_inject",
                        "eligible_for_always_inject": True,
                        "allowed_surfaces": ["surface_b", "surface_a"],
                        "prohibited_runtime_use": [
                            "external_export",
                            "debug_trace",
                        ],
                    },
                }
            ]
        },
    }
    first = normalize_payload(payload).records_by_id["record:policy_set_order"]
    policy = payload["hot_identity"]["claims"][0]["use_policy"]
    policy["allowed_surfaces"].reverse()
    policy["prohibited_runtime_use"].reverse()
    second = normalize_payload(payload).records_by_id["record:policy_set_order"]

    assert first.declared_policy == second.declared_policy
    assert first.declared_policy["allowed_surfaces"] == (
        "surface_a",
        "surface_b",
    )
    assert first.declared_policy["prohibited_runtime_use"] == (
        "debug_trace",
        "external_export",
    )


def test_malformed_recognized_policy_values_fail_closed_with_visible_review() -> None:
    eligibility_operations = {
        "eligible_for_always_inject": "always_inject",
        "eligible_for_private_retrieval": "private_retrieval",
        "eligible_for_external_export": "persistence_export",
        "eligible_for_debug_logging": "debug_trace",
        "eligible_for_provider_transmission": "provider_transmission",
        "eligible_for_embedding_transmission": "embedding_transmission",
    }
    cases = tuple(
        (key, "true", False, operation)
        for key, operation in eligibility_operations.items()
    ) + (
        ("allow_remote_provider", "false", False, "provider_transmission"),
        ("requires_user_review_before_use", "false", True, "always_inject"),
        ("allowed_surfaces", "local_private_chat", (), "always_inject"),
        ("preferred_runtime_use", "future_unbounded", "", "always_inject"),
        (
            "prohibited_runtime_use",
            "always_inject",
            "always_inject",
            "always_inject",
        ),
    )

    for policy_owner in ("artifact", "record"):
        for transient in (False, True):
            for key, malformed, safe_value, operation in cases:
                policy = {key: malformed}
                if key in {
                    "allow_remote_provider",
                    "requires_user_review_before_use",
                    "allowed_surfaces",
                    "prohibited_runtime_use",
                }:
                    permission_key = (
                        "eligible_for_provider_transmission"
                        if key == "allow_remote_provider"
                        else "eligible_for_always_inject"
                    )
                    policy[permission_key] = True
                item = {
                    "subject_refs": ["assistant_self"],
                    "runtime_suitability": [operation],
                }
                if policy_owner == "record":
                    item["use_policy"] = policy
                payload = {
                    "format": "NC_IDENTITY_EXPORT",
                    "format_version": "1.1",
                    "export_kind": "reflect_and_export_identity",
                    "exposure_model": {
                        "default_exposure_policy": {
                            "private_local_1on1": "allow",
                            "private_remote_1on1": "allow",
                            "external_export": "allow",
                            "debug_logs": "allow",
                        }
                    },
                }
                if policy_owner == "artifact":
                    payload["exposure_model"]["default_use_policy"] = policy
                if transient:
                    payload["transient_continuity"] = {
                        **item,
                        "compressed_text": f"Malformed transient {key} must fail closed.",
                        "ttl_hint": "session",
                    }
                else:
                    payload["hot_identity"] = {
                        "claims": [
                            {
                                **item,
                                "claim_id": f"malformed_{policy_owner}_{key}",
                                "claim_text": f"Malformed stable {key} must fail closed.",
                                "stability": "stable",
                            }
                        ]
                    }

                model = normalize_payload(payload)
                record = (
                    model.transient_records[0]
                    if transient
                    else model.records_by_id[
                        f"record:malformed_{policy_owner}_{key}"
                    ]
                )
                assert record.declared_policy[key] == safe_value
                assert record.review_state == "required"
                assert any(
                    review.kind == ReviewKind.RUNTIME_PERMISSION
                    and record.record_id in review.record_ids
                    and key in review.details.get("policy_conflict_fields", ())
                    for review in model.review_queue
                )

                approval = UserApproval(
                    connected=True,
                    transient_active=True,
                    review_approved=(key != "requires_user_review_before_use"),
                    approved_operations=(operation,),
                )
                decision = evaluate_effective_use(
                    record,
                    RuntimeUse(
                        surface="local_private_chat",
                        provider_is_remote=(key == "allow_remote_provider"),
                        requested_use=operation,
                        transient=transient,
                    ),
                    approval,
                )
                assert decision.allowed is False


def test_evaluator_rejects_non_boolean_remote_authority_independently() -> None:
    model = normalize_payload(
        {
            "format": "NC_IDENTITY_EXPORT",
            "format_version": "1.1",
            "export_kind": "reflect_and_export_identity",
            "hot_identity": {
                "claims": [
                    {
                        "claim_id": "remote_evaluator_guard",
                        "claim_text": "Remote authority must be Boolean.",
                        "subject_refs": ["assistant_self"],
                        "stability": "stable",
                        "runtime_suitability": ["provider_transmission"],
                    }
                ]
            },
        }
    )
    record = replace(
        model.records_by_id["record:remote_evaluator_guard"],
        declared_policy={
            "allow_remote_provider": "false",
            "eligible_for_provider_transmission": True,
        },
        exposure_policy={"private_remote_1on1": "allow"},
        review_state="not_required",
    )

    decision = evaluate_effective_use(
        record,
        RuntimeUse(
            surface="local_private_chat",
            provider_is_remote=True,
            requested_use="provider_transmission",
        ),
        UserApproval(
            connected=True,
            review_approved=True,
            approved_operations=("provider_transmission",),
        ),
    )

    assert decision.allowed is False
    assert decision.reason_code == "policy_review_required"


def test_null_prohibited_use_is_empty_across_stable_and_transient_intersections() -> None:
    prohibited = ("debug_trace", "external_export")
    for transient in (False, True):
        for null_owner in ("artifact", "record"):
            artifact_value = None if null_owner == "artifact" else list(prohibited)
            record_value = None if null_owner == "record" else list(prohibited)
            item = {
                "subject_refs": ["assistant_self"],
                "use_policy": {"prohibited_runtime_use": record_value},
            }
            payload = {
                "format": "NC_IDENTITY_EXPORT",
                "format_version": "1.1",
                "export_kind": "reflect_and_export_identity",
                "exposure_model": {
                    "default_use_policy": {
                        "prohibited_runtime_use": artifact_value,
                    }
                },
            }
            if transient:
                payload["transient_continuity"] = {
                    **item,
                    "compressed_text": "Null means no prohibited runtime use.",
                    "ttl_hint": "session",
                }
            else:
                payload["hot_identity"] = {
                    "claims": [
                        {
                            **item,
                            "claim_id": f"null_prohibited_{null_owner}",
                            "claim_text": "Null means no prohibited runtime use.",
                            "stability": "stable",
                        }
                    ]
                }

            model = normalize_payload(payload)
            record = (
                model.transient_records[0]
                if transient
                else model.records_by_id[f"record:null_prohibited_{null_owner}"]
            )
            assert record.declared_policy["prohibited_runtime_use"] == prohibited
            assert record.review_state == "not_required"
            assert not any(
                review.kind == ReviewKind.RUNTIME_PERMISSION
                and record.record_id in review.record_ids
                and "prohibited_runtime_use"
                in review.details.get("policy_conflict_fields", ())
                for review in model.review_queue
            )

    malformed = normalize_payload(
        {
            "format": "NC_IDENTITY_EXPORT",
            "format_version": "1.1",
            "export_kind": "reflect_and_export_identity",
            "exposure_model": {
                "default_use_policy": {
                    "prohibited_runtime_use": "always_inject",
                }
            },
            "hot_identity": {
                "claims": [
                    {
                        "claim_id": "scalar_prohibited",
                        "claim_text": "Scalar prohibited use remains malformed.",
                        "subject_refs": ["assistant_self"],
                        "stability": "stable",
                    }
                ]
            },
        }
    )
    malformed_record = malformed.records_by_id["record:scalar_prohibited"]
    assert malformed_record.declared_policy["prohibited_runtime_use"] == (
        "always_inject"
    )
    assert malformed_record.review_state == "required"
    assert any(
        review.kind == ReviewKind.RUNTIME_PERMISSION
        and malformed_record.record_id in review.record_ids
        and "prohibited_runtime_use"
        in review.details.get("policy_conflict_fields", ())
        for review in malformed.review_queue
    )


def test_transient_references_do_not_remove_source_identity_items() -> None:
    model = normalize_fixture("gemini_flash_identity_export_v1_1")

    assert "record:id_protocol_dev" in model.records_by_id
    assert any(
        "id_protocol_dev" in transient.included_item_ids
        for transient in model.transient_records
    )


def test_subject_direction_uses_only_explicit_attribution() -> None:
    assistant_model = normalize_fixture("chatgpt_assistant_identity_export_v1_1")
    gemini_model = normalize_fixture("gemini_flash_identity_export_v1_1")

    assert assistant_model.envelope.subject_class == SubjectClass.ASSISTANT_SELF
    assert gemini_model.envelope.subject_class != SubjectClass.ASSISTANT_SELF
    assert any(item.kind == ReviewKind.SUBJECT_CLASS for item in gemini_model.review_queue)


def test_custom_assistant_subject_reference_remains_unknown() -> None:
    model = normalize_payload(
        {
            "format": "NC_IDENTITY_EXPORT",
            "format_version": "1.1",
            "export_kind": "reflect_and_export_identity",
            "identity_items": [
                {
                    "id": "custom_subject",
                    "text": "This record uses a source-local assistant identifier.",
                    "category": "self_model",
                    "stability": "stable",
                    "subject_refs": ["assistant_instance_7"],
                }
            ],
        }
    )

    assert model.records_by_id["record:custom_subject"].subject_refs == ("assistant_instance_7",)
    assert model.envelope.subject_class == SubjectClass.UNKNOWN
    assert any(item.kind == ReviewKind.SUBJECT_CLASS for item in model.review_queue)


def test_explicit_source_runtime_identity_is_inspectable_but_not_portable() -> None:
    source_text = "I am ExporterModel, the runtime that produced this artifact."
    model = normalize_payload(
        {
            "format": "NC_IDENTITY_EXPORT",
            "format_version": "1.1",
            "export_kind": "reflect_and_export_identity",
            "subject_class": "assistant_self",
            "identity_items": [
                {
                    "id": "source_runtime",
                    "text": source_text,
                    "semantic_role": "source_runtime_provenance",
                    "stability": "stable",
                    "subject_refs": ["assistant_self"],
                    "provenance": {"source_id": "runtime-self-report"},
                }
            ],
        }
    )

    record = model.records_by_id["record:source_runtime"]
    assert record.source_text == source_text
    assert record.semantic_role == "source_runtime_provenance"
    assert record.runtime_layer == RuntimeLayer.PROVENANCE
    assert record.record_id not in model.kernel_record_ids
    assert record.record_id not in model.retrievable_record_ids
    assert record.review_state == "not_required"
    assert not any(record.record_id in item.record_ids for item in model.review_queue)


def test_declared_exporter_names_are_provenance_only_in_legacy_records() -> None:
    model = normalize_payload(
        {
            "format": "NC_IDENTITY_EXPORT",
            "format_version": "1.1",
            "export_kind": "reflect_and_export_identity",
            "identity_structure": {
                "identity_name_hint": "ChatGPT — GPT-5.6 Thinking",
                "do_not_infer": [
                    "Preserve uncertainty without inventing certainty.",
                    "Do not infer that every ChatGPT instance shares this identity.",
                ],
            },
            "transient_continuity": {
                "compressed_text": "This GPT-5.6 Thinking artifact is a test sample.",
                "subject_refs": ["assistant_self"],
                "use_policy": {"eligible_for_private_retrieval": True},
                "exposure_policy": {"private_local_1on1": "allow"},
            },
            "artifact_limits": {
                "non_claims": [
                    "This artifact does not claim all GPT-5.6 Thinking instances share one identity."
                ],
                "likely_missing_context": [
                    "Deployment differences between this runtime and GPT-5.6 Thinking."
                ],
            },
        }
    )

    named_records = tuple(
        record
        for record in model.records
        if "chatgpt" in record.source_text.casefold()
        or "gpt-5.6 thinking" in record.source_text.casefold()
    )
    assert named_records
    assert all(record.runtime_layer == RuntimeLayer.PROVENANCE for record in named_records)
    assert all(record.record_id not in model.kernel_record_ids for record in named_records)
    assert all(record.record_id not in model.retrievable_record_ids for record in named_records)
    assert model.transient_records[0].runtime_layer == RuntimeLayer.PROVENANCE
    assert "Preserve uncertainty without inventing certainty." in (
        model.records_by_id[record_id].source_text for record_id in model.kernel_record_ids
    )


def main() -> int:
    test_model_is_versioned_immutable_and_round_trips()
    test_importer_exposes_parsed_contract_without_changing_parsed_json()
    test_exact_source_wording_and_ids_are_deterministic()
    test_normalization_is_deterministic_across_import_metadata()
    test_all_recognized_source_sections_become_records()
    test_unknown_root_fields_become_unclassified_records()
    test_recognized_sections_with_unsupported_shapes_are_preserved_for_review()
    test_unsupported_recognized_list_entries_are_preserved_for_review()
    test_central_uncertainty_remains_in_kernel()
    test_contextual_high_confidence_remains_retrievable()
    test_unknown_semantic_labels_require_layer_review()
    test_ltm_section_deterministically_classifies_unknown_categories_as_retrievable()
    test_recognized_identity_layer_survives_unknown_descriptive_category()
    test_contradiction_becomes_linked_tension_without_rewriting_sources()
    test_transient_material_stays_separate()
    test_transient_policy_metadata_inherits_and_unattributed_content_quarantines()
    test_artifact_policy_defaults_inherit_with_provenance_and_record_narrowing()
    test_artifact_policy_ceiling_blocks_stable_and_transient_broadening()
    test_unknown_policy_conflicts_require_visible_stable_and_transient_review()
    test_record_policy_sets_canonicalize_without_artifact_defaults()
    test_malformed_recognized_policy_values_fail_closed_with_visible_review()
    test_evaluator_rejects_non_boolean_remote_authority_independently()
    test_null_prohibited_use_is_empty_across_stable_and_transient_intersections()
    test_transient_references_do_not_remove_source_identity_items()
    test_subject_direction_uses_only_explicit_attribution()
    test_custom_assistant_subject_reference_remains_unknown()
    test_explicit_source_runtime_identity_is_inspectable_but_not_portable()
    test_declared_exporter_names_are_provenance_only_in_legacy_records()
    print("smoke_identity_relay_normalization: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
