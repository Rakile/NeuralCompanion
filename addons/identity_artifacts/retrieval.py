from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from addons.identity_artifacts.attestations import TransientActivationState
from addons.identity_artifacts.normalized_model import (
    IdentityRecord,
    NormalizedIdentityModel,
    RuntimeLayer,
    TransientRecord,
)
from addons.identity_artifacts.policy import EffectiveUseDecision
from addons.identity_artifacts.retrieval_index import (
    DEFAULT_SEMANTIC_THRESHOLD,
    SEMANTIC_THRESHOLD_REVISION,
    SemanticHit,
    SemanticSearchResult,
)


_SIGNAL_ORDER = (
    "entity_relationship",
    "topic",
    "project_thread",
    "tag_hint",
    "category_rule",
    "temporal_continuity",
    "contradiction_correction",
    "semantic_fallback",
)
_SIGNAL_WEIGHTS = MappingProxyType(
    {
        "entity_relationship": 3.0,
        "topic": 1.0,
        "project_thread": 2.5,
        "tag_hint": 2.0,
        "category_rule": 1.5,
        "temporal_continuity": 1.25,
        "contradiction_correction": 3.0,
    }
)
_DETERMINISTIC_SIGNALS = frozenset(
    {
        "entity_relationship",
        "project_thread",
        "contradiction_correction",
    }
)
_WORD_RE = re.compile(r"[a-z0-9]+")
_STOP_WORDS = frozenset(
    {
        "about",
        "after",
        "again",
        "also",
        "and",
        "are",
        "before",
        "but",
        "for",
        "from",
        "has",
        "have",
        "into",
        "its",
        "our",
        "that",
        "the",
        "their",
        "then",
        "this",
        "was",
        "were",
        "what",
        "when",
        "with",
    }
)


@dataclass(frozen=True)
class TurnQueryEnvelope:
    latest_user_turn: str
    latest_exchange: str = ""
    recent_trajectory: tuple[str, ...] = ()
    named_entities: tuple[str, ...] = ()
    relationships: tuple[str, ...] = ()
    active_persona: str = ""
    active_projects: tuple[str, ...] = ()
    unresolved_threads: tuple[str, ...] = ()
    explicit_corrections: tuple[str, ...] = ()
    kernel_terms: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "latest_user_turn", self.latest_user_turn.strip())
        object.__setattr__(self, "latest_exchange", self.latest_exchange.strip())
        object.__setattr__(self, "active_persona", self.active_persona.strip())
        for name in (
            "recent_trajectory",
            "named_entities",
            "relationships",
            "active_projects",
            "unresolved_threads",
            "explicit_corrections",
            "kernel_terms",
        ):
            object.__setattr__(self, name, _clean_values(getattr(self, name)))


@dataclass(frozen=True)
class CandidateActivation:
    record_id: str
    signals: tuple[str, ...]
    deterministic: bool
    score_components: Mapping[str, float]
    policy_reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "signals", tuple(self.signals))
        object.__setattr__(
            self,
            "score_components",
            MappingProxyType(
                {
                    str(name): float(value)
                    for name, value in sorted(self.score_components.items())
                }
            ),
        )


@dataclass(frozen=True)
class CandidateSet:
    eligible: tuple[CandidateActivation, ...]
    denied_record_ids: tuple[str, ...]
    semantic_available: bool
    semantic_reason: str
    semantic_threshold: float = DEFAULT_SEMANTIC_THRESHOLD
    semantic_threshold_revision: str = SEMANTIC_THRESHOLD_REVISION
    denial_reasons: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "eligible", tuple(self.eligible))
        object.__setattr__(self, "denied_record_ids", tuple(self.denied_record_ids))
        object.__setattr__(
            self,
            "denial_reasons",
            MappingProxyType(
                {
                    str(record_id): str(reason)
                    for record_id, reason in sorted(self.denial_reasons.items())
                }
            ),
        )


def build_turn_query_envelope(
    latest_user_turn: str,
    *,
    latest_exchange: str = "",
    recent_trajectory: Iterable[str] = (),
    named_entities: Iterable[str] = (),
    relationships: Iterable[str] = (),
    active_persona: str = "",
    active_projects: Iterable[str] = (),
    unresolved_threads: Iterable[str] = (),
    explicit_corrections: Iterable[str] = (),
    kernel_terms: Iterable[str] = (),
) -> TurnQueryEnvelope:
    return TurnQueryEnvelope(
        latest_user_turn=str(latest_user_turn or ""),
        latest_exchange=str(latest_exchange or ""),
        recent_trajectory=tuple(recent_trajectory),
        named_entities=tuple(named_entities),
        relationships=tuple(relationships),
        active_persona=str(active_persona or ""),
        active_projects=tuple(active_projects),
        unresolved_threads=tuple(unresolved_threads),
        explicit_corrections=tuple(explicit_corrections),
        kernel_terms=tuple(kernel_terms),
    )


def generate_identity_candidates(
    model: NormalizedIdentityModel,
    query: TurnQueryEnvelope,
    policy_decisions: Mapping[str, EffectiveUseDecision],
    semantic_hits: Sequence[SemanticHit] | SemanticSearchResult = (),
    *,
    transient_states: Mapping[str, TransientActivationState] | None = None,
) -> CandidateSet:
    (
        hits_by_id,
        semantic_available,
        semantic_reason,
        semantic_threshold,
        semantic_threshold_revision,
    ) = _semantic_state(semantic_hits)
    quarantined_ids = {
        record_id
        for item in model.quarantine
        for record_id in item.record_ids
    }
    denial_reasons: dict[str, str] = {}
    candidate_sources: list[tuple[IdentityRecord | TransientRecord, str]] = []

    seen_ids: set[str] = set()
    for record_id in model.retrievable_record_ids:
        if record_id in seen_ids:
            continue
        seen_ids.add(record_id)
        record = model.records_by_id.get(record_id)
        decision = policy_decisions.get(record_id)
        if record_id in quarantined_ids:
            denial_reasons[record_id] = "quarantined"
            continue
        if record is None:
            denial_reasons[record_id] = "retrievable_record_missing"
            continue
        if decision is None:
            denial_reasons[record_id] = "authorization_required"
            continue
        if not decision.allowed:
            denial_reasons[record_id] = decision.reason_code
            continue
        candidate_sources.append((record, decision.reason_code))

    for transient in model.transient_records:
        record_id = transient.record_id
        if not record_id or record_id in seen_ids:
            continue
        seen_ids.add(record_id)
        if transient.runtime_layer == RuntimeLayer.PROVENANCE:
            denial_reasons[record_id] = "provenance_only"
            continue
        if record_id in quarantined_ids:
            denial_reasons[record_id] = "quarantined"
            continue
        decision = policy_decisions.get(record_id)
        if decision is None:
            denial_reasons[record_id] = "authorization_required"
            continue
        if not decision.allowed:
            denial_reasons[record_id] = decision.reason_code
            continue
        state = transient_states.get(record_id) if transient_states is not None else None
        if state is None:
            denial_reasons[record_id] = "transient_activation_required"
            continue
        if not state.active or state.review_required:
            denial_reasons[record_id] = state.reason_code
            continue
        candidate_sources.append((transient, decision.reason_code))

    tension_record_ids = {
        record_id for tension in model.tensions for record_id in tension.record_ids
    }
    activations = tuple(
        _activation_for(
            record,
            policy_reason,
            query,
            tension_record_ids,
            hits_by_id.get(record.record_id),
        )
        for record, policy_reason in candidate_sources
    )
    ordered = tuple(
        sorted(
            activations,
            key=lambda item: (
                not item.deterministic,
                -sum(item.score_components.values()),
                item.record_id,
            ),
        )
    )
    return CandidateSet(
        eligible=ordered,
        denied_record_ids=tuple(sorted(denial_reasons)),
        semantic_available=semantic_available,
        semantic_reason=semantic_reason,
        semantic_threshold=semantic_threshold,
        semantic_threshold_revision=semantic_threshold_revision,
        denial_reasons=denial_reasons,
    )


def _activation_for(
    record: IdentityRecord | TransientRecord,
    policy_reason: str,
    query: TurnQueryEnvelope,
    tension_record_ids: set[str],
    semantic_score: float | None,
) -> CandidateActivation:
    source_text = record.source_text
    subject_refs = tuple(record.subject_refs)
    semantic_role = getattr(record, "semantic_role", "transient_continuity")
    tags = tuple(getattr(record, "tags", ()))
    retrieval_hints = tuple(getattr(record, "retrieval_hints", ()))
    durability = getattr(record, "durability", "transient")
    searchable = " ".join((source_text, *subject_refs, *tags, *retrieval_hints))
    query_text = " ".join(
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
    signals: set[str] = set()

    if _matches_any(searchable, (*query.named_entities, *query.relationships)):
        signals.add("entity_relationship")

    topic_query = " ".join(
        (query.latest_user_turn, query.latest_exchange, *query.recent_trajectory)
    )
    if _tokens(searchable) & _tokens(topic_query):
        signals.add("topic")

    if _matches_any(searchable, (*query.active_projects, *query.unresolved_threads)):
        signals.add("project_thread")

    if tags or retrieval_hints:
        if _matches_any(query_text, (*tags, *retrieval_hints)):
            signals.add("tag_hint")

    role = semantic_role.casefold()
    if _category_rule_applies(role, query):
        signals.add("category_rule")

    temporal_terms = ("episode", "history", "temporal", "timeline", "session", "transient")
    temporal_marker = " ".join((role, durability.casefold(), *tags, *retrieval_hints))
    if (
        (query.latest_exchange or query.recent_trajectory)
        and any(term in temporal_marker for term in temporal_terms)
    ):
        signals.add("temporal_continuity")

    correction_requested = bool(query.explicit_corrections) or bool(
        _tokens(query.latest_user_turn)
        & {"correct", "corrected", "correction", "contradiction", "wrong"}
    )
    correction_record = record.record_id in tension_record_ids or any(
        term in role for term in ("correct", "contradiction", "tension")
    )
    if correction_requested and correction_record:
        signals.add("contradiction_correction")

    if semantic_score is not None:
        signals.add("semantic_fallback")

    ordered_signals = tuple(signal for signal in _SIGNAL_ORDER if signal in signals)
    score_components = {
        signal: (
            float(semantic_score)
            if signal == "semantic_fallback" and semantic_score is not None
            else _SIGNAL_WEIGHTS[signal]
        )
        for signal in ordered_signals
    }
    deterministic = any(
        signal in _DETERMINISTIC_SIGNALS for signal in ordered_signals
    )
    return CandidateActivation(
        record_id=record.record_id,
        signals=ordered_signals,
        deterministic=deterministic,
        score_components=score_components,
        policy_reason=policy_reason,
    )


def _semantic_state(
    semantic_hits: Sequence[SemanticHit] | SemanticSearchResult,
) -> tuple[dict[str, float], bool, str, float, str]:
    if isinstance(semantic_hits, SemanticSearchResult):
        available = semantic_hits.semantic_available
        reason = semantic_hits.reason
        threshold = semantic_hits.semantic_threshold
        threshold_revision = semantic_hits.semantic_threshold_revision
        hits = semantic_hits.hits if available else ()
    else:
        available = True
        reason = "available"
        threshold = DEFAULT_SEMANTIC_THRESHOLD
        threshold_revision = SEMANTIC_THRESHOLD_REVISION
        hits = semantic_hits
    by_id: dict[str, float] = {}
    for hit in hits:
        score = float(hit.score)
        if not math.isfinite(score):
            continue
        previous = by_id.get(hit.record_id)
        if previous is None or score > previous:
            by_id[hit.record_id] = score
    return by_id, available, reason, threshold, threshold_revision


def _category_rule_applies(role: str, query: TurnQueryEnvelope) -> bool:
    if any(term in role for term in ("boundary", "principle", "value", "non_invention")):
        return bool(query.kernel_terms)
    if "relationship" in role:
        return bool(query.relationships or query.named_entities)
    if any(term in role for term in ("project", "thread")):
        return bool(query.active_projects or query.unresolved_threads)
    if any(term in role for term in ("correct", "contradiction", "tension")):
        return bool(query.explicit_corrections)
    if any(term in role for term in ("episode", "history", "temporal", "timeline")):
        return bool(query.latest_exchange or query.recent_trajectory)
    if "transient" in role:
        return bool(query.latest_user_turn or query.recent_trajectory)
    return False


def _matches_any(text: str, values: Iterable[str]) -> bool:
    folded = text.casefold()
    return any(value.casefold() in folded for value in values if value.strip())


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in _WORD_RE.findall(value.casefold())
        if len(token) >= 3 and token not in _STOP_WORDS
    }


def _clean_values(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return tuple(result)
