from __future__ import annotations

import http.server
from PySide6 import QtCore, QtGui
import json
import re
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Callable

from core.sensory_prompt_defaults import resolve_prompt

from addons.spotify_sense.intent_router import infer_music_mood, route_music_intent
from addons.spotify_sense.settings import (
    DEFAULT_HIDDEN_COMMENTARY_STYLE_PROMPT,
    DEFAULT_MUSIC_CONVERSATION_PROMPT,
    DEFAULT_SETTINGS,
    TOKEN_KEYS,
    SpotifySenseSettings,
)
from addons.spotify_sense.spotify_client import SpotifySenseClient


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
SENSORY_BEHAVIOR_CONTRIBUTOR_ID = "nc.spotify_sense.behavior"
DEFAULT_SPOTIFY_SOURCE_GUIDANCE = (
    "Spotify Sense supplies metadata, not raw audio or a user request. Ground music references in the supplied track title, "
    "artists, album, playback state, and mood hint. For hidden snapshots, speak only when hidden_response_allowed=true "
    "or should_speak_recommended=true; preserve the supplied commentary style and [sensory_action:spotify_sense] tag. "
    "Otherwise set should_speak=false."
)
SPOTIFY_HIDDEN_BEHAVIOR_PROMPT = (
    "For spotify_sense hidden PINGs, set should_speak=true only when hidden_response_allowed=true or "
    "should_speak_recommended=true. Include [sensory_action:spotify_sense] in tags. In proactive_candidate, instruct "
    "the assistant to write one brief natural sentence grounded in the supplied track title and artists, following "
    "commentary_style_prompt, with no introduction, question, follow-up, raw-audio claim, or song-change announcement. "
    "Otherwise set should_speak=false and proactive_candidate=\"\"."
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



def _spotify_sense_tab_icon(icon_key: str, accent_hex: str) -> QtGui.QIcon:
    accent = QtGui.QColor(str(accent_hex or "#22c55e"))
    if not accent.isValid():
        accent = QtGui.QColor("#22c55e")
    canvas = QtGui.QPixmap(36, 36)
    canvas.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(canvas)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    pen = QtGui.QPen(accent, 2.4, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(QtCore.Qt.NoBrush)

    key = str(icon_key or "").strip().lower()
    if key == "overview":
        painter.drawEllipse(QtCore.QRectF(8, 8, 20, 20))
        painter.drawEllipse(QtCore.QRectF(15, 15, 6, 6))
        painter.drawLine(18, 4, 18, 10)
        painter.drawLine(18, 26, 18, 32)
        painter.drawLine(4, 18, 10, 18)
        painter.drawLine(26, 18, 32, 18)
    elif key == "connect":
        painter.drawRoundedRect(QtCore.QRectF(9, 14, 18, 12), 4, 4)
        painter.drawLine(14, 10, 14, 14)
        painter.drawLine(22, 10, 22, 14)
        painter.drawLine(18, 26, 18, 31)
    elif key == "playback":
        path = QtGui.QPainterPath()
        path.moveTo(13, 9)
        path.lineTo(27, 18)
        path.lineTo(13, 27)
        path.closeSubpath()
        painter.setBrush(QtGui.QBrush(accent))
        painter.drawPath(path)
        painter.setBrush(QtCore.Qt.NoBrush)
    elif key == "awareness":
        painter.drawEllipse(QtCore.QRectF(6, 11, 24, 14))
        painter.drawEllipse(QtCore.QRectF(14, 15, 8, 6))
    elif key == "ducking":
        painter.drawRect(QtCore.QRectF(7, 14, 6, 8))
        speaker = QtGui.QPainterPath()
        speaker.moveTo(13, 14)
        speaker.lineTo(22, 8)
        speaker.lineTo(22, 28)
        speaker.lineTo(13, 22)
        speaker.closeSubpath()
        painter.drawPath(speaker)
        painter.drawArc(QtCore.QRectF(20, 11, 11, 14), -45 * 16, 90 * 16)
    elif key == "story":
        painter.drawRoundedRect(QtCore.QRectF(8, 8, 20, 22), 3, 3)
        painter.drawLine(18, 8, 18, 30)
        painter.drawLine(11, 14, 15, 14)
        painter.drawLine(21, 14, 25, 14)
    elif key == "hidden":
        painter.drawEllipse(QtCore.QRectF(7, 7, 22, 22))
        painter.drawEllipse(QtCore.QRectF(14, 14, 8, 8))
        painter.drawLine(18, 3, 18, 9)
        painter.drawLine(18, 27, 18, 33)
        painter.drawLine(3, 18, 9, 18)
        painter.drawLine(27, 18, 33, 18)
    elif key == "advanced":
        for x, y in ((10, 12), (18, 22), (26, 15)):
            painter.drawLine(x, 7, x, 29)
            painter.drawEllipse(QtCore.QRectF(x - 3, y - 3, 6, 6))
    else:
        painter.drawRoundedRect(QtCore.QRectF(8, 8, 20, 20), 5, 5)

    painter.end()
    return QtGui.QIcon(canvas)


class _OAuthHTTPServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True



class _OAuthServerResource:
    def __init__(self, server) -> None:
        self._server = server

    def close(self) -> None:
        try:
            self._server.shutdown()
        finally:
            self._server.server_close()


class SpotifySenseController(QtCore.QObject):
    oauth_callback_received = QtCore.Signal(dict)
    async_result_ready = QtCore.Signal(str, dict)
    status_message = QtCore.Signal(str)

    def __init__(self, context):
        super().__init__()
        self.context = context
        self.settings = SpotifySenseSettings(context.storage)
        self.client = SpotifySenseClient(self.settings)
        self._widgets = []
        self._controls = {}
        self._oauth_server = None
        self._last_track_id = ""
        self._last_track_comment_at = 0.0
        self._remembered_volume: int | None = None
        self._remembered_duck_device_id: str | None = None
        self._pending_duck_restore: tuple[int, int, str | None] | None = None
        self._duck_start_pending = False
        self._cached_music_context: dict[str, Any] = {}
        self._native_current_track: dict[str, Any] = {}
        self._native_devices: list[dict[str, Any]] = []
        self._native_playlists: list[dict[str, Any]] = []
        self._native_artist: dict[str, Any] = {}
        self._native_discovery: list[dict[str, Any]] = []
        self._native_dashboard_loading = False
        self._native_dashboard_error = ""
        self._native_status = "Spotify Sense is ready."
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
        self._generation_lock = threading.RLock()
        self._closing = False
        self._ui_target_key = "spotify.controller"
        self._ui_target = context.ui_dispatcher.bind_target(self._ui_target_key, self)
        self._sensory_provider_registered = False
        self._sensory_contributor_registered = False
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

    def _spawn_owned(self, name: str, target):
        tasks = self.context.tasks if self.context is not None else None
        if tasks is None:
            raise RuntimeError("Spotify Sense requires an addon task owner.")
        return tasks.spawn(name, target)

    def _post_ui(self, callback, *, target=None) -> bool:
        with self._generation_lock:
            if self._closing:
                return False
            try:
                self.context.ui_dispatcher.post(callback, target=target or self._ui_target)
            except Exception:
                return False
        return True

    def _register_sensory_provider(self):
        service = self.context.capabilities.sensory_targets if self.context is not None else None
        if service is None:
            return
        try:
            service.register_provider(
                provider_id=SENSORY_PROVIDER_ID,
                label="Spotify Sense",
                instruction=(
                    "Hidden music awareness from Spotify metadata. Treat it as ambient context only; "
                    "do not claim to hear raw audio. Snapshot metadata supplies track details, "
                    "commentary style, and whether a fresh song-change reaction is allowed."
                ),
                description="Current Spotify track metadata for music-aware chat and optional hidden sensory feedback.",
                order=340,
                capture_handler=self.capture_sensory_snapshot,
                metadata={
                    "kind": "music",
                    "provider": "spotify",
                    "text_only": True,
                    "hide_vision_source_tab": True,
                    "pingpong_prompt": DEFAULT_SPOTIFY_SOURCE_GUIDANCE,
                },
            )
            self._sensory_provider_registered = True
            self._register_sensory_behavior_contributor()
        except Exception as exc:
            try:
                self.context.logger.warning("[SpotifySense] Could not register sensory provider: %s", exc)
            except Exception:
                pass

    def _register_sensory_behavior_contributor(self):
        service = self.context.capabilities.sensory_targets if self.context is not None else None
        if service is None:
            return
        try:
            service.register_prompt_contributor(
                contributor_id=SENSORY_BEHAVIOR_CONTRIBUTOR_ID,
                source_id=SENSORY_PROVIDER_ID,
                label="Spotify Sense",
                prompt=SPOTIFY_HIDDEN_BEHAVIOR_PROMPT,
                order=345,
                metadata={
                    "type": "behavior_rule",
                    "behavior_count": 1,
                    "active_behaviors": [
                        {
                            "trigger": "Spotify Sense hidden music reaction opportunity is allowed.",
                            "action": "Write one brief sentence about the supplied track title and artists using the current commentary style; no introduction, question, or follow-up.",
                            "repeat_mode": "One-off",
                            "repeat_interval": 1,
                        }
                    ],
                },
            )
            self._sensory_contributor_registered = True
        except Exception as exc:
            try:
                self.context.logger.warning("[SpotifySense] Could not register sensory behavior prompt: %s", exc)
            except Exception:
                pass

    def _unregister_sensory_behavior_contributor(self):
        if not self._sensory_contributor_registered:
            return
        service = self.context.capabilities.sensory_targets if self.context is not None else None
        if service is not None:
            try:
                service.unregister_prompt_contributor(SENSORY_BEHAVIOR_CONTRIBUTOR_ID)
            except Exception:
                pass
        self._sensory_contributor_registered = False

    def _unregister_sensory_provider(self):
        self._unregister_sensory_behavior_contributor()
        if not self._sensory_provider_registered:
            return
        service = self.context.capabilities.sensory_targets if self.context is not None else None
        if service is not None:
            try:
                service.unregister_provider(SENSORY_PROVIDER_ID)
            except Exception:
                pass
        self._sensory_provider_registered = False

    def _sync_activation_presentation(self) -> str:
        enabled = bool(self.settings.data.get("enabled", False))
        configured = bool(str(self.settings.data.get("client_id") or "").strip())
        connected = bool(self.client.is_connected())
        account = str(
            self.settings.data.get("account_display_name")
            or self.settings.data.get("account_id")
            or "Spotify account"
        ).strip()

        toggle = getattr(self, "enable_checkbox", None)
        if toggle is not None and hasattr(toggle, "setText"):
            toggle.setText(f"Spotify Sense: {'ON' if enabled else 'OFF'}")

        if not configured:
            text = (
                "Spotify Sense is ON, but setup is incomplete. Add a Spotify Developer app Client ID, then connect."
                if enabled
                else "Spotify Sense is OFF. Add a Spotify Developer app Client ID, then connect."
            )
        elif not connected:
            text = (
                "Spotify Sense is ON, but Spotify is not connected; use Login / Connect."
                if enabled
                else "Spotify Sense is OFF. Spotify is not connected; use Login / Connect."
            )
        elif enabled:
            text = f"Spotify Sense is ON and connected as {account}."
        else:
            text = f"Spotify Sense is OFF. Connected as {account}."

        status = getattr(self, "activation_status_label", None)
        if status is not None and hasattr(status, "setText"):
            status.setText(text)
            if enabled and connected:
                status.setStyleSheet("color: #86efac; font-weight: 700;")
            elif enabled or connected:
                status.setStyleSheet("color: #facc15; font-weight: 700;")
            else:
                status.setStyleSheet("color: #9fb3c8; font-weight: 700;")
        return text

    def _runtime_config_service(self):
        return self.context.capabilities.runtime_config if self.context is not None else None

    def _debug_log_path(self) -> Path:
        storage = self.context.storage if self.context is not None else None
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
        return resolve_prompt(
            self._source_guidance_map().get(SENSORY_PROVIDER_ID, ""),
            DEFAULT_SPOTIFY_SOURCE_GUIDANCE,
            legacy_hashes=(
                "926a7634da64fc43b3b4fd4c23ef129c97ad089d587895cbd38cc3e9a34b2114",
                "d6e156f23a6f843e5f7b69533ee37b1b9dbc65d177f173f2d6a7e164947f6d85",
            ),
        )

    def _notify_shell_settings_changed(self):
        try:
            sensory_targets = self.context.capabilities.sensory_targets if self.context is not None else None
            if sensory_targets is not None:
                sensory_targets.notify_settings_changed()
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

    def _current_hidden_commentary_style_prompt(self) -> str:
        editor = getattr(self, "hidden_commentary_style_edit", None)
        if editor is not None and hasattr(editor, "toPlainText"):
            text = str(editor.toPlainText() or "").strip()
            if not text:
                text = str(self.settings.data.get("hidden_commentary_style_prompt") or "").strip()
        else:
            text = str(self.settings.data.get("hidden_commentary_style_prompt") or "").strip()
        return text or DEFAULT_HIDDEN_COMMENTARY_STYLE_PROMPT

    def _current_music_conversation_prompt(self) -> str:
        editor = getattr(self, "music_conversation_prompt_edit", None)
        if editor is not None and hasattr(editor, "toPlainText"):
            text = str(editor.toPlainText() or "").strip()
            if not text:
                text = str(self.settings.data.get("music_conversation_prompt") or "").strip()
        else:
            text = str(self.settings.data.get("music_conversation_prompt") or "").strip()
        return text or DEFAULT_MUSIC_CONVERSATION_PROMPT

    def _save_music_conversation_prompt(self, *, silent: bool = False):
        prompt = self._current_music_conversation_prompt()
        self.settings.update(music_conversation_prompt=prompt)
        if not silent:
            self._set_hidden_sensory_status("Spotify music-conversation prompt saved.")

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

    def _save_hidden_commentary_style(self, *, silent: bool = False):
        timer = getattr(self, "_hidden_style_save_timer", None)
        if timer is not None and hasattr(timer, "isActive") and timer.isActive():
            timer.stop()
        prompt = self._current_hidden_commentary_style_prompt()
        self.settings.update(hidden_commentary_style_prompt=prompt)
        if not silent:
            self._set_hidden_sensory_status("Hidden commentary style saved.")

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
        self._set_status(self._sync_activation_presentation())

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
                controller._queue_oauth_callback(payload)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h3>Spotify Sense connected.</h3>"
                    b"<p>You can return to NeuralCompanion.</p></body></html>"
                )
                controller._spawn_owned(
                    "oauth-callback-close",
                    lambda _cancel: self.server.shutdown(),
                )

            def log_message(self, _format, *_args):
                return

        try:
            server = _OAuthHTTPServer((host, port), CallbackHandler)
        except Exception as exc:
            return {"ok": False, "error": f"Could not start local Spotify callback on {host}:{port}: {exc}"}
        self._oauth_server = server
        self.context.tasks.register_resource("oauth-server", _OAuthServerResource(server))
        self._spawn_owned("oauth-server", lambda _cancel: server.serve_forever())
        return {"ok": True}

    @QtCore.Slot(dict)
    def _handle_oauth_callback(self, payload: dict[str, Any]):
        if payload.get("error"):
            self._set_status(f"Spotify authorization cancelled or rejected: {payload.get('error')}")
            return
        code = str(payload.get("code") or "")
        state = str(payload.get("state") or "")
        self._run_async("oauth", lambda: self.client.exchange_code(code, state))

    def _queue_oauth_callback(self, payload: dict[str, Any]) -> bool:
        callback_payload = dict(payload or {})
        return self._post_ui(
            lambda: self._handle_oauth_callback(callback_payload),
        )

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

    def _on_dashboard_refresh(self):
        if self._native_dashboard_loading:
            return
        self._native_dashboard_loading = True
        self._native_dashboard_error = ""
        self._run_async("music_hub", self._fetch_music_hub)

    def _on_play_context(self, uri: str):
        context_uri = str(uri or "").strip()
        if not context_uri:
            raise ValueError("A Spotify playlist or album URI is required.")

        def work():
            self._mark_user_music_change()
            return self._enrich_playback_change_result(
                self.client.play(
                    context_uri=context_uri,
                    device_id=self._selected_device_id(),
                ),
                fetch_current=True,
            )

        self._run_async("play", work)

    def _on_queue_uri(self, uri: str):
        item_uri = str(uri or "").strip()
        if not item_uri:
            raise ValueError("A Spotify track URI is required.")

        def work():
            self._mark_user_music_change()
            return self.client.add_to_queue(
                item_uri,
                device_id=self._selected_device_id(),
            )

        self._run_async("queue", work)

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

    def _selected_device_id(self) -> str:
        combo = getattr(self, "default_device_combo", None)
        if combo is not None:
            return str(combo.currentData() or "").strip()
        return str(self.settings.data.get("default_device_id") or "").strip()

    def _run_async(self, kind: str, callback: Callable[[], dict[str, Any]]):
        def runner(cancel):
            with self._generation_lock:
                if self._closing or cancel.is_set():
                    return
                try:
                    result = callback()
                    if not isinstance(result, dict):
                        result = {"ok": True, "data": result}
                except Exception as exc:
                    result = {"ok": False, "error": str(exc)}
                if self._closing or cancel.is_set():
                    return
                self._post_ui(
                    lambda: self._handle_async_result(str(kind), result),
                )

        self._spawn_owned(f"async-{kind}", runner)

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
        if kind == "music_hub":
            self._native_dashboard_loading = False
            if not result.get("ok"):
                self._native_dashboard_error = str(
                    result.get("error") or "Could not refresh Spotify Music Hub."
                )
                self._set_status(self._native_dashboard_error)
                return
            current_result = result.get("current_track_result")
            if isinstance(current_result, dict):
                self._update_current_track(current_result, from_monitor=False)
            self._native_playlists = [
                dict(item)
                for item in list(result.get("playlists") or [])
                if isinstance(item, dict)
            ]
            self._native_artist = dict(result.get("artist") or {})
            self._native_discovery = [
                dict(item)
                for item in list(result.get("discovery") or [])
                if isinstance(item, dict)
            ]
            self._native_dashboard_error = str(result.get("warning") or "")
            self._set_status("Spotify Music Hub refreshed.")
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
        return None

    def _update_devices(self, result: dict[str, Any]):
        if not result.get("ok"):
            self._set_status(str(result.get("error") or "Could not refresh Spotify devices."))
            return
        devices = list(((result.get("data") or {}).get("devices") or []))
        self._native_devices = [dict(item) for item in devices if isinstance(item, dict)]
        combo = getattr(self, "default_device_combo", None)
        if combo is None:
            self._set_status(f"Spotify devices refreshed: {len(devices)} found.")
            return
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
            self._native_current_track = {}
            self._cached_music_context_at = time.time()
            self._clear_album_art()
            if not from_monitor:
                label = getattr(self, "current_track_label", None)
                if label is not None:
                    label.setText("Current track: nothing is currently playing.")
                self._set_status("Current track: nothing is currently playing.")
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

    def _best_image_record(self, images: list[Any]) -> dict[str, Any]:
        candidates: list[tuple[int, int, str, int, int]] = []
        for image in images:
            if not isinstance(image, dict):
                continue
            url = str(image.get("url") or "").strip()
            if not url:
                continue
            width = int(image.get("width") or 0)
            height = int(image.get("height") or 0)
            size = max(width, height)
            candidates.append((size, width * height, url, width, height))
        if not candidates:
            return {}
        size, _area, url, width, height = max(
            candidates,
            key=lambda item: (item[0], item[1]),
        )
        return {
            "url": url,
            "width": width or size,
            "height": height or size,
        }

    def _best_album_art_url(self, images: list[Any]) -> str:
        return str(self._best_image_record(images).get("url") or "")

    def _compact_track(self, result: dict[str, Any]) -> dict[str, Any]:
        data = dict(result.get("data") or {})
        item = dict(data.get("item") or data.get("track") or {})
        artists = item.get("artists") or []
        artist_names = []
        artist_ids = []
        artist_urls = []
        for artist in artists:
            if isinstance(artist, dict):
                name = str(artist.get("name") or "").strip()
                if name:
                    artist_names.append(name)
                artist_id = str(artist.get("id") or "").strip()
                if artist_id:
                    artist_ids.append(artist_id)
                artist_url = str(
                    dict(artist.get("external_urls") or {}).get("spotify") or ""
                ).strip()
                if artist_url:
                    artist_urls.append(artist_url)
        album = item.get("album") or {}
        album_images = list(album.get("images") or []) if isinstance(album, dict) else []
        album_art = self._best_image_record(album_images)
        device = (data.get("device") or {}) if isinstance(data.get("device"), dict) else {}
        return {
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or ""),
            "artists": artist_names,
            "artist_ids": artist_ids,
            "artist_urls": artist_urls,
            "album": str(album.get("name") or ""),
            "album_id": str(album.get("id") or ""),
            "album_art_url": str(album_art.get("url") or ""),
            "album_art_width": int(album_art.get("width") or 0),
            "album_art_height": int(album_art.get("height") or 0),
            "release_date": str(album.get("release_date") or ""),
            "uri": str(item.get("uri") or ""),
            "external_url": str(
                dict(item.get("external_urls") or {}).get("spotify") or ""
            ),
            "is_playing": bool(data.get("is_playing", False)),
            "progress_ms": int(data.get("progress_ms") or 0),
            "duration_ms": int(item.get("duration_ms") or 0),
            "device": str(device.get("name") or ""),
            "context": str((data.get("context") or {}).get("uri") or ""),
        }

    def _compact_playlists(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        if not result.get("ok"):
            return []
        compact: list[dict[str, Any]] = []
        for item in list(dict(result.get("data") or {}).get("items") or []):
            if not isinstance(item, dict):
                continue
            artwork = self._best_image_record(list(item.get("images") or []))
            tracks = dict(item.get("tracks") or {})
            compact.append(
                {
                    "id": str(item.get("id") or ""),
                    "name": str(item.get("name") or "Untitled playlist"),
                    "description": str(item.get("description") or ""),
                    "owner": str(dict(item.get("owner") or {}).get("display_name") or ""),
                    "track_count": int(tracks.get("total") or 0),
                    "image_url": str(artwork.get("url") or ""),
                    "uri": str(item.get("uri") or ""),
                    "external_url": str(
                        dict(item.get("external_urls") or {}).get("spotify") or ""
                    ),
                }
            )
        return compact

    def _compact_artist(
        self,
        artist_result: dict[str, Any],
        albums_result: dict[str, Any],
    ) -> dict[str, Any]:
        if not artist_result.get("ok"):
            return {}
        data = dict(artist_result.get("data") or {})
        artwork = self._best_image_record(list(data.get("images") or []))
        albums: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        if albums_result.get("ok"):
            for item in list(dict(albums_result.get("data") or {}).get("items") or []):
                if not isinstance(item, dict):
                    continue
                album_id = str(item.get("id") or "").strip()
                if album_id and album_id in seen_ids:
                    continue
                if album_id:
                    seen_ids.add(album_id)
                album_art = self._best_image_record(list(item.get("images") or []))
                albums.append(
                    {
                        "id": album_id,
                        "name": str(item.get("name") or "Untitled release"),
                        "release_date": str(item.get("release_date") or ""),
                        "image_url": str(album_art.get("url") or ""),
                        "uri": str(item.get("uri") or ""),
                        "external_url": str(
                            dict(item.get("external_urls") or {}).get("spotify") or ""
                        ),
                    }
                )
        return {
            "id": str(data.get("id") or ""),
            "name": str(data.get("name") or ""),
            "genres": [
                str(item)
                for item in list(data.get("genres") or [])
                if str(item or "").strip()
            ],
            "image_url": str(artwork.get("url") or ""),
            "external_url": str(
                dict(data.get("external_urls") or {}).get("spotify") or ""
            ),
            "albums": albums[:12],
        }

    def _compact_discovery(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        if not result.get("ok"):
            return []
        compact: list[dict[str, Any]] = []
        current_id = str(self._native_current_track.get("id") or "")
        for item in list(dict(result.get("data") or {}).get("items") or []):
            if not isinstance(item, dict):
                continue
            track = self._compact_track(
                {"ok": True, "data": {"item": item, "is_playing": False}}
            )
            if track.get("id") and track.get("id") != current_id:
                compact.append(track)
        return compact[:12]

    def _fetch_music_hub(self) -> dict[str, Any]:
        if not self.client.is_connected():
            return {"ok": False, "error": "Spotify is not connected."}
        current_result = self.client.get_current_track()
        track = self._compact_track(current_result) if current_result.get("ok") else {}
        artist_ids = list(track.get("artist_ids") or [])
        playlists_result = self.client.get_current_user_playlists(limit=20)
        artist_result: dict[str, Any] = {"ok": False}
        albums_result: dict[str, Any] = {"ok": False}
        if artist_ids:
            artist_result = self.client.get_artist(artist_ids[0])
            albums_result = self.client.get_artist_albums(artist_ids[0], limit=12)
        discovery_result = self.client.get_top_items(
            "tracks",
            time_range="short_term",
            limit=12,
        )
        warnings = []
        if not playlists_result.get("ok"):
            warnings.append("Playlists could not be loaded.")
        if artist_ids and not artist_result.get("ok"):
            warnings.append("Artist details could not be loaded.")
        if not discovery_result.get("ok"):
            warnings.append("Reconnect Spotify to enable personalized discovery.")
        return {
            "ok": True,
            "current_track_result": current_result,
            "playlists": self._compact_playlists(playlists_result),
            "artist": self._compact_artist(artist_result, albums_result),
            "discovery": self._compact_discovery(discovery_result),
            "warning": " ".join(warnings),
        }

    def _cache_music_context(self, track: dict[str, Any]):
        self._native_current_track = dict(track or {})
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

    def _build_hidden_song_change_context_text(self, payload: dict[str, Any]) -> str:
        artists = ", ".join(str(item) for item in list(payload.get("artists") or []) if str(item or "").strip())
        style_prompt = self._current_hidden_commentary_style_prompt()
        return "\n".join(
            (
                "Hidden Spotify song-change commentary only; Spotify metadata is not raw audio.",
                f"Track: {payload.get('track') or 'Unknown track'}.",
                f"Artists: {artists or 'Unknown artist'}.",
                f"Commentary style: {style_prompt}",
                "Set should_speak=true and include [sensory_action:spotify_sense] in tags.",
                "In proactive_candidate, preserve this track, artists, and style while instructing one brief natural sentence with no introduction, question, follow-up, raw-audio claim, or song-change announcement.",
                "Avoid openings: " + ", ".join(SPOTIFY_HIDDEN_FORBIDDEN_OPENINGS) + ".",
            )
        )

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
            f"Spotify music-conversation prompt: {self._current_music_conversation_prompt()}",
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
            "reaction_goal": "Instruct the assistant to write one brief sentence about this track using the supplied metadata and commentary style; no question or follow-up.",
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
        self._last_hidden_response_snapshot_at = now
        self._last_track_comment_at = max(float(self._last_track_comment_at or 0.0), now)
        self._remember_hidden_comment_offer(track_key=track_key, payload=payload, angle=angle, now=now)
        self._pending_track_change_context = None
        style_prompt = self._current_hidden_commentary_style_prompt()
        content_text = self._build_hidden_song_change_context_text(payload)
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
                "metadata_only": True,
                "cache_policy": "one_shot",
                "hidden_response_allowed": True,
                "hidden_response_cooldown_seconds": hidden_cooldown,
                "proactive_candidate": "",
                "comment_brief": comment_brief,
                "forbidden_openings": list(SPOTIFY_HIDDEN_FORBIDDEN_OPENINGS),
                "commentary_style_prompt": style_prompt,
                "should_speak_recommended": True,
            },
        }

    def _track_sentence(self, track: dict[str, Any]) -> str:
        artists = ", ".join(track.get("artists") or []) or "Unknown artist"
        return f"Now playing: {track.get('name') or 'Unknown track'} by {artists}."

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
        if capability_name == "runtime.spotify.native_snapshot":
            return self.native_snapshot()
        if capability_name == "runtime.spotify.native_update":
            return self.native_update(dict(payload or {}))
        if capability_name == "runtime.spotify.native_action":
            return self.native_action(dict(payload or {}))
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

    def _set_volume_smooth(
        self,
        *,
        start: int,
        target: int,
        device_id: str | None,
        duration_ms: int,
        reason: str,
        generation: int | None = None,
        on_complete: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        start_value = max(0, min(100, int(start)))
        target_value = max(0, min(100, int(target)))
        duration = max(0, int(duration_ms or 0))
        generation = self._next_duck_transition_generation() if generation is None else int(generation)

        def complete(result: dict[str, Any]) -> None:
            if not callable(on_complete):
                return
            try:
                on_complete(dict(result or {}))
            except Exception as exc:
                self._debug_log(
                    "duck_volume_completion_failed",
                    {"reason": reason, "error": str(exc)},
                )

        if duration <= 0 or start_value == target_value:
            if not self._volume_transition_is_current(generation):
                result = {"ok": True, "cancelled": True, "reason": "stale_duck_transition"}
                complete(result)
                return result
            result = self.client.set_volume(target_value, device_id=device_id)
            self._debug_log("duck_volume_set", {"reason": reason, "volume": target_value, "device_id": device_id, "result": result})
            complete(dict(result or {}))
            return result

        steps = max(2, min(16, int(round(duration / 120.0)) or 2))
        sleep_seconds = duration / 1000.0 / steps

        def runner(cancel):
            last_result: dict[str, Any] = {"ok": True}
            self._debug_log(
                "duck_volume_transition_start",
                {"reason": reason, "from": start_value, "to": target_value, "steps": steps, "duration_ms": duration, "device_id": device_id},
            )
            for index in range(1, steps + 1):
                if cancel.is_set() or not self._volume_transition_is_current(generation):
                    self._debug_log("duck_volume_transition_cancelled", {"reason": reason, "step": index, "device_id": device_id})
                    complete({"ok": False, "cancelled": True, "reason": "stale_or_cancelled_transition"})
                    return
                fraction = index / float(steps)
                volume = int(round(start_value + ((target_value - start_value) * fraction)))
                last_result = dict(self.client.set_volume(volume, device_id=device_id) or {})
                self._debug_log("duck_volume_step", {"reason": reason, "step": index, "steps": steps, "volume": volume, "result": last_result})
                if not bool(last_result.get("ok")):
                    complete(last_result)
                    return
                if index < steps:
                    if cancel.wait(sleep_seconds):
                        complete({"ok": False, "cancelled": True, "reason": "cancelled_transition"})
                        return
            self._debug_log("duck_volume_transition_done", {"reason": reason, "to": target_value, "result": last_result})
            complete(last_result)

        self._spawn_owned("duck-fade", runner)
        return {"ok": True, "transitioning": True, "from": start_value, "to": target_value, "duration_ms": duration}

    def duck_start(self):
        if not bool(self.settings.data.get("duck_while_speaking", False)):
            self._debug_log("duck_start_skipped", {"reason": "disabled"})
            return {"ok": True, "ducked": False, "message": "Lower music while NC speaks is disabled."}
        pending_restore = getattr(self, "_pending_duck_restore", None)
        if pending_restore is not None:
            self._next_duck_transition_generation()
            self._pending_duck_restore = None
            self._remembered_volume = max(0, min(100, int(pending_restore[1])))
            self._remembered_duck_device_id = pending_restore[2]
            self._duck_start_pending = False
            self._debug_log(
                "duck_restore_superseded",
                {
                    "preserved_restore_volume": self._remembered_volume,
                    "device_id": self._remembered_duck_device_id,
                },
            )
        if self._duck_is_active():
            target_volume = self._duck_target_volume(int(self._remembered_volume or 0))
            device_id = self._remembered_duck_device_id or str(self.settings.data.get("default_device_id") or "").strip() or None
            self._debug_log(
                "duck_start_refresh",
                {"device_id": device_id, "previous_volume": self._remembered_volume, "target_volume": target_volume},
            )
            return {
                "ok": True,
                "ducked": True,
                "already_active": True,
                "pending": bool(getattr(self, "_duck_start_pending", False)),
                "previous_volume": self._remembered_volume,
                "target_volume": target_volume,
            }
        device_id = str(self.settings.data.get("default_device_id") or "").strip() or None
        try:
            fallback_volume = int(self.settings.data.get("default_volume") or 30)
        except Exception:
            fallback_volume = 30
        self._remembered_volume = max(0, min(100, fallback_volume))
        self._remembered_duck_device_id = device_id
        target_volume = self._duck_target_volume(self._remembered_volume)
        duration_ms = int(self.settings.data.get("duck_fade_down_ms", 650) or 0)
        generation = self._next_duck_transition_generation()
        self._duck_start_pending = True

        def worker(cancel) -> None:
            try:
                state = self.client.get_playback_state()
            except Exception as exc:
                state = {"ok": False, "error": str(exc), "error_type": type(exc).__name__}
            if cancel.is_set() or not self._volume_transition_is_current(generation):
                return
            device = (state.get("data") or {}).get("device") or {} if isinstance(state, dict) and state.get("ok") else {}
            state_error = None if isinstance(state, dict) and state.get("ok") else dict(state or {})
            resolved_device_id = device_id or str(device.get("id") or "").strip() or None
            try:
                previous_volume = max(0, min(100, int(device.get("volume_percent"))))
            except Exception:
                previous_volume = int(self._remembered_volume or fallback_volume)
            if cancel.is_set() or not self._volume_transition_is_current(generation):
                return
            self._remembered_volume = previous_volume
            self._remembered_duck_device_id = resolved_device_id
            resolved_target = self._duck_target_volume(previous_volume)
            self._duck_start_pending = False
            result = self._set_volume_smooth(
                start=previous_volume,
                target=resolved_target,
                device_id=resolved_device_id,
                duration_ms=duration_ms,
                reason="tts_duck_start",
                generation=generation,
            )
            self._debug_log(
                "duck_start",
                {
                    "device_id": resolved_device_id,
                    "previous_volume": previous_volume,
                    "target_volume": resolved_target,
                    "duration_ms": duration_ms,
                    "state_error": state_error,
                    "result": result,
                },
            )
            if not bool(result.get("ok")) and self._volume_transition_is_current(generation):
                self._remembered_volume = None
                self._remembered_duck_device_id = None

        self._spawn_owned("duck-start", worker)
        return {
            "ok": True,
            "ducked": True,
            "queued": True,
            "previous_volume": self._remembered_volume,
            "target_volume": target_volume,
        }

    def duck_end(self):
        if bool(getattr(self, "_duck_start_pending", False)):
            self._next_duck_transition_generation()
            self._duck_start_pending = False
            self._remembered_volume = None
            self._remembered_duck_device_id = None
            self._debug_log("duck_end_pending_cancelled", {})
            return {"ok": True, "restored": False, "cancelled_pending": True}
        if not bool(self.settings.data.get("restore_volume_after_speech", True)):
            self._next_duck_transition_generation()
            self._debug_log("duck_end_restore_disabled", {"previous_volume": self._remembered_volume, "device_id": self._remembered_duck_device_id})
            self._remembered_volume = None
            self._remembered_duck_device_id = None
            self._duck_start_pending = False
            return {"ok": True, "restored": False, "message": "Restore volume after speech is disabled."}
        if self._remembered_volume is None:
            if getattr(self, "_pending_duck_restore", None) is not None:
                return {"ok": True, "restored": False, "pending": True, "message": "Spotify volume restoration is still pending."}
            return {"ok": True, "restored": False, "message": "No remembered Spotify volume to restore."}
        target_volume = int(self._remembered_volume)
        device_id = self._remembered_duck_device_id
        current_volume = int(self.settings.data.get("duck_volume_percent", 15) or 15)
        duration_ms = int(self.settings.data.get("duck_fade_up_ms", 900) or 0)
        generation = self._next_duck_transition_generation()
        self._pending_duck_restore = (generation, target_volume, device_id)
        self._remembered_volume = None
        self._remembered_duck_device_id = None
        self._duck_start_pending = False

        def complete_restore(transition_result: dict[str, Any]) -> None:
            pending = getattr(self, "_pending_duck_restore", None)
            if (
                pending is None
                or int(pending[0]) != generation
                or not self._volume_transition_is_current(generation)
            ):
                return
            final_result = dict(transition_result or {})
            used_fallback = False
            if not bool(final_result.get("ok")) and not bool(final_result.get("cancelled")):
                used_fallback = True
                final_result = dict(self.client.set_volume(target_volume, device_id=device_id) or {})
            if bool(final_result.get("ok")):
                self._pending_duck_restore = None
            self._debug_log(
                "duck_restore_complete",
                {
                    "device_id": device_id,
                    "restore_volume": target_volume,
                    "generation": generation,
                    "used_fallback": used_fallback,
                    "result": final_result,
                },
            )

        result = self._set_volume_smooth(
            start=current_volume,
            target=target_volume,
            device_id=device_id,
            duration_ms=duration_ms,
            reason="tts_duck_end",
            generation=generation,
            on_complete=complete_restore,
        )
        pending = getattr(self, "_pending_duck_restore", None) is not None
        restored = not pending and not bool(result.get("cancelled"))
        self._debug_log("duck_end", {"device_id": device_id, "restore_volume": target_volume, "duration_ms": duration_ms, "pending": pending, "result": result})
        return {
            "ok": bool(result.get("ok")) or restored,
            "restored": restored,
            "pending": pending,
            "volume": target_volume,
            "result": result,
        }

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

        def run_transition(cancel=None) -> dict[str, Any]:
            if cancel is not None and cancel.is_set():
                return {"ok": False, "cancelled": True, "reason": "addon_context_closed"}
            down_result = self._set_volume_blocking(
                start=start_volume,
                target=floor_volume,
                device_id=device_id,
                duration_ms=fade_down_ms,
                reason="story_music_fade_down",
                generation=generation,
                is_current=self._story_transition_is_current,
                cancel=cancel,
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
                cancel=cancel,
            )
            self._debug_log(
                "story_music_transition",
                {"query": query, "mood": mood, "music_kind": music_kind, "fade": fade, "play_result": play_result, "up_result": up_result},
            )
            return {"ok": playback_ok, "playback": play_result, "fade_up": up_result}

        if fade_down_ms > 0 or fade_up_ms > 0:
            self._spawn_owned("story-music", run_transition)
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
        cancel=None,
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
            if (cancel is not None and cancel.is_set()) or not current_checker(generation):
                return {"ok": False, "cancelled": True, "reason": reason}
            if cancel_if_duck_active and self._duck_is_active():
                return {"ok": True, "skipped": True, "reason": "tts_duck_active"}
            fraction = index / float(steps)
            volume = int(round(start_value + ((target_value - start_value) * fraction)))
            last_result = self.client.set_volume(volume, device_id=device_id)
            if not bool(isinstance(last_result, dict) and last_result.get("ok")):
                return last_result if isinstance(last_result, dict) else {"ok": False, "error": "Spotify volume update failed."}
            if index < steps:
                if cancel is not None and cancel.wait(sleep_seconds):
                    return {"ok": False, "cancelled": True, "reason": reason}
                if cancel is None:
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

    def native_snapshot(self) -> dict[str, Any]:
        """Return cached, non-secret state for the native QML settings surface."""
        settings = {
            key: value
            for key, value in dict(self.settings.data).items()
            if key not in TOKEN_KEYS
        }
        track = dict(self._native_current_track or {})
        return {
            "settings": settings,
            "connected": bool(self.client.is_connected()),
            "enabled": bool(settings.get("enabled", False)),
            "activation_status": self._sync_activation_presentation(),
            "status": str(self._native_status or ""),
            "track": track,
            "track_text": self._track_sentence(track) if track.get("id") else "Current track: nothing is currently playing.",
            "devices": [dict(item) for item in self._native_devices],
            "hidden_presets": [dict(item) for item in self._hidden_sensory_preset_records()],
            "hidden_quick_ids": list(self._hidden_sensory_quick_ids()),
            "source_guidance": self._current_source_guidance(),
            "debug_log_path": str(self._debug_log_path()),
            "music_hub": {
                "loading": bool(self._native_dashboard_loading),
                "error": str(self._native_dashboard_error or ""),
                "playlists": [dict(item) for item in self._native_playlists],
                "artist": dict(self._native_artist),
                "discovery": [dict(item) for item in self._native_discovery],
            },
        }

    def native_update(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Apply one validated native setting through the existing settings owner."""
        key = str(payload.get("key") or "").strip()
        value = payload.get("value")
        supported = set(DEFAULT_SETTINGS) - TOKEN_KEYS
        if key in supported:
            self._update_setting(key, value)
        elif key == "source_guidance":
            text = str(value or "").strip() or DEFAULT_SPOTIFY_SOURCE_GUIDANCE
            service = self._runtime_config_service()
            if service is None:
                raise RuntimeError("Runtime config service is unavailable; Spotify source guidance was not saved.")
            prompt_map = self._source_guidance_map()
            prompt_map[SENSORY_PROVIDER_ID] = text
            service.update("sensory_pingpong_source_prompts", prompt_map)
            self._notify_shell_settings_changed()
            self._set_status("Spotify hidden sensory source guidance saved.")
        elif key == "hidden_preset_id":
            record = self._hidden_sensory_record_by_id(str(value or ""))
            if record is not None:
                self._load_hidden_sensory_preset_record(record)
        elif key.startswith("hidden_quick_") and bool(value):
            try:
                slot = int(key.rsplit("_", 1)[-1]) - 1
            except (TypeError, ValueError):
                slot = -1
            quick_ids = self._hidden_sensory_quick_ids()
            if 0 <= slot < len(quick_ids):
                record = self._hidden_sensory_record_by_id(quick_ids[slot])
                if record is not None:
                    self._load_hidden_sensory_preset_record(record)
        else:
            raise KeyError(f"Unknown Spotify Sense setting '{key}'.")
        return self.native_snapshot()

    def native_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Route native actions into the existing controller and owned workers."""
        action = str(payload.get("action") or "").strip().lower()
        if action == "save_settings":
            self._set_status("Settings saved.")
        elif action == "connect":
            self._on_connect()
        elif action == "disconnect":
            self._on_disconnect()
        elif action == "refresh_devices":
            self._on_refresh_devices()
        elif action == "current_track":
            self._on_current_track()
        elif action == "dashboard_refresh":
            self._on_dashboard_refresh()
        elif action == "play":
            self._on_play()
        elif action == "pause":
            self._on_pause()
        elif action == "next":
            self._on_next()
        elif action == "previous":
            self._on_previous()
        elif action == "volume_30":
            self._on_volume_30()
        elif action == "play_context":
            self._on_play_context(str(payload.get("uri") or ""))
        elif action == "queue_uri":
            self._on_queue_uri(str(payload.get("uri") or ""))
        elif action == "preview_intent":
            result = route_music_intent(str(payload.get("text") or ""))
            if result.get("matched"):
                self._set_status(
                    f"Matched {str(result.get('tool') or '')} with confidence "
                    f"{float(result.get('confidence') or 0.0):.2f}. Use LLM tools with confirmation to execute."
                )
            else:
                self._set_status("No safe Spotify intent matched.")
        elif action == "open_debug_log":
            self._on_open_debug_log()
        elif action == "save_hidden_preset":
            self._save_hidden_sensory_style_as_preset()
        elif action == "add_hidden_quick":
            self._on_hidden_sensory_add_quick_clicked()
        elif action == "remove_hidden_quick":
            self._on_hidden_sensory_remove_quick_clicked()
        elif action == "save_hidden_style":
            self._save_hidden_commentary_style()
        elif action == "save_conversation_prompt":
            self._save_music_conversation_prompt()
        elif action == "reset_conversation_prompt":
            self.settings.update(music_conversation_prompt=DEFAULT_MUSIC_CONVERSATION_PROMPT)
            self._set_status("Restored the recommended Spotify music-conversation prompt.")
        elif action == "save_source_guidance":
            self._set_status("Spotify hidden sensory source guidance saved.")
        elif action == "reset_source_guidance":
            self.native_update({"key": "source_guidance", "value": DEFAULT_SPOTIFY_SOURCE_GUIDANCE})
        else:
            raise KeyError(f"Unknown Spotify Sense action '{action}'.")
        return self.native_snapshot()

    def _set_status(self, text: str):
        self._native_status = str(text or "")
        label = getattr(self, "status_label", None)
        if label is not None:
            label.setText(str(text or ""))

    def shutdown(self):
        with self._generation_lock:
            if self._closing:
                return
            self._closing = True
            try:
                self.context.ui_dispatcher.invalidate_target(self._ui_target_key)
            except Exception:
                pass
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
