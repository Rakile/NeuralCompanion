from __future__ import annotations

import http.server
import json
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Callable

from PySide6 import QtCore, QtGui, QtWidgets

from .intent_router import infer_music_mood, route_music_intent
from .settings import DEFAULT_SETTINGS, TOKEN_KEYS, SpotifySenseSettings
from .spotify_client import SpotifySenseClient


READ_TOOLS = {
    "spotify.current_track",
    "spotify.devices",
    "spotify.commentary",
    "spotify.route_intent",
}

CONTROL_TOOLS = {
    "spotify.play_search",
    "spotify.play_playlist",
    "spotify.pause",
    "spotify.resume",
    "spotify.next",
    "spotify.previous",
    "spotify.volume",
    "spotify.shuffle",
    "spotify.repeat",
    "spotify.transfer_device",
    "spotify.add_to_queue",
    "spotify.duck.start",
    "spotify.duck.end",
    "spotify.story_hook",
}

TOOL_NAMES = READ_TOOLS | CONTROL_TOOLS
SENSORY_PROVIDER_ID = "spotify_sense"
DEFAULT_SPOTIFY_SOURCE_GUIDANCE = (
    "Spotify Sense provides metadata only. Treat it as ambient music context, not a user request and not raw audio analysis. "
    "Use track title, artists, album, playback state, and mood hint to support the current conversation, story, coding session, or user command. "
    "Do not repeatedly mention Spotify. Speak about music only when the user asks, when a fresh track-change comment is allowed, or when it clearly improves the reply."
)
MUSIC_RESPONSE_MODES = (
    ("Off", "off"),
    ("Subtle", "subtle"),
    ("Companion", "companion"),
    ("DJ / Music Critic", "dj_critic"),
    ("Story soundtrack", "story_soundtrack"),
)

SETTING_TOOLTIPS = {
    "enabled": "Turns Spotify Sense on. The addon still needs a connected Spotify account before it can read or control playback.",
    "allow_llm_control": "Allows autonomous/model-initiated Spotify changes. Direct user voice commands can still run when Spotify is connected.",
    "require_confirmation": "Keeps autonomous/tool-triggered playback changes blocked unless the request is confirmed. Direct user commands are treated as confirmed.",
    "duck_while_speaking": "Temporarily lowers Spotify volume while NC speaks, if the active Spotify device allows volume control.",
    "restore_volume_after_speech": "Restores the saved Spotify volume after NC finishes speaking.",
    "duck_fade_down_ms": "How long Spotify takes to fade down when NC starts speaking. Set to 0 for immediate changes.",
    "duck_fade_up_ms": "How long Spotify takes to fade back up after NC stops speaking. Set to 0 for immediate restore.",
    "comment_on_song_changes": "Allows a short optional acknowledgement when Spotify detects a new track, subject to the cooldown timers.",
    "allow_queue_changes": "Allows NC tools to add tracks to the Spotify queue.",
    "allow_playlist_changes": "Allows NC tools to start playlists or playlist contexts.",
    "story_mode_background_music": "Allows story hooks to select background music when story mode asks for it.",
    "song_change_monitor_enabled": "Polls Spotify periodically so NC can notice track changes and update music context.",
    "music_awareness_enabled": "Adds compact current-track metadata to normal chat context. No audio is recorded or analyzed.",
    "album_art_thumbnail_enabled": "Shows the current track album/single cover as a small thumbnail in this addon tab.",
    "include_paused_track_context": "Keeps paused Spotify track metadata visible to NC. Leave off if paused music should be ignored.",
    "music_awareness_relevance_only": "Tells NC to mention the music only when it helps the current reply or creative task.",
    "default_volume": "Default volume used for quick tests and fallback relative volume math.",
    "duck_volume_percent": "Spotify volume percentage while NC is speaking.",
    "proactive_comment_cooldown_seconds": "Minimum time between normal song-change acknowledgement opportunities.",
    "hidden_response_cooldown_seconds": "Minimum time between hidden Spotify sensory responses. This prevents periodic music chatter.",
    "user_music_change_cooldown_seconds": "How long NC waits after an external/user track change before it may change Spotify playback.",
    "autonomous_music": "How much story/routine code may change music without a direct user command.",
    "music_response_mode": "How strongly NC may use current-track metadata in replies.",
    "default_device_id": "Spotify device used for playback commands. Empty means Spotify's active/default device.",
    "coding_mode_query": "Search phrase used by coding/focus story hooks.",
    "debug_logging_enabled": "Writes Spotify Sense route, playback, and ducking diagnostics to an addon-local debug log file.",
}


class _OAuthHTTPServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True


class SpotifySenseController(QtCore.QObject):
    oauth_callback_received = QtCore.Signal(dict)
    async_result_ready = QtCore.Signal(str, dict)
    status_message = QtCore.Signal(str)

    def __init__(self, context):
        super().__init__()
        self.context = context
        self.settings = SpotifySenseSettings(context.storage)
        self.client = SpotifySenseClient(self.settings)
        self._widgets: list[QtWidgets.QWidget] = []
        self._controls: dict[str, QtWidgets.QWidget] = {}
        self._oauth_server = None
        self._last_track_id = ""
        self._last_track_comment_at = 0.0
        self._remembered_volume: int | None = None
        self._remembered_duck_device_id: str | None = None
        self._cached_music_context: dict[str, Any] = {}
        self._cached_music_context_at = 0.0
        self._last_context_refresh_request_at = 0.0
        self._context_refresh_in_flight = False
        self._pending_track_change_context: dict[str, Any] | None = None
        self._pending_direct_command_context: dict[str, Any] | None = None
        self._last_hidden_response_snapshot_at = 0.0
        self._last_nc_music_change_at = 0.0
        self._last_user_music_change_at = 0.0
        self._last_album_art_url = ""
        self._duck_transition_lock = threading.RLock()
        self._duck_transition_generation = 0
        self._sensory_provider_registered = False

        self.oauth_callback_received.connect(self._handle_oauth_callback, QtCore.Qt.QueuedConnection)
        self.async_result_ready.connect(self._handle_async_result, QtCore.Qt.QueuedConnection)
        self.status_message.connect(self._set_status, QtCore.Qt.QueuedConnection)

        self._register_sensory_provider()
        self._track_monitor_timer = QtCore.QTimer(self)
        self._track_monitor_timer.setInterval(7000)
        self._track_monitor_timer.timeout.connect(self._poll_track_change)
        self._sync_monitor_timer()

    def _register_sensory_provider(self):
        service = self.context.get_service("qt.sensory") if getattr(self, "context", None) is not None else None
        if service is None:
            return
        try:
            service.register_provider(
                provider_id=SENSORY_PROVIDER_ID,
                label="Spotify Sense",
                instruction=(
                    "Hidden music awareness from Spotify metadata. Treat it as ambient context only; "
                    "do not claim to hear raw audio. Do not speak about Spotify repeatedly; set should_speak=false "
                    "unless the current snapshot explicitly says a fresh song-change comment is allowed."
                ),
                description="Current Spotify track metadata for music-aware chat and optional hidden sensory feedback.",
                order=340,
                capture_handler=self.capture_sensory_snapshot,
                metadata={
                    "kind": "music",
                    "provider": "spotify",
                    "text_only": True,
                    "hide_vision_source_tab": True,
                    "pingpong_prompt": (
                        "Spotify Sense provides metadata only. Set should_speak=true only when content_text says "
                        "hidden response is allowed now. Otherwise keep=false or keep=true with should_speak=false."
                    ),
                },
            )
            self._sensory_provider_registered = True
        except Exception as exc:
            try:
                self.context.logger.warning("[SpotifySense] Could not register sensory provider: %s", exc)
            except Exception:
                pass

    def _unregister_sensory_provider(self):
        if not self._sensory_provider_registered:
            return
        service = self.context.get_service("qt.sensory") if getattr(self, "context", None) is not None else None
        if service is not None:
            try:
                service.unregister_provider(SENSORY_PROVIDER_ID)
            except Exception:
                pass
        self._sensory_provider_registered = False

    def _section_group(self, title: str) -> tuple[QtWidgets.QGroupBox, QtWidgets.QVBoxLayout]:
        group = QtWidgets.QGroupBox(str(title or "").strip())
        group.setStyleSheet(
            "QGroupBox {"
            "  color: #dbeafe;"
            "  font-weight: 700;"
            "  border: 1px solid rgba(96, 165, 250, 0.32);"
            "  border-radius: 7px;"
            "  margin-top: 10px;"
            "  padding-top: 10px;"
            "}"
            "QGroupBox::title {"
            "  subcontrol-origin: margin;"
            "  left: 10px;"
            "  padding: 0 4px;"
            "}"
        )
        layout = QtWidgets.QVBoxLayout(group)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        return group, layout

    def build_tab(self):
        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("spotify_sense_addon_tab")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        content = QtWidgets.QWidget()
        content.setObjectName("spotify_sense_content")
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        card = QtWidgets.QFrame()
        card.setObjectName("spotify_sense_card")
        card.setStyleSheet(
            "QFrame#spotify_sense_card {"
            "  background: rgba(10, 18, 30, 0.74);"
            "  border: 1px solid #2f4b68;"
            "  border-radius: 8px;"
            "}"
        )
        card_layout = QtWidgets.QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(10)

        title = QtWidgets.QLabel("Spotify Sense")
        title.setObjectName("spotify_sense_title")
        title.setStyleSheet("font-size: 14px; font-weight: 800; color: #ecfeff;")
        card_layout.addWidget(title)

        intro = QtWidgets.QLabel(
            "Optional Spotify Web API controls for current-track awareness, safe music commands, ducking, and story hooks."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #9fb3c8;")
        card_layout.addWidget(intro)

        guide = QtWidgets.QLabel(
            "How it works: add your Spotify Client ID, save, log in, then enable Spotify Sense. "
            "Direct user commands like \"pause music\" or \"play calm focus music\" can run when Spotify is connected. "
            "Use LLM Spotify control for autonomous/model-initiated changes. "
            "Music awareness sends metadata only; hidden responses and NC music changes use the cooldowns below."
        )
        guide.setObjectName("spotify_sense_guide")
        guide.setWordWrap(True)
        guide.setStyleSheet(
            "QLabel#spotify_sense_guide {"
            "  color: #dbeafe;"
            "  background: rgba(30, 64, 96, 0.42);"
            "  border: 1px solid rgba(96, 165, 250, 0.35);"
            "  border-radius: 6px;"
            "  padding: 8px;"
            "}"
        )
        guide.setToolTip("Quick setup and behavior summary for Spotify Sense.")
        card_layout.addWidget(guide)

        commands = QtWidgets.QLabel(
            "Common voice commands: \"play ambient electronic\", \"play relaxing focus music\", "
            "\"pause music\", \"resume Spotify\", \"skip this\", \"previous track\", "
            "\"next song and comment about it\", \"what song is this?\", "
            "\"turn Spotify down\", \"turn Spotify up\"."
        )
        commands.setObjectName("spotify_sense_commands")
        commands.setWordWrap(True)
        commands.setStyleSheet(
            "QLabel#spotify_sense_commands {"
            "  color: #c7d2fe;"
            "  background: rgba(15, 23, 42, 0.45);"
            "  border: 1px solid rgba(129, 140, 248, 0.30);"
            "  border-radius: 6px;"
            "  padding: 8px;"
            "}"
        )
        commands.setToolTip("Examples of phrases Spotify Sense can route from typed or spoken chat. Add \"and comment about it\" when you want NC to react after changing tracks.")
        card_layout.addWidget(commands)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setObjectName("spotify_sense_status")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        card_layout.addWidget(self.status_label)

        connection_group, connection_layout = self._section_group("Connection")
        auth_grid = QtWidgets.QGridLayout()
        auth_grid.setContentsMargins(0, 0, 0, 0)
        auth_grid.setHorizontalSpacing(10)
        auth_grid.setVerticalSpacing(6)

        self.client_id_edit = QtWidgets.QLineEdit()
        self.client_id_edit.setObjectName("spotify_sense_client_id")
        self.client_id_edit.setPlaceholderText("Spotify app Client ID")
        self.client_id_edit.setText(str(self.settings.data.get("client_id") or ""))
        self.client_id_edit.setToolTip("Paste the Client ID from your Spotify Developer Dashboard app.")
        self.client_id_edit.editingFinished.connect(self._on_text_settings_finished)

        self.redirect_uri_edit = QtWidgets.QLineEdit()
        self.redirect_uri_edit.setObjectName("spotify_sense_redirect_uri")
        self.redirect_uri_edit.setText(str(self.settings.data.get("redirect_uri") or DEFAULT_SETTINGS["redirect_uri"]))
        self.redirect_uri_edit.setToolTip("Must match the redirect URI configured in the Spotify Developer Dashboard.")
        self.redirect_uri_edit.editingFinished.connect(self._on_text_settings_finished)

        auth_grid.addWidget(QtWidgets.QLabel("Client ID"), 0, 0)
        auth_grid.addWidget(self.client_id_edit, 0, 1, 1, 3)
        auth_grid.addWidget(QtWidgets.QLabel("Redirect URI"), 1, 0)
        auth_grid.addWidget(self.redirect_uri_edit, 1, 1, 1, 3)
        auth_grid.setColumnStretch(1, 1)
        connection_layout.addLayout(auth_grid)

        auth_buttons = QtWidgets.QHBoxLayout()
        auth_buttons.setContentsMargins(0, 0, 0, 0)
        auth_buttons.setSpacing(8)
        for label, handler in (
            ("Save Settings", self._on_save_settings),
            ("Login / Connect", self._on_connect),
            ("Disconnect", self._on_disconnect),
            ("Refresh Devices", self._on_refresh_devices),
        ):
            button = QtWidgets.QPushButton(label)
            button.setToolTip(
                {
                    "Save Settings": "Save Client ID, redirect URI, and local Spotify Sense settings.",
                    "Login / Connect": "Open Spotify OAuth login and grant the required playback scopes.",
                    "Disconnect": "Clear local Spotify tokens from addon storage.",
                    "Refresh Devices": "Reload Spotify devices so playback commands can target the right device.",
                }.get(label, "")
            )
            button.clicked.connect(handler)
            auth_buttons.addWidget(button)
        auth_buttons.addStretch(1)
        connection_layout.addLayout(auth_buttons)
        card_layout.addWidget(connection_group)

        settings_group, settings_layout = self._section_group("Playback And Awareness")
        settings_grid = QtWidgets.QGridLayout()
        settings_grid.setContentsMargins(0, 0, 0, 0)
        settings_grid.setHorizontalSpacing(10)
        settings_grid.setVerticalSpacing(6)

        self.enable_checkbox = self._checkbox("Enable Spotify Sense", "enabled")
        self.llm_checkbox = self._checkbox("Allow autonomous LLM Spotify control", "allow_llm_control")
        self.confirm_checkbox = self._checkbox("Require confirmation before changing music", "require_confirmation")
        self.duck_checkbox = self._checkbox("Duck music while NC speaks", "duck_while_speaking")
        self.restore_checkbox = self._checkbox("Restore volume after speech", "restore_volume_after_speech")
        self.comment_checkbox = self._checkbox("Comment on song changes", "comment_on_song_changes")
        self.queue_checkbox = self._checkbox("Allow queue changes", "allow_queue_changes")
        self.playlist_checkbox = self._checkbox("Allow playlist changes", "allow_playlist_changes")
        self.story_checkbox = self._checkbox("Story mode background music", "story_mode_background_music")
        self.monitor_checkbox = self._checkbox("Song-change monitor", "song_change_monitor_enabled")
        self.awareness_checkbox = self._checkbox("Enable music awareness in chat", "music_awareness_enabled")
        self.album_art_checkbox = self._checkbox("Album art thumbnail", "album_art_thumbnail_enabled")
        self.paused_context_checkbox = self._checkbox("Include paused Spotify track context", "include_paused_track_context")
        self.relevance_checkbox = self._checkbox("Only mention music when relevant", "music_awareness_relevance_only")

        self.autonomy_combo = QtWidgets.QComboBox()
        self.autonomy_combo.setObjectName("spotify_sense_autonomous_music")
        self.autonomy_combo.setToolTip(SETTING_TOOLTIPS["autonomous_music"])
        for label, value in (("Off", "off"), ("Routines only", "routines"), ("Full", "full")):
            self.autonomy_combo.addItem(label, value)
        self._set_combo_value(self.autonomy_combo, self.settings.data.get("autonomous_music", "off"))
        self.autonomy_combo.currentIndexChanged.connect(lambda _index: self._update_setting("autonomous_music", self.autonomy_combo.currentData()))

        self.response_mode_combo = QtWidgets.QComboBox()
        self.response_mode_combo.setObjectName("spotify_sense_music_response_mode")
        self.response_mode_combo.setToolTip(SETTING_TOOLTIPS["music_response_mode"])
        for label, value in MUSIC_RESPONSE_MODES:
            self.response_mode_combo.addItem(label, value)
        self._set_combo_value(self.response_mode_combo, self.settings.data.get("music_response_mode", "subtle"))
        self.response_mode_combo.currentIndexChanged.connect(lambda _index: self._update_setting("music_response_mode", self.response_mode_combo.currentData()))
        self._controls["music_response_mode"] = self.response_mode_combo

        self.default_device_combo = QtWidgets.QComboBox()
        self.default_device_combo.setObjectName("spotify_sense_default_device")
        self.default_device_combo.setToolTip(SETTING_TOOLTIPS["default_device_id"])
        self.default_device_combo.addItem("Active device / default", "")
        self.default_device_combo.currentIndexChanged.connect(lambda _index: self._update_setting("default_device_id", self.default_device_combo.currentData()))

        self.default_volume_spin = self._spinbox("default_volume", 0, 100)
        self.duck_volume_spin = self._spinbox("duck_volume_percent", 0, 100)
        self.duck_fade_down_spin = self._spinbox("duck_fade_down_ms", 0, 5000, suffix="ms")
        self.duck_fade_up_spin = self._spinbox("duck_fade_up_ms", 0, 5000, suffix="ms")
        self.comment_cooldown_spin = self._spinbox("proactive_comment_cooldown_seconds", 15, 3600, suffix="s")
        self.hidden_response_cooldown_spin = self._spinbox("hidden_response_cooldown_seconds", 15, 7200, suffix="s")
        self.user_change_cooldown_spin = self._spinbox("user_music_change_cooldown_seconds", 0, 3600, suffix="s")
        self.debug_log_checkbox = self._checkbox("Debug log", "debug_logging_enabled")

        self.coding_query_edit = QtWidgets.QLineEdit()
        self.coding_query_edit.setObjectName("spotify_sense_coding_query")
        self.coding_query_edit.setText(str(self.settings.data.get("coding_mode_query") or "relaxing focus music"))
        self.coding_query_edit.setToolTip(SETTING_TOOLTIPS["coding_mode_query"])
        self.coding_query_edit.editingFinished.connect(self._on_text_settings_finished)

        rows = [
            (self.enable_checkbox, self.llm_checkbox),
            (self.confirm_checkbox, self.monitor_checkbox),
            (self.duck_checkbox, self.restore_checkbox),
            (self.comment_checkbox, self.queue_checkbox),
            (self.playlist_checkbox, self.story_checkbox),
            (self.awareness_checkbox, self.paused_context_checkbox),
            (self.relevance_checkbox, self.album_art_checkbox),
            (self.debug_log_checkbox, QtWidgets.QWidget()),
        ]
        row_index = 0
        for left, right in rows:
            settings_grid.addWidget(left, row_index, 0, 1, 2)
            settings_grid.addWidget(right, row_index, 2, 1, 2)
            row_index += 1
        settings_grid.addWidget(QtWidgets.QLabel("Autonomous music"), row_index, 0)
        settings_grid.addWidget(self.autonomy_combo, row_index, 1)
        settings_grid.addWidget(QtWidgets.QLabel("Music response mode"), row_index, 2)
        settings_grid.addWidget(self.response_mode_combo, row_index, 3)
        row_index += 1
        settings_grid.addWidget(QtWidgets.QLabel("Default volume"), row_index, 0)
        settings_grid.addWidget(self.default_volume_spin, row_index, 1)
        settings_grid.addWidget(QtWidgets.QLabel("Duck volume"), row_index, 2)
        settings_grid.addWidget(self.duck_volume_spin, row_index, 3)
        row_index += 1
        settings_grid.addWidget(QtWidgets.QLabel("Duck fade down"), row_index, 0)
        settings_grid.addWidget(self.duck_fade_down_spin, row_index, 1)
        settings_grid.addWidget(QtWidgets.QLabel("Duck fade up"), row_index, 2)
        settings_grid.addWidget(self.duck_fade_up_spin, row_index, 3)
        row_index += 1
        settings_grid.addWidget(QtWidgets.QLabel("Song-change comment cooldown"), row_index, 0)
        settings_grid.addWidget(self.comment_cooldown_spin, row_index, 1)
        settings_grid.addWidget(QtWidgets.QLabel("Default device"), row_index, 2)
        settings_grid.addWidget(self.default_device_combo, row_index, 3)
        row_index += 1
        settings_grid.addWidget(QtWidgets.QLabel("Hidden response cooldown"), row_index, 0)
        settings_grid.addWidget(self.hidden_response_cooldown_spin, row_index, 1)
        settings_grid.addWidget(QtWidgets.QLabel("User change lockout"), row_index, 2)
        settings_grid.addWidget(self.user_change_cooldown_spin, row_index, 3)
        row_index += 1
        settings_grid.addWidget(QtWidgets.QLabel("Coding mode search"), row_index, 0)
        settings_grid.addWidget(self.coding_query_edit, row_index, 1, 1, 3)
        settings_grid.setColumnStretch(3, 1)
        settings_layout.addLayout(settings_grid)
        card_layout.addWidget(settings_group)

        now_group, now_layout = self._section_group("Now Playing")
        self.current_track_label = QtWidgets.QLabel("Current track: not checked yet.")
        self.current_track_label.setObjectName("spotify_sense_current_track")
        self.current_track_label.setWordWrap(True)
        self.current_track_label.setStyleSheet("color: #cbd5e1;")
        self.album_art_label = QtWidgets.QLabel("No cover")
        self.album_art_label.setObjectName("spotify_sense_album_art")
        self.album_art_label.setFixedSize(96, 96)
        self.album_art_label.setAlignment(QtCore.Qt.AlignCenter)
        self.album_art_label.setToolTip("Current Spotify album or single cover. Controlled by the Album art thumbnail toggle.")
        self.album_art_label.setStyleSheet(
            "QLabel#spotify_sense_album_art {"
            "  color: #64748b;"
            "  background: rgba(2, 6, 23, 0.55);"
            "  border: 1px solid rgba(96, 165, 250, 0.34);"
            "  border-radius: 8px;"
            "}"
        )
        now_row = QtWidgets.QHBoxLayout()
        now_row.setContentsMargins(0, 0, 0, 0)
        now_row.setSpacing(10)
        now_row.addWidget(self.album_art_label, 0, QtCore.Qt.AlignTop)
        now_row.addWidget(self.current_track_label, 1)
        now_layout.addLayout(now_row)

        test_buttons = QtWidgets.QHBoxLayout()
        test_buttons.setContentsMargins(0, 0, 0, 0)
        test_buttons.setSpacing(8)
        for label, handler in (
            ("Current Track", self._on_current_track),
            ("Play / Pause", self._on_play_pause),
            ("Next", self._on_next),
            ("Volume 30%", self._on_volume_30),
        ):
            button = QtWidgets.QPushButton(label)
            button.setToolTip(
                {
                    "Current Track": "Read current Spotify playback metadata.",
                    "Play / Pause": "Toggle playback on the selected or active Spotify device.",
                    "Next": "Skip to the next Spotify track.",
                    "Volume 30%": "Set Spotify volume to 30 percent on the selected or active device.",
                }.get(label, "")
            )
            button.clicked.connect(handler)
        test_buttons.addWidget(button)
        test_buttons.addStretch(1)
        now_layout.addLayout(test_buttons)
        card_layout.addWidget(now_group)

        test_group, test_layout = self._section_group("Command Preview")
        intent_row = QtWidgets.QHBoxLayout()
        intent_row.setContentsMargins(0, 0, 0, 0)
        intent_row.setSpacing(8)
        self.intent_edit = QtWidgets.QLineEdit()
        self.intent_edit.setObjectName("spotify_sense_intent_test")
        self.intent_edit.setPlaceholderText("Try: play relaxing focus music, skip this, what song is this?")
        self.intent_edit.setToolTip("Type a music command to see which Spotify tool the addon would choose.")
        route_button = QtWidgets.QPushButton("Preview Intent")
        route_button.setToolTip("Preview the safe intent route without changing playback.")
        route_button.clicked.connect(self._on_preview_intent)
        log_button = QtWidgets.QPushButton("Open Debug Log")
        log_button.setToolTip("Open the addon-local Spotify Sense debug log file.")
        log_button.clicked.connect(self._on_open_debug_log)
        intent_row.addWidget(self.intent_edit, 1)
        intent_row.addWidget(route_button)
        intent_row.addWidget(log_button)
        test_layout.addLayout(intent_row)
        card_layout.addWidget(test_group)

        card_layout.addWidget(self._build_hidden_sensory_group())

        layout.addWidget(card)
        layout.addStretch(1)
        scroll.setWidget(content)
        self._widgets.append(scroll)
        self._refresh_connection_status()
        self._on_refresh_devices()
        return scroll

    def _runtime_config_service(self):
        return self.context.get_service("qt.runtime_config") if getattr(self, "context", None) is not None else None

    def _debug_log_path(self) -> Path:
        storage = getattr(self.context, "storage", None)
        if storage is not None:
            try:
                return Path(storage.resolve("spotify_sense_debug.log"))
            except Exception:
                pass
        return Path.cwd() / "runtime" / "spotify_sense_debug.log"

    def _redact_debug_payload(self, value: Any) -> Any:
        if isinstance(value, dict):
            redacted = {}
            for key, item in value.items():
                key_text = str(key or "")
                if any(token in key_text.lower() for token in ("token", "secret", "authorization", "client_id", "refresh")):
                    redacted[key_text] = "[redacted]"
                else:
                    redacted[key_text] = self._redact_debug_payload(item)
            return redacted
        if isinstance(value, list):
            return [self._redact_debug_payload(item) for item in value[:25]]
        return value

    def _debug_log(self, message: str, payload: Any = None):
        if not bool(self.settings.data.get("debug_logging_enabled", False)):
            return
        try:
            path = self._debug_log_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            line = f"[{timestamp}] {str(message or '').strip()}"
            if payload is not None:
                line += " " + json.dumps(self._redact_debug_payload(payload), ensure_ascii=True, sort_keys=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except Exception:
            pass

    def _on_open_debug_log(self):
        path = self._debug_log_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text("Spotify Sense debug log.\nEnable Debug log to record route/playback/duck diagnostics.\n", encoding="utf-8")
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path.resolve())))
            self._set_status(f"Opened Spotify Sense debug log: {path}")
        except Exception as exc:
            self._set_status(f"Could not open Spotify Sense debug log: {exc}")

    def _runtime_config_snapshot(self) -> dict[str, Any]:
        service = self._runtime_config_service()
        if service is None:
            return {}
        try:
            return dict(service.snapshot() or {})
        except Exception:
            return {}

    def _source_guidance_map(self) -> dict[str, str]:
        value = self._runtime_config_snapshot().get("sensory_pingpong_source_prompts", {})
        if not isinstance(value, dict):
            return {}
        return {str(key or "").strip().lower(): str(item or "") for key, item in value.items() if str(key or "").strip()}

    def _current_source_guidance(self) -> str:
        return str(self._source_guidance_map().get(SENSORY_PROVIDER_ID, "") or DEFAULT_SPOTIFY_SOURCE_GUIDANCE).strip()

    def _save_source_guidance(self):
        editor = getattr(self, "source_guidance_edit", None)
        text = str(editor.toPlainText() if editor is not None else "").strip() or DEFAULT_SPOTIFY_SOURCE_GUIDANCE
        service = self._runtime_config_service()
        if service is None:
            self._set_status("Runtime config service is unavailable; Spotify source guidance was not saved.")
            return
        prompt_map = self._source_guidance_map()
        prompt_map[SENSORY_PROVIDER_ID] = text
        try:
            service.update("sensory_pingpong_source_prompts", prompt_map)
            shell = self.context.get_service("qt.shell") if getattr(self, "context", None) is not None else None
            if shell is not None:
                shell.notify_settings_changed()
            self._set_status("Spotify hidden sensory source guidance saved.")
        except Exception as exc:
            self._set_status(f"Could not save Spotify source guidance: {exc}")

    def _reset_source_guidance(self):
        editor = getattr(self, "source_guidance_edit", None)
        if editor is not None:
            editor.setPlainText(DEFAULT_SPOTIFY_SOURCE_GUIDANCE)
        self._save_source_guidance()

    def _build_hidden_sensory_group(self):
        group, layout = self._section_group("Hidden Sensory Source")
        note = QtWidgets.QLabel(
            "Spotify Sense is still available as a hidden sensory source, but its source guidance now lives here instead of a separate Vision source tab."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #9fb3c8;")
        layout.addWidget(note)

        self.source_guidance_edit = QtWidgets.QPlainTextEdit()
        self.source_guidance_edit.setObjectName("spotify_sense_source_guidance")
        self.source_guidance_edit.setMinimumHeight(90)
        self.source_guidance_edit.setPlainText(self._current_source_guidance())
        self.source_guidance_edit.setToolTip("Prompt fragment used when Spotify Sense contributes hidden sensory context.")
        layout.addWidget(self.source_guidance_edit)

        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        save_button = QtWidgets.QPushButton("Save Guidance")
        save_button.setToolTip("Save the Spotify Sense hidden sensory guidance into NC runtime settings.")
        save_button.clicked.connect(self._save_source_guidance)
        reset_button = QtWidgets.QPushButton("Use Recommended")
        reset_button.setToolTip("Restore the recommended Spotify Sense hidden sensory guidance.")
        reset_button.clicked.connect(self._reset_source_guidance)
        row.addWidget(save_button)
        row.addWidget(reset_button)
        row.addStretch(1)
        layout.addLayout(row)
        return group

    def _checkbox(self, label: str, key: str):
        checkbox = QtWidgets.QCheckBox(label)
        checkbox.setObjectName(f"spotify_sense_{key}")
        checkbox.setToolTip(SETTING_TOOLTIPS.get(str(key), ""))
        checkbox.setChecked(bool(self.settings.data.get(key, DEFAULT_SETTINGS.get(key, False))))
        checkbox.toggled.connect(lambda checked, setting_key=key: self._update_setting(setting_key, bool(checked)))
        self._controls[key] = checkbox
        return checkbox

    def _spinbox(self, key: str, minimum: int, maximum: int, *, suffix: str = "%"):
        spinbox = QtWidgets.QSpinBox()
        spinbox.setObjectName(f"spotify_sense_{key}")
        spinbox.setToolTip(SETTING_TOOLTIPS.get(str(key), ""))
        spinbox.setRange(int(minimum), int(maximum))
        spinbox.setSuffix(str(suffix or ""))
        spinbox.setValue(int(self.settings.data.get(key, DEFAULT_SETTINGS.get(key, minimum)) or minimum))
        spinbox.valueChanged.connect(lambda value, setting_key=key: self._update_setting(setting_key, int(value)))
        self._controls[key] = spinbox
        return spinbox

    def _set_combo_value(self, combo, value):
        target = str(value or "").strip()
        for index in range(combo.count()):
            if str(combo.itemData(index) or "").strip() == target:
                combo.setCurrentIndex(index)
                return

    def _on_text_settings_finished(self):
        self.settings.update(
            client_id=str(getattr(self, "client_id_edit", None).text() if getattr(self, "client_id_edit", None) is not None else self.settings.data.get("client_id") or "").strip(),
            redirect_uri=str(getattr(self, "redirect_uri_edit", None).text() if getattr(self, "redirect_uri_edit", None) is not None else self.settings.data.get("redirect_uri") or DEFAULT_SETTINGS["redirect_uri"]).strip() or DEFAULT_SETTINGS["redirect_uri"],
            coding_mode_query=str(getattr(self, "coding_query_edit", None).text() if getattr(self, "coding_query_edit", None) is not None else self.settings.data.get("coding_mode_query") or DEFAULT_SETTINGS["coding_mode_query"]).strip() or DEFAULT_SETTINGS["coding_mode_query"],
        )
        self._refresh_connection_status()

    def _on_save_settings(self):
        self._on_text_settings_finished()
        self._set_status("Settings saved.")

    def _update_setting(self, key: str, value: Any):
        self.settings.update(**{str(key): value})
        if str(key) in {"enabled", "song_change_monitor_enabled", "music_awareness_enabled", "include_paused_track_context", "music_response_mode"}:
            self._sync_monitor_timer()
            self._request_music_context_refresh(force=True)
        if str(key) == "album_art_thumbnail_enabled":
            if bool(value):
                self._request_album_art_for_payload(self._cached_music_context)
            else:
                self._clear_album_art()
        self._refresh_connection_status()

    def _refresh_connection_status(self):
        data = self.settings.data
        if not str(data.get("client_id") or "").strip():
            text = "Not configured. Add a Spotify Developer app Client ID, then connect."
        elif self.client.is_connected():
            account = str(data.get("account_display_name") or data.get("account_id") or "Spotify account")
            text = f"Connected as {account}. Spotify Sense is {'enabled' if data.get('enabled') else 'disabled'}."
        else:
            text = "Not connected. Use Login / Connect after saving the Client ID."
        self._set_status(text)

    def _on_connect(self):
        self._on_text_settings_finished()
        auth = self.client.build_authorization_url()
        if not auth.get("ok"):
            self._set_status(str(auth.get("error") or "Spotify authorization could not start."))
            return
        server_result = self._start_oauth_server()
        if not server_result.get("ok"):
            self._set_status(str(server_result.get("error") or "OAuth callback server could not start."))
            return
        try:
            webbrowser.open(str(auth.get("url") or ""))
        except Exception as exc:
            self._set_status(f"Open this URL in your browser: {auth.get('url')} ({exc})")
            return
        self._set_status("Spotify authorization opened in your browser. Approve access to finish connecting.")

    def _start_oauth_server(self) -> dict[str, Any]:
        parsed = urllib.parse.urlparse(str(self.settings.data.get("redirect_uri") or DEFAULT_SETTINGS["redirect_uri"]))
        host = parsed.hostname or "127.0.0.1"
        port = int(parsed.port or 80)
        path = parsed.path or "/spotify/callback"
        if parsed.scheme != "http" or host not in {"127.0.0.1", "localhost"}:
            return {"ok": False, "error": "Redirect URI must be a local http://127.0.0.1 or localhost callback."}

        old_server = self._oauth_server
        if old_server is not None:
            try:
                old_server.shutdown()
                old_server.server_close()
            except Exception:
                pass

        controller = self

        class CallbackHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - http.server method name
                request_path = urllib.parse.urlparse(self.path)
                if request_path.path != path:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"Spotify Sense callback path not found.")
                    return
                query = urllib.parse.parse_qs(request_path.query)
                payload = {key: values[0] if values else "" for key, values in query.items()}
                controller.oauth_callback_received.emit(payload)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h3>Spotify Sense connected.</h3>"
                    b"<p>You can return to NeuralCompanion.</p></body></html>"
                )
                threading.Thread(target=self.server.shutdown, daemon=True).start()

            def log_message(self, _format, *_args):
                return

        try:
            server = _OAuthHTTPServer((host, port), CallbackHandler)
        except Exception as exc:
            return {"ok": False, "error": f"Could not start local Spotify callback on {host}:{port}: {exc}"}
        self._oauth_server = server
        thread = threading.Thread(target=server.serve_forever, name="SpotifySenseOAuth", daemon=True)
        thread.start()
        return {"ok": True}

    @QtCore.Slot(dict)
    def _handle_oauth_callback(self, payload: dict[str, Any]):
        if payload.get("error"):
            self._set_status(f"Spotify authorization cancelled or rejected: {payload.get('error')}")
            return
        code = str(payload.get("code") or "")
        state = str(payload.get("state") or "")
        self._run_async("oauth", lambda: self.client.exchange_code(code, state))

    def _on_disconnect(self):
        self.settings.update(
            access_token="",
            refresh_token="",
            expires_at=0,
            scopes=[],
            account_display_name="",
            account_id="",
        )
        self._last_track_id = ""
        self._cached_music_context = {}
        self._cached_music_context_at = 0.0
        self._pending_track_change_context = None
        self._pending_direct_command_context = None
        self._last_hidden_response_snapshot_at = 0.0
        self._last_nc_music_change_at = 0.0
        self._last_user_music_change_at = 0.0
        self._refresh_connection_status()
        self._set_status("Disconnected from Spotify Sense. Local tokens were cleared.")

    def _on_refresh_devices(self):
        self._run_async("devices", self.client.get_devices)

    def _on_current_track(self):
        self._run_async("current_track", self.client.get_current_track)

    def _on_play_pause(self):
        def work():
            self._mark_user_music_change()
            state = self.client.get_playback_state()
            if not state.get("ok"):
                return state
            data = dict(state.get("data") or {})
            device_id = self._selected_device_id()
            if bool(data.get("is_playing")):
                return self.client.pause(device_id=device_id)
            return self.client.play(device_id=device_id)

        self._run_async("play_pause", work)

    def _on_next(self):
        def work():
            self._mark_user_music_change()
            return self.client.next(device_id=self._selected_device_id())

        self._run_async("next", work)

    def _on_volume_30(self):
        def work():
            self._mark_user_music_change()
            return self.client.set_volume(30, device_id=self._selected_device_id())

        self._run_async("volume", work)

    def _on_preview_intent(self):
        result = route_music_intent(self.intent_edit.text())
        if not result.get("matched"):
            self._set_status("No safe Spotify intent matched.")
            return
        tool = str(result.get("tool") or "")
        confidence = float(result.get("confidence") or 0.0)
        self._set_status(f"Matched {tool} with confidence {confidence:.2f}. Use LLM tools with confirmation to execute.")

    def _selected_device_id(self) -> str:
        combo = getattr(self, "default_device_combo", None)
        if combo is not None:
            return str(combo.currentData() or "").strip()
        return str(self.settings.data.get("default_device_id") or "").strip()

    def _run_async(self, kind: str, callback: Callable[[], dict[str, Any]]):
        def runner():
            try:
                result = callback()
                if not isinstance(result, dict):
                    result = {"ok": True, "data": result}
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            self.async_result_ready.emit(str(kind), result)

        threading.Thread(target=runner, name=f"SpotifySense-{kind}", daemon=True).start()

    @QtCore.Slot(str, dict)
    def _handle_async_result(self, kind: str, result: dict[str, Any]):
        if kind == "oauth":
            if result.get("ok"):
                profile = dict(result.get("profile") or {})
                self.settings.update(
                    account_display_name=str(profile.get("display_name") or profile.get("id") or ""),
                    account_id=str(profile.get("id") or ""),
                    enabled=True,
                )
                self._sync_control_values()
                self._refresh_connection_status()
                self._on_refresh_devices()
                self._sync_monitor_timer()
                self.context.logger.info("[SpotifySense] Spotify OAuth connection completed.")
            else:
                self._set_status(str(result.get("error") or "Spotify authorization failed."))
            return
        if kind == "devices":
            self._update_devices(result)
            return
        if kind == "music_context_refresh":
            self._context_refresh_in_flight = False
            self._update_current_track(result, from_monitor=True)
            return
        if kind == "album_art":
            self._update_album_art(result)
            return
        if kind in {"current_track", "track_monitor"}:
            self._update_current_track(result, from_monitor=(kind == "track_monitor"))
            return
        if result.get("ok"):
            self._set_status(f"Spotify action completed: {kind}.")
        else:
            self._set_status(str(result.get("error") or f"Spotify action failed: {kind}."))

    def _sync_control_values(self):
        for key, widget in list(self._controls.items()):
            value = self.settings.data.get(key, DEFAULT_SETTINGS.get(key))
            try:
                widget.blockSignals(True)
                if isinstance(widget, QtWidgets.QCheckBox):
                    widget.setChecked(bool(value))
                elif isinstance(widget, QtWidgets.QSpinBox):
                    widget.setValue(int(value or 0))
                elif isinstance(widget, QtWidgets.QComboBox):
                    self._set_combo_value(widget, value)
            finally:
                try:
                    widget.blockSignals(False)
                except Exception:
                    pass

    def _update_devices(self, result: dict[str, Any]):
        combo = getattr(self, "default_device_combo", None)
        if combo is None:
            return
        if not result.get("ok"):
            self._set_status(str(result.get("error") or "Could not refresh Spotify devices."))
            return
        devices = list(((result.get("data") or {}).get("devices") or []))
        target = str(self.settings.data.get("default_device_id") or "")
        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem("Active device / default", "")
            for device in devices:
                device_id = str(device.get("id") or "").strip()
                if not device_id:
                    continue
                label = str(device.get("name") or "Spotify device")
                if device.get("is_active"):
                    label = f"{label} (active)"
                combo.addItem(label, device_id)
            self._set_combo_value(combo, target)
        finally:
            combo.blockSignals(False)
        self._set_status(f"Spotify devices refreshed: {len(devices)} found.")

    def _clear_album_art(self):
        label = getattr(self, "album_art_label", None)
        if label is not None:
            label.clear()
            label.setText("No cover")
        self._last_album_art_url = ""

    def _request_album_art_for_payload(self, payload: dict[str, Any] | None):
        if not bool(self.settings.data.get("album_art_thumbnail_enabled", True)):
            self._clear_album_art()
            return
        url = str((payload or {}).get("album_art_url") or "").strip()
        if not url:
            self._clear_album_art()
            return
        if url == self._last_album_art_url:
            return
        self._last_album_art_url = url
        self._run_async("album_art", lambda target_url=url: self._fetch_album_art(target_url))

    def _fetch_album_art(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(str(url), headers={"User-Agent": "NeuralCompanion-SpotifySense/1.0"})
        with urllib.request.urlopen(request, timeout=8) as response:
            data = response.read(1024 * 1024)
        return {"ok": True, "url": str(url), "image_bytes": data}

    def _update_album_art(self, result: dict[str, Any]):
        if not bool(self.settings.data.get("album_art_thumbnail_enabled", True)):
            self._clear_album_art()
            return
        label = getattr(self, "album_art_label", None)
        if label is None:
            return
        if not result.get("ok"):
            label.clear()
            label.setText("No cover")
            return
        raw = result.get("image_bytes")
        if not isinstance(raw, (bytes, bytearray)) or not raw:
            label.clear()
            label.setText("No cover")
            return
        pixmap = QtGui.QPixmap()
        if not pixmap.loadFromData(bytes(raw)):
            label.clear()
            label.setText("No cover")
            return
        label.setText("")
        label.setPixmap(
            pixmap.scaled(
                label.size(),
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation,
            )
        )

    def _update_current_track(self, result: dict[str, Any], *, from_monitor: bool = False):
        if not result.get("ok"):
            if not from_monitor:
                self._set_status(str(result.get("error") or "Could not read current Spotify track."))
            return
        compact = self._compact_track(result)
        if not compact.get("id"):
            self._cached_music_context = {}
            self._cached_music_context_at = time.time()
            self._clear_album_art()
            if not from_monitor:
                self.current_track_label.setText("Current track: nothing is currently playing.")
            return
        self._cache_music_context(compact)
        self._request_album_art_for_payload(compact)
        label = self._track_sentence(compact)
        if getattr(self, "current_track_label", None) is not None:
            self.current_track_label.setText(label)
        self._publish_music_mood(compact)
        if from_monitor:
            self._handle_track_monitor_change(compact)
        else:
            self._set_status(label)

    def _handle_track_monitor_change(self, track: dict[str, Any]):
        track_id = str(track.get("id") or "")
        if not track_id or track_id == self._last_track_id:
            return
        self._last_track_id = track_id
        now = time.time()
        self._mark_external_track_change(now)
        payload = {"track": dict(track), "mood": infer_music_mood(track), "changed_at": now}
        try:
            self.context.events.publish("spotify_track_changed", payload)
        except Exception:
            pass
        cooldown = int(self.settings.data.get("proactive_comment_cooldown_seconds", 120) or 120)
        if bool(self.settings.data.get("comment_on_song_changes", False)) and now - self._last_track_comment_at >= cooldown:
            self._last_track_comment_at = now
            self._pending_track_change_context = {
                "changed_at": now,
                "track": self._music_context_payload_from_track(track),
                "commentary": self._commentary_for_track(track),
            }
            self._set_status(self._commentary_for_track(track))

    def _mark_user_music_change(self):
        self._last_user_music_change_at = time.time()

    def _mark_external_track_change(self, now: float | None = None):
        changed_at = float(now if now is not None else time.time())
        # Spotify does not label who changed playback. If NC did not trigger a
        # music command recently, treat the track change as user/external input.
        if changed_at - float(self._last_nc_music_change_at or 0.0) > 12.0:
            self._last_user_music_change_at = changed_at

    def _mark_nc_music_change(self):
        self._last_nc_music_change_at = time.time()

    def _user_music_change_remaining_seconds(self) -> int:
        cooldown = int(self.settings.data.get("user_music_change_cooldown_seconds", 120) or 0)
        if cooldown <= 0 or self._last_user_music_change_at <= 0:
            return 0
        elapsed = time.time() - float(self._last_user_music_change_at or 0.0)
        return max(0, int(round(cooldown - elapsed)))

    def _best_album_art_url(self, images: list[Any]) -> str:
        candidates = []
        for image in images:
            if not isinstance(image, dict):
                continue
            url = str(image.get("url") or "").strip()
            if not url:
                continue
            width = int(image.get("width") or 0)
            height = int(image.get("height") or 0)
            size = max(width, height)
            candidates.append((abs(size - 128), size, url))
        if not candidates:
            return ""
        candidates.sort(key=lambda item: (item[0], item[1]))
        return candidates[0][2]

    def _compact_track(self, result: dict[str, Any]) -> dict[str, Any]:
        data = dict(result.get("data") or {})
        item = dict(data.get("item") or data.get("track") or {})
        artists = item.get("artists") or []
        artist_names = []
        for artist in artists:
            if isinstance(artist, dict):
                name = str(artist.get("name") or "").strip()
                if name:
                    artist_names.append(name)
        album = item.get("album") or {}
        album_images = list(album.get("images") or []) if isinstance(album, dict) else []
        album_art_url = self._best_album_art_url(album_images)
        device = (data.get("device") or {}) if isinstance(data.get("device"), dict) else {}
        return {
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or ""),
            "artists": artist_names,
            "album": str(album.get("name") or ""),
            "album_art_url": album_art_url,
            "uri": str(item.get("uri") or ""),
            "is_playing": bool(data.get("is_playing", False)),
            "progress_ms": int(data.get("progress_ms") or 0),
            "duration_ms": int(item.get("duration_ms") or 0),
            "device": str(device.get("name") or ""),
            "context": str((data.get("context") or {}).get("uri") or ""),
        }

    def _cache_music_context(self, track: dict[str, Any]):
        payload = self._music_context_payload_from_track(track)
        self._cached_music_context = dict(payload)
        self._cached_music_context_at = time.time()

    def _music_context_payload_from_track(self, track: dict[str, Any]) -> dict[str, Any]:
        compact = dict(track or {})
        return {
            "source": SENSORY_PROVIDER_ID,
            "is_playing": bool(compact.get("is_playing", False)),
            "track": str(compact.get("name") or ""),
            "artists": [str(item) for item in list(compact.get("artists") or []) if str(item or "").strip()],
            "album": str(compact.get("album") or ""),
            "album_art_url": str(compact.get("album_art_url") or ""),
            "progress_ms": int(compact.get("progress_ms") or 0),
            "duration_ms": int(compact.get("duration_ms") or 0),
            "device": str(compact.get("device") or ""),
            "context": str(compact.get("context") or ""),
            "uri": str(compact.get("uri") or ""),
            "mood_hint": infer_music_mood(compact),
            "metadata_only": True,
        }

    def _music_context_enabled(self) -> bool:
        if not bool(self.settings.data.get("enabled", False)):
            return False
        if not bool(self.settings.data.get("music_awareness_enabled", True)):
            return False
        if str(self.settings.data.get("music_response_mode", "subtle") or "subtle").strip().lower() == "off":
            return False
        return self.client.is_connected()

    def _current_music_context_payload(self) -> dict[str, Any]:
        if not self._music_context_enabled():
            return {}
        payload = dict(self._cached_music_context or {})
        if not payload.get("track"):
            self._request_music_context_refresh(force=False)
            return {}
        max_age = int(self.settings.data.get("music_context_cache_seconds", 45) or 45)
        age = time.time() - float(self._cached_music_context_at or 0.0)
        if age > max_age:
            self._request_music_context_refresh(force=False)
        if age > max(max_age * 4, 90):
            return {}
        if not bool(payload.get("is_playing")) and not bool(self.settings.data.get("include_paused_track_context", False)):
            return {}
        payload["cache_age_seconds"] = max(0, int(age))
        return payload

    def _request_music_context_refresh(self, *, force: bool = False):
        if not self.client.is_connected():
            return
        now = time.time()
        if self._context_refresh_in_flight:
            return
        if not force and now - self._last_context_refresh_request_at < 5.0:
            return
        self._last_context_refresh_request_at = now
        self._context_refresh_in_flight = True
        self._run_async("music_context_refresh", self.client.get_current_track)

    def _music_mode_instruction(self) -> str:
        mode = str(self.settings.data.get("music_response_mode", "subtle") or "subtle").strip().lower()
        if mode == "companion":
            return "Use the music as a companion mood signal. Briefly acknowledge it when it genuinely fits the conversation."
        if mode == "dj_critic":
            return "You may use a playful DJ/music-critic flavor when the user is talking about music, but keep it concise."
        if mode == "story_soundtrack":
            return "Use the music as soundtrack context for story, roleplay, scene pacing, and atmosphere when relevant."
        return "Use the music quietly as ambient mood context. Do not mention it unless it helps the current reply."

    def _build_music_context_text(self, payload: dict[str, Any], *, consume_pending: bool = False) -> str:
        if not payload:
            return ""
        artists = ", ".join(payload.get("artists") or []) or "Unknown artist"
        progress = int(payload.get("progress_ms") or 0)
        duration = int(payload.get("duration_ms") or 0)
        progress_text = f"{progress}/{duration} ms" if duration > 0 else f"{progress} ms"
        mention_rule = (
            "Only mention the music when it is relevant to the user's message or the current creative task."
            if bool(self.settings.data.get("music_awareness_relevance_only", True))
            else "You may naturally mention the music, but avoid repeating it every turn."
        )
        lines = [
            "Hidden Spotify music awareness only, not a user request.",
            "Spotify metadata is available; do not claim to hear or analyze raw audio.",
            f"Now playing: {payload.get('track') or 'Unknown track'} by {artists}.",
            f"Album: {payload.get('album') or 'Unknown album'}.",
            f"Playback: {'playing' if payload.get('is_playing') else 'paused'}; progress: {progress_text}.",
            f"Device: {payload.get('device') or 'unknown'}; context: {payload.get('context') or 'none'}.",
            f"Mood hint from metadata: {payload.get('mood_hint') or 'neutral'}.",
            f"Music response mode: {self.settings.data.get('music_response_mode', 'subtle')}. {self._music_mode_instruction()}",
            mention_rule,
        ]
        pending = dict(self._pending_track_change_context or {})
        if pending and bool(self.settings.data.get("comment_on_song_changes", False)):
            pending_track = dict(pending.get("track") or {})
            lines.append(
                "Recent Spotify track change: "
                f"{pending_track.get('track') or payload.get('track') or 'Unknown track'}; "
                f"optional short acknowledgement: {pending.get('commentary') or self._commentary_for_track({'name': payload.get('track'), 'artists': payload.get('artists')})}"
            )
            if consume_pending:
                self._pending_track_change_context = None
        return "\n".join(lines)

    def collect_chat_context(self, _payload: dict[str, Any] | None = None):
        payload = self._current_music_context_payload()
        direct_command_text = self._consume_direct_command_context_text()
        if not payload and not direct_command_text:
            return None
        context_text = self._build_music_context_text(payload, consume_pending=True) if payload else ""
        if direct_command_text:
            context_text = "\n".join(item for item in (context_text, direct_command_text) if item)
        if not context_text:
            return None
        return {
            "context": context_text,
            "debug": {
                "matches": 1,
                "sources": [SENSORY_PROVIDER_ID],
                "mood": payload.get("mood_hint", "neutral") if payload else "neutral",
                "track": payload.get("track", "") if payload else "",
            },
        }

    def _consume_direct_command_context_text(self) -> str:
        pending = dict(self._pending_direct_command_context or {})
        if not pending:
            return ""
        age = time.time() - float(pending.get("created_at", 0.0) or 0.0)
        self._pending_direct_command_context = None
        if age > 30.0:
            return ""
        lines = [
            "Fresh Spotify command result, directly requested by the user.",
            f"User command: {pending.get('user_text') or 'music command'}.",
            "The Spotify playback command has already been executed before this reply. Do not ask for confirmation or say you cannot control Spotify.",
            f"Command result: {pending.get('response_text') or 'Spotify playback was updated.'}",
            "Briefly mention the current or selected track/playlist when it is relevant.",
        ]
        if bool(pending.get("comment_requested", False)):
            lines.append("The user explicitly asked for a comment about the music; give a brief, natural reaction to the current track.")
        return "\n".join(lines)

    def capture_sensory_snapshot(self, _capture_context=None):
        payload = self._current_music_context_payload()
        if not payload:
            return None
        pending = dict(self._pending_track_change_context or {})
        now = time.time()
        hidden_cooldown = int(self.settings.data.get("hidden_response_cooldown_seconds", 300) or 300)
        hidden_ready = now - float(self._last_hidden_response_snapshot_at or 0.0) >= hidden_cooldown
        can_offer_hidden_response = (
            bool(self.settings.data.get("comment_on_song_changes", False))
            and bool(pending)
            and hidden_ready
        )
        if not can_offer_hidden_response:
            # Normal chat still receives Spotify context through collect_chat_context().
            # The hidden PING/PONG loop should only get Spotify when a fresh,
            # cooldown-approved music comment is available.
            return None
        self._last_hidden_response_snapshot_at = now
        return {
            "source": SENSORY_PROVIDER_ID,
            "captured_at": now,
            "content_text": (
                self._build_music_context_text(payload, consume_pending=False)
                + "\nHidden Spotify response is allowed now because a new track-change context is pending and the hidden response cooldown has elapsed."
            ),
            "metadata": {
                "kind": "music",
                "provider": "spotify",
                "track": str(payload.get("track") or ""),
                "artists": list(payload.get("artists") or []),
                "album": str(payload.get("album") or ""),
                "is_playing": bool(payload.get("is_playing", False)),
                "mood_hint": str(payload.get("mood_hint") or "neutral"),
                "metadata_only": True,
                "hidden_response_allowed": True,
                "hidden_response_cooldown_seconds": hidden_cooldown,
            },
        }

    def _track_sentence(self, track: dict[str, Any]) -> str:
        artists = ", ".join(track.get("artists") or []) or "Unknown artist"
        mood = infer_music_mood(track)
        return f"Now playing: {track.get('name') or 'Unknown track'} by {artists}. Mood hint: {mood}."

    def _enrich_play_result(self, result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(result, dict) or not result.get("ok"):
            return result
        enriched = dict(result)
        selected = dict(enriched.get("selected_item") or {})
        current_track = {}
        try:
            time.sleep(0.35)
            current = self.client.get_current_track()
            if current.get("ok"):
                current_track = self._compact_track(current)
        except Exception as exc:
            self._debug_log("spotify_current_after_play_failed", {"error": str(exc), "selected_item": selected})
            current_track = {}
        if current_track.get("name"):
            enriched["current_track"] = dict(current_track)
            self._cache_music_context(current_track)
        elif selected:
            fallback_track = self._track_payload_from_selected_item(selected)
            if fallback_track.get("name"):
                self._cache_music_context(fallback_track)
        return enriched

    def _enrich_playback_change_result(self, result: dict[str, Any], *, fetch_current: bool = False) -> dict[str, Any]:
        if not isinstance(result, dict) or not result.get("ok") or not fetch_current:
            return result
        enriched = dict(result)
        try:
            time.sleep(0.25)
            current = self.client.get_current_track()
            if current.get("ok"):
                current_track = self._compact_track(current)
                if current_track.get("name"):
                    enriched["current_track"] = current_track
                    self._cache_music_context(current_track)
        except Exception:
            pass
        return enriched

    def _track_payload_from_selected_item(self, selected: dict[str, Any]) -> dict[str, Any]:
        payload = dict(selected or {})
        return {
            "id": str(payload.get("id") or ""),
            "name": str(payload.get("name") or ""),
            "artists": [str(item) for item in list(payload.get("artists") or []) if str(item or "").strip()],
            "album": str(payload.get("album") or ""),
            "uri": str(payload.get("uri") or ""),
            "is_playing": True,
            "progress_ms": 0,
            "duration_ms": 0,
            "device": "",
            "context": str(payload.get("uri") or ""),
        }

    def _selected_item_sentence(self, selected: dict[str, Any]) -> str:
        payload = dict(selected or {})
        name = str(payload.get("name") or "").strip()
        item_type = str(payload.get("type") or "").strip().lower()
        artists = ", ".join(payload.get("artists") or [])
        if item_type == "track" and name:
            return f"selected track: {name}{f' by {artists}' if artists else ''}"
        if item_type == "playlist" and name:
            owner = str(payload.get("owner") or "").strip()
            return f"selected playlist: {name}{f' by {owner}' if owner else ''}"
        return ""

    def _commentary_for_track(self, track: dict[str, Any]) -> str:
        artists = ", ".join(track.get("artists") or []) or "Unknown artist"
        mood = infer_music_mood(track)
        return f"Song changed: {track.get('name') or 'Unknown track'} by {artists}. This fits a {mood} mood."

    def _publish_music_mood(self, track: dict[str, Any]):
        try:
            self.context.events.publish(
                "spotify_music_mood_changed",
                {"mood": infer_music_mood(track), "track": dict(track), "source": "spotify_sense"},
            )
        except Exception:
            pass

    def _sync_monitor_timer(self):
        should_run = (
            self.client.is_connected()
            and bool(self.settings.data.get("enabled", False))
            and (
                bool(self.settings.data.get("song_change_monitor_enabled", False))
                or bool(self.settings.data.get("music_awareness_enabled", True))
            )
        )
        if should_run and not self._track_monitor_timer.isActive():
            self._track_monitor_timer.start()
            self._request_music_context_refresh(force=True)
        elif not should_run and self._track_monitor_timer.isActive():
            self._track_monitor_timer.stop()

    def _poll_track_change(self):
        if (
            not self.client.is_connected()
            or not bool(self.settings.data.get("enabled", False))
            or not (
                bool(self.settings.data.get("song_change_monitor_enabled", False))
                or bool(self.settings.data.get("music_awareness_enabled", True))
            )
        ):
            self._sync_monitor_timer()
            return
        self._run_async("track_monitor", self.client.get_current_track)

    def invoke_capability(self, capability: str, payload: dict[str, Any] | None = None):
        capability_name = str(capability or "").strip().lower()
        if capability_name == "tts.duck.start":
            capability_name = "spotify.duck.start"
        elif capability_name == "tts.duck.end":
            capability_name = "spotify.duck.end"
        if capability_name == "chat_context.collect":
            return self.collect_chat_context(dict(payload or {}))
        if capability_name == "chat.user_text_command":
            return self._handle_user_text_command(dict(payload or {}), report_misses=False)
        if capability_name == "spotify.handle_user_text":
            return self._handle_user_text_command(dict(payload or {}), report_misses=True)
        if capability_name in {"spotify.music_context", "spotify.context"}:
            context_payload = self._current_music_context_payload()
            return {"ok": bool(context_payload), "tool": capability_name, "context": context_payload}
        if capability_name not in TOOL_NAMES:
            return None
        request = dict(payload or {})
        guard = self._guard_capability(capability_name, request)
        if guard is not None:
            return guard
        try:
            result = self._invoke_spotify_tool(capability_name, request)
            if (
                capability_name in CONTROL_TOOLS
                and capability_name not in {"spotify.duck.start", "spotify.duck.end"}
                and isinstance(result, dict)
                and bool(result.get("ok"))
            ):
                self._mark_nc_music_change()
            return result
        except Exception as exc:
            self.context.logger.exception("[SpotifySense] Capability failed: %s", capability_name)
            return {"ok": False, "tool": capability_name, "error": str(exc)}

    def _handle_user_text_command(self, payload: dict[str, Any], *, report_misses: bool = False):
        role = str(payload.get("role") or "user").strip().lower()
        if role and role != "user":
            return {"ok": True, "handled": False, "reason": "role_not_user"} if report_misses else None
        text = str(payload.get("text") or payload.get("utterance") or "").strip()
        routed = route_music_intent(text)
        self._debug_log("user_text_route", {"text": text, "route": routed})
        if not routed.get("matched"):
            return {"ok": True, "handled": False, "route": routed} if report_misses else None
        confidence = float(routed.get("confidence") or 0.0)
        if confidence < 0.72:
            return {"ok": True, "handled": False, "route": routed, "reason": "low_confidence"} if report_misses else None
        tool = str(routed.get("tool") or "").strip()
        if not tool:
            return {"ok": True, "handled": False, "route": routed, "reason": "no_tool"} if report_misses else None
        request = dict(routed.get("args") or {})
        request.update({
            "confirmed": True,
            "direct_user_request": True,
        })
        if payload.get("device_id"):
            request["device_id"] = payload.get("device_id")
        result = self.invoke_capability(tool, request)
        self._debug_log("user_text_command_result", {"tool": tool, "request": request, "result": result})
        response_text = self._user_command_response_text(tool, result, routed)
        wants_comment = bool(request.get("comment", False))
        use_llm_response = bool(
            isinstance(result, dict)
            and result.get("ok")
            and (
                tool == "spotify.play_search"
                or (
                    wants_comment
                    and tool in {"spotify.current_track", "spotify.next", "spotify.previous", "spotify.resume"}
                )
            )
        )
        if use_llm_response:
            self._pending_direct_command_context = {
                "created_at": time.time(),
                "user_text": text,
                "tool": tool,
                "response_text": response_text,
                "comment_requested": wants_comment,
            }
        return {
            "ok": bool(isinstance(result, dict) and result.get("ok")),
            "handled": True,
            "tool": tool,
            "route": routed,
            "result": result,
            "response_text": response_text,
            "use_llm_response": use_llm_response,
        }

    def _user_command_response_text(self, tool: str, result: Any, routed: dict[str, Any]) -> str:
        data = dict(result or {}) if isinstance(result, dict) else {}
        if not data.get("ok"):
            code = str(data.get("error_code") or "").strip()
            if code == "disabled":
                return "Spotify Sense is disabled. Enable Spotify Sense in the addon tab first."
            if code == "llm_control_disabled":
                return "Spotify playback control is off. Enable Allow LLM Spotify control in Spotify Sense, then try again."
            if code == "user_music_change_cooldown":
                remaining = int(data.get("remaining_seconds") or 0)
                return f"Spotify was changed manually or externally just now, so I will wait {remaining}s before changing it."
            if data.get("requires_confirmation"):
                return "Spotify playback changes require confirmation before I can do that."
            error_text = str(data.get("error") or "Spotify did not accept the command.").strip()
            return f"Spotify command matched, but I could not complete it: {error_text}"
        if tool == "spotify.current_track":
            track = dict(data.get("track") or {})
            if track:
                return self._track_sentence(track)
            return "Spotify is connected, but I could not find a current track."
        if tool == "spotify.pause":
            return "Paused Spotify."
        if tool == "spotify.resume":
            current_track = dict(data.get("current_track") or {})
            if current_track.get("name"):
                return "Resumed Spotify playback. " + self._track_sentence(current_track)
            return "Resumed Spotify playback."
        if tool == "spotify.next":
            current_track = dict(data.get("current_track") or {})
            if current_track.get("name"):
                return "Skipped to the next Spotify track. " + self._track_sentence(current_track)
            return "Skipped to the next Spotify track."
        if tool == "spotify.previous":
            current_track = dict(data.get("current_track") or {})
            if current_track.get("name"):
                return "Went back to the previous Spotify track. " + self._track_sentence(current_track)
            return "Went back to the previous Spotify track."
        if tool == "spotify.volume":
            return "Updated Spotify volume."
        if tool == "spotify.play_search":
            route_args = dict(routed.get("args") or {})
            query = str(route_args.get("display_query") or route_args.get("query") or "").strip()
            current_track = dict(data.get("current_track") or {})
            if current_track.get("name"):
                return "Started Spotify. " + self._track_sentence(current_track)
            selected_text = self._selected_item_sentence(dict(data.get("selected_item") or {}))
            if selected_text:
                return f"Started Spotify for {query}; {selected_text}." if query else f"Started Spotify; {selected_text}."
            return f"Started Spotify playback for {query}." if query else "Started Spotify playback."
        if tool == "spotify.play_playlist":
            return "Started the requested Spotify playlist."
        return "Spotify command completed."

    def _guard_capability(self, capability_name: str, payload: dict[str, Any]):
        direct_user_request = bool(payload.get("direct_user_request", False))
        if not bool(self.settings.data.get("enabled", False)) and not direct_user_request:
            return {"ok": False, "tool": capability_name, "error_code": "disabled", "error": "Spotify Sense is disabled."}
        if capability_name in CONTROL_TOOLS:
            if (
                capability_name not in {"spotify.duck.start", "spotify.duck.end"}
                and not direct_user_request
                and not bool(self.settings.data.get("allow_llm_control", False))
            ):
                return {"ok": False, "tool": capability_name, "error_code": "llm_control_disabled", "error": "LLM Spotify control is disabled."}
            if (
                capability_name not in {"spotify.duck.start", "spotify.duck.end"}
                and not direct_user_request
                and not bool(payload.get("override_user_change_cooldown", False))
            ):
                remaining = self._user_music_change_remaining_seconds()
                if remaining > 0:
                    return {
                        "ok": False,
                        "tool": capability_name,
                        "error_code": "user_music_change_cooldown",
                        "remaining_seconds": remaining,
                        "error": (
                            "Spotify was changed externally/user-side recently. "
                            f"NC will wait {remaining}s before changing playback."
                        ),
                    }
            if capability_name == "spotify.add_to_queue" and not bool(self.settings.data.get("allow_queue_changes", False)):
                return {"ok": False, "tool": capability_name, "error_code": "queue_disabled", "error": "Queue changes are disabled."}
            if capability_name == "spotify.play_playlist" and not bool(self.settings.data.get("allow_playlist_changes", False)):
                return {"ok": False, "tool": capability_name, "error_code": "playlist_disabled", "error": "Playlist changes are disabled."}
            if (
                bool(self.settings.data.get("require_confirmation", True))
                and not bool(payload.get("confirmed", False))
                and not direct_user_request
                and capability_name not in {"spotify.duck.start", "spotify.duck.end"}
            ):
                return {
                    "ok": False,
                    "tool": capability_name,
                    "requires_confirmation": True,
                    "error": "Spotify playback changes require confirmation.",
                }
        return None

    def _invoke_spotify_tool(self, capability_name: str, payload: dict[str, Any]):
        device_id = str(payload.get("device_id") or self.settings.data.get("default_device_id") or "").strip() or None
        if capability_name == "spotify.current_track":
            result = self.client.get_current_track()
            if result.get("ok"):
                return {"ok": True, "tool": capability_name, "track": self._compact_track(result), "raw": result.get("data") or {}}
            return result
        if capability_name == "spotify.devices":
            return self.client.get_devices()
        if capability_name == "spotify.commentary":
            result = self.client.get_current_track()
            if not result.get("ok"):
                return result
            track = self._compact_track(result)
            return {"ok": True, "tool": capability_name, "commentary": self._commentary_for_track(track), "track": track}
        if capability_name == "spotify.route_intent":
            routed = route_music_intent(str(payload.get("text") or payload.get("utterance") or ""))
            if not routed.get("matched") or not bool(payload.get("execute", False)):
                return {"ok": True, "tool": capability_name, "route": routed, "executed": False}
            next_payload = dict(routed.get("args") or {})
            next_payload.update({key: value for key, value in payload.items() if key in {"confirmed", "device_id"}})
            return self.invoke_capability(str(routed.get("tool") or ""), next_payload)
        if capability_name == "spotify.play_search":
            query = str(payload.get("query") or "").strip()
            if not query:
                return {"ok": False, "tool": capability_name, "error_code": "invalid_query", "error": "query is required."}
            preferred_type = str(payload.get("preferred_type") or "auto").strip().lower()
            self._debug_log("spotify_play_search_start", {"query": query, "preferred_type": preferred_type, "device_id": device_id})
            result = self._enrich_play_result(self.client.play(query=query, device_id=device_id, preferred_type=preferred_type))
            self._debug_log("spotify_play_search_done", {"query": query, "preferred_type": preferred_type, "result": result})
            return result
        if capability_name == "spotify.play_playlist":
            uri = str(payload.get("context_uri") or payload.get("playlist_uri") or "").strip()
            if not uri:
                return {"ok": False, "tool": capability_name, "error_code": "invalid_playlist", "error": "playlist_uri or context_uri is required."}
            return self.client.play(context_uri=uri, device_id=device_id)
        if capability_name == "spotify.pause":
            return self.client.pause(device_id=device_id)
        if capability_name == "spotify.resume":
            return self._enrich_playback_change_result(
                self.client.play(device_id=device_id),
                fetch_current=bool(payload.get("comment", False)),
            )
        if capability_name == "spotify.next":
            return self._enrich_playback_change_result(
                self.client.next(device_id=device_id),
                fetch_current=bool(payload.get("comment", False)),
            )
        if capability_name == "spotify.previous":
            return self._enrich_playback_change_result(
                self.client.previous(device_id=device_id),
                fetch_current=bool(payload.get("comment", False)),
            )
        if capability_name == "spotify.volume":
            return self._invoke_volume(payload, device_id=device_id)
        if capability_name == "spotify.shuffle":
            return self.client.shuffle(bool(payload.get("enabled", False)), device_id=device_id)
        if capability_name == "spotify.repeat":
            return self.client.repeat(payload.get("mode", "off"), device_id=device_id)
        if capability_name == "spotify.transfer_device":
            target_device = str(payload.get("device_id") or "").strip()
            return self.client.transfer_device(target_device, play=bool(payload.get("play", False)))
        if capability_name == "spotify.add_to_queue":
            return self.client.add_to_queue(payload.get("uri"), device_id=device_id)
        if capability_name == "spotify.duck.start":
            return self.duck_start()
        if capability_name == "spotify.duck.end":
            return self.duck_end()
        if capability_name == "spotify.story_hook":
            return self._story_hook(payload, device_id=device_id)
        return None

    def _invoke_volume(self, payload: dict[str, Any], *, device_id: str | None):
        if "relative" in payload:
            state = self.client.get_playback_state()
            if not state.get("ok"):
                return state
            current = int(((state.get("data") or {}).get("device") or {}).get("volume_percent") or self.settings.data.get("default_volume") or 30)
            percent = current + int(payload.get("relative") or 0)
        else:
            percent = payload.get("percent", payload.get("volume_percent", self.settings.data.get("default_volume", 30)))
        return self.client.set_volume(percent, device_id=device_id)

    def _next_duck_transition_generation(self) -> int:
        with self._duck_transition_lock:
            self._duck_transition_generation += 1
            return int(self._duck_transition_generation)

    def _volume_transition_is_current(self, generation: int) -> bool:
        with self._duck_transition_lock:
            return int(generation) == int(self._duck_transition_generation)

    def _set_volume_smooth(self, *, start: int, target: int, device_id: str | None, duration_ms: int, reason: str) -> dict[str, Any]:
        start_value = max(0, min(100, int(start)))
        target_value = max(0, min(100, int(target)))
        duration = max(0, int(duration_ms or 0))
        generation = self._next_duck_transition_generation()
        if duration <= 0 or start_value == target_value:
            result = self.client.set_volume(target_value, device_id=device_id)
            self._debug_log("duck_volume_set", {"reason": reason, "volume": target_value, "device_id": device_id, "result": result})
            return result

        steps = max(2, min(16, int(round(duration / 120.0)) or 2))
        sleep_seconds = duration / 1000.0 / steps

        def runner():
            last_result = None
            self._debug_log(
                "duck_volume_transition_start",
                {"reason": reason, "from": start_value, "to": target_value, "steps": steps, "duration_ms": duration, "device_id": device_id},
            )
            for index in range(1, steps + 1):
                if not self._volume_transition_is_current(generation):
                    self._debug_log("duck_volume_transition_cancelled", {"reason": reason, "step": index, "device_id": device_id})
                    return
                fraction = index / float(steps)
                volume = int(round(start_value + ((target_value - start_value) * fraction)))
                last_result = self.client.set_volume(volume, device_id=device_id)
                self._debug_log("duck_volume_step", {"reason": reason, "step": index, "steps": steps, "volume": volume, "result": last_result})
                if index < steps:
                    time.sleep(sleep_seconds)
            self._debug_log("duck_volume_transition_done", {"reason": reason, "to": target_value, "result": last_result})

        threading.Thread(target=runner, name="SpotifySenseDuckFade", daemon=True).start()
        return {"ok": True, "transitioning": True, "from": start_value, "to": target_value, "duration_ms": duration}

    def duck_start(self):
        if not bool(self.settings.data.get("duck_while_speaking", False)):
            return {"ok": True, "ducked": False, "message": "Spotify ducking is disabled."}
        device_id = str(self.settings.data.get("default_device_id") or "").strip() or None
        state = self.client.get_playback_state()
        if not state.get("ok"):
            return state
        device = (state.get("data") or {}).get("device") or {}
        if not device_id:
            device_id = str(device.get("id") or "").strip() or None
        try:
            self._remembered_volume = int(device.get("volume_percent"))
        except Exception:
            self._remembered_volume = int(self.settings.data.get("default_volume") or 30)
        self._remembered_duck_device_id = device_id
        target_volume = int(self.settings.data.get("duck_volume_percent", 15) or 15)
        duration_ms = int(self.settings.data.get("duck_fade_down_ms", 650) or 0)
        result = self._set_volume_smooth(
            start=self._remembered_volume,
            target=target_volume,
            device_id=device_id,
            duration_ms=duration_ms,
            reason="tts_duck_start",
        )
        self._debug_log(
            "duck_start",
            {"device_id": device_id, "previous_volume": self._remembered_volume, "target_volume": target_volume, "duration_ms": duration_ms, "result": result},
        )
        return {"ok": bool(result.get("ok")), "ducked": bool(result.get("ok")), "previous_volume": self._remembered_volume, "result": result}

    def duck_end(self):
        if not bool(self.settings.data.get("restore_volume_after_speech", True)):
            self._next_duck_transition_generation()
            self._debug_log("duck_end_restore_disabled", {"previous_volume": self._remembered_volume, "device_id": self._remembered_duck_device_id})
            self._remembered_volume = None
            self._remembered_duck_device_id = None
            return {"ok": True, "restored": False, "message": "Restore volume after speech is disabled."}
        if self._remembered_volume is None:
            return {"ok": True, "restored": False, "message": "No remembered Spotify volume to restore."}
        target_volume = int(self._remembered_volume)
        device_id = self._remembered_duck_device_id
        current_volume = int(self.settings.data.get("duck_volume_percent", 15) or 15)
        duration_ms = int(self.settings.data.get("duck_fade_up_ms", 900) or 0)
        result = self._set_volume_smooth(
            start=current_volume,
            target=target_volume,
            device_id=device_id,
            duration_ms=duration_ms,
            reason="tts_duck_end",
        )
        restored = self._remembered_volume
        self._remembered_volume = None
        self._remembered_duck_device_id = None
        self._debug_log("duck_end", {"device_id": device_id, "restore_volume": restored, "duration_ms": duration_ms, "result": result})
        return {"ok": bool(result.get("ok")), "restored": bool(result.get("ok")), "volume": restored, "result": result}

    def _story_hook(self, payload: dict[str, Any], *, device_id: str | None):
        if not bool(self.settings.data.get("story_mode_background_music", False)):
            return {"ok": True, "started": False, "message": "Story mode background music is disabled."}
        autonomy = str(self.settings.data.get("autonomous_music") or "off")
        if autonomy == "off":
            return {"ok": False, "error_code": "autonomy_disabled", "error": "Autonomous music is disabled."}
        event = str(payload.get("event") or payload.get("scene_event") or "").strip().lower()
        if autonomy == "routines" and event not in {"story_start", "scene_start", "coding_start"}:
            return {"ok": False, "error_code": "routine_only", "error": "Autonomous music is limited to routine starts."}
        mood = str(payload.get("mood") or "fantasy").strip().lower()
        query = str(payload.get("query") or self._story_query_for_mood(mood)).strip()
        return self.client.play(query=query, device_id=device_id)

    def _story_query_for_mood(self, mood: str) -> str:
        mapping = {
            "dark": "dark cinematic ambient music",
            "epic": "epic fantasy adventure music",
            "calm": "calm fantasy ambience",
            "sad": "melancholy orchestral ambient music",
            "focus": str(self.settings.data.get("coding_mode_query") or "relaxing focus music"),
        }
        return mapping.get(str(mood or "").lower(), "fantasy story ambience")

    def export_session_state(self):
        return {
            "spotify_sense": {
                key: value
                for key, value in dict(self.settings.data).items()
                if key not in TOKEN_KEYS and key not in {"client_id"}
            }
        }

    def import_session_state(self, session):
        payload = dict(session or {}).get("spotify_sense")
        if isinstance(payload, dict):
            safe_payload = {key: value for key, value in payload.items() if key not in TOKEN_KEYS and key != "client_id"}
            self.settings.update(**safe_payload)
            self._sync_control_values()
            self._sync_monitor_timer()
        return None

    def _set_status(self, text: str):
        label = getattr(self, "status_label", None)
        if label is not None:
            label.setText(str(text or ""))

    def shutdown(self):
        self._unregister_sensory_provider()
        if self._track_monitor_timer.isActive():
            self._track_monitor_timer.stop()
        if self._oauth_server is not None:
            try:
                self._oauth_server.shutdown()
                self._oauth_server.server_close()
            except Exception:
                pass
            self._oauth_server = None
        self._widgets.clear()
        self._controls.clear()
