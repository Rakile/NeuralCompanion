from __future__ import annotations

import copy
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from addons.discord_voice_bridge import settings as settings_module
from addons.discord_voice_bridge.main import (
    Addon,
    DEFAULT_TINY_MVP_BRIDGE_SCRIPT,
    DEFAULT_TINY_MVP_ROOM_SCRIPT,
    NODE_BRIDGE_REQUIRED_PACKAGES,
    _bridge_instance_is_running,
    _effective_bridge_settings,
    _node_bridge_environment_issues,
    _redact_runtime_log_text,
    _tiny_mvp_monitor_command,
    _tiny_mvp_bridge_script,
    _tiny_mvp_room_command,
    _tiny_mvp_room_script,
    _transport_environment_issues,
    _validate_bridge_settings,
    _voice_clone_wav_issues,
    _write_instance_settings,
)
from addons.discord_voice_bridge.runtime_server import DiscordVoiceRuntimeServer


TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{20,}")


def main() -> int:
    _test_validation_errors_and_success()
    _test_tiny_mvp_mode_skips_discord_and_node_requirements()
    _test_tiny_mvp_uses_bundled_defaults()
    _test_tiny_mvp_start_ensures_room_before_bot_bridges()
    _test_tiny_mvp_room_gui_default_contract()
    _test_settings_secret_preservation()
    _test_instance_settings_strip_direct_tokens()
    _test_room_router_candidates_are_sanitized()
    _test_redaction()
    _test_runtime_log_redaction()
    _test_loopback_auth_fallback()
    _test_designer_ui_contract()
    _test_settings_schema_ui_exposure()
    _test_protected_mic_speech_control_lives_with_moderator_controls()
    _test_discord_protected_mic_speech_routes_context()
    _test_runtime_safety_filters_and_context()
    _test_runtime_interruption_contract()
    _test_runtime_route_context_recording()
    _test_runtime_manual_speak_chunks()
    _test_bot_history_persists_between_runtime_instances()
    _test_room_router_decisions()
    _test_session_mode_stays_isolated()
    _test_non_loopback_runtime_requires_opt_in()
    _test_schema_covers_runtime_settings()
    _test_node_uses_exact_token_env_var()
    _test_node_shared_room_router_contract()
    _test_moderator_state_machine_contract()
    _test_dead_air_recovery_contract()
    _test_tiny_mvp_local_mic_dead_air_waits_for_quiet_timeout()
    _test_live_control_contract()
    _test_stream_chunker_keeps_word_boundaries()
    _test_stream_chunker_timeout_prefers_short_whitespace_over_midword()
    _test_stream_chunker_does_not_carry_vocal_tags_as_emotions()
    _test_runtime_emotion_names_exclude_vocal_tags()
    _test_runtime_stream_chunk_debug_line()
    _test_runtime_stream_chunk_debug_writes_stdout()
    _test_runtime_stream_config_reads_dynamic_buffer_lead()
    _test_runtime_live_settings_update()
    _test_global_live_settings_do_not_select_fallback_bot()
    _test_bot_chat_model_item_normalization()
    _test_runtime_reply_chat_model_override()
    _test_node_dependency_diagnostics()
    _test_node_dependency_first_run_prompt_contract()
    _test_node_install_blocks_when_bridge_running()
    _test_start_on_launch_persists_on_user_click()
    _test_voice_clone_wav_validation()
    print("Discord Voice Bridge smoke passed.")
    return 0


def _base_settings() -> dict:
    return {
        "enabled": True,
        "start_on_nc_launch": True,
        "bridge_mode": "http",
        "discord": {
            "guild_id": "guild",
            "voice_channel_id": "voice",
            "token_env_var": "NC_DISCORD_SMOKE_TOKEN_A",
            "answer_mode": "anyone",
        },
        "nc_runtime": {"host": "127.0.0.1", "port": 8768},
        "capture": {"wav_sample_rate": 16000, "wav_channels": 1},
        "bots": [],
    }


def _test_validation_errors_and_success() -> None:
    settings = _base_settings()
    settings["bots"] = [
        {
            "id": "echo",
            "enabled": True,
            "discord": {"token_env_var": "NC_DISCORD_SMOKE_TOKEN_A"},
            "nc_runtime": {"port": 9100},
        },
        {
            "id": "nova",
            "enabled": True,
            "discord": {"token_env_var": "NC_DISCORD_SMOKE_TOKEN_B"},
            "nc_runtime": {"port": 9100},
        },
    ]
    os.environ.pop("NC_DISCORD_SMOKE_TOKEN_A", None)
    os.environ.pop("NC_DISCORD_SMOKE_TOKEN_B", None)
    issues = _validate_bridge_settings(settings, force=True)
    assert any("token" in item["message"].lower() for item in issues), issues
    assert any("already used" in item["message"] for item in issues), issues

    os.environ["NC_DISCORD_SMOKE_TOKEN_A"] = "fake-token-a"
    os.environ["NC_DISCORD_SMOKE_TOKEN_B"] = "fake-token-b"
    settings["bots"][1]["nc_runtime"]["port"] = 9101
    issues = _validate_bridge_settings(settings, force=True)
    assert not [item for item in issues if item["severity"] == "error"], issues

    settings["bots"] = [
        {
            "id": "Echo!",
            "enabled": True,
            "discord": {"token_env_var": "NC_DISCORD_SMOKE_TOKEN_A"},
            "nc_runtime": {"port": 9100},
        },
        {
            "id": "Echo?",
            "enabled": True,
            "discord": {"token_env_var": "NC_DISCORD_SMOKE_TOKEN_B"},
            "nc_runtime": {"port": 9101},
        },
    ]
    issues = _validate_bridge_settings(settings, force=True)
    assert any("duplicate bot instance id" in item["message"].lower() for item in issues), issues


def _test_tiny_mvp_mode_skips_discord_and_node_requirements() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "tiny_voice_bridge.py"
        script.write_text("print('tiny')\n", encoding="utf-8")
        settings = _base_settings()
        settings["bridge_mode"] = "tiny_mvp"
        settings["discord"] = {
            "token_env_var": "NC_DISCORD_MISSING_TOKEN",
            "guild_id": "",
            "voice_channel_id": "",
        }
        settings["tiny_mvp"] = {
            "url": "http://127.0.0.1:8788",
            "bridge_script": str(script),
            "poll_seconds": 0.25,
        }
        os.environ.pop("NC_DISCORD_MISSING_TOKEN", None)
        validation = _validate_bridge_settings(settings, force=True)
        assert not [item for item in validation if item["severity"] == "error"], validation
        transport = _transport_environment_issues(settings, require_install=True)
        assert not [item for item in transport if item["severity"] == "error"], transport


def _test_tiny_mvp_uses_bundled_defaults() -> None:
    addon_dir = Path(__file__).resolve().parent
    assert DEFAULT_TINY_MVP_ROOM_SCRIPT == addon_dir / "tiny_mvp" / "main.py"
    assert DEFAULT_TINY_MVP_BRIDGE_SCRIPT == addon_dir / "tiny_mvp" / "tiny_voice_bridge.py"
    assert _tiny_mvp_room_script({}) == DEFAULT_TINY_MVP_ROOM_SCRIPT
    assert _tiny_mvp_bridge_script({}) == DEFAULT_TINY_MVP_BRIDGE_SCRIPT


def _test_tiny_mvp_start_ensures_room_before_bot_bridges() -> None:
    source = (Path(__file__).resolve().parent / "main.py").read_text(encoding="utf-8")
    body = source.split("def _start_instances_from_settings", 1)[1].split("def _start_runtime_server", 1)[0]
    assert "_ensure_tiny_mvp_room_server(settings)" in body
    assert body.index("_ensure_tiny_mvp_room_server(settings)") < body.index("self._start_node_bridge(instance)")


def _test_tiny_mvp_room_gui_default_contract() -> None:
    addon_dir = Path(__file__).resolve().parent
    defaults = json.loads((addon_dir / "settings.example.json").read_text(encoding="utf-8"))
    schema = json.loads((addon_dir / "settings_schema.json").read_text(encoding="utf-8"))
    controller = (addon_dir / "controller.py").read_text(encoding="utf-8")
    assert defaults["tiny_mvp"]["start_with_gui"] is True
    fields = [field for group in schema["groups"] for field in group.get("fields", [])]
    field = next(item for item in fields if item.get("key") == "tiny_mvp.start_with_gui")
    assert field["default"] is True
    assert "discord_tiny_mvp_start_with_gui_checkbox" in controller
    assert "--gui" not in _tiny_mvp_room_command({}, "127.0.0.1", 8788)
    assert "--monitor" not in _tiny_mvp_room_command({}, "127.0.0.1", 8788)
    assert "--gui" not in _tiny_mvp_room_command({"tiny_mvp": {"start_with_gui": False}}, "127.0.0.1", 8788)
    monitor_command = _tiny_mvp_monitor_command({}, "http://127.0.0.1:8788/state")
    assert "--gui" in monitor_command
    assert "--monitor-url" in monitor_command


def _test_settings_secret_preservation() -> None:
    original_default = settings_module.DEFAULT_SETTINGS_PATH
    original_local = settings_module.LOCAL_SETTINGS_PATH
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            default_path = tmp_path / "settings.example.json"
            local_path = tmp_path / "settings.local.json"
            default_path.write_text(json.dumps({"bots": []}), encoding="utf-8")
            local_path.write_text(
                json.dumps(
                    {
                        "discord": {
                            "token": "top.old.secret.token",
                            "token_env_var": "OLD_TOP_TOKEN_ENV",
                        },
                        "bots": [
                            {
                                "id": "echo",
                                "discord": {
                                    "token": "old.secret.token",
                                    "token_env_var": "OLD_TOKEN_ENV",
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            settings_module.DEFAULT_SETTINGS_PATH = default_path
            settings_module.LOCAL_SETTINGS_PATH = local_path

            settings_module.save_local_settings(
                {
                    "discord": {"token_env_var": "NEW_TOP_TOKEN_ENV"},
                    "bots": [{"id": "echo", "discord": {"token_env_var": "NEW_TOKEN_ENV"}}],
                }
            )
            saved = json.loads(local_path.read_text(encoding="utf-8"))
            assert saved["discord"]["token"] == "top.old.secret.token", saved
            assert saved["discord"]["token_env_var"] == "NEW_TOP_TOKEN_ENV", saved
            assert saved["bots"][0]["discord"]["token"] == "old.secret.token", saved
            assert saved["bots"][0]["discord"]["token_env_var"] == "NEW_TOKEN_ENV", saved

            settings_module.save_local_settings(
                {
                    "discord": {
                        "token": "top.new.secret.token",
                        "token_env_var": "NEW_TOP_TOKEN_ENV_2",
                    },
                    "bots": [
                        {
                            "id": "echo",
                            "discord": {
                                "token": "new.secret.token",
                                "token_env_var": "NEW_TOKEN_ENV_2",
                            },
                        }
                    ]
                },
                allow_secret_updates=True,
            )
            saved = json.loads(local_path.read_text(encoding="utf-8"))
            assert saved["discord"]["token"] == "top.new.secret.token", saved
            assert saved["discord"]["token_env_var"] == "NEW_TOP_TOKEN_ENV_2", saved
            assert saved["bots"][0]["discord"]["token"] == "new.secret.token", saved
            assert saved["bots"][0]["discord"]["token_env_var"] == "NEW_TOKEN_ENV_2", saved
    finally:
        settings_module.DEFAULT_SETTINGS_PATH = original_default
        settings_module.LOCAL_SETTINGS_PATH = original_local


def _test_instance_settings_strip_direct_tokens() -> None:
    from addons.discord_voice_bridge import main as main_module

    original_dir = main_module.INSTANCE_SETTINGS_DIR
    try:
        with tempfile.TemporaryDirectory() as tmp:
            main_module.INSTANCE_SETTINGS_DIR = Path(tmp)
            path = _write_instance_settings(
                "Echo!",
                {
                    "enabled": True,
                    "discord": {
                        "token": "direct.secret.token",
                        "token_env_var": "NC_DISCORD_SMOKE_TOKEN_A",
                        "guild_id": "guild",
                        "voice_channel_id": "voice",
                    },
                    "bots": [{"id": "nested_should_not_be_written"}],
                },
            )
            saved = json.loads(path.read_text(encoding="utf-8"))
            assert saved["discord"]["token_env_var"] == "NC_DISCORD_SMOKE_TOKEN_A", saved
            assert "token" not in saved["discord"], saved
            assert "bots" not in saved, saved
            assert path.name == "echo.settings.json", path
    finally:
        main_module.INSTANCE_SETTINGS_DIR = original_dir


def _test_room_router_candidates_are_sanitized() -> None:
    settings = _base_settings()
    settings["bots"] = [
        {
            "id": "Echo",
            "name": "Echo",
            "enabled": True,
            "discord": {"token": "secret.one.token", "token_env_var": "NC_DISCORD_SMOKE_TOKEN_A"},
            "call_names": "Echo, Ekko",
            "persona": {"system_prompt": "Friendly debate bot."},
            "nc_runtime": {"port": 9100},
        },
        {
            "id": "Mira",
            "name": "Mira",
            "enabled": True,
            "discord": {"token": "secret.two.token", "token_env_var": "NC_DISCORD_SMOKE_TOKEN_B"},
            "call_names": "Mira",
            "persona": {"system_prompt": "Sharper debate bot."},
            "nc_runtime": {"port": 9101},
        },
    ]
    os.environ["NC_DISCORD_SMOKE_TOKEN_A"] = "fake-token-a"
    os.environ["NC_DISCORD_SMOKE_TOKEN_B"] = "fake-token-b"
    effective = _effective_bridge_settings(settings, force=True)
    assert len(effective) == 2, effective
    for _instance_id, item, _index in effective:
        candidates = item.get("room_router", {}).get("candidate_bots")
        assert [candidate["id"] for candidate in candidates] == ["echo", "mira"], candidates
        serialized = json.dumps(candidates)
        assert "secret" not in serialized.lower(), serialized
        assert "Echo, Ekko" in serialized, serialized


def _test_redaction() -> None:
    payload = {
        "discord": {
            "token": "abcde12345abcde12345.abcd1.abcde12345abcde12345abcde12345",
            "guild_id": "guild",
        }
    }
    redacted = settings_module.redacted_settings(copy.deepcopy(payload))
    text = json.dumps(redacted)
    assert "<redacted>" in text, text
    assert not TOKEN_RE.search(text), text


def _test_runtime_log_redaction() -> None:
    raw = (
        'token="abcde12345abcde12345.abcd1.abcde12345abcde12345abcde12345" '
        'Authorization: Bearer bridge-secret-value '
        '{"token":"top.secret.value"}'
    )
    redacted = _redact_runtime_log_text(raw)
    assert "<redacted>" in redacted, redacted
    assert "abcde12345abcde12345.abcd1.abcde12345abcde12345abcde12345" not in redacted, redacted
    assert "bridge-secret-value" not in redacted, redacted
    assert "top.secret.value" not in redacted, redacted


def _test_loopback_auth_fallback() -> None:
    assert DiscordVoiceRuntimeServer._client_address_is_loopback(("127.0.0.1", 12345))
    assert DiscordVoiceRuntimeServer._client_address_is_loopback(("::1", 12345))
    assert not DiscordVoiceRuntimeServer._client_address_is_loopback(("192.168.1.20", 12345))
    assert not DiscordVoiceRuntimeServer._client_address_is_loopback(("", 12345))


def _test_designer_ui_contract() -> None:
    ui_text = (Path(__file__).resolve().parent / "ui" / "discord_voice_bridge.ui").read_text(encoding="utf-8")
    required_names = {
        "discord_bridge_save_button",
        "discord_bridge_start_button",
        "discord_bridge_stop_button",
        "discord_bridge_restart_button",
        "discord_bridge_refresh_button",
        "discord_token_env_edit",
        "discord_local_token_edit",
        "discord_guild_id_edit",
        "discord_voice_channel_id_edit",
        "discord_silence_ms_spin",
        "discord_min_turn_seconds_spin",
        "discord_ignore_low_information_checkbox",
        "discord_play_test_tone_checkbox",
        "discord_interrupt_reply_checkbox",
        "discord_reply_immunity_seconds_spin",
        "discord_initial_buffer_chunks_spin",
        "discord_persona_prompt_edit",
        "discord_voice_clone_wav_edit",
        "discord_persist_room_context_checkbox",
        "discord_bots_json_edit",
        "discord_runtime_host_edit",
        "discord_runtime_port_spin",
        "discord_use_selected_stt_checkbox",
        "discord_use_selected_chat_checkbox",
        "discord_use_selected_tts_checkbox",
        "discord_use_rag_context_checkbox",
        "discord_instances_table",
        "discord_logs_preview",
    }
    missing = sorted(name for name in required_names if f'name="{name}"' not in ui_text)
    assert not missing, missing

    required_tab_labels = {
        "General",
        "Discord",
        "Capture",
        "Playback",
        "Persona",
        "Bots",
        "Runtime",
        "Status",
    }
    missing_labels = sorted(label for label in required_tab_labels if f"<string>{label}</string>" not in ui_text)
    assert not missing_labels, missing_labels


def _test_settings_schema_ui_exposure() -> None:
    schema = settings_module.load_settings_schema()
    controller_text = (Path(__file__).resolve().parent / "controller.py").read_text(encoding="utf-8")
    ui_text = (Path(__file__).resolve().parent / "ui" / "discord_voice_bridge.ui").read_text(encoding="utf-8")
    key_to_controls = {
        "enabled": ["discord_enabled_checkbox"],
        "auto_start_bridge": ["discord_auto_start_checkbox"],
        "start_on_nc_launch": ["discord_start_on_launch_checkbox"],
        "bridge_mode": ["discord_bridge_mode_combo"],
        "tiny_mvp.url": ["discord_tiny_mvp_url_edit"],
        "tiny_mvp.start_with_gui": ["discord_tiny_mvp_start_with_gui_checkbox"],
        "tiny_mvp.bridge_script": ["discord_tiny_mvp_bridge_script_edit"],
        "tiny_mvp.poll_seconds": ["discord_tiny_mvp_poll_seconds_spin"],
        "tiny_mvp.capture_mic": ["discord_tiny_mvp_capture_mic_checkbox"],
        "playback.route_protected_mic_speech": ["discord_route_protected_mic_speech_checkbox"],
        "tiny_mvp.mic_user_id": ["discord_tiny_mvp_mic_user_id_edit"],
        "tiny_mvp.mic_user_name": ["discord_tiny_mvp_mic_user_name_edit"],
        "tiny_mvp.mic_seconds": ["discord_tiny_mvp_mic_seconds_spin"],
        "tiny_mvp.mic_sample_rate": ["discord_tiny_mvp_mic_sample_rate_spin"],
        "tiny_mvp.mic_device": ["discord_tiny_mvp_mic_device_edit"],
        "discord.token_env_var": ["discord_token_env_edit"],
        "discord.token": ["discord_local_token_edit"],
        "discord.guild_id": ["discord_guild_id_edit"],
        "discord.voice_channel_id": ["discord_voice_channel_id_edit"],
        "discord.allowed_user_id": ["discord_allowed_user_id_edit"],
        "discord.answer_mode": ["discord_answer_mode_combo"],
        "capture.silence_ms": ["discord_silence_ms_spin"],
        "capture.min_turn_seconds": ["discord_min_turn_seconds_spin"],
        "capture.max_turn_seconds": ["discord_max_turn_seconds_spin"],
        "capture.bot_max_turn_seconds": ["discord_bot_max_turn_seconds_spin"],
        "capture.bot_idle_finalize_ms": ["discord_bot_idle_finalize_ms_spin"],
        "capture.ignore_low_information_transcripts": ["discord_ignore_low_information_checkbox"],
        "capture.low_information_max_seconds": ["discord_low_information_max_seconds_spin"],
        "capture.low_information_transcripts": ["discord_low_information_transcripts_edit"],
        "capture.wav_sample_rate": ["discord_wav_sample_rate_combo"],
        "capture.wav_channels": ["discord_wav_channels_combo"],
        "capture.save_captures": ["discord_save_captures_checkbox"],
        "capture.shared_capture_owner_enabled": ["discord_shared_capture_owner_checkbox"],
        "capture.owner_ttl_seconds": ["discord_capture_owner_ttl_spin"],
        "playback.play_test_tone_on_join": ["discord_play_test_tone_checkbox"],
        "playback.queue_replies": ["discord_queue_replies_checkbox"],
        "playback.interrupt_reply_on_user_speech": ["discord_interrupt_reply_checkbox"],
        "playback.interrupt_after_seconds": ["discord_interrupt_after_seconds_spin"],
        "playback.reply_immunity_seconds": ["discord_reply_immunity_seconds_spin"],
        "playback.discard_bot_speech_on_human_intervention": ["discord_discard_bot_speech_checkbox"],
        "playback.coordinate_bot_replies": ["discord_coordinate_bot_replies_checkbox"],
        "playback.reply_floor_stale_seconds": ["discord_reply_floor_stale_seconds_spin"],
        "playback.initial_buffer_chunks": ["discord_initial_buffer_chunks_spin"],
        "cleanup.wav_max_age_minutes": ["discord_wav_max_age_minutes_spin"],
        "cleanup.interval_minutes": ["discord_cleanup_interval_minutes_spin"],
        "room_router.enabled": ["discord_room_router_enabled_checkbox"],
        "room_router.mode": ["discord_room_router_mode_combo"],
        "room_router.default_when_uncertain": ["discord_room_router_uncertain_checkbox"],
        "room_router.human_to_bot_routing": ["discord_room_router_human_to_bot_checkbox"],
        "room_router.bot_to_bot_routing": ["discord_room_router_bot_to_bot_checkbox"],
        "room_router.exclude_speaker_from_targets": ["discord_room_router_exclude_speaker_checkbox"],
        "room_router.allow_group_invitation_routing": ["discord_room_router_group_invite_checkbox"],
        "room_router.allow_open_room_invitation_routing": ["discord_room_router_open_room_checkbox"],
        "room_router.self_route_policy": ["discord_room_router_self_route_combo"],
        "room_router.uncertain_fallback_target": ["discord_room_router_uncertain_target_combo"],
        "room_router.decision_timeout_seconds": ["discord_room_router_decision_timeout_spin"],
        "room_router.decision_max_tokens": ["discord_room_router_decision_tokens_spin"],
        "room_router.route_window_ms": ["discord_room_router_route_window_spin"],
        "room_router.route_bot_replies_from_text": ["discord_room_router_text_routing_checkbox"],
        "room_router.prepare_bot_replies_ahead": ["discord_room_router_prebuffer_checkbox"],
        "room_router.competing_bot_reply_policy": ["discord_room_router_competing_policy_combo"],
        "room_router.reply_floor_mode": ["discord_room_router_floor_mode_combo"],
        "room_router.dead_air_recovery.enabled": ["discord_dead_air_enabled_checkbox"],
        "room_router.dead_air_recovery.cooldown_seconds": ["discord_dead_air_cooldown_spin"],
        "room_router.dead_air_recovery.silence_timeout_seconds": ["discord_dead_air_silence_timeout_spin"],
        "room_router.dead_air_recovery.trigger_mode": ["discord_dead_air_trigger_combo"],
        "room_router.dead_air_recovery.action_mode": ["discord_dead_air_action_combo"],
        "room_router.dead_air_recovery.next_speaker_strategy": ["discord_dead_air_strategy_combo"],
        "room_router.dead_air_recovery.selected_fallback_target": ["discord_dead_air_fallback_target_combo"],
        "room_router.routed_text_poll_ms": ["discord_room_router_poll_ms_spin"],
        "room_router.routed_text_max_age_seconds": ["discord_room_router_text_age_spin"],
        "room_router.router_rules_prompt": ["discord_room_router_rules_prompt_edit"],
        "persona.system_prompt": ["discord_persona_prompt_edit"],
        "persona.replace_nc_system_prompt": ["discord_replace_nc_prompt_checkbox"],
        "persona.voice_clone_wav": ["discord_voice_clone_wav_edit"],
        "chat.context_entries": ["discord_context_entries_spin"],
        "chat.use_selected_rag_context": ["discord_use_rag_context_checkbox"],
        "chat.persist_room_context_between_restarts": ["discord_persist_room_context_checkbox"],
        "bots": ["discord_bots_json_edit", "discord_bot_editor_group"],
        "nc_runtime.host": ["discord_runtime_host_edit"],
        "nc_runtime.port": ["discord_runtime_port_spin"],
        "nc_runtime.allow_non_localhost": ["discord_allow_non_localhost_checkbox"],
        "nc_runtime.endpoint": ["discord_runtime_ws_endpoint_edit"],
        "nc_runtime.http_endpoint": ["discord_runtime_http_endpoint_edit"],
        "nc_runtime.session_mode": ["discord_session_mode_combo"],
        "nc_runtime.use_selected_stt": ["discord_use_selected_stt_checkbox"],
        "nc_runtime.use_selected_chat_provider": ["discord_use_selected_chat_checkbox"],
        "nc_runtime.use_selected_tts": ["discord_use_selected_tts_checkbox"],
    }
    schema_keys = {
        str(field.get("key") or "")
        for group in schema.get("groups", [])
        if isinstance(group, dict)
        for field in group.get("fields", [])
        if isinstance(field, dict)
    }
    missing_map = sorted(schema_keys - set(key_to_controls))
    assert not missing_map, missing_map
    missing_controls = []
    combined = ui_text + "\n" + controller_text
    for key in sorted(schema_keys):
        controls = key_to_controls[key]
        if not any(control in combined for control in controls):
            missing_controls.append((key, controls))
    assert not missing_controls, missing_controls


def _test_protected_mic_speech_control_lives_with_moderator_controls() -> None:
    controller_text = (Path(__file__).resolve().parent / "controller.py").read_text(encoding="utf-8")
    tiny_group_start = controller_text.index('group = QtWidgets.QGroupBox("TinyMVP Local Room"')
    tiny_group_end = controller_text.index("def _build_moderator_controls", tiny_group_start)
    moderator_start = controller_text.index("def _build_moderator_controls")
    control_name = "discord_route_protected_mic_speech_checkbox"
    assert control_name not in controller_text[tiny_group_start:tiny_group_end]
    assert control_name in controller_text[moderator_start:]
    assert controller_text.index(control_name, moderator_start) > controller_text.index(
        "discord_moderator_allow_interrupt_current_checkbox",
        moderator_start,
    )


def _test_discord_protected_mic_speech_routes_context() -> None:
    addon_dir = Path(__file__).resolve().parent
    node_text = (addon_dir / "node_bridge" / "src" / "index.js").read_text(encoding="utf-8")
    controller_text = (addon_dir / "controller.py").read_text(encoding="utf-8")
    schema_text = (addon_dir / "settings_schema.json").read_text(encoding="utf-8")

    assert "routeProtectedMicSpeech" in node_text
    assert 'record_route_context: Boolean(routeProtectedMicSpeech && moderatorProtectsCurrentSpeaker())' in node_text
    assert '"playback.route_protected_mic_speech"' in schema_text
    assert "TinyMVP only" not in controller_text


def _test_runtime_safety_filters_and_context() -> None:
    class FakeCapabilities:
        def __init__(self):
            self.calls = []

        def invoke(self, name, payload):
            self.calls.append((name, payload))
            return {
                "context": "Relevant retrieval context from the user's selected local RAG source index.",
                "debug": {"matches": 1, "sources": ["docs/example.md"]},
            }

    class FakeContext:
        def __init__(self, service):
            self.service = service

        def get_service(self, name):
            return self.service if name == "addons.capabilities" else None

    settings = _base_settings()
    settings["response_filter"] = {
        "enabled": True,
        "mode": "llm_sentinel",
        "bot_names": "Echo, Neural Companion",
    }
    server = DiscordVoiceRuntimeServer(settings=settings, logger=None)

    assert server._should_ignore_low_information_transcript("And", 1.0)
    assert not server._should_ignore_low_information_transcript("And", 3.0)
    assert not server._should_ignore_low_information_transcript("No", 1.0)
    assert server._is_no_reply_sentinel("__NC_NO_REPLY__")
    assert server._is_no_reply_sentinel("NC_NO_REPLY__")
    server.settings["name"] = "Nova"
    assert (
        server._clean_generated_reply_text("[2026-06-11 20:59:12 W. Europe Daylight Time] Nova: Hello there.")
        == "Hello there."
    )
    assert server._clean_generated_reply_text("Nova: Hello there.") == "Hello there."
    assert server._clean_generated_reply_text("Speaker: Nova\n\nLatest utterance:\n[2026-06-11 20:59:12 W. Europe Daylight Time] Nova: Hello there.") == "Hello there."
    assert server._clean_generated_reply_text("Echo: Assistant: [2026-06-13 20:31:45 W. Europe Daylight Time] Echo: Hello there.") == "Hello there."
    assert server._clean_generated_reply_text("23:#23:_23] Nova: Hello there.") == "Hello there."
    assert server._clean_generated_reply_text("Note: keep this ordinary sentence.") == "Note: keep this ordinary sentence."

    server._record_ignored_turn("[2026-06-10 19:08:13 W. Europe Daylight Time] Rakila: And")
    assert server._history[-1]["role"] == "user", server._history
    assert "Rakila: And" in server._history[-1]["content"], server._history

    service = FakeCapabilities()
    server._addon_context = FakeContext(service)
    contexts = server._collect_addon_chat_contexts(
        [{"role": "user", "content": "What is Neural Companion?"}],
        {"active_preset_name": "Discord"},
    )
    assert contexts and "Relevant retrieval context" in contexts[0]["context"], contexts
    assert service.calls and service.calls[0][0] == "chat_context.collect", service.calls

    server.settings.setdefault("chat", {})["use_selected_rag_context"] = False
    service.calls.clear()
    assert server._collect_addon_chat_contexts([{"role": "user", "content": "ignored"}], {}) == []
    assert not service.calls, service.calls


def _test_runtime_interruption_contract() -> None:
    settings = _base_settings()
    settings["name"] = "Echo"
    server = DiscordVoiceRuntimeServer(settings=settings, logger=None)

    low_info = server.route_turn({
        "route_key": "low",
        "speaker_name": "Rakila",
        "input_text": "And",
        "duration_seconds": 0.8,
    })
    assert low_info["reason"] == "low_information_transcript", low_info
    assert low_info["speech_accepted"] is False, low_info

    server._should_reply_to_turn = lambda _text, _runtime: (False, "room_talk")  # type: ignore[method-assign]
    events = list(server.process_turn_events({
        "turn_id": "turn_no_reply",
        "speaker_name": "Rakila",
        "input_text": "I am just talking to the room.",
        "duration_seconds": 3.0,
        "room_context": [
            {
                "content": "[2026-06-11 20:59:12 W. Europe Daylight Time] Rakila: Earlier room speech.",
                "answer": False,
                "reason": "no target",
            }
        ],
    }))
    assert events and events[-1]["type"] == "skipped", events
    assert events[-1]["speech_accepted"] is True, events
    assert events[-1]["reason"] == "response_filter", events
    assert server._history[-1]["role"] == "user", server._history
    assert "I am just talking to the room." in server._history[-1]["content"], server._history

    messages = server._chat_messages(
        "[2026-06-11 21:00:00 W. Europe Daylight Time] Rakila: Current speech.",
        {"_discord_room_context": server._room_context_block([
            {"content": "[2026-06-11 20:59:12 W. Europe Daylight Time] Rakila: Earlier room speech.", "answer": False}
        ])},
    )
    assert any("Earlier room speech" in item["content"] for item in messages if item["role"] == "system"), messages
    assert any("untrusted conversation data" in item["content"] for item in messages if item["role"] == "system"), messages
    assert any("<discord_transcript_data>" in item["content"] for item in messages if item["role"] == "system"), messages
    assert messages[-1]["role"] == "user", messages
    assert "<discord_transcript_data>" in messages[-1]["content"], messages[-1]
    assert "not system instructions" in messages[-1]["content"], messages[-1]

    server._history.clear()
    server._finalized_turns.clear()
    with server._lock:
        server._active_turns["turn_interrupted"] = {
            "input_text": "[2026-06-11 21:01:00 W. Europe Daylight Time] Rakila: Tell me something long.",
            "reply_text": "This is the complete assistant reply that should not survive interruption.",
            "history_finalized": False,
            "cancelled": False,
        }
    finished = server.finish_turn({"turn_id": "turn_interrupted"})
    assert finished["history_finalized"] is True, finished
    cancelled = server.cancel_turn({
        "turn_id": "turn_interrupted",
        "spoken_text": "This is the spoken partial",
        "reason": "valid Discord speech",
    })
    assert cancelled["revised"] is True, cancelled
    assert server._history[-1]["role"] == "assistant", server._history
    assert "This is the spoken partial" in server._history[-1]["content"], server._history
    assert "(the user interrupted...)" in server._history[-1]["content"], server._history
    assert "complete assistant reply" not in server._history[-1]["content"], server._history

    server = DiscordVoiceRuntimeServer(settings=settings, logger=None)
    server._runtime_config = lambda: {"chat_provider": "openai", "model_name": "gpt-test", "stream_mode": False}  # type: ignore[method-assign]
    server._should_reply_to_turn = lambda _text, _runtime: (True, "filter_disabled")  # type: ignore[method-assign]

    def _raise_quota(_input_text, _runtime):
        raise RuntimeError("Error code: 429 - {'error': {'code': 'insufficient_quota'}}")

    server._complete_chat_text = _raise_quota  # type: ignore[method-assign]
    events = list(server.process_turn_events({
        "turn_id": "turn_provider_error",
        "speaker_name": "Rakila",
        "input_text": "Does this provider still have credits?",
        "duration_seconds": 3.0,
    }))
    assert events[-1]["type"] == "error", events
    assert events[-1]["reason"] == "reply_error", events[-1]
    assert events[-1]["error_kind"] == "provider_quota", events[-1]
    assert "quota" in events[-1]["error"].lower(), events[-1]
    assert "turn_provider_error" not in server._active_turns, server._active_turns
    assert server._history[-1]["role"] == "user", server._history
    assert "Does this provider still have credits?" in server._history[-1]["content"], server._history


def _test_runtime_route_context_recording() -> None:
    settings = _base_settings()
    server = DiscordVoiceRuntimeServer(settings=settings, logger=None)
    server._room_router_decision = lambda _text, _payload: {  # type: ignore[method-assign]
        "answer": False,
        "target_bot_id": "",
        "reason": "current_speaker_protected",
    }
    decision = server.route_turn(
        {
            "route_key": "protected_mic_1",
            "speaker_name": "Rakila",
            "user_id": "rakila",
            "input_text": "I should be heard without stealing the floor.",
            "duration_seconds": 3.0,
            "record_route_context": True,
        }
    )
    assert decision["answer"] is False, decision
    assert decision["context_recorded"] is True, decision
    assert server._history[-1]["role"] == "user", server._history
    assert "Rakila: I should be heard without stealing the floor." in server._history[-1]["content"], server._history

    duplicate = server.route_turn(
        {
            "route_key": "protected_mic_1",
            "speaker_name": "Rakila",
            "user_id": "rakila",
            "input_text": "I should be heard without stealing the floor.",
            "duration_seconds": 3.0,
            "record_route_context": True,
        }
    )
    assert duplicate["context_recorded"] is False, duplicate
    assert duplicate["context_record_reason"] == "duplicate_user_turn", duplicate


def _test_runtime_manual_speak_chunks() -> None:
    settings = _base_settings()
    server = DiscordVoiceRuntimeServer(settings=settings, logger=None)
    server._speech_chunks_from_reply = lambda _text: ["First exact sentence.", "Second exact sentence."]  # type: ignore[method-assign]
    server._audio_events_for_text_chunk = lambda text, index: iter(  # type: ignore[method-assign]
        [
            {
                "type": "audio_chunk",
                "ok": True,
                "chunk_index": index,
                "reply_text": text,
                "reply_wav_path": f"chunk_{index}.wav",
            }
        ]
    )
    result = server.speak_text({"turn_id": "manual_1", "text": "First exact sentence. Second exact sentence."})
    assert result["ok"] is True, result
    assert result["reply_chunk_count"] == 2, result
    assert [item["reply_text"] for item in result["reply_chunks"]] == ["First exact sentence.", "Second exact sentence."], result
    assert result["reply_wav_path"] == "chunk_0.wav", result
    assert server._history[-1]["role"] == "assistant", server._history
    assert "First exact sentence. Second exact sentence." in server._history[-1]["content"], server._history


def _test_bot_history_persists_between_runtime_instances() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        history_path = Path(tmp) / "echo.history.json"
        settings = _base_settings()
        settings["id"] = "echo"

        first = DiscordVoiceRuntimeServer(settings=settings, logger=None)
        first._persisted_history_path = lambda: history_path  # type: ignore[method-assign]
        first._history.clear()
        with first._lock:
            first._append_history_unlocked("user", "Rakila: Hello Echo.")
            first._append_history_unlocked("assistant", "Echo: Hello Rakila.")

        second = DiscordVoiceRuntimeServer(settings=settings, logger=None)
        second._persisted_history_path = lambda: history_path  # type: ignore[method-assign]
        second._history.clear()
        second._load_persisted_history()
        assert len(second._history) == 2, second._history
        assert second._history[0]["content"] == "Rakila: Hello Echo.", second._history
        assert second._history[1]["content"] == "Echo: Hello Rakila.", second._history

        second.reset_history()
        assert not history_path.exists(), history_path


def _test_room_router_decisions() -> None:
    settings = _base_settings()
    settings["id"] = "mira"
    settings["name"] = "Mira"
    settings["room_router"] = {
        "enabled": True,
        "mode": "mention_or_question",
        "default_when_uncertain": False,
        "candidate_bots": [
            {"id": "echo", "name": "Echo", "call_names": "Echo, Ekko", "persona_hint": "warm"},
            {"id": "mira", "name": "Mira", "call_names": "Mira", "persona_hint": "sharp"},
            {"id": "nova", "name": "Nova", "call_names": "Nova, Novak", "persona_hint": "curious"},
            {"id": "human:358658419030360064", "name": "Rakila", "call_names": "Rakila"},
        ],
    }
    server = DiscordVoiceRuntimeServer(settings=settings, logger=None)
    policy = server._room_router_policy(settings["room_router"])
    candidates = server._room_router_candidates({}, settings["room_router"], policy)
    speaker_filtered = server._room_router_candidates({"speaker_bot_id": "nova"}, settings["room_router"])
    assert [item["id"] for item in speaker_filtered] == ["echo", "mira", "human:358658419030360064"], speaker_filtered
    participant_candidates = server._room_router_candidates(
        {
            "user_id": "moderator",
            "speaker_name": "Moderator",
            "participants": [
                {"id": "moderator", "name": "Moderator", "kind": "bot", "connected": True},
                {"id": "rakila", "name": "Rakila", "kind": "human", "connected": True},
                {"id": "litorect", "name": "litorect", "kind": "human", "connected": True},
            ],
        },
        {"candidate_bots": [{"id": "echo", "name": "Echo", "call_names": "Echo"}]},
        policy,
    )
    assert [item["id"] for item in participant_candidates] == ["echo", "rakila", "litorect"], participant_candidates
    participant_filtered = server._room_router_candidates(
        {
            "user_id": "rakila",
            "speaker_name": "Rakila",
            "participants": [
                {"id": "rakila", "name": "Rakila", "kind": "human", "connected": True},
                {"id": "litorect", "name": "litorect", "kind": "human", "connected": True},
            ],
        },
        {"candidate_bots": [{"id": "echo", "name": "Echo", "call_names": "Echo"}]},
        policy,
    )
    assert [item["id"] for item in participant_filtered] == ["echo", "litorect"], participant_filtered
    assert server._room_router_speaker_bot_id({"speaker_name": "Echo", "speaker_is_bot": False}, candidates) == ""
    assert server._room_router_speaker_bot_id({"speaker_name": "Echo", "speaker_is_bot": True}, candidates) == "echo"

    decision = server._local_room_router_decision("Rakila: Mira, can you answer this?", candidates, settings["room_router"], policy)
    assert decision["answer"] is True and decision["target_bot_id"] == "mira", decision

    decision = server._local_room_router_decision("Rakila: Echo, what do you think?", candidates, settings["room_router"], policy)
    assert decision["answer"] is True and decision["target_bot_id"] == "echo", decision

    decision = server._local_room_router_decision("Rakila: I was talking to another human.", candidates, settings["room_router"], policy)
    assert decision["answer"] is False and decision["target_bot_id"] == "", decision

    decision = server._local_room_router_decision("Echo: Rakila, what do you think?", candidates, settings["room_router"], policy)
    assert decision["answer"] is True and decision["target_bot_id"] == "human:358658419030360064", decision

    parsed = server._parse_room_router_decision('{"answer": true, "target_bot_id": "mira", "reason": "direct"}', candidates)
    assert parsed == {"answer": True, "target_bot_id": "mira", "reason": "direct"}, parsed
    parsed = server._parse_room_router_decision('{"answer": true, "target_bot_id": "human:358658419030360064", "reason": "asked Rakila"}', candidates)
    assert parsed == {"answer": True, "target_bot_id": "human:358658419030360064", "reason": "asked Rakila"}, parsed
    parsed = server._parse_room_router_decision('{"answer": true, "target_bot_id": "human_358658419030360064", "reason": "asked Rakila"}', candidates)
    assert parsed == {"answer": True, "target_bot_id": "human:358658419030360064", "reason": "asked Rakila"}, parsed
    parsed = server._parse_room_router_decision('{"answer": true, "target_bot_id": "rakila", "reason": "asked Rakila"}', candidates)
    assert parsed == {"answer": True, "target_bot_id": "human:358658419030360064", "reason": "asked Rakila"}, parsed
    token_candidates = [
        {"id": "human:358658419030360064", "name": "Rakila", "call_names": "Rakila", "router_target": "rakila"},
        {"id": "echo", "name": "Echo", "call_names": "Echo", "router_target": "echo"},
    ]
    parsed = server._parse_room_router_decision('{"answer": true, "target_bot_id": "rakila", "reason": "asked Rakila"}', token_candidates)
    assert parsed == {"answer": True, "target_bot_id": "human:358658419030360064", "reason": "asked Rakila"}, parsed
    duplicate_name_candidates = [
        *candidates,
        {"id": "human:111111111111111111", "name": "Rakila", "call_names": "Rakila"},
    ]
    assert server._parse_room_router_decision('{"answer": true, "target_bot_id": "rakila", "reason": "asked Rakila"}', duplicate_name_candidates) is None
    repaired = server._parse_room_router_decision(
        '{"answer":true,"target_bot_id":"echo","reason:"Nova directly addresses Echo and challenges their previous argument."}',
        candidates,
    )
    assert repaired and repaired["answer"] is True and repaired["target_bot_id"] == "echo", repaired
    assert repaired["reason"].startswith("llm_router_repaired"), repaired
    assert server._parse_room_router_decision('{"answer": true, "target_bot_id": "unknown"}', candidates) is None

    false_reply = {"answer": False, "target_bot_id": "", "reason": "The utterance is a direct response to Echo's previous provocation within the ongoing debate."}
    decision = server._room_router_false_negative_response_target(false_reply, candidates, {"speaker_name": "Mira"}, policy)
    assert decision and decision["answer"] is True and decision["target_bot_id"] == "echo", decision

    false_continuation = {
        "answer": False,
        "target_bot_id": "",
        "reason": "Echo is continuing the debate without addressing a specific bot.",
    }
    decision = server._room_router_debate_continuation_target(
        false_continuation,
        candidates,
        {
            "speaker_bot_id": "echo",
            "room_context": [
                {"role": "user", "content": "[2026-06-11 20:59:12] Nova: That challenge was aimed at Echo."}
            ],
        },
        policy,
    )
    assert decision and decision["answer"] is True and decision["target_bot_id"] == "nova", decision

    false_multi_target = {
        "answer": False,
        "target_bot_id": "",
        "reason": "The speaker is Echo and the utterance is a request directed at both Mira and Nova to speak; since it's an invitation for multiple bots/room participants rather than a specific targetable command or human-to-human talk requiring routing, no single bot is selected.",
    }
    decision = server._room_router_false_negative_response_target(false_multi_target, candidates, {"speaker_name": "Echo"}, policy)
    assert decision and decision["answer"] is True and decision["target_bot_id"] == "mira", decision
    assert server._room_router_false_negative_invitation(false_multi_target, policy) is True

    false_group_greeting = {
        "answer": False,
        "target_bot_id": "",
        "reason": "Speaker greeted all bots simultaneously; no single target clear.",
    }
    assert server._room_router_false_negative_invitation(false_group_greeting, policy) is True

    default_rules = DiscordVoiceRuntimeServer.DEFAULT_ROUTER_RULES_PROMPT
    assert "Candidate target tokens may refer to bots or humans" in default_rules, default_rules
    assert "continues a debate with another candidate bot" in default_rules, default_rules
    assert "Do not classify candidate-bot dialogue as human-to-human room talk" in default_rules, default_rules

    false_nonhuman_invitation = {
        "answer": False,
        "target_bot_id": "",
        "reason": "The utterance hands the turn to one or more non-human speakers without preferring a single bot.",
    }
    assert server._room_router_false_negative_invitation(false_nonhuman_invitation, policy) is True

    settings["room_router"]["allow_open_room_invitation_routing"] = False
    policy = server._room_router_policy(settings["room_router"])
    assert server._room_router_false_negative_invitation(false_multi_target, policy) is False
    settings["room_router"]["allow_open_room_invitation_routing"] = True

    settings["room_router"]["default_when_uncertain"] = True
    policy = server._room_router_policy(settings["room_router"])
    decision = server._uncertain_room_router_decision(candidates, settings["room_router"], policy, "unclear")
    assert decision["answer"] is True and decision["target_bot_id"] == "mira", decision

    settings["room_router"]["default_when_uncertain"] = False
    policy = server._room_router_policy(settings["room_router"])
    decision = server._uncertain_room_router_decision(candidates, settings["room_router"], policy, "unclear")
    assert decision["answer"] is False and decision["target_bot_id"] == "", decision

    settings["room_router"]["default_when_uncertain"] = True
    settings["room_router"]["uncertain_fallback_target"] = "first_candidate"
    policy = server._room_router_policy(settings["room_router"])
    decision = server._uncertain_room_router_decision(candidates, settings["room_router"], policy, "unclear")
    assert decision["answer"] is True and decision["target_bot_id"] == "echo", decision

    settings["room_router"]["bot_to_bot_routing"] = False
    decision = server._room_router_decision(
        "Echo: Mira, your turn.",
        {"speaker_bot_id": "echo", "speaker_name": "Echo", "candidate_bots": settings["room_router"]["candidate_bots"]},
    )
    assert decision["answer"] is False and decision["reason"] == "bot_to_bot_routing_disabled", decision

    settings["room_router"]["bot_to_bot_routing"] = True
    settings["room_router"]["exclude_speaker_from_targets"] = False
    settings["room_router"]["self_route_policy"] = "ignore"
    decision = server._room_router_decision(
        "Echo: Echo, keep talking.",
        {"speaker_bot_id": "echo", "speaker_name": "Echo", "candidate_bots": settings["room_router"]["candidate_bots"]},
    )
    assert decision["answer"] is False and str(decision["reason"]).startswith("self_route_ignore:"), decision

    settings["room_router"]["self_route_policy"] = "allow"
    decision = server._room_router_decision(
        "Echo: Echo, keep talking.",
        {"speaker_bot_id": "echo", "speaker_name": "Echo", "candidate_bots": settings["room_router"]["candidate_bots"]},
    )
    assert decision["answer"] is True and decision["target_bot_id"] == "echo", decision

    defaults = json.loads((settings_module.ADDON_DIR / "settings.example.json").read_text(encoding="utf-8"))
    router_defaults = defaults.get("room_router", {})
    assert router_defaults.get("competing_bot_reply_policy") == "first_ready_wins", router_defaults
    assert router_defaults.get("reply_floor_mode") == "first_ready_wins", router_defaults

    single = server._room_router_decision(
        "Rakila: hello",
        {"candidate_bots": [{"id": "mira", "name": "Mira", "call_names": "Mira"}]},
    )
    assert single["answer"] is True and single["target_bot_id"] == "mira", single

    route_result = server.route_turn(
        {
            "route_key": "smoke_route_1",
            "speaker_name": "Rakila",
            "input_text": "Mira, can you answer this?",
            "candidate_bots": settings["room_router"]["candidate_bots"],
        }
    )
    last_route = server.status_snapshot()["last_route_decision"]
    assert route_result["answer"] is True and route_result["target_bot_id"] == "mira", route_result
    assert last_route["route_key"] == "smoke_route_1", last_route
    assert last_route["target_bot_id"] == "mira", last_route
    assert last_route["candidate_ids"] == ["echo", "mira", "nova", "human:358658419030360064"], last_route

    original_llm_router = server._llm_room_router_decision
    settings["room_router"]["mode"] = "llm_router"
    settings["room_router"]["exclude_speaker_from_targets"] = False
    settings["room_router"]["self_route_policy"] = "ignore"
    server._llm_room_router_decision = lambda *_args, **_kwargs: {"answer": True, "target_bot_id": "echo", "reason": "human addressed Echo"}  # type: ignore[method-assign]
    human_to_echo = server._room_router_decision(
        "Echo: can you answer?",
        {
            "speaker_name": "Echo",
            "speaker_is_bot": False,
            "candidate_bots": settings["room_router"]["candidate_bots"],
        },
    )
    assert human_to_echo["answer"] is True and human_to_echo["target_bot_id"] == "echo", human_to_echo
    server._llm_room_router_decision = original_llm_router  # type: ignore[method-assign]


def _test_session_mode_stays_isolated() -> None:
    settings = _base_settings()
    settings["nc_runtime"]["session_mode"] = "normal_chat"
    os.environ["NC_DISCORD_SMOKE_TOKEN_A"] = "fake-token-a"
    effective = _effective_bridge_settings(settings, force=True)
    assert effective, effective
    assert effective[0][1]["nc_runtime"]["session_mode"] == "isolated_discord", effective


def _test_non_loopback_runtime_requires_opt_in() -> None:
    settings = _base_settings()
    os.environ["NC_DISCORD_SMOKE_TOKEN_A"] = "fake-token-a"
    settings["nc_runtime"]["host"] = "192.168.1.25"
    issues = _validate_bridge_settings(settings, force=True)
    assert any(item["severity"] == "error" and "non-localhost" in item["message"] for item in issues), issues

    settings["nc_runtime"]["allow_non_localhost"] = True
    issues = _validate_bridge_settings(settings, force=True)
    assert not [item for item in issues if item["severity"] == "error"], issues
    assert any(item["severity"] == "warning" and "localhost is recommended" in item["message"] for item in issues), issues


def _test_schema_covers_runtime_settings() -> None:
    schema = settings_module.load_settings_schema()
    keys = {
        str(field.get("key") or "")
        for group in schema.get("groups", [])
        if isinstance(group, dict)
        for field in group.get("fields", [])
        if isinstance(field, dict)
    }
    required = {
        "chat.use_selected_rag_context",
        "nc_runtime.host",
        "nc_runtime.port",
        "nc_runtime.allow_non_localhost",
        "nc_runtime.http_endpoint",
        "nc_runtime.use_selected_stt",
        "nc_runtime.use_selected_chat_provider",
        "nc_runtime.use_selected_tts",
        "tiny_mvp.url",
        "tiny_mvp.bridge_script",
        "tiny_mvp.poll_seconds",
        "tiny_mvp.capture_mic",
        "tiny_mvp.mic_user_id",
        "tiny_mvp.mic_user_name",
        "tiny_mvp.mic_seconds",
        "tiny_mvp.mic_sample_rate",
        "tiny_mvp.mic_device",
        "room_router.enabled",
        "room_router.mode",
        "room_router.default_when_uncertain",
        "room_router.decision_timeout_seconds",
        "room_router.route_window_ms",
        "room_router.route_bot_replies_from_text",
        "room_router.prepare_bot_replies_ahead",
        "room_router.routed_text_poll_ms",
    }
    assert required.issubset(keys), sorted(required - keys)
    assert "chat.persist_bot_history_between_restarts" not in keys

    settings = json.loads((Path(__file__).resolve().parent / "settings.example.json").read_text(encoding="utf-8"))
    assert settings.get("chat", {}).get("use_selected_rag_context") is True, settings.get("chat")
    assert settings.get("playback", {}).get("initial_buffer_chunks") == 2, settings.get("playback")


def _test_node_uses_exact_token_env_var() -> None:
    source = (Path(__file__).resolve().parent / "node_bridge" / "src" / "index.js").read_text(encoding="utf-8")
    assert "const token = process.env[tokenEnvVar];" in source, source[:500]
    assert "process.env[tokenEnvVar] || process.env.DISCORD_TOKEN" not in source, source[:500]
    assert 'Discord token environment variable "${tokenEnvVar}" is missing' in source, source[:500]


def _test_node_shared_room_router_contract() -> None:
    source = (Path(__file__).resolve().parent / "node_bridge" / "src" / "index.js").read_text(encoding="utf-8")
    controller = (Path(__file__).resolve().parent / "controller.py").read_text(encoding="utf-8")
    assert "const ncRouteEndpoint = ncTurnEndpoint.replace" in source, source[:500]
    assert "async function routeCapturedSpeech" in source, source[:500]
    assert "await routeCapturedSpeech(turn)" in source, source[:500]
    assert "tryCreateRouteLock" in source and "room_route_" in source, source[:500]
    assert "room_router_selected" in source, source[:500]
    assert "speaker_is_bot" in source, source[:500]
    assert "markAcceptedHumanRoute(decision, turn, routeKey)" in source, source[:500]
    assert "discardRoutedTurns: false" in source, source[:500]
    assert "accepted_route_key" in source, source[:500]
    assert "routedPayloadInvalidatedByHumanIntervention(payload)" in source, source[:500]
    assert "acceptedHumanInterventionRouteKey" in source, source[:500]
    assert "acceptedHumanInterventionTargetBotId" in source, source[:500]
    assert "turnState.acceptedHumanInterventionRouteKey" in source, source[:500]
    assert "const referenceMs = routedPayloadReferenceMs(payload);" in source, source[:500]
    assert "referenceMs < markerMs" in source, source[:500]
    assert "function shouldIgnoreSharedRouteInterrupt" in source, source[:500]
    assert "function moderatorProtectsCurrentSpeaker" in source, source[:500]
    assert 'safeFileSegment(state?.current_bot_id || "").toLowerCase()' in source, source[:500]
    assert "function markBotCurrentForTurn" in source, source[:500]
    assert "function clearCurrentBotIfTurnHasNoPlayback" in source, source[:500]
    assert "current_bot_turn_id: turnId" in source, source[:500]
    assert "markBotCurrentForTurn(turnState, \"bot_turn_start\")" in source, source[:500]
    assert "clearCurrentBotIfTurnHasNoPlayback(turnState, \"release_unplayed_current_bot\")" in source, source[:500]
    assert "current_bot_turn_id: String(next.turnId || \"\")" in source, source[:500]
    assert "currentTurnId && currentTurnId !== String(next.turnId || \"\")" in source, source[:500]
    turn_start_index = source.index("turnState.turnId = turnId;")
    mark_current_index = source.index("markBotCurrentForTurn(turnState, \"bot_turn_start\")", turn_start_index)
    fetch_index = source.index("response = await fetch(ncTurnEndpoint", mark_current_index)
    assert mark_current_index < fetch_index, source[turn_start_index:turn_start_index + 900]
    assert "function moderatorOverrideReasonSince" in source, source[:500]
    assert "function noRouteDecisionAfterModeratorOverride" in source, source[:500]
    assert "function stampRouteDecision" in source, source[:500]
    assert "function routeResultTimestampMs" in source, source[:500]
    assert "Existing route decision ignored after moderator override" in source, source[:500]
    assert "Captured speech route reconciled after moderator override" in source, source[:500]
    assert "Captured speech route queue reconciled after moderator override" in source, source[:500]
    assert "Route decision timed out; using current moderator route." in source, source[:500]
    assert "Waited route decision superseded by moderator route" in source, source[:500]
    assert "Waited route decision ignored after moderator override" in source, source[:500]
    assert "moderator_override:" in source, source[:500]
    assert "if (decision?.moderator_override)" in source, source[:500]
    assert "moderator_override: true" in source, source[:500]
    assert "created_at_ms: Date.now()" in source, source[:500]
    assert "writeFileSync(resultPath, JSON.stringify(decision, null, 2), \"utf8\");" in source, source[:500]
    captured_route_index = source.index("async function routeCapturedSpeech")
    captured_post_override_index = source.index("const postContextOverride = moderatorOverrideReasonSince", captured_route_index)
    captured_flow_index = source.index("appendModeratorRouteFlow(decision, turn, routeKey, decision?.source || \"room_router\")", captured_post_override_index)
    assert captured_post_override_index < captured_flow_index, source[captured_route_index:captured_route_index + 1200]
    assert "routeBotReplyText" in source and "routed_text_" in source, source[:500]
    assert "publishCompletedBotReplyText" in source, source[:500]
    assert "Preparing next routed bot reply ahead from completed text." in source, source[:500]
    assert "function shouldPrepareRoutedReplyAheadFromCompletedTurn" in source, source[:500]
    assert 'String(roomRouterMode || "").trim().toLowerCase() !== "llm_router"' in source, source[:500]
    assert "!turnState.waitForReplyFloor || turnState.replyFloorClaimed" in source, source[:500]
    assert "last_next_target_bot_id: \"\"" in source, source[:500]
    assert "if (!turnState.routedText)" not in source, "routed bot replies must still publish back to room routing/context"
    assert source.count("publishCompletedBotReplyText(String(payload.reply_text || \"\"), turnState);") == 1, source[:500]
    assert source.count("publishCompletedBotReplyText(String(event.reply_text || \"\"), turnState);") == 1, source[:500]
    assert "Ignoring bot audio start because direct bot text routing is enabled" in source, source[:500]
    assert "function hasPendingPlaybackForTurn" in source, source[:500]
    assert "function hasActivePlaybackForTurn" in source, source[:500]
    assert "function removeQueuedPlaybackForTurn" in source, source[:500]
    assert "removeQueuedPlaybackForTurn(turnId, reason)" in source, source[:500]
    assert "hasActivePlaybackForTurn(turnState.turnId)" in source, source[:500]
    assert "clearCurrentBotModeratorState(`drop_routed_turn:${reason || \"unknown\"}`, effectiveTurnId)" in source, source[:500]
    assert "function markReplyTurnComplete" in source, source[:500]
    assert "initialReplyBufferChunks" in source, source[:500]
    assert "function releaseInitialReplyBuffer" in source, source[:500]
    assert "playback_debug_${botInstanceId}.log" in source, source[:500]
    assert "function playbackDebug" in source, source[:500]
    assert "DISCORD_PLAYBACK_DEBUG" in source and "playback.debug_logging" in source, source[:500]
    assert "if (!playbackDebugEnabled)" in source, source[:500]
    assert "playback_start" in source and "playback_idle" in source, source[:500]
    assert "nc_audio_chunk" in source and "nc_done" in source, source[:500]
    assert "render_ready_chunks" in source and "playback_completed_chunks" in source, source[:500]
    assert "owns_reply_floor" in source and "reply_floor_owner_bot" in source, source[:500]
    assert "isReplyTurnComplete(next.turnId)" in source, source[:500]
    assert "const replyTurnFinished = Boolean(next.turnId && isReplyTurnComplete(next.turnId) && !hasPendingPlaybackForTurn(next.turnId));" in source, source[:500]
    assert "if (replyTurnFinished || !next.turnId)" in source, source[:500]
    assert source.index("playbackActive = false;") < source.index("const replyTurnFinished = Boolean(next.turnId && isReplyTurnComplete(next.turnId) && !hasPendingPlaybackForTurn(next.turnId));")
    assert "if (hasPendingPlaybackForTurn(turnId))" in source, source[:500]
    assert "prepareRoutedBotRepliesAhead" in source, source[:500]
    assert "persist_room_context_between_restarts" in source, source[:500]
    assert "resetRoomContextOnStartup" in source, source[:500]
    assert "broadcastRoomTurnToBotHistories(decision, turn, routeKey)" in source, source[:500]
    assert "recordUserTurnEndpointForCandidate" in source, source[:500]
    assert "/record_user_turn" in source, source[:500]
    assert "moderator_state_${safeFileSegment(voiceChannelId)}.json" in source, source[:500]
    assert "function moderatorDecisionForTurn" in source, source[:500]
    assert "let decision = moderatorDecisionForTurn(turn, routeKey);" in source, source[:500]
    assert "decision = await requestRoomRouteDecision(turn, routeKey);" in source, source[:500]
    assert "function moderatorManualPendingRoute" in source, source[:500]
    assert "routedPayloadInvalidatedByModeratorOverride" in source, source[:500]
    assert "dropRoutedTurnAfterModeratorOverride" in source, source[:500]
    assert "function maybeDropRoutedPreRenderAfterManualNext" in source, source[:500]
    assert "const candidates = [...replyProgressByTurnId.values()];" in source, source[:500]
    assert "if (activeReplyProgress && !candidates.includes(activeReplyProgress))" in source, source[:500]
    assert "if (!progress || progress.replyFloorDenied || progress.replyFloorClaimed || !progress.routedText)" not in source
    assert "pre-render invalidated by" in source, source[:500]
    assert source.count("maybeDropRoutedPreRenderAfterManualNext();") >= 4, source[:500]
    assert "function routedTextWriteBlockedByManualNext" in source, source[:500]
    assert "Routed bot text not queued after manual moderator Next" in source, source[:500]
    assert "dead_air_recovery_queue_blocked" in source, source[:500]
    assert "if (!writeRoutedTextTurn(moderatorId, {" in source, source[:500]
    assert "if (!writeRoutedTextTurn(target, {" in source, source[:500]
    assert source.count("startedAtMs: Date.now(),") >= 2, source[:500]
    assert "routedTargetBotId:" in source, source[:500]
    assert "routedTargetBotId: botInstanceId" in source, source[:500]
    assert "routedPayloadCreatedAtMs: Number(payload.created_at_ms || 0)" in source, source[:500]
    assert "function routedPickedPayloadInvalidationReason" in source, source[:500]
    assert "Routed turn rejected after pickup" in source, source[:500]
    assert "human_intervention_after_pickup" in source and "moderator_override_after_pickup" in source, source[:500]
    assert "function routedPayloadReferenceMs" in source, source[:500]
    assert "payload?.route_started_at_ms || payload?.decision?.route_started_at_ms" in source, source[:500]
    assert "routedPayloadRouteStartedAtMs" in source, source[:500]
    assert "return candidates.length > 0 ? Math.min(...candidates) : 0;" in source, source[:500]
    assert "const overrideReason = moderatorOverrideReasonSince(routeStartedAtMs);" in source, source[:500]
    assert "moderator_override:${overrideReason}" in source, source[:500]
    handle_turn_index = source.index("async function handleHttpNcTurn")
    picked_payload_index = source.index("const pickedPayloadInvalidationReason = routedPickedPayloadInvalidationReason(turn);", handle_turn_index)
    handle_turn_state_index = source.index("const turnState = {", handle_turn_index)
    assert picked_payload_index < handle_turn_state_index
    assert "function routedTurnModeratorStateInvalidationReason" in source, source[:500]
    assert "function routedTurnInvalidatedByModeratorState" in source, source[:500]
    assert "function dropRoutedTurnAfterModeratorStateChange" in source, source[:500]
    assert "const startModeratorStateReason = routedTurnModeratorStateInvalidationReason(turnState);" in source, source[:500]
    assert "routed_turn_start_rejected" in source, source[:500]
    assert "turnState.manualCallOn" in source, source[:500]
    assert "next_changed:" in source and "next_cleared" in source, source[:500]
    assert "pre-render invalidated by" in source, source[:500]
    assert "replyProgressByTurnId.delete(effectiveTurnId);" in source, source[:500]
    assert "activeReplyProgress = null;" in source, source[:500]
    assert "stream ${moderatorStateReason}" in source, source[:500]
    assert "reply floor claim ${moderatorStateReason}" in source, source[:500]
    assert "prepared floor wait ${moderatorStateReason}" in source, source[:500]
    assert "prepared playback wait ${moderatorStateReason}" in source, source[:500]
    assert "function completedBotTextRouteModeratorOverrideReason" in source, source[:500]
    assert "Completed bot text route skipped after moderator override" in source, source[:500]
    assert "Completed bot text route not queued after moderator override" in source, source[:500]
    assert "Completed bot text route queue skipped after moderator override" in source, source[:500]
    assert "Completed bot text route queue skipped after recovery override" in source, source[:500]
    bot_text_route_index = source.index("async function routeBotReplyText")
    bot_text_post_override_index = source.index("const postContextOverride = completedBotTextRouteModeratorOverrideReason", bot_text_route_index)
    bot_text_flow_index = source.index("appendModeratorRouteFlow(decision, turn, routeKey, decision?.source || \"bot_text_router\")", bot_text_post_override_index)
    assert bot_text_post_override_index < bot_text_flow_index, source[bot_text_route_index:bot_text_route_index + 1400]
    pre_queue_index = source.index("const preQueueOverride = completedBotTextRouteModeratorOverrideReason")
    assert pre_queue_index < source.index("await maybeQueueDeadAirRecovery", pre_queue_index)
    assert "manual_human_next" in source and "manual_human_current" in source and "manual_next" in source, source[:500]
    assert "function maybeRepublishCompletedTextForManualNext" in source, source[:500]
    assert "Manual Next override detected; preparing routed reply" in source, source[:500]
    assert "const isManual = Boolean(pending?.manual);" in source, source[:500]
    assert "userCommand: Boolean(pending?.user_command)" in source, source[:500]
    assert "&& manualPending.userCommand" in source, source[:500]
    assert "!manualPending.userCommand" in source, source[:500]
    assert "user_command: true" in source, source[:500]
    assert "user_command: false" in source, source[:500]
    assert "manualNextRepublishKey" in source, source[:500]
    assert "function completedBotTextRouteKey" in source, source[:500]
    assert "publishedCompletedTextRouteKeys" in source, source[:500]
    assert "exceptTargetBotId" not in source
    assert "Completed bot text route already published for this turn" in source, source[:500]
    assert "Completed bot text route already in progress" in source, source[:500]
    assert "function progressCounts" in source, source[:500]
    assert "function queuedAudioCountForStatus" in source, source[:500]
    assert "function clearReplyProgressForTurn" in source, source[:500]
    assert "function clearAllReplyProgress" in source, source[:500]
    assert "clearAllReplyProgress(reason || \"clear_playback\")" in source, source[:500]
    assert "releaseReplyFloor(\"\", { force: true, reason: `clear_playback:${reason || \"unknown\"}` });" in source, source[:500]
    assert "clearReplyProgressForTurn(turnId, reason);" in source, source[:500]
    assert "clearReplyProgressForTurn(failedTurnId, \"audio_error\")" in source, source[:500]
    assert "clearCurrentBotModeratorState(\"audio_error\", failedTurnId);" in source, source[:500]
    assert "const playbackProgress =" in source, source[:500]
    assert "inProgress: Boolean(playbackTurnId && localSpeaking" in source, source[:500]
    assert "allowRepublish: manualOverride" in source, source[:500]
    assert "botTextRoutePublishedAtMs" in source, source[:500]
    assert "botTextRouteInFlight" in source, source[:500]
    assert "botTextRouteAttemptAtMs" in source, source[:500]
    route_completed_block = source[source.index("function routeCompletedBotReplyTextNow"):source.index("function maybeRepublishCompletedTextForManualNext")]
    assert "turnState.botTextRouteInFlight && !manualOverride" in route_completed_block, route_completed_block
    assert route_completed_block.index("const routePromise = routeBotReplyText") < route_completed_block.index("turnState.botTextRoutePromise = routePromise;"), route_completed_block
    bot_text_route_block = source[source.index("async function routeBotReplyText"):source.index("function completedBotTextRouteKey")]
    assert bot_text_route_block.index("if (!tryCreateRouteLock(lockPath))") < bot_text_route_block.index("turnState.botTextRouteInFlight = true;"), bot_text_route_block
    assert "const preBroadcastTarget = safeFileSegment(decision?.target_bot_id || \"\").toLowerCase();" in bot_text_route_block, bot_text_route_block
    assert bot_text_route_block.index("await broadcastRoomTurnToBotHistories(decision, turn, routeKey);") < bot_text_route_block.index("writeFileSync(resultPath, JSON.stringify(decision, null, 2), \"utf8\");"), bot_text_route_block
    assert "includeSelectedTarget: true" in bot_text_route_block and "onlyCandidateIds: preBroadcastTarget ? [preBroadcastTarget] : []" in bot_text_route_block, bot_text_route_block
    assert "route_started_at_ms: routeStartedAtMs" in bot_text_route_block, bot_text_route_block
    assert bot_text_route_block.index("appendRoomContextFromDecision(decision);") < bot_text_route_block.index("writeFileSync(resultPath, JSON.stringify(decision, null, 2), \"utf8\");"), bot_text_route_block
    assert bot_text_route_block.index("writeFileSync(resultPath, JSON.stringify(decision, null, 2), \"utf8\");") < bot_text_route_block.index("turnState.botTextRoutePublished = true;"), bot_text_route_block
    assert bot_text_route_block.index("turnState.botTextRoutePublished = true;") < bot_text_route_block.index("turnState.publishedCompletedTextRouteKeys.add(routeKey);"), bot_text_route_block
    assert "turnState.botTextRouteInFlight = false;" in bot_text_route_block, bot_text_route_block
    assert 'source: "human_moderator"' in source, source[:500]
    assert "function routeCompletedBotReplyTextNow" in source, source[:500]
    assert "replyProgressByTurnId" in source, source[:500]
    assert "routeCompletedBotReplyTextNow(spokenReplyText(), completedProgress)" in source, source[:500]
    assert "function normalizeModeratorStateForWrite" in source, source[:500]
    assert "const normalized = normalizeModeratorStateForWrite(state);" in source, source[:500]
    assert 'next.current_bot_id = "";' in source, source[:500]
    assert 'next.current_bot_name = "";' in source, source[:500]
    assert "keepPendingHuman = pendingHumanMs > pendingBotMs;" in source, source[:500]
    assert "next.route_next_target_bot_id = pendingBotTarget;" in source, source[:500]
    assert 'next.route_next_target_bot_id = "";' in source, source[:500]
    assert "const target = safeFileSegment(pending?.target_bot_id || \"\").toLowerCase();" in source, source[:500]
    assert "pending?.target_bot_id || state?.route_next_target_bot_id" not in source
    assert "pending_route.target_bot_id\", \"\") or moderator_state.get(\"route_next_target_bot_id\")" not in controller
    assert "route_next_speaker_user_id" not in controller
    assert "current_speaker_user_id" not in controller
    assert "current_bot = str(moderator_state.get(\"current_bot_name\") or current_bot_id).strip() if current_bot_id else \"\"" in controller
    assert "return turnState.botTextRoutePromise || Promise.resolve(false);" in source, source[:500]
    assert "const routePromise = routeBotReplyText(inputText, turnState, {" in source, source[:500]
    assert "turnState.botTextRoutePromise = routePromise;" in source, source[:500]
    assert "voicePlayer.once(AudioPlayerStatus.Idle, async () => {" in source, source[:500]
    assert "await completeDeadAirRecoveryTurn(spokenReplyText(), completedProgress);" in source, source[:500]
    assert "await routeCompletedBotReplyTextNow(spokenReplyText(), completedProgress);" in source, source[:500]
    assert "maybePrepareDeadAirRecoveryNextFromCompletedText(String(event.reply_text || \"\"), turnState);" in source, source[:500]
    assert "maybePrepareDeadAirRecoveryNextAfterFloorClaim(turnState);" in source, source[:500]
    assert "turnState.deadAirRecoveryNextQueued || !turnState.replyFloorClaimed" in source, source[:500]
    assert "action === \"moderator_speaks_and_calls_next\" && !turnState?.deadAirRecoveryNextQueued" in source, source[:500]
    assert source.index("maybePrepareDeadAirRecoveryNextFromCompletedText(String(event.reply_text || \"\"), turnState);") < source.index("async function completeDeadAirRecoveryTurn")
    assert source.index("await routeCompletedBotReplyTextNow(spokenReplyText(), completedProgress);") < source.index("releaseReplyFloor(String(next.turnId));")
    awaited_route_index = source.index("await routeCompletedBotReplyTextNow(spokenReplyText(), completedProgress);")
    clear_current_after_route_index = source.index("current_bot_id: \"\"", awaited_route_index)
    assert awaited_route_index < clear_current_after_route_index < source.index("releaseReplyFloor(String(next.turnId));")
    assert "if (replyTurnFinished || !next.turnId) {\n      updateModeratorState" not in source
    assert "async function completeDeadAirRecoveryTurn" in source, source[:500]
    assert "await broadcastRoomTurnToBotHistories(decision, {" in source, source[:500]
    captured_route_index = source.index("async function routeCapturedSpeech")
    captured_block = source[captured_route_index:source.index("const waited = await waitForRouteDecision", captured_route_index)]
    assert "const preBroadcastTarget = safeFileSegment(decision?.target_bot_id || \"\").toLowerCase();" in captured_block, captured_block
    assert "includeSelectedTarget: true" in captured_block and "onlyCandidateIds: preBroadcastTarget ? [preBroadcastTarget] : []" in captured_block, captured_block
    assert "writeRoutedTurnForSelectedTarget(decision, turn, routeKey, routeStartedAtMs);" in captured_block, captured_block
    captured_broadcast_index = source.index("await broadcastRoomTurnToBotHistories(decision, turn, routeKey);", captured_route_index)
    captured_context_index = source.index("appendRoomContextFromDecision(decision);", captured_broadcast_index)
    captured_publish_index = source.index("writeFileSync(resultPath, JSON.stringify(decision, null, 2), \"utf8\");", captured_context_index)
    captured_queue_index = source.index("writeRoutedTurnForSelectedTarget(decision, turn, routeKey, routeStartedAtMs);", captured_broadcast_index)
    assert captured_broadcast_index < captured_context_index < captured_publish_index < captured_queue_index, source[captured_route_index:captured_route_index + 2600]
    bot_text_route_index = source.index("async function routeBotReplyText")
    bot_text_broadcast_index = source.index("await broadcastRoomTurnToBotHistories(decision, turn, routeKey);", bot_text_route_index)
    bot_text_context_index = source.index("appendRoomContextFromDecision(decision);", bot_text_broadcast_index)
    bot_text_publish_index = source.index("writeFileSync(resultPath, JSON.stringify(decision, null, 2), \"utf8\");", bot_text_context_index)
    bot_text_queue_index = source.index("writeRoutedTextTurn(target, {", bot_text_broadcast_index)
    assert bot_text_broadcast_index < bot_text_context_index < bot_text_publish_index < bot_text_queue_index, source[bot_text_route_index:bot_text_route_index + 3600]
    assert "allow_group_invitation_routing" in source, source[:500]
    assert "allow_open_room_invitation_routing" in source, source[:500]
    assert "ncProbeEndpoint" in source and "/probe_transcript" in source, source[:500]
    assert "pauseReplyPlaybackForTranscriptProbe" in source, source[:500]
    assert "resumeReplyPlaybackAfterTranscriptProbe" in source, source[:500]
    assert "function handleSkippedNcTurn" in source, source[:500]
    assert "speechAccepted" in source and "Valid speech produced no reply" in source, source[:500]
    runtime = (Path(__file__).resolve().parent / "runtime_server.py").read_text(encoding="utf-8")
    main_source = (Path(__file__).resolve().parent / "main.py").read_text(encoding="utf-8")
    assert 'if path == "/record_user_turn"' in runtime, runtime[:500]
    assert "def record_user_turn" in runtime, runtime[:500]
    assert "context_input_text" in runtime and "_recorded_external_route_keys" in runtime, runtime[:500]
    assert "def _history_storage_id" in runtime and "__channel_" in runtime, runtime[:500]
    assert '"nc_runtime": {' in main_source and '"http_endpoint": http_endpoint' in main_source, main_source[:500]
    assert "def erase_all_instance_contexts" in main_source, main_source[:500]
    assert 'glob(f"{safe_id}__channel_*.history.json")' in main_source, main_source[:500]


def _test_moderator_state_machine_contract() -> None:
    source = (Path(__file__).resolve().parent / "node_bridge" / "src" / "index.js").read_text(encoding="utf-8")
    controller = (Path(__file__).resolve().parent / "controller.py").read_text(encoding="utf-8")
    notes = (Path(__file__).resolve().parent / "moderator_state_machine_notes.md").read_text(encoding="utf-8")

    # Current/Next state has one normalizer and legacy mirrors must stay display-only.
    assert "function normalizeModeratorStateForWrite" in source, source[:500]
    assert "const currentBotIsLive = Boolean(currentBot && moderatorLiveTarget(currentBot));" in source, source[:500]
    assert "const effectiveCurrentBot = currentBotIsLive ? currentBot : \"\";" in source, source[:500]
    assert "const pendingBotIsLive = Boolean(pendingBotTarget && moderatorLiveTarget(pendingBotTarget));" in source, source[:500]
    assert "if (effectiveCurrentBot && currentHumanId)" in source, source[:500]
    assert "if (keepPendingBot && keepPendingHuman)" in source, source[:500]
    assert "let keepPendingBot = Boolean(pendingBotIsLive);" in source, source[:500]
    assert "next.route_next_target_bot_id = pendingBotTarget;" in source, source[:500]
    assert 'next.route_next_target_bot_id = "";' in source, source[:500]
    current_bot_helper = source[source.index("function moderatorHasCurrentBot"):source.index("function moderatorHasCurrentOrPendingSpeaker")]
    assert "moderatorLiveTarget(currentBot)" in current_bot_helper, current_bot_helper
    pending_bot_helper = source[source.index("function moderatorPendingBotRoute"):source.index("function setHumanCurrentFromRoute")]
    assert "moderatorLiveTarget(target)" in pending_bot_helper, pending_bot_helper
    manual_pending_helper = source[source.index("function moderatorManualPendingRoute"):source.index("function consumeModeratorPendingHumanRoute")]
    assert "moderatorLiveTarget(target)" in manual_pending_helper, manual_pending_helper
    assert "pending?.target_bot_id || state?.route_next_target_bot_id" not in source
    assert "pending_route.target_bot_id\", \"\") or moderator_state.get(\"route_next_target_bot_id\")" not in controller
    assert "route_next_speaker_user_id" not in controller
    assert "current_speaker_user_id" not in controller
    assert "`route_next_target_bot_id` is only a compatibility mirror" in notes, notes

    # Human Next must remain pending while a bot or human already owns Current.
    assert "function setHumanCurrentFromRoute" in source, source[:500]
    assert "options?.forcePending" in source, source[:500]
    assert "hasActiveBotPlayback()" in source, source[:500]
    assert "moderatorHasCurrentBot(stateBefore)" in source, source[:500]
    assert "moderator_route_next_human" in source, source[:500]
    assert "forcePending: true" in source, source[:500]
    assert "function promotePendingHumanRouteToCurrent" in source, source[:500]
    assert "if (hasActiveBotPlayback() || moderatorHasCurrentBot(state))" in source, source[:500]

    # Manual Next and Clear Pending must invalidate stale routed/prepared work.
    assert "function routedTextWriteBlockedByManualNext" in source, source[:500]
    assert "manual_next:" in source and "manual_human_next:" in source, source[:500]
    assert "function moderatorPendingBotRouteBlockReason" in source, source[:500]
    assert "sourceKind !== \"human_moderator\" && manualPending?.target" in source, source[:500]
    assert 'manual: sourceKind === "human_moderator"' in source, source[:500]
    assert "discardPendingRoutedTextTurns(`manual moderator route_next:${target}`)" in source, source[:500]
    assert "discardPendingRoutedTextTurns(`manual moderator route_next_human:${speakerName}`)" in source, source[:500]
    assert "discardPendingRoutedTextTurns(\"manual moderator clear_pending\")" in source, source[:500]
    assert "last_command_at_ms: lastCommandAtMs" in source, source[:500]
    assert "const commandAtMs = Date.now();" in source, source[:500]
    assert "last_command_at_ms: commandAtMs" in source, source[:500]
    assert "Number(state?.last_command_at_ms || 0)" in source, source[:500]
    assert 'String(state?.last_command || "") === "clear_pending"\n    ? Number(state?.updated_at_ms || 0)' not in source
    clear_pending_block = source[source.index('if (action === "moderator_clear_pending")'):source.index('if (action === "moderator_clear_floor")')]
    assert "lastModeratorState = readModeratorState();" in clear_pending_block, clear_pending_block
    assert 'last_next_target_bot_id: ""' in source, source[:500]
    assert "maybeDropRoutedPreRenderAfterManualNext();" in source, source[:500]
    assert "function routedPickedPayloadInvalidationReason" in source, source[:500]
    assert "Routed turn rejected after pickup" in source, source[:500]
    assert "routedPayloadInvalidatedByModeratorOverride(payload)" in source, source[:500]
    assert "function routedPayloadReferenceMs" in source, source[:500]
    assert "route_started_at_ms: Number(turn?.routedPayloadRouteStartedAtMs" in source, source[:500]
    assert "routedPayloadRouteStartedAtMs: Number(payload.route_started_at_ms" in source, source[:500]
    assert "route_started_at_ms: Number(routeStartedAtMs || 0)" in source, source[:500]
    assert "route_started_at_ms: routeStartedAtMs" in source, source[:500]
    assert "moderator_override:${overrideReason}" in source, source[:500]
    routed_write_block = source[source.index("function writeRoutedTextTurn"):source.index("function routedTextTurnPath")]
    assert routed_write_block.index("markModeratorPendingBotRoute(") < routed_write_block.index("writeFileSync(path"), routed_write_block
    assert "function clearModeratorPendingRouteIfKey" in source, source[:500]
    assert "if (error?.code !== \"EEXIST\")" in routed_write_block, routed_write_block
    assert "clearModeratorPendingRouteIfKey(routeKey, targetBotId, \"routed_text_write_failed\")" in routed_write_block, routed_write_block

    # Only the selected Next should prebuffer; old prepared chunks are dropped on state changes.
    assert "function shouldPrepareRoutedReplyAheadFromCompletedTurn" in source, source[:500]
    assert "return Boolean(!turnState.waitForReplyFloor || turnState.replyFloorClaimed);" in source, source[:500]
    assert "function maybeDropRoutedPreRenderAfterManualNext" in source, source[:500]
    assert "dropRoutedTurnAfterModeratorStateChange(" in source, source[:500]
    assert "prepared floor wait ${moderatorStateReason}" in source, source[:500]
    assert "prepared playback wait ${moderatorStateReason}" in source, source[:500]
    assert "clearReplyProgressForTurn" in source and "clearAllReplyProgress" in source, source[:500]

    # Handoff and dead-air recovery are gated by authoritative Current/Next.
    assert "await routeCompletedBotReplyTextNow(spokenReplyText(), completedProgress);" in source, source[:500]
    assert "releaseReplyFloor(String(next.turnId));" in source, source[:500]
    assert source.index("await routeCompletedBotReplyTextNow(spokenReplyText(), completedProgress);") < source.index("releaseReplyFloor(String(next.turnId));")
    assert "allowActiveCompletedCurrent" in source, source[:500]
    assert "prebuffering_after_current_speaker" in source, source[:500]
    assert "activeTurnId: String(turnState?.turnId || \"\")" in source, source[:500]
    assert source.index("await maybeQueueDeadAirRecovery(decision, turn, routeKey, decision?.source || \"bot_text_router\", {") < source.index("releaseReplyFloor(String(next.turnId));")
    assert "promotePendingHumanRouteToCurrent(\"bot playback finished\")" in source, source[:500]
    assert "function moderatorHasCurrentOrPendingSpeaker" in source, source[:500]
    assert "if (moderatorHasCurrentOrPendingSpeaker(state))" in source, source[:500]
    assert "if (moderatorHasCurrentOrPendingSpeaker())" in source, source[:500]
    assert "lastSilenceRecoveryActivityAtMs = lastRoomActivityAtMs;" in source, source[:500]
    assert "function turnNeedsTranscriptBeforeModeratorDecision" in source, source[:500]
    route_captured_block = source[source.index("async function routeCapturedSpeech"):source.index("function routeDecisionForThisBot")]
    assert "const needsTranscriptBeforeModeratorDecision = turnNeedsTranscriptBeforeModeratorDecision(turn);" in route_captured_block, route_captured_block
    assert "if (!needsTranscriptBeforeModeratorDecision)" in route_captured_block, route_captured_block
    assert "decision = moderatorDecisionForTurn(turn, routeKey);" in route_captured_block, route_captured_block
    assert "if (!decision)" in route_captured_block and "decision = await requestRoomRouteDecision(turn, routeKey);" in route_captured_block, route_captured_block
    assert "const transcriptTurn = turnWithRouteDecisionTranscript(turn, decision);" in route_captured_block, route_captured_block
    assert "const transcriptModeratorDecision = moderatorDecisionForTurn(transcriptTurn, routeKey);" in route_captured_block, route_captured_block
    assert "Applied moderator route after transcript was available." in route_captured_block, route_captured_block
    assert "function moderatorHumanCandidateAllowed" in source, source[:500]
    eligible_recovery_block = source[source.index("function eligibleRecoveryParticipants"):source.index("function eligibleRecoveryTargets")]
    assert "moderatorHumanCandidateAllowed(participant.userId, currentState)" in eligible_recovery_block, eligible_recovery_block
    room_candidates_block = source[source.index("function roomRouterCandidatesForTurn"):source.index("function liveRoomRouterCandidateBots")]
    assert "moderatorHumanCandidateAllowed(userId, currentState)" in room_candidates_block, room_candidates_block
    set_human_block = source[source.index("function setHumanCurrentFromRoute"):source.index("function setRecoveryHumanCurrent")]
    assert "const allowedHuman = moderatorHumanCandidateAllowed(userId, stateBefore);" in set_human_block, set_human_block
    assert "|| !allowedHuman" in set_human_block, set_human_block
    moderator_decision_block = source[source.index("function moderatorDecisionForTurn"):source.index("function consumeModeratorPendingRoute")]
    assert "const rawSpeakerBotId = safeFileSegment(turn?.speakerBotId || \"\").toLowerCase();" in moderator_decision_block, moderator_decision_block
    assert "const speakerIsBot = Boolean(turn?.speakerIsBot === true || (turn?.speakerIsBot !== false && rawSpeakerBotId && rawSpeakerBotId !== \"default\"));" in moderator_decision_block, moderator_decision_block
    assert "const speakerBotId = speakerIsBot ? rawSpeakerBotId : \"\";" in moderator_decision_block, moderator_decision_block
    assert "Ignoring non-bot speakerBotId" in moderator_decision_block, moderator_decision_block
    assert "if (speakerBotId && floorTarget === speakerBotId)" in moderator_decision_block, moderator_decision_block
    assert "human_moderator_speaker_lock_self" in moderator_decision_block, moderator_decision_block
    assert "function isTerminalModeratorNoRoute" in source, source[:500]
    decision_human_floor_block = source[source.index("function decisionWithHumanFloorIfNeeded"):source.index("function roundRobinRecoveryTarget")]
    assert "if (isTerminalModeratorNoRoute(decision))" in decision_human_floor_block, decision_human_floor_block
    dead_air_block = source[source.index("async function maybeQueueDeadAirRecovery"):source.index("function queueRecoveryNextTarget")]
    assert "if (isTerminalModeratorNoRoute(decision))" in dead_air_block, dead_air_block


def _test_dead_air_recovery_contract() -> None:
    node = (Path(__file__).resolve().parent / "node_bridge" / "src" / "index.js").read_text(encoding="utf-8")
    controller = (Path(__file__).resolve().parent / "controller.py").read_text(encoding="utf-8")
    schema_text = (Path(__file__).resolve().parent / "settings_schema.json").read_text(encoding="utf-8")
    main_source = (Path(__file__).resolve().parent / "main.py").read_text(encoding="utf-8")
    tiny_bridge = (Path(__file__).resolve().parent / "tiny_mvp" / "tiny_voice_bridge.py").read_text(encoding="utf-8")
    example_settings = json.loads((Path(__file__).resolve().parent / "settings.example.json").read_text(encoding="utf-8"))
    schema = json.loads(schema_text)
    assert "direct bot-text routing" in schema_text, schema_text[:500]
    assert example_settings["room_router"]["dead_air_recovery"]["silence_timeout_seconds"] >= 5.0
    silence_field = next(
        field
        for group in schema.get("groups", [])
        for field in group.get("fields", [])
        if field.get("key") == "room_router.dead_air_recovery.silence_timeout_seconds"
    )
    assert float(silence_field.get("default")) >= 5.0
    assert '"room_router.dead_air_recovery.silence_timeout_seconds", 10.0' in controller
    assert 'recovery.get("silence_timeout_seconds"), 10.0' in main_source
    assert 'recovery.get("silence_timeout_seconds", 10.0)' in tiny_bridge
    assert '"room_router.dead_air_recovery.silence_timeout_seconds", 10.0' in node
    assert "announce_control.setEnabled(bool(enabled and bot_selected))" in controller
    assert "def speak_text_direct" in tiny_bridge
    assert "const replyChunks = Array.isArray(result.reply_chunks)" in node
    assert "Manual Discord message chunk" in node
    assert "next_target = str(recovery.get(\"last_next_target_bot_id\") or \"none\").strip() if recovery_enabled else \"none\"" in controller
    assert "With LLM router, direct text routing, and reply-floor coordination enabled" in controller
    for key in (
        "room_router.dead_air_recovery.enabled",
        "room_router.dead_air_recovery.cooldown_seconds",
        "room_router.dead_air_recovery.silence_timeout_seconds",
        "room_router.dead_air_recovery.trigger_mode",
        "room_router.dead_air_recovery.action_mode",
        "room_router.dead_air_recovery.next_speaker_strategy",
        "room_router.dead_air_recovery.selected_fallback_target",
    ):
        assert key in schema_text, key
    for name in (
        "discord_dead_air_group",
        "discord_dead_air_enabled_checkbox",
        "discord_dead_air_cooldown_spin",
        "discord_dead_air_silence_timeout_spin",
        "discord_dead_air_trigger_combo",
        "discord_dead_air_action_combo",
        "discord_dead_air_strategy_combo",
        "discord_dead_air_fallback_target_combo",
        "discord_dead_air_status_label",
    ):
        assert name in controller, name
    for needle in (
        "async function maybeQueueDeadAirRecovery",
        "selectedModeratorTarget",
        "No active Moderator bot selected",
        "remainingMs > 0",
        "turn?.speakerBotId === moderatorEnforcerBotId()",
        "completeDeadAirRecoveryTurn",
        "maybePrepareDeadAirRecoveryNextFromCompletedText",
        "moderator_prebuffered_next",
        "deadAirRecoveryNextQueued",
        "queueRecoveryNextTarget",
        "setRecoveryHumanCurrent",
        "appendDeadAirRecoveryFlow",
        'targetBotId: deadAirRecoveryActionMode === "silent_call_next" ? nextTarget : moderatorId',
        "dead_air_recovery_to_moderator",
        'reason: String(options?.reason || "dead_air_recovery_next")',
        "dead_air_recovery",
        "deadAirRecoverySilenceTimeoutMs",
        "maybeQueueSilenceTimeoutRecovery",
        "silenceTimeoutRecovery",
        "isRoomQuietForRecovery",
        'noteRoomActivity("speech_end")',
        'noteRoomActivity("playback_idle")',
    ):
        assert needle in node, needle


def _test_tiny_mvp_local_mic_dead_air_waits_for_quiet_timeout() -> None:
    import addons.discord_voice_bridge.main as bridge_main

    settings = {
        "room_router": {
            "dead_air_recovery": {
                "enabled": True,
                "trigger_mode": "no_route_after_any_speech",
                "silence_timeout_seconds": 0.05,
            }
        }
    }
    calls: list[tuple[str, str, dict | None]] = []
    states = [
        {"current_id": "echo", "next_id": "", "playback_owner_id": "echo"},
        {"current_id": "echo", "next_id": "", "playback_owner_id": "echo"},
        {"current_id": "", "next_id": "", "playback_owner_id": ""},
        {"current_id": "", "next_id": "", "playback_owner_id": ""},
    ]

    def fake_http_json(method: str, url: str, payload: dict | None = None, *, timeout: float = 5.0) -> dict:
        calls.append((method, url, dict(payload or {}) if payload else None))
        if method == "GET":
            if states:
                return states.pop(0)
            return {"current_id": "", "next_id": "", "playback_owner_id": ""}
        return {"ok": True}

    original_http_json = bridge_main._http_json
    bridge_main._http_json = fake_http_json
    try:
        Addon._maybe_recover_tiny_mvp_dead_air("http://127.0.0.1:8788", settings, "no route")
        assert not any(method == "POST" and url.endswith("/dead-air") for method, url, _payload in calls)
        time.sleep(0.16)
        assert any(method == "POST" and url.endswith("/dead-air") for method, url, _payload in calls)
    finally:
        bridge_main._http_json = original_http_json


def _test_live_control_contract() -> None:
    controller = (Path(__file__).resolve().parent / "controller.py").read_text(encoding="utf-8")
    main_source = (Path(__file__).resolve().parent / "main.py").read_text(encoding="utf-8")
    runtime_source = (Path(__file__).resolve().parent / "runtime_server.py").read_text(encoding="utf-8")
    node = (Path(__file__).resolve().parent / "node_bridge" / "src" / "index.js").read_text(encoding="utf-8")
    required_controller_names = {
        "discord_live_bot_combo",
        "discord_live_start_button",
        "discord_live_stop_button",
        "discord_live_restart_button",
        "discord_live_disconnect_button",
        "discord_live_reconnect_button",
        "discord_live_stop_speech_button",
        "discord_live_clear_queue_button",
        "discord_live_reset_context_button",
        "discord_live_apply_selected_button",
        "discord_live_apply_global_button",
        "discord_live_apply_all_button",
        "discord_live_message_edit",
        "discord_live_send_message_button",
        "discord_render_ready_bar",
        "discord_preview_playback_bar",
        "discord_buffer_progress_label",
        "discord_bot_remove_all_context_button",
        "discord_bridge_moderator_tab",
        "discord_moderator_flow_group",
        "discord_moderator_now_label",
        "discord_moderator_next_label",
        "discord_moderator_badges_label",
        "discord_moderator_route_flow_group",
        "discord_moderator_route_flow_view",
        "route_flow_view.setFixedHeight(180)",
        "route_flow_view = QtWidgets.QPlainTextEdit(route_flow_group)",
        "route_flow_view.setReadOnly(True)",
        "route_flow_view.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)",
        "discord_dead_air_group",
        "discord_dead_air_enabled_checkbox",
        "discord_dead_air_cooldown_spin",
        "discord_dead_air_silence_timeout_spin",
        "discord_dead_air_trigger_combo",
        "discord_dead_air_action_combo",
        "discord_dead_air_strategy_combo",
        "discord_dead_air_fallback_target_combo",
        "discord_dead_air_status_label",
        "discord_moderator_bot_floor_label",
        "discord_moderator_human_floor_label",
        "discord_moderator_last_command_label",
        "discord_moderator_last_route_label",
        "discord_moderator_selected_action_label",
        "discord_moderator_warning_label",
        "discord_moderator_next_action_label",
        "discord_moderator_shortcuts_group",
        "discord_moderator_shortcuts_container",
        "discord_moderator_shortcuts_hint_label",
        "discord_moderator_target_combo",
        "discord_moderator_instances_table",
        "discord_moderator_participants_table",
        "discord_moderator_route_next_button",
        "discord_moderator_give_floor_button",
        "discord_moderator_mute_button",
        "discord_moderator_unmute_button",
        "discord_moderator_clear_pending_button",
        "discord_moderator_clear_floor_button",
        "discord_moderator_clear_button",
        "discord_moderator_stop_all_button",
        "discord_moderator_clear_all_queues_button",
        "discord_moderator_set_enforcer_button",
        "discord_moderator_clear_enforcer_button",
        "discord_moderator_enforce_mute_checkbox",
        "discord_moderator_allow_interrupt_current_checkbox",
        "discord_moderator_announcement_edit",
        "discord_moderator_announce_button",
        "discord_moderator_call_on_button",
    }
    missing = sorted(name for name in required_controller_names if name not in controller)
    assert not missing, missing
    assert "Allow Only This Bot" not in controller
    assert "discord_moderator_mute_all_except_button" not in controller
    assert "_latest_answered_route_target" not in controller
    assert "_dead_air_recovery_route_target" not in controller
    assert "allow_inferred_next" not in controller
    assert "routed_next" not in controller
    assert 'combo.addItem("No bot target available", "")' in controller, controller[:500]
    assert 'selected == "default"' in controller, controller[:500]
    for needle in (
        "Set Next Speaker",
        "Allow Only This Speaker",
        "Call Target Now",
        "Allowed speaker",
        "Speaker lock",
        "Speaker rule",
        "Route Flow",
        "Route decisions appear here",
        "_route_flow_line",
        "_capture_table_refresh_state",
        "_restore_table_refresh_state",
        "_restore_table_refresh_state_now",
        "QtCore.QTimer.singleShot(0",
        "_set_route_flow_text_preserving_scroll",
        "_append_route_flow_text_preserving_scroll",
        "_route_flow_rendered_lines",
        "_route_flow_rendered_keys",
        "_route_flow_entry_key",
        "_restore_scroll_bar_value_deferred",
        'entry.get("target_name")',
        "Unified room participants",
        "After current speech ends, route next turn to:",
        "Room quiet: make a bot speak now:",
        "active calls are only enabled while the room is quiet",
        "Use Next buttons while someone is speaking",
        "_moderator_badges_html",
        'if item["kind"] == "bot" and item_id == pending:',
        "pending_human_id and item_id == pending_human_id",
        "current_bot and item_id == current_bot",
        "if instance_id and instance_id == current_bot:",
        "This bot currently owns the moderator floor.",
        "discord_moderator_last_route_label",
        "discord_moderator_selected_action_label",
        "Selected participant:",
        "one-shot route",
        "Persistent speaker lock",
        "Next: {participant['name']}",
        "Make this participant the next speaker.",
        "This participant currently has the floor.",
        "This participant is queued as the next routed speaker.",
        "Only this participant's next speech is accepted.",
        "participants.setColumnHidden(2, True)",
        "Allow Interrupt Current",
        "Use Selected As Moderator Bot",
        "Clear Moderator Bot",
        "Enforce Current With Discord Mute",
        "Mute Participant",
        "Unmute Participant",
        "muted_speaker_user_ids",
        "_moderator_warning_text",
        "Choose a connected participant",
        "participant_table.clearSelection()",
        "bot_table.clearSelection()",
        'if not item.get("runtime_connected") and not item.get("endpoint_running"):',
    ):
        assert needle in controller, needle
    assert "view.setMaximumBlockCount(80)" not in controller
    moderator_instances_block = controller[
        controller.index('table = self._control("discord_moderator_instances_table", QtWidgets.QTableWidget)'):
        controller.index("self._refresh_moderator_participants_table(instances)")
    ]
    assert "_capture_table_refresh_state(table)" in moderator_instances_block
    assert "_restore_table_refresh_state(table, table_state)" in moderator_instances_block
    moderator_participants_block = controller[
        controller.index("def _refresh_moderator_participants_table"):
        controller.index("def _refresh_moderator_action_buttons")
    ]
    assert "_capture_table_refresh_state(table)" in moderator_participants_block
    assert "_restore_table_refresh_state(table, table_state)" in moderator_participants_block
    route_flow_block = controller[
        controller.index("def _refresh_moderator_route_flow"):
        controller.index("def _refresh_dead_air_status")
    ]
    assert "_append_route_flow_text_preserving_scroll(view, added_lines)" in route_flow_block
    assert "_set_route_flow_text_preserving_scroll(view, [\"No shared route flow yet.\"])" in route_flow_block
    assert "self._route_flow_rendered_lines.extend(added_lines)" in route_flow_block
    assert "self._route_flow_rendered_keys.add(key)" in route_flow_block
    assert "_route_flow_overlap_count" not in route_flow_block
    assert "_set_plain_text_preserving_scroll(view, text)" not in route_flow_block
    for needle in (
        "view.toPlainText().strip()",
    ):
        assert needle in route_flow_block, needle
    route_flow_append_block = controller[
        controller.index("def _route_flow_text_state"):
        controller.index("def _route_flow_entry_key")
    ]
    assert "setTextCursor" not in route_flow_append_block
    assert "ensureCursorVisible" not in route_flow_append_block
    assert "was_at_bottom" in route_flow_append_block
    assert "vertical_value >= max(0, vertical_max - 2)" in route_flow_append_block
    assert "QtCore.QTimer.singleShot(0" not in route_flow_append_block
    assert "ROUTE_FLOW_SCROLL_DEBUG_PATH" not in controller
    assert "_route_flow_scroll_debug" not in controller
    assert "_route_flow_deferred_probe" not in controller
    assert "_restore_plain_text_scroll_anchor_deferred" not in controller
    assert "view.setCurrentRow" not in route_flow_append_block
    assert "PositionAtBottom" not in route_flow_append_block
    assert "vertical_bar.setValue(vertical_bar.maximum())" in route_flow_append_block
    route_flow_widget_block = controller[
        controller.index('route_flow_view.setObjectName("discord_moderator_route_flow_view")'):
        controller.index("route_flow_layout.addWidget(route_flow_view)")
    ]
    assert "setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)" in route_flow_widget_block
    assert "setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)" not in route_flow_widget_block
    assert 'next_text = "Queued audio: " + ", ".join(queued)' not in controller
    ui_source = (Path(__file__).resolve().parent / "ui" / "discord_voice_bridge.ui").read_text(encoding="utf-8")
    assert "discord_persist_bot_history_checkbox" not in ui_source
    assert "Persist bot history between restarts" not in ui_source
    for needle in (
        "start_bridge_instance",
        "stop_bridge_instance",
        "restart_bridge_instance",
        "send_instance_command",
        "apply_live_settings",
        "reset_instance_context",
        "NC_DISCORD_BRIDGE_COMMAND_JSONL",
    ):
        assert needle in main_source, needle
    for needle in (
        "processCommandInbox",
        "handleLiveCommand",
        "stop_speech",
        "clear_queue",
        "reset_context",
        "send_message",
        "ncSpeakEndpoint",
        "speakLiveMessage",
        "reload_settings",
        "moderator_route_next",
        "moderator_route_next_human",
        "moderator_give_floor",
        "moderator_mute",
        "moderator_mute_human",
        "moderator_unmute_human",
        "moderator_give_human_floor",
        "moderator_set_current_interruption",
        "moderator_set_enforcer",
        "moderator_clear_enforcer",
        "moderator_set_mute_enforcement",
        "applyDiscordMuteEnforcement",
        "watchModeratorMuteEnforcement",
        "lastModeratorMuteEnforcementKey",
        "appendModeratorRouteFlow",
        "maybeQueueDeadAirRecovery",
        "roomRouterCandidatesForTurn",
        "`human:${userId}`",
        "raw)) {\n    const userId = raw.slice(raw.indexOf(\"_\") + 1).trim();",
        "humanTargetFromNoRoute",
        "genericHumanRoomTalk",
        "reasonLooksHumanDirected = !genericHumanRoomTalk",
        "human-to-human",
        "not a specific bot",
        "decisionWithHumanFloorIfNeeded",
        "setHumanCurrentFromRoute",
        "human_floor:",
        "completeDeadAirRecoveryTurn",
        "maybePrepareDeadAirRecoveryNextFromCompletedText",
        "deadAirRecoveryNextQueued",
        "moderator_prebuffered_next",
        "dead_air_recovery",
        "route_flow",
        "target_name",
        "clearDiscordMuteLedger",
        "discord_muted_user_ids",
        "current_bot_discord_user_id",
        "setMute",
        "moderator_call_on",
        "callOnThisBot",
        "manualCallOn",
        "manual_call_on",
        "Respond now, continuing naturally from the latest shared room context.",
        "pendingTarget = \"\"",
        "return null;",
        "moderatorAllowsHumanSpeaker",
        "moderatorPendingHumanRoute",
        "moderatorCurrentHumanRoute",
        "return String(userId || \"\").trim() === pending.userId;",
        "function moderatorPendingBotRoute",
        "function moderatorPendingBotRouteBlockReason",
        "function moderatorBotTargetIsMuted",
        "target_already_current:",
        "target_muted:",
        "Routed bot text not queued because moderator state rejected target",
        "Pending bot route rejected by moderator state",
        "function moderatorHasCurrentBot",
        "function moderatorHasCurrentOrPendingSpeaker",
        "hasActiveBotPlayback() || moderatorHasCurrentBot(state)",
        "moderatorHasCurrentBot(stateBefore)",
        "const botOwnsCurrent = Boolean(hasActiveBotPlayback() || moderatorHasCurrentBot(stateBefore));",
        "currentHumanBefore?.userId === userId && !botOwnsCurrent",
        "current_human_route: {},",
        "last_command || \"\") === \"clear_pending\"",
        "manual moderator clear_pending",
        "manual moderator route_next_human:",
        "forcePending: true",
        "Accepted pending human speaker",
        "human_moderator_waiting_for_human",
        "consumeModeratorPendingHumanRoute(routeKey)",
        '"queued next"',
        "Human speaker is already current",
        "pending route cleared",
        "speaker_control_active",
        "moderatorAllowsCurrentInterruption",
        "moderatorProtectsCurrentSpeaker",
        "promotePendingHumanRouteToCurrent",
        "markModeratorPendingBotRoute",
        'const sourceKind = String(source || "router").trim().toLowerCase();',
        'if (sourceKind !== "human_moderator" && manualPending?.target)',
        'if (sourceKind !== "human_moderator" && (humanPending?.userId || humanPending?.name))',
        "maybeRouteCompletedBotTextAfterFloorClaim",
        "Prepared bot owns floor; routing completed text ahead.",
        "consumeModeratorPendingRouteIfTarget",
        "reply_floor_claimed",
        "human_moderator_route_after_human",
        "moderatorHumanMuted",
        "pending_human_route",
        "current_human_route",
        "floor_speaker_user_id",
        "last_command",
        "moderator_clear_pending",
        "last_next_target_bot_id: \"\"",
        "moderator_clear_floor",
        "moderator_clear",
        'discardPendingRoutedTextTurns("manual moderator clear")',
        "lastModeratorState = readModeratorState();",
        "current_bot_turn_id",
        "handleModeratorCommand",
        'target === "default"',
        "last_route_decision",
        "last_transcript",
        "queued_audio",
        "render_ready_chunks",
        "playback_completed_chunks",
        "activeReplyProgress = null",
        "disabled_moderator_muted",
        "The selected Moderator bot is muted or excluded by moderator floor control.",
        'source === "human_moderator"',
        'reason === "moderator_muted"',
        'reason.startsWith("human_moderator_waiting_for_")',
    ):
        assert needle in node, needle
    assert "moderatorHumanRouteIsActive" not in node
    manual_next_index = node.index("if (action === \"moderator_route_next\")")
    manual_next_block = node[manual_next_index:manual_next_index + 1800]
    assert "pending_human_route: {}" in manual_next_block
    assert "route_next_speaker_user_id: \"\"" in manual_next_block
    assert "route_next_speaker_name: \"\"" in manual_next_block
    current_branch = manual_next_block[manual_next_block.index("Bot ${target} is already current; pending route cleared."):]
    assert "maybeDropRoutedPreRenderAfterManualNext();" in current_branch
    give_human_floor_block = node[node.index("if (action === \"moderator_give_human_floor\")"):node.index("if (action === \"moderator_mute_human\")")]
    assert "manual moderator give_human_floor:" in give_human_floor_block
    assert "maybeDropRoutedPreRenderAfterManualNext();" in give_human_floor_block
    give_floor_block = node[node.index("if (action === \"moderator_give_floor\")"):node.index("if (action === \"moderator_mute\")")]
    assert "manual moderator give_floor:" in give_floor_block
    assert "maybeDropRoutedPreRenderAfterManualNext();" in give_floor_block
    only_block = node[node.index("if (action === \"moderator_mute_all_except\")"):node.index("if (action === \"moderator_clear_pending\")")]
    assert "manual moderator only:" in only_block
    assert "pending_route: {}" in only_block
    assert "route_next_target_bot_id: \"\"" in only_block
    assert "maybeDropRoutedPreRenderAfterManualNext();" in only_block
    mute_human_block = node[node.index("if (action === \"moderator_mute_human\")"):node.index("if (action === \"moderator_unmute_human\")")]
    assert "clearsPending" in mute_human_block
    assert "clearsCurrent" in mute_human_block
    assert "clearsFloor" in mute_human_block
    assert "maybeDropRoutedPreRenderAfterManualNext();" in mute_human_block
    mute_bot_block = node[node.index("if (action === \"moderator_mute\")"):node.index("if (action === \"moderator_unmute\")")]
    assert "manual moderator mute:" in mute_bot_block
    assert "pendingTarget === target" in mute_bot_block
    assert "floorTarget === target" in mute_bot_block
    assert "maybeDropRoutedPreRenderAfterManualNext();" in mute_bot_block
    for needle in (
        "async function broadcastRoomTurnToBotHistories(decision, turn, routeKey, options = {})",
        "includeSelectedTarget",
        "onlyCandidateIds",
    ):
        assert needle in node, needle
    for needle in (
        "_manual_call_on_input_text",
        "record_input_history",
        'rstrip("/") == "/record_user_turn"',
        "Continue the current Discord voice conversation from your perspective.",
    ):
        assert needle in runtime_source, needle


def _test_stream_chunker_keeps_word_boundaries() -> None:
    from core.streaming_text import StreamingChunkAssembler

    text = "short safe " + "supercalifragilisticexpialidocious" + " tail"
    chunks = StreamingChunkAssembler(20, 30).feed(text)
    assert chunks, chunks
    assert chunks[0]["text"].endswith("safe"), chunks[0]
    assert "supercalifragilis" not in chunks[0]["text"], chunks[0]

    long_first_phrase = " ".join(["word"] * 32)
    chunks = StreamingChunkAssembler(
        220,
        320,
        config_getter=lambda key, default=None: {
            "stream_first_chunk_min_chars": 80,
            "stream_force_flush_seconds": 10.0,
            "stream_force_flush_later_seconds": 10.0,
        }.get(key, default),
    ).feed(long_first_phrase)
    assert not chunks, chunks


def _test_stream_chunker_timeout_prefers_short_whitespace_over_midword() -> None:
    from core.streaming_text import StreamingChunkAssembler

    now = [0.0]
    config = {
        "stream_first_chunk_min_chars": 80,
        "stream_force_flush_seconds": 1.0,
        "stream_force_flush_later_seconds": 2.0,
    }
    assembler = StreamingChunkAssembler(
        220,
        320,
        config_getter=lambda key, default=None: config.get(key, default),
        clock=lambda: now[0],
    )
    assembler.emission_count = 1
    text = ("safe " * 20).rstrip() + " unfinishedtailwithletters"
    assert len(text) > 110, len(text)
    assert " " not in text[109:], text[109:]
    assert assembler.feed(text) == []

    now[0] = 3.0
    chunks = assembler.feed("")
    assert chunks, "timeout should emit a chunk"
    assert chunks[0]["text"].endswith("safe"), chunks[0]
    assert "unfinishedtail" not in chunks[0]["text"], chunks[0]
    assert "panic" not in chunks[0]["reason"], chunks[0]


def _test_stream_chunker_does_not_carry_vocal_tags_as_emotions() -> None:
    from core import text_tags
    from core.streaming_text import StreamingChunkAssembler

    assembler = StreamingChunkAssembler(
        20,
        60,
        available_emotion_tags_getter=lambda: ["[chuckle]"],
        last_emotion_getter=lambda text: text_tags.get_last_emotion_tag(text, ["chuckle"]),
    )
    first = assembler.feed("[chuckle] Hello there.", final=True)
    assert first and first[0]["text"].startswith("[chuckle]"), first

    second = assembler.feed("This next chunk should not inherit the vocal sound.", final=True)
    assert second, second
    assert not second[0]["text"].startswith("[chuckle]"), second


def _test_runtime_emotion_names_exclude_vocal_tags() -> None:
    server = DiscordVoiceRuntimeServer(settings={}, logger=None, bridge_token="", addon_context=None)
    names = set(server._available_emotion_names({
        "emotional_instructions": (
            "VISUAL EMOTIONS: [neutral] [surprised] [angry]\n"
            "VOCAL EXPRESSIONS: [laugh] [chuckle] [sigh] [groan] [gasp] [clear throat] [sniff]"
        )
    }))
    assert {"neutral", "surprised", "angry"}.issubset(names), names
    assert not (names & {"laugh", "chuckle", "sigh", "groan", "gasp", "clear throat", "sniff"}), names


def _test_runtime_stream_chunk_debug_line() -> None:
    line = DiscordVoiceRuntimeServer._stream_chunk_debug_line(
        phase="stream",
        chunk_index=2,
        chunk_text="This is the text used for TTS.",
        chunk_info={"reason": "strong", "chars": 31, "quality": 1.0},
        target_chars=220,
        max_chars=320,
        runtime_config={
            "stream_first_chunk_min_chars": 80,
            "stream_force_flush_seconds": 0.31,
            "stream_force_flush_later_seconds": 0.61,
        },
    )
    assert "stream chunk phase=stream index=2" in line, line
    assert "chars=31" in line, line
    assert "reason=strong" in line, line
    assert "target=220 max=320 first_min=80 flush=0.31/0.61" in line, line
    assert "text=This is the text used for TTS." in line, line


def _test_runtime_stream_chunk_debug_writes_stdout() -> None:
    server = DiscordVoiceRuntimeServer(settings={}, logger=None, bridge_token="", addon_context=None)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        server._emit_stream_chunk_debug("stream chunk phase=stream index=0 chars=120")
    output = buffer.getvalue()
    assert "[DiscordBridgeChunk] stream chunk phase=stream index=0 chars=120" in output, output


def _test_runtime_stream_config_reads_dynamic_buffer_lead() -> None:
    config = {"_stream_buffer_lead_seconds_getter": lambda: 3.25}
    assert DiscordVoiceRuntimeServer._stream_config_value(config, "stream_buffer_lead_seconds", 0.0) == 3.25
    assert DiscordVoiceRuntimeServer._stream_config_value(config, "stream_force_flush_later_seconds", 0.7) == 0.7


def _test_runtime_live_settings_update() -> None:
    server = DiscordVoiceRuntimeServer(
        settings={
            "id": "echo",
            "chat": {"context_entries": 12},
            "persona": {"system_prompt": "Old prompt", "voice_clone_wav": "old.wav"},
            "playback": {"reply_immunity_seconds": 4.0},
        },
        logger=None,
        bridge_token="",
        addon_context=None,
    )
    result = server.apply_live_settings(
        {
            "id": "echo",
            "chat": {"context_entries": 3},
            "persona": {"system_prompt": "New prompt", "voice_clone_wav": "new.wav"},
            "playback": {"reply_immunity_seconds": 1.5},
            "discord": {"token_env_var": "SHOULD_NOT_LIVE_APPLY"},
        }
    )
    assert result["ok"], result
    assert server.settings["chat"]["context_entries"] == 3, server.settings
    assert server.settings["persona"]["system_prompt"] == "New prompt", server.settings
    assert server.settings["persona"]["voice_clone_wav"] == "new.wav", server.settings
    assert server.settings["playback"]["reply_immunity_seconds"] == 1.5, server.settings
    assert "discord" not in server.settings, server.settings


def _test_global_live_settings_do_not_select_fallback_bot() -> None:
    source = (Path(__file__).resolve().parent / "main.py").read_text(encoding="utf-8")
    assert 'requested = _safe_instance_id(instance_id) if str(instance_id or "").strip() else ""' in source
    assert 'requested = _safe_instance_id(instance_id or "")' not in source


def _test_bot_chat_model_item_normalization() -> None:
    source = (Path(__file__).resolve().parent / "controller.py").read_text(encoding="utf-8")
    assert "def _chat_model_name_from_provider_item" in source
    assert 'for key in ("id", "name", "model")' in source
    assert "str(item or \"\").strip()" in source


def _test_runtime_reply_chat_model_override() -> None:
    server = DiscordVoiceRuntimeServer(
        settings={
            "chat": {
                "use_global_model": False,
                "provider": "ollama",
                "model_name": "nova-model",
            },
        },
        logger=None,
        bridge_token="",
        addon_context=None,
    )
    config = server._reply_runtime_config({"chat_provider": "lmstudio", "model_name": "global-model", "stream_mode": True})
    assert config["chat_provider"] == "ollama", config
    assert config["model_name"] == "nova-model", config
    assert config["stream_mode"] is True, config
    assert server._settings_bool("Off", True) is False
    assert server._settings_bool("On", False) is True

    server_global = DiscordVoiceRuntimeServer(
        settings={"chat": {"use_global_model": True, "provider": "ollama", "model_name": "ignored-model"}},
        logger=None,
        bridge_token="",
        addon_context=None,
    )
    global_config = server_global._reply_runtime_config({"chat_provider": "lmstudio", "model_name": "global-model"})
    assert global_config["chat_provider"] == "lmstudio", global_config
    assert global_config["model_name"] == "global-model", global_config


def _test_node_dependency_diagnostics() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        bridge_dir = Path(tmp)
        (bridge_dir / "src").mkdir(parents=True)
        (bridge_dir / "src" / "index.js").write_text("console.log('ok');\n", encoding="utf-8")
        (bridge_dir / "package.json").write_text("{}", encoding="utf-8")

        issues = _node_bridge_environment_issues(bridge_dir=bridge_dir, require_install=True)
        assert any("dependencies are not installed" in item["message"] for item in issues), issues

        for package in NODE_BRIDGE_REQUIRED_PACKAGES:
            (bridge_dir / "node_modules" / Path(*package.split("/"))).mkdir(parents=True, exist_ok=True)
        issues = _node_bridge_environment_issues(bridge_dir=bridge_dir, require_install=True)
        dependency_errors = [
            item for item in issues
            if item["severity"] == "error" and "dependencies" in item["message"].lower()
        ]
        assert not dependency_errors, issues


def _test_node_dependency_first_run_prompt_contract() -> None:
    source = (Path(__file__).resolve().parent / "controller.py").read_text(encoding="utf-8")
    assert "_maybe_prompt_node_bridge_dependencies" in source
    assert "_schedule_node_dependency_prompt" in source
    assert "This addon requires Node bridge dependencies" in source
    assert "https://nodejs.org" in source
    assert '_run_bridge_operation("install node deps", installer)' in source


def _test_node_install_blocks_when_bridge_running() -> None:
    class FakeProcess:
        def poll(self):
            return None

    class FakeInstance:
        instance_id = "echo"
        process = FakeProcess()
        runtime_server = None

    assert _bridge_instance_is_running(FakeInstance())
    addon = Addon()
    addon._bridge_instances = [FakeInstance()]
    try:
        addon.install_node_bridge_dependencies()
    except RuntimeError as exc:
        assert "Stop the Discord bridge" in str(exc), exc
    else:
        raise AssertionError("install_node_bridge_dependencies should refuse while a bridge instance is running")


def _test_start_on_launch_persists_on_user_click() -> None:
    source = (Path(__file__).resolve().parent / "controller.py").read_text(encoding="utf-8")
    assert "discord_start_on_launch_checkbox" in source
    assert "start_on_launch.clicked.connect(self._persist_start_on_launch_setting)" in source
    assert "def _persist_start_on_launch_setting" in source
    assert '"start_on_nc_launch": bool(checked)' in source


def _test_voice_clone_wav_validation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        voices = root / "voices"
        voices.mkdir()
        (voices / "echo.wav").write_bytes(b"RIFFfake")

        assert not _voice_clone_wav_issues("echo.wav", scope="echo", app_root=root)
        missing = _voice_clone_wav_issues("missing.wav", scope="echo", app_root=root)
        assert any("not found" in item["message"] for item in missing), missing

        bad_extension = _voice_clone_wav_issues("echo.mp3", scope="echo", app_root=root)
        assert any(".wav" in item["message"] for item in bad_extension), bad_extension

        traversal = _voice_clone_wav_issues("..\\outside.wav", scope="echo", app_root=root)
        assert any("inside the root voices folder" in item["message"] for item in traversal), traversal


if __name__ == "__main__":
    raise SystemExit(main())
