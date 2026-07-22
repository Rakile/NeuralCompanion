from __future__ import annotations

import copy
import importlib
import inspect
import json
import os
import tempfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier, Event, Thread

from addons.audio_story_mode import (
    audio_fingerprint,
    checkpointing,
    project_autosave,
    project_models,
    project_store,
    story_memory,
    story_projects,
)


@contextmanager
def _raises(expected_type):
    try:
        yield
    except expected_type:
        return
    raise AssertionError(f"Expected {expected_type.__name__}")


def _manager_with_fake_fingerprints(tmp_path: Path) -> story_projects.StoryProjectManager:
    fingerprints = {
        "good.wav": {
            "algorithm": "sha256-sampled-v1",
            "digest": "good",
            "size_bytes": 10,
            "duration_ms": 1000,
        },
        "different.wav": {
            "algorithm": "sha256-sampled-v1",
            "digest": "different",
            "size_bytes": 11,
            "duration_ms": 1000,
        },
        "moved.wav": {
            "algorithm": "sha256-sampled-v1",
            "digest": "good",
            "size_bytes": 10,
            "duration_ms": 1050,
        },
    }

    def fingerprint_reader(path, _duration_reader, **_kwargs):
        name = Path(path).name
        if name == "broken.wav":
            raise ValueError("audio duration is unavailable")
        return dict(fingerprints[name])

    return story_projects.StoryProjectManager(
        project_store.StoryProjectStore(tmp_path),
        duration_reader=lambda _path: 1.0,
        fingerprint_reader=fingerprint_reader,
    )


def _session_controller():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    controller_module = importlib.import_module("addons.audio_story_mode.controller")
    controller = controller_module.AudioStoryModeController(context=None)
    controller._set_imported_audio_paths = lambda paths, clear_story=False: None
    controller._prepare_source_media = lambda: None
    controller._refresh_controls = lambda: None
    return app, controller


def test_controller_legacy_session_import_is_immutable_and_never_auto_migrates() -> None:
    _app, controller = _session_controller()
    legacy = {
        "audio_story_mode_audio_path": "chapter.wav",
        "audio_story_mode_story_bible": {"summary": "Saved"},
    }
    before = copy.deepcopy(legacy)

    def reject_automatic_migration(*_args, **_kwargs):
        raise AssertionError("legacy session loading must never prepare a migration")

    controller._story_project_manager.prepare_legacy_migration = reject_automatic_migration
    try:
        controller.import_session_state(legacy)
        assert legacy == before
        assert controller.current_story_project_id == ""
        assert controller.legacy_story_available_for_migration
    finally:
        controller.shutdown()


def test_controller_exports_current_project_identity_as_reopen_hint() -> None:
    from addons.audio_story_mode.session_schema import flatten_audio_story_mode_settings

    _app, controller = _session_controller()
    controller.current_story_project_id = "project-reopen-hint"
    controller._current_story_project = {
        "project_id": "project-reopen-hint",
        "manifest_revision": 23,
    }
    try:
        exported = flatten_audio_story_mode_settings(controller.export_session_state())
        assert exported["audio_story_mode_project_id"] == "project-reopen-hint"
        assert exported["audio_story_mode_project_revision"] == 23
    finally:
        controller.shutdown()


def test_controller_without_project_keeps_legacy_session_shape() -> None:
    from addons.audio_story_mode.session_schema import flatten_audio_story_mode_settings

    _app, controller = _session_controller()
    try:
        exported = flatten_audio_story_mode_settings(controller.export_session_state())
        assert "audio_story_mode_project_id" not in exported
        assert "audio_story_mode_project_revision" not in exported
    finally:
        controller.shutdown()


def test_controller_project_session_hint_reopens_authoritative_store_project() -> None:
    _app, controller = _session_controller()
    authoritative = {
        "project_id": "project-reopen-hint",
        "manifest_revision": 31,
        "name": "Authoritative",
    }
    calls = []
    controller._story_project_manager.open_with_recovery = lambda project_id: (
        authoritative if project_id == "project-reopen-hint" else None,
        False,
    )

    def capture_job(operation, work, **kwargs):
        calls.append((operation, work(), kwargs))

    controller._launch_story_project_job = capture_job
    try:
        controller.import_session_state(
            {
                "audio_story_mode": {
                    "project": {
                        "project_id": "project-reopen-hint",
                        "revision": 7,
                    }
                }
            }
        )
        assert calls == [
            (
                "open",
                {
                    "project": authoritative,
                    "recovery_changed": False,
                    "backup_recovered": False,
                },
                {
                    "project_id": "project-reopen-hint",
                    "switch_project": True,
                    "supersede_busy": True,
                },
            )
        ]
        assert not controller.legacy_story_available_for_migration
        assert controller._legacy_story_session_payload == {}
    finally:
        controller.shutdown()


def test_controller_save_current_story_delegates_legacy_preview_to_worker() -> None:
    _app, controller = _session_controller()
    controller_module = importlib.import_module("addons.audio_story_mode.controller")
    legacy = {
        "audio_story_mode_audio_path": "chapter.wav",
        "audio_story_mode_story_bible": {"summary": "Saved"},
    }
    controller.import_session_state(legacy)
    prepared = []
    launched = []
    preview = {
        "kind": "audio_story_legacy_migration",
        "project": {"project_id": "preview-project", "name": "Saved Story"},
        "valid": [],
        "invalid": [{"path": "chapter.wav", "error": "missing"}],
        "conflicts": [],
    }
    controller._story_project_manager.prepare_legacy_migration = (
        lambda payload, name: prepared.append((copy.deepcopy(payload), name)) or preview
    )
    controller._launch_story_project_job = (
        lambda operation, work, **kwargs: launched.append((operation, work, kwargs))
    )
    original_get_text = controller_module.QtWidgets.QInputDialog.getText
    controller_module.QtWidgets.QInputDialog.getText = staticmethod(
        lambda *_args, **_kwargs: ("Saved Story", True)
    )
    try:
        controller._save_current_story_as_project()
        assert prepared == [], "fingerprinting ran on the UI action call"
        assert len(launched) == 1
        operation, work, kwargs = launched[0]
        assert operation == "legacy-migration-preview"
        assert kwargs == {
            "project_id": "__legacy_migration__",
            "switch_project": False,
        }
        assert work() == preview
        assert prepared == [(legacy, "Saved Story")]
        assert controller._legacy_story_session_payload == legacy
    finally:
        controller_module.QtWidgets.QInputDialog.getText = original_get_text
        controller.shutdown()


def test_controller_legacy_migration_missing_audio_requires_confirmation_before_commit_worker() -> None:
    _app, controller = _session_controller()
    controller_module = importlib.import_module("addons.audio_story_mode.controller")
    preview = {
        "kind": "audio_story_legacy_migration",
        "project": {"project_id": "preview-project", "name": "Saved Story"},
        "valid": [],
        "invalid": [{"path": "broken.wav", "error": "audio duration is unavailable"}],
        "conflicts": [],
    }
    committed = {
        "project_id": "preview-project",
        "name": "Saved Story",
        "manifest_revision": 1,
    }
    commit_calls = []
    launches = []
    questions = []
    controller._story_project_job_is_current = lambda _payload: True
    controller._apply_open_story_project = lambda _project: None
    controller._story_project_manager.commit_legacy_migration = (
        lambda value: commit_calls.append(copy.deepcopy(value)) or committed
    )
    controller._launch_story_project_job = (
        lambda operation, work, **kwargs: launches.append((operation, work, kwargs))
    )
    original_question = controller_module.QtWidgets.QMessageBox.question
    try:
        controller_module.QtWidgets.QMessageBox.question = staticmethod(
            lambda *_args, **_kwargs: controller_module.QtWidgets.QMessageBox.No
        )
        controller._on_story_project_job_finished(
            {"operation": "legacy-migration-preview", "result": preview}
        )
        assert launches == []
        assert commit_calls == []

        def accept(*args, **_kwargs):
            questions.append(str(args[2]))
            return controller_module.QtWidgets.QMessageBox.Yes

        controller_module.QtWidgets.QMessageBox.question = staticmethod(accept)
        controller._on_story_project_job_finished(
            {"operation": "legacy-migration-preview", "result": preview}
        )
        assert len(launches) == 1
        assert questions and "broken.wav" in questions[0]
        assert "missing" in questions[0].lower()
        operation, work, kwargs = launches[0]
        assert operation == "legacy-migration-commit"
        assert kwargs == {
            "project_id": "preview-project",
            "switch_project": True,
        }
        assert commit_calls == [], "project creation ran before the worker"
        assert work() == {"project": committed, "recovery_changed": False}
        assert commit_calls == [preview]
    finally:
        controller_module.QtWidgets.QMessageBox.question = original_question
        controller.shutdown()


def test_controller_legacy_migration_worker_error_reenables_explicit_action() -> None:
    _app, controller = _session_controller()
    controller_module = importlib.import_module("addons.audio_story_mode.controller")
    button = controller_module.QtWidgets.QPushButton(
        "Save Current Story as Project"
    )
    button.setVisible(False)
    button.setEnabled(False)
    controller.audio_story_project_save_current_button = button
    controller.legacy_story_available_for_migration = True
    controller._story_project_busy = True
    controller._story_project_job_is_current = lambda _payload: True

    controller._on_story_project_job_finished(
        {
            "operation": "legacy-migration-preview",
            "error": "fingerprint service unavailable",
        }
    )

    assert not button.isHidden()
    assert button.isEnabled()
    controller.shutdown()


def test_controller_legacy_migration_commit_hydrates_persisted_derived_state() -> None:
    _app, controller = _session_controller()
    legacy = {
        "audio_story_mode_story_bible": {"summary": "Migrated summary"},
        "audio_story_mode_scene_plan": [
            {"scene_id": "scene-migrated", "summary": "Migrated scene"}
        ],
        "audio_story_mode_scene_overrides": {
            "pinned_character_ids": ["hero"],
            "global_scene_anchor": "same observatory",
            "global_scene_anchor_enabled": True,
        },
        "audio_story_mode_continuity_memory": {
            "last_scene_id": "scene-migrated",
            "scenes": {"scene-migrated": {"mood": "quiet"}},
        },
        "audio_story_mode_character_anchors": {
            "hero": {"label": "The astronomer"}
        },
        "audio_story_mode_location_anchors": {
            "observatory": {"label": "Old observatory"}
        },
        "audio_story_mode_transcript_chunks": [
            {
                "index": 0,
                "scene_id": "scene-migrated",
                "start_seconds": 0.0,
                "end_seconds": 4.0,
                "text": "The telescope turns.",
            }
        ],
        "audio_story_mode_full_transcript_text": "The telescope turns.",
        "audio_story_mode_raw_transcript_segments": [
            {"start_seconds": 0.0, "end_seconds": 4.0, "text": "The telescope turns."}
        ],
        "audio_story_mode_audio_duration_seconds": 4.0,
    }
    before = copy.deepcopy(legacy)
    project = project_models.new_project_manifest(
        "Migrated Story", project_id="migrated-project", now=1.0
    )
    project["legacy_session_payload"] = copy.deepcopy(legacy)
    controller.legacy_story_available_for_migration = True
    controller._story_project_job_is_current = lambda _payload: True
    controller._launch_story_project_job = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("project hydration must not launch recursive project work")
    )
    controller._prepare_source_media = lambda: None
    controller._sync_story_generated_master_prompt = lambda **_kwargs: None
    controller._refresh_scene_override_controls = lambda: None
    try:
        controller._on_story_project_job_finished(
            {
                "operation": "legacy-migration-commit",
                "result": {"project": project, "recovery_changed": False},
            }
        )
        assert controller.current_story_project_id == "migrated-project"
        assert controller.story_bible == legacy["audio_story_mode_story_bible"]
        assert controller.scene_plan == legacy["audio_story_mode_scene_plan"]
        assert controller.scene_overrides["pinned_character_ids"] == ["hero"]
        assert controller.scene_overrides["global_scene_anchor"] == "same observatory"
        assert controller.continuity_memory == legacy[
            "audio_story_mode_continuity_memory"
        ]
        assert controller.character_anchors == legacy[
            "audio_story_mode_character_anchors"
        ]
        assert controller.location_anchors == legacy[
            "audio_story_mode_location_anchors"
        ]
        assert controller.transcript_chunks == legacy[
            "audio_story_mode_transcript_chunks"
        ]
        assert controller.full_transcript_text == "The telescope turns."
        assert controller._raw_transcript_segments == legacy[
            "audio_story_mode_raw_transcript_segments"
        ]
        assert controller.imported_audio_duration_seconds == 4.0
        assert controller._last_transcription_audio_duration == 4.0
        assert project["legacy_session_payload"] == before
        assert not controller.legacy_story_available_for_migration
    finally:
        controller.shutdown()


def test_controller_matching_autosave_failure_keeps_newest_dirty_snapshot_for_shutdown() -> None:
    _app, controller = _session_controller()
    requests = []

    class TransientFailureQueue:
        def request(self, request):
            requests.append(copy.deepcopy(request))
            if len(requests) == 1:
                controller._story_project_autosave_worker_failed(
                    {
                        "project_id": request.project_id,
                        "revision": request.revision,
                        "error": "transient disk failure",
                    }
                )

        def flush(self, timeout):
            return True

        def shutdown(self, timeout):
            return None

    controller.current_story_project_id = "dirty-project"
    controller._current_story_project = {
        "project_id": "dirty-project",
        "autosave_revision": 1,
        "name": "Newest dirty snapshot",
    }
    controller._story_project_autosave_queue = TransientFailureQueue()
    controller._sync_story_generated_master_prompt = lambda **_kwargs: None
    controller._stop_story = lambda: None
    controller._stop_visual_stream = lambda: None

    controller._queue_story_project_autosave(controller._current_story_project)

    assert controller._story_project_pending_autosave is None
    assert len(requests) == 1
    controller._current_story_project["name"] = "Stale in-memory fallback"

    controller.shutdown()

    assert len(requests) == 2
    assert requests[1].revision == 3
    assert requests[1].snapshot["autosave_revision"] == 3
    assert requests[1].snapshot["name"] == "Newest dirty snapshot"


def test_controller_newer_autosave_success_clears_dirty_snapshot_but_older_does_not() -> None:
    _app, controller = _session_controller()
    requests = []

    class HoldingQueue:
        def request(self, request):
            requests.append(copy.deepcopy(request))
            return None

        def flush(self, timeout):
            return True

        def shutdown(self, timeout):
            return None

    controller.current_story_project_id = "dirty-success-project"
    controller._current_story_project = {
        "project_id": "dirty-success-project",
        "autosave_revision": 1,
    }
    controller._story_project_autosave_queue = HoldingQueue()
    controller._queue_story_project_autosave(controller._current_story_project)
    controller._queue_story_project_autosave(controller._current_story_project)

    dirty = copy.deepcopy(controller._story_project_dirty_autosave)
    assert dirty["revision"] == 3
    controller._story_project_autosave_worker_saved(
        {
            "project_id": "dirty-success-project",
            "autosave_revision": 2,
        }
    )
    assert controller._story_project_dirty_autosave == dirty

    controller._story_project_autosave_ownership[("dirty-success-project", 4)] = {
        "project_id": "dirty-success-project",
        "revision": 4,
        "generation_id": controller._story_project_generation,
        "input_fingerprint": "newer-save",
    }
    controller._story_project_autosave_worker_saved(
        {
            "project_id": "dirty-success-project",
            "autosave_revision": 4,
        }
    )
    assert controller._story_project_dirty_autosave is None
    controller.shutdown()
    assert len(requests) == 2


def test_controller_same_id_session_hint_reopens_and_replaces_stale_derived_state() -> None:
    _app, controller = _session_controller()
    authoritative = project_models.new_project_manifest(
        "Authoritative", project_id="same-project", now=1.0
    )
    authoritative["legacy_session_payload"] = {
        "audio_story_mode_story_bible": {"summary": "Authoritative summary"},
        "audio_story_mode_transcript_chunks": [
            {
                "index": 0,
                "start_seconds": 0.0,
                "end_seconds": 2.0,
                "text": "Authoritative transcript.",
            }
        ],
        "audio_story_mode_full_transcript_text": "Authoritative transcript.",
        "audio_story_mode_audio_duration_seconds": 2.0,
    }
    launches = []
    controller.current_story_project_id = "same-project"
    controller._current_story_project = {
        "project_id": "same-project",
        "name": "Stale session project",
    }
    controller._story_project_manager.open_with_recovery = lambda project_id: (
        copy.deepcopy(authoritative) if project_id == "same-project" else None,
        False,
    )
    controller._launch_story_project_job = (
        lambda operation, work, **kwargs: launches.append(
            (operation, work(), kwargs)
        )
    )
    controller._story_project_job_is_current = lambda _payload: True
    controller._sync_story_generated_master_prompt = lambda **_kwargs: None
    controller._refresh_scene_override_controls = lambda: None
    try:
        controller.import_session_state(
            {
                "audio_story_mode": {
                    "project": {"project_id": "same-project", "revision": 1},
                    "story": {
                        "story_bible": {"summary": "Stale session summary"},
                        "transcript_chunks": [
                            {
                                "index": 0,
                                "start_seconds": 0.0,
                                "end_seconds": 1.0,
                                "text": "Stale transcript.",
                            }
                        ],
                        "full_transcript_text": "Stale transcript.",
                    },
                }
            }
        )
        assert len(launches) == 1
        operation, result, kwargs = launches[0]
        assert operation == "open"
        assert kwargs == {
            "project_id": "same-project",
            "switch_project": True,
            "supersede_busy": True,
        }

        controller._on_story_project_job_finished(
            {"operation": operation, "result": result}
        )

        assert controller.story_bible == {"summary": "Authoritative summary"}
        assert controller.full_transcript_text == "Authoritative transcript."
        assert controller.transcript_chunks[0]["text"] == "Authoritative transcript."
        assert controller.imported_audio_duration_seconds == 2.0
    finally:
        controller.shutdown()


def test_controller_session_hint_supersedes_stale_busy_and_pending_state() -> None:
    _app, controller = _session_controller()
    controller_module = importlib.import_module("addons.audio_story_mode.controller")
    authoritative = project_models.new_project_manifest(
        "Authoritative", project_id="busy-project", now=1.0
    )
    authoritative["legacy_session_payload"] = {
        "audio_story_mode_story_bible": {"summary": "Authoritative after busy"}
    }
    opened = []
    controller.current_story_project_id = "busy-project"
    controller._current_story_project = {
        "project_id": "busy-project",
        "name": "Stale busy project",
    }
    controller.story_bible = {"summary": "Stale busy state"}
    controller._story_project_busy = True
    controller._story_project_pending_autosave = (
        "busy-project",
        8,
        controller._story_project_generation,
        "stale-pending",
    )
    controller._story_project_dirty_autosave = {
        "project_id": "busy-project",
        "revision": 8,
        "generation_id": controller._story_project_generation,
        "input_fingerprint": "stale-pending",
        "snapshot": {
            **controller._current_story_project,
            "autosave_revision": 8,
        },
    }
    controller._story_project_manager.open_with_recovery = lambda project_id: (
        opened.append(project_id) or copy.deepcopy(authoritative),
        False,
    )

    class ImmediateThread:
        def __init__(self, *, target, **_kwargs):
            self._target = target

        def start(self):
            self._target()

    original_thread = controller_module.threading.Thread
    controller_module.threading.Thread = ImmediateThread
    try:
        controller.import_session_state(
            {
                "audio_story_mode": {
                    "project": {"project_id": "busy-project", "revision": 1},
                    "story": {
                        "story_bible": {"summary": "Stale imported session"}
                    },
                }
            }
        )

        assert opened == ["busy-project"]
        assert controller.story_bible == {"summary": "Authoritative after busy"}
        assert controller._story_project_pending_autosave is None
        assert controller._story_project_dirty_autosave is None
    finally:
        controller_module.threading.Thread = original_thread
        controller.shutdown()


def test_controller_authoritative_session_open_waits_for_accepted_autosave_drain() -> None:
    app, controller = _session_controller()
    drain_started = Event()
    release_drain = Event()
    open_called = Event()

    class BlockingDrainQueue:
        def flush(self, timeout):
            drain_started.set()
            return release_drain.wait(timeout)

        def shutdown(self, timeout):
            return None

    authoritative = project_models.new_project_manifest(
        "Authoritative", project_id="drain-project", now=1.0
    )
    authoritative["legacy_session_payload"] = {
        "audio_story_mode_story_bible": {"summary": "Opened after drain"}
    }
    controller.current_story_project_id = "drain-project"
    controller._current_story_project = {
        "project_id": "drain-project",
        "autosave_revision": 4,
    }
    controller._story_project_pending_autosave = (
        "drain-project",
        5,
        controller._story_project_generation,
        "accepted-save",
    )
    controller._story_project_dirty_autosave = {
        "project_id": "drain-project",
        "revision": 5,
        "generation_id": controller._story_project_generation,
        "input_fingerprint": "accepted-save",
        "snapshot": {
            **controller._current_story_project,
            "autosave_revision": 5,
        },
    }
    controller._story_project_autosave_queue = BlockingDrainQueue()

    def open_project(project_id):
        open_called.set()
        assert project_id == "drain-project"
        return copy.deepcopy(authoritative)

    controller._story_project_manager.open_with_recovery = lambda project_id: (
        open_project(project_id),
        False,
    )
    try:
        controller.import_session_state(
            {
                "audio_story_mode": {
                    "project": {"project_id": "drain-project", "revision": 1}
                }
            }
        )

        assert drain_started.wait(1.0)
        assert not open_called.is_set()
        release_drain.set()
        assert open_called.wait(1.0)
        for _ in range(100):
            app.processEvents()
            if controller.story_bible == {"summary": "Opened after drain"}:
                break
            Event().wait(0.01)
        assert controller.story_bible == {"summary": "Opened after drain"}
    finally:
        release_drain.set()
        controller.shutdown()


def test_controller_shutdown_invalidates_first_saves_final_revision_and_preserves_runtime_order() -> None:
    _app, controller = _session_controller()
    controller_module = importlib.import_module("addons.audio_story_mode.controller")
    order = []
    requests = []

    class RecordingQueue:
        def request(self, request):
            order.append("queue-request")
            requests.append(request)

        def flush(self, timeout):
            order.append(("queue-flush", timeout))
            return True

        def shutdown(self, timeout):
            order.append(("queue-shutdown", timeout))

    controller.current_story_project_id = "shutdown-project"
    controller._current_story_project = {
        "project_id": "shutdown-project",
        "manifest_revision": 4,
        "autosave_revision": 2,
    }
    controller._story_project_pending_autosave = (
        "shutdown-project",
        3,
        controller._story_project_generation,
        "pending-input",
    )
    controller._story_project_dirty_autosave = {
        "project_id": "shutdown-project",
        "revision": 3,
        "generation_id": controller._story_project_generation,
        "input_fingerprint": "pending-input",
        "snapshot": {
            **controller._current_story_project,
            "autosave_revision": 3,
        },
    }
    controller._story_project_autosave_queue = RecordingQueue()
    original_invalidate = controller._invalidate_story_project_work

    def invalidate():
        order.append("invalidate")
        original_invalidate()

    controller._invalidate_story_project_work = invalidate
    controller._sync_story_generated_master_prompt = (
        lambda **_kwargs: order.append("prompt-restore")
    )
    controller._stop_story = lambda: order.append("player-and-chromecast-stop")
    controller._stop_visual_stream = lambda: order.append("visual-stream-stop")
    original_engine_loaded = controller_module.audio_story_runtime.engine_loaded
    controller_module.audio_story_runtime.engine_loaded = lambda: True
    try:
        controller.shutdown()
    finally:
        controller_module.audio_story_runtime.engine_loaded = original_engine_loaded

    assert len(requests) == 1
    assert requests[0].project_id == "shutdown-project"
    assert requests[0].revision == 4
    assert requests[0].snapshot["autosave_revision"] == 4
    labels = [item if isinstance(item, str) else item[0] for item in order]
    assert labels == [
        "invalidate",
        "queue-request",
        "queue-flush",
        "queue-shutdown",
        "prompt-restore",
        "player-and-chromecast-stop",
        "visual-stream-stop",
    ]
    flush_timeout = next(item[1] for item in order if not isinstance(item, str) and item[0] == "queue-flush")
    shutdown_timeout = next(item[1] for item in order if not isinstance(item, str) and item[0] == "queue-shutdown")
    assert 0.0 <= flush_timeout <= 1.0
    assert 0.0 <= shutdown_timeout <= 1.0
    assert flush_timeout + shutdown_timeout <= 1.0


def test_controller_shutdown_reports_unresolved_final_save_failure() -> None:
    _app, controller = _session_controller()
    statuses = []

    class FailingQueue:
        def __init__(self):
            self.requested = None

        def request(self, request):
            self.requested = request
            controller._story_project_autosave_worker_failed(
                {
                    "project_id": request.project_id,
                    "revision": request.revision,
                    "error": "disk full",
                }
            )

        def flush(self, timeout):
            return True

        def shutdown(self, timeout):
            return None

    controller.current_story_project_id = "failure-project"
    controller._current_story_project = {
        "project_id": "failure-project",
        "autosave_revision": 5,
    }
    controller._story_project_pending_autosave = (
        "failure-project",
        6,
        controller._story_project_generation,
        "pending-input",
    )
    controller._story_project_dirty_autosave = {
        "project_id": "failure-project",
        "revision": 6,
        "generation_id": controller._story_project_generation,
        "input_fingerprint": "pending-input",
        "snapshot": {
            **controller._current_story_project,
            "autosave_revision": 6,
        },
    }
    controller._story_project_autosave_queue = FailingQueue()
    controller._set_status = statuses.append
    controller._set_story_project_autosave_text = lambda text: statuses.append(text)
    controller._sync_story_generated_master_prompt = lambda **_kwargs: None
    controller._stop_story = lambda: None
    controller._stop_visual_stream = lambda: None

    controller.shutdown()

    assert any(
        "final" in message.lower() and "disk full" in message
        for message in statuses
    )


def test_controller_shutdown_ignores_old_failure_after_newer_final_save_succeeds() -> None:
    _app, controller = _session_controller()
    statuses = []
    requests = []

    class OldFailureThenSuccessQueue:
        def request(self, request):
            requests.append(copy.deepcopy(request))
            controller._story_project_autosave_worker_failed(
                {
                    "project_id": request.project_id,
                    "revision": request.revision - 1,
                    "error": "old failure",
                }
            )
            controller._story_project_autosave_worker_saved(
                copy.deepcopy(request.snapshot)
            )

        def flush(self, timeout):
            return True

        def shutdown(self, timeout):
            return None

    controller.current_story_project_id = "shutdown-ownership-project"
    controller._current_story_project = {
        "project_id": "shutdown-ownership-project",
        "autosave_revision": 5,
    }
    old_generation = controller._story_project_generation
    controller._story_project_pending_autosave = (
        "shutdown-ownership-project",
        6,
        old_generation,
        "old-input",
    )
    controller._story_project_dirty_autosave = {
        "project_id": "shutdown-ownership-project",
        "revision": 6,
        "generation_id": old_generation,
        "input_fingerprint": "old-input",
        "snapshot": {
            **controller._current_story_project,
            "autosave_revision": 6,
        },
    }
    controller._story_project_autosave_ownership[
        ("shutdown-ownership-project", 6)
    ] = {
        "project_id": "shutdown-ownership-project",
        "revision": 6,
        "generation_id": old_generation,
        "input_fingerprint": "old-input",
    }
    controller._story_project_autosave_queue = OldFailureThenSuccessQueue()
    controller._set_status = statuses.append
    controller._set_story_project_autosave_text = statuses.append
    controller._sync_story_generated_master_prompt = lambda **_kwargs: None
    controller._stop_story = lambda: None
    controller._stop_visual_stream = lambda: None

    controller.shutdown()

    assert len(requests) == 1
    assert requests[0].revision == 7
    assert not any("final save unresolved" in message.lower() for message in statuses)


def test_controller_shutdown_matching_success_during_shutdown_clears_timeout_failure() -> None:
    _app, controller = _session_controller()
    statuses = []

    class SuccessDuringShutdownQueue:
        def __init__(self):
            self.requested = None

        def request(self, request):
            self.requested = copy.deepcopy(request)

        def flush(self, timeout):
            return False

        def shutdown(self, timeout):
            controller._story_project_autosave_worker_saved(
                copy.deepcopy(self.requested.snapshot)
            )

    controller.current_story_project_id = "shutdown-late-success-project"
    controller._current_story_project = {
        "project_id": "shutdown-late-success-project",
        "autosave_revision": 4,
    }
    controller._story_project_dirty_autosave = {
        "project_id": "shutdown-late-success-project",
        "revision": 5,
        "generation_id": controller._story_project_generation,
        "input_fingerprint": "dirty-input",
        "snapshot": {
            **controller._current_story_project,
            "autosave_revision": 5,
        },
    }
    controller._story_project_autosave_queue = SuccessDuringShutdownQueue()
    controller._set_status = statuses.append
    controller._set_story_project_autosave_text = statuses.append
    controller._sync_story_generated_master_prompt = lambda **_kwargs: None
    controller._stop_story = lambda: None
    controller._stop_visual_stream = lambda: None

    controller.shutdown()

    assert controller._story_project_dirty_autosave is None
    assert not any("final save unresolved" in message.lower() for message in statuses)


def test_controller_shutdown_ignores_stale_queue_error_without_final_ownership() -> None:
    _app, controller = _session_controller()
    statuses = []

    class StaleFailingQueue:
        def flush(self, timeout):
            raise OSError("stale queue failure")

        def shutdown(self, timeout):
            raise OSError("stale queue shutdown failure")

    controller._story_project_autosave_queue = StaleFailingQueue()
    controller._set_status = statuses.append
    controller._set_story_project_autosave_text = statuses.append
    controller._sync_story_generated_master_prompt = lambda **_kwargs: None
    controller._stop_story = lambda: None
    controller._stop_visual_stream = lambda: None

    controller.shutdown()

    assert controller._story_project_shutdown_final_ownership is None
    assert not any("final save unresolved" in message.lower() for message in statuses)


def test_controller_shutdown_matching_success_is_not_overridden_by_flush_error() -> None:
    _app, controller = _session_controller()
    statuses = []

    class SavedThenFlushErrorQueue:
        def request(self, request):
            controller._story_project_autosave_worker_saved(
                copy.deepcopy(request.snapshot)
            )

        def flush(self, timeout):
            raise OSError("flush failed after final success")

        def shutdown(self, timeout):
            return None

    controller.current_story_project_id = "shutdown-flush-success-project"
    controller._current_story_project = {
        "project_id": "shutdown-flush-success-project",
        "autosave_revision": 3,
    }
    controller._story_project_dirty_autosave = {
        "project_id": "shutdown-flush-success-project",
        "revision": 4,
        "generation_id": controller._story_project_generation,
        "input_fingerprint": "dirty-input",
        "snapshot": {
            **controller._current_story_project,
            "autosave_revision": 4,
        },
    }
    controller._story_project_autosave_queue = SavedThenFlushErrorQueue()
    controller._set_status = statuses.append
    controller._set_story_project_autosave_text = statuses.append
    controller._sync_story_generated_master_prompt = lambda **_kwargs: None
    controller._stop_story = lambda: None
    controller._stop_visual_stream = lambda: None

    controller.shutdown()

    assert controller._story_project_dirty_autosave is None
    assert not any("final save unresolved" in message.lower() for message in statuses)


def test_import_requires_project_and_never_partially_commits_without_confirmation(
    tmp_path: Path,
) -> None:
    manager = _manager_with_fake_fingerprints(tmp_path)
    with _raises(story_projects.NoProjectSelectedError):
        manager.review_import(["good.wav"])
    project = manager.create("Series")
    review = manager.review_import(["good.wav", "broken.wav"])
    assert len(review["valid"]) == 1
    assert len(review["invalid"]) == 1
    assert manager.open(project["project_id"])["chapter_order"] == []
    with _raises(story_projects.ImportConfirmationRequired):
        manager.commit_import(review, valid_only=False)
    assert manager.current_project["chapter_order"] == []
    committed = manager.commit_import(review, valid_only=True)
    assert len(committed["chapter_order"]) == 1


def test_import_blocks_duplicates_cross_project_owners_and_review_switches(tmp_path: Path) -> None:
    manager = _manager_with_fake_fingerprints(tmp_path)
    first = manager.create("First")
    duplicate_review = manager.review_import(["good.wav", "moved.wav"])
    assert len(duplicate_review["valid"]) == 1
    assert duplicate_review["conflicts"][0]["reason"] == "duplicate_in_selection"
    with _raises(story_projects.ImportConflictError):
        manager.commit_import(duplicate_review, valid_only=True)
    assert manager.current_project["chapter_order"] == []

    committed = manager.commit_import(manager.review_import(["good.wav"]), valid_only=False)
    assert len(committed["chapter_order"]) == 1
    assert manager.review_import(["moved.wav"])["conflicts"][0]["reason"] == "already_in_project"

    second = manager.create("Second")
    cross_project = manager.review_import(["moved.wav"])
    assert cross_project["conflicts"][0]["reason"] == "owned_by_another_project"
    assert cross_project["conflicts"][0]["owner"]["project_id"] == first["project_id"]
    with _raises(story_projects.ImportConflictError):
        manager.commit_import(cross_project, valid_only=True)

    safe_review = manager.review_import(["different.wav"])
    manager.open(first["project_id"])
    with _raises(story_projects.ImportReviewError):
        manager.commit_import(safe_review, valid_only=False)
    assert manager.open(second["project_id"])["chapter_order"] == []


def test_failed_import_publication_rolls_back_audio_ownership(tmp_path: Path) -> None:
    manager = _manager_with_fake_fingerprints(tmp_path)
    project = manager.create("Rollback")
    review = manager.review_import(["good.wav"])
    original_save = manager.store.save_project
    save_count = 0

    def fail_publication(payload):
        nonlocal save_count
        save_count += 1
        if save_count == 2:
            raise OSError("simulated publication failure")
        return original_save(payload)

    manager.store.save_project = fail_publication
    try:
        with _raises(OSError):
            manager.commit_import(review, valid_only=False)
    finally:
        manager.store.save_project = original_save

    assert manager.store.load_project(project["project_id"])["chapter_order"] == []
    assert manager.store.audio_owner(review["valid"][0]["fingerprint"]) is None
    manager.store.project_path(project["project_id"]).write_text("{broken", encoding="utf-8")
    recovered = manager.store.load_project(project["project_id"])
    assert recovered["chapter_order"] == []
    assert not recovered.get("audio_memberships")


def test_staged_manifest_rolls_back_when_index_write_fails_before_replacement(
    tmp_path: Path,
) -> None:
    manager = _manager_with_fake_fingerprints(tmp_path)
    project = manager.create("Staged index failure")
    review = manager.review_import(["good.wav"])
    index_path = manager.store.root / "project_index.json"
    original_index = json.loads(index_path.read_text(encoding="utf-8"))
    original_index["pre_transaction_marker"] = "preserve"
    index_path.write_text(json.dumps(original_index), encoding="utf-8")
    original_write = project_store._atomic_write_json
    failed = False

    def fail_staged_index(path: Path, payload, **kwargs) -> None:
        nonlocal failed
        if (
            not failed
            and path.name == "project_index.json"
            and payload.get("audio_owners")
        ):
            failed = True
            raise OSError("simulated staged index write failure")
        original_write(path, payload, **kwargs)

    project_store._atomic_write_json = fail_staged_index
    try:
        with _raises(OSError):
            manager.commit_import(review, valid_only=False)
    finally:
        project_store._atomic_write_json = original_write

    recovered = manager.store.load_project(project["project_id"])
    restored_index = json.loads(index_path.read_text(encoding="utf-8"))
    assert recovered["chapter_order"] == []
    assert not recovered.get("audio_memberships")
    assert restored_index == original_index
    assert manager.store.audio_owner(review["valid"][0]["fingerprint"]) is None


def test_import_review_uses_read_only_ownership_lookup(tmp_path: Path) -> None:
    manager = _manager_with_fake_fingerprints(tmp_path)
    manager.create("Review")
    original_rebuild = manager.store.rebuild_index

    def reject_index_write():
        raise AssertionError("review must not rebuild the persisted index")

    manager.store.rebuild_index = reject_index_write
    try:
        review = manager.review_import(["good.wav"])
    finally:
        manager.store.rebuild_index = original_rebuild

    assert len(review["valid"]) == 1


def test_concurrent_managers_cannot_claim_the_same_audio(tmp_path: Path) -> None:
    first_manager = _manager_with_fake_fingerprints(tmp_path)
    second_manager = _manager_with_fake_fingerprints(tmp_path.resolve())
    first = first_manager.create("First")
    second = second_manager.create("Second")
    first_review = first_manager.review_import(["good.wav"])
    second_review = second_manager.review_import(["good.wav"])
    first_staging = Event()
    second_staging = Event()
    start = Barrier(2)
    results: dict[str, object] = {}

    def gate_staging(manager, own_event: Event, other_event: Event):
        original_save = manager.store.save_project

        def save(payload):
            if payload.get("audio_memberships") and not payload.get("chapters"):
                own_event.set()
                other_event.wait(1.0)
            return original_save(payload)

        manager.store.save_project = save
        return original_save

    first_save = gate_staging(first_manager, first_staging, second_staging)
    second_save = gate_staging(second_manager, second_staging, first_staging)

    def commit(key: str, manager, review) -> None:
        try:
            start.wait()
            results[key] = manager.commit_import(review, valid_only=False)
        except Exception as exc:
            results[key] = exc

    first_thread = Thread(target=commit, args=("first", first_manager, first_review))
    second_thread = Thread(target=commit, args=("second", second_manager, second_review))
    try:
        first_thread.start()
        second_thread.start()
        first_thread.join(4.0)
        second_thread.join(4.0)
    finally:
        first_manager.store.save_project = first_save
        second_manager.store.save_project = second_save

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    successes = [result for result in results.values() if isinstance(result, dict)]
    conflicts = [
        result for result in results.values() if isinstance(result, story_projects.ImportConflictError)
    ]
    assert len(successes) == 1
    assert len(conflicts) == 1
    owner = first_manager.store.audio_owner(first_review["valid"][0]["fingerprint"])
    assert owner["project_id"] in {first["project_id"], second["project_id"]}


def test_failed_import_does_not_rollback_over_newer_project_state(tmp_path: Path) -> None:
    manager = _manager_with_fake_fingerprints(tmp_path)
    project = manager.create("Original")
    review = manager.review_import(["good.wav"])
    original_save = manager.store.save_project
    save_count = 0

    def publish_then_add_concurrent_edit(payload):
        nonlocal save_count
        save_count += 1
        if save_count != 2:
            return original_save(payload)
        published = original_save(payload)
        concurrent = copy.deepcopy(published)
        concurrent["name"] = "Concurrent edit"
        original_save(concurrent)
        raise OSError("simulated error after concurrent publication")

    manager.store.save_project = publish_then_add_concurrent_edit
    try:
        with _raises(OSError):
            manager.commit_import(review, valid_only=False)
    finally:
        manager.store.save_project = original_save

    current = manager.store.load_project(project["project_id"])
    assert current["name"] == "Concurrent edit"
    assert len(current["chapter_order"]) == 1


def test_failed_import_does_not_rollback_over_changed_index_state(tmp_path: Path) -> None:
    manager = _manager_with_fake_fingerprints(tmp_path)
    project = manager.create("Index owner")
    review = manager.review_import(["good.wav"])
    original_save = manager.store.save_project
    save_count = 0

    def publish_then_change_index(payload):
        nonlocal save_count
        save_count += 1
        if save_count != 2:
            return original_save(payload)
        original_save(payload)
        index_path = manager.store.root / "project_index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["concurrent_marker"] = "preserve"
        index_path.write_text(json.dumps(index), encoding="utf-8")
        raise OSError("simulated error after concurrent index update")

    manager.store.save_project = publish_then_change_index
    try:
        with _raises(OSError):
            manager.commit_import(review, valid_only=False)
    finally:
        manager.store.save_project = original_save

    current = manager.store.load_project(project["project_id"])
    index = json.loads((manager.store.root / "project_index.json").read_text(encoding="utf-8"))
    assert len(current["chapter_order"]) == 1
    assert index["concurrent_marker"] == "preserve"


def test_import_commit_rejects_mutated_pairwise_duplicates_before_writing(tmp_path: Path) -> None:
    manager = _manager_with_fake_fingerprints(tmp_path)
    project = manager.create("Duplicates")
    review = manager.review_import(["good.wav", "different.wav"])
    review["valid"][1]["path"] = "moved.wav"
    review["valid"][1]["fingerprint"] = copy.deepcopy(review["valid"][0]["fingerprint"])
    original_save = manager.store.save_project

    def reject_write(_payload):
        raise AssertionError("duplicate validation must finish before persistence")

    manager.store.save_project = reject_write
    try:
        with _raises(story_projects.ImportConflictError):
            manager.commit_import(review, valid_only=False)
    finally:
        manager.store.save_project = original_save

    assert manager.store.load_project(project["project_id"])["chapter_order"] == []


def test_import_commit_rejects_current_fingerprint_convergence_before_writing(
    tmp_path: Path,
) -> None:
    current = False

    def fingerprint_reader(path, _duration_reader, **_kwargs):
        duration_ms = 1050 if current else {"first.wav": 1000, "second.wav": 1100}[Path(path).name]
        return {
            "algorithm": "sha256-sampled-v1",
            "digest": "same-content",
            "size_bytes": 10,
            "duration_ms": duration_ms,
        }

    manager = story_projects.StoryProjectManager(
        project_store.StoryProjectStore(tmp_path),
        duration_reader=lambda _path: 1.0,
        fingerprint_reader=fingerprint_reader,
    )
    project = manager.create("Converged")
    review = manager.review_import(["first.wav", "second.wav"])
    assert len(review["valid"]) == 2
    current = True
    original_save = manager.store.save_project

    def reject_write(_payload):
        raise AssertionError("current duplicate validation must finish before persistence")

    manager.store.save_project = reject_write
    try:
        with _raises(story_projects.ImportConflictError):
            manager.commit_import(review, valid_only=False)
    finally:
        manager.store.save_project = original_save

    assert manager.store.load_project(project["project_id"])["chapter_order"] == []


def test_import_commit_checks_current_fingerprint_against_existing_owner(
    tmp_path: Path,
) -> None:
    def owner_fingerprint(_path, _duration_reader, **_kwargs):
        return {
            "algorithm": "sha256-sampled-v1",
            "digest": "shared",
            "size_bytes": 10,
            "duration_ms": 1100,
        }

    owner_manager = story_projects.StoryProjectManager(
        project_store.StoryProjectStore(tmp_path),
        duration_reader=lambda _path: 1.0,
        fingerprint_reader=owner_fingerprint,
    )
    owner_manager.create("Owner")
    owner_manager.commit_import(owner_manager.review_import(["owner.wav"]), valid_only=False)

    target_duration_ms = 1000

    def target_fingerprint(_path, _duration_reader, **_kwargs):
        return {
            "algorithm": "sha256-sampled-v1",
            "digest": "shared",
            "size_bytes": 10,
            "duration_ms": target_duration_ms,
        }

    target_manager = story_projects.StoryProjectManager(
        project_store.StoryProjectStore(tmp_path.resolve()),
        duration_reader=lambda _path: 1.0,
        fingerprint_reader=target_fingerprint,
    )
    target = target_manager.create("Target")
    review = target_manager.review_import(["target.wav"])
    assert len(review["valid"]) == 1
    target_duration_ms = 1050
    original_save = target_manager.store.save_project

    def reject_write(_payload):
        raise AssertionError("current ownership validation must finish before persistence")

    target_manager.store.save_project = reject_write
    try:
        with _raises(story_projects.ImportConflictError):
            target_manager.commit_import(review, valid_only=False)
    finally:
        target_manager.store.save_project = original_save

    assert target_manager.store.load_project(target["project_id"])["chapter_order"] == []


def test_import_commit_refingerprints_changed_paths_before_writing(tmp_path: Path) -> None:
    fingerprint = {
        "algorithm": "sha256-sampled-v1",
        "digest": "reviewed",
        "size_bytes": 10,
        "duration_ms": 1000,
    }

    def fingerprint_reader(_path, _duration_reader, **_kwargs):
        return copy.deepcopy(fingerprint)

    manager = story_projects.StoryProjectManager(
        project_store.StoryProjectStore(tmp_path),
        duration_reader=lambda _path: 1.0,
        fingerprint_reader=fingerprint_reader,
    )
    project = manager.create("Changed")
    review = manager.review_import(["changing.wav"])
    fingerprint["digest"] = "changed-after-review"
    original_save = manager.store.save_project

    def reject_write(_payload):
        raise AssertionError("changed-file validation must finish before persistence")

    manager.store.save_project = reject_write
    try:
        with _raises(story_projects.ImportReviewError):
            manager.commit_import(review, valid_only=False)
    finally:
        manager.store.save_project = original_save

    assert manager.store.load_project(project["project_id"])["chapter_order"] == []


def test_import_commit_rejects_missing_required_candidate_fields(tmp_path: Path) -> None:
    manager = _manager_with_fake_fingerprints(tmp_path)
    project = manager.create("Malformed")
    review = manager.review_import(["good.wav"])
    review["valid"][0].pop("display_name")
    original_save = manager.store.save_project

    def reject_write(_payload):
        raise AssertionError("candidate validation must finish before persistence")

    manager.store.save_project = reject_write
    try:
        with _raises(story_projects.ImportReviewError):
            manager.commit_import(review, valid_only=False)
    finally:
        manager.store.save_project = original_save

    assert manager.store.load_project(project["project_id"])["chapter_order"] == []


def test_archive_restore_reorder_and_mutations_require_selection(tmp_path: Path) -> None:
    manager = _manager_with_fake_fingerprints(tmp_path)
    project = manager.create("Series")
    committed = manager.commit_import(
        manager.review_import(["good.wav", "different.wav"]),
        valid_only=False,
    )
    first_id, second_id = committed["chapter_order"]

    archived = manager.archive_chapter(first_id)
    assert archived["chapter_order"] == [second_id]
    assert archived["archived_chapter_ids"] == [first_id]
    assert first_id in archived["chapters"]
    restored = manager.restore_chapter(first_id)
    assert restored["chapter_order"] == [second_id, first_id]
    assert restored["archived_chapter_ids"] == []
    reordered = manager.reorder_chapters([first_id, second_id])
    assert reordered["chapter_order"] == [first_id, second_id]
    with _raises(story_projects.ChapterOrderError):
        manager.reorder_chapters([first_id])
    assert manager.current_project["chapter_order"] == [first_id, second_id]

    renamed = manager.rename("Renamed")
    assert renamed["name"] == "Renamed"
    manager.close()
    for operation in (
        lambda: manager.rename("Closed"),
        lambda: manager.archive_chapter(first_id),
        lambda: manager.restore_chapter(first_id),
        lambda: manager.reorder_chapters([first_id, second_id]),
        lambda: manager.relink_chapter(first_id, "moved.wav"),
    ):
        with _raises(story_projects.NoProjectSelectedError):
            operation()
    assert manager.open(project["project_id"])["name"] == "Renamed"


def test_delete_project_removes_only_project_data_and_releases_audio_ownership(
    tmp_path: Path,
) -> None:
    manager = _manager_with_fake_fingerprints(tmp_path)
    source_audio = tmp_path / "source-audio" / "good.wav"
    source_audio.parent.mkdir()
    source_audio.write_bytes(b"original-audio")
    first = manager.create("Remove me")
    manager.commit_import(manager.review_import([str(source_audio)]), valid_only=False)
    first_directory = tmp_path / first["project_id"]
    assert first_directory.is_dir()
    second = manager.create("Keep me")
    manager.open(first["project_id"])
    deleted = manager.delete(first["project_id"])

    assert deleted["project_id"] == first["project_id"]
    assert not first_directory.exists()
    assert source_audio.read_bytes() == b"original-audio"
    assert manager.current_project_id == ""
    assert manager.current_project is None
    assert [project["project_id"] for project in manager.store.list_projects()] == [
        second["project_id"]
    ]
    assert manager.store.audio_owner(
        {
            "algorithm": "sha256-sampled-v1",
            "digest": "good",
            "size_bytes": 10,
            "duration_ms": 1000,
        }
    ) is None
    with _raises(project_store.ProjectNotFoundError):
        manager.open(first["project_id"])


def _manager_with_committed_chapter_memories(
    tmp_path: Path,
    chapter_ids: list[str],
) -> tuple[story_projects.StoryProjectManager, dict]:
    store = project_store.StoryProjectStore(tmp_path)
    manager = story_projects.StoryProjectManager(
        store,
        duration_reader=lambda _path: 1.0,
        fingerprint_reader=lambda *_args, **_kwargs: {},
    )
    project = manager.create("Continuity")
    committed_bible = story_memory.empty_story_memory()
    for index, chapter_id in enumerate(chapter_ids, start=1):
        chapter = project_models.new_chapter_manifest(
            f"Chapter {index}",
            {
                "path": f"{chapter_id}.wav",
                "fingerprint": {
                    "algorithm": "sha256-sampled-v1",
                    "digest": chapter_id,
                    "size_bytes": index,
                    "duration_ms": 1000,
                },
            },
            chapter_id=chapter_id,
        )
        chapter_memory = story_memory.empty_story_memory()
        chapter_memory["characters"][chapter_id] = {
            "display_name": chapter_id.upper(),
            "visual_identity": f"Identity from {chapter_id}",
            "confidence": 1.0,
        }
        analysis_ref = store.save_chapter_document(
            project["project_id"],
            chapter_id,
            "analysis",
            1,
            {"project_story_memory": chapter_memory, "scene_plan": []},
        )
        for stage, checkpoint in chapter["stages"].items():
            checkpoint["status"] = "completed"
            checkpoint["input_fingerprint"] = f"{chapter_id}:{stage}:input"
            checkpoint["expected_input_fingerprint"] = checkpoint[
                "input_fingerprint"
            ]
            checkpoint["output_fingerprint"] = f"{chapter_id}:{stage}:output"
            checkpoint["output_ref"] = f"{chapter_id}:{stage}:output"
            checkpoint["completed_at"] = float(index)
        chapter["stages"]["story_analysis"]["output_ref"] = analysis_ref
        project["chapters"][chapter_id] = chapter
        project["chapter_order"].append(chapter_id)
        committed_bible = story_memory.merge_committed_story_bible(
            committed_bible, chapter_memory
        )
    story_bible_ref = project_store._story_bible_reference(1)
    project_store._atomic_write_json(
        store.project_path(project["project_id"]).parent / story_bible_ref,
        committed_bible,
    )
    project["story_bible_revision"] = 1
    project["story_bible_ref"] = story_bible_ref
    saved = store.save_project(project)
    manager.open(saved["project_id"])
    return manager, saved


def test_archiving_tail_rebuilds_story_bible_without_archived_chapter(
    tmp_path: Path,
) -> None:
    manager, original = _manager_with_committed_chapter_memories(
        tmp_path, ["chapter-a", "chapter-b"]
    )

    archived = manager.archive_chapter("chapter-b")
    rebuilt_bible = manager.store.load_story_bible(original["project_id"])

    assert archived["story_bible_revision"] > original["story_bible_revision"]
    assert set(rebuilt_bible["characters"]) == {"chapter-a"}
    assert archived["chapters"]["chapter-a"]["stages"]["story_analysis"][
        "status"
    ] == "completed"
    assert archived["chapters"]["chapter-a"]["stages"]["transcription"][
        "status"
    ] == "completed"


def test_reorder_rebuilds_bible_from_valid_unchanged_prefix_only(
    tmp_path: Path,
) -> None:
    manager, original = _manager_with_committed_chapter_memories(
        tmp_path, ["chapter-a", "chapter-b", "chapter-c"]
    )

    reordered = manager.reorder_chapters(
        ["chapter-a", "chapter-c", "chapter-b"]
    )
    rebuilt_bible = manager.store.load_story_bible(original["project_id"])

    assert reordered["story_bible_revision"] > original["story_bible_revision"]
    assert set(rebuilt_bible["characters"]) == {"chapter-a"}
    assert reordered["chapters"]["chapter-a"]["stages"]["story_analysis"][
        "status"
    ] == "completed"
    for chapter_id in ("chapter-b", "chapter-c"):
        assert reordered["chapters"][chapter_id]["stages"]["story_analysis"][
            "status"
        ] == "stale"
        assert reordered["chapters"][chapter_id]["stages"]["transcription"][
            "status"
        ] == "completed"


def test_reorder_rejects_completed_prefix_with_changed_analysis_dependency(
    tmp_path: Path,
) -> None:
    manager, original = _manager_with_committed_chapter_memories(
        tmp_path, ["chapter-a", "chapter-b", "chapter-c"]
    )
    changed = manager.store.load_project(original["project_id"])
    changed["chapters"]["chapter-a"]["stages"]["story_analysis"][
        "expected_input_fingerprint"
    ] = "changed-dependency"
    changed = manager.store.save_project(changed)
    manager.open(changed["project_id"])

    reordered = manager.reorder_chapters(
        ["chapter-a", "chapter-c", "chapter-b"]
    )
    rebuilt_bible = manager.store.load_story_bible(original["project_id"])

    assert rebuilt_bible["characters"] == {}
    for chapter_id in ("chapter-a", "chapter-b", "chapter-c"):
        assert reordered["chapters"][chapter_id]["stages"]["story_analysis"][
            "status"
        ] == "stale"
        assert reordered["chapters"][chapter_id]["stages"]["transcription"][
            "status"
        ] == "completed"


def test_relink_requires_matching_fingerprint_and_preserves_old_path_on_failure(
    tmp_path: Path,
) -> None:
    manager = _manager_with_fake_fingerprints(tmp_path)
    manager.create("Series")
    committed = manager.commit_import(manager.review_import(["good.wav"]), valid_only=False)
    chapter = committed["chapters"][committed["chapter_order"][0]]
    with _raises(story_projects.RelinkMismatchError):
        manager.relink_chapter(chapter["chapter_id"], "different.wav")
    current = manager.current_project["chapters"][chapter["chapter_id"]]
    assert current["audio"]["path"] == chapter["audio"]["path"]
    relinked = manager.relink_chapter(chapter["chapter_id"], "moved.wav")
    relinked_chapter = relinked["chapters"][chapter["chapter_id"]]
    assert relinked_chapter["audio"]["path"] == "moved.wav"
    assert relinked_chapter["audio"]["fingerprint"] == chapter["audio"]["fingerprint"]
    assert manager.current_project["chapters"][chapter["chapter_id"]]["audio_reference"]["path"] == (
        "moved.wav"
    )


def test_legacy_preview_is_non_destructive_and_preserves_missing_audio_state(
    tmp_path: Path,
) -> None:
    manager = _manager_with_fake_fingerprints(tmp_path)
    source = {
        "audio_story_mode_audio_paths": ["good.wav", "broken.wav"],
        "audio_story_mode_audio_path": "good.wav",
        "audio_story_mode_full_transcript_text": "Derived words survive.",
        "audio_story_mode_story_bible": {"summary": "Derived story survives."},
    }
    original = copy.deepcopy(source)

    preview = manager.prepare_legacy_migration(source, "Migrated")

    assert source == original
    assert manager.current_project is None
    assert not manager.store.list_projects()
    draft = preview["project"]
    assert len(draft["chapter_order"]) == 2
    missing = [
        draft["chapters"][chapter_id]
        for chapter_id in draft["chapter_order"]
        if draft["chapters"][chapter_id]["audio"]["path"] == "broken.wav"
    ][0]
    assert missing["stages"]["audio_validation"]["status"] == "missing_audio"
    assert draft["legacy_session_payload"] == original

    source["audio_story_mode_story_bible"]["summary"] = "mutated after preview"
    migrated = manager.commit_legacy_migration(preview)
    assert migrated["legacy_session_payload"] == original
    assert len(migrated["chapter_order"]) == 2
    assert manager.current_project_id == migrated["project_id"]


def test_legacy_commit_is_create_like_and_requires_unchanged_opaque_preview(
    tmp_path: Path,
) -> None:
    manager = _manager_with_fake_fingerprints(tmp_path)
    preview = manager.prepare_legacy_migration(
        {"audio_story_mode_audio_path": "good.wav"},
        "Explicitly Named",
    )
    assert manager.current_project_id == ""
    assert isinstance(preview.get("preview_token"), str)
    assert len(preview["preview_token"]) >= 20

    tampered = copy.deepcopy(preview)
    tampered["project"]["name"] = "Tampered"
    with _raises(story_projects.ImportReviewError):
        manager.commit_legacy_migration(tampered)
    assert manager.current_project_id == ""
    assert not manager.store.list_projects()

    migrated = manager.commit_legacy_migration(copy.deepcopy(preview))
    assert migrated["name"] == "Explicitly Named"
    assert manager.current_project_id == migrated["project_id"]
    with _raises(story_projects.ImportReviewError):
        manager.commit_legacy_migration(preview)


def test_concurrent_legacy_migrations_cannot_claim_the_same_audio(tmp_path: Path) -> None:
    first_manager = _manager_with_fake_fingerprints(tmp_path)
    second_manager = _manager_with_fake_fingerprints(tmp_path.resolve())
    source = {"audio_story_mode_audio_path": "good.wav"}
    first_preview = first_manager.prepare_legacy_migration(source, "First migration")
    second_preview = second_manager.prepare_legacy_migration(source, "Second migration")
    first_staging = Event()
    second_staging = Event()
    start = Barrier(2)
    results: dict[str, object] = {}

    def gate_publication(manager, own_event: Event, other_event: Event):
        original_save = manager.store.save_project

        def save(payload):
            own_event.set()
            other_event.wait(1.0)
            return original_save(payload)

        manager.store.save_project = save
        return original_save

    first_save = gate_publication(first_manager, first_staging, second_staging)
    second_save = gate_publication(second_manager, second_staging, first_staging)

    def commit(key: str, manager, preview) -> None:
        try:
            start.wait()
            results[key] = manager.commit_legacy_migration(preview)
        except Exception as exc:
            results[key] = exc

    first_thread = Thread(target=commit, args=("first", first_manager, first_preview))
    second_thread = Thread(target=commit, args=("second", second_manager, second_preview))
    try:
        first_thread.start()
        second_thread.start()
        first_thread.join(4.0)
        second_thread.join(4.0)
    finally:
        first_manager.store.save_project = first_save
        second_manager.store.save_project = second_save

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    successes = [result for result in results.values() if isinstance(result, dict)]
    conflicts = [
        result for result in results.values() if isinstance(result, story_projects.ImportConflictError)
    ]
    assert len(successes) == 1
    assert len(conflicts) == 1


def test_legacy_commit_checks_current_identity_against_new_owner(tmp_path: Path) -> None:
    legacy_duration_ms = 1000

    def legacy_fingerprint(_path, _duration_reader, **_kwargs):
        return {
            "algorithm": "sha256-sampled-v1",
            "digest": "shared",
            "size_bytes": 10,
            "duration_ms": legacy_duration_ms,
        }

    legacy_manager = story_projects.StoryProjectManager(
        project_store.StoryProjectStore(tmp_path),
        duration_reader=lambda _path: 1.0,
        fingerprint_reader=legacy_fingerprint,
    )
    preview = legacy_manager.prepare_legacy_migration(
        {"audio_story_mode_audio_path": "legacy.wav"},
        "Legacy",
    )

    def owner_fingerprint(_path, _duration_reader, **_kwargs):
        return {
            "algorithm": "sha256-sampled-v1",
            "digest": "shared",
            "size_bytes": 10,
            "duration_ms": 1100,
        }

    owner_manager = story_projects.StoryProjectManager(
        project_store.StoryProjectStore(tmp_path.resolve()),
        duration_reader=lambda _path: 1.0,
        fingerprint_reader=owner_fingerprint,
    )
    owner_project = owner_manager.create("Owner")
    owner_manager.commit_import(owner_manager.review_import(["owner.wav"]), valid_only=False)
    legacy_duration_ms = 1050

    with _raises(story_projects.ImportConflictError):
        legacy_manager.commit_legacy_migration(preview)
    assert legacy_manager.current_project_id == ""
    projects = legacy_manager.store.list_projects()
    assert [project["project_id"] for project in projects] == [owner_project["project_id"]]


def test_legacy_commit_rejects_current_fingerprint_convergence(tmp_path: Path) -> None:
    current = False

    def fingerprint_reader(path, _duration_reader, **_kwargs):
        duration_ms = 1050 if current else {"first.wav": 1000, "second.wav": 1100}[Path(path).name]
        return {
            "algorithm": "sha256-sampled-v1",
            "digest": "same-content",
            "size_bytes": 10,
            "duration_ms": duration_ms,
        }

    manager = story_projects.StoryProjectManager(
        project_store.StoryProjectStore(tmp_path),
        duration_reader=lambda _path: 1.0,
        fingerprint_reader=fingerprint_reader,
    )
    preview = manager.prepare_legacy_migration(
        {"audio_story_mode_audio_paths": ["first.wav", "second.wav"]},
        "Converged legacy",
    )
    assert len(preview["valid"]) == 2
    current = True

    with _raises(story_projects.ImportConflictError):
        manager.commit_legacy_migration(preview)
    assert manager.current_project_id == ""
    assert not manager.store.list_projects()


def test_new_project_and_chapter_have_stable_versioned_shape() -> None:
    project = project_models.new_project_manifest(
        "Making Monster Girls", project_id="project-1", now=100.0
    )
    chapter = project_models.new_chapter_manifest(
        "Chapter 1",
        {
            "path": r"N:\books\chapter1.wav",
            "fingerprint": {"digest": "abc", "size_bytes": 12, "duration_ms": 27000},
        },
        chapter_id="chapter-1",
        now=101.0,
    )
    assert project["schema_version"] == 1
    assert project["chapter_order"] == []
    assert chapter["chapter_id"] == "chapter-1"
    assert chapter["stages"]["transcription"]["status"] == "pending"


def test_normalizers_copy_unknown_data_and_repair_required_fields() -> None:
    source = {
        "name": "  Monster Book  ",
        "story_bible_revision": "invalid",
        "autosave_revision": 2.9,
        "chapter_order": ["chapter-1", 2],
        "chapters": {"chapter-1": {"title": "Source chapter"}},
        "archived_chapter_ids": ["chapter-old", 3],
        "custom": {"tags": ["keep"]},
    }
    normalized_project = project_models.normalize_project_manifest(source)
    source["custom"]["tags"].append("mutated")
    assert normalized_project["name"] == "Monster Book"
    assert normalized_project["story_bible_revision"] == 0
    assert normalized_project["autosave_revision"] == 2
    assert normalized_project["chapter_order"] == ["chapter-1", "2"]
    assert normalized_project["custom"] == {"tags": ["keep"]}

    normalized_chapter = project_models.normalize_chapter_manifest(
        {
            "display_name": "  Chapter 1  ",
            "audio_reference": {"path": "chapter1.wav"},
            "stages": {"transcription": {"status": "not-a-status", "attempt_count": "3"}},
        }
    )
    assert normalized_chapter["display_name"] == "Chapter 1"
    assert normalized_chapter["stages"]["transcription"]["status"] == "pending"
    assert normalized_chapter["stages"]["transcription"]["attempt_count"] == 3
    assert normalized_chapter["stages"]["story_analysis"]["status"] == "pending"

    with _raises(ValueError):
        project_models.checkpoint("unknown", "chapter-1")
    with _raises(ValueError):
        project_models.checkpoint("transcription", "chapter-1", status="unknown")


def test_sampled_fingerprint_survives_move_and_detects_changed_content(tmp_path: Path) -> None:
    first = tmp_path / "first.wav"
    moved = tmp_path / "moved.wav"
    first.write_bytes((b"a" * 2048) + (b"b" * 2048) + (b"c" * 2048))
    moved.write_bytes(first.read_bytes())
    read_duration = lambda _path: 6.25
    original = audio_fingerprint.compute_audio_fingerprint(first, read_duration, sample_bytes=512)
    relocated = audio_fingerprint.compute_audio_fingerprint(moved, read_duration, sample_bytes=512)
    assert audio_fingerprint.fingerprint_matches(original, relocated)
    moved.write_bytes(moved.read_bytes()[:-1] + b"x")
    changed = audio_fingerprint.compute_audio_fingerprint(moved, read_duration, sample_bytes=512)
    assert not audio_fingerprint.fingerprint_matches(original, changed)


def test_fingerprint_requires_duration_and_all_identity_fields(tmp_path: Path) -> None:
    audio_file = tmp_path / "chapter.wav"
    audio_file.write_bytes(b"audio")
    with _raises(ValueError):
        audio_fingerprint.compute_audio_fingerprint(audio_file, lambda _path: 0.0)

    fingerprint = audio_fingerprint.compute_audio_fingerprint(audio_file, lambda _path: 1.0)
    near_duration = copy.deepcopy(fingerprint)
    near_duration["duration_ms"] += 50
    assert audio_fingerprint.fingerprint_matches(fingerprint, near_duration)
    near_duration["duration_ms"] += 1
    assert not audio_fingerprint.fingerprint_matches(fingerprint, near_duration)
    missing_digest = copy.deepcopy(fingerprint)
    missing_digest.pop("digest")
    assert not audio_fingerprint.fingerprint_matches(fingerprint, missing_digest)


def test_store_recovers_damaged_primary_and_rebuilds_index(tmp_path: Path) -> None:
    store = project_store.StoryProjectStore(tmp_path)
    created = store.create_project("Series A")
    created["autosave_revision"] = 1
    created = store.save_project(created)
    created["autosave_revision"] = 2
    created = store.save_project(created)
    store.project_path(created["project_id"]).write_text("{broken", encoding="utf-8")

    recovered = store.load_project(created["project_id"])

    assert recovered["autosave_revision"] == 1
    rebuilt = store.rebuild_index()
    assert created["project_id"] in rebuilt["projects"]


def test_audio_membership_is_unique_across_projects(tmp_path: Path) -> None:
    store = project_store.StoryProjectStore(tmp_path)
    first = store.create_project("One")
    second = store.create_project("Two")
    fingerprint = {
        "algorithm": "sha256-sampled-v1",
        "digest": "d1",
        "size_bytes": 50,
        "duration_ms": 1000,
    }

    store.register_audio(first["project_id"], "chapter-1", fingerprint)

    assert store.audio_owner(fingerprint) == {
        "project_id": first["project_id"],
        "chapter_id": "chapter-1",
    }
    with _raises(project_store.AudioOwnershipConflict):
        store.register_audio(second["project_id"], "chapter-2", fingerprint)


def test_analysis_transaction_does_not_publish_pointers_when_staging_fails(tmp_path: Path) -> None:
    store = project_store.StoryProjectStore(tmp_path)
    project = store.create_project("Transaction")
    chapter = project_models.new_chapter_manifest(
        "Chapter 1", {"path": "chapter.wav"}, chapter_id="chapter-1"
    )
    project["chapter_order"] = [chapter["chapter_id"]]
    project["chapters"] = {chapter["chapter_id"]: chapter}
    store.save_project(project)
    original = store.load_project(project["project_id"])
    original_write = project_store._atomic_write_json

    def fail_story_bible_stage(path: Path, payload, **kwargs) -> None:
        if path.name == "story_bible.1.json":
            raise OSError("simulated staging failure")
        original_write(path, payload, **kwargs)

    project_store._atomic_write_json = fail_story_bible_stage
    try:
        with _raises(OSError):
            store.commit_analysis_transaction(
                original,
                chapter["chapter_id"],
                {"summary": "analysis"},
                {"title": "story bible"},
            )
    finally:
        project_store._atomic_write_json = original_write

    recovered = store.load_project(project["project_id"])
    assert recovered["story_bible_revision"] == 0
    assert recovered["chapters"][chapter["chapter_id"]]["stages"]["story_analysis"]["output_ref"] == ""


def test_analysis_transaction_publishes_prepared_checkpoint_state_atomically(
    tmp_path: Path,
) -> None:
    store = project_store.StoryProjectStore(tmp_path)
    project = store.create_project("Prepared transaction")
    first = project_models.new_chapter_manifest(
        "Chapter 1", {"path": "chapter-1.wav"}, chapter_id="chapter-1"
    )
    second = project_models.new_chapter_manifest(
        "Chapter 2", {"path": "chapter-2.wav"}, chapter_id="chapter-2"
    )
    project["chapter_order"] = [first["chapter_id"], second["chapter_id"]]
    project["chapters"] = {
        first["chapter_id"]: first,
        second["chapter_id"]: second,
    }
    prepared = store.save_project(project)
    prepared["chapters"][first["chapter_id"]]["stages"]["story_analysis"].update(
        {
            "status": "completed",
            "input_fingerprint": "analysis-input",
            "expected_input_fingerprint": "analysis-input",
            "output_fingerprint": "analysis-output",
        }
    )
    prepared["chapters"][first["chapter_id"]]["stages"]["scene_planning"].update(
        {
            "status": "completed",
            "input_fingerprint": "scene-input",
            "expected_input_fingerprint": "scene-input",
            "output_fingerprint": "scene-output",
        }
    )
    prepared["chapters"][second["chapter_id"]]["stages"]["story_analysis"].update(
        {"status": "stale", "output_ref": "", "output_fingerprint": ""}
    )

    committed = store.commit_analysis_transaction(
        prepared,
        first["chapter_id"],
        {"summary": "analysis"},
        {"title": "story bible"},
    )
    reopened = store.load_project(project["project_id"])

    for manifest in (committed, reopened):
        stages = manifest["chapters"][first["chapter_id"]]["stages"]
        assert manifest["story_bible_revision"] == 1
        assert stages["story_analysis"]["status"] == "completed"
        assert stages["story_analysis"]["output_ref"].endswith("analysis.1.json")
        assert stages["scene_planning"]["status"] == "completed"
        assert (
            manifest["chapters"][second["chapter_id"]]["stages"]["story_analysis"][
                "status"
            ]
            == "stale"
        )


def test_analysis_transaction_recovers_from_post_manifest_index_failure(
    tmp_path: Path,
) -> None:
    store = project_store.StoryProjectStore(tmp_path)
    project = store.create_project("Recoverable index")
    chapter = project_models.new_chapter_manifest(
        "Chapter 1", {"path": "chapter.wav"}, chapter_id="chapter-1"
    )
    project["chapter_order"] = [chapter["chapter_id"]]
    project["chapters"] = {chapter["chapter_id"]: chapter}
    prepared = store.save_project(project)
    prepared["chapters"][chapter["chapter_id"]]["stages"]["story_analysis"].update(
        {
            "status": "completed",
            "input_fingerprint": "analysis-input",
            "expected_input_fingerprint": "analysis-input",
            "output_fingerprint": "analysis-output",
        }
    )
    prepared["chapters"][chapter["chapter_id"]]["stages"]["scene_planning"].update(
        {
            "status": "completed",
            "input_fingerprint": "scene-input",
            "expected_input_fingerprint": "scene-input",
            "output_fingerprint": "scene-output",
        }
    )
    original_rebuild = store.rebuild_index

    def fail_index_after_manifest() -> dict:
        raise OSError("simulated project index failure")

    store.rebuild_index = fail_index_after_manifest
    try:
        committed = store.commit_analysis_transaction(
            prepared,
            chapter["chapter_id"],
            {"summary": "analysis"},
            {"title": "story bible"},
        )
    finally:
        store.rebuild_index = original_rebuild

    reopened = store.load_project(project["project_id"])
    analysis = reopened["chapters"][chapter["chapter_id"]]["stages"][
        "story_analysis"
    ]
    scene = reopened["chapters"][chapter["chapter_id"]]["stages"][
        "scene_planning"
    ]
    assert committed["story_bible_revision"] == 1
    assert reopened["story_bible_revision"] == 1
    assert analysis["status"] == "completed"
    assert analysis["output_ref"].endswith("analysis.1.json")
    assert scene["status"] == "completed"
    assert store.load_story_bible(project["project_id"]) == {"title": "story bible"}
    assert store.index_rebuild_pending is True
    assert "simulated project index failure" in store.last_index_error
    assert "index_rebuild_pending" not in reopened
    assert "last_index_error" not in reopened

    listed = store.list_projects()
    rebuilt_index = json.loads(store._index_path.read_text(encoding="utf-8"))

    assert [item["project_id"] for item in listed] == [project["project_id"]]
    assert rebuilt_index["projects"][project["project_id"]]["updated_at"] == reopened[
        "updated_at"
    ]
    assert store.index_rebuild_pending is False
    assert store.last_index_error == ""


def test_analysis_transaction_rejects_stale_manifest_without_overwriting_revision(tmp_path: Path) -> None:
    store = project_store.StoryProjectStore(tmp_path)
    project = store.create_project("Concurrent")
    chapter = project_models.new_chapter_manifest(
        "Chapter 1", {"path": "chapter.wav"}, chapter_id="chapter-1"
    )
    project["chapter_order"] = [chapter["chapter_id"]]
    project["chapters"] = {chapter["chapter_id"]: chapter}
    store.save_project(project)
    stale = store.load_project(project["project_id"])
    store.commit_analysis_transaction(
        stale,
        chapter["chapter_id"],
        {"summary": "first"},
        {"title": "first bible"},
    )

    with _raises(project_store.ProjectStoreError):
        store.commit_analysis_transaction(
            stale,
            chapter["chapter_id"],
            {"summary": "stale"},
            {"title": "stale bible"},
        )

    current = store.load_project(project["project_id"])
    assert current["story_bible_revision"] == 1
    assert store.load_story_bible(project["project_id"]) == {"title": "first bible"}
    assert store.load_chapter_document(project["project_id"], chapter["chapter_id"], "analysis") == {
        "summary": "first"
    }


def test_analysis_transaction_retry_uses_new_revision_after_failed_staging(tmp_path: Path) -> None:
    store = project_store.StoryProjectStore(tmp_path)
    project = store.create_project("Retry")
    chapter = project_models.new_chapter_manifest(
        "Chapter 1", {"path": "chapter.wav"}, chapter_id="chapter-1"
    )
    project["chapter_order"] = [chapter["chapter_id"]]
    project["chapters"] = {chapter["chapter_id"]: chapter}
    baseline = store.save_project(project)
    original_write = project_store._atomic_write_json

    def fail_first_story_bible_stage(path: Path, payload, **kwargs) -> None:
        if path.name == "story_bible.1.json":
            raise OSError("simulated staging failure")
        original_write(path, payload, **kwargs)

    project_store._atomic_write_json = fail_first_story_bible_stage
    try:
        with _raises(OSError):
            store.commit_analysis_transaction(
                baseline,
                chapter["chapter_id"],
                {"summary": "orphaned"},
                {"title": "orphaned bible"},
            )
    finally:
        project_store._atomic_write_json = original_write

    committed = store.commit_analysis_transaction(
        baseline,
        chapter["chapter_id"],
        {"summary": "retry"},
        {"title": "retry bible"},
    )

    assert committed["story_bible_revision"] == 2
    assert store.load_chapter_document(
        project["project_id"], chapter["chapter_id"], "analysis", revision=1
    ) == {"summary": "orphaned"}
    assert store.load_story_bible(project["project_id"]) == {"title": "retry bible"}


def test_audio_membership_matches_duration_tolerance_and_rejects_invalid_duration(tmp_path: Path) -> None:
    store = project_store.StoryProjectStore(tmp_path)
    first = store.create_project("One")
    second = store.create_project("Two")
    fingerprint = {
        "algorithm": "sha256-sampled-v1",
        "digest": "d1",
        "size_bytes": 50,
        "duration_ms": 1000,
    }
    near_duration = {**fingerprint, "duration_ms": 1050}
    outside_tolerance = {**fingerprint, "duration_ms": 1051}

    store.register_audio(first["project_id"], "chapter-1", fingerprint)

    assert store.audio_owner(near_duration) == {
        "project_id": first["project_id"],
        "chapter_id": "chapter-1",
    }
    assert store.audio_owner(outside_tolerance) is None
    store.register_audio(second["project_id"], "chapter-2", outside_tolerance)
    with _raises(ValueError):
        store.register_audio(first["project_id"], "chapter-3", {**fingerprint, "duration_ms": 0})


def test_recovery_save_preserves_last_known_good_backup(tmp_path: Path) -> None:
    store = project_store.StoryProjectStore(tmp_path)
    project = store.create_project("Backup")
    project["autosave_revision"] = 1
    project = store.save_project(project)
    project["autosave_revision"] = 2
    project = store.save_project(project)
    primary = store.project_path(project["project_id"])
    primary.write_text("{broken", encoding="utf-8")

    recovered = store.load_project(project["project_id"])
    recovered["autosave_revision"] = 3
    store.save_project(recovered)
    primary.write_text("{broken again", encoding="utf-8")

    assert store.load_project(project["project_id"])["autosave_revision"] == 1


def test_project_document_references_reject_traversal_and_wrong_locations(tmp_path: Path) -> None:
    store = project_store.StoryProjectStore(tmp_path)
    project = store.create_project("References")
    chapter = project_models.new_chapter_manifest(
        "Chapter 1", {"path": "chapter.wav"}, chapter_id="chapter-1"
    )
    project["chapter_order"] = [chapter["chapter_id"]]
    project["chapters"] = {chapter["chapter_id"]: chapter}
    committed = store.commit_analysis_transaction(
        store.save_project(project),
        chapter["chapter_id"],
        {"summary": "analysis"},
        {"title": "bible"},
    )
    path = store.project_path(project["project_id"])

    for unsafe_reference in (
        "../outside.json",
        "./story_bible.1.json",
        str(tmp_path / "outside.json"),
        "chapters/chapter-1/analysis.1.json",
    ):
        unsafe_bible = copy.deepcopy(committed)
        unsafe_bible["story_bible_ref"] = unsafe_reference
        path.write_text(json.dumps(unsafe_bible), encoding="utf-8")
        with _raises(project_store.ProjectCorruptError):
            store.load_story_bible(project["project_id"])

    for unsafe_reference in (
        "../story_bible.1.json",
        "./chapters/chapter-1/analysis.1.json",
        str(tmp_path / "outside.json"),
        "story_bible.1.json",
        "chapters/other/analysis.1.json",
    ):
        unsafe_analysis = copy.deepcopy(committed)
        unsafe_analysis["chapters"][chapter["chapter_id"]]["stages"]["story_analysis"]["output_ref"] = (
            unsafe_reference
        )
        path.write_text(json.dumps(unsafe_analysis), encoding="utf-8")
        with _raises(project_store.ProjectCorruptError):
            store.load_chapter_document(project["project_id"], chapter["chapter_id"], "analysis")


def test_project_image_persistence_copies_provider_output_into_owned_chapter_path(
    tmp_path: Path,
) -> None:
    store = project_store.StoryProjectStore(tmp_path / "projects")
    project = project_models.new_project_manifest(
        "Owned images", project_id="owned-images", now=1.0
    )
    chapter = project_models.new_chapter_manifest(
        "Chapter 1", {}, chapter_id="chapter-1", now=1.0
    )
    project["chapters"]["chapter-1"] = chapter
    project["chapter_order"] = ["chapter-1"]
    store.save_project(project)
    provider_output = tmp_path / "provider-cache" / "temporary.png"
    provider_output.parent.mkdir(parents=True)
    provider_output.write_bytes(b"fake-generated-image")

    output_ref = store.persist_project_image(
        project["project_id"], "chapter-1", "scene-1", provider_output
    )

    owned_path = store.project_path(project["project_id"]).parent / output_ref
    assert output_ref == "chapters/chapter-1/images/scene-1.png"
    assert owned_path.is_file()
    assert owned_path.read_bytes() == b"fake-generated-image"
    assert provider_output.is_file()


def test_analysis_transactions_are_serialized_across_store_instances(tmp_path: Path) -> None:
    first_store = project_store.StoryProjectStore(tmp_path)
    second_store = project_store.StoryProjectStore(tmp_path.resolve())
    project = first_store.create_project("Concurrent stores")
    chapter = project_models.new_chapter_manifest(
        "Chapter 1", {"path": "chapter.wav"}, chapter_id="chapter-1"
    )
    project["chapter_order"] = [chapter["chapter_id"]]
    project["chapters"] = {chapter["chapter_id"]: chapter}
    baseline = first_store.save_project(project)
    first_staging = Event()
    release_first = Event()
    second_attempted = Event()
    second_finished = Event()
    results: dict[str, object] = {}
    original_write = project_store._atomic_write_json

    def block_first_story_bible(path: Path, payload, **kwargs) -> None:
        if path.name == "story_bible.1.json" and not first_staging.is_set():
            first_staging.set()
            assert release_first.wait(2.0)
        original_write(path, payload, **kwargs)

    def commit_first() -> None:
        try:
            results["first"] = first_store.commit_analysis_transaction(
                baseline,
                chapter["chapter_id"],
                {"summary": "first"},
                {"title": "first bible"},
            )
        except Exception as exc:
            results["first"] = exc

    def commit_second() -> None:
        second_attempted.set()
        try:
            results["second"] = second_store.commit_analysis_transaction(
                baseline,
                chapter["chapter_id"],
                {"summary": "second"},
                {"title": "second bible"},
            )
        except Exception as exc:
            results["second"] = exc
        finally:
            second_finished.set()

    project_store._atomic_write_json = block_first_story_bible
    first_thread = Thread(target=commit_first)
    second_thread = Thread(target=commit_second)
    try:
        first_thread.start()
        assert first_staging.wait(2.0)
        second_thread.start()
        assert second_attempted.wait(2.0)
        assert not second_finished.wait(0.1)
        release_first.set()
        first_thread.join(2.0)
        second_thread.join(2.0)
    finally:
        release_first.set()
        first_thread.join(2.0)
        second_thread.join(2.0)
        project_store._atomic_write_json = original_write

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert isinstance(results["first"], dict)
    assert isinstance(results["second"], project_store.ProjectConflictError)
    assert first_store.load_story_bible(project["project_id"]) == {"title": "first bible"}
    assert first_store.load_chapter_document(
        project["project_id"], chapter["chapter_id"], "analysis"
    ) == {"summary": "first"}


def test_document_recovery_save_preserves_last_known_good_backup(tmp_path: Path) -> None:
    store = project_store.StoryProjectStore(tmp_path)
    project = store.create_project("Document backup")
    project_id = project["project_id"]
    reference = store.save_chapter_document(project_id, "chapter-1", "transcript", 1, {"revision": 1})
    store.save_chapter_document(project_id, "chapter-1", "transcript", 1, {"revision": 2})
    primary = store.project_path(project_id).parent / reference
    primary.write_text("{broken", encoding="utf-8")

    recovered = store.load_chapter_document(project_id, "chapter-1", "transcript", revision=1)
    store.save_chapter_document(project_id, "chapter-1", "transcript", 1, recovered)
    primary.write_text("{broken again", encoding="utf-8")

    assert store.load_chapter_document(project_id, "chapter-1", "transcript", revision=1) == {
        "revision": 1
    }


def test_atomic_json_document_write_preserves_valid_backup_for_list_payloads(tmp_path: Path) -> None:
    path = tmp_path / "document.json"
    project_store._atomic_write_json(path, ["first"])
    project_store._atomic_write_json(path, ["second"])
    path.write_text("{broken", encoding="utf-8")

    project_store._atomic_write_json(path, ["recovered"])
    path.write_text("{broken again", encoding="utf-8")

    assert project_store._load_json_with_backup(path) == ["first"]


def test_autosave_coalesces_latest_pending_request_by_arrival() -> None:
    started, release = Event(), Event()
    saved, callbacks = [], []

    def save(snapshot: dict) -> dict:
        saved.append(snapshot)
        if snapshot["revision"] == 10:
            started.set()
            assert release.wait(1.0)
        return snapshot

    queue = project_autosave.ProjectAutosaveQueue(
        save=save,
        on_saved=callbacks.append,
        on_failed=lambda result: (_ for _ in ()).throw(AssertionError(result)),
    )
    try:
        queue.request(project_autosave.SaveRequest("p1", 10, {"revision": 10}))
        assert started.wait(1.0)
        queue.request(project_autosave.SaveRequest("p1", 2, {"revision": 2}))
        queue.request(project_autosave.SaveRequest("p1", 1, {"revision": 1}))
        release.set()
        assert queue.flush(1.0)
    finally:
        release.set()
        queue.shutdown(1.0)

    assert [snapshot["revision"] for snapshot in saved] == [10, 1]
    assert [snapshot["revision"] for snapshot in callbacks] == [10, 1]


def test_autosave_callback_can_enqueue_follow_up_save() -> None:
    saved = []

    def on_saved(result: dict) -> None:
        saved.append(result)
        if result["revision"] == 1:
            queue.request(project_autosave.SaveRequest("p1", 2, {"revision": 2}))

    queue = project_autosave.ProjectAutosaveQueue(
        save=lambda snapshot: snapshot,
        on_saved=on_saved,
        on_failed=lambda result: (_ for _ in ()).throw(AssertionError(result)),
    )
    try:
        queue.request(project_autosave.SaveRequest("p1", 1, {"revision": 1}))
        assert queue.flush(1.0)
    finally:
        queue.shutdown(1.0)

    assert [snapshot["revision"] for snapshot in saved] == [1, 2]


def test_autosave_flush_waits_while_save_is_active() -> None:
    started, release = Event(), Event()

    def save(snapshot: dict) -> dict:
        started.set()
        assert release.wait(1.0)
        return snapshot

    queue = project_autosave.ProjectAutosaveQueue(
        save=save,
        on_saved=lambda _result: None,
        on_failed=lambda result: (_ for _ in ()).throw(AssertionError(result)),
    )
    try:
        queue.request(project_autosave.SaveRequest("p1", 1, {"revision": 1}))
        assert started.wait(1.0)
        assert not queue.flush(0.01)
        release.set()
        assert queue.flush(1.0)
    finally:
        release.set()
        queue.shutdown(1.0)


def test_autosave_shutdown_drains_accepted_work_and_rejects_new_requests() -> None:
    started, release = Event(), Event()
    saved = []

    def save(snapshot: dict) -> dict:
        saved.append(snapshot)
        if snapshot["revision"] == 1:
            started.set()
            assert release.wait(1.0)
        return snapshot

    queue = project_autosave.ProjectAutosaveQueue(
        save=save,
        on_saved=lambda _result: None,
        on_failed=lambda result: (_ for _ in ()).throw(AssertionError(result)),
    )
    try:
        queue.request(project_autosave.SaveRequest("p1", 1, {"revision": 1}))
        assert started.wait(1.0)
        queue.request(project_autosave.SaveRequest("p1", 2, {"revision": 2}))
        queue.shutdown(0.01)
        with _raises(RuntimeError):
            queue.request(project_autosave.SaveRequest("p1", 3, {"revision": 3}))
        release.set()
        assert queue.flush(1.0)
    finally:
        release.set()
        queue.shutdown(1.0)

    assert [snapshot["revision"] for snapshot in saved] == [1, 2]


def test_worker_result_requires_matching_project_generation_and_input() -> None:
    result = {"project_id": "p1", "generation_id": 4, "input_fingerprint": "abc"}
    assert project_autosave.result_is_current(
        result, project_id="p1", generation_id=4, input_fingerprint="abc"
    )
    assert not project_autosave.result_is_current(
        result, project_id="p2", generation_id=4, input_fingerprint="abc"
    )
    assert not project_autosave.result_is_current(
        {**result, "project_id": ""}, project_id="p1", generation_id=4, input_fingerprint="abc"
    )
    assert not project_autosave.result_is_current(
        {**result, "generation_id": None}, project_id="p1", generation_id=4, input_fingerprint="abc"
    )
    assert not project_autosave.result_is_current(
        {**result, "input_fingerprint": ""},
        project_id="p1",
        generation_id=4,
        input_fingerprint="abc",
    )
    assert not project_autosave.result_is_current(
        {**result, "generation_id": 5}, project_id="p1", generation_id=4, input_fingerprint="abc"
    )
    assert not project_autosave.result_is_current(
        {**result, "input_fingerprint": "different"},
        project_id="p1",
        generation_id=4,
        input_fingerprint="abc",
    )
    assert not project_autosave.result_is_current(
        {**result, "generation_id": True}, project_id="p1", generation_id=1, input_fingerprint="abc"
    )


def _project_with_two_chapters(*, completed: bool) -> dict:
    project = project_models.new_project_manifest("Series", project_id="p1", now=1.0)
    for index, chapter_id in enumerate(("c1", "c2"), start=1):
        chapter = project_models.new_chapter_manifest(
            f"Chapter {index}",
            {
                "path": f"chapter_{index}.wav",
                "fingerprint": {
                    "algorithm": "sha256-sampled-v1",
                    "digest": f"digest-{index}",
                    "size_bytes": 100 + index,
                    "duration_ms": 10000,
                },
            },
            chapter_id=chapter_id,
            now=float(index),
        )
        if completed:
            for stage in project_models.STAGES:
                chapter["stages"][stage]["status"] = "completed"
        project["chapters"][chapter_id] = chapter
        project["chapter_order"].append(chapter_id)
    return project


def _mark_checkpoint_reusable(checkpoint: dict, fingerprint: str = "input") -> None:
    checkpoint["status"] = "completed"
    checkpoint["input_fingerprint"] = fingerprint
    checkpoint["expected_input_fingerprint"] = fingerprint


def test_checkpoint_transitions_fingerprint_and_attempt_history() -> None:
    checkpoint = project_models.checkpoint("transcription", "c1")
    assert checkpointing.settings_fingerprint({"b": [2, 1], "a": "å"}) == checkpointing.settings_fingerprint(
        {"a": "å", "b": [2, 1]}
    )

    started = checkpointing.start_checkpoint(
        checkpoint,
        input_fingerprint="input-1",
        now=10.0,
        provider="local",
        model="test-model",
    )
    assert checkpoint["status"] == "pending"
    assert started["status"] == "running"
    assert started["attempt_count"] == 1
    assert started["started_at"] == 10.0
    assert started["provider"] == "local"
    completed = checkpointing.complete_checkpoint(
        started, output_ref="chapters/c1/transcript.1.json", output_fingerprint="output-1", now=11.0
    )
    assert completed["status"] == "completed"
    assert completed["completed_at"] == 11.0
    with _raises(checkpointing.CheckpointTransitionError):
        checkpointing.complete_checkpoint(checkpoint, output_ref="", output_fingerprint="")

    restarted = checkpointing.start_checkpoint(
        {**completed, "status": "failed"}, input_fingerprint="input-2"
    )
    assert restarted["attempt_count"] == 2
    failed = checkpointing.fail_checkpoint(restarted, error="offline", now=12.0)
    assert failed["status"] == "failed"
    assert failed["error"] == "offline"


def test_recovery_and_resume_skip_completed_work() -> None:
    project = _project_with_two_chapters(completed=False)
    chapter = project["chapters"]["c1"]
    for stage in ("audio_validation", "transcription", "transcript_combination"):
        _mark_checkpoint_reusable(chapter["stages"][stage], fingerprint=stage)
    project["chapters"]["c1"]["stages"]["story_analysis"]["status"] = "running"

    recovered, changed = checkpointing.recover_interrupted(project)

    assert changed
    assert project["chapters"]["c1"]["stages"]["story_analysis"]["status"] == "running"
    assert recovered["chapters"]["c1"]["stages"]["story_analysis"]["status"] == "interrupted"
    plan = checkpointing.build_resume_plan(recovered)
    assert plan[0] == {"chapter_id": "c1", "stage": "story_analysis", "unit_id": "c1"}
    assert plan[1] == {"chapter_id": "c2", "stage": "audio_validation", "unit_id": "c2"}


def test_earlier_analysis_change_stales_later_continuity_not_transcript() -> None:
    project = _project_with_two_chapters(completed=True)

    changed = checkpointing.invalidate_project(
        project, chapter_id="c1", from_stage="story_analysis", include_later_chapters=True
    )

    assert project["chapters"]["c1"]["stages"]["story_analysis"]["status"] == "completed"
    assert changed["chapters"]["c1"]["stages"]["story_analysis"]["status"] == "stale"
    assert changed["chapters"]["c2"]["stages"]["transcription"]["status"] == "completed"
    assert changed["chapters"]["c2"]["stages"]["story_analysis"]["status"] == "stale"
    assert changed["chapters"]["c2"]["stages"]["image_generation"]["status"] == "stale"


def test_committed_story_bible_merge_is_defensive_and_confidence_aware() -> None:
    existing = {
        "characters": {
            "hero": {
                "display_name": "Hero",
                "aliases": ["the traveler"],
                "visual_identity": "weathered face and a dark wool coat",
                "confidence": 0.8,
            }
        }
    }
    chapter_update = {
        "characters": {
            "hero": {
                "display_name": "Unknown",
                "aliases": ["the traveler", "Captain"],
                "visual_identity": "a red coat",
                "confidence": 0.6,
            },
            "guide": {
                "display_name": "Guide",
                "aliases": ["Guide"],
                "confidence": 0.7,
            },
        }
    }
    existing_before = copy.deepcopy(existing)
    update_before = copy.deepcopy(chapter_update)

    merged = story_memory.merge_committed_story_bible(existing, chapter_update)

    assert existing == existing_before
    assert chapter_update == update_before
    assert merged["characters"]["hero"]["display_name"] == "Hero"
    assert merged["characters"]["hero"]["visual_identity"] == (
        "weathered face and a dark wool coat"
    )
    assert merged["characters"]["hero"]["aliases"] == ["the traveler", "Captain"]
    assert merged["characters"]["guide"]["display_name"] == "Guide"

    refined = story_memory.merge_committed_story_bible(
        merged,
        {
            "characters": {
                "hero": {
                    "display_name": "Hero",
                    "visual_identity": (
                        "weathered face, dark wool coat, and a silver compass brooch"
                    ),
                    "confidence": 1.0,
                }
            }
        },
    )
    assert refined["characters"]["hero"]["visual_identity"].endswith(
        "silver compass brooch"
    )


def test_resume_uses_scene_image_work_and_rejects_changed_expected_input() -> None:
    project = _project_with_two_chapters(completed=True)
    chapter = project["chapters"]["c1"]
    for stage in project_models.STAGES:
        _mark_checkpoint_reusable(chapter["stages"][stage], fingerprint=stage)
    chapter["stages"]["image_generation"]["expected_input_fingerprint"] = "new-image-input"
    chapter["stages"]["image_generation"]["input_fingerprint"] = "old-image-input"
    chapter["scene_checkpoints"] = {
        "scene-1": {
            "stage": "image_generation",
            "unit_id": "scene-1",
            "status": "pending",
        }
    }

    plan = checkpointing.build_resume_plan(project)

    assert plan[0] == {"chapter_id": "c1", "stage": "image_generation", "unit_id": "scene-1"}


def test_resume_requires_a_nonempty_matching_expected_input_fingerprint() -> None:
    project = _project_with_two_chapters(completed=False)
    chapter = project["chapters"]["c1"]
    for stage in project_models.STAGES:
        _mark_checkpoint_reusable(chapter["stages"][stage], fingerprint=stage)
    checkpoint = chapter["stages"]["audio_validation"]
    checkpoint.pop("expected_input_fingerprint")

    assert checkpointing.build_resume_plan(project)[0] == {
        "chapter_id": "c1",
        "stage": "audio_validation",
        "unit_id": "c1",
    }

    checkpoint["expected_input_fingerprint"] = ""
    assert checkpointing.build_resume_plan(project)[0]["chapter_id"] == "c1"

    checkpoint["expected_input_fingerprint"] = "audio_validation"
    assert checkpointing.build_resume_plan(project)[0] == {
        "chapter_id": "c2",
        "stage": "audio_validation",
        "unit_id": "c2",
    }


def test_resume_does_not_emit_or_bypass_missing_audio() -> None:
    project = _project_with_two_chapters(completed=False)
    project["chapters"]["c1"]["stages"]["audio_validation"]["status"] = "missing_audio"

    assert checkpointing.build_resume_plan(project) == [
        {"chapter_id": "c2", "stage": "audio_validation", "unit_id": "c2"}
    ]


def test_manifest_save_is_project_locked_and_rejects_stale_snapshots(tmp_path: Path) -> None:
    store = project_store.StoryProjectStore(tmp_path)
    created = store.create_project("Original")
    first = copy.deepcopy(created)
    second = copy.deepcopy(created)
    first["name"] = "First"
    second["name"] = "Second"
    start = Barrier(2)
    outcomes: list[object] = []

    def save(snapshot: dict) -> None:
        start.wait()
        try:
            outcomes.append(store.save_project(snapshot))
        except Exception as exc:
            outcomes.append(exc)

    threads = [Thread(target=save, args=(first,)), Thread(target=save, args=(second,))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(3.0)

    assert all(not thread.is_alive() for thread in threads)
    assert len([item for item in outcomes if isinstance(item, dict)]) == 1
    assert len(
        [item for item in outcomes if isinstance(item, project_store.ProjectConflictError)]
    ) == 1
    persisted = store.load_project(created["project_id"])
    assert persisted["name"] in {"First", "Second"}
    assert persisted["manifest_revision"] == created["manifest_revision"] + 1


def test_chapter_rename_and_order_mutations_invalidate_only_derived_continuity(
    tmp_path: Path,
) -> None:
    manager = _manager_with_fake_fingerprints(tmp_path)
    manager.create("Series")
    project = manager.commit_import(
        manager.review_import(["good.wav", "different.wav"]), valid_only=False
    )
    first_id, second_id = project["chapter_order"]
    for chapter_id in (first_id, second_id):
        for stage in project_models.STAGES:
            checkpoint = project["chapters"][chapter_id]["stages"][stage]
            checkpoint.update(
                {
                    "status": "completed",
                    "input_fingerprint": stage,
                    "expected_input_fingerprint": stage,
                    "output_fingerprint": stage,
                    "output_ref": f"{stage}.json",
                }
            )
        project["chapters"][chapter_id]["scene_checkpoints"] = {
            f"scene-{chapter_id}": {
                **project_models.checkpoint("image_generation", f"scene-{chapter_id}"),
                "status": "completed",
                "input_fingerprint": "image",
                "expected_input_fingerprint": "image",
                "output_fingerprint": "image",
                "output_ref": "image.png",
            }
        }
    manager._select(manager.store.save_project(project))

    renamed = manager.rename_chapter(first_id, "Opening Chapter")
    assert renamed["chapters"][first_id]["display_name"] == "Opening Chapter"
    assert renamed["chapters"][first_id]["stages"]["story_analysis"]["status"] == "completed"

    reordered = manager.reorder_chapters([second_id, first_id])
    for chapter_id in (second_id, first_id):
        stages = reordered["chapters"][chapter_id]["stages"]
        assert stages["transcription"]["status"] == "completed"
        assert stages["transcript_combination"]["status"] == "completed"
        assert stages["story_analysis"]["status"] == "stale"
        assert stages["scene_planning"]["status"] == "stale"
        assert stages["image_generation"]["status"] == "stale"
        assert all(
            item["status"] == "stale"
            for item in reordered["chapters"][chapter_id]["scene_checkpoints"].values()
        )

    reset = copy.deepcopy(reordered)
    for chapter_id in (second_id, first_id):
        for stage in project_models.STAGES:
            checkpoint = reset["chapters"][chapter_id]["stages"][stage]
            checkpoint.update(
                {
                    "status": "completed",
                    "input_fingerprint": stage,
                    "expected_input_fingerprint": stage,
                    "output_fingerprint": stage,
                    "output_ref": f"{stage}.json",
                }
            )
        for checkpoint in reset["chapters"][chapter_id]["scene_checkpoints"].values():
            checkpoint.update(
                {
                    "status": "completed",
                    "input_fingerprint": "image",
                    "expected_input_fingerprint": "image",
                    "output_fingerprint": "image",
                    "output_ref": "image.png",
                }
            )
    manager._select(manager.store.save_project(reset))
    restored_order = [second_id, first_id]
    archived = manager.archive_chapter(second_id)
    assert archived["chapter_order"] == [first_id]
    assert archived["chapters"][first_id]["stages"]["transcription"]["status"] == "completed"
    assert archived["chapters"][first_id]["stages"]["story_analysis"]["status"] == "stale"
    restored = manager.restore_chapter(second_id)
    assert restored["chapter_order"] == [first_id, second_id]
    assert restored["chapters"][second_id]["stages"]["story_analysis"]["status"] == "stale"
    assert restored_order != restored["chapter_order"]


def test_legacy_migration_materializes_project_documents_and_story_bible(
    tmp_path: Path,
) -> None:
    manager = _manager_with_fake_fingerprints(tmp_path)
    source = {
        "audio_story_mode_audio_paths": ["good.wav", "broken.wav"],
        "audio_story_mode_transcript_chunks": [{"text": "Once upon a time."}],
        "audio_story_mode_full_transcript_text": "Once upon a time.",
        "audio_story_mode_raw_transcript_segments": [{"text": "Once upon a time."}],
        "audio_story_mode_scene_plan": [{"scene_id": "opening", "summary": "Arrival"}],
        "audio_story_mode_story_bible": {"summary": "A continuing tale"},
        "audio_story_mode_scene_overrides": {"pinned_character_ids": ["hero"]},
    }
    original = copy.deepcopy(source)
    migrated = manager.commit_legacy_migration(
        manager.prepare_legacy_migration(source, "Migrated")
    )

    assert source == original
    assert migrated["legacy_session_payload"] == original
    assert migrated["story_bible_revision"] == 1
    assert manager.store.load_story_bible(migrated["project_id"])["summary"] == "A continuing tale"
    owner_id = migrated["legacy_artifact_chapter_id"]
    transcript = manager.store.load_chapter_document(
        migrated["project_id"], owner_id, "transcript", 1
    )
    analysis = manager.store.load_chapter_document(
        migrated["project_id"], owner_id, "analysis", 1
    )
    assert transcript["full_text"] == "Once upon a time."
    assert analysis["scene_plan"][0]["scene_id"] == "opening"
    reopened = manager.open(migrated["project_id"])
    assert reopened["chapters"][owner_id]["stages"]["audio_validation"]["status"] == "completed"
    assert reopened["chapters"][owner_id]["stages"]["transcription"]["status"] == "completed"
    missing = next(
        chapter
        for chapter in reopened["chapters"].values()
        if chapter["audio_reference"]["path"] == "broken.wav"
    )
    assert missing["stages"]["audio_validation"]["status"] == "missing_audio"


def test_project_image_attempts_are_versioned_and_failed_replacement_keeps_previous(
    tmp_path: Path,
) -> None:
    store = project_store.StoryProjectStore(tmp_path / "projects")
    project = store.create_project("Images")
    chapter = project_models.new_chapter_manifest(
        "Chapter", {"path": "chapter.wav", "fingerprint": {}}
    )
    project["chapters"][chapter["chapter_id"]] = chapter
    project["chapter_order"] = [chapter["chapter_id"]]
    store.save_project(project)
    first_source = tmp_path / "first.png"
    second_source = tmp_path / "second.png"
    first_source.write_bytes(b"first-image")
    second_source.write_bytes(b"second-image")

    first = store.persist_project_image_attempt(
        project["project_id"], chapter["chapter_id"], "scene-1", first_source, "attempt-1"
    )
    second = store.persist_project_image_attempt(
        project["project_id"], chapter["chapter_id"], "scene-1", second_source, "attempt-2"
    )

    assert first["output_ref"] != second["output_ref"]
    first_path = store.resolve_project_image(
        project["project_id"], chapter["chapter_id"], first["output_ref"]
    )
    assert first_path.read_bytes() == b"first-image"
    assert second["output_fingerprint"] != first["output_fingerprint"]
    with _raises(FileNotFoundError):
        store.persist_project_image_attempt(
            project["project_id"], chapter["chapter_id"], "scene-1", tmp_path / "missing.png", "attempt-3"
        )
    assert first_path.read_bytes() == b"first-image"


def test_backup_load_is_observable_read_only_and_repair_is_explicit(tmp_path: Path) -> None:
    store = project_store.StoryProjectStore(tmp_path)
    created = store.create_project("Recover")
    updated = copy.deepcopy(created)
    updated["name"] = "Recovered Name"
    saved = store.save_project(updated)
    primary = store.project_path(saved["project_id"])
    primary.write_text("{broken", encoding="utf-8")
    before = primary.read_bytes()

    recovered, used_backup = store.load_project_with_recovery(saved["project_id"])

    assert used_backup is True
    assert recovered["name"] == "Recover"
    assert primary.read_bytes() == before
    assert store.repair_project_primary(saved["project_id"], recovered["manifest_revision"])
    repaired, used_backup = store.load_project_with_recovery(saved["project_id"])
    assert not used_backup
    assert repaired["manifest_revision"] == recovered["manifest_revision"]


def test_autosave_rebases_only_queued_descendant_after_successful_cas(
    tmp_path: Path,
) -> None:
    store = project_store.StoryProjectStore(tmp_path)
    created = store.create_project("Autosave CAS")
    first = copy.deepcopy(created)
    first["autosave_revision"] = 1
    second = copy.deepcopy(created)
    second["autosave_revision"] = 2
    save_started = Event()
    release_save = Event()
    saved: list[dict] = []
    failed: list[dict] = []

    def save(snapshot: dict) -> dict:
        if int(snapshot.get("autosave_revision", 0) or 0) == 1:
            save_started.set()
            assert release_save.wait(2.0)
        return store.save_project(snapshot)

    queue_service = project_autosave.ProjectAutosaveQueue(save, saved.append, failed.append)
    try:
        queue_service.request(project_autosave.SaveRequest(created["project_id"], 1, first))
        assert save_started.wait(1.0)
        queue_service.request(project_autosave.SaveRequest(created["project_id"], 2, second))
        release_save.set()
        assert queue_service.flush(2.0)
    finally:
        release_save.set()
        queue_service.shutdown(1.0)

    assert failed == []
    assert [item["autosave_revision"] for item in saved] == [1, 2]
    persisted = store.load_project(created["project_id"])
    assert persisted["autosave_revision"] == 2
    assert persisted["manifest_revision"] == created["manifest_revision"] + 2


def test_controller_partial_import_requires_explicit_valid_only_confirmation() -> None:
    _app, controller = _session_controller()
    review = {
        "valid": [{"path": "good.wav"}],
        "invalid": [{"path": "bad.wav", "error": "broken"}],
        "conflicts": [],
    }
    calls: list[str] = []

    assert controller._valid_only_import_decision(
        review, lambda: calls.append("cancel") or False
    ) is None
    assert calls == ["cancel"]
    assert controller._valid_only_import_decision(
        review, lambda: calls.append("confirm") or True
    ) is True
    assert calls == ["cancel", "confirm"]
    assert controller._valid_only_import_decision(
        {**review, "invalid": []}, lambda: (_ for _ in ()).throw(AssertionError())
    ) is False
    assert controller._valid_only_import_decision(
        {**review, "conflicts": [{"path": "dup.wav"}]}, lambda: True
    ) is None
    controller.shutdown()


def test_controller_project_pipeline_owner_rejects_overlap_and_releases_exact_owner() -> None:
    _app, controller = _session_controller()
    controller.current_story_project_id = "project-1"
    statuses: list[str] = []
    controller._set_status = statuses.append

    transcription_owner = controller._begin_story_project_mutating_pipeline("transcription")
    assert transcription_owner
    assert controller._begin_story_project_mutating_pipeline("image generation") is None
    assert "transcription" in statuses[-1].lower()
    controller._end_story_project_mutating_pipeline("not-the-owner")
    assert controller._story_project_mutating_pipeline_owner["token"] == transcription_owner
    controller._end_story_project_mutating_pipeline(transcription_owner)
    assert controller._story_project_mutating_pipeline_owner is None
    assert controller._begin_story_project_mutating_pipeline("image generation")
    controller.shutdown()


def test_controller_story_analysis_rebuild_respects_project_pipeline_owner() -> None:
    _app, controller = _session_controller()
    controller_module = importlib.import_module("addons.audio_story_mode.controller")
    controller.current_story_project_id = "project-1"
    controller._raw_transcript_segments = [{"text": "chapter"}]
    controller._last_transcription_audio_duration = 1.0
    controller._set_status = lambda _message: None
    transcription_owner = controller._begin_story_project_mutating_pipeline(
        "transcription"
    )
    before_job = controller._transcription_job_id
    controller._start_story_payload_rebuild_job()
    assert controller._transcription_job_id == before_job

    controller._end_story_project_mutating_pipeline(transcription_owner)
    started: list[bool] = []

    class CapturedThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            started.append(True)

    original_thread = controller_module.threading.Thread
    controller_module.threading.Thread = CapturedThread
    try:
        controller._start_story_payload_rebuild_job()
        assert started == [True]
        assert controller._analysis_project_pipeline_owner
        assert controller._story_project_mutating_pipeline_owner["label"] == "story analysis"
    finally:
        controller_module.threading.Thread = original_thread
        controller._end_story_project_mutating_pipeline(
            controller._analysis_project_pipeline_owner
        )
        controller.shutdown()


def test_project_ui_exposes_chapter_rename_and_persisted_order_controls() -> None:
    ui_path = Path(__file__).with_name("ui") / "audio_story_mode.ui"
    names = {
        element.attrib.get("name", "")
        for element in ET.parse(ui_path).iter("widget")
    }
    assert {
        "audio_story_project_chapter_rename_button",
        "audio_story_project_chapter_move_up_button",
        "audio_story_project_chapter_move_down_button",
    }.issubset(names)


def test_controller_chapter_moves_use_persisted_project_order() -> None:
    _app, controller = _session_controller()
    controller.current_story_project_id = "ordered-project"
    controller._current_story_project = {
        "project_id": "ordered-project",
        "chapter_order": ["chapter-a", "chapter-b", "chapter-c"],
        "chapters": {},
    }
    controller.imported_audio_paths = ["transient-c.wav", "transient-a.wav"]
    controller._selected_story_project_chapter = lambda: {
        "chapter_id": "chapter-b",
        "archived": False,
    }
    requested: list[list[str]] = []
    controller._story_project_manager.reorder_chapters = (
        lambda order: requested.append(list(order)) or controller._current_story_project
    )
    controller._run_story_project_mutation = (
        lambda _operation, mutation: mutation()
    )

    controller._move_story_project_chapter_up()
    controller._move_story_project_chapter_down()

    assert requested == [
        ["chapter-b", "chapter-a", "chapter-c"],
        ["chapter-a", "chapter-c", "chapter-b"],
    ]
    controller.shutdown()


def test_controller_schedules_backup_repair_only_after_visible_open() -> None:
    _app, controller = _session_controller()
    project = project_models.new_project_manifest("Recovered", project_id="recover-1")
    events: list[str] = []
    controller._story_project_input_fingerprint = "owned-open"
    controller._apply_open_story_project = (
        lambda *_args, **_kwargs: events.append("visible-open")
    )
    controller._schedule_story_project_recovery_repair = (
        lambda value: events.append(f"repair:{value['project_id']}")
    )
    controller._set_story_project_autosave_text = lambda _text: None
    controller._set_status = lambda text: events.append(
        "visible-recovery-status"
        if "recovery backup" in str(text).lower()
        else "other-status"
    )

    controller._on_story_project_job_finished(
        {
            "operation": "open",
            "project_id": project["project_id"],
            "generation_id": controller._story_project_generation,
            "input_fingerprint": "owned-open",
            "result": {
                "project": project,
                "recovery_changed": False,
                "backup_recovered": True,
            },
        }
    )

    assert events[-3:] == [
        "visible-open",
        "visible-recovery-status",
        "repair:recover-1",
    ]
    controller.shutdown()


def main() -> int:
    tests = [
        test
        for name, test in sorted(globals().items())
        if name.startswith("test_") and callable(test)
    ]
    failures = 0
    for test in tests:
        try:
            parameters = tuple(inspect.signature(test).parameters)
            if parameters == ("tmp_path",):
                with tempfile.TemporaryDirectory() as directory:
                    test(Path(directory))
            elif not parameters:
                test()
            else:
                raise AssertionError(f"Unsupported smoke fixture(s): {', '.join(parameters)}")
        except Exception as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc}")
        else:
            print(f"PASS {test.__name__}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
