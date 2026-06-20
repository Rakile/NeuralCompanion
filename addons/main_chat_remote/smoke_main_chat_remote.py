from __future__ import annotations

import json
import base64
import contextlib
import io
import os
import shutil
import socket
import struct
import tempfile
import threading
import time
import urllib.request
import wave
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import addons.main_chat_remote.remote_backend as remote_backend_module
from addons.main_chat_remote.backend_process import (
    BackendProcessSupervisor,
    generate_pairing_code,
    normalize_pairing_code as normalize_supervisor_pairing_code,
)
from addons.main_chat_remote.controller import (
    BridgeSettings,
    MainChatBridgeServer,
    MainChatRemoteController,
    free_local_port,
    redact_sensitive_query_values as redact_bridge_sensitive_query_values,
)
from addons.main_chat_remote.media_bridge import MainChatMediaBridge
from addons.main_chat_remote.remote_backend import (
    BridgeClient,
    MainChatRemoteBackend,
    normalize_pairing_code as normalize_remote_pairing_code,
    redact_sensitive_query_values,
)
from addons.main_chat_remote.scripts import backend_venv
from core.addons.manager import AddonManager


class _Logger:
    def info(self, *_args):
        return None

    def warning(self, *_args):
        return None

    def debug(self, *_args):
        return None


class _Snapshot:
    def __init__(self, payload):
        self._payload = dict(payload)

    def snapshot(self):
        return dict(self._payload)


class _RuntimeStatus:
    def snapshot(self):
        return {"running": True, "chat_provider": "smoke", "model_name": "smoke-model"}

    def status_line(self):
        return "runtime: running | smoke"


class _RuntimeControls:
    def __init__(self):
        self.last_action = ""

    def snapshot(self):
        return {"actions": ["pause_speech", "skip_speech", "replay_last_assistant"], "last_action": self.last_action}

    def trigger(self, action):
        self.last_action = str(action or "")
        return {"accepted": True, "action": self.last_action}


class _EngineLifecycle:
    def snapshot(self):
        return {"running": True, "engine_connected": True}

    def start_engine(self):
        return self.snapshot()

    def stop_engine(self):
        return {"running": False, "engine_connected": False}


class _ChatReplay:
    def snapshot_chat_session(self):
        return {
            "version": 1,
            "saved_at": 1.0,
            "conversation_history": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ],
        }

    def replayable_chat_entries(self):
        return [{"replay_index": 1, "role": "assistant", "content": "hi", "preview": "Assistant: hi"}]


class _RuntimeConfig:
    def snapshot(self):
        return {
            "chat_provider": "smoke-llm",
            "model_name": "smoke-model",
            "stt_backend": "smoke-stt",
            "stt_model_size": "tiny",
            "tts_backend": "smoke-tts",
            "visual_reply_provider": "smoke-visual",
        }

    def engine_attr(self, name, default=None):
        if str(name) == "transcribe_file_with_stt":
            return lambda _path, language=None: ((), {"text": "transcribed smoke"})
        return default


class _VisualReply:
    def __init__(self):
        self.requests = []
        self.visible = False
        self.clear_count = 0

    def settings_snapshot(self):
        return {"mode_value": "auto", "provider_value": "smoke", "size_value": "1024x1024"}

    def request_generation(self, **kwargs):
        self.requests.append(dict(kwargs))
        return {"accepted": True, "request_id": "smoke_visual"}

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def clear(self, **_kwargs):
        self.clear_count += 1
        return True


class _AddonCapabilities:
    def __init__(self):
        self.calls = []

    def invoke(self, capability, payload=None):
        name = str(capability or "")
        data = dict(payload or {})
        self.calls.append((name, data))
        if name == "mprc.remote_state":
            return {
                "schema_version": 1,
                "session": {
                    "enabled": True,
                    "mode": "story",
                    "turn_index": 3,
                    "scene_title": "Smoke Scene",
                    "location": "Bridge Test",
                    "mood": "focused",
                    "objective": "Keep the phone story panel current.",
                },
                "personas": [
                    {
                        "id": "narrator",
                        "display_name": "Narrator",
                        "role": "narrator",
                        "enabled": True,
                        "active": True,
                        "current_speaker": False,
                        "narrator": True,
                        "voice_enabled": True,
                        "visual_enabled": False,
                    },
                    {
                        "id": "guide",
                        "display_name": "Guide",
                        "role": "support",
                        "enabled": True,
                        "active": False,
                        "current_speaker": True,
                        "narrator": False,
                        "voice_enabled": True,
                        "visual_enabled": True,
                    },
                ],
                "latest_reply": "[NARRATOR] The bridge lights up.\n[CHARACTER: Guide] We can see the phone now.",
                "segments": [
                    {"segment_id": 1, "speaker_name": "Narrator", "role": "narrator", "text": "The bridge lights up."},
                    {"segment_id": 2, "speaker_name": "Guide", "role": "character", "text": "We can see the phone now."},
                ],
                "choices": [{"id": "1", "text": "Check the story panel."}],
                "speech_audio": {"available": True, "items": []},
                "audio_cues": [],
                "memory": {
                    "available": True,
                    "backend": "sqlite",
                    "configured_backend": "sqlite",
                    "database_available": True,
                    "database_status": "ready",
                    "databank_available": True,
                    "configured_databank_source_count": 1,
                    "indexed_databank_source_count": 1,
                    "event_count": 5,
                    "chapter_count": 2,
                    "pinned_fact_count": 1,
                    "character_memory_count": 2,
                    "location_memory_count": 1,
                    "fallback_note": "",
                },
                "cast": {
                    "available": True,
                    "dependency_error": "",
                    "devices": [{"name": "Living Room TV", "label": "Living Room TV (Cast)"}],
                    "selected_device": "Living Room TV",
                    "active_device": "",
                    "casting": False,
                    "busy": False,
                    "status": "Found 1 Chromecast device(s).",
                    "stream": {"running": False, "url": "", "port": 8766},
                },
                "visual": {
                    "latest_prompt": "Guide watches the phone story panel update, focused mood.",
                    "last_visual_reply_at": 12.0,
                    "auto_image_count": 1,
                },
            }
        if name == "mprc.remote_send":
            return {"accepted": True, "message": "MPRC text queued.", "text": data.get("text")}
        if name == "mprc.remote_choice":
            return {"accepted": True, "message": "MPRC choice queued.", "choice": data.get("choice")}
        if name in {"mprc.remote_play", "mprc.remote_pause", "mprc.remote_visual"}:
            return {"accepted": True, "message": f"{name} queued."}
        if name == "mprc.remote_cast":
            return {
                "accepted": True,
                "message": "Cast action queued.",
                "cast": {
                    "available": True,
                    "selected_device": str(data.get("device_name") or ""),
                    "active_device": str(data.get("device_name") or ""),
                    "casting": str(data.get("action") or "") == "start",
                    "busy": False,
                    "status": "Cast action queued.",
                    "stream": {"running": True, "url": "http://127.0.0.1:8766/", "port": 8766},
                },
            }
        return None


class _Shell:
    def __init__(self):
        self.sent = []

    def send_typed_chat_message(self, text=None):
        self.sent.append(str(text or ""))
        return True


class _Context:
    def __init__(self, root: Path):
        self.app_root = root
        self.logger = _Logger()
        self.llm = _Snapshot({"provider": "smoke"})
        self.tts = _Snapshot({"backend": "smoke-tts"})
        self.avatar = _Snapshot({"avatar_engine": "none"})
        self._services = {
            "qt.shell": _Shell(),
            "qt.runtime_status": _RuntimeStatus(),
            "qt.runtime_controls": _RuntimeControls(),
            "qt.engine_lifecycle": _EngineLifecycle(),
            "qt.chat_replay": _ChatReplay(),
            "qt.runtime_config": _RuntimeConfig(),
            "qt.visual_reply": _VisualReply(),
            "addons.capabilities": _AddonCapabilities(),
        }

    def get_service(self, name, default=None):
        return self._services.get(str(name), default)


def _copy_manager_smoke_addon(app_root: Path) -> None:
    source_dir = ROOT / "addons" / "main_chat_remote"
    target_dir = app_root / "addons" / "main_chat_remote"
    target_dir.mkdir(parents=True, exist_ok=True)
    for file_name in ("addon.json", "main.py"):
        shutil.copy2(source_dir / file_name, target_dir / file_name)


def _addon_manager_smoke(root: Path) -> None:
    main_source = (ROOT / "addons" / "main_chat_remote" / "main.py").read_text(encoding="utf-8")
    assert "context.ui.register_manifest_tab(" in main_source
    assert "context.ui.register_tab(" not in main_source
    app_root = root / "manager_app"
    _copy_manager_smoke_addon(app_root)
    host = _Context(app_root)
    manager = AddonManager(
        app_root=app_root,
        llm_snapshot_getter=lambda: {"provider": "smoke"},
        tts_snapshot_getter=lambda: {"backend": "smoke-tts"},
        avatar_snapshot_getter=lambda: {"avatar_engine": "none"},
        host_services=dict(host._services),
    )
    records = manager.discover()
    assert len(records) == 1
    assert records[0].manifest.id == "nc.main_chat_remote"
    assert manager.get_addon_id_for_service("service_registry", service_name="main_chat.remote") == ""
    manager.initialize_all()
    record = manager.get_addon_record("nc.main_chat_remote")
    assert record is not None
    assert record.state == "initialized", record.error
    assert manager.get_addon_id_for_service("service_registry", service_name="main_chat.remote") == "nc.main_chat_remote"
    contributions = manager.get_tab_contributions("top_level")
    assert len(contributions) == 1
    contribution = contributions[0]
    assert contribution.id == "main_chat_remote_tab"
    assert contribution.title == "Main Chat Remote"
    assert contribution.order == 930
    assert contribution.metadata.get("runtime_role") == "main_chat_remote"
    service = manager.get_registered_service("main_chat.remote")
    assert isinstance(service, MainChatRemoteController)
    status = manager.invoke_addon_capability("nc.main_chat_remote", "main_chat_remote.status")
    assert status["bridge"]["running"] is False
    assert status["backend"]["running"] is False
    assert status["backend"]["venv_python"].endswith("nc_phone_remote\\Scripts\\python.exe") or status["backend"]["venv_python"].endswith("nc_phone_remote/bin/python")
    assert "main_chat_remote" in manager.export_session_state()
    manager.unload_all()
    assert manager.get_registered_service("main_chat.remote") is None


def _addon_capability_payload_isolation_smoke(root: Path) -> None:
    class _Manifest:
        def __init__(self, addon_id):
            self.id = addon_id

    class _Record:
        def __init__(self, addon_id, instance):
            self.manifest = _Manifest(addon_id)
            self.instance = instance
            self.state = "initialized"
            self.context = None

    class _MutatingAddon:
        def __init__(self, name, result=None):
            self.name = name
            self.result = result

        def invoke_capability(self, capability, payload=None):
            data = dict(payload or {})
            nested = data.get("nested")
            if isinstance(nested, dict):
                nested["changed_by"] = self.name
            data["changed_by"] = self.name
            if isinstance(payload, dict):
                payload.update(data)
            return self.result

    class _ObserverAddon:
        def __init__(self):
            self.seen = []

        def invoke_capability(self, capability, payload=None):
            data = dict(payload or {})
            nested = dict(data.get("nested") or {})
            self.seen.append({"top": data.get("changed_by"), "nested": nested.get("changed_by")})
            return {"top": data.get("changed_by"), "nested": nested.get("changed_by")}

    manager = AddonManager(
        app_root=root / "payload_isolation_app",
        llm_snapshot_getter=lambda: {},
        tts_snapshot_getter=lambda: {},
        avatar_snapshot_getter=lambda: {},
    )
    observer = _ObserverAddon()
    manager._records = [
        _Record("mutator", _MutatingAddon("first", result=None)),
        _Record("observer", observer),
    ]
    payload = {"text": "hello", "nested": {"original": True}}
    result = manager.invoke_capability("smoke.capability", payload)
    assert result == {"top": None, "nested": None}
    assert observer.seen == [{"top": None, "nested": None}]
    assert payload == {"text": "hello", "nested": {"original": True}}

    first = _MutatingAddon("first", result="first")
    second = _MutatingAddon("second", result="second")
    manager._records = [
        _Record("first", first),
        _Record("second", second),
    ]
    payload = {"text": "hello", "nested": {"original": True}}
    results = manager.invoke_all_capabilities("smoke.capability", payload)
    assert results == ["first", "second"]
    assert payload == {"text": "hello", "nested": {"original": True}}


def _backend_process_smoke(root: Path) -> None:
    class _ExitedProcess:
        pid = 12345
        returncode = 7

        def poll(self) -> int:
            return self.returncode

    class _RunningProcess:
        pid = 23456
        returncode = None

        def poll(self):
            return None

    class _UnstoppableProcess:
        pid = 34567
        returncode = None

        def poll(self):
            return None

        def terminate(self):
            raise RuntimeError("terminate denied")

    generated_code = generate_pairing_code()
    assert generated_code.isdigit()
    assert len(generated_code) == 6
    assert normalize_supervisor_pairing_code("65-43 21") == "654321"
    assert normalize_supervisor_pairing_code("abc") == ""
    app_root = root / "backend_process_app"
    runtime_dir = app_root / "runtime" / "main_chat_remote"
    supervisor = BackendProcessSupervisor(
        app_root=app_root,
        runtime_dir=runtime_dir,
        bridge_info_path=runtime_dir / "bridge_info.json",
    )
    status = supervisor.status_snapshot()
    assert status["running"] is False
    assert status["venv_python_exists"] is False
    assert status["bridge_info_exists"] is False
    assert status["create_command"][1].endswith("backend_venv.py")
    assert status["create_command"][status["create_command"].index("--venv-dir") + 1] == str(supervisor.venv_dir)
    assert status["create_command"][status["create_command"].index("--bridge-info") + 1] == str(supervisor.bridge_info_path)
    helper_start = supervisor.start_helper_command(host="127.0.0.1", port=9001)
    assert helper_start[1].endswith("backend_venv.py")
    assert helper_start[helper_start.index("--venv-dir") + 1] == str(supervisor.venv_dir)
    assert helper_start[helper_start.index("--bridge-info") + 1] == str(supervisor.bridge_info_path)
    assert helper_start[helper_start.index("--host") + 1] == "127.0.0.1"
    assert helper_start[helper_start.index("--port") + 1] == "9001"
    assert helper_start[-1] == "--start"
    formatted = MainChatRemoteController._format_command([r"C:\Program Files\Python\python.exe", "script.py", "--arg", "has space"])
    assert '"C:\\Program Files\\Python\\python.exe"' in formatted
    assert '"has space"' in formatted
    assert "654321" not in " ".join(supervisor.start_command())
    assert status["pairing_code"] == ""
    assert status["health"]["status"] == "not_started"
    supervisor._process = _ExitedProcess()
    supervisor._pairing_code = "654321"
    supervisor._health = {"ok": True, "status": "ready"}
    exited = supervisor.status_snapshot()
    assert exited["running"] is False
    assert exited["pid"] == 0
    assert exited["returncode"] == 7
    assert exited["pairing_code"] == ""
    assert exited["health"]["status"] == "exited"
    assert exited["health"]["returncode"] == 7

    refresh_supervisor = BackendProcessSupervisor(
        app_root=app_root,
        runtime_dir=runtime_dir,
        bridge_info_path=runtime_dir / "bridge_info.json",
    )
    refresh_process = _RunningProcess()
    refresh_calls = []

    def fake_probe_health(*, host=None, port=None, timeout_seconds=1.0, process=None):
        refresh_calls.append((host, port, timeout_seconds, process))
        result = {"ok": False, "status": "unhealthy", "checked_at": time.time()}
        with refresh_supervisor._lock:
            refresh_supervisor._health = dict(result)
        return result

    refresh_supervisor._process = refresh_process
    refresh_supervisor._pairing_code = "123456"
    refresh_supervisor._health = {"ok": True, "status": "ready", "checked_at": time.time() - 10.0}
    refresh_supervisor.probe_health = fake_probe_health
    refresh_status = refresh_supervisor.status_snapshot()
    assert refresh_status["running"] is True
    deadline = time.time() + 2.0
    while time.time() < deadline and not refresh_calls:
        time.sleep(0.02)
    assert refresh_calls
    assert refresh_supervisor.status_snapshot()["health"]["status"] == "unhealthy"

    start = supervisor.start()
    assert start["accepted"] is False
    assert "venv Python not found" in start["message"]
    supervisor.python_exe.parent.mkdir(parents=True, exist_ok=True)
    supervisor.python_exe.write_text("", encoding="utf-8")
    supervisor.bridge_info_path.parent.mkdir(parents=True, exist_ok=True)
    supervisor.bridge_info_path.write_text(
        json.dumps({"service": "nc_main_chat_bridge", "enabled": False, "token": "stale"}),
        encoding="utf-8",
    )
    stale_bridge_info = supervisor.start()
    assert stale_bridge_info["accepted"] is False
    assert "Bridge info is not usable" in stale_bridge_info["message"]
    assert "not enabled" in stale_bridge_info["message"]

    stop_failure_supervisor = BackendProcessSupervisor(
        app_root=app_root,
        runtime_dir=runtime_dir,
        bridge_info_path=runtime_dir / "bridge_info.json",
    )
    stuck_process = _UnstoppableProcess()
    stop_failure_supervisor._process = stuck_process
    stop_failure_supervisor._pairing_code = "123456"
    failed_stop = stop_failure_supervisor.stop()
    assert failed_stop["accepted"] is False
    assert "terminate denied" in failed_stop["message"]
    assert stop_failure_supervisor._process is stuck_process
    assert stop_failure_supervisor.status_snapshot()["running"] is True

    stale_probe_supervisor = BackendProcessSupervisor(
        app_root=app_root,
        runtime_dir=runtime_dir,
        bridge_info_path=runtime_dir / "bridge_info.json",
    )
    stale_process = _RunningProcess()
    stale_probe_supervisor._process = stale_process
    stale_probe_supervisor._health = {"ok": False, "status": "stopped"}

    class _HealthResponse:
        status = 200

        @staticmethod
        def read():
            return b'{"ok": true}'

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

    original_urlopen = urllib.request.urlopen
    try:
        urllib.request.urlopen = lambda *_args, **_kwargs: _HealthResponse()
        with stale_probe_supervisor._lock:
            stale_probe_supervisor._process = None
        stale_result = stale_probe_supervisor.probe_health(host="127.0.0.1", port=free_local_port(), process=stale_process)
    finally:
        urllib.request.urlopen = original_urlopen
    assert stale_result["ok"] is True
    assert stale_probe_supervisor._health["status"] == "stopped"

    stop = supervisor.stop()
    assert stop["accepted"] is True


def _wait_for_backend_task(controller: MainChatRemoteController, *, timeout_seconds: float = 2.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not controller._current_backend_task():
            return
        time.sleep(0.02)
    raise AssertionError("backend task did not finish")


def _controller_backend_task_smoke(root: Path) -> None:
    app_root = root / "controller_backend_task_app"
    context = _Context(app_root)
    controller = MainChatRemoteController(context)
    controller._settings = BridgeSettings(enabled=False, port=free_local_port()).normalized()
    try:
        controller.start_remote_backend()
        _wait_for_backend_task(controller)
        status = controller.status_snapshot()
        assert status["bridge"]["running"] is True
        assert status["backend"]["running"] is False
        last_result = status["backend"]["last_result"]
        assert last_result["accepted"] is False
        assert "venv Python not found" in last_result["message"]
    finally:
        controller.shutdown()


def _bridge_info_lifecycle_smoke(root: Path) -> None:
    context = _Context(root / "bridge_info_lifecycle_app")
    controller = MainChatRemoteController(context)
    controller._settings = BridgeSettings(enabled=False, port=free_local_port()).normalized()
    try:
        assert not controller.bridge_info_path.exists()
        controller.start_bridge()
        assert controller.bridge_info_path.exists()
        assert not list(controller.bridge_info_path.parent.glob(f".{controller.bridge_info_path.name}.*.tmp"))
        payload = json.loads(controller.bridge_info_path.read_text(encoding="utf-8"))
        assert payload["enabled"] is True
        assert payload["token"] == controller._settings.token
        first_updated_at = float(payload["updated_at"])
        controller._last_bridge_info_write = 0.0
        controller.status_snapshot()
        refreshed_payload = json.loads(controller.bridge_info_path.read_text(encoding="utf-8"))
        assert float(refreshed_payload["updated_at"]) >= first_updated_at
        assert not list(controller.bridge_info_path.parent.glob(f".{controller.bridge_info_path.name}.*.tmp"))
        controller.stop_bridge()
        stopped_status = controller.status_snapshot()
        assert stopped_status["bridge"]["enabled"] is False
        assert stopped_status["bridge"]["running"] is False
        assert not controller.bridge_info_path.exists()
        controller.bridge_info_path.parent.mkdir(parents=True, exist_ok=True)
        controller.bridge_info_path.write_text(json.dumps({"token": "stale"}), encoding="utf-8")
        controller.import_session_state({"main_chat_remote": {"bridge": {"enabled": False, "token": "stale"}}})
        assert not controller.bridge_info_path.exists()
    finally:
        controller.shutdown()


def _controller_shutdown_timer_smoke(root: Path) -> None:
    class _Signal:
        def __init__(self):
            self.disconnected = False

        def disconnect(self, _callback):
            self.disconnected = True

    class _Timer:
        def __init__(self):
            self.stopped = False
            self.timeout = _Signal()

        def stop(self):
            self.stopped = True

    controller = MainChatRemoteController(_Context(root / "shutdown_timer_app"))
    timer = _Timer()
    controller._refresh_timer = timer
    controller._tab = object()
    controller.shutdown()
    assert timer.stopped is True
    assert timer.timeout.disconnected is True
    assert controller._refresh_timer is None
    assert controller._tab is None


def _stt_upload_retention_smoke(root: Path) -> None:
    context = _Context(root / "stt_retention_app")
    controller = MainChatRemoteController(context)
    upload_dir = controller.stt_upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    base_time = 1_000_000.0
    old_upload = upload_dir / "phone_old.wav"
    old_upload.write_bytes(b"old")
    os.utime(old_upload, (base_time - 120.0, base_time - 120.0))
    unrelated = upload_dir / "notes.txt"
    unrelated.write_text("keep", encoding="utf-8")
    os.utime(unrelated, (base_time - 120.0, base_time - 120.0))
    recent_paths = []
    for index in range(5):
        path = upload_dir / f"phone_recent_{index}.wav"
        path.write_bytes(f"recent {index}".encode("ascii"))
        stamp = base_time - float(index)
        os.utime(path, (stamp, stamp))
        recent_paths.append(path)
    controller._cleanup_stt_uploads(now=base_time, max_age_seconds=60.0, max_files=3)
    assert not old_upload.exists()
    assert unrelated.exists()
    kept_names = {path.name for path in upload_dir.glob("phone_*")}
    assert kept_names == {path.name for path in recent_paths[:3]}
    controller.shutdown()


def _stt_upload_unavailable_no_cache_smoke(root: Path) -> None:
    class _NoRuntimeConfig:
        def engine_attr(self, _name, default=None):
            return default

    context = _Context(root / "stt_unavailable_app")
    context._services["qt.runtime_config"] = _NoRuntimeConfig()
    controller = MainChatRemoteController(context)
    try:
        payload = {
            "audio_base64": base64.b64encode(b"phone audio").decode("ascii"),
            "format": "wav",
            "send_to_chat": True,
        }
        result = controller.remote_stt_upload(payload)
        assert result["accepted"] is False
        assert result["audio_cached"] is False
        assert "file transcription" in result["error"]
        assert not list(controller.stt_upload_dir.glob("phone_*"))
    finally:
        controller.shutdown()


def _media_bridge_retention_smoke(root: Path) -> None:
    cache_dir = root / "media_bridge_retention"
    source = root / "media_bridge_source.wav"
    _write_wav(source)
    bridge = MainChatMediaBridge(cache_dir)
    assert bridge._int_value(0, default=99) == 0
    assert bridge._int_value("0", default=99) == 0
    assert bridge._int_value("", default=99) == 99
    bridge.begin_tts_capture("retention smoke")
    for index in range(70):
        accepted = bridge.handle_tts_audio_chunk_ready(
            {
                "audio_path": str(source),
                "text": f"chunk {index}",
                "duration_seconds": 1.25,
                "sequence_index": index,
                "sample_rate": 16000,
                "source_meta": {"display_name": "Assistant"},
            }
        )
        assert accepted["captured"] is True
        assert accepted["skip_local_playback"] is False
    snapshot = bridge.snapshot()
    items = list(snapshot["items"])
    ids = [str(item["id"]) for item in items]
    assert len(items) == 64
    assert len(ids) == len(set(ids))
    assert items[0]["index"] == 7
    assert items[-1]["index"] == 70
    assert items[0]["sequence_index"] == 6
    assert items[-1]["sequence_index"] == 69
    assert items[-1]["duration_seconds"] == 1.25
    assert len(list(cache_dir.glob("*.wav"))) == 64
    bridge.cleanup()
    assert not list(cache_dir.glob("*.wav"))


def _media_bridge_auto_capture_smoke(root: Path) -> None:
    cache_dir = root / "media_bridge_auto_capture"
    source = root / "media_bridge_auto_source.wav"
    _write_wav(source)
    bridge = MainChatMediaBridge(cache_dir)
    accepted = bridge.handle_tts_audio_chunk_ready(
        {
            "audio_path": str(source),
            "text": "desktop-originated reply",
            "duration_seconds": 0.25,
            "sample_rate": 16000,
            "source_meta": {"display_name": "Assistant"},
        }
    )
    assert accepted["captured"] is True
    assert accepted["skip_local_playback"] is False
    snapshot = bridge.snapshot()
    assert snapshot["available"] is True
    assert snapshot["capture_active"] is True
    assert snapshot["source_excerpt"] == "desktop-originated reply"
    assert snapshot["items"][0]["speaker"] == "Assistant"
    assert Path(bridge.audio_file_path(snapshot["items"][0]["id"])).exists()
    bridge.cleanup()


def _media_bridge_audio_format_smoke(root: Path) -> None:
    cache_dir = root / "media_bridge_audio_format"
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    source = root / "media_bridge_source.mp3"
    source.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00")
    bridge = MainChatMediaBridge(cache_dir)
    accepted = bridge.handle_tts_audio_chunk_ready(
        {
            "audio_path": str(source),
            "text": "mp3 smoke",
            "duration_seconds": 2.5,
            "source_meta": {"display_name": "Assistant"},
        }
    )
    assert accepted["captured"] is True
    assert accepted["skip_local_playback"] is False
    snapshot = bridge.snapshot()
    item = snapshot["items"][0]
    audio_path = bridge.audio_file_path(item["id"])
    assert audio_path.suffix == ".mp3"
    assert item["content_type"].startswith("audio/")
    assert item["duration_seconds"] == 2.5
    unsupported = root / "media_bridge_source.txt"
    unsupported.write_text("not audio", encoding="utf-8")
    assert bridge.handle_tts_audio_chunk_ready({"audio_path": str(unsupported)}) is None
    bridge.cleanup()


def _stt_result_normalization_smoke() -> None:
    class _Segment:
        def __init__(self, text: str):
            self.text = text

    assert MainChatRemoteController._stt_text_from_result("plain text") == "plain text"
    assert MainChatRemoteController._stt_text_from_result(((), {"text": "dict text"})) == "dict text"
    assert MainChatRemoteController._stt_text_from_result(([_Segment("hello"), _Segment("world")], object())) == "hello world"
    assert MainChatRemoteController._stt_text_from_result({"segments": [{"text": "nested"}]}) == "nested"


def _stt_upload_serialization_smoke(root: Path) -> None:
    class _SerialRuntimeConfig:
        def __init__(self):
            self.active = 0
            self.max_active = 0
            self.calls = 0
            self.lock = threading.Lock()

        def engine_attr(self, name, default=None):
            if str(name) != "transcribe_file_with_stt":
                return default

            def transcribe(_path, language=None):
                with self.lock:
                    self.active += 1
                    self.calls += 1
                    self.max_active = max(self.max_active, self.active)
                time.sleep(0.05)
                with self.lock:
                    self.active -= 1
                return (), {"text": f"serialized {self.calls}"}

            return transcribe

    context = _Context(root / "stt_serialization_app")
    runtime_config = _SerialRuntimeConfig()
    context._services["qt.runtime_config"] = runtime_config
    controller = MainChatRemoteController(context)
    payload = {
        "audio_base64": base64.b64encode(b"phone audio").decode("ascii"),
        "format": "wav",
        "send_to_chat": False,
    }
    results: list[dict[str, Any]] = []
    try:
        threads = [
            threading.Thread(target=lambda: results.append(controller.remote_stt_upload(payload)), daemon=True)
            for _index in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2.0)
        assert len(results) == 2
        assert all(item.get("accepted") is True for item in results)
        assert runtime_config.calls == 2
        assert runtime_config.max_active == 1
    finally:
        controller.shutdown()


def _phone_status_redaction_smoke(root: Path) -> None:
    class _RunningProcess:
        pid = 45678

        def poll(self):
            return None

    controller = MainChatRemoteController(_Context(root / "phone_status_redaction_app"))
    try:
        process = _RunningProcess()
        with controller.backend_process._lock:
            controller.backend_process._process = process
            controller.backend_process._pairing_code = "654321"
            controller.backend_process._last_result = {"accepted": True, "pairing_code": "654321"}
            controller.backend_process._health = {"ok": True, "status": "ready", "checked_at": time.time()}
        status = controller._phone_status_snapshot()
        backend = status["backend"]
        assert backend["running"] is True
        assert backend["pairing_code"] == ""
        assert backend["pairing_code_digits"] == 6
        assert backend["pairing_code_configured"] is True
        assert backend["last_result"]["pairing_code"] == ""
        assert backend["last_result"]["pairing_code_configured"] is True
    finally:
        with controller.backend_process._lock:
            controller.backend_process._process = None
        controller.shutdown()


def _phone_safe_payload_smoke(root: Path) -> None:
    controller = MainChatRemoteController(_Context(root / "phone_safe_payload_app"))
    try:
        payload = controller._phone_safe_payload(
            {
                "image_path": str(root / "visual.png"),
                "image_url_path": "/api/visual/image",
                "image_cache_key": "cache-key-is-not-a-secret",
                "token_configured": True,
                "nested": {
                    "frame_path": str(root / "frame.png"),
                    "frame_url_path": "/api/musetalk/frame/smoke",
                    "stream_url_path": "/api/musetalk/stream",
                    "url_path": "/api/audio/file/chunk",
                    "model_path": str(root / "models" / "avatar.bin"),
                    "output_dir": str(root / "outputs"),
                    "cacheFolder": str(root / "cache"),
                    "source_root": str(root / "source"),
                    "command": [str(root / "python.exe"), "remote_backend.py"],
                    "api_key": "private-api-key",
                    "openai_api_key": "private-openai-api-key",
                    "apiKey": "private-camel-api-key",
                    "client_secret": "private-client-secret",
                    "bearerToken": "private-bearer-token",
                    "token": "private-token",
                    "access_token": "private-access-token",
                },
            }
        )
        raw = json.dumps(payload)
        assert str(root) not in raw
        assert "private-api-key" not in raw
        assert "private-openai-api-key" not in raw
        assert "private-camel-api-key" not in raw
        assert "private-client-secret" not in raw
        assert "private-bearer-token" not in raw
        assert "private-token" not in raw
        assert "private-access-token" not in raw
        assert "image_path" not in payload
        assert payload["image_url_path"] == "/api/visual/image"
        assert payload["image_cache_key"] == "cache-key-is-not-a-secret"
        assert payload["token_configured"] is True
        assert "frame_path" not in payload["nested"]
        assert payload["nested"]["frame_url_path"] == "/api/musetalk/frame/smoke"
        assert payload["nested"]["stream_url_path"] == "/api/musetalk/stream"
        assert payload["nested"]["url_path"] == "/api/audio/file/chunk"
        assert "model_path" not in payload["nested"]
        assert "output_dir" not in payload["nested"]
        assert "cacheFolder" not in payload["nested"]
        assert "source_root" not in payload["nested"]
        assert "command" not in payload["nested"]
        assert "api_key" not in payload["nested"]
        assert "openai_api_key" not in payload["nested"]
        assert "apiKey" not in payload["nested"]
        assert "client_secret" not in payload["nested"]
        assert "bearerToken" not in payload["nested"]
        assert "token" not in payload["nested"]
        assert "access_token" not in payload["nested"]
    finally:
        controller.shutdown()


def _remote_control_fallback_allowlist_smoke(root: Path) -> None:
    class _EmptyControls:
        def __init__(self):
            self.triggered = []

        def snapshot(self):
            return {"actions": []}

        def trigger(self, action):
            self.triggered.append(str(action or ""))
            return {"accepted": True, "action": action}

    context = _Context(root / "remote_control_allowlist_app")
    controls = _EmptyControls()
    context._services["qt.runtime_controls"] = controls
    controller = MainChatRemoteController(context)
    try:
        accepted = controller.remote_control("pause_speech")
        assert accepted["accepted"] is True
        assert controls.triggered == ["pause_speech"]
        rejected = controller.remote_control("arbitrary_desktop_command")
        assert rejected["accepted"] is False
        assert "Unsupported action" in rejected["message"]
        assert controls.triggered == ["pause_speech"]
    finally:
        controller.shutdown()


def _wait_for_visual_request_status(controller: MainChatRemoteController, request_id: str, statuses: set[str], *, timeout_seconds: float = 2.0) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        visual = controller.visual_snapshot(phone_safe=True)
        latest = dict(visual.get("latest_request") or {})
        if latest.get("request_id") == request_id and latest.get("status") in statuses:
            return latest
        time.sleep(0.02)
    return dict(controller.visual_snapshot(phone_safe=True).get("latest_request") or {})


def _visual_request_tracking_smoke(root: Path) -> None:
    class _RejectingVisual(_VisualReply):
        def request_generation(self, **kwargs):
            self.requests.append(dict(kwargs))
            return False

    context = _Context(root / "visual_request_tracking_app")
    controller = MainChatRemoteController(context)
    invoked_main = []
    original_invoke_main = controller._invoke_main

    def tracking_invoke_main(func):
        invoked_main.append(getattr(func, "__name__", ""))
        return original_invoke_main(func)

    controller._invoke_main = tracking_invoke_main
    try:
        accepted = controller.remote_visual_request({"prompt": "tracked visual"})
        assert accepted["accepted"] is True
        request_id = accepted["request_id"]
        queued = dict(accepted["visual"]["latest_request"])
        assert queued["request_id"] == request_id
        assert queued["status"] in {"queued", "running", "done"}
        done = _wait_for_visual_request_status(controller, request_id, {"done"})
        assert done["status"] == "done"
        assert done["accepted"] is True
        assert done["prompt_preview"] == "tracked visual"
        assert "generate" in invoked_main
        raw = json.dumps(controller.visual_snapshot(phone_safe=True))
        assert "image_path" not in raw
    finally:
        controller.shutdown()

    rejecting_context = _Context(root / "visual_request_reject_app")
    rejecting_context._services["qt.visual_reply"] = _RejectingVisual()
    rejecting_controller = MainChatRemoteController(rejecting_context)
    try:
        rejected = rejecting_controller.remote_visual_request({"prompt": "rejected visual"})
        request_id = rejected["request_id"]
        latest = _wait_for_visual_request_status(rejecting_controller, request_id, {"rejected"})
        assert latest["status"] == "rejected"
        assert latest["accepted"] is False
    finally:
        rejecting_controller.shutdown()


def _remote_state_phone_safe_smoke(root: Path) -> None:
    class _LeakyReplay(_ChatReplay):
        def replayable_chat_entries(self):
            return [
                {
                    "replay_index": 1,
                    "role": "assistant",
                    "content": "hi",
                    "image_path": str(root / "visual.png"),
                    "command": ["python", "backend.py"],
                    "preview": "Assistant: hi",
                }
            ]

    context = _Context(root / "remote_state_phone_safe_app")
    context._services["qt.chat_replay"] = _LeakyReplay()
    context.llm = _Snapshot(
        {
            "provider": "smoke",
            "backend_script": str(root / "private.py"),
            "api_key": "private-llm-key",
            "nested": {"refresh_token": "private-refresh"},
        }
    )
    controller = MainChatRemoteController(context)
    try:
        state = controller.remote_state_snapshot()
        encoded = json.dumps(state)
        assert str(root) not in encoded
        assert "backend.py" not in encoded
        assert "private-llm-key" not in encoded
        assert "private-refresh" not in encoded
        assert "image_path" not in encoded
        assert "backend_script" not in state["llm"]
        assert "api_key" not in state["llm"]
        assert "refresh_token" not in state["llm"]["nested"]
        assert state["replayable"][0]["preview"] == "Assistant: hi"
    finally:
        controller.shutdown()


def _engine_tts_audio_chunk_ready_fanout_smoke() -> None:
    source = (ROOT / "engine.py").read_text(encoding="utf-8", errors="replace")
    marker = "def _notify_addon_tts_audio_chunk_ready"
    start = source.index(marker)
    end = source.index("\ndef _notify_addon_tts_duck_start", start)
    block = source[start:end]
    assert "_invoke_all_addon_capabilities" in source
    assert "_invoke_all_addon_capabilities(\"tts.audio_chunk_ready\"" in block
    assert "_invoke_addon_capability(\"tts.audio_chunk_ready\"" not in block
    assert "skip_local_playback" in block


def _backend_venv_helper_smoke(root: Path) -> None:
    valid_bridge_info = root / "valid_helper_bridge_info.json"
    valid_bridge_info.write_text(
        json.dumps(
            {
                "service": "nc_main_chat_bridge",
                "enabled": True,
                "url": "http://localhost:8776",
                "token": "token-value",
                "updated_at": time.time(),
            }
        ),
        encoding="utf-8",
    )
    valid_status = backend_venv.check_status(root / "venv", valid_bridge_info)
    assert valid_status["bridge_info_usable"] is True
    assert valid_status["bridge_info_error"] == ""
    missing_validation = backend_venv.validate_bridge_info(root / "missing_bridge_info.json")
    assert missing_validation["ok"] is False
    assert "not found" in missing_validation["error"]
    stale_bridge_info = root / "stale_helper_bridge_info.json"
    stale_bridge_info.write_text(
        json.dumps(
            {
                "service": "nc_main_chat_bridge",
                "enabled": True,
                "url": "http://localhost:8776",
                "token": "token-value",
                "updated_at": time.time() - remote_backend_module.BRIDGE_INFO_MAX_AGE_SECONDS - 1.0,
            }
        ),
        encoding="utf-8",
    )
    stale_validation = backend_venv.validate_bridge_info(stale_bridge_info)
    assert stale_validation["ok"] is False
    assert "stale" in stale_validation["error"]
    future_bridge_info = root / "future_helper_bridge_info.json"
    future_bridge_info.write_text(
        json.dumps(
            {
                "service": "nc_main_chat_bridge",
                "enabled": True,
                "url": "http://localhost:8776",
                "token": "token-value",
                "updated_at": time.time() + remote_backend_module.BRIDGE_INFO_MAX_FUTURE_SKEW_SECONDS + 1.0,
            }
        ),
        encoding="utf-8",
    )
    future_validation = backend_venv.validate_bridge_info(future_bridge_info)
    assert future_validation["ok"] is False
    assert "future" in future_validation["error"]

    parser = backend_venv.build_arg_parser()
    args = parser.parse_args(
        [
            "--venv-dir",
            str(root / "venv"),
            "--bridge-info",
            str(root / "bridge_info.json"),
            "--start",
            "--pairing-code",
            "654321",
            "--dry-run",
        ]
    )
    command = backend_venv.backend_command(args, backend_venv.venv_python(Path(args.venv_dir)))
    env = backend_venv.backend_environment(args)
    assert "654321" not in " ".join(command)
    assert env is not None
    assert env.get("NC_MAIN_CHAT_REMOTE_CODE") == "654321"
    assert env.get("NC_MAIN_CHAT_REMOTE_HIDE_CODE_OUTPUT") == "1"
    args.pairing_code = "65-43 21"
    formatted_env = backend_venv.backend_environment(args)
    assert formatted_env is not None
    assert formatted_env.get("NC_MAIN_CHAT_REMOTE_CODE") == "654321"
    args.pairing_code = "abc"
    previous_code = os.environ.get("NC_MAIN_CHAT_REMOTE_CODE")
    previous_hide = os.environ.get("NC_MAIN_CHAT_REMOTE_HIDE_CODE_OUTPUT")
    try:
        os.environ["NC_MAIN_CHAT_REMOTE_CODE"] = "999999"
        os.environ["NC_MAIN_CHAT_REMOTE_HIDE_CODE_OUTPUT"] = "1"
        generated_env = backend_venv.backend_environment(args)
    finally:
        if previous_code is None:
            os.environ.pop("NC_MAIN_CHAT_REMOTE_CODE", None)
        else:
            os.environ["NC_MAIN_CHAT_REMOTE_CODE"] = previous_code
        if previous_hide is None:
            os.environ.pop("NC_MAIN_CHAT_REMOTE_HIDE_CODE_OUTPUT", None)
        else:
            os.environ["NC_MAIN_CHAT_REMOTE_HIDE_CODE_OUTPUT"] = previous_hide
    assert generated_env is not None
    assert "NC_MAIN_CHAT_REMOTE_CODE" not in generated_env
    assert "NC_MAIN_CHAT_REMOTE_HIDE_CODE_OUTPUT" not in generated_env


def _backend_pairing_output_smoke() -> None:
    assert normalize_remote_pairing_code("65-43 21") == "654321"
    assert normalize_remote_pairing_code("abc") == ""
    assert remote_backend_module.local_network_client("127.0.0.1") is True
    assert remote_backend_module.local_network_client("192.168.1.20") is True
    assert remote_backend_module.local_network_client("10.1.2.3") is True
    assert remote_backend_module.local_network_client("172.16.0.10") is True
    assert remote_backend_module.local_network_client("172.31.255.254") is True
    assert remote_backend_module.local_network_client("169.254.10.20") is True
    assert remote_backend_module.local_network_client("fc00::1") is True
    assert remote_backend_module.local_network_client("fe80::1%12") is True
    assert remote_backend_module.local_network_client("::ffff:192.168.1.20") is True
    assert remote_backend_module.local_network_client("8.8.8.8") is False
    assert remote_backend_module.local_network_client("1.1.1.1") is False
    assert remote_backend_module.local_network_client("203.0.113.10") is False
    assert remote_backend_module.local_network_client("172.32.0.1") is False
    assert remote_backend_module.local_network_client("::ffff:8.8.8.8") is False
    assert remote_backend_module.normalize_bridge_url("127.0.0.1:9000/health?x=1") == "http://127.0.0.1:9000"
    assert remote_backend_module.normalize_bridge_url("http://localhost:9000/base") == "http://localhost:9000"
    assert remote_backend_module.normalize_bridge_url("http://[::1]:9000/base") == "http://[::1]:9000"
    assert remote_backend_module.normalize_bridge_url("http://192.168.1.20:8776") == remote_backend_module.DEFAULT_BRIDGE_URL
    assert remote_backend_module.normalize_bridge_url("https://localhost:8776") == remote_backend_module.DEFAULT_BRIDGE_URL
    redacted = redact_sensitive_query_values('"GET /ws?code=123456&fps=2&token=secret HTTP/1.1" 101')
    assert "123456" not in redacted
    assert "secret" not in redacted
    assert "code=<redacted>" in redacted
    assert "token=<redacted>" in redacted
    bridge_redacted = redact_bridge_sensitive_query_values('"GET /api/state?token=bridge-secret&code=123456 HTTP/1.1" 401')
    assert "bridge-secret" not in bridge_redacted
    assert "123456" not in bridge_redacted
    request = BridgeClient("http://127.0.0.1:8776", "secret-token").build_request("GET", "/api/state?after=1")
    assert request.full_url == "http://127.0.0.1:8776/api/state?after=1"
    assert request.get_header("X-nc-bridge-token") == "secret-token"
    fallback_request = BridgeClient("http://192.168.1.20:8776", "secret-token").build_request("GET", "/api/state")
    assert fallback_request.full_url == f"{remote_backend_module.DEFAULT_BRIDGE_URL}/api/state"
    visible_backend = MainChatRemoteBackend(host="127.0.0.1", port=free_local_port(), pairing_code="65-43 21")
    hidden_backend = MainChatRemoteBackend(
        host="127.0.0.1",
        port=free_local_port(),
        pairing_code="654321",
        hide_pairing_code_output=True,
    )
    generated_backend = MainChatRemoteBackend(
        host="127.0.0.1",
        port=free_local_port(),
        pairing_code="abc",
    )
    assert visible_backend.pairing_code_display_text() == "654321"
    assert hidden_backend.pairing_code_display_text() == "configured by launcher"
    assert generated_backend.pairing_code.isdigit()
    assert len(generated_backend.pairing_code) == 6
    public_status = visible_backend.public_status_snapshot()
    assert public_status["pairing_code_digits"] == len("654321")
    assert "clients" not in public_status
    assert "bridge_url" not in public_status
    public_bridge_health = remote_backend_module.public_bridge_health_snapshot(
        {
            "ok": True,
            "service": "nc_main_chat_bridge",
            "bridge": {
                "enabled": True,
                "running": True,
                "host": "127.0.0.1",
                "port": 8776,
                "url": "http://127.0.0.1:8776",
                "token_configured": True,
                "started_at": 1.0,
            },
        }
    )
    encoded_health = json.dumps(public_bridge_health)
    assert public_bridge_health["ok"] is True
    assert public_bridge_health["bridge"]["running"] is True
    assert "127.0.0.1" not in encoded_health
    assert "8776" not in encoded_health
    assert "token_configured" not in encoded_health
    bridge_path = visible_backend._handler_class()._bridge_path(
        "/api/musetalk/stream",
        "code=123456&fps=8&token=phone-supplied&wait=2",
    )
    assert bridge_path == "/api/musetalk/stream?fps=8&wait=2"
    assert "code=" not in bridge_path
    assert "token=" not in bridge_path


def _bridge_info_load_smoke(root: Path) -> None:
    valid = root / "valid_bridge_info.json"
    valid.write_text(
        json.dumps(
            {
                "service": "nc_main_chat_bridge",
                "enabled": True,
                "url": "http://localhost:8776/health",
                "token": "token-value",
                "updated_at": time.time(),
            }
        ),
        encoding="utf-8",
    )
    loaded = remote_backend_module.load_bridge_info(valid)
    assert loaded["url"] == "http://localhost:8776"
    assert loaded["token"] == "token-value"

    disabled = root / "disabled_bridge_info.json"
    disabled.write_text(
        json.dumps(
            {
                "service": "nc_main_chat_bridge",
                "enabled": False,
                "url": "http://localhost:8776",
                "token": "token-value",
            }
        ),
        encoding="utf-8",
    )
    try:
        remote_backend_module.load_bridge_info(disabled)
    except ValueError as exc:
        assert "not enabled" in str(exc)
    else:
        raise AssertionError("disabled bridge info should be rejected")

    missing_token = root / "missing_token_bridge_info.json"
    missing_token.write_text(
        json.dumps({"service": "nc_main_chat_bridge", "enabled": True, "url": "http://localhost:8776", "updated_at": time.time()}),
        encoding="utf-8",
    )
    try:
        remote_backend_module.load_bridge_info(missing_token)
    except ValueError as exc:
        assert "missing the bridge token" in str(exc)
    else:
        raise AssertionError("tokenless bridge info should be rejected")

    missing_timestamp = root / "missing_timestamp_bridge_info.json"
    missing_timestamp.write_text(
        json.dumps({"service": "nc_main_chat_bridge", "enabled": True, "url": "http://localhost:8776", "token": "token-value"}),
        encoding="utf-8",
    )
    try:
        remote_backend_module.load_bridge_info(missing_timestamp)
    except ValueError as exc:
        assert "freshness timestamp" in str(exc)
    else:
        raise AssertionError("bridge info without timestamp should be rejected")

    stale = root / "stale_bridge_info.json"
    stale.write_text(
        json.dumps(
            {
                "service": "nc_main_chat_bridge",
                "enabled": True,
                "url": "http://localhost:8776",
                "token": "token-value",
                "updated_at": time.time() - remote_backend_module.BRIDGE_INFO_MAX_AGE_SECONDS - 1.0,
            }
        ),
        encoding="utf-8",
    )
    try:
        remote_backend_module.load_bridge_info(stale)
    except ValueError as exc:
        assert "stale" in str(exc)
    else:
        raise AssertionError("stale bridge info should be rejected")

    future = root / "future_bridge_info.json"
    future.write_text(
        json.dumps(
            {
                "service": "nc_main_chat_bridge",
                "enabled": True,
                "url": "http://localhost:8776",
                "token": "token-value",
                "updated_at": time.time() + remote_backend_module.BRIDGE_INFO_MAX_FUTURE_SKEW_SECONDS + 1.0,
            }
        ),
        encoding="utf-8",
    )
    try:
        remote_backend_module.load_bridge_info(future)
    except ValueError as exc:
        assert "future" in str(exc)
    else:
        raise AssertionError("future-dated bridge info should be rejected")


def _remote_backend_main_bridge_info_smoke(root: Path) -> None:
    stale = root / "stale_main_bridge_info.json"
    stale.write_text(
        json.dumps(
            {
                "service": "nc_main_chat_bridge",
                "enabled": True,
                "url": "http://localhost:8776",
                "token": "token-value",
                "updated_at": time.time() - remote_backend_module.BRIDGE_INFO_MAX_AGE_SECONDS - 1.0,
            }
        ),
        encoding="utf-8",
    )
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        result = remote_backend_module.main(["--bridge-info", str(stale), "--port", str(free_local_port())])
    assert result == 3
    stderr_text = stderr.getvalue()
    assert "Bridge info is not usable" in stderr_text
    assert "Traceback" not in stderr_text


def _backend_bridge_unavailable_smoke() -> None:
    backend_port = free_local_port()
    missing_bridge_port = free_local_port()
    backend = MainChatRemoteBackend(
        host="127.0.0.1",
        port=backend_port,
        pairing_code="123456",
        bridge_url=f"http://127.0.0.1:{missing_bridge_port}",
        bridge_token="missing",
    )
    backend.bridge = backend.bridge.with_timeout(0.5)
    backend.start()
    try:
        started = time.perf_counter()
        status, health = _read_http_json(f"http://127.0.0.1:{backend_port}/health", timeout=2.0)
        elapsed = time.perf_counter() - started
        assert status == 200
        assert elapsed < 1.8
        assert health["ok"] is False
        assert health["status"] == "bridge_unavailable"
        assert health["bridge"]["ok"] is False
        assert health["bridge"]["status"] == 502
        assert health["remote"]["pairing_code_digits"] == 6
        assert "clients" not in health["remote"]
        assert "bridge_url" not in health["remote"]
        status, missing = _read_http_json(f"http://127.0.0.1:{backend_port}/not-api", timeout=2.0)
        assert status == 404
        assert missing["ok"] is False
        assert missing["error"] == "Not found"
        stream_started = time.perf_counter()
        stream_status, stream_error = _read_http_json(
            f"http://127.0.0.1:{backend_port}/api/musetalk/stream?code=123456&frames=1",
            timeout=5.0,
        )
        stream_elapsed = time.perf_counter() - stream_started
        assert stream_status == 502
        assert stream_elapsed < 4.5
        assert stream_error["ok"] is False
        assert stream_error["status"] == 502
        assert "Bridge unavailable" in stream_error["error"]
    finally:
        backend.stop()


def _backend_auth_throttle_smoke() -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class BridgeHandler(BaseHTTPRequestHandler):
        def log_message(self, _fmt: str, *_args) -> None:
            return

        def do_GET(self) -> None:
            body = json.dumps({"ok": True, "state": {"chat": {"items": []}}}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()

    backend_port = free_local_port()
    bridge_port = free_local_port()
    bridge_server = ThreadingHTTPServer(("127.0.0.1", bridge_port), BridgeHandler)
    bridge_server.daemon_threads = True
    bridge_thread = threading.Thread(target=bridge_server.serve_forever, name="nc-remote-auth-throttle-bridge", daemon=True)
    backend = MainChatRemoteBackend(
        host="127.0.0.1",
        port=backend_port,
        pairing_code="123456",
        bridge_url=f"http://127.0.0.1:{bridge_port}",
        bridge_token="missing",
    )
    bridge_thread.start()
    backend.start()
    try:
        for _index in range(remote_backend_module.AUTH_FAILURE_LIMIT):
            status, payload = _read_http_json(f"http://127.0.0.1:{backend_port}/api/state?code=0000", timeout=2.0)
            assert status == 401
            assert payload["ok"] is False
            assert payload["error"] == "Unauthorized"
        status, payload = _read_http_json(f"http://127.0.0.1:{backend_port}/api/state?code=0000", timeout=2.0)
        assert status == 429
        assert payload["ok"] is False
        assert "invalid pairing" in payload["error"]
        assert backend.auth_failure_count("127.0.0.1") > remote_backend_module.AUTH_FAILURE_LIMIT
        status, payload = _read_http_json(f"http://127.0.0.1:{backend_port}/api/state?code=123456", timeout=2.0)
        assert status == 200
        assert payload["ok"] is True
        assert backend.auth_failure_count("127.0.0.1") == 0
    finally:
        backend.stop()
        bridge_server.shutdown()
        bridge_server.server_close()
        bridge_thread.join(timeout=2)


def _websocket_handshake_validation_smoke() -> None:
    backend_port = free_local_port()
    backend = MainChatRemoteBackend(
        host="127.0.0.1",
        port=backend_port,
        pairing_code="123456",
        bridge_url=f"http://127.0.0.1:{free_local_port()}",
        bridge_token="unused",
    )
    backend.start()
    try:
        valid_key = base64.b64encode(os.urandom(16)).decode("ascii")
        status, payload = _read_raw_http_json(
            "127.0.0.1",
            backend_port,
            "/ws?code=123456",
            {
                "Sec-WebSocket-Key": valid_key,
                "Sec-WebSocket-Version": "13",
            },
            timeout=2.0,
        )
        assert status == 400
        assert payload["ok"] is False
        assert "upgrade" in str(payload["error"]).lower()

        status, payload = _read_raw_http_json(
            "127.0.0.1",
            backend_port,
            "/ws?code=123456",
            {
                "Upgrade": "websocket",
                "Connection": "Upgrade",
                "Sec-WebSocket-Key": valid_key,
                "Sec-WebSocket-Version": "12",
            },
            timeout=2.0,
        )
        assert status == 400
        assert payload["ok"] is False
        assert "version" in str(payload["error"]).lower()

        status, payload = _read_raw_http_json(
            "127.0.0.1",
            backend_port,
            "/ws?code=123456",
            {
                "Upgrade": "websocket",
                "Connection": "Upgrade",
                "Sec-WebSocket-Key": "not-a-valid-key",
                "Sec-WebSocket-Version": "13",
            },
            timeout=2.0,
        )
        assert status == 400
        assert payload["ok"] is False
        assert "key" in str(payload["error"]).lower()
    finally:
        backend.stop()


def _websocket_state_bridge_timeout_smoke() -> None:
    bridge_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    bridge_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    bridge_listener.bind(("127.0.0.1", 0))
    bridge_listener.listen(1)
    bridge_listener.settimeout(2.0)
    bridge_port = int(bridge_listener.getsockname()[1])

    def stall_bridge() -> None:
        try:
            try:
                connection, _address = bridge_listener.accept()
            except OSError:
                return
            with connection:
                connection.settimeout(0.5)
                try:
                    connection.recv(4096)
                except OSError:
                    pass
                time.sleep(1.0)
        finally:
            try:
                bridge_listener.close()
            except OSError:
                pass

    bridge_thread = threading.Thread(target=stall_bridge, name="nc-remote-smoke-stalling-bridge", daemon=True)
    bridge_thread.start()
    backend_port = free_local_port()
    backend = MainChatRemoteBackend(
        host="127.0.0.1",
        port=backend_port,
        pairing_code="123456",
        bridge_url=f"http://127.0.0.1:{bridge_port}",
        bridge_token="stalling",
    )
    original_timeout = remote_backend_module.WEBSOCKET_STATE_BRIDGE_TIMEOUT_SECONDS
    remote_backend_module.WEBSOCKET_STATE_BRIDGE_TIMEOUT_SECONDS = 0.2
    backend.start()
    try:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        with socket.create_connection(("127.0.0.1", backend_port), timeout=3) as sock:
            sock.settimeout(1.5)
            request = (
                "GET /ws?code=123456 HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{backend_port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n"
                "\r\n"
            )
            sock.sendall(request.encode("ascii"))
            response = b""
            while b"\r\n\r\n" not in response:
                response += sock.recv(4096)
            _headers, _separator, remainder = response.partition(b"\r\n\r\n")
            frame_buffer = bytearray(remainder)
            assert b"101 Switching Protocols" in response
            opcode, payload = _read_ws_frame(sock, frame_buffer)
            assert opcode == 0x1
            hello = json.loads(payload.decode("utf-8"))
            assert hello["type"] == "hello"
            assert "clients" not in hello["remote"]
            assert "bridge_url" not in hello["remote"]
            started = time.perf_counter()
            message = _read_ws_json_type(sock, frame_buffer, {"state"}, max_frames=3)
            elapsed = time.perf_counter() - started
            assert elapsed < 1.0
            state_payload = message["payload"]
            assert state_payload["ok"] is False
            assert state_payload["status"] == 502
            _send_ws_close(sock)
    finally:
        backend.stop()
        remote_backend_module.WEBSOCKET_STATE_BRIDGE_TIMEOUT_SECONDS = original_timeout
        try:
            bridge_listener.close()
        except OSError:
            pass
        bridge_thread.join(timeout=2)


def _write_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 1600)


def _read_json(url: str, token: str):
    request = urllib.request.Request(url, headers={"X-NC-Bridge-Token": token})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _read_phone_json(url: str, code: str):
    request = urllib.request.Request(url, headers={"X-NC-Phone-Code": code})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _read_phone_json_status(url: str, code: str):
    opener = urllib.request.build_opener(_NoHttpErrorProcessor)
    request = urllib.request.Request(url, headers={"X-NC-Phone-Code": code})
    with opener.open(request, timeout=5) as response:
        return int(response.status), json.loads(response.read().decode("utf-8"))


def _post_phone_json(url: str, code: str, payload):
    body = json.dumps(dict(payload or {})).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8", "X-NC-Phone-Code": code},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _options_json(url: str, headers: dict[str, str] | None = None):
    request = urllib.request.Request(url, method="OPTIONS", headers=dict(headers or {}))
    with urllib.request.urlopen(request, timeout=5) as response:
        return int(response.status), json.loads(response.read().decode("utf-8"))


def _read_phone_bytes(url: str, code: str, length: int = 512) -> bytes:
    request = urllib.request.Request(url, headers={"X-NC-Phone-Code": code})
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.read(length)


def _read_url_bytes(url: str, length: int = 512) -> bytes:
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.read(length)


class _NoHttpErrorProcessor(urllib.request.HTTPErrorProcessor):
    def http_response(self, request, response):
        return response

    https_response = http_response


def _read_http_json(url: str, *, timeout: float = 5.0, headers: dict[str, str] | None = None):
    opener = urllib.request.build_opener(_NoHttpErrorProcessor)
    request = urllib.request.Request(url, headers=dict(headers or {}))
    with opener.open(request, timeout=timeout) as response:
        return int(response.status), json.loads(response.read().decode("utf-8"))


def _read_raw_http_json(
    host: str,
    port: int,
    path: str,
    headers: dict[str, str] | None = None,
    *,
    timeout: float = 5.0,
):
    with socket.create_connection((host, int(port)), timeout=timeout) as sock:
        sock.settimeout(timeout)
        lines = [
            f"GET {path} HTTP/1.1",
            f"Host: {host}:{int(port)}",
        ]
        for key, value in dict(headers or {}).items():
            lines.append(f"{key}: {value}")
        lines.append("")
        lines.append("")
        sock.sendall("\r\n".join(lines).encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            response += sock.recv(4096)
        raw_headers, _separator, body = response.partition(b"\r\n\r\n")
        header_lines = raw_headers.decode("iso-8859-1").splitlines()
        status = int(header_lines[0].split()[1])
        header_map = {}
        for line in header_lines[1:]:
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            header_map[key.strip().lower()] = value.strip()
        content_length = int(header_map.get("content-length") or 0)
        while len(body) < content_length:
            chunk = sock.recv(4096)
            if not chunk:
                break
            body += chunk
        return status, json.loads(body[:content_length].decode("utf-8"))


def _write_png(path: Path) -> None:
    path.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
        )
    )


def _install_musetalk_frame(frame_path: Path):
    from addons.musetalk_avatar import state as musetalk_state

    previous_frame_data = dict(getattr(musetalk_state, "current_musetalk_frame_data", {}) or {})
    previous_pipeline_data = dict(musetalk_state.get_musetalk_pipeline_snapshot() or {})
    musetalk_state.current_musetalk_frame_data = {
        "frame_path": str(frame_path),
        "frame_paths": [str(frame_path)],
        "fps": 12,
        "status": "previewing",
        "chunk_id": "smoke_chunk",
        "text": "smoke frame",
    }
    musetalk_state.current_musetalk_pipeline_data = {
        "reply_id": 1,
        "active": True,
        "stream_mode": True,
        "stream_open": True,
        "chunks": [],
        "updated_at": 1.0,
    }

    def restore() -> None:
        musetalk_state.current_musetalk_frame_data = previous_frame_data
        musetalk_state.current_musetalk_pipeline_data = previous_pipeline_data

    return restore


def _read_ws_frame(sock: socket.socket, buffer: bytearray | None = None):
    header = _recv_exact(sock, 2, buffer)
    if not header:
        raise RuntimeError("websocket closed")
    first, second = header[0], header[1]
    opcode = first & 0x0F
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", _recv_exact(sock, 2, buffer))[0]
    elif length == 127:
        length = struct.unpack("!Q", _recv_exact(sock, 8, buffer))[0]
    payload = _recv_exact(sock, length, buffer) if length else b""
    return opcode, payload


def _recv_exact(sock: socket.socket, length: int, buffer: bytearray | None = None) -> bytes:
    chunks = []
    remaining = int(length)
    if buffer:
        prefix = bytes(buffer[:remaining])
        del buffer[:remaining]
        chunks.append(prefix)
        remaining -= len(prefix)
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise RuntimeError("socket closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _send_ws_client_frame(sock: socket.socket, opcode: int, body: bytes, *, split_header: bool = False) -> None:
    mask = os.urandom(4)
    header = bytearray([0x80 | (int(opcode) & 0x0F)])
    length = len(body)
    if length < 126:
        header.append(0x80 | length)
    elif length <= 0xFFFF:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", length))
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(body))
    packet = bytes(header) + mask + masked
    if split_header and len(packet) > 1:
        sock.sendall(packet[:1])
        time.sleep(0.35)
        sock.sendall(packet[1:])
        return
    sock.sendall(packet)


def _send_ws_text(sock: socket.socket, text: str, *, split_header: bool = False) -> None:
    _send_ws_client_frame(sock, 0x1, text.encode("utf-8"), split_header=split_header)


def _send_ws_unmasked_text(sock: socket.socket, text: str) -> None:
    body = text.encode("utf-8")
    length = len(body)
    header = bytearray([0x81])
    if length < 126:
        header.append(length)
    elif length <= 0xFFFF:
        header.append(126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", length))
    sock.sendall(bytes(header) + body)


def _send_ws_ping(sock: socket.socket, payload: bytes = b"ping") -> None:
    _send_ws_client_frame(sock, 0x9, payload)


def _send_ws_close(sock: socket.socket) -> None:
    _send_ws_client_frame(sock, 0x8, b"")


def _websocket_smoke(port: int, code: str) -> None:
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        request = (
            f"GET /ws?code={code} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            response += sock.recv(4096)
        _headers, _separator, remainder = response.partition(b"\r\n\r\n")
        frame_buffer = bytearray(remainder)
        assert b"101 Switching Protocols" in response
        opcode, payload = _read_ws_frame(sock, frame_buffer)
        assert opcode == 0x1
        hello = json.loads(payload.decode("utf-8"))
        assert hello["type"] == "hello"
        assert "clients" not in hello["remote"]
        assert "bridge_url" not in hello["remote"]
        _send_ws_ping(sock, b"phone")
        _read_ws_pong(sock, frame_buffer, b"phone")
        _send_ws_text(sock, json.dumps({"type": "state"}))
        message = _read_ws_json_type(sock, frame_buffer, {"state", "error"})
        assert message["type"] in {"state", "error"}
        send_request_id = "smoke-send-1"
        _send_ws_text(sock, json.dumps({"type": "send_text", "request_id": send_request_id, "text": "websocket smoke"}))
        send_result = _read_ws_json_type(sock, frame_buffer, {"send_result"}, max_frames=8)
        assert send_result["request_id"] == send_request_id
        assert send_result["payload"]["ok"] is True
        assert send_result["payload"]["result"]["accepted"] is True
        control_request_id = "smoke-control-1"
        _send_ws_text(sock, json.dumps({"type": "control", "request_id": control_request_id, "action": "pause_speech"}))
        control_result = _read_ws_json_type(sock, frame_buffer, {"control_result"}, max_frames=8)
        assert control_result["request_id"] == control_request_id
        assert control_result["payload"]["ok"] is True
        assert control_result["payload"]["result"]["accepted"] is True
        visual_request_id = "smoke-visual-1"
        _send_ws_text(sock, json.dumps({"type": "visual", "request_id": visual_request_id, "payload": {"action": "snapshot"}}))
        visual_result = _read_ws_json_type(sock, frame_buffer, {"visual_result"}, max_frames=8)
        assert visual_result["request_id"] == visual_request_id
        assert visual_result["payload"]["ok"] is True
        assert visual_result["payload"]["result"]["accepted"] is True
        engine_start_request_id = "smoke-engine-start-1"
        _send_ws_text(sock, json.dumps({"type": "engine_start", "request_id": engine_start_request_id}))
        engine_start_result = _read_ws_json_type(sock, frame_buffer, {"engine_start_result"}, max_frames=8)
        assert engine_start_result["request_id"] == engine_start_request_id
        assert engine_start_result["payload"]["ok"] is True
        assert engine_start_result["payload"]["result"]["accepted"] is True
        engine_stop_request_id = "smoke-engine-stop-1"
        _send_ws_text(sock, json.dumps({"type": "engine_stop", "request_id": engine_stop_request_id}))
        engine_stop_result = _read_ws_json_type(sock, frame_buffer, {"engine_stop_result"}, max_frames=8)
        assert engine_stop_result["request_id"] == engine_stop_request_id
        assert engine_stop_result["payload"]["ok"] is True
        assert engine_stop_result["payload"]["result"]["accepted"] is True
        _send_ws_text(sock, json.dumps({"type": "split_header_probe"}), split_header=True)
        error_message = _read_ws_json_type(sock, frame_buffer, {"error"}, max_frames=8)
        assert "Unsupported message type" in str(error_message.get("error") or "")
        _send_ws_unmasked_text(sock, json.dumps({"type": "state"}))
        protocol_error = _read_ws_json_type(sock, frame_buffer, {"error"}, max_frames=3)
        assert "masked" in str(protocol_error.get("error") or "").lower()


def _read_ws_json_type(sock: socket.socket, buffer: bytearray, types: set[str], *, max_frames: int = 5) -> dict:
    for _index in range(max(1, int(max_frames))):
        opcode, payload = _read_ws_frame(sock, buffer)
        if opcode != 0x1:
            continue
        message = json.loads(payload.decode("utf-8"))
        if str(message.get("type") or "") in types:
            return message
    raise AssertionError(f"WebSocket did not return one of {sorted(types)}")


def _read_ws_pong(sock: socket.socket, buffer: bytearray, expected: bytes, *, max_frames: int = 5) -> None:
    for _index in range(max(1, int(max_frames))):
        opcode, payload = _read_ws_frame(sock, buffer)
        if opcode == 0xA and payload == expected:
            return
    raise AssertionError("WebSocket did not return pong")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        context = _Context(root)
        controller = MainChatRemoteController(context)
        port = free_local_port()
        settings = BridgeSettings(enabled=True, port=port).normalized()
        bridge = MainChatBridgeServer(controller, settings)
        backend_port = free_local_port()
        pairing_code = "123456"
        backend = MainChatRemoteBackend(
            host="127.0.0.1",
            port=backend_port,
            pairing_code=pairing_code,
            bridge_url=f"http://127.0.0.1:{port}",
            bridge_token=settings.token,
        )
        bridge.start()
        backend.start()
        restore_musetalk = lambda: None
        try:
            bridge_options_status, bridge_options = _options_json(f"http://127.0.0.1:{port}/api/state")
            assert bridge_options_status == 200
            assert bridge_options["ok"] is True
            backend_options_status, backend_options = _options_json(f"http://127.0.0.1:{backend_port}/api/state")
            assert backend_options_status == 200
            assert backend_options["ok"] is True
            health = _read_json(f"http://127.0.0.1:{port}/health", settings.token)
            assert health["ok"] is True
            state = _read_json(f"http://127.0.0.1:{port}/api/state", settings.token)
            assert state["ok"] is True
            assert state["state"]["chat"]["message_count"] == 2
            assert state["state"]["visual"]["service_available"] is True
            assert state["state"]["musetalk"]["stream_url_path"] == "/api/musetalk/stream"
            query_token_status, query_token_payload = _read_http_json(
                f"http://127.0.0.1:{port}/api/state?token={settings.token}",
                timeout=2.0,
            )
            assert query_token_status == 401
            assert query_token_payload["ok"] is False
            assert query_token_payload["error"] == "Unauthorized"
            query_token_header_status, query_token_header_payload = _read_http_json(
                f"http://127.0.0.1:{port}/api/state?token={settings.token}",
                timeout=2.0,
                headers={"X-NC-Bridge-Token": settings.token},
            )
            assert query_token_header_status == 401
            assert query_token_header_payload["ok"] is False
            assert query_token_header_payload["error"] == "Unauthorized"
            rejected_status, rejected_payload = _read_phone_json_status(
                f"http://127.0.0.1:{backend_port}/api/state",
                "0000",
            )
            assert rejected_status == 401
            assert rejected_payload["ok"] is False
            assert rejected_payload["error"] == "Unauthorized"
            result = controller.remote_send_text("from phone")
            assert result["accepted"] is True
            assert context.get_service("qt.shell").sent == ["from phone"]

            source = root / "source.wav"
            _write_wav(source)

            text_only_send = controller.remote_send_text(
                "text only",
                {"capture_phone_audio": False, "play_on_backend": False},
            )
            assert text_only_send["accepted"] is True
            text_only_capture = controller.invoke_capability(
                "tts.audio_chunk_ready",
                {"audio_path": str(source), "text": "text only reply", "sample_rate": 16000},
            )
            assert text_only_capture["captured"] is False
            assert text_only_capture["skip_local_playback"] is True
            text_only_audio = controller.media_snapshot()
            assert text_only_audio["available"] is False
            assert text_only_audio["items"] == []

            backend_audio_send = controller.remote_send_text(
                "phone and computer",
                {"capture_phone_audio": True, "play_on_backend": True},
            )
            assert backend_audio_send["accepted"] is True
            backend_audio_capture = controller.invoke_capability(
                "tts.audio_chunk_ready",
                {"audio_path": str(source), "text": "phone and computer reply", "sample_rate": 16000},
            )
            assert backend_audio_capture["captured"] is True
            assert backend_audio_capture["skip_local_playback"] is False
            assert controller.media_snapshot()["items"]
            cleared_audio = controller.remote_audio_clear()
            assert cleared_audio["accepted"] is True
            assert cleared_audio["audio"]["items"] == []

            replay_capture = controller.remote_control(
                "replay_last_assistant",
                {"capture_phone_audio": False, "play_on_backend": False},
            )
            assert replay_capture["accepted"] is True
            assert context.get_service("qt.runtime_controls").last_action == "replay_last_assistant"
            replay_chunk = controller.invoke_capability(
                "tts.audio_chunk_ready",
                {"audio_path": str(source), "text": "replay reply", "sample_rate": 16000},
            )
            assert replay_chunk["captured"] is False
            assert replay_chunk["skip_local_playback"] is True

            controller.media_bridge.begin_tts_capture("from phone", suppress_backend_playback=True)
            captured = controller.invoke_capability(
                "tts.audio_chunk_ready",
                {"audio_path": str(source), "text": "hi", "sample_rate": 16000, "source_meta": {"display_name": "Assistant"}},
            )
            assert captured["captured"] is True
            assert captured["skip_local_playback"] is True
            audio = controller.media_snapshot()
            assert audio["available"] is True
            audio_id = audio["items"][0]["id"]
            assert controller.audio_file_path(audio_id).exists()
            phone_audio = _read_url_bytes(
                f"http://127.0.0.1:{backend_port}/api/audio/file/{audio_id}?code={pairing_code}",
                32,
            )
            assert phone_audio.startswith(b"RIFF")
            rejected_audio_status, rejected_audio_payload = _read_http_json(
                f"http://127.0.0.1:{backend_port}/api/audio/file/{audio_id}?code=0000"
            )
            assert rejected_audio_status == 401
            assert rejected_audio_payload["ok"] is False
            assert rejected_audio_payload["error"] == "Unauthorized"

            phone_state = _read_phone_json(f"http://127.0.0.1:{backend_port}/api/state", pairing_code)
            assert phone_state["ok"] is True
            assert phone_state["state"]["features"]["text_send"] is True
            assert phone_state["state"]["runtime_settings"]["chat_provider"] == "smoke-llm"
            assert phone_state["state"]["runtime_settings"]["stt_backend"] == "smoke-stt"
            assert phone_state["state"]["runtime_settings"]["tts_backend"] == "smoke-tts"
            assert phone_state["state"]["runtime_settings"]["visual_reply_provider"] == "smoke-visual"
            assert phone_state["state"]["visual"]["service_available"] is True
            assert phone_state["state"]["musetalk"]["stream_url_path"] == "/api/musetalk/stream"
            assert phone_state["state"]["features"]["mprc_story_mode"] is True
            assert phone_state["state"]["mprc"]["available"] is True
            assert phone_state["state"]["mprc"]["session"]["scene_title"] == "Smoke Scene"
            assert phone_state["state"]["mprc"]["segments"][1]["speaker_name"] == "Guide"
            assert phone_state["state"]["mprc"]["visual"]["latest_prompt"].startswith("Guide watches")
            assert phone_state["state"]["mprc"]["cast"]["devices"][0]["name"] == "Living Room TV"
            assert phone_state["state"]["mprc"]["memory"]["backend"] == "sqlite"
            assert phone_state["state"]["mprc"]["memory"]["event_count"] == 5
            assert phone_state["state"]["mprc"]["memory"]["databank_available"] is True
            assert str(root) not in json.dumps(phone_state)
            phone_send = _post_phone_json(
                f"http://127.0.0.1:{backend_port}/api/send",
                pairing_code,
                {"text": "through lan backend", "play_on_backend": True, "capture_phone_audio": True},
            )
            assert phone_send["ok"] is True
            assert phone_send["result"]["accepted"] is True
            phone_mprc = _read_phone_json(f"http://127.0.0.1:{backend_port}/api/mprc", pairing_code)
            assert phone_mprc["ok"] is True
            assert phone_mprc["mprc"]["available"] is True
            phone_mprc_send = _post_phone_json(
                f"http://127.0.0.1:{backend_port}/api/mprc/send",
                pairing_code,
                {"text": "story turn from phone", "intent": "Continue", "speaker_id": "guide"},
            )
            assert phone_mprc_send["ok"] is True
            assert phone_mprc_send["result"]["accepted"] is True
            assert (
                "mprc.remote_send",
                {"text": "story turn from phone", "intent": "Continue", "speaker_id": "guide"},
            ) in context.get_service("addons.capabilities").calls
            phone_mprc_cast = _post_phone_json(
                f"http://127.0.0.1:{backend_port}/api/mprc/cast",
                pairing_code,
                {"action": "start", "device_name": "Living Room TV"},
            )
            assert phone_mprc_cast["ok"] is True
            assert phone_mprc_cast["result"]["accepted"] is True
            assert phone_mprc_cast["result"]["cast"]["casting"] is True
            assert (
                "mprc.remote_cast",
                {"action": "start", "device_name": "Living Room TV"},
            ) in context.get_service("addons.capabilities").calls
            phone_engine_start = _post_phone_json(
                f"http://127.0.0.1:{backend_port}/api/engine/start",
                pairing_code,
                {},
            )
            assert phone_engine_start["ok"] is True
            assert phone_engine_start["result"]["accepted"] is True
            assert phone_engine_start["result"]["engine"]["running"] is True
            phone_engine_stop = _post_phone_json(
                f"http://127.0.0.1:{backend_port}/api/engine/stop",
                pairing_code,
                {},
            )
            assert phone_engine_stop["ok"] is True
            assert phone_engine_stop["result"]["accepted"] is True
            assert phone_engine_stop["result"]["engine"]["running"] is False

            stt_payload = base64.b64encode(source.read_bytes()).decode("ascii")
            phone_stt = _post_phone_json(
                f"http://127.0.0.1:{backend_port}/api/stt",
                pairing_code,
                {"audio_base64": stt_payload, "format": "wav", "send_to_chat": False},
            )
            assert phone_stt["ok"] is True
            assert phone_stt["result"]["text"] == "transcribed smoke"
            assert "audio_path" not in phone_stt["result"]
            assert phone_stt["result"]["audio_cached"] is True

            frame_path = root / "musetalk_frame.png"
            _write_png(frame_path)
            restore_musetalk = _install_musetalk_frame(frame_path)

            visual = _read_phone_json(f"http://127.0.0.1:{backend_port}/api/visual", pairing_code)
            assert visual["ok"] is True
            assert visual["visual"]["service_available"] is True
            visual_request = _post_phone_json(
                f"http://127.0.0.1:{backend_port}/api/visual",
                pairing_code,
                {"prompt": "smoke visual"},
            )
            assert visual_request["ok"] is True
            assert visual_request["result"]["accepted"] is True
            visual_request_id = visual_request["result"]["request_id"]
            assert visual_request["result"]["visual"]["latest_request"]["request_id"] == visual_request_id
            visual_latest = _wait_for_visual_request_status(controller, visual_request_id, {"done"})
            assert visual_latest["status"] == "done"
            visual_last = _post_phone_json(
                f"http://127.0.0.1:{backend_port}/api/visual",
                pairing_code,
                {"action": "generate_last"},
            )
            assert visual_last["ok"] is True
            assert visual_last["result"]["accepted"] is True
            assert context.get_service("qt.visual_reply").requests[-1]["prompt"] == "hi"
            visual_show = _post_phone_json(
                f"http://127.0.0.1:{backend_port}/api/visual",
                pairing_code,
                {"action": "show"},
            )
            assert visual_show["ok"] is True
            assert visual_show["result"]["accepted"] is True
            assert context.get_service("qt.visual_reply").visible is True
            visual_clear = _post_phone_json(
                f"http://127.0.0.1:{backend_port}/api/visual",
                pairing_code,
                {"action": "clear"},
            )
            assert visual_clear["ok"] is True
            assert visual_clear["result"]["accepted"] is True
            assert context.get_service("qt.visual_reply").clear_count == 1

            musetalk = _read_phone_json(f"http://127.0.0.1:{backend_port}/api/musetalk", pairing_code)
            assert musetalk["ok"] is True
            assert "state" in musetalk["musetalk"]
            assert musetalk["musetalk"]["stream_url_path"] == "/api/musetalk/stream"
            assert musetalk["musetalk"]["state"]["stream_url_path"] == "/api/musetalk/stream"
            assert "frame_path" not in json.dumps(musetalk)
            assert str(frame_path) not in json.dumps(musetalk)
            stream = _read_phone_bytes(
                f"http://127.0.0.1:{backend_port}/api/musetalk/stream?frames=1&fps=2",
                pairing_code,
                512,
            )
            assert stream.startswith(b"--nc_musetalk_frame")
            assert b"Content-Type: image/png" in stream
            readiness = controller.backend_process.probe_health(host="127.0.0.1", port=backend_port)
            assert readiness["ok"] is True
            assert readiness["payload"]["remote"]["pairing_code_digits"] == len(pairing_code)
            assert "clients" not in readiness["payload"]["remote"]
            assert "bridge_url" not in readiness["payload"]["remote"]
            assert "url" not in json.dumps(readiness["payload"]["bridge"])
            assert "token_configured" not in json.dumps(readiness["payload"]["bridge"])
            _websocket_smoke(backend_port, pairing_code)
        finally:
            restore_musetalk()
            backend.stop()
            bridge.stop()
            controller.shutdown()
        _addon_manager_smoke(root)
        _addon_capability_payload_isolation_smoke(root)
        _backend_process_smoke(root)
        _controller_backend_task_smoke(root)
        _bridge_info_lifecycle_smoke(root)
        _controller_shutdown_timer_smoke(root)
        _stt_upload_retention_smoke(root)
        _stt_upload_unavailable_no_cache_smoke(root)
        _media_bridge_retention_smoke(root)
        _media_bridge_auto_capture_smoke(root)
        _media_bridge_audio_format_smoke(root)
        _stt_result_normalization_smoke()
        _stt_upload_serialization_smoke(root)
        _phone_status_redaction_smoke(root)
        _phone_safe_payload_smoke(root)
        _remote_control_fallback_allowlist_smoke(root)
        _visual_request_tracking_smoke(root)
        _remote_state_phone_safe_smoke(root)
        _engine_tts_audio_chunk_ready_fanout_smoke()
        _backend_venv_helper_smoke(root)
        _backend_pairing_output_smoke()
        _bridge_info_load_smoke(root)
        _remote_backend_main_bridge_info_smoke(root)
        _backend_bridge_unavailable_smoke()
        _backend_auth_throttle_smoke()
        _websocket_handshake_validation_smoke()
        _websocket_state_bridge_timeout_smoke()
    print("main_chat_remote smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
