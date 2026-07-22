from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from addons.identity_artifacts.importer import IdentityImportResult
from addons.identity_artifacts.normalized_model import (
    NORMALIZED_SCHEMA_VERSION,
    NORMALIZER_REVISION,
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


_ENVELOPE_FIELDS = {
    "format",
    "format_version",
    "export_kind",
    "artifact_mode",
    "default_runtime_context",
    "subject_class",
    "subject",
    "artifact_contract",
    "source_scope",
    "source_registry",
    "coverage_assessment",
    "exposure_model",
    "import_notes",
    "artifact_limits",
    "audits",
    "mechanical_audit",
    "semantic_audit",
}
_SOURCE_SECTIONS = {
    "hot_identity",
    "transient_continuity",
    "identity_structure",
    "identity_items",
    "ltm_seed_records",
    "identity_projections",
    "claims",
    "relationships",
    "relationship_statements",
    "corrective_items",
    "corrections",
    "projects",
    "threads",
    "boundaries",
    "policies",
}
_GENERIC_SECTIONS = (
    "claims",
    "relationships",
    "relationship_statements",
    "corrective_items",
    "corrections",
    "projects",
    "threads",
    "boundaries",
    "policies",
)
_IDENTITY_STRUCTURE_SECTIONS = (
    "relationships",
    "relationship_statements",
    "corrective_items",
    "corrections",
    "projects",
    "threads",
    "boundaries",
    "policies",
)
_CENTRAL_ROLES = {
    "assistant_self",
    "boundary",
    "communication_preference",
    "enduring_value",
    "identity_core",
    "identity_principle",
    "interpretation_pattern",
    "non_invention",
    "principle",
    "reaction_pattern",
    "relationship_continuity",
    "repair_pattern",
    "self_model",
    "stable_principle",
    "value",
    "values",
}
_RETRIEVABLE_ROLES = {
    "active_thread",
    "artifact_limit",
    "claim",
    "correction",
    "location_context",
    "long_term_memory",
    "non_claim",
    "personal_context",
    "policy",
    "project_context",
    "project_history",
    "projection_policy",
    "relationship_episode",
}
_SOURCE_RUNTIME_ROLES = {
    "model_identity",
    "runtime_identity",
    "source_model_identity",
    "source_runtime_provenance",
}
_KNOWN_SEMANTIC_LABELS = (
    _CENTRAL_ROLES
    | _RETRIEVABLE_ROLES
    | _SOURCE_RUNTIME_ROLES
    | {"interaction_style"}
)
_SEMANTIC_FIELDS = ("semantic_role", "category", "identity_layer")
_UNSUPPORTED_SECTION = "__unsupported__"
_SUBJECT_REFERENCE_CLASSES = {
    SubjectClass.ASSISTANT_SELF.value: SubjectClass.ASSISTANT_SELF,
    SubjectClass.OTHER_ENTITY.value: SubjectClass.OTHER_ENTITY,
    SubjectClass.RELATIONSHIP.value: SubjectClass.RELATIONSHIP,
    SubjectClass.MIXED.value: SubjectClass.MIXED,
    SubjectClass.UNKNOWN.value: SubjectClass.UNKNOWN,
    "user": SubjectClass.OTHER_ENTITY,
}
_CONTRADICTION_FIELDS = (
    "contradicts",
    "contradicts_ids",
    "conflicting_record_ids",
    "tension_with",
    "tension_with_ids",
)
_ARTIFACT_PRIVATE_PROJECTIONS = {"full_private", "remote_private"}
_ARTIFACT_RUNTIME_CONTEXTS = {
    "private_local_1on1",
    "private_remote_1on1",
}
_ARTIFACT_EXPOSURE_KEYS = (
    "debug_logs",
    "external_export",
    "private_local_1on1",
    "private_remote_1on1",
)
_EXPOSURE_MODE_RANK = {
    "deny": 0,
    "redact": 1,
    "ask_user": 2,
    "allow": 3,
}
_PREFERRED_RUNTIME_USE_RANK = {
    "retrieve_when_relevant": 1,
    "contextual_retrieval": 1,
    "private_retrieval": 1,
    "ltm_retrieval": 1,
    "inject_when_relevant": 2,
    "always_inject": 3,
    "hot_identity": 3,
}


def normalize_identity_artifact(import_result: IdentityImportResult) -> NormalizedIdentityModel:
    parsed = import_result.raw.parsed
    if import_result.raw.status != "imported" or not isinstance(parsed, dict) or import_result.structured is None:
        raise ValueError("Only successfully imported identity artifacts can be normalized")

    source_registry = import_result.structured.source_registry
    records: list[IdentityRecord] = []
    transient_records: list[TransientRecord] = []
    quarantine: list[QuarantineItem] = []
    review_queue: list[ReviewItem] = []
    used_record_ids: set[str] = set()
    source_id_to_record_id: dict[str, str] = {}
    record_sources: dict[str, Mapping[str, Any]] = {}

    transient = parsed.get("transient_continuity")
    if isinstance(transient, Mapping):
        transient_record = _make_transient_record(
            "$.transient_continuity",
            transient,
            "",
            parsed,
            source_registry,
        )
        transient_records.append(transient_record)
        policy_conflicts = _policy_conflict_fields(transient_record.provenance)
        if policy_conflicts:
            review_queue.append(
                _make_review(
                    ReviewKind.RUNTIME_PERMISSION,
                    record_ids=(transient_record.record_id,),
                    source_paths=(transient_record.source_path,),
                    reason=(
                        "Conflicting unknown declared-policy fields require explicit "
                        "review before runtime use."
                    ),
                    details={"policy_conflict_fields": policy_conflicts},
                )
            )
        quarantine_reason = _transient_quarantine_reason(transient, transient_record)
        if quarantine_reason is not None:
            quarantine.append(
                QuarantineItem(
                    quarantine_id="quarantine:" + _digest(
                        [transient_record.record_id, quarantine_reason.value]
                    ),
                    reason=quarantine_reason,
                    record_ids=(transient_record.record_id,),
                    source_path=transient_record.source_path,
                    source_text=transient_record.source_text,
                    details={"review_state": transient_record.review_state},
                )
            )

    for source_path, section, value in _iter_source_units(parsed):
        if section == _UNSUPPORTED_SECTION:
            record = _make_unclassified_record(
                source_path,
                value,
                used_record_ids,
                wording_kind="unsupported_shape",
            )
            records.append(record)
            review_queue.append(
                _make_review(
                    ReviewKind.RUNTIME_LAYER,
                    record_ids=(record.record_id,),
                    source_paths=(record.source_path,),
                    reason="Recognized source value has an unsupported shape and cannot be classified.",
                )
            )
            continue
        item = value if isinstance(value, Mapping) else {"text": value}
        record = _make_record(
            source_path,
            section,
            item,
            source_registry,
            used_record_ids,
            parsed,
        )
        records.append(record)
        source_id = _source_id(item)
        if source_id:
            source_id_to_record_id.setdefault(source_id, record.record_id)
        record_sources[record.record_id] = item
        if record.runtime_layer == RuntimeLayer.UNCLASSIFIED:
            review_queue.append(
                _make_review(
                    ReviewKind.RUNTIME_LAYER,
                    record_ids=(record.record_id,),
                    source_paths=(record.source_path,),
                    reason="The artifact does not provide enough semantic role or layer evidence.",
                )
            )
        if record.review_state == "required":
            policy_conflicts = _policy_conflict_fields(record.provenance)
            review_queue.append(
                _make_review(
                    ReviewKind.RUNTIME_PERMISSION,
                    record_ids=(record.record_id,),
                    source_paths=(record.source_path,),
                    reason=(
                        "Conflicting unknown declared-policy fields require explicit "
                        "review before runtime use."
                        if policy_conflicts
                        else "The source item explicitly requires user review before use."
                    ),
                    details=(
                        {"policy_conflict_fields": policy_conflicts}
                        if policy_conflicts
                        else None
                    ),
                )
            )

    known_fields = _ENVELOPE_FIELDS | _SOURCE_SECTIONS
    unknown_fields = {str(key): value for key, value in parsed.items() if str(key) not in known_fields}
    for field_name in sorted(unknown_fields):
        source_path = f"$.{field_name}"
        source_text = _source_text(unknown_fields[field_name])
        record_id = _unique_record_id("", source_path, source_text, used_record_ids)
        record = IdentityRecord(
            record_id=record_id,
            source_path=source_path,
            source_text=source_text,
            semantic_role="unclassified",
            subject_refs=(),
            stability="unknown",
            confidence=None,
            epistemic_qualifier="unclassified",
            runtime_layer=RuntimeLayer.UNCLASSIFIED,
            durability="unknown",
            stale_after=None,
            tags=(),
            retrieval_hints=(),
            declared_policy={},
            exposure_policy={},
            privacy_class="unknown",
            runtime_suitability=(),
            review_state="required",
            wording_provenance={"kind": "unknown_field"},
            provenance={"source_path": source_path},
        )
        records.append(record)
        review_queue.append(
            _make_review(
                ReviewKind.UNKNOWN_FIELD,
                record_ids=(record.record_id,),
                source_paths=(record.source_path,),
                reason="Unknown root field preserved without runtime classification.",
                details={"field_name": field_name},
            )
        )

    subject_class = _subject_class(parsed, records)
    if subject_class == SubjectClass.UNKNOWN:
        review_queue.append(
            _make_review(
                ReviewKind.SUBJECT_CLASS,
                proposed_value=SubjectClass.UNKNOWN.value,
                reason="The artifact has no unambiguous explicit subject attribution.",
            )
        )

    envelope = ArtifactEnvelope(
        artifact_hash=import_result.raw.artifact_hash,
        format=import_result.raw.format,
        format_version=import_result.raw.format_version,
        export_kind=import_result.raw.export_kind,
        artifact_mode=_string(parsed.get("artifact_mode")),
        default_runtime_context=_string(parsed.get("default_runtime_context")),
        subject_class=subject_class,
        artifact_contract=_as_mapping(parsed.get("artifact_contract")),
        source_scope=_as_mapping(parsed.get("source_scope")),
        source_registry=source_registry,
        coverage_assessment=_as_mapping(parsed.get("coverage_assessment")),
        exposure_model=_as_mapping(parsed.get("exposure_model")),
        import_notes=_as_mapping(parsed.get("import_notes")),
        artifact_limits=_as_mapping(parsed.get("artifact_limits")),
        mechanical_audit=tuple(import_result.raw.mechanical_warnings),
        semantic_audit=_semantic_audit(parsed),
    )
    tensions = _linked_tensions(records, record_sources, source_id_to_record_id)
    return NormalizedIdentityModel(
        schema_version=NORMALIZED_SCHEMA_VERSION,
        normalizer_revision=NORMALIZER_REVISION,
        envelope=envelope,
        records=tuple(records),
        kernel_record_ids=tuple(
            record.record_id for record in records if record.runtime_layer == RuntimeLayer.KERNEL
        ),
        retrievable_record_ids=tuple(
            record.record_id for record in records if record.runtime_layer == RuntimeLayer.RETRIEVABLE
        ),
        transient_records=tuple(transient_records),
        tensions=tensions,
        review_queue=tuple(review_queue),
        quarantine=tuple(quarantine),
        unknown_fields=unknown_fields,
    )


def _iter_source_units(parsed: Mapping[str, Any]) -> Iterable[tuple[str, str, Any]]:
    yield from _unsupported_envelope_units(parsed)

    hot_identity = parsed.get("hot_identity")
    if isinstance(hot_identity, Mapping):
        yield from _list_units("$.hot_identity.claims", "hot_identity.claims", hot_identity.get("claims"))
    elif hot_identity is not None:
        yield "$.hot_identity", _UNSUPPORTED_SECTION, hot_identity

    transient = parsed.get("transient_continuity")
    if transient is not None and not isinstance(transient, Mapping):
        yield "$.transient_continuity", _UNSUPPORTED_SECTION, transient

    identity_structure = parsed.get("identity_structure")
    if isinstance(identity_structure, Mapping):
        yield from _list_units(
            "$.identity_structure.identity_items",
            "identity_items",
            identity_structure.get("identity_items"),
        )
        yield from _list_units(
            "$.identity_structure.do_not_infer",
            "do_not_infer",
            identity_structure.get("do_not_infer"),
        )
        for section in _IDENTITY_STRUCTURE_SECTIONS:
            yield from _list_units(
                f"$.identity_structure.{section}",
                section,
                identity_structure.get(section),
            )
    elif identity_structure is not None:
        yield "$.identity_structure", _UNSUPPORTED_SECTION, identity_structure

    yield from _list_units("$.identity_items", "identity_items", parsed.get("identity_items"))
    yield from _list_units("$.ltm_seed_records", "ltm_seed_records", parsed.get("ltm_seed_records"))
    yield from _list_units(
        "$.identity_projections",
        "identity_projections",
        parsed.get("identity_projections"),
    )
    for section in _GENERIC_SECTIONS:
        yield from _list_units(f"$.{section}", section, parsed.get(section))

    artifact_limits = parsed.get("artifact_limits")
    if isinstance(artifact_limits, Mapping):
        for field_name in (
            "non_claims",
            "likely_missing_context",
            "known_missing_payloads",
            "source_limitations",
            "possible_hallucination_sources",
        ):
            yield from _list_units(
                f"$.artifact_limits.{field_name}",
                "artifact_limits" if field_name != "non_claims" else "non_claims",
                artifact_limits.get(field_name),
            )
    elif artifact_limits is not None:
        yield "$.artifact_limits", _UNSUPPORTED_SECTION, artifact_limits


def _unsupported_envelope_units(parsed: Mapping[str, Any]) -> Iterable[tuple[str, str, Any]]:
    expected_types: tuple[tuple[str, type | tuple[type, ...]], ...] = (
        ("artifact_mode", str),
        ("default_runtime_context", str),
        ("subject_class", str),
        ("subject", Mapping),
        ("artifact_contract", Mapping),
        ("source_scope", Mapping),
        ("source_registry", list),
        ("coverage_assessment", Mapping),
        ("exposure_model", Mapping),
        ("import_notes", Mapping),
        ("audits", Mapping),
        ("mechanical_audit", Mapping),
        ("semantic_audit", Mapping),
    )
    for field_name, expected_type in expected_types:
        value = parsed.get(field_name)
        if value is not None and not isinstance(value, expected_type):
            yield f"$.{field_name}", _UNSUPPORTED_SECTION, value


def _list_units(path: str, section: str, value: Any) -> Iterable[tuple[str, str, Any]]:
    if value is None:
        return
    if not isinstance(value, list):
        yield path, _UNSUPPORTED_SECTION, value
        return
    for index, item in enumerate(value):
        if isinstance(item, (Mapping, str)):
            yield f"{path}[{index}]", section, item
        else:
            yield f"{path}[{index}]", _UNSUPPORTED_SECTION, item


def _make_unclassified_record(
    source_path: str,
    value: Any,
    used_record_ids: set[str],
    *,
    wording_kind: str,
) -> IdentityRecord:
    source_text = _source_text(value)
    return IdentityRecord(
        record_id=_unique_record_id("", source_path, source_text, used_record_ids),
        source_path=source_path,
        source_text=source_text,
        semantic_role="unclassified",
        subject_refs=(),
        stability="unknown",
        confidence=None,
        epistemic_qualifier="unclassified",
        runtime_layer=RuntimeLayer.UNCLASSIFIED,
        durability="unknown",
        stale_after=None,
        tags=(),
        retrieval_hints=(),
        declared_policy={},
        exposure_policy={},
        privacy_class="unknown",
        runtime_suitability=(),
        review_state="required",
        wording_provenance={"kind": wording_kind},
        provenance={"source_path": source_path},
    )


def _make_record(
    source_path: str,
    section: str,
    item: Mapping[str, Any],
    source_registry: Mapping[str, Any],
    used_record_ids: set[str],
    artifact: Mapping[str, Any],
) -> IdentityRecord:
    source_text = _record_text(item)
    source_id = _source_id(item)
    record_id = _unique_record_id(source_id, source_path, source_text, used_record_ids)
    semantic_role = _semantic_role(section, item)
    stability = _stability(section, item)
    runtime_layer = _runtime_layer(section, semantic_role, stability, item)
    if _contains_declared_source_runtime_name(item, artifact):
        runtime_layer = RuntimeLayer.PROVENANCE
    confidence = _number(item.get("confidence"))
    source_declared_policy = _first_mapping(item, "declared_policy", "use_policy")
    source_exposure_policy = _first_mapping(item, "exposure_policy")
    (
        declared_policy,
        exposure_policy,
        inherited_declared_fields,
        inherited_exposure_fields,
        inheritance_sources,
        policy_conflicts,
    ) = _inherited_record_policy(
        artifact,
        runtime_layer,
        source_declared_policy,
        source_exposure_policy,
    )
    subject_refs = _strings(item.get("subject_refs"))
    if not subject_refs:
        subject_refs = _strings(item.get("subjects"))
    if not subject_refs:
        subject_refs = _strings(item.get("subject_id") or item.get("subject"))
    source_ids = _strings(item.get("source_ids"))
    provenance = _provenance(item.get("provenance"), source_ids, source_registry)
    if inherited_declared_fields or inherited_exposure_fields or policy_conflicts:
        provenance = dict(provenance)
        provenance["policy_inheritance"] = {
            "source_fields": inheritance_sources,
            "declared_policy_fields": inherited_declared_fields,
            "exposure_policy_fields": inherited_exposure_fields,
        }
        if policy_conflicts:
            provenance["policy_review"] = {
                "conflicting_fields": policy_conflicts,
            }
    wording_provenance = _wording_provenance(item.get("wording_provenance"))
    review_required = (
        bool(item.get("user_review_required"))
        or bool(declared_policy.get("requires_user_review_before_use"))
        or bool(policy_conflicts)
    )
    return IdentityRecord(
        record_id=record_id,
        source_path=source_path,
        source_text=source_text,
        semantic_role=semantic_role,
        subject_refs=subject_refs,
        stability=stability,
        confidence=confidence,
        epistemic_qualifier=_epistemic_qualifier(item, confidence),
        runtime_layer=runtime_layer,
        durability=_durability(item, stability),
        stale_after=_optional_string(item.get("stale_after") or item.get("expires_at")),
        tags=_strings(item.get("tags")),
        retrieval_hints=_retrieval_hints(item),
        declared_policy=declared_policy,
        exposure_policy=exposure_policy,
        privacy_class=_string(item.get("privacy_class") or item.get("privacy_sensitivity") or "unspecified"),
        runtime_suitability=_runtime_suitability(item, declared_policy),
        review_state="required" if review_required or runtime_layer == RuntimeLayer.UNCLASSIFIED else "not_required",
        wording_provenance=wording_provenance,
        provenance=provenance,
    )


def _inherited_record_policy(
    artifact: Mapping[str, Any],
    runtime_layer: RuntimeLayer,
    source_declared_policy: Mapping[str, Any],
    source_exposure_policy: Mapping[str, Any],
) -> tuple[
    Mapping[str, Any],
    Mapping[str, Any],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    exposure_model = _as_mapping(artifact.get("exposure_model"))
    runtime_context = _string(artifact.get("default_runtime_context"))
    default_projection = _string(exposure_model.get("default_projection"))
    source_fields: list[str] = []

    artifact_exposure: dict[str, Any] = {}
    nested_exposure = _as_mapping(exposure_model.get("default_exposure_policy"))
    for key in _ARTIFACT_EXPOSURE_KEYS:
        if key in nested_exposure:
            artifact_exposure[key] = nested_exposure[key]
            source_fields.append(f"$.exposure_model.default_exposure_policy.{key}")
    for key in _ARTIFACT_EXPOSURE_KEYS:
        if key in exposure_model:
            artifact_exposure[key] = exposure_model[key]
            source_fields.append(f"$.exposure_model.{key}")
    if (
        default_projection in _ARTIFACT_PRIVATE_PROJECTIONS
        and runtime_context in _ARTIFACT_RUNTIME_CONTEXTS
        and runtime_context not in artifact_exposure
    ):
        artifact_exposure[runtime_context] = "allow"
        source_fields.extend(
            ("$.default_runtime_context", "$.exposure_model.default_projection")
        )

    explicit_declared_defaults = dict(
        _as_mapping(exposure_model.get("default_use_policy"))
    )
    declared_defaults = dict(explicit_declared_defaults)
    if explicit_declared_defaults:
        source_fields.append("$.exposure_model.default_use_policy")
    elif default_projection in _ARTIFACT_PRIVATE_PROJECTIONS:
        if runtime_layer == RuntimeLayer.KERNEL:
            declared_defaults["preferred_runtime_use"] = "always_inject"
        elif runtime_layer == RuntimeLayer.RETRIEVABLE:
            declared_defaults.update(
                {
                    "preferred_runtime_use": "retrieve_when_relevant",
                    "eligible_for_private_retrieval": True,
                }
            )
        if declared_defaults:
            source_fields.append("$.exposure_model.default_projection")

    runtime_policy_declared = any(
        str(key).startswith("eligible_for_")
        or str(key)
        in {
            "preferred_runtime_use",
            "prohibited_runtime_use",
            "allowed_surfaces",
        }
        for key in source_declared_policy
    )
    if explicit_declared_defaults:
        effective_declared, policy_conflicts = _intersect_declared_policy(
            explicit_declared_defaults,
            source_declared_policy,
        )
        inherited_declared_fields = tuple(
            sorted(str(key) for key in explicit_declared_defaults)
        )
    else:
        inherited_declared = (
            {}
            if runtime_policy_declared
            else {
                key: value
                for key, value in declared_defaults.items()
                if key not in source_declared_policy
            }
        )
        effective_declared, policy_conflicts = _validated_declared_policy(
            {**inherited_declared, **dict(source_declared_policy)}
        )
        inherited_declared_fields = tuple(
            sorted(str(key) for key in inherited_declared)
        )
    inherited_exposure = dict(artifact_exposure)
    effective_exposure = dict(artifact_exposure)
    for key, value in source_exposure_policy.items():
        if key not in effective_exposure:
            effective_exposure[key] = value
            continue
        effective_exposure[key] = _narrow_exposure_mode(
            effective_exposure[key],
            value,
        )
        inherited_exposure.pop(key, None)
    return (
        effective_declared,
        effective_exposure,
        inherited_declared_fields,
        tuple(sorted(inherited_exposure)),
        tuple(sorted(set(source_fields))),
        policy_conflicts,
    )


def _intersect_declared_policy(
    artifact_policy: Mapping[str, Any],
    record_policy: Mapping[str, Any],
) -> tuple[Mapping[str, Any], tuple[str, ...]]:
    result, artifact_conflicts = _validated_declared_policy(artifact_policy)
    validated_record, record_conflicts = _validated_declared_policy(record_policy)
    conflicts = [*artifact_conflicts, *record_conflicts]
    for key, record_value in validated_record.items():
        if key not in result:
            if str(key).startswith("eligible_for_") or key == "allow_remote_provider":
                result[key] = False
                if record_value is not False:
                    conflicts.append(str(key))
            elif key == "requires_user_review_before_use":
                result[key] = record_value if type(record_value) is bool else True
                if type(record_value) is not bool:
                    conflicts.append(str(key))
            elif key == "allowed_surfaces":
                result[key] = ()
                if _policy_strings(record_value) != ():
                    conflicts.append(str(key))
            elif key == "preferred_runtime_use":
                result[key] = ""
                if record_value:
                    conflicts.append(str(key))
            elif key == "prohibited_runtime_use":
                values = _policy_strings(record_value)
                if values is None:
                    result[key] = record_value
                    conflicts.append(str(key))
                else:
                    result[key] = values
            else:
                result[key] = record_value
            continue
        artifact_value = result[key]
        if str(key).startswith("eligible_for_") or key == "allow_remote_provider":
            if type(artifact_value) is bool and type(record_value) is bool:
                result[key] = artifact_value and record_value
            else:
                result[key] = False
                conflicts.append(str(key))
            continue
        if key == "requires_user_review_before_use":
            if type(artifact_value) is bool and type(record_value) is bool:
                result[key] = artifact_value or record_value
            else:
                result[key] = True
                conflicts.append(str(key))
            continue
        if key == "allowed_surfaces":
            artifact_surfaces = _policy_strings(artifact_value)
            record_surfaces = _policy_strings(record_value)
            if artifact_surfaces is not None and record_surfaces is not None:
                record_surface_set = set(record_surfaces)
                result[key] = tuple(
                    surface
                    for surface in artifact_surfaces
                    if surface in record_surface_set
                )
            else:
                result[key] = ()
                conflicts.append(str(key))
            continue
        if key == "prohibited_runtime_use":
            artifact_prohibited = _policy_strings(artifact_value)
            record_prohibited = _policy_strings(record_value)
            if artifact_prohibited is not None and record_prohibited is not None:
                result[key] = tuple(
                    dict.fromkeys((*artifact_prohibited, *record_prohibited))
                )
            else:
                result[key] = (
                    artifact_value
                    if artifact_prohibited is None
                    else record_value
                )
                conflicts.append(str(key))
            continue
        if key == "preferred_runtime_use":
            artifact_use = _policy_string(artifact_value)
            record_use = _policy_string(record_value)
            artifact_rank = _PREFERRED_RUNTIME_USE_RANK.get(artifact_use)
            record_rank = _PREFERRED_RUNTIME_USE_RANK.get(record_use)
            if artifact_use == record_use and artifact_rank is not None:
                result[key] = artifact_use
            elif artifact_rank is not None and record_rank is not None:
                result[key] = (
                    record_use if record_rank < artifact_rank else artifact_use
                )
            else:
                result[key] = ""
                conflicts.append(str(key))
            continue
        if artifact_value != record_value:
            conflicts.append(str(key))
        result[key] = artifact_value
    return result, tuple(sorted(set(conflicts)))


def _canonical_declared_policy_value(key: Any, value: Any) -> Any:
    if key not in {"allowed_surfaces", "prohibited_runtime_use"}:
        return value
    if key == "prohibited_runtime_use" and value is None:
        return ()
    values = _policy_strings(value)
    return value if values is None else values


def _validated_declared_policy(
    policy: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    result: dict[str, Any] = {}
    conflicts: list[str] = []
    for key, value in policy.items():
        name = str(key)
        normalized = _canonical_declared_policy_value(key, value)
        malformed = False
        if name.startswith("eligible_for_") or key == "allow_remote_provider":
            if type(value) is not bool:
                normalized = False
                malformed = True
        elif key == "requires_user_review_before_use":
            if type(value) is not bool:
                normalized = True
                malformed = True
        elif key == "allowed_surfaces":
            if _policy_strings(value) is None:
                normalized = ()
                malformed = True
        elif key == "prohibited_runtime_use":
            if value is not None and _policy_strings(value) is None:
                malformed = True
        elif key == "preferred_runtime_use":
            preferred = _policy_string(value)
            if preferred not in _PREFERRED_RUNTIME_USE_RANK:
                normalized = ""
                malformed = True
            else:
                normalized = preferred
        result[key] = normalized
        if malformed:
            conflicts.append(name)
    return result, tuple(sorted(set(conflicts)))


def _policy_strings(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, (list, tuple)):
        return None
    if any(not isinstance(item, str) or not item for item in value):
        return None
    return tuple(sorted(set(value)))


def _policy_string(value: Any) -> str:
    return value.strip().casefold() if isinstance(value, str) else ""


def _policy_conflict_fields(provenance: Mapping[str, Any]) -> tuple[str, ...]:
    review = provenance.get("policy_review")
    if not isinstance(review, Mapping):
        return ()
    fields = review.get("conflicting_fields")
    if not isinstance(fields, (list, tuple)):
        return ()
    return tuple(str(field) for field in fields if str(field))


def _narrow_exposure_mode(artifact_value: Any, record_value: Any) -> Any:
    artifact_mode = (
        artifact_value.strip().casefold()
        if isinstance(artifact_value, str)
        else ""
    )
    record_mode = (
        record_value.strip().casefold()
        if isinstance(record_value, str)
        else ""
    )
    if artifact_mode not in _EXPOSURE_MODE_RANK:
        return artifact_value
    if record_mode not in _EXPOSURE_MODE_RANK:
        return record_value
    return min(
        (artifact_mode, record_mode),
        key=lambda mode: _EXPOSURE_MODE_RANK[mode],
    )


def _make_transient_record(
    source_path: str,
    item: Mapping[str, Any],
    source_id: str,
    artifact: Mapping[str, Any],
    source_registry: Mapping[str, Any],
) -> TransientRecord:
    source_text = _record_text(item)
    ttl = item.get("ttl_seconds")
    risk = _number(item.get("staleness_risk"))
    confidence = _number(item.get("confidence"))
    source_declared_policy = _first_mapping(item, "declared_policy", "use_policy")
    source_exposure_policy = _first_mapping(item, "exposure_policy")
    runtime_layer = (
        RuntimeLayer.PROVENANCE
        if _contains_declared_source_runtime_name(item, artifact)
        else RuntimeLayer.RETRIEVABLE
    )
    (
        declared_policy,
        exposure_policy,
        inherited_declared_fields,
        inherited_exposure_fields,
        inheritance_sources,
        policy_conflicts,
    ) = _inherited_record_policy(
        artifact,
        runtime_layer,
        source_declared_policy,
        source_exposure_policy,
    )
    source_ids = _strings(item.get("source_ids"))
    provenance = dict(_provenance(item.get("provenance"), source_ids, source_registry))
    provenance.setdefault("source_path", source_path)
    if inherited_declared_fields or inherited_exposure_fields or policy_conflicts:
        provenance["policy_inheritance"] = {
            "source_fields": inheritance_sources,
            "declared_policy_fields": inherited_declared_fields,
            "exposure_policy_fields": inherited_exposure_fields,
        }
        if policy_conflicts:
            provenance["policy_review"] = {
                "conflicting_fields": policy_conflicts,
            }
    malformed_policy = _transient_policy_is_malformed(item)
    subject_refs = _strings(item.get("subject_refs"))
    attributed = bool(subject_refs) and set(subject_refs) == {
        SubjectClass.ASSISTANT_SELF.value
    }
    review_required = bool(item.get("user_review_required")) or bool(
        declared_policy.get("requires_user_review_before_use")
    ) or bool(policy_conflicts)
    if not source_text.strip() or not attributed or malformed_policy:
        review_state = "quarantined"
    elif review_required:
        review_state = "required"
    else:
        review_state = "not_required"
    return TransientRecord(
        record_id=_prefixed_id("transient", source_id, source_path, source_text),
        source_path=source_path,
        source_text=source_text,
        subject_refs=subject_refs,
        included_item_ids=_strings(item.get("included_item_ids")) or ((source_id,) if source_id else ()),
        ttl_hint=_string(item.get("ttl_hint")),
        ttl_seconds=int(ttl) if isinstance(ttl, (int, float)) and not isinstance(ttl, bool) else None,
        origin_timestamp=_optional_string(item.get("origin_timestamp") or item.get("created_at")),
        expiration_notes=_strings(item.get("expiration_notes")),
        confidence=confidence,
        staleness_risk=risk,
        provenance=provenance,
        active_by_default=False,
        semantic_role="transient_continuity",
        runtime_layer=runtime_layer,
        epistemic_qualifier=_epistemic_qualifier(item, confidence),
        declared_policy=declared_policy,
        exposure_policy=exposure_policy,
        privacy_class=_string(
            item.get("privacy_class")
            or item.get("privacy_sensitivity")
            or "unspecified"
        ),
        runtime_suitability=_runtime_suitability(item, declared_policy),
        review_state=review_state,
        activation_metadata={
            "ttl_hint": _string(item.get("ttl_hint")),
            "ttl_seconds": (
                int(ttl)
                if isinstance(ttl, (int, float)) and not isinstance(ttl, bool)
                else None
            ),
            "active_by_default_requested": bool(item.get("active_by_default", False)),
            "requires_explicit_activation": True,
        },
    )


def _transient_policy_is_malformed(item: Mapping[str, Any]) -> bool:
    for field_names in (("declared_policy", "use_policy"), ("exposure_policy",)):
        present = next((item.get(name) for name in field_names if name in item), None)
        if present is not None and not isinstance(present, Mapping):
            return True
    return False


def _contains_declared_source_runtime_name(
    value: Any,
    artifact: Mapping[str, Any],
) -> bool:
    names = _declared_source_runtime_names(artifact)
    if not names:
        return False
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        text = str(value)
    folded = text.casefold()
    return any(name.casefold() in folded for name in names)


def _declared_source_runtime_names(artifact: Mapping[str, Any]) -> tuple[str, ...]:
    identity_structure = artifact.get("identity_structure")
    if not isinstance(identity_structure, Mapping):
        return ()
    hint = identity_structure.get("identity_name_hint")
    if not isinstance(hint, str) or not hint.strip():
        return ()
    names = [hint.strip()]
    names.extend(
        part.strip()
        for part in re.split(r"\s*(?:—|–|\||/)\s*", hint)
        if part.strip()
    )
    return tuple(dict.fromkeys(name for name in names if len(name) >= 3))


def _transient_quarantine_reason(
    item: Mapping[str, Any],
    transient: TransientRecord,
) -> QuarantineReason | None:
    if not transient.source_text.strip():
        return QuarantineReason.CORRUPTION
    if not transient.subject_refs or set(transient.subject_refs) != {
        SubjectClass.ASSISTANT_SELF.value
    }:
        return QuarantineReason.INVALID_ATTRIBUTION
    if _transient_policy_is_malformed(item):
        return QuarantineReason.POLICY
    return None


def _runtime_layer(
    section: str,
    semantic_role: str,
    stability: str,
    item: Mapping[str, Any],
) -> RuntimeLayer:
    role = semantic_role.lower()
    if role in _SOURCE_RUNTIME_ROLES:
        return RuntimeLayer.PROVENANCE
    if section in {"hot_identity.claims", "do_not_infer", "non_claims"}:
        return RuntimeLayer.KERNEL
    if section in {"ltm_seed_records", "identity_projections", "projects", "threads", "corrective_items", "corrections"}:
        return RuntimeLayer.RETRIEVABLE
    identity_layer = _string(item.get("identity_layer")).lower()
    promotion_target = _string(item.get("promotion_target")).lower()
    if identity_layer:
        if identity_layer in _CENTRAL_ROLES:
            return RuntimeLayer.KERNEL
        if identity_layer in _RETRIEVABLE_ROLES or identity_layer == "interaction_style":
            return RuntimeLayer.RETRIEVABLE
        return RuntimeLayer.UNCLASSIFIED
    if not _semantic_labels_are_known(item, semantic_role):
        return RuntimeLayer.UNCLASSIFIED
    if role in _CENTRAL_ROLES:
        return RuntimeLayer.KERNEL
    if promotion_target == "hot_identity" and stability.lower() not in {"contextual", "transient"}:
        return RuntimeLayer.KERNEL
    if role in _RETRIEVABLE_ROLES or role == "interaction_style":
        return RuntimeLayer.RETRIEVABLE
    return RuntimeLayer.UNCLASSIFIED


def _semantic_labels_are_known(item: Mapping[str, Any], semantic_role: str) -> bool:
    if semantic_role.lower() not in _KNOWN_SEMANTIC_LABELS:
        return False
    for field_name in _SEMANTIC_FIELDS:
        if field_name not in item:
            continue
        value = item.get(field_name)
        if not isinstance(value, str) or value.lower() not in _KNOWN_SEMANTIC_LABELS:
            return False
    return True


def _semantic_role(section: str, item: Mapping[str, Any]) -> str:
    explicit = item.get("semantic_role") or item.get("category") or item.get("identity_layer")
    if explicit is not None and _string(explicit):
        return _string(explicit)
    defaults = {
        "hot_identity.claims": "identity_core",
        "do_not_infer": "non_invention",
        "non_claims": "non_claim",
        "artifact_limits": "artifact_limit",
        "ltm_seed_records": "long_term_memory",
        "identity_projections": "projection_policy",
        "relationships": "relationship_continuity",
        "relationship_statements": "relationship_continuity",
        "corrective_items": "correction",
        "corrections": "correction",
        "projects": "project_context",
        "threads": "active_thread",
        "boundaries": "boundary",
        "policies": "policy",
        "claims": "claim",
    }
    return defaults.get(section, "unclassified")


def _stability(section: str, item: Mapping[str, Any]) -> str:
    if item.get("stability") is not None:
        return _string(item.get("stability"))
    if section in {"hot_identity.claims", "do_not_infer", "non_claims", "artifact_limits", "boundaries", "policies"}:
        return "stable"
    durability = _number(item.get("durability"))
    if durability is not None:
        if durability >= 0.75:
            return "stable"
        if durability <= 0.25:
            return "transient"
        return "contextual"
    if section in {"ltm_seed_records", "identity_projections", "projects", "threads"}:
        return "contextual"
    return "unspecified"


def _durability(item: Mapping[str, Any], stability: str) -> str:
    value = item.get("durability")
    return _string(value) if value is not None else stability


def _epistemic_qualifier(item: Mapping[str, Any], confidence: float | None) -> str:
    explicit = item.get("epistemic_qualifier") or item.get("epistemic_status")
    if explicit is not None and _string(explicit):
        value = _string(explicit)
        lowered = value.lower()
        if any(token in lowered for token in ("uncertain", "contested", "unresolved")):
            return "uncertain"
        return value
    if confidence is None:
        return "unspecified"
    return "uncertain" if confidence < 0.5 else "supported"


def _runtime_suitability(item: Mapping[str, Any], declared_policy: Mapping[str, Any]) -> tuple[str, ...]:
    explicit = _strings(item.get("runtime_suitability"))
    if explicit:
        return explicit
    values: list[str] = []
    preferred = declared_policy.get("preferred_runtime_use")
    if isinstance(preferred, str) and preferred:
        values.append(preferred)
    values.extend(
        str(key)
        for key, value in declared_policy.items()
        if str(key).startswith("eligible_for_") and value is True
    )
    return tuple(dict.fromkeys(values))


def _provenance(
    value: Any,
    source_ids: tuple[str, ...],
    source_registry: Mapping[str, Any],
) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        result: dict[str, Any] = dict(value)
    elif value is None:
        result = {}
    else:
        result = {"value": value}
    if source_ids:
        result["source_ids"] = source_ids
        sources = {source_id: source_registry[source_id] for source_id in source_ids if source_id in source_registry}
        if sources:
            result["sources"] = sources
    return result


def _wording_provenance(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if value is None:
        return {}
    return {"value": value}


def _retrieval_hints(item: Mapping[str, Any]) -> tuple[str, ...]:
    hints = list(_strings(item.get("retrieval_hints")))
    singular = item.get("retrieval_hint")
    if isinstance(singular, str):
        hints.append(singular)
    return tuple(dict.fromkeys(hints))


def _subject_class(parsed: Mapping[str, Any], records: list[IdentityRecord]) -> SubjectClass:
    explicit = parsed.get("subject_class")
    subject = parsed.get("subject")
    if explicit is None and isinstance(subject, Mapping):
        explicit = subject.get("class") or subject.get("subject_class")
    if isinstance(explicit, str):
        try:
            return SubjectClass(explicit)
        except ValueError:
            return SubjectClass.UNKNOWN

    kinds: set[SubjectClass] = set()
    for record in records:
        for reference in record.subject_refs:
            lowered = reference.lower()
            subject_class = _SUBJECT_REFERENCE_CLASSES.get(lowered)
            if subject_class is None or subject_class == SubjectClass.UNKNOWN:
                return SubjectClass.UNKNOWN
            if subject_class == SubjectClass.MIXED:
                return SubjectClass.MIXED
            kinds.add(subject_class)
    if not kinds:
        return SubjectClass.UNKNOWN
    if len(kinds) > 1:
        return SubjectClass.MIXED
    return next(iter(kinds))


def _linked_tensions(
    records: list[IdentityRecord],
    record_sources: Mapping[str, Mapping[str, Any]],
    source_id_to_record_id: Mapping[str, str],
) -> tuple[LinkedTension, ...]:
    records_by_id = {record.record_id: record for record in records}
    parent = {record_id: record_id for record_id in record_sources}

    def find(record_id: str) -> str:
        while parent[record_id] != record_id:
            parent[record_id] = parent[parent[record_id]]
            record_id = parent[record_id]
        return record_id

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    tension_groups: dict[str, list[str]] = defaultdict(list)
    for record_id, item in record_sources.items():
        group = item.get("tension_id") or item.get("tension_group")
        if isinstance(group, str) and group:
            tension_groups[group].append(record_id)
        for field_name in _CONTRADICTION_FIELDS:
            for target in _strings(item.get(field_name)):
                target_id = target if target in records_by_id else source_id_to_record_id.get(target)
                if target_id in parent and target_id != record_id:
                    union(record_id, target_id)
    for group_ids in tension_groups.values():
        for record_id in group_ids[1:]:
            union(group_ids[0], record_id)

    components: dict[str, list[str]] = defaultdict(list)
    for record_id in parent:
        components[find(record_id)].append(record_id)
    tensions: list[LinkedTension] = []
    for record_ids in components.values():
        if len(record_ids) < 2:
            continue
        ordered_ids = tuple(sorted(record_ids))
        subjects = tuple(
            dict.fromkeys(
                reference
                for record_id in ordered_ids
                for reference in records_by_id[record_id].subject_refs
            )
        )
        tensions.append(
            LinkedTension(
                tension_id="tension:" + _digest(list(ordered_ids)),
                record_ids=ordered_ids,
                subject_refs=subjects,
                scope="identity",
                state="unresolved",
                epistemic_states=tuple(
                    records_by_id[record_id].epistemic_qualifier for record_id in ordered_ids
                ),
            )
        )
    return tuple(sorted(tensions, key=lambda item: item.tension_id))


def _make_review(
    kind: ReviewKind,
    *,
    record_ids: tuple[str, ...] = (),
    source_paths: tuple[str, ...] = (),
    proposed_value: str = "",
    reason: str,
    details: Mapping[str, Any] | None = None,
) -> ReviewItem:
    identity = [kind.value, list(record_ids), list(source_paths), proposed_value, reason]
    return ReviewItem(
        review_id="review:" + _digest(identity),
        kind=kind,
        record_ids=record_ids,
        source_paths=source_paths,
        proposed_value=proposed_value,
        reason=reason,
        details=details or {},
    )


def _unique_record_id(
    source_id: str,
    source_path: str,
    source_text: str,
    used_record_ids: set[str],
) -> str:
    record_id = _prefixed_id("record", source_id, source_path, source_text)
    if record_id in used_record_ids:
        record_id = f"{record_id}:{_digest([source_path, source_text])[:12]}"
    used_record_ids.add(record_id)
    return record_id


def _prefixed_id(prefix: str, source_id: str, source_path: str, source_text: str) -> str:
    suffix = source_id or _digest([source_path, source_text])
    return f"{prefix}:{suffix}"


def _digest(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]


def _record_text(item: Mapping[str, Any]) -> str:
    for field_name in (
        "text",
        "claim_text",
        "statement",
        "summary",
        "projection_summary",
        "projected_hot_identity_text",
        "compressed_text",
        "description",
        "policy_text",
        "boundary_text",
        "title",
    ):
        value = item.get(field_name)
        if isinstance(value, str):
            return value
    return _source_text(item)


def _source_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _source_id(item: Mapping[str, Any]) -> str:
    for field_name in (
        "claim_id",
        "id",
        "record_id",
        "projection_id",
        "item_id",
        "relationship_id",
        "project_id",
        "thread_id",
        "boundary_id",
        "policy_id",
    ):
        value = item.get(field_name)
        if value is not None and _string(value):
            return _string(value)
    return ""


def _semantic_audit(parsed: Mapping[str, Any]) -> Mapping[str, Any]:
    audits = parsed.get("audits")
    semantic = parsed.get("semantic_audit")
    if isinstance(audits, Mapping) and isinstance(semantic, Mapping):
        return {"audits": audits, "semantic_audit": semantic}
    if isinstance(audits, Mapping):
        return audits
    if isinstance(semantic, Mapping):
        return semantic
    return {}


def _first_mapping(item: Mapping[str, Any], *field_names: str) -> Mapping[str, Any]:
    for field_name in field_names:
        value = item.get(field_name)
        if isinstance(value, Mapping):
            return value
    return {}


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if item is not None and str(item))
    return ()


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _string(value: Any) -> str:
    return "" if value is None else str(value)


def _optional_string(value: Any) -> str | None:
    return None if value is None else str(value)
