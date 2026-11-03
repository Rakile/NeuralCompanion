"""Complete typed native-QML adapter for Discord Voice Bridge."""

from __future__ import annotations

from .discord_moderator import moderator_view, participant_value, room_participants, route_line
from .discord_local_room import local_room_action, local_room_controls

import copy
import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from PySide6 import QtCore, QtGui

from addons.discord_voice_bridge.native_contract import NATIVE_CONTROL_SPECS
from addons.discord_voice_bridge.bot_accounts import safe_avatar_url
from ui.qml_bridge.adapters.card_layout import apply_card_layout
from ui.qml_bridge.adapters.parity_contract import controls_from_specs, sections_from_specs
from ui.qml_bridge.native_contracts import NativeControl, NativeControlKind, NativeSurface, choices
from ui.qml_bridge.native_registry import NativeSurfaceAdapter
from ui.qml_bridge.voice_references import local_voice_reference_files
from ui.qml_bridge.quick_persona_store import QuickPersonaStore


_APP_ROOT = Path(__file__).resolve().parents[3]
_VOICE_CONTROLS = {"discord_voice_clone_wav_edit", "discord_bot_voice_clone_wav_edit"}


def _voice_choices(files: tuple[Path, ...], configured: Any) -> tuple[tuple[str, str], ...]:
    # Discord resolves relative references from voices/, unlike Persona's paths.
    saved = str(configured or "")
    matched = saved.strip()
    # Keep option values identical to the snapshot for exact QML selection.
    options = [(saved if not matched else "", "Default (no voice override)")]
    for path in files:
        value = saved if path.name.lower() == matched.lower() else path.name
        options.append((value, path.name))
    if saved and not any(value == saved for value, _label in options):
        # Keep custom, external and missing references selectable without rewriting them.
        options.append((saved, f"{matched} (saved reference)"))
    return tuple(options)


_CONTROL_SETTINGS = {
    "discord_dead_air_enabled_checkbox": "room_router.dead_air_recovery.enabled",
    "discord_dead_air_cooldown_spin": "room_router.dead_air_recovery.cooldown_seconds",
    "discord_dead_air_silence_timeout_spin": "room_router.dead_air_recovery.silence_timeout_seconds",
    "discord_dead_air_trigger_combo": "room_router.dead_air_recovery.trigger_mode",
    "discord_dead_air_action_combo": "room_router.dead_air_recovery.action_mode",
    "discord_dead_air_strategy_combo": "room_router.dead_air_recovery.next_speaker_strategy",
    "discord_dead_air_fallback_target_combo": "room_router.dead_air_recovery.selected_fallback_target",
    "discord_route_protected_mic_speech_checkbox": "playback.route_protected_mic_speech",
    "discord_runtime_host_edit": "nc_runtime.host",
    "discord_runtime_port_spin": "nc_runtime.port",
    "discord_session_mode_combo": "nc_runtime.session_mode",
    "discord_use_selected_stt_checkbox": "nc_runtime.use_selected_stt",
    "discord_use_selected_chat_checkbox": "nc_runtime.use_selected_chat_provider",
    "discord_use_selected_tts_checkbox": "nc_runtime.use_selected_tts",
    "discord_allow_non_localhost_checkbox": "nc_runtime.allow_non_localhost",
    "discord_wav_max_age_minutes_spin": "cleanup.wav_max_age_minutes",
    "discord_cleanup_interval_minutes_spin": "cleanup.interval_minutes",
    "discord_use_rag_context_checkbox": "chat.use_selected_rag_context",
    "discord_bots_json_edit": "bots",
    "discord_replace_nc_prompt_checkbox": "persona.replace_nc_system_prompt",
    "discord_persona_prompt_edit": "persona.system_prompt",
    "discord_room_speech_prompt_edit": "persona.room_speech_prompt",
    "discord_transcript_safety_prompt_edit": "persona.transcript_safety_prompt",
    "discord_voice_clone_wav_edit": "persona.voice_clone_wav",
    "discord_filter_enabled_checkbox": "response_filter.enabled",
    "discord_filter_mode_combo": "response_filter.mode",
    "discord_bot_names_edit": "response_filter.bot_names",
    "discord_answer_uncertain_checkbox": "response_filter.default_when_uncertain",
    "discord_room_router_enabled_checkbox": "room_router.enabled",
    "discord_room_router_human_to_bot_checkbox": "room_router.human_to_bot_routing",
    "discord_room_router_bot_to_bot_checkbox": "room_router.bot_to_bot_routing",
    "discord_room_router_exclude_speaker_checkbox": "room_router.exclude_speaker_from_targets",
    "discord_room_router_group_invite_checkbox": "room_router.allow_group_invitation_routing",
    "discord_room_router_open_room_checkbox": "room_router.allow_open_room_invitation_routing",
    "discord_room_router_text_routing_checkbox": "room_router.route_bot_replies_from_text",
    "discord_room_router_prebuffer_checkbox": "room_router.prepare_bot_replies_ahead",
    "discord_room_router_mode_combo": "room_router.mode",
    "discord_room_router_self_route_combo": "room_router.self_route_policy",
    "discord_room_router_uncertain_target_combo": "room_router.uncertain_fallback_target",
    "discord_room_router_competing_policy_combo": "room_router.competing_bot_reply_policy",
    "discord_room_router_floor_mode_combo": "room_router.reply_floor_mode",
    "discord_room_router_uncertain_checkbox": "room_router.default_when_uncertain",
    "discord_room_router_decision_timeout_spin": "room_router.decision_timeout_seconds",
    "discord_room_router_text_age_spin": "room_router.routed_text_max_age_seconds",
    "discord_room_router_decision_tokens_spin": "room_router.decision_max_tokens",
    "discord_room_router_route_window_spin": "room_router.route_window_ms",
    "discord_room_router_poll_ms_spin": "room_router.routed_text_poll_ms",
    "discord_room_router_rules_prompt_edit": "room_router.router_rules_prompt",
    "discord_play_test_tone_checkbox": "playback.play_test_tone_on_join",
    "discord_queue_replies_checkbox": "playback.queue_replies",
    "discord_interrupt_reply_checkbox": "playback.interrupt_reply_on_user_speech",
    "discord_interrupt_after_seconds_spin": "playback.interrupt_after_seconds",
    "discord_reply_immunity_seconds_spin": "playback.reply_immunity_seconds",
    "discord_discard_bot_speech_checkbox": "playback.discard_bot_speech_on_human_intervention",
    "discord_coordinate_bot_replies_checkbox": "playback.coordinate_bot_replies",
    "discord_reply_floor_stale_seconds_spin": "playback.reply_floor_stale_seconds",
    "discord_initial_buffer_chunks_spin": "playback.initial_buffer_chunks",
    "discord_silence_ms_spin": "capture.silence_ms",
    "discord_min_turn_seconds_spin": "capture.min_turn_seconds",
    "discord_max_turn_seconds_spin": "capture.max_turn_seconds",
    "discord_bot_max_turn_seconds_spin": "capture.bot_max_turn_seconds",
    "discord_bot_idle_finalize_ms_spin": "capture.bot_idle_finalize_ms",
    "discord_ignore_low_information_checkbox": "capture.ignore_low_information_transcripts",
    "discord_low_information_max_seconds_spin": "capture.low_information_max_seconds",
    "discord_low_information_transcripts_edit": "capture.low_information_transcripts",
    "discord_wav_sample_rate_combo": "capture.wav_sample_rate",
    "discord_wav_channels_combo": "capture.wav_channels",
    "discord_save_captures_checkbox": "capture.save_captures",
    "discord_shared_capture_owner_checkbox": "capture.shared_capture_owner_enabled",
    "discord_capture_owner_ttl_spin": "capture.owner_ttl_seconds",
    "discord_token_env_edit": "discord.token_env_var",
    "discord_local_token_edit": "discord.token",
    "discord_guild_id_edit": "discord.guild_id",
    "discord_voice_channel_id_edit": "discord.voice_channel_id",
    "discord_allowed_user_id_edit": "discord.allowed_user_id",
    "discord_answer_mode_combo": "discord.answer_mode",
    "discord_start_on_launch_checkbox": "start_on_nc_launch",
    "discord_bridge_mode_combo": "bridge_mode",
    "discord_context_entries_spin": "chat.context_entries",
    "discord_persist_room_context_checkbox": "chat.persist_room_context_between_restarts",
    "discord_tiny_mvp_url_edit": "tiny_mvp.url",
    "discord_tiny_mvp_start_with_gui_checkbox": "tiny_mvp.start_with_gui",
    "discord_tiny_mvp_bridge_script_edit": "tiny_mvp.bridge_script",
    "discord_tiny_mvp_poll_seconds_spin": "tiny_mvp.poll_seconds",
    "discord_tiny_mvp_capture_mic_checkbox": "tiny_mvp.capture_mic",
    "discord_tiny_mvp_mic_user_id_edit": "tiny_mvp.mic_user_id",
    "discord_tiny_mvp_mic_user_name_edit": "tiny_mvp.mic_user_name",
    "discord_tiny_mvp_mic_seconds_spin": "tiny_mvp.mic_seconds",
    "discord_tiny_mvp_mic_sample_rate_spin": "tiny_mvp.mic_sample_rate",
    "discord_tiny_mvp_mic_device_edit": "tiny_mvp.mic_device",
}

_BOT_FIELDS: dict[str, tuple[str, NativeControlKind, Any]] = {
    "discord_bot_enabled_checkbox": ("enabled", NativeControlKind.BOOLEAN, True),
    "discord_bot_id_edit": ("id", NativeControlKind.TEXT, ""),
    "discord_bot_display_name_edit": ("name", NativeControlKind.TEXT, ""),
    "discord_bot_token_env_edit": ("discord.token_env_var", NativeControlKind.TEXT, ""),
    "discord_bot_local_token_edit": ("discord.token", NativeControlKind.TEXT, ""),
    "discord_bot_guild_id_edit": ("discord.guild_id", NativeControlKind.TEXT, ""),
    "discord_bot_voice_channel_id_edit": ("discord.voice_channel_id", NativeControlKind.TEXT, ""),
    "discord_bot_runtime_port_spin": ("nc_runtime.port", NativeControlKind.INTEGER, 8768),
    "discord_bot_context_entries_spin": ("chat.context_entries", NativeControlKind.INTEGER, 20),
    "discord_bot_use_global_chat_model_checkbox": ("chat.use_global_model", NativeControlKind.BOOLEAN, True),
    "discord_bot_chat_provider_combo": ("chat.provider", NativeControlKind.CHOICE, "lmstudio"),
    "discord_bot_chat_model_combo": ("chat.model_name", NativeControlKind.CHOICE, ""),
    "discord_bot_call_names_edit": ("call_names", NativeControlKind.TEXT, ""),
    "discord_bot_voice_clone_wav_edit": ("persona.voice_clone_wav", NativeControlKind.TEXT, ""),
    "discord_bot_replace_nc_prompt_checkbox": ("persona.replace_nc_system_prompt", NativeControlKind.BOOLEAN, False),
    "discord_bot_persona_prompt_edit": ("persona.system_prompt", NativeControlKind.MULTILINE, ""),
}

_TARGET_SELECTION_IDS = {
    "discord_moderator_target_combo",
    "discord_moderator_instances_table",
    "discord_instances_table",
    "discord_live_bot_combo",
}

_ACTION_IDS = {
    str(spec["id"])
    for spec in NATIVE_CONTROL_SPECS
    if str(spec.get("kind")) == "action"
}

_ACTION_METADATA = {
    str(spec["id"]): dict(spec.get("metadata") or {})
    for spec in NATIVE_CONTROL_SPECS
    if str(spec.get("kind")) == "action"
}
_ACTION_METADATA.update(
    {
        "discord_copy_diagnostics_button": {"execution": "ui"},
        "discord_open_logs_button": {"execution": "ui"},
        "discord_install_node_deps_button": {"destructive": True},
        "discord_bot_remove_button": {"destructive": True},
        "discord_bot_remove_all_context_button": {"destructive": True},
        "discord_moderator_clear_button": {"destructive": True},
        "discord_moderator_stop_all_button": {"destructive": True},
        "discord_moderator_clear_all_queues_button": {"destructive": True},
        "discord_bridge_stop_button": {"destructive": True},
    }
)


def _nested(payload: Mapping[str, Any], dotted: str, default: Any = None) -> Any:
    current: Any = payload
    for part in str(dotted or "").split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def _set_nested(payload: dict[str, Any], dotted: str, value: Any) -> None:
    parts = [part for part in str(dotted or "").split(".") if part]
    current = payload
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    if parts:
        current[parts[-1]] = value


def _bot_id(value: Any) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")


def _format_validation(validation: Any) -> str:
    items = list(validation or [])
    if not items:
        return "No validation problems."
    return "\n".join(
        f"[{str(dict(item or {}).get('severity') or 'info').upper()}] "
        f"{str(dict(item or {}).get('message') or item)}"
        for item in items
    )


_ROUTER_LABELS = {
    "discord_room_router_enabled_checkbox": "Enable shared room router",
    "discord_room_router_human_to_bot_checkbox": "Route human speech to bots",
    "discord_room_router_bot_to_bot_checkbox": "Route bot speech to bots",
    "discord_room_router_exclude_speaker_checkbox": "Exclude speaker from targets",
    "discord_room_router_group_invite_checkbox": "Route group bot invitations",
    "discord_room_router_open_room_checkbox": "Route open-room invitations",
    "discord_room_router_text_routing_checkbox": "Route bot replies from text",
    "discord_room_router_prebuffer_checkbox": "Prepare routed bot replies ahead",
    "discord_room_router_mode_combo": "Router mode",
    "discord_room_router_self_route_combo": "Self-route policy",
    "discord_room_router_uncertain_target_combo": "Uncertain fallback target",
    "discord_room_router_competing_policy_combo": "Competing bot reply policy",
    "discord_room_router_floor_mode_combo": "Reply floor mode",
    "discord_room_router_uncertain_checkbox": "Answer when uncertain",
    "discord_room_router_decision_timeout_spin": "Router decision timeout (s)",
    "discord_room_router_text_age_spin": "Routed text max age (s)",
    "discord_room_router_decision_tokens_spin": "Router decision max tokens",
    "discord_room_router_route_window_spin": "Route grouping window (ms)",
    "discord_room_router_poll_ms_spin": "Routed text poll interval (ms)",
    "discord_room_router_rules_prompt_edit": "Router rules prompt",
}
_BASIC_ROUTER_CONTROLS = {
    "discord_room_router_enabled_checkbox", "discord_room_router_human_to_bot_checkbox",
    "discord_room_router_bot_to_bot_checkbox", "discord_room_router_mode_combo",
}
_ADVANCED_CAPTURE_CONTROLS = {
    "discord_shared_capture_owner_checkbox", "discord_capture_owner_ttl_spin",
}
_ADVANCED_PLAYBACK_CONTROLS = {
    "discord_discard_bot_speech_checkbox", "discord_coordinate_bot_replies_checkbox",
    "discord_reply_floor_stale_seconds_spin",
}
_DEPRECATED_FILTER_CONTROLS = {
    "discord_filter_enabled_checkbox", "discord_filter_mode_combo",
    "discord_bot_names_edit", "discord_answer_uncertain_checkbox",
}
_INCOMING_VOICE_CONTROLS = {
    "discord_answer_mode_combo": (
        "Accept incoming voice from",
        "Everyone ignores the ID list. Listed users uses the list; an empty list also accepts everyone. "
        "Save settings and restart the bridge to apply changes.",
    ),
    "discord_allowed_user_id_edit": (
        "Discord user IDs (optional)",
        "Used with Listed users. Separate IDs with commas, spaces or semicolons. "
        "Leave empty to accept everyone's incoming voice.",
    ),
}


def _build_controls() -> tuple[NativeControl, ...]:
    controls: list[NativeControl] = []
    for control in controls_from_specs(NATIVE_CONTROL_SPECS):
        metadata = dict(control.metadata or {})
        metadata.update(_ACTION_METADATA.get(control.id, {}))
        if control.kind is NativeControlKind.MULTILINE:
            metadata["scrollable"] = True
        if control.section == "Filter":
            metadata.update(groupKey="discord_shared_room_router", groupTitle="Shared Room Router", groupColumnSpan=2)
        if control.id in _INCOMING_VOICE_CONTROLS:
            label, description = _INCOMING_VOICE_CONTROLS[control.id]
            metadata.update(
                groupKey="discord_incoming_voice", groupTitle="Incoming Discord voice", groupColumnSpan=2,
                groupDescription="Filters incoming Discord audio before NC transcribes or responds to it. "
                                 "Discord controls who can join the channel. "
                                 "NC's internal bot-to-bot text handovers use room routing separately.",
            )
            control = replace(control, label=label, description=description)
            if control.id == "discord_answer_mode_combo":
                control = replace(control, choices=choices((("allowed_user_only", "Listed users"), ("anyone", "Everyone"))))
        controls.append(replace(control, label=_ROUTER_LABELS.get(control.id, control.label), metadata=metadata))
    return apply_card_layout(controls)


class DiscordVoiceBridgeNativeAdapter(NativeSurfaceAdapter):
    """Expose all 186 reviewed Discord Voice Bridge controls natively."""

    def __init__(self, application_facade: Any, schema: dict[str, Any], parent=None, *, persona_provider=None) -> None:
        super().__init__("discord_voice_bridge_tab", "nc.discord_voice_bridge", parent)
        self._application = application_facade
        self._schema = dict(schema or {})
        self._revision = 0
        self._last_result = ""
        self._last_state: dict[str, Any] = {}
        self._last_settings: dict[str, Any] = {}
        self._target_id = ""
        self._participant: dict[str, str] = {}
        self._moderator_selection_lost = False
        self._moderator_route_lines: dict[str, str] = {}
        self._announcement = ""
        self._live_message = ""
        self._local_room_message = ""
        self._local_room_participant = ""
        self._local_room_selection_admission = ''
        self._local_room_persona = ""
        self._local_room_announcement = ""
        self._local_room_history: dict[str, Any] = {}
        self._local_room_view_state: dict[str, Any] = {}
        self._room_ui_states: dict[str, dict[str, Any]] = {}
        self._room_ui_key = ""
        self._local_room_behavior_error = ""
        self._persona_provider = persona_provider or (lambda: QuickPersonaStore(_APP_ROOT).load().get("personas", {}))
        self._selected_bot_id = ""
        self._router_advanced_visible = False
        self._capture_advanced_visible = False
        self._playback_advanced_visible = False
        self._connection_advanced_visible = False
        self._surface = NativeSurface(
            id=self.surface_id,
            title="Discord Voice Bridge",
            addon_id=self.addon_id,
            sections=("Local room",) + tuple(section for section in sections_from_specs(NATIVE_CONTROL_SPECS) if section != "Bots"),
            description=(
                "Discord transport, room moderation, live bot control, routing, "
                "capture, playback, persona, and multi-bot settings."
            ),
            controls=_build_controls(),
        )

    def _invoke(self, capability: str, payload: dict[str, Any] | None = None) -> Any:
        result = self._application.addons.invoke_addon_capability(
            self.addon_id,
            capability,
            dict(payload or {}),
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            raise RuntimeError(
                str(getattr(failure, "message", "Discord Voice Bridge is unavailable."))
            )
        return result.value

    def _bots(self) -> list[dict[str, Any]]:
        return [
            copy.deepcopy(item)
            for item in list(self._last_settings.get("bots") or [])
            if isinstance(item, dict)
        ]

    def _selected_bot_index(self, bots: list[dict[str, Any]] | None = None) -> int:
        values = self._bots() if bots is None else bots
        for index, bot in enumerate(values):
            if str(bot.get("id") or "") == self._selected_bot_id:
                return index
        return 0 if values else -1

    def _save_bots(self, bots: list[dict[str, Any]], *, selected_id: str = "") -> None:
        self._invoke("runtime.discord.native_update", {"key": "bots", "value": bots})
        if selected_id:
            self._selected_bot_id = selected_id

    @staticmethod
    def _next_bot_port(bots: list[dict[str, Any]]) -> int:
        used = {
            int(_nested(bot, "nc_runtime.port", 0) or 0)
            for bot in bots
            if str(_nested(bot, "nc_runtime.port", "")).strip()
        }
        port = 8768
        while port in used and port < 65535:
            port += 1
        return port

    @staticmethod
    def _unique_bot_id(bots: list[dict[str, Any]], base: str) -> str:
        stem = _bot_id(base) or "bot"
        existing = {_bot_id(bot.get("id")) for bot in bots}
        candidate = stem
        suffix = 2
        while candidate in existing:
            candidate = f"{stem}_{suffix}"
            suffix += 1
        return candidate

    def _instance_options(self, instances: list[dict[str, Any]]) -> tuple[tuple[str, str], ...]:
        result = tuple(
            (
                str(item.get("id") or ""),
                str(item.get("name") or item.get("id") or "Unnamed bot"),
            )
            for item in instances
            if str(item.get("id") or "").strip()
        )
        return result or (("", "No configured bot"),)

    @staticmethod
    def _participant_options(instances: list[dict[str, Any]]) -> tuple[tuple[str, str], ...]:
        found: dict[str, tuple[str, str]] = {}
        for instance in instances:
            instance_id = str(instance.get("id") or "").strip()
            instance_name = str(instance.get("name") or instance_id or "Bot")
            if instance_id:
                value = json.dumps({"id": instance_id, "name": instance_name, "kind": "bot"})
                found[value] = (value, f"{instance_name} · bot")
            node = dict(instance.get("node_status") or {})
            for raw in list(node.get("participants") or []):
                participant = dict(raw or {})
                item_id = str(participant.get("id") or "").strip()
                name = str(participant.get("name") or item_id or "Participant")
                kind = "bot" if bool(participant.get("is_bot")) else "human"
                value = json.dumps({"id": item_id, "name": name, "kind": kind})
                found[value] = (value, f"{name} · {kind}")
        return tuple(found.values()) or (("", "No room participants"),)

    @staticmethod
    def _moderator_state(instances: list[dict[str, Any]]) -> dict[str, Any]:
        best: dict[str, Any] = {}
        updated = -1
        for instance in instances:
            if not instance.get("runtime_connected"):
                continue
            node = dict(instance.get("node_status") or {})
            state = dict(node.get("moderator_state") or node.get("moderator") or {})
            stamp = int(state.get("updated_at_ms") or 0) if state else -1
            if state and stamp >= updated:
                best, updated = state, stamp
        return best

    def snapshot(self) -> NativeSurface:
        state = dict(self._invoke("runtime.discord.native_snapshot") or {})
        self._last_state = copy.deepcopy(state)
        settings = dict(state.get("settings") or {})
        self._last_settings = copy.deepcopy(settings)
        instances = [dict(item or {}) for item in list(state.get("instances") or [])]
        validation = state.get("validation") or []
        instance_options = self._instance_options(instances)
        available_ids = {item[0] for item in instance_options}
        if self._target_id not in available_ids:
            if self._target_id:
                self._moderator_selection_lost = True
            self._target_id = next((str(item.get("id")) for item in instances if item.get("runtime_connected")), instance_options[0][0])
        moderator = self._moderator_state(instances)
        participants = room_participants(instances, moderator)
        selected_participant = next((item for item in participants
                                     if item["id"] == self._participant.get("id")
                                     and item["kind"] == self._participant.get("kind")), {})
        if self._participant and not selected_participant:
            self._participant = {}
            self._moderator_selection_lost = True
        elif selected_participant:
            self._participant = {key: selected_participant[key] for key in ("id", "name", "kind")}
        presentation = moderator_view(instances, moderator, participants, self._target_id,
                                      selected_participant, self._moderator_selection_lost, settings)
        entries = moderator.get("route_flow") or []
        if not entries:
            self._moderator_route_lines.clear()
        for entry in entries:
            if isinstance(entry, dict):
                self._moderator_route_lines.setdefault(json.dumps(entry, sort_keys=True), route_line(entry))
        selected_instance = next(
            (item for item in instances if str(item.get("id") or "") == self._target_id),
            {},
        )
        bots = self._bots()
        bot_index = self._selected_bot_index(bots)
        selected_bot = bots[bot_index] if bot_index >= 0 else {}
        if selected_bot:
            self._selected_bot_id = str(selected_bot.get("id") or "")
        bot_options = tuple(
            (
                str(bot.get("id") or f"bot_{index + 1}"),
                str(bot.get("name") or bot.get("id") or f"Bot {index + 1}"),
            )
            for index, bot in enumerate(bots)
        ) or (("", "No configured bots"),)
        participant_options = tuple((participant_value(row), f"{row['name']} · {row['kind']}") for row in participants)
        selected_value = (
            json.dumps(self._participant) if self._participant else ""
        )
        specs = {str(spec["id"]): spec for spec in NATIVE_CONTROL_SPECS}
        values = {key: copy.deepcopy(spec.get("default")) for key, spec in specs.items()}
        for control_id, setting_key in _CONTROL_SETTINGS.items():
            value = _nested(settings, setting_key, values.get(control_id))
            if control_id == "discord_local_token_edit":
                value = ""
            elif control_id == "discord_low_information_transcripts_edit":
                value = ", ".join(str(item) for item in list(value or []))
            elif control_id == "discord_bots_json_edit":
                value = json.dumps(value or [], ensure_ascii=False, indent=2)
            values[control_id] = value
        for control_id, (path, _kind, default) in _BOT_FIELDS.items():
            values[control_id] = (
                ""
                if control_id == "discord_bot_local_token_edit"
                else _nested(selected_bot, path, default)
            )
        running = sum(1 for item in instances if bool(item.get("runtime_connected")))
        logs = [str(item.get("log_path") or "") for item in instances if item.get("log_path")]
        node = dict(selected_instance.get("node_status") or {})
        render_total = max(0, int(node.get("render_total_chunks") or 0))
        playback_total = max(0, int(node.get("playback_total_chunks") or 0))
        values.update(
            {
                "discord_voice_bridge_intro_label": "Configure Discord voice transport, room routing, moderation, and isolated bot personas.",
                "discord_bridge_status_label": f"{running} of {len(instances)} configured bridge instance(s) running.",
                "discord_moderator_target_combo": self._target_id,
                "discord_moderator_state_label": (f"Moderator bot: {moderator.get('enforcer_bot_id')}" if moderator.get("enforcer_bot_id") else "No moderator bot assigned."),
                "discord_moderator_human_floor_label": str(moderator.get("floor_speaker_name") or "No human speaker lock"),
                "discord_moderator_selected_action_label": presentation["selectedAction"],
                "discord_moderator_warning_label": presentation["warning"],
                "discord_moderator_next_action_label": presentation["nextAction"],
                "discord_moderator_route_flow_view": "\n".join(self._moderator_route_lines.values()) or "No shared route flow yet.",
                "discord_dead_air_status_label": presentation["recoveryStatus"],
                "discord_dead_air_status_label_label": "Dead-air recovery",
                "discord_moderator_shortcuts_hint_label": "Select a participant, then route, allow, mute, or call on that participant.",
                "discord_moderator_instances_table": self._target_id,
                "discord_moderator_participants_table": selected_value,
                "discord_moderator_allow_interrupt_current_checkbox": bool(moderator.get("allow_current_interruption", False)),
                "discord_moderator_enforce_mute_checkbox": bool(moderator.get("enforce_discord_mute", False)),
                "discord_moderator_announcement_edit": self._announcement,
                "discord_moderator_note_label": "Moderator commands are sent only to active local bridge instances.",
                "discord_instances_table": self._target_id,
                "discord_logs_preview": "\n".join(logs) if logs else "No bridge logs found yet.",
                "discord_render_ready_bar": int(100 * int(node.get("render_ready_chunks") or 0) / render_total) if render_total else 0,
                "discord_preview_playback_bar": int(100 * int(node.get("playback_completed_chunks") or 0) / playback_total) if playback_total else 0,
                "discord_live_bot_combo": self._target_id,
                "discord_live_bot_state_label": json.dumps(node or {"state": "stopped"}, ensure_ascii=False),
                "discord_live_message_edit": self._live_message,
                "discord_live_restart_hint_label": "Token, port, guild, and channel changes require a restart.",
                "discord_validation_summary_label": _format_validation(validation),
                "discord_runtime_http_endpoint_edit": str(_nested(settings, "nc_runtime.http_endpoint", "")),
                "discord_runtime_ws_endpoint_edit": str(_nested(settings, "nc_runtime.endpoint", "")),
                "rag_status_label": "Selected NC RAG Context",
                "discord_rag_status_label": "Enabled" if bool(_nested(settings, "chat.use_selected_rag_context", True)) else "Disabled",
                "bots_hint_label": "Each bot has isolated Discord, runtime, model, voice, and persona settings.",
                "discord_bot_list": self._selected_bot_id,
                "discord_transcript_safety_prompt_label": "Transcript safety guidance is applied before the room reply is generated.",
            }
        )
        option_overrides = {
            "discord_moderator_target_combo": instance_options,
            "discord_moderator_instances_table": instance_options,
            "discord_instances_table": instance_options,
            "discord_live_bot_combo": instance_options,
            "discord_dead_air_fallback_target_combo": (("", "Automatic"),) + instance_options,
            "discord_moderator_participants_table": participant_options,
            "discord_bot_list": bot_options,
        }
        voice_files = local_voice_reference_files(_APP_ROOT)
        for control_id in _VOICE_CONTROLS:
            option_overrides[control_id] = _voice_choices(voice_files, values.get(control_id))
        rendered: list[NativeControl] = []
        for control in self._surface.controls:
            dynamic = option_overrides.get(control.id)
            metadata = dict(control.metadata)
            if control.id in {'discord_token_env_edit', 'discord_local_token_edit'}:
                metadata['presentationHidden'] = not self._connection_advanced_visible
                metadata.update(groupKey='discord_legacy_connection', groupTitle='Legacy single-account credentials',
                                groupDescription='Multi-account rooms use Bot accounts. These shared credentials remain available for existing standalone setups.')
            elif control.section == "Bots" or control.id in _DEPRECATED_FILTER_CONTROLS:
                metadata["presentationHidden"] = True
            elif control.id in _ROUTER_LABELS:
                metadata["presentationHidden"] = control.id not in _BASIC_ROUTER_CONTROLS and not self._router_advanced_visible
            elif control.id == "discord_router_advanced_toggle":
                control = replace(control, label=("Hide" if self._router_advanced_visible else "Show") + " Advanced Router Policy")
                values[control.id] = self._router_advanced_visible
            elif control.id in _ADVANCED_CAPTURE_CONTROLS:
                metadata["presentationHidden"] = not self._capture_advanced_visible
            elif control.id == "discord_capture_advanced_toggle":
                control = replace(control, label=("Hide" if self._capture_advanced_visible else "Show") + " Advanced Capture Settings")
                values[control.id] = self._capture_advanced_visible
            elif control.id in _ADVANCED_PLAYBACK_CONTROLS:
                metadata["presentationHidden"] = not self._playback_advanced_visible
            elif control.id == "discord_playback_advanced_toggle":
                control = replace(control, label=("Hide" if self._playback_advanced_visible else "Show") + " Advanced Speaker Coordination")
                values[control.id] = self._playback_advanced_visible
            if control.id == "discord_moderator_state_label":
                metadata.update({key: presentation[key] for key in ("summaryRows", "quickChoices")})
                metadata["hasWarning"] = presentation["warning"] != "No moderator warning."
            elif control.id == "discord_moderator_instances_table":
                metadata["rows"] = presentation["instances"]
            elif control.id == "discord_moderator_participants_table":
                metadata["rows"] = presentation["participants"]
            rendered.append(
                replace(
                    control,
                    kind=NativeControlKind.CHOICE if control.id in _VOICE_CONTROLS else control.kind,
                    value=values.get(control.id, control.default_value),
                    choices=choices(dynamic) if dynamic else control.choices,
                    enabled=presentation["enabled"].get(control.id, control.enabled),
                    metadata=metadata,
                )
            )
        room = copy.deepcopy(state.get("local_room") or {})
        room_key = str(room.get("room_key") or room.get("mode") or "local")
        if room_key != self._room_ui_key:
            if self._room_ui_key:
                self._room_ui_states[self._room_ui_key] = dict(message=self._local_room_message,
                    announcement=self._local_room_announcement, participant=self._local_room_participant,
                    view=copy.deepcopy(self._local_room_view_state))
            saved = self._room_ui_states.get(room_key, {}) if self._room_ui_key else dict(
                message=self._local_room_message, announcement=self._local_room_announcement,
                participant=self._local_room_participant, view=self._local_room_view_state)
            self._local_room_message = str(saved.get("message") or "")
            self._local_room_announcement = str(saved.get("announcement") or "")
            self._local_room_participant = str(saved.get("participant") or "")
            self._local_room_view_state = copy.deepcopy(saved.get("view") or {})
            self._room_ui_key = room_key
        conversation_id = str((room.get('conversation') or {}).get('id') or '')
        if self._local_room_view_state.get('conversation_id') != conversation_id:
            self._local_room_view_state = {'conversation_id':conversation_id,
                'open':bool(self._local_room_view_state.get('open', False)),
                'enlarged':bool(self._local_room_view_state.get('enlarged', False))}
        room['view_state'] = copy.deepcopy(self._local_room_view_state)
        room['behavior_save_error'] = self._local_room_behavior_error
        selected = next((p for p in room.get('participants', [])
                         if str(p.get('participant_id') or p.get('id')) == self._local_room_participant), {})
        admission = str(selected.get('admission_id') or '')
        if self._local_room_participant and (not selected or
                (self._local_room_selection_admission and admission != self._local_room_selection_admission)):
            self._local_room_participant = ''
            self._local_room_history = {}
        self._local_room_selection_admission = admission if self._local_room_participant else ''
        for participant in room.get("participants", []):
            participant["avatar_url"] = self._room_asset_url(participant.get("avatar_path"))
        self._overlay_local_room_history(room)
        rendered.extend(local_room_controls(room, self._local_room_message,
            self._local_room_participant, self._persona_library(), self._local_room_persona, self._local_room_announcement))
        persona_names = {str(persona['id']): str(persona['name']) for persona in self._persona_records()}
        account_rows = []
        for account in state.get('discord_accounts') or []:
            if not isinstance(account, dict):
                continue
            persona = str(account.get('assigned_persona') or '')
            account_rows.append({
                'id': str(account.get('id') or ''), 'label': str(account.get('label') or ''),
                'token_configured': bool(account.get('token_configured')),
                'assigned_persona': persona_names.get(persona, persona),
                'avatar_url': safe_avatar_url(account.get('avatar_url')),
                'discord_name': str(account.get('discord_name') or ''),
                'bot_nickname': str(account.get('bot_nickname') or ''),
                'nickname_error': str(account.get('nickname_error') or ''),
                'verification_state': str(account.get('verification_state') or 'unchecked'),
                'verification_message': str(account.get('verification_message') or 'Not checked yet.'),
                'status': str(account.get('status') or 'Disconnected'),
                'can_edit': bool(account.get('can_edit')), 'can_remove': bool(account.get('can_remove')),
                'blocked_reason': str(account.get('blocked_reason') or ''),
            })
        rendered.append(NativeControl(
            id='discord_accounts_view', label='Bot accounts', kind=NativeControlKind.LIST, section='Discord',
            description='Reusable Discord accounts for your Personas. Add an account with its bot token.',
            metadata={'rows': account_rows},
        ))
        rendered.append(NativeControl(
            id='discord_connection_advanced_toggle', label='Advanced connection settings',
            kind=NativeControlKind.BOOLEAN, section='Discord', value=self._connection_advanced_visible,
            description='Show legacy shared credentials for standalone bridge setups.',
        ))
        for action in ('add', 'update', 'remove', 'check_all'):
            rendered.append(NativeControl(
                id='discord_account_' + action, label=action.capitalize() + ' bot account',
                kind=NativeControlKind.ACTION, section='Discord', metadata={'presentationHidden': True},
            ))
        return replace(self._surface, controls=tuple(rendered), revision=self._revision)

    def _persona_records(self):
        records = self._persona_provider()
        return [dict(p) for p in (records.values() if isinstance(records, dict) else records)
                if isinstance(p, dict) and p.get("id") and p.get("name")]

    def _persona_library(self):
        return [dict(id=p["id"], name=p["name"], avatar_url=self._room_asset_url(p.get("avatar_path")),
                     voice_label=Path(str(p.get("voice_path") or "")).name if p.get("use_cloned_voice", True)
                     and p.get("voice_path") else "Default voice") for p in self._persona_records()]

    @staticmethod
    def _room_asset_url(path):
        source = Path(str(path or ""))
        if not source.is_absolute():
            source = _APP_ROOT / source
        return QtCore.QUrl.fromLocalFile(str(source)).toString() if source.is_file() else ""

    def _overlay_local_room_history(self, room: dict[str, Any]) -> None:
        # The native history result is presentation state for the current room only.
        history = self._local_room_history
        room_key = str(room.get("room_key") or room.get("mode") or "local")
        history_key = str(history.get("room_key") or "")
        if not history or (history_key and history_key != room_key) or (room.get("mode") == "discord" and not history_key):
            return
        conversation = room.get("conversation")
        conversation_id = str((conversation or {}).get("id") or "") if isinstance(conversation, dict) else ""
        if conversation_id and str(history.get("conversation_id") or "") == conversation_id:
            room["history_view"] = copy.deepcopy(history)

    def _set_target(self, value: Any) -> None:
        self._target_id = str(value or "").strip()
        self._participant = {}
        self._moderator_selection_lost = False

    def _send_instance_command(self, command: str, command_payload: dict[str, Any] | None = None) -> Any:
        owner = self._target_id
        if command.startswith("moderator_"):
            running = [str(item.get("id")) for item in self._last_state.get("instances", [])
                       if item.get("runtime_connected")]
            if command == "moderator_set_mute_enforcement":
                owner = str(self._moderator_state(self._last_state.get("instances", [])).get("enforcer_bot_id") or "")
                if owner not in running:
                    raise ValueError("The appointed Discord Moderator bot is not running.")
            elif owner not in running:
                owner = next(iter(running), "")
        if not owner:
            raise ValueError("Choose a Discord bot instance first.")
        return self._invoke(
            "runtime.discord.native_action",
            {
                "action": "send_instance_command",
                "payload": {
                    "instance_id": owner,
                    "command": command,
                    "command_payload": dict(command_payload or {}),
                },
            },
        )

    def set_value(self, control_id: str, value: Any) -> None:
        key = str(control_id or "").strip()
        if key in {"discord_room_mode", "discord_room_bot_binding", "discord_room_anonymous"}:
            raw = value.toVariant() if hasattr(value, "toVariant") else value
            if key == "discord_room_anonymous":
                self._configure_room(key, {"anonymous": raw})
            else:
                self._configure_room(key, {"mode": str(raw)} if key == "discord_room_mode" else raw)
            return
        if key == 'discord_local_room_view_state':
            # Scroll/presentation state stays in this adapter across QML reloads.
            # Never emit changed: that would poll the room while the user scrolls.
            raw = value.toVariant() if hasattr(value, 'toVariant') else value
            if isinstance(raw, dict):
                self._local_room_view_state = copy.deepcopy(raw)
            return
        if key == "discord_local_room_message":
            self._local_room_message = str(value or "")
            # A draft edit must not poll the room on the GUI thread. The view
            # enables Send locally; the next normal snapshot includes this draft.
            return
        elif key == "discord_local_room_participant":
            self._local_room_participant = str(value or "")
            selected = next((p for p in (self._last_state.get('local_room') or {}).get('participants', [])
                             if str(p.get('participant_id') or p.get('id')) == self._local_room_participant), {})
            self._local_room_selection_admission = str(selected.get('admission_id') or '')
        elif key == "discord_local_room_persona":
            self._local_room_persona = str(value or "")
        elif key == "discord_local_room_announcement":
            self._local_room_announcement = str(value or "")
            return
        elif key == "discord_router_advanced_toggle":
            # This is UI disclosure state, not a persisted addon/runtime setting.
            self._router_advanced_visible = bool(value)
        elif key == "discord_capture_advanced_toggle":
            self._capture_advanced_visible = bool(value)
        elif key == "discord_playback_advanced_toggle":
            self._playback_advanced_visible = bool(value)
        elif key == "discord_connection_advanced_toggle":
            self._connection_advanced_visible = bool(value)
        elif key in _TARGET_SELECTION_IDS:
            self._set_target(value)
        elif key == "discord_moderator_participants_table":
            raw = str(value or "").strip()
            self._participant = dict(json.loads(raw)) if raw else {}
            self._moderator_selection_lost = False
            if self._participant.get("kind") == "bot":
                self._target_id = str(self._participant.get("id") or "")
        elif key == "discord_moderator_announcement_edit":
            self._announcement = str(value or "")
            return
        elif key == "discord_live_message_edit":
            self._live_message = str(value or "")
        elif key == "discord_moderator_allow_interrupt_current_checkbox":
            self._require_moderator_control(key)
            enabled = bool(value)
            self._send_instance_command(
                "moderator_set_current_interruption",
                {"allow_current_interruption": enabled, "reason": "native moderator control"},
            )
        elif key == "discord_moderator_enforce_mute_checkbox":
            self._require_moderator_control(key)
            enabled = bool(value)
            self._send_instance_command(
                "moderator_set_mute_enforcement",
                {"enabled": enabled, "reason": "native moderator control"},
            )
        elif key == "discord_bot_list":
            self._selected_bot_id = str(value or "").strip()
        elif key in _BOT_FIELDS:
            bots = self._bots()
            index = self._selected_bot_index(bots)
            if index < 0:
                raise ValueError("Add or select a Discord bot before editing bot settings.")
            path, kind, _default = _BOT_FIELDS[key]
            if kind is NativeControlKind.BOOLEAN:
                normalized: Any = bool(value)
            elif kind is NativeControlKind.INTEGER:
                normalized = int(value)
            else:
                normalized = str(value or "").strip()
            if key == "discord_bot_local_token_edit":
                if normalized:
                    self._invoke(
                        "runtime.discord.native_action",
                        {
                            "action": "set_bot_token",
                            "payload": {
                                "bot_id": str(bots[index].get("id") or ""),
                                "token": normalized,
                            },
                        },
                    )
            else:
                if key == "discord_bot_id_edit":
                    normalized = _bot_id(normalized)
                    if not normalized:
                        raise ValueError("Bot ID is required.")
                    if any(
                        other != index and _bot_id(bot.get("id")) == normalized
                        for other, bot in enumerate(bots)
                    ):
                        raise ValueError(f"Bot ID {normalized!r} already exists.")
                _set_nested(bots[index], path, normalized)
                self._save_bots(bots, selected_id=str(bots[index].get("id") or ""))
        elif key in _CONTROL_SETTINGS:
            setting_key = _CONTROL_SETTINGS[key]
            normalized = value
            if key == "discord_tiny_mvp_mic_user_id_edit":
                normalized = str(value or "").strip().lower()
            elif key == "discord_low_information_transcripts_edit":
                normalized = [
                    item.strip()
                    for item in re.split(r"[,\n]+", str(value or ""))
                    if item.strip()
                ]
            elif key == "discord_bots_json_edit":
                normalized = json.loads(str(value or "[]"))
                if not isinstance(normalized, list):
                    raise ValueError("Bot instances must be a JSON array.")
            self._invoke(
                "runtime.discord.native_update",
                {"key": setting_key, "value": normalized},
            )
        else:
            raise KeyError(f"Unknown Discord Voice Bridge control {control_id!r}.")
        self._revision += 1
        self.changed.emit()

    def _moderator_command(self, command: str) -> tuple[str, dict[str, Any]]:
        participant = dict(self._participant)
        if str(participant.get("kind") or "").lower() == "human":
            command = {
                "moderator_route_next": "moderator_route_next_human",
                "moderator_give_floor": "moderator_give_human_floor",
                "moderator_mute": "moderator_mute_human",
                "moderator_unmute": "moderator_unmute_human",
            }.get(command, command)
            return command, {
                "speaker_user_id": str(participant.get("id") or ""),
                "speaker_name": str(participant.get("name") or ""),
                "reason": "native human moderator control",
            }
        return command, {
            "target_bot_id": str(participant.get("id") or self._target_id),
            "reason": "native moderator control",
        }

    def _require_moderator_control(self, control_id: str) -> None:
        # Recheck the current room at command time, not only the last UI poll.
        control = next((item for item in self.snapshot().controls if item.id == control_id), None)
        if control is None or not control.enabled:
            raise ValueError("This moderator action is not available for the current room or selection.")

    def _bot_action(self, control: str) -> bool:
        if control not in {
            "discord_bot_add_button",
            "discord_bot_duplicate_button",
            "discord_bot_remove_button",
            "discord_bot_remove_all_context_button",
            "discord_bot_chat_model_refresh_button",
            "discord_bot_load_json_button",
            "discord_format_bots_button",
        }:
            return False
        bots = self._bots()
        index = self._selected_bot_index(bots)
        if control == "discord_bot_add_button":
            bot_id = self._unique_bot_id(bots, f"bot_{len(bots) + 1}")
            bots.append(
                {
                    "id": bot_id,
                    "name": f"Bot {len(bots) + 1}",
                    "enabled": True,
                    "discord": {"token_env_var": f"DISCORD_TOKEN_{bot_id.upper()}"},
                    "nc_runtime": {"port": self._next_bot_port(bots)},
                    "chat": {"context_entries": 20, "use_global_model": True},
                    "persona": {},
                }
            )
            self._save_bots(bots, selected_id=bot_id)
            self._last_result = f"Added Discord bot {bot_id}."
        elif control == "discord_bot_duplicate_button":
            if index < 0:
                raise ValueError("Select a Discord bot to duplicate.")
            source = copy.deepcopy(bots[index])
            source_id = str(source.get("id") or "bot")
            bot_id = self._unique_bot_id(bots, f"{source_id}_copy")
            source["id"] = bot_id
            source["name"] = f"{str(source.get('name') or source_id)} Copy"
            source.setdefault("discord", {}).pop("token", None)
            source.setdefault("discord", {})["token_env_var"] = f"DISCORD_TOKEN_{bot_id.upper()}"
            source.setdefault("nc_runtime", {})["port"] = self._next_bot_port(bots)
            bots.append(source)
            self._save_bots(bots, selected_id=bot_id)
            self._last_result = f"Duplicated Discord bot as {bot_id}."
        elif control == "discord_bot_remove_button":
            if index < 0:
                raise ValueError("Select a Discord bot to remove.")
            removed = str(bots[index].get("id") or "bot")
            del bots[index]
            selected = str(bots[min(index, len(bots) - 1)].get("id") or "") if bots else ""
            self._save_bots(bots, selected_id=selected)
            self._selected_bot_id = selected
            self._last_result = f"Removed Discord bot {removed}."
        elif control == "discord_bot_remove_all_context_button":
            self._invoke("runtime.discord.native_action", {"action": "erase_all_contexts", "payload": {}})
            self._last_result = "Removed all persisted Discord bot contexts."
        elif control == "discord_bot_chat_model_refresh_button":
            self._last_result = "Model choices refresh from the active Runtime model catalog."
        elif control == "discord_format_bots_button":
            self._last_result = "Formatted the saved structured bot configuration."
        else:
            self._last_result = "Loaded the structured bot editor from the saved JSON configuration."
        return True

    def _trigger_local_room(self, control_id, captured=None):
        captured = dict(captured or {})
        self.snapshot()
        submitted_draft = str(captured.get("text", self._local_room_message))
        participant_id = str(captured.get("participant_id", self._local_room_participant))
        persona_id = str(captured.get("persona_id", self._local_room_persona))
        announcement = str(captured.get("announcement", self._local_room_announcement))
        topic = str(captured.get("topic") or "")
        user_name = str(captured.get('name') or '')
        target = next((p for p in (self._last_state.get('local_room') or {}).get('participants', [])
                       if str(p.get('participant_id') or p.get('id')) == participant_id), {})
        if captured.get('admission_id') and captured['admission_id'] != target.get('admission_id'):
            raise ValueError('This participant admission changed. Select the card again.')
        action, payload = local_room_action(
            str(control_id), dict(self._last_state.get("local_room") or {}), submitted_draft,
            participant_id, self._persona_library(), persona_id, announcement, topic, user_name, captured.get("behavior"), captured.get('sender_id'))
        if action == "local_room_add_persona":
            record = next((p for p in self._persona_records() if p["id"] == persona_id), None)
            if record is None:
                raise ValueError("This Persona is no longer in your library. Refresh and select it again.")
            payload = {"persona_id": record['id']}
        if action in {'local_room_add_persona', 'local_room_replace_persona'} and captured.get('bot_id'):
            room = self._last_state.get('local_room') or {}
            bot_id = str(captured['bot_id'])
            if room.get('mode') == 'discord' and not any(a.get('bot_id') == bot_id and a.get('available') for a in room.get('available_accounts', [])):
                raise ValueError('This prepared account is unavailable. Choose a free account.')
            payload['bot_id'] = bot_id
        if action == "local_room_set_topic":
            payload["topic"] = str(payload.get("topic") or "").strip()
        previous_announcement = self._local_room_announcement
        if action == "local_room_save_behavior":
            self._local_room_behavior_error = ""
        try:
            result = self._invoke("runtime.discord.native_action", {"action": action, "payload": payload})
        except Exception as error:
            if action == "local_room_save_behavior":
                self._local_room_behavior_error = str(error)
                self.changed.emit()
            raise
        if action == "local_room_history":
            self._local_room_history = copy.deepcopy(result) if isinstance(result, dict) else {}
            if self._local_room_history:
                self._local_room_history['participant_id'] = participant_id
            if self._local_room_history and (self._last_state.get("local_room") or {}).get("mode") == "discord":
                self._local_room_history["room_key"] = str((self._last_state.get("local_room") or {}).get("room_key") or "")
                self._local_room_history["conversation_id"] = str(((self._last_state.get("local_room") or {}).get("conversation") or {}).get("id") or "")
        elif action == "local_room_new_conversation":
            # New conversation clears every Local room history, including removed members.
            self._local_room_history = {}
        elif action == "local_room_control" and str(payload.get("command") or "") in {"guide", "announce"}:
            # Keep the submitted guidance after a click that raced the debounce, but
            # never replace a newer draft typed while the action was in flight.
            if self._local_room_announcement == previous_announcement:
                self._local_room_announcement = str(payload.get("text") or "")
        if action == "local_room_send" and self._local_room_message == submitted_draft:
            self._local_room_message = ""
        self._revision += 1
        self.changed.emit()

    def _configure_room(self, control_id, payload):
        # Refresh before mutation so each control uses current room capabilities.
        control = next((item for item in self.snapshot().controls if item.id == control_id), None)
        if control is None or not control.enabled:
            if control_id == "discord_room_anonymous":
                raise ValueError("Anonymous cannot be changed while room settings are unavailable.")
            raise ValueError("Stop the room before changing its transport or prepared bots.")
        raw = payload.toVariant() if hasattr(payload, "toVariant") else payload
        if not isinstance(raw, dict):
            raise ValueError("Provide a room configuration.")
        if control_id == "discord_room_anonymous":
            if not isinstance(raw.get("anonymous"), bool):
                raise ValueError("Anonymous must be true or false.")
            captured = {"anonymous": raw["anonymous"]}
        elif control_id == "discord_room_mode":
            mode = str(raw.get("mode") or "")
            if mode not in {"local", "discord"}:
                raise ValueError("Choose Local or Discord.")
            captured = {"mode": mode}
        else:
            captured = {"participant_id": str(raw.get("participant_id") or ""),
                        "bot_id": str(raw.get("bot_id") or "")}
            if not captured["participant_id"]:
                raise ValueError("Choose a persona participant before assigning a prepared bot.")
            room = self._last_state.get('local_room') or {}
            member = next((p for p in room.get('participants', [])
                if str(p.get('participant_id') or p.get('id')) == captured['participant_id']), {})
            if raw.get('admission_id') and raw['admission_id'] != member.get('admission_id'):
                raise ValueError('This participant changed. Select the card again.')
            if room.get('phase') == 'running':
                if not member.get('can_replace') or member.get('role') in {'human', 'moderator'}:
                    raise ValueError('This participant cannot change accounts now; the moderator retains its account.')
                if captured['bot_id'] and captured['bot_id'] == member.get('bot_id'):
                    return
                if not any(a.get('bot_id') == captured['bot_id'] and a.get('available') for a in room.get('available_accounts', [])):
                    raise ValueError('Choose a free prepared account.')
        self._invoke("runtime.discord.native_action", {"action": "room_configure", "payload": captured})
        if control_id != "discord_room_anonymous":
            self._local_room_history = {}
        self._revision += 1
        self.changed.emit()

    def trigger_with_payload(self, control_id: str, payload) -> None:
        if str(control_id) in {'discord_account_add', 'discord_account_update', 'discord_account_remove', 'discord_account_check_all'}:
            action = str(control_id).removeprefix('discord_')
            submitted = dict(payload or {})
            request = {}
            if action in {'account_update', 'account_remove'}:
                request['account_id'] = str(submitted.get('account_id') or '').strip()
            if action in {'account_add', 'account_update'}:
                request['label'] = str(submitted.get('label') or '').strip()
                if action == 'account_add' or str(submitted.get('token') or '').strip():
                    request['token'] = str(submitted.get('token') or '').strip()
            result = self._invoke('runtime.discord.native_action', {'action': action, 'payload': request})
            if not isinstance(result, Mapping) or result.get('ok') is not True:
                message = str(result.get('error') or '') if isinstance(result, Mapping) else ''
                raise RuntimeError(message or 'Discord bot account settings were not saved. Refresh and try again.')
            self._last_result = ('Discord bot account checks finished. See each account for its result.'
                                 if action == 'account_check_all' else 'Discord bot account settings updated.')
            self._revision += 1
            self.changed.emit()
        elif str(control_id) in {"discord_room_mode", "discord_room_bot_binding", "discord_room_anonymous"}:
            self._configure_room(str(control_id), payload)
        elif str(control_id).startswith("discord_local_room_"):
            self._trigger_local_room(str(control_id), payload)
        else:
            super().trigger_with_payload(control_id, payload)

    def trigger(self, control_id: str) -> None:
        if str(control_id).startswith("discord_local_room_"):
            self._trigger_local_room(str(control_id))
            return
        if str(control_id).startswith("discord_moderator_"):
            self._require_moderator_control(str(control_id))
        control = str(control_id or "").strip()
        if control not in _ACTION_IDS:
            raise KeyError(f"Unknown Discord Voice Bridge action {control_id!r}.")
        if self._bot_action(control):
            self._revision += 1
            self.changed.emit()
            return
        if control == "discord_copy_diagnostics_button":
            clipboard = QtGui.QGuiApplication.clipboard()
            if clipboard is None:
                raise RuntimeError("The system clipboard is unavailable.")
            clipboard.setText(json.dumps(self._last_state, ensure_ascii=False, indent=2))
            self._last_result = "Copied redacted Discord Voice Bridge diagnostics."
        elif control == "discord_open_logs_button":
            paths = [
                str(dict(item or {}).get("log_path") or "")
                for item in list(self._last_state.get("instances") or [])
            ]
            folder = next((str(Path(path).parent) for path in paths if path), "")
            if not folder or not QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(folder)):
                raise RuntimeError("Discord runtime log folder could not be opened.")
            self._last_result = f"Opened Discord logs folder: {folder}"
        elif control in {"discord_refresh_logs_button", "discord_bridge_refresh_button"}:
            self._last_result = "Discord bridge status refreshed."
        elif control == "discord_bridge_save_button":
            self._invoke("runtime.discord.native_action", {"action": "validate", "payload": {}})
            self._last_result = "Discord Voice Bridge settings are saved."
        elif control == "discord_test_tone_restart_button":
            self._invoke(
                "runtime.discord.native_update",
                {"key": "playback.play_test_tone_on_join", "value": True},
            )
            self._invoke("runtime.discord.native_action", {"action": "restart_all", "payload": {}})
            self._last_result = "Restarted the bridge with the test tone enabled."
        else:
            direct = {
                "discord_validate_settings_button": ("validate", {}),
                "discord_install_node_deps_button": ("install_node_dependencies", {}),
                "discord_bridge_start_button": ("start_all", {}),
                "discord_bridge_stop_button": ("stop_all", {}),
                "discord_bridge_restart_button": ("restart_all", {}),
                "discord_live_start_button": ("start_instance", {"instance_id": self._target_id}),
                "discord_live_stop_button": ("stop_instance", {"instance_id": self._target_id}),
                "discord_live_restart_button": ("restart_instance", {"instance_id": self._target_id}),
                "discord_live_reset_context_button": ("reset_instance_context", {"instance_id": self._target_id}),
                "discord_live_apply_selected_button": ("apply_live", {"instance_id": self._target_id}),
                "discord_live_apply_global_button": ("apply_live", {}),
                "discord_live_apply_all_button": ("apply_live", {}),
            }
            command_map = {
                "discord_live_disconnect_button": "leave",
                "discord_live_reconnect_button": "join",
                "discord_live_stop_speech_button": "stop_playback",
                "discord_live_clear_queue_button": "clear_queue",
                "discord_moderator_set_enforcer_button": "moderator_set_enforcer",
                "discord_moderator_clear_enforcer_button": "moderator_clear_enforcer",
                "discord_moderator_clear_pending_button": "moderator_clear_pending",
                "discord_moderator_clear_floor_button": "moderator_clear_floor",
                "discord_moderator_clear_button": "moderator_clear",
            }
            moderator_map = {
                "discord_moderator_route_next_button": "moderator_route_next",
                "discord_moderator_give_floor_button": "moderator_give_floor",
                "discord_moderator_mute_button": "moderator_mute",
                "discord_moderator_unmute_button": "moderator_unmute",
            }
            if control in direct:
                action, payload = direct[control]
                self._invoke("runtime.discord.native_action", {"action": action, "payload": payload})
            elif control in command_map:
                payload: dict[str, Any] = {}
                if control == "discord_moderator_set_enforcer_button":
                    payload = {"target_bot_id": self._target_id, "reason": "native moderator control"}
                self._send_instance_command(command_map[control], payload)
            elif control in moderator_map:
                command, payload = self._moderator_command(moderator_map[control])
                self._send_instance_command(command, payload)
            elif control == "discord_moderator_stop_all_button":
                self._invoke(
                    "runtime.discord.native_action",
                    {"action": "send_all_command", "payload": {"command": "stop_playback"}},
                )
            elif control == "discord_moderator_clear_all_queues_button":
                self._invoke(
                    "runtime.discord.native_action",
                    {"action": "send_all_command", "payload": {"command": "clear_queue"}},
                )
            elif control == "discord_moderator_announce_button":
                if not self._announcement.strip():
                    raise ValueError("Enter a moderator announcement first.")
                self._send_instance_command(
                    "send_message",
                    {"text": self._announcement.strip(), "moderator_announcement": True},
                )
            elif control == "discord_moderator_call_on_button":
                self._send_instance_command(
                    "moderator_call_on",
                    {
                        "target_bot_id": str(self._participant.get("id") or self._target_id),
                        "text": self._announcement.strip(),
                        "reason": "native moderator call on",
                    },
                )
            elif control == "discord_live_send_message_button":
                if not self._live_message.strip():
                    raise ValueError("Enter a live Discord message first.")
                self._send_instance_command("send_message", {"text": self._live_message.strip()})
            else:
                raise KeyError(f"Discord Voice Bridge action {control!r} has no native binding.")
            self._last_result = f"{control.replace('discord_', '').replace('_', ' ').title()} completed."
        self._revision += 1
        self.changed.emit()


def build_discord_voice_bridge_adapter(application_facade: Any) -> DiscordVoiceBridgeNativeAdapter:
    result = application_facade.addons.invoke_addon_capability(
        "nc.discord_voice_bridge",
        "discord_voice_bridge.settings_schema",
        {},
    )
    if not result.accepted or not isinstance(result.value, dict):
        raise RuntimeError("Discord Voice Bridge settings schema is unavailable.")
    return DiscordVoiceBridgeNativeAdapter(application_facade, dict(result.value))


__all__ = ["DiscordVoiceBridgeNativeAdapter", "build_discord_voice_bridge_adapter"]
