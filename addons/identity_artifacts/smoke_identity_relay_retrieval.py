from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from addons.identity_artifacts.attestations import (
    TransientActivation,
    evaluate_transient_activation,
)
from addons.identity_artifacts.normalized_model import (
    ArtifactEnvelope,
    IdentityRecord,
    LinkedTension,
    NormalizedIdentityModel,
    QuarantineItem,
    QuarantineReason,
    RuntimeLayer,
    TransientRecord,
)
from addons.identity_artifacts.policy import EffectiveUseDecision
from addons.identity_artifacts.retrieval import (
    TurnQueryEnvelope,
    build_turn_query_envelope,
    generate_identity_candidates,
)
from addons.identity_artifacts.retrieval_index import (
    DEFAULT_SEMANTIC_THRESHOLD,
    IDENTITY_INDEX_REVISION,
    IDENTITY_INDEX_SCHEMA_VERSION,
    SEMANTIC_THRESHOLD_REVISION,
    IdentitySemanticIndex,
    SemanticHit,
    SemanticIndexMetadata,
    SemanticSearchResult,
    build_identity_semantic_index,
)


ARTIFACT_HASH = "a" * 64


def _record(
    record_id: str,
    text: str,
    *,
    semantic_role: str = "context",
    subject_refs: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
    retrieval_hints: tuple[str, ...] = (),
    durability: str = "durable",
    stability: str = "stable",
) -> IdentityRecord:
    return IdentityRecord(
        record_id=record_id,
        source_path=f"$.records.{record_id}",
        source_text=text,
        semantic_role=semantic_role,
        subject_refs=subject_refs,
        stability=stability,
        confidence=0.8,
        epistemic_qualifier="reported",
        runtime_layer=RuntimeLayer.RETRIEVABLE,
        durability=durability,
        stale_after=None,
        tags=tags,
        retrieval_hints=retrieval_hints,
        declared_policy={},
        exposure_policy={},
        privacy_class="private",
        runtime_suitability=("contextual_retrieval",),
        review_state="approved",
        wording_provenance={},
        provenance={},
    )


def _model(
    records: tuple[IdentityRecord, ...],
    *,
    retrievable_ids: tuple[str, ...] | None = None,
    transient_records: tuple[TransientRecord, ...] = (),
    quarantine: tuple[QuarantineItem, ...] = (),
    tensions: tuple[LinkedTension, ...] = (),
) -> NormalizedIdentityModel:
    return NormalizedIdentityModel(
        schema_version=1,
        normalizer_revision="identity-relay-v0.1.0",
        envelope=ArtifactEnvelope(
            artifact_hash=ARTIFACT_HASH,
            format="NC_IDENTITY_EXPORT",
            format_version="1.1",
            export_kind="assistant_identity",
        ),
        records=records,
        kernel_record_ids=(),
        retrievable_record_ids=(
            retrievable_ids
            if retrievable_ids is not None
            else tuple(record.record_id for record in records)
        ),
        transient_records=transient_records,
        tensions=tensions,
        review_queue=(),
        quarantine=quarantine,
        unknown_fields={},
    )


def _allowed(reason: str = "allowed") -> EffectiveUseDecision:
    return EffectiveUseDecision(True, ("contextual_retrieval",), reason, reason)


def _denied(reason: str) -> EffectiveUseDecision:
    return EffectiveUseDecision(False, (), reason, reason)


def _allow_all(model: NormalizedIdentityModel) -> dict[str, EffectiveUseDecision]:
    return {record_id: _allowed() for record_id in model.retrievable_record_ids}


def _metadata(**changes: object) -> SemanticIndexMetadata:
    metadata = SemanticIndexMetadata(
        artifact_hash=ARTIFACT_HASH,
        normalizer_revision="identity-relay-v0.1.0",
        normalized_schema_version=1,
        index_schema_version=IDENTITY_INDEX_SCHEMA_VERSION,
        index_revision=IDENTITY_INDEX_REVISION,
        embedding_provider="fake-provider",
        endpoint_identity="local://fake-embeddings",
        embedding_model="fake-embedding-v1",
        embedding_context=2048,
        vector_dimension=3,
        text_hashes={},
        semantic_threshold=DEFAULT_SEMANTIC_THRESHOLD,
        semantic_threshold_revision=SEMANTIC_THRESHOLD_REVISION,
    )
    return replace(metadata, **changes)


def _query() -> TurnQueryEnvelope:
    return TurnQueryEnvelope(
        latest_user_turn="Jesper corrected the Identity Relay launch plan today",
        latest_exchange="We discussed the launch timeline yesterday",
        recent_trajectory=("Identity Relay launch",),
        named_entities=("Jesper",),
        relationships=("collaborator:Jesper",),
        active_persona="Echo",
        active_projects=("Identity Relay",),
        unresolved_threads=("launch plan",),
        explicit_corrections=("launch date corrected",),
        kernel_terms=("non-invention",),
    )


class FakeEmbeddingAdapter:
    def __init__(self, *, fail: bool = False, cancel_token: "CancelToken | None" = None):
        self.fail = fail
        self.cancel_token = cancel_token
        self.calls: list[tuple[str, ...]] = []

    def embed(
        self, texts: tuple[str, ...], *, model: str, context: int
    ) -> tuple[tuple[float, ...], ...]:
        assert model == "fake-embedding-v1"
        assert context == 2048
        self.calls.append(tuple(texts))
        if self.fail:
            raise RuntimeError("provider unavailable")
        if self.cancel_token is not None:
            self.cancel_token.cancel()
        return tuple((1.0, 1.0, 0.5) for _text in texts)


class CancelToken:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def is_cancelled(self) -> bool:
        return self.cancelled


def test_turn_query_envelope_preserves_all_signal_inputs() -> None:
    query = build_turn_query_envelope(
        latest_user_turn="  final turn  ",
        latest_exchange="exchange",
        recent_trajectory=["project arc"],
        named_entities=["Jesper"],
        relationships=["collaborator:Jesper"],
        active_persona="Echo",
        active_projects=["Identity Relay"],
        unresolved_threads=["launch plan"],
        explicit_corrections=["corrected date"],
        kernel_terms=["non-invention"],
    )
    assert query.latest_user_turn == "final turn"
    assert query.recent_trajectory == ("project arc",)
    assert query.named_entities == ("Jesper",)
    assert query.relationships == ("collaborator:Jesper",)
    assert query.active_projects == ("Identity Relay",)
    assert query.unresolved_threads == ("launch plan",)
    assert query.explicit_corrections == ("corrected date",)
    assert query.kernel_terms == ("non-invention",)


def test_source_runtime_provenance_never_becomes_a_retrieval_candidate() -> None:
    provenance = replace(
        _record(
            "source-runtime",
            "I am ExporterModel, the runtime that produced this artifact.",
            semantic_role="source_runtime_provenance",
        ),
        runtime_layer=RuntimeLayer.PROVENANCE,
    )
    transient = TransientRecord(
        record_id="transient:source-runtime",
        source_text="This ExporterModel artifact is a temporary test sample.",
        subject_refs=("assistant_self",),
        runtime_layer=RuntimeLayer.PROVENANCE,
    )
    model = _model((provenance,), retrievable_ids=(), transient_records=(transient,))
    transient_state = evaluate_transient_activation(
        transient=transient,
        saved_activation=TransientActivation(record_id=transient.record_id, active=True),
        now=200,
    )

    candidates = generate_identity_candidates(
        model,
        build_turn_query_envelope(
            "Which model produced this identity?",
            named_entities=("ExporterModel",),
        ),
        {transient.record_id: _allowed()},
        transient_states={transient.record_id: transient_state},
    )

    assert candidates.eligible == ()
    assert candidates.denied_record_ids == (transient.record_id,)
    assert candidates.denial_reasons[transient.record_id] == "provenance_only"


def test_all_activation_signals_are_visible_and_candidates_are_uncapped() -> None:
    records = (
        _record("entity", "Jesper is a trusted collaborator", subject_refs=("Jesper",)),
        _record("topic", "The launch plan remains unresolved"),
        _record("project", "Identity Relay launch checklist", semantic_role="project"),
        _record("tag", "Release details", tags=("launch plan",)),
        _record("category", "Do not invent missing facts", semantic_role="boundary"),
        _record("temporal", "Yesterday the timeline changed", semantic_role="episode"),
        _record("correction", "The launch date was corrected", semantic_role="correction"),
        _record("semantic", "A subtle continuity clue"),
    ) + tuple(_record(f"uncapped-{index:03d}", f"Unrelated detail {index}") for index in range(40))
    model = _model(
        records,
        tensions=(
            LinkedTension(
                tension_id="launch-tension",
                record_ids=("correction", "topic"),
                state="corrected",
            ),
        ),
    )
    semantic = SemanticSearchResult(
        hits=(SemanticHit("semantic", 0.91),),
        semantic_available=True,
        reason="available",
        rebuild_required=False,
        semantic_threshold=DEFAULT_SEMANTIC_THRESHOLD,
        semantic_threshold_revision=SEMANTIC_THRESHOLD_REVISION,
    )

    result = generate_identity_candidates(model, _query(), _allow_all(model), semantic)

    assert len(result.eligible) == len(model.retrievable_record_ids)
    assert {signal for item in result.eligible for signal in item.signals} >= {
        "entity_relationship",
        "topic",
        "project_thread",
        "tag_hint",
        "category_rule",
        "temporal_continuity",
        "contradiction_correction",
        "semantic_fallback",
    }
    assert result.semantic_threshold == DEFAULT_SEMANTIC_THRESHOLD
    assert result.semantic_threshold_revision == SEMANTIC_THRESHOLD_REVISION


def test_authorization_transient_and_quarantine_prefilter_before_scoring() -> None:
    records = (
        _record("allowed", "Identity Relay launch plan"),
        _record("policy-denied", "Identity Relay launch plan"),
        _record("quarantined", "Identity Relay launch plan"),
    )
    transients = (
        TransientRecord(record_id="transient-active", source_text="launch today"),
        TransientRecord(record_id="transient-policy-denied", source_text="launch today"),
        TransientRecord(record_id="transient-inactive", source_text="launch today"),
        TransientRecord(
            record_id="transient-expired", source_text="launch today", ttl_seconds=10
        ),
        TransientRecord(
            record_id="transient-session-mismatch",
            source_text="launch today",
            ttl_hint="session",
        ),
        TransientRecord(
            record_id="transient-review-required",
            source_text="launch today",
            ttl_hint="until the project ends",
        ),
        TransientRecord(record_id="transient-missing-state", source_text="launch today"),
    )
    model = _model(
        records,
        transient_records=transients,
        quarantine=(
            QuarantineItem(
                quarantine_id="q1",
                reason=QuarantineReason.POLICY,
                record_ids=("quarantined",),
            ),
        ),
    )
    decisions = {
        "allowed": _allowed(),
        "policy-denied": _denied("remote_provider_not_permitted"),
        "quarantined": _allowed(),
        "transient-active": _allowed(),
        "transient-policy-denied": _denied("remote_provider_not_permitted"),
        "transient-inactive": _allowed(),
        "transient-expired": _allowed(),
        "transient-session-mismatch": _allowed(),
        "transient-review-required": _allowed(),
        "transient-missing-state": _allowed(),
    }
    transient_states = {
        "transient-active": evaluate_transient_activation(
            transient=transients[0],
            saved_activation=TransientActivation(record_id=transients[0].record_id, active=True),
            now=200,
        ),
        "transient-policy-denied": evaluate_transient_activation(
            transient=transients[1],
            saved_activation=TransientActivation(record_id=transients[1].record_id, active=True),
            now=200,
        ),
        "transient-inactive": evaluate_transient_activation(
            transient=transients[2],
            saved_activation=TransientActivation(record_id=transients[2].record_id, active=False),
            now=200,
        ),
        "transient-expired": evaluate_transient_activation(
            transient=transients[3],
            saved_activation=TransientActivation(
                record_id=transients[3].record_id, active=True, activated_at=100
            ),
            now=111,
        ),
        "transient-session-mismatch": evaluate_transient_activation(
            transient=transients[4],
            saved_activation=TransientActivation(
                record_id=transients[4].record_id,
                active=True,
                session_token="session-a",
            ),
            now=200,
            current_session_token="session-b",
        ),
        "transient-review-required": evaluate_transient_activation(
            transient=transients[5],
            saved_activation=TransientActivation(record_id=transients[5].record_id, active=True),
            now=200,
        ),
    }

    result = generate_identity_candidates(
        model, _query(), decisions, transient_states=transient_states
    )

    assert {item.record_id for item in result.eligible} == {"allowed", "transient-active"}
    assert set(result.denied_record_ids) == {
        "policy-denied",
        "transient-policy-denied",
        "quarantined",
        "transient-inactive",
        "transient-expired",
        "transient-session-mismatch",
        "transient-review-required",
        "transient-missing-state",
    }
    assert result.denial_reasons["policy-denied"] == "remote_provider_not_permitted"
    assert result.denial_reasons["transient-policy-denied"] == (
        "remote_provider_not_permitted"
    )
    assert result.denial_reasons["quarantined"] == "quarantined"
    assert result.denial_reasons["transient-inactive"] == "inactive"
    assert result.denial_reasons["transient-expired"] == "expired"
    assert result.denial_reasons["transient-session-mismatch"] == "session_mismatch"
    assert result.denial_reasons["transient-review-required"] == "ambiguous_expiration"
    assert result.denial_reasons["transient-missing-state"] == "transient_activation_required"
    assert next(
        item for item in result.eligible if item.record_id == "transient-active"
    ).policy_reason == "allowed"
    assert all(item.record_id != "quarantined" for item in result.eligible)


def test_clear_matches_and_candidate_order_are_deterministic() -> None:
    model = _model(
        (
            _record("z-clear", "Identity Relay launch plan Jesper"),
            _record("a-clear", "Identity Relay launch plan Jesper"),
            _record("semantic-only", "Different wording"),
        )
    )
    semantic = (SemanticHit("semantic-only", 0.9),)

    first = generate_identity_candidates(model, _query(), _allow_all(model), semantic)
    second = generate_identity_candidates(model, _query(), _allow_all(model), semantic)

    assert first == second
    assert tuple(item.record_id for item in first.eligible) == (
        "a-clear",
        "z-clear",
        "semantic-only",
    )
    by_id = {item.record_id: item for item in first.eligible}
    assert by_id["a-clear"].deterministic is True
    assert by_id["semantic-only"].deterministic is False
    assert by_id["semantic-only"].signals == ("semantic_fallback",)


def test_weak_lexical_tag_and_temporal_signals_require_judge_review() -> None:
    model = _model(
        (
            _record("topic-only", "Identity continuity details"),
            _record(
                "tag-only",
                "Different wording",
                tags=("identity continuity",),
            ),
            _record(
                "temporal-only",
                "A separate chronology",
                semantic_role="episode",
            ),
        )
    )
    query = TurnQueryEnvelope(
        latest_user_turn="Explain identity continuity",
        latest_exchange="The conversation is still active",
    )

    result = generate_identity_candidates(model, query, _allow_all(model))
    by_id = {item.record_id: item for item in result.eligible}

    assert "topic" in by_id["topic-only"].signals
    assert by_id["topic-only"].deterministic is False
    assert "tag_hint" in by_id["tag-only"].signals
    assert by_id["tag-only"].deterministic is False
    assert "temporal_continuity" in by_id["temporal-only"].signals
    assert by_id["temporal-only"].deterministic is False


def test_deterministic_signals_sort_ahead_of_equal_semantic_fallback() -> None:
    model = _model(
        (
            _record("z-deterministic", "needle"),
            _record("a-semantic", "different wording"),
        )
    )
    query = TurnQueryEnvelope(
        latest_user_turn="needle",
        active_projects=("needle",),
    )

    result = generate_identity_candidates(
        model,
        query,
        _allow_all(model),
        (SemanticHit("a-semantic", 1.0),),
    )

    assert tuple(item.record_id for item in result.eligible) == (
        "z-deterministic",
        "a-semantic",
    )
    assert result.eligible[0].deterministic is True
    assert result.eligible[1].signals == ("semantic_fallback",)


def test_semantic_metadata_mismatch_disables_only_semantic_fallback_visibly() -> None:
    model = _model(
        (
            _record("deterministic", "Jesper launch plan"),
            _record("semantic-only", "Different wording"),
        )
    )
    unavailable = SemanticSearchResult(
        hits=(),
        semantic_available=False,
        reason="embedding_model_mismatch",
        rebuild_required=True,
        semantic_threshold=0.8,
        semantic_threshold_revision=SEMANTIC_THRESHOLD_REVISION,
    )

    result = generate_identity_candidates(model, _query(), _allow_all(model), unavailable)

    assert result.semantic_available is False
    assert result.semantic_reason == "embedding_model_mismatch"
    assert len(result.eligible) == 2
    assert next(item for item in result.eligible if item.record_id == "deterministic").deterministic
    assert next(item for item in result.eligible if item.record_id == "semantic-only").signals == ()


def test_index_search_is_uncapped_and_dimension_errors_are_visible() -> None:
    with TemporaryDirectory() as temporary:
        index = IdentitySemanticIndex(Path(temporary))
        records = tuple(_record(f"record-{value:03d}", f"Record {value}") for value in range(35))
        model = _model(records)
        build = build_identity_semantic_index(
            model,
            FakeEmbeddingAdapter(),
            _metadata(),
            policy_decisions=_allow_all(model),
            cancel_token=CancelToken(),
        )
        assert build.status == "complete"
        assert index.replace(build).published is True

        authorized_ids = set(model.retrievable_record_ids)
        search = index.search(
            ARTIFACT_HASH,
            (1.0, 1.0, 0.5),
            expected_metadata=build.metadata,
            authorized_record_ids=authorized_ids,
        )
        assert search.semantic_available is True
        assert len(search.hits) == 35
        assert tuple(search.hits) == tuple(
            sorted(search.hits, key=lambda hit: (-hit.score, hit.record_id))
        )

        wrong_dimension = index.search(
            ARTIFACT_HASH,
            (1.0, 1.0),
            expected_metadata=build.metadata,
            authorized_record_ids=authorized_ids,
        )
        assert wrong_dimension.semantic_available is False
        assert wrong_dimension.reason == "query_vector_dimension_mismatch"
        assert wrong_dimension.hits == ()


def test_search_authorization_expansion_rebuilds_and_narrowing_stays_available() -> None:
    with TemporaryDirectory() as temporary:
        index = IdentitySemanticIndex(Path(temporary))
        model = _model(
            (
                _record("currently-allowed", "Jesper launch plan"),
                _record("now-denied", "Jesper launch plan"),
            )
        )
        build_decisions = {
            "currently-allowed": _allowed(),
            "now-denied": _denied("remote_provider_not_permitted"),
        }
        narrow_build = build_identity_semantic_index(
            model,
            FakeEmbeddingAdapter(),
            _metadata(),
            policy_decisions=build_decisions,
            cancel_token=CancelToken(),
        )
        assert narrow_build.metadata.authorized_record_ids == ("currently-allowed",)
        assert index.replace(narrow_build).published is True

        missing = index.search(
            ARTIFACT_HASH,
            (1.0, 1.0, 0.5),
            expected_metadata=narrow_build.metadata,
        )
        assert missing.semantic_available is False
        assert missing.reason == "authorization_required"
        assert missing.hits == ()

        expanded = index.search(
            ARTIFACT_HASH,
            (1.0, 1.0, 0.5),
            expected_metadata=narrow_build.metadata,
            authorized_record_ids={"currently-allowed", "now-denied"},
        )
        assert expanded.semantic_available is False
        assert expanded.rebuild_required is True
        assert expanded.reason == "authorization_scope_expanded"
        assert expanded.hits == ()

        decisions = {"currently-allowed": _allowed()}
        candidates = generate_identity_candidates(model, _query(), decisions, missing)
        assert candidates.semantic_available is False
        assert candidates.semantic_reason == "authorization_required"
        assert tuple(item.record_id for item in candidates.eligible) == ("currently-allowed",)
        assert candidates.eligible[0].deterministic is True

        broad_build = build_identity_semantic_index(
            model,
            FakeEmbeddingAdapter(),
            _metadata(),
            policy_decisions=_allow_all(model),
            cancel_token=CancelToken(),
        )
        assert broad_build.metadata.authorized_record_ids == (
            "currently-allowed",
            "now-denied",
        )
        assert index.replace(broad_build).published is True
        narrowed = index.search(
            ARTIFACT_HASH,
            (1.0, 1.0, 0.5),
            expected_metadata=broad_build.metadata,
            authorized_record_ids={"currently-allowed"},
        )
        assert narrowed.semantic_available is True
        assert narrowed.rebuild_required is False
        assert tuple(hit.record_id for hit in narrowed.hits) == ("currently-allowed",)


def test_persisted_entries_round_trip_exact_deterministic_activation_fields() -> None:
    with TemporaryDirectory() as temporary:
        index = IdentitySemanticIndex(Path(temporary))
        record = _record(
            "audit-record",
            "Exact source wording",
            semantic_role="relationship_episode",
            subject_refs=("assistant:self", "person:Jesper"),
            tags=("Tag With Case", "launch-plan"),
            retrieval_hints=("Use exact hint", "Jesper"),
            durability="contextual-session",
        )
        model = _model((record,))
        build = build_identity_semantic_index(
            model,
            FakeEmbeddingAdapter(),
            _metadata(),
            policy_decisions=_allow_all(model),
            cancel_token=CancelToken(),
        )
        assert index.replace(build).published is True

        read = index.read(ARTIFACT_HASH, expected_metadata=build.metadata)
        assert read.semantic_available is True
        assert read.snapshot is not None
        entry = read.snapshot.entries[0]
        assert entry.record_id == record.record_id
        assert entry.source_path == record.source_path
        assert entry.semantic_role == record.semantic_role
        assert entry.subject_refs == record.subject_refs
        assert entry.tags == record.tags
        assert entry.retrieval_hints == record.retrieval_hints
        assert entry.durability == record.durability
        assert entry.text_hash == build.metadata.text_hashes[record.record_id]
        assert entry.vector == (1.0, 1.0, 0.5)
        persisted = json.loads(index.path_for(ARTIFACT_HASH).read_text(encoding="utf-8"))
        assert persisted["metadata"]["authorized_record_ids"] == [record.record_id]


def test_missing_scope_or_deterministic_entry_field_requires_rebuild() -> None:
    with TemporaryDirectory() as temporary:
        index = IdentitySemanticIndex(Path(temporary))
        model = _model((_record("audit-record", "Exact source wording"),))
        build = build_identity_semantic_index(
            model,
            FakeEmbeddingAdapter(),
            _metadata(),
            policy_decisions=_allow_all(model),
            cancel_token=CancelToken(),
        )
        assert index.replace(build).published is True
        path = index.path_for(ARTIFACT_HASH)
        original = json.loads(path.read_text(encoding="utf-8"))

        missing_scope = json.loads(json.dumps(original))
        del missing_scope["metadata"]["authorized_record_ids"]
        path.write_text(json.dumps(missing_scope), encoding="utf-8")
        scope_read = index.read(ARTIFACT_HASH, expected_metadata=build.metadata)
        assert scope_read.semantic_available is False
        assert scope_read.rebuild_required is True
        assert scope_read.reason == "index_corrupt"

        missing_field = json.loads(json.dumps(original))
        del missing_field["entries"][0]["source_path"]
        path.write_text(json.dumps(missing_field), encoding="utf-8")
        field_read = index.read(ARTIFACT_HASH, expected_metadata=build.metadata)
        assert field_read.semantic_available is False
        assert field_read.rebuild_required is True
        assert field_read.reason == "index_corrupt"


def test_index_build_missing_authorization_fails_closed_before_adapter_call() -> None:
    model = _model((_record("private", "PRIVATE SOURCE TEXT"),))
    adapter = FakeEmbeddingAdapter()

    result = build_identity_semantic_index(
        model, adapter, _metadata(), cancel_token=CancelToken()
    )

    assert result.status == "failed"
    assert result.reason == "authorization_required"
    assert result.entries == ()
    assert adapter.calls == []


def test_build_embeds_every_authorized_retrievable_record_and_metadata_is_complete() -> None:
    authorized_records = tuple(
        _record(f"record-{value:03d}", f"Record text {value}") for value in range(66)
    )
    denied = _record("policy-denied", "DENIED SOURCE TEXT MUST NOT BE EMBEDDED")
    quarantined = _record("quarantined", "QUARANTINED SOURCE TEXT")
    records = (*authorized_records, denied, quarantined)
    model = _model(
        records,
        quarantine=(
            QuarantineItem(
                quarantine_id="q-build",
                reason=QuarantineReason.PRIVACY,
                record_ids=(quarantined.record_id,),
            ),
        ),
    )
    adapter = FakeEmbeddingAdapter()
    decisions = _allow_all(model)
    decisions[denied.record_id] = _denied("remote_provider_not_permitted")

    result = build_identity_semantic_index(
        model,
        adapter,
        _metadata(),
        policy_decisions=decisions,
        cancel_token=CancelToken(),
    )

    assert result.status == "complete"
    assert result.cancelled is False
    assert {entry.record_id for entry in result.entries} == {
        record.record_id for record in authorized_records
    }
    assert sum(len(call) for call in adapter.calls) == 66
    assert len(adapter.calls) > 1
    assert all("DENIED SOURCE TEXT" not in text for call in adapter.calls for text in call)
    assert all("QUARANTINED SOURCE TEXT" not in text for call in adapter.calls for text in call)
    assert result.metadata.authorized_record_ids == tuple(
        record.record_id for record in authorized_records
    )
    assert set(result.metadata.text_hashes) == {entry.record_id for entry in result.entries}
    assert result.metadata.artifact_hash == ARTIFACT_HASH
    assert result.metadata.normalizer_revision == model.normalizer_revision
    assert result.metadata.normalized_schema_version == model.schema_version
    assert result.metadata.index_schema_version == IDENTITY_INDEX_SCHEMA_VERSION
    assert result.metadata.index_revision == IDENTITY_INDEX_REVISION
    assert result.metadata.embedding_provider == "fake-provider"
    assert result.metadata.endpoint_identity == "local://fake-embeddings"
    assert result.metadata.embedding_model == "fake-embedding-v1"
    assert result.metadata.embedding_context == 2048
    assert result.metadata.vector_dimension == 3
    assert result.metadata.semantic_threshold == DEFAULT_SEMANTIC_THRESHOLD
    assert result.metadata.semantic_threshold_revision == SEMANTIC_THRESHOLD_REVISION


def test_metadata_changes_request_rebuild_without_mixing_vectors() -> None:
    with TemporaryDirectory() as temporary:
        index = IdentitySemanticIndex(Path(temporary))
        model = _model((_record("one", "One"),))
        built = build_identity_semantic_index(
            model,
            FakeEmbeddingAdapter(),
            _metadata(),
            policy_decisions=_allow_all(model),
            cancel_token=CancelToken(),
        )
        index.replace(built)
        changes = (
            {"embedding_model": "fake-embedding-v2"},
            {"embedding_context": 4096},
            {"vector_dimension": 4},
            {"normalizer_revision": "identity-relay-v0.2.0"},
            {"normalized_schema_version": 2},
            {"index_schema_version": IDENTITY_INDEX_SCHEMA_VERSION + 1},
            {"index_revision": "identity-relay-index-v2"},
            {"semantic_threshold_revision": "identity-relay-semantic-v2"},
        )

        for change in changes:
            read = index.read(ARTIFACT_HASH, expected_metadata=replace(built.metadata, **change))
            assert read.semantic_available is False, change
            assert read.rebuild_required is True, change
            assert "mismatch" in read.reason, change
            assert read.snapshot is None, change


def test_cancel_or_provider_failure_leaves_prior_atomic_index_untouched() -> None:
    with TemporaryDirectory() as temporary:
        index = IdentitySemanticIndex(Path(temporary))
        original_model = _model((_record("original", "Original"),))
        original = build_identity_semantic_index(
            original_model,
            FakeEmbeddingAdapter(),
            _metadata(),
            policy_decisions=_allow_all(original_model),
            cancel_token=CancelToken(),
        )
        assert index.replace(original).published is True
        original_bytes = index.path_for(ARTIFACT_HASH).read_bytes()

        replacement_model = _model((_record("replacement", "Replacement"),))
        token = CancelToken()
        cancelled = build_identity_semantic_index(
            replacement_model,
            FakeEmbeddingAdapter(cancel_token=token),
            _metadata(),
            policy_decisions=_allow_all(replacement_model),
            cancel_token=token,
        )
        assert cancelled.status == "cancelled"
        assert cancelled.cancelled is True
        assert index.replace(cancelled).published is False
        assert index.path_for(ARTIFACT_HASH).read_bytes() == original_bytes

        failed = build_identity_semantic_index(
            replacement_model,
            FakeEmbeddingAdapter(fail=True),
            _metadata(),
            policy_decisions=_allow_all(replacement_model),
            cancel_token=CancelToken(),
        )
        assert failed.status == "failed"
        assert failed.cancelled is False
        assert failed.reason == "embedding_provider_failure"
        assert index.replace(failed).published is False
        assert index.path_for(ARTIFACT_HASH).read_bytes() == original_bytes
        assert not tuple(Path(temporary).glob("*.tmp"))


def main() -> None:
    test_turn_query_envelope_preserves_all_signal_inputs()
    test_source_runtime_provenance_never_becomes_a_retrieval_candidate()
    test_all_activation_signals_are_visible_and_candidates_are_uncapped()
    test_authorization_transient_and_quarantine_prefilter_before_scoring()
    test_clear_matches_and_candidate_order_are_deterministic()
    test_weak_lexical_tag_and_temporal_signals_require_judge_review()
    test_deterministic_signals_sort_ahead_of_equal_semantic_fallback()
    test_semantic_metadata_mismatch_disables_only_semantic_fallback_visibly()
    test_index_search_is_uncapped_and_dimension_errors_are_visible()
    test_search_authorization_expansion_rebuilds_and_narrowing_stays_available()
    test_persisted_entries_round_trip_exact_deterministic_activation_fields()
    test_missing_scope_or_deterministic_entry_field_requires_rebuild()
    test_index_build_missing_authorization_fails_closed_before_adapter_call()
    test_build_embeds_every_authorized_retrievable_record_and_metadata_is_complete()
    test_metadata_changes_request_rebuild_without_mixing_vectors()
    test_cancel_or_provider_failure_leaves_prior_atomic_index_untouched()
    print("smoke_identity_relay_retrieval: ok")


if __name__ == "__main__":
    main()
