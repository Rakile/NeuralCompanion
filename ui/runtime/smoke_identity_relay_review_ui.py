from __future__ import annotations

import sys
import tempfile
import threading
import time
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from PySide6 import QtCore, QtTest, QtWidgets

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from addons.identity_artifacts.attestations import (  # noqa: E402
    IdentityRelayDecisionStore,
    ReviewDecision,
    SubjectClassificationProposal,
    TransientActivation,
)
from addons.identity_artifacts import controller as controller_module  # noqa: E402
from addons.identity_artifacts.controller import IdentityArtifactsController  # noqa: E402
from addons.identity_artifacts.importer import import_identity_artifact  # noqa: E402
from addons.identity_artifacts.normalized_model import (  # noqa: E402
    NORMALIZER_REVISION,
    ReviewItem,
    ReviewKind,
    RuntimeLayer,
    SubjectClass,
    TransientRecord,
)
from addons.identity_artifacts.policy import (  # noqa: E402
    RuntimeUse,
    UserApproval,
    evaluate_effective_use,
)
from addons.identity_artifacts.relay_state import IdentityRelayCapture  # noqa: E402
from addons.identity_artifacts.relay_state import IdentityRelayModel  # noqa: E402
from addons.identity_artifacts.retrieval import (  # noqa: E402
    CandidateActivation,
    CandidateSet,
    build_turn_query_envelope,
)
from addons.identity_artifacts.service import IdentityRelayService  # noqa: E402
from addons.identity_artifacts.review_dialog import (  # noqa: E402
    ConnectionReviewDialog,
    ConnectionReviewModel,
    ConnectionReviewResult,
    ReviewItemDecision,
)
from addons.identity_artifacts.storage import (  # noqa: E402
    ArtifactResolution,
    IdentityArtifactStore,
)


VALID_ARTIFACT = """{
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
          "eligible_for_private_retrieval": true
        }
      }
    ]
  },
  "transient_continuity": {
    "id": "transient-1",
    "text": "Sensitive active thread",
    "ttl": "session"
  }
}"""

UNKNOWN_RECORD_ARTIFACT = """{
  "format": "NC_IDENTITY_EXPORT",
  "format_version": "1.1",
  "export_kind": "reflect_and_export_identity",
  "hot_identity": {"compressed_text": "Continuity"},
  "identity_items": [
    {"id": "record-1", "text": "Continuity claim", "category": "self_model"}
  ]
}"""


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _drain_until(predicate, timeout: float = 3.0):
    app = _app()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents(QtCore.QEventLoop.AllEvents, 20)
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("timed out waiting for queued Qt completion")


def _controller(temp_dir: str):
    root = Path(temp_dir)
    context = SimpleNamespace(
        app_root=root,
        storage=SimpleNamespace(addon_dir=root / "legacy"),
        get_service=lambda _name: None,
    )
    return IdentityArtifactsController(context)


def _approve_self_review(dialog: ConnectionReviewDialog) -> None:
    dialog.choose_subject(SubjectClass.ASSISTANT_SELF)
    for actions in dialog.review_action_buttons.values():
        actions["approve"].click()
    if dialog.model.transient_records:
        dialog.transient_inactive_button.click()


def _review_model(*, subject=SubjectClass.UNKNOWN, has_transient=False, proposal=None):
    review = ReviewItem(
        "review-1",
        ReviewKind.RUNTIME_LAYER,
        ("record-1",),
        ("identity.items[0]",),
        "retrievable",
        "permission is ambiguous",
        details={"supported_runtime_use_scopes": ("contextual_retrieval",)},
    )
    transient = (
        TransientRecord(
            record_id="transient-1",
            source_path="transient_continuity",
            source_text="Sensitive active thread",
            included_item_ids=("record-1",),
            ttl_hint="session",
            expiration_notes=("session-scoped",),
            confidence=0.5,
            staleness_risk=0.75,
            provenance={"provider": "fixture"},
        ),
    ) if has_transient else ()
    return ConnectionReviewModel(
        artifact_ref="library/" + "a" * 64 + ".json",
        artifact_hash="a" * 64,
        identity_label="Continuity",
        normalizer_revision=NORMALIZER_REVISION,
        schema_version=1,
        subject_class=subject,
        proposal=proposal,
        review_items=(review,),
        transient_records=transient,
        migration_messages=("Legacy bytes preserved; original normalization cannot be reversed.",),
        policy_narrowing=("record-1: always_inject narrowed to retrievable by private runtime policy",),
        index_status="embedding_model_mismatch; rebuild required",
        trace_ids=("trace-123",),
        source_text_by_record={"record-1": "Sensitive source wording"},
    )


def test_review_dialog_offers_compact_safe_connect_and_scrollable_advanced_review():
    _app()
    dialog = ConnectionReviewDialog(_review_model(has_transient=True))
    assert dialog.advanced_scroll.isHidden()
    assert dialog.advanced_scroll.widgetResizable() is True
    assert set(dialog.review_action_buttons["review-1"]) == {
        "approve",
        "reclassify",
        "narrow_use",
        "quarantine",
    }
    assert dialog.apply_button.isEnabled() is True

    dialog.choose_subject("assistant_self")
    assert dialog.apply_button.isEnabled() is True
    assert dialog.apply_button.text() == "Connect as Assistant Identity"

    dialog.advanced_button.click()
    assert dialog.advanced_scroll.isHidden() is False
    assert "Sensitive source wording" in dialog.review_text.toPlainText()
    assert "normalizer" in dialog.transparency_text.toPlainText().lower()
    assert "migration" in dialog.transparency_text.toPlainText().lower()
    assert "narrow" in dialog.transparency_text.toPlainText().lower()
    assert "rebuild" in dialog.transparency_text.toPlainText().lower()
    assert "trace-123" in dialog.transparency_text.toPlainText()

    applied = []
    dialog.reviewApplied.connect(applied.append)
    dialog.apply_button.click()
    assert len(applied) == 1
    assert applied[0].subject_class == SubjectClass.ASSISTANT_SELF
    assert applied[0].transient_active is False
    assert tuple(item.action for item in applied[0].item_decisions) == ("approve",)
    dialog.deleteLater()


def test_primary_connect_action_replaces_stale_contextual_subject():
    _app()
    dialog = ConnectionReviewDialog(
        _review_model(subject=SubjectClass.OTHER_ENTITY)
    )
    applied = []
    dialog.reviewApplied.connect(applied.append)

    assert dialog.selected_subject() == SubjectClass.OTHER_ENTITY
    assert dialog.apply_button.text() == "Connect as Assistant Identity"
    dialog.apply_button.click()

    assert len(applied) == 1
    assert applied[0].subject_class == SubjectClass.ASSISTANT_SELF
    assert tuple(item.action for item in applied[0].item_decisions) == ("approve",)
    dialog.deleteLater()


def test_disconnect_review_has_honest_confirmation_action():
    _app()
    dialog = ConnectionReviewDialog(
        ConnectionReviewModel(
            artifact_ref="",
            artifact_hash="",
            identity_label="Disconnect Identity Relay",
            normalizer_revision=NORMALIZER_REVISION,
            schema_version=1,
            subject_class=SubjectClass.ASSISTANT_SELF,
        )
    )
    applied = []
    dialog.reviewApplied.connect(applied.append)

    assert dialog.apply_button.text() == "Disconnect Identity Relay"
    assert dialog.subject_row_widget.isHidden()
    assert dialog.advanced_button.isHidden()
    dialog.apply_button.click()

    assert len(applied) == 1
    assert applied[0].artifact_ref == ""
    dialog.deleteLater()


def test_active_model_proposal_is_attributed_and_never_auto_applied():
    _app()
    proposal = SubjectClassificationProposal(
        SubjectClass.ASSISTANT_SELF,
        "First-person declarations dominate the artifact.",
        ("hot_identity.claims[0]",),
        provider="openai",
        model="gpt-test",
    )
    dialog = ConnectionReviewDialog(_review_model(proposal=proposal))
    assert "openai" in dialog.proposal_label.text()
    assert "gpt-test" in dialog.proposal_label.text()
    assert "First-person declarations" in dialog.proposal_label.text()
    assert dialog.selected_subject() == SubjectClass.UNKNOWN
    assert dialog.apply_button.isEnabled() is True
    dialog.deleteLater()


def test_window_close_is_not_an_implicit_decision():
    app = _app()
    dialog = ConnectionReviewDialog(_review_model())
    applied = []
    cancelled = []
    dialog.reviewApplied.connect(applied.append)
    dialog.reviewCancelled.connect(lambda: cancelled.append(True))
    dialog.show()
    app.processEvents()
    dialog.close()
    app.processEvents()
    assert dialog.isVisible()
    assert applied == []
    assert cancelled == []
    dialog.cancel_review()
    assert cancelled == [True]


def test_connection_requires_explicit_subject_and_non_self_stays_contextual_only():
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        stored = controller.store.save_import(import_identity_artifact(VALID_ARTIFACT))
        controller.request_connection(stored.artifact_ref)
        assert controller.relay_model.ui_snapshot().connected_ref == ""
        assert controller.review_dialog is not None
        assert controller.review_dialog.isVisible()
        controller.review_dialog.choose_subject("other_entity")
        for actions in controller.review_dialog.review_action_buttons.values():
            actions["approve"].click()
        controller.review_dialog.transient_inactive_button.click()
        controller.review_dialog.accept_review()
        assert controller.relay_model.ui_snapshot().connected_ref == ""
        assert "contextual-only" in controller.last_visible_notice.lower()
        saved = IdentityRelayDecisionStore(controller.store.root_dir).load(stored.artifact_hash)
        assert saved.subject_attestation.subject_class == SubjectClass.OTHER_ENTITY
        assert saved.subject_attestation.approved is True


def test_assistant_self_connects_only_after_apply_and_cancel_restores_previous_state():
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        first = controller.store.save_import(import_identity_artifact(VALID_ARTIFACT))
        second = controller.store.save_import(
            import_identity_artifact(VALID_ARTIFACT.replace("Continuity", "Second continuity"))
        )
        decisions = IdentityRelayDecisionStore(controller.store.root_dir)
        decisions.save_subject_attestation(
            artifact_hash=first.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            subject_class=SubjectClass.ASSISTANT_SELF,
            approved=True,
        )
        controller.set_persona_identity_ref(first.artifact_ref)
        controller.update_runtime_transparency(status="blocked", reason="old identity state")

        controller.request_connection(second.artifact_ref)
        assert controller.relay_model.ui_snapshot().connected_ref == first.artifact_ref
        controller.review_dialog.cancel_review()
        assert controller.relay_model.ui_snapshot().connected_ref == first.artifact_ref

        controller.request_connection(second.artifact_ref)
        controller.review_dialog.choose_subject("assistant_self")
        for actions in controller.review_dialog.review_action_buttons.values():
            actions["approve"].click()
        controller.review_dialog.transient_activate_button.click()
        controller.review_dialog.accept_review()
        assert controller.relay_model.ui_snapshot().connected_ref == second.artifact_ref
        assert controller._runtime_transparency["status"] == "ready"
        assert controller._runtime_transparency["reason"] == ""


def test_primary_connect_replaces_saved_contextual_subject_and_connects():
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        stored = controller.store.save_import(import_identity_artifact(VALID_ARTIFACT))
        decisions = IdentityRelayDecisionStore(controller.store.root_dir)
        decisions.save_subject_attestation(
            artifact_hash=stored.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            subject_class=SubjectClass.OTHER_ENTITY,
            approved=True,
        )

        controller.request_connection(stored.artifact_ref)
        assert controller.review_dialog is not None
        assert controller.review_dialog.selected_subject() == SubjectClass.OTHER_ENTITY
        controller.review_dialog.apply_button.click()

        assert controller.relay_model.ui_snapshot().connected_ref == stored.artifact_ref
        saved = decisions.load(stored.artifact_hash)
        assert saved.subject_attestation.subject_class == SubjectClass.ASSISTANT_SELF
        assert "connected" in controller.last_visible_notice.lower()


def test_valid_saved_assistant_identity_restores_without_second_review():
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        stored = controller.store.save_import(import_identity_artifact(VALID_ARTIFACT))
        IdentityRelayDecisionStore(controller.store.root_dir).save_subject_attestation(
            artifact_hash=stored.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            subject_class=SubjectClass.ASSISTANT_SELF,
            approved=True,
        )

        controller.import_session_state({"identity_relay_ref": stored.artifact_ref})

        assert controller.relay_model.ui_snapshot().connected_ref == stored.artifact_ref
        assert controller.review_dialog is None


def test_subject_proposal_runs_off_qt_thread_and_stale_completion_is_discarded():
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        controller._force_async_operations = True
        qt_thread = threading.get_ident()
        calls = []
        completions = []

        def slow(token):
            calls.append(threading.get_ident())
            while not token.is_cancelled():
                time.sleep(0.005)
            return "stale"

        controller._start_operation("proposal", slow, completions.append)
        controller._start_operation("proposal", lambda _token: "current", completions.append)
        _drain_until(lambda: completions == ["current"])
        assert calls and calls[0] != qt_thread
        assert controller.operation_generation("proposal") == 2
        assert completions == ["current"]


def test_malformed_connection_request_is_not_treated_as_disconnect():
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        ref = "library/" + "a" * 64 + ".json"
        controller.relay_model.set_connection(ArtifactResolution(ref, "a" * 64, "Continuity", None))
        controller.request_connection("../" + ref)
        assert controller.relay_model.ui_snapshot().connected_ref == ref
        assert controller.review_dialog is None
        assert "invalid" in controller.last_visible_notice.lower()


def test_saved_other_entity_cannot_replace_approved_self_connection():
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        first = controller.store.save_import(import_identity_artifact(VALID_ARTIFACT))
        second = controller.store.save_import(
            import_identity_artifact(VALID_ARTIFACT.replace("Continuity", "Other entity"))
        )
        decisions = IdentityRelayDecisionStore(controller.store.root_dir)
        decisions.save_subject_attestation(
            artifact_hash=first.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            subject_class=SubjectClass.ASSISTANT_SELF,
            approved=True,
        )
        decisions.save_subject_attestation(
            artifact_hash=second.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            subject_class=SubjectClass.OTHER_ENTITY,
            approved=True,
        )
        controller.set_persona_identity_ref(first.artifact_ref)

        controller.import_preset_state({"identity_relay_ref": second.artifact_ref})

        assert controller.relay_model.ui_snapshot().connected_ref == first.artifact_ref
        assert controller.review_dialog is not None and controller.review_dialog.isVisible()
        assert controller.review_dialog.selected_subject() == SubjectClass.OTHER_ENTITY
        for actions in controller.review_dialog.review_action_buttons.values():
            actions["approve"].click()
        if controller.review_dialog.model.transient_records:
            controller.review_dialog.transient_inactive_button.click()
        controller.review_dialog.accept_review()
        assert controller.relay_model.ui_snapshot().connected_ref == first.artifact_ref
        assert "contextual-only" in controller.last_visible_notice.lower()

        controller.import_session_state({"identity_relay_ref": second.artifact_ref})
        assert controller.relay_model.ui_snapshot().connected_ref == first.artifact_ref
        assert controller.review_dialog is not None and controller.review_dialog.isVisible()
        controller.review_dialog.cancel_review()
        assert controller.relay_model.ui_snapshot().connected_ref == first.artifact_ref


def test_review_actions_persist_complete_metadata_and_change_effective_model():
    from addons.identity_artifacts.smoke_identity_relay_projection import _model

    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        base = _model()
        records = base.records + (
            replace(base.records[0], record_id="quarantine-record"),
        )
        scope = records[2].runtime_suitability[0]
        items = (
            ReviewItem("approve", ReviewKind.RUNTIME_PERMISSION, (records[0].record_id,), (), "", "approve reason", "pending"),
            ReviewItem("reclassify", ReviewKind.RUNTIME_LAYER, (records[1].record_id,), (), "kernel", "reclassify reason", "pending"),
            ReviewItem(
                "narrow",
                ReviewKind.RUNTIME_PERMISSION,
                (records[2].record_id,),
                (),
                "",
                "narrow reason",
                "pending",
                {"supported_runtime_use_scopes": (scope,)},
            ),
            ReviewItem("quarantine", ReviewKind.UNKNOWN_FIELD, (records[3].record_id,), (), "", "quarantine reason", "pending"),
        )
        model = replace(
            base,
            records=records,
            kernel_record_ids=tuple(record.record_id for record in records),
            retrievable_record_ids=tuple(record.record_id for record in records),
            review_queue=items,
        )
        decisions = (
            ReviewItemDecision("approve", "approve", proposed_value="", source_reason="approve reason", prior_state="pending"),
            ReviewItemDecision("reclassify", "reclassify", proposed_value="kernel", replacement_value="retrievable", source_reason="reclassify reason", prior_state="pending"),
            ReviewItemDecision("narrow", "narrow_use", proposed_value="", allowed_scope=scope, source_reason="narrow reason", prior_state="pending"),
            ReviewItemDecision("quarantine", "quarantine", proposed_value="", source_reason="quarantine reason", prior_state="pending"),
        )

        first_state = controller._save_review_decisions(
            model.envelope.artifact_hash,
            model.normalizer_revision,
            decisions,
            review_items=items,
        )
        second_state = controller._save_review_decisions(
            model.envelope.artifact_hash,
            model.normalizer_revision,
            decisions,
            review_items=items,
        )
        persisted = {item.review_id: item for item in second_state.review_decisions}
        assert persisted["approve"].approved is True
        assert persisted["reclassify"].approved is True
        assert persisted["narrow"].approved is True
        assert persisted["quarantine"].approved is False
        assert all(item.revision == 2 for item in persisted.values())
        metadata = {key: json.loads(item.reason) for key, item in persisted.items()}
        assert metadata["reclassify"] == {
            "actor": "local_user",
            "allowed_scope": "",
            "prior_state": "pending",
            "proposed_value": "kernel",
            "replacement_value": "retrievable",
            "source_reason": "reclassify reason",
        }
        assert metadata["narrow"]["allowed_scope"] == scope
        assert first_state.review_decisions[0].revision == 1

        effective = controller._apply_review_decisions(model, second_state)
        by_id = effective.records_by_id
        assert by_id[records[0].record_id].review_state == "approved"
        assert by_id[records[1].record_id].runtime_layer == RuntimeLayer.RETRIEVABLE
        assert by_id[records[2].record_id].runtime_suitability == (scope,)
        assert by_id[records[3].record_id].review_state == "quarantined"
        assert records[3].record_id not in effective.kernel_record_ids
        assert records[3].record_id not in effective.retrievable_record_ids
        assert any(records[3].record_id in item.record_ids for item in effective.quarantine)


def test_reclassify_and_narrow_require_explicit_user_values():
    _app()
    dialog = ConnectionReviewDialog(_review_model(subject=SubjectClass.ASSISTANT_SELF))
    dialog.review_action_buttons["review-1"]["reclassify"].click()
    assert dialog.apply_button.isEnabled() is False
    dialog.review_value_edits["review-1"].setText("retrievable")
    assert dialog.apply_button.isEnabled() is True
    dialog.review_action_buttons["review-1"]["narrow_use"].click()
    dialog.review_value_edits["review-1"].clear()
    assert dialog.apply_button.isEnabled() is False
    dialog.review_value_edits["review-1"].setText("contextual_retrieval")
    assert dialog.apply_button.isEnabled() is True
    dialog.deleteLater()


def test_complete_attestation_and_prior_review_state_is_visible():
    _app()
    prior = ReviewDecision("review-1", "approved", "prior", True, 3, "2026-07-17T01:02:03Z")
    model = replace(
        _review_model(),
        attestation_normalizer_revision="identity-relay-v0.0.9",
        attestation_approved=True,
        attestation_status="approved assistant_self",
        prior_review_decisions=(prior,),
    )
    dialog = ConnectionReviewDialog(model)
    text = dialog.transparency_text.toPlainText()
    assert "identity-relay-v0.0.9" in text
    assert "approved assistant_self" in text
    assert "review-1" in text and "Revision: 3" in text
    assert "Review state: pending" in dialog.review_text.toPlainText()
    dialog.deleteLater()


def test_runtime_subject_proposal_fallback_executes_off_thread_without_auto_apply():
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        runtime = SimpleNamespace(
            snapshot=lambda: {"chat_provider": "fixture", "model_name": "subject-model"},
            engine_attr=lambda _name, default=None: default,
        )
        root = Path(temp_dir)
        context = SimpleNamespace(
            app_root=root,
            storage=SimpleNamespace(addon_dir=root / "legacy"),
            get_service=lambda name: runtime if name == "qt.runtime_config" else None,
        )
        controller = IdentityArtifactsController(context)
        controller._force_async_operations = True
        called_threads = []

        def complete(provider, params, _additional):
            called_threads.append(threading.get_ident())
            assert provider == "fixture"
            assert params["model"] == "subject-model"
            evidence = json.loads(params["messages"][1]["content"])
            return json.dumps(
                {
                    "proposed_class": "assistant_self",
                    "reason": "first-person evidence",
                    "record_ids": [evidence[0]["record_id"]],
                }
            )

        controller._chat_completion = complete
        stored = controller.store.save_import(import_identity_artifact(UNKNOWN_RECORD_ARTIFACT))
        qt_thread = threading.get_ident()
        controller.request_connection(stored.artifact_ref)
        _drain_until(
            lambda: controller.review_dialog is not None
            and "subject-model" in controller.review_dialog.proposal_label.text()
        )
        assert called_threads and called_threads[0] != qt_thread
        assert controller.review_dialog.selected_subject() == SubjectClass.UNKNOWN
        assert "first-person evidence" in controller.review_dialog.proposal_label.text()


def test_runtime_index_fallback_builds_with_active_embedding_configuration():
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        def embed(text, **_kwargs):
            seed = float((sum(ord(char) for char in str(text)) % 7) + 1)
            return [seed, 1.0, 0.5]

        runtime = SimpleNamespace(
            snapshot=lambda: {
                "long_term_memory_embedding_enabled": True,
                "long_term_memory_embedding_base_url": "http://127.0.0.1:1234/v1",
                "long_term_memory_embedding_model": "fixture-embedding",
                "long_term_memory_embedding_context_length": 8192,
            },
            engine_attr=lambda name, default=None: embed if name == "_lmstudio_embedding" else default,
        )
        root = Path(temp_dir)
        context = SimpleNamespace(
            app_root=root,
            storage=SimpleNamespace(addon_dir=root / "legacy"),
            get_service=lambda name: runtime if name == "qt.runtime_config" else None,
        )
        controller = IdentityArtifactsController(context)
        controller._force_async_operations = True
        stored = controller.store.save_import(import_identity_artifact(VALID_ARTIFACT))
        IdentityRelayDecisionStore(controller.store.root_dir).save_subject_attestation(
            artifact_hash=stored.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            subject_class=SubjectClass.ASSISTANT_SELF,
            approved=True,
        )
        controller.set_persona_identity_ref(stored.artifact_ref)

        controller._request_index_rebuild()
        _drain_until(lambda: controller.operation_generation("index") == 1 and not controller._operation_workers)
        result = controller.semantic_index.read(stored.artifact_hash)
        assert result.semantic_available is True
        assert result.snapshot.metadata.embedding_model == "fixture-embedding"
        assert result.snapshot.metadata.vector_dimension == 3


def test_owner_override_is_confirmation_gated_and_persisted_as_global_runtime_config():
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        values = {"identity_relay_owner_override": False}
        notifications = []

        class RuntimeConfig:
            @staticmethod
            def snapshot():
                return dict(values)

            @staticmethod
            def set(key, value):
                values[str(key)] = value

        context = SimpleNamespace(
            app_root=Path(temp_dir),
            storage=SimpleNamespace(addon_dir=Path(temp_dir) / "legacy"),
            get_service=lambda name: (
                RuntimeConfig()
                if name == "qt.runtime_config"
                else SimpleNamespace(
                    notify_settings_changed=lambda: notifications.append(True)
                )
                if name == "qt.shell"
                else None
            ),
        )
        controller = IdentityArtifactsController(context)
        root = controller.create_tab()
        _drain_until(lambda: not controller._operation_workers)
        assert controller.owner_override_checkbox.isChecked() is False
        assert controller.owner_override_status_label.isVisible() is False

        controller._confirm_owner_override_enable = lambda: False
        controller.owner_override_checkbox.setChecked(True)
        assert values["identity_relay_owner_override"] is False
        assert controller.owner_override_checkbox.isChecked() is False

        controller._confirm_owner_override_enable = lambda: True
        controller.owner_override_checkbox.setChecked(True)
        assert values["identity_relay_owner_override"] is True
        assert controller.owner_override_checkbox.isChecked() is True
        assert "external providers" in controller.owner_override_status_label.text().lower()
        assert notifications

        controller.owner_override_checkbox.setChecked(False)
        assert values["identity_relay_owner_override"] is False
        controller.shutdown()
        root.deleteLater()


def test_owner_override_confirmation_names_privacy_consequence():
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        captured = []
        original = QtWidgets.QMessageBox.question
        QtWidgets.QMessageBox.question = lambda _parent, title, message, *args: (
            captured.append((str(title), str(message))) or QtWidgets.QMessageBox.No
        )
        try:
            assert controller._confirm_owner_override_enable() is False
        finally:
            QtWidgets.QMessageBox.question = original
        assert captured
        warning = " ".join(captured[0]).lower()
        assert "privacy" in warning
        assert "external" in warning
        assert "identity" in warning


def test_reject_and_escape_use_explicit_cancel_and_restore_prior_connection():
    app = _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        first = controller.store.save_import(import_identity_artifact(VALID_ARTIFACT))
        second = controller.store.save_import(
            import_identity_artifact(VALID_ARTIFACT.replace("Continuity", "Second"))
        )
        IdentityRelayDecisionStore(controller.store.root_dir).save_subject_attestation(
            artifact_hash=first.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            subject_class=SubjectClass.ASSISTANT_SELF,
            approved=True,
        )
        controller.set_persona_identity_ref(first.artifact_ref)
        controller.request_connection(second.artifact_ref)
        dialog = controller.review_dialog
        cancelled = []
        dialog.reviewCancelled.connect(lambda: cancelled.append(True))
        QtTest.QTest.keyClick(dialog, QtCore.Qt.Key_Escape)
        app.processEvents()
        assert cancelled == [True]
        assert controller.relay_model.ui_snapshot().connected_ref == first.artifact_ref
        assert not dialog.isVisible()

        controller.request_connection(second.artifact_ref)
        controller.review_dialog.reject()
        assert controller.relay_model.ui_snapshot().connected_ref == first.artifact_ref
        assert not controller.review_dialog.isVisible()


def test_headless_operations_still_run_on_qthreadpool():
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        caller_thread = threading.get_ident()
        worker_threads = []
        completions = []
        controller._start_operation(
            "always_threaded",
            lambda _token: worker_threads.append(threading.get_ident()) or "done",
            completions.append,
        )
        assert worker_threads and worker_threads[0] != caller_thread
        assert completions == ["done"]


def test_cancelled_reextract_does_not_cross_save_boundary():
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        controller._force_async_operations = True
        entered = threading.Event()
        release = threading.Event()
        saved = []
        original_import = controller_module.import_identity_artifact
        imported_result = import_identity_artifact(VALID_ARTIFACT)

        class Store:
            def load_metadata(self, _ref):
                return {}

            def load_raw_bytes(self, _ref):
                return VALID_ARTIFACT.encode("utf-8")

            def save_import(self, result):
                saved.append(result)
                raise AssertionError("cancelled re-extraction crossed save boundary")

        def blocking_import(*_args, **_kwargs):
            entered.set()
            release.wait(2.0)
            return imported_result

        controller.store = Store()
        controller_module.import_identity_artifact = blocking_import
        try:
            controller._start_operation(
                "reextract",
                lambda token: controller._perform_reextract(
                    "library/" + "a" * 64 + ".json",
                    connected_ref="",
                    connection_revision=0,
                    token=token,
                ),
                lambda _value: None,
            )
            assert entered.wait(1.0)
            controller.cancel_operation("reextract")
            release.set()
            _drain_until(lambda: not controller._operation_workers)
            assert saved == []
        finally:
            controller_module.import_identity_artifact = original_import


def test_shutdown_suppresses_late_completion_and_addon_delegates():
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        controller._force_async_operations = True
        entered = threading.Event()
        release = threading.Event()
        published = []

        def work(_token):
            entered.set()
            release.wait(2.0)
            return "late"

        controller._start_operation("late", work, published.append)
        assert entered.wait(1.0)
        generation = controller.operation_generation("late")
        controller.shutdown()
        release.set()
        _drain_until(lambda: not controller._operation_workers)
        assert published == []
        assert controller.operation_generation("late") > generation
        assert controller.review_dialog is None
        assert controller.root_widget is None

        from addons.identity_artifacts.main import Addon

        addon = Addon()
        delegated = []
        addon.controller = SimpleNamespace(shutdown=lambda: delegated.append(True))
        addon.shutdown()
        assert delegated == [True]
        assert addon.controller is None


def test_other_entity_cannot_install_or_spoof_authoritative_assistant_self():
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        stored = controller.store.save_import(import_identity_artifact(UNKNOWN_RECORD_ARTIFACT))
        controller.decision_store.save_subject_attestation(
            artifact_hash=stored.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            subject_class=SubjectClass.OTHER_ENTITY,
            approved=True,
        )

        controller.set_persona_identity_ref(stored.artifact_ref)
        assert controller.relay_model.ui_snapshot().connected_ref == ""
        assert controller.capture_turn(
            {
                "normalizer_revision": NORMALIZER_REVISION,
                "attestation_revision": 999,
                "runtime_use": {
                    "subject_class": "assistant_self",
                    "subject_approved": True,
                    "review_decisions": {"made-up": "approved"},
                },
            }
        ) is None

        forged = IdentityRelayCapture(
            enabled=True,
            artifact_ref=stored.artifact_ref,
            artifact_hash=stored.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            attestation_revision=999,
            runtime_use={
                "connected": True,
                "subject_class": "assistant_self",
                "subject_approved": True,
                "review_decisions": {"made-up": "approved"},
            },
        )
        prepared = controller.relay_service.prepare_turn(
            forged,
            build_turn_query_envelope("Continue our work"),
        )
        assert prepared.status == "blocked"
        assert prepared.failure_code == "artifact_hash_mismatch"
        assert prepared.normalized_model is None


def test_transient_activation_is_evaluated_against_current_chat_token():
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        session_artifact = VALID_ARTIFACT.replace(
            '"ttl": "session"', '"ttl_hint": "session"'
        )
        stored = controller.store.save_import(import_identity_artifact(session_artifact))
        controller.decision_store.save_subject_attestation(
            artifact_hash=stored.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            subject_class=SubjectClass.ASSISTANT_SELF,
            approved=True,
        )
        model = controller.store.load_normalized(stored.artifact_ref)
        transient = model.transient_records[0]
        controller._chat_session_token = "old-session-token"
        state = controller.decision_store.load(stored.artifact_hash)
        activation = TransientActivation(
            record_id=transient.record_id,
            active=True,
            activated_at=datetime.now(timezone.utc).isoformat(),
            session_token="old-session-token",
            revision=1,
            reviewed_at=datetime.now(timezone.utc).isoformat(),
        )
        controller.decision_store.save(replace(state, transient_activations=(activation,)))
        controller.set_persona_identity_ref(stored.artifact_ref)

        current = controller.capture_turn({})
        assert current.transient_activation[transient.record_id]["active"] is True
        assert current.transient_activation[transient.record_id]["reason_code"] == "active_for_session"

        controller.reset_chat_session_state()
        expired = controller.capture_turn(
            {"transient_activation": {transient.record_id: {"active": True}}}
        )
        assert expired.transient_activation[transient.record_id]["active"] is False
        assert expired.transient_activation[transient.record_id]["review_required"] is True
        assert expired.transient_activation[transient.record_id]["reason_code"] == "session_mismatch"

        refreshed = replace(
            activation,
            session_token=controller._chat_session_token,
            revision=2,
        )
        controller.decision_store.save(replace(state, transient_activations=(refreshed,)))
        controller._revalidate_session_authority(enabled=True)
        valid = controller.capture_turn({})
        assert valid.transient_activation[transient.record_id]["active"] is True
        assert valid.transient_activation[transient.record_id]["reason_code"] == "active_for_session"

        inactive = replace(
            refreshed,
            active=False,
            activated_at=None,
            revision=3,
        )
        controller.decision_store.save(replace(state, transient_activations=(inactive,)))
        controller.reset_chat_session_state()
        stale_inactive = controller.capture_turn({})
        assert stale_inactive.transient_activation[transient.record_id]["active"] is False
        assert stale_inactive.transient_activation[transient.record_id]["review_required"] is True
        assert stale_inactive.transient_activation[transient.record_id]["reason_code"] == "session_mismatch"


def test_review_values_are_constrained_before_apply_or_persistence():
    _app()
    model = _review_model(subject=SubjectClass.ASSISTANT_SELF)
    dialog = ConnectionReviewDialog(model)
    dialog.review_action_buttons["review-1"]["reclassify"].click()
    dialog.review_value_edits["review-1"].setText("arbitrary-category")
    assert dialog.apply_button.isEnabled() is False
    assert "invalid" in dialog.review_validation_labels["review-1"].text().lower()
    dialog.review_value_edits["review-1"].setText("retrievable")
    assert dialog.apply_button.isEnabled() is True

    dialog.review_action_buttons["review-1"]["narrow_use"].click()
    dialog.review_value_edits["review-1"].setText("send_everywhere")
    assert dialog.apply_button.isEnabled() is False
    dialog.review_value_edits["review-1"].setText("contextual_retrieval")
    assert dialog.apply_button.isEnabled() is True
    dialog.deleteLater()

    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        invalid = ReviewItemDecision(
            "review-1",
            "reclassify",
            proposed_value="retrievable",
            replacement_value="arbitrary-category",
            source_reason="permission is ambiguous",
            prior_state="pending",
        )
        state = controller._save_review_decisions(
            "a" * 64,
            NORMALIZER_REVISION,
            (invalid,),
            review_items=model.review_items,
        )
        assert state.review_decisions == ()


def test_review_attribution_and_decision_fields_are_visible():
    _app()
    metadata = {
        "actor": "local_user",
        "allowed_scope": "contextual_retrieval",
        "prior_state": "pending",
        "proposed_value": "always_inject",
        "replacement_value": "retrievable",
        "source_reason": "private scope required",
    }
    prior = ReviewDecision(
        "review-1",
        "approved_narrow_use",
        json.dumps(metadata, sort_keys=True, separators=(",", ":")),
        True,
        4,
        "2026-07-17T01:02:03+00:00",
    )
    dialog = ConnectionReviewDialog(
        replace(_review_model(), prior_review_decisions=(prior,))
    )
    text = dialog.transparency_text.toPlainText()
    for expected in (
        "Reviewer: local_user",
        "Reviewed: 2026-07-17T01:02:03+00:00",
        "Revision: 4",
        "Source reason: private scope required",
        "Source proposed value: always_inject",
        "Replacement classification: retrievable",
        "Narrowed scope: contextual_retrieval",
        "Approved: True",
        "Prior state: pending",
    ):
        assert expected in text
    dialog.deleteLater()


def test_legacy_scalar_review_reason_remains_renderable():
    _app()
    legacy = ReviewDecision(
        "legacy-review",
        "approved",
        json.dumps("legacy reason"),
        True,
        1,
        "2026-07-17T01:02:03+00:00",
    )
    dialog = ConnectionReviewDialog(
        replace(_review_model(), prior_review_decisions=(legacy,))
    )
    assert "legacy-review" in dialog.transparency_text.toPlainText()
    dialog.deleteLater()


def test_injected_subject_proposals_use_uniform_strict_validation():
    _app()

    def run_case(result_factory):
        temp_dir = tempfile.TemporaryDirectory()
        root = Path(temp_dir.name)

        def classifier(request, **_kwargs):
            return result_factory(request)

        context = SimpleNamespace(
            app_root=root,
            storage=SimpleNamespace(addon_dir=root / "legacy"),
            get_service=lambda name: (
                classifier if name == "identity_relay.subject_classifier" else None
            ),
        )
        controller = IdentityArtifactsController(context)
        controller._force_async_operations = True
        stored = controller.store.save_import(
            import_identity_artifact(UNKNOWN_RECORD_ARTIFACT)
        )
        controller.request_connection(stored.artifact_ref)
        _drain_until(
            lambda: controller.review_dialog is not None
            and not controller._operation_workers
        )
        return controller, stored, temp_dir

    unattributed, stored, _unattributed_temp = run_case(
        lambda request: {
            "proposed_class": "assistant_self",
            "reason": "first-person evidence",
            "evidence_paths": [request["records"][0]["record_id"]],
        }
    )
    assert unattributed.review_dialog.selected_subject() == SubjectClass.UNKNOWN
    assert unattributed.decision_store.load(stored.artifact_hash).pending_proposal is None
    assert "rejected" in unattributed.review_dialog.proposal_label.text().lower()

    invalid_evidence, stored, _invalid_temp = run_case(
        lambda request: {
            "proposed_class": "assistant_self",
            "reason": "first-person evidence",
            "evidence_paths": [
                request["records"][0]["record_id"],
                request["records"][0]["record_id"],
            ],
            "provider": "fixture",
            "model": "classifier-v1",
        }
    )
    assert invalid_evidence.decision_store.load(stored.artifact_hash).pending_proposal is None
    assert "rejected" in invalid_evidence.review_dialog.proposal_label.text().lower()

    valid, stored, _valid_temp = run_case(
        lambda request: {
            "proposed_class": "assistant_self",
            "reason": "first-person evidence",
            "evidence_paths": [request["records"][0]["record_id"]],
            "provider": "fixture",
            "model": "classifier-v1",
        }
    )
    proposal = valid.decision_store.load(stored.artifact_hash).pending_proposal
    assert proposal is not None
    assert proposal.provider == "fixture" and proposal.model == "classifier-v1"
    assert valid.review_dialog.selected_subject() == SubjectClass.UNKNOWN


def test_runtime_index_uses_local_private_chat_policy_surface():
    from addons.identity_artifacts.smoke_identity_relay_projection import _model

    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        base = _model()
        target = replace(
            base.records[1],
            declared_policy={
                "allowed_surfaces": ["local_private_chat"],
                "allow_remote_provider": False,
                "eligible_for_contextual_retrieval": True,
            },
            runtime_suitability=("contextual_retrieval",),
            review_state="not_required",
        )
        model = replace(
            base,
            records=(target,),
            kernel_record_ids=(),
            retrievable_record_ids=(target.record_id,),
            review_queue=(),
            quarantine=(),
        )
        controller.store = SimpleNamespace(load_normalized=lambda _ref: model)
        config = {
            "embedding": lambda text, **_kwargs: [float(len(str(text)) or 1), 1.0],
            "base_url": "http://127.0.0.1:1234/v1",
            "model": "fixture-embedding",
            "context": 8192,
        }
        controller._perform_runtime_index_build(
            "library/" + model.envelope.artifact_hash + ".json",
            config,
            controller_module._CancellationToken(),
        )
        result = controller.semantic_index.read(model.envelope.artifact_hash)
        assert result.semantic_available is True
        assert result.snapshot.metadata.authorized_record_ids == (target.record_id,)


def test_runtime_index_authorizes_the_actual_embedding_endpoint_before_calls():
    from addons.identity_artifacts.smoke_identity_relay_projection import _model

    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        base = _model()
        base_target = replace(
            base.records[1],
            declared_policy={
                "allowed_surfaces": ["local_private_chat"],
                "allow_remote_provider": False,
                "eligible_for_contextual_retrieval": True,
            },
            exposure_policy={
                **dict(base.records[1].exposure_policy),
                "private_local_1on1": "allow",
                "private_remote_1on1": "deny",
            },
            runtime_suitability=("contextual_retrieval",),
            review_state="not_required",
        )

        def run_case(base_url, target):
            model = replace(
                base,
                records=(target,),
                kernel_record_ids=(),
                retrievable_record_ids=(target.record_id,),
                review_queue=(),
                quarantine=(),
            )
            calls = []

            def embedding(text, **_kwargs):
                calls.append(str(text))
                return [float(len(str(text)) or 1), 1.0]

            controller.store = SimpleNamespace(load_normalized=lambda _ref: model)
            result = controller._perform_runtime_index_build(
                "library/" + model.envelope.artifact_hash + ".json",
                {
                    "embedding": embedding,
                    "base_url": base_url,
                    "model": "fixture-embedding",
                    "context": 8192,
                },
                controller_module._CancellationToken(),
            )
            build = result[0] if isinstance(result, tuple) else result
            return build, calls

        local_build, local_calls = run_case(
            "http://127.0.0.1:1234/v1", base_target
        )
        assert local_build.status == "complete"
        assert local_calls

        remote_denied, remote_denied_calls = run_case(
            "https://embeddings.example.test/v1", base_target
        )
        assert remote_denied.status == "failed"
        assert remote_denied.reason == "embedding_transmission_not_authorized"
        assert remote_denied_calls == []

        remote_allowed_target = replace(
            base_target,
            declared_policy={
                **dict(base_target.declared_policy),
                "allow_remote_provider": True,
            },
            exposure_policy={
                **dict(base_target.exposure_policy),
                "private_remote_1on1": "allow",
            },
        )
        remote_allowed, remote_allowed_calls = run_case(
            "https://embeddings.example.test/v1", remote_allowed_target
        )
        assert remote_allowed.status == "complete"
        assert remote_allowed_calls

        unknown, unknown_calls = run_case("://not-an-endpoint", base_target)
        assert unknown.status == "failed"
        assert unknown.reason == "embedding_endpoint_locality_unknown"
        assert unknown_calls == []


def test_injected_index_build_reauthorizes_its_embedding_endpoint():
    from addons.identity_artifacts.policy import EffectiveUseDecision
    from addons.identity_artifacts.smoke_identity_relay_projection import _model

    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        base = _model()
        target = replace(
            base.records[1],
            declared_policy={
                "allowed_surfaces": ["local_private_chat"],
                "allow_remote_provider": False,
                "eligible_for_contextual_retrieval": True,
            },
            exposure_policy={
                **dict(base.records[1].exposure_policy),
                "private_remote_1on1": "deny",
            },
            runtime_suitability=("contextual_retrieval",),
            review_state="not_required",
        )
        model = replace(
            base,
            records=(target,),
            kernel_record_ids=(),
            retrievable_record_ids=(target.record_id,),
            review_queue=(),
            quarantine=(),
        )
        controller.store = SimpleNamespace(load_normalized=lambda _ref: model)
        calls = []

        class Adapter:
            def embed(self, texts, **_kwargs):
                calls.append(tuple(texts))
                return tuple((1.0, 0.0) for _text in texts)

        metadata = controller_module.SemanticIndexMetadata(
            artifact_hash=model.envelope.artifact_hash,
            normalizer_revision=model.normalizer_revision,
            normalized_schema_version=model.schema_version,
            index_schema_version=controller_module.IDENTITY_INDEX_SCHEMA_VERSION,
            index_revision=controller_module.IDENTITY_INDEX_REVISION,
            embedding_provider="injected",
            endpoint_identity="https://embeddings.example.test/v1",
            embedding_model="fixture-embedding",
            embedding_context=8192,
            vector_dimension=2,
        )
        caller_decisions = {
            target.record_id: EffectiveUseDecision(
                True,
                ("private_retrieval",),
                "allowed",
                "Caller authorized retrieval only.",
            )
        }

        result = controller._perform_index_build(
            "library/" + model.envelope.artifact_hash + ".json",
            Adapter(),
            metadata,
            caller_decisions,
            controller_module._CancellationToken(),
        )
        build = result[0] if isinstance(result, tuple) else result

        assert build.status == "failed"
        assert build.reason == "embedding_transmission_not_authorized"
        assert calls == []


def test_reclassified_active_self_is_cut_off_from_legacy_and_v2_capture():
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        stored = controller.store.save_import(import_identity_artifact(VALID_ARTIFACT))
        controller.decision_store.save_subject_attestation(
            artifact_hash=stored.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            subject_class=SubjectClass.ASSISTANT_SELF,
            approved=True,
        )
        controller.set_persona_identity_ref(stored.artifact_ref)
        assert controller.capture_turn_snapshot()["state"] == "active"
        assert controller.capture_turn_snapshot()["hot_identity_text"] == "Continuity"

        controller.decision_store.save_subject_attestation(
            artifact_hash=stored.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            subject_class=SubjectClass.OTHER_ENTITY,
            approved=True,
        )
        controller._revalidate_session_authority(enabled=True)
        assert controller.capture_turn({}) is None
        legacy = controller.capture_turn_snapshot()
        assert legacy is None or (
            legacy["state"] != "active" and not legacy["hot_identity_text"]
        )
        assert controller.relay_model.ui_snapshot().connected_ref == ""


def test_timed_transient_choice_is_per_chat_and_missing_choice_is_unresolved():
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        timed_artifact = VALID_ARTIFACT.replace(
            '"ttl": "session"', '"ttl_seconds": 3600'
        )
        stored = controller.store.save_import(import_identity_artifact(timed_artifact))
        controller.decision_store.save_subject_attestation(
            artifact_hash=stored.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            subject_class=SubjectClass.ASSISTANT_SELF,
            approved=True,
        )
        model = controller.store.load_normalized(stored.artifact_ref)
        transient = model.transient_records[0]
        controller._chat_session_token = "timed-session"
        controller.set_persona_identity_ref(stored.artifact_ref)

        missing = controller.capture_turn({})
        assert missing.transient_activation[transient.record_id] == {
            "active": False,
            "review_required": True,
            "reason_code": "choice_required",
            "expires_at": None,
            "revision": 0,
        }

        state = controller.decision_store.load(stored.artifact_hash)
        activation = TransientActivation(
            record_id=transient.record_id,
            active=True,
            activated_at=datetime.now(timezone.utc).isoformat(),
            session_token="timed-session",
            revision=1,
            reviewed_at=datetime.now(timezone.utc).isoformat(),
        )
        controller.decision_store.save(replace(state, transient_activations=(activation,)))
        controller._revalidate_session_authority(enabled=True)
        current = controller.capture_turn({})
        assert current.transient_activation[transient.record_id]["active"] is True
        assert current.transient_activation[transient.record_id]["review_required"] is False

        controller.reset_chat_session_state()
        stale = controller.capture_turn({})
        assert stale.transient_activation[transient.record_id]["active"] is False
        assert stale.transient_activation[transient.record_id]["review_required"] is True
        assert stale.transient_activation[transient.record_id]["reason_code"] == "session_mismatch"


def test_public_service_requires_complete_frozen_authority_capture():
    with tempfile.TemporaryDirectory() as temp_dir:
        store = IdentityArtifactStore(Path(temp_dir) / "identity-relay")
        stored = store.save_import(import_identity_artifact(UNKNOWN_RECORD_ARTIFACT))
        model = store.load_normalized(stored.artifact_ref)
        service = IdentityRelayService(IdentityRelayModel(), store=store)
        forged = IdentityRelayCapture(
            enabled=True,
            artifact_ref=stored.artifact_ref,
            artifact_hash=stored.artifact_hash,
            normalizer_revision=model.normalizer_revision,
            attestation_revision=99,
            transient_activation={},
            runtime_use={
                "connected": True,
                "surface": "local_private_chat",
                "provider_is_remote": False,
                "subject_class": "assistant_self",
                "subject_approved": True,
                "review_decisions": {},
            },
            frozen_provider={},
        )
        prepared = service.prepare_turn(
            forged,
            build_turn_query_envelope("Continue"),
        )
        assert prepared.status == "blocked"
        assert prepared.failure_code == "artifact_hash_mismatch"
        assert prepared.normalized_model is None


def test_unknown_field_review_reclassifies_and_disables_unsafe_narrow_use():
    from addons.identity_artifacts.smoke_identity_relay_projection import _model

    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        base = _model()
        target = replace(
            base.records[1],
            semantic_role="unclassified",
            runtime_layer=RuntimeLayer.UNCLASSIFIED,
            runtime_suitability=(),
            review_state="required",
        )
        item = ReviewItem(
            "unknown-review",
            ReviewKind.UNKNOWN_FIELD,
            (target.record_id,),
            (target.source_path,),
            "",
            "unknown field requires classification",
            "pending",
        )
        model = replace(
            base,
            records=(target,),
            kernel_record_ids=(),
            retrievable_record_ids=(),
            review_queue=(item,),
            quarantine=(),
        )
        review_item = controller._review_items_for_dialog(model)[0]
        assert "project_context" in review_item.details["supported_reclassifications"]
        assert review_item.details["supported_runtime_use_scopes"] == ()

        dialog_model = replace(
            _review_model(subject=SubjectClass.ASSISTANT_SELF),
            review_items=(review_item,),
            transient_records=(),
        )
        dialog = ConnectionReviewDialog(dialog_model)
        dialog.review_action_buttons[item.review_id]["reclassify"].click()
        dialog.review_value_edits[item.review_id].setText("project_context")
        assert dialog.apply_button.isEnabled() is True
        assert (
            dialog.review_action_buttons[item.review_id]["narrow_use"].isEnabled()
            is False
        )
        assert "unavailable" in dialog.review_validation_labels[
            item.review_id
        ].text().lower()
        dialog.deleteLater()

        reclassified_state = controller._save_review_decisions(
            model.envelope.artifact_hash,
            model.normalizer_revision,
            (
                ReviewItemDecision(
                    item.review_id,
                    "reclassify",
                    replacement_value="project_context",
                    source_reason=item.reason,
                    prior_state=item.state,
                ),
            ),
            review_items=(review_item,),
        )
        reclassified = controller._apply_review_decisions(model, reclassified_state)
        assert reclassified.records[0].semantic_role == "project_context"
        assert reclassified.records[0].runtime_layer == RuntimeLayer.RETRIEVABLE


def test_failed_resolution_never_installs_or_exposes_chat_relay_row():
    from ui.runtime.smoke_identity_relay_ui import _Bridge, _build_widgets

    _app()
    missing_ref = "library/" + "d" * 64 + ".json"
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        backend = _build_widgets()
        frontend = _build_widgets()
        bridge = _Bridge(backend, frontend)
        controller.bind_runtime_controls({"bridge": bridge})
        controller.request_connection(missing_ref, bridge=bridge)
        assert controller.relay_model.ui_snapshot().connected_ref == ""
        controller.mirror_runtime_widgets({"bridge": bridge, "force": True})
        assert frontend.chat_row.isHidden()
        assert "unavailable" in controller.last_visible_notice.lower()

        valid = controller.store.save_import(import_identity_artifact(VALID_ARTIFACT))
        controller.decision_store.save_subject_attestation(
            artifact_hash=valid.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            subject_class=SubjectClass.ASSISTANT_SELF,
            approved=True,
        )
        controller.set_persona_identity_ref(valid.artifact_ref)
        controller.request_connection(missing_ref, bridge=bridge)
        assert controller.relay_model.ui_snapshot().connected_ref == valid.artifact_ref
        assert "unavailable" in controller.last_visible_notice.lower()


def test_incomplete_frozen_capture_blocks_without_store_authority_fallback():
    from addons.identity_artifacts.smoke_identity_relay_projection import _model

    normalized = _model()
    retrieval_calls = []
    loader_calls = []

    class LoaderlessStore:
        def load_normalized(self, _artifact_ref):
            loader_calls.append(True)
            raise AssertionError("frozen preparation read live store authority")

    def retrieve(*_args):
        retrieval_calls.append(True)
        return CandidateSet(
            eligible=(
                CandidateActivation(
                    "record:project",
                    ("project_thread",),
                    True,
                    {"project_thread": 1.0},
                    "allowed",
                ),
            ),
            denied_record_ids=(),
            semantic_available=False,
            semantic_reason="not_needed",
        )

    forged = IdentityRelayCapture(
        enabled=True,
        artifact_ref=f"library/{normalized.envelope.artifact_hash}.json",
        artifact_hash=normalized.envelope.artifact_hash,
        normalizer_revision=normalized.normalizer_revision,
        attestation_revision=1,
        transient_activation={},
        runtime_use={
            "connected": True,
            "surface": "chat",
            "provider_is_remote": False,
            "subject_class": "assistant_self",
            "subject_approved": True,
            "review_decisions": {"review:correction": "approved"},
        },
        frozen_provider={},
    )
    service = IdentityRelayService(
        IdentityRelayModel(),
        store=LoaderlessStore(),
        candidate_retriever=retrieve,
    )

    prepared = service.prepare_turn(forged, build_turn_query_envelope("Continue"))

    assert prepared.status == "blocked"
    assert prepared.failure_code == "artifact_hash_mismatch"
    assert loader_calls == []
    assert retrieval_calls == []


def test_narrow_use_never_broadens_suitability_and_disables_when_unsafe():
    from addons.identity_artifacts.smoke_identity_relay_projection import _model

    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        base = _model()
        contextual = replace(
            base.records[1],
            runtime_suitability=("contextual_retrieval",),
            review_state="required",
        )
        item = ReviewItem(
            "narrow-contextual",
            ReviewKind.RUNTIME_PERMISSION,
            (contextual.record_id,),
            (contextual.source_path,),
            "",
            "runtime use requires review",
            "pending",
        )
        model = replace(
            base,
            records=(contextual,),
            kernel_record_ids=(),
            retrievable_record_ids=(contextual.record_id,),
            review_queue=(item,),
            quarantine=(),
        )
        review_item = controller._review_items_for_dialog(model)[0]
        assert review_item.details["supported_runtime_use_scopes"] == (
            "contextual_retrieval",
        )
        assert "always_inject" not in review_item.details[
            "supported_runtime_use_scopes"
        ]

        before = evaluate_effective_use(
            contextual,
            RuntimeUse("chat", False, requested_use="always_inject"),
            UserApproval(True, review_approved=True),
        )
        assert before.allowed is False
        assert before.reason_code == "runtime_use_not_permitted"

        broaden_attempt = ReviewDecision(
            review_id=item.review_id,
            choice="approved_narrow_use",
            reason=json.dumps({"allowed_scope": "always_inject"}),
            approved=True,
        )
        state = replace(
            controller.decision_store.load(model.envelope.artifact_hash),
            normalizer_revision=model.normalizer_revision,
            review_decisions=(broaden_attempt,),
        )
        after_model = controller._apply_review_decisions(model, state)
        after = evaluate_effective_use(
            after_model.records[0],
            RuntimeUse("chat", False, requested_use="always_inject"),
            UserApproval(True, review_approved=True),
        )
        assert after.allowed is False
        assert after_model.records[0].runtime_suitability == ()

        unsuitable = replace(
            contextual,
            runtime_layer=RuntimeLayer.UNCLASSIFIED,
            runtime_suitability=(),
        )
        unsuitable_model = replace(
            model,
            records=(unsuitable,),
            retrievable_record_ids=(),
        )
        unsuitable_item = controller._review_items_for_dialog(unsuitable_model)[0]
        assert unsuitable_item.details["supported_runtime_use_scopes"] == ()
        dialog = ConnectionReviewDialog(
            replace(
                _review_model(subject=SubjectClass.ASSISTANT_SELF),
                review_items=(unsuitable_item,),
                transient_records=(),
            )
        )
        narrow_button = dialog.review_action_buttons[item.review_id]["narrow_use"]
        assert narrow_button.isEnabled() is False
        assert "unavailable" in dialog.review_validation_labels[
            item.review_id
        ].text().lower()
        dialog.deleteLater()


def test_unavailable_saved_refs_round_trip_without_becoming_connections():
    from ui.runtime.smoke_identity_relay_ui import _Bridge, _build_widgets

    _app()
    missing_ref = "library/" + "e" * 64 + ".json"
    with tempfile.TemporaryDirectory() as temp_dir:
        for import_state, export_state in (
            ("import_preset_state", "export_preset_state"),
            ("import_session_state", "export_session_state"),
        ):
            controller = _controller(temp_dir)
            backend = _build_widgets()
            frontend = _build_widgets()
            bridge = _Bridge(backend, frontend)
            controller.bind_runtime_controls({"bridge": bridge})

            snapshot = getattr(controller, import_state)(
                {"identity_relay_ref": missing_ref}
            )

            assert snapshot.connected_ref == ""
            assert snapshot.availability == "none"
            assert controller.capture_turn_snapshot() is None
            assert getattr(controller, export_state)() == {
                "identity_relay_ref": missing_ref
            }
            assert controller.export_chat_session_state()["artifact_ref"] == missing_ref
            controller.mirror_runtime_widgets({"bridge": bridge, "force": True})
            assert frontend.chat_row.isHidden()
            assert "unavailable" in controller.last_visible_notice.lower()

        controller = _controller(temp_dir)
        valid = controller.store.save_import(import_identity_artifact(VALID_ARTIFACT))
        controller.decision_store.save_subject_attestation(
            artifact_hash=valid.artifact_hash,
            normalizer_revision=NORMALIZER_REVISION,
            subject_class=SubjectClass.ASSISTANT_SELF,
            approved=True,
        )
        controller.set_persona_identity_ref(valid.artifact_ref)

        snapshot = controller.import_session_state(
            {"identity_relay_ref": missing_ref}
        )

        assert snapshot.connected_ref == valid.artifact_ref
        assert snapshot.availability == "available"
        assert controller.capture_turn_snapshot()["state"] == "active"
        assert controller.export_session_state() == {
            "identity_relay_ref": valid.artifact_ref
        }
        assert "unavailable" in controller.last_visible_notice.lower()


def test_context_none_missing_identity_cannot_capture_first_person_content():
    controller = IdentityArtifactsController(context=None)
    artifact_ref = "library/" + "f" * 64 + ".json"
    resolution = ArtifactResolution(
        artifact_ref,
        "f" * 64,
        "Unattested first-person continuity",
        None,
    )

    controller.relay_model.set_connection(resolution)
    assert controller.capture_turn_snapshot() is None
    assert controller.relay_model.ui_snapshot().connected_ref == ""

    controller.relay_model.set_connection(resolution)
    capture = controller.capture_turn(
        {
            "normalizer_revision": NORMALIZER_REVISION,
            "attestation_revision": 99,
            "runtime_use": {
                "subject_class": "assistant_self",
                "subject_approved": True,
            },
        }
    )
    assert capture.normalizer_revision == ""
    assert capture.attestation_revision == 0
    assert capture.runtime_use.get("subject_approved") is None
    prepared = controller.prepare_turn(
        {
            "capture": capture,
            "query": build_turn_query_envelope("Continue"),
        }
    )
    assert prepared.status == "blocked"
    assert prepared.failure_code == "artifact_hash_mismatch"
    assert prepared.normalized_model is None
    assert controller.capture_turn_snapshot() is None
    assert controller.relay_model.ui_snapshot().connected_ref == ""


def test_saved_restore_resolve_and_normalize_run_off_qt_thread():
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        stored = controller.store.save_import(import_identity_artifact(VALID_ARTIFACT))
        qt_thread = threading.get_ident()
        calls = []
        original_resolve = controller.store.resolve_artifact
        original_load = controller.store.load_normalized

        def resolve(artifact_ref):
            calls.append(("resolve", threading.get_ident()))
            return original_resolve(artifact_ref)

        def load(artifact_ref):
            calls.append(("load", threading.get_ident()))
            return original_load(artifact_ref)

        controller.store.resolve_artifact = resolve
        controller.store.load_normalized = load
        controller._force_async_operations = True

        controller.import_preset_state({"identity_relay_ref": stored.artifact_ref})
        _drain_until(
            lambda: controller.review_dialog is not None
            and controller.review_dialog.isVisible()
        )

        assert {name for name, _thread in calls} == {"resolve", "load"}
        assert all(thread_id != qt_thread for _name, thread_id in calls)
        controller.review_dialog.cancel_review()


def test_connection_apply_resolve_and_normalize_run_off_qt_thread():
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        stored = controller.store.save_import(import_identity_artifact(VALID_ARTIFACT))
        controller.request_connection(stored.artifact_ref)
        dialog = controller.review_dialog
        _approve_self_review(dialog)

        qt_thread = threading.get_ident()
        calls = []
        original_resolve = controller.store.resolve_artifact
        original_load = controller.store.load_normalized

        def resolve(artifact_ref):
            calls.append(("resolve", threading.get_ident()))
            return original_resolve(artifact_ref)

        def load(artifact_ref):
            calls.append(("load", threading.get_ident()))
            return original_load(artifact_ref)

        controller.store.resolve_artifact = resolve
        controller.store.load_normalized = load
        controller._force_async_operations = True

        dialog.accept_review()
        _drain_until(
            lambda: controller.relay_model.ui_snapshot().connected_ref
            == stored.artifact_ref
        )

        assert {name for name, _thread in calls} == {"resolve", "load"}
        assert all(thread_id != qt_thread for _name, thread_id in calls)


def test_superseded_connection_apply_cannot_install_late_completion():
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        stored = controller.store.save_import(import_identity_artifact(VALID_ARTIFACT))
        controller.request_connection(stored.artifact_ref)
        dialog = controller.review_dialog
        _approve_self_review(dialog)

        entered = threading.Event()
        release = threading.Event()
        original_resolve = controller.store.resolve_artifact

        def blocking_resolve(artifact_ref):
            entered.set()
            release.wait(2.0)
            return original_resolve(artifact_ref)

        controller.store.resolve_artifact = blocking_resolve
        controller._force_async_operations = True
        delayed_release = threading.Thread(
            target=lambda: (time.sleep(0.3), release.set()),
            daemon=True,
        )
        delayed_release.start()

        dialog.accept_review()
        assert entered.wait(1.0)
        controller.request_connection("../library/" + "9" * 64 + ".json")
        release.set()
        _drain_until(lambda: not controller._operation_workers)

        assert controller.relay_model.ui_snapshot().connected_ref == ""
        assert controller.last_visible_notice == "Invalid Identity Relay artifact reference."


def test_cancelled_connection_apply_stops_before_atomic_review_persistence():
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        stored = controller.store.save_import(import_identity_artifact(VALID_ARTIFACT))
        controller.request_connection(stored.artifact_ref)
        dialog = controller.review_dialog
        dialog.choose_subject(SubjectClass.ASSISTANT_SELF)
        for actions in dialog.review_action_buttons.values():
            actions["approve"].click()
        dialog.transient_activate_button.click()

        resolution_reached = threading.Event()
        release_resolution = threading.Event()
        original_resolve = controller.store.resolve_artifact

        def blocking_resolve(artifact_ref):
            resolution_reached.set()
            assert release_resolution.wait(2.0)
            return original_resolve(artifact_ref)

        controller.store.resolve_artifact = blocking_resolve
        controller._force_async_operations = True

        dialog.accept_review()
        assert resolution_reached.wait(1.0)
        assert controller.cancel_operation("connection_apply") is True
        release_resolution.set()
        _drain_until(lambda: not controller._operation_workers)

        state = controller.decision_store.load(stored.artifact_hash)
        assert state.subject_attestation is None
        assert state.review_decisions == ()
        assert state.transient_activations == ()
        assert controller.relay_model.ui_snapshot().connected_ref == ""


def test_cancel_and_transient_save_have_one_ordered_boundary():
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        controller = _controller(temp_dir)
        stored = controller.store.save_import(import_identity_artifact(VALID_ARTIFACT))
        controller.request_connection(stored.artifact_ref)
        dialog = controller.review_dialog
        dialog.choose_subject(SubjectClass.ASSISTANT_SELF)
        for actions in dialog.review_action_buttons.values():
            actions["approve"].click()
        dialog.transient_activate_button.click()

        construction_paused = threading.Event()
        release_construction = threading.Event()
        cancellation_returned = threading.Event()
        order = []
        order_lock = threading.Lock()
        original_transient_activation = controller_module.TransientActivation
        original_save = controller.decision_store.save

        def mark(name):
            with order_lock:
                order.append(name)

        def blocking_transient_activation(*args, **kwargs):
            construction_paused.set()
            assert release_construction.wait(2.0)
            return original_transient_activation(*args, **kwargs)

        def tracking_save(state):
            if state.transient_activations:
                mark("transient_save_started")
            return original_save(state)

        def cancel_apply():
            assert controller.cancel_operation("connection_apply") is True
            mark("cancel_returned")
            cancellation_returned.set()

        controller_module.TransientActivation = blocking_transient_activation
        controller.decision_store.save = tracking_save
        controller._force_async_operations = True
        try:
            dialog.accept_review()
            assert construction_paused.wait(1.0)
            cancel_thread = threading.Thread(target=cancel_apply, daemon=True)
            cancel_thread.start()
            assert cancellation_returned.wait(1.0)
            release_construction.set()
            _drain_until(lambda: not controller._operation_workers)
            cancel_thread.join(1.0)
            assert not cancel_thread.is_alive()
        finally:
            release_construction.set()
            controller_module.TransientActivation = original_transient_activation
            controller.decision_store.save = original_save

        with order_lock:
            observed_order = tuple(order)
        if "transient_save_started" in observed_order:
            assert observed_order.index("transient_save_started") < observed_order.index(
                "cancel_returned"
            )
        else:
            state = controller.decision_store.load(stored.artifact_hash)
            assert state.transient_activations == ()


def main() -> int:
    test_review_dialog_offers_compact_safe_connect_and_scrollable_advanced_review()
    test_primary_connect_action_replaces_stale_contextual_subject()
    test_disconnect_review_has_honest_confirmation_action()
    test_active_model_proposal_is_attributed_and_never_auto_applied()
    test_window_close_is_not_an_implicit_decision()
    test_connection_requires_explicit_subject_and_non_self_stays_contextual_only()
    test_assistant_self_connects_only_after_apply_and_cancel_restores_previous_state()
    test_primary_connect_replaces_saved_contextual_subject_and_connects()
    test_valid_saved_assistant_identity_restores_without_second_review()
    test_subject_proposal_runs_off_qt_thread_and_stale_completion_is_discarded()
    test_malformed_connection_request_is_not_treated_as_disconnect()
    test_saved_other_entity_cannot_replace_approved_self_connection()
    test_review_actions_persist_complete_metadata_and_change_effective_model()
    test_reclassify_and_narrow_require_explicit_user_values()
    test_complete_attestation_and_prior_review_state_is_visible()
    test_runtime_subject_proposal_fallback_executes_off_thread_without_auto_apply()
    test_runtime_index_fallback_builds_with_active_embedding_configuration()
    test_owner_override_is_confirmation_gated_and_persisted_as_global_runtime_config()
    test_owner_override_confirmation_names_privacy_consequence()
    test_reject_and_escape_use_explicit_cancel_and_restore_prior_connection()
    test_headless_operations_still_run_on_qthreadpool()
    test_cancelled_reextract_does_not_cross_save_boundary()
    test_shutdown_suppresses_late_completion_and_addon_delegates()
    test_other_entity_cannot_install_or_spoof_authoritative_assistant_self()
    test_transient_activation_is_evaluated_against_current_chat_token()
    test_review_values_are_constrained_before_apply_or_persistence()
    test_review_attribution_and_decision_fields_are_visible()
    test_legacy_scalar_review_reason_remains_renderable()
    test_injected_subject_proposals_use_uniform_strict_validation()
    test_runtime_index_uses_local_private_chat_policy_surface()
    test_runtime_index_authorizes_the_actual_embedding_endpoint_before_calls()
    test_injected_index_build_reauthorizes_its_embedding_endpoint()
    test_reclassified_active_self_is_cut_off_from_legacy_and_v2_capture()
    test_timed_transient_choice_is_per_chat_and_missing_choice_is_unresolved()
    test_public_service_requires_complete_frozen_authority_capture()
    test_unknown_field_review_reclassifies_and_disables_unsafe_narrow_use()
    test_failed_resolution_never_installs_or_exposes_chat_relay_row()
    test_incomplete_frozen_capture_blocks_without_store_authority_fallback()
    test_narrow_use_never_broadens_suitability_and_disables_when_unsafe()
    test_unavailable_saved_refs_round_trip_without_becoming_connections()
    test_context_none_missing_identity_cannot_capture_first_person_content()
    test_saved_restore_resolve_and_normalize_run_off_qt_thread()
    test_connection_apply_resolve_and_normalize_run_off_qt_thread()
    test_superseded_connection_apply_cannot_install_late_completion()
    test_cancelled_connection_apply_stops_before_atomic_review_persistence()
    test_cancel_and_transient_save_have_one_ordered_boundary()
    print("smoke_identity_relay_review_ui: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
