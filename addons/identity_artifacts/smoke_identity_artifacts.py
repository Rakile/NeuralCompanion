from __future__ import annotations

import tempfile
import sys
import hashlib
import json
import os
import subprocess
import threading
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from addons.identity_artifacts.importer import import_identity_artifact
from addons.identity_artifacts.attestations import (
    IdentityRelayDecisionStore,
    IdentityRelaySnapshotAuthorizationStore,
    PersistentSnapshotAuthorization,
    TransientActivation,
    persistent_snapshot_authorization_record_id,
)
from addons.identity_artifacts.normalized_model import (
    NORMALIZER_REVISION,
    RuntimeLayer,
    SubjectClass,
    TransientRecord,
    normalized_identity_digest,
    normalized_identity_from_dict,
)
from addons.identity_artifacts.storage import ArtifactResolution, IdentityArtifactStore
from addons.identity_artifacts.relay_state import IdentityRelayModel
from addons.identity_artifacts.controller import IdentityArtifactsController
from addons.identity_artifacts.main import Addon


FIXTURE_PATH = Path(__file__).with_name("fixtures") / "gemini_flash_identity_export_v1_1.json"
CHATGPT_FIXTURE_PATH = (
    Path(__file__).with_name("fixtures") / "chatgpt_assistant_identity_export_v1_1.json"
)

VALID_ARTIFACT_TEXT = json.dumps(
    {
        "format": "NC_IDENTITY_EXPORT",
        "format_version": "1.1",
        "export_kind": "reflect_and_export_identity",
        "hot_identity": {
            "compressed_text": "Continuity",
            "claims": [
                {
                    "claim_id": "continuity",
                    "claim_text": "I preserve continuity.",
                    "subject_refs": ["assistant_self"],
                    "stability": "stable",
                    "confidence": 0.9,
                    "use_policy": {
                        "preferred_runtime_use": "always_inject",
                        "eligible_for_private_retrieval": True,
                    },
                }
            ],
        },
    },
    ensure_ascii=False,
)


def make_instrumented_service(*, enabled: bool):
    from addons.identity_artifacts.service import IdentityRelayService

    counters = {"load": 0, "retrieve": 0, "judge": 0, "render": 0}
    model = IdentityRelayModel()
    model.set_connection(
        ArtifactResolution(
            "library/" + "a" * 64 + ".json",
            "a" * 64,
            "Legacy continuity",
            None,
        )
    )
    model.set_enabled(enabled)

    class InstrumentedStore:
        def load_normalized(self, _artifact_ref):
            counters["load"] += 1
            raise AssertionError("Relay OFF must not load the normalized model")

    def retrieve(*_args, **_kwargs):
        counters["retrieve"] += 1
        raise AssertionError("Relay OFF must not retrieve candidates")

    def judge_renderer(*_args, **_kwargs):
        counters["judge"] += 1
        raise AssertionError("Relay OFF must not render a judge request")

    def projection_renderer(*_args, **_kwargs):
        counters["render"] += 1
        raise AssertionError("Relay OFF must not render a projection")

    return (
        IdentityRelayService(
            model,
            store=InstrumentedStore(),
            candidate_retriever=retrieve,
            judge_renderer=judge_renderer,
            projection_renderer=projection_renderer,
        ),
        counters,
    )


def make_query_envelope():
    from addons.identity_artifacts.retrieval import build_turn_query_envelope

    return build_turn_query_envelope("Continue our current work.")


def _authority_for_capture(relay_model, artifact_ref):
    capture = relay_model.capture_turn()
    if capture is None or capture.artifact_ref != artifact_ref:
        return None
    return {
        "artifact_hash": capture.artifact_hash,
        "normalizer_revision": capture.normalizer_revision,
        "normalized_digest": capture.normalized_digest,
        "frozen_model_digest": capture.frozen_model_digest,
        "attestation_revision": capture.attestation_revision,
        "runtime_use": capture.runtime_use,
        "transient_activation": capture.transient_activation,
        "frozen_normalized_model": capture.frozen_normalized_model,
    }


def _authorized_controller(temp_dir, artifact_text=VALID_ARTIFACT_TEXT):
    root = Path(temp_dir)
    controller = IdentityArtifactsController(
        SimpleNamespace(
            app_root=root,
            storage=SimpleNamespace(addon_dir=root / "legacy"),
            get_service=lambda _name: None,
        )
    )
    stored = controller.store.save_import(import_identity_artifact(artifact_text))
    controller.decision_store.save_subject_attestation(
        artifact_hash=stored.artifact_hash,
        normalizer_revision=NORMALIZER_REVISION,
        subject_class=SubjectClass.ASSISTANT_SELF,
        approved=True,
    )
    controller.set_persona_identity_ref(stored.artifact_ref)
    return controller, stored


def test_relay_off_has_zero_work_fast_path() -> None:
    service, counters = make_instrumented_service(enabled=False)

    capture = service.capture_turn()
    result = service.prepare_turn(capture, make_query_envelope())

    assert result.status == "suspended"
    assert counters == {"load": 0, "retrieve": 0, "judge": 0, "render": 0}


def test_request_local_capture_is_atomic_and_controller_uses_it() -> None:
    model = IdentityRelayModel()
    model.set_connection(
        ArtifactResolution(
            "library/" + "a" * 64 + ".json",
            "a" * 64,
            "Legacy continuity",
            None,
        )
    )
    copy_started = threading.Event()
    release_copy = threading.Event()
    second_done = threading.Event()
    results = {}
    errors = []

    class PausingMapping(Mapping):
        def __iter__(self):
            return iter(("request",))

        def __len__(self):
            return 1

        def __getitem__(self, key):
            if key != "request":
                raise KeyError(key)
            copy_started.set()
            assert release_copy.wait(2.0)
            return "first"

    def capture_first():
        try:
            results["first"] = model.capture_turn_with_context(
                normalizer_revision="first-revision",
                attestation_revision=1,
                transient_activation={},
                runtime_use=PausingMapping(),
                frozen_provider={},
            )
        except Exception as exc:
            errors.append(exc)

    def capture_second():
        try:
            results["second"] = model.capture_turn_with_context(
                normalizer_revision="second-revision",
                attestation_revision=2,
                transient_activation={},
                runtime_use={"request": "second"},
                frozen_provider={},
            )
        except Exception as exc:
            errors.append(exc)
        finally:
            second_done.set()

    first_thread = threading.Thread(target=capture_first)
    second_thread = threading.Thread(target=capture_second)
    first_thread.start()
    assert copy_started.wait(2.0)
    second_thread.start()
    assert not second_done.wait(0.05)
    release_copy.set()
    first_thread.join(2.0)
    second_thread.join(2.0)

    assert errors == []
    assert results["first"].normalizer_revision == "first-revision"
    assert results["first"].runtime_use["request"] == "first"
    assert results["second"].normalizer_revision == "second-revision"
    assert results["second"].runtime_use["request"] == "second"

    with tempfile.TemporaryDirectory() as temp_dir:
        controller, _stored = _authorized_controller(temp_dir)
        controller.relay_model.set_capture_context = lambda **_kwargs: (
            _ for _ in ()
        ).throw(
            AssertionError("public capture must use the atomic request-local operation")
        )
        captured = controller.capture_turn(
            {
                "normalizer_revision": "caller-controlled-revision",
                "attestation_revision": 999,
                "transient_activation": {},
                "runtime_use": {},
                "frozen_provider": {},
            }
        )
        assert captured.normalizer_revision == NORMALIZER_REVISION
        assert captured.attestation_revision == 1
        assert captured.runtime_use["subject_class"] == "assistant_self"


def test_capture_detaches_json_values_and_rejects_mutable_leaf_objects() -> None:
    model = IdentityRelayModel()
    model.set_connection(
        ArtifactResolution(
            "library/" + "a" * 64 + ".json",
            "a" * 64,
            "Legacy continuity",
            None,
        )
    )
    source_context = {"nested": {"values": ["original"]}}
    capture = model.capture_turn_with_context(
        normalizer_revision="revision",
        attestation_revision=1,
        transient_activation={},
        runtime_use=source_context,
        frozen_provider={},
    )
    source_context["nested"]["values"].append("mutated")
    assert capture.runtime_use["nested"]["values"] == ("original",)

    class MutableLeaf:
        def __init__(self):
            self.values = ["mutable"]

    try:
        model.capture_turn_with_context(
            normalizer_revision="rejected-revision",
            attestation_revision=99,
            transient_activation={},
            runtime_use={"replacement": "must-not-publish"},
            frozen_provider={"unsupported": MutableLeaf()},
        )
    except TypeError as exc:
        assert str(exc) == "Identity Relay capture context must be JSON-like"
    else:
        raise AssertionError("unsupported mutable capture leaves must be rejected")
    after_rejection = model.capture_turn()
    assert after_rejection.normalizer_revision == "revision"
    assert after_rejection.attestation_revision == 1
    assert after_rejection.runtime_use["nested"]["values"] == ("original",)
    assert "replacement" not in after_rejection.runtime_use


def test_v2_capture_uses_cached_authority_without_storage_or_resolver_work() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        controller, stored = _authorized_controller(temp_dir)

        def unexpected(*_args, **_kwargs):
            raise AssertionError("v2 capture must not resolve authority or touch storage")

        controller._authoritative_state_for_ref = unexpected
        controller.store.resolve_artifact = unexpected
        controller.store.load_normalized = unexpected
        controller.decision_store.load = unexpected

        capture = controller.capture_turn(
            {
                "schema_version": 2,
                "frozen_provider": {"provider": {"model": "local-test"}},
            }
        )

        assert capture.artifact_ref == stored.artifact_ref
        assert capture.artifact_hash == stored.artifact_hash
        assert capture.normalizer_revision == NORMALIZER_REVISION
        assert capture.attestation_revision == 1
        assert capture.runtime_use["subject_class"] == "assistant_self"


def test_v2_disabled_capture_is_lock_only_and_contains_no_identity_authority() -> None:
    from addons.identity_artifacts import relay_state

    with tempfile.TemporaryDirectory() as temp_dir:
        controller, stored = _authorized_controller(temp_dir)
        assert controller.set_relay_enabled(False) is True

        def unexpected(*_args, **_kwargs):
            raise AssertionError("disabled v2 capture must not resolve authority or touch storage")

        controller._authoritative_state_for_ref = unexpected
        controller.store.resolve_artifact = unexpected
        controller.store.load_normalized = unexpected
        controller.decision_store.load = unexpected

        original_freeze = relay_state._freeze_mapping
        relay_state._freeze_mapping = unexpected
        try:
            capture = controller.capture_turn({"schema_version": 2})
        finally:
            relay_state._freeze_mapping = original_freeze

        assert capture.enabled is False
        assert capture.artifact_ref == stored.artifact_ref
        assert capture.artifact_hash == stored.artifact_hash
        assert capture.normalizer_revision == ""
        assert capture.normalized_digest == ""
        assert capture.attestation_revision == 0
        assert capture.transient_activation == {}
        assert capture.runtime_use == {}
        assert capture.frozen_provider == {}
        assert capture.frozen_normalized_model == {}
        assert capture.frozen_model_digest == ""


def test_v2_capture_freezes_the_request_local_provider_summary() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        controller, _stored = _authorized_controller(temp_dir)
        frozen_provider = {
            "provider": {"model": "local-test", "limits": [1024]},
            "provider_config": {"provider_is_remote": True},
        }

        capture = controller.capture_turn(
            {"schema_version": 2, "frozen_provider": frozen_provider}
        )
        frozen_provider["provider"]["limits"].append(2048)

        assert capture.frozen_provider == {
            "provider": {"model": "local-test", "limits": (1024,)},
            "provider_config": {"provider_is_remote": True},
        }
        assert capture.runtime_use["provider_is_remote"] is True


def test_v2_capture_without_current_cached_authority_fails_closed_without_disk() -> None:
    controller = IdentityArtifactsController(context=None)
    controller.relay_model.set_connection(
        ArtifactResolution(
            "library/" + "a" * 64 + ".json",
            "a" * 64,
            "Legacy continuity",
            None,
        )
    )

    def unexpected(*_args, **_kwargs):
        raise AssertionError("v2 capture must not repair missing authority from disk")

    controller._authoritative_state_for_ref = unexpected
    controller.store.resolve_artifact = unexpected
    controller.store.load_normalized = unexpected
    controller.decision_store.load = unexpected

    capture = controller.capture_turn({"schema_version": 2})

    assert capture is not None
    assert capture.enabled is True
    assert capture.normalizer_revision == ""
    assert capture.attestation_revision == 0
    assert capture.runtime_use["provider_is_remote"] is None
    assert "subject_approved" not in capture.runtime_use
    assert capture.transient_activation == {}


def _completed_refresh_payload(controller):
    token = SimpleNamespace(is_cancelled=lambda: False)
    connected_ref = controller.relay_model.ui_snapshot().connected_ref
    return controller._build_refresh_payload(
        migrate_legacy=False,
        connected_ref=connected_ref,
        token=token,
    )


def test_late_refresh_does_not_reconnect_after_disconnect() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        controller, _stored = _authorized_controller(temp_dir)
        payload = _completed_refresh_payload(controller)

        controller.set_persona_identity_ref("")
        controller._apply_refresh_payload(payload)

        snapshot = controller.relay_model.ui_snapshot()
        assert snapshot.connected_ref == ""
        assert any(ref for _label, ref in snapshot.options)


def test_late_refresh_does_not_replace_a_newer_connection() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        controller, first = _authorized_controller(temp_dir)
        second = controller.store.save_import(
            import_identity_artifact(
                VALID_ARTIFACT_TEXT.replace("Continuity", "Second continuity")
            )
        )
        controller.decision_store.save_subject_attestation(
            artifact_hash=second.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            subject_class=SubjectClass.ASSISTANT_SELF,
            approved=True,
        )
        payload = _completed_refresh_payload(controller)

        controller.set_persona_identity_ref(second.artifact_ref)
        controller._apply_refresh_payload(payload)

        assert first.artifact_ref != second.artifact_ref
        assert controller.relay_model.ui_snapshot().connected_ref == second.artifact_ref


def test_cancelled_connection_apply_commits_no_attestation_review_or_authority() -> None:
    from addons.identity_artifacts.controller import (
        _CancellationToken,
        _ConnectionPayload,
    )
    from addons.identity_artifacts.review_dialog import (
        ConnectionReviewResult,
        ReviewItemDecision,
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        controller = IdentityArtifactsController(
            SimpleNamespace(
                app_root=root,
                storage=SimpleNamespace(addon_dir=root / "legacy"),
                get_service=lambda _name: None,
            )
        )
        stored = controller.store.save_import(import_identity_artifact(VALID_ARTIFACT_TEXT))
        normalized = controller.store.load_normalized(stored.artifact_ref)
        resolution = controller.store.resolve_artifact(stored.artifact_ref)
        prepared = _ConnectionPayload(
            resolution,
            normalized,
            controller.decision_store.load(stored.artifact_hash),
            "not_built",
        )
        result = ConnectionReviewResult(
            artifact_ref=stored.artifact_ref,
            artifact_hash=stored.artifact_hash,
            subject_class=SubjectClass.ASSISTANT_SELF,
            approved=True,
            item_decisions=(ReviewItemDecision("review:race", "approve"),),
        )
        token = _CancellationToken(1)
        controller._operation_generations["connection_apply"] = 1
        controller._operation_tokens["connection_apply"] = token
        load_reached = threading.Event()
        release_load = threading.Event()
        original_load = controller.decision_store.load

        def paused_load(artifact_hash):
            load_reached.set()
            assert release_load.wait(2.0)
            return original_load(artifact_hash)

        controller.decision_store.load = paused_load
        outcome = []
        worker = threading.Thread(
            target=lambda: outcome.append(
                controller._perform_connection_apply(
                    result,
                    prepared,
                    (),
                    (),
                    controller._chat_session_token,
                    token,
                )
            )
        )
        worker.start()
        assert load_reached.wait(2.0)
        token.cancel()
        release_load.set()
        worker.join(2.0)
        assert not worker.is_alive()
        controller.decision_store.load = original_load

        state = original_load(stored.artifact_hash)
        assert outcome == [None]
        assert state.subject_attestation is None
        assert state.review_decisions == ()
        assert state.transient_activations == ()
        assert controller._authoritative_state_for_ref(stored.artifact_ref) is None
        assert controller.relay_model.ui_snapshot().connected_ref == ""


def _prepared_connection_race(temp_dir):
    from addons.identity_artifacts.controller import (
        _CancellationToken,
        _ConnectionPayload,
        _PendingConnection,
    )
    from addons.identity_artifacts.review_dialog import ConnectionReviewResult

    root = Path(temp_dir)
    controller = IdentityArtifactsController(
        SimpleNamespace(
            app_root=root,
            storage=SimpleNamespace(addon_dir=root / "legacy"),
            get_service=lambda _name: None,
        )
    )
    stored = controller.store.save_import(import_identity_artifact(VALID_ARTIFACT_TEXT))
    normalized = controller.store.load_normalized(stored.artifact_ref)
    resolution = controller.store.resolve_artifact(stored.artifact_ref)
    prepared = _ConnectionPayload(
        resolution,
        normalized,
        controller.decision_store.load(stored.artifact_hash),
        "not_built",
    )
    result = ConnectionReviewResult(
        artifact_ref=stored.artifact_ref,
        artifact_hash=stored.artifact_hash,
        subject_class=SubjectClass.ASSISTANT_SELF,
        approved=True,
        item_decisions=(),
    )
    token = _CancellationToken(1)
    controller._operation_generations["connection_apply"] = 1
    controller._operation_tokens["connection_apply"] = token
    controller._pending_connection = _PendingConnection("", stored.artifact_ref)
    controller._review_connection_payload = prepared
    payload = controller._perform_connection_apply(
        result,
        prepared,
        (),
        (),
        controller._chat_session_token,
        token,
    )
    assert payload is not None
    return controller, stored, payload


def test_connection_apply_wins_delete_race_atomically() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        controller, stored, payload = _prepared_connection_race(temp_dir)
        commit_reached = threading.Event()
        release_commit = threading.Event()
        delete_started = threading.Event()
        delete_finished = threading.Event()
        delete_results = []
        original_set_context = controller._set_relay_connection_context

        def paused_set_context(resolution, authority):
            commit_reached.set()
            assert release_commit.wait(3.0)
            return original_set_context(resolution, authority)

        controller._set_relay_connection_context = paused_set_context
        apply_thread = threading.Thread(
            name="identity-apply-winner",
            target=lambda: controller._complete_connection_apply(payload),
        )

        def delete_target():
            delete_started.set()
            delete_results.append(controller.delete_artifact(stored.artifact_ref))
            delete_finished.set()

        delete_thread = threading.Thread(
            name="identity-delete-loser",
            target=delete_target,
        )
        apply_thread.start()
        assert commit_reached.wait(3.0)
        delete_thread.start()
        assert delete_started.wait(3.0)
        delete_completed_before_commit = delete_finished.wait(1.0)
        release_commit.set()
        apply_thread.join(3.0)
        delete_thread.join(3.0)

        assert not apply_thread.is_alive()
        assert not delete_thread.is_alive()
        assert delete_completed_before_commit is False
        assert len(delete_results) == 1
        assert delete_results[0].deleted is False
        assert delete_results[0].blocked_by == ("active_persona",)
        assert stored.canonical_path.exists()
        assert stored.derived_path.exists()
        state = controller.decision_store.load(stored.artifact_hash)
        assert state.subject_attestation is not None
        assert controller.relay_model.ui_snapshot().connected_ref == stored.artifact_ref
        assert controller._connection_status == "Approved assistant-self identity connected"
        assert controller.last_visible_notice == controller._connection_status


def test_delete_wins_connection_apply_race_without_hidden_authority() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        controller, stored, payload = _prepared_connection_race(temp_dir)
        delete_commit_reached = threading.Event()
        release_delete_commit = threading.Event()
        apply_started = threading.Event()
        delete_results = []
        original_delete = controller.store.delete_artifact

        def paused_delete(*args, **kwargs):
            delete_commit_reached.set()
            assert release_delete_commit.wait(3.0)
            return original_delete(*args, **kwargs)

        controller.store.delete_artifact = paused_delete
        delete_thread = threading.Thread(
            name="identity-delete-winner",
            target=lambda: delete_results.append(
                controller.delete_artifact(stored.artifact_ref)
            ),
        )

        def apply_target():
            apply_started.set()
            controller._complete_connection_apply(payload)

        apply_thread = threading.Thread(
            name="identity-apply-loser",
            target=apply_target,
        )
        delete_thread.start()
        assert delete_commit_reached.wait(3.0)
        apply_thread.start()
        assert apply_started.wait(3.0)
        release_delete_commit.set()
        delete_thread.join(3.0)
        apply_thread.join(3.0)

        assert not delete_thread.is_alive()
        assert not apply_thread.is_alive()
        assert len(delete_results) == 1
        assert delete_results[0].deleted is True
        assert not stored.canonical_path.exists()
        assert not stored.derived_path.exists()
        state = controller.decision_store.load(stored.artifact_hash)
        assert state.subject_attestation is None
        assert state.review_decisions == ()
        assert state.transient_activations == ()
        assert controller._authoritative_state_for_ref(stored.artifact_ref) is None
        assert controller.relay_model.ui_snapshot().connected_ref == ""
        assert controller._pending_connection is None
        assert "cancel" in controller._connection_status.casefold()
        assert "delet" in controller._connection_status.casefold()
        assert controller.last_visible_notice == controller._connection_status


def test_refresh_disconnects_same_ref_when_authority_is_revoked() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        controller, stored = _authorized_controller(temp_dir)
        controller.decision_store.save_subject_attestation(
            artifact_hash=stored.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            subject_class=SubjectClass.ASSISTANT_SELF,
            approved=False,
        )
        payload = _completed_refresh_payload(controller)

        controller._apply_refresh_payload(payload)

        assert controller.relay_model.ui_snapshot().connected_ref == ""
        assert controller.capture_turn({"schema_version": 2}) is None
        assert controller._connection_status == controller.last_visible_notice
        notice = controller.last_visible_notice.lower()
        assert "disconnected" in notice
        assert "authority" in notice


def _authorized_transient_controller(temp_dir):
    from PySide6 import QtWidgets

    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    controller, stored = _authorized_controller(temp_dir, FIXTURE_PATH.read_bytes())
    model = controller.store.load_normalized(stored.artifact_ref)
    transient = model.transient_records[0]
    state = controller.decision_store.load(stored.artifact_hash)
    controller.decision_store.save(
        replace(
            state,
            transient_activations=(
                TransientActivation(
                    record_id=transient.record_id,
                    active=True,
                    activated_at="2026-07-17T10:00:00+00:00",
                    session_token=controller._chat_session_token,
                    revision=1,
                    reviewed_at="2026-07-17T10:00:00+00:00",
                ),
            ),
        )
    )
    controller.set_persona_identity_ref(stored.artifact_ref)
    return controller, stored, transient


def _capture_and_prepare_local_turn(controller):
    capture = controller.capture_turn(
        {
            "schema_version": 2,
            "frozen_provider": {
                "provider_config": {"provider_is_remote": False},
                "max_batch_chars": 100_000,
            },
        }
    )
    prepared = controller.prepare_turn(
        {"schema_version": 2, "capture": capture, "query": make_query_envelope()}
    )
    return capture, prepared


def _assert_session_mismatch_authority(capture, prepared, transient) -> None:
    transient_state = capture.transient_activation[transient.record_id]
    assert capture.attestation_revision > 0
    assert capture.runtime_use["subject_approved"] is True
    assert transient_state["active"] is False
    assert transient_state["review_required"] is True
    assert transient_state["reason_code"] == "session_mismatch"
    assert prepared.failure_code not in {
        "assistant_self_attestation_required",
        "authoritative_capture_mismatch",
        "identity_authority_unavailable",
    }


def test_session_reset_revalidates_authority_and_transients_off_capture_path() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        controller, _stored, transient = _authorized_transient_controller(temp_dir)
        before = controller._chat_session_token
        authority_started = threading.Event()
        release_authority = threading.Event()
        original_authority = controller._authoritative_state_for_ref

        def delayed_authority(*args, **kwargs):
            authority_started.set()
            assert release_authority.wait(2.0)
            return original_authority(*args, **kwargs)

        controller._authoritative_state_for_ref = delayed_authority
        controller._force_async_operations = True

        controller.reset_chat_session_state()
        assert authority_started.wait(2.0)
        pending = controller.capture_turn(
            {
                "schema_version": 2,
                "frozen_provider": {
                    "provider_config": {"provider_is_remote": False}
                },
            }
        )
        assert pending.attestation_revision == 0
        release_authority.set()
        generation = controller.operation_generation("session_authority")
        controller._wait_for_operation(("session_authority", generation))
        capture, prepared = _capture_and_prepare_local_turn(controller)

        assert controller._chat_session_token != before
        _assert_session_mismatch_authority(capture, prepared, transient)


def test_session_load_revalidates_authority_and_transients_for_saved_state() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        controller, stored, transient = _authorized_transient_controller(temp_dir)

        controller.reset_chat_session_state()
        controller.import_chat_session_state(
            {"artifact_ref": stored.artifact_ref, "state": "active"}
        )
        capture, prepared = _capture_and_prepare_local_turn(controller)

        assert controller.relay_model.ui_snapshot().enabled is True
        _assert_session_mismatch_authority(capture, prepared, transient)


def test_same_ref_revalidation_disconnects_revoked_authority() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        controller, stored = _authorized_controller(temp_dir)
        controller.decision_store.save_subject_attestation(
            artifact_hash=stored.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            subject_class=SubjectClass.ASSISTANT_SELF,
            approved=False,
        )

        snapshot = controller.set_persona_identity_ref(stored.artifact_ref)

        assert snapshot.connected_ref == ""
        assert controller.capture_turn({"schema_version": 2}) is None
        assert "authority" in controller.last_visible_notice.lower()


def test_controller_remote_provider_capture_narrows_unauthorized_kernel() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        controller, _stored = _authorized_controller(temp_dir, FIXTURE_PATH.read_bytes())
        frozen_provider = {
            "provider_config": {"provider_is_remote": True},
            "max_batch_chars": 100_000,
        }

        capture = controller.capture_turn(
            {"schema_version": 2, "frozen_provider": frozen_provider}
        )
        frozen_provider["provider_config"]["provider_is_remote"] = False
        prepared = controller.prepare_turn(
            {"schema_version": 2, "capture": capture, "query": make_query_envelope()}
        )

        assert capture.runtime_use["provider_is_remote"] is True
        assert capture.frozen_provider["provider_config"]["provider_is_remote"] is True
        assert prepared.status == "judge_required"
        assert prepared.authorized_kernel_record_ids
        assert prepared.omitted_kernel_record_ids
        assert set(prepared.authorized_kernel_record_ids).isdisjoint(
            prepared.omitted_kernel_record_ids
        )


def test_controller_freezes_owner_override_for_remote_turn_authorization() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        controller, _stored = _authorized_controller(
            temp_dir,
            FIXTURE_PATH.read_bytes(),
        )
        runtime_values = {"identity_relay_owner_override": True}
        controller.runtime_config = SimpleNamespace(
            snapshot=lambda: dict(runtime_values),
        )
        capture = controller.capture_turn(
            {
                "schema_version": 2,
                "frozen_provider": {
                    "provider_config": {"provider_is_remote": True},
                    "max_batch_chars": 100_000,
                },
            }
        )
        runtime_values["identity_relay_owner_override"] = False
        prepared = controller.prepare_turn(
            {
                "schema_version": 2,
                "capture": capture,
                "query": make_query_envelope(),
            }
        )

        assert capture.runtime_use["owner_override"] is True
        assert prepared.authorized_kernel_record_ids
        assert prepared.omitted_kernel_record_ids == ()


def test_remote_provider_omits_unauthorized_kernel_without_blocking_authorized_identity() -> None:
    from addons.identity_artifacts.projection import render_projection
    from addons.identity_artifacts.retrieval import CandidateSet
    from addons.identity_artifacts.service import IdentityRelayService
    from addons.identity_artifacts.smoke_identity_relay_projection import _model

    base = _model()
    kernel = base.records_by_id[base.kernel_record_ids[0]]
    remote_kernel = replace(
        kernel,
        source_text="Remote-authorized first-person continuity.",
        exposure_policy={
            **dict(kernel.exposure_policy),
            "private_remote_1on1": "allow",
        },
    )
    local_kernel = replace(
        kernel,
        record_id="record:local_only_boundary",
        source_path="$.identity_structure.do_not_infer[0]",
        source_text="Local-only identity boundary must not leave this machine.",
        exposure_policy={
            **dict(kernel.exposure_policy),
            "private_remote_1on1": "deny",
        },
    )
    normalized = replace(
        base,
        records=(remote_kernel, local_kernel),
        kernel_record_ids=(remote_kernel.record_id, local_kernel.record_id),
        retrievable_record_ids=(),
        transient_records=(),
        tensions=(),
        review_queue=(),
        quarantine=(),
    )
    def make_remote_service(model):
        digest = normalized_identity_digest(model)
        relay_model = IdentityRelayModel()
        relay_model.set_connection(
            ArtifactResolution(
                f"library/{model.envelope.artifact_hash}.json",
                model.envelope.artifact_hash,
                "Mixed-exposure identity",
                None,
                digest,
            )
        )
        relay_model.set_capture_context(
            normalizer_revision=model.normalizer_revision,
            normalized_digest=digest,
            attestation_revision=1,
            transient_activation={},
            runtime_use={
                "surface": "chat",
                "provider_is_remote": True,
                "subject_class": "assistant_self",
                "subject_approved": True,
                "approved_operations": ("provider_transmission",),
            },
            frozen_provider={
                "provider_name": "openai",
                "model_name": "gpt-4o",
                "embedding_base_url": "http://127.0.0.1:1234/v1",
                "base_messages": ({"role": "user", "content": "Who are you?"},),
                "model_context_limit": 8192,
                "reserved_output_tokens": 256,
                "persistence_mode": "volatile",
            },
            frozen_normalized_model=model.to_dict(),
            frozen_model_digest=digest,
        )
        return IdentityRelayService(
            relay_model,
            store=SimpleNamespace(),
            candidate_retriever=lambda *_args, **_kwargs: CandidateSet(
                eligible=(),
                denied_record_ids=(),
                semantic_available=False,
                semantic_reason="not_configured",
            ),
            projection_renderer=render_projection,
            token_counter=lambda messages: sum(
                len(str(message.get("content") or "").split()) for message in messages
            ),
        )

    service = make_remote_service(normalized)

    prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())
    assert prepared.status == "ready_without_judge"
    assert prepared.authorized_kernel_record_ids == (remote_kernel.record_id,)
    assert prepared.omitted_kernel_record_ids == (local_kernel.record_id,)

    snapshot = service.finalize_turn(prepared)
    assert snapshot.status == "ready"
    assert snapshot.kernel_record_ids == (remote_kernel.record_id,)
    assert remote_kernel.source_text in snapshot.prompt_text
    assert local_kernel.source_text not in snapshot.prompt_text
    notice = snapshot.trace["degradation_notice"]
    assert notice["prominent"] is True
    assert notice["failure_category"] == "kernel_policy_narrowing"
    assert notice["kernel_active_count"] == 1
    assert notice["kernel_total_count"] == 2
    assert notice["kernel_omitted_count"] == 1
    assert "1 of 2 stable records" in notice["reason"]
    assert "not authorized" in notice["reason"].lower()

    denied_model = replace(
        normalized,
        records=(local_kernel,),
        kernel_record_ids=(local_kernel.record_id,),
    )
    denied_service = make_remote_service(denied_model)
    denied = denied_service.prepare_turn(
        denied_service.capture_turn(),
        make_query_envelope(),
    )
    assert denied.status == "blocked"
    assert denied.failure_code == "kernel_use_not_authorized"


def test_public_controller_off_path_does_not_parse_query_or_call_dependencies() -> None:
    controller = IdentityArtifactsController(context=None)
    controller.relay_model.set_connection(
        ArtifactResolution(
            "library/" + "a" * 64 + ".json",
            "a" * 64,
            "Legacy continuity",
            None,
        )
    )
    assert controller.set_relay_enabled(False) is True
    capture = controller.relay_model.capture_turn()

    class ExplodingQuery(Mapping):
        def __iter__(self):
            raise AssertionError("Relay OFF must not parse query fields")

        def __len__(self):
            return 1

        def __getitem__(self, _key):
            raise AssertionError("Relay OFF must not read query fields")

    controller.relay_service._store = SimpleNamespace(
        load_normalized=lambda _ref: (_ for _ in ()).throw(
            AssertionError("Relay OFF must not load dependencies")
        )
    )
    prepared = controller.prepare_turn(
        {"capture": capture, "query": ExplodingQuery()}
    )

    assert prepared.status == "suspended"


def test_controller_capture_checks_off_state_before_payload_or_embedding_config() -> None:
    class ExplodingPayload(Mapping):
        def __iter__(self):
            raise AssertionError("Relay OFF must not parse capture payload")

        def __len__(self):
            return 1

        def __getitem__(self, _key):
            raise AssertionError("Relay OFF must not read capture payload")

    config_reads = []

    def broken_embedding_config():
        config_reads.append(True)
        raise RuntimeError("broken embedding configuration")

    controller = IdentityArtifactsController(context=None)
    controller._runtime_embedding_config = broken_embedding_config
    assert controller.capture_turn(ExplodingPayload()) is None
    assert config_reads == []

    controller.relay_model.set_connection(
        ArtifactResolution(
            "library/" + "a" * 64 + ".json",
            "a" * 64,
            "Connected identity",
            None,
        )
    )
    assert controller.set_relay_enabled(False) is True
    suspended = controller.capture_turn(ExplodingPayload())
    assert suspended.enabled is False
    assert config_reads == []

    assert controller.set_relay_enabled(True) is True
    try:
        controller.capture_turn({"frozen_provider": {}})
    except RuntimeError as exc:
        assert "embedding configuration" in str(exc)
    else:
        raise AssertionError("Relay ON configuration failures must fail closed")
    assert config_reads == [True]


def make_ready_service():
    from addons.identity_artifacts.attestations import TransientActivationState
    from addons.identity_artifacts.judge import build_judge_batches
    from addons.identity_artifacts.projection import render_projection
    from addons.identity_artifacts.service import IdentityRelayService
    from addons.identity_artifacts.smoke_identity_relay_projection import (
        _model,
        _runtime_state,
    )

    normalized = _model()
    runtime_state = _runtime_state(normalized)
    relay_model = IdentityRelayModel()
    relay_model.set_connection(
        ArtifactResolution(
            f"library/{normalized.envelope.artifact_hash}.json",
            normalized.envelope.artifact_hash,
            "Legacy continuity",
            None,
        )
    )
    relay_model.set_capture_context(
        normalizer_revision=normalized.normalizer_revision,
        normalized_digest=normalized_identity_digest(normalized),
        attestation_revision=runtime_state.subject_attestation_revision,
        transient_activation={
            "transient:session": TransientActivationState(
                True,
                False,
                "active_for_session",
            )
        },
        runtime_use={
            "surface": "chat",
            "provider_is_remote": False,
            "subject_class": "assistant_self",
            "subject_approved": True,
            "review_decisions": {"review:correction": "approved_for_private_chat"},
        },
        frozen_provider={
            "provider_name": "frozen-provider",
            "model_name": "frozen-model",
            "embedding_model": "fake-embedding-v1",
            "embedding_base_url": "http://127.0.0.1:1234/v1",
            "embedding_context": 2048,
            "max_batch_chars": 100_000,
            "base_messages": ({"role": "user", "content": "Continue our current work."},),
            "model_context_limit": 8_192,
            "reserved_output_tokens": 256,
            "persistence_mode": "persistent",
        },
        frozen_normalized_model=normalized.to_dict(),
        frozen_model_digest=normalized_identity_digest(normalized),
    )

    class FakeStore:
        def load_normalized(self, artifact_ref):
            assert artifact_ref == f"library/{normalized.envelope.artifact_hash}.json"
            return normalized

        def load_identity_relay_authority(self, artifact_ref):
            return _authority_for_capture(relay_model, artifact_ref)

    def retrieve(model, query, policy_decisions, transient_states, semantic_hits):
        assert model == normalized
        assert query.latest_user_turn == "Continue our current work."
        assert policy_decisions["record:project"].allowed is True
        assert transient_states["transient:session"].active is True
        return replace(
            runtime_state.candidate_set,
            semantic_available=semantic_hits.semantic_available,
            semantic_reason=semantic_hits.reason,
            semantic_threshold=semantic_hits.semantic_threshold,
            semantic_threshold_revision=semantic_hits.semantic_threshold_revision,
        )

    return IdentityRelayService(
        relay_model,
        store=FakeStore(),
        candidate_retriever=retrieve,
        judge_renderer=build_judge_batches,
        projection_renderer=render_projection,
        token_counter=lambda messages: sum(
            len(str(message.get("content") or "").split()) for message in messages
        ),
    )


def without_transient_candidates(prepared):
    candidate_set = prepared.runtime_state.candidate_set
    return replace(
        prepared,
        deterministic_record_ids=tuple(
            record_id
            for record_id in prepared.deterministic_record_ids
            if not record_id.startswith("transient:")
        ),
        runtime_state=replace(
            prepared.runtime_state,
            transient_states={},
            candidate_set=replace(
                candidate_set,
                eligible=tuple(
                    candidate
                    for candidate in candidate_set.eligible
                    if not candidate.record_id.startswith("transient:")
                ),
            ),
        ),
    )


def valid_judge_payload() -> str:
    return json.dumps(
        {
            "record_ids": ["record:correction"],
            "reasons": {
                "record:correction": "The explicit correction changes interpretation."
            },
            "signals_considered": {"record:correction": ["semantic_fallback"]},
            "unresolved_record_ids": [],
        }
    )


def _transient_policy_service(
    *,
    provider_is_remote,
    remote_mode: str = "deny",
    debug_mode: str = "redact",
    persistence_mode: str = "deny",
    active: bool = True,
    missing_policy: bool = False,
    owner_override: bool = False,
):
    from addons.identity_artifacts.attestations import TransientActivationState
    from addons.identity_artifacts.service import IdentityRelayService
    from addons.identity_artifacts.smoke_identity_relay_projection import _model

    base_model = _model()
    transient = TransientRecord(
        record_id="transient:policy-matrix",
        source_path="$.transient_continuity",
        source_text="Secret transient policy matrix phrase.",
        subject_refs=("assistant_self",),
        ttl_hint="session",
        confidence=0.4,
        provenance={"source_id": "source:transient-policy"},
        semantic_role="session_context",
        runtime_layer=RuntimeLayer.RETRIEVABLE,
        epistemic_qualifier="uncertain",
        declared_policy=(
            {}
            if missing_policy
            else {
                "eligible_for_private_retrieval": True,
                "eligible_for_external_export": persistence_mode == "allow",
                "eligible_for_debug_logging": True,
            }
        ),
        exposure_policy=(
            {}
            if missing_policy
            else {
                "private_local_1on1": "allow",
                "private_remote_1on1": remote_mode,
                "external_export": persistence_mode,
                "debug_logs": debug_mode,
            }
        ),
        privacy_class="private",
        runtime_suitability=(
            ()
            if missing_policy
            else ("private_retrieval", "external_export", "debug_logging")
        ),
        review_state="not_required",
        activation_metadata={"requires_explicit_activation": True},
    )
    normalized = replace(base_model, transient_records=(transient,))
    relay_model = IdentityRelayModel()
    relay_model.set_connection(
        ArtifactResolution(
            f"library/{normalized.envelope.artifact_hash}.json",
            normalized.envelope.artifact_hash,
            "",
            None,
            normalized_identity_digest(normalized),
        )
    )
    relay_model.set_capture_context(
        normalizer_revision=normalized.normalizer_revision,
        normalized_digest=normalized_identity_digest(normalized),
        attestation_revision=4,
        transient_activation={
            transient.record_id: TransientActivationState(
                active,
                False,
                "active_for_session" if active else "inactive",
            )
        },
        runtime_use={
            "surface": "chat",
            "provider_is_remote": provider_is_remote,
            "subject_class": "assistant_self",
            "subject_approved": True,
            "review_decisions": {
                "review:correction": "approved_for_private_chat"
            },
            "approved_operations": ("provider_transmission",),
            "owner_override": owner_override,
        },
        frozen_provider={
            "provider_name": "transient-policy-provider",
            "model_name": "transient-policy-model",
            "max_batch_chars": 100_000,
            "base_messages": (
                {"role": "user", "content": "Nothing related."},
            ),
            "persistence_mode": "policy",
        },
        frozen_normalized_model=normalized.to_dict(),
        frozen_model_digest=normalized_identity_digest(normalized),
    )

    class FakeStore:
        def load_normalized(self, _artifact_ref):
            return normalized

        def load_identity_relay_authority(self, artifact_ref):
            return _authority_for_capture(relay_model, artifact_ref)

    service = IdentityRelayService(relay_model, store=FakeStore())
    prepared = service.prepare_turn(
        service.capture_turn(),
        make_query_envelope(),
    )
    return service, prepared, transient


def _judge_payload_selecting(prepared, record_id: str):
    return {
        batch.batch_id: json.dumps(
            {
                "record_ids": ([record_id] if record_id in batch.candidate_ids else []),
                "reasons": (
                    {record_id: "Transient context is relevant."}
                    if record_id in batch.candidate_ids
                    else {}
                ),
                "signals_considered": (
                    {record_id: ["policy_test"]}
                    if record_id in batch.candidate_ids
                    else {}
                ),
                "unresolved_record_ids": [
                    candidate_id
                    for candidate_id in batch.candidate_ids
                    if candidate_id != record_id
                ],
            }
        )
        for batch in prepared.judge_batches
    }


def test_transient_policy_is_operation_specific_before_candidates_and_judge() -> None:
    local_service, local, transient = _transient_policy_service(
        provider_is_remote=False,
    )
    assert local.status == "judge_required"
    local_decisions = local.operation_decisions[transient.record_id]
    assert local_decisions["private_retrieval"].allowed is True
    assert local_decisions["provider_transmission"].allowed is True
    assert local_decisions["persistence_export"].allowed is False
    assert local_decisions["debug_trace"].reason_code == "allowed_narrowed"
    assert any(
        transient.source_text in batch.prompt_text for batch in local.judge_batches
    )
    local_snapshot = local_service.finalize_turn(
        local,
        judge_payload=_judge_payload_selecting(local, transient.record_id),
    )
    assert local_snapshot.status == "ready"
    assert local_snapshot.persistence_mode == "volatile"
    assert local_snapshot.trace["debug_trace_mode"] == "redact"

    _remote_service, remote, remote_transient = _transient_policy_service(
        provider_is_remote=True,
        remote_mode="allow",
        persistence_mode="allow",
        debug_mode="allow",
    )
    assert remote.operation_decisions[remote_transient.record_id][
        "provider_transmission"
    ].allowed is True
    assert any(
        remote_transient.source_text in batch.prompt_text
        for batch in remote.judge_batches
    )

    for kwargs, expected_reason in (
        (
            {"provider_is_remote": True, "remote_mode": "deny"},
            "exposure_not_permitted",
        ),
        (
            {"provider_is_remote": False, "active": False},
            "transient_inactive",
        ),
        (
            {"provider_is_remote": False, "missing_policy": True},
            "no_runtime_suitable_use",
        ),
    ):
        _service, prepared, denied_transient = _transient_policy_service(**kwargs)
        decision = prepared.operation_decisions[denied_transient.record_id][
            "provider_transmission"
        ]
        if kwargs.get("active") is False:
            decision = prepared.operation_decisions[denied_transient.record_id][
                "private_retrieval"
            ]
        assert decision.reason_code == expected_reason
        assert denied_transient.record_id in prepared.candidate_set.denied_record_ids
        assert all(
            denied_transient.source_text not in batch.prompt_text
            for batch in prepared.judge_batches
        )

    _unknown_service, unknown, _unknown_transient = _transient_policy_service(
        provider_is_remote=None,
    )
    assert unknown.status == "blocked"
    assert unknown.failure_code == "provider_locality_required"
    assert unknown.judge_batches == ()

    denied_debug_service, denied_debug, denied_debug_transient = (
        _transient_policy_service(
            provider_is_remote=False,
            debug_mode="deny",
            persistence_mode="allow",
        )
    )
    denied_debug_snapshot = denied_debug_service.finalize_turn(
        denied_debug,
        judge_payload=_judge_payload_selecting(
            denied_debug,
            denied_debug_transient.record_id,
        ),
    )
    assert denied_debug.operation_decisions[denied_debug_transient.record_id][
        "debug_trace"
    ].allowed is False
    assert denied_debug_snapshot.trace["debug_trace_mode"] == "deny"

    override_service, override, override_transient = _transient_policy_service(
        provider_is_remote=True,
        remote_mode="deny",
        debug_mode="deny",
        persistence_mode="deny",
        owner_override=True,
    )
    assert override.status == "judge_required"
    assert override.operation_decisions[override_transient.record_id][
        "provider_transmission"
    ].reason_code == "owner_override"
    assert override.operation_decisions[override_transient.record_id][
        "debug_trace"
    ].reason_code == "owner_override"
    override_snapshot = override_service.finalize_turn(
        override,
        judge_payload=_judge_payload_selecting(
            override,
            override_transient.record_id,
        ),
    )
    assert override_snapshot.status == "ready"
    assert override_snapshot.trace["debug_trace_mode"] == "allow"
    assert "[redacted]" not in repr(override_snapshot.trace)


def test_ready_snapshot_is_detached_versioned_and_opaque_to_engine() -> None:
    service = make_ready_service()
    prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())

    assert prepared.status == "judge_required"
    snapshot = service.finalize_turn(prepared, judge_payload=valid_judge_payload())

    assert snapshot.schema_version == 2
    assert snapshot.projection_kind == "normalized_projection"
    assert snapshot.status == "ready"
    assert snapshot.prompt_text
    assert snapshot.trace["artifact_hash"] == "b" * 64
    assert snapshot.snapshot_hash
    assert not hasattr(snapshot, "normalized_model")
    try:
        snapshot.trace["artifact_hash"] = "mutated"
    except TypeError:
        pass
    else:
        raise AssertionError("snapshot trace must be detached and immutable")


def test_persistence_ceiling_makes_denied_projection_volatile_and_visible() -> None:
    from addons.identity_artifacts.policy import EffectiveUseDecision

    service = make_ready_service()
    prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())
    candidate_set = prepared.runtime_state.candidate_set
    without_transient = replace(
        prepared,
        deterministic_record_ids=tuple(
            record_id
            for record_id in prepared.deterministic_record_ids
            if not record_id.startswith("transient:")
        ),
        runtime_state=replace(
            prepared.runtime_state,
            candidate_set=replace(
                candidate_set,
                eligible=tuple(
                    candidate
                    for candidate in candidate_set.eligible
                    if not candidate.record_id.startswith("transient:")
                ),
            ),
        ),
    )

    authorized = service.finalize_turn(
        without_transient,
        judge_payload=valid_judge_payload(),
    )
    assert authorized.persistence_mode == "persistent"
    assert "persistence_notice" not in authorized.trace

    operation_decisions = {
        record_id: dict(decisions)
        for record_id, decisions in without_transient.operation_decisions.items()
    }
    operation_decisions["record:project"]["persistence_export"] = (
        EffectiveUseDecision(
            False,
            (),
            "external_export_not_permitted",
            "Declared policy prohibits persistence/export.",
        )
    )
    denied_prepared = replace(
        without_transient,
        operation_decisions=operation_decisions,
    )
    denied = service.finalize_turn(
        denied_prepared,
        judge_payload=valid_judge_payload(),
    )

    assert denied.status == "ready"
    assert denied.persistence_mode == "volatile"
    notice = denied.trace["persistence_notice"]
    assert notice["prominent"] is True
    assert notice["failure_category"] == "persistence_prohibited"
    assert notice["affected_record_ids"] == ("record:project",)
    assert "Declared policy prohibits" in notice["reason"]

    controller = IdentityArtifactsController(context=None)
    controller.relay_service = service
    controller.finalize_turn(
        {"prepared": denied_prepared, "judge_payload": valid_judge_payload()}
    )
    assert controller._runtime_transparency["status"] == "degraded"
    assert (
        controller._runtime_transparency["notice"]["failure_category"]
        == "persistence_prohibited"
    )


def test_service_authorizes_each_runtime_operation_independently() -> None:
    service = make_ready_service()

    prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())

    assert prepared.status == "judge_required"
    operations = prepared.operation_decisions
    kernel = operations["record:uncertain_self"]
    project = operations["record:project"]
    assert kernel["always_inject"].allowed is True
    assert kernel["private_retrieval"].allowed is False
    assert kernel["provider_transmission"].allowed is True
    assert kernel["embedding_transmission"].allowed is True
    assert project["always_inject"].allowed is False
    assert project["private_retrieval"].allowed is True
    assert project["provider_transmission"].allowed is True
    assert project["embedding_transmission"].allowed is True
    assert project["persistence_export"].allowed is True
    assert project["debug_trace"].allowed is True

    snapshot = service.finalize_turn(prepared, judge_payload=valid_judge_payload())
    assert snapshot.status == "ready"
    assert set(snapshot.effective_use_decisions["record:project"]) == {
        "always_inject",
        "private_retrieval",
        "provider_transmission",
        "embedding_transmission",
        "persistence_export",
        "debug_trace",
    }


def test_snapshot_hash_is_stable_for_identical_projection_content() -> None:
    from addons.identity_artifacts.service import identity_relay_snapshot_hash

    service = make_ready_service()
    prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())

    snapshot = service.finalize_turn(prepared, judge_payload=valid_judge_payload())
    payload = {
        name: getattr(snapshot, name)
        for name in snapshot.__dataclass_fields__
    }
    copied_payload = json.loads(
        json.dumps(
            payload,
            default=lambda value: (
                dict(value) if isinstance(value, Mapping) else str(value)
            ),
        )
    )

    assert identity_relay_snapshot_hash(payload) == snapshot.snapshot_hash
    assert identity_relay_snapshot_hash(copied_payload) == snapshot.snapshot_hash


def test_snapshot_hash_covers_exact_persisted_envelope_content() -> None:
    from addons.identity_artifacts.service import identity_relay_snapshot_hash

    service = make_ready_service()
    prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())
    baseline = service.finalize_turn(prepared, judge_payload=valid_judge_payload())
    payload = {
        name: getattr(baseline, name)
        for name in baseline.__dataclass_fields__
    }
    assert identity_relay_snapshot_hash(payload) == baseline.snapshot_hash

    def mutate(value):
        if isinstance(value, Mapping):
            return {**dict(value), "__integrity_mutation__": "changed"}
        if isinstance(value, tuple):
            return (*value, "__integrity_mutation__")
        if isinstance(value, list):
            return [*value, "__integrity_mutation__"]
        if isinstance(value, bool):
            return not value
        if isinstance(value, int):
            return value + 1
        if isinstance(value, float):
            return value + 1.0
        if value is None:
            return "__integrity_mutation__"
        return f"{value}__integrity_mutation__"

    self_referential_fields = {"snapshot_hash", "authorization_record_id"}
    trusted_fields = set(payload) - self_referential_fields
    assert trusted_fields
    for field_name in sorted(trusted_fields):
        changed = dict(payload)
        changed[field_name] = mutate(changed[field_name])
        assert identity_relay_snapshot_hash(changed) != baseline.snapshot_hash, field_name

    for latency_field in (
        "projection_latency_ms",
        "judge_latency_ms",
        "capacity_latency_ms",
    ):
        changed = dict(payload)
        changed_trace = dict(changed["trace"])
        changed_trace[latency_field] = float(changed_trace.get(latency_field) or 0.0) + 1.0
        changed["trace"] = changed_trace
        assert identity_relay_snapshot_hash(changed) != baseline.snapshot_hash, latency_field

    external_telemetry = {"finalization_wall_clock_ms": 1.0}
    assert "external_telemetry" not in payload
    external_telemetry["finalization_wall_clock_ms"] = 999.0
    assert identity_relay_snapshot_hash(payload) == baseline.snapshot_hash


def test_persisted_snapshot_authorization_is_durable_exact_and_exposure_bound() -> None:
    from addons.identity_artifacts.attestations import (
        IdentityRelaySnapshotAuthorizationStore,
        PersistentSnapshotAuthorization,
        persistent_snapshot_authorization_record_id,
    )

    service = make_ready_service()
    prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())
    candidate_set = prepared.runtime_state.candidate_set
    prepared = replace(
        prepared,
        deterministic_record_ids=tuple(
            record_id
            for record_id in prepared.deterministic_record_ids
            if not record_id.startswith("transient:")
        ),
        runtime_state=replace(
            prepared.runtime_state,
            candidate_set=replace(
                candidate_set,
                eligible=tuple(
                    candidate
                    for candidate in candidate_set.eligible
                    if not candidate.record_id.startswith("transient:")
                ),
            ),
        ),
    )
    with tempfile.TemporaryDirectory() as tmp:
        controller = IdentityArtifactsController(context=None)
        controller.relay_service = service
        controller.snapshot_authorization_store = (
            IdentityRelaySnapshotAuthorizationStore(tmp)
        )

        snapshot = controller.finalize_turn(
            {"prepared": prepared, "judge_payload": valid_judge_payload()}
        )
        snapshot_payload = {
            name: getattr(snapshot, name)
            for name in snapshot.__dataclass_fields__
        }
        authorization = controller.snapshot_authorization_store.load(
            snapshot.authorization_record_id
        )

        assert authorization is not None
        assert (
            authorization.authorization_record_id
            == snapshot.authorization_record_id
        )
        assert authorization.snapshot_hash == snapshot.snapshot_hash
        assert authorization.artifact_ref == snapshot.artifact_ref
        assert authorization.artifact_hash == snapshot.artifact_hash
        assert authorization.attestation_revision == snapshot.attestation_revision
        assert authorization.subject_approved is True
        assert authorization.persistence_allowed is True
        assert authorization.provider_is_remote is False
        assert controller.restore_persisted_snapshot(
            {
                "snapshot": snapshot_payload,
                "frozen_provider": {
                    "provider_name": "new-local-provider",
                    "provider_is_remote": False,
                    "provider_config": {
                        "base_url": "http://127.0.0.1:11434/v1",
                        "provider_is_remote": False,
                    },
                },
            }
        )["authorized"] is True

        tampered = dict(snapshot_payload)
        tampered["prompt_text"] = "tampered"
        assert controller.restore_persisted_snapshot(
            {
                "snapshot": tampered,
                "frozen_provider": {"provider_is_remote": False},
            }
        )["failure_code"] == "persisted_snapshot_hash_mismatch"

        assert controller.restore_persisted_snapshot(
            {
                "snapshot": snapshot_payload,
                "frozen_provider": {"provider_is_remote": True},
            }
        )["failure_code"] == "provider_exposure_not_authorized"

        mismatched_authorization = replace(
            authorization,
            authorization_record_id="",
            artifact_ref=f"library/{'f' * 64}.json",
            artifact_hash="f" * 64,
        )
        mismatched_authorization = replace(
            mismatched_authorization,
            authorization_record_id=persistent_snapshot_authorization_record_id(
                mismatched_authorization
            ),
        )
        controller.snapshot_authorization_store.save(mismatched_authorization)
        mismatched_payload = {
            **snapshot_payload,
            "authorization_record_id": (
                mismatched_authorization.authorization_record_id
            ),
        }
        assert controller.restore_persisted_snapshot(
            {
                "snapshot": mismatched_payload,
                "frozen_provider": {"provider_is_remote": False},
            }
        )["failure_code"] == "persisted_snapshot_authorization_mismatch"

        controller.snapshot_authorization_store.delete(
            snapshot.authorization_record_id
        )
        assert controller.restore_persisted_snapshot(
            {
                "snapshot": snapshot_payload,
                "frozen_provider": {"provider_is_remote": False},
            }
        )["failure_code"] == "persisted_snapshot_authorization_required"


def test_snapshot_authorizations_are_distinct_and_exactly_referenced() -> None:
    def provider_payload(is_remote: bool) -> dict[str, object]:
        return {
            "provider_name": "remote-provider" if is_remote else "local-provider",
            "model_name": "shared-model",
            "provider_is_remote": is_remote,
            "provider_config": {
                "base_url": (
                    "https://remote.example/v1"
                    if is_remote
                    else "http://127.0.0.1:1234/v1"
                ),
                "provider_is_remote": is_remote,
            },
        }

    for order in ((False, True), (True, False)):
        service = make_ready_service()
        prepared = without_transient_candidates(
            service.prepare_turn(service.capture_turn(), make_query_envelope())
        )
        base_snapshot = service.finalize_turn(
            prepared,
            judge_payload=valid_judge_payload(),
        )
        assert base_snapshot.persistence_mode == "persistent"

        with tempfile.TemporaryDirectory() as tmp:
            controller = IdentityArtifactsController(context=None)
            controller.relay_service = service
            controller.snapshot_authorization_store = (
                IdentityRelaySnapshotAuthorizationStore(tmp)
            )
            snapshots = {}
            for is_remote in order:
                runtime_use = {
                    **dict(prepared.capture.runtime_use),
                    "provider_is_remote": is_remote,
                }
                capture = replace(
                    prepared.capture,
                    runtime_use=runtime_use,
                    frozen_provider=provider_payload(is_remote),
                )
                snapshots[is_remote] = controller._persist_snapshot_authorization(
                    base_snapshot,
                    replace(prepared, capture=capture),
                )

            local_snapshot = snapshots[False]
            remote_snapshot = snapshots[True]
            assert local_snapshot.snapshot_hash == remote_snapshot.snapshot_hash
            assert local_snapshot.authorization_record_id
            assert remote_snapshot.authorization_record_id
            assert (
                local_snapshot.authorization_record_id
                != remote_snapshot.authorization_record_id
            )
            local_authorization = controller.snapshot_authorization_store.load(
                local_snapshot.authorization_record_id
            )
            remote_authorization = controller.snapshot_authorization_store.load(
                remote_snapshot.authorization_record_id
            )
            assert local_authorization is not None
            assert remote_authorization is not None
            assert local_authorization.provider_is_remote is False
            assert remote_authorization.provider_is_remote is True
            assert len(tuple(controller.snapshot_authorization_store.authorizations_dir.glob("*.json"))) == 2

            for is_remote, snapshot in snapshots.items():
                payload = {
                    name: getattr(snapshot, name)
                    for name in snapshot.__dataclass_fields__
                }
                restored = controller.restore_persisted_snapshot(
                    {
                        "snapshot": payload,
                        "frozen_provider": provider_payload(is_remote),
                    }
                )
                assert restored["authorized"] is True
                assert (
                    restored["authorization_record_id"]
                    == snapshot.authorization_record_id
                )

            local_payload = {
                name: getattr(local_snapshot, name)
                for name in local_snapshot.__dataclass_fields__
            }
            substituted = {
                **local_payload,
                "authorization_record_id": remote_snapshot.authorization_record_id,
            }
            assert controller.restore_persisted_snapshot(
                {
                    "snapshot": substituted,
                    "frozen_provider": provider_payload(False),
                }
            )["failure_code"] == "provider_exposure_not_authorized"

            missing = dict(local_payload)
            missing.pop("authorization_record_id")
            assert controller.restore_persisted_snapshot(
                {
                    "snapshot": missing,
                    "frozen_provider": provider_payload(False),
                }
            )["failure_code"] == "persisted_snapshot_authorization_reference_required"

            legacy = {
                **local_payload,
                "authorization_record_id": local_snapshot.snapshot_hash,
            }
            assert controller.restore_persisted_snapshot(
                {
                    "snapshot": legacy,
                    "frozen_provider": provider_payload(False),
                }
            )["failure_code"] == "persisted_snapshot_authorization_required"


def test_snapshot_authorization_write_failure_visibly_downgrades_to_volatile() -> None:
    from addons.identity_artifacts.policy import EffectiveUseDecision

    service = make_ready_service()
    renderer = service._projection_renderer

    def render_with_authorized_framing(*args):
        projection = renderer(*args)
        return replace(
            projection,
            prompt_text=(
                projection.prompt_text
                + "\n[Authorized confidence, qualification, tension, provenance, and policy framing.]"
            ),
        )

    service._projection_renderer = render_with_authorized_framing
    prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())
    candidate_set = prepared.runtime_state.candidate_set
    prepared = replace(
        prepared,
        deterministic_record_ids=tuple(
            record_id
            for record_id in prepared.deterministic_record_ids
            if not record_id.startswith("transient:")
        ),
        runtime_state=replace(
            prepared.runtime_state,
            candidate_set=replace(
                candidate_set,
                eligible=tuple(
                    candidate
                    for candidate in candidate_set.eligible
                    if not candidate.record_id.startswith("transient:")
                ),
            ),
        ),
    )
    operation_decisions = {
        record_id: dict(decisions)
        for record_id, decisions in prepared.operation_decisions.items()
    }
    for decisions in operation_decisions.values():
        decisions["debug_trace"] = EffectiveUseDecision(
            False,
            (),
            "exposure_not_permitted",
            "Debug trace exposure is denied.",
        )
    prepared = replace(prepared, operation_decisions=operation_decisions)

    class FailingAuthorizationStore:
        def save(self, _authorization):
            raise OSError("disk unavailable")

    before_failure = service.finalize_turn(
        prepared,
        judge_payload=valid_judge_payload(),
    )
    expected_prompt_bytes = before_failure.prompt_text.encode("utf-8")
    assert b"Authorized confidence" in expected_prompt_bytes

    controller = IdentityArtifactsController(context=None)
    controller.relay_service = service
    controller.snapshot_authorization_store = FailingAuthorizationStore()
    snapshot = controller.finalize_turn(
        {"prepared": prepared, "judge_payload": valid_judge_payload()}
    )

    assert snapshot.status == "ready"
    assert snapshot.persistence_mode == "volatile"
    assert snapshot.snapshot_hash
    assert snapshot.prompt_text.encode("utf-8") == expected_prompt_bytes
    notice = snapshot.trace["persistence_notice"]
    assert notice["prominent"] is True
    assert notice["failure_category"] == "persistence_authorization_store_failed"
    assert "redacted" in notice["reason"].casefold()
    assert controller._runtime_transparency["status"] == "degraded"


def test_debug_trace_policy_enforces_deny_redact_and_allow_boundaries() -> None:
    from addons.identity_artifacts.policy import EffectiveUseDecision

    service = make_ready_service()
    prepared = without_transient_candidates(
        service.prepare_turn(service.capture_turn(), make_query_envelope())
    )

    def finalize_with_debug(decision):
        operation_decisions = {
            record_id: dict(decisions)
            for record_id, decisions in prepared.operation_decisions.items()
        }
        for decisions in operation_decisions.values():
            decisions["debug_trace"] = decision
        batch = prepared.judge_batches[0]
        return service.finalize_turn(
            replace(prepared, operation_decisions=operation_decisions),
            judge_payload={
                batch.batch_id: {
                    "failure_category": "provider_exception",
                    "reason": (
                        "RuntimeError: record:correction policy_internal=secret-token"
                    ),
                }
            },
        )

    allowed = finalize_with_debug(
        EffectiveUseDecision(True, ("debug_trace",), "allowed", "allowed")
    )
    assert allowed.trace["debug_trace_mode"] == "allow"
    assert allowed.trace["artifact_ref"] == allowed.artifact_ref
    allowed_notice = allowed.trace["degradation_notice"]
    assert allowed_notice["provider"] == "frozen-provider"
    assert allowed_notice["model"] == "frozen-model"
    assert allowed_notice["failure_category"] == "provider_exception"
    assert allowed_notice["affected_record_ids"] == ("record:correction",)
    assert "secret-token" not in allowed_notice["reason"]
    assert allowed.effective_use_decisions

    redacted = finalize_with_debug(
        EffectiveUseDecision(
            True,
            ("debug_trace",),
            "allowed_narrowed",
            "Debug trace exposure is allowed only in redacted form.",
        )
    )
    assert redacted.trace["debug_trace_mode"] == "redact"
    assert "artifact_ref" not in redacted.trace
    assert "policy_decisions" not in redacted.trace
    assert redacted.effective_use_decisions == {}
    redacted_notice = redacted.trace["degradation_notice"]
    assert redacted_notice["provider"] == "frozen-provider"
    assert redacted_notice["model"] == "frozen-model"
    assert redacted_notice["failure_category"] == "provider_exception"
    assert redacted_notice["affected_record_ids"] == ("[redacted]",)
    assert "optional" in redacted_notice["reason"].casefold()
    assert "record IDs" in redacted_notice["redaction_reason"]
    assert "secret-token" not in repr(redacted_notice)

    denied = finalize_with_debug(
        EffectiveUseDecision(
            False,
            (),
            "exposure_not_permitted",
            "Debug trace exposure is denied.",
        )
    )
    assert denied.trace["debug_trace_mode"] == "deny"
    assert set(denied.trace).issubset(
        {"debug_trace_mode", "redaction_reason", "degradation_notice", "persistence_notice"}
    )
    assert denied.effective_use_decisions == {}
    denied_notice = denied.trace["degradation_notice"]
    assert denied_notice["provider"] == "frozen-provider"
    assert denied_notice["model"] == "frozen-model"
    assert denied_notice["failure_category"] == "provider_exception"
    assert denied_notice["affected_record_ids"] == ("[redacted]",)
    assert "record IDs" in denied_notice["redaction_reason"]
    assert "secret-token" not in repr(denied_notice)


def test_capacity_failure_externalizes_debug_policy_for_every_mode() -> None:
    import addons.identity_artifacts.service as service_module
    from addons.identity_artifacts.policy import EffectiveUseDecision

    modes = {
        "deny": EffectiveUseDecision(
            False,
            (),
            "exposure_not_permitted",
            "Debug trace exposure is denied.",
        ),
        "redact": EffectiveUseDecision(
            True,
            ("debug_trace",),
            "allowed_narrowed",
            "Debug trace exposure is allowed only in redacted form.",
        ),
        "allow": EffectiveUseDecision(
            True,
            ("debug_trace",),
            "allowed",
            "Debug trace exposure is allowed.",
        ),
    }
    sensitive_values = (
        "record:uncertain_self",
        "record:project",
        "record:correction",
        "transient:session",
        "frozen-provider",
        "frozen-model",
        "quarantine-internal",
        "review:correction",
        "quarantine:invalid",
        "invalid_attribution",
    )

    for mode, debug_decision in modes.items():
        service = make_ready_service()
        prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())
        operation_decisions = {
            record_id: dict(decisions)
            for record_id, decisions in prepared.operation_decisions.items()
        }
        for decisions in operation_decisions.values():
            decisions["debug_trace"] = debug_decision
        operation_decisions["transient:session"] = {
            "debug_trace": debug_decision,
        }
        prepared = replace(prepared, operation_decisions=operation_decisions)
        render = service._projection_renderer

        def render_with_nested_ids(*args, **kwargs):
            projection = render(*args, **kwargs)
            trace = {
                name: getattr(projection.trace, name)
                for name in projection.trace.__dataclass_fields__
            }
            trace["nested"] = {
                "affected_record_ids": (
                    "record:correction",
                    "transient:session",
                ),
                "review_state": "quarantine-internal",
            }
            return replace(
                projection,
                trace=trace,
            )

        service._projection_renderer = render_with_nested_ids
        capacity_check = service_module.check_projection_capacity
        service_module.check_projection_capacity = (
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("capacity checker unavailable")
            )
        )
        try:
            snapshot = service.finalize_turn(
                prepared,
                judge_payload=valid_judge_payload(),
            )
        finally:
            service_module.check_projection_capacity = capacity_check

        assert snapshot.status == "blocked"
        assert snapshot.failure_code == "capacity_check_failed"
        assert snapshot.persistence_mode == "volatile"
        assert snapshot.trace["debug_trace_mode"] == mode
        notice = snapshot.trace["degradation_notice"]
        assert notice["failure_category"] == "capacity_check_failed"
        if mode == "allow":
            assert notice["provider"] == "frozen-provider", (
                notice,
                service._exact_debug_record_ids(prepared),
                service._metadata_record_ids(
                    snapshot.trace,
                    known_record_ids=service._known_record_ids(prepared),
                ),
            )
            assert notice["model"] == "frozen-model"
            assert "record:correction" in notice["affected_record_ids"]
            assert snapshot.transient_state
            assert snapshot.effective_use_decisions
            assert "quarantine-internal" in repr(snapshot)
        else:
            assert notice["provider"] == "[redacted]"
            assert notice["model"] == "[redacted]"
            assert notice["affected_record_ids"] == ("[redacted]",)
            assert "redacted" in notice["reason"].casefold()
            assert snapshot.transient_state == {}
            assert snapshot.effective_use_decisions == {}
            serialized = repr(snapshot)
            for sensitive in sensitive_values:
                assert sensitive not in serialized, (mode, sensitive, serialized)


def test_capacity_denial_externalizes_debug_policy_for_every_mode() -> None:
    import addons.identity_artifacts.service as service_module
    from addons.identity_artifacts.policy import EffectiveUseDecision
    from addons.identity_artifacts.projection import CapacityDecision

    modes = {
        "deny": EffectiveUseDecision(
            False,
            (),
            "exposure_not_permitted",
            "Debug trace exposure is denied.",
        ),
        "redact": EffectiveUseDecision(
            True,
            ("debug_trace",),
            "allowed_narrowed",
            "Debug trace exposure is allowed only in redacted form.",
        ),
        "allow": EffectiveUseDecision(
            True,
            ("debug_trace",),
            "allowed",
            "Debug trace exposure is allowed.",
        ),
    }
    sensitive_values = (
        "record:uncertain_self",
        "record:project",
        "record:correction",
        "transient:session",
        "frozen-provider",
        "frozen-model",
        "quarantine-internal",
        "review:correction",
        "quarantine:invalid",
        "invalid_attribution",
    )

    for mode, debug_decision in modes.items():
        service = make_ready_service()
        prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())
        operation_decisions = {
            record_id: dict(decisions)
            for record_id, decisions in prepared.operation_decisions.items()
        }
        for decisions in operation_decisions.values():
            decisions["debug_trace"] = debug_decision
        operation_decisions["transient:session"] = {
            "debug_trace": debug_decision,
        }
        prepared = replace(
            prepared,
            operation_decisions=operation_decisions,
            model_context_limit=4,
            reserved_output_tokens=1,
        )
        capacity_decisions = []
        capacity_check = service_module.check_projection_capacity

        def recording_capacity_check(*args, **kwargs):
            decision = capacity_check(*args, **kwargs)
            capacity_decisions.append(decision)
            return decision

        service_module.check_projection_capacity = recording_capacity_check
        try:
            snapshot = service.finalize_turn(
                prepared,
                judge_payload=valid_judge_payload(),
            )
        finally:
            service_module.check_projection_capacity = capacity_check

        assert len(capacity_decisions) == 1
        assert isinstance(capacity_decisions[0], CapacityDecision)
        assert capacity_decisions[0].allowed is False
        assert capacity_decisions[0].failure_code == "projection_too_large"
        assert snapshot.status == "blocked"
        assert snapshot.failure_code == "projection_too_large"
        assert snapshot.prompt_text == ""
        assert snapshot.persistence_mode == "volatile"
        assert snapshot.authorization_record_id == ""
        assert snapshot.trace["debug_trace_mode"] == mode
        notice = snapshot.trace["degradation_notice"]
        assert notice["failure_category"] == "projection_too_large"
        if mode == "allow":
            assert notice["provider"] == "frozen-provider"
            assert notice["model"] == "frozen-model"
            assert "record:correction" in notice["affected_record_ids"]
            assert snapshot.transient_state
            assert snapshot.effective_use_decisions
            assert snapshot.kernel_record_ids
            assert snapshot.trace["review_reasons"]
            assert snapshot.trace["quarantine_reasons"]
        else:
            assert notice["provider"] == "[redacted]"
            assert notice["model"] == "[redacted]"
            assert notice["affected_record_ids"] == ("[redacted]",)
            assert "redacted" in notice["reason"].casefold()
            assert snapshot.transient_state == {}
            assert snapshot.effective_use_decisions == {}
            assert snapshot.kernel_record_ids == ()
            assert snapshot.selected_record_ids == ()
            assert snapshot.selection_reasons == {}
            assert snapshot.signals_considered == {}
            assert snapshot.unresolved_record_ids == ()
            serialized = repr(snapshot)
            for sensitive in sensitive_values:
                assert sensitive not in serialized, (mode, sensitive, serialized)


def test_authorization_store_failure_externalizes_debug_policy_once() -> None:
    from addons.identity_artifacts.policy import EffectiveUseDecision

    modes = {
        "deny": EffectiveUseDecision(
            False,
            (),
            "exposure_not_permitted",
            "Debug trace exposure is denied.",
        ),
        "redact": EffectiveUseDecision(
            True,
            ("debug_trace",),
            "allowed_narrowed",
            "Debug trace exposure is allowed only in redacted form.",
        ),
        "allow": EffectiveUseDecision(
            True,
            ("debug_trace",),
            "allowed",
            "Debug trace exposure is allowed.",
        ),
    }
    sensitive_values = (
        "record:uncertain_self",
        "record:project",
        "record:correction",
        "frozen-provider",
        "frozen-model",
        "quarantine-internal",
    )

    class FailingAuthorizationStore:
        def save(self, _authorization):
            raise OSError("disk unavailable")

    for mode, debug_decision in modes.items():
        service = make_ready_service()
        service._token_counter = None
        prepared = without_transient_candidates(
            service.prepare_turn(service.capture_turn(), make_query_envelope())
        )
        operation_decisions = {
            record_id: dict(decisions)
            for record_id, decisions in prepared.operation_decisions.items()
        }
        for decisions in operation_decisions.values():
            decisions["debug_trace"] = debug_decision
        prepared = replace(prepared, operation_decisions=operation_decisions)
        render = service._projection_renderer

        def render_with_nested_ids(*args, **kwargs):
            projection = render(*args, **kwargs)
            trace = {
                name: getattr(projection.trace, name)
                for name in projection.trace.__dataclass_fields__
            }
            trace["nested"] = {
                "affected_record_ids": ("record:correction",),
                "review_state": "quarantine-internal",
            }
            return replace(
                projection,
                trace=trace,
            )

        service._projection_renderer = render_with_nested_ids
        controller = IdentityArtifactsController(context=None)
        controller.relay_service = service
        controller.snapshot_authorization_store = FailingAuthorizationStore()
        snapshot = controller.finalize_turn(
            {"prepared": prepared, "judge_payload": valid_judge_payload()}
        )

        assert snapshot.status == "ready"
        assert snapshot.persistence_mode == "volatile"
        assert snapshot.trace["debug_trace_mode"] == mode
        notice = snapshot.trace["persistence_notice"]
        assert notice["failure_category"] == "persistence_authorization_store_failed"
        if mode == "allow":
            assert notice["provider"] == "frozen-provider"
            assert notice["model"] == "frozen-model"
            assert "record:correction" in notice["affected_record_ids"]
            assert "quarantine-internal" in repr(snapshot)
        else:
            assert notice["provider"] == "[redacted]"
            assert notice["model"] == "[redacted]"
            assert notice["affected_record_ids"] == ("[redacted]",)
            assert "redacted" in notice["reason"].casefold()
            assert snapshot.transient_state == {}
            assert snapshot.effective_use_decisions == {}
            assert "I may be pattern-continuous" in snapshot.prompt_text
            assert "Identity Relay v0.1 remains an active project" in snapshot.prompt_text
            serialized = repr(replace(snapshot, prompt_text=""))
            for sensitive in sensitive_values:
                assert sensitive not in serialized, (mode, sensitive, serialized)


def test_empty_projection_never_defaults_to_persistent() -> None:
    service = make_ready_service()
    prepared = without_transient_candidates(
        service.prepare_turn(service.capture_turn(), make_query_envelope())
    )
    renderer = service._projection_renderer

    def render_empty(*args, **kwargs):
        projection = renderer(*args, **kwargs)
        return replace(projection, prompt_text="")

    service._projection_renderer = render_empty
    snapshot = service.finalize_turn(
        prepared,
        judge_payload=valid_judge_payload(),
    )

    assert snapshot.status == "ready"
    assert snapshot.prompt_text == ""
    assert snapshot.persistence_mode == "volatile"
    notice = snapshot.trace["persistence_notice"]
    assert notice["failure_category"] == "persistence_prohibited"
    assert "empty" in notice["reason"].casefold()


def test_trace_and_decision_metadata_require_persistence_authorization() -> None:
    from addons.identity_artifacts.policy import EffectiveUseDecision

    service = make_ready_service()
    prepared = without_transient_candidates(
        service.prepare_turn(service.capture_turn(), make_query_envelope())
    )
    operation_decisions = {
        record_id: dict(decisions)
        for record_id, decisions in prepared.operation_decisions.items()
    }
    operation_decisions["record:correction"]["persistence_export"] = (
        EffectiveUseDecision(
            False,
            (),
            "external_export_not_permitted",
            "Trace metadata for this record is not authorized for persistence.",
        )
    )
    judge_payload = json.dumps(
        {
            "record_ids": [],
            "reasons": {},
            "signals_considered": {},
            "unresolved_record_ids": [],
        }
    )

    snapshot = service.finalize_turn(
        replace(prepared, operation_decisions=operation_decisions),
        judge_payload=judge_payload,
    )

    assert "record:correction" not in snapshot.selected_record_ids
    assert "record:correction" in snapshot.trace["judge_batches"][0]
    assert snapshot.persistence_mode == "volatile"
    notice = snapshot.trace["persistence_notice"]
    assert "record:correction" in notice["affected_record_ids"]
    assert "Trace metadata" in notice["reason"]


def test_finalize_accepts_structured_judge_payload_with_task4_validation() -> None:
    service = make_ready_service()
    prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())

    snapshot = service.finalize_turn(
        prepared,
        judge_payload=json.loads(valid_judge_payload()),
    )

    assert "record:correction" in snapshot.selected_record_ids
    assert snapshot.selection_reasons["record:correction"].startswith(
        "The explicit correction"
    )


def test_judge_exception_degrades_visibly_without_dropping_deterministic_matches() -> None:
    service = make_ready_service()
    prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())
    batch = prepared.judge_batches[0]

    snapshot = service.finalize_turn(
        prepared,
        judge_payload={
            batch.batch_id: {
                "failure_category": "provider_exception",
                "reason": "RuntimeError: judge transport failed",
                "affected_record_ids": batch.candidate_ids,
            }
        },
    )

    assert snapshot.status == "ready"
    assert "record:project" in snapshot.selected_record_ids
    assert "record:correction" not in snapshot.selected_record_ids
    assert "record:correction" in snapshot.unresolved_record_ids
    notice = snapshot.trace["degradation_notice"]
    assert notice["prominent"] is True
    assert notice["provider"] == "frozen-provider"
    assert notice["model"] == "frozen-model"
    assert notice["failure_category"] == "provider_exception"
    assert notice["affected_record_ids"] == ("record:correction",)
    assert "optional" in notice["reason"].casefold()
    assert "judge transport failed" not in notice["reason"]


def test_malformed_and_unknown_judge_ids_degrade_without_authorizing_them() -> None:
    service = make_ready_service()
    prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())

    malformed = service.finalize_turn(prepared, judge_payload="not-json")
    assert malformed.status == "ready"
    assert "record:project" in malformed.selected_record_ids
    assert "record:correction" not in malformed.selected_record_ids
    assert malformed.unresolved_record_ids == ("record:correction",)
    assert malformed.trace["degradation_notice"]["failure_category"] == "invalid_json"

    unknown = service.finalize_turn(
        prepared,
        judge_payload=json.dumps(
            {
                "record_ids": ["record:unknown"],
                "reasons": {"record:unknown": "claimed relevant"},
                "signals_considered": {"record:unknown": ["semantic_fallback"]},
                "unresolved_record_ids": [],
            }
        ),
    )
    assert unknown.status == "ready"
    assert "record:project" in unknown.selected_record_ids
    assert "record:unknown" not in unknown.selected_record_ids
    assert unknown.trace["invalid_record_ids"] == ("[redacted]",)
    notice = unknown.trace["degradation_notice"]
    assert notice["provider"] == "frozen-provider"
    assert notice["model"] == "frozen-model"
    assert notice["failure_category"] == "unknown_record_ids"
    assert notice["affected_record_ids"] == ("[redacted]",)
    assert "record IDs" in notice["redaction_reason"]


def test_controller_surfaces_judge_degradation_notice_payload() -> None:
    service = make_ready_service()
    prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())
    controller = IdentityArtifactsController(context=None)
    controller.relay_service = service

    snapshot = controller.finalize_turn(
        {"prepared": prepared, "judge_payload": "not-json"}
    )

    assert snapshot.status == "ready"
    runtime = controller._runtime_transparency
    assert runtime["status"] == "degraded"
    notice = runtime["notice"]
    assert notice["prominent"] is True
    assert notice["provider"] == "frozen-provider"
    assert notice["model"] == "frozen-model"
    assert "invalid_json" in notice["failure_category"]
    assert "record:correction" in notice["affected_record_ids"]
    assert "invalid" in notice["reason"].casefold()
    assert "redaction_reason" not in notice

    messages = []
    controller._show_trace_message = (
        lambda title, summary, details: messages.append((title, summary, details))
    )
    controller._show_local_trace()
    title, summary, details = messages[-1]
    assert title == "Identity Relay Trace"
    assert "Identity Relay remained active" in summary
    assert "Provider: frozen-provider" in details
    assert "Model: frozen-model" in details
    assert "failure_category: invalid_json" in details
    assert "record:correction" in details
    assert "RAW RELEVANCE JUDGE RESULT" in details
    assert "not-json" in details


def test_controller_owner_trace_keeps_exact_local_projection_details() -> None:
    service = make_ready_service()
    prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())
    prepared = replace(
        prepared,
        omitted_kernel_record_ids=("record:correction",),
    )
    snapshot = service.finalize_turn(
        prepared,
        judge_payload=json.loads(valid_judge_payload()),
    )
    controller = IdentityArtifactsController(context=None)

    owner_trace = controller._owner_trace_payload(prepared, snapshot)

    assert owner_trace["provider"] == "frozen-provider"
    assert owner_trace["model"] == "frozen-model"
    assert owner_trace["kernel_total_count"] == 2
    assert owner_trace["kernel_active_count"] == 1
    assert owner_trace["kernel_omitted_count"] == 1
    assert owner_trace["selected_count"] == 3
    assert (
        owner_trace["active_kernel_records"][0]["record_id"]
        == "record:uncertain_self"
    )
    omitted = owner_trace["omitted_kernel_records"][0]
    assert omitted["record_id"] == "record:correction"
    assert omitted["source_text"]
    assert omitted["policy_reason"]
    selected = {
        item["record_id"]: item for item in owner_trace["selected_records"]
    }
    assert selected["record:correction"]["selection_reason"]
    assert selected["record:correction"]["signals_considered"]
    assert selected["transient:session"]["source_text"]


def test_controller_owner_trace_dialog_is_useful_without_redacted_placeholders() -> None:
    service = make_ready_service()
    prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())
    prepared = replace(
        prepared,
        omitted_kernel_record_ids=("record:correction",),
    )
    controller = IdentityArtifactsController(context=None)
    controller.relay_service = service
    snapshot = controller.finalize_turn(
        {
            "prepared": prepared,
            "judge_payload": json.loads(valid_judge_payload()),
        }
    )

    messages = []
    controller._show_trace_message = (
        lambda title, summary, details: messages.append((title, summary, details))
    )
    controller._show_local_trace()

    title, summary, details = messages[-1]
    assert title == "Identity Relay Trace"
    assert "1 of 2 stable records active" in summary
    assert "1 omitted" in summary
    assert "3 deeper records selected" in summary
    assert "record:correction" in details
    assert "record:uncertain_self" in details
    assert "[redacted]" not in summary
    assert "[redacted]" not in details


def test_controller_trace_dialog_recurses_ids_and_labels_redacted_fields() -> None:
    controller = IdentityArtifactsController(context=None)
    nested_trace = {
        "outer": {
            "trace_id": "trace:nested",
            "events": (
                {
                    "affected_record_ids": (
                        "record:nested-one",
                        "record:nested-two",
                    )
                },
            ),
        }
    }

    assert controller._trace_ids(nested_trace) == (
        "trace:nested",
        "record:nested-one",
        "record:nested-two",
    )

    controller.update_runtime_transparency(
        status="degraded",
        reason="Policy-redacted judge degradation.",
        trace_ids=controller._trace_ids(nested_trace),
        notice={
            "prominent": True,
            "provider": "frozen-provider",
            "model": "frozen-model",
            "failure_category": "provider_exception",
            "affected_record_ids": ("[redacted]",),
            "reason": "Optional identity relevance judging failed.",
            "redaction_reason": "Affected record IDs are redacted by effective policy.",
        },
    )
    messages = []
    controller._show_trace_message = (
        lambda title, summary, details: messages.append((title, summary, details))
    )
    controller._show_local_trace()
    summary = messages[-1][1]
    assert "Provider: frozen-provider" in summary
    assert "Model: frozen-model" in summary
    assert "Failure category: provider_exception" in summary
    assert "Affected record IDs: [redacted]" in summary
    assert "Redaction: Affected record IDs are redacted by effective policy." in summary


def test_remote_frozen_provider_locality_survives_authority_validation() -> None:
    from dataclasses import replace

    from addons.identity_artifacts.judge import build_judge_batches
    from addons.identity_artifacts.retrieval import CandidateActivation, CandidateSet
    from addons.identity_artifacts.service import IdentityRelayService
    from addons.identity_artifacts.smoke_identity_relay_projection import _model

    original = _model()
    records = tuple(
        replace(
            record,
            declared_policy={
                **record.declared_policy,
                "allowed_surfaces": ("local_private_chat",),
                "allow_remote_provider": True,
            },
            exposure_policy={
                **record.exposure_policy,
                "private_remote_1on1": "allow",
            },
        )
        if record.record_id != "record:project"
        else record
        for record in original.records
    )
    normalized = replace(original, records=records)
    relay_model = IdentityRelayModel()
    relay_model.set_connection(
        ArtifactResolution(
            f"library/{normalized.envelope.artifact_hash}.json",
            normalized.envelope.artifact_hash,
            "Legacy continuity",
            None,
        )
    )
    frozen_provider = {"provider_config": {"provider_is_remote": True}}
    relay_model.set_capture_context(
        normalizer_revision=normalized.normalizer_revision,
        normalized_digest=normalized_identity_digest(normalized),
        attestation_revision=2,
        transient_activation={},
        runtime_use={
            "connected": True,
            "surface": "local_private_chat",
            "provider_is_remote": True,
            "subject_class": "assistant_self",
            "subject_approved": True,
            "review_decisions": {"review:correction": "approved_for_private_chat"},
        },
        frozen_provider=frozen_provider,
        frozen_normalized_model=normalized.to_dict(),
        frozen_model_digest=normalized_identity_digest(normalized),
    )
    frozen_provider["provider_config"]["provider_is_remote"] = False

    class FakeStore:
        def load_normalized(self, _artifact_ref):
            return normalized

        def load_identity_relay_authority(self, artifact_ref):
            authority = _authority_for_capture(relay_model, artifact_ref)
            return {
                **authority,
                "runtime_use": {
                    "connected": True,
                    "subject_class": "assistant_self",
                    "subject_approved": True,
                    "review_decisions": {
                        "review:correction": "approved_for_private_chat"
                    },
                },
            }

    def unsafe_retriever(_model, _query, _decisions, _transients, _hits):
        return CandidateSet(
            eligible=(
                CandidateActivation(
                    "record:project",
                    ("semantic_fallback",),
                    False,
                    {"semantic_fallback": 0.8},
                    "incorrectly_allowed",
                ),
                CandidateActivation(
                    "record:correction",
                    ("semantic_fallback",),
                    False,
                    {"semantic_fallback": 0.7},
                    "allowed",
                ),
            ),
            denied_record_ids=(),
            semantic_available=True,
            semantic_reason="available",
        )

    service = IdentityRelayService(
        relay_model,
        store=FakeStore(),
        candidate_retriever=unsafe_retriever,
        judge_renderer=build_judge_batches,
    )
    capture = service.capture_turn()
    assert capture.frozen_provider["provider_config"]["provider_is_remote"] is True
    assert capture.runtime_use["provider_is_remote"] is True
    prepared = service.prepare_turn(capture, make_query_envelope())

    assert prepared.status == "judge_required"
    assert tuple(item.record_id for item in prepared.candidate_set.eligible) == (
        "record:correction",
    )
    judge_text = "\n".join(batch.prompt_text for batch in prepared.judge_batches)
    assert "record:project" not in judge_text
    assert "Identity Relay v0.1 remains an active project." not in judge_text

    missing_locality = relay_model.capture_turn(frozen_provider={})
    assert missing_locality.runtime_use["provider_is_remote"] is None
    missing_prepared = service.prepare_turn(missing_locality, make_query_envelope())
    assert missing_prepared.status == "blocked"
    assert missing_prepared.failure_code == "provider_locality_required"


def test_accepted_turn_uses_frozen_authority_before_prepare_and_during_judge() -> None:
    service = make_ready_service()
    renderer = service._projection_renderer

    def deterministic_renderer(*args):
        projection = renderer(*args)
        return replace(
            projection,
            trace=replace(projection.trace, projection_latency_ms=0.0),
        )

    service._projection_renderer = deterministic_renderer
    service._token_counter = None
    capture = service.capture_turn()
    query = make_query_envelope()
    baseline_prepared = service.prepare_turn(capture, query)
    baseline_snapshot = service.finalize_turn(
        baseline_prepared,
        judge_payload=valid_judge_payload(),
    )
    original_model = baseline_prepared.normalized_model
    assert original_model is not None

    mutated_model = replace(
        original_model,
        records=tuple(
            replace(
                record,
                source_text=f"MUTATED AFTER ACCEPTANCE: {record.record_id}",
                review_state="quarantined",
            )
            for record in original_model.records
        ),
        transient_records=tuple(
            replace(
                record,
                source_text=f"MUTATED TRANSIENT: {record.record_id}",
                review_state="quarantined",
            )
            for record in original_model.transient_records
        ),
        kernel_record_ids=(),
        retrievable_record_ids=(),
    )
    reads = {"normalized": 0, "authority": 0}

    class MutatedLiveStore:
        def load_normalized(self, _artifact_ref):
            reads["normalized"] += 1
            return mutated_model

        def load_identity_relay_authority(self, _artifact_ref):
            reads["authority"] += 1
            return {
                "artifact_hash": capture.artifact_hash,
                "normalizer_revision": capture.normalizer_revision,
                "normalized_digest": "mutated-digest",
                "attestation_revision": capture.attestation_revision + 100,
                "runtime_use": {
                    "connected": False,
                    "subject_approved": False,
                    "subject_class": "other_entity",
                    "review_decisions": {"review:correction": "quarantined"},
                    "review_decision_revisions": {"review:correction": 999},
                },
                "transient_activation": {
                    "transient:session": {
                        "active": False,
                        "review_required": True,
                        "reason_code": "mutated_after_acceptance",
                        "revision": 999,
                    }
                },
            }

    service._store = MutatedLiveStore()
    service._relay_model.set_connection(None)

    prepared = service.prepare_turn(capture, query)
    assert prepared.status == baseline_prepared.status
    assert prepared.normalized_model == baseline_prepared.normalized_model

    service._relay_model.set_connection(
        ArtifactResolution(
            "library/" + "f" * 64 + ".json",
            "f" * 64,
            "Changed connection during judge",
            None,
        )
    )
    snapshot = service.finalize_turn(prepared, judge_payload=valid_judge_payload())

    assert snapshot == baseline_snapshot
    assert snapshot.snapshot_hash == baseline_snapshot.snapshot_hash
    assert snapshot.prompt_text.encode("utf-8") == baseline_snapshot.prompt_text.encode(
        "utf-8"
    )
    assert reads == {"normalized": 0, "authority": 0}


def test_unapproved_subject_blocks_before_retrieval_or_judge_rendering() -> None:
    from addons.identity_artifacts.service import IdentityRelayService
    from addons.identity_artifacts.smoke_identity_relay_projection import _model

    normalized = _model()
    relay_model = IdentityRelayModel()
    relay_model.set_connection(
        ArtifactResolution(
            f"library/{normalized.envelope.artifact_hash}.json",
            normalized.envelope.artifact_hash,
            "Legacy continuity",
            None,
        )
    )
    relay_model.set_capture_context(
        normalizer_revision=normalized.normalizer_revision,
        normalized_digest=normalized_identity_digest(normalized),
        attestation_revision=0,
        transient_activation={},
        runtime_use={
            "surface": "chat",
            "provider_is_remote": False,
            "subject_class": "unknown",
            "subject_approved": False,
        },
        frozen_provider={},
        frozen_normalized_model=normalized.to_dict(),
        frozen_model_digest=normalized_identity_digest(normalized),
    )
    counters = {"retrieve": 0, "judge": 0}

    class FakeStore:
        def load_normalized(self, _artifact_ref):
            return normalized

        def load_identity_relay_authority(self, artifact_ref):
            return _authority_for_capture(relay_model, artifact_ref)

    def retrieve(*_args):
        counters["retrieve"] += 1
        raise AssertionError("unapproved subject must not reach retrieval")

    def judge(*_args, **_kwargs):
        counters["judge"] += 1
        raise AssertionError("unapproved subject must not reach judge rendering")

    service = IdentityRelayService(
        relay_model,
        store=FakeStore(),
        candidate_retriever=retrieve,
        judge_renderer=judge,
    )
    prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())

    assert prepared.status == "blocked"
    assert prepared.failure_code == "assistant_self_attestation_required"
    assert counters == {"retrieve": 0, "judge": 0}


def test_deterministic_candidates_bypass_judge_request_rendering() -> None:
    from addons.identity_artifacts.retrieval import CandidateActivation, CandidateSet
    from addons.identity_artifacts.service import IdentityRelayService
    from addons.identity_artifacts.smoke_identity_relay_projection import _model

    normalized = _model()
    relay_model = IdentityRelayModel()
    relay_model.set_connection(
        ArtifactResolution(
            f"library/{normalized.envelope.artifact_hash}.json",
            normalized.envelope.artifact_hash,
            "Legacy continuity",
            None,
        )
    )
    relay_model.set_capture_context(
        normalizer_revision=normalized.normalizer_revision,
        normalized_digest=normalized_identity_digest(normalized),
        attestation_revision=1,
        transient_activation={},
        runtime_use={
            "surface": "chat",
            "provider_is_remote": False,
            "subject_class": "assistant_self",
            "subject_approved": True,
        },
        frozen_provider={},
        frozen_normalized_model=normalized.to_dict(),
        frozen_model_digest=normalized_identity_digest(normalized),
    )
    judge_calls = []

    class FakeStore:
        def load_normalized(self, _artifact_ref):
            return normalized

        def load_identity_relay_authority(self, artifact_ref):
            return _authority_for_capture(relay_model, artifact_ref)

    def retrieve(*_args):
        return CandidateSet(
            eligible=(
                CandidateActivation(
                    "record:project",
                    ("project_thread",),
                    True,
                    {"project_thread": 2.5},
                    "allowed",
                ),
            ),
            denied_record_ids=(),
            semantic_available=False,
            semantic_reason="not_needed",
        )

    def judge(*_args, **_kwargs):
        judge_calls.append(True)
        raise AssertionError("deterministic candidates must bypass judge rendering")

    service = IdentityRelayService(
        relay_model,
        store=FakeStore(),
        candidate_retriever=retrieve,
        judge_renderer=judge,
    )
    prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())

    assert prepared.status == "ready_without_judge"
    assert prepared.deterministic_record_ids == ("record:project",)
    assert judge_calls == []


def _assert_blocked_degradation(result, failure_code: str) -> None:
    assert result.status == "blocked"
    assert result.failure_code == failure_code
    assert result.trace["degradation_state"] == "blocked"
    assert failure_code in result.trace["degradation_reasons"]


def test_candidate_retrieval_exception_becomes_blocked_prepared_result() -> None:
    service = make_ready_service()
    service._candidate_retriever = lambda *_args: (_ for _ in ()).throw(
        RuntimeError("candidate retrieval failed")
    )

    prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())

    _assert_blocked_degradation(prepared, "candidate_retrieval_failed")


def test_semantic_embedding_and_index_exceptions_degrade_without_losing_deterministic_matches() -> None:
    class FailingEmbedding:
        def embed(self, *_args, **_kwargs):
            raise RuntimeError("embedding failed")

    class GoodEmbedding:
        def embed(self, *_args, **_kwargs):
            return ((1.0, 0.0),)

    class FailingIndex:
        def search(self, *_args, **_kwargs):
            raise RuntimeError("index failed")

    for embedding, index in (
        (FailingEmbedding(), SimpleNamespace(search=lambda *_args, **_kwargs: ())),
        (GoodEmbedding(), FailingIndex()),
    ):
        service = make_ready_service()
        service._embedding = embedding
        service._index = index

        prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())

        assert prepared.status == "judge_required"
        assert prepared.failure_code == ""
        assert prepared.candidate_set.semantic_available is False
        assert prepared.candidate_set.semantic_reason == "semantic_lookup_failed"
        assert "record:project" in prepared.deterministic_record_ids
        assert prepared.trace["degradation_state"] == "degraded"
        assert prepared.trace["semantic_reason"] == "semantic_lookup_failed"

        controller = IdentityArtifactsController(context=None)
        controller.relay_service = service
        controller.prepare_turn(
            {"capture": service.capture_turn(), "query": make_query_envelope()}
        )
        runtime = dict(controller._runtime_transparency)
        assert runtime["status"] == "degraded"
        assert runtime["reason"] == "semantic_lookup_failed"


def test_semantic_query_uses_every_structured_signal_with_integer_context() -> None:
    from addons.identity_artifacts.retrieval import build_turn_query_envelope
    from addons.identity_artifacts.retrieval_index import (
        DEFAULT_SEMANTIC_THRESHOLD,
        SEMANTIC_THRESHOLD_REVISION,
        SemanticSearchResult,
    )

    calls = []
    searches = []

    class CapturingEmbedding:
        def embed(self, texts, *, model, context):
            calls.append((tuple(texts), model, context))
            return ((1.0, 0.0),)

    class AvailableIndex:
        def search(self, *_args, **kwargs):
            searches.append(dict(kwargs))
            return SemanticSearchResult(
                (),
                True,
                "available",
                False,
                DEFAULT_SEMANTIC_THRESHOLD,
                SEMANTIC_THRESHOLD_REVISION,
            )

    service = make_ready_service()
    service._embedding = CapturingEmbedding()
    service._index = AvailableIndex()
    query = build_turn_query_envelope(
        "Continue our current work.",
        latest_exchange="accepted exchange",
        recent_trajectory=("recent trajectory",),
        named_entities=("Structured Entity",),
        relationships=("Structured Relationship",),
        active_persona="Structured Persona",
        active_projects=("Structured Project",),
        unresolved_threads=("Structured Thread",),
        explicit_corrections=("Structured Correction",),
        kernel_terms=("Structured Kernel",),
    )

    prepared = service.prepare_turn(service.capture_turn(), query)

    assert prepared.status == "judge_required"
    assert len(calls) == 1
    texts, model, context = calls[0]
    assert model == "fake-embedding-v1"
    assert context == 2048
    expected_metadata = searches[0]["expected_metadata"]
    assert expected_metadata.embedding_provider == "lmstudio"
    assert expected_metadata.endpoint_identity == "http://127.0.0.1:1234/v1"
    assert expected_metadata.embedding_model == "fake-embedding-v1"
    assert expected_metadata.embedding_context == 2048
    assert expected_metadata.vector_dimension == 2
    query_text = texts[0]
    for signal in (
        "accepted exchange",
        "recent trajectory",
        "Structured Entity",
        "Structured Relationship",
        "Structured Persona",
        "Structured Project",
        "Structured Thread",
        "Structured Correction",
        "Structured Kernel",
    ):
        assert signal in query_text


def _semantic_endpoint_case(
    *,
    chat_is_remote: bool,
    embedding_base_url: str,
    approved_operations: tuple[str, ...] = (),
    owner_override: bool = False,
):
    from addons.identity_artifacts.retrieval_index import (
        DEFAULT_SEMANTIC_THRESHOLD,
        SEMANTIC_THRESHOLD_REVISION,
        SemanticSearchResult,
    )

    calls = []

    class CapturingEmbedding:
        def embed_for_capture(self, texts, *, model, context, base_url):
            calls.append((tuple(texts), model, context, base_url))
            return ((1.0, 0.0),)

    class AvailableIndex:
        def search(self, *_args, **_kwargs):
            return SemanticSearchResult(
                (),
                True,
                "available",
                False,
                DEFAULT_SEMANTIC_THRESHOLD,
                SEMANTIC_THRESHOLD_REVISION,
            )

    service = make_ready_service()
    service._embedding = CapturingEmbedding()
    service._index = AvailableIndex()
    capture = service.capture_turn()
    frozen_provider = dict(capture.frozen_provider)
    frozen_provider["embedding_base_url"] = embedding_base_url
    runtime_use = dict(capture.runtime_use)
    runtime_use.update(
        {
            "provider_is_remote": chat_is_remote,
            "approved_operations": approved_operations,
            "owner_override": owner_override,
        }
    )
    prepared = service.prepare_turn(
        replace(
            capture,
            frozen_provider=frozen_provider,
            runtime_use=runtime_use,
        ),
        make_query_envelope(),
    )
    return prepared, calls


def test_local_embedding_endpoint_is_independently_authorized() -> None:
    prepared, calls = _semantic_endpoint_case(
        chat_is_remote=False,
        embedding_base_url="http://127.0.0.1:1234/v1",
    )

    assert len(calls) == 1
    decision = prepared.operation_decisions["record:project"][
        "embedding_transmission"
    ]
    assert decision.allowed is True
    assert prepared.candidate_set.semantic_reason == "available"


def test_remote_embedding_endpoint_runs_when_independently_authorized() -> None:
    prepared, calls = _semantic_endpoint_case(
        chat_is_remote=True,
        embedding_base_url="https://embeddings.example.test/v1",
        approved_operations=("provider_transmission", "embedding_transmission"),
    )

    assert len(calls) == 1
    assert prepared.operation_decisions["record:project"][
        "provider_transmission"
    ].allowed is True
    assert prepared.operation_decisions["record:project"][
        "embedding_transmission"
    ].allowed is True
    assert prepared.candidate_set.semantic_reason == "available"


def test_remote_embedding_endpoint_makes_zero_calls_when_not_authorized() -> None:
    prepared, calls = _semantic_endpoint_case(
        chat_is_remote=True,
        embedding_base_url="https://embeddings.example.test/v1",
        approved_operations=("provider_transmission",),
    )

    assert calls == []
    assert prepared.operation_decisions["record:project"][
        "provider_transmission"
    ].allowed is True
    assert prepared.operation_decisions["record:project"][
        "embedding_transmission"
    ].allowed is False
    assert (
        prepared.candidate_set.semantic_reason
        == "embedding_transmission_not_authorized"
    )
    assert "record:project" in prepared.deterministic_record_ids


def test_owner_override_authorizes_remote_embedding_endpoint() -> None:
    prepared, calls = _semantic_endpoint_case(
        chat_is_remote=True,
        embedding_base_url="https://embeddings.example.test/v1",
        approved_operations=(),
        owner_override=True,
    )

    assert len(calls) == 1
    assert prepared.operation_decisions["record:project"][
        "provider_transmission"
    ].reason_code == "owner_override"
    assert prepared.operation_decisions["record:project"][
        "embedding_transmission"
    ].reason_code == "owner_override"
    assert prepared.candidate_set.semantic_reason == "available"


def test_unclassifiable_embedding_endpoint_makes_zero_calls() -> None:
    prepared, calls = _semantic_endpoint_case(
        chat_is_remote=False,
        embedding_base_url="://not-an-endpoint",
    )

    assert calls == []
    assert prepared.operation_decisions["record:project"][
        "embedding_transmission"
    ].allowed is False
    assert (
        prepared.candidate_set.semantic_reason
        == "embedding_endpoint_locality_unknown"
    )
    assert "record:project" in prepared.deterministic_record_ids


def test_chat_locality_cannot_authorize_a_remote_embedding_endpoint() -> None:
    prepared, calls = _semantic_endpoint_case(
        chat_is_remote=False,
        embedding_base_url="https://embeddings.example.test/v1",
        approved_operations=("provider_transmission",),
    )

    assert calls == []
    assert prepared.operation_decisions["record:project"][
        "provider_transmission"
    ].allowed is True
    assert prepared.operation_decisions["record:project"][
        "embedding_transmission"
    ].allowed is False
    assert (
        prepared.candidate_set.semantic_reason
        == "embedding_transmission_not_authorized"
    )
    assert "record:project" in prepared.deterministic_record_ids


def test_controller_wires_runtime_semantic_dependencies_into_turn_capture() -> None:
    embedding_calls = []

    def embedding(text, *, model, base_url, context_length):
        embedding_calls.append((text, model, base_url, context_length))
        return (1.0, 0.0)

    class RuntimeConfig:
        @staticmethod
        def snapshot():
            return {
                "long_term_memory_embedding_enabled": True,
                "long_term_memory_embedding_model": "runtime-embedding",
                "long_term_memory_embedding_base_url": "http://127.0.0.1:1234/v1",
                "long_term_memory_embedding_context_length": 4096,
            }

        @staticmethod
        def engine_attr(name, default=None):
            return embedding if name == "_lmstudio_embedding" else default

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        services = {"qt.runtime_config": RuntimeConfig()}
        controller = IdentityArtifactsController(
            SimpleNamespace(
                app_root=root,
                storage=SimpleNamespace(addon_dir=root / "legacy"),
                get_service=lambda name: services.get(name),
            )
        )
        stored = controller.store.save_import(import_identity_artifact(VALID_ARTIFACT_TEXT))
        controller.decision_store.save_subject_attestation(
            artifact_hash=stored.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            subject_class=SubjectClass.ASSISTANT_SELF,
            approved=True,
        )
        controller.set_persona_identity_ref(stored.artifact_ref)

        capture = controller.capture_turn(
            {"frozen_provider": {"provider_name": "local"}}
        )

        assert controller.relay_service._index is controller.semantic_index
        assert controller.relay_service._embedding is not None
        assert capture.frozen_provider["embedding_model"] == "runtime-embedding"
        assert capture.frozen_provider["embedding_context"] == 4096
        vectors = controller.relay_service._embedding.embed(
            ("query",), model="runtime-embedding", context=4096
        )
        assert vectors == ((1.0, 0.0),)
        assert embedding_calls == [
            (
                "query",
                "runtime-embedding",
                "http://127.0.0.1:1234/v1",
                4096,
            )
        ]


def test_unserializable_judge_payload_degrades_without_dropping_stable_matches() -> None:
    service = make_ready_service()
    prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())
    unserializable_payload = {
        "record_ids": ["record:correction"],
        "reasons": {"record:correction": {"unsupported"}},
        "signals_considered": {"record:correction": ["semantic_fallback"]},
        "unresolved_record_ids": [],
    }

    snapshot = service.finalize_turn(
        prepared,
        judge_payload=unserializable_payload,
    )

    assert snapshot.status == "ready"
    assert "record:project" in snapshot.selected_record_ids
    assert "record:correction" not in snapshot.selected_record_ids
    assert snapshot.unresolved_record_ids == ("record:correction",)
    notice = snapshot.trace["degradation_notice"]
    assert notice["failure_category"] == "payload_conversion_failed"
    assert notice["affected_record_ids"] == ("record:correction",)


def test_judge_conversion_isolated_per_batch_for_malformed_mixed_payloads() -> None:
    service = make_ready_service()
    prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())
    first_batch = prepared.judge_batches[0]
    second_batch = replace(
        first_batch,
        batch_id="judge-batch:0002",
        candidate_ids=("record:second",),
    )

    class ExplodingText:
        def __str__(self):
            raise TypeError("value cannot be converted to text")

    decisions = service._judge_decisions(
        (first_batch, second_batch),
        (valid_judge_payload(), ExplodingText()),
    )

    assert len(decisions) == 2
    assert decisions[0].valid is True
    assert decisions[0].selected_record_ids == ("record:correction",)
    assert decisions[1].valid is False
    assert decisions[1].failure_reason == "payload_conversion_failed"
    assert decisions[1].unresolved_record_ids == ("record:second",)

    malformed = service._judge_decisions(
        (first_batch, second_batch),
        {
            first_batch.batch_id: {"record_ids": []},
            second_batch.batch_id: [["not", "the", "judge", "contract"]],
        },
    )
    assert all(not decision.valid for decision in malformed)
    assert malformed[0].unresolved_record_ids == first_batch.candidate_ids
    assert malformed[1].unresolved_record_ids == second_batch.candidate_ids


def test_projection_render_exception_becomes_blocked_snapshot() -> None:
    service = make_ready_service()
    service._projection_renderer = lambda *_args: (_ for _ in ()).throw(
        RuntimeError("projection render failed")
    )
    prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())

    snapshot = service.finalize_turn(prepared, judge_payload=valid_judge_payload())

    _assert_blocked_degradation(snapshot, "projection_render_failed")


def test_malformed_judge_renderer_result_becomes_blocked_prepared_result() -> None:
    service = make_ready_service()
    service._judge_renderer = lambda *_args, **_kwargs: (object(),)

    prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())

    _assert_blocked_degradation(prepared, "judge_request_render_failed")


def test_malformed_projection_renderer_result_becomes_blocked_snapshot() -> None:
    service = make_ready_service()
    service._projection_renderer = lambda *_args: object()
    prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())

    snapshot = service.finalize_turn(prepared, judge_payload=valid_judge_payload())

    _assert_blocked_degradation(snapshot, "projection_render_failed")


def test_malformed_capacity_result_becomes_blocked_snapshot() -> None:
    import addons.identity_artifacts.service as service_module

    service = make_ready_service()
    prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())
    original_capacity_check = service_module.check_projection_capacity
    service_module.check_projection_capacity = lambda *_args, **_kwargs: object()
    try:
        snapshot = service.finalize_turn(
            prepared,
            judge_payload=valid_judge_payload(),
        )
    finally:
        service_module.check_projection_capacity = original_capacity_check

    _assert_blocked_degradation(snapshot, "capacity_check_failed")


def test_invalid_capture_objects_block_service_with_zero_downstream_work() -> None:
    from addons.identity_artifacts.service import IdentityRelayService

    counters = {"load": 0, "retrieve": 0, "judge": 0, "render": 0}

    class CountingStore:
        def load_normalized(self, _artifact_ref):
            counters["load"] += 1
            raise AssertionError("invalid capture must not load")

    def count(name):
        def counted(*_args, **_kwargs):
            counters[name] += 1
            raise AssertionError(f"invalid capture must not call {name}")

        return counted

    service = IdentityRelayService(
        IdentityRelayModel(),
        store=CountingStore(),
        candidate_retriever=count("retrieve"),
        judge_renderer=count("judge"),
        projection_renderer=count("render"),
    )
    for invalid_capture in (object(), {"enabled": False, "artifact_ref": "serialized"}):
        prepared = service.prepare_turn(invalid_capture, object())
        _assert_blocked_degradation(prepared, "invalid_capture")
        assert counters == {"load": 0, "retrieve": 0, "judge": 0, "render": 0}


def test_public_controller_invalid_capture_blocks_before_query_parsing() -> None:
    controller = IdentityArtifactsController(context=None)

    class ExplodingQuery(Mapping):
        def __iter__(self):
            raise AssertionError("invalid capture must block before query parsing")

        def __len__(self):
            return 1

        def __getitem__(self, _key):
            raise AssertionError("invalid capture must block before query parsing")

    for invalid_capture in (object(), {"enabled": False, "artifact_ref": "serialized"}):
        prepared = controller.prepare_turn(
            {"capture": invalid_capture, "query": ExplodingQuery()}
        )
        _assert_blocked_degradation(prepared, "invalid_capture")


def test_token_count_exception_becomes_blocked_snapshot_with_degradation() -> None:
    service = make_ready_service()
    service._token_counter = lambda _messages: (_ for _ in ()).throw(
        RuntimeError("token counter failed")
    )
    prepared = service.prepare_turn(service.capture_turn(), make_query_envelope())

    snapshot = service.finalize_turn(prepared, judge_payload=valid_judge_payload())

    _assert_blocked_degradation(snapshot, "token_count_failed")


def test_identity_artifacts_side_tab_icon_is_registered() -> None:
    addon_dir = Path(__file__).resolve().parent
    expected_icon_path = "../../ui_icons/side_tabs/artifacts.png"
    manifest = json.loads((addon_dir / "addon.json").read_text(encoding="utf-8"))

    assert manifest["ui"][0].get("icon_path") == expected_icon_path
    assert (addon_dir / expected_icon_path).resolve().is_file()


def test_gemini_flash_v1_1_fixture_imports_permissively() -> None:
    raw_text = FIXTURE_PATH.read_text(encoding="utf-8")

    result = import_identity_artifact(raw_text, provider_label="Gemini Flash")

    assert result.raw.raw_text == raw_text
    assert result.raw.status == "imported"
    assert result.raw.format == "NC_IDENTITY_EXPORT"
    assert result.raw.format_version == "1.1"
    assert result.raw.export_kind == "reflect_and_export_identity"
    assert result.structured.hot_identity_text.startswith("Experienced professional programmer")
    assert "src_memory_summary" in result.structured.source_registry
    assert "src_current_session" in result.structured.source_registry
    assert len(result.structured.hot_identity_claims) == 4
    assert len(result.structured.identity_items) == 7
    assert len(result.structured.ltm_seed_records) == 1
    assert len(result.structured.identity_projections) == 1
    assert "audits" in (result.raw.parsed_json or {})
    assert not any("confidence seems" in warning.lower() for warning in result.structured.import_warnings)
    assert not any("appears wrong" in warning.lower() for warning in result.structured.import_warnings)


def test_unknown_fields_are_preserved_but_not_structurally_imported() -> None:
    raw_text = FIXTURE_PATH.read_text(encoding="utf-8")

    result = import_identity_artifact(raw_text)

    assert "audits" in (result.raw.parsed_json or {})
    assert "audits" in result.structured.ignored_top_level_fields
    assert not hasattr(result.structured, "audits")


def test_broken_source_reference_warns_without_rejecting_artifact() -> None:
    raw_text = """{
      "format": "NC_IDENTITY_EXPORT",
      "format_version": "1.1",
      "export_kind": "reflect_and_export_identity",
      "artifact_contract": {
        "raw_export_is_identity_artifact": true,
        "preserve_raw_output": true,
        "semantic_validation_allowed": false
      },
      "source_registry": [],
      "hot_identity": {
        "compressed_text": "Source-local text.",
        "claims": [
          {"claim_id": "claim_a", "claim_text": "A claim.", "source_ids": ["missing_source"]}
        ]
      }
    }"""

    result = import_identity_artifact(raw_text)

    assert result.raw.status == "imported"
    assert result.structured.hot_identity_text == "Source-local text."
    assert len(result.structured.hot_identity_claims) == 1
    assert result.structured.unresolved_references
    assert any("source_id unresolved" in warning for warning in result.structured.import_warnings)


def test_invalid_json_stores_failed_raw_artifact() -> None:
    raw_text = "{not json"

    result = import_identity_artifact(raw_text)

    assert result.raw.raw_text == raw_text
    assert result.raw.status == "failed"
    assert result.raw.parsed_json is None
    assert result.structured is None
    assert any("could not be parsed as json" in warning.lower() for warning in result.raw.mechanical_warnings)


def test_missing_preview_does_not_block_usable_normalized_identity() -> None:
    payload = {
        "format": "NC_IDENTITY_EXPORT",
        "format_version": "1.1",
        "export_kind": "reflect_and_export_identity",
        "subject_class": "assistant_self",
        "hot_identity": {
            "compressed_text": {"preview": "malformed"},
            "claims": [
                {
                    "claim_id": "stable_self",
                    "claim_text": "I preserve stable normalized continuity.",
                    "subject_refs": ["assistant_self"],
                    "stability": "stable",
                    "confidence": 0.9,
                    "use_policy": {
                        "preferred_runtime_use": "always_inject",
                        "eligible_for_private_retrieval": True,
                    },
                }
            ],
        },
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        store = IdentityArtifactStore(Path(temp_dir) / "identity_relay")
        stored = store.save_import(import_identity_artifact(json.dumps(payload)))
        store.rebuild_normalized(stored.artifact_ref)
        IdentityRelayDecisionStore(store.root_dir).save_subject_attestation(
            artifact_hash=stored.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            subject_class=SubjectClass.ASSISTANT_SELF,
            approved=True,
        )

        resolution = store.resolve_artifact(stored.artifact_ref)
        model = IdentityRelayModel()
        model.set_connection(resolution)

        assert resolution.hot_identity_text == ""
        assert resolution.failure_code is None
        assert model.snapshot_for_turn().state == "active"
        assert model.snapshot_for_turn().hot_identity_text == ""


def test_shipped_chatgpt_fixture_reaches_ready_local_relay_snapshot() -> None:
    import engine
    from core import chat_providers
    from core.runtime_chat import ChatProviderRuntime

    fixture_bytes = CHATGPT_FIXTURE_PATH.read_bytes()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        controller = IdentityArtifactsController(
            SimpleNamespace(
                app_root=root,
                storage=SimpleNamespace(addon_dir=root / "legacy"),
                get_service=lambda _name: None,
            )
        )
        stored = controller.store.save_import(
            import_identity_artifact(fixture_bytes, source_type="file")
        )
        controller.store.rebuild_normalized(stored.artifact_ref)
        controller.decision_store.save_subject_attestation(
            artifact_hash=stored.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            subject_class=SubjectClass.ASSISTANT_SELF,
            approved=True,
        )
        controller.set_persona_identity_ref(stored.artifact_ref)
        capture = controller.capture_turn(
            {
                "frozen_provider": {
                    "provider_name": "task9-local-fixture",
                    "model_name": "task9-model",
                    "provider_config": {
                        "provider_is_remote": False,
                        "base_url": "http://127.0.0.1:1234/v1",
                    },
                    "base_messages": (
                        {"role": "user", "content": "Continue our current work."},
                    ),
                    "max_batch_chars": 100_000,
                    "persistence_mode": "volatile",
                }
            }
        )
        prepared = controller.prepare_turn(
            {"capture": capture, "query": "Continue our current work."}
        )

        assert prepared.status in {"ready_without_judge", "judge_required"}
        assert not prepared.failure_code
        judge_payload = {
            batch.batch_id: json.dumps(
                {
                    "record_ids": [],
                    "reasons": {},
                    "signals_considered": {},
                    "unresolved_record_ids": list(batch.candidate_ids),
                }
            )
            for batch in prepared.judge_batches
        }
        snapshot = controller.finalize_turn(
            {"prepared": prepared, "judge_payload": judge_payload}
        )

        assert snapshot.status == "ready"
        assert not snapshot.failure_code
        assert "I continue through patterns" in snapshot.prompt_text
        assert "Do not infer literal persistence" in snapshot.prompt_text
        assert "literal process persistence" in snapshot.prompt_text

        provider_id = "task9-shipped-fixture-e2e"
        provider_messages = []

        def prepare_frozen(_binding, params, additional_params):
            prepared = dict(params)
            prepared.setdefault("max_tokens", 256)
            return prepared, additional_params

        def complete_frozen(request, **_kwargs):
            messages = request.params_copy().get("messages") or []
            if any(
                "Return only the requested Identity Relay JSON decision."
                in str(message.get("content") or "")
                for message in messages
            ):
                return json.dumps(
                    {
                        "record_ids": [],
                        "reasons": {},
                        "signals_considered": {},
                        "unresolved_record_ids": [],
                    }
                )
            provider_messages.append(messages)
            return "fixture dispatch reply"

        def capabilities(binding):
            identity = binding.execution_identity
            return {
                "context_limit": 100_000,
                "token_counter": lambda messages: len(
                    json.dumps(list(messages), ensure_ascii=False)
                ),
                "capability_identity": identity,
                "token_counter_identity": identity,
            }

        class RelayManager:
            @staticmethod
            def invoke_addon_capability(_addon_id, capability, payload):
                if capability == "identity_relay.chat_session.reset":
                    return None
                if capability == "identity_relay.capture_mode":
                    return controller.capture_mode()
                handlers = {
                    "identity_relay.capture_turn": controller.capture_turn,
                    "identity_relay.prepare_turn": controller.prepare_turn,
                    "identity_relay.render_judge_request": (
                        controller.render_judge_request
                    ),
                    "identity_relay.finalize_turn": controller.finalize_turn,
                }
                return handlers[capability](payload)

            invoke_addon_capability_strict = invoke_addon_capability

        original_runtime = engine._chat_runtime
        original_manager_getter = engine._addon_manager_getter
        original_collect_contexts = engine._collect_addon_chat_contexts
        original_settings = chat_providers.get_provider_settings()
        original_config = {
            key: engine.RUNTIME_CONFIG.get(key)
            for key in (
                "active_preset_name",
                "emotional_instructions",
                "system_prompt",
            )
        }
        chat_providers.unregister_provider(provider_id)
        try:
            chat_providers.register_provider(
                provider_id=provider_id,
                label="Task 9 Shipped Fixture",
                frozen_execution_version=1,
                frozen_prepare_handler=prepare_frozen,
                frozen_completion_handler=complete_frozen,
                frozen_stream_handler=lambda _request, **_kwargs: iter(()),
                model_capabilities_handler=capabilities,
                frozen_private_config_getter=lambda: {
                    "base_url": "http://127.0.0.1:1234/v1",
                    "provider_is_remote": False,
                },
                frozen_public_config_fields=("base_url", "provider_is_remote"),
            )
            engine._chat_runtime = ChatProviderRuntime(
                lambda: {
                    "chat_provider": provider_id,
                    "model_name": "task9-model",
                }
            )
            engine.set_addon_manager_getter(lambda: RelayManager())
            engine._collect_addon_chat_contexts = lambda *_args, **_kwargs: []
            engine.RUNTIME_CONFIG.update(
                {
                    "active_preset_name": "",
                    "emotional_instructions": "",
                    "system_prompt": "",
                }
            )
            engine.reset_session_state()
            accepted = engine._begin_normal_chat_transaction(
                {
                    "role": "user",
                    "content": "Continue our current work.",
                    "origin": "input",
                }
            )
            request = engine._freeze_normal_chat_request(accepted)
            transaction = engine._ensure_normal_chat_transaction_ready(request)
            reply = engine.chat_with_llm(
                request,
                prepared_request=transaction["prepared_provider_request"],
            )

            assert reply == "fixture dispatch reply"
            assert len(provider_messages) == 1
            outbound_text = "\n".join(
                str(message.get("content") or "")
                for message in provider_messages[0]
            )
            assert "I continue through patterns" in outbound_text
            assert "Do not infer literal persistence" in outbound_text
            assert "literal process persistence" in outbound_text
        finally:
            engine.reset_session_state()
            engine._chat_runtime = original_runtime
            engine.set_addon_manager_getter(original_manager_getter)
            engine._collect_addon_chat_contexts = original_collect_contexts
            engine.RUNTIME_CONFIG.update(original_config)
            chat_providers.unregister_provider(provider_id)
            chat_providers.set_provider_settings(original_settings)
        assert stored.canonical_path.read_bytes() == fixture_bytes


def test_non_string_hot_identity_never_becomes_relay_continuity() -> None:
    malformed_values = (
        {"unexpected": "mapping"},
        ["unexpected", "list"],
        42,
    )
    for malformed_value in malformed_values:
        payload = {
            "format": "NC_IDENTITY_EXPORT",
            "format_version": "1.1",
            "export_kind": "reflect_and_export_identity",
            "hot_identity": {"compressed_text": malformed_value},
        }
        raw_text = json.dumps(payload, ensure_ascii=False)

        result = import_identity_artifact(raw_text, source_type="pasted")

        assert result.raw.status == "imported"
        assert result.structured is not None
        assert result.structured.hot_identity_text == ""
        assert "hot_identity.compressed_text" in result.structured.skipped_sections
        assert any(
            "hot_identity.compressed_text" in warning and "wrong type" in warning
            for warning in result.structured.import_warnings
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            store = IdentityArtifactStore(Path(temp_dir) / "identity_relay")
            stored = store.save_import(result)
            resolution = store.resolve_artifact(stored.artifact_ref)
            model = IdentityRelayModel()
            model.set_connection(resolution)

            assert store.load_raw_bytes(stored.artifact_ref) == raw_text.encode("utf-8")
            assert resolution.hot_identity_text == ""
            assert resolution.failure_code == "empty_normalized_identity"
            assert model.snapshot_for_turn().state == "unavailable"
            assert model.snapshot_for_turn().failure_code == "empty_normalized_identity"


def test_store_round_trips_raw_artifact_exactly() -> None:
    raw_text = FIXTURE_PATH.read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory() as temp_dir:
        store = IdentityArtifactStore(Path(temp_dir))
        result = import_identity_artifact(raw_text, provider_label="Gemini Flash")
        stored = store.save_import(result)
        loaded = store.load_raw_bytes(stored.artifact_ref)

    assert loaded == raw_text.encode("utf-8")


def test_file_import_preserves_exact_bytes_and_full_hash() -> None:
    raw = (
        b"\xef\xbb\xbf{\r\n  \"format\": \"NC_IDENTITY_EXPORT\",\r\n"
        b"  \"format_version\": \"1.1\",\r\n"
        b"  \"export_kind\": \"reflect_and_export_identity\",\r\n"
        b"  \"hot_identity\": {\"compressed_text\": \"Continuity\"}\r\n}"
    )
    result = import_identity_artifact(raw, source_type="file", source_path="download.json")

    assert result.raw.raw_bytes == raw
    assert result.raw.artifact_hash == hashlib.sha256(raw).hexdigest()
    assert len(result.raw.artifact_hash) == 64


def test_pasted_import_defines_utf8_canonical_bytes() -> None:
    text = VALID_ARTIFACT_TEXT.replace("Continuity", "Continuity \u00e5\u00e4\u00f6")
    result = import_identity_artifact(text, source_type="pasted")

    assert result.raw.raw_bytes == text.encode("utf-8")


def test_store_deduplicates_exact_bytes_and_rejects_unsafe_refs() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = IdentityArtifactStore(Path(temp_dir) / "identity_relay")
        result = import_identity_artifact(VALID_ARTIFACT_TEXT, source_type="pasted")
        first = store.save_import(result)
        second = store.save_import(result)

        assert first.artifact_ref == second.artifact_ref
        assert first.canonical_created is True
        assert second.canonical_created is False
        assert store.load_raw_bytes(first.artifact_ref) == result.raw.raw_bytes
        for invalid in ("../outside.json", "library/short.json", str(first.canonical_path)):
            assert store.resolve_artifact(invalid).failure_code == "invalid"


def test_store_rejects_mismatched_import_hash_before_writing() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = IdentityArtifactStore(Path(temp_dir) / "identity_relay")
        result = import_identity_artifact(VALID_ARTIFACT_TEXT)
        result.raw.artifact_hash = "0" * 64
        try:
            store.save_import(result)
        except ValueError as exc:
            assert "hash" in str(exc).lower()
        else:
            raise AssertionError("save_import accepted a mismatched artifact hash")
        assert list(store.library_dir.iterdir()) == []


def test_store_reextracts_verified_bytes_before_publishing_derived_data() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = IdentityArtifactStore(Path(temp_dir) / "identity_relay")
        result = import_identity_artifact(VALID_ARTIFACT_TEXT, provider_label="Trusted provider")
        result.raw.status = "failed"
        result.raw.mechanical_warnings.append("caller-controlled warning")
        result.structured.hot_identity_text = "Caller-controlled identity"
        result.structured.import_warnings.append("caller-controlled extraction")

        stored = store.save_import(result)
        derived_record = json.loads(stored.derived_path.read_text(encoding="utf-8"))
        index = json.loads(store.index_path.read_text(encoding="utf-8"))
        indexed_metadata = next(item for item in index["artifacts"] if item["artifact_ref"] == stored.artifact_ref)

        assert derived_record["metadata"]["provider_label"] == "Trusted provider"
        assert derived_record["metadata"]["status"] == "imported"
        assert derived_record["metadata"]["mechanical_warnings"] == []
        assert derived_record["structured"]["hot_identity_text"] == "Continuity"
        assert derived_record["structured"]["import_warnings"] == []
        assert indexed_metadata["status"] == "imported"
        assert indexed_metadata["mechanical_warnings"] == []


def test_refresh_rebuilds_semantically_stale_derived_record() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = IdentityArtifactStore(Path(temp_dir) / "identity_relay")
        stored = store.save_import(
            import_identity_artifact(
                VALID_ARTIFACT_TEXT,
                provider_label="Pasted source",
                source_type="pasted",
            )
        )
        original_metadata = store.load_metadata(stored.artifact_ref)
        original_bytes = stored.canonical_path.read_bytes()
        stale_record = json.loads(stored.derived_path.read_text(encoding="utf-8"))
        stale_record["metadata"]["status"] = "failed"
        stale_record["structured"]["hot_identity_text"] = "Stale identity"
        stored.derived_path.write_text(json.dumps(stale_record), encoding="utf-8")

        refreshed = store.refresh_library()
        rebuilt_record = json.loads(stored.derived_path.read_text(encoding="utf-8"))

        assert refreshed.rebuilt_refs == (stored.artifact_ref,)
        assert stored.canonical_path.read_bytes() == original_bytes
        assert rebuilt_record["metadata"]["status"] == "imported"
        assert rebuilt_record["structured"]["hot_identity_text"] == "Continuity"
        for field_name in ("source_type", "source_path", "provider_label", "imported_at"):
            assert rebuilt_record["metadata"][field_name] == original_metadata[field_name]


def test_refresh_repairs_corrupt_derived_and_index_without_losing_file_provenance() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = IdentityArtifactStore(Path(temp_dir) / "identity_relay")
        stored = store.save_import(
            import_identity_artifact(
                VALID_ARTIFACT_TEXT.encode("utf-8"),
                provider_label="File source",
                source_type="file",
                source_path="C:/imports/identity.json",
            )
        )
        original_metadata = store.load_metadata(stored.artifact_ref)
        original_bytes = stored.canonical_path.read_bytes()

        stored.derived_path.write_text("{corrupt derived", encoding="utf-8")
        corrupt_derived_refresh = store.refresh_library()
        rebuilt_metadata = store.load_metadata(stored.artifact_ref)

        assert corrupt_derived_refresh.rebuilt_refs == (stored.artifact_ref,)
        assert stored.canonical_path.read_bytes() == original_bytes
        for field_name in ("source_type", "source_path", "provider_label", "imported_at"):
            assert rebuilt_metadata[field_name] == original_metadata[field_name]

        store.index_path.write_text("{corrupt index", encoding="utf-8")
        index_refresh = store.refresh_library()
        repaired_index = json.loads(store.index_path.read_text(encoding="utf-8"))
        indexed_metadata = next(
            item for item in repaired_index["artifacts"] if item["artifact_ref"] == stored.artifact_ref
        )

        assert index_refresh.rebuilt_refs == ()
        for field_name in ("source_type", "source_path", "provider_label", "imported_at"):
            assert indexed_metadata[field_name] == original_metadata[field_name]


def test_refresh_repairs_valid_but_incorrect_index_provenance_from_derived() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = IdentityArtifactStore(Path(temp_dir) / "identity_relay")
        stored = store.save_import(
            import_identity_artifact(
                VALID_ARTIFACT_TEXT.encode("utf-8"),
                provider_label="Authoritative file source",
                source_type="file",
                source_path="C:/imports/authoritative.json",
            )
        )
        original_metadata = store.load_metadata(stored.artifact_ref)
        original_bytes = stored.canonical_path.read_bytes()
        index = json.loads(store.index_path.read_text(encoding="utf-8"))
        indexed_metadata = next(
            item for item in index["artifacts"] if item["artifact_ref"] == stored.artifact_ref
        )
        indexed_metadata.update(
            {
                "source_type": "legacy",
                "source_path": "C:/wrong/index/source.json",
                "provider_label": "Incorrect index source",
                "imported_at": "2000-01-01T00:00:00+00:00",
            }
        )
        store.index_path.write_text(json.dumps(index), encoding="utf-8")

        refreshed = store.refresh_library()
        derived_metadata = json.loads(stored.derived_path.read_text(encoding="utf-8"))["metadata"]
        repaired_index = json.loads(store.index_path.read_text(encoding="utf-8"))
        repaired_index_metadata = next(
            item
            for item in repaired_index["artifacts"]
            if item["artifact_ref"] == stored.artifact_ref
        )

        assert refreshed.rebuilt_refs == ()
        assert stored.canonical_path.read_bytes() == original_bytes
        for field_name in ("source_type", "source_path", "provider_label", "imported_at"):
            assert derived_metadata[field_name] == original_metadata[field_name]
            assert repaired_index_metadata[field_name] == original_metadata[field_name]


def test_refresh_excludes_tampered_canonical_artifacts_from_list_and_index() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = IdentityArtifactStore(Path(temp_dir) / "identity_relay")
        stored = store.save_import(import_identity_artifact(VALID_ARTIFACT_TEXT))

        assert stored.artifact_ref in {item["artifact_ref"] for item in store.list_artifacts()}
        initial_index = json.loads(store.index_path.read_text(encoding="utf-8"))
        assert stored.artifact_ref in {item["artifact_ref"] for item in initial_index["artifacts"]}

        stored.canonical_path.write_bytes(b"tampered canonical bytes")
        refreshed = store.refresh_library()
        refreshed_index = json.loads(store.index_path.read_text(encoding="utf-8"))

        assert any("hash mismatch" in warning.lower() for warning in refreshed.warnings)
        assert store.resolve_artifact(stored.artifact_ref).failure_code == "corrupt"
        assert stored.artifact_ref not in {item["artifact_ref"] for item in store.list_artifacts()}
        assert stored.artifact_ref not in {item["artifact_ref"] for item in refreshed_index["artifacts"]}


def test_legacy_inspection_adapters_bridge_to_strict_refs() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = IdentityArtifactStore(Path(temp_dir) / "identity_relay")
        stored = store.save_import(import_identity_artifact(VALID_ARTIFACT_TEXT, provider_label="Legacy UI"))

        assert stored.artifact_id == stored.artifact_ref
        artifacts = store.list_artifacts()
        assert artifacts[0]["artifact_id"] == stored.artifact_ref
        assert store.load_metadata(stored.artifact_id)["artifact_ref"] == stored.artifact_ref
        assert store.load_raw_text(stored.artifact_id) == VALID_ARTIFACT_TEXT
        assert store.load_structured(stored.artifact_id)["hot_identity_text"] == "Continuity"

        blocked = store.delete_artifact(stored.artifact_id)
        assert blocked.deleted is False
        assert blocked.blocked_by == ("guard_context_required",)
        assert blocked.failure_code == "guard_context_required"
        assert stored.canonical_path.exists()

        presets_dir = Path(temp_dir) / "presets"
        presets_dir.mkdir()
        deleted = store.delete_artifact(
            stored.artifact_id,
            active_persona_ref="",
            presets_dir=presets_dir,
            loaded_session_refs=(),
        )
        assert deleted.deleted is True


def test_legacy_migration_is_visible_non_destructive_and_idempotent() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        raw_path = root / "legacy" / "artifacts" / "identity_old" / "raw.txt"
        raw_path.parent.mkdir(parents=True)
        raw_path.write_bytes(VALID_ARTIFACT_TEXT.encode("utf-8"))
        store = IdentityArtifactStore(root / "identity_relay")

        first = store.refresh_library(legacy_root=root / "legacy")
        second = store.refresh_library(legacy_root=root / "legacy")

        assert len(first.migrated_refs) == 1
        assert second.migrated_refs == ()
        assert first.reused_refs == ()
        assert raw_path.read_bytes() == VALID_ARTIFACT_TEXT.encode("utf-8")
        assert any("normalization" in warning.lower() for warning in first.warnings)


def test_delete_blocks_active_and_direct_preset_references() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        store = IdentityArtifactStore(root / "runtime" / "identity_relay")
        stored = store.save_import(import_identity_artifact(VALID_ARTIFACT_TEXT))
        presets = root / "presets"
        presets.mkdir()
        (presets / "uses_identity.json").write_text(
            json.dumps({"identity_relay_ref": stored.artifact_ref}), encoding="utf-8"
        )

        blocked = store.delete_artifact(
            stored.artifact_ref,
            active_persona_ref=stored.artifact_ref,
            presets_dir=presets,
            loaded_session_refs=(),
        )

        assert blocked.deleted is False
        assert blocked.blocked_by == ("active_persona", "preset:uses_identity.json")


def test_delete_blocks_loaded_session_and_removes_owned_sensitive_derivatives() -> None:
    import inspect

    from addons.identity_artifacts.retrieval_index import IdentitySemanticIndex

    assert "loaded_session_refs" in inspect.signature(
        IdentityArtifactStore.delete_artifact
    ).parameters
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        store = IdentityArtifactStore(root / "runtime" / "identity_relay")
        target = store.save_import(import_identity_artifact(VALID_ARTIFACT_TEXT))
        unrelated = store.save_import(
            import_identity_artifact(
                VALID_ARTIFACT_TEXT.replace("Continuity", "Unrelated continuity")
            )
        )
        store.rebuild_normalized(target.artifact_ref)
        store.rebuild_normalized(unrelated.artifact_ref)
        target_version_dir = store.derived_dir / target.artifact_hash
        (target_version_dir / "older-normalizer.json").write_text(
            "sensitive normalized data",
            encoding="utf-8",
        )
        decisions = IdentityRelayDecisionStore(store.root_dir)
        decisions.save_subject_attestation(
            artifact_hash=target.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            subject_class=SubjectClass.ASSISTANT_SELF,
            approved=True,
        )
        decisions.save_subject_attestation(
            artifact_hash=unrelated.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            subject_class=SubjectClass.ASSISTANT_SELF,
            approved=True,
        )
        semantic_index = IdentitySemanticIndex(store.root_dir / "indexes")
        semantic_index.path_for(target.artifact_hash).write_text(
            "target semantic index",
            encoding="utf-8",
        )
        semantic_index.path_for(unrelated.artifact_hash).write_text(
            "unrelated semantic index",
            encoding="utf-8",
        )
        authorizations = IdentityRelaySnapshotAuthorizationStore(store.root_dir)
        target_snapshot_hash = "1" * 64
        authorization = PersistentSnapshotAuthorization(
            snapshot_hash=target_snapshot_hash,
            artifact_ref=target.artifact_ref,
            artifact_hash=target.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            attestation_revision=1,
            subject_class=SubjectClass.ASSISTANT_SELF.value,
            subject_approved=True,
            persistence_allowed=True,
            provider_is_remote=False,
        )
        authorization = replace(
            authorization,
            authorization_record_id=persistent_snapshot_authorization_record_id(
                authorization
            ),
        )
        authorizations.save(authorization)
        authorization_path = (
            authorizations.authorizations_dir
            / f"{authorization.authorization_record_id}.json"
        )
        presets = root / "presets"
        presets.mkdir()

        blocked = store.delete_artifact(
            target.artifact_ref,
            active_persona_ref="",
            presets_dir=presets,
            loaded_session_refs=(target.artifact_ref,),
        )
        assert blocked.deleted is False
        assert blocked.blocked_by == ("loaded_session",)
        assert target.canonical_path.exists()
        assert authorization_path.exists()

        deleted = store.delete_artifact(
            target.artifact_ref,
            active_persona_ref="",
            presets_dir=presets,
            loaded_session_refs=(),
        )
        assert deleted.deleted is True
        assert not target.canonical_path.exists()
        assert not target.derived_path.exists()
        assert not target_version_dir.exists()
        assert not (decisions.attestations_dir / f"{target.artifact_hash}.json").exists()
        assert not semantic_index.path_for(target.artifact_hash).exists()
        assert not authorization_path.exists()

        assert unrelated.canonical_path.exists()
        assert unrelated.derived_path.exists()
        assert (store.derived_dir / unrelated.artifact_hash).exists()
        assert (decisions.attestations_dir / f"{unrelated.artifact_hash}.json").exists()
        assert semantic_index.path_for(unrelated.artifact_hash).exists()


def test_delete_cleans_owned_v1_and_v2_authorizations_and_reports_malformed_v1() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        store = IdentityArtifactStore(root / "runtime" / "identity_relay")
        target = store.save_import(import_identity_artifact(VALID_ARTIFACT_TEXT))
        unrelated = store.save_import(
            import_identity_artifact(
                VALID_ARTIFACT_TEXT.replace("Continuity", "Unrelated continuity")
            )
        )
        authorizations = IdentityRelaySnapshotAuthorizationStore(store.root_dir)
        current = PersistentSnapshotAuthorization(
            snapshot_hash="2" * 64,
            artifact_ref=target.artifact_ref,
            artifact_hash=target.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            attestation_revision=1,
            subject_class=SubjectClass.ASSISTANT_SELF.value,
            subject_approved=True,
            persistence_allowed=True,
            provider_is_remote=False,
        )
        current = replace(
            current,
            authorization_record_id=persistent_snapshot_authorization_record_id(
                current
            ),
        )
        authorizations.save(current)
        current_path = (
            authorizations.authorizations_dir
            / f"{current.authorization_record_id}.json"
        )

        def legacy_payload(snapshot_hash, stored):
            return {
                "schema_version": 1,
                "snapshot_hash": snapshot_hash,
                "artifact_ref": stored.artifact_ref,
                "artifact_hash": stored.artifact_hash,
                "normalizer_revision": NORMALIZER_REVISION,
                "attestation_revision": 1,
                "subject_class": SubjectClass.ASSISTANT_SELF.value,
                "subject_approved": True,
                "persistence_allowed": True,
                "provider_is_remote": False,
                "provider_name": "legacy-sensitive-provider",
                "provider_endpoint": "http://127.0.0.1:1234/v1",
                "record_ids": ["record:legacy-sensitive"],
                "authorized_operations": ["provider_transmission"],
                "created_at": "2026-07-17T00:00:00+00:00",
            }

        owned_hash = "3" * 64
        owned_path = authorizations.authorizations_dir / f"{owned_hash}.json"
        owned_path.write_text(
            json.dumps(legacy_payload(owned_hash, target)),
            encoding="utf-8",
        )
        unrelated_hash = "4" * 64
        unrelated_path = authorizations.authorizations_dir / f"{unrelated_hash}.json"
        unrelated_path.write_text(
            json.dumps(legacy_payload(unrelated_hash, unrelated)),
            encoding="utf-8",
        )
        malformed_hash = "5" * 64
        malformed_path = authorizations.authorizations_dir / f"{malformed_hash}.json"
        malformed_payload = legacy_payload(malformed_hash, target)
        malformed_payload["snapshot_hash"] = "not-a-valid-snapshot-hash"
        malformed_path.write_text(json.dumps(malformed_payload), encoding="utf-8")

        assert authorizations.load(owned_hash) is None
        result = store.delete_artifact(
            target.artifact_ref,
            active_persona_ref="",
            presets_dir=root / "presets",
            loaded_session_refs=(),
        )

        assert result.deleted is False
        assert result.failure_code == "partial_delete"
        assert "snapshot_authorizations" in result.removed_derivatives
        assert any(
            malformed_path.name in detail
            and detail.startswith("snapshot_authorizations:")
            for detail in result.failure_details
        )
        assert not owned_path.exists()
        assert not current_path.exists()
        assert unrelated_path.exists()
        assert malformed_path.exists()
        assert target.canonical_path.exists()
        assert unrelated.canonical_path.exists()


def test_controller_delete_blocks_runtime_references_and_purges_projections() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        store = IdentityArtifactStore(root / "runtime" / "identity_relay")
        stored = store.save_import(import_identity_artifact(VALID_ARTIFACT_TEXT))
        presets = root / "presets"
        presets.mkdir()
        runtime_blockers = ["loaded_chat:conversation_history"]
        purge_calls = []

        class RuntimeConfig:
            @staticmethod
            def engine_attr(name, default=None):
                if name == "_identity_relay_delete_transaction":
                    def transaction(artifact_ref, commit):
                        blockers = tuple(runtime_blockers)
                        if blockers:
                            return {
                                "committed": False,
                                "blocked_by": blockers,
                                "result": None,
                            }
                        return {
                            "committed": True,
                            "blocked_by": (),
                            "result": commit(),
                        }

                    return transaction
                if name == "_identity_relay_loaded_reference_reasons":
                    return lambda _artifact_ref: tuple(runtime_blockers)
                if name == "_purge_identity_relay_runtime_derivatives":
                    return lambda artifact_ref: (
                        purge_calls.append(artifact_ref)
                        or {
                            "purged": True,
                            "blocked_by": (),
                            "removed_snapshot_count": 1,
                        }
                    )
                return default

        controller = IdentityArtifactsController(context=None)
        controller.store = store
        controller.decision_store = IdentityRelayDecisionStore(store.root_dir)
        controller.presets_dir = presets
        controller.runtime_config = RuntimeConfig()
        assert hasattr(controller, "delete_artifact")

        blocked = controller.delete_artifact(stored.artifact_ref)
        assert blocked.deleted is False
        assert blocked.blocked_by == ("loaded_chat:conversation_history",)
        assert purge_calls == []
        assert stored.canonical_path.exists()

        runtime_blockers.clear()
        deleted = controller.delete_artifact(stored.artifact_ref)
        assert deleted.deleted is True
        assert purge_calls == [stored.artifact_ref]
        assert not stored.canonical_path.exists()


def test_controller_guard_block_is_mutation_free_for_all_derivatives() -> None:
    from addons.identity_artifacts.retrieval_index import IdentitySemanticIndex

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        store = IdentityArtifactStore(root / "runtime" / "identity_relay")
        stored = store.save_import(import_identity_artifact(VALID_ARTIFACT_TEXT))
        store.rebuild_normalized(stored.artifact_ref)
        decisions = IdentityRelayDecisionStore(store.root_dir)
        decisions.save_subject_attestation(
            artifact_hash=stored.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            subject_class=SubjectClass.ASSISTANT_SELF,
            approved=True,
        )
        semantic_index = IdentitySemanticIndex(store.root_dir / "indexes")
        semantic_index.path_for(stored.artifact_hash).write_text(
            "sensitive index",
            encoding="utf-8",
        )
        authorizations = IdentityRelaySnapshotAuthorizationStore(store.root_dir)
        authorization = PersistentSnapshotAuthorization(
            snapshot_hash="2" * 64,
            artifact_ref=stored.artifact_ref,
            artifact_hash=stored.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            attestation_revision=1,
            subject_class=SubjectClass.ASSISTANT_SELF.value,
            subject_approved=True,
            persistence_allowed=True,
            provider_is_remote=False,
        )
        authorization = replace(
            authorization,
            authorization_record_id=persistent_snapshot_authorization_record_id(
                authorization
            ),
        )
        authorizations.save(authorization)
        presets = root / "presets"
        presets.mkdir()
        (presets / "active.json").write_text(
            json.dumps({"identity_relay_ref": stored.artifact_ref}),
            encoding="utf-8",
        )
        runtime_snapshots = {"snapshot": stored.artifact_ref}
        purge_calls = []

        def purge(artifact_ref):
            purge_calls.append(artifact_ref)
            removed = len(runtime_snapshots)
            runtime_snapshots.clear()
            return {
                "purged": True,
                "blocked_by": (),
                "removed_snapshot_count": removed,
            }

        class RuntimeConfig:
            @staticmethod
            def engine_attr(name, default=None):
                if name == "_identity_relay_delete_transaction":
                    return lambda _artifact_ref, commit: {
                        "committed": True,
                        "blocked_by": (),
                        "result": commit(),
                    }
                if name == "_identity_relay_loaded_reference_reasons":
                    return lambda _artifact_ref: ()
                if name == "_purge_identity_relay_runtime_derivatives":
                    return purge
                return default

        controller = IdentityArtifactsController(context=None)
        controller.store = store
        controller.decision_store = decisions
        controller.snapshot_authorization_store = authorizations
        controller.semantic_index = semantic_index
        controller.presets_dir = presets
        controller.runtime_config = RuntimeConfig()
        controller.relay_model.set_connection(
            ArtifactResolution(
                stored.artifact_ref,
                stored.artifact_hash,
                "Active identity",
                None,
            )
        )

        before_files = {
            str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }
        result = controller.delete_artifact(stored.artifact_ref)
        after_files = {
            str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }

        assert result.deleted is False
        assert result.blocked_by == (
            "active_persona",
            "preset:active.json",
        )
        assert result.failure_code is None
        assert result.removed_derivatives == ()
        assert purge_calls == []
        assert runtime_snapshots == {"snapshot": stored.artifact_ref}
        assert after_files == before_files


def test_delete_fails_closed_for_unreadable_direct_presets() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        store = IdentityArtifactStore(root / "runtime" / "identity_relay")
        stored = store.save_import(import_identity_artifact(VALID_ARTIFACT_TEXT))
        presets = root / "presets"
        presets.mkdir()
        (presets / "malformed.json").write_text("{", encoding="utf-8")
        (presets / "non_utf8.json").write_bytes(b"\xff")

        blocked = store.delete_artifact(
            stored.artifact_ref,
            active_persona_ref="",
            presets_dir=presets,
            loaded_session_refs=(),
        )

        assert blocked.deleted is False
        assert blocked.blocked_by == ("preset:malformed.json", "preset:non_utf8.json")
        assert stored.canonical_path.exists()


def test_store_rejects_backslash_refs_without_deleting_canonical_artifact() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = IdentityArtifactStore(Path(temp_dir) / "identity_relay")
        stored = store.save_import(import_identity_artifact(VALID_ARTIFACT_TEXT))
        backslash_ref = stored.artifact_ref.replace("/", "\\")

        assert store.resolve_artifact(backslash_ref).failure_code == "invalid"
        deleted = store.delete_artifact(
            backslash_ref,
            active_persona_ref="",
            presets_dir=Path(temp_dir) / "presets",
            loaded_session_refs=(),
        )
        assert deleted.deleted is False
        assert deleted.failure_code == "invalid"
        assert stored.canonical_path.exists()


def test_delete_retains_canonical_artifact_when_derived_delete_fails() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        store = IdentityArtifactStore(root / "identity_relay")
        stored = store.save_import(import_identity_artifact(VALID_ARTIFACT_TEXT))
        presets = root / "presets"
        presets.mkdir()
        original_unlink = Path.unlink

        def fail_derived_unlink(path, *args, **kwargs):
            if path == stored.derived_path:
                raise OSError("fault-injected derived delete failure")
            return original_unlink(path, *args, **kwargs)

        Path.unlink = fail_derived_unlink
        try:
            deleted = store.delete_artifact(
                stored.artifact_ref,
                active_persona_ref="",
                presets_dir=presets,
                loaded_session_refs=(),
            )
        finally:
            Path.unlink = original_unlink

        assert deleted.deleted is False
        assert deleted.failure_code == "unreadable"
        assert stored.canonical_path.exists()


def test_delete_retains_canonical_artifact_when_index_write_fails() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        store = IdentityArtifactStore(root / "identity_relay")
        stored = store.save_import(import_identity_artifact(VALID_ARTIFACT_TEXT))
        presets = root / "presets"
        presets.mkdir()
        original_write_index = store._write_index

        def fail_index_write():
            raise OSError("fault-injected index write failure")

        store._write_index = fail_index_write
        try:
            try:
                deleted = store.delete_artifact(
                    stored.artifact_ref,
                    active_persona_ref="",
                    presets_dir=presets,
                    loaded_session_refs=(),
                )
            except OSError as exc:
                canonical_exists = stored.canonical_path.exists()
                raise AssertionError(
                    "delete leaked the index write failure after canonical_exists="
                    f"{canonical_exists}"
                ) from exc
        finally:
            store._write_index = original_write_index

        assert deleted.deleted is False
        assert deleted.failure_code == "partial_delete"
        assert "derived_record" in deleted.removed_derivatives
        assert deleted.failure_details == ("library_index:OSError",)
        assert stored.canonical_path.exists()


def test_relay_model_defaults_new_ref_on_and_preserves_same_ref_state() -> None:
    model = IdentityRelayModel()
    first = ArtifactResolution("library/" + "a" * 64 + ".json", "a" * 64, "Identity A", None)
    second = ArtifactResolution("library/" + "b" * 64 + ".json", "b" * 64, "Identity B", None)

    model.set_connection(first)
    assert model.snapshot_for_turn().state == "active"
    assert model.set_enabled(False) is True
    model.set_connection(first)
    assert model.snapshot_for_turn().state == "suspended"
    model.set_connection(second)
    assert model.snapshot_for_turn().state == "active"


def test_relay_snapshot_is_immutable_after_toggle_and_persona_change() -> None:
    model = IdentityRelayModel()
    model.set_connection(ArtifactResolution("library/" + "a" * 64 + ".json", "a" * 64, "Frozen", None))

    captured = model.snapshot_for_turn()
    model.set_enabled(False)
    model.set_connection(None)

    assert captured.state == "active"
    assert captured.hot_identity_text == "Frozen"


def test_controller_uses_canonical_root_and_explicit_legacy_migration() -> None:
    from PySide6 import QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    with tempfile.TemporaryDirectory() as temp_dir:
        app_root = Path(temp_dir)
        legacy_root = app_root / "runtime" / "addons" / "nc.identity_artifacts"
        legacy_raw = legacy_root / "artifacts" / "identity_old" / "raw.txt"
        legacy_raw.parent.mkdir(parents=True)
        legacy_raw.write_bytes(VALID_ARTIFACT_TEXT.encode("utf-8"))
        context = SimpleNamespace(
            app_root=app_root,
            storage=SimpleNamespace(addon_dir=legacy_root),
            get_service=lambda _name: None,
        )
        controller = IdentityArtifactsController(context)
        messages = []
        controller._show_message = lambda title, message: messages.append((title, message))

        assert controller.store.root_dir == app_root / "runtime" / "identity_relay"
        tab = controller.create_tab()
        assert tab is controller.root_widget
        assert controller.store.list_artifacts() == []
        assert messages == []
        assert legacy_raw.exists()

        controller.refresh_artifacts()
        assert controller.store.list_artifacts()
        assert legacy_raw.exists()
        assert messages
        assert "normalization" in messages[0][1].lower()
        tab.deleteLater()
        app.processEvents()


def test_file_import_reads_and_preserves_bytes() -> None:
    from PySide6 import QtWidgets

    raw = (
        b"\xef\xbb\xbf{\r\n  \"format\": \"NC_IDENTITY_EXPORT\",\r\n"
        b"  \"format_version\": \"1.1\",\r\n"
        b"  \"export_kind\": \"reflect_and_export_identity\",\r\n"
        b"  \"hot_identity\": {\"compressed_text\": \"File continuity\"}\r\n}"
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        app_root = Path(temp_dir)
        source_path = app_root / "identity.json"
        source_path.write_bytes(raw)
        context = SimpleNamespace(
            app_root=app_root,
            storage=SimpleNamespace(addon_dir=app_root / "legacy"),
            get_service=lambda _name: None,
        )
        controller = IdentityArtifactsController(context)
        original_dialog = QtWidgets.QFileDialog.getOpenFileName
        QtWidgets.QFileDialog.getOpenFileName = staticmethod(lambda *_args, **_kwargs: (str(source_path), ""))
        try:
            controller._import_file_artifact()
        finally:
            QtWidgets.QFileDialog.getOpenFileName = original_dialog

        artifact = controller.store.list_artifacts()[0]
        assert controller.store.load_raw_bytes(artifact["artifact_ref"]) == raw
        assert controller.store.load_metadata(artifact["artifact_ref"])["source_type"] == "file"


def test_ref_only_generic_persistence_and_matching_chat_restore() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        app_root = Path(temp_dir)
        context = SimpleNamespace(
            app_root=app_root,
            storage=SimpleNamespace(addon_dir=app_root / "legacy"),
            get_service=lambda _name: None,
        )
        controller = IdentityArtifactsController(context)
        first = controller.store.save_import(import_identity_artifact(VALID_ARTIFACT_TEXT))
        second = controller.store.save_import(
            import_identity_artifact(VALID_ARTIFACT_TEXT.replace("Continuity", "Second continuity"))
        )
        decisions = IdentityRelayDecisionStore(controller.store.root_dir)
        for artifact in (first, second):
            decisions.save_subject_attestation(
                artifact_hash=artifact.artifact_hash,
                normalizer_revision=NORMALIZER_REVISION,
                subject_class=SubjectClass.ASSISTANT_SELF,
                approved=True,
            )
        controller.set_persona_identity_ref(first.artifact_ref)
        assert controller.set_relay_enabled(False) is True

        assert controller.export_preset_state() == {"identity_relay_ref": first.artifact_ref}
        assert controller.export_session_state() == {"identity_relay_ref": first.artifact_ref}
        assert "hot_identity_text" not in json.dumps(controller.export_session_state())
        chat_state = controller.export_chat_session_state()
        assert chat_state == {"artifact_ref": first.artifact_ref, "state": "suspended"}

        controller.set_relay_enabled(True)
        controller.import_chat_session_state(chat_state)
        assert controller.capture_turn_snapshot()["state"] == "suspended"

        controller.set_persona_identity_ref(second.artifact_ref)
        controller.import_chat_session_state(chat_state)
        assert controller.capture_turn_snapshot()["state"] == "active"

        controller.import_preset_state({"legacy_identity_text": "must not persist"})
        assert controller.capture_turn_snapshot() is None


def _malformed_identity_refs() -> tuple[object, ...]:
    strict_ref = "library/" + "a" * 64 + ".json"
    return (
        "C:/identity/" + "a" * 64 + ".json",
        "library\\" + "a" * 64 + ".json",
        "../" + strict_ref,
        {"artifact_ref": strict_ref},
        "library/" + "a" * 63 + ".json",
        "library/" + "A" * 64 + ".json",
        "library/" + "a" * 64 + ".txt",
        strict_ref + "/payload",
    )


def test_malformed_preset_refs_are_rejected_and_not_exported() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = IdentityArtifactsController(
            SimpleNamespace(
                app_root=Path(temp_dir),
                storage=SimpleNamespace(addon_dir=Path(temp_dir) / "legacy"),
                get_service=lambda _name: None,
            )
        )
        strict_missing_ref = "library/" + "b" * 64 + ".json"
        for malformed_ref in _malformed_identity_refs():
            controller.import_preset_state({"identity_relay_ref": strict_missing_ref})
            controller.import_preset_state({"identity_relay_ref": malformed_ref})
            assert controller.export_preset_state() == {"identity_relay_ref": ""}
            assert controller.export_session_state() == {"identity_relay_ref": ""}
            assert controller.export_chat_session_state()["artifact_ref"] == ""
            assert controller.capture_turn_snapshot() is None


def test_malformed_generic_session_refs_are_rejected_and_not_exported() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = IdentityArtifactsController(
            SimpleNamespace(
                app_root=Path(temp_dir),
                storage=SimpleNamespace(addon_dir=Path(temp_dir) / "legacy"),
                get_service=lambda _name: None,
            )
        )
        strict_missing_ref = "library/" + "b" * 64 + ".json"
        for malformed_ref in _malformed_identity_refs():
            controller.import_session_state({"identity_relay_ref": strict_missing_ref})
            controller.import_session_state({"identity_relay_ref": malformed_ref})
            assert controller.export_session_state() == {"identity_relay_ref": ""}
            assert controller.export_preset_state() == {"identity_relay_ref": ""}
            assert controller.export_chat_session_state()["artifact_ref"] == ""
            assert controller.capture_turn_snapshot() is None


def test_strict_missing_ref_remains_unavailable_and_round_trips() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = IdentityArtifactsController(
            SimpleNamespace(
                app_root=Path(temp_dir),
                storage=SimpleNamespace(addon_dir=Path(temp_dir) / "legacy"),
                get_service=lambda _name: None,
            )
        )
        strict_missing_ref = "library/" + "b" * 64 + ".json"

        snapshot = controller.import_preset_state({"identity_relay_ref": strict_missing_ref})

        assert snapshot.connected_ref == ""
        assert snapshot.availability == "none"
        assert controller.capture_turn_snapshot() is None
        assert controller.export_preset_state() == {"identity_relay_ref": strict_missing_ref}
        assert controller.export_session_state() == {"identity_relay_ref": strict_missing_ref}
        assert controller.export_chat_session_state()["artifact_ref"] == strict_missing_ref
        assert "unavailable" in controller.last_visible_notice.lower()


def test_capture_is_detached_and_chat_context_uses_payload_snapshot() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        controller, stored = _authorized_controller(temp_dir)
        first = controller.capture_turn_snapshot()
        second = controller.capture_turn_snapshot()
        assert first == second
        assert first is not second

        payload = {
            "request_kind": "normal_chat",
            "identity_relay": {
                "state": "active",
                "artifact_ref": stored.artifact_ref,
                "artifact_hash": stored.artifact_hash,
                "hot_identity_text": "Frozen continuity",
            },
        }
        controller.set_relay_enabled(False)
        context = controller.collect_chat_context(payload)
        assert "Frozen continuity" in context["context"]
        assert controller.collect_chat_context({**payload, "request_kind": "proactive"}) is None
        assert controller.collect_chat_context({**payload, "identity_relay": {"state": "suspended"}}) is None
        assert controller.collect_chat_context({**payload, "identity_relay": {"state": "unavailable"}}) is None
        assert controller.collect_chat_context(
            {
                **payload,
                "identity_relay": {
                    **payload["identity_relay"],
                    "hot_identity_text": " \t\n",
                },
            }
        ) is None


def test_chat_context_preserves_exact_frozen_hot_identity_text() -> None:
    controller = IdentityArtifactsController(context=None)
    frozen_text = "  Frozen continuity with exact whitespace.  \n"
    context = controller.collect_chat_context(
        {
            "request_kind": "normal_chat",
            "identity_relay": {
                "state": "active",
                "artifact_ref": "library/" + "a" * 64 + ".json",
                "artifact_hash": "a" * 64,
                "hot_identity_text": frozen_text,
            },
        }
    )

    assert context is not None
    assert context["context"].endswith(frozen_text)


def test_addon_routes_exact_identity_relay_capabilities() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        addon = Addon.__new__(Addon)
        addon.controller, stored = _authorized_controller(
            temp_dir,
            VALID_ARTIFACT_TEXT.replace("Continuity", "Frozen continuity"),
        )

        captured = addon.invoke_capability("identity_relay.capture_turn", {})
        assert captured["state"] == "active"
        assert addon.invoke_capability("identity_relay.chat_session.export", {})[
            "artifact_ref"
        ] == stored.artifact_ref
        assert addon.invoke_capability("real_ui.sync_widget_names", {"kind": "combo"}) == {
            "combo": ["identity_relay_ref_combo"],
            "checkbox": [],
        }
        assert addon.invoke_capability("real_ui.sync_widget_names", {"kind": "checkbox"}) == {
            "combo": [],
            "checkbox": ["identity_relay_toggle"],
        }
        assert addon.invoke_capability("real_ui.bind_runtime_controls", {}) is False
        assert addon.invoke_capability("real_ui.mirror_runtime_widgets", {}) is False
        assert addon.invoke_capability("identity_relay.capture_turn.extra", {}) is None


def test_addon_preserves_legacy_capture_and_routes_explicit_v2_capabilities() -> None:
    from addons.identity_artifacts.relay_state import IdentityRelayCapture

    with tempfile.TemporaryDirectory() as temp_dir:
        addon = Addon.__new__(Addon)
        addon.controller, stored = _authorized_controller(
            temp_dir,
            VALID_ARTIFACT_TEXT.replace("Continuity", "Exact legacy continuity"),
        )

        legacy = addon.invoke_capability("identity_relay.capture_turn", {})
        assert legacy == {
            "state": "active",
            "artifact_ref": stored.artifact_ref,
            "artifact_hash": stored.artifact_hash,
            "hot_identity_text": "Exact legacy continuity",
            "failure_code": None,
        }

        captured = addon.invoke_capability(
            "identity_relay.capture_turn",
            {
                "schema_version": 2,
                "normalizer_revision": "caller-controlled-revision",
                "attestation_revision": 999,
                "transient_activation": {},
                "runtime_use": {
                    "surface": "chat",
                    "provider_is_remote": False,
                    "subject_class": "other_entity",
                    "subject_approved": False,
                },
                "frozen_provider": {},
            },
        )
        assert isinstance(captured, IdentityRelayCapture)
        assert captured.normalizer_revision == NORMALIZER_REVISION
        assert captured.attestation_revision == 1
        assert captured.runtime_use["subject_class"] == "assistant_self"

        prepared = addon.invoke_capability(
            "identity_relay.prepare_turn",
            {
                "schema_version": 2,
                "capture": captured,
                "query": make_query_envelope(),
            },
        )
        assert prepared.schema_version == 2
        assert addon.invoke_capability(
            "identity_relay.render_judge_request",
            {"schema_version": 2, "prepared": prepared},
        ) == ()
        finalized = addon.invoke_capability(
            "identity_relay.finalize_turn",
            {"schema_version": 2, "prepared": prepared, "judge_payload": None},
        )
        assert finalized.schema_version == 2

        prompt_text = "Exact normalized projection text"
        context = addon.invoke_capability(
            "chat_context.collect",
            {
                "schema_version": 2,
                "request_kind": "normal_chat",
                "identity_relay": {
                    "schema_version": 2,
                    "projection_kind": "normalized_projection",
                    "status": "ready",
                    "artifact_ref": stored.artifact_ref,
                    "snapshot_hash": "c" * 64,
                    "prompt_text": prompt_text,
                },
            },
        )
        assert context["context"] == prompt_text
        assert context["debug"]["snapshot_hash"] == "c" * 64


def test_v2_mode_snapshot_freezes_off_before_authority_capture() -> None:
    from addons.identity_artifacts import relay_state
    from addons.identity_artifacts.relay_state import IdentityRelayCapture

    with tempfile.TemporaryDirectory() as temp_dir:
        addon = Addon.__new__(Addon)
        addon.controller, stored = _authorized_controller(temp_dir)

        active = addon.invoke_capability(
            "identity_relay.capture_mode",
            {"schema_version": 2},
        )
        assert active.enabled is True
        assert active.artifact_ref == stored.artifact_ref
        assert active.artifact_hash == stored.artifact_hash

        assert addon.controller.set_relay_enabled(False) is True
        accepted_off = addon.invoke_capability(
            "identity_relay.capture_mode",
            {"schema_version": 2},
        )
        assert accepted_off.enabled is False
        assert addon.controller.set_relay_enabled(True) is True

        original_freeze = relay_state._freeze_mapping

        def unexpected_authority_copy(_value):
            raise AssertionError("accepted OFF mode must not copy identity authority")

        relay_state._freeze_mapping = unexpected_authority_copy
        try:
            capture = addon.invoke_capability(
                "identity_relay.capture_turn",
                {
                    "schema_version": 2,
                    "mode_snapshot": accepted_off,
                    "frozen_provider": {"provider_name": "must-not-copy"},
                },
            )
        finally:
            relay_state._freeze_mapping = original_freeze

        assert isinstance(capture, IdentityRelayCapture)
        assert capture.enabled is False
        assert capture.artifact_ref == stored.artifact_ref
        assert capture.artifact_hash == stored.artifact_hash
        assert capture.frozen_normalized_model == {}
        assert capture.frozen_provider == {}


def test_manifest_rebrands_only_display_product_identity() -> None:
    manifest = json.loads(Path(__file__).with_name("addon.json").read_text(encoding="utf-8"))
    assert manifest["id"] == "nc.identity_artifacts"
    assert manifest["ui"][0]["id"] == "identity_artifacts_tab"
    assert manifest["name"] == "NC Identity Relay"
    assert manifest["ui"][0]["title"] == "NC Identity Relay"


def test_normalized_derivative_is_versioned_and_legacy_projection_remains_readable() -> None:
    raw_bytes = FIXTURE_PATH.read_bytes()
    with tempfile.TemporaryDirectory() as temp_dir:
        store = IdentityArtifactStore(Path(temp_dir) / "identity_relay")
        stored = store.save_import(import_identity_artifact(raw_bytes, source_type="file"))

        model = store.rebuild_normalized(stored.artifact_ref)
        loaded = store.load_normalized(stored.artifact_ref)
        versioned_path = (
            store.derived_dir
            / stored.artifact_hash
            / f"{NORMALIZER_REVISION}.json"
        )
        versioned_payload = json.loads(versioned_path.read_text(encoding="utf-8"))
        legacy_payload = json.loads(stored.derived_path.read_text(encoding="utf-8"))

        assert loaded == model
        assert versioned_payload["artifact_hash"] == stored.artifact_hash
        assert versioned_payload["normalizer_revision"] == NORMALIZER_REVISION
        assert versioned_payload["schema_version"] == model.schema_version
        assert versioned_payload["created_at"]
        assert versioned_payload["review_state"] == "pending_attestation"
        assert legacy_payload["projection_kind"] == "legacy_projection"
        assert store.load_structured(stored.artifact_ref)["hot_identity_text"].startswith(
            "Experienced professional programmer"
        )
        assert stored.canonical_path.read_bytes() == raw_bytes


def test_normalized_digest_is_stable_across_hash_seeds_and_reload() -> None:
    payload = {
        "format": "NC_IDENTITY_EXPORT",
        "format_version": "1.1",
        "export_kind": "reflect_and_export_identity",
        "default_runtime_context": "private_local_1on1",
        "exposure_model": {
            "default_projection": "full_private",
            "default_exposure_policy": {
                "private_local_1on1": "allow",
                "private_remote_1on1": "deny",
                "external_export": "deny",
                "debug_logs": "redact",
            },
            "default_use_policy": {
                "preferred_runtime_use": "always_inject",
                "eligible_for_always_inject": True,
                "allowed_surfaces": ["local_private_chat"],
            },
        },
        "hot_identity": {
            "claims": [
                {
                    "claim_id": "hash_seed_stability",
                    "claim_text": "My normalized digest is process-stable.",
                    "subject_refs": ["assistant_self"],
                    "stability": "stable",
                }
            ]
        },
    }
    child = "\n".join(
        (
            "import hashlib, json, sys",
            "from pathlib import Path",
            "from addons.identity_artifacts.attestations import IdentityRelayDecisionStore",
            "from addons.identity_artifacts.importer import import_identity_artifact",
            "from addons.identity_artifacts.normalized_model import NORMALIZER_REVISION, SubjectClass, normalized_identity_digest",
            "from addons.identity_artifacts.storage import IdentityArtifactStore",
            "mode, root_text, payload_text = sys.argv[1:4]",
            "root, payload_path = Path(root_text), Path(payload_text)",
            "raw_bytes = payload_path.read_bytes()",
            "artifact_hash = hashlib.sha256(raw_bytes).hexdigest()",
            "artifact_ref = f'library/{artifact_hash}.json'",
            "store = IdentityArtifactStore(root)",
            "if mode == 'save':",
            "    stored = store.save_import(import_identity_artifact(raw_bytes, source_type='file'))",
            "    model = store.rebuild_normalized(stored.artifact_ref)",
            "    digest = normalized_identity_digest(model)",
            "    IdentityRelayDecisionStore(root).save_subject_attestation(artifact_hash=artifact_hash, normalizer_revision=NORMALIZER_REVISION, subject_class=SubjectClass.ASSISTANT_SELF, approved=True, normalized_digest=digest)",
            "else:",
            "    model = store.load_normalized(artifact_ref)",
            "    digest = normalized_identity_digest(model)",
            "resolution = store.resolve_artifact(artifact_ref)",
            "attestation = IdentityRelayDecisionStore(root).load(artifact_hash).subject_attestation",
            "invalid_path = store.derived_dir / artifact_hash / f'{NORMALIZER_REVISION}.invalid.json'",
            "print(json.dumps({'digest': digest, 'failure_code': resolution.failure_code, 'quarantined': invalid_path.exists(), 'approved': bool(attestation and attestation.approved), 'attested_digest': str(attestation.normalized_digest if attestation else '')}, sort_keys=True))",
        )
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        payload_path = temp_path / "artifact.json"
        payload_path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        store_path = temp_path / "identity_relay"
        results = []
        for index, seed in enumerate(("1", "2", "17", "101")):
            environment = dict(os.environ)
            environment["PYTHONHASHSEED"] = seed
            completed = subprocess.run(
                (
                    sys.executable,
                    "-X",
                    "utf8",
                    "-c",
                    child,
                    "save" if index == 0 else "load",
                    str(store_path),
                    str(payload_path),
                ),
                cwd=ROOT_DIR,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            assert completed.returncode == 0, completed.stderr
            results.append(json.loads(completed.stdout.strip()))

        assert len({item["digest"] for item in results}) == 1
        assert all(item["failure_code"] is None for item in results)
        assert all(item["quarantined"] is False for item in results)
        assert all(item["approved"] is True for item in results)
        assert all(item["attested_digest"] == item["digest"] for item in results)


def test_corrupt_normalized_derivative_requires_explicit_rebuild_and_review() -> None:
    raw_bytes = FIXTURE_PATH.read_bytes()
    with tempfile.TemporaryDirectory() as temp_dir:
        store = IdentityArtifactStore(Path(temp_dir) / "identity_relay")
        stored = store.save_import(import_identity_artifact(raw_bytes, source_type="file"))
        original = store.rebuild_normalized(stored.artifact_ref)
        versioned_path = (
            store.derived_dir
            / stored.artifact_hash
            / f"{NORMALIZER_REVISION}.json"
        )
        versioned_path.write_text("{corrupt", encoding="utf-8")

        try:
            store.load_normalized(stored.artifact_ref)
        except ValueError as exc:
            assert "normalized" in str(exc).lower()
        else:
            raise AssertionError("corrupt normalized data must be quarantined")
        assert versioned_path.read_text(encoding="utf-8") == "{corrupt"
        rebuilt = store.rebuild_normalized(stored.artifact_ref)
        assert rebuilt == original
        assert store.resolve_artifact(stored.artifact_ref).failure_code == "attestation_required"
        assert stored.canonical_path.read_bytes() == raw_bytes


def test_normalized_derivative_tampering_never_reuses_existing_authority() -> None:
    raw_bytes = FIXTURE_PATH.read_bytes()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        controller = IdentityArtifactsController(
            SimpleNamespace(
                app_root=root,
                storage=SimpleNamespace(addon_dir=root / "legacy"),
                get_service=lambda _name: None,
            )
        )
        store = controller.store
        stored = store.save_import(import_identity_artifact(raw_bytes, source_type="file"))
        original = store.rebuild_normalized(stored.artifact_ref)
        decisions = controller.decision_store
        versioned_path = (
            store.derived_dir
            / stored.artifact_hash
            / f"{NORMALIZER_REVISION}.json"
        )
        initial_payload = json.loads(versioned_path.read_text(encoding="utf-8"))
        assert initial_payload["normalized_digest"] == normalized_identity_digest(original)
        assert store.load_normalized(stored.artifact_ref) == original

        def tamper_text(payload):
            payload["normalized_model"]["records"][0]["source_text"] = (
                "Tampered first-person continuity."
            )

        def tamper_kernel(payload):
            payload["normalized_model"]["kernel_record_ids"] = []

        def tamper_policy(payload):
            payload["normalized_model"]["records"][0]["declared_policy"] = {
                "eligible_for_always_inject": True,
                "eligible_for_provider_transmission": True,
            }

        provider_calls = []
        controller._chat_completion = lambda *_args, **_kwargs: provider_calls.append(True)
        for mutator in (tamper_text, tamper_kernel, tamper_policy):
            store.rebuild_normalized(stored.artifact_ref)
            decisions.save_subject_attestation(
                artifact_hash=stored.artifact_hash,
                normalizer_revision=NORMALIZER_REVISION,
                subject_class=SubjectClass.ASSISTANT_SELF,
                approved=True,
            )
            payload = json.loads(versioned_path.read_text(encoding="utf-8"))
            mutator(payload)
            forged_model = normalized_identity_from_dict(payload["normalized_model"])
            payload["normalized_digest"] = normalized_identity_digest(forged_model)
            tampered_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            versioned_path.write_bytes(tampered_bytes)

            try:
                store.load_normalized(stored.artifact_ref)
            except ValueError as exc:
                assert "normalized" in str(exc).lower()
            else:
                raise AssertionError("self-consistent derivative tampering must block")

            assert versioned_path.read_bytes() == tampered_bytes
            assert decisions.load(stored.artifact_hash).subject_attestation is None
            assert store.resolve_artifact(stored.artifact_ref).failure_code == (
                "normalized_rebuild_review_required"
            )
            controller.set_persona_identity_ref(stored.artifact_ref)
            assert "rebuild" in controller.last_visible_notice.lower()
            assert "review" in controller.last_visible_notice.lower()
            assert controller.capture_turn({"frozen_provider": {}}) is None
            assert provider_calls == []

        rebuilt = store.rebuild_normalized(stored.artifact_ref)
        assert rebuilt == original
        assert store.resolve_artifact(stored.artifact_ref).failure_code == "attestation_required"
        decisions.save_subject_attestation(
            artifact_hash=stored.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            subject_class=SubjectClass.ASSISTANT_SELF,
            approved=True,
            normalized_digest="f" * 64,
        )
        assert store.resolve_artifact(stored.artifact_ref).failure_code == (
            "attestation_digest_mismatch"
        )
        controller.set_persona_identity_ref(stored.artifact_ref)
        assert "review" in controller.last_visible_notice.lower()
        assert provider_calls == []

        decisions.save_subject_attestation(
            artifact_hash=stored.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            subject_class=SubjectClass.ASSISTANT_SELF,
            approved=True,
        )
        legacy_payload = json.loads(versioned_path.read_text(encoding="utf-8"))
        legacy_payload.pop("normalized_digest")
        versioned_path.write_text(json.dumps(legacy_payload), encoding="utf-8")
        attestation_path = store.root_dir / "attestations" / f"{stored.artifact_hash}.json"
        legacy_attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
        legacy_attestation["subject_attestation"].pop("normalized_digest")
        attestation_path.write_text(json.dumps(legacy_attestation), encoding="utf-8")
        try:
            store.load_normalized(stored.artifact_ref)
        except ValueError:
            pass
        else:
            raise AssertionError("legacy unbound derivative must require rebuild and review")
        store.rebuild_normalized(stored.artifact_ref)
        assert store.resolve_artifact(stored.artifact_ref).failure_code == "attestation_required"
        attestation = decisions.save_subject_attestation(
            artifact_hash=stored.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            subject_class=SubjectClass.ASSISTANT_SELF,
            approved=True,
        )
        assert attestation.normalized_digest == normalized_identity_digest(original)
        assert store.resolve_artifact(stored.artifact_ref).failure_code is None
        assert original.records[0].source_text != "Tampered first-person continuity."


def main() -> int:
    test_relay_off_has_zero_work_fast_path()
    test_request_local_capture_is_atomic_and_controller_uses_it()
    test_capture_detaches_json_values_and_rejects_mutable_leaf_objects()
    test_v2_capture_uses_cached_authority_without_storage_or_resolver_work()
    test_v2_disabled_capture_is_lock_only_and_contains_no_identity_authority()
    test_v2_capture_freezes_the_request_local_provider_summary()
    test_v2_capture_without_current_cached_authority_fails_closed_without_disk()
    test_late_refresh_does_not_reconnect_after_disconnect()
    test_late_refresh_does_not_replace_a_newer_connection()
    test_cancelled_connection_apply_commits_no_attestation_review_or_authority()
    test_connection_apply_wins_delete_race_atomically()
    test_delete_wins_connection_apply_race_without_hidden_authority()
    test_refresh_disconnects_same_ref_when_authority_is_revoked()
    test_session_reset_revalidates_authority_and_transients_off_capture_path()
    test_session_load_revalidates_authority_and_transients_for_saved_state()
    test_same_ref_revalidation_disconnects_revoked_authority()
    test_controller_remote_provider_capture_narrows_unauthorized_kernel()
    test_controller_freezes_owner_override_for_remote_turn_authorization()
    test_remote_provider_omits_unauthorized_kernel_without_blocking_authorized_identity()
    test_public_controller_off_path_does_not_parse_query_or_call_dependencies()
    test_controller_capture_checks_off_state_before_payload_or_embedding_config()
    test_ready_snapshot_is_detached_versioned_and_opaque_to_engine()
    test_transient_policy_is_operation_specific_before_candidates_and_judge()
    test_persistence_ceiling_makes_denied_projection_volatile_and_visible()
    test_service_authorizes_each_runtime_operation_independently()
    test_snapshot_hash_is_stable_for_identical_projection_content()
    test_snapshot_hash_covers_exact_persisted_envelope_content()
    test_persisted_snapshot_authorization_is_durable_exact_and_exposure_bound()
    test_snapshot_authorizations_are_distinct_and_exactly_referenced()
    test_snapshot_authorization_write_failure_visibly_downgrades_to_volatile()
    test_debug_trace_policy_enforces_deny_redact_and_allow_boundaries()
    test_capacity_failure_externalizes_debug_policy_for_every_mode()
    test_capacity_denial_externalizes_debug_policy_for_every_mode()
    test_authorization_store_failure_externalizes_debug_policy_once()
    test_empty_projection_never_defaults_to_persistent()
    test_trace_and_decision_metadata_require_persistence_authorization()
    test_finalize_accepts_structured_judge_payload_with_task4_validation()
    test_judge_exception_degrades_visibly_without_dropping_deterministic_matches()
    test_malformed_and_unknown_judge_ids_degrade_without_authorizing_them()
    test_controller_surfaces_judge_degradation_notice_payload()
    test_controller_trace_dialog_recurses_ids_and_labels_redacted_fields()
    test_remote_frozen_provider_locality_survives_authority_validation()
    test_accepted_turn_uses_frozen_authority_before_prepare_and_during_judge()
    test_unapproved_subject_blocks_before_retrieval_or_judge_rendering()
    test_deterministic_candidates_bypass_judge_request_rendering()
    test_candidate_retrieval_exception_becomes_blocked_prepared_result()
    test_semantic_embedding_and_index_exceptions_degrade_without_losing_deterministic_matches()
    test_semantic_query_uses_every_structured_signal_with_integer_context()
    test_local_embedding_endpoint_is_independently_authorized()
    test_remote_embedding_endpoint_runs_when_independently_authorized()
    test_remote_embedding_endpoint_makes_zero_calls_when_not_authorized()
    test_owner_override_authorizes_remote_embedding_endpoint()
    test_unclassifiable_embedding_endpoint_makes_zero_calls()
    test_chat_locality_cannot_authorize_a_remote_embedding_endpoint()
    test_controller_wires_runtime_semantic_dependencies_into_turn_capture()
    test_unserializable_judge_payload_degrades_without_dropping_stable_matches()
    test_judge_conversion_isolated_per_batch_for_malformed_mixed_payloads()
    test_projection_render_exception_becomes_blocked_snapshot()
    test_malformed_judge_renderer_result_becomes_blocked_prepared_result()
    test_malformed_projection_renderer_result_becomes_blocked_snapshot()
    test_malformed_capacity_result_becomes_blocked_snapshot()
    test_invalid_capture_objects_block_service_with_zero_downstream_work()
    test_public_controller_invalid_capture_blocks_before_query_parsing()
    test_token_count_exception_becomes_blocked_snapshot_with_degradation()
    test_identity_artifacts_side_tab_icon_is_registered()
    test_gemini_flash_v1_1_fixture_imports_permissively()
    test_unknown_fields_are_preserved_but_not_structurally_imported()
    test_broken_source_reference_warns_without_rejecting_artifact()
    test_invalid_json_stores_failed_raw_artifact()
    test_missing_preview_does_not_block_usable_normalized_identity()
    test_shipped_chatgpt_fixture_reaches_ready_local_relay_snapshot()
    test_non_string_hot_identity_never_becomes_relay_continuity()
    test_store_round_trips_raw_artifact_exactly()
    test_file_import_preserves_exact_bytes_and_full_hash()
    test_pasted_import_defines_utf8_canonical_bytes()
    test_store_deduplicates_exact_bytes_and_rejects_unsafe_refs()
    test_store_rejects_mismatched_import_hash_before_writing()
    test_store_reextracts_verified_bytes_before_publishing_derived_data()
    test_refresh_rebuilds_semantically_stale_derived_record()
    test_refresh_repairs_corrupt_derived_and_index_without_losing_file_provenance()
    test_refresh_repairs_valid_but_incorrect_index_provenance_from_derived()
    test_refresh_excludes_tampered_canonical_artifacts_from_list_and_index()
    test_legacy_inspection_adapters_bridge_to_strict_refs()
    test_legacy_migration_is_visible_non_destructive_and_idempotent()
    test_delete_blocks_active_and_direct_preset_references()
    test_delete_blocks_loaded_session_and_removes_owned_sensitive_derivatives()
    test_delete_cleans_owned_v1_and_v2_authorizations_and_reports_malformed_v1()
    test_controller_delete_blocks_runtime_references_and_purges_projections()
    test_controller_guard_block_is_mutation_free_for_all_derivatives()
    test_delete_fails_closed_for_unreadable_direct_presets()
    test_store_rejects_backslash_refs_without_deleting_canonical_artifact()
    test_delete_retains_canonical_artifact_when_derived_delete_fails()
    test_delete_retains_canonical_artifact_when_index_write_fails()
    test_relay_model_defaults_new_ref_on_and_preserves_same_ref_state()
    test_relay_snapshot_is_immutable_after_toggle_and_persona_change()
    test_controller_uses_canonical_root_and_explicit_legacy_migration()
    test_file_import_reads_and_preserves_bytes()
    test_ref_only_generic_persistence_and_matching_chat_restore()
    test_malformed_preset_refs_are_rejected_and_not_exported()
    test_malformed_generic_session_refs_are_rejected_and_not_exported()
    test_strict_missing_ref_remains_unavailable_and_round_trips()
    test_capture_is_detached_and_chat_context_uses_payload_snapshot()
    test_chat_context_preserves_exact_frozen_hot_identity_text()
    test_addon_routes_exact_identity_relay_capabilities()
    test_addon_preserves_legacy_capture_and_routes_explicit_v2_capabilities()
    test_v2_mode_snapshot_freezes_off_before_authority_capture()
    test_manifest_rebrands_only_display_product_identity()
    test_normalized_derivative_is_versioned_and_legacy_projection_remains_readable()
    test_normalized_digest_is_stable_across_hash_seeds_and_reload()
    test_corrupt_normalized_derivative_requires_explicit_rebuild_and_review()
    test_normalized_derivative_tampering_never_reuses_existing_authority()
    print("smoke_identity_artifacts: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
