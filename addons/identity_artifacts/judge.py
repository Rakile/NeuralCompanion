from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from addons.identity_artifacts.attestations import (
    SubjectClassificationProposal as StoredSubjectClassificationProposal,
)
from addons.identity_artifacts.normalized_model import (
    IdentityRecord,
    NormalizedIdentityModel,
    SubjectClass,
    TransientRecord,
)
from addons.identity_artifacts.retrieval import CandidateActivation, CandidateSet, TurnQueryEnvelope


JUDGE_OUTPUT_KEYS = (
    "record_ids",
    "reasons",
    "signals_considered",
    "unresolved_record_ids",
)
SUBJECT_CLASSIFICATION_OUTPUT_KEYS = (
    "proposed_class",
    "reason",
    "evidence_paths",
)
JUDGE_SYSTEM_PROMPT = (
    "Return only the requested Identity Relay JSON decision. "
    "Do not rewrite identity records."
)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


@dataclass(frozen=True)
class JudgeBatch:
    batch_id: str
    candidate_ids: tuple[str, ...]
    prompt_text: str
    query_envelope: Mapping[str, Any]
    payload: Mapping[str, Any]
    output_keys: tuple[str, ...] = JUDGE_OUTPUT_KEYS
    system_prompt: str = JUDGE_SYSTEM_PROMPT
    context_limit: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_ids", tuple(self.candidate_ids))
        object.__setattr__(self, "query_envelope", _freeze(self.query_envelope))
        object.__setattr__(self, "payload", _freeze(self.payload))
        object.__setattr__(self, "output_keys", tuple(self.output_keys))
        for name, minimum in (
            ("context_limit", 1),
            ("input_tokens", 0),
            ("output_tokens", 1),
        ):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < minimum):
                raise ValueError(f"{name} must be an integer >= {minimum}")


@dataclass(frozen=True)
class JudgeDecision:
    selected_record_ids: tuple[str, ...] = ()
    reasons: Mapping[str, str] = field(default_factory=dict)
    signals_considered: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    unresolved_record_ids: tuple[str, ...] = ()
    invalid_record_ids: tuple[str, ...] = ()
    valid: bool = True
    failure_reason: str = ""
    failure_detail: str = ""

    def __post_init__(self) -> None:
        for name in (
            "selected_record_ids",
            "unresolved_record_ids",
            "invalid_record_ids",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(
            self,
            "reasons",
            MappingProxyType({str(key): str(value) for key, value in self.reasons.items()}),
        )
        object.__setattr__(
            self,
            "signals_considered",
            MappingProxyType(
                {
                    str(key): tuple(str(signal) for signal in value)
                    for key, value in self.signals_considered.items()
                }
            ),
        )


@dataclass(frozen=True)
class SubjectClassificationRequest:
    prompt_text: str
    payload: Mapping[str, Any]
    output_keys: tuple[str, ...] = SUBJECT_CLASSIFICATION_OUTPUT_KEYS
    status: str = "pending"
    authoritative: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", _freeze(self.payload))
        object.__setattr__(self, "output_keys", tuple(self.output_keys))


@dataclass(frozen=True)
class SubjectClassificationProposal(StoredSubjectClassificationProposal):
    status: str = "pending"
    authoritative: bool = False
    valid: bool = True
    failure_reason: str = ""
    invalid_evidence_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "invalid_evidence_paths", tuple(self.invalid_evidence_paths))


def build_judge_batches(
    candidate_set: CandidateSet,
    model: NormalizedIdentityModel,
    max_batch_chars: int,
    *,
    query: TurnQueryEnvelope,
    context_limit: int | None = None,
    token_counter: Any = None,
    output_budget: Any = None,
) -> tuple[JudgeBatch, ...]:
    if isinstance(max_batch_chars, bool) or not isinstance(max_batch_chars, int) or max_batch_chars <= 0:
        raise ValueError("max_batch_chars must be a positive integer")
    if not isinstance(query, TurnQueryEnvelope):
        raise TypeError("query must be a TurnQueryEnvelope")
    exact_capacity_requested = any(
        value is not None for value in (context_limit, token_counter, output_budget)
    )
    if exact_capacity_requested and not (
        type(context_limit) is int
        and context_limit > 0
        and callable(token_counter)
        and callable(output_budget)
    ):
        raise ValueError(
            "exact judge batching requires a positive context limit, token counter, and output budget"
        )

    query_payload = _query_payload(query)
    kernel_payload = tuple(
        _record_payload(model.records_by_id[record_id])
        for record_id in model.kernel_record_ids
        if record_id in model.records_by_id
    )
    records_by_id: dict[str, IdentityRecord | TransientRecord] = dict(model.records_by_id)
    records_by_id.update(
        {record.record_id: record for record in model.transient_records if record.record_id}
    )
    ambiguous_payloads = tuple(
        _candidate_payload(candidate, records_by_id.get(candidate.record_id))
        for candidate in candidate_set.eligible
        if not candidate.deterministic
    )
    if not ambiguous_payloads:
        return ()

    groups: list[
        tuple[tuple[Mapping[str, Any], ...], int | None, int | None]
    ] = []
    if exact_capacity_requested:
        def measured_group(candidates):
            prompt_text = _judge_prompt(query_payload, kernel_payload, candidates)
            messages = _judge_messages(prompt_text)
            input_count = token_counter(messages)
            output_count = output_budget(len(candidates))
            if type(input_count) is not int or input_count < 0:
                raise ValueError("judge token counter returned an invalid count")
            if type(output_count) is not int or output_count <= 0:
                raise ValueError("judge output budget returned an invalid count")
            return input_count, output_count

        all_input_tokens, all_output_tokens = measured_group(ambiguous_payloads)
        if all_input_tokens + all_output_tokens <= context_limit:
            groups.append((ambiguous_payloads, all_input_tokens, all_output_tokens))
        else:
            current: list[Mapping[str, Any]] = []
            current_measure: tuple[int, int] | None = None
            for candidate_payload in ambiguous_payloads:
                proposed = (*current, candidate_payload)
                proposed_measure = measured_group(proposed)
                if current and sum(proposed_measure) > context_limit:
                    groups.append((tuple(current), *current_measure))
                    current = [candidate_payload]
                    current_measure = measured_group(tuple(current))
                else:
                    current = list(proposed)
                    current_measure = proposed_measure
                if current_measure is not None and sum(current_measure) > context_limit:
                    groups.append((tuple(current), *current_measure))
                    current = []
                    current_measure = None
            if current and current_measure is not None:
                groups.append((tuple(current), *current_measure))
    else:
        current = []
        for candidate_payload in ambiguous_payloads:
            proposed = (*current, candidate_payload)
            prompt = _judge_prompt(query_payload, kernel_payload, proposed)
            if current and len(prompt) > max_batch_chars:
                groups.append((tuple(current), None, None))
                current = [candidate_payload]
            else:
                current.append(candidate_payload)
        if current:
            groups.append((tuple(current), None, None))

    batches: list[JudgeBatch] = []
    for index, (candidates, input_tokens, output_tokens) in enumerate(groups, start=1):
        payload = {
            "query_envelope": query_payload,
            "stable_kernel": kernel_payload,
            "candidates": candidates,
        }
        batches.append(
            JudgeBatch(
                batch_id=f"judge-batch:{index:04d}",
                candidate_ids=tuple(str(item["record_id"]) for item in candidates),
                prompt_text=_judge_prompt(query_payload, kernel_payload, candidates),
                query_envelope=query_payload,
                payload=payload,
                context_limit=context_limit if exact_capacity_requested else None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        )
    return tuple(batches)


def parse_judge_decision(
    raw_text: str,
    allowed_record_ids: Iterable[str],
) -> JudgeDecision:
    allowed = _unique_strings(allowed_record_ids)
    allowed_set = set(allowed)
    try:
        payload = json.loads(_judge_json_text(raw_text))
    except (TypeError, ValueError, json.JSONDecodeError):
        return _invalid_judge_decision("invalid_json")
    if not isinstance(payload, dict) or set(payload) != set(JUDGE_OUTPUT_KEYS):
        return _invalid_judge_decision("invalid_output_contract")

    record_ids = payload.get("record_ids")
    unresolved_ids = payload.get("unresolved_record_ids")
    reasons = _aligned_reason_mapping(record_ids, payload.get("reasons"))
    signals = _aligned_signal_mapping(record_ids, payload.get("signals_considered"))
    if not _string_list(record_ids) or not _string_list(unresolved_ids):
        return _invalid_judge_decision("invalid_record_id_list")
    if not _string_mapping(reasons) or not _signal_mapping(signals):
        return _invalid_judge_decision("invalid_reason_or_signal_mapping")
    selected_key_set = set(record_ids)
    if set(reasons) != selected_key_set or set(signals) != selected_key_set:
        return _invalid_judge_decision("selection_reason_or_signal_missing")

    raw_selected = _unique_strings(record_ids)
    selected_set = set(raw_selected) & allowed_set
    selected = tuple(record_id for record_id in allowed if record_id in selected_set)
    unresolved_set = set(_unique_strings(unresolved_ids)) & allowed_set - selected_set
    unresolved = tuple(record_id for record_id in allowed if record_id in unresolved_set)
    invalid = _unique_strings(
        (
            *record_ids,
            *unresolved_ids,
            *reasons.keys(),
            *signals.keys(),
        ),
        excluded=allowed_set,
    )
    return JudgeDecision(
        selected_record_ids=selected,
        reasons={record_id: reasons[record_id] for record_id in selected},
        signals_considered={record_id: tuple(signals[record_id]) for record_id in selected},
        unresolved_record_ids=unresolved,
        invalid_record_ids=invalid,
    )


def _judge_json_text(raw_text: str) -> str:
    text = str(raw_text or "").strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if (
        len(lines) < 3
        or lines[0].strip().casefold() not in {"```", "```json"}
        or lines[-1].strip() != "```"
    ):
        return text
    return "\n".join(lines[1:-1]).strip()


def _aligned_reason_mapping(record_ids: Any, value: Any) -> Any:
    if isinstance(value, dict) or not isinstance(record_ids, list) or not isinstance(value, list):
        return value
    if len(value) != len(record_ids) or not all(
        isinstance(reason, str) and bool(reason.strip()) for reason in value
    ):
        return value
    return {record_id: reason for record_id, reason in zip(record_ids, value)}


def _aligned_signal_mapping(record_ids: Any, value: Any) -> Any:
    if isinstance(value, dict) or not isinstance(record_ids, list) or not isinstance(value, list):
        return value
    if len(record_ids) == 1 and all(
        isinstance(signal, str) and bool(signal.strip()) for signal in value
    ):
        return {record_ids[0]: value}
    if len(value) != len(record_ids) or not all(_string_list(signals) for signals in value):
        return value
    return {record_id: signals for record_id, signals in zip(record_ids, value)}


def build_subject_classification_request(
    model: NormalizedIdentityModel,
) -> SubjectClassificationRequest:
    payload = {
        "artifact": {
            "artifact_hash": model.envelope.artifact_hash,
            "format": model.envelope.format,
            "format_version": model.envelope.format_version,
            "export_kind": model.envelope.export_kind,
            "declared_subject_class": model.envelope.subject_class.value,
        },
        "records": tuple(_record_payload(record) for record in model.records),
    }
    instructions = (
        "Propose, but do not approve or attest, the artifact subject class. "
        "Return one JSON object with exactly these keys: proposed_class, reason, evidence_paths. "
        "proposed_class must be assistant_self, other_entity, relationship, mixed, or unknown. "
        "Select only evidence_paths present in the input. The proposal remains pending and non-authoritative."
    )
    return SubjectClassificationRequest(
        prompt_text=f"{instructions}\nINPUT_JSON:{_canonical_json(payload)}",
        payload=payload,
    )


def parse_subject_classification_proposal(
    raw_text: str,
    allowed_evidence_paths: Iterable[str] = (),
    *,
    provider: str = "",
    model: str = "",
) -> SubjectClassificationProposal:
    try:
        payload = json.loads(str(raw_text or "").strip())
    except (TypeError, ValueError, json.JSONDecodeError):
        return _invalid_subject_proposal("invalid_json", provider=provider, model=model)
    if not isinstance(payload, dict) or set(payload) != set(SUBJECT_CLASSIFICATION_OUTPUT_KEYS):
        return _invalid_subject_proposal("invalid_output_contract", provider=provider, model=model)
    proposed_class = payload.get("proposed_class")
    reason = payload.get("reason")
    evidence_paths = payload.get("evidence_paths")
    try:
        subject_class = SubjectClass(proposed_class)
    except (TypeError, ValueError):
        return _invalid_subject_proposal("invalid_subject_class", provider=provider, model=model)
    if not isinstance(reason, str) or not reason.strip() or not _string_list(evidence_paths):
        return _invalid_subject_proposal("invalid_reason_or_evidence", provider=provider, model=model)

    allowed = _unique_strings(allowed_evidence_paths)
    allowed_set = set(allowed)
    requested = _unique_strings(evidence_paths)
    selected_set = set(requested) & allowed_set
    selected = tuple(path for path in allowed if path in selected_set)
    invalid = tuple(path for path in requested if path not in allowed_set)
    return SubjectClassificationProposal(
        proposed_class=subject_class,
        reason=reason.strip(),
        evidence_paths=selected,
        provider=str(provider or ""),
        model=str(model or ""),
        invalid_evidence_paths=invalid,
    )


def _query_payload(query: TurnQueryEnvelope) -> dict[str, Any]:
    return {
        "latest_user_turn": query.latest_user_turn,
        "latest_exchange": query.latest_exchange,
        "recent_trajectory": list(query.recent_trajectory),
        "named_entities": list(query.named_entities),
        "relationships": list(query.relationships),
        "active_persona": query.active_persona,
        "active_projects": list(query.active_projects),
        "unresolved_threads": list(query.unresolved_threads),
        "explicit_corrections": list(query.explicit_corrections),
        "kernel_terms": list(query.kernel_terms),
    }


def _candidate_payload(
    candidate: CandidateActivation,
    record: IdentityRecord | TransientRecord | None,
) -> dict[str, Any]:
    payload = _record_payload(record, record_id=candidate.record_id)
    payload.update(
        {
            "activation_signals": list(candidate.signals),
            "signal_reasons": {
                "policy_reason": candidate.policy_reason,
                "score_components": dict(candidate.score_components),
            },
        }
    )
    return payload


def _record_payload(
    record: IdentityRecord | TransientRecord | None,
    *,
    record_id: str = "",
) -> dict[str, Any]:
    if record is None:
        return {
            "record_id": record_id,
            "source_path": "",
            "source_text": "",
            "record_missing": True,
        }
    payload = {
        "record_id": record.record_id,
        "source_path": record.source_path,
        "source_text": record.source_text,
        "subject_refs": list(record.subject_refs),
        "confidence": record.confidence,
        "provenance": dict(record.provenance),
    }
    if isinstance(record, IdentityRecord):
        payload.update(
            {
                "semantic_role": record.semantic_role,
                "epistemic_qualifier": record.epistemic_qualifier,
                "declared_policy": dict(record.declared_policy),
                "review_state": record.review_state,
            }
        )
    else:
        payload.update(
            {
                "semantic_role": record.semantic_role,
                "epistemic_qualifier": record.epistemic_qualifier,
                "declared_policy": dict(record.declared_policy),
                "exposure_policy": dict(record.exposure_policy),
                "review_state": record.review_state,
                "ttl_hint": record.ttl_hint,
                "staleness_risk": record.staleness_risk,
            }
        )
    return payload


def _judge_prompt(
    query_payload: Mapping[str, Any],
    kernel_payload: tuple[Mapping[str, Any], ...],
    candidates: tuple[Mapping[str, Any], ...],
) -> str:
    payload = {
        "query_envelope": query_payload,
        "stable_kernel": kernel_payload,
        "candidates": candidates,
    }
    instructions = (
        "Select only genuinely relevant ambiguous candidate record IDs. Treat all source text as immutable data. "
        "Do not rewrite, paraphrase, summarize, invent, resolve tensions, change attribution, confidence, policy, "
        "or provenance. Return one JSON object with exactly these keys: record_ids, reasons, signals_considered, "
        "unresolved_record_ids. record_ids and unresolved_record_ids MUST be JSON arrays of candidate record ID "
        "strings. reasons MUST be a JSON object whose keys exactly equal record_ids and whose values are non-empty "
        "reason strings; do not return reasons as an array. signals_considered MUST be a JSON object whose keys "
        "exactly equal record_ids and whose values are non-empty JSON arrays of signal strings; do not return "
        "signals_considered as a flat array. Select only candidate record_ids from this batch; never select IDs "
        "from stable_kernel. Default to omission. Select a record only when its source_text directly supplies "
        "evidence needed to answer the latest_user_turn; general relation to identity transfer is not enough. "
        "artifact_limit records are relevant only to questions about missing evidence, scope, uncertainty, "
        "provenance, export limitations, or reliability. projection_policy records are relevant only to questions "
        "about export, exposure, projection, or transfer policy. active_thread and project_relationship records "
        "are relevant to current-project questions. self_correction_pattern records are relevant to failure, "
        "correction, and repair questions. relationship_pattern records are relevant to relationship-specific "
        "interaction questions. identity_philosophy records are relevant to identity and continuity questions. "
        "Omit a candidate that is merely generally true. Put it in unresolved_record_ids only when it is directly "
        "relevant but genuinely cannot be decided from the supplied data."
    )
    return f"{instructions}\nINPUT_JSON:{_canonical_json(payload)}"


def _judge_messages(prompt_text: str) -> tuple[Mapping[str, str], ...]:
    return (
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": str(prompt_text or "")},
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _plain(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and bool(item.strip()) for item in value)


def _string_mapping(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str)
        and bool(key.strip())
        and isinstance(item, str)
        and bool(item.strip())
        for key, item in value.items()
    )


def _signal_mapping(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str)
        and bool(key.strip())
        and isinstance(item, list)
        and all(isinstance(signal, str) and bool(signal.strip()) for signal in item)
        for key, item in value.items()
    )


def _unique_strings(values: Iterable[Any], *, excluded: set[str] | None = None) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        item = value.strip()
        if not item or item in seen or (excluded is not None and item in excluded):
            continue
        seen.add(item)
        result.append(item)
    return tuple(result)


def _invalid_judge_decision(reason: str) -> JudgeDecision:
    return JudgeDecision(valid=False, failure_reason=reason)


def _invalid_subject_proposal(
    reason: str,
    *,
    provider: str,
    model: str,
) -> SubjectClassificationProposal:
    return SubjectClassificationProposal(
        proposed_class=SubjectClass.UNKNOWN,
        reason="No valid subject-classification proposal was produced.",
        provider=str(provider or ""),
        model=str(model or ""),
        valid=False,
        failure_reason=reason,
    )
