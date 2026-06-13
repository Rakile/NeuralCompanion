from __future__ import annotations

import http.server
import threading
import time
import urllib.parse
import webbrowser
from typing import Any, Callable

from PySide6 import QtCore, QtWidgets

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
MUSIC_RESPONSE_MODES = (
    ("Off", "off"),
    ("Subtle", "subtle"),
    ("Companion", "companion"),
    ("DJ / Music Critic", "dj_critic"),
    ("Story soundtrack", "story_soundtrack"),
)


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
        self._cached_music_context: dict[str, Any] = {}
        self._cached_music_context_at = 0.0
        self._last_context_refresh_request_at = 0.0
        self._context_refresh_in_flight = False
        self._pending_track_change_context: dict[str, Any] | None = None
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
                    "do not claim to hear raw audio."
                ),
                description="Current Spotify track metadata for music-aware chat and optional hidden sensory feedback.",
                order=340,
                capture_handler=self.capture_sensory_snapshot,
                metadata={"kind": "music", "provider": "spotify", "text_only": True},
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

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setObjectName("spotify_sense_status")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        card_layout.addWidget(self.status_label)

        auth_grid = QtWidgets.QGridLayout()
        auth_grid.setContentsMargins(0, 0, 0, 0)
        auth_grid.setHorizontalSpacing(10)
        auth_grid.setVerticalSpacing(6)

        self.client_id_edit = QtWidgets.QLineEdit()
        self.client_id_edit.setObjectName("spotify_sense_client_id")
        self.client_id_edit.setPlaceholderText("Spotify app Client ID")
        self.client_id_edit.setText(str(self.settings.data.get("client_id") or ""))
        self.client_id_edit.editingFinished.connect(self._on_text_settings_finished)

        self.redirect_uri_edit = QtWidgets.QLineEdit()
        self.redirect_uri_edit.setObjectName("spotify_sense_redirect_uri")
        self.redirect_uri_edit.setText(str(self.settings.data.get("redirect_uri") or DEFAULT_SETTINGS["redirect_uri"]))
        self.redirect_uri_edit.editingFinished.connect(self._on_text_settings_finished)

        auth_grid.addWidget(QtWidgets.QLabel("Client ID"), 0, 0)
        auth_grid.addWidget(self.client_id_edit, 0, 1, 1, 3)
        auth_grid.addWidget(QtWidgets.QLabel("Redirect URI"), 1, 0)
        auth_grid.addWidget(self.redirect_uri_edit, 1, 1, 1, 3)
        auth_grid.setColumnStretch(1, 1)
        card_layout.addLayout(auth_grid)

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
            button.clicked.connect(handler)
            auth_buttons.addWidget(button)
        auth_buttons.addStretch(1)
        card_layout.addLayout(auth_buttons)

        settings_grid = QtWidgets.QGridLayout()
        settings_grid.setContentsMargins(0, 0, 0, 0)
        settings_grid.setHorizontalSpacing(10)
        settings_grid.setVerticalSpacing(6)

        self.enable_checkbox = self._checkbox("Enable Spotify Sense", "enabled")
        self.llm_checkbox = self._checkbox("Allow LLM Spotify control", "allow_llm_control")
        self.confirm_checkbox = self._checkbox("Require confirmation before changing music", "require_confirmation")
        self.duck_checkbox = self._checkbox("Duck music while NC speaks", "duck_while_speaking")
        self.restore_checkbox = self._checkbox("Restore volume after speech", "restore_volume_after_speech")
        self.comment_checkbox = self._checkbox("Comment on song changes", "comment_on_song_changes")
        self.queue_checkbox = self._checkbox("Allow queue changes", "allow_queue_changes")
        self.playlist_checkbox = self._checkbox("Allow playlist changes", "allow_playlist_changes")
        self.story_checkbox = self._checkbox("Story mode background music", "story_mode_background_music")
        self.monitor_checkbox = self._checkbox("Song-change monitor", "song_change_monitor_enabled")
        self.awareness_checkbox = self._checkbox("Enable music awareness in chat", "music_awareness_enabled")
        self.paused_context_checkbox = self._checkbox("Include paused Spotify track context", "include_paused_track_context")
        self.relevance_checkbox = self._checkbox("Only mention music when relevant", "music_awareness_relevance_only")

        self.autonomy_combo = QtWidgets.QComboBox()
        self.autonomy_combo.setObjectName("spotify_sense_autonomous_music")
        for label, value in (("Off", "off"), ("Routines only", "routines"), ("Full", "full")):
            self.autonomy_combo.addItem(label, value)
        self._set_combo_value(self.autonomy_combo, self.settings.data.get("autonomous_music", "off"))
        self.autonomy_combo.currentIndexChanged.connect(lambda _index: self._update_setting("autonomous_music", self.autonomy_combo.currentData()))

        self.response_mode_combo = QtWidgets.QComboBox()
        self.response_mode_combo.setObjectName("spotify_sense_music_response_mode")
        for label, value in MUSIC_RESPONSE_MODES:
            self.response_mode_combo.addItem(label, value)
        self._set_combo_value(self.response_mode_combo, self.settings.data.get("music_response_mode", "subtle"))
        self.response_mode_combo.currentIndexChanged.connect(lambda _index: self._update_setting("music_response_mode", self.response_mode_combo.currentData()))
        self._controls["music_response_mode"] = self.response_mode_combo

        self.default_device_combo = QtWidgets.QComboBox()
        self.default_device_combo.setObjectName("spotify_sense_default_device")
        self.default_device_combo.addItem("Active device / default", "")
        self.default_device_combo.currentIndexChanged.connect(lambda _index: self._update_setting("default_device_id", self.default_device_combo.currentData()))

        self.default_volume_spin = self._spinbox("default_volume", 0, 100)
        self.duck_volume_spin = self._spinbox("duck_volume_percent", 0, 100)
        self.comment_cooldown_spin = self._spinbox("proactive_comment_cooldown_seconds", 15, 3600, suffix="s")

        self.coding_query_edit = QtWidgets.QLineEdit()
        self.coding_query_edit.setObjectName("spotify_sense_coding_query")
        self.coding_query_edit.setText(str(self.settings.data.get("coding_mode_query") or "relaxing focus music"))
        self.coding_query_edit.editingFinished.connect(self._on_text_settings_finished)

        rows = [
            (self.enable_checkbox, self.llm_checkbox),
            (self.confirm_checkbox, self.monitor_checkbox),
            (self.duck_checkbox, self.restore_checkbox),
            (self.comment_checkbox, self.queue_checkbox),
            (self.playlist_checkbox, self.story_checkbox),
            (self.awareness_checkbox, self.paused_context_checkbox),
            (self.relevance_checkbox, QtWidgets.QWidget()),
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
        settings_grid.addWidget(QtWidgets.QLabel("Song-change comment cooldown"), row_index, 0)
        settings_grid.addWidget(self.comment_cooldown_spin, row_index, 1)
        settings_grid.addWidget(QtWidgets.QLabel("Default device"), row_index, 2)
        settings_grid.addWidget(self.default_device_combo, row_index, 3)
        row_index += 1
        settings_grid.addWidget(QtWidgets.QLabel("Coding mode search"), row_index, 0)
        settings_grid.addWidget(self.coding_query_edit, row_index, 1, 1, 3)
        settings_grid.setColumnStretch(3, 1)
        card_layout.addLayout(settings_grid)

        self.current_track_label = QtWidgets.QLabel("Current track: not checked yet.")
        self.current_track_label.setObjectName("spotify_sense_current_track")
        self.current_track_label.setWordWrap(True)
        self.current_track_label.setStyleSheet("color: #cbd5e1;")
        card_layout.addWidget(self.current_track_label)

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
            button.clicked.connect(handler)
            test_buttons.addWidget(button)
        test_buttons.addStretch(1)
        card_layout.addLayout(test_buttons)

        intent_row = QtWidgets.QHBoxLayout()
        intent_row.setContentsMargins(0, 0, 0, 0)
        intent_row.setSpacing(8)
        self.intent_edit = QtWidgets.QLineEdit()
        self.intent_edit.setObjectName("spotify_sense_intent_test")
        self.intent_edit.setPlaceholderText("Try: play relaxing focus music, skip this, what song is this?")
        route_button = QtWidgets.QPushButton("Preview Intent")
        route_button.clicked.connect(self._on_preview_intent)
        intent_row.addWidget(self.intent_edit, 1)
        intent_row.addWidget(route_button)
        card_layout.addLayout(intent_row)

        layout.addWidget(card)
        layout.addStretch(1)
        scroll.setWidget(content)
        self._widgets.append(scroll)
        self._refresh_connection_status()
        self._on_refresh_devices()
        return scroll

    def _checkbox(self, label: str, key: str):
        checkbox = QtWidgets.QCheckBox(label)
        checkbox.setObjectName(f"spotify_sense_{key}")
        checkbox.setChecked(bool(self.settings.data.get(key, DEFAULT_SETTINGS.get(key, False))))
        checkbox.toggled.connect(lambda checked, setting_key=key: self._update_setting(setting_key, bool(checked)))
        self._controls[key] = checkbox
        return checkbox

    def _spinbox(self, key: str, minimum: int, maximum: int, *, suffix: str = "%"):
        spinbox = QtWidgets.QSpinBox()
        spinbox.setObjectName(f"spotify_sense_{key}")
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
        self._refresh_connection_status()
        self._set_status("Disconnected from Spotify Sense. Local tokens were cleared.")

    def _on_refresh_devices(self):
        self._run_async("devices", self.client.get_devices)

    def _on_current_track(self):
        self._run_async("current_track", self.client.get_current_track)

    def _on_play_pause(self):
        def work():
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
        self._run_async("next", lambda: self.client.next(device_id=self._selected_device_id()))

    def _on_volume_30(self):
        self._run_async("volume", lambda: self.client.set_volume(30, device_id=self._selected_device_id()))

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

    def _update_current_track(self, result: dict[str, Any], *, from_monitor: bool = False):
        if not result.get("ok"):
            if not from_monitor:
                self._set_status(str(result.get("error") or "Could not read current Spotify track."))
            return
        compact = self._compact_track(result)
        if not compact.get("id"):
            self._cached_music_context = {}
            self._cached_music_context_at = time.time()
            if not from_monitor:
                self.current_track_label.setText("Current track: nothing is currently playing.")
            return
        self._cache_music_context(compact)
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
        device = (data.get("device") or {}) if isinstance(data.get("device"), dict) else {}
        return {
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or ""),
            "artists": artist_names,
            "album": str(album.get("name") or ""),
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
        if not payload:
            return None
        context_text = self._build_music_context_text(payload, consume_pending=True)
        if not context_text:
            return None
        return {
            "context": context_text,
            "debug": {
                "matches": 1,
                "sources": [SENSORY_PROVIDER_ID],
                "mood": payload.get("mood_hint", "neutral"),
                "track": payload.get("track", ""),
            },
        }

    def capture_sensory_snapshot(self, _capture_context=None):
        payload = self._current_music_context_payload()
        if not payload:
            return None
        return {
            "source": SENSORY_PROVIDER_ID,
            "captured_at": time.time(),
            "content_text": self._build_music_context_text(payload, consume_pending=False),
            "metadata": {
                "kind": "music",
                "provider": "spotify",
                "track": str(payload.get("track") or ""),
                "artists": list(payload.get("artists") or []),
                "album": str(payload.get("album") or ""),
                "is_playing": bool(payload.get("is_playing", False)),
                "mood_hint": str(payload.get("mood_hint") or "neutral"),
                "metadata_only": True,
            },
        }

    def _track_sentence(self, track: dict[str, Any]) -> str:
        artists = ", ".join(track.get("artists") or []) or "Unknown artist"
        mood = infer_music_mood(track)
        return f"Now playing: {track.get('name') or 'Unknown track'} by {artists}. Mood hint: {mood}."

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
        if capability_name == "chat_context.collect":
            return self.collect_chat_context(dict(payload or {}))
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
            return self._invoke_spotify_tool(capability_name, request)
        except Exception as exc:
            self.context.logger.exception("[SpotifySense] Capability failed: %s", capability_name)
            return {"ok": False, "tool": capability_name, "error": str(exc)}

    def _guard_capability(self, capability_name: str, payload: dict[str, Any]):
        if not bool(self.settings.data.get("enabled", False)):
            return {"ok": False, "tool": capability_name, "error_code": "disabled", "error": "Spotify Sense is disabled."}
        if capability_name in CONTROL_TOOLS:
            if capability_name not in {"spotify.duck.start", "spotify.duck.end"} and not bool(self.settings.data.get("allow_llm_control", False)):
                return {"ok": False, "tool": capability_name, "error_code": "llm_control_disabled", "error": "LLM Spotify control is disabled."}
            if capability_name == "spotify.add_to_queue" and not bool(self.settings.data.get("allow_queue_changes", False)):
                return {"ok": False, "tool": capability_name, "error_code": "queue_disabled", "error": "Queue changes are disabled."}
            if capability_name == "spotify.play_playlist" and not bool(self.settings.data.get("allow_playlist_changes", False)):
                return {"ok": False, "tool": capability_name, "error_code": "playlist_disabled", "error": "Playlist changes are disabled."}
            if (
                bool(self.settings.data.get("require_confirmation", True))
                and not bool(payload.get("confirmed", False))
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
            return self.client.play(query=query, device_id=device_id)
        if capability_name == "spotify.play_playlist":
            uri = str(payload.get("context_uri") or payload.get("playlist_uri") or "").strip()
            if not uri:
                return {"ok": False, "tool": capability_name, "error_code": "invalid_playlist", "error": "playlist_uri or context_uri is required."}
            return self.client.play(context_uri=uri, device_id=device_id)
        if capability_name == "spotify.pause":
            return self.client.pause(device_id=device_id)
        if capability_name == "spotify.resume":
            return self.client.play(device_id=device_id)
        if capability_name == "spotify.next":
            return self.client.next(device_id=device_id)
        if capability_name == "spotify.previous":
            return self.client.previous(device_id=device_id)
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

    def duck_start(self):
        if not bool(self.settings.data.get("duck_while_speaking", False)):
            return {"ok": True, "ducked": False, "message": "Spotify ducking is disabled."}
        state = self.client.get_playback_state()
        if not state.get("ok"):
            return state
        device = (state.get("data") or {}).get("device") or {}
        try:
            self._remembered_volume = int(device.get("volume_percent"))
        except Exception:
            self._remembered_volume = int(self.settings.data.get("default_volume") or 30)
        result = self.client.set_volume(self.settings.data.get("duck_volume_percent", 15))
        return {"ok": bool(result.get("ok")), "ducked": bool(result.get("ok")), "previous_volume": self._remembered_volume, "result": result}

    def duck_end(self):
        if not bool(self.settings.data.get("restore_volume_after_speech", True)):
            return {"ok": True, "restored": False, "message": "Restore volume after speech is disabled."}
        if self._remembered_volume is None:
            return {"ok": True, "restored": False, "message": "No remembered Spotify volume to restore."}
        result = self.client.set_volume(self._remembered_volume)
        restored = self._remembered_volume
        self._remembered_volume = None
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
