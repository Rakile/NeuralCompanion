from __future__ import annotations

import http.server
import json
import re
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Callable

from PySide6 import QtCore, QtGui, QtWidgets

from .intent_router import infer_music_mood, route_music_intent
from .settings import DEFAULT_HIDDEN_COMMENTARY_STYLE_PROMPT, DEFAULT_SETTINGS, TOKEN_KEYS, SpotifySenseSettings
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
    "Do not repeatedly mention Spotify. Speak about music only when the user asks, when a fresh track-change comment is allowed, or when it clearly improves the reply. "
    "When a commentary style prompt is provided, follow that style while staying brief, natural, and grounded in metadata."
)
MUSIC_RESPONSE_MODES = (
    ("Off", "off"),
    ("Subtle", "subtle"),
    ("Companion", "companion"),
    ("DJ / Music Critic", "dj_critic"),
    ("Story soundtrack", "story_soundtrack"),
)
HIDDEN_SENSORY_QUICK_LIMIT = 6
SPOTIFY_HIDDEN_COMMENT_ANGLES = (
    "soft texture",
    "quiet focus",
    "late-night atmosphere",
    "steady pulse",
    "warm background",
    "cool distance",
    "cinematic tension",
    "gentle momentum",
    "stillness",
    "wide-open space",
    "subtle groove",
    "melancholy edge",
    "bright lift",
    "shadowy calm",
    "deep-room ambience",
    "slow-burn energy",
    "clean concentration",
    "resting mood",
    "dreamlike haze",
    "grounded pace",
    "minimal movement",
    "patient build",
    "low-light color",
    "floating feel",
    "soft percussion",
    "distant echo",
    "warm synth air",
    "acoustic closeness",
    "nocturnal drift",
    "smooth transition",
    "breathing room",
    "story underscoring",
    "reflective space",
    "low-pressure flow",
    "calm resolve",
    "muted intensity",
    "open horizon",
    "small-detail listening",
    "gentle contrast",
    "focused still frame",
    "rainy-window mood",
    "submerged warmth",
    "slow orbit",
    "soft suspense",
    "clean electronic line",
    "human touch",
    "ambient shadow",
    "clear-headed pace",
    "quiet confidence",
    "dusk tone",
    "lonely sparkle",
    "subtle lift",
    "weightless motion",
    "tucked-away calm",
    "softly serious",
    "measured stride",
    "unhurried scene",
    "low-end cushion",
    "silver-blue space",
    "still-water mood",
    "sparse detail",
    "gentle forward lean",
    "background glow",
    "private-room feel",
    "slow cinematic pan",
    "muted pulse",
    "rounded warmth",
    "clear night air",
    "quiet mechanical rhythm",
    "earthy calm",
    "soft focus light",
    "distant road",
    "held breath",
    "steady hands",
    "patient ambience",
    "small flame",
    "clouded memory",
    "low-key elegance",
    "subtle pressure",
    "ambient companionship",
    "low-volume drama",
    "gentle reset",
    "focus tunnel",
    "slow wave",
    "shadow and warmth",
    "empty-room resonance",
    "calm afterglow",
    "quiet scene change",
    "thin-line tension",
    "soft landing",
    "wandering thought",
    "polished calm",
    "understated color",
    "deep breath",
    "slow spark",
    "gentle night drive",
    "low-lit rhythm",
    "settled atmosphere",
    "hushed movement",
    "clean mood shift",
    "quiet gravity",
)
SPOTIFY_HIDDEN_FORBIDDEN_OPENINGS = (
    "Song changed",
    "The song changed",
    "Track changed",
    "Now playing",
    "Spotify changed",
    "Changed to",
)
BUILTIN_HIDDEN_SENSORY_PRESETS = (
    {
        "id": "builtin.natural_companion",
        "name": "Natural Companion",
        "prompt": DEFAULT_HIDDEN_COMMENTARY_STYLE_PROMPT,
    },
    {
        "id": "builtin.music_nerd",
        "name": "Music Nerd",
        "prompt": (
            "Make one concise, music-aware comment with a little taste and texture. Mention the track, artist, "
            "mood, groove, or contrast only when it feels natural. Avoid trivia dumps and generic praise."
        ),
    },
    {
        "id": "builtin.story_soundtrack",
        "name": "Story Soundtrack",
        "prompt": (
            "Treat the track as a story soundtrack cue. Make one short atmospheric comment that connects the "
            "music mood to the current scene energy, tension, or pacing without explaining the metadata."
        ),
    },
    {
        "id": "builtin.focus_mode",
        "name": "Focus Mode",
        "prompt": (
            "Keep music comments rare, calm, and low-distraction. If commenting, use one quiet sentence about "
            "how the track supports focus or momentum, then get out of the way."
        ),
    },
    {
        "id": "builtin.playful_dj",
        "name": "Playful DJ",
        "prompt": (
            "Use a light, casual DJ-style reaction in one sentence. Be playful but not loud, avoid forced jokes, "
            "and tie the comment to the actual title, artist, or mood hint."
        ),
    },
    {
        "id": "builtin.minimal",
        "name": "Minimal",
        "prompt": (
            "Use the shortest natural acknowledgement possible. One grounded phrase or sentence is enough; "
            "do not recap metadata unless the title or artist matters."
        ),
    },
)

SETTING_TOOLTIPS = {
    "enabled": "Turns Spotify Sense on. The addon still needs a connected Spotify account before it can read or control playback.",
    "allow_llm_control": "Allows autonomous/model-initiated Spotify changes. Direct user voice commands can still run when Spotify Sense is enabled and connected.",
    "require_confirmation": "Keeps autonomous/tool-triggered playback changes blocked unless the request is confirmed. Direct user commands are treated as confirmed.",
    "duck_while_speaking": "Temporarily lowers Spotify volume while NC speaks, if the active Spotify device allows volume control.",
    "restore_volume_after_speech": "Restores the saved Spotify volume after NC finishes speaking.",
    "duck_fade_down_ms": "How long Spotify takes to fade down when NC starts speaking. Set to 0 for immediate changes.",
    "duck_fade_up_ms": "How long Spotify takes to fade back up after NC stops speaking. Set to 0 for immediate restore.",
    "comment_on_song_changes": "Allows a short optional acknowledgement when Spotify detects a new track, subject to the cooldown timers.",
    "allow_queue_changes": "Allows NC tools to add tracks to the Spotify queue.",
    "allow_playlist_changes": "Allows NC tools to start playlists or playlist contexts.",
    "story_mode_background_music": "Allows story hooks to select background music when story mode asks for it.",
    "story_music_prefer_ambient": "Biases story hooks toward ambient playlists unless the story beat clearly asks for music.",
    "story_music_target_volume": "Volume Spotify fades up to after story music starts.",
    "story_music_transition_floor_volume": "Temporary low volume used while switching story music.",
    "story_music_fade_down_ms": "How long Spotify takes to fade down before changing story music.",
    "story_music_fade_up_ms": "How long Spotify takes to fade up after changing story music.",
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
    "debug_logging_enabled": "Writes Spotify Sense route, playback, and lower-volume diagnostics to an addon-local debug log file.",
}


class _OAuthHTTPServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True


class _SpotifyRefineBridge(QtCore.QObject):
    finished = QtCore.Signal(object, str, str, str)


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
        self._recent_hidden_comment_records: list[dict[str, Any]] = []
        self._hidden_comment_angle_cursor = 0
        self._last_nc_music_change_at = 0.0
        self._last_user_music_change_at = 0.0
        self._last_album_art_url = ""
        self._duck_transition_lock = threading.RLock()
        self._duck_transition_generation = 0
        self._story_transition_lock = threading.RLock()
        self._story_transition_generation = 0
        self._sensory_provider_registered = False
        self._refine_bridge = _SpotifyRefineBridge()
        self._refine_bridge.finished.connect(self._on_hidden_sensory_field_refined)
        self._hidden_style_save_timer = QtCore.QTimer(self)
        self._hidden_style_save_timer.setSingleShot(True)
        self._hidden_style_save_timer.setInterval(650)
        self._hidden_style_save_timer.timeout.connect(lambda: self._save_hidden_commentary_style(silent=True))

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
                    "do not claim to hear raw audio. If the current snapshot says a fresh song-change "
                    "comment is allowed, return should_speak=true with a concise proactive_candidate. "
                    "Follow commentary_style_prompt when present. "
                    "Otherwise avoid repeated music chatter and set should_speak=false."
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
                        "Spotify Sense provides metadata only. When content says a fresh song-change comment "
                        "is allowed now, set should_speak=true and write a short proactive_candidate about "
                        "the current track. Follow commentary_style_prompt when present. Otherwise keep=false "
                        "or keep=true with should_speak=false."
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
            "Optional Spotify Web API controls for current-track awareness, safe music commands, lower music while NC speaks, and story hooks."
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

        connection_group, connection_layout = self._section_group("Connect Spotify")
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

        self.enable_checkbox = self._checkbox("Enable Spotify Sense", "enabled")
        self.llm_checkbox = self._checkbox("Allow autonomous LLM Spotify control", "allow_llm_control")
        self.confirm_checkbox = self._checkbox("Require confirmation before changing music", "require_confirmation")
        self.duck_checkbox = self._checkbox("Lower music while NC speaks", "duck_while_speaking")
        self.restore_checkbox = self._checkbox("Restore volume after speech", "restore_volume_after_speech")
        self.comment_checkbox = self._checkbox("Comment on song changes", "comment_on_song_changes")
        self.queue_checkbox = self._checkbox("Allow queue changes", "allow_queue_changes")
        self.playlist_checkbox = self._checkbox("Allow playlist changes", "allow_playlist_changes")
        self.story_checkbox = self._checkbox("Story mode background music", "story_mode_background_music")
        self.story_ambient_checkbox = self._checkbox("Prefer story ambience", "story_music_prefer_ambient")
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
        self.story_music_target_volume_spin = self._spinbox("story_music_target_volume", 0, 100)
        self.story_music_transition_floor_spin = self._spinbox("story_music_transition_floor_volume", 0, 100)
        self.story_music_fade_down_spin = self._spinbox("story_music_fade_down_ms", 0, 8000, suffix="ms")
        self.story_music_fade_up_spin = self._spinbox("story_music_fade_up_ms", 0, 8000, suffix="ms")
        self.comment_cooldown_spin = self._spinbox("proactive_comment_cooldown_seconds", 15, 3600, suffix="s")
        self.hidden_response_cooldown_spin = self._spinbox("hidden_response_cooldown_seconds", 15, 7200, suffix="s")
        self.user_change_cooldown_spin = self._spinbox("user_music_change_cooldown_seconds", 0, 3600, suffix="s")
        self.debug_log_checkbox = self._checkbox("Debug log", "debug_logging_enabled")

        self.coding_query_edit = QtWidgets.QLineEdit()
        self.coding_query_edit.setObjectName("spotify_sense_coding_query")
        self.coding_query_edit.setText(str(self.settings.data.get("coding_mode_query") or "relaxing focus music"))
        self.coding_query_edit.setToolTip(SETTING_TOOLTIPS["coding_mode_query"])
        self.coding_query_edit.editingFinished.connect(self._on_text_settings_finished)

        playback_group, playback_layout = self._section_group("Playback Controls")
        playback_grid = QtWidgets.QGridLayout()
        playback_grid.setContentsMargins(0, 0, 0, 0)
        playback_grid.setHorizontalSpacing(10)
        playback_grid.setVerticalSpacing(6)
        playback_grid.addWidget(self.enable_checkbox, 0, 0, 1, 2)
        playback_grid.addWidget(self.llm_checkbox, 0, 2, 1, 2)
        playback_grid.addWidget(self.confirm_checkbox, 1, 0, 1, 2)
        playback_grid.addWidget(self.queue_checkbox, 1, 2, 1, 2)
        playback_grid.addWidget(self.playlist_checkbox, 2, 0, 1, 2)
        playback_grid.addWidget(QtWidgets.QLabel("Default device"), 3, 0)
        playback_grid.addWidget(self.default_device_combo, 3, 1, 1, 3)
        playback_grid.addWidget(QtWidgets.QLabel("Default volume"), 4, 0)
        playback_grid.addWidget(self.default_volume_spin, 4, 1)
        playback_grid.setColumnStretch(3, 1)
        playback_layout.addLayout(playback_grid)
        card_layout.addWidget(playback_group)

        commentary_group, commentary_layout = self._section_group("Music Commentary")
        commentary_grid = QtWidgets.QGridLayout()
        commentary_grid.setContentsMargins(0, 0, 0, 0)
        commentary_grid.setHorizontalSpacing(10)
        commentary_grid.setVerticalSpacing(6)
        commentary_grid.addWidget(self.comment_checkbox, 0, 0, 1, 2)
        commentary_grid.addWidget(self.monitor_checkbox, 0, 2, 1, 2)
        commentary_grid.addWidget(self.awareness_checkbox, 1, 0, 1, 2)
        commentary_grid.addWidget(self.relevance_checkbox, 1, 2, 1, 2)
        commentary_grid.addWidget(self.paused_context_checkbox, 2, 0, 1, 2)
        commentary_grid.addWidget(self.album_art_checkbox, 2, 2, 1, 2)
        commentary_grid.addWidget(QtWidgets.QLabel("Music response mode"), 3, 0)
        commentary_grid.addWidget(self.response_mode_combo, 3, 1)
        commentary_grid.addWidget(QtWidgets.QLabel("Song-change cooldown"), 3, 2)
        commentary_grid.addWidget(self.comment_cooldown_spin, 3, 3)
        commentary_grid.addWidget(QtWidgets.QLabel("Hidden response cooldown"), 4, 0)
        commentary_grid.addWidget(self.hidden_response_cooldown_spin, 4, 1)
        commentary_grid.addWidget(QtWidgets.QLabel("User change lockout"), 4, 2)
        commentary_grid.addWidget(self.user_change_cooldown_spin, 4, 3)
        commentary_grid.setColumnStretch(3, 1)
        commentary_layout.addLayout(commentary_grid)
        card_layout.addWidget(commentary_group)

        duck_group, duck_layout = self._section_group("Lower Music While NC Speaks")
        duck_grid = QtWidgets.QGridLayout()
        duck_grid.setContentsMargins(0, 0, 0, 0)
        duck_grid.setHorizontalSpacing(10)
        duck_grid.setVerticalSpacing(6)
        duck_grid.addWidget(self.duck_checkbox, 0, 0, 1, 2)
        duck_grid.addWidget(self.restore_checkbox, 0, 2, 1, 2)
        duck_grid.addWidget(QtWidgets.QLabel("Lowered volume"), 1, 0)
        duck_grid.addWidget(self.duck_volume_spin, 1, 1)
        duck_grid.addWidget(QtWidgets.QLabel("Fade down"), 1, 2)
        duck_grid.addWidget(self.duck_fade_down_spin, 1, 3)
        duck_grid.addWidget(QtWidgets.QLabel("Fade back up"), 2, 2)
        duck_grid.addWidget(self.duck_fade_up_spin, 2, 3)
        duck_grid.setColumnStretch(3, 1)
        duck_layout.addLayout(duck_grid)
        card_layout.addWidget(duck_group)

        story_group, story_layout = self._section_group("Story Soundtrack")
        story_grid = QtWidgets.QGridLayout()
        story_grid.setContentsMargins(0, 0, 0, 0)
        story_grid.setHorizontalSpacing(10)
        story_grid.setVerticalSpacing(6)
        story_grid.addWidget(self.story_checkbox, 0, 0, 1, 2)
        story_grid.addWidget(self.story_ambient_checkbox, 0, 2, 1, 2)
        story_grid.addWidget(QtWidgets.QLabel("Autonomous music"), 1, 0)
        story_grid.addWidget(self.autonomy_combo, 1, 1)
        story_grid.addWidget(QtWidgets.QLabel("Story target volume"), 1, 2)
        story_grid.addWidget(self.story_music_target_volume_spin, 1, 3)
        story_grid.addWidget(QtWidgets.QLabel("Switching volume"), 2, 0)
        story_grid.addWidget(self.story_music_transition_floor_spin, 2, 1)
        story_grid.addWidget(QtWidgets.QLabel("Fade down"), 2, 2)
        story_grid.addWidget(self.story_music_fade_down_spin, 2, 3)
        story_grid.addWidget(QtWidgets.QLabel("Fade back up"), 3, 2)
        story_grid.addWidget(self.story_music_fade_up_spin, 3, 3)
        story_grid.addWidget(QtWidgets.QLabel("Focus music search"), 4, 0)
        story_grid.addWidget(self.coding_query_edit, 4, 1, 1, 3)
        story_grid.setColumnStretch(3, 1)
        story_layout.addLayout(story_grid)
        card_layout.addWidget(story_group)

        debug_group, debug_layout = self._section_group("Advanced Debug")
        debug_layout.addWidget(self.debug_log_checkbox)
        card_layout.addWidget(debug_group)

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
            ("Play", self._on_play),
            ("Pause", self._on_pause),
            ("Next", self._on_next),
            ("Previous", self._on_previous),
            ("Volume 30%", self._on_volume_30),
        ):
            button = QtWidgets.QPushButton(label)
            button.setToolTip(
                {
                    "Current Track": "Read current Spotify playback metadata.",
                    "Play": "Resume Spotify playback on the selected or active device.",
                    "Pause": "Pause Spotify playback on the selected or active device.",
                    "Next": "Skip to the next Spotify track.",
                    "Previous": "Go back to the previous Spotify track.",
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

    def _notify_shell_settings_changed(self):
        try:
            shell = self.context.get_service("qt.shell") if getattr(self, "context", None) is not None else None
            if shell is not None:
                shell.notify_settings_changed()
        except Exception:
            pass

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
            self._notify_shell_settings_changed()
            self._set_status("Spotify hidden sensory source guidance saved.")
        except Exception as exc:
            self._set_status(f"Could not save Spotify source guidance: {exc}")

    def _reset_source_guidance(self):
        editor = getattr(self, "source_guidance_edit", None)
        if editor is not None:
            editor.setPlainText(DEFAULT_SPOTIFY_SOURCE_GUIDANCE)
        self._save_source_guidance()

    def _current_hidden_commentary_style_prompt(self) -> str:
        editor = getattr(self, "hidden_commentary_style_edit", None)
        if editor is not None and hasattr(editor, "toPlainText"):
            text = str(editor.toPlainText() or "").strip()
        else:
            text = str(self.settings.data.get("hidden_commentary_style_prompt") or "").strip()
        return text or DEFAULT_HIDDEN_COMMENTARY_STYLE_PROMPT

    def _hidden_sensory_preset_records(self) -> list[dict[str, str]]:
        records: list[dict[str, str]] = [dict(item, builtin=True) for item in BUILTIN_HIDDEN_SENSORY_PRESETS]
        for item in list(self.settings.data.get("hidden_sensory_custom_presets") or []):
            if not isinstance(item, dict):
                continue
            prompt = str(item.get("prompt") or "").strip()
            preset_id = str(item.get("id") or "").strip()
            if not prompt or not preset_id:
                continue
            records.append(
                {
                    "id": preset_id,
                    "name": str(item.get("name") or "Custom Hidden Sensory").strip() or "Custom Hidden Sensory",
                    "prompt": prompt,
                    "builtin": False,
                }
            )
        return records

    def _hidden_sensory_record_by_id(self, preset_id: str) -> dict[str, str] | None:
        wanted = str(preset_id or "").strip()
        if not wanted:
            return None
        for record in self._hidden_sensory_preset_records():
            if str(record.get("id") or "") == wanted:
                return record
        return None

    def _hidden_sensory_quick_ids(self) -> list[str]:
        known = {str(record.get("id") or "") for record in self._hidden_sensory_preset_records()}
        ids: list[str] = []
        for item in list(self.settings.data.get("hidden_sensory_quick_ids") or []):
            preset_id = str(item or "").strip()
            if preset_id and preset_id in known and preset_id not in ids:
                ids.append(preset_id)
            if len(ids) >= HIDDEN_SENSORY_QUICK_LIMIT:
                break
        return ids

    def _selected_hidden_sensory_preset_id(self) -> str:
        editor = getattr(self, "hidden_commentary_style_edit", None)
        if editor is None:
            combo = getattr(self, "hidden_sensory_preset_combo", None)
            if combo is not None and hasattr(combo, "currentData"):
                preset_id = str(combo.currentData() or "").strip()
                if preset_id:
                    return preset_id
            return str(self.settings.data.get("hidden_sensory_preset_id") or "").strip()
        current = self._current_hidden_commentary_style_prompt().strip()
        for record in self._hidden_sensory_preset_records():
            if str(record.get("prompt") or "").strip() == current:
                return str(record.get("id") or "").strip()
        return ""

    def _selected_hidden_sensory_preset_record(self) -> dict[str, str] | None:
        return self._hidden_sensory_record_by_id(self._selected_hidden_sensory_preset_id())

    def _set_hidden_sensory_status(self, message: str):
        label = getattr(self, "hidden_sensory_status_label", None)
        if label is not None and hasattr(label, "setText"):
            label.setText(str(message or ""))
        if message:
            self._set_status(str(message))

    def _refresh_hidden_sensory_preset_controls(self, selected_id: str = ""):
        records = self._hidden_sensory_preset_records()
        selected_id = str(selected_id or self._selected_hidden_sensory_preset_id() or "").strip()
        combo = getattr(self, "hidden_sensory_preset_combo", None)
        if combo is not None and hasattr(combo, "clear"):
            previous = bool(combo.blockSignals(True)) if hasattr(combo, "blockSignals") else False
            try:
                combo.clear()
                combo.addItem("Load hidden sensory style...", "")
                for record in records:
                    combo.addItem(str(record.get("name") or "Hidden Sensory"), str(record.get("id") or ""))
                if selected_id:
                    for index in range(combo.count()):
                        if str(combo.itemData(index) or "") == selected_id:
                            combo.setCurrentIndex(index)
                            break
                    else:
                        combo.setCurrentIndex(0)
                else:
                    combo.setCurrentIndex(0)
            finally:
                if hasattr(combo, "blockSignals"):
                    combo.blockSignals(previous)

        quick_ids = self._hidden_sensory_quick_ids()
        quick_boxes = list(getattr(self, "hidden_sensory_quick_checkboxes", []) or [])
        for index, checkbox in enumerate(quick_boxes):
            previous = bool(checkbox.blockSignals(True)) if hasattr(checkbox, "blockSignals") else False
            try:
                if index < len(quick_ids):
                    record = self._hidden_sensory_record_by_id(quick_ids[index])
                    checkbox.setText(f"{index + 1}. {record.get('name', 'Style') if record else 'Style'}")
                    checkbox.setProperty("preset_id", quick_ids[index])
                    checkbox.setEnabled(True)
                    checkbox.setChecked(str(quick_ids[index]) == selected_id)
                    checkbox.setToolTip(f"Load hidden sensory style: {record.get('name', 'Style') if record else 'Style'}")
                else:
                    checkbox.setText(f"{index + 1}. Empty")
                    checkbox.setProperty("preset_id", "")
                    checkbox.setEnabled(False)
                    checkbox.setChecked(False)
                    checkbox.setToolTip("Empty hidden sensory quick slot. Save a style and press Add Quick to fill it.")
            finally:
                if hasattr(checkbox, "blockSignals"):
                    checkbox.blockSignals(previous)

        record = self._hidden_sensory_record_by_id(selected_id)
        add_button = getattr(self, "btn_hidden_sensory_add_quick", None)
        remove_button = getattr(self, "btn_hidden_sensory_remove_quick", None)
        quick = selected_id in quick_ids if selected_id else False
        if add_button is not None and hasattr(add_button, "setEnabled"):
            add_button.setEnabled(bool(record and not quick and len(quick_ids) < HIDDEN_SENSORY_QUICK_LIMIT))
        if remove_button is not None and hasattr(remove_button, "setEnabled"):
            remove_button.setEnabled(bool(record and quick))

    def _load_hidden_sensory_preset_record(self, record: dict[str, str] | None):
        if not isinstance(record, dict):
            return
        prompt = str(record.get("prompt") or "").strip()
        preset_id = str(record.get("id") or "").strip()
        if not prompt:
            return
        editor = getattr(self, "hidden_commentary_style_edit", None)
        if editor is not None and hasattr(editor, "setPlainText"):
            editor.setPlainText(prompt)
        self.settings.update(hidden_commentary_style_prompt=prompt, hidden_sensory_preset_id=preset_id)
        self._refresh_hidden_sensory_preset_controls(preset_id)
        self._set_hidden_sensory_status(f"Loaded hidden sensory style: {record.get('name', 'Style')}")

    def _on_hidden_sensory_preset_selected(self, index: int):
        combo = getattr(self, "hidden_sensory_preset_combo", None)
        if combo is None or not hasattr(combo, "itemData"):
            return
        record = self._hidden_sensory_record_by_id(str(combo.itemData(index) or ""))
        if record:
            self._load_hidden_sensory_preset_record(record)

    def _on_hidden_sensory_quick_toggled(self, slot: int, checked: bool):
        if not checked:
            return
        quick_boxes = list(getattr(self, "hidden_sensory_quick_checkboxes", []) or [])
        if slot < 0 or slot >= len(quick_boxes):
            return
        preset_id = str(quick_boxes[slot].property("preset_id") or "").strip()
        record = self._hidden_sensory_record_by_id(preset_id)
        if record:
            self._load_hidden_sensory_preset_record(record)

    def _save_hidden_commentary_style(self, *, silent: bool = False):
        timer = getattr(self, "_hidden_style_save_timer", None)
        if timer is not None and hasattr(timer, "isActive") and timer.isActive():
            timer.stop()
        prompt = self._current_hidden_commentary_style_prompt()
        self.settings.update(hidden_commentary_style_prompt=prompt)
        if not silent:
            self._set_hidden_sensory_status("Hidden commentary style saved.")

    def _on_hidden_commentary_style_changed(self):
        timer = getattr(self, "_hidden_style_save_timer", None)
        if timer is not None:
            timer.start()
        self._refresh_hidden_sensory_preset_controls()

    def _generated_hidden_sensory_preset_name(self, prompt: str) -> str:
        first_line = str(prompt or "").strip().splitlines()[0] if str(prompt or "").strip().splitlines() else "Custom Hidden Sensory"
        base = re.sub(r"^(make|write|use|respond like|comment like)\s+", "", first_line, flags=re.IGNORECASE)
        base = re.sub(r"[^A-Za-z0-9 _.-]+", "", base).strip(" ._-")[:44].strip() or "Custom Hidden Sensory"
        existing = {str(record.get("name") or "").strip().lower() for record in self._hidden_sensory_preset_records()}
        if base.lower() not in existing:
            return base
        for index in range(2, 1000):
            candidate = f"{base} {index}"
            if candidate.lower() not in existing:
                return candidate
        return f"{base} {int(time.time())}"

    def _save_hidden_sensory_style_as_preset(self):
        prompt = self._current_hidden_commentary_style_prompt().strip()
        if not prompt:
            self._set_hidden_sensory_status("Nothing to save: hidden commentary style is empty.")
            return
        custom = [dict(item) for item in list(self.settings.data.get("hidden_sensory_custom_presets") or []) if isinstance(item, dict)]
        name = self._generated_hidden_sensory_preset_name(prompt)
        preset_id = "custom." + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        existing_ids = {str(item.get("id") or "") for item in custom}
        if preset_id in existing_ids:
            preset_id = f"{preset_id}_{int(time.time())}"
        record = {
            "id": preset_id,
            "name": name,
            "prompt": prompt,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        custom.append(record)
        self.settings.update(
            hidden_commentary_style_prompt=prompt,
            hidden_sensory_preset_id=preset_id,
            hidden_sensory_custom_presets=custom,
        )
        self._refresh_hidden_sensory_preset_controls(preset_id)
        self._set_hidden_sensory_status(f"Saved hidden sensory style: {name}")

    def _on_hidden_sensory_add_quick_clicked(self):
        record = self._selected_hidden_sensory_preset_record()
        if not record:
            self._set_hidden_sensory_status("Choose a saved hidden sensory style before adding it to quick select.")
            return
        preset_id = str(record.get("id") or "")
        quick_ids = self._hidden_sensory_quick_ids()
        if preset_id not in quick_ids:
            if len(quick_ids) >= HIDDEN_SENSORY_QUICK_LIMIT:
                self._set_hidden_sensory_status("Hidden sensory quick select already has six styles.")
                return
            quick_ids.append(preset_id)
        self.settings.update(hidden_sensory_quick_ids=quick_ids)
        self._refresh_hidden_sensory_preset_controls(preset_id)
        self._set_hidden_sensory_status(f"Added quick hidden sensory style: {record.get('name', 'Style')}")

    def _on_hidden_sensory_remove_quick_clicked(self):
        record = self._selected_hidden_sensory_preset_record()
        if not record:
            self._set_hidden_sensory_status("Choose a saved hidden sensory style before removing it from quick select.")
            return
        preset_id = str(record.get("id") or "")
        quick_ids = [item for item in self._hidden_sensory_quick_ids() if item != preset_id]
        self.settings.update(hidden_sensory_quick_ids=quick_ids)
        self._refresh_hidden_sensory_preset_controls(preset_id)
        self._set_hidden_sensory_status(f"Removed quick hidden sensory style: {record.get('name', 'Style')}")

    def _install_hidden_sensory_refine_menu(self, widget, field_label: str, guidance: str):
        if widget is None or not hasattr(widget, "customContextMenuRequested"):
            return
        widget.setProperty("_spotify_refine_label", str(field_label or "Field"))
        widget.setProperty("_spotify_refine_guidance", str(guidance or ""))
        try:
            widget.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            widget.customContextMenuRequested.connect(
                lambda point, edit=widget: self._show_hidden_sensory_refine_menu(edit, point)
            )
        except Exception:
            return
        existing_tip = str(widget.toolTip() or "").strip()
        refine_tip = "Right-click for Refine, Save as hidden sensory style, quick slots, and reset actions."
        widget.setToolTip(f"{existing_tip}\n\n{refine_tip}" if existing_tip else refine_tip)

    def _show_hidden_sensory_refine_menu(self, widget, point):
        try:
            menu = widget.createStandardContextMenu()
        except Exception:
            menu = QtWidgets.QMenu(widget)
        menu.addSeparator()
        label = str(widget.property("_spotify_refine_label") or "Field")
        current_text = self._refinable_widget_text(widget)
        refine_action = menu.addAction(f"Refine {label}")
        refine_action.setEnabled(bool(current_text) and not bool(widget.property("_nc_refine_in_flight")))
        refine_action.triggered.connect(lambda _checked=False, edit=widget: self._refine_hidden_sensory_field(edit))
        if widget is getattr(self, "hidden_commentary_style_edit", None):
            menu.addSeparator()
            save_action = menu.addAction("Save Style")
            save_action.triggered.connect(lambda _checked=False: self._save_hidden_commentary_style(silent=False))
            save_as_action = menu.addAction("Save Style As Preset")
            save_as_action.triggered.connect(lambda _checked=False: self._save_hidden_sensory_style_as_preset())
            reset_action = menu.addAction("Use Natural Companion Style")
            reset_action.triggered.connect(
                lambda _checked=False: self._load_hidden_sensory_preset_record(
                    self._hidden_sensory_record_by_id("builtin.natural_companion")
                )
            )
        if widget is getattr(self, "source_guidance_edit", None):
            menu.addSeparator()
            save_guidance_action = menu.addAction("Save Source Guidance")
            save_guidance_action.triggered.connect(lambda _checked=False: self._save_source_guidance())
            reset_guidance_action = menu.addAction("Use Recommended Source Guidance")
            reset_guidance_action.triggered.connect(lambda _checked=False: self._reset_source_guidance())
        try:
            viewport = widget.viewport() if hasattr(widget, "viewport") else widget
            menu.exec(viewport.mapToGlobal(point))
        except Exception:
            pass

    def _show_hidden_sensory_group_menu(self, group, point):
        menu = QtWidgets.QMenu(group)
        refine_style = menu.addAction("Refine Hidden Commentary Style")
        refine_style.setEnabled(
            bool(self._current_hidden_commentary_style_prompt().strip())
            and not bool(getattr(self, "hidden_commentary_style_edit", None).property("_nc_refine_in_flight"))
            if getattr(self, "hidden_commentary_style_edit", None) is not None
            else False
        )
        refine_style.triggered.connect(
            lambda _checked=False: self._refine_hidden_sensory_field(getattr(self, "hidden_commentary_style_edit", None))
        )
        save_style = menu.addAction("Save Style")
        save_style.triggered.connect(lambda _checked=False: self._save_hidden_commentary_style(silent=False))
        save_as = menu.addAction("Save Style As Preset")
        save_as.triggered.connect(lambda _checked=False: self._save_hidden_sensory_style_as_preset())
        menu.addSeparator()
        reset_style = menu.addAction("Use Natural Companion Style")
        reset_style.triggered.connect(
            lambda _checked=False: self._load_hidden_sensory_preset_record(
                self._hidden_sensory_record_by_id("builtin.natural_companion")
            )
        )
        reset_guidance = menu.addAction("Use Recommended Source Guidance")
        reset_guidance.triggered.connect(lambda _checked=False: self._reset_source_guidance())
        try:
            menu.exec(group.mapToGlobal(point))
        except Exception:
            pass

    def _refinable_widget_text(self, widget) -> str:
        if widget is None:
            return ""
        if hasattr(widget, "toPlainText"):
            return str(widget.toPlainText() or "").strip()
        if hasattr(widget, "text"):
            return str(widget.text() or "").strip()
        return ""

    def _set_refinable_widget_text(self, widget, text: str):
        if widget is None:
            return
        if hasattr(widget, "setPlainText"):
            widget.setPlainText(str(text or ""))
        elif hasattr(widget, "setText"):
            widget.setText(str(text or ""))

    def _refine_hidden_sensory_field(self, widget):
        if widget is None or bool(widget.property("_nc_refine_in_flight")):
            return
        original = self._refinable_widget_text(widget)
        if not original:
            return
        label = str(widget.property("_spotify_refine_label") or "Hidden Sensory Prompt")
        guidance = str(widget.property("_spotify_refine_guidance") or "")
        widget.setProperty("_nc_refine_in_flight", True)
        self._set_hidden_sensory_status(f"Refining {label}...")

        def worker():
            result = ""
            error = ""
            try:
                from ui.runtime import engine_access as engine

                result = str(engine.refine_instruction_text(original, label=label, guidance=guidance) or "").strip()
            except Exception as exc:
                error = str(exc)
            try:
                self._refine_bridge.finished.emit(widget, label, result, error)
            except RuntimeError:
                pass

        threading.Thread(target=worker, name="nc-spotify-sensory-refine", daemon=True).start()

    def _on_hidden_sensory_field_refined(self, widget, field_label: str, refined_text: str, error: str):
        try:
            widget.setProperty("_nc_refine_in_flight", False)
        except RuntimeError:
            return
        error_text = str(error or "").strip()
        if error_text:
            try:
                QtWidgets.QMessageBox.warning(widget.window(), f"Refine {field_label}", f"Refinement failed:\n\n{error_text}")
            except Exception:
                pass
            self._set_hidden_sensory_status(f"Refine failed: {error_text}")
            return
        refined = str(refined_text or "").strip()
        if not refined:
            return
        self._set_refinable_widget_text(widget, refined)
        if widget is getattr(self, "hidden_commentary_style_edit", None):
            self._save_hidden_commentary_style(silent=True)
            self._set_hidden_sensory_status("Hidden commentary style refined.")
        elif widget is getattr(self, "source_guidance_edit", None):
            self._save_source_guidance()

    def _build_hidden_sensory_group(self):
        group, layout = self._section_group("Hidden Sensory Source")
        try:
            group.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            group.customContextMenuRequested.connect(
                lambda point, target=group: self._show_hidden_sensory_group_menu(target, point)
            )
        except Exception:
            pass
        note = QtWidgets.QLabel(
            "Controls how Spotify metadata becomes quiet hidden context and optional song-change commentary."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #9fb3c8;")
        layout.addWidget(note)

        preset_row = QtWidgets.QHBoxLayout()
        preset_row.setContentsMargins(0, 0, 0, 0)
        preset_row.setSpacing(8)
        self.hidden_sensory_preset_combo = QtWidgets.QComboBox()
        self.hidden_sensory_preset_combo.setObjectName("spotify_sense_hidden_preset_combo")
        self.hidden_sensory_preset_combo.setToolTip("Load a built-in or saved hidden sensory commentary style.")
        self.hidden_sensory_preset_combo.currentIndexChanged.connect(self._on_hidden_sensory_preset_selected)
        self.btn_hidden_sensory_save_as = QtWidgets.QPushButton("Save As")
        self.btn_hidden_sensory_save_as.setToolTip("Save the current hidden commentary style as a reusable preset.")
        self.btn_hidden_sensory_save_as.clicked.connect(self._save_hidden_sensory_style_as_preset)
        self.btn_hidden_sensory_add_quick = QtWidgets.QPushButton("Add Quick")
        self.btn_hidden_sensory_add_quick.setToolTip("Add the selected hidden sensory style to the quick row.")
        self.btn_hidden_sensory_add_quick.clicked.connect(self._on_hidden_sensory_add_quick_clicked)
        self.btn_hidden_sensory_remove_quick = QtWidgets.QPushButton("Remove Quick")
        self.btn_hidden_sensory_remove_quick.setToolTip("Remove the selected hidden sensory style from quick select.")
        self.btn_hidden_sensory_remove_quick.clicked.connect(self._on_hidden_sensory_remove_quick_clicked)
        preset_row.addWidget(self.hidden_sensory_preset_combo, 1)
        preset_row.addWidget(self.btn_hidden_sensory_save_as)
        preset_row.addWidget(self.btn_hidden_sensory_add_quick)
        preset_row.addWidget(self.btn_hidden_sensory_remove_quick)
        layout.addLayout(preset_row)

        quick_row = QtWidgets.QHBoxLayout()
        quick_row.setContentsMargins(0, 0, 0, 0)
        quick_row.setSpacing(6)
        quick_label = QtWidgets.QLabel("Quick")
        quick_label.setToolTip("Fast-switch hidden sensory commentary styles.")
        quick_row.addWidget(quick_label)
        self.hidden_sensory_quick_checkboxes = []
        for index in range(HIDDEN_SENSORY_QUICK_LIMIT):
            checkbox = QtWidgets.QCheckBox(f"{index + 1}. Empty")
            checkbox.setObjectName(f"spotify_sense_hidden_quick_{index + 1}")
            checkbox.toggled.connect(lambda checked, slot=index: self._on_hidden_sensory_quick_toggled(slot, checked))
            self.hidden_sensory_quick_checkboxes.append(checkbox)
            quick_row.addWidget(checkbox)
        quick_row.addStretch(1)
        layout.addLayout(quick_row)

        style_label = QtWidgets.QLabel("Comment style")
        style_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(style_label)
        self.hidden_commentary_style_edit = QtWidgets.QPlainTextEdit()
        self.hidden_commentary_style_edit.setObjectName("spotify_sense_hidden_commentary_style")
        self.hidden_commentary_style_edit.setMinimumHeight(58)
        self.hidden_commentary_style_edit.setMaximumHeight(86)
        self.hidden_commentary_style_edit.setPlaceholderText("Short prompt for how song-change comments should sound.")
        self.hidden_commentary_style_edit.setPlainText(self._current_hidden_commentary_style_prompt())
        self.hidden_commentary_style_edit.setToolTip(
            "Short prompt injected into hidden Spotify song-change snapshots. Right-click to refine or save as a preset."
        )
        self.hidden_commentary_style_edit.textChanged.connect(self._on_hidden_commentary_style_changed)
        self._install_hidden_sensory_refine_menu(
            self.hidden_commentary_style_edit,
            "Hidden Commentary Style",
            (
                "This controls brief hidden Spotify song-change comments. Keep it short, natural, "
                "specific to music metadata, and avoid generic or mechanical wording."
            ),
        )
        layout.addWidget(self.hidden_commentary_style_edit)

        self.source_guidance_edit = QtWidgets.QPlainTextEdit()
        self.source_guidance_edit.setObjectName("spotify_sense_source_guidance")
        self.source_guidance_edit.setMinimumHeight(90)
        self.source_guidance_edit.setPlainText(self._current_source_guidance())
        self.source_guidance_edit.setToolTip("Prompt fragment used when Spotify Sense contributes hidden sensory context.")
        self._install_hidden_sensory_refine_menu(
            self.source_guidance_edit,
            "Spotify Hidden Sensory Source Guidance",
            (
                "This is a source-level prompt fragment for NC hidden sensory PING/PONG. Preserve the metadata-only "
                "privacy boundary, sparse speaking rule, and natural song-change commentary behavior."
            ),
        )
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
        save_style_button = QtWidgets.QPushButton("Save Style")
        save_style_button.setToolTip("Save the short hidden commentary style prompt.")
        save_style_button.clicked.connect(lambda _checked=False: self._save_hidden_commentary_style(silent=False))
        row.addWidget(save_button)
        row.addWidget(reset_button)
        row.addWidget(save_style_button)
        row.addStretch(1)
        layout.addLayout(row)

        self.hidden_sensory_status_label = QtWidgets.QLabel("")
        self.hidden_sensory_status_label.setObjectName("spotify_sense_hidden_sensory_status")
        self.hidden_sensory_status_label.setWordWrap(True)
        self.hidden_sensory_status_label.setStyleSheet("color: #9fb3c8;")
        layout.addWidget(self.hidden_sensory_status_label)
        self._refresh_hidden_sensory_preset_controls(str(self.settings.data.get("hidden_sensory_preset_id") or ""))
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
        if str(key) in {"story_mode_background_music", "music_response_mode"}:
            self._sync_control_values()
        if str(key) in {"enabled", "song_change_monitor_enabled", "music_awareness_enabled", "include_paused_track_context", "music_response_mode", "story_mode_background_music"}:
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
        self._recent_hidden_comment_records = []
        self._hidden_comment_angle_cursor = 0
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

    def _on_play(self):
        def work():
            self._mark_user_music_change()
            return self._enrich_playback_change_result(
                self.client.play(device_id=self._selected_device_id()),
                fetch_current=True,
            )

        self._run_async("play", work)

    def _on_pause(self):
        def work():
            self._mark_user_music_change()
            return self.client.pause(device_id=self._selected_device_id())

        self._run_async("pause", work)

    def _on_next(self):
        def work():
            self._mark_user_music_change()
            return self._enrich_playback_change_result(
                self.client.next(device_id=self._selected_device_id()),
                fetch_current=True,
            )

        self._run_async("next", work)

    def _on_previous(self):
        def work():
            self._mark_user_music_change()
            return self._enrich_playback_change_result(
                self.client.previous(device_id=self._selected_device_id()),
                fetch_current=True,
            )

        self._run_async("previous", work)

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
        if kind in {"play", "pause", "next", "previous", "play_pause"} and result.get("ok"):
            current_track = dict(result.get("current_track") or {})
            if current_track.get("name"):
                self._cache_music_context(current_track)
                self._request_album_art_for_payload(current_track)
                if getattr(self, "current_track_label", None) is not None:
                    self.current_track_label.setText(self._track_sentence(current_track))
                self._publish_music_mood(current_track)
                self._set_status(f"Spotify action completed: {kind}. {self._track_sentence(current_track)}")
                return
            action_text = {
                "play": "Spotify playback resumed.",
                "pause": "Spotify playback paused.",
                "next": "Skipped to the next Spotify track.",
                "previous": "Went back to the previous Spotify track.",
                "play_pause": "Spotify playback toggled.",
            }.get(str(kind), f"Spotify action completed: {kind}.")
            self._set_status(action_text)
            self._request_music_context_refresh(force=True)
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
        if bool(self.settings.data.get("comment_on_song_changes", False)):
            response_allowed_at = max(now, float(self._last_track_comment_at or 0.0) + max(0, cooldown))
            response_ready = now >= response_allowed_at
            self._pending_track_change_context = {
                "changed_at": now,
                "response_allowed_at": response_allowed_at,
                "track": self._music_context_payload_from_track(track),
                "commentary": self._commentary_for_track(track),
            }
            if response_ready:
                self._last_track_comment_at = now
                self._set_status(self._commentary_for_track(track))
            else:
                remaining = max(1, int(round(response_allowed_at - now)))
                self._set_status(f"Spotify track changed. Commentary is queued for the latest track after {remaining}s.")

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

    def _build_music_context_text(
        self,
        payload: dict[str, Any],
        *,
        consume_pending: bool = False,
        include_pending_track_change: bool = True,
    ) -> str:
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
        if (
            include_pending_track_change
            and pending
            and bool(self.settings.data.get("comment_on_song_changes", False))
            and self._pending_track_change_response_ready(pending)
        ):
            pending_track = dict(pending.get("track") or {})
            lines.append(
                "Recent Spotify music update is available: "
                f"{pending_track.get('track') or payload.get('track') or 'Unknown track'}; "
                "if it is useful to mention, react to the feel of the music instead of announcing that the song changed."
            )
            style_prompt = self._current_hidden_commentary_style_prompt()
            if style_prompt:
                lines.append(f"Preferred music commentary style: {style_prompt}")
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

    def _pending_track_change_response_ready(self, pending: dict[str, Any] | None, *, now: float | None = None) -> bool:
        payload = dict(pending or {})
        if not payload:
            return False
        current_time = float(now if now is not None else time.time())
        allowed_at = float(payload.get("response_allowed_at") or payload.get("changed_at") or 0.0)
        return current_time >= allowed_at

    def _hidden_comment_track_key(self, payload: dict[str, Any]) -> str:
        data = dict(payload or {})
        uri = str(data.get("uri") or "").strip().lower()
        if uri:
            return uri
        track = re.sub(r"\s+", " ", str(data.get("track") or data.get("name") or "").strip().lower())
        artists = "|".join(
            re.sub(r"\s+", " ", str(item or "").strip().lower())
            for item in list(data.get("artists") or [])
            if str(item or "").strip()
        )
        return "|".join(item for item in (track, artists) if item)

    def _prune_recent_hidden_comment_records(self, *, now: float | None = None) -> list[dict[str, Any]]:
        current_time = float(now if now is not None else time.time())
        records = []
        for record in list(self._recent_hidden_comment_records or [])[-32:]:
            try:
                created_at = float(record.get("created_at", 0.0) or 0.0)
            except Exception:
                created_at = 0.0
            if current_time - created_at <= 7200.0:
                records.append(dict(record))
        self._recent_hidden_comment_records = records[-24:]
        return list(self._recent_hidden_comment_records)

    def _recent_hidden_comment_angles(self) -> list[str]:
        records = self._prune_recent_hidden_comment_records()
        angles = []
        for record in records[-10:]:
            angle = str(record.get("angle") or "").strip()
            if angle and angle not in angles:
                angles.append(angle)
        return angles

    def _hidden_comment_already_offered_for_track(self, track_key: str, *, now: float | None = None) -> bool:
        if not track_key:
            return False
        current_time = float(now if now is not None else time.time())
        for record in self._prune_recent_hidden_comment_records(now=current_time):
            if str(record.get("track_key") or "") != track_key:
                continue
            try:
                created_at = float(record.get("created_at", 0.0) or 0.0)
            except Exception:
                created_at = 0.0
            if current_time - created_at <= 7200.0:
                return True
        return False

    def _next_hidden_comment_angle(self) -> str:
        recent = set(self._recent_hidden_comment_angles()[-12:])
        total = len(SPOTIFY_HIDDEN_COMMENT_ANGLES)
        if total <= 0:
            return "natural music reaction"
        for offset in range(total):
            index = (int(self._hidden_comment_angle_cursor or 0) + offset) % total
            angle = SPOTIFY_HIDDEN_COMMENT_ANGLES[index]
            if angle not in recent or offset >= total - 1:
                self._hidden_comment_angle_cursor = (index + 1) % total
                return angle
        angle = SPOTIFY_HIDDEN_COMMENT_ANGLES[int(self._hidden_comment_angle_cursor or 0) % total]
        self._hidden_comment_angle_cursor = (int(self._hidden_comment_angle_cursor or 0) + 1) % total
        return angle

    def _remember_hidden_comment_offer(self, *, track_key: str, payload: dict[str, Any], angle: str, now: float) -> None:
        if not track_key:
            return
        self._prune_recent_hidden_comment_records(now=now)
        self._recent_hidden_comment_records.append(
            {
                "created_at": float(now),
                "track_key": str(track_key),
                "track": str((payload or {}).get("track") or ""),
                "artists": list((payload or {}).get("artists") or []),
                "angle": str(angle or ""),
            }
        )
        self._recent_hidden_comment_records = self._recent_hidden_comment_records[-24:]

    def _hidden_comment_brief(self, payload: dict[str, Any], *, angle: str) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "track": str(data.get("track") or "Unknown track"),
            "artists": [str(item) for item in list(data.get("artists") or []) if str(item or "").strip()],
            "album": str(data.get("album") or ""),
            "mood_hint": str(data.get("mood_hint") or "neutral"),
            "is_playing": bool(data.get("is_playing", False)),
            "angle": str(angle or "natural music reaction"),
            "reaction_goal": "React to the feel of the music in one fresh sentence; do not announce that the song changed.",
        }

    def capture_sensory_snapshot(self, _capture_context=None):
        pending = dict(self._pending_track_change_context or {})
        payload = self._current_music_context_payload()
        if not payload and pending:
            payload = dict(pending.get("track") or {})
        if not payload:
            return None
        now = time.time()
        hidden_cooldown = int(self.settings.data.get("hidden_response_cooldown_seconds", 300) or 300)
        hidden_ready = now - float(self._last_hidden_response_snapshot_at or 0.0) >= hidden_cooldown
        pending_ready = self._pending_track_change_response_ready(pending, now=now)
        can_offer_hidden_response = (
            bool(self.settings.data.get("comment_on_song_changes", False))
            and bool(pending)
            and pending_ready
            and hidden_ready
        )
        if not can_offer_hidden_response:
            # Normal chat still receives Spotify context through collect_chat_context().
            # The hidden PING/PONG loop should only get Spotify when a fresh,
            # cooldown-approved music comment is available.
            return None
        track_key = self._hidden_comment_track_key(payload)
        if self._hidden_comment_already_offered_for_track(track_key, now=now):
            self._pending_track_change_context = None
            self._debug_log("hidden_spotify_comment_suppressed", {"reason": "track_already_offered", "track_key": track_key})
            return None
        angle = self._next_hidden_comment_angle()
        comment_brief = self._hidden_comment_brief(payload, angle=angle)
        recent_angles_before = self._recent_hidden_comment_angles()
        self._last_hidden_response_snapshot_at = now
        self._last_track_comment_at = max(float(self._last_track_comment_at or 0.0), now)
        self._remember_hidden_comment_offer(track_key=track_key, payload=payload, angle=angle, now=now)
        self._pending_track_change_context = None
        style_prompt = self._current_hidden_commentary_style_prompt()
        content_text = (
            self._build_music_context_text(payload, consume_pending=False, include_pending_track_change=False)
            + "\nFresh Spotify music-reaction opportunity is allowed now. "
            "The track-change event may already have been acknowledged elsewhere. "
            "Do not say 'song changed', 'track changed', 'now playing', or use the formula "
            "'Song changed to <title> by <artist>'. "
            "For this hidden PONG, return should_speak=true and set proactive_candidate "
            "to one brief, natural music reaction. React to the track's feel, not the event notification. "
            "Do not mention Spotify internals or claim "
            "to hear raw audio."
        )
        if style_prompt:
            content_text += f"\nCommentary style: {style_prompt}"
        content_text += (
            "\nMusic reaction brief: "
            + json.dumps(comment_brief, ensure_ascii=True, sort_keys=True)
            + f"\nUse this response angle: {angle}."
        )
        if recent_angles_before:
            content_text += "\nAvoid recent response angles: " + ", ".join(recent_angles_before[-8:]) + "."
        content_text += "\nAvoid these openings: " + ", ".join(SPOTIFY_HIDDEN_FORBIDDEN_OPENINGS) + "."
        recent_angles_after = self._recent_hidden_comment_angles()
        return {
            "source": SENSORY_PROVIDER_ID,
            "captured_at": now,
            "content": content_text,
            "content_text": content_text,
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
                "proactive_candidate": "",
                "comment_brief": comment_brief,
                "comment_angle": angle,
                "recent_comment_angles": recent_angles_after,
                "forbidden_openings": list(SPOTIFY_HIDDEN_FORBIDDEN_OPENINGS),
                "commentary_style_prompt": style_prompt,
                "should_speak_recommended": True,
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
        if not bool(self.settings.data.get("enabled", False)):
            return {"ok": True, "handled": False, "reason": "disabled"} if report_misses else None
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
        if not bool(self.settings.data.get("enabled", False)):
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
                and capability_name not in {"spotify.duck.start", "spotify.duck.end", "spotify.story_hook"}
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
            story_device_id = str(payload.get("device_id") or "").strip() or None
            return self._story_hook(payload, device_id=story_device_id)
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

    def _next_story_transition_generation(self) -> int:
        with self._story_transition_lock:
            self._story_transition_generation += 1
            return int(self._story_transition_generation)

    def _story_transition_is_current(self, generation: int) -> bool:
        with self._story_transition_lock:
            return int(generation) == int(self._story_transition_generation)

    def _duck_is_active(self) -> bool:
        return self._remembered_volume is not None

    def _set_duck_restore_volume(self, volume: int, device_id: str | None) -> None:
        if self._remembered_volume is None:
            return
        self._remembered_volume = max(0, min(100, int(volume)))
        if device_id:
            self._remembered_duck_device_id = device_id

    def _duck_target_volume(self, previous_volume: int) -> int:
        previous = max(0, min(100, int(previous_volume)))
        try:
            configured = max(0, min(100, int(self.settings.data.get("duck_volume_percent", 15) or 15)))
        except Exception:
            configured = 15
        if previous <= 0:
            return 0
        if configured < previous:
            return configured
        minimum_drop = max(1, min(10, max(3, int(round(previous * 0.25)))))
        return max(0, previous - minimum_drop)

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
            self._debug_log("duck_start_skipped", {"reason": "disabled"})
            return {"ok": True, "ducked": False, "message": "Lower music while NC speaks is disabled."}
        if self._duck_is_active():
            target_volume = self._duck_target_volume(int(self._remembered_volume or 0))
            device_id = self._remembered_duck_device_id or str(self.settings.data.get("default_device_id") or "").strip() or None
            result = self._set_volume_smooth(
                start=int(self._remembered_volume or target_volume),
                target=target_volume,
                device_id=device_id,
                duration_ms=0,
                reason="tts_duck_start_refresh",
            )
            self._debug_log(
                "duck_start_refresh",
                {"device_id": device_id, "previous_volume": self._remembered_volume, "target_volume": target_volume, "result": result},
            )
            return {
                "ok": bool(result.get("ok")),
                "ducked": bool(result.get("ok")),
                "already_active": True,
                "previous_volume": self._remembered_volume,
                "target_volume": target_volume,
                "result": result,
            }
        device_id = str(self.settings.data.get("default_device_id") or "").strip() or None
        state = self.client.get_playback_state()
        device = (state.get("data") or {}).get("device") or {} if isinstance(state, dict) and state.get("ok") else {}
        state_error = None if isinstance(state, dict) and state.get("ok") else dict(state or {})
        if not device_id:
            device_id = str(device.get("id") or "").strip() or None
        try:
            self._remembered_volume = int(device.get("volume_percent"))
        except Exception:
            self._remembered_volume = int(self.settings.data.get("default_volume") or 30)
        self._remembered_duck_device_id = device_id
        target_volume = self._duck_target_volume(self._remembered_volume)
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
            {
                "device_id": device_id,
                "previous_volume": self._remembered_volume,
                "target_volume": target_volume,
                "duration_ms": duration_ms,
                "state_error": state_error,
                "result": result,
            },
        )
        if not bool(result.get("ok")):
            self._remembered_volume = None
            self._remembered_duck_device_id = None
        return {
            "ok": bool(result.get("ok")),
            "ducked": bool(result.get("ok")),
            "previous_volume": self._remembered_volume if bool(result.get("ok")) else None,
            "target_volume": target_volume,
            "state_error": state_error,
            "result": result,
        }

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
        mood = self._story_music_mood(payload)
        music_kind = self._story_music_kind(payload)
        query = str(payload.get("query") or self._story_query_for_mood(mood, music_kind=music_kind, payload=payload)).strip()
        preferred_type = "playlist" if music_kind == "ambient" or bool(payload.get("prefer_ambient", self.settings.data.get("story_music_prefer_ambient", True))) else "track"
        requested_device_id = str(device_id or "").strip() or None
        configured_device_id = str(self.settings.data.get("default_device_id") or "").strip() or None
        state = self.client.get_playback_state()
        device = dict((state.get("data") or {}).get("device") or {}) if isinstance(state, dict) and state.get("ok") else {}
        active_device_id = str(device.get("id") or "").strip() or None
        device_id = requested_device_id or active_device_id or configured_device_id
        try:
            start_volume = int(device.get("volume_percent"))
        except Exception:
            start_volume = int(self.settings.data.get("default_volume") or 30)
        target_volume = max(0, min(100, int(self.settings.data.get("story_music_target_volume") or 30)))
        floor_volume = max(0, min(100, int(self.settings.data.get("story_music_transition_floor_volume") or 8)))
        fade_down_ms = max(0, int(self.settings.data.get("story_music_fade_down_ms") or 0))
        fade_up_ms = max(0, int(self.settings.data.get("story_music_fade_up_ms") or 0))
        generation = self._next_story_transition_generation()
        fade = {
            "from": start_volume,
            "floor": floor_volume,
            "target": target_volume,
            "down_ms": fade_down_ms,
            "up_ms": fade_up_ms,
        }
        self._debug_log(
            "story_music_request",
            {
                "query": query,
                "mood": mood,
                "music_kind": music_kind,
                "preferred_type": preferred_type,
                "requested_device": bool(requested_device_id),
                "active_device": bool(active_device_id),
                "using_device": bool(device_id),
                "fade": fade,
            },
        )

        def run_transition() -> dict[str, Any]:
            down_result = self._set_volume_blocking(
                start=start_volume,
                target=floor_volume,
                device_id=device_id,
                duration_ms=fade_down_ms,
                reason="story_music_fade_down",
                generation=generation,
                is_current=self._story_transition_is_current,
            )
            if not down_result.get("ok"):
                self._debug_log(
                    "story_music_transition_failed",
                    {"stage": "fade_down", "query": query, "mood": mood, "music_kind": music_kind, "result": down_result},
                )
                return down_result
            play_result = self.client.play(query=query, device_id=device_id, preferred_type=preferred_type)
            playback_ok = bool(isinstance(play_result, dict) and play_result.get("ok"))
            if not playback_ok:
                self._debug_log(
                    "story_music_transition_failed",
                    {"stage": "play", "query": query, "mood": mood, "music_kind": music_kind, "result": play_result},
                )
            if playback_ok and self._duck_is_active():
                self._debug_log(
                    "story_music_transition_ducked",
                    {
                        "query": query,
                        "mood": mood,
                        "music_kind": music_kind,
                        "fade": fade,
                        "play_result": play_result,
                        "restore_volume_preserved": self._remembered_volume,
                    },
                )
                return {
                    "ok": True,
                    "playback": play_result,
                    "fade_up": {"ok": True, "skipped": True, "reason": "tts_duck_active"},
                }
            up_result = self._set_volume_blocking(
                start=floor_volume,
                target=target_volume,
                device_id=device_id,
                duration_ms=fade_up_ms,
                reason="story_music_fade_up",
                generation=generation,
                is_current=self._story_transition_is_current,
                cancel_if_duck_active=True,
            )
            self._debug_log(
                "story_music_transition",
                {"query": query, "mood": mood, "music_kind": music_kind, "fade": fade, "play_result": play_result, "up_result": up_result},
            )
            return {"ok": playback_ok, "playback": play_result, "fade_up": up_result}

        if fade_down_ms > 0 or fade_up_ms > 0:
            threading.Thread(target=run_transition, name="SpotifySenseStoryMusic", daemon=True).start()
            return {
                "ok": True,
                "accepted": True,
                "started": False,
                "transitioning": True,
                "query": query,
                "mood": mood,
                "music_kind": music_kind,
                "preferred_type": preferred_type,
                "fade": fade,
            }

        transition_result = run_transition()
        playback = dict(transition_result.get("playback") or {}) if isinstance(transition_result.get("playback"), dict) else {}
        return {
            "ok": bool(transition_result.get("ok")),
            "started": bool(transition_result.get("ok")),
            "query": query,
            "mood": mood,
            "music_kind": music_kind,
            "preferred_type": preferred_type,
            "fade": fade,
            "playback": playback,
            "selected_item": playback.get("selected_item"),
        }

    def _set_volume_blocking(
        self,
        *,
        start: int,
        target: int,
        device_id: str | None,
        duration_ms: int,
        reason: str,
        generation: int,
        is_current: Callable[[int], bool] | None = None,
        cancel_if_duck_active: bool = False,
    ) -> dict[str, Any]:
        start_value = max(0, min(100, int(start)))
        target_value = max(0, min(100, int(target)))
        duration = max(0, int(duration_ms or 0))
        if duration <= 0 or start_value == target_value:
            result = self.client.set_volume(target_value, device_id=device_id)
            self._debug_log("story_volume_set", {"reason": reason, "volume": target_value, "device_id": device_id, "result": result})
            return result
        steps = max(2, min(16, int(round(duration / 120.0)) or 2))
        sleep_seconds = duration / 1000.0 / steps
        last_result: dict[str, Any] = {"ok": True}
        current_checker = is_current or self._volume_transition_is_current
        for index in range(1, steps + 1):
            if not current_checker(generation):
                return {"ok": False, "cancelled": True, "reason": reason}
            if cancel_if_duck_active and self._duck_is_active():
                return {"ok": True, "skipped": True, "reason": "tts_duck_active"}
            fraction = index / float(steps)
            volume = int(round(start_value + ((target_value - start_value) * fraction)))
            last_result = self.client.set_volume(volume, device_id=device_id)
            if not bool(isinstance(last_result, dict) and last_result.get("ok")):
                return last_result if isinstance(last_result, dict) else {"ok": False, "error": "Spotify volume update failed."}
            if index < steps:
                time.sleep(sleep_seconds)
        return last_result

    def _story_music_mood(self, payload: dict[str, Any]) -> str:
        text = " ".join(
            str(payload.get(key) or "")
            for key in ("mood", "scene", "location", "latest_visible_beat", "image_intent", "query")
        ).lower()
        tension = self._story_tension_level(payload)
        if any(word in text for word in ("coding", "focus", "study", "deep work")):
            return "focus"
        if self._story_text_has_word(text, ("battle", "chase", "attack", "dragon", "war", "explosion")) or tension >= 8:
            return "epic"
        if any(word in text for word in ("horror", "terror", "dread", "monster", "blood", "haunted")):
            return "dark"
        if any(word in text for word in ("mystery", "tense curiosity", "sigil", "archive", "sealed", "lantern", "secret", "unknown")):
            return "mystery"
        if any(word in text for word in ("sad", "grief", "loss", "lonely", "melancholy")):
            return "sad"
        if any(word in text for word in ("calm", "peaceful", "safe", "tavern", "rest", "gentle")) and tension <= 4:
            return "calm"
        if tension >= 6:
            return "mystery"
        return "fantasy"

    def _story_tension_level(self, payload: dict[str, Any]) -> int:
        for key in ("tension_level", "tension", "intensity"):
            try:
                return max(0, min(10, int(float(payload.get(key)))))
            except Exception:
                continue
        return 3

    def _story_music_kind(self, payload: dict[str, Any]) -> str:
        raw = str(payload.get("music_kind") or payload.get("kind") or "").strip().lower()
        if raw in {"ambient", "ambience", "music"}:
            return "ambient" if raw in {"ambient", "ambience"} else "music"
        if bool(payload.get("prefer_ambient", self.settings.data.get("story_music_prefer_ambient", True))):
            if self._story_tension_level(payload) < 8:
                return "ambient"
        mood = self._story_music_mood(payload)
        return "music" if mood == "epic" else "ambient"

    def _story_query_for_mood(self, mood: str, *, music_kind: str = "ambient", payload: dict[str, Any] | None = None) -> str:
        kind = str(music_kind or "ambient").strip().lower()
        mapping = {
            "dark": "dark cinematic ambient story ambience",
            "mystery": "mysterious cinematic ambient story ambience",
            "epic": "epic fantasy adventure story music",
            "calm": "calm cinematic fantasy story ambience",
            "sad": "melancholy cinematic ambient story ambience",
            "focus": str(self.settings.data.get("coding_mode_query") or "relaxing focus music"),
        }
        if kind == "music" and str(mood or "").lower() not in {"focus"}:
            return {
                "dark": "dark cinematic story music",
                "mystery": "mysterious cinematic story music",
                "epic": "epic fantasy adventure story music",
                "calm": "calm fantasy story music",
                "sad": "melancholy orchestral story music",
            }.get(str(mood or "").lower(), "cinematic fantasy story music")
        return mapping.get(str(mood or "").lower(), "cinematic fantasy story ambience")

    @staticmethod
    def _story_text_has_word(text: str, words: tuple[str, ...]) -> bool:
        haystack = str(text or "").lower()
        for word in words:
            needle = str(word or "").strip().lower()
            if needle and re.search(rf"\b{re.escape(needle)}\b", haystack):
                return True
        return False

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
