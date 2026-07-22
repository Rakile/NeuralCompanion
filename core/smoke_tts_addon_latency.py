"""Regression probes for addon work on the normal-chat TTS critical path."""

from __future__ import annotations

import os
import json
import queue
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = str(Path(__file__).resolve().parent)
sys.path[:] = [entry for entry in sys.path if str(Path(entry or ".").resolve()) != SCRIPT_DIR]
sys.path[:] = [entry for entry in sys.path if str(Path(entry or ".").resolve()) != str(ROOT)]
sys.path.insert(0, str(ROOT))


MAX_CRITICAL_PATH_SECONDS = 0.20


def _assert_returns_while_slow_work_is_blocked(
    callback,
    *,
    slow_work_entered: threading.Event,
    release_slow_work: threading.Event,
) -> object:
    completed = threading.Event()
    result: dict[str, object] = {}

    def invoke() -> None:
        try:
            result["value"] = callback()
        except BaseException as exc:  # pragma: no cover - surfaced below
            result["error"] = exc
        finally:
            completed.set()

    thread = threading.Thread(target=invoke, name="nc-tts-addon-latency-probe", daemon=True)
    thread.start()
    try:
        assert slow_work_entered.wait(1.0), "The simulated slow addon work did not start"
        assert completed.wait(MAX_CRITICAL_PATH_SECONDS), (
            "Addon capability blocked normal-chat TTS while unrelated slow work was in progress"
        )
    finally:
        release_slow_work.set()
        thread.join(timeout=1.0)
    if "error" in result:
        raise result["error"]  # type: ignore[misc]
    return result.get("value")


def test_spotify_duck_start_does_not_wait_for_web_api() -> None:
    from addons.spotify_sense.controller import SpotifySenseController

    entered = threading.Event()
    release = threading.Event()
    volume_calls: list[tuple[int, str | None]] = []

    class _Client:
        def get_playback_state(self):
            entered.set()
            release.wait(2.0)
            return {
                "ok": True,
                "data": {"device": {"id": "active-device", "volume_percent": 55}},
            }

        def set_volume(self, percent, device_id=None):
            volume_calls.append((int(percent), device_id))
            return {"ok": True, "percent": int(percent), "device_id": device_id}

    controller = SpotifySenseController.__new__(SpotifySenseController)
    controller.settings = SimpleNamespace(
        data={
            "duck_while_speaking": True,
            "restore_volume_after_speech": True,
            "default_device_id": "configured-device",
            "default_volume": 44,
            "duck_volume_percent": 12,
            "duck_fade_down_ms": 0,
            "duck_fade_up_ms": 0,
        }
    )
    controller.client = _Client()
    controller._remembered_volume = None
    controller._remembered_duck_device_id = None
    controller._duck_transition_lock = threading.RLock()
    controller._duck_transition_generation = 0
    controller._debug_log = lambda *_args, **_kwargs: None

    result = _assert_returns_while_slow_work_is_blocked(
        controller.duck_start,
        slow_work_entered=entered,
        release_slow_work=release,
    )
    assert isinstance(result, dict) and result.get("ok") is True

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not volume_calls:
        time.sleep(0.01)
    assert volume_calls, "Queued Spotify ducking never reached the volume operation"


def _mprc_probe():
    from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

    probe = object.__new__(MultiPersonaRoleplayController)
    probe._state_lock = threading.RLock()
    probe._shutting_down = False
    probe._worker_sequence = 0
    probe._active_worker_tokens = set()
    probe._worker_threads = {}
    probe._assistant_reply_serial_lock = threading.Lock()
    probe._request_ui_refresh = lambda: None
    probe.session = SimpleNamespace(enabled=True)
    probe.mprc_play_isolated_active = lambda: False
    return probe


def test_mprc_unsupported_tts_hook_does_not_wait_for_state_lock() -> None:
    probe = _mprc_probe()
    lock_held = threading.Event()
    release = threading.Event()

    def hold_lock() -> None:
        with probe._state_lock:
            lock_held.set()
            release.wait(2.0)

    holder = threading.Thread(target=hold_lock, name="nc-mprc-lock-holder", daemon=True)
    holder.start()
    assert lock_held.wait(1.0)

    completed = threading.Event()
    result: dict[str, object] = {}

    def invoke() -> None:
        result["value"] = probe.invoke_capability_threadsafe("tts.duck.start", {})
        completed.set()

    caller = threading.Thread(target=invoke, name="nc-mprc-unsupported-hook", daemon=True)
    caller.start()
    try:
        assert completed.wait(MAX_CRITICAL_PATH_SECONDS), (
            "MPRC waited for its state lock before rejecting an unsupported TTS capability"
        )
        assert result.get("value") is None
    finally:
        release.set()
        holder.join(timeout=1.0)
        caller.join(timeout=1.0)


def test_mprc_assistant_reply_processing_is_queued() -> None:
    probe = _mprc_probe()
    entered = threading.Event()
    release = threading.Event()

    def record_assistant_text(*_args, **_kwargs):
        entered.set()
        release.wait(2.0)
        return True

    probe.roleplay_engine = SimpleNamespace(record_assistant_text=record_assistant_text)
    result = _assert_returns_while_slow_work_is_blocked(
        lambda: probe.invoke_capability_threadsafe(
            "roleplay.assistant_reply",
            {"text": "A completed normal-chat response."},
        ),
        slow_work_entered=entered,
        release_slow_work=release,
    )
    assert isinstance(result, dict) and result.get("queued") is True


def test_mprc_assistant_reply_queue_does_not_wait_for_state_lock() -> None:
    probe = _mprc_probe()
    probe.roleplay_engine = SimpleNamespace(record_assistant_text=lambda *_args, **_kwargs: True)
    lock_held = threading.Event()
    release = threading.Event()

    def hold_lock() -> None:
        with probe._state_lock:
            lock_held.set()
            release.wait(2.0)

    holder = threading.Thread(target=hold_lock, name="nc-mprc-reply-lock-holder", daemon=True)
    holder.start()
    assert lock_held.wait(1.0)
    completed = threading.Event()
    result: dict[str, object] = {}

    def invoke() -> None:
        result["value"] = probe.invoke_capability_threadsafe(
            "roleplay.assistant_reply",
            {"text": "A completed normal-chat response."},
        )
        completed.set()

    caller = threading.Thread(target=invoke, name="nc-mprc-reply-queue", daemon=True)
    caller.start()
    try:
        assert completed.wait(MAX_CRITICAL_PATH_SECONDS), (
            "MPRC waited for its state lock before queueing assistant-reply bookkeeping"
        )
        assert isinstance(result.get("value"), dict) and result["value"].get("queued") is True
    finally:
        release.set()
        holder.join(timeout=1.0)
        caller.join(timeout=1.0)


def test_mprc_voice_route_debug_does_not_wait_for_disk() -> None:
    from addons.multi_persona_roleplay.voice_routing import PersonaVoiceRouter

    entered = threading.Event()
    release = threading.Event()
    router = PersonaVoiceRouter(SimpleNamespace(context=SimpleNamespace(logger=None)))

    with tempfile.TemporaryDirectory(prefix="nc-mprc-voice-debug-") as temp_dir:
        log_path = Path(temp_dir) / "voice_route.jsonl"

        def slow_log_path() -> Path:
            entered.set()
            release.wait(2.0)
            return log_path

        router._voice_route_log_path = slow_log_path
        _assert_returns_while_slow_work_is_blocked(
            lambda: router._write_voice_route_debug({}, "Narrator reply", {"segments": []}, []),
            slow_work_entered=entered,
            release_slow_work=release,
        )

        worker = getattr(router, "_voice_route_debug_thread", None)
        if worker is not None:
            worker.join(timeout=1.0)


def test_mprc_remote_audio_copy_does_not_block_playback() -> None:
    from addons.multi_persona_roleplay import controller as controller_module
    from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

    entered = threading.Event()
    release = threading.Event()
    original_copy = controller_module.shutil.copy2

    with tempfile.TemporaryDirectory(prefix="nc-mprc-remote-audio-") as temp_dir:
        root = Path(temp_dir)
        source_path = root / "source.wav"
        source_path.write_bytes(b"RIFF-test-wave")

        probe = object.__new__(MultiPersonaRoleplayController)
        probe.context = SimpleNamespace(logger=None)
        probe.settings = {"remote_enabled": True}
        probe._remote_server_installed = lambda: True
        probe._remote_audio_lock = threading.RLock()
        probe._remote_audio_generation = 1
        probe._remote_audio_capture_until = time.time() + 60.0
        probe._remote_audio_items = []
        probe._remote_audio_status = "rendering"
        probe._remote_audio_source_excerpt = ""
        probe._remote_audio_capture_index = 0
        probe._remote_audio_copy_queue = queue.Queue(maxsize=64)
        probe._remote_audio_copy_thread = None
        probe._remote_audio_cache_dir = lambda: root / "cache"
        probe._wav_duration_seconds = lambda _path: 0.25

        def slow_copy(source, target):
            entered.set()
            release.wait(2.0)
            Path(target).parent.mkdir(parents=True, exist_ok=True)
            return original_copy(source, target)

        controller_module.shutil.copy2 = slow_copy
        try:
            result = _assert_returns_while_slow_work_is_blocked(
                lambda: probe.handle_tts_audio_chunk_ready(
                    {
                        "audio_path": str(source_path),
                        "text": "First chunk",
                        "source_meta": {"persona_id": "mira", "display_name": "Mira"},
                    }
                ),
                slow_work_entered=entered,
                release_slow_work=release,
            )
        finally:
            controller_module.shutil.copy2 = original_copy

        assert result is True
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not probe._remote_audio_items:
            time.sleep(0.01)
        assert probe._remote_audio_items, "Queued phone-audio copy did not complete"


def test_mprc_segment_state_save_does_not_block_playback() -> None:
    from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

    entered = threading.Event()
    release = threading.Event()
    persona = SimpleNamespace(id="mira")
    probe = object.__new__(MultiPersonaRoleplayController)
    probe._state_lock = threading.RLock()
    probe._shutting_down = False
    probe._state_save_queue_lock = threading.RLock()
    probe._state_save_pending = False
    probe._state_save_thread = None
    probe._tts_generation_ids = set()
    probe._pending_tts_persona_visuals = []
    probe.session = SimpleNamespace(
        current_speaker_id="",
        ar_state=SimpleNamespace(active_characters=[]),
    )
    probe.settings = {"show_current_character_visual": False}
    probe.persona_by_id = lambda _persona_id: persona
    probe._add_persona_to_active_character_state = lambda persona_id: probe.session.ar_state.active_characters.append(persona_id)
    probe._request_ui_refresh = lambda: None
    probe._maybe_generate_character_image_during_tts = lambda _persona: None
    probe._maybe_generate_visual_reply_during_tts = lambda _persona, _text: None

    def slow_save_state() -> None:
        entered.set()
        release.wait(2.0)

    probe.save_state = slow_save_state
    _assert_returns_while_slow_work_is_blocked(
        lambda: probe.handle_tts_persona_visual("mira", "Hello"),
        slow_work_entered=entered,
        release_slow_work=release,
    )

    worker = getattr(probe, "_state_save_thread", None)
    if worker is not None:
        worker.join(timeout=1.0)


def test_mprc_visual_generation_waits_for_tts_prebuffering() -> None:
    from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

    persona = SimpleNamespace(id="mira")
    probe = object.__new__(MultiPersonaRoleplayController)
    probe._state_lock = threading.RLock()
    probe._shutting_down = False
    probe._tts_generation_ids = set()
    probe._pending_tts_persona_visuals = []
    probe.session = SimpleNamespace(
        enabled=True,
        current_speaker_id="",
        ar_state=SimpleNamespace(active_characters=[]),
    )
    probe.settings = {"show_current_character_visual": True}
    probe.persona_by_id = lambda persona_id: persona if persona_id == "mira" else None
    probe._add_persona_to_active_character_state = lambda persona_id: probe.session.ar_state.active_characters.append(persona_id)
    probe._queue_state_save = lambda: None
    probe._request_ui_refresh = lambda: None
    calls: list[tuple[str, str]] = []
    probe._maybe_generate_character_image_during_tts = lambda item: calls.append(("character", item.id))
    probe._maybe_generate_visual_reply_during_tts = lambda item, text: calls.append(("reply", f"{item.id}:{text}"))

    probe.handle_tts_generation_started({"trace_id": "trace-a"})
    probe.handle_tts_persona_visual("mira", "Hello from Mira")

    assert calls == [], "MPRC started visual work while TTS was still prebuffering"
    assert probe._pending_tts_persona_visuals == [("mira", "Hello from Mira")]

    probe.handle_tts_generation_finished({"trace_id": "trace-a"})

    assert calls == [("character", "mira"), ("reply", "mira:Hello from Mira")]
    assert probe._pending_tts_persona_visuals == []

    calls.clear()
    probe.handle_tts_generation_started({"trace_id": "trace-b"})
    probe.handle_tts_persona_visual("mira", "Cancelled visual")
    probe.session.enabled = False
    probe.invoke_capability_threadsafe("tts.generation_finished", {"trace_id": "trace-b"})

    assert probe._tts_generation_ids == set()
    assert probe._pending_tts_persona_visuals == []
    assert calls == [], "MPRC released deferred visuals after it was disabled"


def test_mprc_isolated_play_uses_completed_turn_visual_only() -> None:
    from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

    persona = SimpleNamespace(id="lilith")
    probe = object.__new__(MultiPersonaRoleplayController)
    probe.settings = {"show_current_character_visual": True}
    probe.mprc_play_isolated_active = lambda: True
    calls: list[tuple[str, str]] = []
    probe._maybe_generate_character_image_during_tts = lambda item: calls.append(("character", item.id))
    probe._maybe_generate_visual_reply_during_tts = lambda item, text: calls.append(("reply", f"{item.id}:{text}"))

    probe._start_tts_persona_visuals(persona, "Lilith enters the alley")

    assert calls == [("character", "lilith")], (
        "Isolated MPRC Play must keep character-picture updates without starting a competing per-segment Visual Reply"
    )


def test_buddy_completed_reply_does_not_wait_for_settings_disk() -> None:
    from addons.buddy_chat.controller import BuddyChatController
    from addons.buddy_chat.models import BuddySettings

    entered = threading.Event()
    release = threading.Event()

    class _Storage:
        def write_json(self, *_args, **_kwargs):
            entered.set()
            release.wait(2.0)

    probe = object.__new__(BuddyChatController)
    probe.context = SimpleNamespace(storage=_Storage(), logger=None)
    probe.settings = BuddySettings.default()
    probe.settings.enabled = True
    probe._state_lock = threading.RLock()
    probe._shutting_down = False
    probe._last_session_export_state = probe._session_export_payload_unlocked()
    probe._settings_write_lock = threading.RLock()
    probe._pending_settings_payload = None
    probe._settings_write_thread = None

    result = _assert_returns_while_slow_work_is_blocked(
        lambda: probe.invoke_capability_threadsafe(
            "buddy_chat.assistant_reply",
            {"text": "A completed normal-chat response."},
        ),
        slow_work_entered=entered,
        release_slow_work=release,
    )
    assert isinstance(result, dict) and result.get("recorded") is True
    assert result.get("completed_reply_count") == 1


def test_addon_manager_writes_bounded_tts_latency_trace() -> None:
    from core.addons.manager import AddonManager, LoadedAddon
    from core.addons.manifest import AddonManifest

    class _SlowAddon:
        def invoke_capability(self, _capability, _payload=None):
            time.sleep(0.03)
            return {"ok": True}

    with tempfile.TemporaryDirectory(prefix="nc-tts-latency-trace-") as temp_dir:
        root = Path(temp_dir)
        addon_root = root / "addons" / "slow_addon"
        addon_root.mkdir(parents=True)
        manifest = AddonManifest(
            id="nc.slow_probe",
            name="Slow Probe",
            version="1.0.0",
            entry_point="main.py",
            enabled=True,
            manifest_path=addon_root / "addon.json",
        )
        manager = AddonManager(
            app_root=root,
            llm_snapshot_getter=lambda: {},
            tts_snapshot_getter=lambda: {},
            avatar_snapshot_getter=lambda: {},
        )
        manager._records = [
            LoadedAddon(
                manifest=manifest,
                root_dir=addon_root,
                instance=_SlowAddon(),
                state="initialized",
            )
        ]

        manager.invoke_all_capabilities("tts.duck.start", {"secret": "must-not-be-recorded"})
        manager.record_latency_event(
            "tts_pipeline_start",
            trace_id="probe-1",
            backend="chatterbox",
            input_chars=24,
        )
        assert manager.flush_latency_diagnostics(timeout=1.0)
        trace_path = root / "runtime" / "logs" / "tts_addon_latency.jsonl"
        rows = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        manager.close_latency_diagnostics()

        addon_rows = [row for row in rows if row.get("event") == "addon_capability"]
        assert addon_rows
        row = addon_rows[-1]
        assert row["addon_id"] == "nc.slow_probe"
        assert row["capability"] == "tts.duck.start"
        assert float(row["duration_ms"]) >= 20.0
        assert "secret" not in json.dumps(row).lower()
        pipeline_rows = [row for row in rows if row.get("event") == "tts_pipeline_start"]
        assert pipeline_rows and pipeline_rows[-1]["trace_id"] == "probe-1"


def test_addon_manager_unload_closes_latency_writer() -> None:
    from core.addons.manager import AddonManager

    with tempfile.TemporaryDirectory(prefix="nc-tts-latency-shutdown-") as temp_dir:
        manager = AddonManager(
            app_root=Path(temp_dir),
            llm_snapshot_getter=lambda: {},
            tts_snapshot_getter=lambda: {},
            avatar_snapshot_getter=lambda: {},
        )
        diagnostics = manager._latency_diagnostics
        assert diagnostics._thread.is_alive()

        manager.unload_all()

        diagnostics._thread.join(timeout=1.0)
        assert diagnostics._closed is True
        assert not diagnostics._thread.is_alive()


def main() -> None:
    test_spotify_duck_start_does_not_wait_for_web_api()
    test_mprc_unsupported_tts_hook_does_not_wait_for_state_lock()
    test_mprc_assistant_reply_processing_is_queued()
    test_mprc_assistant_reply_queue_does_not_wait_for_state_lock()
    test_mprc_voice_route_debug_does_not_wait_for_disk()
    test_mprc_remote_audio_copy_does_not_block_playback()
    test_mprc_segment_state_save_does_not_block_playback()
    test_mprc_visual_generation_waits_for_tts_prebuffering()
    test_mprc_isolated_play_uses_completed_turn_visual_only()
    test_buddy_completed_reply_does_not_wait_for_settings_disk()
    test_addon_manager_writes_bounded_tts_latency_trace()
    test_addon_manager_unload_closes_latency_writer()
    print("TTS addon latency regression probes passed.")


if __name__ == "__main__":
    main()
