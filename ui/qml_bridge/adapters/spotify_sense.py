"""Native QML surface for Spotify Sense.

The adapter is presentation-only. Spotify ownership, OAuth, persistence,
sensory context, playback policy, and asynchronous work remain in the addon.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Mapping

from ui.qml_bridge.adapters.card_layout import apply_card_layout
from ui.qml_bridge.native_contracts import (
    NativeChoice,
    NativeControl,
    NativeControlKind,
    NativeSurface,
    choices,
)
from ui.qml_bridge.native_registry import NativeSurfaceAdapter


_SETTING_KEYS = {
    "spotify_sense_enabled": "enabled",
    "spotify_sense_client_id": "client_id",
    "spotify_sense_redirect_uri": "redirect_uri",
    "spotify_sense_allow_llm_control": "allow_llm_control",
    "spotify_sense_require_confirmation": "require_confirmation",
    "spotify_sense_allow_queue_changes": "allow_queue_changes",
    "spotify_sense_allow_playlist_changes": "allow_playlist_changes",
    "spotify_sense_default_device": "default_device_id",
    "spotify_sense_default_volume": "default_volume",
    "spotify_sense_comment_on_song_changes": "comment_on_song_changes",
    "spotify_sense_song_change_monitor_enabled": "song_change_monitor_enabled",
    "spotify_sense_music_awareness_enabled": "music_awareness_enabled",
    "spotify_sense_music_awareness_relevance_only": "music_awareness_relevance_only",
    "spotify_sense_include_paused_track_context": "include_paused_track_context",
    "spotify_sense_album_art_thumbnail_enabled": "album_art_thumbnail_enabled",
    "spotify_sense_music_response_mode": "music_response_mode",
    "spotify_sense_proactive_comment_cooldown_seconds": "proactive_comment_cooldown_seconds",
    "spotify_sense_hidden_response_cooldown_seconds": "hidden_response_cooldown_seconds",
    "spotify_sense_user_music_change_cooldown_seconds": "user_music_change_cooldown_seconds",
    "spotify_sense_duck_while_speaking": "duck_while_speaking",
    "spotify_sense_restore_volume_after_speech": "restore_volume_after_speech",
    "spotify_sense_duck_volume_percent": "duck_volume_percent",
    "spotify_sense_duck_fade_down_ms": "duck_fade_down_ms",
    "spotify_sense_duck_fade_up_ms": "duck_fade_up_ms",
    "spotify_sense_story_mode_background_music": "story_mode_background_music",
    "spotify_sense_story_music_prefer_ambient": "story_music_prefer_ambient",
    "spotify_sense_autonomous_music": "autonomous_music",
    "spotify_sense_story_music_target_volume": "story_music_target_volume",
    "spotify_sense_story_music_transition_floor_volume": "story_music_transition_floor_volume",
    "spotify_sense_story_music_fade_down_ms": "story_music_fade_down_ms",
    "spotify_sense_story_music_fade_up_ms": "story_music_fade_up_ms",
    "spotify_sense_coding_query": "coding_mode_query",
    "spotify_sense_hidden_commentary_style": "hidden_commentary_style_prompt",
    "spotify_sense_music_conversation_prompt": "music_conversation_prompt",
    "spotify_sense_source_guidance": "source_guidance",
    "spotify_sense_debug_logging_enabled": "debug_logging_enabled",
}

_ACTIONS = {
    "unnamed_qpushbutton_save_settings": "save_settings",
    "unnamed_qpushbutton_login_connect": "connect",
    "unnamed_qpushbutton_disconnect": "disconnect",
    "unnamed_qpushbutton_refresh_devices": "refresh_devices",
    "unnamed_qpushbutton_current_track": "current_track",
    "unnamed_qpushbutton_play": "play",
    "unnamed_qpushbutton_pause": "pause",
    "unnamed_qpushbutton_next": "next",
    "unnamed_qpushbutton_previous": "previous",
    "unnamed_qpushbutton_volume_30": "volume_30",
    "unnamed_qpushbutton_preview_intent": "preview_intent",
    "unnamed_qpushbutton_open_debug_log": "open_debug_log",
    "unnamed_qpushbutton_save_as": "save_hidden_preset",
    "unnamed_qpushbutton_add_quick": "add_hidden_quick",
    "unnamed_qpushbutton_remove_quick": "remove_hidden_quick",
    "unnamed_qpushbutton_save_conversation_prompt": "save_conversation_prompt",
    "unnamed_qpushbutton_use_recommended_conversation_prompt": "reset_conversation_prompt",
    "unnamed_qpushbutton_save_guidance": "save_source_guidance",
    "unnamed_qpushbutton_use_recommended": "reset_source_guidance",
    "unnamed_qpushbutton_save_style": "save_hidden_style",
}


class SpotifySenseNativeAdapter(NativeSurfaceAdapter):
    def __init__(
        self,
        application_facade: Any,
        surface: NativeSurface,
        *,
        persist: Callable[[], object] | None = None,
        parent=None,
    ) -> None:
        super().__init__(surface.id, surface.addon_id, parent)
        self._application = application_facade
        self._surface = surface
        self._persist = persist
        self._intent_test = ""
        self._revision = 0

    def _invoke(self, capability: str, payload=None) -> object:
        result = self._application.addons.invoke_addon_capability(
            self.addon_id, capability, dict(payload or {})
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            raise RuntimeError(
                str(getattr(failure, "message", "Spotify Sense is unavailable."))
            )
        return result.value

    def _snapshot_payload(self) -> dict[str, object]:
        value = self._invoke("runtime.spotify.native_snapshot")
        if not isinstance(value, Mapping):
            raise RuntimeError("Spotify Sense snapshot is not a mapping.")
        return dict(value)

    def snapshot(self) -> NativeSurface:
        payload = self._snapshot_payload()
        settings = dict(payload.get("settings") or {})
        presets = [dict(item) for item in list(payload.get("hidden_presets") or [])]
        quick_ids = [str(item or "") for item in list(payload.get("hidden_quick_ids") or [])]
        selected_preset = str(settings.get("hidden_sensory_preset_id") or "")
        preset_by_id = {str(item.get("id") or ""): item for item in presets}
        preset_options = tuple(
            NativeChoice(str(item.get("id") or ""), str(item.get("name") or "Hidden Sensory"))
            for item in presets
            if str(item.get("id") or "")
        )
        device_options = [NativeChoice("", "Active device / default")]
        for item in list(payload.get("devices") or []):
            device = dict(item)
            device_id = str(device.get("id") or "")
            if not device_id:
                continue
            name = str(device.get("name") or "Spotify device")
            if device.get("is_active"):
                name += " (active)"
            device_options.append(NativeChoice(device_id, name))

        values: dict[str, object] = {
            control_id: settings.get(setting_key)
            for control_id, setting_key in _SETTING_KEYS.items()
        }
        values.update(
            {
                "unnamed_qlabel_qlabel#2": "Optional Spotify Web API controls for current-track awareness, safe music commands, lower music while NC speaks, and story hooks.",
                "spotify_sense_guide": "How it works: add your Spotify Client ID, save, log in, then enable Spotify Sense. Direct user commands can run when Spotify is connected; autonomous/model-initiated changes follow the playback permissions below.",
                "spotify_sense_commands": "Common voice commands: play ambient electronic, play relaxing focus music, pause music, resume Spotify, skip this, previous track, what song is this, or turn Spotify down.",
                "spotify_sense_status": str(payload.get("status") or ""),
                "spotify_sense_activation_status": str(payload.get("activation_status") or ""),
                "spotify_sense_current_track": str(payload.get("track_text") or ""),
                "spotify_sense_album_art": str(
                    dict(payload.get("track") or {}).get("album_art_url") or ""
                ),
                "spotify_sense_music_hub_page": "Rich playback, artist, playlist, and discovery view.",
                "unnamed_qlabel_qlabel": "Controls how Spotify metadata becomes quiet hidden context and optional song-change commentary.",
                "spotify_sense_hidden_preset_combo": selected_preset,
                "spotify_sense_source_guidance": str(payload.get("source_guidance") or ""),
                "spotify_sense_intent_test": self._intent_test,
            }
        )
        controls = []
        for control in self._surface.controls:
            updates: dict[str, object] = {
                "value": values.get(control.id, control.default_value)
            }
            if control.id == "spotify_sense_default_device":
                updates["choices"] = tuple(device_options)
            elif control.id == "spotify_sense_hidden_preset_combo":
                updates["choices"] = (NativeChoice("", "Load hidden sensory style..."),) + preset_options
            elif control.id.startswith("spotify_sense_hidden_quick_"):
                slot = int(control.id.rsplit("_", 1)[-1]) - 1
                preset_id = quick_ids[slot] if slot < len(quick_ids) else ""
                record = preset_by_id.get(preset_id, {})
                label = str(record.get("name") or "Empty")
                updates.update(
                    value=bool(preset_id and preset_id == selected_preset),
                    label=f"{slot + 1}. {label}",
                    enabled=bool(preset_id),
                )
            controls.append(replace(control, **updates))
        return replace(
            self._surface,
            controls=apply_card_layout(
                controls,
                overrides=_spotify_card_overrides(),
            ),
            revision=self._revision,
        )

    def set_value(self, control_id: str, value: Any) -> None:
        key = str(control_id or "").strip()
        if key == "spotify_sense_intent_test":
            self._intent_test = str(value or "")
        elif key == "spotify_sense_hidden_preset_combo":
            self._invoke(
                "runtime.spotify.native_update",
                {"key": "hidden_preset_id", "value": value},
            )
        elif key.startswith("spotify_sense_hidden_quick_"):
            self._invoke(
                "runtime.spotify.native_update",
                {"key": key.removeprefix("spotify_sense_"), "value": bool(value)},
            )
        else:
            setting_key = _SETTING_KEYS.get(key)
            if setting_key is None:
                raise KeyError(f"Unknown Spotify Sense setting '{control_id}'.")
            self._invoke(
                "runtime.spotify.native_update",
                {"key": setting_key, "value": value},
            )
            if callable(self._persist) and setting_key != "client_id":
                self._persist()
        self._revision += 1
        self.changed.emit()

    def trigger(self, control_id: str) -> None:
        action = _ACTIONS.get(str(control_id or "").strip())
        if action is None:
            raise KeyError(f"Unknown Spotify Sense action '{control_id}'.")
        payload: dict[str, object] = {"action": action}
        if action == "preview_intent":
            payload["text"] = self._intent_test
        self._invoke("runtime.spotify.native_action", payload)
        if callable(self._persist) and action not in {
            "current_track", "play", "pause", "next", "previous", "volume_30",
            "refresh_devices", "preview_intent", "open_debug_log",
        }:
            self._persist()
        self._revision += 1
        self.changed.emit()


def _control_group(
    key: str,
    title: str,
    *,
    column_span: int = 1,
    **presentation: object,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "groupKey": key,
        "groupTitle": title,
        "groupColumnSpan": max(1, min(2, int(column_span))),
    }
    metadata.update(presentation)
    return metadata


def _spotify_card_overrides() -> dict[str, tuple[str, str, int]]:
    placements: dict[str, tuple[str, str, int]] = {}

    def place(ids: tuple[str, ...], key: str, title: str, span: int = 1) -> None:
        for control_id in ids:
            placements[control_id] = (key, title, span)

    place(
        (
            "spotify_sense_client_id",
            "spotify_sense_redirect_uri",
            "unnamed_qpushbutton_save_settings",
            "unnamed_qpushbutton_login_connect",
            "unnamed_qpushbutton_disconnect",
            "unnamed_qpushbutton_refresh_devices",
        ),
        "connect_account",
        "Account configuration",
    )
    place(
        (
            "spotify_sense_allow_llm_control",
            "spotify_sense_require_confirmation",
            "spotify_sense_allow_queue_changes",
            "spotify_sense_allow_playlist_changes",
        ),
        "playback_permissions",
        "Playback permissions",
    )
    place(
        ("spotify_sense_default_device", "spotify_sense_default_volume"),
        "playback_device_volume",
        "Device and volume",
    )
    place(
        (
            "spotify_sense_music_awareness_enabled",
            "spotify_sense_music_awareness_relevance_only",
            "spotify_sense_include_paused_track_context",
            "spotify_sense_album_art_thumbnail_enabled",
            "spotify_sense_music_response_mode",
        ),
        "awareness_music",
        "Music awareness",
    )
    place(
        (
            "spotify_sense_comment_on_song_changes",
            "spotify_sense_song_change_monitor_enabled",
            "spotify_sense_proactive_comment_cooldown_seconds",
            "spotify_sense_hidden_response_cooldown_seconds",
            "spotify_sense_user_music_change_cooldown_seconds",
        ),
        "awareness_song_changes",
        "Song-change commentary",
    )
    place(
        (
            "spotify_sense_duck_while_speaking",
            "spotify_sense_restore_volume_after_speech",
        ),
        "ducking_behavior",
        "Voice ducking behavior",
    )
    place(
        (
            "spotify_sense_duck_volume_percent",
            "spotify_sense_duck_fade_down_ms",
            "spotify_sense_duck_fade_up_ms",
        ),
        "ducking_levels",
        "Levels and fades",
    )
    place(
        (
            "spotify_sense_story_mode_background_music",
            "spotify_sense_story_music_prefer_ambient",
            "spotify_sense_autonomous_music",
            "spotify_sense_coding_query",
        ),
        "story_autonomy",
        "Story autonomy",
    )
    place(
        (
            "spotify_sense_story_music_target_volume",
            "spotify_sense_story_music_transition_floor_volume",
            "spotify_sense_story_music_fade_down_ms",
            "spotify_sense_story_music_fade_up_ms",
        ),
        "story_transitions",
        "Story transitions",
    )
    place(
        (
            "unnamed_qlabel_qlabel",
            "spotify_sense_hidden_preset_combo",
            "unnamed_qpushbutton_save_as",
        ),
        "hidden_presets",
        "Preset library",
    )
    place(
        tuple(f"spotify_sense_hidden_quick_{index}" for index in range(1, 7))
        + (
            "unnamed_qpushbutton_add_quick",
            "unnamed_qpushbutton_remove_quick",
        ),
        "hidden_quick_styles",
        "Quick styles",
    )
    place(
        (
            "spotify_sense_hidden_commentary_style",
            "spotify_sense_music_conversation_prompt",
            "unnamed_qpushbutton_save_conversation_prompt",
            "unnamed_qpushbutton_use_recommended_conversation_prompt",
            "unnamed_qpushbutton_save_style",
        ),
        "hidden_response_prompts",
        "Response prompts",
        2,
    )
    place(
        (
            "spotify_sense_source_guidance",
            "unnamed_qpushbutton_save_guidance",
            "unnamed_qpushbutton_use_recommended",
        ),
        "hidden_source_guidance",
        "Source guidance",
        2,
    )
    place(
        (
            "spotify_sense_debug_logging_enabled",
            "unnamed_qpushbutton_open_debug_log",
        ),
        "advanced_diagnostics",
        "Diagnostics",
    )
    place(
        (
            "spotify_sense_intent_test",
            "unnamed_qpushbutton_preview_intent",
        ),
        "advanced_intent_test",
        "Intent test",
    )
    return placements


def _action(
    control_id: str,
    label: str,
    section: str,
    *,
    destructive: bool = False,
    metadata: Mapping[str, object] | None = None,
) -> NativeControl:
    options: dict[str, object] = {
        "execution": "ui",
        "destructive": destructive,
    }
    options.update(dict(metadata or {}))
    return NativeControl(
        control_id,
        label,
        NativeControlKind.ACTION,
        section,
        metadata=options,
    )


def _integer(control_id: str, label: str, section: str, minimum: int, maximum: int) -> NativeControl:
    return NativeControl(
        control_id, label, NativeControlKind.INTEGER, section,
        minimum=minimum, maximum=maximum, step=1,
    )


def build_spotify_sense_adapter(
    application_facade: Any,
    *,
    persist: Callable[[], object] | None = None,
) -> SpotifySenseNativeAdapter:
    overview_activation = _control_group(
        "overview_activation",
        "Activation and status",
    )
    overview_information = _control_group(
        "overview_information",
        "Spotify Sense at a glance",
        stackedLayout=True,
    )
    overview_playback = _control_group(
        "overview_playback",
        "Playback",
        column_span=2,
    )
    overview_playback_content = _control_group(
        "overview_playback",
        "Playback",
        column_span=2,
        stackedLayout=True,
    )
    overview_action = _control_group(
        "overview_playback",
        "Playback",
        column_span=2,
        actionStrip=True,
        compactActionWidth=148,
    )
    connect_account = _control_group(
        "connect_account",
        "Account configuration",
        stackedLayout=True,
        editableWhileInactive=True,
    )
    connect_action = _control_group(
        "connect_account",
        "Account configuration",
        actionStrip=True,
        compactActionWidth=156,
    )
    surface = NativeSurface(
        id="spotify_sense_tab",
        title="Spotify Sense",
        addon_id="nc.spotify_sense",
        sections=("Overview", "Music Hub", "Connect", "Playback", "Awareness", "Ducking", "Story", "Hidden Sense", "Advanced"),
        description="Spotify connection, playback safety, music awareness, ducking, story hooks, and hidden sensory guidance.",
        controls=(
            NativeControl("spotify_sense_status", "Spotify Sense Status", NativeControlKind.DISPLAY, "Overview", metadata=overview_activation),
            NativeControl("spotify_sense_enabled", "Enable Spotify Sense", NativeControlKind.BOOLEAN, "Overview", metadata=overview_activation),
            NativeControl("spotify_sense_activation_status", "Spotify Sense Activation Status", NativeControlKind.DISPLAY, "Overview", metadata=overview_activation),
            NativeControl("unnamed_qlabel_qlabel#2", "Overview", NativeControlKind.DISPLAY, "Overview", metadata=overview_information),
            NativeControl("spotify_sense_guide", "Spotify Sense Guide", NativeControlKind.DISPLAY, "Overview", metadata=overview_information),
            NativeControl("spotify_sense_commands", "Spotify Sense Commands", NativeControlKind.DISPLAY, "Overview", metadata=overview_information),
            NativeControl(
                "spotify_sense_album_art",
                "Album artwork",
                NativeControlKind.IMAGE,
                "Overview",
                metadata={
                    **overview_playback_content,
                    "imageMinimumWidth": 180,
                    "imageMinimumHeight": 180,
                    "imagePreferredWidth": 220,
                    "imagePreferredHeight": 220,
                    "editorPreferredWidth": 220,
                    "imagePlaceholder": "No album artwork available",
                    "readOnly": True,
                },
            ),
            NativeControl("spotify_sense_current_track", "Now playing", NativeControlKind.DISPLAY, "Overview", metadata=overview_playback_content),
            _action("unnamed_qpushbutton_play", "Play", "Overview", metadata=overview_action),
            _action("unnamed_qpushbutton_pause", "Pause", "Overview", metadata=overview_action),
            _action("unnamed_qpushbutton_next", "Next", "Overview", metadata=overview_action),
            _action("unnamed_qpushbutton_previous", "Previous", "Overview", metadata=overview_action),
            _action("unnamed_qpushbutton_current_track", "Refresh track", "Overview", metadata=overview_action),
            _action("unnamed_qpushbutton_volume_30", "Volume 30%", "Overview", metadata=overview_action),
            NativeControl("spotify_sense_music_hub_page", "Music Hub", NativeControlKind.DISPLAY, "Music Hub"),
            NativeControl("spotify_sense_client_id", "Client ID", NativeControlKind.TEXT, "Connect", metadata=connect_account),
            NativeControl("spotify_sense_redirect_uri", "Redirect URI", NativeControlKind.TEXT, "Connect", metadata=connect_account),
            _action("unnamed_qpushbutton_save_settings", "Save Settings", "Connect", metadata=connect_action),
            _action("unnamed_qpushbutton_login_connect", "Login / Connect", "Connect", metadata=connect_action),
            _action("unnamed_qpushbutton_disconnect", "Disconnect", "Connect", destructive=True, metadata=connect_action),
            _action("unnamed_qpushbutton_refresh_devices", "Refresh Devices", "Connect", metadata=connect_action),
            NativeControl("spotify_sense_allow_llm_control", "Allow autonomous LLM Spotify control", NativeControlKind.BOOLEAN, "Playback"),
            NativeControl("spotify_sense_require_confirmation", "Require confirmation before changing music", NativeControlKind.BOOLEAN, "Playback"),
            NativeControl("spotify_sense_allow_queue_changes", "Allow queue changes", NativeControlKind.BOOLEAN, "Playback"),
            NativeControl("spotify_sense_allow_playlist_changes", "Allow playlist changes", NativeControlKind.BOOLEAN, "Playback"),
            NativeControl("spotify_sense_default_device", "Default device", NativeControlKind.CHOICE, "Playback", choices=(NativeChoice("", "Active device / default"),)),
            _integer("spotify_sense_default_volume", "Default volume", "Playback", 0, 100),
            NativeControl("spotify_sense_comment_on_song_changes", "Comment on song changes", NativeControlKind.BOOLEAN, "Awareness"),
            NativeControl("spotify_sense_song_change_monitor_enabled", "Song-change monitor", NativeControlKind.BOOLEAN, "Awareness"),
            NativeControl("spotify_sense_music_awareness_enabled", "Enable music awareness in chat", NativeControlKind.BOOLEAN, "Awareness"),
            NativeControl("spotify_sense_music_awareness_relevance_only", "Only mention music when relevant", NativeControlKind.BOOLEAN, "Awareness"),
            NativeControl("spotify_sense_include_paused_track_context", "Include paused Spotify track context", NativeControlKind.BOOLEAN, "Awareness"),
            NativeControl("spotify_sense_album_art_thumbnail_enabled", "Album art thumbnail", NativeControlKind.BOOLEAN, "Awareness"),
            NativeControl("spotify_sense_music_response_mode", "Music response mode", NativeControlKind.CHOICE, "Awareness", choices=choices((("off", "Off"), ("subtle", "Subtle"), ("companion", "Companion"), ("dj_critic", "DJ / Music Critic"), ("story_soundtrack", "Story soundtrack")))),
            _integer("spotify_sense_proactive_comment_cooldown_seconds", "Proactive comment cooldown (seconds)", "Awareness", 15, 3600),
            _integer("spotify_sense_hidden_response_cooldown_seconds", "Hidden response cooldown (seconds)", "Awareness", 15, 7200),
            _integer("spotify_sense_user_music_change_cooldown_seconds", "User music-change cooldown (seconds)", "Awareness", 0, 3600),
            NativeControl("spotify_sense_duck_while_speaking", "Lower music while NC speaks", NativeControlKind.BOOLEAN, "Ducking"),
            NativeControl("spotify_sense_restore_volume_after_speech", "Restore volume after speech", NativeControlKind.BOOLEAN, "Ducking"),
            _integer("spotify_sense_duck_volume_percent", "Duck volume", "Ducking", 0, 100),
            _integer("spotify_sense_duck_fade_down_ms", "Fade down (ms)", "Ducking", 0, 5000),
            _integer("spotify_sense_duck_fade_up_ms", "Fade up (ms)", "Ducking", 0, 5000),
            NativeControl("spotify_sense_story_mode_background_music", "Story mode background music", NativeControlKind.BOOLEAN, "Story"),
            NativeControl("spotify_sense_story_music_prefer_ambient", "Prefer story ambience", NativeControlKind.BOOLEAN, "Story"),
            NativeControl("spotify_sense_autonomous_music", "Autonomous music", NativeControlKind.CHOICE, "Story", choices=choices((("off", "Off"), ("routines", "Routines only"), ("full", "Full")))),
            _integer("spotify_sense_story_music_target_volume", "Story music target volume", "Story", 0, 100),
            _integer("spotify_sense_story_music_transition_floor_volume", "Transition floor volume", "Story", 0, 100),
            _integer("spotify_sense_story_music_fade_down_ms", "Story fade down (ms)", "Story", 0, 8000),
            _integer("spotify_sense_story_music_fade_up_ms", "Story fade up (ms)", "Story", 0, 8000),
            NativeControl("spotify_sense_coding_query", "Coding-mode query", NativeControlKind.TEXT, "Story"),
            NativeControl("unnamed_qlabel_qlabel", "Hidden Sense", NativeControlKind.DISPLAY, "Hidden Sense"),
            NativeControl("spotify_sense_hidden_preset_combo", "Hidden sensory preset", NativeControlKind.CHOICE, "Hidden Sense", choices=(NativeChoice("", "Load hidden sensory style..."),)),
            _action("unnamed_qpushbutton_save_as", "Save As", "Hidden Sense"),
            _action("unnamed_qpushbutton_add_quick", "Add Quick", "Hidden Sense"),
            _action("unnamed_qpushbutton_remove_quick", "Remove Quick", "Hidden Sense", destructive=True),
            *(NativeControl(f"spotify_sense_hidden_quick_{index}", f"{index}. Empty", NativeControlKind.BOOLEAN, "Hidden Sense") for index in range(1, 7)),
            NativeControl("spotify_sense_hidden_commentary_style", "Hidden commentary style", NativeControlKind.MULTILINE, "Hidden Sense"),
            NativeControl("spotify_sense_music_conversation_prompt", "Music conversation prompt", NativeControlKind.MULTILINE, "Hidden Sense"),
            _action("unnamed_qpushbutton_save_conversation_prompt", "Save Conversation Prompt", "Hidden Sense"),
            _action("unnamed_qpushbutton_use_recommended_conversation_prompt", "Use Recommended Conversation Prompt", "Hidden Sense"),
            NativeControl("spotify_sense_source_guidance", "Source guidance", NativeControlKind.MULTILINE, "Hidden Sense"),
            _action("unnamed_qpushbutton_save_guidance", "Save Guidance", "Hidden Sense"),
            _action("unnamed_qpushbutton_use_recommended", "Use Recommended", "Hidden Sense"),
            _action("unnamed_qpushbutton_save_style", "Save Style", "Hidden Sense"),
            NativeControl("spotify_sense_debug_logging_enabled", "Debug log", NativeControlKind.BOOLEAN, "Advanced"),
            NativeControl("spotify_sense_intent_test", "Intent test", NativeControlKind.TEXT, "Advanced"),
            _action("unnamed_qpushbutton_preview_intent", "Preview Intent", "Advanced"),
            _action("unnamed_qpushbutton_open_debug_log", "Open Debug Log", "Advanced"),
        ),
    )
    return SpotifySenseNativeAdapter(application_facade, surface, persist=persist)


__all__ = ["SpotifySenseNativeAdapter", "build_spotify_sense_adapter"]
