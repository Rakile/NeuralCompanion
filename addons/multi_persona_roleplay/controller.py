from __future__ import annotations

import copy
import html
import json
import math
import platform
import re
import shutil
import struct
import threading
import time
import weakref
import wave
import zipfile
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from .audio_prompts import AUDIO_TYPES, create_audio_prompt
from . import prompting
from . import story_director
from .chromecast_bridge import DEFAULT_MPRC_CAST_STREAM_PORT, MprcChromecastBridge
from .models import (
    AR_INTERACTION_FREQUENCIES,
    AR_MODE,
    AR_PACING_MODES,
    BEHAVIOR_MODES,
    MEMORY_SCOPES,
    SESSION_MODES,
    SESSION_MODE_DESCRIPTIONS,
    VISUAL_MODE_DESCRIPTIONS,
    VISUAL_MODE_LABELS,
    VISUAL_MODES,
    VISUAL_PROVIDERS,
    VISUAL_SIZES,
    VOICE_BACKENDS,
    PersonaConfig,
    RoleplaySessionState,
    normalize_persona_id,
    personas_from_payload,
    unique_persona_id,
)
from .long_memory import RoleplayLongMemory
from .remote_backend import DEFAULT_REMOTE_PORT, MPRCRemoteBackend, generate_remote_code, lan_ip_address
from .roleplay_engine import RoleplayEngine
from .storage import RoleplayStorage
from .structured_output import STRUCTURED_STORY_SCHEMA_VERSION, build_structured_story_output_schema
from .visual_reply import PersonaVisualReply
from .voice_routing import PersonaVoiceRouter, VOICE_REFERENCE_BACKENDS, normalize_tts_backend


def _mprc_checkbox_stylesheet(text_color: str = "#f4f7fb", font_weight: str = "600") -> str:
    return f"""
    QCheckBox {{
        color: {text_color};
        font-weight: {font_weight};
        spacing: 9px;
        min-height: 24px;
    }}
    QCheckBox:disabled {{
        color: #7f8fa3;
    }}
    QCheckBox::indicator {{
        width: 20px;
        height: 20px;
        image: url(ui/assets/checkbox_round_inactive.svg);
        background: transparent;
        border: 0px;
    }}
    QCheckBox::indicator:hover {{
        image: url(ui/assets/checkbox_round_inactive.svg);
        background: transparent;
        border: 0px;
    }}
    QCheckBox::indicator:checked {{
        image: url(ui/assets/checkbox_round_active.svg);
        background: transparent;
        border: 0px;
        width: 20px;
        height: 20px;
    }}
    QCheckBox::indicator:checked:hover {{
        image: url(ui/assets/checkbox_round_active.svg);
        background: transparent;
        border: 0px;
        width: 20px;
        height: 20px;
    }}
    QCheckBox::indicator:disabled {{
        image: url(ui/assets/checkbox_round_inactive.svg);
        background: transparent;
        border: 0px;
        width: 20px;
        height: 20px;
    }}
    QCheckBox::indicator:checked:disabled {{
        image: url(ui/assets/checkbox_round_active.svg);
        background: transparent;
        border: 0px;
        width: 20px;
        height: 20px;
    }}
    """


MPRC_CHECKBOX_STYLESHEET = _mprc_checkbox_stylesheet()


class _MprcRefineBridge(QtCore.QObject):
    finished = QtCore.Signal(str, str, str, str)

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.finished.connect(self._on_finished)

    @QtCore.Slot(str, str, str, str)
    def _on_finished(self, token: str, field_label: str, refined_text: str, error: str):
        controller = getattr(self, "controller", None)
        if controller is not None:
            controller._on_field_refined(str(token or ""), str(field_label or ""), str(refined_text or ""), str(error or ""))


class _MprcStoryBridge(QtCore.QObject):
    finished = QtCore.Signal(str, str, str)

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.finished.connect(self._on_finished)

    @QtCore.Slot(str, str, str)
    def _on_finished(self, token: str, payload_text: str, error: str):
        controller = getattr(self, "controller", None)
        if controller is not None:
            controller._on_master_story_generated(str(token or ""), str(payload_text or ""), str(error or ""))


class _MprcChatTurnBridge(QtCore.QObject):
    finished = QtCore.Signal(str, str, str)

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.finished.connect(self._on_finished)

    @QtCore.Slot(str, str, str)
    def _on_finished(self, token: str, reply_text: str, error: str):
        controller = getattr(self, "controller", None)
        if controller is not None:
            controller._on_mprc_chat_turn_finished(str(token or ""), str(reply_text or ""), str(error or ""))


class _MprcVoicePreviewBridge(QtCore.QObject):
    finished = QtCore.Signal(str, str)

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.finished.connect(self._on_finished)

    @QtCore.Slot(str, str)
    def _on_finished(self, token: str, error: str):
        controller = getattr(self, "controller", None)
        if controller is not None:
            controller._on_voice_preview_finished(str(token or ""), str(error or ""))


class _MprcObjectResultBridge(QtCore.QObject):
    finished = QtCore.Signal(object, object)

    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self._callback = callback
        self.finished.connect(self._on_finished)

    @QtCore.Slot(object, object)
    def _on_finished(self, key, result):
        callback = getattr(self, "_callback", None)
        if callable(callback):
            callback(key, result)


class _MprcStoryAudioBridge(QtCore.QObject):
    play_requested = QtCore.Signal(object)

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.play_requested.connect(self._on_play_requested)

    @QtCore.Slot(object)
    def _on_play_requested(self, entry):
        controller = getattr(self, "controller", None)
        if controller is not None and not controller.is_shutdown():
            controller._play_story_audio_entry(entry)


class _MprcUiBridge(QtCore.QObject):
    refresh_requested = QtCore.Signal()
    debug_refresh_requested = QtCore.Signal()
    event_log_refresh_requested = QtCore.Signal()
    visual_reply_requested = QtCore.Signal(str, str)
    tts_character_image_requested = QtCore.Signal(str)
    tts_visual_reply_requested = QtCore.Signal(str, str)
    manual_visual_finished = QtCore.Signal(str, str, object)
    remote_request = QtCore.Signal(object)
    shutdown_requested = QtCore.Signal()

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.refresh_requested.connect(self._on_refresh_requested)
        self.debug_refresh_requested.connect(self._on_debug_refresh_requested)
        self.event_log_refresh_requested.connect(self._on_event_log_refresh_requested)
        self.visual_reply_requested.connect(self._on_visual_reply_requested)
        self.tts_character_image_requested.connect(self._on_tts_character_image_requested)
        self.tts_visual_reply_requested.connect(self._on_tts_visual_reply_requested)
        self.manual_visual_finished.connect(self._on_manual_visual_finished)
        self.remote_request.connect(self._on_remote_request)
        self.shutdown_requested.connect(self._on_shutdown_requested)

    @QtCore.Slot()
    def _on_refresh_requested(self):
        controller = getattr(self, "controller", None)
        if controller is not None and not controller.is_shutdown():
            controller.refresh_ui()

    @QtCore.Slot()
    def _on_debug_refresh_requested(self):
        controller = getattr(self, "controller", None)
        if controller is not None and not controller.is_shutdown():
            controller._refresh_debug()

    @QtCore.Slot()
    def _on_event_log_refresh_requested(self):
        controller = getattr(self, "controller", None)
        if controller is not None and not controller.is_shutdown():
            controller._refresh_event_log_panel()

    @QtCore.Slot(str, str)
    def _on_visual_reply_requested(self, persona_id: str, reason: str):
        controller = getattr(self, "controller", None)
        if controller is not None and not controller.is_shutdown():
            controller._queue_visual_worker(
                "mprc_visual_reply",
                lambda: controller._run_auto_visual_reply_request(str(persona_id or ""), str(reason or "manual")),
            )

    @QtCore.Slot(str)
    def _on_tts_character_image_requested(self, persona_id: str):
        controller = getattr(self, "controller", None)
        if controller is not None and not controller.is_shutdown():
            controller._queue_visual_worker(
                "mprc_tts_character_image",
                lambda: controller._run_tts_character_image_request(str(persona_id or "")),
            )

    @QtCore.Slot(str, str)
    def _on_tts_visual_reply_requested(self, persona_id: str, spoken_text: str):
        controller = getattr(self, "controller", None)
        if controller is not None and not controller.is_shutdown():
            controller._queue_visual_worker(
                "mprc_tts_visual_reply",
                lambda: controller._run_tts_visual_reply_request(str(persona_id or ""), str(spoken_text or "")),
            )

    @QtCore.Slot(str, str, object)
    def _on_manual_visual_finished(self, kind: str, persona_id: str, result):
        controller = getattr(self, "controller", None)
        if controller is not None and not controller.is_shutdown():
            controller._on_manual_visual_finished(str(kind or ""), str(persona_id or ""), result)

    @QtCore.Slot(object)
    def _on_remote_request(self, payload):
        controller = getattr(self, "controller", None)
        if controller is not None and not controller.is_shutdown():
            controller._handle_remote_thread_request(payload)

    @QtCore.Slot()
    def _on_shutdown_requested(self):
        controller = getattr(self, "controller", None)
        if controller is not None:
            controller._shutdown_qt_objects()


class _MprcTabButton(QtWidgets.QFrame):
    clicked = QtCore.Signal(int)
    move_requested = QtCore.Signal(int, int)

    def __init__(self, index: int, title: str, icon: QtGui.QIcon, color: str, tooltip: str, parent=None):
        super().__init__(parent)
        self._index = index
        self._color = color
        self._selected = False
        self._drag_start_pos = QtCore.QPoint()
        self._dragging = False
        self._last_move_target_index: int | None = None
        self.setObjectName("mprc_custom_tab_button")
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip((str(tooltip or "").strip() + "\nDrag to move this tab button.").strip())
        self.setMinimumSize(80, 68)
        self.setMaximumSize(96, 68)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(7, 4, 7, 5)
        layout.setSpacing(1)

        self._title = QtWidgets.QLabel(title)
        self._title.setObjectName("mprc_custom_tab_title")
        self._title.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self._title.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)
        title_font = self._title.font()
        title_font.setBold(True)
        self._title.setFont(title_font)
        self._title.setMinimumHeight(16)

        self._icon = QtWidgets.QLabel()
        self._icon.setObjectName("mprc_custom_tab_icon")
        self._icon.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self._icon.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)
        self._icon.setPixmap(icon.pixmap(QtCore.QSize(36, 36)))
        self._icon.setFixedHeight(38)

        layout.addWidget(self._title)
        layout.addWidget(self._icon)
        self._apply_style()

    def set_selected(self, selected: bool):
        self._selected = bool(selected)
        self._apply_style()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_start_pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            self._dragging = False
            self._last_move_target_index = None
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & QtCore.Qt.LeftButton:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            if (pos - self._drag_start_pos).manhattanLength() >= QtWidgets.QApplication.startDragDistance():
                self._dragging = True
                self.setCursor(QtCore.Qt.ClosedHandCursor)
                target = self._tab_button_at_event(event)
                if target is not None and target is not self and target._index != self._last_move_target_index:
                    self._last_move_target_index = target._index
                    self.move_requested.emit(self._index, target._index)
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            if self._dragging:
                target = self._tab_button_at_event(event)
                if target is not None and target is not self and target._index != self._last_move_target_index:
                    self.move_requested.emit(self._index, target._index)
            else:
                self.clicked.emit(self._index)
            self._dragging = False
            self._last_move_target_index = None
            self.setCursor(QtCore.Qt.PointingHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    @staticmethod
    def _tab_button_at_event(event) -> "_MprcTabButton | None":
        try:
            global_pos = event.globalPosition().toPoint()
        except Exception:
            global_pos = event.globalPos()
        widget = QtWidgets.QApplication.widgetAt(global_pos)
        while widget is not None:
            if isinstance(widget, _MprcTabButton):
                return widget
            widget = widget.parentWidget()
        return None

    def _apply_style(self):
        background = "#1c2d43" if self._selected else "#111b28"
        border = self._color if self._selected else "#36506d"
        bottom = self._color if self._selected else "#36506d"
        self.setStyleSheet(
            f"""
            QFrame#mprc_custom_tab_button {{
                background: {background};
                border: 1px solid {border};
                border-bottom-color: {bottom};
                border-radius: 9px;
            }}
            QLabel#mprc_custom_tab_title {{
                color: {self._color};
                font-weight: 800;
                background: transparent;
                border: none;
            }}
            QLabel#mprc_custom_tab_icon {{
                background: transparent;
                border: none;
            }}
            """
        )


class _MprcCurrentPageStack(QtWidgets.QStackedWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.currentChanged.connect(lambda *_args: self.updateGeometry())

    def sizeHint(self):
        current = self.currentWidget()
        return current.sizeHint() if current is not None else super().sizeHint()

    def minimumSizeHint(self):
        current = self.currentWidget()
        return current.minimumSizeHint() if current is not None else super().minimumSizeHint()


class _MprcTabNavScrollArea(QtWidgets.QScrollArea):
    def wheelEvent(self, event):
        event.ignore()


class _MprcFloatingPlayWindow(QtWidgets.QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setObjectName("mprc_floating_play_window")
        self.setWindowTitle("MPRC Play")
        self.setMinimumSize(920, 560)
        self.resize(1280, 820)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)

    def closeEvent(self, event):
        controller = getattr(self, "controller", None)
        if controller is not None and not controller.is_shutdown():
            controller._dock_chat_play_tab()
            event.ignore()
            return
        super().closeEvent(event)


class MultiPersonaRoleplayController:
    STATE_KEY = "multi_persona_roleplay"

    def __init__(self, context):
        self.context = context
        self._state_lock = threading.RLock()
        self._shutting_down = False
        self._worker_sequence = 0
        self._active_worker_tokens: set[str] = set()
        self._worker_threads: dict[str, threading.Thread] = {}
        self._refine_widgets: dict[str, weakref.ReferenceType[Any]] = {}
        self.storage = RoleplayStorage(context)
        self.storage.ensure_defaults()
        self.personas: list[PersonaConfig] = self.storage.load_personas()
        self.session: RoleplaySessionState = self.storage.load_session()
        self.visual_styles = self.storage.load_visual_styles()
        self.settings = self.storage.load_settings()
        self._ensure_remote_settings_defaults()
        self._ensure_chromecast_settings_defaults()
        self.long_memory = RoleplayLongMemory(self.storage, logger=getattr(context, "logger", None))
        self.voice_router = PersonaVoiceRouter(self)
        self.roleplay_engine = RoleplayEngine(self)
        self.visual_reply = PersonaVisualReply(self)
        self.visual_reply_service = self._host_service("qt.visual_reply")
        self.dialog_service = self._host_service("qt.dialogs") or self._host_service("qt.dialog")
        self.runtime_config = self._host_service("qt.runtime_config")
        self.runtime_controls = self._host_service("qt.runtime_controls")
        self.shell = self._host_service("qt.shell")
        self._widget = None
        self._debug_prompt = ""
        self._debug_visual_prompt = ""
        self._chat_visual_prompt_debug = ""
        self._debug_voice = ""
        self._validation_result = ""
        self._story_event_log: list[dict[str, str]] = self._load_story_event_log()
        self._visual_debug_log: list[dict[str, str]] = self._load_visual_debug_log()
        self._audiofx_player = None
        self._audiofx_output = None
        self._guide_speech_process = None
        self._guide_speech_command_cache: dict[str, Any] | None = None
        self._guide_speech_command_checked = False
        self._story_audio_block_active = False
        self._story_audio_pending_text = ""
        self._last_story_audio_cues: dict[str, float] = {}
        self._syncing = False
        self._controls: dict[str, Any] = {}
        self._refine_bridge = _MprcRefineBridge(self)
        self._story_bridge = _MprcStoryBridge(self)
        self._chat_turn_bridge = _MprcChatTurnBridge(self)
        self._voice_preview_bridge = _MprcVoicePreviewBridge(self)
        self._story_audio_bridge = _MprcStoryAudioBridge(self)
        self._ui_bridge = _MprcUiBridge(self)
        self._adopt_qobject_bridges(self._qt_application_instance())
        self._editor_commit_timer = QtCore.QTimer()
        self._editor_commit_timer.setSingleShot(True)
        self._editor_commit_timer.timeout.connect(self._commit_scheduled_editor)
        self._editor_commit_include_identity = False
        self._commit_timers: dict[str, QtCore.QTimer] = {}
        self._master_story_draft: dict[str, Any] = {}
        self._manual_character_image_inflight: set[str] = set()
        self._tts_persona_visual_inflight: set[str] = set()
        self._tts_visual_reply_inflight: set[str] = set()
        self._last_tts_visual_reply_at: dict[str, float] = {}
        self._suppress_next_auto_visual_reply = False
        self._mprc_tts_lock = threading.RLock()
        self._mprc_tts_state_lock = threading.RLock()
        self._mprc_tts_controller = None
        self._mprc_tts_token = ""
        self._voice_preview_status_widgets: dict[str, weakref.ReferenceType[Any]] = {}
        self._mprc_chat_history: list[dict[str, str]] = []
        self._mprc_pending_chat_users: dict[str, dict[str, str]] = {}
        self._remote_backend: MPRCRemoteBackend | None = None
        self._remote_latest_reply_text = ""
        self._remote_audio_lock = threading.RLock()
        self._remote_audio_generation = 0
        self._remote_audio_capture_until = 0.0
        self._remote_audio_items: list[dict[str, Any]] = []
        self._remote_audio_status = "idle"
        self._remote_audio_source_excerpt = ""
        self._chromecast_bridge = MprcChromecastBridge(self)
        self._chromecast_ui_busy = False
        self._chromecast_ui_status = ""
        self._last_spotify_story_music_key = ""
        self._last_spotify_story_music_at = 0.0
        self._last_spotify_story_music_payload: dict[str, Any] = {}
        self._last_spotify_story_music_result: dict[str, Any] = {}
        self._chat_play_page = None
        self._chat_play_placeholder = None
        self._chat_play_floating_window = None
        self._chat_play_stack_index = -1
        self._ensure_session_persona()
        self._sync_remote_backend_from_settings()

    def _host_service(self, name: str):
        try:
            return self.context.get_service(name)
        except Exception:
            return None

    def _peer_service(self, name: str):
        services = getattr(self.context, "services", None)
        if services is None:
            return None
        try:
            return services.get(str(name or ""), None)
        except TypeError:
            try:
                return services.get(str(name or ""))
            except Exception:
                return None
        except Exception:
            return None

    def _spotify_sense_service(self):
        return self._peer_service("spotify.sense")

    def _remote_server_installed(self) -> bool:
        return bool(self.settings.get("remote_server_installed", False))

    def _ensure_remote_settings_defaults(self, *, installed: bool | None = None) -> None:
        changed = False
        installed = self._remote_server_installed() if installed is None else bool(installed)
        if self.settings.get("remote_server_installed") != installed:
            self.settings["remote_server_installed"] = installed
            changed = True
        if self.settings.pop("remote_token", None) is not None:
            changed = True
        if not installed:
            if bool(self.settings.get("remote_enabled", False)):
                self.settings["remote_enabled"] = False
                changed = True
            if changed:
                self.storage.save_settings(self.settings)
            return
        if "remote_enabled" not in self.settings:
            self.settings["remote_enabled"] = False
            changed = True
        if not str(self.settings.get("remote_host") or "").strip():
            self.settings["remote_host"] = "0.0.0.0"
            changed = True
        try:
            port = int(self.settings.get("remote_port", DEFAULT_REMOTE_PORT) or DEFAULT_REMOTE_PORT)
        except Exception:
            port = DEFAULT_REMOTE_PORT
        port = max(1, min(65535, port))
        if self.settings.get("remote_port") != port:
            self.settings["remote_port"] = port
            changed = True
        code = self._normalized_remote_code(self.settings.get("remote_code"))
        if not code:
            self.settings["remote_code"] = generate_remote_code()
            changed = True
        elif self.settings.get("remote_code") != code:
            self.settings["remote_code"] = code
            changed = True
        if changed:
            self.storage.save_settings(self.settings)

    def _ensure_chromecast_settings_defaults(self) -> None:
        changed = False
        if "chromecast_device_name" not in self.settings:
            self.settings["chromecast_device_name"] = ""
            changed = True
        try:
            port = int(self.settings.get("chromecast_stream_port", DEFAULT_MPRC_CAST_STREAM_PORT) or DEFAULT_MPRC_CAST_STREAM_PORT)
        except Exception:
            port = DEFAULT_MPRC_CAST_STREAM_PORT
        port = max(1024, min(65535, port))
        if self.settings.get("chromecast_stream_port") != port:
            self.settings["chromecast_stream_port"] = port
            changed = True
        if changed:
            self.storage.save_settings(self.settings)

    def is_shutdown(self) -> bool:
        with self._state_lock:
            return bool(self._shutting_down)

    @staticmethod
    def _qt_application_instance() -> QtCore.QObject | None:
        try:
            instance = getattr(QtCore.QCoreApplication, "instance", None)
            return instance() if callable(instance) else None
        except Exception:
            return None

    def _is_ui_thread(self) -> bool:
        app = self._qt_application_instance()
        try:
            return bool(app is not None and QtCore.QThread.currentThread() == app.thread())
        except Exception:
            return False

    def _adopt_qobject_bridges(self, parent: QtCore.QObject | None) -> None:
        app = self._qt_application_instance()
        ui_thread = app.thread() if app is not None else None
        for bridge in (
            getattr(self, "_refine_bridge", None),
            getattr(self, "_story_bridge", None),
            getattr(self, "_chat_turn_bridge", None),
            getattr(self, "_story_audio_bridge", None),
            getattr(self, "_ui_bridge", None),
        ):
            if bridge is None:
                continue
            try:
                if ui_thread is not None and bridge.thread() != ui_thread and bridge.parent() is None:
                    bridge.moveToThread(ui_thread)
                if parent is not None and bridge.parent() is not parent and bridge.thread() == parent.thread():
                    bridge.setParent(parent)
            except RuntimeError:
                pass

    def _new_worker_token(self, prefix: str) -> str:
        with self._state_lock:
            if self._shutting_down:
                return ""
            self._worker_sequence += 1
            token = f"{str(prefix or 'worker')}_{self._worker_sequence}"
            self._active_worker_tokens.add(token)
            return token

    def _worker_should_emit(self, token: str) -> bool:
        with self._state_lock:
            return bool(token and token in self._active_worker_tokens and not self._shutting_down)

    def _finish_worker_token(self, token: str) -> bool:
        with self._state_lock:
            self._worker_threads.pop(str(token or ""), None)
            if not token or token not in self._active_worker_tokens or self._shutting_down:
                self._active_worker_tokens.discard(str(token or ""))
                return False
            self._active_worker_tokens.discard(token)
        self._request_ui_refresh()
        return True

    def _cancel_worker_token(self, token: str) -> None:
        with self._state_lock:
            self._active_worker_tokens.discard(str(token or ""))
            self._worker_threads.pop(str(token or ""), None)

    def _start_daemon_worker(self, token: str, target, *, name: str) -> bool:
        if not token or not callable(target):
            return False
        thread = threading.Thread(target=target, name=name, daemon=True)
        with self._state_lock:
            if self._shutting_down or token not in self._active_worker_tokens:
                self._active_worker_tokens.discard(token)
                return False
            self._worker_threads[token] = thread
        thread.start()
        self._request_ui_refresh()
        return True

    def invoke_capability_threadsafe(self, capability: str, payload: dict[str, Any] | None = None):
        name = str(capability or "").strip().lower()
        data = dict(payload or {})
        with self._state_lock:
            if self._shutting_down:
                return None
            if name == "chat_context.collect":
                return self.roleplay_engine.chat_context(data)
            if name == "tts.voice_route":
                return self.voice_router.effective_voice_config(data)
            if name == "tts.voice_segments":
                return self.voice_router.split_text_by_persona(data)
            if name == "tts.segment_started":
                self.handle_tts_persona_visual(
                    str(data.get("persona_id") or ""),
                    str(data.get("text") or ""),
                )
                return True
            if name == "tts.audio_chunk_ready":
                return self.handle_tts_audio_chunk_ready(data)
            if name == "roleplay.assistant_reply":
                self.roleplay_engine.record_assistant_text(str(data.get("text") or ""))
                return True
            if name == "roleplay.play_audio_cues":
                return self.play_story_audio_cue_ids(list(data.get("cue_ids") or []))
            if name == "roleplay.audio_settings":
                return self.audio_settings_snapshot()
        if name == "mprc.remote_state":
            return self.remote_snapshot()
        if name == "mprc.remote_send":
            text = str(data.get("text") or data.get("message") or "").strip()
            if not text:
                return {"accepted": False, "message": "text is required"}
            return self.remote_send_user_text(
                text,
                intent=str(data.get("intent") or "Auto"),
                speaker_id=str(data.get("speaker_id") or ""),
            )
        if name == "mprc.remote_choice":
            choice = str(data.get("choice") or data.get("choice_id") or data.get("text") or "").strip()
            if not choice:
                return {"accepted": False, "message": "choice is required"}
            return self.remote_select_choice(choice)
        if name == "mprc.remote_play":
            return self.remote_play()
        if name == "mprc.remote_pause":
            return self.remote_pause()
        if name == "mprc.remote_visual":
            return self.remote_request_visual()
        if name == "mprc.remote_cast":
            return self.remote_chromecast_action(data)
        return None

    def shutdown(self) -> None:
        bridge = getattr(self, "_chromecast_bridge", None)
        if bridge is not None:
            try:
                bridge.stop_stream()
            except Exception:
                pass
        self._stop_remote_backend()
        with self._state_lock:
            if self._shutting_down:
                return
            self._shutting_down = True
            self._active_worker_tokens.clear()
            self._worker_threads.clear()
            self._refine_widgets.clear()
        if self._is_ui_thread():
            self._shutdown_qt_objects()
            return
        bridge = getattr(self, "_ui_bridge", None)
        if bridge is not None:
            try:
                bridge.shutdown_requested.emit()
            except RuntimeError:
                pass

    def _shutdown_qt_objects(self) -> None:
        try:
            self._dock_chat_play_tab()
        except Exception:
            pass
        self._stop_guide_speech()
        player = getattr(self, "_audiofx_player", None)
        if player is not None:
            try:
                player.stop()
            except Exception:
                pass
            try:
                player.setAudioOutput(None)
            except Exception:
                pass
            try:
                player.deleteLater()
            except RuntimeError:
                pass
        output = getattr(self, "_audiofx_output", None)
        if output is not None:
            try:
                output.deleteLater()
            except RuntimeError:
                pass
        self._audiofx_player = None
        self._audiofx_output = None
        window = getattr(self, "_chat_play_floating_window", None)
        if window is not None:
            try:
                window.controller = None
                window.hide()
                window.deleteLater()
            except RuntimeError:
                pass
        self._chat_play_floating_window = None
        self._chat_play_placeholder = None
        self._chat_play_page = None
        self._chat_play_stack_index = -1
        for attr in ("_refine_bridge", "_story_bridge", "_chat_turn_bridge", "_voice_preview_bridge", "_story_audio_bridge", "_ui_bridge"):
            bridge = getattr(self, attr, None)
            if bridge is None:
                continue
            try:
                bridge.disconnect()
            except Exception:
                pass
            try:
                bridge.controller = None
            except Exception:
                pass
            try:
                bridge.setParent(None)
                bridge.deleteLater()
            except RuntimeError:
                pass
            setattr(self, attr, None)
        self._widget = None
        self._controls.clear()

    def _notify_changed(self):
        notifier = getattr(self.shell, "notify_settings_changed", None) if self.shell is not None else None
        if callable(notifier):
            notifier()

    def save_state(self):
        with self._state_lock:
            if self._shutting_down:
                return
            self.storage.save_personas(self.personas)
            self.storage.save_session(self.session)

    def _remote_host(self) -> str:
        return str(self.settings.get("remote_host") or "0.0.0.0").strip() or "0.0.0.0"

    def _remote_port(self) -> int:
        try:
            port = int(self.settings.get("remote_port", DEFAULT_REMOTE_PORT) or DEFAULT_REMOTE_PORT)
        except Exception:
            port = DEFAULT_REMOTE_PORT
        return max(1, min(65535, port))

    @staticmethod
    def _normalized_remote_code(value: Any) -> str:
        digits = re.sub(r"\D+", "", str(value or ""))
        if not digits:
            return ""
        try:
            numeric = int(digits)
        except Exception:
            return ""
        return f"{numeric:06d}" if 100000 <= numeric <= 999999 else ""

    def _remote_code(self) -> str:
        code = self._normalized_remote_code(self.settings.get("remote_code"))
        if code:
            return code
        code = generate_remote_code()
        self.settings["remote_code"] = code
        self.settings.pop("remote_token", None)
        self.storage.save_settings(self.settings)
        return code

    def _sync_remote_backend_from_settings(self) -> None:
        if not self._remote_server_installed():
            if bool(self.settings.get("remote_enabled", False)):
                self.settings["remote_enabled"] = False
                self.storage.save_settings(self.settings)
            self._stop_remote_backend()
            self._refresh_remote_controls()
            return
        self._ensure_remote_settings_defaults(installed=True)
        if bool(self.settings.get("remote_enabled", False)):
            self._start_remote_backend()
        else:
            self._stop_remote_backend()
        self._refresh_remote_controls()

    def _start_remote_backend(self) -> None:
        if not self._remote_server_installed():
            return
        host = self._remote_host()
        port = self._remote_port()
        code = self._remote_code()
        backend = getattr(self, "_remote_backend", None)
        if backend is not None and backend.running and backend.host == host and backend.port == port and backend.code == code:
            return
        if backend is not None:
            backend.stop()
        try:
            backend = MPRCRemoteBackend(self, host=host, port=port, code=code)
            backend.start()
            self._remote_backend = backend
            self._record_story_event(f"remote backend started at {backend.display_url}", severity="info", kind="runtime", persist=True)
        except Exception as exc:
            self._remote_backend = None
            self.settings["remote_enabled"] = False
            self.storage.save_settings(self.settings)
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[MPRC Remote] Could not start remote backend: %s", exc)
            self._record_story_event(f"remote backend failed to start: {exc}", severity="warning", kind="runtime", persist=True)

    def _stop_remote_backend(self) -> None:
        backend = getattr(self, "_remote_backend", None)
        self._remote_backend = None
        if backend is not None:
            backend.stop()

    def remote_status_snapshot(self) -> dict[str, Any]:
        if not self._remote_server_installed():
            return {
                "installed": False,
                "enabled": False,
                "running": False,
                "host": "",
                "port": int(DEFAULT_REMOTE_PORT),
                "url": "",
                "code_configured": False,
                "pairing_code": "",
                "connected_clients": 0,
                "clients": [],
                "started_at": 0.0,
            }
        backend = getattr(self, "_remote_backend", None)
        if backend is not None:
            status = backend.status_snapshot()
        else:
            status = {
                "installed": True,
                "enabled": bool(self.settings.get("remote_enabled", False)),
                "running": False,
                "host": self._remote_host(),
                "port": self._remote_port(),
                "url": f"http://{lan_ip_address() if self._remote_host() in {'', '0.0.0.0', '::'} else self._remote_host()}:{self._remote_port()}",
                "code_configured": bool(self._normalized_remote_code(self.settings.get("remote_code"))),
                "connected_clients": 0,
                "clients": [],
                "started_at": 0.0,
            }
        status["installed"] = True
        status["pairing_code"] = self._remote_code()
        status.update(self._engine_speech_status())
        return status

    def _engine_speech_status(self) -> dict[str, Any]:
        try:
            from core.engine_access import engine_module

            engine = engine_module()
            audio_playing = getattr(engine, "audio_playing", None)
            playback_paused = getattr(engine, "playback_paused", None)
            pause_after_chunk = getattr(engine, "pause_after_chunk", None)
            manual_pause_active = getattr(engine, "manual_pause_active", None)
            return {
                "speech_playing": bool(audio_playing is not None and hasattr(audio_playing, "is_set") and audio_playing.is_set()),
                "speech_paused": bool(
                    (playback_paused is not None and hasattr(playback_paused, "is_set") and playback_paused.is_set())
                    or (pause_after_chunk is not None and hasattr(pause_after_chunk, "is_set") and pause_after_chunk.is_set())
                    or (manual_pause_active is not None and hasattr(manual_pause_active, "is_set") and manual_pause_active.is_set())
                ),
            }
        except Exception:
            return {"speech_playing": False, "speech_paused": False}

    def _set_engine_speech_paused(self, paused: bool) -> bool:
        try:
            from core.engine_access import engine_module

            engine = engine_module()
            playback_paused = getattr(engine, "playback_paused", None)
            pause_after_chunk = getattr(engine, "pause_after_chunk", None)
            manual_pause_active = getattr(engine, "manual_pause_active", None)
            if paused:
                if manual_pause_active is not None and hasattr(manual_pause_active, "set"):
                    manual_pause_active.set()
                if pause_after_chunk is not None and hasattr(pause_after_chunk, "set"):
                    pause_after_chunk.set()
                return True
            if manual_pause_active is not None and hasattr(manual_pause_active, "clear"):
                manual_pause_active.clear()
            if pause_after_chunk is not None and hasattr(pause_after_chunk, "clear"):
                pause_after_chunk.clear()
            if playback_paused is not None and hasattr(playback_paused, "clear"):
                playback_paused.clear()
            try:
                engine.last_resume_requested_at = time.time()
            except Exception:
                pass
            return True
        except Exception:
            return False

    def _remote_audio_cache_dir(self) -> Path:
        root = Path(__file__).resolve().parents[2] / "runtime" / "mprc_remote_audio"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _begin_remote_speech_audio_capture(self, reply_text: str) -> None:
        if not self._remote_server_installed() or not bool(self.settings.get("remote_enabled", False)):
            return
        with self._remote_audio_lock:
            self._remote_audio_generation += 1
            old_items = list(self._remote_audio_items or [])
            self._remote_audio_items = []
            self._remote_audio_status = "rendering"
            self._remote_audio_capture_until = time.time() + 900.0
            self._remote_audio_source_excerpt = self._mprc_compact(str(reply_text or ""), 240)
        for item in old_items:
            path = Path(str(item.get("_file_path") or ""))
            if path.exists():
                try:
                    path.unlink()
                except Exception:
                    pass

    def handle_tts_audio_chunk_ready(self, payload: dict[str, Any] | None = None):
        if not self._remote_server_installed() or not bool(self.settings.get("remote_enabled", False)):
            return None
        data = dict(payload or {})
        source_path = Path(str(data.get("audio_path") or ""))
        if not source_path.exists() or source_path.suffix.lower() != ".wav":
            return None
        now = time.time()
        with self._remote_audio_lock:
            if now > float(self._remote_audio_capture_until or 0.0):
                return None
            generation = int(self._remote_audio_generation or 0)
            index = len(self._remote_audio_items) + 1
        target_id = f"g{generation:04d}_{index:03d}_{int(now * 1000)}"
        target_path = self._remote_audio_cache_dir() / f"{target_id}.wav"
        try:
            shutil.copy2(source_path, target_path)
        except Exception as exc:
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[MPRC Remote] Could not copy TTS chunk for phone audio: %s", exc)
            return None
        duration = self._wav_duration_seconds(target_path)
        meta = dict(data.get("source_meta") or {}) if isinstance(data.get("source_meta"), dict) else {}
        item = {
            "id": target_id,
            "_file_path": str(target_path),
            "url_path": f"/api/speech-audio/file/{target_id}",
            "index": index,
            "text": str(data.get("text") or "").strip(),
            "persona_id": str(meta.get("persona_id") or ""),
            "speaker": str(meta.get("display_name") or meta.get("persona_id") or "Narrator").strip() or "Narrator",
            "duration_seconds": duration,
            "created_at": now,
        }
        with self._remote_audio_lock:
            if generation != int(self._remote_audio_generation or 0):
                try:
                    target_path.unlink()
                except Exception:
                    pass
                return None
            self._remote_audio_items.append(item)
            self._remote_audio_items = self._remote_audio_items[-48:]
            self._remote_audio_status = "ready"
        return True

    @staticmethod
    def _wav_duration_seconds(path: Path) -> float:
        try:
            with wave.open(str(path), "rb") as handle:
                frames = int(handle.getnframes() or 0)
                rate = int(handle.getframerate() or 0)
            return round(frames / rate, 3) if rate > 0 else 0.0
        except Exception:
            return 0.0

    def remote_speech_audio_snapshot(self) -> dict[str, Any]:
        with self._remote_audio_lock:
            items = [
                {key: value for key, value in dict(item).items() if not str(key).startswith("_")}
                for item in list(self._remote_audio_items or [])
            ]
            status = str(self._remote_audio_status or "idle")
            capture_active = time.time() <= float(self._remote_audio_capture_until or 0.0)
            generation = int(self._remote_audio_generation or 0)
            source_excerpt = str(self._remote_audio_source_excerpt or "")
        if not items and not capture_active:
            status = "idle"
        return {
            "available": bool(items),
            "status": status,
            "generation": generation,
            "capture_active": bool(capture_active),
            "source_excerpt": source_excerpt,
            "items": items,
        }

    def remote_speech_audio_file_path(self, audio_id: str) -> Path:
        wanted = re.sub(r"[^A-Za-z0-9_.-]+", "", str(audio_id or ""))
        if not wanted:
            raise FileNotFoundError("speech audio id is required")
        with self._remote_audio_lock:
            for item in list(self._remote_audio_items or []):
                if str(item.get("id") or "") == wanted:
                    path = Path(str(item.get("_file_path") or ""))
                    if path.exists() and path.is_file():
                        return path
        raise FileNotFoundError("speech audio chunk not found")

    def _handle_remote_thread_request(self, payload) -> None:
        data = payload if isinstance(payload, dict) else {}
        event = data.get("event")
        try:
            func = data.get("func")
            if not callable(func):
                raise RuntimeError("remote request is missing callable")
            data["result"] = func()
        except Exception as exc:
            data["error"] = str(exc) or repr(exc)
        finally:
            if event is not None and hasattr(event, "set"):
                event.set()

    def _run_remote_on_ui_thread(self, func, *, timeout: float = 30.0):
        if not callable(func):
            raise RuntimeError("remote UI request is not callable")
        if self._is_ui_thread():
            return func()
        bridge = getattr(self, "_ui_bridge", None)
        if bridge is None:
            raise RuntimeError("MPRC UI bridge is unavailable")
        event = threading.Event()
        payload: dict[str, Any] = {"func": func, "event": event, "result": None, "error": ""}
        try:
            bridge.remote_request.emit(payload)
        except RuntimeError as exc:
            raise RuntimeError(f"MPRC UI bridge rejected remote request: {exc}") from exc
        if not event.wait(max(1.0, float(timeout or 30.0))):
            raise RuntimeError("MPRC remote request timed out waiting for UI thread")
        if payload.get("error"):
            raise RuntimeError(str(payload.get("error") or "MPRC remote request failed"))
        return payload.get("result")

    def remote_personas_snapshot(self) -> list[dict[str, Any]]:
        active_id = str(self.session.active_persona_id or "")
        current_id = str(self.session.current_speaker_id or "")
        narrator_id = self.selected_narrator_persona_id()
        items: list[dict[str, Any]] = []
        for persona in list(self.personas or []):
            items.append(
                {
                    "id": persona.id,
                    "display_name": persona.display_name,
                    "role": persona.role or persona.behavior_mode,
                    "enabled": bool(persona.enabled),
                    "active": persona.id == active_id,
                    "current_speaker": persona.id == current_id,
                    "narrator": persona.id == narrator_id,
                    "description": self._mprc_compact(persona.ar_description or persona.description, 400),
                    "visual_enabled": bool(persona.visual.enabled),
                    "voice_enabled": bool(persona.voice.enabled),
                }
            )
        return items

    def remote_session_snapshot(self) -> dict[str, Any]:
        state = self.session.ar_state
        return {
            "enabled": bool(self.session.enabled),
            "mode": self.session.mode,
            "turn_index": int(self.session.turn_index or 0),
            "active_persona_id": self.session.active_persona_id,
            "current_speaker_id": self.session.current_speaker_id,
            "scene_title": self.session.scene_title,
            "location": state.location or self.session.location,
            "time_of_day": state.time_of_day or self.session.time_of_day,
            "mood": state.mood or self.session.mood,
            "objective": state.story_goal or self.session.objective,
            "scene_summary": self.session.scene_summary,
            "ar_state": state.to_dict(),
            "character_state_summaries": dict(self.session.character_state_summaries or {}),
        }

    def remote_memory_snapshot(self) -> dict[str, Any]:
        memory = getattr(self, "long_memory", None)
        if memory is None:
            return {
                "available": False,
                "backend": "unavailable",
                "status": "unavailable",
                "message": "Story memory is not available.",
            }
        try:
            payload = memory.load()
        except Exception as exc:
            return {
                "available": False,
                "backend": "unavailable",
                "status": "error",
                "message": f"Story memory could not be read: {exc}",
            }

        settings = dict(getattr(self, "settings", {}) or {})
        database = getattr(memory, "database", None)
        backend = self._remote_memory_backend_label(database, settings)
        configured_sources = self._remote_memory_databank_sources(settings)
        event_count = len([item for item in list(payload.get("events") or []) if isinstance(item, dict)])
        chapter_count = len([item for item in list(payload.get("chapters") or []) if isinstance(item, dict)])
        pinned = [str(item).strip() for item in list(payload.get("pinned_facts") or []) if str(item).strip()]
        character_memory = payload.get("character_memory") if isinstance(payload.get("character_memory"), dict) else {}
        location_memory = payload.get("location_memory") if isinstance(payload.get("location_memory"), dict) else {}
        database_available = database is not None
        databank = getattr(memory, "databank", None)
        indexed_sources = getattr(memory, "_indexed_databank_sources", set()) or set()
        configured_backend = str(
            settings.get("long_memory_database_backend")
            or settings.get("memory_database_backend")
            or ""
        ).strip().lower()
        fallback_note = ""
        if configured_backend in {"postgres", "postgresql"} and backend == "sqlite":
            fallback_note = "PostgreSQL is configured but SQLite is active."
        return {
            "available": True,
            "backend": backend,
            "configured_backend": configured_backend or "sqlite",
            "database_available": bool(database_available),
            "database_status": "ready" if database_available else "json_only",
            "databank_available": databank is not None,
            "configured_databank_source_count": len(configured_sources),
            "indexed_databank_source_count": len(indexed_sources),
            "event_count": event_count,
            "chapter_count": chapter_count,
            "pinned_fact_count": len(pinned),
            "character_memory_count": len(character_memory),
            "location_memory_count": len(location_memory),
            "fallback_note": fallback_note,
        }

    @staticmethod
    def _remote_memory_backend_label(database, settings: dict[str, Any]) -> str:
        type_name = type(database).__name__.lower() if database is not None else ""
        if "postgres" in type_name:
            return "postgresql"
        if "sqlite" in type_name:
            return "sqlite"
        configured = str(
            settings.get("long_memory_database_backend")
            or settings.get("memory_database_backend")
            or ""
        ).strip().lower()
        if configured in {"postgres", "postgresql"}:
            return "postgresql"
        if configured == "sqlite":
            return "sqlite"
        return "json"

    @staticmethod
    def _remote_memory_databank_sources(settings: dict[str, Any]) -> list[str]:
        sources = settings.get("long_memory_databank_sources") or settings.get("memory_databank_sources") or []
        if isinstance(sources, str):
            return [line.strip() for line in sources.splitlines() if line.strip()]
        return [str(item).strip() for item in list(sources or []) if str(item or "").strip()]

    def remote_snapshot(self) -> dict[str, Any]:
        latest_reply = self._remote_latest_reply()
        choices = self._extract_ar_choices(latest_reply) or [
            str(item)
            for item in list(self.session.ar_state.pending_choices or [])
            if str(item or "").strip()
        ]
        return {
            "schema_version": 1,
            "remote": self.remote_status_snapshot(),
            "session": self.remote_session_snapshot(),
            "personas": self.remote_personas_snapshot(),
            "latest_reply": latest_reply,
            "segments": self._remote_story_segments(latest_reply),
            "choices": [
                {"id": str(index), "text": choice}
                for index, choice in enumerate(choices[:6], start=1)
            ],
            "memory": self.remote_memory_snapshot(),
            "speech_audio": self.remote_speech_audio_snapshot(),
            "audio_cues": self.available_story_audio_files(),
            "cast": self.remote_chromecast_snapshot(),
            "visual": {
                "latest_prompt": str(self._debug_visual_prompt or self._chat_visual_prompt_debug or ""),
                "last_visual_reply_at": float(self.session.last_visual_reply_at or 0.0),
                "auto_image_count": int(self.session.auto_image_count or 0),
            },
        }

    def _remote_latest_reply(self) -> str:
        if str(self._remote_latest_reply_text or "").strip():
            return str(self._remote_latest_reply_text or "").strip()
        for message in reversed(list(self._mprc_chat_history or [])):
            if str((message or {}).get("role") or "").strip().lower() == "assistant":
                return str((message or {}).get("content") or "").strip()
        return ""

    def _remote_story_segments(self, text: str) -> list[dict[str, Any]]:
        raw = str(text or "").strip()
        if not raw:
            return []
        tag_pattern = re.compile(
            r"\[(NARRATOR|CHARACTER:\s*[^\]]+|AMBIENCE:\s*[^\]]+|AMBIENT:\s*[^\]]+|MUSIC:\s*[^\]]+|FX:\s*[^\]]+|SFX:\s*[^\]]+|STINGER:\s*[^\]]+|AUDIO:\s*[^\]]+|CHOICES)\]",
            flags=re.IGNORECASE,
        )
        matches = list(tag_pattern.finditer(raw))
        if not matches:
            return [{"segment_id": 1, "speaker_id": "narrator", "speaker_name": "Narrator", "role": "narrator", "text": raw}]
        segments: list[dict[str, Any]] = []
        for index, match in enumerate(matches):
            tag = str(match.group(1) or "").strip()
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
            body = raw[start:end].strip()
            lowered = tag.lower()
            if lowered == "choices":
                continue
            role = "narrator"
            speaker_name = "Narrator"
            speaker_id = "narrator"
            if lowered.startswith("character:"):
                role = "character"
                speaker_name = re.sub(r"^character:\s*", "", tag, flags=re.IGNORECASE).strip()
                speaker_id = self._remote_persona_id_for_name(speaker_name)
            elif ":" in tag:
                role = "audio"
                speaker_name = tag.split(":", 1)[0].strip().upper()
                speaker_id = "audio"
                body = f"[{tag}] {body}".strip()
            if body:
                segments.append(
                    {
                        "segment_id": len(segments) + 1,
                        "speaker_id": speaker_id,
                        "speaker_name": speaker_name,
                        "role": role,
                        "text": body,
                    }
                )
        return segments

    def _remote_persona_id_for_name(self, name: str) -> str:
        wanted = str(name or "").strip().lower()
        for persona in list(self.personas or []):
            if wanted in {persona.id.lower(), persona.display_name.strip().lower()}:
                return persona.id
        return normalize_persona_id(name) or "unknown_speaker"

    def remote_update_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        def apply_update():
            data = dict(payload or {})
            state = self.session.ar_state
            for key in ("scene_title", "location", "time_of_day", "mood", "objective", "scene_summary"):
                if key in data:
                    setattr(self.session, key, str(data.get(key) or "").strip())
            ar_payload = data.get("ar_state") if isinstance(data.get("ar_state"), dict) else data
            for key, attr in (
                ("current_scene", "current_scene"),
                ("location", "location"),
                ("time_of_day", "time_of_day"),
                ("mood", "mood"),
                ("story_goal", "story_goal"),
                ("player_intent", "player_intent"),
            ):
                if key in ar_payload:
                    setattr(state, attr, str(ar_payload.get(key) or "").strip())
            if "active_characters" in ar_payload and isinstance(ar_payload.get("active_characters"), list):
                state.active_characters = [
                    normalize_persona_id(item)
                    for item in ar_payload.get("active_characters")
                    if str(item or "").strip()
                ][:8]
            if "pending_choices" in ar_payload and isinstance(ar_payload.get("pending_choices"), list):
                state.pending_choices = [str(item or "").strip() for item in ar_payload.get("pending_choices") if str(item or "").strip()][:6]
            if "enabled" in data:
                self.session.enabled = bool(data.get("enabled"))
            if "mode" in data:
                mode = str(data.get("mode") or "").strip()
                if mode in SESSION_MODES:
                    self.session.mode = mode
            self.save_state()
            self._request_ui_refresh()
            return self.remote_snapshot()

        return self._run_remote_on_ui_thread(apply_update)

    def remote_send_user_text(self, text: str, *, intent: str = "Auto", speaker_id: str = "") -> dict[str, Any]:
        def send():
            player_text = str(text or "").strip()
            if not player_text:
                raise RuntimeError("text is required")
            if self._mprc_pending_chat_users:
                raise RuntimeError("MPRC turn is already running")
            self._stop_mprc_chat_speech()
            intent_text = self._infer_mprc_chat_intent(player_text, intent)
            latest_user_text = f"{intent_text}: {player_text}"
            self.session.ar_state.player_intent = latest_user_text
            speaker = self.persona_by_id(str(speaker_id or "").strip())
            if speaker is not None:
                self.session.current_speaker_id = speaker.id
            self.session.enabled = True
            if self.session.mode == AR_MODE:
                self.ensure_ar_state(latest_user_text)
            self.save_state()
            self._append_chat_play_line("Remote [{0}]".format(intent_text), player_text, role="user")
            self._start_mprc_chat_turn(intent=intent_text, player_text=player_text, speaker_id=str(speaker_id or "").strip())
            return self.remote_snapshot()

        return self._run_remote_on_ui_thread(send)

    def remote_select_choice(self, choice: str) -> dict[str, Any]:
        text = str(choice or "").strip()
        if text.isdigit():
            index = int(text) - 1
            choices = [str(item or "").strip() for item in list(self.session.ar_state.pending_choices or []) if str(item or "").strip()]
            if 0 <= index < len(choices):
                text = choices[index]
        return self.remote_send_user_text(text, intent="Auto")

    def remote_play(self) -> dict[str, Any]:
        def play():
            was_paused = bool(self._engine_speech_status().get("speech_paused", False))
            if was_paused and self._set_engine_speech_paused(False):
                self._append_chat_play_line("Remote", "Speech resume requested.", role="system")
                self._set_chat_play_status("MPRC Remote speech resume requested.")
                return self.remote_snapshot()
            self.session.enabled = True
            if self.session.mode == AR_MODE:
                self.ensure_ar_state("Continue")
            self.save_state()
            if int(getattr(self.session, "turn_index", 0) or 0) <= 0 and not self._mprc_pending_chat_users:
                self._start_mprc_opening_turn()
            else:
                self._append_chat_play_line("Remote", "Play/resume requested.", role="system")
                self._set_chat_play_status("MPRC Remote play/resume requested.")
            return self.remote_snapshot()

        return self._run_remote_on_ui_thread(play)

    def remote_pause(self) -> dict[str, Any]:
        def pause():
            self._set_engine_speech_paused(True)
            self._append_chat_play_line("Remote", "Speech pause requested.", role="system")
            self._set_chat_play_status("MPRC Remote speech pause requested. Current speech can resume from the remote app or PC Pause / Resume.")
            return self.remote_snapshot()

        return self._run_remote_on_ui_thread(pause)

    def remote_request_visual(self) -> dict[str, Any]:
        def request():
            persona = self.current_speaker_persona() or self.active_persona()
            if persona is None:
                raise RuntimeError("No active persona for Visual Reply")
            self.request_auto_visual_reply(persona.id, "manual", self._remote_latest_reply())
            self._set_chat_play_status("MPRC Remote Visual Reply requested.")
            return self.remote_snapshot()

        return self._run_remote_on_ui_thread(request)

    def remote_chromecast_snapshot(self) -> dict[str, Any]:
        bridge = getattr(self, "_chromecast_bridge", None)
        if bridge is None:
            return {
                "available": False,
                "dependency_error": "MPRC Chromecast bridge is unavailable.",
                "devices": [],
                "selected_device": "",
                "active_device": "",
                "casting": False,
                "busy": False,
                "status": "MPRC Chromecast bridge is unavailable.",
                "stream": {"running": False, "url": "", "port": DEFAULT_MPRC_CAST_STREAM_PORT},
            }
        return dict(bridge.snapshot() or {})

    def remote_chromecast_action(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        bridge = getattr(self, "_chromecast_bridge", None)
        if bridge is None:
            return {"accepted": False, "message": "MPRC Chromecast bridge is unavailable.", "cast": self.remote_chromecast_snapshot()}
        return dict(bridge.action(dict(payload or {})) or {})

    def export_session_state(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                self.STATE_KEY: {
                    "session": self.session.to_dict(),
                    "active_persona_id": self.session.active_persona_id,
                }
            }

    def import_session_state(self, payload: dict[str, Any] | None):
        data = dict(payload or {}).get(self.STATE_KEY)
        if isinstance(data, dict) and isinstance(data.get("session"), dict):
            with self._state_lock:
                if self._shutting_down:
                    return
                self.session = RoleplaySessionState.from_dict(data.get("session"))
                self._ensure_session_persona()
                self.save_state()
            self._request_ui_refresh()

    def current_tts_backend(self) -> str:
        try:
            if self.runtime_config is not None:
                return normalize_tts_backend(self.runtime_config.get("tts_backend", ""))
        except Exception:
            return ""
        try:
            snapshot = self.context.tts.snapshot()
            return normalize_tts_backend(snapshot.get("tts_backend") or snapshot.get("backend") or "")
        except Exception:
            return ""

    def story_sounds_enabled(self) -> bool:
        with self._state_lock:
            return bool(self.settings.get("story_sounds_enabled", True))

    def audio_settings_snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            items = self._audiofx_items()
            available = self.available_story_audio_files()
            return {
                "story_sounds_enabled": self.story_sounds_enabled(),
                "audio_fx_items": items,
                "ready_audio_fx_items": [item for item in items if self._audiofx_file_ready(item)],
                "available_audio_files": available,
            }

    def _load_story_event_log(self) -> list[dict[str, str]]:
        raw = self.settings.get("story_event_log")
        if not isinstance(raw, list):
            return []
        entries: list[dict[str, str]] = []
        for item in raw[-80:]:
            if not isinstance(item, dict):
                continue
            message = str(item.get("message") or "").strip()
            if not message:
                continue
            entries.append({
                "time": str(item.get("time") or "").strip(),
                "severity": str(item.get("severity") or "info").strip() or "info",
                "kind": str(item.get("kind") or "").strip(),
                "message": message[:500],
            })
        return entries

    def _record_story_event(self, message: str, *, severity: str = "info", kind: str = "", persist: bool = False) -> None:
        text = str(message or "").strip()
        if not text:
            return
        with self._state_lock:
            if self._shutting_down:
                return
            entry = {
                "time": QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate),
                "severity": str(severity or "info").strip() or "info",
                "kind": str(kind or "").strip(),
                "message": text[:500],
            }
            self._story_event_log.append(entry)
            self._story_event_log = self._story_event_log[-80:]
            if persist:
                self.settings["story_event_log"] = list(self._story_event_log)
                self.storage.save_settings(self.settings)
        self._request_event_log_refresh()

    def _story_event_log_text(self) -> str:
        if not self._story_event_log:
            return "No skipped or failed story actions have been recorded yet."
        lines = []
        for item in self._story_event_log[-40:]:
            stamp = str(item.get("time") or "").replace("T", " ")[:19]
            severity = str(item.get("severity") or "info").upper()
            kind = str(item.get("kind") or "").strip()
            prefix = f"{stamp} [{severity}]"
            if kind:
                prefix += f" {kind}:"
            lines.append(f"{prefix} {item.get('message') or ''}".strip())
        return "\n".join(lines)

    def _refresh_event_log_panel(self) -> None:
        widget = self._controls.get("story_event_log")
        if widget is not None and hasattr(widget, "setPlainText"):
            widget.setPlainText(self._story_event_log_text())

    def _request_event_log_refresh(self) -> None:
        bridge = getattr(self, "_ui_bridge", None)
        if bridge is None:
            return
        try:
            bridge.event_log_refresh_requested.emit()
        except RuntimeError:
            pass

    def _load_visual_debug_log(self) -> list[dict[str, str]]:
        raw = self.settings.get("visual_reply_debug_log")
        if not isinstance(raw, list):
            return []
        entries: list[dict[str, str]] = []
        for item in raw[-120:]:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "").strip()
            message = str(item.get("message") or "").strip()
            prompt = str(item.get("prompt") or "").strip()
            if not source and not message and not prompt:
                continue
            entries.append({
                "time": str(item.get("time") or "").strip(),
                "status": str(item.get("status") or "info").strip() or "info",
                "source": source[:120],
                "reason": str(item.get("reason") or "").strip()[:80],
                "persona_id": str(item.get("persona_id") or "").strip()[:80],
                "persona": str(item.get("persona") or "").strip()[:120],
                "message": message[:500],
                "prompt": prompt[:1200],
            })
        return entries

    def _record_visual_debug(
        self,
        *,
        source: str,
        reason: str = "",
        persona: PersonaConfig | None = None,
        accepted: bool | None = None,
        message: str = "",
        prompt: str = "",
        persist: bool = True,
    ) -> None:
        with self._state_lock:
            if self._shutting_down:
                return
            raw_message = str(message or "").strip()
            if accepted is None:
                status = "queued"
            elif accepted:
                status = "accepted"
            else:
                lowered = raw_message.lower()
                status = "failed" if any(word in lowered for word in ("failed", "error", "exception", "crash")) else "skipped"
            entry = {
                "time": QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate),
                "status": status,
                "source": str(source or "").strip()[:120],
                "reason": str(reason or "").strip()[:80],
                "persona_id": str(getattr(persona, "id", "") or "").strip()[:80],
                "persona": str(getattr(persona, "display_name", "") or "").strip()[:120],
                "message": raw_message[:500],
                "prompt": str(prompt or "").strip()[:1200],
            }
            self._visual_debug_log.append(entry)
            self._visual_debug_log = self._visual_debug_log[-120:]
            if persist:
                self.settings["visual_reply_debug_log"] = list(self._visual_debug_log)
                self.storage.save_settings(self.settings)
        self._request_debug_refresh()

    def _visual_debug_log_text(self) -> str:
        if not self._visual_debug_log:
            return "No Visual Reply calls have been recorded yet."
        lines = []
        for item in self._visual_debug_log[-60:]:
            stamp = str(item.get("time") or "").replace("T", " ")[:19]
            status = str(item.get("status") or "info").upper()
            source = str(item.get("source") or "visual_reply")
            reason = str(item.get("reason") or "").strip()
            persona = str(item.get("persona") or item.get("persona_id") or "").strip()
            message = str(item.get("message") or "").strip()
            head = f"{stamp} [{status}] {source}"
            if reason:
                head += f" reason={reason}"
            if persona:
                head += f" persona={persona}"
            if message:
                head += f" - {message}"
            lines.append(head)
            prompt = str(item.get("prompt") or "").strip()
            if prompt:
                preview = " ".join(prompt.split())
                preview_text = prompting._compact(preview, 420)
                suffix = f" ({len(prompt)} chars)" if len(preview_text) < len(preview) else ""
                lines.append(f"    prompt preview{suffix}: {preview_text}")
        return "\n".join(lines)

    def _clear_visual_debug_log(self):
        with self._state_lock:
            self._visual_debug_log = []
            self.settings["visual_reply_debug_log"] = []
            self.storage.save_settings(self.settings)
        self._request_debug_refresh()

    def available_story_audio_files(self) -> list[dict[str, Any]]:
        items = self._audiofx_items()
        available = self._available_audio_files()
        if items:
            available = self._sync_available_audio_database(items, persist=False)
        return [item for item in available if bool(item.get("ready", False))]

    def active_persona(self) -> PersonaConfig | None:
        self._ensure_session_persona()
        active_id = str(self.session.active_persona_id or "").strip()
        for persona in self.personas:
            if persona.id == active_id:
                return persona
        return self.personas[0] if self.personas else None

    def selected_narrator_persona_id(self) -> str:
        mode = self._narrator_selection_mode()
        wanted = self._stored_narrator_persona_id()
        if mode == "explicit" and wanted and any(persona.id == wanted for persona in self.personas):
            return wanted
        auto = self._auto_ar_narrator_persona()
        return auto.id if auto is not None else ""

    def selected_narrator_persona(self) -> PersonaConfig | None:
        wanted = self.selected_narrator_persona_id()
        return self.persona_by_id(wanted) if wanted else None

    def _stored_narrator_persona_id(self) -> str:
        wanted = normalize_persona_id(self.settings.get("narrator_persona_id", ""))
        return wanted if any(persona.id == wanted for persona in self.personas) else ""

    def _narrator_selection_mode(self) -> str:
        mode = str(self.settings.get("narrator_persona_mode", "") or "").strip().lower()
        if mode in {"auto", "explicit"}:
            return mode
        wanted = self._stored_narrator_persona_id()
        if not wanted:
            return "auto"
        selected = next((persona for persona in self.personas if persona.id == wanted), None)
        if selected is None:
            return "auto"
        if self.session.mode == AR_MODE and self._looks_like_legacy_current_speaker_narrator_setting(selected):
            return "auto"
        return "explicit"

    def _looks_like_legacy_current_speaker_narrator_setting(self, persona: PersonaConfig | None) -> bool:
        if persona is None or self._persona_looks_like_narrator(persona):
            return False
        stale_ids = {
            str(self.session.active_persona_id or "").strip(),
            str(self.session.current_speaker_id or "").strip(),
        }
        if persona.id not in stale_ids:
            return False
        auto = self._auto_ar_narrator_persona()
        return auto is not None and auto.id != persona.id

    def _auto_ar_narrator_persona(self) -> PersonaConfig | None:
        active_ids = [normalize_persona_id(item) for item in list(self.session.ar_state.active_characters or []) if str(item or "").strip()]
        active_order = {persona_id: index for index, persona_id in enumerate(active_ids)}
        ranked: list[tuple[int, int, PersonaConfig]] = []
        for index, persona in enumerate(self.personas):
            if not bool(getattr(persona, "enabled", True)):
                continue
            score = self._persona_narrator_score(persona)
            if score <= 0:
                continue
            if persona.id in active_order:
                score += 30
                order = active_order[persona.id]
            else:
                order = 1000 + index
            voice = getattr(persona, "voice", None)
            if bool(getattr(voice, "enabled", False)) and str(getattr(voice, "sample_path", "") or "").strip():
                score += 5
            ranked.append((score, -order, persona))
        if not ranked:
            return None
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return ranked[0][2]

    def _ordered_narrator_selector_personas(self) -> list[PersonaConfig]:
        scored: list[tuple[int, int, PersonaConfig]] = []
        rest: list[tuple[int, PersonaConfig]] = []
        for index, persona in enumerate(self.personas):
            score = self._persona_narrator_score(persona)
            if score > 0:
                scored.append((score, -index, persona))
            else:
                rest.append((index, persona))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in scored] + [item[1] for item in rest]

    def _ordered_voice_selector_personas(self) -> list[PersonaConfig]:
        master = [(self._master_narrator_number(persona), index, persona) for index, persona in enumerate(self.personas) if self._persona_is_master_narrator(persona)]
        rest = [(index, persona) for index, persona in enumerate(self.personas) if not self._persona_is_master_narrator(persona)]
        master.sort(key=lambda item: (item[0], item[1]))
        return [item[2] for item in master] + [item[1] for item in rest]

    def _master_narrator_personas(self) -> list[PersonaConfig]:
        return [persona for persona in self.personas if self._persona_is_master_narrator(persona)]

    def _master_narrator_number(self, persona: PersonaConfig | None) -> int:
        if persona is None or not self._persona_is_master_narrator(persona):
            return 0
        for index, item in enumerate(self._master_narrator_personas(), start=1):
            if item.id == persona.id:
                return index
        return 0

    @staticmethod
    def _persona_is_master_narrator(persona: PersonaConfig | None) -> bool:
        return bool(getattr(persona, "master_narrator", False))

    @classmethod
    def _persona_narrator_score(cls, persona: PersonaConfig | None) -> int:
        if persona is None:
            return 0
        display = str(persona.display_name or "").strip().lower()
        role = str(persona.role or "").strip().lower()
        behavior = str(persona.behavior_mode or "").strip().lower()
        tags = {str(tag or "").strip().lower() for tag in list(persona.tags or []) if str(tag or "").strip()}
        text = " ".join(
            [
                str(persona.id or ""),
                display,
                role,
                behavior,
                " ".join(tags),
            ]
        ).lower()
        if cls._persona_is_master_narrator(persona):
            return 140
        if display == "story narrator":
            return 100
        if behavior == "narrator":
            return 90
        if "narrator" in tags:
            return 85
        if "narrator" in role:
            return 82
        if any(token in text for token in ("narration", "immersive-narration", "storyteller", "story teller")):
            return 75
        if "narrator" in text:
            return 70
        return 0

    @staticmethod
    def _persona_looks_like_narrator(persona: PersonaConfig | None) -> bool:
        return MultiPersonaRoleplayController._persona_narrator_score(persona) > 0

    def persona_by_id(self, persona_id: str) -> PersonaConfig | None:
        self._ensure_session_persona()
        target = str(persona_id or "").strip()
        if not target:
            return None
        for persona in self.personas:
            if persona.id == target:
                return persona
        return None

    def current_speaker_persona(self) -> PersonaConfig | None:
        return self.persona_by_id(self.session.current_speaker_id) or self.active_persona()

    def prompt_persona(self) -> PersonaConfig | None:
        if self.session.mode != "Single active persona":
            return self.current_speaker_persona()
        return self.active_persona()

    def ensure_ar_state(self, latest_user_text: str = ""):
        state = self.session.ar_state
        changed = False
        if state.current_scene == "" and self.session.scene_title:
            state.current_scene = self.session.scene_title
            changed = True
        if state.location == "" and self.session.location:
            state.location = self.session.location
            changed = True
        if state.story_goal == "" and self.session.objective:
            state.story_goal = self.session.objective
            changed = True
        if state.mood == "" and self.session.mood:
            state.mood = self.session.mood
            changed = True
        if state.time_of_day == "" and self.session.time_of_day:
            state.time_of_day = self.session.time_of_day
            changed = True
        known = {persona.id for persona in self.personas}
        active = [item for item in list(state.active_characters or []) if item in known]
        if not active:
            narrator = self._ar_narrator_persona()
            seed = []
            if narrator is not None:
                seed.append(narrator.id)
            if self.session.current_speaker_id in known and self.session.current_speaker_id not in seed:
                seed.append(self.session.current_speaker_id)
            for persona in self.personas:
                if persona.enabled and persona.id not in seed:
                    seed.append(persona.id)
                if len(seed) >= 4:
                    break
            state.active_characters = seed
            changed = True
        cleaned_intent = str(latest_user_text or "").strip()
        if cleaned_intent:
            state.player_intent = cleaned_intent[:220]
            changed = True
        if changed:
            logger = getattr(self.context, "logger", None)
            if logger is not None and self.session.mode == AR_MODE:
                logger.info("[AR_MODE] AR state prepared: scene=%s location=%s", state.current_scene, state.location)

    def record_ar_reply(self, assistant_text: str):
        state = self.session.ar_state
        event = str(assistant_text or "").strip()
        if not event:
            return
        self._remote_latest_reply_text = event
        previous_choices = list(state.pending_choices or [])
        changed = self._update_ar_state_from_reply(event)
        changed = self._apply_ar_progression_fallback(event) or changed
        extracted_choices = self._extract_ar_choices(event)
        if extracted_choices and list(state.pending_choices or []) == previous_choices:
            state.pending_choices = extracted_choices
            changed = True
        if not changed:
            compact = event.replace("\r", " ").replace("\n", " ")
            while "  " in compact:
                compact = compact.replace("  ", " ")
            state.recent_events.append(compact[:260])
            state.recent_events = state.recent_events[-12:]
            state.pending_choices = extracted_choices
        if changed:
            self._request_ui_refresh()
        logger = getattr(self.context, "logger", None)
        if logger is not None:
            logger.info("[AR_MODE] Recorded AR reply event; choices=%s", len(state.pending_choices))

    def _update_ar_state_from_reply(self, assistant_text: str) -> bool:
        if self.is_shutdown() or not str(assistant_text or "").strip():
            return False
        try:
            from core.engine_access import engine_module

            engine = engine_module()
            model_name = str(getattr(engine, "RUNTIME_CONFIG", {}).get("model_name", "") or "").strip()
            if not model_name:
                return False
            if hasattr(engine, "_is_model_catalog_placeholder") and engine._is_model_catalog_placeholder(model_name):
                return False
            prompt = prompting.build_scene_update_prompt(self.session, self._mprc_strip_audio_tags(assistant_text))
            params = {
                "model": model_name,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are NeuralCompanion's hidden MPRC AR state updater. "
                            "Return strict JSON only, no markdown and no prose. "
                            "Track visible story progression for the next turn and Visual Reply prompts."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 800,
                "response_format": {"type": "json_object"},
                "timeout": 45,
            }
            additional_params: dict[str, Any] = {}
            if hasattr(engine, "_apply_chat_provider_generation_fields"):
                engine._apply_chat_provider_generation_fields(params, additional_params)
            params["temperature"] = 0.1
            params["max_tokens"] = 800
            params["response_format"] = {"type": "json_object"}
            params["timeout"] = max(45, int(float(params.get("timeout", 0) or 0)))
            raw_text = ""
            last_error = None
            for _attempt in range(2):
                try:
                    raw_text = str(engine._chat_completion_create(params, additional_params) or "").strip()
                    break
                except Exception as exc:
                    last_error = exc
                    message = str(exc).lower()
                    changed = False
                    if "response_format" in message or "json_object" in message:
                        changed = "response_format" in params
                        params.pop("response_format", None)
                    if ("timeout" in message or "unsupported" in message) and "timeout" in params:
                        params.pop("timeout", None)
                        changed = True
                    if not changed:
                        raise
            if not raw_text and last_error is not None:
                raise last_error
            payload = prompting.parse_json_object(raw_text) or {}
            return self._apply_ar_scene_update_payload(payload)
        except Exception as exc:
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.info("[MPRC] Hidden AR state update skipped: %s", exc)
            return False

    def _apply_ar_scene_update_payload(self, payload: dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False
        state = self.session.ar_state
        changed = False

        def assign_text(target: Any, attr: str, value: Any, limit: int) -> bool:
            text = prompting._compact(str(value or "").strip(), limit)
            if not text or text == str(getattr(target, attr, "") or ""):
                return False
            setattr(target, attr, text)
            return True

        changed = assign_text(self.session, "scene_summary", payload.get("scene_summary"), 1400) or changed
        changed = assign_text(state, "current_scene", payload.get("current_scene"), 360) or changed
        changed = assign_text(state, "location", payload.get("location"), 180) or changed
        changed = assign_text(state, "time_of_day", payload.get("time_of_day"), 120) or changed
        changed = assign_text(state, "mood", payload.get("mood"), 180) or changed
        changed = assign_text(state, "story_goal", payload.get("story_goal") or payload.get("current_objective"), 300) or changed

        try:
            tension = int(payload.get("tension_level"))
            tension = max(0, min(10, tension))
            if tension != int(getattr(state, "tension_level", 0) or 0):
                state.tension_level = tension
                changed = True
        except Exception:
            pass

        recent_event = prompting._compact(str(payload.get("recent_event") or "").strip(), 260)
        if recent_event:
            events = [str(item or "").strip() for item in list(state.recent_events or []) if str(item or "").strip()]
            if not events or events[-1] != recent_event:
                events.append(recent_event)
                state.recent_events = events[-12:]
                changed = True

        raw_choices = payload.get("pending_choices")
        if isinstance(raw_choices, list):
            choices = [prompting._compact(str(item or "").strip(), 180) for item in raw_choices if str(item or "").strip()]
            choices = choices[:6]
            if choices != list(state.pending_choices or []):
                state.pending_choices = choices
                changed = True

        summaries = payload.get("character_state_summaries")
        if isinstance(summaries, dict):
            known_ids = {persona.id for persona in self.personas}
            current = dict(self.session.character_state_summaries or {})
            for persona_id, summary in summaries.items():
                normalized = normalize_persona_id(str(persona_id or ""))
                if normalized not in known_ids:
                    continue
                text = prompting._compact(str(summary or "").strip(), 360)
                if text and current.get(normalized) != text:
                    current[normalized] = text
                    changed = True
            if changed:
                self.session.character_state_summaries = current
        return changed

    def _apply_ar_progression_fallback(self, assistant_text: str) -> bool:
        visible = self._mprc_latest_visible_story_beat(assistant_text)
        if not visible:
            return False
        state = self.session.ar_state
        changed = False
        compact_scene = prompting._compact(visible, 360)
        current_scene = str(getattr(state, "current_scene", "") or "").strip()
        if compact_scene and compact_scene.lower() != current_scene.lower():
            state.current_scene = compact_scene
            changed = True
        visible_reply = self._strip_mprc_choices_block(self._mprc_strip_audio_tags(str(assistant_text or "")))
        inferred_location = self._infer_mprc_progression_location(
            "\n".join(
                part
                for part in (
                    str(getattr(state, "player_intent", "") or ""),
                    visible_reply,
                    visible,
                )
                if part.strip()
            )
        )
        current_location = str(getattr(state, "location", "") or "").strip()
        if inferred_location and inferred_location.lower() != current_location.lower():
            state.location = inferred_location
            changed = True
        recent_event = prompting._compact(visible, 260)
        if recent_event:
            events = [str(item or "").strip() for item in list(state.recent_events or []) if str(item or "").strip()]
            if not events or events[-1] != recent_event:
                events.append(recent_event)
                state.recent_events = events[-12:]
                changed = True
        return changed

    @staticmethod
    def _mprc_latest_visible_story_beat(text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        raw = re.sub(
            r"\[(?:AMBIENCE|AMBIENT|MUSIC|FX|SFX|STINGER|AUDIO):[^\]]+\]",
            " ",
            raw,
            flags=re.IGNORECASE,
        )
        raw = re.sub(r"(?is)\[CHOICES\].*$", " ", raw)
        raw = re.sub(r"\[(?:/?NARRATOR|CHARACTER:\s*[^\]]+)\]", "\n", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\b(?:Story|Assistant)\s*:\s*", " ", raw, flags=re.IGNORECASE)
        paragraphs = [
            re.sub(r"\s+", " ", part).strip(" -")
            for part in re.split(r"\n{2,}|\r?\n", raw)
        ]
        blocked_starts = ("what do you do", "what's your next move", "whats your next move")
        for paragraph in reversed(paragraphs):
            lowered = paragraph.lower()
            if len(paragraph) < 24 or lowered.startswith(blocked_starts):
                continue
            return prompting._compact(paragraph, 700)
        compact = re.sub(r"\s+", " ", raw).strip()
        return prompting._compact(compact, 700)

    def _infer_mprc_progression_location(self, text: str) -> str:
        value = re.sub(r"\s+", " ", str(text or "").strip().lower())
        if not value:
            return ""
        if re.search(r"\b(forest|woods|woodland|wilds|wilderness|grove|tree line|treeline)\b", value):
            return "Wilds outside the tavern" if re.search(r"\b(tavern|inn)\b", value) else "Forest"
        if re.search(r"\b(street|road|lane|alley|market|square|courtyard|stable yard)\b", value):
            return "Street outside the tavern" if re.search(r"\b(tavern|inn)\b", value) else "Street"
        if re.search(r"\b(outside|outdoors|open air|threshold|through the door|out the door|leaves? the tavern|leaves? the inn|leaving the tavern|leaving the inn|steps? out|walks? out|push(?:es)? .*door open)\b", value):
            return "Outside the tavern" if re.search(r"\b(tavern|inn)\b", value) else "Outside"
        for pattern in (
            r"\b(?:enter|enters|entered|step into|steps into|walk into|walks into|move into|moves into)\s+the\s+([a-z][a-z0-9 '\-]{2,42})",
            r"\b(?:arrive at|arrives at|reach|reaches|reached)\s+the\s+([a-z][a-z0-9 '\-]{2,42})",
        ):
            match = re.search(pattern, value)
            if match:
                location = re.split(r"\b(?:and|as|while|where|before|with)\b|[,.]", match.group(1))[0].strip(" ',-")
                words = [word for word in location.split() if word]
                if 1 <= len(words) <= 6:
                    return " ".join(word.capitalize() for word in words)
        return ""

    def ensure_personas_from_assistant_text(self, assistant_text: str, *, source: str = "assistant_reply") -> list[str]:
        text = str(assistant_text or "")
        if not text.strip():
            return []
        created_ids: list[str] = []
        for name, context_text in self._character_contexts_from_text(text):
            before_auto = self._chat_auto_created_persona_ids()
            persona = self.ensure_persona_for_character_label(name, context_text=context_text, source=source, save=False)
            after_auto = self._chat_auto_created_persona_ids()
            if persona is not None and persona.id not in before_auto and persona.id in after_auto and persona.id not in created_ids:
                created_ids.append(persona.id)
        if created_ids:
            self._mark_auto_personas(created_ids)
            self.save_state()
            self._request_ui_refresh()
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.info("[MPRC] Auto-created persona(s) from chat: %s", ", ".join(created_ids))
        return created_ids

    def ensure_persona_for_character_label(self, name: str, *, context_text: str = "", source: str = "chat", save: bool = True) -> PersonaConfig | None:
        display_name = self._clean_character_name(name)
        if not display_name:
            return None
        existing = self._find_persona_by_name_or_id(display_name)
        if existing is not None:
            self._add_persona_to_active_character_state(existing.id)
            if save:
                self.save_state()
            return existing
        if not self._character_label_looks_auto_creatable(display_name):
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.info("[MPRC] Ignored non-name character label from %s: %s", source, display_name)
            return None
        persona = self._build_auto_chat_persona(display_name, context_text=context_text, source=source)
        self.personas.append(persona)
        self._mark_auto_personas([persona.id])
        self._add_persona_to_active_character_state(persona.id)
        if not self.session.active_persona_id:
            self.session.active_persona_id = persona.id
        if not self.session.current_speaker_id:
            self.session.current_speaker_id = persona.id
        if save:
            self.save_state()
            self._request_ui_refresh()
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.info("[MPRC] Auto-created persona from %s: %s (%s)", source, persona.display_name, persona.id)
        return persona

    def _character_contexts_from_text(self, text: str) -> list[tuple[str, str]]:
        value = str(text or "")
        pattern = re.compile(r"\[CHARACTER\s*:\s*([^\]]{1,120})\]\s*", re.IGNORECASE)
        matches = list(pattern.finditer(value))
        contexts: list[tuple[str, str]] = []
        seen: set[str] = set()
        section_pattern = re.compile(
            r"\n\s*\[(?:CHARACTER\s*:\s*[^\]]+|NARRATOR|CHOICES|AMBIENCE\s*:?[^\]]*|AMBIENT\s*:?[^\]]*|MUSIC\s*:?[^\]]*|FX\s*:?[^\]]*|SFX\s*:?[^\]]*|STINGER\s*:?[^\]]*|AUDIO\s*:?[^\]]*|SOUND\s*:?[^\]]*)\]",
            re.IGNORECASE,
        )
        for index, match in enumerate(matches):
            name = self._clean_character_name(match.group(1))
            if not name:
                continue
            key = normalize_persona_id(name)
            if key in seen:
                continue
            seen.add(key)
            next_start = matches[index + 1].start() if index + 1 < len(matches) else len(value)
            section_match = section_pattern.search(value, match.end())
            if section_match is not None:
                next_start = min(next_start, section_match.start())
            before = value[max(0, match.start() - 420) : match.start()]
            after = value[match.end() : min(len(value), next_start, match.end() + 700)]
            context = self._compact_character_context(before, after)
            contexts.append((name, context))
        return contexts

    def _compact_character_context(self, before: str, after: str) -> str:
        pieces = []
        before_text = self._strip_story_control_tags(before)
        if before_text:
            sentences = re.split(r"(?<=[.!?])\s+", before_text)
            pieces.append(" ".join(sentence for sentence in sentences[-2:] if sentence).strip())
        after_text = self._strip_story_control_tags(after)
        if after_text:
            pieces.append(after_text)
        compact = " ".join(piece for piece in pieces if piece)
        compact = re.sub(r"\s+", " ", compact).strip()
        return compact[:700]

    @staticmethod
    def _strip_story_control_tags(text: str) -> str:
        value = str(text or "")
        value = re.sub(r"\[(?:NARRATOR|CHOICES|AMBIENCE\s*:?[^\]]*|AMBIENT\s*:?[^\]]*|MUSIC\s*:?[^\]]*|FX\s*:?[^\]]*|SFX\s*:?[^\]]*|STINGER\s*:?[^\]]*|AUDIO\s*:?[^\]]*|SOUND\s*:?[^\]]*)\]", " ", value, flags=re.IGNORECASE)
        value = re.sub(r"\[(?:neutral|laugh|chuckle|sigh|groan|gasp|clear throat|sniff)\]", " ", value, flags=re.IGNORECASE)
        return value.strip()

    def _clean_character_name(self, name: Any) -> str:
        value = str(name or "").strip()
        value = re.sub(r"\s+", " ", value).strip(" \t\r\n:;,.")
        if not value or len(value) > 80:
            return ""
        lowered = value.lower()
        blocked = {
            "narrator",
            "choices",
            "choice",
            "ambience",
            "ambient",
            "music",
            "fx",
            "sfx",
            "stinger",
            "audio",
            "sound",
            "you",
            "assistant",
            "user",
        }
        if lowered in blocked:
            return ""
        if not re.search(r"[A-Za-z]", value):
            return ""
        return value

    @staticmethod
    def _character_label_looks_auto_creatable(name: str) -> bool:
        value = str(name or "").strip()
        if not value:
            return False
        if re.search(r"[.!?\"“”]", value):
            return False
        words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'_-]*", value)
        if not words or len(words) > 5:
            return False
        lowered_words = {word.lower().strip("_-") for word in words}
        phrase_markers = {
            "and",
            "or",
            "but",
            "you",
            "your",
            "yours",
            "me",
            "my",
            "mine",
            "we",
            "our",
            "ours",
            "they",
            "their",
            "it",
            "its",
            "will",
            "would",
            "should",
            "could",
            "can",
            "can't",
            "cannot",
            "have",
            "has",
            "had",
            "are",
            "is",
            "was",
            "were",
            "look",
            "tell",
            "whisper",
            "again",
        }
        if lowered_words & phrase_markers:
            return False
        first_alpha = re.search(r"[A-Za-z]", value)
        if first_alpha is not None and not first_alpha.group(0).isupper():
            return False
        return True

    @staticmethod
    def _persona_name_aliases(persona: PersonaConfig) -> set[str]:
        aliases: set[str] = set()

        def add(value: Any) -> None:
            text = str(value or "").strip()
            if not text:
                return
            aliases.add(text.lower())
            aliases.add(normalize_persona_id(text))

        add(getattr(persona, "id", ""))
        display_name = str(getattr(persona, "display_name", "") or "").strip()
        add(display_name)
        without_parenthetical = re.sub(r"\s*\([^)]*\)\s*", " ", display_name).strip()
        add(without_parenthetical)
        for alias in re.findall(r"\(([^)]{1,80})\)", display_name):
            add(alias)
        return {alias for alias in aliases if alias}

    def _find_persona_by_name_or_id(self, name: str) -> PersonaConfig | None:
        wanted_id = normalize_persona_id(name)
        wanted_name = str(name or "").strip().lower()
        wanted_aliases = {wanted_id, wanted_name}
        for persona in self.personas:
            if persona.id == wanted_id or wanted_id in self._persona_name_aliases(persona):
                return persona
        for persona in self.personas:
            if wanted_aliases & self._persona_name_aliases(persona):
                return persona
        return None

    def _build_auto_chat_persona(self, display_name: str, *, context_text: str = "", source: str = "chat") -> PersonaConfig:
        existing_ids = {p.id for p in self.personas}
        persona_id = unique_persona_id(display_name, existing_ids)
        context = self._compact_auto_persona_description(display_name, context_text)
        role = self._infer_auto_persona_role(display_name, context)
        tags = self._infer_auto_persona_tags(context)
        description = context or f"Auto-created story character introduced in the active chat as {display_name}."
        ar_description = description
        system_prompt = (
            f"You are {display_name}. Stay consistent with the established story description and speak only as this character. "
            "Keep replies grounded in the current scene, preserve user agency, and avoid taking over the user's actions."
        )
        ar_system_prompt = (
            f"In AlternativeReality mode, portray {display_name} as a cinematic story character. "
            "Use the established scene description, speak in a distinct voice when tagged, and let the narrator handle action narration unless this character is directly speaking."
        )
        persona = PersonaConfig(
            id=persona_id,
            enabled=True,
            display_name=display_name,
            role=role,
            description=description,
            system_prompt=system_prompt,
            ar_profile_enabled=True,
            ar_description=ar_description,
            ar_system_prompt=ar_system_prompt,
            speaking_style=self._infer_auto_speaking_style(context),
            allowed_tone="consistent with the active story, consensual, non-explicit, and user-agency friendly",
            response_length="balanced",
            memory_scope="persona-only",
            behavior_mode="group participant",
            tags=tags,
        )
        persona.visual.enabled = True
        persona.visual.mode = "manual"
        persona.visual.provider = "inherit"
        persona.visual.size = "inherit"
        persona.visual.character_description = self._auto_visual_description(display_name, context)
        persona.visual.clothing_props = self._auto_visual_clothing(context)
        persona.visual.environment_style = self.session.location or self.session.ar_state.location or self.session.scene_title
        persona.visual.negative_prompt = "text, watermark, logo, distorted face, extra limbs"
        return persona

    def _compact_auto_persona_description(self, display_name: str, context_text: str) -> str:
        context = re.sub(r"\s+", " ", str(context_text or "")).strip()
        if not context:
            return ""
        context = re.sub(rf"^\s*{re.escape(display_name)}\s*[:\-]\s*", "", context, flags=re.IGNORECASE)
        return f"Auto-created from active chat: {context[:460].strip()}"

    def _infer_auto_persona_role(self, display_name: str, context: str) -> str:
        lowered = str(context or "").lower()
        role_markers = (
            ("captain", "captain"),
            ("detective", "detective"),
            ("merchant", "merchant"),
            ("vendor", "vendor"),
            ("guard", "guard"),
            ("queen", "queen"),
            ("king", "king"),
            ("mage", "mage"),
            ("wizard", "wizard"),
            ("orc", "orc character"),
            ("goblin", "goblin character"),
            ("demon", "demon character"),
            ("robot", "robot character"),
            ("android", "android character"),
            ("guide", "guide"),
            ("ally", "ally"),
            ("enemy", "rival"),
            ("villain", "antagonist"),
        )
        for marker, role in role_markers:
            if marker in lowered or marker in display_name.lower():
                return role
        return "story character"

    def _infer_auto_persona_tags(self, context: str) -> list[str]:
        lowered = str(context or "").lower()
        tags = ["auto", "story", "chat-created"]
        for marker, tag in (
            ("fantasy", "fantasy"),
            ("magic", "fantasy"),
            ("orc", "fantasy"),
            ("goblin", "fantasy"),
            ("cyber", "sci-fi"),
            ("neon", "sci-fi"),
            ("submarine", "adventure"),
            ("captain", "adventure"),
            ("mystery", "mystery"),
            ("detective", "mystery"),
            ("horror", "horror"),
        ):
            if marker in lowered and tag not in tags:
                tags.append(tag)
        return tags[:10]

    def _infer_auto_speaking_style(self, context: str) -> str:
        lowered = str(context or "").lower()
        if "gruff" in lowered:
            return "gruff, direct, and grounded"
        if "snark" in lowered or "sarcastic" in lowered:
            return "snarky, quick, and expressive"
        if "whisper" in lowered or "quiet" in lowered:
            return "quiet, careful, and atmospheric"
        if "captain" in lowered or "command" in lowered:
            return "controlled, authoritative, and deliberate"
        return "distinct, consistent, and scene-aware"

    def _auto_visual_description(self, display_name: str, context: str) -> str:
        pieces = [
            f"{display_name}, story character portrait",
            context,
            "clear face, readable silhouette, expressive eyes",
        ]
        return ". ".join(str(piece or "").strip(" .") for piece in pieces if str(piece or "").strip())[:900]

    def _auto_visual_clothing(self, context: str) -> str:
        lowered = str(context or "").lower()
        if any(word in lowered for word in ("fantasy", "orc", "goblin", "mage", "wizard", "castle")):
            return "fantasy costume and props inferred from the story description"
        if any(word in lowered for word in ("cyber", "neon", "hologram", "android")):
            return "futuristic clothing, cyberpunk details, and story-appropriate gear"
        if any(word in lowered for word in ("captain", "submarine", "sea", "nautilus")):
            return "nautical adventure clothing and story-appropriate equipment"
        return "story-appropriate outfit and props"

    def _chat_auto_created_persona_ids(self) -> set[str]:
        raw = self.settings.get("chat_auto_created_persona_ids")
        if not isinstance(raw, list):
            return set()
        return {normalize_persona_id(item) for item in raw if str(item or "").strip()}

    def _mark_auto_personas(self, persona_ids: list[str]) -> None:
        current = self._chat_auto_created_persona_ids()
        for persona_id in list(persona_ids or []):
            normalized = normalize_persona_id(persona_id)
            if normalized:
                current.add(normalized)
        self.settings["chat_auto_created_persona_ids"] = sorted(current)
        self.storage.save_settings(self.settings)

    def _remove_chat_auto_personas(self) -> int:
        auto_ids = self._chat_auto_created_persona_ids()
        if not auto_ids:
            return 0
        existing_ids = {persona.id for persona in self.personas}
        removed_ids = {persona_id for persona_id in auto_ids if persona_id in existing_ids}
        if removed_ids:
            self.personas = [persona for persona in self.personas if persona.id not in removed_ids]
            self.session.character_state_summaries = {
                str(persona_id): summary
                for persona_id, summary in dict(self.session.character_state_summaries or {}).items()
                if normalize_persona_id(persona_id) not in removed_ids
            }
            state = self.session.ar_state
            state.active_characters = [
                normalize_persona_id(persona_id)
                for persona_id in list(state.active_characters or [])
                if normalize_persona_id(persona_id) not in removed_ids
            ]
            if self.session.active_persona_id in removed_ids:
                self.session.active_persona_id = ""
            if self.session.current_speaker_id in removed_ids:
                self.session.current_speaker_id = ""
            self._ensure_session_persona()
        for key in (
            "chat_auto_created_persona_ids",
            "master_story_created_persona_ids",
            "master_story_linked_persona_ids",
        ):
            raw = self.settings.get(key)
            if isinstance(raw, list):
                self.settings[key] = [
                    normalize_persona_id(item)
                    for item in raw
                    if normalize_persona_id(item) and normalize_persona_id(item) not in auto_ids
                ]
        for key in ("narrator_persona_id", "selected_narrator_id"):
            if normalize_persona_id(self.settings.get(key)) in removed_ids:
                self.settings[key] = ""
        self.storage.save_settings(self.settings)
        return len(removed_ids)

    def _link_persona_to_current_story(self, persona_id: str) -> None:
        normalized = normalize_persona_id(persona_id)
        if not normalized:
            return
        linked = self._master_story_linked_persona_ids()
        linked.add(normalized)
        self.settings["master_story_linked_persona_ids"] = sorted(linked)
        created = self._master_story_created_persona_ids()
        if normalized in self._chat_auto_created_persona_ids():
            created.add(normalized)
            self.settings["master_story_created_persona_ids"] = sorted(created)
        self.storage.save_settings(self.settings)

    def _add_persona_to_active_character_state(self, persona_id: str) -> None:
        normalized = normalize_persona_id(persona_id)
        if not normalized:
            return
        if normalized not in self.session.character_state_summaries:
            persona = self.persona_by_id(normalized)
            if persona is not None:
                self.session.character_state_summaries[normalized] = ". ".join(
                    part for part in (persona.role, persona.description or persona.ar_description) if part
                )[:300]
        state = self.session.ar_state
        active = [item for item in list(state.active_characters or []) if item]
        if normalized not in active:
            active.append(normalized)
            state.active_characters = active[-8:]

    def _request_ui_refresh(self) -> None:
        if self.is_shutdown():
            return
        bridge = getattr(self, "_ui_bridge", None)
        if bridge is not None:
            try:
                bridge.refresh_requested.emit()
            except RuntimeError:
                pass

    def request_auto_visual_reply(self, persona_id: str, reason: str, source_text: str = "") -> None:
        if self.is_shutdown():
            return
        persona = self.persona_by_id(str(persona_id or "").strip())
        self._record_visual_debug(
            source="auto_visual_trigger",
            reason=str(reason or "manual"),
            persona=persona,
            accepted=None,
            message="Auto Visual Reply request queued for a background worker.",
        )
        if not self._queue_visual_worker(
            "mprc_visual_reply",
            lambda: self._run_auto_visual_reply_request(
                str(persona_id or ""),
                str(reason or "manual"),
                str(source_text or ""),
            ),
        ):
            self._record_visual_debug(
                source="auto_visual_trigger",
                reason=str(reason or "manual"),
                persona=persona,
                accepted=False,
                message="Auto Visual Reply request could not start a background worker.",
            )

    def _queue_visual_worker(self, prefix: str, target) -> bool:
        token = self._new_worker_token(str(prefix or "mprc_visual"))
        if not token:
            return False

        def worker():
            try:
                target()
            except Exception as exc:
                logger = getattr(self.context, "logger", None)
                if logger is not None:
                    logger.warning("[MPRC] Background visual worker failed: %s", exc)
            finally:
                self._finish_worker_token(token)

        if self._start_daemon_worker(token, worker, name=str(prefix or "mprc-visual-worker")):
            return True
        self._cancel_worker_token(token)
        return False

    def _emit_manual_visual_finished(self, kind: str, persona_id: str, result: Any) -> None:
        bridge = getattr(self, "_ui_bridge", None)
        if bridge is None:
            return
        try:
            bridge.manual_visual_finished.emit(str(kind or ""), str(persona_id or ""), result)
        except RuntimeError:
            pass

    def _on_manual_visual_finished(self, kind: str, persona_id: str, result: Any) -> None:
        result_dict = dict(result or {}) if isinstance(result, dict) else {"message": str(result or "")}
        key = str(persona_id or "").strip()
        if kind == "character_picture":
            with self._state_lock:
                self._manual_character_image_inflight.discard(key)
            if not bool(result_dict.get("ok")):
                self._warn("Create Character Picture", result_dict.get("message") or "Character picture generation was not accepted.")
            return
        if kind in {"manual_visual_reply", "status_visual_reply"}:
            self._debug_visual_prompt = json.dumps(result_dict, indent=2, ensure_ascii=True)
            self._refresh_debug()
        if kind == "status_visual_reply":
            persona = self.persona_by_id(key)
            persona_name = str(getattr(persona, "display_name", "") or key or "selected persona")
            accepted = bool(result_dict.get("accepted"))
            message = str(result_dict.get("message") or "submitted")
            self._record_story_event(
                f"visual test {'accepted' if accepted else 'skipped'} for {persona_name}: {message}",
                severity="info" if accepted else "warning",
                kind="visual",
                persist=True,
            )
            self._set_master_story_status(f"Visual Reply test for {persona_name}: {message}.")
        if kind == "story_avatar_batch":
            message = str(result_dict.get("message") or "").strip() or "Story avatar generation finished."
            accepted = bool(result_dict.get("accepted", True))
            lowered = message.lower()
            severity = "warning" if not accepted or any(word in lowered for word in ("failed", "skipped", "unavailable")) else "info"
            self._record_story_event(
                f"avatar generation batch: {message}",
                severity=severity,
                kind="visual",
                persist=True,
            )
            self._set_master_story_status(f"Story avatar generation finished: {message}")
            self._request_ui_refresh()

    def _run_manual_visual_reply_request(self, persona_id: str, *, kind: str) -> None:
        result: dict[str, Any]
        try:
            persona = self.persona_by_id(str(persona_id or "").strip()) if str(persona_id or "").strip() else None
            result = self.visual_reply.request_generation(persona=persona, reason="manual")
        except Exception as exc:
            result = {"accepted": False, "message": f"Visual Reply request failed: {exc}"}
        self._emit_manual_visual_finished(kind, str(persona_id or ""), result)

    def _run_auto_visual_reply_request(self, persona_id: str, reason: str, source_text: str = "") -> None:
        if self.is_shutdown():
            return
        persona = self.persona_by_id(persona_id)
        if persona is None:
            self._record_visual_debug(
                source="auto_visual_request",
                reason=str(reason or "manual"),
                accepted=False,
                message=f"No persona matched Visual Reply request id '{persona_id}'.",
            )
            return
        result = self.visual_reply.request_generation(persona=persona, reason=reason, source_text=source_text)
        logger = getattr(self.context, "logger", None)
        if logger is not None and not bool(result.get("accepted")):
            logger.info("MPRC auto Visual Reply skipped: %s", result.get("message", "not accepted"))
        if not bool(result.get("accepted")):
            self._record_story_event(
                f"image skipped: {result.get('message', 'not accepted')}",
                severity="info",
                kind="visual",
                persist=True,
            )

    def build_visual_action_prompt(
        self,
        *,
        persona: PersonaConfig,
        source_text: str,
        base_prompt: str,
        reason: str = "manual",
        provider: str = "",
    ) -> str:
        reply_text = self._mprc_strip_audio_tags(str(source_text or "").strip())
        if not reply_text or persona is None or self.is_shutdown():
            return ""
        provider_id = prompting.normalize_visual_provider_id(provider or "inherit") or "inherit"
        prompt_style = prompting.visual_prompt_style(provider_id)
        try:
            from core.engine_access import engine_module

            engine = engine_module()
            model_name = str(getattr(engine, "RUNTIME_CONFIG", {}).get("model_name", "") or "").strip()
            if not model_name:
                return ""
            if hasattr(engine, "_is_model_catalog_placeholder") and engine._is_model_catalog_placeholder(model_name):
                return ""
            state = self.session.ar_state
            active_ids = [normalize_persona_id(item) for item in list(state.active_characters or []) if str(item or "").strip()]
            if not active_ids:
                active_ids = [self.session.current_speaker_id, self.session.active_persona_id, persona.id]
            active_cast = []
            seen = set()
            for persona_id in active_ids:
                cast_persona = self.persona_by_id(persona_id)
                if cast_persona is None or cast_persona.id in seen:
                    continue
                seen.add(cast_persona.id)
                active_cast.append(
                    {
                        "id": cast_persona.id,
                        "name": cast_persona.display_name,
                        "role": cast_persona.role or cast_persona.behavior_mode,
                        "appearance": (
                            cast_persona.visual.character_description
                            or cast_persona.ar_description
                            or cast_persona.description
                        ),
                        "clothing_props": cast_persona.visual.clothing_props,
                    }
                )
            visual = persona.visual
            prompt_payload = {
                "task": "Create one image prompt for the current MPRC story reply.",
                "provider": provider_id,
                "prompt_style": prompt_style,
                "trigger_reason": str(reason or "manual"),
                "selected_visual_persona": {
                    "id": persona.id,
                    "name": persona.display_name,
                    "role": persona.role or persona.behavior_mode,
                    "appearance": visual.character_description or persona.ar_description or persona.description,
                    "clothing_props": visual.clothing_props,
                    "environment_style": visual.environment_style,
                    "negative_prompt": visual.negative_prompt,
                    "include_active_speaker_focus": bool(visual.include_active_speaker),
                },
                "scene_state": {
                    "title": self.session.scene_title,
                    "summary": self._mprc_compact(self.session.scene_summary, 600),
                    "current_scene": self._mprc_compact(state.current_scene or self.session.scene_title, 360),
                    "location": state.location or self.session.location,
                    "time_of_day": state.time_of_day or self.session.time_of_day,
                    "mood": state.mood or self.session.mood,
                    "objective": state.story_goal or self.session.objective,
                    "recent_events": [
                        self._mprc_compact(item, 220)
                        for item in list(state.recent_events or self.session.recent_events or [])[-4:]
                        if str(item or "").strip()
                    ],
                    "pending_choices": [
                        self._mprc_compact(item, 160)
                        for item in list(state.pending_choices or [])[:4]
                        if str(item or "").strip()
                    ],
                },
                "active_cast": active_cast[:6],
                "current_story_reply": self._mprc_compact(reply_text, 2400),
                "fallback_prompt": self._mprc_compact(base_prompt, 900),
            }
            system_prompt = (
                "You are NeuralCompanion's hidden MPRC visual-action prompt planner. "
                "Return strict JSON only, no markdown and no prose. "
                "Focus on the visible action happening in current_story_reply. "
                "Use scene_state and active_cast only to keep identity, setting, and continuity grounded. "
                "current_story_reply overrides older scene_state summary, selected_visual_persona environment_style, and stale location memory. "
                "Use selected_visual_persona as character identity inside the current scene, not as a static portrait subject. "
                "If selected_visual_persona.include_active_speaker_focus is false, do not make the active speaker name or face the main composition unless the current story reply visibly requires it. "
                "Do not invent new characters, props, injuries, weapons, monsters, or location changes unless visible in the current story reply. "
                "Do not include hidden reasoning."
            )
            style_rule = {
                "runware": (
                    "- Provider style is Runware: return one compact direct positive prompt, preferably comma-separated visual phrases. "
                    "Keep it under 520 characters and avoid multi-step narrative instructions or hidden metadata."
                ),
                "grok": (
                    "- Provider style is xAI/Grok: return a richer natural-language image prompt with visible action, persona identity, "
                    "appearance, location, mood/lighting, style, and continuity. Avoid JSON in the final image_prompt."
                ),
                "comfyui": (
                    "- Provider style is ComfyUI: use a direct compact positive prompt without labels like 'Story scene image' or 'Current story moment'."
                ),
            }.get(
                prompt_style,
                "- Provider style is general Visual Reply: return a clear story-scene prompt under 900 characters.",
            )
            prompt_limit_label = "520" if prompt_style == "runware" else "1300" if prompt_style == "grok" else "760" if prompt_style == "comfyui" else "900"
            user_prompt = (
                "Return this exact JSON shape:\n"
                '{"image_prompt":"ready image prompt focused on the current visible action","negative_prompt":"optional concise avoid list"}\n\n'
                "Rules:\n"
                "- image_prompt must describe who is visibly doing what, where, with mood/lighting/camera.\n"
                "- Start from current_story_reply/current scene action, then add character appearance as continuity detail.\n"
                "- Prioritize action, body language, object interaction, threat, discovery, movement, or reaction from current_story_reply.\n"
                "- Keep recurring character identity consistent using active_cast and selected_visual_persona, but never replace the scene with a character-card description.\n"
                "- If no concrete action is visible, show the current scene state and atmosphere instead of a portrait.\n"
                f"{style_rule}\n"
                f"- Keep image_prompt under {prompt_limit_label} characters.\n\n"
                "Input JSON:\n"
                f"{json.dumps(prompt_payload, ensure_ascii=False, indent=2)}"
            )
            params = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 700,
                "response_format": {"type": "json_object"},
                "timeout": 45,
            }
            additional_params: dict[str, Any] = {}
            if hasattr(engine, "_apply_chat_provider_generation_fields"):
                engine._apply_chat_provider_generation_fields(params, additional_params)
            params["temperature"] = 0.2
            params["max_tokens"] = 700
            params["response_format"] = {"type": "json_object"}
            params["timeout"] = max(45, int(float(params.get("timeout", 0) or 0)))
            last_error = None
            raw_text = ""
            for _attempt in range(2):
                try:
                    raw_text = str(engine._chat_completion_create(params, additional_params) or "").strip()
                    break
                except Exception as exc:
                    last_error = exc
                    message = str(exc).lower()
                    changed = False
                    if "response_format" in message or "json_object" in message:
                        changed = "response_format" in params
                        params.pop("response_format", None)
                    if ("timeout" in message or "unsupported" in message) and "timeout" in params:
                        params.pop("timeout", None)
                        changed = True
                    if not changed:
                        raise
            if not raw_text and last_error is not None:
                raise last_error
            payload = prompting.parse_json_object(raw_text) or {}
            prompt = str(payload.get("image_prompt") or payload.get("prompt") or "").strip()
            if len(prompt) < 20:
                return ""
            prompt_limit = 520 if prompt_style == "runware" else 1300 if prompt_style == "grok" else 760 if prompt_style == "comfyui" else 900
            prompt = prompting._compact(prompt, prompt_limit)
            self.set_chat_visual_prompt_debug_from_parts(
                persona=persona,
                reason=str(reason or "manual"),
                provider=provider_id,
                stage="hidden LLM current-reply action prompt",
                final_prompt=prompt,
                base_prompt=base_prompt,
                source_text=reply_text,
                request_payload=prompt_payload,
            )
            self._record_visual_debug(
                source="visual_action_prompt",
                reason=str(reason or "manual"),
                persona=persona,
                accepted=None,
                message="Hidden LLM built current-reply visual action prompt.",
                prompt=prompt,
            )
            return prompt
        except Exception as exc:
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.info("[MPRC] Visual action prompt refinement skipped: %s", exc)
            self._record_visual_debug(
                source="visual_action_prompt",
                reason=str(reason or "manual"),
                persona=persona,
                accepted=False,
                message=f"Hidden LLM visual action prompt skipped: {exc}",
                prompt=base_prompt,
            )
            return ""

    def _extract_ar_choices(self, text: str) -> list[str]:
        raw = str(text or "")
        marker = raw.lower().find("[choices]")
        if marker < 0:
            return []
        block = raw[marker + len("[choices]") :]
        next_section = block.find("[")
        if next_section >= 0:
            block = block[:next_section]
        choices = []
        for line in block.splitlines():
            clean = str(line or "").strip()
            clean = re.sub(r"^\s*(?:[-*]\s+|\d+[.)]\s+)", "", clean)
            if clean:
                choices.append(clean[:180])
            if len(choices) >= 6:
                break
        return choices

    def _ar_narrator_persona(self) -> PersonaConfig | None:
        selected = self.selected_narrator_persona()
        if selected is not None:
            return selected
        for persona in self.personas:
            if persona.display_name.strip().lower() == "story narrator":
                return persona
        for persona in self.personas:
            text = " ".join([persona.id, persona.role, persona.behavior_mode, ",".join(persona.tags)]).lower()
            if "narrator" in text:
                return persona
        return None

    def _ensure_session_persona(self):
        if not self.personas:
            self.personas = self.storage.load_personas()
        known = {persona.id for persona in self.personas}
        if self.session.active_persona_id not in known:
            self.session.active_persona_id = self.personas[0].id if self.personas else ""
        if self.session.current_speaker_id not in known:
            self.session.current_speaker_id = self.session.active_persona_id

    def set_debug_prompt(self, prompt: str) -> None:
        with self._state_lock:
            if self._shutting_down:
                return
            self._debug_prompt = str(prompt or "")
        self._request_debug_refresh()

    def set_chat_visual_prompt_debug_from_parts(
        self,
        *,
        persona: PersonaConfig | None,
        reason: str = "manual",
        provider: str = "",
        stage: str = "",
        final_prompt: str = "",
        base_prompt: str = "",
        source_text: str = "",
        request_payload: dict[str, Any] | None = None,
    ) -> None:
        payload = dict(request_payload or {}) if isinstance(request_payload, dict) else {}
        provider_info = payload.get("provider_info") if isinstance(payload.get("provider_info"), dict) else {}
        prompt_style = str(provider_info.get("prompt_style") or prompting.visual_prompt_style(provider or "inherit"))
        lines = [
            "MPRC Visual Prompt Debug",
            f"Stage: {stage or 'base prompt'}",
            f"Reason: {reason or 'manual'}",
            f"Effective provider: {provider or provider_info.get('effective_provider') or 'inherit'}",
            f"Prompt style: {prompt_style}",
            f"Persona provider override: {provider_info.get('persona_provider_override', 'inherit')}",
            f"Active Visual Reply provider snapshot: {provider_info.get('active_provider_snapshot') or provider_info.get('active_provider_raw') or 'unknown'}",
        ]
        if persona is not None:
            visual = getattr(persona, "visual", None)
            lines.extend(
                [
                    "",
                    "[Persona / Visual Settings]",
                    f"Persona: {persona.display_name} ({persona.id})",
                    f"Role: {persona.role or persona.behavior_mode}",
                    f"Visual mode: {getattr(visual, 'mode', '')}",
                    f"Provider override: {getattr(visual, 'provider', '')}",
                    f"Model override: {getattr(visual, 'model', '')}",
                    f"Size override: {getattr(visual, 'size', '')}",
                    f"Style preset: {getattr(visual, 'style_preset', '')}",
                    f"Include scene summary: {bool(getattr(visual, 'include_scene_summary', False))}",
                    f"Include active speaker: {bool(getattr(visual, 'include_active_speaker', False))}",
                    f"Character description: {self._mprc_compact(getattr(visual, 'character_description', ''), 420)}",
                    f"Clothing / props: {self._mprc_compact(getattr(visual, 'clothing_props', ''), 260)}",
                    f"Environment style: {self._mprc_compact(getattr(visual, 'environment_style', ''), 260)}",
                    f"Negative prompt: {self._mprc_compact(getattr(visual, 'negative_prompt', ''), 260)}",
                ]
            )
        state = self.session.ar_state
        lines.extend(
            [
                "",
                "[AR State Inputs]",
                f"Current scene: {self._mprc_compact(state.current_scene or self.session.scene_title, 420)}",
                f"Location: {self._mprc_compact(state.location or self.session.location, 260)}",
                f"Time: {self._mprc_compact(state.time_of_day or self.session.time_of_day, 160)}",
                f"Mood: {self._mprc_compact(state.mood or self.session.mood, 220)}",
                f"Story goal: {self._mprc_compact(state.story_goal or self.session.objective, 320)}",
                f"Active characters: {', '.join(list(state.active_characters or []))}",
                f"Pending choices: {self._mprc_join_compact(list(state.pending_choices or []), 6, 140)}",
                f"Recent events: {self._mprc_join_compact(list(state.recent_events or [])[-4:], 4, 180)}",
                f"Scene summary: {self._mprc_compact(self.session.scene_summary, 700)}",
            ]
        )
        if source_text:
            lines.extend(["", "[Current Story Reply Input]", self._mprc_compact(source_text, 1800)])
        if payload:
            lines.extend(["", "[Hidden LLM Request Payload]", json.dumps(payload, indent=2, ensure_ascii=False)])
        if base_prompt:
            lines.extend(["", "[Fallback/Base Prompt]", self._mprc_compact(base_prompt, 1200)])
        if final_prompt:
            lines.extend(["", "[Final Image Prompt Sent]", final_prompt])
        with self._state_lock:
            if self._shutting_down:
                return
            self._chat_visual_prompt_debug = "\n".join(str(item) for item in lines if item is not None).strip()
        self._request_debug_refresh()

    def _request_debug_refresh(self) -> None:
        bridge = getattr(self, "_ui_bridge", None)
        if bridge is None:
            return
        try:
            bridge.debug_refresh_requested.emit()
        except RuntimeError:
            pass

    def bind_designer_tab(self, widget):
        from PySide6 import QtCore, QtWidgets

        if self.is_shutdown():
            return widget
        if widget is None:
            raise RuntimeError("Multi Persona Roleplay Designer UI did not provide a widget.")
        self._adopt_qobject_bridges(widget)
        mount = widget.findChild(QtWidgets.QWidget, "multi_persona_roleplay_mount")
        if mount is None:
            mount = widget
        layout = mount.layout()
        if layout is None:
            layout = QtWidgets.QVBoxLayout(mount)
            layout.setContentsMargins(0, 0, 0, 0)
        self._controls.clear()
        while layout.count():
            item = layout.takeAt(0)
            child = item.widget()
            if child is not None:
                child.setParent(None)
                child.deleteLater()
        panel = self._build_panel()
        layout.addWidget(panel)
        widget.setObjectName("multi_persona_roleplay_tab")
        widget.setProperty("addon_id", "nc.multi_persona_roleplay")
        self._widget = widget
        QtCore.QTimer.singleShot(0, self.refresh_ui)
        return widget

    def _build_panel(self):
        from PySide6 import QtCore, QtWidgets
        from PySide6 import QtGui

        root = QtWidgets.QWidget()
        root.setObjectName("mprc_root")
        self._controls["root"] = root
        root_layout = QtWidgets.QVBoxLayout(root)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)
        root_layout.setAlignment(QtCore.Qt.Alignment())

        header = QtWidgets.QHBoxLayout()
        enabled = QtWidgets.QCheckBox("Enable roleplay mode")
        enabled.setObjectName("mprc_enabled_checkbox")
        show_character = QtWidgets.QCheckBox("Track current speaker in character preview")
        show_character.setObjectName("mprc_show_character_checkbox")
        ar_mode = QtWidgets.QCheckBox("AlternativeReality Mode")
        ar_mode.setObjectName("mprc_ar_mode_checkbox")
        active = QtWidgets.QComboBox()
        active.setObjectName("mprc_active_persona_combo")
        header.addWidget(enabled)
        header.addWidget(show_character)
        header.addWidget(ar_mode)
        header.addStretch(1)
        header.addWidget(QtWidgets.QLabel("Active persona"))
        header.addWidget(active, 1)
        root_layout.addLayout(header)
        self._controls["enabled"] = enabled
        self._controls["show_character"] = show_character
        self._controls["ar_mode"] = ar_mode
        self._controls["active"] = active
        root_layout.addWidget(self._build_character_preview_panel())

        tabs = QtWidgets.QWidget()
        tabs.setObjectName("mprc_inner_tabs")
        tabs.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        tabs_layout = QtWidgets.QVBoxLayout(tabs)
        tabs_layout.setContentsMargins(5, 5, 5, 5)
        tabs_layout.setSpacing(4)
        nav_row = QtWidgets.QWidget()
        nav_row.setObjectName("mprc_inner_tab_nav_row")
        nav_row_layout = QtWidgets.QHBoxLayout(nav_row)
        nav_row_layout.setContentsMargins(0, 0, 0, 0)
        nav_row_layout.setSpacing(4)
        nav_prev = QtWidgets.QToolButton()
        nav_prev.setObjectName("mprc_inner_tab_prev_button")
        nav_prev.setText("<")
        nav_prev.setToolTip("Show earlier roleplay tabs")
        nav_prev.setFixedSize(22, 58)
        nav_next = QtWidgets.QToolButton()
        nav_next.setObjectName("mprc_inner_tab_next_button")
        nav_next.setText(">")
        nav_next.setToolTip("Show later roleplay tabs")
        nav_next.setFixedSize(22, 58)
        nav_scroll = _MprcTabNavScrollArea()
        nav_scroll.setObjectName("mprc_inner_tab_scroll")
        nav_scroll.setWidgetResizable(False)
        nav_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        nav_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        nav_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        nav_scroll.setFixedHeight(84)
        nav_scroll.setFocusPolicy(QtCore.Qt.NoFocus)
        nav_scroll.viewport().setAutoFillBackground(False)
        nav = QtWidgets.QWidget()
        nav.setObjectName("mprc_inner_tab_nav")
        nav.setFixedHeight(80)
        nav_layout = QtWidgets.QHBoxLayout(nav)
        nav_layout.setContentsMargins(0, 4, 0, 8)
        nav_layout.setSpacing(5)
        stack = _MprcCurrentPageStack()
        stack.setObjectName("mprc_inner_tab_stack")
        stack.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        buttons: list[_MprcTabButton] = []
        tab_specs = [
            ("play", self._build_chat_play_tab(), "Play", "MPRC-owned chat and play surface.", "#f97316"),
            ("guide", self._build_guide_tab(), "Guide", "Step-by-step guide and default scenario notes.", "#38bdf8"),
            ("status", self._build_status_tab(), "Story Health", "Readable story readiness checks, repair actions, voice checks, memory, and skipped-action notes.", "#facc15"),
            ("registry", self._build_registry_tab(), "Registry", "Persona Registry", "#60a5fa"),
            ("editor", self._build_editor_tab(), "Editor", "Persona Editor", "#a78bfa"),
            ("voice", self._build_voice_tab(), "Voice", "Voice Per Persona", "#22c55e"),
            ("session", self._build_session_tab(), "Session", "Roleplay Session", "#f59e0b"),
            ("ar", self._build_ar_tab(), "AR", "AlternativeReality Mode", "#06b6d4"),
            ("master", self._build_master_story_tab(), "Master", "Master Story Builder", "#e879f9"),
            (
                "audio",
                self._build_audio_tab(),
                "Story Sounds",
                "Story Sounds and Story Sound Library.\n"
                "Use this tab to import sound packs, attach local sound files, build audio prompts, preview cues, and make story tags like [AMBIENCE: pub ambient], [MUSIC: ...], [FX: ...], and [STINGER: ...] play in the background instead of being spoken.",
                "#14b8a6",
            ),
            ("visual", self._build_visual_tab(), "Story Images", "Scene image settings for character, mood, image intent, and Visual Reply generation.", "#fb7185"),
            ("debug", self._build_debug_tab(), "Troubleshooting", "Advanced prompt, routing, state, and Visual Reply diagnostics.", "#94a3b8"),
        ]
        for key, page, title, tooltip, color in tab_specs:
            wrapped_page = self._wrap_mprc_tab_page(page, title)
            index = stack.addWidget(wrapped_page)
            if str(getattr(wrapped_page, "objectName", lambda: "")() or "") == "mprc_chat_play_tab":
                self._chat_play_page = wrapped_page
                self._chat_play_stack_index = index
            button = _MprcTabButton(index, title, self._tab_icon(title.lower(), color), color, tooltip)
            button.setProperty("_mprc_tab_key", key)
            button.clicked.connect(self._select_mprc_tab)
            button.move_requested.connect(self._move_mprc_tab_button)
            buttons.append(button)
        self._controls["tab_buttons_all"] = buttons
        self._controls["tab_button_layout"] = nav_layout
        self._apply_mprc_tab_button_order(persist=False)
        nav_scroll.setWidget(nav)
        nav_row_layout.addWidget(nav_prev, 0)
        nav_row_layout.addWidget(nav_scroll, 1)
        nav_row_layout.addWidget(nav_next, 0)
        tabs_layout.addWidget(nav_row)
        tabs_layout.addWidget(stack, 1)
        root_layout.addWidget(tabs, 1)
        self._controls["tabs"] = tabs
        self._controls["tab_stack"] = stack
        self._controls.setdefault("tab_buttons", buttons)
        self._controls["tab_nav_scroll"] = nav_scroll
        self._controls["tab_nav_prev"] = nav_prev
        self._controls["tab_nav_next"] = nav_next
        nav_prev.clicked.connect(lambda *_args: self._scroll_mprc_tab_nav(-1))
        nav_next.clicked.connect(lambda *_args: self._scroll_mprc_tab_nav(1))
        try:
            scrollbar = nav_scroll.horizontalScrollBar()
            scrollbar.valueChanged.connect(lambda *_args: self._update_mprc_tab_nav_buttons())
            scrollbar.rangeChanged.connect(lambda *_args: self._update_mprc_tab_nav_buttons())
            QtCore.QTimer.singleShot(0, self._update_mprc_tab_nav_buttons)
        except Exception:
            pass
        self._select_mprc_tab(0)
        self._assign_control_object_names()
        self._install_tooltips_and_refine()
        self._install_spellcheck_widgets()

        enabled.toggled.connect(self._on_enabled_changed)
        show_character.toggled.connect(self._on_show_character_changed)
        ar_mode.toggled.connect(self._on_ar_mode_changed)
        active.currentIndexChanged.connect(lambda *_args: self._on_active_persona_changed())

        root.setStyleSheet(
            MPRC_CHECKBOX_STYLESHEET + """
            QWidget#mprc_root { background: #101720; color: #f4f7fb; }
            QGroupBox { border: 1px solid #36506d; border-radius: 10px; margin-top: 10px; padding: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #dbeafe; font-weight: 700; }
            QLabel { color: #f4f7fb; }
            QLabel[muted="true"] { color: #9fb3c8; }
            QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {
                background: #182536; color: #f4f7fb; border: 1px solid #3d5a7c; border-radius: 8px; padding: 4px;
            }
            QPushButton { background: #1b2b40; color: #f4f7fb; border: 1px solid #416184; border-radius: 8px; padding: 6px 10px; font-weight: 600; }
            QPushButton:hover { background: #243956; }
            QToolButton#mprc_inner_tab_prev_button, QToolButton#mprc_inner_tab_next_button {
                background: #1b2b40; color: #f4f7fb; border: 1px solid #416184; border-radius: 8px; font-weight: 800;
            }
            QToolButton#mprc_inner_tab_prev_button:disabled, QToolButton#mprc_inner_tab_next_button:disabled {
                color: #6f8298; border-color: #2b4058;
            }
            QWidget#mprc_inner_tabs { background: #101720; border: none; border-radius: 12px; }
            QScrollArea#mprc_inner_tab_scroll {
                background: transparent;
                border: none;
                border-radius: 10px;
            }
            QScrollArea#mprc_inner_tab_scroll > QWidget,
            QScrollArea#mprc_inner_tab_scroll > QWidget > QWidget {
                background: transparent;
                border: none;
            }
            QWidget#mprc_inner_tab_nav { background: transparent; }
            QStackedWidget#mprc_inner_tab_stack {
                background: #122033;
                border: 1px solid #2d4561;
                border-top-color: #36506d;
                border-radius: 10px;
                padding: 3px;
            }
            QTabWidget::pane {
                background: #101720;
                border: 1px solid #2b4059;
                border-radius: 10px;
                top: -1px;
            }
            QTabBar::tab {
                background: #111c28;
                color: #e8f2ff;
                border: 1px solid #2b4059;
                border-radius: 8px;
                min-height: 22px;
                padding: 5px 12px;
                margin-right: 3px;
            }
            QTabBar::tab:selected {
                background: #17263a;
                border-color: #4f78a2;
            }
            QTabBar::tab:hover {
                background: #1b3048;
                border-color: #5f8bb8;
            }
            """
        )
        return root

    def _wrap_mprc_tab_page(self, page, title: str):
        if page is None:
            return page
        original_name = str(page.objectName() or "")
        scroll = QtWidgets.QScrollArea()
        if original_name == "mprc_chat_play_tab":
            page.setObjectName("mprc_chat_play_content")
            scroll.setObjectName("mprc_chat_play_tab")
        else:
            scroll.setObjectName(f"mprc_{normalize_persona_id(title)}_tab_scroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        scroll.viewport().setAutoFillBackground(False)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; } QScrollArea > QWidget > QWidget { background: transparent; }")
        scroll.setWidget(page)
        return scroll

    def _apply_mprc_tab_button_order(self, *, persist: bool = False, order_keys: list[str] | None = None) -> None:
        layout = self._controls.get("tab_button_layout")
        all_buttons = list(self._controls.get("tab_buttons_all") or [])
        if layout is None or not all_buttons:
            return
        by_key = {
            str(button.property("_mprc_tab_key") or ""): button
            for button in all_buttons
            if str(button.property("_mprc_tab_key") or "").strip()
        }
        default_order = [str(button.property("_mprc_tab_key") or "") for button in all_buttons]
        raw_order = order_keys if order_keys is not None else self.settings.get("mprc_tab_button_order")
        requested = [str(item or "").strip() for item in list(raw_order or []) if str(item or "").strip()]
        ordered_keys = [key for key in requested if key in by_key]
        ordered_keys.extend(key for key in default_order if key and key not in ordered_keys)
        ordered_buttons = [by_key[key] for key in ordered_keys if key in by_key]
        while layout.count():
            layout.takeAt(0)
        for button in ordered_buttons:
            layout.addWidget(button)
        layout.addStretch(1)
        self._controls["tab_buttons"] = ordered_buttons
        if persist:
            self.settings["mprc_tab_button_order"] = ordered_keys
            self.storage.save_settings(self.settings)
        try:
            parent = layout.parentWidget()
            if parent is not None:
                parent.adjustSize()
                parent.updateGeometry()
            nav_scroll = self._controls.get("tab_nav_scroll")
            if nav_scroll is not None and nav_scroll.widget() is not None:
                nav_scroll.widget().adjustSize()
        except Exception:
            pass
        current = self._controls.get("tab_stack").currentIndex() if self._controls.get("tab_stack") is not None else 0
        self._select_mprc_tab(current)

    def _move_mprc_tab_button(self, source_index: int, target_index: int) -> None:
        buttons = list(self._controls.get("tab_buttons") or [])
        if source_index == target_index or not buttons:
            return
        source_pos = next((index for index, button in enumerate(buttons) if int(getattr(button, "_index", -1)) == int(source_index)), -1)
        target_pos = next((index for index, button in enumerate(buttons) if int(getattr(button, "_index", -1)) == int(target_index)), -1)
        if source_pos < 0 or target_pos < 0:
            return
        button = buttons.pop(source_pos)
        insert_pos = target_pos if source_pos > target_pos else target_pos
        insert_pos = max(0, min(len(buttons), insert_pos))
        buttons.insert(insert_pos, button)
        order_keys = [str(item.property("_mprc_tab_key") or "") for item in buttons]
        self._apply_mprc_tab_button_order(persist=True, order_keys=order_keys)

    def _select_mprc_tab(self, index: int):
        stack = self._controls.get("tab_stack")
        buttons = self._controls.get("tab_buttons") or []
        if stack is not None:
            stack.setCurrentIndex(index)
            try:
                self._sync_mprc_tab_stack_height()
                stack.updateGeometry()
                parent = stack.parentWidget()
                while parent is not None:
                    parent.updateGeometry()
                    parent = parent.parentWidget()
            except Exception:
                pass
        for button in buttons:
            if hasattr(button, "set_selected"):
                button.set_selected(int(getattr(button, "_index", -1)) == int(index))
        self._ensure_mprc_tab_button_visible(index)
        self._update_mprc_tab_nav_buttons()

    def _scroll_mprc_tab_nav(self, direction: int) -> None:
        nav_scroll = self._controls.get("tab_nav_scroll")
        if nav_scroll is None:
            return
        try:
            scrollbar = nav_scroll.horizontalScrollBar()
            step = max(90, int(nav_scroll.viewport().width() * 0.65))
            scrollbar.setValue(scrollbar.value() + (step if int(direction or 0) > 0 else -step))
            self._update_mprc_tab_nav_buttons()
        except Exception:
            pass

    def _ensure_mprc_tab_button_visible(self, index: int) -> None:
        nav_scroll = self._controls.get("tab_nav_scroll")
        buttons = self._controls.get("tab_buttons") or []
        if nav_scroll is None:
            return
        button = next((item for item in buttons if int(getattr(item, "_index", -1)) == int(index)), None)
        if button is None:
            return
        try:
            nav_scroll.ensureWidgetVisible(button, 12, 0)
        except Exception:
            pass

    def _update_mprc_tab_nav_buttons(self) -> None:
        nav_scroll = self._controls.get("tab_nav_scroll")
        prev_button = self._controls.get("tab_nav_prev")
        next_button = self._controls.get("tab_nav_next")
        if nav_scroll is None or prev_button is None or next_button is None:
            return
        try:
            scrollbar = nav_scroll.horizontalScrollBar()
            has_overflow = scrollbar.maximum() > scrollbar.minimum()
            prev_button.setVisible(has_overflow)
            next_button.setVisible(has_overflow)
            prev_button.setEnabled(scrollbar.value() > scrollbar.minimum())
            next_button.setEnabled(scrollbar.value() < scrollbar.maximum())
        except Exception:
            pass

    def _sync_mprc_tab_stack_height(self) -> None:
        stack = self._controls.get("tab_stack")
        tabs = self._controls.get("tabs")
        if stack is None:
            return
        current = stack.currentWidget()
        if current is None:
            return
        is_play = str(current.objectName() or "") == "mprc_chat_play_tab"
        if not is_play:
            stack.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
            stack.setMinimumHeight(420)
            stack.setMaximumHeight(16777215)
            if tabs is not None:
                tabs.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
                tabs.setMinimumHeight(520)
                tabs.setMaximumHeight(16777215)
            return
        height = 620
        stack.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        stack.setMinimumHeight(height)
        stack.setMaximumHeight(16777215)
        if tabs is not None:
            tabs.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
            nav_height = 84
            try:
                nav = tabs.findChild(QtWidgets.QScrollArea, "mprc_inner_tab_scroll")
                if nav is not None:
                    nav_height = max(nav_height, int(nav.height() or nav.sizeHint().height() or 0))
            except Exception:
                pass
            frame = 4
            total = height + nav_height + frame
            tabs.setMinimumHeight(total)
            tabs.setMaximumHeight(16777215)

    def _assign_control_object_names(self):
        for key, widget in list(self._controls.items()):
            if not isinstance(widget, QtCore.QObject):
                continue
            try:
                if not str(widget.objectName() or "").strip():
                    widget.setObjectName(f"mprc_{key}")
            except Exception:
                continue

    def _group(self, title: str):
        from PySide6 import QtWidgets

        box = QtWidgets.QGroupBox(title)
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        return box, layout

    def _tab_icon(self, kind: str, color: str):
        from PySide6 import QtCore, QtGui

        pixmap = QtGui.QPixmap(50, 50)
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        accent = QtGui.QColor(color)
        painter.setPen(QtGui.QPen(accent, 3))
        painter.setBrush(QtGui.QColor(17, 27, 40))
        painter.drawRoundedRect(4, 4, 42, 42, 10, 10)
        painter.setBrush(accent)
        painter.setPen(QtGui.QPen(accent, 3))
        key = str(kind or "").lower()
        if key == "play":
            points = [
                QtCore.QPointF(18, 13),
                QtCore.QPointF(18, 37),
                QtCore.QPointF(36, 25),
            ]
            painter.drawPolygon(QtGui.QPolygonF(points))
        elif key == "guide":
            painter.drawEllipse(14, 10, 22, 22)
            painter.drawLine(25, 32, 25, 39)
        elif key == "status":
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawEllipse(12, 12, 26, 26)
            painter.drawLine(25, 17, 25, 27)
            painter.drawLine(25, 32, 25, 33)
        elif key == "registry":
            for y in (13, 24, 35):
                painter.drawEllipse(12, y, 6, 6)
                painter.drawLine(23, y + 3, 38, y + 3)
        elif key == "cast":
            painter.drawEllipse(15, 13, 9, 9)
            painter.drawEllipse(27, 13, 9, 9)
            painter.drawRoundedRect(12, 26, 13, 12, 4, 4)
            painter.drawRoundedRect(27, 26, 13, 12, 4, 4)
        elif key == "editor":
            painter.drawLine(15, 35, 34, 16)
            painter.drawLine(30, 12, 38, 20)
            painter.drawLine(13, 38, 22, 35)
        elif key == "voice":
            painter.drawRect(14, 19, 7, 13)
            painter.drawArc(19, 14, 18, 24, -45 * 16, 90 * 16)
            painter.drawArc(24, 10, 18, 32, -45 * 16, 90 * 16)
        elif key == "session":
            painter.drawEllipse(11, 12, 28, 28)
            painter.drawLine(25, 25, 25, 15)
            painter.drawLine(25, 25, 34, 30)
        elif key == "events":
            painter.drawLine(18, 12, 18, 38)
            for y in (15, 25, 35):
                painter.drawEllipse(15, y - 3, 6, 6)
                painter.drawLine(24, y, 37, y)
        elif key == "ar":
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRoundedRect(12, 14, 26, 22, 6, 6)
            painter.drawLine(18, 14, 18, 10)
            painter.drawLine(32, 14, 32, 10)
            painter.drawEllipse(18, 23, 4, 4)
            painter.drawEllipse(28, 23, 4, 4)
        elif key == "audio":
            painter.drawEllipse(13, 20, 6, 10)
            painter.drawEllipse(29, 20, 6, 10)
            painter.drawLine(19, 25, 29, 25)
            painter.drawArc(14, 11, 20, 24, 20 * 16, 140 * 16)
        elif key == "visual":
            painter.drawRect(11, 14, 28, 22)
            painter.drawEllipse(28, 18, 5, 5)
            painter.drawLine(14, 34, 22, 27)
            painter.drawLine(22, 27, 29, 33)
            painter.drawLine(29, 33, 37, 25)
        elif key == "choices":
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRoundedRect(12, 12, 27, 26, 6, 6)
            painter.drawLine(18, 19, 31, 19)
            painter.drawLine(18, 27, 31, 27)
            painter.drawLine(18, 35, 27, 35)
        elif key == "master":
            painter.drawLine(15, 15, 35, 15)
            painter.drawLine(15, 23, 35, 23)
            painter.drawLine(15, 31, 29, 31)
            painter.drawEllipse(31, 29, 7, 7)
        elif key == "debug":
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawEllipse(14, 14, 22, 22)
            painter.drawEllipse(22, 22, 6, 6)
            for x1, y1, x2, y2 in ((25, 8, 25, 14), (25, 36, 25, 42), (8, 25, 14, 25), (36, 25, 42, 25)):
                painter.drawLine(x1, y1, x2, y2)
        else:
            painter.drawRoundedRect(14, 13, 22, 24, 5, 5)
            painter.drawLine(18, 20, 32, 20)
            painter.drawLine(18, 27, 32, 27)
        painter.end()
        return QtGui.QIcon(pixmap)

    def _story_state_tab_button(self, title: str, icon_key: str, color: str):
        from PySide6 import QtCore, QtWidgets

        button = QtWidgets.QWidget()
        button.setObjectName("mprc_story_state_tab_button")
        button.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        button.setFixedSize(80, 64)
        layout = QtWidgets.QVBoxLayout(button)
        layout.setContentsMargins(7, 3, 7, 4)
        layout.setSpacing(1)

        label = QtWidgets.QLabel(str(title or ""))
        label.setObjectName("mprc_story_state_tab_title")
        label.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)
        label.setStyleSheet(f"color: {color}; font-weight: 800; background: transparent; border: none;")
        label.setMinimumHeight(16)

        icon = QtWidgets.QLabel()
        icon.setObjectName("mprc_story_state_tab_icon")
        icon.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)
        icon.setPixmap(self._tab_icon(icon_key, color).pixmap(QtCore.QSize(34, 34)))
        icon.setFixedHeight(36)
        icon.setStyleSheet("background: transparent; border: none;")

        layout.addWidget(label)
        layout.addWidget(icon)
        return button

    @staticmethod
    def _story_state_tab_stylesheet() -> str:
        return """
        QTabWidget#mprc_story_state_tabs {
            background: #122033;
            border: none;
        }
        QTabWidget#mprc_story_state_tabs::pane {
            background: #122033;
            border: 1px solid #2d4561;
            border-radius: 10px;
            top: -1px;
        }
        QTabWidget#mprc_story_state_tabs QTabBar {
            background: #122033;
        }
        QTabWidget#mprc_story_state_tabs QTabBar::tab {
            background: #111b28;
            border: 1px solid #36506d;
            border-radius: 9px;
            min-width: 86px;
            min-height: 68px;
            padding: 0px;
            margin-right: 4px;
            margin-bottom: 2px;
        }
        QTabWidget#mprc_story_state_tabs QTabBar::tab:selected {
            background: #1c2d43;
            border-color: #4f78a2;
        }
        QTabWidget#mprc_story_state_tabs QTabBar::tab:hover {
            background: #17263a;
            border-color: #5f8bb8;
        }
        """

    def _build_chat_play_story_engine_box(self, parent=None):
        box = QtWidgets.QGroupBox("Story Engine")
        box.setObjectName("mprc_story_engine_box")
        box.setToolTip("Read-only view of the MPRC story systems used by the next Play turn.")
        box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        box.setMinimumHeight(220)
        box.setMaximumHeight(420)
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        tabs = QtWidgets.QTabWidget(box)
        tabs.setObjectName("mprc_story_engine_tabs")
        tabs.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        tabs.setMinimumHeight(180)
        tabs.setStyleSheet(
            """
            QTabWidget#mprc_story_engine_tabs::pane {
                border: 1px solid #2d4561;
                border-radius: 8px;
                background: #0b121a;
                top: -1px;
            }
            QTabWidget#mprc_story_engine_tabs QTabBar::tab {
                background: #111b28;
                border: 1px solid #36506d;
                border-top-left-radius: 7px;
                border-top-right-radius: 7px;
                color: #dbeafe;
                min-height: 24px;
                padding: 4px 8px;
                margin-right: 3px;
            }
            QTabWidget#mprc_story_engine_tabs QTabBar::tab:selected {
                background: #1c2d43;
                border-color: #4f78a2;
            }
            QFrame[mprcInsightCard="true"] {
                background: #08111b;
                border: 1px solid #26394f;
                border-radius: 7px;
            }
            QLabel[mprcInsightTitle="true"] {
                color: #dbeafe;
                font-weight: 800;
            }
            QLabel[mprcInsightHelp="true"] {
                color: #9fb3c8;
            }
            QPlainTextEdit[mprcInsightText="true"] {
                background: #07101a;
                border: 1px solid #203149;
                border-radius: 6px;
                color: #dbeafe;
            }
            """
        )
        layout.addWidget(tabs)

        def add_page(
            title: str,
            icon_key: str,
            color: str,
            object_name: str,
            headline: str,
            help_text: str,
        ) -> QtWidgets.QPlainTextEdit:
            page = QtWidgets.QWidget()
            page.setObjectName(f"{object_name}_page")
            page_layout = QtWidgets.QVBoxLayout(page)
            page_layout.setContentsMargins(7, 7, 7, 7)
            page_layout.setSpacing(6)

            card = QtWidgets.QFrame(page)
            card.setProperty("mprcInsightCard", True)
            card_layout = QtWidgets.QVBoxLayout(card)
            card_layout.setContentsMargins(9, 8, 9, 9)
            card_layout.setSpacing(5)

            title_label = QtWidgets.QLabel(headline)
            title_label.setProperty("mprcInsightTitle", True)
            title_label.setWordWrap(True)
            help_label = QtWidgets.QLabel(help_text)
            help_label.setProperty("mprcInsightHelp", True)
            help_label.setWordWrap(True)

            summary = QtWidgets.QPlainTextEdit()
            summary.setObjectName(object_name)
            summary.setProperty("mprcInsightText", True)
            summary.setReadOnly(True)
            summary.setMinimumHeight(110)
            summary.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)

            card_layout.addWidget(title_label)
            card_layout.addWidget(help_label)
            card_layout.addWidget(summary, 1)
            page_layout.addWidget(card, 1)
            index = tabs.addTab(page, self._tab_icon(icon_key, color), title)
            tabs.setTabToolTip(index, help_text)
            return summary

        story_director_summary = add_page(
            "Story Director",
            "master",
            "#a78bfa",
            "mprc_chat_story_director_summary",
            "How the next story turn is steered",
            "Shows focused speaker, setup cast mode, pacing, choices, and structured-output state.",
        )
        memory_summary = add_page(
            "Memory/Data Bank",
            "session",
            "#60a5fa",
            "mprc_chat_memory_databank_summary",
            "What long memory can contribute",
            "Shows addon-local memory, configured story archives, and data-bank indexing state.",
        )
        visual_summary = add_page(
            "Visual Beat",
            "visual",
            "#fb7185",
            "mprc_chat_visual_beat_summary",
            "Which story moment Visual Reply should draw",
            "Shows the visible scene beat, subject, mood, location, and image prompt intent.",
        )
        voice_summary = add_page(
            "Voice Segments",
            "voice",
            "#34d399",
            "mprc_chat_voice_segments_summary",
            "How a reply is split for multiple voices",
            "Shows the speaker tags and current voice-routing preview for the latest story reply.",
        )
        spotify_summary = add_page(
            "Spotify Music",
            "audio",
            "#1db954",
            "mprc_chat_spotify_music_summary",
            "Which soundtrack request is sent to Spotify Sense",
            "Shows the mood, ambience/music choice, query, and last Spotify Sense result for story playback.",
        )

        self._controls.update(
            {
                "chat_story_engine_box": box,
                "chat_story_engine_tabs": tabs,
                "chat_story_director_summary": story_director_summary,
                "chat_memory_databank_summary": memory_summary,
                "chat_visual_beat_summary": visual_summary,
                "chat_voice_segments_summary": voice_summary,
                "chat_spotify_music_summary": spotify_summary,
            }
        )
        return box

    def _build_character_preview_panel(self):
        from PySide6 import QtCore, QtWidgets

        panel = QtWidgets.QGroupBox("Current Character")
        panel.setObjectName("mprc_character_preview_panel")
        panel.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        panel.setMinimumHeight(500)
        panel.setMaximumHeight(16777215)
        current_row = QtWidgets.QHBoxLayout()
        current_row.setContentsMargins(20, 0, 0, 0)
        current_row.setSpacing(14)
        image = QtWidgets.QLabel()
        image.setObjectName("mprc_current_character_image")
        image.setFixedSize(230, 300)
        image.setMinimumSize(230, 300)
        image.setMaximumSize(230, 300)
        image.setProperty("_mprc_image_width", 230)
        image.setProperty("_mprc_image_height", 300)
        image.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        image.setAlignment(QtCore.Qt.AlignCenter)
        image.setToolTip("The active persona picture. This updates when the active persona changes.")
        info = QtWidgets.QVBoxLayout()
        info.setContentsMargins(0, 4, 0, 0)
        info.setSpacing(4)
        info_scroll = QtWidgets.QScrollArea()
        info_scroll.setObjectName("mprc_current_character_info_scroll")
        info_scroll.setWidgetResizable(True)
        info_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        info_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        info_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        info_scroll.setMinimumHeight(86)
        info_scroll.setMaximumHeight(132)
        info_scroll.setStyleSheet("QScrollArea#mprc_current_character_info_scroll { background: transparent; border: 0px; }")
        info_text = QtWidgets.QWidget()
        info_text.setObjectName("mprc_current_character_info_text")
        info_text.setStyleSheet("QWidget#mprc_current_character_info_text { background: transparent; }")
        info_text_layout = QtWidgets.QVBoxLayout(info_text)
        info_text_layout.setContentsMargins(0, 0, 8, 0)
        info_text_layout.setSpacing(3)
        name = QtWidgets.QLabel("No active persona")
        name.setObjectName("mprc_current_character_name")
        name.setStyleSheet("font-size: 16px; font-weight: 800;")
        role = QtWidgets.QLabel("")
        role.setObjectName("mprc_current_character_role")
        role.setWordWrap(True)
        role.setProperty("muted", True)
        role.setMaximumWidth(760)
        meta = QtWidgets.QLabel("")
        meta.setObjectName("mprc_current_character_meta")
        meta.setWordWrap(True)
        meta.setProperty("muted", True)
        meta.setMaximumWidth(900)
        story = QtWidgets.QLabel("")
        story.setObjectName("mprc_current_character_story")
        story.setWordWrap(True)
        story.setProperty("muted", True)
        story.setMaximumWidth(900)
        quick_status = QtWidgets.QLabel("")
        quick_status.setObjectName("mprc_current_character_quick_status")
        quick_status.setWordWrap(True)
        quick_status.setProperty("muted", True)
        view_row = QtWidgets.QHBoxLayout()
        view_label = QtWidgets.QLabel("Show")
        view_label.setObjectName("mprc_current_character_view_label")
        view_label.setProperty("muted", True)
        view_mode = QtWidgets.QComboBox()
        view_mode.setObjectName("mprc_current_character_view_mode")
        view_mode.addItem("Active story personas", "active_story")
        view_mode.addItem("All personas", "all")
        view_mode.setToolTip("Choose whether the Current Character card shows only the loaded story roster or every saved persona.")
        view_row.addWidget(view_label)
        view_row.addWidget(view_mode, 0)
        view_row.addStretch(1)
        button_row = QtWidgets.QHBoxLayout()
        change_avatar = QtWidgets.QPushButton("Change Avatar Image")
        save_persona = QtWidgets.QPushButton("Save Persona")
        import_persona = QtWidgets.QPushButton("Import Persona")
        export_personas = QtWidgets.QPushButton("Export Personas")
        duplicate_persona = QtWidgets.QPushButton("Duplicate")
        edit_persona = QtWidgets.QPushButton("Edit Persona")
        for button in (change_avatar, save_persona, import_persona, export_personas, duplicate_persona, edit_persona):
            button.setMinimumHeight(30)
            button_row.addWidget(button)
        button_row.addStretch(1)
        info_text_layout.addWidget(name)
        info_text_layout.addWidget(role)
        info_text_layout.addWidget(meta)
        info_text_layout.addWidget(story)
        info_text_layout.addStretch(1)
        info_scroll.setWidget(info_text)
        info.addLayout(view_row)
        info.addWidget(info_scroll, 1)
        info.addLayout(button_row)
        info.addWidget(quick_status)
        current_row.addWidget(image, 0, QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        current_row.addLayout(info, 1)
        layout.addLayout(current_row)
        roster_frame = QtWidgets.QFrame()
        roster_frame.setObjectName("mprc_character_roster_frame")
        roster_frame.setMinimumHeight(172)
        roster_frame.setMaximumHeight(190)
        roster_frame.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        roster_frame.setStyleSheet(
            """
            QFrame#mprc_character_roster_frame {
                border: 1px solid #36506d;
                border-radius: 10px;
                background: #08111b;
            }
            """
        )
        roster_layout = QtWidgets.QVBoxLayout(roster_frame)
        roster_layout.setContentsMargins(14, 12, 14, 14)
        roster_layout.setSpacing(0)
        strip = QtWidgets.QScrollArea()
        strip.setWidgetResizable(False)
        strip.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        strip.setMinimumHeight(146)
        strip.setMaximumHeight(154)
        strip.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        strip.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        strip.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        strip.setFrameShape(QtWidgets.QFrame.NoFrame)
        strip.setStyleSheet(
            "QScrollArea { background: transparent; border: 0px; border-radius: 8px; } "
            "QScrollArea > QWidget > QWidget { background: #08111b; }"
        )
        strip_content = QtWidgets.QWidget()
        strip_content.setObjectName("mprc_character_roster_content")
        strip_content.setMinimumHeight(136)
        strip_content.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        strip_content.setStyleSheet("QWidget#mprc_character_roster_content { background: #08111b; }")
        strip_layout = QtWidgets.QHBoxLayout(strip_content)
        strip_layout.setContentsMargins(0, 0, 0, 2)
        strip_layout.setSpacing(12)
        strip.setWidget(strip_content)
        roster_layout.addWidget(strip)
        layout.addWidget(roster_frame, 0)
        self._controls.update({
            "character_preview_panel": panel,
            "current_character_image": image,
            "current_character_name": name,
            "current_character_role": role,
            "current_character_meta": meta,
            "current_character_story": story,
            "current_character_quick_status": quick_status,
            "current_character_view_label": view_label,
            "current_character_view_mode": view_mode,
            "quick_change_avatar": change_avatar,
            "quick_save_persona": save_persona,
            "quick_import_persona": import_persona,
            "quick_export_personas": export_personas,
            "quick_duplicate_persona": duplicate_persona,
            "quick_edit_persona": edit_persona,
            "character_roster_frame": roster_frame,
            "character_roster_strip": strip,
            "character_roster_content": strip_content,
            "character_roster_layout": strip_layout,
        })
        change_avatar.clicked.connect(self._quick_change_avatar_image)
        save_persona.clicked.connect(self._quick_save_persona)
        import_persona.clicked.connect(self._quick_import_persona)
        export_personas.clicked.connect(self._export_personas)
        duplicate_persona.clicked.connect(self._quick_duplicate_persona)
        edit_persona.clicked.connect(self._quick_edit_persona)
        view_mode.currentIndexChanged.connect(lambda *_args: self._on_current_character_view_mode_changed())
        return panel

    def _guide(self, text: str):
        from PySide6 import QtWidgets

        label = QtWidgets.QLabel(str(text or "").strip())
        label.setWordWrap(True)
        label.setProperty("muted", True)
        label.setToolTip("Quick guide for this Roleplay addon section.")
        return label

    def _build_chat_play_tab(self):
        from PySide6 import QtCore, QtWidgets
        from PySide6 import QtUiTools

        ui_path = Path(__file__).resolve().parent / "ui" / "chat_play.ui"
        ui_file = QtCore.QFile(str(ui_path))
        if not ui_file.open(QtCore.QIODevice.ReadOnly):
            raise RuntimeError(f"Could not open MPRC Chat/Play UI file: {ui_path}")
        try:
            page = QtUiTools.QUiLoader().load(ui_file)
        finally:
            ui_file.close()
        if page is None:
            raise RuntimeError(f"MPRC Chat/Play UI file did not produce a widget: {ui_path}")

        controls = {
            "chat_start": page.findChild(QtWidgets.QPushButton, "mprc_chat_start_button"),
            "chat_pause": page.findChild(QtWidgets.QPushButton, "mprc_chat_pause_button"),
            "chat_restart": page.findChild(QtWidgets.QPushButton, "mprc_chat_restart_button"),
            "chat_clear": page.findChild(QtWidgets.QPushButton, "mprc_chat_clear_button"),
            "chat_float": page.findChild(QtWidgets.QPushButton, "mprc_chat_float_button"),
            "chat_export_structured_output": page.findChild(QtWidgets.QPushButton, "mprc_chat_export_structured_output_button"),
            "chat_story_font_size_label": page.findChild(QtWidgets.QLabel, "mprc_chat_story_font_size_label"),
            "chat_story_font_size": page.findChild(QtWidgets.QSpinBox, "mprc_chat_story_font_size_spin"),
            "chat_remote_install": page.findChild(QtWidgets.QPushButton, "mprc_chat_remote_install_button"),
            "chat_remote_enabled": page.findChild(QtWidgets.QCheckBox, "mprc_chat_remote_enabled_checkbox"),
            "chat_remote_host": page.findChild(QtWidgets.QLineEdit, "mprc_chat_remote_host_input"),
            "chat_remote_port": page.findChild(QtWidgets.QSpinBox, "mprc_chat_remote_port_spin"),
            "chat_remote_code": page.findChild(QtWidgets.QSpinBox, "mprc_chat_remote_code_spin"),
            "chat_remote_regenerate_token": page.findChild(QtWidgets.QPushButton, "mprc_chat_remote_regenerate_token_button"),
            "chat_remote_status": page.findChild(QtWidgets.QLabel, "mprc_chat_remote_status_label"),
            "chat_voice_volume_label": page.findChild(QtWidgets.QLabel, "mprc_chat_voice_volume_label"),
            "chat_voice_volume": page.findChild(QtWidgets.QSlider, "mprc_chat_voice_volume_slider"),
            "chat_voice_volume_value": page.findChild(QtWidgets.QLabel, "mprc_chat_voice_volume_value"),
            "chat_voice_volume_popout": page.findChild(QtWidgets.QToolButton, "mprc_chat_voice_volume_popout_button"),
            "chat_runtime_splitter": page.findChild(QtWidgets.QSplitter, "mprc_story_runtime_splitter"),
            "chat_story_feed_box": page.findChild(QtWidgets.QGroupBox, "mprc_story_feed_box"),
            "chat_player_action_box": page.findChild(QtWidgets.QGroupBox, "mprc_player_action_box"),
            "chat_visual_prompt_debug_box": page.findChild(QtWidgets.QGroupBox, "mprc_visual_prompt_debug_box"),
            "chat_visual_prompt_debug": page.findChild(QtWidgets.QPlainTextEdit, "mprc_visual_prompt_debug_text"),
            "chat_send": page.findChild(QtWidgets.QPushButton, "mprc_chat_send_button"),
            "chat_speaker_label": page.findChild(QtWidgets.QLabel, "mprc_chat_speaker_label"),
            "chat_speaker": page.findChild(QtWidgets.QComboBox, "mprc_chat_speaker_combo"),
            "chat_intent_label": page.findChild(QtWidgets.QLabel, "mprc_chat_mode_label"),
            "chat_intent": page.findChild(QtWidgets.QComboBox, "mprc_chat_intent_combo"),
            "chat_transcript": page.findChild(QtWidgets.QTextBrowser, "mprc_chat_transcript"),
            "chat_input": page.findChild(QtWidgets.QPlainTextEdit, "mprc_chat_input"),
            "chat_use_ar": page.findChild(QtWidgets.QCheckBox, "mprc_chat_use_ar_checkbox"),
            "chat_visuals": page.findChild(QtWidgets.QCheckBox, "mprc_chat_visuals_checkbox"),
            "chat_status": page.findChild(QtWidgets.QLabel, "mprc_chat_status_label"),
            "chat_scene_state_box": page.findChild(QtWidgets.QGroupBox, "mprc_scene_state_box"),
            "chat_scene_state": page.findChild(QtWidgets.QLabel, "mprc_chat_scene_state_label"),
            "chat_active_speaker": page.findChild(QtWidgets.QLabel, "mprc_chat_active_speaker_label"),
            "chat_story_state_tabs": page.findChild(QtWidgets.QTabWidget, "mprc_story_state_tabs"),
            "chat_present_characters": page.findChild(QtWidgets.QListWidget, "mprc_chat_present_characters_list"),
            "chat_recent_events": page.findChild(QtWidgets.QListWidget, "mprc_chat_recent_events_list"),
            "chat_next_actions": page.findChild(QtWidgets.QListWidget, "mprc_chat_next_actions_list"),
            "chat_director_box": page.findChild(QtWidgets.QGroupBox, "mprc_director_box"),
            "chat_director_pacing_label": page.findChild(QtWidgets.QLabel, "mprc_director_pacing_label"),
            "chat_director_pacing": page.findChild(QtWidgets.QComboBox, "mprc_chat_director_pacing_combo"),
            "chat_director_tone_label": page.findChild(QtWidgets.QLabel, "mprc_director_tone_label"),
            "chat_director_tone": page.findChild(QtWidgets.QComboBox, "mprc_chat_director_tone_combo"),
            "chat_director_agency_label": page.findChild(QtWidgets.QLabel, "mprc_director_agency_label"),
            "chat_director_agency": page.findChild(QtWidgets.QComboBox, "mprc_chat_director_agency_combo"),
            "chat_director_choice_mode_label": page.findChild(QtWidgets.QLabel, "mprc_director_choice_mode_label"),
            "chat_director_choice_mode": page.findChild(QtWidgets.QComboBox, "mprc_chat_director_choice_mode_combo"),
            "chat_advance_scene": page.findChild(QtWidgets.QPushButton, "mprc_chat_advance_scene_button"),
            "chat_summarize": page.findChild(QtWidgets.QPushButton, "mprc_chat_summarize_button"),
            "chat_repair": page.findChild(QtWidgets.QPushButton, "mprc_chat_repair_button"),
        }
        controls["chat_input"] = self._replace_chat_play_input(controls.get("chat_input"))
        if controls.get("chat_float") is None:
            toolbar = page.findChild(QtWidgets.QHBoxLayout, "mprc_chat_play_toolbar")
            if toolbar is not None:
                float_button = QtWidgets.QPushButton("Float Play")
                float_button.setObjectName("mprc_chat_float_button")
                toolbar.insertWidget(min(4, toolbar.count()), float_button)
                controls["chat_float"] = float_button
        self._ensure_chat_play_voice_volume_controls(page, controls)
        self._ensure_chat_play_structured_output_controls(page, controls)
        self._ensure_chat_play_story_font_controls(page, controls)
        self._ensure_chat_play_remote_controls(page, controls)
        self._ensure_chat_play_chromecast_controls(page, controls)
        self._ensure_chat_play_buffer_race_controls(page, controls)
        self._controls.update({key: widget for key, widget in controls.items() if widget is not None})
        self._configure_chat_play_layout(page)

        intent = controls.get("chat_intent")
        if intent is not None:
            intent.addItems(["Auto", "Act", "Say", "Direct", "OOC"])
            intent.setCurrentText("Auto")
        pacing = controls.get("chat_director_pacing")
        if pacing is not None:
            pacing.addItems(list(AR_PACING_MODES))
            pacing.currentTextChanged.connect(self._on_mprc_chat_pacing_changed)
        tone = controls.get("chat_director_tone")
        if tone is not None:
            tone.addItems(["Keep current", "Cinematic", "Horror", "Mystery", "Adventure", "Quiet", "High tension"])
        agency = controls.get("chat_director_agency")
        if agency is not None:
            agency.addItems(["Guided", "Open", "Strict consequences"])
        choice_mode = controls.get("chat_director_choice_mode")
        if choice_mode is not None:
            choice_mode.addItem("Offer choices", "choices")
            choice_mode.addItem("Ask next move", "ask_next_move")
            choice_mode.currentIndexChanged.connect(lambda *_args: self._on_mprc_chat_choice_mode_changed())

        transcript = controls.get("chat_transcript")
        if transcript is not None:
            transcript.setHtml(
                "<div style='color:#9fb3c8;'>MPRC Play transcript is separate from normal chat.</div>"
            )
            self._apply_chat_play_story_font_size(self._chat_story_font_size(), transcript=transcript)
            self._restore_chat_play_feed_from_state()
        status = controls.get("chat_status")
        if status is not None:
            status.setProperty("muted", True)
        send = controls.get("chat_send")
        if send is not None:
            send.clicked.connect(self._on_mprc_chat_send_clicked)
        chat_input = controls.get("chat_input")
        if chat_input is not None and hasattr(chat_input, "sendRequested"):
            chat_input.sendRequested.connect(self._on_mprc_chat_send_clicked)
        clear = controls.get("chat_clear")
        if clear is not None:
            clear.clicked.connect(self._on_mprc_chat_clear_clicked)
        float_button = controls.get("chat_float")
        if float_button is not None:
            float_button.clicked.connect(self._toggle_chat_play_floating)
        export_structured = controls.get("chat_export_structured_output")
        if export_structured is not None:
            export_structured.clicked.connect(self._on_export_mprc_structured_output_clicked)
        structured_output = controls.get("chat_structured_output")
        if structured_output is not None:
            structured_output.toggled.connect(self._on_mprc_chat_structured_output_changed)
        structured_scope = controls.get("chat_structured_output_scope")
        if structured_scope is not None:
            structured_scope.currentIndexChanged.connect(lambda *_args: self._on_mprc_chat_structured_output_scope_changed())
        story_font_size = controls.get("chat_story_font_size")
        if story_font_size is not None:
            story_font_size.valueChanged.connect(lambda value: self._on_mprc_story_font_size_changed(value))
        remote_install = controls.get("chat_remote_install")
        if remote_install is not None:
            remote_install.clicked.connect(self._on_mprc_remote_install_clicked)
        remote_enabled = controls.get("chat_remote_enabled")
        if remote_enabled is not None:
            remote_enabled.toggled.connect(self._on_mprc_remote_enabled_changed)
        remote_host = controls.get("chat_remote_host")
        if remote_host is not None:
            remote_host.editingFinished.connect(self._on_mprc_remote_endpoint_changed)
        remote_port = controls.get("chat_remote_port")
        if remote_port is not None:
            remote_port.valueChanged.connect(lambda *_args: self._on_mprc_remote_endpoint_changed())
        remote_code = controls.get("chat_remote_code")
        if remote_code is not None:
            remote_code.valueChanged.connect(lambda *_args: self._on_mprc_remote_code_changed())
        remote_regen = controls.get("chat_remote_regenerate_token")
        if remote_regen is not None:
            remote_regen.clicked.connect(self._on_mprc_remote_regenerate_token)
        cast_refresh = controls.get("chat_chromecast_refresh")
        if cast_refresh is not None:
            cast_refresh.clicked.connect(self._on_mprc_chromecast_refresh_clicked)
        cast_install = controls.get("chat_chromecast_install")
        if cast_install is not None:
            cast_install.clicked.connect(self._on_mprc_chromecast_install_clicked)
        cast_start = controls.get("chat_chromecast_start")
        if cast_start is not None:
            cast_start.clicked.connect(self._on_mprc_chromecast_start_clicked)
        cast_stop = controls.get("chat_chromecast_stop")
        if cast_stop is not None:
            cast_stop.clicked.connect(self._on_mprc_chromecast_stop_clicked)
        cast_device = controls.get("chat_chromecast_device")
        if cast_device is not None:
            cast_device.currentIndexChanged.connect(lambda *_args: self._on_mprc_chromecast_device_changed())
        volume_slider = controls.get("chat_voice_volume")
        if volume_slider is not None:
            volume_slider.valueChanged.connect(self._on_mprc_voice_volume_changed)
        volume_popout = controls.get("chat_voice_volume_popout")
        if volume_popout is not None:
            volume_popout.clicked.connect(self._show_mprc_voice_volume_popout)
        start = controls.get("chat_start")
        if start is not None:
            start.clicked.connect(self._on_mprc_chat_start_clicked)
        pause = controls.get("chat_pause")
        if pause is not None:
            pause.clicked.connect(self._on_mprc_chat_pause_clicked)
        restart = controls.get("chat_restart")
        if restart is not None:
            restart.clicked.connect(self._on_mprc_chat_restart_clicked)
        speaker = controls.get("chat_speaker")
        if speaker is not None:
            speaker.currentIndexChanged.connect(lambda *_args: self._on_mprc_chat_speaker_changed())
        visuals = controls.get("chat_visuals")
        if visuals is not None:
            visuals.toggled.connect(self._on_mprc_chat_visuals_changed)
        choices = controls.get("chat_next_actions")
        if choices is not None:
            choices.itemClicked.connect(lambda item: self._on_mprc_choice_selected(item, send=False))
            choices.itemDoubleClicked.connect(lambda item: self._on_mprc_choice_selected(item, send=True))
            choices.itemActivated.connect(lambda item: self._on_mprc_choice_selected(item, send=True))
        advance = controls.get("chat_advance_scene")
        if advance is not None:
            advance.clicked.connect(lambda: self._on_mprc_director_action("advance"))
        summarize = controls.get("chat_summarize")
        if summarize is not None:
            summarize.clicked.connect(lambda: self._on_mprc_director_action("summarize"))
        repair = controls.get("chat_repair")
        if repair is not None:
            repair.clicked.connect(lambda: self._on_mprc_director_action("repair"))
        self._sync_chat_play_story_font_controls()
        self._refresh_remote_controls()
        self._refresh_chromecast_controls()
        return page

    def _ensure_chat_play_structured_output_controls(self, page, controls: dict[str, Any]) -> None:
        toolbar = page.findChild(QtWidgets.QHBoxLayout, "mprc_chat_play_toolbar") if page is not None else None
        if toolbar is None:
            return
        button = controls.get("chat_export_structured_output")
        if button is None:
            button = QtWidgets.QPushButton("Export Structured LLM Output")
            button.setObjectName("mprc_chat_export_structured_output_button")
            button.setToolTip("Export the current MPRC cast as a strict JSON Schema for provider Structured Output.")
            insert_at = toolbar.count()
            float_button = controls.get("chat_float")
            if float_button is not None:
                for index in range(toolbar.count()):
                    item = toolbar.itemAt(index)
                    if item is not None and item.widget() is float_button:
                        insert_at = index + 1
                        break
            toolbar.insertWidget(insert_at, button)
            controls["chat_export_structured_output"] = button
        structured_toggle = controls.get("chat_structured_output")
        if structured_toggle is None:
            structured_toggle = QtWidgets.QCheckBox("Structured JSON")
            structured_toggle.setObjectName("mprc_chat_structured_output_checkbox")
            structured_toggle.setToolTip("Send the MPRC story JSON Schema only with MPRC Play chat requests.")
            insert_at = toolbar.count()
            if button is not None:
                for index in range(toolbar.count()):
                    item = toolbar.itemAt(index)
                    if item is not None and item.widget() is button:
                        insert_at = index + 1
                        break
            toolbar.insertWidget(insert_at, structured_toggle)
            controls["chat_structured_output"] = structured_toggle
        structured_scope = controls.get("chat_structured_output_scope")
        if structured_scope is None:
            structured_scope = QtWidgets.QComboBox()
            structured_scope.setObjectName("mprc_chat_structured_output_scope_combo")
            structured_scope.addItem("Every turn", "every_turn")
            structured_scope.addItem("First turn only", "first_turn")
            structured_scope.setToolTip("Choose when MPRC Play attaches the structured-output JSON Schema to chat requests.")
            insert_at = toolbar.count()
            if structured_toggle is not None:
                for index in range(toolbar.count()):
                    item = toolbar.itemAt(index)
                    if item is not None and item.widget() is structured_toggle:
                        insert_at = index + 1
                        break
            toolbar.insertWidget(insert_at, structured_scope)
            controls["chat_structured_output_scope"] = structured_scope

    def _ensure_chat_play_story_font_controls(self, page, controls: dict[str, Any]) -> None:
        toolbar = page.findChild(QtWidgets.QHBoxLayout, "mprc_chat_play_toolbar") if page is not None else None
        if toolbar is None:
            return
        label = controls.get("chat_story_font_size_label")
        if label is None:
            label = QtWidgets.QLabel("Story Font")
            label.setObjectName("mprc_chat_story_font_size_label")
            label.setToolTip("Font size for the MPRC Story Feed response window.")
            toolbar.addWidget(label)
            controls["chat_story_font_size_label"] = label
        spin = controls.get("chat_story_font_size")
        if spin is None:
            spin = QtWidgets.QSpinBox()
            spin.setObjectName("mprc_chat_story_font_size_spin")
            spin.setRange(9, 28)
            spin.setSuffix(" pt")
            spin.setMaximumWidth(82)
            spin.setToolTip("Set the font size used by the MPRC Story Feed response window.")
            toolbar.addWidget(spin)
            controls["chat_story_font_size"] = spin
        self._sync_chat_play_story_font_controls(spin=spin)

    def _ensure_chat_play_remote_controls(self, page, controls: dict[str, Any]) -> None:
        toolbar = page.findChild(QtWidgets.QHBoxLayout, "mprc_chat_play_toolbar") if page is not None else None
        if toolbar is None:
            return
        remote_install = controls.get("chat_remote_install")
        if remote_install is None:
            remote_install = QtWidgets.QPushButton("Install Remote")
            remote_install.setObjectName("mprc_chat_remote_install_button")
            remote_install.setToolTip("Install optional LAN Remote controls for the Android companion app. The server remains off until LAN Remote is enabled.")
            toolbar.addWidget(remote_install)
            controls["chat_remote_install"] = remote_install
        remote_enabled = controls.get("chat_remote_enabled")
        if remote_enabled is None:
            remote_enabled = QtWidgets.QCheckBox("LAN Remote")
            remote_enabled.setObjectName("mprc_chat_remote_enabled_checkbox")
            remote_enabled.setToolTip("Enable the local-network MPRC remote backend for the Android companion app.")
            toolbar.addWidget(remote_enabled)
            controls["chat_remote_enabled"] = remote_enabled
        remote_host = controls.get("chat_remote_host")
        if remote_host is None:
            remote_host = QtWidgets.QLineEdit()
            remote_host.setObjectName("mprc_chat_remote_host_input")
            remote_host.setPlaceholderText("0.0.0.0")
            remote_host.setMaximumWidth(95)
            remote_host.setToolTip("Remote bind host. 0.0.0.0 accepts LAN clients; requests are still limited to local-network addresses.")
            toolbar.addWidget(remote_host)
            controls["chat_remote_host"] = remote_host
        remote_port = controls.get("chat_remote_port")
        if remote_port is None:
            remote_port = QtWidgets.QSpinBox()
            remote_port.setObjectName("mprc_chat_remote_port_spin")
            remote_port.setRange(1, 65535)
            remote_port.setMaximumWidth(82)
            remote_port.setToolTip("Remote backend TCP port.")
            toolbar.addWidget(remote_port)
            controls["chat_remote_port"] = remote_port
        remote_code = controls.get("chat_remote_code")
        if remote_code is None:
            remote_code = QtWidgets.QSpinBox()
            remote_code.setObjectName("mprc_chat_remote_code_spin")
            remote_code.setRange(100000, 999999)
            remote_code.setMaximumWidth(92)
            remote_code.setToolTip("Six-digit pairing code for the Android remote app. You can type your own number.")
            toolbar.addWidget(remote_code)
            controls["chat_remote_code"] = remote_code
        remote_regen = controls.get("chat_remote_regenerate_token")
        if remote_regen is None:
            remote_regen = QtWidgets.QPushButton("Random Code")
            remote_regen.setObjectName("mprc_chat_remote_regenerate_token_button")
            remote_regen.setToolTip("Generate a new six-digit MPRC remote pairing code. Android clients must reconnect with the new code.")
            toolbar.addWidget(remote_regen)
            controls["chat_remote_regenerate_token"] = remote_regen
        else:
            remote_regen.setText("Random Code")
            remote_regen.setToolTip("Generate a new six-digit MPRC remote pairing code. Android clients must reconnect with the new code.")
        remote_status = controls.get("chat_remote_status")
        if remote_status is None:
            remote_status = QtWidgets.QLabel()
            remote_status.setObjectName("mprc_chat_remote_status_label")
            remote_status.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            remote_status.setToolTip("MPRC remote LAN URL, pairing code, and client status.")
            remote_status.setMinimumWidth(220)
            toolbar.addWidget(remote_status)
            controls["chat_remote_status"] = remote_status

    def _ensure_chat_play_chromecast_controls(self, page, controls: dict[str, Any]) -> None:
        toolbar = page.findChild(QtWidgets.QHBoxLayout, "mprc_chat_play_toolbar") if page is not None else None
        if toolbar is None:
            return
        label = controls.get("chat_chromecast_label")
        if label is None:
            label = QtWidgets.QLabel("Cast")
            label.setObjectName("mprc_chat_chromecast_label")
            label.setToolTip("Backend-controlled Chromecast output for the MPRC Story Cast page.")
            toolbar.addWidget(label)
            controls["chat_chromecast_label"] = label
        device = controls.get("chat_chromecast_device")
        if device is None:
            device = QtWidgets.QComboBox()
            device.setObjectName("mprc_chat_chromecast_device_combo")
            device.setMinimumWidth(130)
            device.setMaximumWidth(220)
            device.setToolTip("Chromecast device used for MPRC story audio and Visual Reply display.")
            toolbar.addWidget(device)
            controls["chat_chromecast_device"] = device
        refresh = controls.get("chat_chromecast_refresh")
        if refresh is None:
            refresh = QtWidgets.QPushButton("Find Cast")
            refresh.setObjectName("mprc_chat_chromecast_refresh_button")
            refresh.setToolTip("Discover Chromecast devices on the LAN.")
            toolbar.addWidget(refresh)
            controls["chat_chromecast_refresh"] = refresh
        install = controls.get("chat_chromecast_install")
        if install is None:
            install = QtWidgets.QPushButton("Install Cast")
            install.setObjectName("mprc_chat_chromecast_install_button")
            install.setToolTip("Install optional Chromecast Python dependencies in the active environment.")
            toolbar.addWidget(install)
            controls["chat_chromecast_install"] = install
        start = controls.get("chat_chromecast_start")
        if start is None:
            start = QtWidgets.QPushButton("Start Cast")
            start.setObjectName("mprc_chat_chromecast_start_button")
            start.setToolTip("Open the MPRC Story Cast page on the selected Chromecast.")
            toolbar.addWidget(start)
            controls["chat_chromecast_start"] = start
        stop = controls.get("chat_chromecast_stop")
        if stop is None:
            stop = QtWidgets.QPushButton("Stop Cast")
            stop.setObjectName("mprc_chat_chromecast_stop_button")
            stop.setToolTip("Stop MPRC Chromecast playback and close the Story Cast stream server.")
            toolbar.addWidget(stop)
            controls["chat_chromecast_stop"] = stop
        status = controls.get("chat_chromecast_status")
        if status is None:
            status = QtWidgets.QLabel()
            status.setObjectName("mprc_chat_chromecast_status_label")
            status.setMinimumWidth(170)
            status.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            status.setToolTip("MPRC Chromecast status.")
            toolbar.addWidget(status)
            controls["chat_chromecast_status"] = status

    def _ensure_chat_play_voice_volume_controls(self, page, controls: dict[str, Any]) -> None:
        toolbar = page.findChild(QtWidgets.QHBoxLayout, "mprc_chat_play_toolbar") if page is not None else None
        if toolbar is None:
            return
        slider = controls.get("chat_voice_volume")
        label = controls.get("chat_voice_volume_label")
        value = controls.get("chat_voice_volume_value")
        popout = controls.get("chat_voice_volume_popout")
        if popout is None:
            popout = QtWidgets.QToolButton()
            popout.setObjectName("mprc_chat_voice_volume_popout_button")
            popout.setText("Set")
            popout.setToolTip("Open a wider voice-volume slider.")
            popout.setAutoRaise(False)
            popout.setMinimumWidth(38)
            controls["chat_voice_volume_popout"] = popout
        if slider is not None and label is not None and value is not None:
            self._sync_chat_play_voice_volume_controls(slider=slider, value_label=value)
            if popout.parentWidget() is None:
                insert_at = toolbar.count()
                for index in range(toolbar.count()):
                    item = toolbar.itemAt(index)
                    if item is not None and item.widget() is value:
                        insert_at = index + 1
                        break
                toolbar.insertWidget(insert_at, popout)
            return

        label = QtWidgets.QLabel("Voice")
        label.setObjectName("mprc_chat_voice_volume_label")
        label.setToolTip("Volume for MPRC-routed story voice in the Play tab.")
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setObjectName("mprc_chat_voice_volume_slider")
        slider.setRange(0, 100)
        slider.setMinimumWidth(96)
        slider.setMaximumWidth(150)
        slider.setToolTip("Set the volume for addon-routed Play voice. This does not change AudioFX/background sound volume.")
        value = QtWidgets.QLabel("")
        value.setObjectName("mprc_chat_voice_volume_value")
        value.setMinimumWidth(42)
        value.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        value.setToolTip("Current MPRC Play voice volume percentage.")
        self._sync_chat_play_voice_volume_controls(slider=slider, value_label=value)

        insert_at = toolbar.count()
        float_button = controls.get("chat_float")
        if float_button is not None:
            for index in range(toolbar.count()):
                item = toolbar.itemAt(index)
                if item is not None and item.widget() is float_button:
                    insert_at = index + 1
                    break
        toolbar.insertWidget(insert_at, label)
        toolbar.insertWidget(insert_at + 1, slider)
        toolbar.insertWidget(insert_at + 2, value)
        toolbar.insertWidget(insert_at + 3, popout)
        controls["chat_voice_volume_label"] = label
        controls["chat_voice_volume"] = slider
        controls["chat_voice_volume_value"] = value

    def _ensure_chat_play_buffer_race_controls(self, page, controls: dict[str, Any]) -> None:
        if page is None:
            return
        box = page.findChild(QtWidgets.QGroupBox, "mprc_buffer_race_box")
        if box is not None:
            controls["chat_buffer_race_box"] = box
            controls["chat_buffer_race_summary"] = page.findChild(QtWidgets.QLabel, "mprc_buffer_race_summary")
            controls["chat_buffer_race_render"] = page.findChild(QtWidgets.QProgressBar, "mprc_buffer_race_render_bar")
            controls["chat_buffer_race_playback"] = page.findChild(QtWidgets.QProgressBar, "mprc_buffer_race_playback_bar")
            return

        box = QtWidgets.QGroupBox("Buffer Race", page)
        box.setObjectName("mprc_buffer_race_box")
        box.setToolTip("Shows whether story/render work or TTS/playback work is currently waiting or running.")
        box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        summary = QtWidgets.QLabel("Idle: render and playback buffers are clear.")
        summary.setObjectName("mprc_buffer_race_summary")
        summary.setProperty("muted", True)
        summary.setWordWrap(True)

        render_bar = self._build_chat_play_buffer_bar("mprc_buffer_race_render_bar")
        playback_bar = self._build_chat_play_buffer_bar("mprc_buffer_race_playback_bar")
        render_bar.setFormat("Render Ready: idle")
        playback_bar.setFormat("Preview / Playback: idle")

        layout.addWidget(summary)
        layout.addWidget(render_bar)
        layout.addWidget(playback_bar)
        controls.update({
            "chat_buffer_race_box": box,
            "chat_buffer_race_summary": summary,
            "chat_buffer_race_render": render_bar,
            "chat_buffer_race_playback": playback_bar,
        })

    def _build_chat_play_buffer_bar(self, object_name: str):
        bar = QtWidgets.QProgressBar()
        bar.setObjectName(object_name)
        bar.setRange(0, 100)
        bar.setValue(100)
        bar.setTextVisible(True)
        bar.setMinimumHeight(18)
        bar.setMaximumHeight(20)
        bar.setStyleSheet(
            """
            QProgressBar {
                border: 1px solid #24384f;
                border-radius: 5px;
                background: #08111b;
                color: #dbeafe;
                text-align: center;
                font-weight: 600;
            }
            QProgressBar::chunk {
                border-radius: 4px;
                background: #22c55e;
            }
            """
        )
        return bar

    def _configure_chat_play_toolbar_rows(self, page) -> None:
        if page is None or page.findChild(QtWidgets.QWidget, "mprc_chat_play_toolbar_panel") is not None:
            return
        root_layout = page.layout()
        toolbar = page.findChild(QtWidgets.QHBoxLayout, "mprc_chat_play_toolbar")
        if root_layout is None or toolbar is None:
            return

        toolbar_index = -1
        for index in range(root_layout.count()):
            item = root_layout.itemAt(index)
            if item is not None and item.layout() is toolbar:
                toolbar_index = index
                break
        if toolbar_index < 0:
            return

        old_widgets = []
        while toolbar.count():
            item = toolbar.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                old_widgets.append(widget)

        panel = QtWidgets.QFrame(page)
        panel.setObjectName("mprc_chat_play_toolbar_panel")
        panel.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        panel.setMaximumWidth(980)
        panel.setStyleSheet(
            """
            QFrame#mprc_chat_play_toolbar_panel {
                background: #101923;
                border: 1px solid #273342;
                border-radius: 8px;
            }
            QFrame#mprc_chat_play_toolbar_advanced {
                background: #0b121a;
                border: 1px solid #1f3042;
                border-radius: 6px;
            }
            QFrame#mprc_chat_play_toolbar_voice_focus_row {
                background: #0b121a;
                border: 1px solid #1f3042;
                border-radius: 6px;
            }
            QFrame[advancedCard="true"] {
                background: #101923;
                border: 1px solid #2b4058;
                border-radius: 7px;
            }
            QLabel[advancedCardTitle="true"] {
                color: #dbeafe;
                font-weight: 800;
                padding-bottom: 2px;
            }
            QLabel[advancedFieldLabel="true"] {
                color: #9fb3c8;
                font-weight: 700;
            }
            QToolButton#mprc_chat_play_toolbar_advanced_toggle {
                background: #122033;
                border: 1px solid #36506d;
                border-radius: 6px;
                color: #dbeafe;
                font-weight: 700;
                min-height: 26px;
                padding: 3px 10px;
            }
            QToolButton#mprc_chat_play_toolbar_advanced_toggle:checked {
                border-color: #39d98a;
                color: #f4f7fb;
            }
            """
        )
        rows_layout = QtWidgets.QVBoxLayout(panel)
        rows_layout.setObjectName("mprc_chat_play_toolbar_rows")
        rows_layout.setContentsMargins(10, 8, 10, 8)
        rows_layout.setSpacing(6)

        actions_row = QtWidgets.QHBoxLayout()
        actions_row.setObjectName("mprc_chat_play_toolbar_actions_row")
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(8)
        rows_layout.addLayout(actions_row)

        voice_focus_frame = QtWidgets.QFrame(panel)
        voice_focus_frame.setObjectName("mprc_chat_play_toolbar_voice_focus_row")
        voice_focus_frame.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        voice_focus_row = QtWidgets.QHBoxLayout(voice_focus_frame)
        voice_focus_row.setObjectName("mprc_chat_play_toolbar_voice_focus_inner_row")
        voice_focus_row.setContentsMargins(10, 7, 10, 7)
        voice_focus_row.setSpacing(8)
        rows_layout.addWidget(voice_focus_frame)

        advanced = QtWidgets.QFrame(panel)
        advanced.setObjectName("mprc_chat_play_toolbar_advanced")
        advanced.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        advanced_layout = QtWidgets.QVBoxLayout(advanced)
        advanced_layout.setContentsMargins(8, 7, 8, 8)
        advanced_layout.setSpacing(8)
        rows_layout.addWidget(advanced)

        advanced_toggle = QtWidgets.QToolButton(panel)
        advanced_toggle.setObjectName("mprc_chat_play_toolbar_advanced_toggle")
        advanced_toggle.setCheckable(True)
        advanced_toggle.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        advanced_toggle.setAutoRaise(False)
        advanced_toggle.setToolTip("Show or hide the extra Play controls: structured output, LAN remote, and Chromecast.")

        root_layout.takeAt(toolbar_index)
        root_layout.insertWidget(toolbar_index, panel)

        widget_map: dict[str, QtWidgets.QWidget] = {}
        for widget in old_widgets:
            name = str(widget.objectName() or "")
            if name:
                widget_map[name] = widget
        for widget in self._controls.values():
            if isinstance(widget, QtWidgets.QWidget):
                name = str(widget.objectName() or "")
                if name and name not in widget_map:
                    widget_map[name] = widget

        moved: set[int] = set()
        card_widgets: dict[str, QtWidgets.QFrame] = {}
        card_layouts: dict[str, QtWidgets.QVBoxLayout] = {}

        def make_card(key: str, title: str) -> QtWidgets.QVBoxLayout:
            card = QtWidgets.QFrame(advanced)
            card.setObjectName(f"mprc_chat_play_advanced_{key}_card")
            card.setProperty("advancedCard", True)
            card.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
            layout = QtWidgets.QVBoxLayout(card)
            layout.setContentsMargins(10, 8, 10, 10)
            layout.setSpacing(6)
            title_label = QtWidgets.QLabel(title)
            title_label.setObjectName(f"mprc_chat_play_advanced_{key}_title")
            title_label.setProperty("advancedCardTitle", True)
            layout.addWidget(title_label)
            advanced_layout.addWidget(card)
            card_widgets[key] = card
            card_layouts[key] = layout
            return layout

        def make_row(card_key: str, row_key: str) -> QtWidgets.QHBoxLayout:
            layout = card_layouts[card_key]
            row = QtWidgets.QHBoxLayout()
            row.setObjectName(f"mprc_chat_play_advanced_{card_key}_{row_key}_row")
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            layout.addLayout(row)
            return row

        def make_field_label(text: str) -> QtWidgets.QLabel:
            label = QtWidgets.QLabel(text)
            label.setProperty("advancedFieldLabel", True)
            return label

        def add(name: str, row: QtWidgets.QHBoxLayout, stretch: int = 0) -> None:
            widget = widget_map.get(name)
            if widget is None or id(widget) in moved:
                return
            row.addWidget(widget, stretch)
            moved.add(id(widget))

        def add_label(text: str, row: QtWidgets.QHBoxLayout, object_name: str = "") -> QtWidgets.QLabel:
            label = make_field_label(text)
            if object_name:
                label.setObjectName(object_name)
                self._controls[object_name] = label
            row.addWidget(label)
            return label

        def make_status_label_compact(name: str) -> None:
            widget = widget_map.get(name)
            if isinstance(widget, QtWidgets.QLabel):
                widget.setWordWrap(True)
                widget.setMinimumWidth(0)
                widget.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)

        for name in (
            "mprc_chat_start_button",
            "mprc_chat_pause_button",
            "mprc_chat_restart_button",
            "mprc_chat_clear_button",
            "mprc_chat_float_button",
        ):
            add(name, actions_row)
        actions_row.addWidget(advanced_toggle)
        actions_row.addStretch(1)

        voice_slider = widget_map.get("mprc_chat_voice_volume_slider")
        if isinstance(voice_slider, QtWidgets.QSlider):
            voice_slider.setMinimumWidth(96)
            voice_slider.setMaximumWidth(150)
            voice_slider.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        intent_combo = widget_map.get("mprc_chat_intent_combo")
        if isinstance(intent_combo, QtWidgets.QComboBox):
            intent_combo.setMinimumWidth(76)
            intent_combo.setMaximumWidth(120)
            intent_combo.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        focus_combo = widget_map.get("mprc_chat_speaker_combo")
        if isinstance(focus_combo, QtWidgets.QComboBox):
            focus_combo.setMinimumWidth(220)
            focus_combo.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        for label_name in ("mprc_chat_voice_volume_label", "mprc_chat_mode_label", "mprc_chat_speaker_label"):
            label_widget = widget_map.get(label_name)
            if isinstance(label_widget, QtWidgets.QLabel):
                label_widget.setProperty("advancedFieldLabel", True)
        add("mprc_chat_voice_volume_label", voice_focus_row)
        add("mprc_chat_voice_volume_slider", voice_focus_row)
        add("mprc_chat_voice_volume_value", voice_focus_row)
        add("mprc_chat_voice_volume_popout_button", voice_focus_row)
        voice_focus_row.addSpacing(8)
        add("mprc_chat_mode_label", voice_focus_row)
        add("mprc_chat_intent_combo", voice_focus_row)
        voice_focus_row.addSpacing(8)
        add("mprc_chat_speaker_label", voice_focus_row)
        add("mprc_chat_speaker_combo", voice_focus_row, 1)

        make_card("structured", "Structured Output")
        structured_actions_row = make_row("structured", "actions")
        add("mprc_chat_export_structured_output_button", structured_actions_row)
        structured_actions_row.addStretch(1)
        structured_options_row = make_row("structured", "options")
        add("mprc_chat_structured_output_checkbox", structured_options_row)
        add("mprc_chat_structured_output_scope_combo", structured_options_row)
        structured_options_row.addStretch(1)
        font_row = make_row("structured", "font")
        add("mprc_chat_story_font_size_label", font_row)
        add("mprc_chat_story_font_size_spin", font_row)
        font_row.addStretch(1)

        make_card("remote", "LAN Remote")
        remote_actions_row = make_row("remote", "actions")
        add("mprc_chat_remote_install_button", remote_actions_row)
        add("mprc_chat_remote_enabled_checkbox", remote_actions_row)
        add("mprc_chat_remote_regenerate_token_button", remote_actions_row)
        remote_actions_row.addStretch(1)
        remote_endpoint_row = make_row("remote", "endpoint")
        add_label("Host", remote_endpoint_row, "chat_remote_host_label")
        add("mprc_chat_remote_host_input", remote_endpoint_row)
        add_label("Port", remote_endpoint_row, "chat_remote_port_label")
        add("mprc_chat_remote_port_spin", remote_endpoint_row)
        add_label("Code", remote_endpoint_row, "chat_remote_code_label")
        add("mprc_chat_remote_code_spin", remote_endpoint_row)
        remote_endpoint_row.addStretch(1)
        make_status_label_compact("mprc_chat_remote_status_label")
        remote_status_row = make_row("remote", "status")
        add("mprc_chat_remote_status_label", remote_status_row, 1)

        make_card("cast", "Chromecast")
        cast_device_row = make_row("cast", "device")
        cast_label = widget_map.get("mprc_chat_chromecast_label")
        if isinstance(cast_label, QtWidgets.QLabel):
            cast_label.setText("Device")
        add("mprc_chat_chromecast_label", cast_device_row)
        add("mprc_chat_chromecast_device_combo", cast_device_row, 1)
        add("mprc_chat_chromecast_refresh_button", cast_device_row)
        add("mprc_chat_chromecast_install_button", cast_device_row)
        cast_action_row = make_row("cast", "actions")
        add("mprc_chat_chromecast_start_button", cast_action_row)
        add("mprc_chat_chromecast_stop_button", cast_action_row)
        cast_action_row.addStretch(1)
        make_status_label_compact("mprc_chat_chromecast_status_label")
        cast_status_row = make_row("cast", "status")
        add("mprc_chat_chromecast_status_label", cast_status_row, 1)

        for widget in old_widgets:
            if id(widget) not in moved:
                cast_status_row.addWidget(widget)
                moved.add(id(widget))
        advanced_layout.addStretch(1)

        self._configure_chat_play_toolbar_advanced_toggle(advanced_toggle, advanced)

        self._controls.update({
            "chat_toolbar_panel": panel,
            "chat_toolbar_actions_row": actions_row,
            "chat_toolbar_voice_focus_row": voice_focus_frame,
            "chat_toolbar_structured_card": card_widgets.get("structured"),
            "chat_toolbar_remote_card": card_widgets.get("remote"),
            "chat_toolbar_cast_card": card_widgets.get("cast"),
            "chat_toolbar_advanced": advanced,
            "chat_toolbar_advanced_toggle": advanced_toggle,
        })

    def _configure_chat_play_toolbar_advanced_toggle(self, toggle, advanced) -> None:
        expanded = bool(self.settings.get("chat_toolbar_advanced_expanded", True))
        self._apply_chat_play_toolbar_advanced_state(toggle, advanced, expanded)
        toggle.clicked.connect(lambda checked: self._on_chat_play_toolbar_advanced_toggled(toggle, advanced, bool(checked)))

    def _on_chat_play_toolbar_advanced_toggled(self, toggle, advanced, expanded: bool) -> None:
        self.settings["chat_toolbar_advanced_expanded"] = bool(expanded)
        self.storage.save_settings(self.settings)
        self._apply_chat_play_toolbar_advanced_state(toggle, advanced, bool(expanded))

    def _apply_chat_play_toolbar_advanced_state(self, toggle, advanced, expanded: bool) -> None:
        if advanced is not None:
            advanced.setVisible(bool(expanded))
            advanced.setMaximumHeight(16777215 if expanded else 0)
        if toggle is not None:
            toggle.blockSignals(True)
            toggle.setChecked(bool(expanded))
            toggle.blockSignals(False)
            toggle.setText("Advanced ^" if expanded else "Advanced v")

    def _replace_chat_play_input(self, widget):
        if widget is None:
            return None
        try:
            from ui.runtime.spellcheck import ChatMessageInput
        except Exception:
            return widget
        if isinstance(widget, ChatMessageInput):
            return widget
        parent = widget.parentWidget()
        if parent is None:
            return widget
        layout = self._find_layout_containing_widget(parent.layout(), widget)
        if layout is None:
            return widget
        replacement = ChatMessageInput(parent)
        replacement.setObjectName(str(widget.objectName() or "mprc_chat_input"))
        replacement.setPlaceholderText(str(getattr(widget, "placeholderText", lambda: "")() or "Type a player action..."))
        replacement.setToolTip(str(widget.toolTip() or "Type the next player action. Enter sends; Shift+Enter inserts a newline."))
        replacement.setEnabled(widget.isEnabled())
        replacement.setHidden(widget.isHidden())
        replacement.setMinimumWidth(widget.minimumWidth())
        replacement.setMinimumHeight(max(72, int(widget.minimumHeight() or 0)))
        maximum_height = int(widget.maximumHeight() or 0)
        if 0 < maximum_height < 16777215:
            replacement.setMaximumHeight(max(maximum_height, replacement.minimumHeight()))
        else:
            replacement.setMaximumHeight(130)
        try:
            replacement.textChanged.disconnect(replacement._sync_height_to_content)
        except Exception:
            pass
        replacement.setStyleSheet(str(widget.styleSheet() or ""))
        layout.replaceWidget(widget, replacement)
        widget.setObjectName(f"{replacement.objectName()}_legacy")
        widget.hide()
        widget.deleteLater()
        return replacement

    def _find_layout_containing_widget(self, layout, widget):
        if layout is None or widget is None:
            return None
        for index in range(layout.count()):
            item = layout.itemAt(index)
            if item is None:
                continue
            if item.widget() is widget:
                return layout
            nested = item.layout()
            if nested is not None:
                found = self._find_layout_containing_widget(nested, widget)
                if found is not None:
                    return found
        return None

    def _configure_chat_play_layout(self, page) -> None:
        def widget(name: str):
            try:
                return page.findChild(QtWidgets.QWidget, name)
            except Exception:
                return None

        splitter_style = """
        QSplitter::handle {
            background: transparent;
            border: 0;
        }
        QSplitter::handle:hover {
            background: transparent;
        }
        """

        page.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        page.setMinimumHeight(920)
        page.setMaximumHeight(16777215)

        root_layout = page.layout()
        if root_layout is not None:
            root_layout.setSizeConstraint(QtWidgets.QLayout.SetDefaultConstraint)
            root_layout.setAlignment(QtCore.Qt.Alignment())
            for index in range(root_layout.count()):
                try:
                    root_layout.setStretch(index, 1 if index == 1 else 0)
                except Exception:
                    pass

        self._configure_chat_play_toolbar_rows(page)

        splitter = widget("mprc_story_runtime_splitter")
        if splitter is not None:
            splitter.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
            splitter.setMinimumHeight(500)
            splitter.setMaximumHeight(16777215)
            splitter.setHandleWidth(6)
            splitter.setStyleSheet(splitter_style)
            if hasattr(splitter, "setStretchFactor"):
                splitter.setStretchFactor(0, 3)
                splitter.setStretchFactor(1, 2)

        story_feed = widget("mprc_story_feed_box")
        if story_feed is not None:
            story_feed.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
            story_feed.setMinimumHeight(180)
            story_feed.setMaximumHeight(16777215)
        transcript = widget("mprc_chat_transcript")
        if transcript is not None:
            transcript.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
            transcript.setMinimumHeight(130)
            transcript.setMaximumHeight(16777215)

        main_panel = widget("mprc_story_main_panel")
        main_layout = main_panel.layout() if main_panel is not None else None
        if main_layout is not None:
            main_layout.setAlignment(QtCore.Qt.Alignment())
            main_splitter = widget("mprc_story_main_vertical_splitter")
            if main_splitter is None:
                buffer_box = widget("mprc_buffer_race_box")
                story_box = widget("mprc_story_feed_box")
                action_box = widget("mprc_player_action_box")
                visual_debug_box = widget("mprc_visual_prompt_debug_box")
                if story_box is not None and action_box is not None:
                    while main_layout.count():
                        main_layout.takeAt(0)
                    main_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical, main_panel)
                    main_splitter.setObjectName("mprc_story_main_vertical_splitter")
                    if buffer_box is not None:
                        main_splitter.addWidget(buffer_box)
                    main_splitter.addWidget(story_box)
                    main_splitter.addWidget(action_box)
                    if visual_debug_box is not None:
                        main_splitter.addWidget(visual_debug_box)
                    main_splitter.setChildrenCollapsible(False)
                    main_splitter.setHandleWidth(6)
                    main_splitter.setStyleSheet(splitter_style)
                    offset = 1 if buffer_box is not None else 0
                    if buffer_box is not None:
                        main_splitter.setStretchFactor(0, 0)
                    main_splitter.setStretchFactor(offset, 1)
                    main_splitter.setStretchFactor(offset + 1, 0)
                    if visual_debug_box is not None:
                        main_splitter.setStretchFactor(offset + 2, 0)
                        main_splitter.setSizes(([78] if buffer_box is not None else []) + [340, 150, 150])
                    else:
                        main_splitter.setSizes(([78] if buffer_box is not None else []) + [360, 150])
                    main_layout.addWidget(main_splitter, 1)
            if main_splitter is not None:
                main_splitter.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
            for index in range(main_layout.count()):
                try:
                    main_layout.setStretch(index, 1)
                except Exception:
                    pass

        flexible_heights = {
            "mprc_buffer_race_box": (58, 92),
            "mprc_player_action_box": (120, 220),
            "mprc_visual_prompt_debug_box": (120, 320),
            "mprc_scene_state_box": (105, 230),
            "mprc_story_state_tabs_box": (210, 16777215),
            "mprc_story_state_tabs": (190, 16777215),
            "mprc_director_box": (190, 260),
            "mprc_story_engine_box": (220, 420),
            "mprc_story_engine_tabs": (180, 16777215),
        }
        for name, (min_height, max_height) in flexible_heights.items():
            item = widget(name)
            if item is None:
                continue
            item.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
            item.setMinimumHeight(min_height)
            item.setMaximumHeight(max_height)

        for name, max_height in (
            ("mprc_chat_input", 130),
            ("mprc_visual_prompt_debug_text", 16777215),
            ("mprc_chat_present_characters_list", 16777215),
            ("mprc_chat_recent_events_list", 16777215),
            ("mprc_chat_next_actions_list", 16777215),
        ):
            item = widget(name)
            if item is not None:
                item.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
                item.setMaximumHeight(max_height)

        state_tabs = widget("mprc_story_state_tabs")
        if isinstance(state_tabs, QtWidgets.QTabWidget):
            state_tab_specs = (
                (0, "Cast", "cast", "#60a5fa"),
                (1, "Events", "events", "#facc15"),
                (2, "Choices", "choices", "#fb7185"),
            )
            for tab_index, tab_title, icon_key, icon_color in state_tab_specs:
                if tab_index < state_tabs.count():
                    state_tabs.setTabText(tab_index, "")
                    state_tabs.setTabIcon(tab_index, QtGui.QIcon())
                    state_tabs.setTabToolTip(tab_index, tab_title)
                    state_tabs.tabBar().setTabButton(
                        tab_index,
                        QtWidgets.QTabBar.LeftSide,
                        self._story_state_tab_button(tab_title, icon_key, icon_color),
                    )
            state_tabs.setStyleSheet(self._story_state_tab_stylesheet())

        for name in ("mprc_story_state_sidebar",):
            panel = widget(name)
            layout = panel.layout() if panel is not None else None
            if layout is None:
                continue
            layout.setAlignment(QtCore.Qt.Alignment())
            sidebar_splitter = widget("mprc_story_state_vertical_splitter")
            if sidebar_splitter is None:
                scene_box = widget("mprc_scene_state_box")
                tabs_box = widget("mprc_story_state_tabs")
                director_box = widget("mprc_director_box")
                engine_box = widget("mprc_story_engine_box")
                if engine_box is None:
                    engine_box = self._build_chat_play_story_engine_box(panel)
                if scene_box is not None and tabs_box is not None and director_box is not None:
                    while layout.count():
                        layout.takeAt(0)
                    tabs_container = widget("mprc_story_state_tabs_box")
                    if tabs_container is None:
                        tabs_container = QtWidgets.QGroupBox("Story State", panel)
                        tabs_container.setObjectName("mprc_story_state_tabs_box")
                        tabs_container.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
                        tabs_container.setMinimumHeight(210)
                        tabs_container.setMaximumHeight(16777215)
                        tabs_layout = QtWidgets.QVBoxLayout(tabs_container)
                        tabs_layout.setContentsMargins(8, 8, 8, 8)
                        tabs_layout.setSpacing(4)
                        tabs_box.setParent(tabs_container)
                        tabs_layout.addWidget(tabs_box)
                        self._controls["chat_story_state_tabs_box"] = tabs_container
                    sidebar_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical, panel)
                    sidebar_splitter.setObjectName("mprc_story_state_vertical_splitter")
                    sidebar_splitter.addWidget(scene_box)
                    sidebar_splitter.addWidget(tabs_container)
                    sidebar_splitter.addWidget(director_box)
                    if engine_box is not None:
                        sidebar_splitter.addWidget(engine_box)
                    sidebar_splitter.setChildrenCollapsible(False)
                    sidebar_splitter.setHandleWidth(6)
                    sidebar_splitter.setStyleSheet(splitter_style)
                    sidebar_splitter.setStretchFactor(0, 0)
                    sidebar_splitter.setStretchFactor(1, 1)
                    sidebar_splitter.setStretchFactor(2, 0)
                    if engine_box is not None:
                        sidebar_splitter.setStretchFactor(3, 1)
                        sidebar_splitter.setSizes([130, 210, 180, 240])
                    else:
                        sidebar_splitter.setSizes([130, 230, 190])
                    layout.addWidget(sidebar_splitter, 1)
            if sidebar_splitter is not None:
                sidebar_splitter.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
            for index in range(layout.count()):
                try:
                    layout.setStretch(index, 1)
                except Exception:
                    pass

        status = widget("mprc_chat_status_label")
        if status is not None:
            status.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
            status.setMaximumHeight(30)
        self._refresh_chat_play_buffer_race()

    def _chat_play_is_floating(self) -> bool:
        window = getattr(self, "_chat_play_floating_window", None)
        return window is not None

    def _set_chat_play_float_button_text(self) -> None:
        button = self._controls.get("chat_float")
        if button is None or not hasattr(button, "setText"):
            return
        if self._chat_play_is_floating():
            button.setText("Dock Play")
            button.setToolTip("Return the MPRC Play surface to the addon tab.")
        else:
            button.setText("Float Play")
            button.setToolTip("Move the MPRC Play surface into a floating window.")

    def _build_chat_play_placeholder(self):
        placeholder = QtWidgets.QWidget()
        placeholder.setObjectName("mprc_chat_play_floating_placeholder")
        layout = QtWidgets.QVBoxLayout(placeholder)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        message = QtWidgets.QLabel("MPRC Play is floating in its own window.")
        message.setObjectName("mprc_chat_play_floating_placeholder_label")
        message.setAlignment(QtCore.Qt.AlignCenter)
        message.setWordWrap(True)
        dock_button = QtWidgets.QPushButton("Dock Play")
        dock_button.setObjectName("mprc_chat_play_dock_placeholder_button")
        dock_button.clicked.connect(self._dock_chat_play_tab)
        layout.addStretch(1)
        layout.addWidget(message, 0, QtCore.Qt.AlignCenter)
        layout.addWidget(dock_button, 0, QtCore.Qt.AlignCenter)
        layout.addStretch(1)
        return placeholder

    def _toggle_chat_play_floating(self):
        if self._chat_play_is_floating():
            self._dock_chat_play_tab()
        else:
            self._float_chat_play_tab()

    def _float_chat_play_tab(self):
        if self.is_shutdown():
            return
        page = getattr(self, "_chat_play_page", None)
        stack = self._controls.get("tab_stack")
        if page is None or stack is None:
            return
        existing = getattr(self, "_chat_play_floating_window", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            self._set_chat_play_float_button_text()
            return
        index = stack.indexOf(page)
        if index < 0:
            index = int(getattr(self, "_chat_play_stack_index", 0) or 0)
        self._chat_play_stack_index = max(0, index)
        placeholder = self._build_chat_play_placeholder()
        stack.removeWidget(page)
        stack.insertWidget(self._chat_play_stack_index, placeholder)
        stack.setCurrentIndex(self._chat_play_stack_index)
        self._chat_play_placeholder = placeholder

        parent_window = None
        try:
            parent_window = self._widget.window() if self._widget is not None else None
        except Exception:
            parent_window = None
        window = _MprcFloatingPlayWindow(self, parent_window)
        style_source = self._controls.get("root") or self._widget
        if style_source is not None:
            try:
                window.setStyleSheet(style_source.styleSheet())
            except Exception:
                pass
        layout = QtWidgets.QVBoxLayout(window)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(0)
        layout.addWidget(page)
        page.setVisible(True)
        page.show()
        page.updateGeometry()
        self._chat_play_floating_window = window
        self._set_chat_play_float_button_text()
        self._sync_mprc_tab_stack_height()
        window.show()
        try:
            window.layout().activate()
        except Exception:
            pass
        window.raise_()
        window.activateWindow()

    def _dock_chat_play_tab(self):
        page = getattr(self, "_chat_play_page", None)
        stack = self._controls.get("tab_stack")
        if page is None or stack is None:
            return
        window = getattr(self, "_chat_play_floating_window", None)
        placeholder = getattr(self, "_chat_play_placeholder", None)
        if window is None and placeholder is None and stack.indexOf(page) >= 0:
            self._set_chat_play_float_button_text()
            return
        index = stack.indexOf(placeholder) if placeholder is not None else -1
        if index < 0:
            index = int(getattr(self, "_chat_play_stack_index", 0) or 0)
        self._chat_play_stack_index = max(0, index)
        if window is not None:
            try:
                layout = window.layout()
                if layout is not None:
                    layout.removeWidget(page)
            except Exception:
                pass
            try:
                window.controller = None
                window.hide()
                window.deleteLater()
            except RuntimeError:
                pass
        self._chat_play_floating_window = None
        page.setParent(None)
        if placeholder is not None:
            try:
                stack.removeWidget(placeholder)
                placeholder.deleteLater()
            except RuntimeError:
                pass
        self._chat_play_placeholder = None
        if stack.indexOf(page) < 0:
            stack.insertWidget(self._chat_play_stack_index, page)
        stack.setCurrentWidget(page)
        page.setVisible(True)
        page.show()
        page.updateGeometry()
        self._set_chat_play_float_button_text()
        self._sync_mprc_tab_stack_height()
        try:
            stack.updateGeometry()
        except Exception:
            pass

    def _append_chat_play_line(self, speaker: str, text: str, *, role: str = "note") -> None:
        transcript = self._controls.get("chat_transcript")
        if transcript is None:
            return
        speaker_text = html.escape(str(speaker or "").strip() or "MPRC")
        body = html.escape(str(text or "").strip())
        if not body:
            return
        color = {
            "user": "#dbeafe",
            "assistant": "#bbf7d0",
            "system": "#fef3c7",
        }.get(str(role or "").strip().lower(), "#9fb3c8")
        line = (
            f"<p style='margin:6px 0; color:{color};'>"
            f"<b>{speaker_text}:</b> {body.replace(chr(10), '<br/>')}"
            "</p>"
        )
        bar = None
        old_value = 0
        should_autoscroll = True
        try:
            bar = transcript.verticalScrollBar()
            old_value = int(bar.value())
            remaining = int(bar.maximum()) - old_value
            should_autoscroll = remaining <= max(24, int(bar.pageStep()) // 3)
        except Exception:
            bar = None
            should_autoscroll = True
        transcript.append(line)
        try:
            bar = bar or transcript.verticalScrollBar()
            if should_autoscroll:
                bar.setValue(bar.maximum())
            else:
                bar.setValue(min(old_value, bar.maximum()))
        except Exception:
            pass

    def _restore_chat_play_feed_from_state(self) -> None:
        transcript = self._controls.get("chat_transcript")
        if transcript is None or bool(transcript.property("_mprc_state_restored")):
            return
        turn_index = int(getattr(self.session, "turn_index", 0) or 0)
        restored_beats = self._restored_chat_play_beats()
        if turn_index <= 0 and not restored_beats:
            return
        transcript.setProperty("_mprc_state_restored", True)
        self._append_chat_play_line(
            "System",
            "Restored an ongoing MPRC story from saved state. The full Play transcript is not persisted; fuller archived story beats are shown below when available.",
            role="system",
        )
        for beat in restored_beats:
            self._append_chat_play_line("Restored Beat", beat, role="assistant")

    def _restored_chat_play_beats(self) -> list[str]:
        beats: list[str] = []
        try:
            payload = self.long_memory.load()
        except Exception:
            payload = {}
        events = list(payload.get("events") or []) if isinstance(payload, dict) else []
        for event in events[-6:]:
            if not isinstance(event, dict):
                continue
            text = str(event.get("assistant_text") or event.get("summary") or "").strip()
            if text:
                beats.append(self._mprc_compact(self._mprc_strip_audio_tags(text), 1600))
        if beats:
            return beats
        ar_events = list(getattr(self.session.ar_state, "recent_events", []) or [])
        events = ar_events or list(getattr(self.session, "recent_events", []) or [])
        for event in events[-6:]:
            text = str(event or "").strip()
            if text:
                beats.append(self._mprc_strip_audio_tags(text))
        return beats

    def _set_chat_play_status(self, message: str) -> None:
        status = self._controls.get("chat_status")
        if status is not None and hasattr(status, "setText"):
            status.setText(str(message or ""))

    def _on_mprc_chat_start_clicked(self):
        use_ar = self._controls.get("chat_use_ar")
        self.session.enabled = True
        if use_ar is not None and use_ar.isChecked():
            self.session.mode = AR_MODE
        if int(getattr(self.session, "turn_index", 0) or 0) <= 0:
            self._reset_mprc_chat_history()
        self.save_state()
        self._set_chat_play_status("MPRC Play session is active.")
        self._append_chat_play_line("System", "Play session armed inside MPRC.", role="system")
        if self._mprc_story_should_open_on_start():
            self._start_mprc_opening_turn()
        else:
            self.refresh_ui()

    def _mprc_story_should_open_on_start(self) -> bool:
        if int(getattr(self.session, "turn_index", 0) or 0) > 0:
            return False
        send_button = self._controls.get("chat_send")
        if send_button is not None and bool(send_button.property("_mprc_in_flight")):
            return False
        return True

    def _start_mprc_opening_turn(self) -> None:
        message = (
            "Continue. Open the current story from the stored scene and Master Story setup. "
            "Include a concise [NARRATOR] opening/backstory beat, introduce the immediate situation, "
            "show who is present, and end at a natural point for player action or [CHOICES]."
        )
        self.session.ar_state.player_intent = message
        self.ensure_ar_state(message)
        self.save_state()
        self._append_chat_play_line("System", "Opening current story from MPRC Play.", role="system")
        self._start_mprc_chat_turn(
            intent="System",
            player_text=message,
            speaker_id="",
            display_user=False,
            status="Opening MPRC story through the selected chat provider...",
        )

    def _on_mprc_chat_pause_clicked(self):
        self._stop_mprc_chat_playback()
        self.session.enabled = False
        self.save_state()
        self._set_chat_play_status("MPRC Play stopped.")
        self._append_chat_play_line("System", "Play session stopped.", role="system")
        self._refresh_chat_play_controls()

    def _on_mprc_chat_restart_clicked(self):
        self._stop_mprc_chat_playback()
        self._reset_mprc_chat_history()
        removed_auto_personas = self._remove_chat_auto_personas()
        transcript = self._controls.get("chat_transcript")
        if transcript is not None:
            transcript.clear()
        self.session.enabled = True
        self.session.turn_index = 0
        self.session.recent_events = []
        self.session.character_state_summaries = {}
        self.session.last_visual_reply_at = 0.0
        self.session.auto_image_count = 0
        self.session.ar_state.recent_events = []
        self.session.ar_state.pending_choices = []
        self.session.ar_state.player_intent = ""
        self.session.ar_state.tension_level = 2
        use_ar = self._controls.get("chat_use_ar")
        if use_ar is not None and hasattr(use_ar, "isChecked") and bool(use_ar.isChecked()):
            self.session.mode = AR_MODE
        self.ensure_ar_state()
        try:
            self.roleplay_engine._recent_assistant_texts = []
        except Exception:
            pass
        self._clear_story_memory_preserving_pins()
        self.save_state()
        restart_note = "Story restarted from the current setup. Story and character memory were reset."
        status_note = "MPRC story restarted. Saved story setup was left intact; story memory was reset."
        if removed_auto_personas:
            restart_note += f" Removed {removed_auto_personas} auto-created chat persona(s)."
            status_note += f" Removed {removed_auto_personas} [Auto Chat] persona(s)."
        self._append_chat_play_line("System", restart_note, role="system")
        self._set_chat_play_status(status_note)
        self._refresh_memory_browser()
        self._refresh_persona_selectors()
        self._refresh_reliability_panels()
        self._refresh_chat_play_controls()

    def _on_mprc_chat_clear_clicked(self):
        transcript = self._controls.get("chat_transcript")
        if transcript is not None:
            transcript.clear()
        self._set_chat_play_status("MPRC Play transcript cleared.")

    def _reset_mprc_chat_history(self) -> None:
        self._mprc_chat_history = []
        self._mprc_pending_chat_users = {}

    def _stop_mprc_chat_playback(self) -> None:
        send_button = self._controls.get("chat_send")
        if send_button is not None:
            token = str(send_button.property("_mprc_worker_token") or "").strip()
            if token:
                self._cancel_worker_token(token)
                self._mprc_pending_chat_users.pop(token, None)
            send_button.setProperty("_mprc_in_flight", False)
            send_button.setProperty("_mprc_worker_token", "")
            send_button.setEnabled(True)
        self._stop_mprc_chat_speech()

    def _stop_mprc_chat_speech(self) -> None:
        with self._mprc_tts_state_lock:
            tts_controller = self._mprc_tts_controller
            self._mprc_tts_controller = None
            tts_token = str(self._mprc_tts_token or "")
            self._mprc_tts_token = ""
        if tts_token:
            self._cancel_worker_token(tts_token)
        try:
            if tts_controller is not None and hasattr(tts_controller, "cancel"):
                tts_controller.cancel()
        except Exception:
            pass
        try:
            player = getattr(self, "_audiofx_player", None)
            if player is not None:
                player.stop()
        except Exception:
            pass
        try:
            from core.engine_access import engine_module

            engine = engine_module()
            stop_event = getattr(engine, "stop_playback", None)
            if stop_event is not None and hasattr(stop_event, "set"):
                stop_event.set()
            paused_event = getattr(engine, "playback_paused", None)
            if paused_event is not None and hasattr(paused_event, "clear"):
                paused_event.clear()
            transition = getattr(engine, "transition_musetalk_to_idle_after_interrupt", None)
            if callable(transition):
                transition()
        except Exception as exc:
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[MPRC] Could not stop MPRC playback: %s", exc)

    def _on_mprc_chat_send_clicked(self):
        input_widget = self._controls.get("chat_input")
        text = str(input_widget.toPlainText() if input_widget is not None and hasattr(input_widget, "toPlainText") else "").strip()
        if not text:
            self._set_chat_play_status("Add a player action before sending.")
            return
        send_button = self._controls.get("chat_send")
        if send_button is not None and bool(send_button.property("_mprc_in_flight")):
            self._set_chat_play_status("MPRC turn is already running.")
            return
        self._stop_mprc_chat_speech()
        intent_choice = "Auto"
        intent_combo = self._controls.get("chat_intent")
        if intent_combo is not None and hasattr(intent_combo, "currentText"):
            intent_choice = str(intent_combo.currentText() or "Auto").strip() or "Auto"
        intent = self._infer_mprc_chat_intent(text, intent_choice)
        speaker = "Player"
        speaker_id = ""
        combo = self._controls.get("chat_speaker")
        if combo is not None and hasattr(combo, "currentText"):
            selected = str(combo.currentText() or "").strip()
            if selected:
                speaker = selected
            if hasattr(combo, "currentData"):
                speaker_id = str(combo.currentData() or "").strip()
        latest_user_text = f"{intent}: {text}"
        self.session.ar_state.player_intent = latest_user_text
        if speaker_id:
            self.session.current_speaker_id = speaker_id
        use_ar = self._controls.get("chat_use_ar")
        if use_ar is not None and hasattr(use_ar, "isChecked") and bool(use_ar.isChecked()):
            self.session.mode = AR_MODE
        self.session.enabled = True
        self.ensure_ar_state(latest_user_text)
        self.save_state()
        self._append_chat_play_line(f"{speaker} [{intent}]", text, role="user")
        if input_widget is not None and hasattr(input_widget, "clear"):
            input_widget.clear()
        self._start_mprc_chat_turn(intent=intent, player_text=text, speaker_id=speaker_id)

    def _start_mprc_chat_turn(
        self,
        *,
        intent: str,
        player_text: str,
        speaker_id: str = "",
        display_user: bool = True,
        status: str = "MPRC turn running through the selected chat provider...",
    ) -> None:
        send_button = self._controls.get("chat_send")
        if send_button is not None and bool(send_button.property("_mprc_in_flight")):
            self._set_chat_play_status("MPRC turn is already running.")
            return
        try:
            messages = self._build_mprc_chat_turn_messages(intent=intent, player_text=player_text, speaker_id=speaker_id)
        except Exception as exc:
            self._set_chat_play_status(f"Could not build MPRC turn prompt: {exc}")
            return
        token = self._new_worker_token("mprc_chat")
        if not token:
            return
        user_message = next((item for item in reversed(messages) if str(item.get("role", "") or "") == "user"), {})
        if user_message:
            self._mprc_pending_chat_users[token] = dict(user_message)
        if send_button is not None:
            send_button.setProperty("_mprc_in_flight", True)
            send_button.setProperty("_mprc_worker_token", token)
            send_button.setEnabled(False)
        self._set_chat_play_status(status)
        self._refresh_chat_play_controls()

        def worker():
            error = ""
            reply = ""
            try:
                reply = self._run_mprc_chat_provider(messages)
            except Exception as exc:
                error = str(exc) or repr(exc)
            if not self._worker_should_emit(token):
                return
            try:
                bridge = getattr(self, "_chat_turn_bridge", None)
                if bridge is not None:
                    bridge.finished.emit(token, reply, error)
                else:
                    self._cancel_worker_token(token)
            except RuntimeError:
                self._cancel_worker_token(token)

        if not self._start_daemon_worker(token, worker, name="nc-mprc-chat-turn"):
            self._mprc_pending_chat_users.pop(token, None)
            if send_button is not None:
                send_button.setProperty("_mprc_in_flight", False)
                send_button.setProperty("_mprc_worker_token", "")
                send_button.setEnabled(True)
            self._set_chat_play_status("Could not start MPRC turn worker.")

    def _on_mprc_choice_selected(self, item, *, send: bool = False):
        choice = str(item.text() if item is not None and hasattr(item, "text") else "").strip()
        if not choice:
            return
        input_widget = self._controls.get("chat_input")
        if input_widget is not None and hasattr(input_widget, "setPlainText"):
            input_widget.setPlainText(choice)
            try:
                input_widget.setFocus()
                cursor = input_widget.textCursor()
                cursor.movePosition(QtGui.QTextCursor.End)
                input_widget.setTextCursor(cursor)
            except Exception:
                pass
        intent_combo = self._controls.get("chat_intent")
        if intent_combo is not None and hasattr(intent_combo, "setCurrentText"):
            intent_combo.setCurrentText("Auto")
        if send:
            self._set_chat_play_status("Choice selected and sent.")
            self._on_mprc_chat_send_clicked()
        else:
            self._set_chat_play_status("Choice loaded into Player Action. Edit or Send.")

    def _infer_mprc_chat_intent(self, text: str, selected_intent: str = "Auto") -> str:
        selected = str(selected_intent or "Auto").strip()
        if selected and selected.lower() != "auto":
            return selected
        value = str(text or "").strip()
        lowered = value.lower()
        if not value:
            return "Act"
        if lowered.startswith(("ooc:", "[ooc]", "out of character:", "out-of-character:")):
            return "OOC"
        if lowered.startswith(("direct:", "director:", "scene:", "pace:", "tone:", "camera:")):
            return "Direct"
        if lowered.startswith(("say ", "ask ", "tell ", "reply ", "answer ", "whisper ", "shout ")):
            return "Say"
        if value.startswith(('"', "'")):
            return "Say"
        return "Act"

    def _build_mprc_chat_turn_messages(self, *, intent: str, player_text: str, speaker_id: str = "") -> list[dict[str, str]]:
        player_action = str(player_text or "").strip()
        if not player_action:
            raise ValueError("Player action is empty.")
        intent_text = str(intent or "Act").strip() or "Act"
        latest_user_text = player_action if intent_text.lower() == "system" else f"{intent_text}: {player_action}"
        director_text = self._mprc_chat_director_context()
        full_setup = not bool(self._mprc_chat_history) and int(getattr(self.session, "turn_index", 0) or 0) <= 0
        structured_output_rules = (
            self._mprc_structured_output_prompt_rules()
            if self._mprc_chat_structured_output_applies(full_setup=full_setup)
            else ""
        )
        if full_setup:
            context_text = self._mprc_chat_full_context(
                latest_user_text,
                cast_mode=story_director.CAST_MODE_JOINED_CAST,
            )
            system_parts = [
                "You are NeuralCompanion's dedicated Multi Persona Roleplay story runtime. This is separate from normal chat history.",
                "Write only the next story response to the player's action. Do not summarize these instructions or expose prompt structure.",
                "Preserve player agency: never decide major player actions, private thoughts, or consent for the player.",
                "Use clear story-native formatting. In AR mode, prefer [NARRATOR], [CHARACTER: Exact Name], exact listed story audio tags when needed, and follow the Director response ending mode.",
                "Treat the user payload's focus instruction as binding for who performs or frames the latest action.",
                structured_output_rules,
                context_text,
                director_text,
            ]
        else:
            story_director_context = ""
            if prompting.is_alternative_reality_mode(self.session):
                story_director_context = self._mprc_chat_full_context(
                    latest_user_text,
                    cast_mode=story_director.CAST_MODE_FOCUSED_SPEAKER,
                )
            system_parts = [
                "You are NeuralCompanion's dedicated Multi Persona Roleplay story runtime. Continue the existing MPRC Play conversation below.",
                "Write only the next story response to the player's latest action. Do not recap the full setup unless the player asks.",
                "Preserve player agency: never decide major player actions, private thoughts, or consent for the player.",
                "In AR mode, use [NARRATOR], [CHARACTER: Exact Name], exact listed story audio tags when needed, and follow the Director response ending mode.",
                "Treat the user payload's focus instruction as binding for who performs or frames the latest action.",
                structured_output_rules,
                story_director_context,
                self._mprc_chat_compact_turn_context(latest_user_text),
                director_text,
            ]
        system_prompt = "\n\n".join(part for part in system_parts if str(part or "").strip())
        self.set_debug_prompt(system_prompt)
        focused = self.persona_by_id(speaker_id) if speaker_id else None
        if focused is not None and self._persona_looks_like_narrator(focused):
            focus_instruction = (
                f"The player is directing the scene through narrator focus '{focused.display_name}'. "
                "Treat the player_action as scene-level narration or direction unless it explicitly names another speaker."
            )
        elif focused is not None:
            focus_instruction = (
                f"The player is acting through or speaking as '{focused.display_name}' for this turn. "
                "Treat the player_action as that character's intended action or dialogue unless it explicitly names another actor."
            )
        else:
            focus_instruction = (
                "No character focus is selected. Treat the player_action as the player's own action or director instruction, "
                "depending on the intent."
            )
        user_payload = {
            "intent": intent_text,
            "player_action": player_action,
            "focused_speaker": focused.display_name if focused is not None else "Player",
            "focus_instruction": focus_instruction,
            "instruction": "Advance the MPRC scene by one coherent turn without touching normal chat continuity.",
        }
        messages = [{"role": "system", "content": system_prompt}]
        messages.append({"role": "user", "content": json.dumps(user_payload, ensure_ascii=True, indent=2)})
        return messages

    def _mprc_chat_full_context(
        self,
        latest_user_text: str,
        *,
        cast_mode: str = story_director.CAST_MODE_FOCUSED_SPEAKER,
    ) -> str:
        prompt_personas = self.story_prompt_personas()
        if prompting.is_alternative_reality_mode(self.session):
            return prompting.build_alternative_reality_prompt(
                prompt_personas,
                self.session,
                latest_user_text=latest_user_text,
                available_audio=self.available_story_audio_files(),
                narrator_persona_id=self.selected_narrator_persona_id(),
                cast_mode=cast_mode,
            )
        persona = self.current_speaker_persona() or self.active_persona()
        context_text = prompting.build_persona_system_prompt(persona, self.session) if persona is not None else ""
        if self.session.mode != "Single active persona":
            context_text = (context_text + "\n\n" + prompting.build_multi_character_prompt(prompt_personas, self.session)).strip()
        return context_text

    def _mprc_chat_compact_turn_context(self, latest_user_text: str) -> str:
        state = self.session.ar_state
        active_lines = self._mprc_chat_active_character_lines()
        cue_lines = self._mprc_chat_audio_activation_lines()
        history_lines = self._mprc_chat_history_lines()
        parts = [
            "MPRC compact turn state:",
            "Progression rule: latest player intent and latest visible story beat override older scene summary/location memory.",
            f"Scene: {self._mprc_compact(state.current_scene or self.session.scene_title, 180)}",
            f"Location: {self._mprc_compact(state.location or self.session.location, 140)}",
            f"Time: {self._mprc_compact(state.time_of_day or self.session.time_of_day, 80)}",
            f"Mood: {self._mprc_compact(state.mood or self.session.mood, 100)}",
            f"Tension: {int(getattr(state, 'tension_level', 0) or 0)}",
            f"Goal: {self._mprc_compact(state.story_goal or self.session.objective, 220)}",
            f"Latest player intent: {self._mprc_compact(latest_user_text or state.player_intent, 220)}",
            f"Pending choices: {self._mprc_join_compact(state.pending_choices, 4, 120)}",
            f"Recent events: {self._mprc_join_compact(list(state.recent_events or [])[-4:], 4, 150)}",
            f"Scene summary: {self._mprc_compact(self.session.scene_summary, 700)}",
        ]
        if active_lines:
            parts.append("Active cast:\n" + "\n".join(active_lines))
        if cue_lines:
            parts.append("Allowed story audio tags:\n" + "\n".join(cue_lines))
        if history_lines:
            parts.append("Recent play transcript (compact):\n" + "\n".join(history_lines))
        return "\n".join(item for item in parts if str(item or "").strip()).strip()

    def _mprc_chat_active_character_lines(self) -> list[str]:
        state = self.session.ar_state
        active_ids = [normalize_persona_id(item) for item in list(state.active_characters or []) if str(item or "").strip()]
        if not active_ids:
            active_ids = [self.session.current_speaker_id, self.session.active_persona_id]
        lines = []
        seen = set()
        for persona_id in active_ids:
            persona = self.persona_by_id(persona_id)
            if persona is None or persona.id in seen:
                continue
            seen.add(persona.id)
            role = self._mprc_compact(persona.role or persona.behavior_mode, 80)
            desc = self._mprc_compact(getattr(persona, "ar_description", "") or persona.description, 180)
            instruction = self._mprc_compact(getattr(persona, "ar_system_prompt", ""), 220)
            line = f"- {persona.display_name} ({persona.id})"
            if role:
                line += f": {role}"
            if desc:
                line += f"; {desc}"
            if instruction:
                line += f"; instruction={instruction}"
            lines.append(line)
        return lines[:6]

    def _mprc_chat_audio_activation_lines(self) -> list[str]:
        lines = []
        for item in list(self.available_story_audio_files() or [])[:16]:
            if not isinstance(item, dict) or not item.get("ready", True):
                continue
            audio_type = str(item.get("type") or "Audio").strip().upper() or "AUDIO"
            if audio_type in {"SFX"}:
                audio_type = "FX"
            if audio_type not in {"AMBIENCE", "AMBIENT", "MUSIC", "FX", "STINGER", "AUDIO"}:
                audio_type = "AUDIO"
            if audio_type == "AMBIENT":
                audio_type = "AMBIENCE"
            description = self._mprc_compact(str(item.get("description") or item.get("prompt") or item.get("id") or ""), 120)
            if description:
                lines.append(f"- [{audio_type}: {description}]")
        return lines

    def _mprc_chat_history_lines(self) -> list[str]:
        lines = []
        for message in list(self._mprc_chat_history or [])[-8:]:
            role = str((message or {}).get("role") or "").strip().lower()
            content = str((message or {}).get("content") or "").strip()
            if not role or not content:
                continue
            if role == "user":
                label = "Player"
                try:
                    payload = json.loads(content)
                except Exception:
                    payload = {}
                if isinstance(payload, dict):
                    intent = str(payload.get("intent") or "Action").strip() or "Action"
                    action = str(payload.get("player_action") or "").strip()
                    content = f"{intent}: {action}" if action else content
                lines.append(f"- {label}: {self._mprc_compact(content, 180)}")
            elif role == "assistant":
                lines.append(f"- Story: {self._mprc_compact(self._mprc_strip_audio_tags(content), 240)}")
        return lines

    @staticmethod
    def _mprc_strip_audio_tags(text: str) -> str:
        return re.sub(
            r"\[(?:AMBIENCE|AMBIENT|MUSIC|FX|SFX|STINGER|AUDIO):[^\]]+\]",
            " ",
            str(text or ""),
            flags=re.IGNORECASE,
        )

    @staticmethod
    def _mprc_compact(text: Any, limit: int) -> str:
        value = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(value) <= max(0, int(limit or 0)):
            return value
        return value[: max(0, int(limit or 0) - 1)].rstrip() + "..."

    def _mprc_join_compact(self, items: list[Any], count: int, limit: int) -> str:
        values = [self._mprc_compact(item, limit) for item in list(items or []) if str(item or "").strip()]
        return "; ".join(values[-max(0, int(count or 0)):]) or "none"

    def _mprc_chat_director_context(self) -> str:
        tone = self._control_current_text("chat_director_tone")
        agency = self._control_current_text("chat_director_agency")
        pacing = str(self.session.ar_pacing or self._control_current_text("chat_director_pacing") or "Balanced").strip()
        choice_mode = self._mprc_chat_choice_mode()
        lines = [
            f"Director pacing: {pacing}",
            f"Director tone: {tone or 'Keep current'}",
            f"Player agency mode: {agency or 'Guided'}",
            (
                'Response ending mode: Ask "What\'s your next move?" Do not include [CHOICES].'
                if choice_mode == "ask_next_move"
                else "Response ending mode: Always end with [CHOICES] containing 2 to 4 concrete playable next actions."
            ),
            "Progression priority: the latest player action overrides older scene summary/location memory. If the player leaves, enters, travels, or moves to a new place, transition there unless a concrete immediate obstacle blocks it.",
        ]
        return "MPRC Play director controls:\n" + "\n".join(lines)

    def _control_current_text(self, key: str) -> str:
        widget = self._controls.get(key)
        if widget is not None and hasattr(widget, "currentText"):
            return str(widget.currentText() or "").strip()
        return ""

    def _mprc_structured_output_cast(self) -> dict[str, dict[str, str]]:
        cast: dict[str, dict[str, str]] = {}
        try:
            personas = list(self.story_prompt_personas() or [])
        except Exception:
            personas = []
        if not personas:
            personas = list(getattr(self, "personas", []) or [])
        for persona in personas:
            persona_id = normalize_persona_id(getattr(persona, "id", "") or "")
            if not persona_id or persona_id in {"narrator", "unknown_speaker"}:
                continue
            if self._persona_looks_like_narrator(persona):
                continue
            display_name = re.sub(r"\s+", " ", str(getattr(persona, "display_name", "") or persona_id)).strip()
            if display_name:
                cast[persona_id] = {"speaker_name": display_name}
        return cast

    def _mprc_structured_output_schema(self) -> dict[str, Any]:
        return build_structured_story_output_schema(
            self._mprc_structured_output_cast(),
            require_choices=self._mprc_chat_should_offer_choices(),
        )

    def _mprc_chat_structured_output_enabled(self) -> bool:
        return bool(self.settings.get("chat_structured_output_enabled", True))

    def _mprc_chat_structured_output_scope(self) -> str:
        scope = str(self.settings.get("chat_structured_output_scope") or "every_turn").strip().lower()
        return scope if scope in {"every_turn", "first_turn"} else "every_turn"

    def _mprc_chat_choice_mode(self) -> str:
        mode = str(self.settings.get("chat_choice_mode") or "choices").strip().lower()
        return mode if mode in {"choices", "ask_next_move"} else "choices"

    def _mprc_chat_should_offer_choices(self) -> bool:
        return self._mprc_chat_choice_mode() != "ask_next_move"

    def _mprc_chat_structured_output_applies(self, *, full_setup: bool) -> bool:
        if not self._mprc_chat_structured_output_enabled():
            return False
        scope = self._mprc_chat_structured_output_scope()
        return scope == "every_turn" or bool(full_setup)

    def _mprc_chat_structured_response_format(self) -> dict[str, Any]:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "mprc_story_turn",
                "strict": True,
                "schema": self._mprc_structured_output_schema(),
            },
        }

    def _apply_mprc_chat_structured_response_format(self, params: dict[str, Any], *, full_setup: bool) -> bool:
        if not self._mprc_chat_structured_output_applies(full_setup=full_setup):
            return False
        params["response_format"] = self._mprc_chat_structured_response_format()
        self._apply_mprc_chat_structured_token_cap(params)
        return True

    @staticmethod
    def _apply_mprc_chat_structured_token_cap(params: dict[str, Any]) -> None:
        cap = 2400
        for key in ("max_completion_tokens", "max_tokens"):
            if key not in params:
                continue
            try:
                current = int(params.get(key))
            except Exception:
                current = cap
            if current <= 0 or current > cap:
                params[key] = cap
            return
        params["max_tokens"] = cap

    def _mprc_structured_output_prompt_rules(self) -> str:
        cast = {"narrator": {"speaker_name": "Narrator"}}
        cast.update(self._mprc_structured_output_cast())
        cast["unknown_speaker"] = {"speaker_name": "Unknown Speaker"}
        cast_lines = [
            f"- {speaker_id}: {item.get('speaker_name') or speaker_id}"
            for speaker_id, item in cast.items()
        ]
        choice_rule = (
            "- The choices array must contain 2 to 4 concise playable next actions. These become [CHOICES] at the end of the reply."
            if self._mprc_chat_should_offer_choices()
            else '- The choices array must be empty. End the final narrator segment by asking "What\'s your next move?"'
        )
        return "\n".join(
            [
                "Structured Output rules:",
                f"- Return one compact JSON object matching schema_version {STRUCTURED_STORY_SCHEMA_VERSION}. No markdown or usage metadata.",
                "- Use only these speaker_id values; do not output speaker_name because voice routing maps speaker_id locally:",
                *cast_lines,
                "- Never output voice IDs, voice file paths, or made-up voice keys.",
                "Story Director segment discipline:",
                "- Put one speaker per segment; split quoted dialogue into character segments, not narrator text.",
                "- Character segment text must contain only the spoken words or first-person thought. Put attribution, movement, facial expression, and consequences in narrator segments.",
                "- If two characters speak, use two character segments. Do not combine multiple speakers in one segment.",
                "- If narration surrounds dialogue, alternate narrator and character segments so multi-TTS can route every chunk cleanly.",
                "- Narrator segments must carry scene action, setting, visible consequences, attribution, and pacing beats.",
                "- Keep the turn short: no more than 6 story segments; put playable options only in choices.",
                choice_rule,
            ]
        )

    def _on_export_mprc_structured_output_clicked(self) -> None:
        schema = self._mprc_structured_output_schema()
        path = self._save_file(
            "Export MPRC Structured LLM Output Schema",
            str(Path.home() / "mprc_structured_llm_output_schema.json"),
            "JSON Schema (*.json);;JSON files (*.json)",
        )
        if not path:
            self._set_chat_play_status("Structured Output export cancelled.")
            return
        try:
            Path(path).write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            self._warn("Export Structured Output", f"Export failed:\n\n{exc}")
            self._set_chat_play_status(f"Structured Output export failed: {exc}")
            return
        self._set_chat_play_status(f"Exported Structured Output schema to {path}.")

    def _run_mprc_chat_provider(self, messages: list[dict[str, str]]) -> str:
        from core.engine_access import engine_module

        engine = engine_module()
        model_name = str(getattr(engine, "RUNTIME_CONFIG", {}).get("model_name", "") or "").strip()
        if hasattr(engine, "_is_model_catalog_placeholder") and engine._is_model_catalog_placeholder(model_name):
            raise RuntimeError("Choose a chat model before running MPRC Play.")
        params = {
            "model": model_name,
            "messages": list(messages or []),
        }
        additional_params: dict[str, Any] = {}
        if hasattr(engine, "_apply_chat_provider_generation_fields"):
            engine._apply_chat_provider_generation_fields(params, additional_params)
        full_setup = not bool(self._mprc_chat_history) and int(getattr(self.session, "turn_index", 0) or 0) <= 0
        structured_output_applied = self._apply_mprc_chat_structured_response_format(params, full_setup=full_setup)
        try:
            reply = str(engine._chat_completion_create(params, additional_params) or "").strip()
        except Exception as exc:
            if not structured_output_applied or not self._mprc_chat_provider_error_is_structured_output_compatibility(exc):
                raise
            fallback_params = dict(params)
            fallback_params.pop("response_format", None)
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[MPRC] MPRC Play structured output rejected by provider; retrying without schema: %s", exc)
            self._record_story_event(
                f"structured output fallback: provider rejected request-scoped schema ({exc})",
                severity="warning",
                kind="runtime",
                persist=True,
            )
            reply = str(engine._chat_completion_create(fallback_params, additional_params) or "").strip()
        if not reply:
            raise RuntimeError("The selected chat provider returned an empty MPRC reply.")
        return reply

    @staticmethod
    def _mprc_chat_provider_error_is_structured_output_compatibility(exc: Exception) -> bool:
        text = str(exc or "").lower()
        markers = (
            "response_format",
            "json_schema",
            "structured output",
            "structured_output",
            "schema",
        )
        return any(marker in text for marker in markers)

    def _finalize_mprc_chat_reply_choice_mode(self, reply: str) -> str:
        text = str(reply or "").strip()
        if not text:
            return ""
        if not self._mprc_chat_should_offer_choices():
            return self._ensure_mprc_next_move_reply(text)
        if self._extract_ar_choices(text):
            return text
        choices = self._mprc_fallback_reply_choices()
        if not choices:
            return text
        return f"{text.rstrip()}\n\n[CHOICES]\n" + "\n".join(
            f"{index}. {choice}" for index, choice in enumerate(choices, start=1)
        )

    def _ensure_mprc_next_move_reply(self, reply: str) -> str:
        text = self._strip_mprc_choices_block(str(reply or "").strip())
        if not text:
            text = "[NARRATOR]"
        if re.search(r"what(?:'|’)?s your next move\?\s*$", text, flags=re.IGNORECASE):
            return text.strip()
        return f"{text.rstrip()}\n\n[NARRATOR]\nWhat's your next move?"

    @staticmethod
    def _strip_mprc_choices_block(text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        match = re.search(r"(?ims)\n?\s*\[CHOICES\]\s*.*$", raw)
        return raw[: match.start()].rstrip() if match else raw

    def _mprc_fallback_reply_choices(self) -> list[str]:
        state = self.session.ar_state
        choices: list[str] = []
        objective = self._mprc_compact(state.story_goal or self.session.objective, 120)
        if objective:
            choices.append(f"Pursue objective: {objective}")
        active = self.current_speaker_persona() or self.active_persona()
        if active is not None and not self._persona_looks_like_narrator(active):
            choices.append(f"Ask {active.display_name} what they notice")
        choices.extend(["Investigate the scene", "Proceed cautiously"])
        normalized: list[str] = []
        seen: set[str] = set()
        for choice in choices:
            clean = re.sub(r"\s+", " ", str(choice or "")).strip()
            if not clean:
                continue
            key = clean.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(clean[:180])
            if len(normalized) >= 4:
                break
        return normalized

    def _on_mprc_chat_turn_finished(self, token: str, reply_text: str, error: str):
        send_button = self._controls.get("chat_send")
        token = str(token or "")
        if not self._finish_worker_token(str(token or "")):
            self._mprc_pending_chat_users.pop(token, None)
            return
        if send_button is not None:
            send_button.setProperty("_mprc_in_flight", False)
            send_button.setProperty("_mprc_worker_token", "")
            send_button.setEnabled(True)
        if error:
            self._mprc_pending_chat_users.pop(token, None)
            self._set_chat_play_status(f"MPRC turn failed: {error}")
            self._append_chat_play_line("System", f"MPRC turn failed: {error}", role="system")
            return
        reply = self._normalize_mprc_structured_reply(
            str(reply_text or "").strip(),
            cast=self._mprc_structured_output_cast(),
        )
        reply = self._finalize_mprc_chat_reply_choice_mode(reply)
        if not reply:
            self._mprc_pending_chat_users.pop(token, None)
            self._set_chat_play_status("MPRC turn returned no story text.")
            return
        self._remote_latest_reply_text = reply
        user_message = self._mprc_pending_chat_users.pop(token, None)
        user_text = self._mprc_chat_message_text(user_message)
        if user_message:
            self._remember_mprc_chat_message(user_message)
        self._remember_mprc_chat_message({"role": "assistant", "content": reply})
        self._append_chat_play_line("Story", reply, role="assistant")
        allow_visuals = self._control_checked("chat_visuals", False)
        self._suppress_next_auto_visual_reply = not allow_visuals
        try:
            self.roleplay_engine.record_assistant_text(reply)
        except Exception as exc:
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[MPRC] Reply hook update failed: %s", exc)
        finally:
            self._suppress_next_auto_visual_reply = False
        self._maybe_request_spotify_story_music(reply, user_text=user_text)
        self._speak_mprc_chat_reply(reply)
        self._set_chat_play_status("MPRC turn complete.")
        self._refresh_chat_play_controls()

    @staticmethod
    def _normalize_mprc_structured_reply(text: str, cast: dict[str, dict[str, str]] | None = None) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        payload = MultiPersonaRoleplayController._extract_mprc_structured_reply_payload(raw)
        if payload is None:
            recovered = MultiPersonaRoleplayController._recover_mprc_partial_structured_reply(raw, cast=cast)
            if recovered:
                return recovered
            if MultiPersonaRoleplayController._mprc_reply_looks_like_structured_json(raw):
                return (
                    "[NARRATOR]\n"
                    "The structured story response was incomplete and could not be converted. "
                    "Please continue with a shorter story turn."
                )
            return raw
        converted = MultiPersonaRoleplayController._mprc_structured_reply_to_ar_text(payload, cast=cast)
        if converted:
            return converted
        if MultiPersonaRoleplayController._mprc_reply_looks_like_structured_json(raw):
            return (
                "[NARRATOR]\n"
                "The structured story response did not contain usable story segments. "
                "Please continue with a shorter story turn."
            )
        return raw

    @staticmethod
    def _recover_mprc_partial_structured_reply(text: str, cast: dict[str, dict[str, str]] | None = None) -> str:
        raw = str(text or "").strip()
        if not MultiPersonaRoleplayController._mprc_reply_looks_like_structured_json(raw):
            return ""
        segments = [
            item
            for item in MultiPersonaRoleplayController._recover_mprc_json_array_items(raw, "segments")
            if isinstance(item, dict)
        ]
        if not segments:
            return ""
        choices = MultiPersonaRoleplayController._recover_mprc_json_array_items(raw, "choices")
        payload: dict[str, Any] = {"segments": segments, "choices": choices}
        converted = MultiPersonaRoleplayController._mprc_structured_reply_to_ar_text(payload, cast=cast)
        if not converted:
            return ""
        if not choices and MultiPersonaRoleplayController._mprc_structured_json_probably_truncated(raw):
            converted = (
                f"{converted}\n\n"
                "[NARRATOR]\n"
                "The structured response was cut off before it finished. Continue with a shorter turn."
            )
        return converted

    @staticmethod
    def _recover_mprc_json_array_items(text: str, key: str) -> list[Any]:
        raw = str(text or "")
        match = re.search(rf'"{re.escape(str(key or ""))}"\s*:\s*\[', raw)
        if not match:
            return []
        decoder = json.JSONDecoder()
        items: list[Any] = []
        pos = match.end()
        while pos < len(raw):
            while pos < len(raw) and raw[pos] in " \t\r\n,":
                pos += 1
            if pos >= len(raw) or raw[pos] == "]":
                break
            try:
                item, end = decoder.raw_decode(raw[pos:])
            except Exception:
                break
            items.append(item)
            pos += end
        return items

    @staticmethod
    def _mprc_reply_looks_like_structured_json(text: str) -> bool:
        raw = str(text or "")
        head = raw[:5000]
        if STRUCTURED_STORY_SCHEMA_VERSION in head:
            return True
        return '"segments"' in head and ('"speaker_id"' in head or '"response_type"' in head)

    @staticmethod
    def _mprc_structured_json_probably_truncated(text: str) -> bool:
        raw = str(text or "")
        return raw.count("{") != raw.count("}") or raw.count("[") != raw.count("]")

    @staticmethod
    def _extract_mprc_structured_reply_payload(text: str) -> dict[str, Any] | None:
        raw = str(text or "").strip()
        if not raw or "{" not in raw:
            return None
        decoder = json.JSONDecoder()
        for start in [match.start() for match in re.finditer(r"\{", raw)]:
            try:
                payload, _end = decoder.raw_decode(raw[start:])
            except Exception:
                continue
            if isinstance(payload, dict) and MultiPersonaRoleplayController._is_mprc_structured_reply_payload(payload):
                return payload
        return None

    @staticmethod
    def _is_mprc_structured_reply_payload(payload: dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False
        if isinstance(payload.get("segments"), list):
            return True
        story = payload.get("story")
        if isinstance(story, dict) and isinstance(story.get("segments"), list):
            return True
        return isinstance(payload.get("choices"), list) and any(
            key in payload for key in ("segments", "story", "reply", "response")
        )

    @staticmethod
    def _mprc_structured_reply_to_ar_text(payload: dict[str, Any], cast: dict[str, dict[str, str]] | None = None) -> str:
        if not isinstance(payload, dict):
            return ""
        story = payload.get("story")
        source = story if isinstance(story, dict) else payload
        parts: list[str] = []
        choices: list[str] = []
        for item in list(source.get("segments") or []):
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or item.get("type") or item.get("role") or "").strip().lower()
            text = str(item.get("text") or item.get("content") or item.get("body") or "").strip()
            if not text:
                continue
            if kind in {"choice", "choices", "option", "options"}:
                choices.extend(MultiPersonaRoleplayController._mprc_structured_choice_lines(text))
                continue
            section = MultiPersonaRoleplayController._mprc_structured_segment_to_ar_text(kind, item, text, cast=cast)
            if section:
                parts.append(section)
        for item in list(source.get("choices") or payload.get("choices") or []):
            choice = MultiPersonaRoleplayController._mprc_structured_choice_text(item)
            if choice:
                choices.append(choice)
        if choices:
            normalized_choices = list(dict.fromkeys(choice for choice in choices if choice))
            if normalized_choices:
                lines = ["[CHOICES]"]
                lines.extend(f"{index}. {choice}" for index, choice in enumerate(normalized_choices, start=1))
                parts.append("\n".join(lines))
        return "\n\n".join(part for part in parts if str(part or "").strip()).strip()

    @staticmethod
    def _mprc_structured_segment_to_ar_text(
        kind: str,
        item: dict[str, Any],
        text: str,
        cast: dict[str, dict[str, str]] | None = None,
    ) -> str:
        if MultiPersonaRoleplayController._mprc_structured_text_starts_with_ar_tag(text):
            return text.strip()
        speaker_id = normalize_persona_id(item.get("speaker_id") or "")
        speaker = MultiPersonaRoleplayController._mprc_structured_speaker_name(
            item.get("speaker") or item.get("speaker_name") or item.get("name") or item.get("character")
        )
        cast_map = dict(cast or {})
        cast_map.setdefault("narrator", {"speaker_name": "Narrator"})
        cast_map.setdefault("unknown_speaker", {"speaker_name": "Unknown Speaker"})
        if speaker_id in cast_map:
            speaker = str(cast_map[speaker_id].get("speaker_name") or speaker or speaker_id).strip()
        if kind == "sfx":
            tags = [
                f"[FX: {tag}]"
                for tag in (
                    re.sub(r"\s+", " ", str(tag or "")).strip()
                    for tag in list(item.get("sfx_tags") or [])
                )
                if tag
            ]
            if not tags:
                tags.append(f"[SFX: {text.strip()}]")
            else:
                tags.append(f"[NARRATOR]\n{text.strip()}")
            return "\n".join(tags)
        if kind in {"music", "ambience", "ambient", "fx", "sfx", "stinger", "audio", "sound"}:
            audio_type = {
                "ambient": "AMBIENCE",
                "ambience": "AMBIENCE",
                "music": "MUSIC",
                "fx": "FX",
                "sfx": "SFX",
                "stinger": "STINGER",
                "audio": "AUDIO",
                "sound": "AUDIO",
            }.get(kind, "AUDIO")
            return f"[{audio_type}: {text.strip()}]"
        if kind == "narrator" or speaker_id in {"narrator", "unknown_speaker"}:
            return f"[NARRATOR]\n{text.strip()}"
        if speaker and not MultiPersonaRoleplayController._mprc_structured_speaker_is_narrator(speaker):
            spoken = MultiPersonaRoleplayController._mprc_structured_character_spoken_text(text)
            return f"[CHARACTER: {speaker}]\n{spoken.strip()}"
        return f"[NARRATOR]\n{text.strip()}"

    @staticmethod
    def _mprc_structured_character_spoken_text(text: str) -> str:
        raw = re.sub(r"\s+", " ", str(text or "")).strip()
        if not raw:
            return ""
        quoted = [
            re.sub(r"\s+", " ", match).strip()
            for match in re.findall(r'["“](.+?)["”]', raw, flags=re.DOTALL)
            if re.sub(r"\s+", " ", match).strip()
        ]
        if quoted:
            return " ".join(quoted).strip()
        return raw.strip(" \"“”")

    @staticmethod
    def _mprc_structured_speaker_name(value: Any) -> str:
        speaker = re.sub(r"\s+", " ", str(value or "")).strip()
        if not speaker:
            return ""
        speaker = re.sub(r"^\[?\s*(?:character|speaker)\s*:\s*", "", speaker, flags=re.IGNORECASE).strip()
        speaker = re.sub(r"\s*\]$", "", speaker).strip()
        return speaker.strip(" :")

    @staticmethod
    def _mprc_structured_speaker_is_narrator(speaker: str) -> bool:
        value = str(speaker or "").strip().lower()
        return not value or value in {"narrator", "story narrator", "master narrator"} or value.startswith("narrator #")

    @staticmethod
    def _mprc_structured_text_starts_with_ar_tag(text: str) -> bool:
        return bool(
            re.match(
                r"^\s*\[/?(?:NARRATOR|CHARACTER|CHOICES|AMBIENCE|AMBIENT|MUSIC|FX|SFX|STINGER|AUDIO)\b",
                str(text or ""),
                flags=re.IGNORECASE,
            )
        )

    @staticmethod
    def _mprc_structured_choice_lines(text: str) -> list[str]:
        return [
            choice
            for choice in (
                MultiPersonaRoleplayController._mprc_structured_choice_text(line)
                for line in str(text or "").splitlines()
            )
            if choice
        ]

    @staticmethod
    def _mprc_structured_choice_text(item: Any) -> str:
        if isinstance(item, dict):
            for key in ("text", "content", "label", "title", "action", "choice"):
                value = str(item.get(key) or "").strip()
                if value:
                    item = value
                    break
            else:
                return ""
        choice = re.sub(r"\s+", " ", str(item or "")).strip()
        choice = re.sub(r"^(?:[-*]\s+|\d+[\.)]\s*)", "", choice).strip()
        return choice

    def _remember_mprc_chat_message(self, message: dict[str, str]) -> None:
        role = str((message or {}).get("role") or "").strip().lower()
        content = str((message or {}).get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            return
        self._mprc_chat_history.append({"role": role, "content": content})
        self._mprc_chat_history = self._mprc_chat_history[-16:]

    def _speak_mprc_chat_reply(self, reply: str) -> None:
        text = str(reply or "").strip()
        if not text:
            return
        voice_segments = self._mprc_chat_reply_voice_segments(text)
        self._begin_remote_speech_audio_capture(text)
        token = self._new_worker_token("mprc_tts")
        if not token:
            return
        with self._mprc_tts_state_lock:
            self._mprc_tts_token = token

        def worker():
            logger = getattr(self.context, "logger", None)
            try:
                from core.engine_access import engine_module

                engine = engine_module()
                if getattr(engine, "tts_model", None) is None:
                    init_tts = getattr(engine, "init_tts", None)
                    if not callable(init_tts):
                        if logger is not None:
                            logger.info("[MPRC] TTS init is unavailable; skipping MPRC Play reply speech.")
                        return
                    with self._mprc_tts_lock:
                        if getattr(engine, "tts_model", None) is None and not bool(init_tts()):
                            if logger is not None:
                                logger.info("[MPRC] TTS could not be initialized; skipping MPRC Play reply speech.")
                            return
                if self._worker_should_emit(token) and hasattr(engine, "speak_async"):
                    controller = engine.speak_async(text, text_iterable=list(voice_segments or []))
                    with self._mprc_tts_state_lock:
                        if self._worker_should_emit(token):
                            self._mprc_tts_controller = controller
            except Exception as exc:
                if logger is not None:
                    logger.warning("[MPRC] Could not speak MPRC Play reply: %s", exc)
            finally:
                with self._mprc_tts_state_lock:
                    if self._mprc_tts_token == token:
                        self._mprc_tts_token = ""
                self._finish_worker_token(token)

        if not self._start_daemon_worker(token, worker, name="nc-mprc-tts"):
            with self._mprc_tts_state_lock:
                if self._mprc_tts_token == token:
                    self._mprc_tts_token = ""
            self._cancel_worker_token(token)

    def _mprc_chat_reply_voice_segments(self, text: str) -> list[dict[str, Any]]:
        content = str(text or "").strip()
        if not content:
            return []
        volume_percent = self.mprc_voice_volume_percent()
        volume = volume_percent / 100.0
        backend = self.current_tts_backend()

        def with_volume(segment: dict[str, Any]) -> dict[str, Any]:
            item = dict(segment or {})
            item["voice_volume"] = volume
            item["voice_volume_percent"] = volume_percent
            route = item.get("voice_route")
            if isinstance(route, dict):
                route = dict(route)
            else:
                route = {}
            route["volume"] = volume
            route["volume_percent"] = volume_percent
            item["voice_route"] = route
            return item

        try:
            routed = self.voice_router.split_text_by_persona(
                {
                    "text": content,
                    "tts_backend": backend,
                    "streaming": False,
                }
            )
            segments = [with_volume(item) for item in list((routed or {}).get("segments") or []) if isinstance(item, dict)]
            if segments:
                return segments
        except Exception as exc:
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[MPRC] Could not prepare routed Play voice segments: %s", exc)

        route = {}
        try:
            route = self.voice_router.effective_voice_config(
                {
                    "text": content,
                    "tts_backend": backend,
                    "streaming": False,
                }
            )
        except Exception:
            route = {}
        segment = {
            "text": content,
            "persona_id": str((route or {}).get("persona_id") or ""),
            "display_name": str((route or {}).get("display_name") or ""),
            "voice_path": str((route or {}).get("sample_path") or "") if (route or {}).get("supported") else "",
            "voice_route": route if isinstance(route, dict) else {},
        }
        return [with_volume(segment)]

    def _on_mprc_chat_speaker_changed(self):
        combo = self._controls.get("chat_speaker")
        raw_speaker_id = combo.currentData() if combo is not None and hasattr(combo, "currentData") else ""
        speaker_id = str(raw_speaker_id or "").strip()
        if speaker_id:
            self.session.current_speaker_id = speaker_id
            self.save_state()
            self._set_chat_play_status(f"Current MPRC speaker set to {combo.currentText()}.")
        self._refresh_chat_play_story_engine_cards()

    def _on_mprc_chat_visuals_changed(self, checked: bool):
        self.settings["chat_play_allow_story_visuals"] = bool(checked)
        self.storage.save_settings(self.settings)
        self._set_chat_play_status(
            "MPRC Play story visuals enabled." if checked else "MPRC Play story visuals disabled."
        )

    def _on_mprc_chat_structured_output_changed(self, checked: bool):
        if self._syncing:
            return
        self.settings["chat_structured_output_enabled"] = bool(checked)
        self.storage.save_settings(self.settings)
        scope = self._controls.get("chat_structured_output_scope")
        if scope is not None and hasattr(scope, "setEnabled"):
            scope.setEnabled(bool(checked))
        self._refresh_chat_play_story_engine_cards()
        self._set_chat_play_status(
            "MPRC Play request-scoped Structured JSON enabled." if checked else "MPRC Play Structured JSON disabled."
        )

    def _on_mprc_chat_structured_output_scope_changed(self):
        if self._syncing:
            return
        combo = self._controls.get("chat_structured_output_scope")
        scope = str(combo.currentData() or "every_turn").strip() if combo is not None and hasattr(combo, "currentData") else "every_turn"
        if scope not in {"every_turn", "first_turn"}:
            scope = "every_turn"
        self.settings["chat_structured_output_scope"] = scope
        self.storage.save_settings(self.settings)
        label = "every MPRC Play turn" if scope == "every_turn" else "only the first/opening MPRC Play turn"
        self._refresh_chat_play_story_engine_cards()
        self._set_chat_play_status(f"MPRC Play Structured JSON scope: {label}.")

    def _refresh_remote_controls(self) -> None:
        installed = self._remote_server_installed()
        remote_install = self._controls.get("chat_remote_install")
        if remote_install is not None:
            if hasattr(remote_install, "setVisible"):
                remote_install.setVisible(not installed)
            if hasattr(remote_install, "setEnabled"):
                remote_install.setEnabled(not installed)
        remote_control_keys = (
            "chat_remote_enabled",
            "chat_remote_host_label",
            "chat_remote_host",
            "chat_remote_port_label",
            "chat_remote_port",
            "chat_remote_code_label",
            "chat_remote_code",
            "chat_remote_regenerate_token",
            "chat_remote_status",
        )
        for key in remote_control_keys:
            widget = self._controls.get(key)
            if widget is not None and hasattr(widget, "setVisible"):
                widget.setVisible(installed)
        if not installed:
            remote_enabled = self._controls.get("chat_remote_enabled")
            if remote_enabled is not None and hasattr(remote_enabled, "setChecked"):
                remote_enabled.blockSignals(True)
                remote_enabled.setChecked(False)
                remote_enabled.blockSignals(False)
                if hasattr(remote_enabled, "setEnabled"):
                    remote_enabled.setEnabled(False)
            remote_status = self._controls.get("chat_remote_status")
            if remote_status is not None and hasattr(remote_status, "setText"):
                remote_status.setText("")
            return
        enabled = bool(self.settings.get("remote_enabled", False))
        host = self._remote_host()
        port = self._remote_port()
        code = self._remote_code()
        status = self.remote_status_snapshot()
        remote_enabled = self._controls.get("chat_remote_enabled")
        if remote_enabled is not None and hasattr(remote_enabled, "setChecked"):
            remote_enabled.blockSignals(True)
            remote_enabled.setChecked(enabled)
            remote_enabled.blockSignals(False)
            if hasattr(remote_enabled, "setEnabled"):
                remote_enabled.setEnabled(True)
        remote_host = self._controls.get("chat_remote_host")
        if remote_host is not None and hasattr(remote_host, "setText"):
            remote_host.blockSignals(True)
            remote_host.setText(host)
            remote_host.blockSignals(False)
            remote_host.setEnabled(not enabled)
        remote_port = self._controls.get("chat_remote_port")
        if remote_port is not None and hasattr(remote_port, "setValue"):
            remote_port.blockSignals(True)
            remote_port.setValue(port)
            remote_port.blockSignals(False)
            remote_port.setEnabled(not enabled)
        remote_code = self._controls.get("chat_remote_code")
        if remote_code is not None and hasattr(remote_code, "setValue"):
            remote_code.blockSignals(True)
            try:
                remote_code.setValue(int(code))
            except Exception:
                remote_code.setValue(100000)
            remote_code.blockSignals(False)
            remote_code.setEnabled(True)
        remote_regen = self._controls.get("chat_remote_regenerate_token")
        if remote_regen is not None and hasattr(remote_regen, "setEnabled"):
            remote_regen.setEnabled(True)
        remote_status = self._controls.get("chat_remote_status")
        if remote_status is not None and hasattr(remote_status, "setText"):
            if bool(status.get("running")):
                text = f"Remote: {status.get('url')} | code {code} | clients {status.get('connected_clients', 0)}"
            else:
                text = f"Remote: off | port {port} | code {code}"
            remote_status.setText(text)
            remote_status.setToolTip(f"URL: {status.get('url')}\nPairing code: {code}\nLAN clients only.")

    @staticmethod
    def _chromecast_device_name(device: dict[str, Any]) -> str:
        return str((device or {}).get("name") or (device or {}).get("label") or (device or {}).get("uuid") or "").strip()

    @staticmethod
    def _chromecast_device_tooltip(device: dict[str, Any]) -> str:
        parts = []
        for key, label in (("model_name", "Model"), ("host", "Host"), ("cast_type", "Type"), ("uuid", "UUID")):
            value = str((device or {}).get(key) or "").strip()
            if value:
                parts.append(f"{label}: {value}")
        return "\n".join(parts)

    def _selected_chromecast_device_name(self) -> str:
        combo = self._controls.get("chat_chromecast_device")
        if combo is None:
            return str(self.settings.get("chromecast_device_name") or "").strip()
        try:
            value = str(combo.currentData() or "").strip()
            if value:
                return value
            text = str(combo.currentText() or "").strip()
            if text and text.lower() != "no cast devices":
                return text
        except Exception:
            pass
        return str(self.settings.get("chromecast_device_name") or "").strip()

    def _refresh_chromecast_controls(self) -> None:
        try:
            snapshot = self.remote_chromecast_snapshot()
        except Exception as exc:
            snapshot = {"available": False, "dependency_error": str(exc), "devices": []}
        devices = [dict(item) for item in list(snapshot.get("devices") or []) if isinstance(item, dict)]
        dependency_error = str(snapshot.get("dependency_error") or "").strip()
        selected = str(
            snapshot.get("selected_device")
            or snapshot.get("active_device")
            or self.settings.get("chromecast_device_name")
            or ""
        ).strip()
        with self._state_lock:
            ui_busy = bool(self._chromecast_ui_busy)
            ui_status = str(self._chromecast_ui_status or "").strip()
        bridge_busy = bool(snapshot.get("busy"))
        busy = ui_busy or bridge_busy
        available = bool(snapshot.get("available")) and not dependency_error
        casting = bool(snapshot.get("casting"))

        combo = self._controls.get("chat_chromecast_device")
        if combo is not None and hasattr(combo, "clear"):
            combo.blockSignals(True)
            combo.clear()
            seen: set[str] = set()
            for device in devices:
                name = self._chromecast_device_name(device)
                if not name or name in seen:
                    continue
                combo.addItem(name, name)
                index = combo.count() - 1
                tooltip = self._chromecast_device_tooltip(device)
                if tooltip:
                    combo.setItemData(index, tooltip, QtCore.Qt.ToolTipRole)
                seen.add(name)
            if selected and selected not in seen:
                combo.addItem(selected, selected)
            if combo.count() <= 0:
                combo.addItem("No Cast devices", "")
            index = combo.findData(selected) if selected else -1
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.setEnabled(available and not busy and bool(devices or selected))
            combo.blockSignals(False)

        refresh = self._controls.get("chat_chromecast_refresh")
        if refresh is not None and hasattr(refresh, "setEnabled"):
            refresh.setEnabled(not busy and not dependency_error)
        install = self._controls.get("chat_chromecast_install")
        if install is not None:
            if hasattr(install, "setVisible"):
                install.setVisible(bool(dependency_error))
            if hasattr(install, "setEnabled"):
                install.setEnabled(bool(dependency_error) and not busy)
        start = self._controls.get("chat_chromecast_start")
        selected_for_start = self._selected_chromecast_device_name()
        if start is not None and hasattr(start, "setEnabled"):
            start.setEnabled(available and not busy and bool(selected_for_start))
        stop = self._controls.get("chat_chromecast_stop")
        if stop is not None and hasattr(stop, "setEnabled"):
            stop.setEnabled(not busy and casting)
        label = self._controls.get("chat_chromecast_label")
        if label is not None and hasattr(label, "setEnabled"):
            label.setEnabled(not busy)

        status = self._controls.get("chat_chromecast_status")
        if status is not None and hasattr(status, "setText"):
            if ui_status:
                text = ui_status
            elif dependency_error:
                text = "Cast dependencies missing."
            elif busy:
                text = "Cast action running..."
            elif casting:
                text = f"Casting: {snapshot.get('active_device') or selected_for_start or 'device'}"
            elif devices:
                text = f"Cast ready: {len(devices)} device{'s' if len(devices) != 1 else ''}"
            else:
                text = str(snapshot.get("status") or "Cast ready. Find devices.")
            status.setText(text)
            stream = snapshot.get("stream") if isinstance(snapshot.get("stream"), dict) else {}
            status.setToolTip(
                "\n".join(
                    part for part in (
                        text,
                        f"Stream: {stream.get('url')}" if stream.get("url") else "",
                        dependency_error,
                    ) if part
                )
            )

    def _queue_mprc_chromecast_action(self, action: str, device_name: str = "") -> None:
        normalized = str(action or "").strip().lower()
        if normalized not in {"refresh", "install", "start", "stop", "status"}:
            return
        with self._state_lock:
            if self._chromecast_ui_busy:
                self._chromecast_ui_status = "Chromecast action is already running."
                self._request_ui_refresh()
                return
            self._chromecast_ui_busy = True
            self._chromecast_ui_status = f"Chromecast {normalized} requested..."
        token = self._new_worker_token("mprc_cast")
        if not token:
            with self._state_lock:
                self._chromecast_ui_busy = False
                self._chromecast_ui_status = "Could not start Chromecast worker."
            self._request_ui_refresh()
            return

        def worker():
            message = ""
            try:
                payload: dict[str, Any] = {"action": normalized}
                clean_device = str(device_name or "").strip()
                if clean_device:
                    payload["device_name"] = clean_device
                result = self.remote_chromecast_action(payload)
                accepted = bool((result or {}).get("accepted", False)) if isinstance(result, dict) else False
                cast_state = (result or {}).get("cast") if isinstance(result, dict) else {}
                cast_state = cast_state if isinstance(cast_state, dict) else {}
                message = str((result or {}).get("message") or (result or {}).get("status") or "").strip() if isinstance(result, dict) else ""
                if not message:
                    if normalized == "start" and bool(cast_state.get("casting")):
                        message = f"Casting to {cast_state.get('active_device') or clean_device or 'Chromecast'}."
                    elif normalized == "stop":
                        message = "Chromecast stopped."
                    elif normalized == "refresh":
                        count = len(list(cast_state.get("devices") or []))
                        message = f"Chromecast discovery found {count} device{'s' if count != 1 else ''}."
                    elif normalized == "install":
                        message = "Chromecast dependency install finished."
                    else:
                        message = "Chromecast action finished."
                if not accepted and isinstance(result, dict):
                    message = str(result.get("message") or result.get("error") or message or "Chromecast action was not accepted.")
            except Exception as exc:
                message = f"Chromecast {normalized} failed: {exc}"
                logger = getattr(self.context, "logger", None)
                if logger is not None:
                    logger.warning("[MPRC Chromecast] %s failed: %s", normalized, exc)
            finally:
                with self._state_lock:
                    self._chromecast_ui_busy = False
                    self._chromecast_ui_status = message
                self._finish_worker_token(token)

        if not self._start_daemon_worker(token, worker, name=f"nc-mprc-chromecast-{normalized}"):
            with self._state_lock:
                self._chromecast_ui_busy = False
                self._chromecast_ui_status = "Could not start Chromecast worker."
            self._cancel_worker_token(token)
            self._request_ui_refresh()

    def _on_mprc_chromecast_device_changed(self):
        if self._syncing:
            return
        device_name = self._selected_chromecast_device_name()
        if not device_name:
            return
        if str(self.settings.get("chromecast_device_name") or "").strip() == device_name:
            return
        self.settings["chromecast_device_name"] = device_name
        self.storage.save_settings(self.settings)
        self._refresh_chromecast_controls()

    def _on_mprc_chromecast_refresh_clicked(self):
        if self._syncing:
            return
        self._queue_mprc_chromecast_action("refresh")

    def _on_mprc_chromecast_install_clicked(self):
        if self._syncing:
            return
        self._queue_mprc_chromecast_action("install")

    def _on_mprc_chromecast_start_clicked(self):
        if self._syncing:
            return
        device_name = self._selected_chromecast_device_name()
        if not device_name:
            with self._state_lock:
                self._chromecast_ui_status = "Choose a Chromecast device first."
            self._refresh_chromecast_controls()
            return
        self.settings["chromecast_device_name"] = device_name
        self.storage.save_settings(self.settings)
        self._queue_mprc_chromecast_action("start", device_name)

    def _on_mprc_chromecast_stop_clicked(self):
        if self._syncing:
            return
        self._queue_mprc_chromecast_action("stop")

    def _on_mprc_remote_install_clicked(self):
        if self._syncing:
            return
        self.settings["remote_server_installed"] = True
        self.settings["remote_enabled"] = False
        self._ensure_remote_settings_defaults(installed=True)
        self.storage.save_settings(self.settings)
        self._refresh_remote_controls()
        self._set_chat_play_status("MPRC Remote controls installed. Enable LAN Remote when you want to use the Android companion app.")

    def _on_mprc_remote_enabled_changed(self, checked: bool):
        if self._syncing:
            return
        if not self._remote_server_installed():
            self.settings["remote_enabled"] = False
            self.storage.save_settings(self.settings)
            self._refresh_remote_controls()
            self._set_chat_play_status("Install MPRC Remote controls before enabling the LAN server.")
            return
        self.settings["remote_enabled"] = bool(checked)
        self.storage.save_settings(self.settings)
        self._sync_remote_backend_from_settings()
        status = self.remote_status_snapshot()
        if bool(status.get("running")):
            self._set_chat_play_status(f"MPRC Remote enabled at {status.get('url')}.")
        else:
            self._set_chat_play_status("MPRC Remote disabled.")

    def _on_mprc_remote_endpoint_changed(self):
        if self._syncing:
            return
        if not self._remote_server_installed():
            return
        host_widget = self._controls.get("chat_remote_host")
        port_widget = self._controls.get("chat_remote_port")
        host = str(host_widget.text() if host_widget is not None and hasattr(host_widget, "text") else self._remote_host()).strip() or "0.0.0.0"
        try:
            port = int(port_widget.value() if port_widget is not None and hasattr(port_widget, "value") else self._remote_port())
        except Exception:
            port = DEFAULT_REMOTE_PORT
        port = max(1, min(65535, port))
        changed = host != self._remote_host() or port != self._remote_port()
        self.settings["remote_host"] = host
        self.settings["remote_port"] = port
        self.storage.save_settings(self.settings)
        if changed and bool(self.settings.get("remote_enabled", False)):
            self._sync_remote_backend_from_settings()
        else:
            self._refresh_remote_controls()

    def _on_mprc_remote_code_changed(self):
        if self._syncing:
            return
        if not self._remote_server_installed():
            return
        code_widget = self._controls.get("chat_remote_code")
        try:
            code = self._normalized_remote_code(code_widget.value() if code_widget is not None and hasattr(code_widget, "value") else self._remote_code())
        except Exception:
            code = ""
        if not code:
            code = generate_remote_code()
        changed = code != self._remote_code()
        self.settings["remote_code"] = code
        self.settings.pop("remote_token", None)
        self.storage.save_settings(self.settings)
        if changed and bool(self.settings.get("remote_enabled", False)):
            self._sync_remote_backend_from_settings()
        else:
            self._refresh_remote_controls()
        self._set_chat_play_status(f"MPRC Remote pairing code set to {code}.")

    def _on_mprc_remote_regenerate_token(self):
        if self._syncing:
            return
        if not self._remote_server_installed():
            return
        self.settings["remote_code"] = generate_remote_code()
        self.settings.pop("remote_token", None)
        self.storage.save_settings(self.settings)
        if bool(self.settings.get("remote_enabled", False)):
            self._sync_remote_backend_from_settings()
        else:
            self._refresh_remote_controls()
        self._set_chat_play_status("MPRC Remote pairing code changed. Android clients must reconnect.")

    def _on_mprc_chat_pacing_changed(self, value: str):
        if self._syncing:
            return
        choice = str(value or "").strip()
        if choice:
            self.session.ar_pacing = choice
            self.save_state()
            self._refresh_chat_play_story_engine_cards()
            self._set_chat_play_status(f"Director pacing set to {choice}.")

    def _on_mprc_chat_choice_mode_changed(self):
        if self._syncing:
            return
        combo = self._controls.get("chat_director_choice_mode")
        mode = str(combo.currentData() or "choices").strip() if combo is not None and hasattr(combo, "currentData") else "choices"
        if mode not in {"choices", "ask_next_move"}:
            mode = "choices"
        self.settings["chat_choice_mode"] = mode
        self.storage.save_settings(self.settings)
        self._refresh_chat_play_state_sidebar()
        label = 'ask "What\'s your next move?" without fixed choices' if mode == "ask_next_move" else "offer fixed choices at the end"
        self._set_chat_play_status(f"Director choice mode set to {label}.")

    def _on_mprc_director_action(self, action: str):
        label = {
            "advance": "Advance scene requested.",
            "summarize": "Story summary requested.",
            "repair": "Continuity repair requested.",
        }.get(str(action or "").strip().lower(), "Director action requested.")
        self._append_chat_play_line("Director", label, role="system")
        self._set_chat_play_status(f"{label} Dedicated director execution is the next wiring step.")

    def _guide_speech_command(self) -> dict[str, Any] | None:
        if self._guide_speech_command_checked:
            return self._guide_speech_command_cache
        self._guide_speech_command_checked = True
        system = platform.system().lower()
        if system == "windows":
            for executable in ("powershell.exe", "powershell", "pwsh.exe", "pwsh"):
                program = shutil.which(executable)
                if not program:
                    continue
                script = (
                    "$text = [Console]::In.ReadToEnd(); "
                    "Add-Type -AssemblyName System.Speech; "
                    "$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                    "$speaker.Speak($text)"
                )
                self._guide_speech_command_cache = {
                    "program": program,
                    "arguments": ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                    "stdin": True,
                }
                return self._guide_speech_command_cache
        if system == "darwin":
            program = shutil.which("say")
            if program:
                self._guide_speech_command_cache = {"program": program, "arguments": [], "stdin": False}
                return self._guide_speech_command_cache
        for executable, arguments in (("spd-say", ["--wait"]), ("espeak", [])):
            program = shutil.which(executable)
            if program:
                self._guide_speech_command_cache = {"program": program, "arguments": arguments, "stdin": False}
                return self._guide_speech_command_cache
        self._guide_speech_command_cache = None
        return None

    def _guide_speech_row(self, title: str, text_provider):
        from PySide6 import QtWidgets

        row = QtWidgets.QHBoxLayout()
        button = QtWidgets.QPushButton(f"Read {title}")
        slug = self.storage.story_id(title)
        button.setObjectName(f"mprc_guide_read_{slug}")
        if self._guide_speech_command() is None:
            button.setEnabled(False)
            button.setToolTip("Guide speech is unavailable because no supported system speech command was found.")
        else:
            button.setToolTip(f"Read the {title} guide section aloud.")
            button.clicked.connect(
                lambda _checked=False, section=title, provider=text_provider: self._speak_guide_section(
                    section,
                    provider() if callable(provider) else provider,
                )
            )
        row.addWidget(button)
        row.addStretch(1)
        return row

    def _set_guide_speech_status(self, message: str) -> None:
        label = self._controls.get("guide_speech_status")
        if label is not None and hasattr(label, "setText"):
            label.setText(str(message or ""))

    def _speak_guide_section(self, title: str, text: str) -> None:
        if self.is_shutdown():
            return
        command = self._guide_speech_command()
        if command is None:
            self._warn("Guide Speech", "No supported system speech command was found.")
            return
        speech_text = "\n\n".join(part for part in (str(title or "").strip(), str(text or "").strip()) if part).strip()
        if not speech_text:
            self._set_guide_speech_status("Nothing to read.")
            return
        self._stop_guide_speech()
        process = QtCore.QProcess(self._widget if isinstance(self._widget, QtCore.QObject) else None)
        self._guide_speech_process = process
        try:
            process.finished.connect(lambda *_args, p=process: self._on_guide_speech_finished(p))
            process.errorOccurred.connect(lambda *_args, p=process: self._on_guide_speech_finished(p))
        except Exception:
            pass
        arguments = list(command.get("arguments") or [])
        if not command.get("stdin"):
            arguments.append(speech_text)
        try:
            process.start(str(command.get("program") or ""), arguments)
            if command.get("stdin"):
                process.write(speech_text.encode("utf-8"))
                process.closeWriteChannel()
            self._set_guide_speech_status(f"Reading: {title}")
        except Exception as exc:
            self._guide_speech_process = None
            self._set_guide_speech_status("Guide speech failed.")
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[MPRC] Guide speech failed: %s", exc)

    def _on_guide_speech_finished(self, process=None) -> None:
        if process is not None and process is not getattr(self, "_guide_speech_process", None):
            try:
                process.deleteLater()
            except Exception:
                pass
            return
        if self._guide_speech_process is not None:
            try:
                self._guide_speech_process.deleteLater()
            except Exception:
                pass
        self._guide_speech_process = None
        self._set_guide_speech_status("Guide speech stopped.")

    def _stop_guide_speech(self) -> None:
        process = getattr(self, "_guide_speech_process", None)
        self._guide_speech_process = None
        if process is not None:
            try:
                process.kill()
                process.deleteLater()
            except Exception:
                pass
        self._set_guide_speech_status("")

    def _install_tooltips_and_refine(self):
        tooltip_map = {
            "enabled": "Turn MPRC prompt and voice routing on or off. Off restores normal NC chat behavior, normal chat history, and normal voice routing.",
            "active": "Choose the persona that currently shapes MPRC replies, voice routing, character preview, and Visual Reply prompts. In AR Play, Focus can temporarily direct a turn without changing this saved active persona.",
            "ar_mode": "Switch MPRC into AlternativeReality, a narrator-led interactive audiobook/adventure runtime. AR mode expects [NARRATOR], [CHARACTER: Name], [CHOICES], and story audio tags.",
            "chat_start": "Arm the MPRC Play runtime. If an active story exists, the narrator opens or continues that story inside the isolated Play feed instead of normal NC chat.",
            "chat_pause": "Stop the current MPRC Play speech/playback path. Use this when you want to interrupt spoken story output before sending another action.",
            "chat_restart": "Restart the active story from the current setup. This clears story/character memory for the active run and removes auto-created chat characters, while keeping saved personas and saved story files.",
            "chat_clear": "Clear the visible Play transcript. This does not delete personas, story setup, saved memory, or normal NC chat history.",
            "chat_float": "Move the MPRC Play surface into its own floating window, or dock it back into the addon tab when already floating.",
            "chat_export_structured_output": "Export one strict JSON Schema file for LM Studio or another provider Structured Output field. The schema is built from the current MPRC cast.",
            "chat_story_font_size_label": "Font-size setting for the MPRC Story Feed response window.",
            "chat_story_font_size": "Set the font size used by the MPRC Story Feed response window.",
            "chat_remote_install": "Install optional LAN Remote controls for the Android companion app. This does not start the server.",
            "chat_remote_enabled": "Enable the local LAN-only MPRC Remote HTTP backend for the Android companion app.",
            "chat_remote_host": "Bind host for the remote backend. Use 0.0.0.0 for LAN access; requests are still limited to local/private clients.",
            "chat_remote_port": "TCP port for the remote backend. Default is 8765.",
            "chat_remote_code": "Six-digit pairing code for the Android remote app. You can type your own number.",
            "chat_remote_regenerate_token": "Generate a new six-digit remote pairing code. Android clients must reconnect with the new code.",
            "chat_remote_status": "Shows the remote LAN URL, six-digit pairing code, and recent client count.",
            "chat_structured_output": "Attach the MPRC story JSON Schema directly to MPRC Play chat requests only. This does not affect Master Story, persona generation, normal chat, or Visual Reply.",
            "chat_structured_output_scope": "Choose whether request-scoped Structured JSON is used on every MPRC Play turn or only on the opening turn.",
            "chat_runtime_splitter": "Resizable divider between the Story Feed/player action area and the scene-state sidebar.",
            "chat_story_feed_box": "Isolated MPRC story transcript. It shows narrator/character output, choices, selected player actions, and restored memory beats without writing into normal NC chat.",
            "chat_transcript": "Live MPRC Story Feed. Spoken narrator/character chunks are derived from this structured story text and routed by [NARRATOR] and [CHARACTER: Name] tags.",
            "chat_player_action_box": "Player input area for acting, speaking, directing the scene, or asking out-of-character questions inside the MPRC Play runtime.",
            "chat_input": "Type the next player action, dialogue, director note, or OOC request. Choice clicks can fill this field; double-clicking a choice sends it.",
            "chat_use_ar": "Use AlternativeReality prompting for this Play turn. Keep enabled for narrator-led story play; disable only when testing non-AR MPRC behavior.",
            "chat_visuals": "Allow this Play turn to request story-scene Visual Reply images when persona visual settings, cooldowns, and provider readiness allow it.",
            "chat_send": "Send the Player Action to the MPRC-only turn pipeline. If speech is still playing, MPRC stops it before continuing so replies do not overlap.",
            "chat_visual_prompt_debug_box": "Debug-only breakdown of the latest MPRC Visual Reply prompt request. Use this to see which story reply, AR state, persona visual settings, and fallback prompt contributed to the final image prompt.",
            "chat_visual_prompt_debug": "Read-only Visual Reply prompt audit for MPRC Play. It shows the final image prompt plus the current story reply, AR state inputs, persona visual settings, and hidden LLM payload when available.",
            "chat_intent_label": "Intent controls how MPRC interprets the Player Action before building the Play prompt.",
            "chat_intent": "Auto lets MPRC infer Act, Say, Direct, or OOC from the text. Choose a mode only when you want to force how the next Player Action is framed.",
            "chat_speaker_label": "Focus chooses whose perspective or scope the next Player Action targets.",
            "chat_speaker": "Focus for the next Play turn. Player means user/director action; Narrator means scene-level direction; a character means the player acts or speaks through that character for this turn.",
            "chat_status": "Short Play status line for isolated runtime state, send locks, restore notices, visual request state, and story start/stop messages.",
            "chat_scene_state_box": "Compact current scene card used as prompt context: scene, location, time, mood, objective, and active speaker.",
            "chat_scene_state": "Current scene fields carried into the next MPRC Play prompt.",
            "chat_active_speaker": "Resolved active speaker for the current story moment. This can differ from Active persona when Focus or story routing chooses another character.",
            "chat_story_state_tabs": "Cast, Events, and Choices for the current Play scene. These tabs expose enough structured state to understand who is present, what just happened, and what can be done next.",
            "chat_present_characters": "Characters currently present in the story scene. [Auto Chat] entries were created from story labels and are removed by Restart Story.",
            "chat_recent_events": "Recent story events remembered by MPRC. These are compact visible continuity beats, not hidden chain-of-thought.",
            "chat_next_actions": "Current player choices. Click a choice to copy it into Player Action; double-click or press Enter to send it immediately.",
            "chat_director_box": "Director controls for pacing, tone, agency, and maintenance actions that steer the next Play request without editing the story draft.",
            "chat_director_pacing_label": "Pacing controls how quickly the narrator moves from description to consequence or choice.",
            "chat_director_pacing": "Pacing hint for the next Play request. Balanced keeps normal rhythm; faster modes reach choices sooner; slower/audiobook modes allow more narration.",
            "chat_director_tone_label": "Tone controls the emotional color requested for the next scene beat.",
            "chat_director_tone": "Tone hint for the next Play request. Keep current preserves the story's present mood; other choices nudge the narrator for the next beat.",
            "chat_director_agency_label": "Agency controls how strongly MPRC constrains player options and consequences.",
            "chat_director_agency": "Agency hint for the next Play request. Guided offers clear options; Open leaves more room; Strict consequences asks the narrator to enforce outcomes more firmly.",
            "chat_director_choice_mode_label": "Choose whether story replies end with fixed choices or a freeform move prompt.",
            "chat_director_choice_mode": "Offer choices guarantees [CHOICES] at the end. Ask next move removes fixed choices and ends with a freeform prompt.",
            "chat_advance_scene": "Queue a director action asking the narrator to move the scene forward while preserving current continuity.",
            "chat_summarize": "Queue an out-of-character story summary request inside the Play feed.",
            "chat_repair": "Queue a director repair request asking MPRC to restate/repair confusing story state, choices, or speaker routing.",
            "character_preview_panel": "Current-character dashboard. It follows the active persona or current speaker when tracking is enabled, and gives quick access to avatar, save/import/export, duplicate, and edit actions.",
            "current_character_image": "The active persona picture. This updates when the active persona changes or when Track current speaker in character preview follows a story speaker.",
            "current_character_name": "Display name of the persona currently shown in the preview panel.",
            "current_character_role": "Role/archetype for the previewed persona, such as narrator, companion, story character, or auto-created chat participant.",
            "current_character_meta": "Quick status for the current character: ID, behavior, memory scope, voice readiness, visual readiness, and whether an AR profile is active.",
            "current_character_story": "Shows which active and saved Master Stories include this character, and whether the character is active/speaking in the current story.",
            "current_character_quick_status": "Status messages from quick persona actions such as save, import, duplicate, avatar changes, and editor jumps.",
            "current_character_view_mode": "Choose whether the Current Character card shows only personas linked to the loaded story roster or all saved personas.",
            "character_roster_frame": "Horizontal preview strip for the story/persona roster. It is a visual selector, separate from the Registry list.",
            "character_roster_strip": "Scroll through character picture tiles. Click a tile to switch the active persona.",
            "character_roster_content": "Container for the current story/persona picture tiles.",
            "quick_change_avatar": "Choose a new avatar image for the current character.",
            "quick_save_persona": "Save persona, session, and addon settings immediately.",
            "quick_import_persona": "Import persona JSON from disk. This uses the same import flow as the Registry tab.",
            "quick_export_personas": "Export all current personas to a JSON file.",
            "quick_duplicate_persona": "Duplicate the current character as a new editable persona.",
            "quick_edit_persona": "Jump to the Persona Editor for the current character.",
            "show_character": "Keep the character preview panel synchronized with the current speaker. This is only the preview/highlight behavior; story-scene images are controlled by each persona's Visual tab.",
            "persona_list": "All saved personas. Select one to edit it or make it active. [Story] means linked to a saved/active story; [Auto Chat] means MPRC created it from a new character label in the current chat.",
            "add_persona": "Create a new neutral editable persona.",
            "duplicate_persona": "Copy the selected persona as a starting point for a variant.",
            "delete_persona": "Delete the selected persona. At least one persona is always kept.",
            "import_personas": "Import personas from a JSON file.",
            "export_personas": "Export all personas to a JSON file.",
            "reset_defaults": "Restore the bundled neutral defaults and clear the current roleplay scene.",
            "load_default_scenario": "Load the bundled touch-and-go group scenario with all default personas represented.",
            "persona_id": "Stable local ID for this persona. Keep it short and lowercase. Right-click to refine if needed.",
            "persona_enabled": "Enable or disable this persona without deleting it. Disabled personas are kept in storage but ignored by normal routing and story cast selection.",
            "master_narrator": "Mark this persona as a favorite Master narrator. Master narrators are numbered in selectors, prioritized for narrator auto-pick, and protected from deletion.",
            "display_name": "Name shown in the Roleplay UI and prompts. Right-click to refine.",
            "role": "Short archetype or role, such as mentor, narrator, technician, or explorer. Right-click to refine.",
            "description": "Compact visible description of who this persona is. Right-click to refine this Short Description field.",
            "character_image": "Preview of the selected character picture.",
            "character_image_path": "Path to the active persona picture. MPRC stores only the path.",
            "character_image_browse": "Choose a character picture from your drive.",
            "character_image_generate": "Generate a character picture from this persona's prompt/description through Visual Reply.",
            "character_image_clear": "Clear this persona's character picture path.",
            "system_prompt": "Core persona instruction injected into chat when roleplay is enabled. Right-click to refine.",
            "ar_profile_enabled": "Use this persona's AR-specific description and system prompt when AlternativeReality mode is active.",
            "ar_description": "AlternativeReality-only character description. Right-click to refine into cinematic adventure style.",
            "ar_system_prompt": "AlternativeReality-only persona instruction. Right-click to refine for AR pacing, intimacy, and adventure tone.",
            "speaking_style": "How this persona should sound in normal replies. Right-click to refine.",
            "allowed_tone": "Tone boundaries for this persona. Right-click to refine.",
            "response_length": "Preferred length of replies for this persona.",
            "temperature_hint": "Optional style note for randomness or energy. Right-click to refine.",
            "memory_scope": "Controls how the prompt frames persona-specific continuity.",
            "behavior_mode": "Sets the persona's roleplay framing.",
            "tags": "Comma-separated tags for organizing personas. Right-click to refine.",
            "guide_read_all": "Read every section of the Guide tab aloud using the local system speech helper, if one is available.",
            "guide_stop_speech": "Stop Guide tab speech playback.",
            "guide_speech_status": "Shows whether the Guide tab is speaking, stopped, or unavailable on this system.",
            "voice_enabled": "Use this persona's voice sample when roleplay mode is enabled. If disabled or unsupported, NC falls back to the active TTS backend's normal voice.",
            "narrator_persona": "Choose which persona voice is used for [NARRATOR]. Auto uses the Story Narrator/narrator-tagged persona, then falls back to the active persona.",
            "voice_follow_active": "Keep the Voice tab locked to the current active persona. Disable this only when you intentionally want to edit another persona's voice.",
            "voice_current_persona": "Shows the exact persona whose voice fields will be changed.",
            "voice_persona": "Choose which persona's voice settings are shown in the fields below.",
            "voice_backend": "Backend preference. Inherit is safest; overrides warn if they do not match the active NC TTS backend.",
            "voice_sample": "Path to a local reference audio file. MPRC stores only the path. Right-click to refine path text only if needed.",
            "voice_sample_picker": "Fast picker for audio files in the local voices folder. Selecting one writes its full path into Voice sample path.",
            "voice_browse": "Browse for a local voice sample.",
            "voice_clear": "Clear the voice sample path.",
            "voice_preset": "Optional backend-specific voice preset name. Right-click to refine.",
            "voice_language": "Optional language hint for backends that support per-request language.",
            "voice_test": "Check the selected voice routing setup and show warnings if it cannot be applied.",
            "voice_warning": "Voice routing status and fallback warnings.",
            "session_mode": "Choose how active personas participate in the scene.",
            "scene_title": "Short name for the current scene. Right-click to refine.",
            "location": "Current scene location. Right-click to refine.",
            "time_of_day": "Current time, era, or timing cue. Right-click to refine.",
            "mood": "Current mood or atmosphere. Right-click to refine.",
            "objective": "Current scene goal or task. Right-click to refine.",
            "scene_summary": "Compact visible scene continuity summary. Right-click to refine.",
            "roster": "Read-only list of enabled personas in the current group.",
            "auto_select": "Allow the addon to frame speaker selection automatically in multi-character modes.",
            "next_speaker": "Manual next speaker for group or narrator modes.",
            "continuity": "Include continuity guidance in the roleplay prompt.",
            "update_scene": "Keep compact recent event summaries after assistant replies.",
            "ar_enabled": "Switch MPRC into AlternativeReality from inside the dedicated AR tab.",
            "ar_use_persona_profiles": "When enabled, AR uses each persona's AR description and AR system prompt instead of normal companion/tabletop wording.",
            "ar_pacing": "AlternativeReality pacing. Audiobook mode allows longer narration before asking the user.",
            "ar_interaction": "How often AlternativeReality should pause for player choices.",
            "ar_tension": "Compact 0-10 tension hint for the AR prompt.",
            "ar_current_scene": "Current AR scene beat used when the player says continue.",
            "ar_location": "Current AR location carried into the next Play prompt. Keep it concise and visible, not secret.",
            "ar_time_of_day": "Current AR time, lighting, era, or timing cue carried into the next Play prompt.",
            "ar_mood": "Current AR mood/atmosphere hint. This steers tone but should stay short enough to remain prompt-safe.",
            "ar_story_goal": "Current story objective used by Play and Continue requests.",
            "ar_active_characters": "Comma-separated persona IDs active in the AR scene. Characters still speak only when relevant.",
            "ar_player_intent": "Latest player intent/action summary for AR continuity.",
            "ar_pending_choices": "Optional player choices shown or remembered by AR mode.",
            "ar_recent_events": "Read-only compact AR event history. These are visible continuity beats, not hidden reasoning.",
            "ar_seed": "Copy scene, location, mood, time, and objective from the regular Session tab into AR state.",
            "ar_fill_profiles": "Fill missing AR descriptions and AR system prompts from the bundled cinematic adventure defaults.",
            "ar_clear": "Clear AR state and reseed safe defaults if AR mode is active.",
            "story_status": "Readable status of the active story pipeline: story, AR, narrator, personas, memory, voices, visuals, and AudioFX.",
            "story_first_run": "One-click first-run path: load the demo story, validate it, test AudioFX/Visual Reply, and queue Continue.",
            "story_template": "Choose a polished built-in story template to load into AR.",
            "story_load_template": "Load the selected built-in template with narrator, one character, memory seed, visual profile, and AudioFX cue.",
            "story_export_bundle": "Export the current story, linked cast, narrator setup, memory snapshot, AudioFX links, visual settings, and voice routing as a portable JSON bundle.",
            "story_import_bundle": "Import a portable MPRC story bundle and apply it after saving a recovery backup.",
            "story_export_status": "Story Library Export summary. Green option rows have data available to save into the portable story package.",
            "story_export_button": "Create a zip story package from the selected Story Library Export sections. Selected avatar, voice, and AudioFX files are copied into the package when available.",
            "story_import_button": "Import a zip story package, extract assets into this addon's runtime assets folder, remap file paths, and protect existing personas with unique imported IDs.",
            "story_export_preview": "Preview which selected Story Library Export sections currently have data before creating a package.",
            "story_status_refresh": "Recalculate the runtime status and voice routing inspector.",
            "story_validate": "Check the active story for broken narrator, persona, voice, image, memory, AudioFX, and schema/resource issues.",
            "story_restore_backup": "Restore the latest recovery snapshot made automatically before Apply Draft changes story/persona state.",
            "story_reset_only": "Clear only the active story runtime memory and recent scene state without deleting saved personas or unrelated stories.",
            "story_demo": "Load a small local demo story with a narrator, one character, Visual Reply trigger settings, AudioFX cue, and story memory seed.",
            "story_test_narrator_voice": "Queue a short narrator-labelled voice test through the normal chat/TTS path.",
            "story_test_character_voice": "Queue a short character-labelled voice test for the selected or active story character.",
            "story_test_visual": "Request one Visual Reply image using the active story character's visual profile.",
            "story_test_audio": "Play one ready AudioFX cue, creating the local test cues first if needed.",
            "story_validation": "Validation results are shown here so setup problems are visible without opening logs.",
            "story_repair_narrator": "Lock the current story to a usable narrator persona.",
            "story_repair_voice": "Browse for a voice sample for the story narrator or selected voice persona.",
            "story_repair_audio": "Remove missing-file AudioFX items from the active AudioFX list so validation stops routing to broken cues.",
            "story_repair_image": "Browse for a replacement image path for the first broken story persona image or the active persona.",
            "story_repair_memory": "Create or refresh the active story's memory snapshot.",
            "story_repair_personas": "Create safe placeholder personas for missing story persona links.",
            "story_repair_overrides": "Remove persona overrides that point to missing personas or malformed data.",
            "story_voice_routes": "Shows which persona and voice sample each narrator/character role will route to.",
            "story_preview_next": "Preview the next AR prompt request using Continue as the next player action.",
            "story_explain_next": "Explain narrator, active character, voice, memory, Visual Reply, and AudioFX routing for the next turn.",
            "story_next_inspector": "Next-turn inspector output for prompt preview and routing explanation.",
            "story_pinned_facts": "Pinned story facts inserted into long memory context. Keep one compact fact per line.",
            "story_memory_list": "Recent addon-local story memories. Select one to inspect or delete it.",
            "story_memory_refresh": "Reload pinned facts and recent memory from addon storage.",
            "story_memory_save_pins": "Save the pinned facts field into addon-local long memory.",
            "story_memory_delete": "Delete the selected recent memory event and rebuild compact memory indexes.",
            "story_memory_reset_character": "Clear character-specific memory summaries while keeping story events.",
            "story_memory_reset_story": "Clear story event memory while keeping pinned facts.",
            "story_event_log": "Readable reasons for skipped or failed story actions, such as missing AudioFX, unsupported voice backend, cooldowns, or missing memory.",
            "story_clear_log": "Clear the readable skipped-action log.",
            "master_story_prompt": "Describe the full story you want. MPRC asks the current chat provider to draft personas and session state from this.",
            "master_story_visual_direction": "Optional visual art direction for generated persona appearances and avatar portraits.",
            "master_story_sfw_mode": "Keep generated Master Story drafts non-explicit. Romance and mature emotional themes are allowed, but explicit sexual content is avoided.",
            "master_story_native_persona_count": "Target number of story-native persona profiles the Master generator should draft when the prompt does not already name them.",
            "master_story_max_created_characters": "Hard limit for how many new personas can be created from one Master Story apply.",
            "master_story_allow_exceed_max_created_characters": "Override the Master Story apply limit and allow more new personas than Maximum created characters.",
            "master_story_use_existing_personas": "Let the Master generator consider your already saved personas and let Apply Draft map story characters onto them.",
            "master_story_use_ar": "Build the story for AlternativeReality mode with AR scene state and AR persona profiles.",
            "master_story_auto_create": "Create missing personas from the story draft when no existing persona matches.",
            "master_story_update_existing": "Update matching personas with non-empty story fields while preserving voice samples and images unless explicitly provided.",
            "master_story_auto_avatars": "After applying a story, request avatar pictures for newly created personas through the existing Visual Reply service.",
            "master_story_avatar_style_sheets": "Optional and default off. After new personas have avatar images, request character reference sheets for image-to-image capable Visual Reply runtimes.",
            "master_story_clear_memory": "Clear old MPRC long memory and start a fresh roleplay session before applying this draft.",
            "master_story_generate": "Generate a reviewable JSON story setup from the prompt.",
            "master_story_apply": "Review character links, then apply the JSON draft to MPRC personas and the current roleplay session.",
            "master_story_save": "Save the current draft as a reusable story in addon storage.",
            "master_story_restart": "Clear current story memory, recent scene state, and Master Story links while keeping saved personas and saved story files.",
            "master_story_draft": "Review or edit the generated story JSON before applying or saving.",
            "master_story_list": "Saved Master Story setups. Loading one relinks existing personas or creates missing ones when enabled.",
            "master_story_load": "Load and apply the selected saved story.",
            "master_story_delete": "Delete the selected saved story from addon storage.",
            "master_story_status": "Status for story generation, save, load, and persona linking.",
            "master_story_image_frame": "Framed 180x180 story image preview for the selected saved story.",
            "master_story_image": "Story image preview. MPRC creates a local fallback cover when a saved story has no image yet.",
            "audio_intro": "Overview for the Audio tab. Story Sounds turns written audio tags into background playback when a matching ready AudioFX item exists.",
            "audio_story_box": "Top-level on/off control for story-triggered AR sounds. Keep this enabled when you want ambience, music, FX, and stingers to play from story tags.",
            "audio_story_note": "Explains what Story Sounds affects. Manual preview buttons still work even when story-triggered playback is disabled.",
            "audiofx_volume_label": "Volume for MPRC AudioFX playback.",
            "audiofx_volume": "Set the volume for addon AudioFX playback. This affects automatic story/background sounds and manual AudioFX previews, but not NC's main TTS voice volume.",
            "audiofx_volume_value": "Current AudioFX volume percentage.",
            "chat_voice_volume_label": "Volume for MPRC-routed Play voice.",
            "chat_voice_volume": "Set the volume for addon-routed story voice in the Play tab. This does not change AudioFX/background sounds.",
            "chat_voice_volume_value": "Current MPRC Play voice volume percentage.",
            "chat_voice_volume_popout": "Open a wider voice-volume control if the toolbar slider is too compact.",
            "audiofx_test_mode": "Create and keep a small local test AudioFX set active for checking tag playback without needing a full external sound library.",
            "audiofx_create_test_sounds": "Generate local WAV test sounds and register them as ready AudioFX items for Ambience, Music, FX, and Stinger tag testing.",
            "audiofx_play_test_tag": "Manually trigger the exact test tag [AMBIENCE: pub ambient]. Use this to confirm playback before relying on generated story text.",
            "audio_prompt_box": "Local prompt builder for reusable audio-generation prompts. It does not generate audio by itself; it creates descriptions you can save or use elsewhere.",
            "audio_story_sounds": "Enable or disable AR story-triggered audio playback. When enabled, tags like [AMBIENCE: pub ambient] are removed from TTS and used to play matching AudioFX files.",
            "audio_sound_description": "Describe the music, ambience, FX, emotion, environment, or sound you want. This can become a saved prompt or AudioFX description. Right-click to refine.",
            "audio_examples": "Example Sound Description inputs you can type or adapt.",
            "audio_type": "Choose how the description should be shaped and categorized: Auto, Music, Ambience, FX, or Stinger.",
            "audio_create_prompt": "Create a polished cinematic Suno-style audio prompt from the description.",
            "audio_prompt_output": "Editable generated prompt. Right-click to refine or edit by hand.",
            "audio_copy_prompt": "Copy the generated audio prompt to the clipboard.",
            "audio_save_prompt": "Save the generated prompt in addon settings for later reuse.",
            "audio_save_item_description": "Store the generated prompt as the addon audio item description and update/create the selected AudioFX item.",
            "audio_clear_prompt": "Clear the audio prompt builder fields.",
            "audio_variation_ambience": "Generate an environment-first variation from the current description.",
            "audio_variation_horror": "Generate a darker horror version from the current description.",
            "audio_variation_calm": "Generate a calmer version from the current description.",
            "audio_variation_action": "Generate a more action-focused version from the current description.",
            "audio_saved_box": "Saved prompt manager for prompts stored in addon settings.",
            "audio_saved_count": "Shows how many audio prompts are saved.",
            "audio_saved_prompts": "Saved audio prompts. Double-click a prompt to load it into the editor.",
            "audio_load_saved": "Load the selected saved prompt into the description, type, and output fields.",
            "audio_delete_saved": "Delete the selected saved prompt from addon settings.",
            "audiofx_box": "Manage reusable AudioFX items that connect a sound description to a local audio file. Ready items are available to AR prompts and story audio tags.",
            "audiofx_count": "Shows how many AudioFX items are saved, how many have ready files, and how many story audio cues are available.",
            "audiofx_list": "AudioFX items. Green text means the attached local audio file exists and is indexed for story use. Double-click an item to load its description into the prompt builder.",
            "audiofx_status": "Shows the selected AudioFX file path and ready/missing status, plus import results after loading a sound pack.",
            "audiofx_create": "Create a new AudioFX item from the current Sound Description and generated prompt.",
            "audiofx_import_pack": "Import a prepared AudioFX sound pack folder containing mprc_audio_pack.json or audio_pack.json. This bulk-adds ready sounds, updates existing matching cues, and avoids duplicate entries.",
            "audiofx_add_file": "Attach or replace the local audio file for the selected AudioFX item and add it to the story audio database.",
            "audiofx_play": "Play the selected AudioFX file as a manual preview. This works even when Story Sounds is off.",
            "audiofx_load": "Load the selected AudioFX description and prompt into the prompt builder.",
            "audiofx_delete": "Delete the selected AudioFX item from addon settings. The audio file on disk is not deleted.",
            "reset_scene": "Clear current scene state while keeping the active persona.",
            "export_session": "Export the current roleplay session JSON.",
            "import_session": "Import a roleplay session JSON.",
            "visual_enabled": "Allow this persona to request story-scene images in the existing Visual Reply window.",
            "visual_mode": "Controls when this persona may automatically request Visual Reply story images.",
            "visual_mode_note": "Explains the selected automatic image trigger.",
            "visual_provider": "Visual Reply provider override. Inherit uses NC's current Visual Reply provider.",
            "visual_model": "Optional image model override. Right-click to refine only if the model name is descriptive text.",
            "visual_size": "Image size override for this persona.",
            "visual_style": "Persona-specific visual style preset.",
            "visual_character": "Visual identity and appearance for this persona. Right-click to refine.",
            "visual_clothing": "Recurring clothing, tools, or props. Right-click to refine.",
            "visual_environment": "Environment style for images. Right-click to refine.",
            "visual_negative": "Things image generation should avoid. Right-click to refine.",
            "visual_continuity": "Preserve recurring character and scene details across image prompts.",
            "visual_scene": "Include the latest roleplay scene summary in image prompts.",
            "visual_speaker": "Include active speaker identity in image prompts.",
            "visual_interval": "When Visual mode is auto_every_n_replies, generate after this many assistant replies.",
            "visual_cooldown": "Minimum seconds between automatic image requests.",
            "visual_max_auto": "Maximum automatic images allowed in one roleplay session. Zero means no auto limit.",
            "visual_auto_show": "Show the existing Visual Reply dock when an image is requested.",
            "visual_generate": "Request a story-scene image in the existing Visual Reply window using the selected persona's effective image prompt.",
            "visual_preview": "Show the generated image prompt in the debug panel without requesting an image.",
            "debug_prompt": "Effective persona prompt/context used by MPRC for the current or last routed request. Use this to verify persona, AR, memory, scene, and instruction text before blaming the model.",
            "debug_visual": "Effective Visual Reply payload/prompt for the current persona or last story image request. Use this to inspect provider, model, size, persona visual fields, scene context, and skip reasons.",
            "debug_voice": "Effective voice routing config for the current or last persona route. Use this to verify persona ID, selected voice sample, backend support, route reason, warning, and fallback behavior.",
            "debug_state": "Compact JSON state snapshot for MPRC: session, AR state, active persona, memory, story links, and runtime flags that feed prompt/routing decisions.",
            "debug_clear": "Clear the Debug tab panes. This only clears the displayed debug output, not story state, memory, generated images, or Visual Reply settings.",
            "debug_visual_calls": "Live Visual Reply audit log for MPRC. It shows queued, accepted, skipped, and failed image requests with persona, reason, source, and prompt preview.",
            "debug_visual_calls_copy": "Copy the Visual Reply call log to the clipboard.",
            "debug_visual_calls_clear": "Clear the MPRC Visual Reply call log. This does not delete generated images or change Visual Reply settings.",
        }
        for key, tooltip in tooltip_map.items():
            widget = self._controls.get(key)
            if widget is not None and hasattr(widget, "setToolTip"):
                widget.setToolTip(tooltip)

        refine_map = {
            "persona_id": ("Persona ID", "Refine into a stable lowercase identifier. Use words separated by underscores."),
            "display_name": ("Display Name", "Refine into a short user-facing character name."),
            "role": ("Role / Archetype", "Refine into a compact role or archetype label."),
            "description": ("Short Description", "Refine into a concise persona description. Keep it short and prompt-ready."),
            "character_image_path": ("Character Picture Path", "Clean up the local image path only. Do not invent a file path."),
            "system_prompt": ("System Prompt", "Refine into a clear persona prompt. Preserve all constraints and roleplay intent."),
            "ar_description": ("AR Description", "Refine into a cinematic, suggestive, non-explicit adventure character description."),
            "ar_system_prompt": ("AR System Prompt", "Refine into AlternativeReality persona instructions: adventurous, intimate, consensual, stylish, and not tabletop/DnD-specific."),
            "master_story_prompt": ("Master Story Prompt", "Refine into a complete story setup request with premise, tone, characters, scene, objective, and pacing. Keep it non-explicit and user-agency friendly."),
            "master_story_visual_direction": ("Avatar Visual Direction", "Refine into concise art direction for persona portraits. Include genre, costume, mood, and medium without over-constraining the image model."),
            "master_story_draft": ("Master Story JSON Draft", "Clean up this story JSON while preserving schema, persona IDs, and all user-authored story intent."),
            "speaking_style": ("Speaking Style", "Refine into compact voice and phrasing guidance."),
            "allowed_tone": ("Allowed Tone", "Refine into concise tone boundaries."),
            "temperature_hint": ("Temperature / Style Hint", "Refine into a short style-control hint without inventing settings."),
            "tags": ("Tags", "Refine into comma-separated lowercase tags."),
            "voice_sample": ("Voice Sample Path", "Clean up the path text only. Do not invent a file path."),
            "voice_preset": ("Voice Preset Name", "Refine into a short backend preset label."),
            "scene_title": ("Scene Title", "Refine into a short title for the roleplay scene."),
            "location": ("Location", "Refine into a compact scene location."),
            "time_of_day": ("Time / Mood", "Refine into a compact timing cue."),
            "mood": ("Mood", "Refine into concise atmosphere guidance."),
            "objective": ("Current Objective", "Refine into a clear current scene goal."),
            "scene_summary": ("Scene Summary", "Refine into compact visible continuity notes. Do not add hidden reasoning."),
            "audio_sound_description": ("Sound Description", "Refine into a compact audio-generation description. Preserve the user's intended sound."),
            "audio_prompt_output": ("Audio Prompt", "Improve this Suno-style prompt while preserving type, mood, environment, and no-vocals constraints."),
            "visual_model": ("Image Model Override", "Clean up the model name only. Do not invent a different model."),
            "visual_character": ("Character Visual Description", "Refine into a concise visual identity prompt."),
            "visual_clothing": ("Clothing / Props", "Refine into compact recurring wardrobe and prop details."),
            "visual_environment": ("Environment Style", "Refine into concise image environment guidance."),
            "visual_negative": ("Negative Prompt / Avoid List", "Refine into clear image-generation exclusions."),
        }
        for key, (label, guidance) in refine_map.items():
            self._install_refine_menu(self._controls.get(key), label, guidance)

    def _install_refine_menu(self, widget, field_label: str, guidance: str = ""):
        if widget is None or bool(getattr(widget, "isReadOnly", lambda: False)()):
            return
        if not (hasattr(widget, "text") or hasattr(widget, "toPlainText")):
            return
        widget.setProperty("_mprc_refine_label", str(field_label or "Field"))
        widget.setProperty("_mprc_refine_guidance", str(guidance or ""))
        try:
            widget.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            widget.customContextMenuRequested.connect(
                lambda point, edit=widget: self._show_refine_menu(edit, point)
            )
        except Exception:
            return
        existing_tip = str(widget.toolTip() or "").strip()
        refine_tip = "Right-click this field and choose Refine to improve it with the current chat provider."
        widget.setToolTip(f"{existing_tip}\n\n{refine_tip}" if existing_tip else refine_tip)

    def _show_refine_menu(self, widget, point):
        from PySide6 import QtWidgets

        menu = widget.createStandardContextMenu() if hasattr(widget, "createStandardContextMenu") else QtWidgets.QMenu(widget)
        try:
            from ui.runtime.spellcheck import add_spellcheck_suggestions_to_menu

            add_spellcheck_suggestions_to_menu(widget, menu, point)
        except Exception:
            pass
        menu.addSeparator()
        label = str(widget.property("_mprc_refine_label") or "Field")
        current_text = self._refinable_widget_text(widget)
        action = menu.addAction(f"Refine {label}")
        action.setEnabled(bool(current_text) and not bool(widget.property("_nc_refine_in_flight")))
        action.triggered.connect(lambda _checked=False, edit=widget: self._refine_field(edit))
        menu.exec(widget.mapToGlobal(point))

    def _install_spellcheck_widgets(self) -> None:
        spellcheck_keys = (
            "chat_input",
            "description",
            "system_prompt",
            "ar_description",
            "ar_system_prompt",
            "scene_summary",
            "ar_pending_choices",
            "audio_sound_description",
            "audio_prompt_output",
            "master_story_prompt",
            "master_story_visual_direction",
            "visual_character",
        )
        for key in spellcheck_keys:
            self._attach_spellcheck_to_widget(self._controls.get(key))

    def _attach_spellcheck_to_widget(self, widget) -> bool:
        if widget is None:
            return False
        if not isinstance(widget, (QtWidgets.QPlainTextEdit, QtWidgets.QTextEdit)):
            return False
        try:
            if bool(widget.isReadOnly()):
                return False
        except Exception:
            return False
        try:
            from ui.runtime.spellcheck import attach_spellcheck

            attached = bool(attach_spellcheck(widget))
        except Exception:
            return False
        if attached and not bool(widget.property("_mprc_refine_label")) and not bool(widget.property("_mprc_spellcheck_menu_installed")):
            try:
                widget.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
                widget.customContextMenuRequested.connect(
                    lambda point, edit=widget: self._show_spellcheck_menu(edit, point)
                )
                widget.setProperty("_mprc_spellcheck_menu_installed", True)
            except Exception:
                pass
        return attached

    def _show_spellcheck_menu(self, widget, point) -> None:
        from PySide6 import QtWidgets

        menu = widget.createStandardContextMenu() if hasattr(widget, "createStandardContextMenu") else QtWidgets.QMenu(widget)
        try:
            from ui.runtime.spellcheck import add_spellcheck_suggestions_to_menu

            add_spellcheck_suggestions_to_menu(widget, menu, point)
        except Exception:
            pass
        menu.exec(widget.mapToGlobal(point))

    def _refinable_widget_text(self, widget) -> str:
        if widget is None:
            return ""
        if hasattr(widget, "toPlainText"):
            return str(widget.toPlainText() or "").strip()
        if hasattr(widget, "text"):
            return str(widget.text() or "").strip()
        return ""

    def _set_refinable_widget_text(self, widget, text: str) -> None:
        if widget is None:
            return
        if hasattr(widget, "setPlainText"):
            widget.setPlainText(str(text or ""))
        elif hasattr(widget, "setText"):
            widget.setText(str(text or ""))

    def _refine_field(self, widget):
        if widget is None or self.is_shutdown() or bool(widget.property("_nc_refine_in_flight")):
            return
        original = self._refinable_widget_text(widget)
        if not original:
            return
        label = str(widget.property("_mprc_refine_label") or "Field")
        guidance = str(widget.property("_mprc_refine_guidance") or "")
        if widget is self._controls.get("master_story_prompt"):
            guidance = (guidance + "\n\n" + self._master_story_generation_constraints_text()).strip()
        token = self._new_worker_token("refine")
        if not token:
            return
        widget.setProperty("_nc_refine_in_flight", True)
        widget.setProperty("_nc_refine_token", token)
        try:
            self._refine_widgets[token] = weakref.ref(widget)
        except TypeError:
            self._refine_widgets[token] = lambda widget=widget: widget

        def worker():
            error = ""
            result = ""
            try:
                from core.engine_access import engine_module

                engine = engine_module()
                result = str(engine.refine_instruction_text(original, label=label, guidance=guidance) or "").strip()
            except Exception as exc:
                error = str(exc) or repr(exc)
            if not self._worker_should_emit(token):
                return
            try:
                bridge = getattr(self, "_refine_bridge", None)
                if bridge is not None:
                    bridge.finished.emit(token, label, result, error)
                else:
                    self._cancel_worker_token(token)
            except RuntimeError:
                self._cancel_worker_token(token)

        if not self._start_daemon_worker(token, worker, name="nc-mprc-refine"):
            self._refine_widgets.pop(token, None)
            widget.setProperty("_nc_refine_in_flight", False)
            widget.setProperty("_nc_refine_token", "")

    def _on_field_refined(self, token: str, field_label: str, refined_text: str, error: str):
        from PySide6 import QtWidgets

        widget_ref = self._refine_widgets.pop(str(token or ""), None)
        if not self._finish_worker_token(str(token or "")):
            return
        widget = widget_ref() if callable(widget_ref) else None
        if widget is None:
            return
        try:
            widget.setProperty("_nc_refine_in_flight", False)
            widget.setProperty("_nc_refine_token", "")
        except Exception:
            return
        if error:
            QtWidgets.QMessageBox.warning(widget.window(), f"Refine {field_label}", f"Refinement failed:\n\n{error}")
            return
        refined = str(refined_text or "").strip()
        if self._refined_text_looks_like_mprc_structured_output(refined):
            QtWidgets.QMessageBox.warning(
                widget.window(),
                f"Refine {field_label}",
                (
                    "The provider returned a structured MPRC story response instead of refined field text.\n\n"
                    "The field was left unchanged. Disable provider-level Structured Output for refine requests, "
                    "or retry now that NC strips request-scoped structured-output settings from refinement."
                ),
            )
            return
        if refined:
            self._set_refinable_widget_text(widget, refined)

    @staticmethod
    def _refined_text_looks_like_mprc_structured_output(text: str) -> bool:
        raw = str(text or "").strip()
        if not raw.startswith("{"):
            return False
        lowered = raw.lower()
        return (
            '"schema_version"' in lowered
            and "mprc.story_output" in lowered
            and '"segments"' in lowered
        ) or (
            '"response_type"' in lowered
            and '"story_turn"' in lowered
            and '"segments"' in lowered
        )

    def _build_status_tab(self):
        from PySide6 import QtWidgets

        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.addWidget(self._guide("Story Health gives you plain-language readiness checks, repair actions, voice tests, story memory, and notes about why an action did not happen."))

        top_box, top_layout = self._group("Story Health")
        status = QtWidgets.QPlainTextEdit()
        status.setReadOnly(True)
        status.setMinimumHeight(155)
        top_layout.addWidget(status)
        first_run_row = QtWidgets.QHBoxLayout()
        first_run = QtWidgets.QPushButton("Start Demo / Validate / Continue")
        template_combo = QtWidgets.QComboBox()
        for template_id, label in self._story_template_choices():
            template_combo.addItem(label, template_id)
        load_template = QtWidgets.QPushButton("Load Template")
        export_bundle = QtWidgets.QPushButton("Export Story Bundle")
        import_bundle = QtWidgets.QPushButton("Import Story Bundle")
        for button in (first_run, load_template, export_bundle, import_bundle):
            first_run_row.addWidget(button)
        first_run_row.addWidget(template_combo, 1)
        top_layout.addLayout(first_run_row)
        action_row = QtWidgets.QHBoxLayout()
        refresh = QtWidgets.QPushButton("Refresh Health")
        validate = QtWidgets.QPushButton("Check Story Setup")
        restore = QtWidgets.QPushButton("Restore Last Backup")
        reset_story = QtWidgets.QPushButton("Reset This Story")
        demo = QtWidgets.QPushButton("Load Demo Story")
        for button in (refresh, validate, restore, reset_story, demo):
            action_row.addWidget(button)
        action_row.addStretch(1)
        top_layout.addLayout(action_row)
        test_row = QtWidgets.QHBoxLayout()
        test_narrator = QtWidgets.QPushButton("Test narrator voice")
        test_character = QtWidgets.QPushButton("Test selected character voice")
        test_visual = QtWidgets.QPushButton("Test Visual Reply")
        test_audio = QtWidgets.QPushButton("Test Story Sound")
        for button in (test_narrator, test_character, test_visual, test_audio):
            test_row.addWidget(button)
        test_row.addStretch(1)
        top_layout.addLayout(test_row)
        layout.addWidget(top_box)

        validation_box, validation_layout = self._group("Setup Checks")
        validation = QtWidgets.QPlainTextEdit()
        validation.setReadOnly(True)
        validation.setMinimumHeight(150)
        validation.setPlaceholderText("Press Check Story Setup to inspect the active story.")
        validation_layout.addWidget(validation)
        repair_row = QtWidgets.QHBoxLayout()
        repair_narrator = QtWidgets.QPushButton("Choose narrator")
        repair_voice = QtWidgets.QPushButton("Browse voice file")
        repair_audio = QtWidgets.QPushButton("Disable Missing Story Sounds")
        repair_image = QtWidgets.QPushButton("Fix broken image path")
        repair_memory = QtWidgets.QPushButton("Create memory snapshot")
        repair_personas = QtWidgets.QPushButton("Relink personas")
        repair_overrides = QtWidgets.QPushButton("Reset invalid overrides")
        for button in (repair_narrator, repair_voice, repair_audio, repair_image, repair_memory, repair_personas, repair_overrides):
            repair_row.addWidget(button)
        repair_row.addStretch(1)
        validation_layout.addLayout(repair_row)
        layout.addWidget(validation_box)

        route_box, route_layout = self._group("Voice Routing Check")
        routes = QtWidgets.QPlainTextEdit()
        routes.setReadOnly(True)
        routes.setMinimumHeight(145)
        route_layout.addWidget(routes)
        inspector_row = QtWidgets.QHBoxLayout()
        preview_next = QtWidgets.QPushButton("Preview next AR request")
        explain_next = QtWidgets.QPushButton("Explain next routing")
        inspector_row.addWidget(preview_next)
        inspector_row.addWidget(explain_next)
        inspector_row.addStretch(1)
        route_layout.addLayout(inspector_row)
        next_inspector = QtWidgets.QPlainTextEdit()
        next_inspector.setReadOnly(True)
        next_inspector.setMinimumHeight(150)
        next_inspector.setPlaceholderText("Use Preview next AR request or Explain next routing to inspect the next turn.")
        route_layout.addWidget(next_inspector)
        layout.addWidget(route_box)

        memory_box, memory_layout = self._group("Story Memory")
        pinned = QtWidgets.QPlainTextEdit()
        pinned.setMinimumHeight(80)
        pinned.setPlaceholderText("Pinned facts that should stay in story memory, one per line.")
        memory_list = QtWidgets.QListWidget()
        memory_list.setMinimumHeight(135)
        memory_buttons = QtWidgets.QHBoxLayout()
        memory_refresh = QtWidgets.QPushButton("Refresh Story Memory")
        memory_save_pins = QtWidgets.QPushButton("Save Pinned Facts")
        memory_delete = QtWidgets.QPushButton("Delete Selected Memory")
        memory_reset_character = QtWidgets.QPushButton("Reset Character Memory")
        memory_reset_story = QtWidgets.QPushButton("Reset Story Memory")
        for button in (memory_refresh, memory_save_pins, memory_delete, memory_reset_character, memory_reset_story):
            memory_buttons.addWidget(button)
        memory_buttons.addStretch(1)
        memory_layout.addWidget(QtWidgets.QLabel("Pinned story facts"))
        memory_layout.addWidget(pinned)
        memory_layout.addWidget(QtWidgets.QLabel("Recent story memory"))
        memory_layout.addWidget(memory_list)
        memory_layout.addLayout(memory_buttons)
        layout.addWidget(memory_box)

        log_box, log_layout = self._group("What Needs Attention")
        event_log = QtWidgets.QPlainTextEdit()
        event_log.setReadOnly(True)
        event_log.setMinimumHeight(120)
        clear_log = QtWidgets.QPushButton("Clear Notes")
        log_layout.addWidget(event_log)
        log_layout.addWidget(clear_log)
        layout.addWidget(log_box)

        self._controls.update({
            "story_status": status,
            "story_first_run": first_run,
            "story_template": template_combo,
            "story_load_template": load_template,
            "story_export_bundle": export_bundle,
            "story_import_bundle": import_bundle,
            "story_status_refresh": refresh,
            "story_validate": validate,
            "story_restore_backup": restore,
            "story_reset_only": reset_story,
            "story_demo": demo,
            "story_test_narrator_voice": test_narrator,
            "story_test_character_voice": test_character,
            "story_test_visual": test_visual,
            "story_test_audio": test_audio,
            "story_validation": validation,
            "story_repair_narrator": repair_narrator,
            "story_repair_voice": repair_voice,
            "story_repair_audio": repair_audio,
            "story_repair_image": repair_image,
            "story_repair_memory": repair_memory,
            "story_repair_personas": repair_personas,
            "story_repair_overrides": repair_overrides,
            "story_voice_routes": routes,
            "story_preview_next": preview_next,
            "story_explain_next": explain_next,
            "story_next_inspector": next_inspector,
            "story_pinned_facts": pinned,
            "story_memory_list": memory_list,
            "story_memory_refresh": memory_refresh,
            "story_memory_save_pins": memory_save_pins,
            "story_memory_delete": memory_delete,
            "story_memory_reset_character": memory_reset_character,
            "story_memory_reset_story": memory_reset_story,
            "story_event_log": event_log,
            "story_clear_log": clear_log,
        })
        first_run.clicked.connect(self._start_demo_validate_continue)
        load_template.clicked.connect(self._load_selected_story_template)
        export_bundle.clicked.connect(self._export_story_bundle)
        import_bundle.clicked.connect(self._import_story_bundle)
        refresh.clicked.connect(self._refresh_reliability_panels)
        validate.clicked.connect(self._validate_story_setup_to_ui)
        restore.clicked.connect(self._restore_last_pre_apply_backup)
        reset_story.clicked.connect(self._reset_current_story_only)
        demo.clicked.connect(self._load_demo_story)
        test_narrator.clicked.connect(self._test_narrator_voice_from_status)
        test_character.clicked.connect(self._test_selected_character_voice_from_status)
        test_visual.clicked.connect(self._test_visual_reply_from_status)
        test_audio.clicked.connect(self._test_audiofx_from_status)
        repair_narrator.clicked.connect(self._repair_choose_narrator)
        repair_voice.clicked.connect(self._repair_browse_voice_file)
        repair_audio.clicked.connect(self._repair_disable_missing_audiofx)
        repair_image.clicked.connect(self._repair_fix_broken_image_path)
        repair_memory.clicked.connect(self._repair_create_memory_snapshot)
        repair_personas.clicked.connect(self._repair_relink_personas)
        repair_overrides.clicked.connect(self._repair_reset_invalid_overrides)
        preview_next.clicked.connect(self._preview_next_ar_request)
        explain_next.clicked.connect(self._explain_next_routing)
        memory_refresh.clicked.connect(self._refresh_memory_browser)
        memory_save_pins.clicked.connect(self._save_pinned_facts)
        memory_delete.clicked.connect(self._delete_selected_memory)
        memory_reset_character.clicked.connect(self._reset_character_memory_only)
        memory_reset_story.clicked.connect(self._reset_story_memory_only)
        clear_log.clicked.connect(self._clear_story_event_log)
        return page

    def _build_registry_tab(self):
        from PySide6 import QtWidgets

        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(self._guide("Create, copy, import, export, and choose personas here. Select a persona to edit its prompt, voice, scene, and visual settings."))
        top = QtWidgets.QHBoxLayout()
        persona_list = QtWidgets.QListWidget()
        persona_list.setObjectName("mprc_persona_list")
        top.addWidget(persona_list, 2)
        buttons = QtWidgets.QVBoxLayout()
        for key, label in (
            ("add_persona", "Add persona"),
            ("duplicate_persona", "Duplicate persona"),
            ("delete_persona", "Delete persona"),
            ("import_personas", "Import JSON"),
            ("export_personas", "Export JSON"),
            ("reset_defaults", "Reset to safe defaults"),
        ):
            button = QtWidgets.QPushButton(label)
            self._controls[key] = button
            buttons.addWidget(button)
        buttons.addStretch(1)
        top.addLayout(buttons)
        layout.addLayout(top)
        self._controls["persona_list"] = persona_list
        persona_list.currentRowChanged.connect(lambda *_args: self._on_persona_list_changed())
        self._controls["add_persona"].clicked.connect(self._add_persona)
        self._controls["duplicate_persona"].clicked.connect(self._duplicate_persona)
        self._controls["delete_persona"].clicked.connect(self._delete_persona)
        self._controls["import_personas"].clicked.connect(self._import_personas)
        self._controls["export_personas"].clicked.connect(self._export_personas)
        self._controls["reset_defaults"].clicked.connect(self._reset_defaults)
        return page

    def _build_guide_tab(self):
        from PySide6 import QtWidgets

        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        layout.addWidget(self._guide("Start here for the addon-local quick reference. For a full guided overlay, open Tutorials and run 14. Multi Persona Roleplay."))
        guide_sections: list[tuple[str, Any]] = []

        speech_row = QtWidgets.QHBoxLayout()
        read_all = QtWidgets.QPushButton("Read whole guide")
        read_all.setObjectName("mprc_guide_read_all")
        stop_speech = QtWidgets.QPushButton("Stop guide speech")
        stop_speech.setObjectName("mprc_guide_stop_speech")
        speech_status = QtWidgets.QLabel("")
        speech_status.setObjectName("mprc_guide_speech_status")
        speech_status.setProperty("muted", True)
        speech_status.setWordWrap(True)
        speech_row.addWidget(read_all)
        speech_row.addWidget(stop_speech)
        speech_row.addWidget(speech_status, 1)
        layout.addLayout(speech_row)
        self._controls["guide_read_all"] = read_all
        self._controls["guide_stop_speech"] = stop_speech
        self._controls["guide_speech_status"] = speech_status
        if self._guide_speech_command() is None:
            read_all.setEnabled(False)
            stop_speech.setEnabled(False)
            read_all.setToolTip("Guide speech is unavailable because no supported system speech command was found.")
            stop_speech.setToolTip("Guide speech is unavailable because no supported system speech command was found.")
            speech_status.setText("Guide speech unavailable.")
        else:
            read_all.setToolTip("Read every Guide tab section aloud.")
            stop_speech.setToolTip("Stop Guide tab speech.")
            stop_speech.clicked.connect(self._stop_guide_speech)

        steps_box, steps_layout = self._group("Quick Start")
        steps = [
            "1. Open Status first. Press Start Demo / Validate / Continue for the fastest known-good proof path.",
            "2. In Status, validate the active story, narrator lock, linked personas, memory snapshot, voice readiness, Visual Reply readiness, and AudioFX readiness.",
            "3. Pick the narrator and story personas. Use Master for a generated story draft, or Registry / Editor for manual persona setup.",
            "4. Open Voice and assign a local voice sample path for every persona that should sound different. Newly created personas do not get unique voices until they have voice samples.",
            "5. Confirm the active NC TTS backend supports voice samples. Chatterbox and PocketTTS reference-audio backends can route samples; unsupported backends fall back safely.",
            "6. Open Visual and choose each persona's Visual Reply behavior. Grok/xAI gets richer natural-language prompts; Runware gets shorter direct prompts; ComfyUI keeps compact prompt behavior.",
            "7. Test the Response Window or Play mode. Plain AR narration should stay on the narrator voice; voices should switch only on explicit [NARRATOR] or [CHARACTER: Name] sections.",
            "8. If validation reports a problem, use the repair buttons before guessing: choose narrator, browse voice file, disable missing AudioFX, fix image path, create memory snapshot, relink personas, or reset invalid overrides.",
            "9. Use Preview next AR request and Explain next routing when you want to understand the next Continue turn before running it.",
            "10. Use Story Library Export below the Story Library card when a story is ready to move, share, or back up as a zip package with selectable sections. Green rows mean data exists; selected avatar, voice, and AudioFX files are copied into the package.",
        ]
        for step in steps:
            label = QtWidgets.QLabel(step)
            label.setWordWrap(True)
            label.setToolTip("Step-by-step starter guide for MPRC.")
            steps_layout.addWidget(label)
        guide_sections.append(("Quick Start", lambda steps=tuple(steps): "\n".join(steps)))
        steps_layout.addLayout(self._guide_speech_row("Quick Start", lambda steps=tuple(steps): "\n".join(steps)))
        layout.addWidget(steps_box)

        cockpit_box, cockpit_layout = self._group("Story Health")
        cockpit_text = QtWidgets.QPlainTextEdit()
        cockpit_text.setReadOnly(True)
        cockpit_text.setMinimumHeight(200)
        cockpit_text.setPlainText(
            "The Story Health tab is the local story readiness view. Use it whenever you want confidence that AR is ready before pressing Continue.\n\n"
            "What it gives you:\n"
            "- Start Demo / Validate / Continue: one-click first-run path for narrator-led AR, AudioFX, Visual Reply, and Continue.\n"
            "- Built-in templates: fantasy mystery, sci-fi horror, and cozy tavern adventure.\n"
            "- Story Health: active story, AR on/off, story-owned narrator, active personas, memory, voices, visuals, and story sounds.\n"
            "- Check Story Setup: readable setup checks in the UI, not only logs.\n"
            "- Repair buttons: choose narrator, browse voice file, disable missing story sounds, fix image path, create memory snapshot, relink personas, and reset invalid overrides.\n"
            "- Voice Routing Check: shows exactly how [NARRATOR] and [CHARACTER: Name] route to personas and voice files.\n"
            "- Next-turn inspector: preview the next AR request or explain narrator, character, voice, memory, Visual Reply, and AudioFX routing.\n"
            "- Story Memory: pin facts, review recent memory, delete one memory, reset character memory, or reset story memory.\n"
            "- Story Bundle export/import: compact JSON bundle for story setup, cast, narrator setup, memory, prompts, AudioFX, visuals, and routing.\n"
            "- Story Library Export in the Master tab: zip package export/import below Story Library, with selectable sections, green availability rows, copied avatar/voice/audio assets, and safe import remapping.\n\n"
            "If something does not happen, check Setup Checks and What Needs Attention before changing prompts."
        )
        cockpit_text.setToolTip("Explains the Story Health tab and confidence workflow.")
        cockpit_layout.addWidget(cockpit_text)
        guide_sections.append(("Story Health", cockpit_text.toPlainText))
        cockpit_layout.addLayout(self._guide_speech_row("Story Health", cockpit_text.toPlainText))
        layout.addWidget(cockpit_box)

        ar_box, ar_layout = self._group("AlternativeReality Mode")
        ar_text = QtWidgets.QPlainTextEdit()
        ar_text.setReadOnly(True)
        ar_text.setMinimumHeight(185)
        ar_text.setPlainText(
            "AR mode is the story-first mode for MPRC. It is meant for cinematic interactive adventures rather than normal assistant chat or equal-turn group chat.\n\n"
            "What AR changes:\n"
            "- The narrator leads the scene and only brings in characters when they are relevant.\n"
            "- Personas can use their AR description and AR system prompt instead of their normal companion prompt.\n"
            "- The prompt keeps compact state: current scene, location, mood, story goal, active characters, recent events, and pending choices.\n"
            "- Replies may include structured sections like [NARRATOR], [CHARACTER: Name], [AMBIENCE: pub ambient], [MUSIC: adventure music], [FX: magic shimmer], [STINGER: danger stinger], and [CHOICES].\n"
            "- Audio tags are not spoken by TTS. They trigger matching AudioFX files in the background when Story Sounds is enabled.\n"
            "- Story Sounds can use the AudioFX database so the model knows which local sound cues are available.\n"
            "- Character labels such as [CHARACTER: Name] are used for per-persona voice routing when the persona has a valid voice sample.\n\n"
            "Good AR setup:\n"
            "1. Enable AlternativeReality Mode.\n"
            "2. Keep Use AR persona prompts enabled.\n"
            "3. Fill AR descriptions for characters that need a different story identity.\n"
            "4. Set pacing to Slow / Audiobook for longer narration, or Balanced for more frequent user choices.\n"
            "5. Add story sound files in the Story Sounds tab if you want ambience cues to play during the story."
        )
        ar_text.setToolTip("Explains what AlternativeReality mode changes and how to set it up.")
        ar_layout.addWidget(ar_text)
        guide_sections.append(("AlternativeReality Mode", ar_text.toPlainText))
        ar_layout.addLayout(self._guide_speech_row("AlternativeReality Mode", ar_text.toPlainText))
        layout.addWidget(ar_box)

        master_box, master_layout = self._group("Master Story Builder")
        master_text = QtWidgets.QPlainTextEdit()
        master_text.setReadOnly(True)
        master_text.setMinimumHeight(160)
        master_text.setPlainText(
            "Master turns one story prompt into a reusable story setup. The draft can include session state, AR state, linked personas, and visual profiles.\n\n"
            "Story Library Export sits directly below the Story Library card. Use it when you want a portable zip package instead of the compact JSON Story Bundle: choose which sections to include, use the green rows to see what data exists, and include avatar/voice/AudioFX files when you want the package to restore local assets on import.\n\n"
            "Useful options:\n"
            "- Avatar visual direction: steer character portrait style, genre, costume language, and mood.\n"
            "- Native story personas to draft: target how many original story characters the prompt should ask for.\n"
            "- Maximum created characters: prevent one story from creating more new personas than you intended.\n"
            "- Use already created personas: let the generator and Apply Draft map story roles onto your existing cast.\n"
            "- Clean-start story memory on apply: clears MPRC long-memory and current scene state before the new draft is applied.\n"
            "- Auto-create missing personas: create story characters that are not already in your registry.\n"
            "- Update matching existing personas: fill non-empty story fields into matching personas while preserving voice samples and existing pictures unless replaced.\n"
            "- Create avatar images for new personas: request portraits through the existing Visual Reply service.\n\n"
            "- Create avatar style sheets for new personas: optional and default off; after a new persona has an avatar image, request a full character reference sheet for image-to-image capable Visual Reply workflows.\n"
            "  Use this when your image runtime can use the avatar picture as a reference. The request asks for consistent expressions, angles, poses, detail insets, and a palette so later story images have a stronger identity anchor.\n\n"
            "Apply Draft workflow:\n"
            "- Draft Characters lists every character generated by the story draft.\n"
            "- Draft Character shows the role, description, AR profile, visual profile, and story context for the selected draft character.\n"
            "- Persona Mapping lets you create a fresh persona, use an existing persona as-is, update one, or save a story-only alternate profile for the selected existing persona.\n"
            "- The Workflow Options row includes Request avatar style sheets, mirroring the Master tab setting for this apply run.\n"
            "- Apply Result explains exactly what will happen to prompts, AR profiles, pictures, voices, story links, avatar requests, style-sheet requests, and memory before you apply.\n"
            "- Draft Avatar / Visual Prompt is editable. Right-click it and choose Refine Avatar Visual Prompt when the generated prompt needs cleanup before requesting the image.\n"
            "- Generated draft avatar images immediately appear as Draft Characters thumbnails and are carried into Apply Story.\n"
            "- Draft Voice lets you assign a .wav from the project voices folder before applying. Preview Voice loads the active NC TTS runtime and plays the editable emotional sample text with the selected voice.\n"
            "- Clear / Restart Story removes old MPRC long-memory, current scene state, and Master Story links while keeping saved personas and story files.\n\n"
            "Persona markers:\n"
            "- [Active Story] means this persona is the active persona for the loaded story.\n"
            "- [Story] means this persona is linked to the loaded story.\n"
            "- [New Story] means this persona was created by the current Master Story apply/load action."
        )
        master_text.setToolTip("Explains Master Story generation, persona linking, avatar images, and story markers.")
        master_layout.addWidget(master_text)
        guide_sections.append(("Master Story Builder", master_text.toPlainText))
        master_layout.addLayout(self._guide_speech_row("Master Story Builder", master_text.toPlainText))
        layout.addWidget(master_box)

        visual_box, visual_layout = self._group("Visual Reply Story Images")
        visual_text = QtWidgets.QPlainTextEdit()
        visual_text.setReadOnly(True)
        visual_text.setMinimumHeight(175)
        visual_text.setPlainText(
            "The Visual tab controls real story-scene images sent to the existing Visual Reply window. It is separate from the current-character preview panel.\n\n"
            "Recommended workflow:\n"
            "1. Select a persona, then enable story images in Visual Reply for that persona.\n"
            "2. Choose When to generate. Good first choices are When user asks for image, Important story moments, AR story beats, or When choices appear. Every assistant reply is useful for testing but can generate too many images with paid providers.\n"
            "3. Fill Character visual description, clothing / props, and environment style so the scene prompt keeps identity and setting consistent.\n"
            "4. Keep Use latest scene summary and Include active speaker enabled when you want images to show what is happening in the story instead of only a portrait.\n"
            "5. Use Preview Image Prompt before generating. Use Generate Visual Reply for a manual test. Auto requests still respect cooldown and max auto images per session.\n\n"
            "Provider prompt styles:\n"
            "- Grok/xAI: richer natural-language prompt with current story moment, visible action, persona identity, appearance, scene, mood, lighting, style, and continuity.\n"
            "- Runware: shorter direct prompt with concrete subject, action, location, style, lighting/mood, and continuity terms. This avoids overloading Runware with long story instructions.\n"
            "- ComfyUI: compact direct positive prompt, preserving the existing ComfyUI behavior.\n\n"
            "If images do not appear, check that Visual Reply itself has a configured provider, this persona has visual generation enabled, the trigger mode matches the scene, cooldown has expired, and max auto images/session has not been reached."
        )
        visual_text.setToolTip("Explains the difference between character preview and real story-scene Visual Reply generation.")
        visual_layout.addWidget(visual_text)
        guide_sections.append(("Visual Reply Story Images", visual_text.toPlainText))
        visual_layout.addLayout(self._guide_speech_row("Visual Reply Story Images", visual_text.toPlainText))
        layout.addWidget(visual_box)

        audio_box, audio_layout = self._group("Audio Tab And Story Sounds")
        audio_text = QtWidgets.QPlainTextEdit()
        audio_text.setReadOnly(True)
        audio_text.setMinimumHeight(230)
        audio_text.setPlainText(
            "The Story Sounds tab controls the sounds a story can actually play. It has two related jobs: build/save sound descriptions, and connect those descriptions to real local audio files.\n\n"
            "Recommended workflow:\n"
            "1. Open Story Sounds and keep Story Sounds enabled.\n"
            "2. Click Import Audio Pack Resources and choose a prepared pack folder such as Q:\\Sounds. The folder should contain mprc_audio_pack.json or audio_pack.json.\n"
            "3. Set story sound volume low enough that background sounds do not overpower TTS. This affects automatic story sounds and manual previews only.\n"
            "4. Check the Story Sound Library. Green items are ready: the local file exists and is indexed for story use.\n"
            "5. Use Play Sound to preview a selected cue, or Play [AMBIENCE: pub ambient] to test tag playback.\n"
            "6. In AR stories, the model should choose from available AudioFX descriptions and write exact tags such as [AMBIENCE: pub ambient], [MUSIC: adventure music], [FX: magic shimmer], or [STINGER: danger stinger].\n"
            "7. When a matching tag appears in chat, MPRC removes that tag before TTS and plays the matching file in the background.\n\n"
            "Important rules:\n"
            "- The model should not invent sound names. It should choose descriptions that exist in the Story Sound Library.\n"
            "- [AMBIENCE: ...] is for background environments, [MUSIC: ...] is for music, [FX: ...] is for short effects, and [STINGER: ...] is for brief dramatic hits.\n"
            "- Imported sound packs only store file paths in addon settings. Removing an AudioFX item does not delete the sound file from disk.\n"
            "- If a tag is spoken aloud, either Story Sounds is off, the cue was not matched, or the tag reached TTS before the audio scanner saw a complete bracketed tag."
        )
        audio_text.setToolTip("Comprehensive guide for the Audio tab, sound pack import, AudioFX readiness, story tags, and TTS-safe playback.")
        audio_layout.addWidget(audio_text)
        guide_sections.append(("Audio Tab And Story Sounds", audio_text.toPlainText))
        audio_layout.addLayout(self._guide_speech_row("Audio Tab And Story Sounds", audio_text.toPlainText))
        layout.addWidget(audio_box)

        workflow_box, workflow_layout = self._group("Which Tab To Use")
        workflow_text = QtWidgets.QPlainTextEdit()
        workflow_text.setReadOnly(True)
        workflow_text.setMinimumHeight(135)
        workflow_text.setPlainText(
            "Play: isolated story feed, Player Action input, Response Window-style speech playback, Focus, choices, and story-scene Visual Reply triggers.\n"
            "Guide: quick start and default scenario overview.\n"
            "Status: production cockpit for demo start, templates, validation, repair, voice routing, memory editing, tests, bundles, and skipped-action logs.\n"
            "Master: build, save, and load complete stories from one prompt, including visual profiles and optional avatar images.\n"
            "Registry: add, duplicate, delete, import, export, and select personas.\n"
            "Editor: tune the active persona, AR profile, prompt, character picture, and text fields.\n"
            "Voice: assign per-persona voice samples and check backend support. Newly created personas need voice samples before they can sound different.\n"
            "Session: normal roleplay scene state and roster controls.\n"
            "AR: AlternativeReality pacing, story state, active characters, and choices.\n"
            "Visual: per-persona story-image generation, Visual Reply trigger modes, image prompt preview, cooldown, and auto image limits.\n"
            "Audio: saved audio prompts and AudioFX files available to the story. Ready AudioFX cues can be played by [AMBIENCE: description], [MUSIC: description], [FX: description], [STINGER: description], or [AUDIO: description].\n"
            "Debug: inspect effective prompt, voice route, Visual Reply payload, provider prompt style, and compact state."
        )
        workflow_text.setToolTip("Quick map of what each MPRC tab controls.")
        workflow_layout.addWidget(workflow_text)
        guide_sections.append(("Which Tab To Use", workflow_text.toPlainText))
        workflow_layout.addLayout(self._guide_speech_row("Which Tab To Use", workflow_text.toPlainText))
        layout.addWidget(workflow_box)

        troubleshoot_box, troubleshoot_layout = self._group("Troubleshooting")
        troubleshoot_text = QtWidgets.QPlainTextEdit()
        troubleshoot_text.setReadOnly(True)
        troubleshoot_text.setMinimumHeight(180)
        troubleshoot_text.setPlainText(
            "Image not generating: open Visual Reply itself and confirm provider, model, API key/base URL, and image size. Then check this persona's Visual tab: enabled, trigger mode, cooldown, and max auto images.\n\n"
            "Runware image quality drops: use Preview Image Prompt and keep the prompt compact. Runware usually works better with direct concrete visual phrases than with long story instructions.\n\n"
            "Grok/xAI image is too plain: add richer character appearance, clothing/props, scene, mood, lighting, and style details. Grok/xAI handles natural-language prompts better than Runware.\n\n"
            "Voice not applying: newly created personas need a voice sample path in the Voice tab, and the active NC TTS backend must support reference audio. Unsupported backends keep speaking with the normal voice.\n\n"
            "Voice changes during one response: check Troubleshooting or Story Health -> Voice Routing Check. A voice should switch only on explicit [NARRATOR], [CHARACTER: Exact Persona Display Name], or supported speaker labels; plain AR narration should stay on the narrator.\n\n"
            "Narrator/persona mismatch: choose the narrator explicitly in Status or Voice, then validate. The inspector shows route reasons such as explicit_persona, text_speaker_label, ar_narrator_default, ar_stream_speaker, current_speaker, or active_persona."
        )
        troubleshoot_text.setToolTip("Common MPRC setup and routing fixes.")
        troubleshoot_layout.addWidget(troubleshoot_text)
        guide_sections.append(("Troubleshooting", troubleshoot_text.toPlainText))
        troubleshoot_layout.addLayout(self._guide_speech_row("Troubleshooting", troubleshoot_text.toPlainText))
        layout.addWidget(troubleshoot_box)

        scenario_box, scenario_layout = self._group("Default Saved Scenario")
        scenario_text = QtWidgets.QPlainTextEdit()
        scenario_text.setReadOnly(True)
        scenario_text.setMinimumHeight(170)
        scenario_text.setPlainText(
            "The Lantern Archive\n\n"
            "Mode: Narrator + characters\n"
            "Location: A quiet archive workshop with a planning table, map wall, voice recorder, and image board.\n"
            "Mood: Curious, focused, collaborative\n"
            "Objective: Use the full persona roster to plan a small mystery scene, explain choices clearly, and generate story images when useful.\n\n"
            "Persona roster:\n"
            "- Mentor: guides setup and explains options.\n"
            "- Friend: keeps the session relaxed and easy to continue.\n"
            "- Story Narrator: describes scene beats and atmosphere.\n"
            "- Game Master: tracks choices, objectives, and consequences.\n"
            "- Custom Character Template: ready for the user to reshape."
        )
        scenario_text.setToolTip("Read-only overview of the default scenario saved with this addon.")
        scenario_layout.addWidget(scenario_text)
        guide_sections.append(("Default Saved Scenario", scenario_text.toPlainText))
        scenario_layout.addLayout(self._guide_speech_row("Default Saved Scenario", scenario_text.toPlainText))

        reset_row = QtWidgets.QHBoxLayout()
        load_default = QtWidgets.QPushButton("Load Default Scenario")
        load_default.setToolTip("Replace the current session with the bundled touch-and-go default scenario.")
        load_default.clicked.connect(self._load_default_scenario)
        reset_row.addWidget(load_default)
        reset_row.addStretch(1)
        scenario_layout.addLayout(reset_row)
        layout.addWidget(scenario_box)
        layout.addStretch(1)
        self._controls["load_default_scenario"] = load_default
        if read_all.isEnabled():
            read_all.clicked.connect(
                lambda _checked=False: self._speak_guide_section(
                    "MPRC Guide",
                    "\n\n".join(
                        f"{title}\n{provider() if callable(provider) else provider}"
                        for title, provider in guide_sections
                    ),
                )
            )
        return page

    def _build_editor_tab(self):
        from PySide6 import QtCore, QtWidgets

        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.addWidget(self._guide("Edit the active persona. Right-click any text field and choose Refine to improve that field using the current chat provider and the field's own label."))
        box, form_layout = self._group("Persona Editor")
        form = QtWidgets.QFormLayout()
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        controls = {
            "persona_id": QtWidgets.QLineEdit(),
            "persona_enabled": QtWidgets.QCheckBox("Enabled"),
            "master_narrator": QtWidgets.QCheckBox("Master narrator"),
            "display_name": QtWidgets.QLineEdit(),
            "role": QtWidgets.QLineEdit(),
            "description": QtWidgets.QTextEdit(),
            "character_image_path": QtWidgets.QLineEdit(),
            "system_prompt": QtWidgets.QTextEdit(),
            "ar_profile_enabled": QtWidgets.QCheckBox("Use AR profile in AlternativeReality mode"),
            "ar_description": QtWidgets.QTextEdit(),
            "ar_system_prompt": QtWidgets.QTextEdit(),
            "speaking_style": QtWidgets.QLineEdit(),
            "allowed_tone": QtWidgets.QLineEdit(),
            "response_length": QtWidgets.QComboBox(),
            "temperature_hint": QtWidgets.QLineEdit(),
            "memory_scope": QtWidgets.QComboBox(),
            "behavior_mode": QtWidgets.QComboBox(),
            "tags": QtWidgets.QLineEdit(),
        }
        controls["description"].setMaximumHeight(70)
        controls["system_prompt"].setMinimumHeight(110)
        controls["ar_description"].setMaximumHeight(80)
        controls["ar_system_prompt"].setMinimumHeight(120)
        controls["response_length"].addItems(["short", "balanced", "detailed"])
        controls["memory_scope"].addItems(list(MEMORY_SCOPES))
        controls["behavior_mode"].addItems(list(BEHAVIOR_MODES))
        for key, widget in controls.items():
            self._controls[key] = widget
        form.addRow("Persona ID", controls["persona_id"])
        form.addRow("", controls["persona_enabled"])
        controls["master_narrator"].setToolTip(
            "Mark this persona as a favorite Master narrator. Master narrators are numbered in selectors, preferred for AR narrator auto-pick, and protected from deletion."
        )
        form.addRow("", controls["master_narrator"])
        form.addRow("Display name", controls["display_name"])
        form.addRow("Role / archetype", controls["role"])
        form.addRow("Short description", controls["description"])
        image_preview = QtWidgets.QLabel()
        image_preview.setObjectName("mprc_editor_character_image")
        image_preview.setFixedSize(120, 120)
        image_preview.setAlignment(QtCore.Qt.AlignCenter)
        image_path_row = QtWidgets.QHBoxLayout()
        image_path_row.addWidget(controls["character_image_path"], 1)
        image_browse = QtWidgets.QPushButton("Add Character picture")
        image_generate = QtWidgets.QPushButton("Create from prompt")
        image_clear = QtWidgets.QPushButton("Clear")
        image_path_row.addWidget(image_browse)
        image_path_row.addWidget(image_generate)
        image_path_row.addWidget(image_clear)
        self._controls["character_image"] = image_preview
        self._controls["character_image_browse"] = image_browse
        self._controls["character_image_generate"] = image_generate
        self._controls["character_image_clear"] = image_clear
        form.addRow("Character picture", image_preview)
        form.addRow("Picture path", image_path_row)
        form.addRow("System prompt", controls["system_prompt"])
        form.addRow("", controls["ar_profile_enabled"])
        form.addRow("AR description", controls["ar_description"])
        form.addRow("AR system prompt", controls["ar_system_prompt"])
        form.addRow("Speaking style", controls["speaking_style"])
        form.addRow("Allowed tone", controls["allowed_tone"])
        form.addRow("Response length", controls["response_length"])
        form.addRow("Temperature/style hint", controls["temperature_hint"])
        form.addRow("Memory scope", controls["memory_scope"])
        form.addRow("Roleplay behavior", controls["behavior_mode"])
        form.addRow("Tags", controls["tags"])
        form_layout.addLayout(form)
        layout.addWidget(box)
        layout.addStretch(1)
        text_area_keys = {"description", "system_prompt", "ar_description", "ar_system_prompt"}
        identity_line_keys = {"persona_id", "display_name"}
        for key, widget in controls.items():
            if key in text_area_keys:
                continue
            if hasattr(widget, "textChanged"):
                if key in identity_line_keys and hasattr(widget, "editingFinished"):
                    widget.editingFinished.connect(lambda key=key: self._commit_editor_now(include_identity=True))
                else:
                    widget.textChanged.connect(lambda *_args: self._schedule_editor_commit(include_identity=False))
                    if hasattr(widget, "editingFinished"):
                        widget.editingFinished.connect(lambda key=key: self._commit_editor_now(include_identity=False))
            elif hasattr(widget, "currentTextChanged"):
                widget.currentTextChanged.connect(lambda *_args: self._commit_editor_now(include_identity=False))
            elif hasattr(widget, "toggled"):
                widget.toggled.connect(lambda *_args: self._commit_editor_now(include_identity=False))
        controls["description"].textChanged.connect(lambda *_args: self._schedule_editor_commit(include_identity=False))
        controls["system_prompt"].textChanged.connect(lambda *_args: self._schedule_editor_commit(include_identity=False))
        controls["ar_description"].textChanged.connect(lambda *_args: self._schedule_editor_commit(include_identity=False))
        controls["ar_system_prompt"].textChanged.connect(lambda *_args: self._schedule_editor_commit(include_identity=False))
        image_browse.clicked.connect(self._browse_character_image)
        image_generate.clicked.connect(self._generate_character_image)
        image_clear.clicked.connect(lambda *_args: (controls["character_image_path"].setText(""), self._commit_editor_now(include_identity=False)))
        return page

    def _build_voice_tab(self):
        from PySide6 import QtWidgets

        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.addWidget(self._guide("Assign a local voice reference per persona. MPRC applies it only when roleplay mode is enabled and the active TTS backend supports voice samples."))
        box, box_layout = self._group("Voice Per Persona")
        form = QtWidgets.QFormLayout()
        narrator_persona = QtWidgets.QComboBox()
        follow_active = QtWidgets.QCheckBox("Follow active persona")
        follow_active.setChecked(bool(self.settings.get("voice_follow_active_persona", True)))
        current_persona = QtWidgets.QLabel("")
        current_persona.setWordWrap(True)
        current_persona.setProperty("muted", True)
        voice_persona = QtWidgets.QComboBox()
        enabled = QtWidgets.QCheckBox("Voice enabled")
        backend = QtWidgets.QComboBox()
        backend.addItems(list(VOICE_BACKENDS))
        sample = QtWidgets.QLineEdit()
        sample.setMinimumWidth(520)
        sample.setPlaceholderText("Selected voice sample .wav path")
        sample.setToolTip("Full path to the selected voice sample file.")
        sample_picker = QtWidgets.QComboBox()
        sample_picker.setMinimumWidth(420)
        sample_picker.setToolTip("Quickly choose an audio file from the project voices folder.")
        sample_picker.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        sample_picker_view = QtWidgets.QTreeView()
        sample_picker_view.setHeaderHidden(True)
        sample_picker_view.setRootIsDecorated(False)
        sample_picker_view.setItemsExpandable(False)
        sample_picker_view.setAllColumnsShowFocus(True)
        sample_picker.setView(sample_picker_view)
        sample_picker.setModelColumn(1)
        browse = QtWidgets.QPushButton("Browse")
        clear = QtWidgets.QPushButton("Clear")
        test = QtWidgets.QPushButton("Test voice")
        sample_row = QtWidgets.QHBoxLayout()
        sample_row.addWidget(test)
        sample_row.addWidget(sample, 1)
        sample_row.addWidget(browse)
        sample_row.addWidget(clear)
        sample_picker_row = QtWidgets.QHBoxLayout()
        sample_picker_row.addWidget(sample_picker, 1)
        preset = QtWidgets.QLineEdit()
        language = QtWidgets.QComboBox()
        language.addItems(["", "en", "fr", "de", "es", "pt", "it", "ja", "ko", "zh"])
        warning = QtWidgets.QLabel("")
        warning.setProperty("muted", True)
        warning.setWordWrap(True)
        form.addRow("Narrator voice persona", narrator_persona)
        form.addRow("", follow_active)
        form.addRow("Currently editing", current_persona)
        form.addRow("Edit voice for persona", voice_persona)
        form.addRow("", enabled)
        form.addRow("Backend override", backend)
        form.addRow("Voice sample path", sample_row)
        form.addRow("Voice files in \\voices", sample_picker_row)
        form.addRow("Voice preset name", preset)
        form.addRow("Language", language)
        box_layout.addLayout(form)
        box_layout.addWidget(warning)
        layout.addWidget(box)
        layout.addStretch(1)
        self._controls.update({
            "narrator_persona": narrator_persona,
            "voice_follow_active": follow_active,
            "voice_current_persona": current_persona,
            "voice_persona": voice_persona,
            "voice_enabled": enabled,
            "voice_backend": backend,
            "voice_sample": sample,
            "voice_sample_picker": sample_picker,
            "voice_browse": browse,
            "voice_clear": clear,
            "voice_preset": preset,
            "voice_language": language,
            "voice_test": test,
            "voice_warning": warning,
        })
        narrator_persona.currentIndexChanged.connect(lambda *_args: self._commit_narrator_persona())
        follow_active.toggled.connect(lambda *_args: self._commit_voice_follow_active())
        voice_persona.currentIndexChanged.connect(lambda *_args: self._commit_voice_persona())
        enabled.toggled.connect(lambda *_args: self._commit_voice_now())
        backend.currentTextChanged.connect(lambda *_args: self._commit_voice_now())
        sample_picker.currentIndexChanged.connect(lambda *_args: self._select_voice_sample_from_picker())
        sample.textChanged.connect(lambda *_args: self._schedule_voice_commit())
        sample.editingFinished.connect(self._commit_voice_now)
        preset.textChanged.connect(lambda *_args: self._schedule_voice_commit())
        preset.editingFinished.connect(self._commit_voice_now)
        language.currentTextChanged.connect(lambda *_args: self._commit_voice_now())
        browse.clicked.connect(self._browse_voice_sample)
        clear.clicked.connect(lambda *_args: (sample.setText(""), self._sync_voice_sample_picker(""), self._commit_voice_now()))
        test.clicked.connect(self._test_voice)
        self._populate_voice_sample_picker()
        return page

    def _build_session_tab(self):
        from PySide6 import QtWidgets

        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.addWidget(self._guide("Track the visible roleplay scene. Keep this compact: summaries are prompt context, not hidden reasoning."))
        box, box_layout = self._group("Roleplay Session")
        form = QtWidgets.QFormLayout()
        mode = QtWidgets.QComboBox()
        mode.addItems(list(SESSION_MODES))
        for index, mode_name in enumerate(SESSION_MODES):
            mode.setItemData(index, SESSION_MODE_DESCRIPTIONS.get(mode_name, ""), QtCore.Qt.ToolTipRole)
        mode_note = QtWidgets.QLabel("")
        mode_note.setObjectName("mprc_session_mode_note")
        mode_note.setWordWrap(True)
        mode_note.setProperty("muted", True)
        mode_note.setMinimumHeight(34)
        scene_title = QtWidgets.QLineEdit()
        location = QtWidgets.QLineEdit()
        time_of_day = QtWidgets.QLineEdit()
        mood = QtWidgets.QLineEdit()
        objective = QtWidgets.QLineEdit()
        scene_summary = QtWidgets.QTextEdit()
        roster = QtWidgets.QTextEdit()
        roster.setReadOnly(True)
        auto_select = QtWidgets.QCheckBox("Auto-select speaker")
        next_speaker = QtWidgets.QComboBox()
        continuity = QtWidgets.QCheckBox("Keep scene continuity")
        update_scene = QtWidgets.QCheckBox("Update scene after each assistant reply")
        reset = QtWidgets.QPushButton("Reset scene")
        export_session = QtWidgets.QPushButton("Export session")
        import_session = QtWidgets.QPushButton("Import session")
        button_row = QtWidgets.QHBoxLayout()
        for button in (reset, export_session, import_session):
            button_row.addWidget(button)
        button_row.addStretch(1)
        form.addRow("Mode", mode)
        form.addRow("", mode_note)
        form.addRow("Scene title", scene_title)
        form.addRow("Location", location)
        form.addRow("Time / mood", time_of_day)
        form.addRow("Mood", mood)
        form.addRow("Current objective", objective)
        form.addRow("Scene summary", scene_summary)
        form.addRow("Character roster", roster)
        form.addRow("", auto_select)
        form.addRow("Manual next speaker", next_speaker)
        form.addRow("", continuity)
        form.addRow("", update_scene)
        box_layout.addLayout(form)
        box_layout.addLayout(button_row)
        layout.addWidget(box)
        self._controls.update({
            "session_mode": mode,
            "session_mode_note": mode_note,
            "scene_title": scene_title,
            "location": location,
            "time_of_day": time_of_day,
            "mood": mood,
            "objective": objective,
            "scene_summary": scene_summary,
            "roster": roster,
            "auto_select": auto_select,
            "next_speaker": next_speaker,
            "continuity": continuity,
            "update_scene": update_scene,
            "reset_scene": reset,
            "export_session": export_session,
            "import_session": import_session,
        })
        mode.currentTextChanged.connect(lambda value="": (self._update_session_mode_note(value), self._commit_session_now(refresh_ui=True)))
        next_speaker.currentTextChanged.connect(lambda *_args: self._commit_session_now(refresh_ui=False))
        for widget in (scene_title, location, time_of_day, mood, objective):
            widget.textChanged.connect(lambda *_args: self._schedule_session_commit())
            widget.editingFinished.connect(lambda widget=widget: self._commit_session_now(refresh_ui=False))
        scene_summary.textChanged.connect(lambda *_args: self._schedule_session_commit())
        for widget in (auto_select, continuity, update_scene):
            widget.toggled.connect(lambda *_args: self._commit_session_now(refresh_ui=False))
        reset.clicked.connect(self._reset_scene)
        export_session.clicked.connect(self._export_session)
        import_session.clicked.connect(self._import_session)
        return page

    def _build_ar_tab(self):
        from PySide6 import QtWidgets

        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.addWidget(self._guide("AlternativeReality is a narrator-led interactive audiobook/adventure mode. It uses compact state to continue scenes, choose relevant characters, and avoid equal-response group chat."))

        settings_box, settings_layout = self._group("AR Runtime")
        settings_form = QtWidgets.QFormLayout()
        ar_enabled = QtWidgets.QCheckBox("AlternativeReality Mode")
        ar_use_persona_profiles = QtWidgets.QCheckBox("Use AR persona prompts")
        ar_pacing = QtWidgets.QComboBox()
        ar_pacing.addItems(list(AR_PACING_MODES))
        ar_interaction = QtWidgets.QComboBox()
        ar_interaction.addItems(list(AR_INTERACTION_FREQUENCIES))
        tension = QtWidgets.QSpinBox()
        tension.setRange(0, 10)
        settings_form.addRow("", ar_enabled)
        settings_form.addRow("", ar_use_persona_profiles)
        settings_form.addRow("Pacing", ar_pacing)
        settings_form.addRow("Interaction frequency", ar_interaction)
        settings_form.addRow("Tension level", tension)
        settings_layout.addLayout(settings_form)
        settings_layout.addWidget(self._guide("Audiobook pacing allows longer narrative passages before asking the player. Fast mode reaches choices sooner."))

        state_box, state_layout = self._group("AR State")
        state_form = QtWidgets.QFormLayout()
        current_scene = QtWidgets.QLineEdit()
        location = QtWidgets.QLineEdit()
        time_of_day = QtWidgets.QLineEdit()
        mood = QtWidgets.QLineEdit()
        story_goal = QtWidgets.QLineEdit()
        active_characters = QtWidgets.QLineEdit()
        player_intent = QtWidgets.QLineEdit()
        pending_choices = QtWidgets.QTextEdit()
        recent_events = QtWidgets.QTextEdit()
        recent_events.setReadOnly(True)
        state_form.addRow("Current scene", current_scene)
        state_form.addRow("Location", location)
        state_form.addRow("Time of day", time_of_day)
        state_form.addRow("Mood", mood)
        state_form.addRow("Story goal", story_goal)
        state_form.addRow("Active characters", active_characters)
        state_form.addRow("Player intent", player_intent)
        state_form.addRow("Pending choices", pending_choices)
        state_form.addRow("Recent events", recent_events)
        state_layout.addLayout(state_form)

        button_row = QtWidgets.QHBoxLayout()
        seed = QtWidgets.QPushButton("Seed from session")
        fill_profiles = QtWidgets.QPushButton("Fill AR persona prompts")
        clear = QtWidgets.QPushButton("Clear AR state")
        button_row.addWidget(seed)
        button_row.addWidget(fill_profiles)
        button_row.addWidget(clear)
        button_row.addStretch(1)
        state_layout.addLayout(button_row)

        layout.addWidget(settings_box)
        layout.addWidget(state_box)
        layout.addStretch(1)
        self._controls.update({
            "ar_enabled": ar_enabled,
            "ar_use_persona_profiles": ar_use_persona_profiles,
            "ar_pacing": ar_pacing,
            "ar_interaction": ar_interaction,
            "ar_tension": tension,
            "ar_current_scene": current_scene,
            "ar_location": location,
            "ar_time_of_day": time_of_day,
            "ar_mood": mood,
            "ar_story_goal": story_goal,
            "ar_active_characters": active_characters,
            "ar_player_intent": player_intent,
            "ar_pending_choices": pending_choices,
            "ar_recent_events": recent_events,
            "ar_seed": seed,
            "ar_fill_profiles": fill_profiles,
            "ar_clear": clear,
        })
        ar_enabled.toggled.connect(self._on_ar_mode_changed)
        ar_use_persona_profiles.toggled.connect(lambda *_args: self._commit_ar_state_now())
        for widget in (ar_pacing, ar_interaction):
            widget.currentTextChanged.connect(lambda *_args: self._commit_ar_state_now())
        for widget in (current_scene, location, time_of_day, mood, story_goal, active_characters, player_intent):
            widget.textChanged.connect(lambda *_args: self._schedule_ar_state_commit())
            widget.editingFinished.connect(self._commit_ar_state_now)
        tension.valueChanged.connect(lambda *_args: self._commit_ar_state_now())
        pending_choices.textChanged.connect(lambda *_args: self._schedule_ar_state_commit())
        seed.clicked.connect(self._seed_ar_state_from_session)
        fill_profiles.clicked.connect(self._fill_ar_persona_profiles)
        clear.clicked.connect(self._clear_ar_state)
        return page

    def _build_audio_tab(self):
        from PySide6 import QtWidgets

        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        intro = self._guide("Story Sounds controls AR-triggered background audio. Use it for ambience, music, effects, stingers, and Spotify Sense story music hooks.")
        layout.addWidget(intro)

        story_box, story_layout = self._group("Story Sounds")
        story_sounds = QtWidgets.QCheckBox("Story Sounds")
        story_sounds.setChecked(True)
        story_layout.addWidget(story_sounds)
        volume_row = QtWidgets.QHBoxLayout()
        volume_label = QtWidgets.QLabel("Story sound volume")
        volume_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        volume_slider.setRange(0, 100)
        volume_slider.setValue(self._audiofx_volume_percent())
        volume_value = QtWidgets.QLabel(f"{volume_slider.value()}%")
        volume_value.setMinimumWidth(44)
        volume_row.addWidget(volume_label)
        volume_row.addWidget(volume_slider, 1)
        volume_row.addWidget(volume_value)
        story_layout.addLayout(volume_row)
        test_mode = QtWidgets.QCheckBox("Sound test mode")
        create_test_sounds = QtWidgets.QPushButton("Create Test Sounds")
        play_test_tag = QtWidgets.QPushButton("Play [AMBIENCE: pub ambient]")
        test_row = QtWidgets.QHBoxLayout()
        test_row.addWidget(test_mode)
        test_row.addWidget(create_test_sounds)
        test_row.addWidget(play_test_tag)
        test_row.addStretch(1)
        story_layout.addLayout(test_row)
        story_note = self._guide("When disabled, story-triggered sound tags are ignored. Manual preview and test buttons still work. If Spotify Sense is enabled, story music requests can also choose fitting background music.")
        story_layout.addWidget(story_note)

        prompt_box, prompt_layout = self._group("Create Prompt for Audio")
        form = QtWidgets.QFormLayout()
        description = QtWidgets.QPlainTextEdit()
        description.setMinimumHeight(76)
        description.setPlaceholderText("Describe the sound, ambience, music, emotion, environment, or effect you want...")
        examples = QtWidgets.QLabel(
            "Examples: dark cave with distant creature sounds; epic final boss battle music; "
            "peaceful fantasy tavern ambience; cyberpunk rain city at night; magic spell charging sound"
        )
        examples.setWordWrap(True)
        examples.setProperty("muted", True)
        audio_type = QtWidgets.QComboBox()
        audio_type.addItems(list(AUDIO_TYPES))
        create = QtWidgets.QPushButton("Create Prompt for Audio")
        output = QtWidgets.QPlainTextEdit()
        output.setMinimumHeight(150)
        output.setPlaceholderText("Generated audio prompt will appear here.")
        form.addRow("Sound Description", description)
        form.addRow("", examples)
        form.addRow("Type", audio_type)
        form.addRow("", create)
        form.addRow("Generated prompt", output)
        prompt_layout.addLayout(form)

        quick_row = QtWidgets.QHBoxLayout()
        ambience = QtWidgets.QPushButton("Generate ambience variation")
        horror = QtWidgets.QPushButton("Generate horror version")
        calmer = QtWidgets.QPushButton("Generate calmer version")
        action = QtWidgets.QPushButton("Generate action version")
        for button in (ambience, horror, calmer, action):
            quick_row.addWidget(button)
        quick_row.addStretch(1)
        prompt_layout.addLayout(quick_row)

        button_row = QtWidgets.QHBoxLayout()
        copy_prompt = QtWidgets.QPushButton("Copy Prompt")
        save_prompt = QtWidgets.QPushButton("Save Prompt")
        save_description = QtWidgets.QPushButton("Save as Audio Item Description")
        clear = QtWidgets.QPushButton("Clear")
        for button in (copy_prompt, save_prompt, save_description, clear):
            button_row.addWidget(button)
        button_row.addStretch(1)
        prompt_layout.addLayout(button_row)

        saved_box, saved_layout = self._group("Saved Audio Prompts")
        saved_count = QtWidgets.QLabel("No saved prompts")
        saved_count.setProperty("muted", True)
        saved_list = QtWidgets.QListWidget()
        saved_list.setMinimumHeight(120)
        saved_buttons = QtWidgets.QHBoxLayout()
        load_saved = QtWidgets.QPushButton("Load Selected")
        delete_saved = QtWidgets.QPushButton("Delete Selected")
        saved_buttons.addWidget(load_saved)
        saved_buttons.addWidget(delete_saved)
        saved_buttons.addStretch(1)
        saved_layout.addWidget(saved_count)
        saved_layout.addWidget(saved_list)
        saved_layout.addLayout(saved_buttons)

        audiofx_box, audiofx_layout = self._group("Story Sound Library")
        audiofx_count = QtWidgets.QLabel("No story sound items")
        audiofx_count.setProperty("muted", True)
        audiofx_list = QtWidgets.QListWidget()
        audiofx_list.setMinimumHeight(140)
        audiofx_status = QtWidgets.QLabel("Create a story sound from the current description, then attach a local audio file.")
        audiofx_status.setWordWrap(True)
        audiofx_status.setProperty("muted", True)
        audiofx_buttons = QtWidgets.QHBoxLayout()
        create_audiofx = QtWidgets.QPushButton("Create Story Sound")
        import_audio_pack = QtWidgets.QPushButton("Import Sound Pack")
        add_audio_file = QtWidgets.QPushButton("Add Sound File")
        play_sound = QtWidgets.QPushButton("Play Sound")
        load_audiofx = QtWidgets.QPushButton("Load Description")
        delete_audiofx = QtWidgets.QPushButton("Delete Story Sound")
        for button in (create_audiofx, import_audio_pack, add_audio_file, play_sound, load_audiofx, delete_audiofx):
            audiofx_buttons.addWidget(button)
        audiofx_buttons.addStretch(1)
        audiofx_layout.addWidget(audiofx_count)
        audiofx_layout.addWidget(audiofx_list)
        audiofx_layout.addWidget(audiofx_status)
        audiofx_layout.addLayout(audiofx_buttons)

        layout.addWidget(story_box)
        layout.addWidget(prompt_box)
        layout.addWidget(saved_box)
        layout.addWidget(audiofx_box)
        layout.addStretch(1)
        self._controls.update({
            "audio_intro": intro,
            "audio_story_box": story_box,
            "audio_story_note": story_note,
            "audio_prompt_box": prompt_box,
            "audio_story_sounds": story_sounds,
            "audiofx_volume_label": volume_label,
            "audiofx_volume": volume_slider,
            "audiofx_volume_value": volume_value,
            "audiofx_test_mode": test_mode,
            "audiofx_create_test_sounds": create_test_sounds,
            "audiofx_play_test_tag": play_test_tag,
            "audio_sound_description": description,
            "audio_examples": examples,
            "audio_type": audio_type,
            "audio_create_prompt": create,
            "audio_prompt_output": output,
            "audio_copy_prompt": copy_prompt,
            "audio_save_prompt": save_prompt,
            "audio_save_item_description": save_description,
            "audio_clear_prompt": clear,
            "audio_variation_ambience": ambience,
            "audio_variation_horror": horror,
            "audio_variation_calm": calmer,
            "audio_variation_action": action,
            "audio_saved_box": saved_box,
            "audio_saved_count": saved_count,
            "audio_saved_prompts": saved_list,
            "audio_load_saved": load_saved,
            "audio_delete_saved": delete_saved,
            "audiofx_box": audiofx_box,
            "audiofx_count": audiofx_count,
            "audiofx_list": audiofx_list,
            "audiofx_status": audiofx_status,
            "audiofx_create": create_audiofx,
            "audiofx_import_pack": import_audio_pack,
            "audiofx_add_file": add_audio_file,
            "audiofx_play": play_sound,
            "audiofx_load": load_audiofx,
            "audiofx_delete": delete_audiofx,
        })
        story_sounds.toggled.connect(self._on_story_sounds_changed)
        volume_slider.valueChanged.connect(self._on_audiofx_volume_changed)
        test_mode.toggled.connect(self._on_audiofx_test_mode_changed)
        create_test_sounds.clicked.connect(self._create_test_audiofx)
        play_test_tag.clicked.connect(self._play_test_ambience_tag)
        description.textChanged.connect(lambda *_args: self._schedule_audio_settings_commit())
        audio_type.currentTextChanged.connect(lambda *_args: self._commit_audio_settings_now())
        output.textChanged.connect(lambda *_args: self._schedule_audio_settings_commit())
        create.clicked.connect(lambda *_args: self._create_audio_prompt())
        ambience.clicked.connect(lambda *_args: self._create_audio_prompt("ambience"))
        horror.clicked.connect(lambda *_args: self._create_audio_prompt("horror"))
        calmer.clicked.connect(lambda *_args: self._create_audio_prompt("calmer"))
        action.clicked.connect(lambda *_args: self._create_audio_prompt("action"))
        copy_prompt.clicked.connect(self._copy_audio_prompt)
        save_prompt.clicked.connect(self._save_audio_prompt)
        save_description.clicked.connect(self._save_audio_item_description)
        clear.clicked.connect(self._clear_audio_prompt)
        saved_list.itemSelectionChanged.connect(self._update_audio_saved_buttons)
        saved_list.itemDoubleClicked.connect(lambda *_args: self._load_saved_audio_prompt())
        load_saved.clicked.connect(self._load_saved_audio_prompt)
        delete_saved.clicked.connect(self._delete_saved_audio_prompt)
        audiofx_list.itemSelectionChanged.connect(self._update_audiofx_buttons)
        audiofx_list.itemDoubleClicked.connect(lambda *_args: self._load_selected_audiofx())
        create_audiofx.clicked.connect(self._create_new_audiofx)
        import_audio_pack.clicked.connect(self._import_audio_pack_resources)
        add_audio_file.clicked.connect(self._add_audiofx_file)
        play_sound.clicked.connect(self._play_selected_audiofx)
        load_audiofx.clicked.connect(self._load_selected_audiofx)
        delete_audiofx.clicked.connect(self._delete_selected_audiofx)
        return page

    def _build_master_story_tab(self):
        from PySide6 import QtWidgets

        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.addWidget(self._guide("Describe a whole story once, then let the current chat provider draft matching session state and persona profiles. Review the JSON before applying it."))

        builder_box, builder_layout = self._group("Master Story Builder")
        form = QtWidgets.QFormLayout()
        story_prompt = QtWidgets.QPlainTextEdit()
        story_prompt.setMinimumHeight(130)
        story_prompt.setPlaceholderText(
            "Example: A stylish rainy-night mystery at an old hotel, with a seductive but non-explicit adventure tone, "
            "a narrator, a charming ally, a dangerous curator, and a clear opening objective..."
        )
        visual_direction = QtWidgets.QPlainTextEdit()
        visual_direction.setMinimumHeight(80)
        visual_direction.setPlaceholderText(
            "Optional: describe the avatar art direction, such as fantasy portraits, cinematic realism, "
            "oil-painted nautical adventurers, gothic hotel staff, matching costume language..."
        )
        sfw_mode = QtWidgets.QCheckBox("SFW mode")
        sfw_mode.setChecked(bool(self.settings.get("master_story_sfw_mode", True)))
        sfw_mode.setToolTip(
            "When enabled, the story generator keeps romance, conflict, horror, prejudice, and mature emotional themes non-explicit. "
            "It avoids explicit sexual content, erotic descriptions, and graphic nudity."
        )
        native_count = QtWidgets.QSpinBox()
        native_count.setRange(0, 24)
        native_count.setValue(self._master_story_int_setting("master_story_native_persona_count", 4, 0, 24))
        max_characters = QtWidgets.QSpinBox()
        max_characters.setRange(1, 40)
        max_characters.setValue(self._master_story_int_setting("master_story_max_created_characters", 8, 1, 40))
        allow_exceed_max = QtWidgets.QCheckBox("Allow exceeding max created characters")
        allow_exceed_max.setChecked(bool(self.settings.get("master_story_allow_exceed_max_created_characters", False)))
        use_existing = QtWidgets.QCheckBox("Use already created personas")
        use_existing.setChecked(bool(self.settings.get("master_story_use_existing_personas", True)))
        use_ar = QtWidgets.QCheckBox("Build as AlternativeReality story")
        use_ar.setChecked(bool(self.settings.get("master_story_use_ar", True)))
        auto_create = QtWidgets.QCheckBox("Auto-create missing personas")
        auto_create.setChecked(bool(self.settings.get("master_story_auto_create", True)))
        update_existing = QtWidgets.QCheckBox("Update matching existing personas")
        update_existing.setChecked(bool(self.settings.get("master_story_update_existing", True)))
        auto_avatars = QtWidgets.QCheckBox("Create avatar images for new personas")
        auto_avatars.setChecked(bool(self.settings.get("master_story_auto_avatars", True)))
        avatar_style_sheets = QtWidgets.QCheckBox("Create avatar style sheets for new personas")
        avatar_style_sheets.setChecked(bool(self.settings.get("master_story_avatar_style_sheets", False)))
        clear_memory = QtWidgets.QCheckBox("Clean-start story memory on apply")
        clear_memory.setChecked(bool(self.settings.get("master_story_clear_memory", True)))
        form.addRow("Story prompt", story_prompt)
        form.addRow("Avatar visual direction", visual_direction)
        form.addRow("", sfw_mode)
        form.addRow("Native story personas to draft", native_count)
        form.addRow("Maximum created characters", max_characters)
        form.addRow("", allow_exceed_max)
        form.addRow("", use_existing)
        form.addRow("", use_ar)
        form.addRow("", auto_create)
        form.addRow("", update_existing)
        form.addRow("", auto_avatars)
        form.addRow("", avatar_style_sheets)
        form.addRow("", clear_memory)
        builder_layout.addLayout(form)

        action_row = QtWidgets.QHBoxLayout()
        generate = QtWidgets.QPushButton("Generate Story Setup")
        apply = QtWidgets.QPushButton("Apply Draft")
        save = QtWidgets.QPushButton("Save Story")
        restart = QtWidgets.QPushButton("Clear / Restart Story")
        action_row.addWidget(generate)
        action_row.addWidget(apply)
        action_row.addWidget(save)
        action_row.addWidget(restart)
        action_row.addStretch(1)
        builder_layout.addLayout(action_row)

        draft = QtWidgets.QPlainTextEdit()
        draft.setMinimumHeight(240)
        draft.setPlaceholderText("Generated story JSON draft appears here. You can edit it before applying or saving.")
        builder_layout.addWidget(draft)

        library_box, library_layout = self._group("Story Library")
        library_content = QtWidgets.QHBoxLayout()
        library_left = QtWidgets.QVBoxLayout()
        library_row = QtWidgets.QHBoxLayout()
        story_list = QtWidgets.QComboBox()
        load = QtWidgets.QPushButton("Load Story")
        delete = QtWidgets.QPushButton("Delete Story")
        library_row.addWidget(story_list, 1)
        library_row.addWidget(load)
        library_row.addWidget(delete)
        library_left.addLayout(library_row)
        status = QtWidgets.QLabel("Saved stories live in addon storage and can relink or create personas on load.")
        status.setProperty("muted", True)
        status.setWordWrap(True)
        library_left.addWidget(status)
        image_frame = QtWidgets.QFrame()
        image_frame.setObjectName("mprc_story_image_frame")
        image_frame.setFixedSize(202, 202)
        image_frame.setStyleSheet(
            "QFrame#mprc_story_image_frame { background: #0e1723; border: 1px solid #36506d; border-radius: 8px; padding: 10px; }"
        )
        image_layout = QtWidgets.QVBoxLayout(image_frame)
        image_layout.setContentsMargins(10, 10, 10, 10)
        image_layout.setSpacing(0)
        story_image = QtWidgets.QLabel("No story image")
        story_image.setObjectName("mprc_story_image")
        story_image.setFixedSize(180, 180)
        story_image.setAlignment(QtCore.Qt.AlignCenter)
        story_image.setWordWrap(True)
        story_image.setProperty("muted", True)
        image_layout.addWidget(story_image)
        library_content.addLayout(library_left, 1)
        library_content.addWidget(image_frame)
        library_layout.addLayout(library_content)

        export_box = self._build_story_export_card()

        layout.addWidget(library_box)
        layout.addWidget(export_box)
        layout.addWidget(builder_box)
        layout.addStretch(1)
        self._controls.update({
            "master_story_prompt": story_prompt,
            "master_story_visual_direction": visual_direction,
            "master_story_sfw_mode": sfw_mode,
            "master_story_native_persona_count": native_count,
            "master_story_max_created_characters": max_characters,
            "master_story_allow_exceed_max_created_characters": allow_exceed_max,
            "master_story_use_existing_personas": use_existing,
            "master_story_use_ar": use_ar,
            "master_story_auto_create": auto_create,
            "master_story_update_existing": update_existing,
            "master_story_auto_avatars": auto_avatars,
            "master_story_avatar_style_sheets": avatar_style_sheets,
            "master_story_clear_memory": clear_memory,
            "master_story_generate": generate,
            "master_story_apply": apply,
            "master_story_save": save,
            "master_story_restart": restart,
            "master_story_draft": draft,
            "master_story_list": story_list,
            "master_story_load": load,
            "master_story_delete": delete,
            "master_story_status": status,
            "master_story_image_frame": image_frame,
            "master_story_image": story_image,
        })
        generate.clicked.connect(self._generate_master_story)
        apply.clicked.connect(self._apply_master_story_draft)
        save.clicked.connect(self._save_master_story)
        restart.clicked.connect(self._restart_master_story)
        load.clicked.connect(self._load_selected_master_story)
        delete.clicked.connect(self._delete_selected_master_story)
        story_list.currentIndexChanged.connect(lambda *_args: self._on_master_story_selection_changed())
        sfw_mode.toggled.connect(lambda *_args: self._commit_master_story_options())
        native_count.valueChanged.connect(lambda *_args: self._commit_master_story_options())
        max_characters.valueChanged.connect(lambda *_args: self._commit_master_story_options())
        allow_exceed_max.toggled.connect(lambda *_args: self._commit_master_story_options())
        use_existing.toggled.connect(lambda *_args: self._commit_master_story_options())
        use_ar.toggled.connect(lambda *_args: self._commit_master_story_options())
        auto_create.toggled.connect(lambda *_args: self._commit_master_story_options())
        update_existing.toggled.connect(lambda *_args: self._commit_master_story_options())
        auto_avatars.toggled.connect(lambda *_args: self._commit_master_story_options())
        avatar_style_sheets.toggled.connect(lambda *_args: self._commit_master_story_options())
        clear_memory.toggled.connect(lambda *_args: self._commit_master_story_options())
        return page

    def _build_story_export_card(self):
        from PySide6 import QtWidgets

        box, layout = self._group("Story Library Export")
        description = QtWidgets.QLabel(
            "Export or import a complete story setup with selected personas, voices, memory, sounds, and story assets."
        )
        description.setWordWrap(True)
        description.setProperty("muted", True)
        layout.addWidget(description)

        options_layout = QtWidgets.QGridLayout()
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setHorizontalSpacing(18)
        options_layout.setVerticalSpacing(4)
        option_controls: dict[str, Any] = {}
        saved_selection = self.settings.get("story_library_export_sections")
        selected = set(saved_selection if isinstance(saved_selection, list) else [])
        for index, spec in enumerate(self._story_export_option_specs()):
            key = str(spec.get("key") or "").strip()
            if not key:
                continue
            checkbox = QtWidgets.QCheckBox(str(spec.get("label") or key))
            checkbox.setChecked(key in selected if selected else bool(spec.get("default", True)))
            checkbox.setToolTip(str(spec.get("tooltip") or ""))
            checkbox.toggled.connect(lambda *_args: self._on_story_export_option_changed())
            option_controls[key] = checkbox
            options_layout.addWidget(checkbox, index // 2, index % 2)
        layout.addLayout(options_layout)

        status = QtWidgets.QLabel("Story export availability will appear here.")
        status.setWordWrap(True)
        status.setProperty("muted", True)
        layout.addWidget(status)

        buttons = QtWidgets.QHBoxLayout()
        export_button = QtWidgets.QPushButton("Export")
        import_button = QtWidgets.QPushButton("Import")
        preview_button = QtWidgets.QPushButton("Preview package contents")
        for button in (export_button, import_button, preview_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self._controls["story_export_options"] = option_controls
        self._controls["story_export_status"] = status
        self._controls["story_export_button"] = export_button
        self._controls["story_import_button"] = import_button
        self._controls["story_export_preview"] = preview_button
        export_button.clicked.connect(self._export_story_package)
        import_button.clicked.connect(self._import_story_package)
        preview_button.clicked.connect(self._preview_story_package_contents)
        QtCore.QTimer.singleShot(0, self._refresh_story_export_card)
        return box

    def _build_visual_tab(self):
        from PySide6 import QtWidgets

        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.addWidget(self._guide("Story Images decides when a scene should produce a Visual Reply image and what scene, character, mood, and image intent should guide it."))
        box, box_layout = self._group("Story Images")
        form = QtWidgets.QFormLayout()
        enabled = QtWidgets.QCheckBox("Enable story images in Visual Reply for this persona")
        mode = QtWidgets.QComboBox()
        for mode_id in VISUAL_MODES:
            mode.addItem(VISUAL_MODE_LABELS.get(mode_id, mode_id), mode_id)
        mode_note = QtWidgets.QLabel()
        mode_note.setWordWrap(True)
        mode_note.setProperty("muted", True)
        provider = QtWidgets.QComboBox()
        provider.addItems(list(VISUAL_PROVIDERS))
        model = QtWidgets.QLineEdit()
        size = QtWidgets.QComboBox()
        size.addItems(list(VISUAL_SIZES))
        style = QtWidgets.QComboBox()
        style.addItem("", "")
        for item in self.visual_styles:
            style.addItem(str(item.get("label") or item.get("id") or ""), str(item.get("id") or ""))
        character = QtWidgets.QTextEdit()
        clothing = QtWidgets.QLineEdit()
        environment = QtWidgets.QLineEdit()
        negative = QtWidgets.QLineEdit()
        continuity = QtWidgets.QCheckBox("Keep visual continuity")
        scene = QtWidgets.QCheckBox("Use latest scene summary")
        speaker = QtWidgets.QCheckBox("Include active speaker")
        interval = QtWidgets.QSpinBox()
        interval.setRange(1, 100)
        cooldown = QtWidgets.QSpinBox()
        cooldown.setRange(0, 86400)
        max_auto = QtWidgets.QSpinBox()
        max_auto.setRange(0, 100)
        auto_show = QtWidgets.QCheckBox("Auto-show Visual Reply dock")
        generate = QtWidgets.QPushButton("Generate Visual Reply")
        preview = QtWidgets.QPushButton("Preview Image Prompt")
        form.addRow("", enabled)
        form.addRow("When to generate", mode)
        form.addRow("", mode_note)
        form.addRow("Image provider", provider)
        form.addRow("Image model (optional)", model)
        form.addRow("Image size", size)
        form.addRow("Style preset", style)
        form.addRow("Character and scene look", character)
        form.addRow("Clothing / props", clothing)
        form.addRow("Scene mood and place", environment)
        form.addRow("Avoid in image", negative)
        form.addRow("", continuity)
        form.addRow("", scene)
        form.addRow("", speaker)
        form.addRow("Check every N replies", interval)
        form.addRow("Wait between images", cooldown)
        form.addRow("Max images this session", max_auto)
        form.addRow("", auto_show)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(generate)
        row.addWidget(preview)
        row.addStretch(1)
        box_layout.addLayout(form)
        box_layout.addLayout(row)
        layout.addWidget(box)
        self._controls.update({
            "visual_enabled": enabled,
            "visual_mode": mode,
            "visual_mode_note": mode_note,
            "visual_provider": provider,
            "visual_model": model,
            "visual_size": size,
            "visual_style": style,
            "visual_character": character,
            "visual_clothing": clothing,
            "visual_environment": environment,
            "visual_negative": negative,
            "visual_continuity": continuity,
            "visual_scene": scene,
            "visual_speaker": speaker,
            "visual_interval": interval,
            "visual_cooldown": cooldown,
            "visual_max_auto": max_auto,
            "visual_auto_show": auto_show,
            "visual_generate": generate,
            "visual_preview": preview,
        })
        mode.currentIndexChanged.connect(lambda *_args: self._update_visual_mode_note())
        mode.currentIndexChanged.connect(lambda *_args: self._commit_visual_now())
        for widget in (provider, size, style):
            widget.currentTextChanged.connect(lambda *_args: self._commit_visual_now())
        for widget in (model, clothing, environment, negative):
            widget.textChanged.connect(lambda *_args: self._schedule_visual_commit())
            widget.editingFinished.connect(self._commit_visual_now)
        character.textChanged.connect(lambda *_args: self._schedule_visual_commit())
        for widget in (enabled, continuity, scene, speaker, auto_show):
            widget.toggled.connect(lambda *_args: self._commit_visual_now())
        for widget in (interval, cooldown, max_auto):
            widget.valueChanged.connect(lambda *_args: self._commit_visual_now())
        preview.clicked.connect(self._preview_visual_prompt)
        generate.clicked.connect(self._generate_visual_reply)
        return page

    def _build_debug_tab(self):
        from PySide6 import QtWidgets

        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.addWidget(self._guide("Troubleshooting keeps advanced prompt, voice, state, and Visual Reply diagnostics out of the normal story workflow. Expand a section only when you need to inspect what was sent."))
        for key, title in (
            ("debug_prompt", "Advanced: persona prompt"),
            ("debug_visual", "Advanced: image prompt"),
            ("debug_voice", "Advanced: voice routing"),
            ("debug_state", "Advanced: story state summary"),
        ):
            box, box_layout = self._group(title)
            box.setCheckable(True)
            box.setChecked(False)
            text = QtWidgets.QPlainTextEdit()
            text.setReadOnly(True)
            text.setMinimumHeight(100)
            copy_button = QtWidgets.QPushButton("Copy")
            copy_button.clicked.connect(lambda *_args, edit=text: QtWidgets.QApplication.clipboard().setText(edit.toPlainText()))
            box_layout.addWidget(text)
            box_layout.addWidget(copy_button)
            text.setVisible(False)
            copy_button.setVisible(False)
            box.toggled.connect(lambda checked, edit=text, button=copy_button: (edit.setVisible(bool(checked)), button.setVisible(bool(checked))))
            layout.addWidget(box)
            self._controls[key] = text
        calls_box, calls_layout = self._group("Advanced: Visual Reply request log")
        calls_box.setCheckable(True)
        calls_box.setChecked(False)
        calls = QtWidgets.QPlainTextEdit()
        calls.setReadOnly(True)
        calls.setMinimumHeight(160)
        calls_copy = QtWidgets.QPushButton("Copy")
        calls_clear = QtWidgets.QPushButton("Clear Visual Reply Log")
        calls_copy.clicked.connect(lambda *_args, edit=calls: QtWidgets.QApplication.clipboard().setText(edit.toPlainText()))
        calls_clear.clicked.connect(self._clear_visual_debug_log)
        calls_buttons = QtWidgets.QHBoxLayout()
        calls_buttons.addWidget(calls_copy)
        calls_buttons.addWidget(calls_clear)
        calls_buttons.addStretch(1)
        calls_layout.addWidget(calls)
        calls_layout.addLayout(calls_buttons)
        calls.setVisible(False)
        calls_copy.setVisible(False)
        calls_clear.setVisible(False)
        calls_box.toggled.connect(
            lambda checked: (
                calls.setVisible(bool(checked)),
                calls_copy.setVisible(bool(checked)),
                calls_clear.setVisible(bool(checked)),
            )
        )
        layout.addWidget(calls_box)
        self._controls["debug_visual_calls"] = calls
        self._controls["debug_visual_calls_copy"] = calls_copy
        self._controls["debug_visual_calls_clear"] = calls_clear
        clear = QtWidgets.QPushButton("Clear troubleshooting output")
        clear.clicked.connect(self._clear_debug)
        layout.addWidget(clear)
        self._controls["debug_clear"] = clear
        return page

    def refresh_ui(self):
        if self._widget is None or self.is_shutdown():
            return
        self._ensure_session_persona()
        active = self.active_persona()
        self._syncing = True
        try:
            self._refresh_persona_selectors()
            self._refresh_chat_play_controls()
            self._refresh_narrator_selector()
            self._refresh_voice_persona_selector()
            self._controls["enabled"].setChecked(bool(self.session.enabled))
            self._controls["show_character"].setChecked(bool(self.settings.get("show_current_character_visual", False)))
            self._controls["ar_mode"].setChecked(self.session.mode == AR_MODE)
            if active is not None:
                self._populate_editor(active)
                self._populate_voice(self._selected_voice_persona() or active)
                self._populate_visual(active)
            self._populate_session()
            self._populate_ar()
            self._populate_audio()
            self._populate_master_stories()
            self._refresh_story_export_card()
            self._refresh_character_preview()
            self._refresh_debug()
            self._refresh_reliability_panels()
        finally:
            self._syncing = False

    def _refresh_persona_selectors(self):
        active_id = self.session.active_persona_id
        combo = self._controls.get("active")
        if combo is not None:
            combo.blockSignals(True)
            combo.clear()
            for persona in self.personas:
                combo.addItem(self._persona_story_label(persona), persona.id)
            index = combo.findData(active_id)
            combo.setCurrentIndex(max(0, index))
            combo.blockSignals(False)
        persona_list = self._controls.get("persona_list")
        if persona_list is not None:
            persona_list.blockSignals(True)
            persona_list.clear()
            from PySide6 import QtWidgets

            for persona in self.personas:
                label = self._persona_story_label(persona) + ("" if persona.enabled else " (disabled)")
                list_item = QtWidgets.QListWidgetItem(label)
                list_item.setData(32, persona.id)
                list_item.setToolTip(self._persona_story_tooltip(persona))
                persona_list.addItem(list_item)
            row = next((i for i, p in enumerate(self.personas) if p.id == active_id), 0)
            persona_list.setCurrentRow(max(0, row))
            persona_list.blockSignals(False)
        delete_button = self._controls.get("delete_persona")
        if delete_button is not None and hasattr(delete_button, "setEnabled"):
            selected = self.active_persona()
            protected = self._persona_is_master_narrator(selected)
            delete_button.setEnabled(len(self.personas) > 1 and not protected)
            if protected:
                delete_button.setToolTip("Master narrator personas are protected. Uncheck Master narrator in Editor before deleting.")
            else:
                delete_button.setToolTip("Delete the selected persona.")
        next_speaker = self._controls.get("next_speaker")
        if next_speaker is not None:
            next_speaker.blockSignals(True)
            next_speaker.clear()
            for persona in self.personas:
                next_speaker.addItem(self._persona_story_label(persona), persona.id)
            index = next_speaker.findData(self.session.current_speaker_id)
            next_speaker.setCurrentIndex(max(0, index))
            next_speaker.blockSignals(False)

    def _refresh_chat_play_controls(self):
        self._set_chat_play_float_button_text()
        self._sync_chat_play_voice_volume_controls()
        combo = self._controls.get("chat_speaker")
        if combo is not None:
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Player", "")
            for persona in self.personas:
                combo.addItem(self._persona_story_label(persona), persona.id)
            index = combo.findData(self.session.current_speaker_id)
            combo.setCurrentIndex(max(0, index))
            combo.blockSignals(False)
        use_ar = self._controls.get("chat_use_ar")
        if use_ar is not None and hasattr(use_ar, "setChecked"):
            use_ar.blockSignals(True)
            use_ar.setChecked(self.session.mode == AR_MODE)
            use_ar.blockSignals(False)
        visuals = self._controls.get("chat_visuals")
        if visuals is not None and hasattr(visuals, "setChecked"):
            visuals.blockSignals(True)
            visuals.setChecked(bool(self.settings.get("chat_play_allow_story_visuals", False)))
            visuals.blockSignals(False)
        structured_output = self._controls.get("chat_structured_output")
        if structured_output is not None and hasattr(structured_output, "setChecked"):
            structured_output.blockSignals(True)
            structured_output.setChecked(self._mprc_chat_structured_output_enabled())
            structured_output.blockSignals(False)
        structured_scope = self._controls.get("chat_structured_output_scope")
        if structured_scope is not None and hasattr(structured_scope, "findData"):
            structured_scope.blockSignals(True)
            index = structured_scope.findData(self._mprc_chat_structured_output_scope())
            structured_scope.setCurrentIndex(max(0, index))
            structured_scope.setEnabled(self._mprc_chat_structured_output_enabled())
            structured_scope.blockSignals(False)
        self._refresh_remote_controls()
        self._refresh_chromecast_controls()
        self._sync_chat_play_story_font_controls()
        self._refresh_chat_play_buffer_race()
        pacing = self._controls.get("chat_director_pacing")
        if pacing is not None and hasattr(pacing, "setCurrentText"):
            pacing.blockSignals(True)
            pacing.setCurrentText(str(self.session.ar_pacing or "Balanced"))
            pacing.blockSignals(False)
        choice_mode = self._controls.get("chat_director_choice_mode")
        if choice_mode is not None and hasattr(choice_mode, "findData"):
            choice_mode.blockSignals(True)
            index = choice_mode.findData(self._mprc_chat_choice_mode())
            choice_mode.setCurrentIndex(max(0, index))
            choice_mode.blockSignals(False)
        self._refresh_chat_play_state_sidebar()

    def _chat_story_font_size(self) -> int:
        try:
            value = int(self.settings.get("chat_story_font_size", 13))
        except Exception:
            value = 13
        return max(9, min(28, value))

    def _sync_chat_play_story_font_controls(self, *, spin=None) -> None:
        spin = spin or self._controls.get("chat_story_font_size")
        value = self._chat_story_font_size()
        if spin is not None and hasattr(spin, "setValue"):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        self._apply_chat_play_story_font_size(value)

    def _apply_chat_play_story_font_size(self, size: int | None = None, *, transcript=None) -> None:
        try:
            value = int(size if size is not None else self._chat_story_font_size())
        except Exception:
            value = 13
        value = max(9, min(28, value))
        transcript = transcript or self._controls.get("chat_transcript")
        if transcript is None:
            return
        try:
            font = QtGui.QFont(transcript.font())
            font.setPointSize(value)
            transcript.setFont(font)
            document = transcript.document() if hasattr(transcript, "document") else None
            if document is not None and hasattr(document, "setDefaultFont"):
                document.setDefaultFont(font)
        except RuntimeError:
            return
        except Exception:
            return

    def _on_mprc_story_font_size_changed(self, value: int) -> None:
        if self._syncing:
            return
        try:
            size = int(value)
        except Exception:
            size = 13
        size = max(9, min(28, size))
        self.settings["chat_story_font_size"] = size
        self.storage.save_settings(self.settings)
        self._apply_chat_play_story_font_size(size)

    def _show_mprc_voice_volume_popout(self) -> None:
        source = self._controls.get("chat_voice_volume_popout")
        parent = source if isinstance(source, QtWidgets.QWidget) else None
        popup = QtWidgets.QDialog(parent, QtCore.Qt.Popup)
        popup.setObjectName("mprc_chat_voice_volume_popout")
        popup.setWindowTitle("Voice volume")
        popup.setMinimumWidth(320)
        popup.setStyleSheet(
            """
            QDialog#mprc_chat_voice_volume_popout {
                background: #101923;
                border: 1px solid #36506d;
                border-radius: 8px;
            }
            QLabel {
                color: #dbeafe;
                font-weight: 700;
            }
            """
        )
        layout = QtWidgets.QVBoxLayout(popup)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        header.addWidget(QtWidgets.QLabel("Voice volume"))
        header.addStretch(1)
        value_label = QtWidgets.QLabel(f"{self.mprc_voice_volume_percent()}%")
        value_label.setMinimumWidth(42)
        value_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        header.addWidget(value_label)
        layout.addLayout(header)

        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setMinimumWidth(280)
        slider.setValue(self.mprc_voice_volume_percent())
        slider.setToolTip("Set the volume for addon-routed Play voice.")
        layout.addWidget(slider)

        def apply_volume(value: int) -> None:
            volume = max(0, min(100, int(value or 0)))
            value_label.setText(f"{volume}%")
            main_slider = self._controls.get("chat_voice_volume")
            if main_slider is not None and main_slider is not slider and hasattr(main_slider, "setValue"):
                main_slider.setValue(volume)
            else:
                self._on_mprc_voice_volume_changed(volume)

        slider.valueChanged.connect(apply_volume)
        self._chat_voice_volume_popup = popup
        if parent is not None:
            popup.move(parent.mapToGlobal(QtCore.QPoint(0, parent.height() + 4)))
        popup.show()
        slider.setFocus(QtCore.Qt.PopupFocusReason)

    def mprc_voice_volume_percent(self) -> int:
        try:
            value = int(self.settings.get("mprc_voice_volume", 100))
        except Exception:
            value = 100
        return max(0, min(100, value))

    def mprc_voice_volume_factor(self) -> float:
        return self.mprc_voice_volume_percent() / 100.0

    def _sync_chat_play_voice_volume_controls(self, *, slider=None, value_label=None) -> None:
        slider = slider or self._controls.get("chat_voice_volume")
        value_label = value_label or self._controls.get("chat_voice_volume_value")
        volume = self.mprc_voice_volume_percent()
        if slider is not None and hasattr(slider, "setValue"):
            slider.blockSignals(True)
            slider.setValue(volume)
            slider.blockSignals(False)
        if value_label is not None and hasattr(value_label, "setText"):
            value_label.setText(f"{volume}%")

    def _on_mprc_voice_volume_changed(self, value: int) -> None:
        if self._syncing:
            return
        try:
            volume = int(value)
        except Exception:
            volume = 100
        volume = max(0, min(100, volume))
        self.settings["mprc_voice_volume"] = volume
        self.storage.save_settings(self.settings)
        label = self._controls.get("chat_voice_volume_value")
        if label is not None and hasattr(label, "setText"):
            label.setText(f"{volume}%")
        self._refresh_debug()

    def _refresh_chat_play_buffer_race(self) -> None:
        summary = self._controls.get("chat_buffer_race_summary")
        render_bar = self._controls.get("chat_buffer_race_render")
        playback_bar = self._controls.get("chat_buffer_race_playback")
        if summary is None and render_bar is None and playback_bar is None:
            return
        counts = self._chat_play_buffer_race_counts()
        render_active = counts["render_active"]
        playback_active = counts["playback_active"]
        total_active = render_active + playback_active
        if summary is not None and hasattr(summary, "setText"):
            if total_active:
                summary.setText(f"Active: render {render_active}, preview/playback {playback_active}.")
            else:
                summary.setText("Idle: render and playback buffers are clear.")
        if render_bar is not None and hasattr(render_bar, "setValue"):
            render_bar.setValue(100 if render_active == 0 else 38)
            render_bar.setFormat("Render Ready: ready" if render_active == 0 else f"Render Ready: {render_active} running")
        if playback_bar is not None and hasattr(playback_bar, "setValue"):
            playback_bar.setValue(100 if playback_active == 0 else 38)
            playback_bar.setFormat(
                "Preview / Playback: ready" if playback_active == 0 else f"Preview / Playback: {playback_active} running"
            )

    def _chat_play_buffer_race_counts(self) -> dict[str, int]:
        with self._state_lock:
            tokens = [str(token or "") for token in self._active_worker_tokens]
            manual_images = len(self._manual_character_image_inflight)
            tts_persona_visuals = len(self._tts_persona_visual_inflight)
            tts_visual_replies = len(self._tts_visual_reply_inflight)
            story_audio_active = bool(self._story_audio_block_active)
        with self._mprc_tts_state_lock:
            tts_active = bool(self._mprc_tts_token or self._mprc_tts_controller is not None)

        render_prefixes = (
            "mprc_chat",
            "mprc_visual",
            "mprc_manual_visual",
            "mprc_draft_avatar",
            "mprc_story_avatar",
            "mprc_tts_character_image",
            "mprc_tts_visual_reply",
            "master_story",
            "refine",
        )
        playback_prefixes = ("mprc_tts", "voice_preview")
        render_active = sum(1 for token in tokens if token.startswith(render_prefixes))
        playback_active = sum(
            1
            for token in tokens
            if token.startswith(playback_prefixes)
            and not token.startswith(("mprc_tts_character_image", "mprc_tts_visual_reply"))
        )
        render_active = max(render_active, manual_images + tts_persona_visuals + tts_visual_replies)
        playback_active = max(playback_active, 1 if tts_active else 0)
        playback_active += 1 if story_audio_active else 0
        return {
            "render_active": max(0, int(render_active)),
            "playback_active": max(0, int(playback_active)),
        }

    def _set_list_items(self, widget, items: list[str], *, empty_text: str = ""):
        if widget is None:
            return
        widget.clear()
        visible = [str(item or "").strip() for item in list(items or []) if str(item or "").strip()]
        if not visible and empty_text:
            visible = [empty_text]
        for text in visible:
            widget.addItem(text)

    def _set_chat_play_summary_text(self, key: str, text: str) -> None:
        widget = self._controls.get(key)
        if widget is None or not hasattr(widget, "setPlainText"):
            return
        widget.setPlainText(str(text or "").strip())

    def _refresh_chat_play_story_engine_cards(self) -> None:
        if not self._controls.get("chat_story_engine_tabs"):
            return
        self._set_chat_play_summary_text("chat_story_director_summary", self._chat_play_story_director_summary_text())
        self._set_chat_play_summary_text("chat_memory_databank_summary", self._chat_play_memory_databank_summary_text())
        self._set_chat_play_summary_text("chat_visual_beat_summary", self._chat_play_visual_beat_summary_text())
        self._set_chat_play_summary_text("chat_voice_segments_summary", self._chat_play_voice_segments_summary_text())
        self._set_chat_play_summary_text("chat_spotify_music_summary", self._chat_play_spotify_music_summary_text())

    def _chat_play_story_director_summary_text(self) -> str:
        full_setup = not bool(self._mprc_chat_history) and int(getattr(self.session, "turn_index", 0) or 0) <= 0
        speaker = self.current_speaker_persona()
        narrator = self.selected_narrator_persona()
        pacing = str(self.session.ar_pacing or self._control_current_text("chat_director_pacing") or "Balanced").strip()
        tone = str(self._control_current_text("chat_director_tone") or "Keep current").strip()
        agency = str(self._control_current_text("chat_director_agency") or "Guided").strip()
        choice_mode = "Ask next move" if self._mprc_chat_choice_mode() == "ask_next_move" else "Offer choices"
        structured = "on" if self._mprc_chat_structured_output_enabled() else "off"
        structured_scope = self._mprc_chat_structured_output_scope().replace("_", " ")
        lines = [
            "Cast mode: Focused speaker for normal Play turns; Joined cast for the opening/setup prompt.",
            f"Current prompt mode: {'Joined cast' if full_setup else 'Focused speaker'}.",
            f"Focused speaker: {speaker.display_name if speaker is not None else 'Player'}.",
            f"Narrator voice/persona: {narrator.display_name if narrator is not None else 'auto / not resolved yet'}.",
            f"Director controls: pacing={pacing}, tone={tone}, agency={agency}, ending={choice_mode}.",
            f"Structured JSON: {structured}, scope={structured_scope}.",
            "Speaker discipline: narration, character dialogue, choices, and story audio tags are kept in separate blocks for routing.",
        ]
        return "\n".join(lines)

    def _chat_play_memory_databank_summary_text(self) -> str:
        backend_raw = str(
            self.settings.get("long_memory_database_backend")
            or self.settings.get("memory_database_backend")
            or "sqlite"
        ).strip().lower()
        backend_label = {
            "sqlite": "SQLite",
            "postgres": "PostgreSQL",
            "postgresql": "PostgreSQL",
        }.get(backend_raw, backend_raw or "SQLite")
        sources = self._remote_memory_databank_sources(self.settings)
        memory = getattr(self, "long_memory", None)
        payload: dict[str, Any] = {}
        if memory is not None and hasattr(memory, "load"):
            try:
                loaded = memory.load()
                payload = loaded if isinstance(loaded, dict) else {}
            except Exception:
                payload = {}
        events = list(payload.get("events") or []) if isinstance(payload.get("events"), list) else []
        chapters = list(payload.get("chapters") or []) if isinstance(payload.get("chapters"), list) else []
        pinned_raw = payload.get("pinned_facts")
        if isinstance(pinned_raw, str):
            pinned = [item.strip() for item in pinned_raw.splitlines() if item.strip()]
        else:
            pinned = [str(item).strip() for item in list(pinned_raw or []) if str(item).strip()]
        character_memory = dict(payload.get("character_memory") or {}) if isinstance(payload.get("character_memory"), dict) else {}
        indexed_sources = sorted(str(item) for item in list(getattr(memory, "_indexed_databank_sources", set()) or []) if str(item).strip())
        database_available = bool(getattr(memory, "database", None) is not None)
        databank_available = bool(getattr(memory, "databank", None) is not None)
        lines = [
            f"Database backend: {backend_label} ({'available' if database_available else 'not open'}).",
            f"Data bank: {'available' if databank_available else 'not available'}.",
            f"Pinned facts: {len(pinned)}.",
            f"Remembered story events: {len(events)}.",
            f"Chapter summaries: {len(chapters)}.",
            f"Character memory entries: {len(character_memory)}.",
            "Configured data-bank sources: " + (", ".join(sources) if sources else "none configured."),
            "Indexed data-bank sources: " + (", ".join(indexed_sources) if indexed_sources else "none indexed yet."),
            "Prompt use: relevant memory and data-bank snippets are read into hidden MPRC story context; this card does not change memory.",
        ]
        return "\n".join(lines)

    def _chat_play_visual_beat_summary_text(self) -> str:
        persona = self.current_speaker_persona() or self.active_persona()
        latest = self._latest_mprc_story_reply_text()
        beat = story_director.build_visual_beat_context(
            persona=persona,
            session=self.session,
            reason="assistant_reply" if latest else "manual",
            source_text=latest,
        )
        prompt, prompt_reason, prompt_persona = self._chat_play_visual_prompt_snapshot()
        lines = [
            f"Latest visible beat: {beat.get('latest_visible_action') or 'No latest visible action yet.'}",
            f"Visual subject: {beat.get('visual_subject') or 'current scene'}.",
            f"Location: {beat.get('location') or 'unknown'}.",
            f"Time: {beat.get('time_of_day') or 'not set'}.",
            f"Mood: {beat.get('mood') or 'not set'}.",
            f"Story goal: {beat.get('story_goal') or 'not set'}.",
            f"Image intent: {prompt or 'No Visual Reply prompt has been generated yet.'}",
        ]
        if prompt_reason or prompt_persona:
            lines.append(
                "Prompt snapshot: "
                + ", ".join(
                    item for item in (f"reason={prompt_reason}" if prompt_reason else "", f"persona={prompt_persona}" if prompt_persona else "") if item
                )
            )
        lines.append("Selection rule: prefer the newest visible scene beat; ignore choices, hidden prompt text, and stale setup.")
        return "\n".join(lines)

    def _chat_play_voice_segments_summary_text(self) -> str:
        latest = self._latest_mprc_story_reply_text()
        tag_speakers = self._mprc_story_reply_tagged_speakers(latest)
        lines = [
            "Multi-voice contract: [NARRATOR] carries narration; [CHARACTER: Exact Name] carries only that speaker's spoken line.",
            "Tagged speakers: " + (", ".join(tag_speakers) if tag_speakers else "none in latest reply yet."),
        ]
        if not latest:
            lines.append("Latest reply: no Play story reply has been produced yet.")
            return "\n".join(lines)
        try:
            segments = self._mprc_chat_reply_voice_segments(latest)
        except Exception as exc:
            segments = []
            lines.append(f"Route preview unavailable: {exc}")
        lines.append(f"Route preview segments: {len(segments)}.")
        for index, segment in enumerate(list(segments or [])[:8], start=1):
            route = dict(segment.get("voice_route") or {}) if isinstance(segment, dict) else {}
            persona_id = str(segment.get("persona_id") or route.get("persona_id") or "").strip()
            display = str(segment.get("display_name") or route.get("display_name") or persona_id or "Narrator").strip()
            sample = str(segment.get("voice_path") or route.get("sample_path") or "").strip()
            sample_label = Path(sample).name if sample else "no voice sample"
            reason = str(route.get("route_reason") or "route").strip()
            text = self._mprc_compact(segment.get("text", ""), 110) if isinstance(segment, dict) else ""
            lines.append(f"{index}. {display}: {sample_label}, {reason}, {text}")
        return "\n".join(lines)

    def _chat_play_spotify_music_summary_text(self) -> str:
        service = self._spotify_sense_service()
        payload = dict(getattr(self, "_last_spotify_story_music_payload", {}) or {})
        result = dict(getattr(self, "_last_spotify_story_music_result", {}) or {})
        lines = [
            "Spotify Sense: " + ("available" if service is not None else "not loaded"),
            "Story music: MPRC only sends scene intent; Spotify Sense owns playback, device selection, and fades.",
        ]
        if not payload:
            lines.append("Last request: none yet.")
            lines.append("Default selection rule: prefer cinematic ambience unless the story beat clearly needs active music.")
            return "\n".join(lines)
        lines.extend(
            [
                f"Last request mood: {payload.get('mood') or 'unknown'}.",
                f"Music kind: {payload.get('music_kind') or 'ambient'}.",
                f"Spotify query: {payload.get('query') or 'not set'}.",
                f"Latest visible beat: {payload.get('latest_visible_beat') or 'none captured'}.",
            ]
        )
        if result:
            if result.get("ok"):
                state = "transitioning" if result.get("transitioning") else ("started" if result.get("started") else "accepted")
                if result.get("skipped"):
                    state = "skipped"
                lines.append(f"Last result: {state}.")
            else:
                lines.append(f"Last result: blocked or failed: {result.get('error') or result.get('error_code') or 'unknown error'}.")
        else:
            lines.append("Last result: pending or not sent.")
        return "\n".join(lines)

    @staticmethod
    def _mprc_chat_message_text(message: dict[str, str] | None) -> str:
        if not isinstance(message, dict):
            return ""
        return str(message.get("content") or message.get("text") or "").strip()

    def _spotify_story_music_payload_for_reply(self, assistant_text: str, *, user_text: str = "") -> dict[str, Any]:
        persona = self.current_speaker_persona() or self.active_persona()
        beat = story_director.build_visual_beat_context(
            persona=persona,
            session=self.session,
            reason="spotify_story_music",
            source_text=str(assistant_text or ""),
        )
        ar_state = getattr(self.session, "ar_state", None)
        latest_visible = str(beat.get("latest_visible_action") or "").strip()
        scene = str(
            getattr(ar_state, "current_scene", "")
            or getattr(self.session, "scene_summary", "")
            or getattr(self.session, "scene_title", "")
            or ""
        ).strip()
        location = str(beat.get("location") or getattr(self.session, "location", "") or "").strip()
        mood = self._spotify_story_music_mood(
            assistant_text,
            user_text=user_text,
            beat=beat,
        )
        music_kind = self._spotify_story_music_kind(
            assistant_text,
            user_text=user_text,
            beat=beat,
            mood=mood,
        )
        prompt, prompt_reason, prompt_persona = self._chat_play_visual_prompt_snapshot()
        query = self._spotify_story_music_query(mood, music_kind)
        payload: dict[str, Any] = {
            "event": "story_turn",
            "source": "multi_persona_roleplay",
            "mood": mood,
            "music_kind": music_kind,
            "query": query,
            "prefer_ambient": music_kind == "ambient",
            "scene": scene,
            "location": location,
            "time_of_day": str(beat.get("time_of_day") or "").strip(),
            "story_goal": str(beat.get("story_goal") or "").strip(),
            "latest_visible_beat": latest_visible,
            "visual_subject": str(beat.get("visual_subject") or "").strip(),
            "image_intent": prompt,
            "image_intent_reason": prompt_reason,
            "image_intent_persona": prompt_persona,
            "user_text": str(user_text or "").strip(),
            "reply_excerpt": self._mprc_compact(assistant_text, 600),
            "tension_level": self._spotify_story_tension_level(),
        }
        active_cast = [
            self._persona_story_label(persona)
            for persona in self.story_prompt_personas()
            if getattr(persona, "id", "")
        ]
        if active_cast:
            payload["active_cast"] = active_cast[:8]
        return payload

    def _maybe_request_spotify_story_music(self, assistant_text: str, *, user_text: str = "") -> None:
        payload = self._spotify_story_music_payload_for_reply(assistant_text, user_text=user_text)
        self._last_spotify_story_music_payload = dict(payload)
        service = self._spotify_sense_service()
        if service is None or not hasattr(service, "invoke_capability"):
            self._last_spotify_story_music_result = {
                "ok": True,
                "started": False,
                "skipped": True,
                "reason": "spotify_sense_unavailable",
                "message": "Spotify Sense service is not loaded.",
            }
            self._request_ui_refresh()
            return
        key = "|".join(str(payload.get(item) or "") for item in ("query", "mood", "music_kind"))
        cooldown_seconds = self._spotify_story_music_cooldown_seconds()
        now = time.time()
        if (
            key
            and key == str(getattr(self, "_last_spotify_story_music_key", "") or "")
            and now - float(getattr(self, "_last_spotify_story_music_at", 0.0) or 0.0) < cooldown_seconds
        ):
            self._last_spotify_story_music_result = {
                "ok": True,
                "started": False,
                "skipped": True,
                "reason": "cooldown",
                "query": payload.get("query"),
            }
            self._request_ui_refresh()
            return
        token = self._new_worker_token("mprc_spotify_music")
        if not token:
            return

        def worker() -> None:
            result: dict[str, Any]
            try:
                raw = service.invoke_capability("spotify.story_hook", dict(payload))
                result = dict(raw or {}) if isinstance(raw, dict) else {"ok": False, "error": "Spotify Sense returned no result."}
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            self._last_spotify_story_music_result = result
            if bool(result.get("ok")) and not bool(result.get("skipped")) and key:
                self._last_spotify_story_music_key = key
                self._last_spotify_story_music_at = time.time()
            self._finish_worker_token(token)

        if not self._start_daemon_worker(token, worker, name="nc-mprc-spotify-story-music"):
            self._cancel_worker_token(token)

    def _spotify_story_music_cooldown_seconds(self) -> float:
        try:
            return max(0.0, float(self.settings.get("spotify_story_music_cooldown_seconds", 45)))
        except Exception:
            return 45.0

    def _spotify_story_tension_level(self) -> int:
        state = getattr(self.session, "ar_state", None)
        for source in (state, self.session):
            try:
                return max(0, min(10, int(float(getattr(source, "tension_level", 0) or 0))))
            except Exception:
                continue
        return 3

    def _spotify_story_music_mood(self, assistant_text: str, *, user_text: str = "", beat: dict[str, Any] | None = None) -> str:
        beat = dict(beat or {})
        text = " ".join(
            str(item or "")
            for item in (
                assistant_text,
                user_text,
                beat.get("mood"),
                beat.get("latest_visible_action"),
                beat.get("current_scene"),
                beat.get("location"),
                beat.get("story_goal"),
                beat.get("recent_visible_events"),
            )
        ).lower()
        tension = self._spotify_story_tension_level()
        if self._spotify_story_text_has_word(text, ("battle", "chase", "attack", "dragon", "war", "explosion")) or tension >= 8:
            return "epic"
        if any(word in text for word in ("horror", "terror", "dread", "monster", "haunted", "blood")):
            return "dark"
        if any(word in text for word in ("mystery", "tense curiosity", "archive", "sigil", "sealed", "lantern", "secret", "unknown")):
            return "mystery"
        if any(word in text for word in ("sad", "grief", "loss", "lonely", "melancholy")):
            return "sad"
        if any(word in text for word in ("calm", "peaceful", "safe", "rest", "tavern", "gentle")) and tension <= 4:
            return "calm"
        if tension >= 6:
            return "mystery"
        return "fantasy"

    def _spotify_story_music_kind(
        self,
        assistant_text: str,
        *,
        user_text: str = "",
        beat: dict[str, Any] | None = None,
        mood: str = "",
    ) -> str:
        text = " ".join([assistant_text, user_text, str((beat or {}).get("latest_visible_action") or "")]).lower()
        if (
            "[music:" in text
            or self._spotify_story_text_has_word(text, ("battle", "chase", "song"))
            or "theme swells" in text
            or "music rises" in text
        ):
            return "music"
        if str(mood or "").strip().lower() == "epic" and self._spotify_story_tension_level() >= 8:
            return "music"
        return "ambient"

    @staticmethod
    def _spotify_story_music_query(mood: str, music_kind: str) -> str:
        normalized_mood = str(mood or "fantasy").strip().lower()
        normalized_kind = str(music_kind or "ambient").strip().lower()
        ambient = {
            "dark": "dark cinematic ambient story ambience",
            "mystery": "mysterious cinematic ambient story ambience",
            "epic": "epic fantasy adventure story ambience",
            "calm": "calm cinematic fantasy story ambience",
            "sad": "melancholy cinematic ambient story ambience",
            "fantasy": "cinematic fantasy story ambience",
        }
        music = {
            "dark": "dark cinematic story music",
            "mystery": "mysterious cinematic story music",
            "epic": "epic fantasy adventure story music",
            "calm": "calm fantasy story music",
            "sad": "melancholy orchestral story music",
            "fantasy": "cinematic fantasy story music",
        }
        return (music if normalized_kind == "music" else ambient).get(
            normalized_mood,
            "cinematic fantasy story music" if normalized_kind == "music" else "cinematic fantasy story ambience",
        )

    @staticmethod
    def _spotify_story_text_has_word(text: str, words: tuple[str, ...]) -> bool:
        haystack = str(text or "").lower()
        for word in words:
            needle = str(word or "").strip().lower()
            if needle and re.search(rf"\b{re.escape(needle)}\b", haystack):
                return True
        return False

    def _latest_mprc_story_reply_text(self) -> str:
        latest = str(getattr(self, "_remote_latest_reply_text", "") or "").strip()
        if latest:
            return latest
        for message in reversed(list(getattr(self, "_mprc_chat_history", []) or [])):
            if not isinstance(message, dict):
                continue
            if str(message.get("role") or "").strip().lower() == "assistant":
                content = str(message.get("content") or "").strip()
                if content:
                    return content
        return ""

    def _chat_play_visual_prompt_snapshot(self) -> tuple[str, str, str]:
        raw = str(getattr(self, "_debug_visual_prompt", "") or "").strip()
        if raw.startswith("{"):
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {}
            if isinstance(payload, dict):
                prompt = str(payload.get("prompt") or payload.get("final_prompt") or payload.get("image_prompt") or "").strip()
                reason = str(payload.get("reason") or "").strip()
                persona_id = str(payload.get("persona_id") or payload.get("visual_subject") or "").strip()
                return self._mprc_compact(prompt, 260), self._mprc_compact(reason, 80), self._mprc_compact(persona_id, 80)
        debug = str(getattr(self, "_chat_visual_prompt_debug", "") or "").strip()
        if debug:
            one_line = self._mprc_compact(debug, 260)
            return one_line, "", ""
        return "", "", ""

    @staticmethod
    def _mprc_story_reply_tagged_speakers(text: str) -> list[str]:
        speakers: list[str] = []
        for match in re.finditer(r"\[(NARRATOR|CHARACTER\s*:\s*([^\]]+))\]", str(text or ""), flags=re.IGNORECASE):
            raw = match.group(2) if match.group(2) is not None else match.group(1)
            speaker = re.sub(r"\s+", " ", str(raw or "")).strip()
            if speaker.lower() == "narrator":
                speaker = "Narrator"
            if speaker and speaker not in speakers:
                speakers.append(speaker)
        return speakers

    def _refresh_chat_play_state_sidebar(self):
        active = self.active_persona()
        speaker = self.current_speaker_persona()
        ar_state = self.session.ar_state
        scene = str(ar_state.current_scene or self.session.scene_title or "Untitled scene").strip()
        location = str(ar_state.location or self.session.location or "Unknown location").strip()
        time_of_day = str(ar_state.time_of_day or self.session.time_of_day or "").strip()
        mood = str(ar_state.mood or self.session.mood or "").strip()
        objective = str(ar_state.story_goal or self.session.objective or "").strip()
        scene_lines = [
            f"Scene: {scene}",
            f"Location: {location}",
        ]
        if time_of_day:
            scene_lines.append(f"Time: {time_of_day}")
        if mood:
            scene_lines.append(f"Mood: {mood}")
        if objective:
            scene_lines.append(f"Objective: {objective}")
        scene_label = self._controls.get("chat_scene_state")
        if scene_label is not None and hasattr(scene_label, "setText"):
            scene_label.setText("\n".join(scene_lines))
        speaker_label = self._controls.get("chat_active_speaker")
        if speaker_label is not None and hasattr(speaker_label, "setText"):
            speaker_text = speaker.display_name if speaker is not None else "none"
            if active is not None and speaker is not None and active.id != speaker.id:
                speaker_text += f" (active persona: {active.display_name})"
            speaker_label.setText(f"Active speaker: {speaker_text}")

        active_ids = [normalize_persona_id(item) for item in list(ar_state.active_characters or []) if str(item or "").strip()]
        present = []
        if active_ids:
            for persona_id in active_ids:
                persona = self.persona_by_id(persona_id)
                present.append(self._persona_story_label(persona) if persona is not None else persona_id)
        else:
            for persona in self.personas:
                if persona.enabled:
                    present.append(self._persona_story_label(persona))
        self._set_list_items(
            self._controls.get("chat_present_characters"),
            present[:8],
            empty_text="No present characters marked.",
        )

        events = list(ar_state.recent_events or self.session.recent_events or [])
        self._set_list_items(
            self._controls.get("chat_recent_events"),
            [str(item) for item in events[-6:]],
            empty_text="No recent story events yet.",
        )

        choices = [str(item) for item in list(ar_state.pending_choices or []) if str(item or "").strip()]
        if not choices and self._mprc_chat_should_offer_choices():
            if objective:
                choices.append(f"Pursue objective: {objective}")
            choices.extend(["Ask the active speaker", "Investigate the scene", "Direct the pacing or tone"])
        self._set_list_items(
            self._controls.get("chat_next_actions"),
            choices[:6],
            empty_text="" if not self._mprc_chat_should_offer_choices() else "No suggested next actions yet.",
        )
        self._refresh_chat_play_story_engine_cards()

    def _refresh_narrator_selector(self):
        combo = self._controls.get("narrator_persona")
        if combo is None:
            return
        mode = self._narrator_selection_mode()
        selected = self._stored_narrator_persona_id() if mode == "explicit" else ""
        auto = self._auto_ar_narrator_persona()
        combo.blockSignals(True)
        combo.clear()
        auto_label = "Auto narrator"
        if auto is not None:
            auto_label = f"Auto narrator ({auto.display_name})"
        combo.addItem(auto_label, "")
        combo.setItemData(
            0,
            "Automatically choose the best narrator persona for AR. Use an explicit persona below to lock [NARRATOR] to one voice.",
            QtCore.Qt.ToolTipRole,
        )
        for persona in self._ordered_narrator_selector_personas():
            label = self._persona_voice_selector_label(persona)
            if self._persona_looks_like_narrator(persona) and not self._persona_is_master_narrator(persona):
                label += " [Narrator]"
            combo.addItem(label, persona.id)
            combo.setItemData(
                combo.count() - 1,
                f"Use {persona.display_name} for [NARRATOR] voice routing.",
                QtCore.Qt.ToolTipRole,
            )
        index = combo.findData(selected)
        combo.setCurrentIndex(max(0, index))
        combo.blockSignals(False)

    def _voice_follows_active(self) -> bool:
        return bool(self.settings.get("voice_follow_active_persona", True))

    def _stored_voice_persona_id(self) -> str:
        if self._voice_follows_active():
            active = self.active_persona()
            return active.id if active is not None else ""
        wanted = normalize_persona_id(self.settings.get("voice_edit_persona_id", ""))
        if wanted and any(persona.id == wanted for persona in self.personas):
            return wanted
        active = self.active_persona()
        return active.id if active is not None else ""

    def _selected_voice_persona(self) -> PersonaConfig | None:
        wanted = self._stored_voice_persona_id()
        return self.persona_by_id(wanted) if wanted else self.active_persona()

    def _refresh_voice_persona_selector(self):
        combo = self._controls.get("voice_persona")
        if combo is None:
            return
        follow = self._voice_follows_active()
        follow_widget = self._controls.get("voice_follow_active")
        if follow_widget is not None and hasattr(follow_widget, "setChecked"):
            follow_widget.blockSignals(True)
            follow_widget.setChecked(follow)
            follow_widget.blockSignals(False)
        combo.setEnabled(not follow)
        selected = self._stored_voice_persona_id()
        combo.blockSignals(True)
        combo.clear()
        narrator_id = self.selected_narrator_persona_id()
        for persona in self._ordered_voice_selector_personas():
            label = self._persona_voice_selector_label(persona)
            if persona.id == narrator_id:
                label += " [AR narrator]"
            combo.addItem(label, persona.id)
            combo.setItemData(
                combo.count() - 1,
                f"Edit voice settings for {persona.display_name}.",
                QtCore.Qt.ToolTipRole,
            )
        index = combo.findData(selected)
        combo.setCurrentIndex(max(0, index))
        combo.blockSignals(False)
        self._update_voice_target_label()

    def _update_voice_target_label(self):
        label = self._controls.get("voice_current_persona")
        if label is None or not hasattr(label, "setText"):
            return
        persona = self._selected_voice_persona()
        if persona is None:
            label.setText("No persona selected.")
            return
        mode = "following active persona" if self._voice_follows_active() else "manual voice selection"
        active_note = "active" if persona.id == self.session.active_persona_id else "not active"
        sample = str(getattr(persona.voice, "sample_path", "") or "").strip()
        sample_note = Path(sample).name if sample else "no voice sample"
        label.setText(f"{persona.display_name} ({persona.id}) - {mode}, {active_note}, {sample_note}")

    def _persona_story_label(self, persona: PersonaConfig) -> str:
        label = str(persona.display_name or persona.id).strip() or persona.id
        master_number = self._master_narrator_number(persona)
        if master_number:
            label += f" #{master_number} [Master Narrator]"
        linked = self._master_story_linked_persona_ids()
        created = self._master_story_created_persona_ids()
        auto_chat = self._chat_auto_created_persona_ids()
        if persona.id in auto_chat:
            label += " [Auto Chat]"
        elif persona.id == self.session.active_persona_id and persona.id in linked:
            label += " [Active Story]"
        elif persona.id in created:
            label += " [New Story]"
        elif persona.id in linked:
            label += " [Story]"
        return label

    def _persona_voice_selector_label(self, persona: PersonaConfig) -> str:
        label = str(persona.display_name or persona.id).strip() or persona.id
        master_number = self._master_narrator_number(persona)
        if master_number:
            return f"{label} #{master_number} ({persona.id} #{master_number}) [Master Narrator]"
        return f"{label} ({persona.id})"

    def _persona_story_tooltip(self, persona: PersonaConfig) -> str:
        pieces = [f"{persona.display_name} ({persona.id})"]
        master_number = self._master_narrator_number(persona)
        if master_number:
            pieces.append(f"Master narrator #{master_number}. Protected from deletion and prioritized for narrator voice selection.")
        if persona.id in self._chat_auto_created_persona_ids():
            pieces.append("Auto-created from a [CHARACTER: Name] tag in the active chat. Edit this persona to add voice, prompts, and pictures.")
        if persona.id in self._master_story_linked_persona_ids():
            title = str(self.settings.get("last_master_story_title") or self.settings.get("last_master_story_id") or "current Master Story").strip()
            pieces.append(f"Linked to {title}.")
        if persona.id in self._master_story_created_persona_ids():
            pieces.append("Created by the current Master Story apply/load action.")
        if persona.character_image_path:
            pieces.append(f"Character picture: {persona.character_image_path}")
        return "\n".join(pieces)

    def _master_story_linked_persona_ids(self) -> set[str]:
        raw = self.settings.get("master_story_linked_persona_ids")
        if not isinstance(raw, list):
            return set()
        return {normalize_persona_id(item) for item in raw if str(item or "").strip()}

    def _master_story_created_persona_ids(self) -> set[str]:
        raw = self.settings.get("master_story_created_persona_ids")
        if not isinstance(raw, list):
            return set()
        return {normalize_persona_id(item) for item in raw if str(item or "").strip()}

    def _populate_editor(self, persona: PersonaConfig):
        widgets = self._controls
        widgets["persona_id"].setText(persona.id)
        widgets["persona_enabled"].setChecked(bool(persona.enabled))
        widgets["master_narrator"].setChecked(self._persona_is_master_narrator(persona))
        widgets["display_name"].setText(persona.display_name)
        widgets["role"].setText(persona.role)
        widgets["description"].setPlainText(persona.description)
        widgets["character_image_path"].setText(persona.character_image_path)
        self._set_image_label(widgets.get("character_image"), persona.character_image_path, fallback_text="No picture")
        widgets["system_prompt"].setPlainText(persona.system_prompt)
        widgets["ar_profile_enabled"].setChecked(bool(persona.ar_profile_enabled))
        widgets["ar_description"].setPlainText(persona.ar_description)
        widgets["ar_system_prompt"].setPlainText(persona.ar_system_prompt)
        widgets["speaking_style"].setText(persona.speaking_style)
        widgets["allowed_tone"].setText(persona.allowed_tone)
        widgets["response_length"].setCurrentText(persona.response_length)
        widgets["temperature_hint"].setText(persona.temperature_hint)
        widgets["memory_scope"].setCurrentText(persona.memory_scope)
        widgets["behavior_mode"].setCurrentText(persona.behavior_mode)
        widgets["tags"].setText(", ".join(persona.tags))

    def _populate_voice(self, persona: PersonaConfig):
        voice = persona.voice
        self._controls["voice_enabled"].setChecked(voice.enabled)
        self._controls["voice_backend"].setCurrentText(voice.backend)
        self._controls["voice_sample"].setText(voice.sample_path)
        self._sync_voice_sample_picker(voice.sample_path)
        self._controls["voice_preset"].setText(voice.preset_name)
        self._controls["voice_language"].setCurrentText(voice.language if voice.language else "")
        self._update_voice_target_label()
        self._update_voice_warning()

    def _populate_visual(self, persona: PersonaConfig):
        visual = persona.visual
        self._controls["visual_enabled"].setChecked(visual.enabled)
        mode_combo = self._controls["visual_mode"]
        mode_index = mode_combo.findData(visual.mode)
        if mode_index < 0:
            mode_index = mode_combo.findText(visual.mode)
        mode_combo.setCurrentIndex(max(0, mode_index))
        self._controls["visual_provider"].setCurrentText(visual.provider)
        self._controls["visual_model"].setText(visual.model)
        self._controls["visual_size"].setCurrentText(visual.size)
        index = self._controls["visual_style"].findData(visual.style_preset)
        self._controls["visual_style"].setCurrentIndex(max(0, index))
        self._controls["visual_character"].setPlainText(visual.character_description)
        self._controls["visual_clothing"].setText(visual.clothing_props)
        self._controls["visual_environment"].setText(visual.environment_style)
        self._controls["visual_negative"].setText(visual.negative_prompt)
        self._controls["visual_continuity"].setChecked(visual.keep_continuity)
        self._controls["visual_scene"].setChecked(visual.include_scene_summary)
        self._controls["visual_speaker"].setChecked(visual.include_active_speaker)
        self._controls["visual_interval"].setValue(visual.auto_reply_interval)
        self._controls["visual_cooldown"].setValue(visual.cooldown_seconds)
        self._controls["visual_max_auto"].setValue(visual.max_auto_images_per_session)
        self._controls["visual_auto_show"].setChecked(visual.auto_show_dock)
        self._update_visual_mode_note()

    def _update_visual_mode_note(self):
        label = self._controls.get("visual_mode_note")
        combo = self._controls.get("visual_mode")
        if label is None or combo is None:
            return
        mode = str(combo.currentData() or combo.currentText() or "off").strip()
        label.setText(VISUAL_MODE_DESCRIPTIONS.get(mode, "Controls when this persona can request Visual Reply story images."))

    def _update_session_mode_note(self, mode: str | None = None) -> None:
        label = self._controls.get("session_mode_note")
        combo = self._controls.get("session_mode")
        if label is None:
            return
        selected = str(mode or "").strip()
        if not selected and combo is not None and hasattr(combo, "currentText"):
            selected = str(combo.currentText() or "").strip()
        label.setText(SESSION_MODE_DESCRIPTIONS.get(selected, "Choose how personas, narration, and story direction are framed for the current scene."))

    def _populate_session(self):
        c = self._controls
        c["session_mode"].setCurrentText(self.session.mode)
        self._update_session_mode_note(self.session.mode)
        c["scene_title"].setText(self.session.scene_title)
        c["location"].setText(self.session.location)
        c["time_of_day"].setText(self.session.time_of_day)
        c["mood"].setText(self.session.mood)
        c["objective"].setText(self.session.objective)
        c["scene_summary"].setPlainText(self.session.scene_summary)
        c["auto_select"].setChecked(self.session.auto_select_speaker)
        c["continuity"].setChecked(self.session.keep_scene_continuity)
        c["update_scene"].setChecked(self.session.update_scene_after_reply)
        roster = "\n".join(f"{persona.display_name} ({persona.id}) - {persona.behavior_mode}" for persona in self.personas if persona.enabled)
        c["roster"].setPlainText(roster)

    def _populate_ar(self):
        c = self._controls
        state = self.session.ar_state
        c["ar_enabled"].setChecked(self.session.mode == AR_MODE)
        c["ar_use_persona_profiles"].setChecked(bool(self.session.ar_use_persona_profiles))
        c["ar_pacing"].setCurrentText(self.session.ar_pacing)
        c["ar_interaction"].setCurrentText(self.session.ar_interaction_frequency)
        c["ar_tension"].setValue(int(state.tension_level or 0))
        c["ar_current_scene"].setText(state.current_scene)
        c["ar_location"].setText(state.location)
        c["ar_time_of_day"].setText(state.time_of_day)
        c["ar_mood"].setText(state.mood)
        c["ar_story_goal"].setText(state.story_goal)
        c["ar_active_characters"].setText(", ".join(state.active_characters))
        c["ar_player_intent"].setText(state.player_intent)
        c["ar_pending_choices"].setPlainText("\n".join(state.pending_choices))
        c["ar_recent_events"].setPlainText("\n".join(state.recent_events))

    def _populate_audio(self):
        c = self._controls
        if "audio_story_sounds" not in c:
            return
        c["audio_story_sounds"].setChecked(self.story_sounds_enabled())
        if "audiofx_volume" in c:
            volume = self._audiofx_volume_percent()
            c["audiofx_volume"].blockSignals(True)
            c["audiofx_volume"].setValue(volume)
            c["audiofx_volume"].blockSignals(False)
            if "audiofx_volume_value" in c:
                c["audiofx_volume_value"].setText(f"{volume}%")
            self._apply_audiofx_volume()
        if "audiofx_test_mode" in c:
            c["audiofx_test_mode"].setChecked(bool(self.settings.get("audiofx_test_mode", False)))
        c["audio_sound_description"].setPlainText(str(self.settings.get("audio_prompt_description") or ""))
        audio_type = str(self.settings.get("audio_prompt_type") or "Auto").strip()
        c["audio_type"].setCurrentText(audio_type if audio_type in AUDIO_TYPES else "Auto")
        c["audio_prompt_output"].setPlainText(str(self.settings.get("audio_prompt_output") or ""))
        self._populate_audio_saved_prompts()
        self._populate_audiofx_items()

    def _saved_audio_prompts(self) -> list[dict[str, str]]:
        saved = self.settings.get("saved_audio_prompts")
        if not isinstance(saved, list):
            return []
        prompts: list[dict[str, str]] = []
        for item in saved:
            if not isinstance(item, dict):
                continue
            prompt = str(item.get("prompt") or "").strip()
            if not prompt:
                continue
            prompts.append({
                "created_at": str(item.get("created_at") or "").strip(),
                "type": str(item.get("type") or "Auto").strip() or "Auto",
                "description": str(item.get("description") or "").strip(),
                "prompt": prompt,
            })
        return prompts

    def _populate_audio_saved_prompts(self):
        saved_list = self._controls.get("audio_saved_prompts")
        saved_count = self._controls.get("audio_saved_count")
        if saved_list is None:
            return
        prompts = self._saved_audio_prompts()
        saved_list.blockSignals(True)
        saved_list.clear()
        from PySide6 import QtWidgets

        for index, item in enumerate(prompts):
            label = self._audio_saved_prompt_label(item, index)
            list_item = QtWidgets.QListWidgetItem(label)
            list_item.setData(32, index)
            list_item.setToolTip(str(item.get("prompt") or ""))
            saved_list.addItem(list_item)
        saved_list.blockSignals(False)
        if saved_count is not None:
            saved_count.setText(f"{len(prompts)} saved prompt{'s' if len(prompts) != 1 else ''}")
        self._update_audio_saved_buttons()

    def _audio_saved_prompt_label(self, item: dict[str, str], index: int) -> str:
        audio_type = str(item.get("type") or "Auto").strip() or "Auto"
        description = str(item.get("description") or "").strip()
        prompt = str(item.get("prompt") or "").strip()
        title = description or prompt
        title = title.replace("\r", " ").replace("\n", " ")
        while "  " in title:
            title = title.replace("  ", " ")
        if len(title) > 86:
            title = title[:83].rstrip() + "..."
        return f"{index + 1}. [{audio_type}] {title}"

    def _selected_audio_prompt_index(self) -> int:
        saved_list = self._controls.get("audio_saved_prompts")
        if saved_list is None:
            return -1
        item = saved_list.currentItem()
        if item is None:
            return -1
        try:
            return int(item.data(32))
        except Exception:
            return -1

    def _update_audio_saved_buttons(self):
        selected = self._selected_audio_prompt_index() >= 0
        for key in ("audio_load_saved", "audio_delete_saved"):
            button = self._controls.get(key)
            if button is not None:
                button.setEnabled(selected)

    def _audiofx_items(self) -> list[dict[str, str]]:
        raw = self.settings.get("audio_fx_items")
        if not isinstance(raw, list):
            return []
        items: list[dict[str, str]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            description = str(item.get("description") or "").strip()
            prompt = str(item.get("prompt") or "").strip()
            file_path = str(item.get("file_path") or "").strip()
            if not description and not prompt and not file_path:
                continue
            items.append({
                "id": str(item.get("id") or "").strip() or self._new_audiofx_id(items),
                "type": str(item.get("type") or "Auto").strip() or "Auto",
                "description": description,
                "prompt": prompt,
                "file_path": file_path,
                "created_at": str(item.get("created_at") or "").strip(),
                "updated_at": str(item.get("updated_at") or "").strip(),
            })
        return items

    def _available_audio_files(self) -> list[dict[str, Any]]:
        raw = self.settings.get("available_audio_files")
        if not isinstance(raw, list):
            return []
        files: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            file_path = str(item.get("file_path") or "").strip()
            if not file_path:
                continue
            path_key = self._audio_file_key(file_path)
            if path_key in seen_paths:
                continue
            seen_paths.add(path_key)
            files.append({
                "id": str(item.get("id") or "").strip() or self._audio_cue_id_from_path(file_path),
                "type": str(item.get("type") or "Audio").strip() or "Audio",
                "description": str(item.get("description") or "").strip(),
                "prompt": str(item.get("prompt") or "").strip(),
                "file_path": file_path,
                "file_name": str(item.get("file_name") or "").strip() or Path(file_path).name,
                "source": str(item.get("source") or "manual").strip() or "manual",
                "source_audiofx_id": str(item.get("source_audiofx_id") or "").strip(),
                "ready": bool(file_path and Path(file_path).exists()),
                "created_at": str(item.get("created_at") or "").strip(),
                "updated_at": str(item.get("updated_at") or "").strip(),
            })
        return files

    def _audiofx_available_entry(self, item: dict[str, str]) -> dict[str, Any] | None:
        file_path = str(item.get("file_path") or "").strip()
        if not file_path:
            return None
        path = Path(file_path)
        if not path.exists():
            return None
        cue_id = str(item.get("id") or "").strip() or self._audio_cue_id_from_path(file_path)
        return {
            "id": cue_id,
            "type": str(item.get("type") or "Audio").strip() or "Audio",
            "description": str(item.get("description") or "").strip(),
            "prompt": str(item.get("prompt") or "").strip(),
            "file_path": str(path.resolve()),
            "file_name": path.name,
            "source": "audiofx",
            "source_audiofx_id": cue_id,
            "ready": True,
            "created_at": str(item.get("created_at") or "").strip(),
            "updated_at": str(item.get("updated_at") or "").strip(),
        }

    def _sync_available_audio_database(self, items: list[dict[str, str]] | None = None, *, persist: bool = True) -> list[dict[str, Any]]:
        items = list(items if items is not None else self._audiofx_items())
        existing = self._available_audio_files()
        audiofx_ids = {str(item.get("id") or "").strip() for item in items}
        merged: list[dict[str, Any]] = []
        by_path: dict[str, dict[str, Any]] = {}

        for entry in existing:
            if entry.get("source") == "audiofx" and str(entry.get("source_audiofx_id") or "") not in audiofx_ids:
                continue
            key = self._audio_file_key(entry.get("file_path", ""))
            if key:
                by_path[key] = dict(entry)

        for item in items:
            entry = self._audiofx_available_entry(item)
            if entry is None:
                continue
            by_path[self._audio_file_key(entry["file_path"])] = entry

        for key in sorted(by_path):
            merged.append(by_path[key])
        if persist:
            self.settings["available_audio_files"] = merged
        return merged

    def _audio_file_key(self, file_path: str) -> str:
        raw = str(file_path or "").strip()
        if not raw:
            return ""
        try:
            return str(Path(raw).resolve()).lower()
        except Exception:
            return raw.lower()

    def strip_story_audio_for_tts(self, text: str, *, streaming: bool = False, collect_cues: bool = False):
        """Remove non-spoken story audio cues and optionally defer playback."""
        collected_cues: list[str] = []

        def handle_cues(cue_text: str, *, warn_unmatched: bool = False) -> bool:
            if not collect_cues:
                return self._trigger_story_audio_cues(cue_text, warn_unmatched=warn_unmatched)
            cue_ids = self._story_audio_cue_ids(cue_text)
            if not cue_ids:
                if warn_unmatched:
                    logger = getattr(self.context, "logger", None)
                    if logger is not None:
                        logger.warning("[AR_MODE] Ignored unmatched ambience tag: %s", str(cue_text or "").strip()[:160])
                return False
            seen = {str(cue_id).lower() for cue_id in collected_cues}
            for cue_id in cue_ids:
                key = str(cue_id).lower()
                if key not in seen:
                    collected_cues.append(cue_id)
                    seen.add(key)
            return True

        original = str(text or "")
        if not original:
            return ("", False, collected_cues) if collect_cues else ("", False)
        if streaming:
            original = self._story_audio_pending_text + original
            self._story_audio_pending_text = ""
            original, pending = self._split_pending_story_audio_tag(original)
            if pending:
                self._story_audio_pending_text = pending
                if not original.strip():
                    return ("", True, collected_cues) if collect_cues else ("", True)
        else:
            self._story_audio_pending_text = ""
        lines = original.splitlines()
        cleaned: list[str] = []
        changed = False
        in_audio_block = bool(self._story_audio_block_active) if streaming else False

        for raw_line in lines:
            line = str(raw_line or "")
            audio_command = re.match(r"^\s*\[(AMBIENCE|AMBIENT|MUSIC|FX|SFX|STINGER|AUDIO|SOUND)(?:\s*:\s*([^\]]+))?\]\s*(.*)$", line, re.IGNORECASE)
            section = re.match(r"^\s*\[(NARRATOR|CHOICES)\]\s*(.*)$", line, re.IGNORECASE)
            character = re.match(r"^\s*\[CHARACTER\s*:\s*([^\]]+)\]\s*(.*)$", line, re.IGNORECASE)
            if audio_command:
                changed = True
                cue_name = str(audio_command.group(2) or "").strip()
                body = str(audio_command.group(3) or "").strip()
                handle_cues(" ".join(part for part in (cue_name, body) if part), warn_unmatched=bool(cue_name))
                in_audio_block = not bool(cue_name)
                continue
            if section:
                label = section.group(1).strip().upper()
                in_audio_block = False
                cleaned.append(line)
                continue
            if character:
                in_audio_block = False
                cleaned.append(line)
                continue
            if in_audio_block:
                cue_ids = self._story_audio_cue_ids(line)
                if cue_ids or not line.strip():
                    changed = True
                    handle_cues(line)
                    continue
                if line.lstrip().startswith(("*", "-", "•")) and re.search(r"\b(?:file|ready|ambience|ambient|music|stinger|fx|sfx|audiofx|audio|sound)\b", line, re.IGNORECASE):
                    changed = True
                    handle_cues(line)
                    continue
                in_audio_block = False
            stripped = self._strip_inline_story_audio_cues(line, collected_cues=collected_cues if collect_cues else None)
            if stripped != line:
                changed = True
                if stripped.strip():
                    cleaned.append(stripped)
                continue
            cleaned.append(line)

        if streaming:
            self._story_audio_block_active = in_audio_block
        else:
            self._story_audio_block_active = False
        cleaned_text = "\n".join(cleaned).strip()
        return (cleaned_text, changed, collected_cues) if collect_cues else (cleaned_text, changed)

    @staticmethod
    def _split_pending_story_audio_tag(text: str) -> tuple[str, str]:
        value = str(text or "")
        start = value.rfind("[")
        if start < 0:
            return value, ""
        tail = value[start:]
        if "]" in tail:
            return value, ""
        if re.match(r"^\[(?:A|AM|AMB|AMBI|AMBIEN|AMBIENC|AMBIENCE|AMBIENT|M|MU|MUS|MUSI|MUSIC|F|FX|S|SF|SFX|ST|STI|STIN|STING|STINGE|STINGER|SO|SOU|SOUN|SOUND|AU|AUD|AUDI|AUDIO)(?:\s*:\s*)?[^\]]*$", tail, re.IGNORECASE):
            return value[:start], tail
        return value, ""

    def play_story_audio_from_reply(self, text: str) -> int:
        """Scan a complete assistant reply for audio tags missed by streaming chunks."""
        played = 0
        for cue_text in re.findall(r"\[(?:AMBIENCE|AMBIENT|MUSIC|FX|SFX|STINGER|AUDIO|SOUND)\s*:\s*([^\]]+)\]", str(text or ""), re.IGNORECASE):
            if self._trigger_story_audio_cues(cue_text, warn_unmatched=True):
                played += 1
        return played

    def play_story_audio_cue_ids(self, cue_ids: list[str] | tuple[str, ...] | set[str]) -> int:
        played = 0
        for cue_id in list(cue_ids or []):
            if self._play_story_audio_cue(str(cue_id or "")):
                played += 1
        return played

    def _strip_inline_story_audio_cues(self, line: str, *, collected_cues: list[str] | None = None) -> str:
        text = str(line or "")
        cue_ids = self._story_audio_cue_ids(text)
        if not cue_ids:
            return text
        if collected_cues is None:
            for cue_id in cue_ids:
                self._play_story_audio_cue(cue_id)
        else:
            seen = {str(cue_id).lower() for cue_id in collected_cues}
            for cue_id in cue_ids:
                key = str(cue_id).lower()
                if key not in seen:
                    collected_cues.append(cue_id)
                    seen.add(key)
        stripped = text
        for cue_id in cue_ids:
            stripped = re.sub(rf"[\*\s\-\u2022]*{re.escape(cue_id)}\s*:?.*$", "", stripped, flags=re.IGNORECASE)
        return stripped.strip(" \t*-")

    def _story_audio_cue_ids(self, text: str) -> list[str]:
        entries = self._story_audio_entries()
        known: dict[str, str] = {}
        for entry in entries:
            for key in ("id", "source_audiofx_id"):
                value = str(entry.get(key) or "").strip()
                if value:
                    known[value.lower()] = value
        found: list[str] = []
        seen: set[str] = set()
        for match in re.finditer(r"\b(?:audiofx|audio)[_-][A-Za-z0-9_:-]{3,}\b", str(text or ""), re.IGNORECASE):
            raw = match.group(0).strip().rstrip(".,;:*)]")
            key = raw.lower()
            cue_id = known.get(key)
            if cue_id and cue_id.lower() not in seen:
                found.append(cue_id)
                seen.add(cue_id.lower())
        if found:
            return found
        cue_id = self._story_audio_cue_id_for_query(text, entries)
        if cue_id:
            found.append(cue_id)
        return found

    def _story_audio_cue_id_for_query(self, query: str, entries: list[dict[str, Any]]) -> str:
        wanted = self._audio_match_key(query)
        wanted_tokens = self._audio_match_tokens(query)
        if not wanted and not wanted_tokens:
            return ""
        scored: list[tuple[float, str]] = []
        for entry in entries:
            if not bool(entry.get("ready", True)):
                continue
            cue_id = str(entry.get("id") or entry.get("source_audiofx_id") or "").strip()
            if not cue_id:
                continue
            labels = [
                entry.get("id"),
                entry.get("source_audiofx_id"),
                entry.get("description"),
                entry.get("file_name"),
                Path(str(entry.get("file_name") or "")).stem,
                entry.get("prompt"),
                entry.get("type"),
            ]
            best = 0.0
            for label in labels:
                label_text = str(label or "").strip()
                label_key = self._audio_match_key(label_text)
                label_tokens = self._audio_match_tokens(label_text)
                if not label_key and not label_tokens:
                    continue
                if wanted and label_key and wanted == label_key:
                    best = max(best, 100.0)
                elif wanted and label_key and (wanted in label_key or label_key in wanted):
                    best = max(best, 88.0)
                elif wanted_tokens and label_tokens:
                    overlap = len(wanted_tokens & label_tokens)
                    if overlap:
                        if wanted_tokens <= label_tokens or label_tokens <= wanted_tokens:
                            best = max(best, 82.0 + min(8.0, overlap))
                        else:
                            best = max(best, 70.0 * (overlap / max(1, len(wanted_tokens | label_tokens))))
            if best >= 60.0:
                scored.append((best, cue_id))
        if not scored:
            return ""
        scored.sort(key=lambda item: item[0], reverse=True)
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            return ""
        return scored[0][1]

    @staticmethod
    def _audio_match_key(value: Any) -> str:
        text = str(value or "").lower()
        text = re.sub(r"^\s*\[?ambience\s*:?", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(?:file|ready|missing|prompt|description|status)\b", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\.[a-z0-9]{2,5}\b", " ", text)
        return re.sub(r"[^a-z0-9]+", " ", text).strip()

    @classmethod
    def _audio_match_tokens(cls, value: Any) -> set[str]:
        stop = {"ambience", "ambient", "audio", "sound", "file", "ready", "missing", "prompt", "description", "status"}
        return {
            token
            for token in cls._audio_match_key(value).split()
            if len(token) >= 3 and token not in stop
        }

    def _trigger_story_audio_cues(self, text: str, *, warn_unmatched: bool = False) -> bool:
        cue_ids = self._story_audio_cue_ids(text)
        if not cue_ids:
            if warn_unmatched:
                logger = getattr(self.context, "logger", None)
                if logger is not None:
                    logger.warning("[AR_MODE] Ignored unmatched ambience tag: %s", str(text or "").strip()[:160])
                self._record_story_event(
                    f"sound skipped: no matching AudioFX for '{str(text or '').strip()[:120]}'",
                    severity="warning",
                    kind="audiofx",
                    persist=True,
                )
            return False
        for cue_id in cue_ids:
            self._play_story_audio_cue(cue_id)
        return True

    def _play_story_audio_cue(self, cue_id: str) -> bool:
        logger = getattr(self.context, "logger", None)
        if not self.story_sounds_enabled():
            if logger is not None:
                logger.info("[AR_MODE] Story Sounds disabled; skipped AudioFX cue %s", cue_id)
            self._record_story_event(f"sound skipped: Story Sounds disabled for {cue_id}", severity="info", kind="audiofx", persist=True)
            return False
        entry = self._story_audio_entry(cue_id)
        if entry is None:
            if logger is not None:
                logger.warning("[AR_MODE] AudioFX cue was requested but not ready: %s", cue_id)
            self._record_story_event(f"sound skipped: no matching ready AudioFX for {cue_id}", severity="warning", kind="audiofx", persist=True)
            return False
        now = time.monotonic()
        cue_key = str(entry.get("id") or cue_id).lower()
        with self._state_lock:
            if self._shutting_down:
                return False
            if now - float(self._last_story_audio_cues.get(cue_key, 0.0) or 0.0) < 1.5:
                self._record_story_event(f"sound skipped: cooldown for {cue_key}", severity="info", kind="audiofx", persist=False)
                return True
            self._last_story_audio_cues[cue_key] = now
        try:
            bridge = getattr(self, "_story_audio_bridge", None)
            if bridge is None:
                return False
            bridge.play_requested.emit(dict(entry))
            if logger is not None:
                logger.info("[AR_MODE] Queued story AudioFX cue %s: %s", entry.get("id") or cue_id, entry.get("file_path") or "")
            return True
        except RuntimeError as exc:
            self._record_story_event(f"sound skipped: playback bridge unavailable for {cue_id}: {exc}", severity="warning", kind="audiofx", persist=True)
            return False

    def _story_audio_entry(self, cue_id: str) -> dict[str, Any] | None:
        wanted = str(cue_id or "").strip().lower()
        if not wanted:
            return None
        for entry in self._story_audio_entries():
            ids = {
                str(entry.get("id") or "").strip().lower(),
                str(entry.get("source_audiofx_id") or "").strip().lower(),
            }
            file_path = str(entry.get("file_path") or "").strip()
            if wanted in ids and file_path and Path(file_path).exists():
                return dict(entry)
        return None

    def _story_audio_entries(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in self.available_story_audio_files():
            if not isinstance(entry, dict):
                continue
            key = self._audio_file_key(entry.get("file_path", "")) or str(entry.get("id") or "").lower()
            if key and key not in seen:
                entries.append(dict(entry))
                seen.add(key)
        for item in self._audiofx_items():
            entry = self._audiofx_available_entry(item)
            if entry is None:
                continue
            key = self._audio_file_key(entry.get("file_path", "")) or str(entry.get("id") or "").lower()
            if key and key not in seen:
                entries.append(entry)
                seen.add(key)
        return entries

    def _audio_cue_id_from_path(self, file_path: str) -> str:
        name = Path(str(file_path or "audio")).stem.lower()
        cue = []
        previous = False
        for char in name:
            if char.isalnum():
                cue.append(char)
                previous = False
            elif not previous:
                cue.append("_")
                previous = True
        text = "".join(cue).strip("_") or "audio"
        return f"audio_{text[:48]}"

    def _save_audiofx_items(self, items: list[dict[str, str]]) -> None:
        self.settings["audio_fx_items"] = [dict(item) for item in list(items or [])]
        self._sync_available_audio_database(items)
        self.storage.save_settings(self.settings)

    def _populate_audiofx_items(self):
        audiofx_list = self._controls.get("audiofx_list")
        if audiofx_list is None:
            return
        items = self._audiofx_items()
        audiofx_list.blockSignals(True)
        audiofx_list.clear()
        from PySide6 import QtWidgets

        ready_count = 0
        for index, item in enumerate(items):
            ready = self._audiofx_file_ready(item)
            if ready:
                ready_count += 1
            list_item = QtWidgets.QListWidgetItem(self._audiofx_label(item, index, ready))
            list_item.setData(32, index)
            list_item.setToolTip(self._audiofx_tooltip(item, ready))
            if ready:
                list_item.setForeground(QtGui.QColor("#22c55e"))
            else:
                list_item.setForeground(QtGui.QColor("#f4f7fb"))
            audiofx_list.addItem(list_item)
        audiofx_list.blockSignals(False)
        count = self._controls.get("audiofx_count")
        if count is not None:
            available_count = len(self.available_story_audio_files())
            count.setText(
                f"{len(items)} AudioFX item{'s' if len(items) != 1 else ''} - "
                f"{ready_count} ready - {available_count} story audio cue{'s' if available_count != 1 else ''}"
            )
        self._update_audiofx_buttons()

    def _audiofx_label(self, item: dict[str, str], index: int, ready: bool) -> str:
        audio_type = str(item.get("type") or "Auto").strip() or "Auto"
        description = str(item.get("description") or "").strip()
        prompt = str(item.get("prompt") or "").strip()
        title = (description or prompt or "Untitled AudioFX").replace("\r", " ").replace("\n", " ")
        while "  " in title:
            title = title.replace("  ", " ")
        if len(title) > 80:
            title = title[:77].rstrip() + "..."
        status = "ready" if ready else "needs file"
        return f"AudioFX {index + 1} - [{audio_type}] {title} ({status})"

    def _audiofx_tooltip(self, item: dict[str, str], ready: bool) -> str:
        status = "Ready" if ready else "Needs a valid local sound file"
        parts = [
            f"Status: {status}",
            f"Description: {str(item.get('description') or '').strip()}",
            f"File: {str(item.get('file_path') or '').strip()}",
            f"Prompt: {str(item.get('prompt') or '').strip()}",
        ]
        return "\n".join(part for part in parts if not part.endswith(": "))

    def _audiofx_file_ready(self, item: dict[str, str]) -> bool:
        file_path = str(item.get("file_path") or "").strip()
        return bool(file_path and Path(file_path).exists())

    def _audiofx_volume_percent(self) -> int:
        try:
            value = int(self.settings.get("audiofx_volume", 60))
        except Exception:
            value = 60
        return max(0, min(100, value))

    def _apply_audiofx_volume(self) -> None:
        if self._audiofx_output is None:
            return
        try:
            self._audiofx_output.setVolume(self._audiofx_volume_percent() / 100.0)
        except Exception:
            pass

    def _selected_audiofx_index(self) -> int:
        audiofx_list = self._controls.get("audiofx_list")
        if audiofx_list is None:
            return -1
        item = audiofx_list.currentItem()
        if item is None:
            return -1
        try:
            return int(item.data(32))
        except Exception:
            return -1

    def _select_audiofx_index(self, index: int):
        audiofx_list = self._controls.get("audiofx_list")
        if audiofx_list is not None and index >= 0:
            audiofx_list.setCurrentRow(index)

    def _update_audiofx_buttons(self):
        index = self._selected_audiofx_index()
        items = self._audiofx_items()
        selected = 0 <= index < len(items)
        ready = bool(selected and self._audiofx_file_ready(items[index]))
        for key in ("audiofx_load", "audiofx_delete"):
            button = self._controls.get(key)
            if button is not None:
                button.setEnabled(selected)
        create_button = self._controls.get("audiofx_create")
        if create_button is not None:
            create_button.setEnabled(True)
        add_file_button = self._controls.get("audiofx_add_file")
        if add_file_button is not None:
            add_file_button.setEnabled(True)
        play_button = self._controls.get("audiofx_play")
        if play_button is not None:
            play_button.setEnabled(ready)
        status = self._controls.get("audiofx_status")
        if status is not None:
            if selected:
                file_path = str(items[index].get("file_path") or "").strip()
                status_text = "Ready and indexed: " + file_path if ready else "Needs sound file: " + (file_path or "none attached")
                status.setText(status_text)
                status.setStyleSheet("color: #22c55e;" if ready else "color: #facc15;")
            else:
                status.setText("Create an AudioFX item from the current sound description, then attach a local audio file.")
                status.setStyleSheet("")

    def _new_audiofx_id(self, existing_items: list[dict[str, str]] | None = None) -> str:
        stamp = QtCore.QDateTime.currentDateTimeUtc().toString("yyyyMMddHHmmsszzz")
        base = f"audiofx_{stamp}"
        known = {str(item.get("id") or "") for item in list(existing_items or [])}
        if base not in known:
            return base
        suffix = 2
        while f"{base}_{suffix}" in known:
            suffix += 1
        return f"{base}_{suffix}"

    def _audiofx_pack_id(self, pack_id: str, item_id: str, existing_items: list[dict[str, str]]) -> str:
        raw_pack = re.sub(r"[^a-z0-9_]+", "_", str(pack_id or "audio_pack").lower()).strip("_") or "audio_pack"
        raw_item = re.sub(r"[^a-z0-9_]+", "_", str(item_id or "item").lower()).strip("_") or "item"
        return f"{raw_pack}_{raw_item}"[:96].strip("_") or "audio_pack_item"

    def _import_audio_pack_resources(self):
        start = r"Q:\Sounds" if Path(r"Q:\Sounds").exists() else str(Path.home())
        path = self._open_directory("Import Audio Pack Resources", start)
        if not path:
            return
        try:
            added, updated, skipped = self._import_audio_pack_from_path(path)
        except Exception as exc:
            self._warn("Import Audio Pack Resources", f"Audio pack import failed:\n\n{exc}")
            return
        status = self._controls.get("audiofx_status")
        if status is not None:
            status.setStyleSheet("color: #22c55e;" if added or updated else "color: #facc15;")
            status.setText(f"Imported audio pack: {added} added, {updated} updated, {skipped} skipped.")
        logger = getattr(self.context, "logger", None)
        if logger is not None:
            logger.info("[AR_MODE] Imported AudioFX pack from %s: added=%s updated=%s skipped=%s", path, added, updated, skipped)

    def _import_audio_pack_from_path(self, pack_path: str | Path) -> tuple[int, int, int]:
        manifest_path = self._find_audio_pack_manifest(Path(pack_path))
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = payload.get("entries")
        if not isinstance(entries, list):
            entries = payload.get("items")
        if not isinstance(entries, list):
            raise ValueError("The selected folder does not contain an MPRC audio pack manifest with entries.")
        pack_id = str(payload.get("pack_id") or payload.get("id") or manifest_path.parent.name or "audio_pack").strip()
        items = self._audiofx_items()
        by_id = {str(item.get("id") or "").strip().lower(): index for index, item in enumerate(items)}
        by_path = {self._audio_file_key(item.get("file_path", "")): index for index, item in enumerate(items) if item.get("file_path")}
        now = QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate)
        added = 0
        updated = 0
        skipped = 0

        for entry in entries:
            if not isinstance(entry, dict):
                skipped += 1
                continue
            file_path = self._resolve_audio_pack_file(manifest_path.parent, entry)
            if not file_path:
                skipped += 1
                continue
            item_id = self._audiofx_pack_id(pack_id, str(entry.get("id") or Path(file_path).stem), items)
            audio_type = str(entry.get("type") or "Auto").strip()
            description = str(entry.get("description") or entry.get("name") or Path(file_path).stem).strip()
            prompt = str(entry.get("prompt") or description).strip()
            incoming = {
                "id": item_id,
                "type": audio_type if audio_type in AUDIO_TYPES else "Auto",
                "description": description,
                "prompt": prompt,
                "file_path": str(Path(file_path).resolve()),
                "created_at": now,
                "updated_at": now,
            }
            path_key = self._audio_file_key(incoming["file_path"])
            index = by_path.get(path_key)
            if index is None:
                index = by_id.get(item_id.lower())
            if index is None:
                items.append(incoming)
                by_id[incoming["id"].lower()] = len(items) - 1
                by_path[path_key] = len(items) - 1
                added += 1
            else:
                created_at = str(items[index].get("created_at") or "").strip()
                incoming["created_at"] = created_at or now
                items[index] = incoming
                by_id[incoming["id"].lower()] = index
                by_path[path_key] = index
                updated += 1

        if not added and not updated:
            return added, updated, skipped
        self.settings["story_sounds_enabled"] = True
        story_toggle = self._controls.get("audio_story_sounds")
        if story_toggle is not None:
            story_toggle.blockSignals(True)
            story_toggle.setChecked(True)
            story_toggle.blockSignals(False)
        self._save_audiofx_items(items)
        self._populate_audiofx_items()
        if added:
            self._select_audiofx_index(len(items) - added)
        return added, updated, skipped

    def _find_audio_pack_manifest(self, pack_path: Path) -> Path:
        path = pack_path.expanduser()
        if path.is_file():
            return path
        if not path.exists() or not path.is_dir():
            raise FileNotFoundError(f"Audio pack folder was not found: {path}")
        candidates = [
            path / "mprc_audio_pack.json",
            path / "audio_pack.json",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        for candidate in sorted(path.glob("*.json")):
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(data, dict) and isinstance(data.get("entries") or data.get("items"), list):
                return candidate
        raise FileNotFoundError("No audio pack manifest was found. Expected mprc_audio_pack.json or audio_pack.json.")

    def _resolve_audio_pack_file(self, pack_root: Path, entry: dict[str, Any]) -> str:
        raw_candidates = [
            entry.get("relative_path"),
            entry.get("file_path"),
            entry.get("file_name"),
        ]
        for raw in raw_candidates:
            value = str(raw or "").strip()
            if not value:
                continue
            candidate = Path(value)
            if not candidate.is_absolute():
                candidate = pack_root / candidate
            if candidate.exists() and candidate.is_file():
                return str(candidate)
        file_name = str(entry.get("file_name") or "").strip()
        if file_name:
            matches = list(pack_root.rglob(file_name))
            for match in matches:
                if match.is_file():
                    return str(match)
        return ""

    def _selected_persona(self) -> PersonaConfig | None:
        return self.active_persona()

    def _schedule_delayed_commit(self, key: str, callback, *, delay_ms: int = 450) -> None:
        if self._syncing:
            return
        timer_key = str(key or "").strip()
        if not timer_key:
            return
        timer = self._commit_timers.get(timer_key)
        if timer is None:
            timer = QtCore.QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(callback)
            self._commit_timers[timer_key] = timer
        timer.start(max(0, int(delay_ms)))

    def _commit_delayed_now(self, key: str, callback) -> None:
        timer = self._commit_timers.get(str(key or "").strip())
        if timer is not None and timer.isActive():
            timer.stop()
        callback()

    def _schedule_editor_commit(self, *, include_identity: bool = False, delay_ms: int = 450) -> None:
        if self._syncing:
            return
        self._editor_commit_include_identity = bool(self._editor_commit_include_identity or include_identity)
        timer = getattr(self, "_editor_commit_timer", None)
        if timer is not None:
            timer.start(max(0, int(delay_ms)))
        else:
            self._commit_editor(include_identity=include_identity)

    def _commit_scheduled_editor(self) -> None:
        include_identity = bool(getattr(self, "_editor_commit_include_identity", False))
        self._editor_commit_include_identity = False
        self._commit_editor(include_identity=include_identity)

    def _commit_editor_now(self, *, include_identity: bool = True) -> None:
        timer = getattr(self, "_editor_commit_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()
        self._editor_commit_include_identity = False
        self._commit_editor(include_identity=include_identity)

    def _schedule_voice_commit(self) -> None:
        self._schedule_delayed_commit("voice", self._commit_voice)

    def _commit_voice_now(self) -> None:
        self._commit_delayed_now("voice", self._commit_voice)

    def _schedule_visual_commit(self) -> None:
        self._schedule_delayed_commit("visual", self._commit_visual)

    def _commit_visual_now(self) -> None:
        self._commit_delayed_now("visual", self._commit_visual)

    def _schedule_session_commit(self) -> None:
        self._schedule_delayed_commit("session", lambda: self._commit_session(refresh_ui=False))

    def _commit_session_now(self, *, refresh_ui: bool = True) -> None:
        self._commit_delayed_now("session", lambda: self._commit_session(refresh_ui=refresh_ui))

    def _schedule_ar_state_commit(self) -> None:
        self._schedule_delayed_commit("ar_state", self._commit_ar_state)

    def _commit_ar_state_now(self) -> None:
        self._commit_delayed_now("ar_state", self._commit_ar_state)

    def _schedule_audio_settings_commit(self) -> None:
        self._schedule_delayed_commit("audio_settings", self._commit_audio_settings)

    def _commit_audio_settings_now(self) -> None:
        self._commit_delayed_now("audio_settings", self._commit_audio_settings)

    def _commit_editor(self, *, include_identity: bool = True):
        if self._syncing:
            return
        persona = self._selected_persona()
        if persona is None:
            return
        old_id = persona.id
        old_display_name = persona.display_name
        old_image_path = persona.character_image_path
        old_master_narrator = self._persona_is_master_narrator(persona)
        if include_identity:
            requested_id = unique_persona_id(self._controls["persona_id"].text(), {p.id for p in self.personas if p is not persona})
            persona.id = requested_id
        persona.enabled = self._controls["persona_enabled"].isChecked()
        persona.master_narrator = bool(self._controls["master_narrator"].isChecked())
        if include_identity:
            persona.display_name = self._controls["display_name"].text().strip() or persona.id.replace("_", " ").title()
        persona.role = self._controls["role"].text().strip()
        persona.description = self._controls["description"].toPlainText().strip()
        persona.character_image_path = self._controls["character_image_path"].text().strip()
        persona.system_prompt = self._controls["system_prompt"].toPlainText().strip()
        persona.ar_profile_enabled = self._controls["ar_profile_enabled"].isChecked()
        persona.ar_description = self._controls["ar_description"].toPlainText().strip()
        persona.ar_system_prompt = self._controls["ar_system_prompt"].toPlainText().strip()
        persona.speaking_style = self._controls["speaking_style"].text().strip()
        persona.allowed_tone = self._controls["allowed_tone"].text().strip()
        persona.response_length = self._controls["response_length"].currentText().strip() or "balanced"
        persona.temperature_hint = self._controls["temperature_hint"].text().strip()
        persona.memory_scope = self._controls["memory_scope"].currentText().strip()
        persona.behavior_mode = self._controls["behavior_mode"].currentText().strip()
        persona.tags = [item.strip().lower() for item in self._controls["tags"].text().split(",") if item.strip()]
        if self.session.active_persona_id == old_id:
            self.session.active_persona_id = persona.id
        if self.session.current_speaker_id == old_id:
            self.session.current_speaker_id = persona.id
        settings_changed = False
        if normalize_persona_id(self.settings.get("narrator_persona_id", "")) == old_id:
            self.settings["narrator_persona_id"] = persona.id
            self.settings["narrator_persona_mode"] = "explicit"
            settings_changed = True
        if normalize_persona_id(self.settings.get("voice_edit_persona_id", "")) == old_id:
            self.settings["voice_edit_persona_id"] = persona.id
            settings_changed = True
        if settings_changed:
            self.storage.save_settings(self.settings)
        self.save_state()
        self._notify_changed()
        identity_changed = old_id != persona.id or old_display_name != persona.display_name
        if identity_changed or old_master_narrator != self._persona_is_master_narrator(persona):
            self._refresh_persona_selectors()
            if "session_mode" in self._controls:
                self._populate_session()
            self._refresh_narrator_selector()
            self._refresh_voice_persona_selector()
        if old_image_path != persona.character_image_path:
            self._set_image_label(self._controls.get("character_image"), persona.character_image_path, fallback_text="No picture")
        self._refresh_character_preview()
        self._refresh_debug()

    def _commit_voice(self):
        if self._syncing:
            return
        persona = self._selected_voice_persona()
        if persona is None:
            return
        voice = persona.voice
        voice.enabled = self._controls["voice_enabled"].isChecked()
        voice.backend = self._controls["voice_backend"].currentText().strip() or "inherit"
        voice.sample_path = self._controls["voice_sample"].text().strip()
        voice.preset_name = self._controls["voice_preset"].text().strip()
        voice.language = self._controls["voice_language"].currentText().strip().lower()
        self.save_state()
        self._sync_voice_sample_picker(voice.sample_path)
        self._update_voice_target_label()
        self._update_voice_warning()

    def _commit_voice_follow_active(self):
        if self._syncing:
            return
        previous_target = self._selected_voice_persona()
        widget = self._controls.get("voice_follow_active")
        follow = bool(widget.isChecked()) if widget is not None and hasattr(widget, "isChecked") else True
        self.settings["voice_follow_active_persona"] = follow
        target = self.active_persona() if follow else (previous_target or self.active_persona())
        if target is not None:
            self.settings["voice_edit_persona_id"] = target.id
        self.storage.save_settings(self.settings)
        persona = self._selected_voice_persona()
        was_syncing = self._syncing
        self._syncing = True
        try:
            self._refresh_voice_persona_selector()
            if persona is not None:
                self._populate_voice(persona)
        finally:
            self._syncing = was_syncing
        self._update_voice_target_label()
        self._update_voice_warning()
        self._refresh_debug()

    def _commit_voice_persona(self):
        if self._syncing:
            return
        if self._voice_follows_active():
            self._refresh_voice_persona_selector()
            return
        combo = self._controls.get("voice_persona")
        if combo is None:
            return
        selected = normalize_persona_id(combo.currentData() or "")
        if not selected or self.persona_by_id(selected) is None:
            return
        self.settings["voice_edit_persona_id"] = selected
        self.storage.save_settings(self.settings)
        persona = self.persona_by_id(selected)
        if persona is not None:
            was_syncing = self._syncing
            self._syncing = True
            try:
                self._populate_voice(persona)
            finally:
                self._syncing = was_syncing
        self._update_voice_target_label()
        self._update_voice_warning()
        self._refresh_debug()

    def _commit_narrator_persona(self):
        if self._syncing:
            return
        combo = self._controls.get("narrator_persona")
        if combo is None:
            return
        selected = str(combo.currentData() or "").strip()
        self.settings["narrator_persona_id"] = selected
        self.settings["narrator_persona_mode"] = "explicit" if selected else "auto"
        narrator = self.persona_by_id(selected) if selected else self.selected_narrator_persona()
        if narrator is not None and not self._voice_follows_active():
            self.settings["voice_edit_persona_id"] = narrator.id
        self.storage.save_settings(self.settings)
        was_syncing = self._syncing
        self._syncing = True
        try:
            self._refresh_voice_persona_selector()
            voice_target = self._selected_voice_persona()
            if voice_target is not None:
                self._populate_voice(voice_target)
        finally:
            self._syncing = was_syncing
        self._persist_current_story_narrator_lock()
        self._update_voice_warning()
        self._refresh_debug()

    def _commit_visual(self):
        if self._syncing:
            return
        persona = self._selected_persona()
        if persona is None:
            return
        visual = persona.visual
        visual.enabled = self._controls["visual_enabled"].isChecked()
        visual.mode = str(self._controls["visual_mode"].currentData() or self._controls["visual_mode"].currentText()).strip() or "off"
        visual.provider = self._controls["visual_provider"].currentText().strip() or "inherit"
        visual.model = self._controls["visual_model"].text().strip()
        visual.size = self._controls["visual_size"].currentText().strip() or "inherit"
        visual.style_preset = str(self._controls["visual_style"].currentData() or "").strip()
        visual.character_description = self._controls["visual_character"].toPlainText().strip()
        visual.clothing_props = self._controls["visual_clothing"].text().strip()
        visual.environment_style = self._controls["visual_environment"].text().strip()
        visual.negative_prompt = self._controls["visual_negative"].text().strip()
        visual.keep_continuity = self._controls["visual_continuity"].isChecked()
        visual.include_scene_summary = self._controls["visual_scene"].isChecked()
        visual.include_active_speaker = self._controls["visual_speaker"].isChecked()
        visual.auto_reply_interval = int(self._controls["visual_interval"].value())
        visual.cooldown_seconds = int(self._controls["visual_cooldown"].value())
        visual.max_auto_images_per_session = int(self._controls["visual_max_auto"].value())
        visual.auto_show_dock = self._controls["visual_auto_show"].isChecked()
        self.save_state()
        self._refresh_debug()

    def _commit_session(self, *, refresh_ui: bool = True):
        if self._syncing:
            return
        c = self._controls
        previous_mode = self.session.mode
        self.session.mode = c["session_mode"].currentText().strip() or "Single active persona"
        self.session.scene_title = c["scene_title"].text().strip()
        self.session.location = c["location"].text().strip()
        self.session.time_of_day = c["time_of_day"].text().strip()
        self.session.mood = c["mood"].text().strip()
        self.session.objective = c["objective"].text().strip()
        self.session.scene_summary = c["scene_summary"].toPlainText().strip()
        self.session.auto_select_speaker = c["auto_select"].isChecked()
        self.session.current_speaker_id = str(c["next_speaker"].currentData() or self.session.active_persona_id).strip()
        self.session.keep_scene_continuity = c["continuity"].isChecked()
        self.session.update_scene_after_reply = c["update_scene"].isChecked()
        if self.session.mode == AR_MODE:
            if previous_mode != AR_MODE:
                self.settings["last_non_ar_mode"] = previous_mode or "Narrator + characters"
                self.storage.save_settings(self.settings)
            self.session.enabled = True
            self.ensure_ar_state()
        else:
            self.settings["last_non_ar_mode"] = self.session.mode
            self.storage.save_settings(self.settings)
        self.save_state()
        if refresh_ui:
            self.refresh_ui()
        else:
            self._refresh_chat_play_state_sidebar()
            self._refresh_story_export_card()
        self._refresh_debug()

    def _commit_ar_state(self):
        if self._syncing:
            return
        c = self._controls
        state = self.session.ar_state
        self.session.ar_use_persona_profiles = c["ar_use_persona_profiles"].isChecked()
        self.session.ar_pacing = c["ar_pacing"].currentText().strip() or "Balanced"
        self.session.ar_interaction_frequency = c["ar_interaction"].currentText().strip() or "Ask sometimes"
        state.tension_level = int(c["ar_tension"].value())
        state.current_scene = c["ar_current_scene"].text().strip()
        state.location = c["ar_location"].text().strip()
        state.time_of_day = c["ar_time_of_day"].text().strip()
        state.mood = c["ar_mood"].text().strip()
        state.story_goal = c["ar_story_goal"].text().strip()
        state.active_characters = [
            normalize_persona_id(item)
            for item in c["ar_active_characters"].text().split(",")
            if item.strip()
        ][:8]
        state.player_intent = c["ar_player_intent"].text().strip()
        state.pending_choices = [
            item.strip()
            for item in c["ar_pending_choices"].toPlainText().splitlines()
            if item.strip()
        ][:6]
        if self.session.mode == AR_MODE:
            self.ensure_ar_state()
        self.save_state()
        self._refresh_debug()

    def _seed_ar_state_from_session(self):
        if self._syncing:
            return
        state = self.session.ar_state
        state.current_scene = self.session.scene_title or state.current_scene
        state.location = self.session.location or state.location
        state.time_of_day = self.session.time_of_day or state.time_of_day
        state.mood = self.session.mood or state.mood
        state.story_goal = self.session.objective or state.story_goal
        self.ensure_ar_state()
        self.save_state()
        self.refresh_ui()

    def _fill_ar_persona_profiles(self):
        if self._syncing:
            return
        defaults = [PersonaConfig.from_dict(item) for item in self.storage._default_json("personas.json", [])]
        defaults_by_id = {persona.id: persona for persona in defaults}
        changed = False
        for persona in self.personas:
            default = defaults_by_id.get(persona.id)
            if default is None:
                continue
            if not str(persona.ar_description or "").strip() and str(default.ar_description or "").strip():
                persona.ar_description = default.ar_description
                changed = True
            if not str(persona.ar_system_prompt or "").strip() and str(default.ar_system_prompt or "").strip():
                persona.ar_system_prompt = default.ar_system_prompt
                changed = True
        if changed:
            self.save_state()
            self.refresh_ui()
        else:
            self._warn("AR Persona Prompts", "All matching default personas already have AR prompt profiles filled.")

    def _clear_ar_state(self):
        if self._syncing:
            return
        from .models import AlternativeRealityState

        self.session.ar_state = AlternativeRealityState()
        self.ensure_ar_state()
        self.save_state()
        self.refresh_ui()

    def _populate_master_stories(self):
        combo = self._controls.get("master_story_list")
        if combo is None:
            return
        current_id = self._selected_master_story_id()
        combo.blockSignals(True)
        combo.clear()
        stories = self.storage.load_story_index()
        if not stories:
            combo.addItem("No saved stories", "")
        else:
            for story in stories:
                title = str(story.get("title") or story.get("id") or "Story").strip()
                updated = str(story.get("updated_at") or "").strip()
                label = f"{title}  ({updated[:10]})" if updated else title
                combo.addItem(label, str(story.get("id") or ""))
            if current_id:
                index = combo.findData(current_id)
                if index >= 0:
                    combo.setCurrentIndex(index)
        combo.blockSignals(False)
        self._update_master_story_buttons()

    def _selected_master_story_id(self) -> str:
        combo = self._controls.get("master_story_list")
        if combo is None:
            return ""
        return str(combo.currentData() or "").strip()

    def _update_master_story_buttons(self):
        story_id = self._selected_master_story_id()
        for key in ("master_story_load", "master_story_delete"):
            button = self._controls.get(key)
            if button is not None:
                button.setEnabled(bool(story_id))
        self._refresh_master_story_image_preview()

    def _on_master_story_selection_changed(self):
        self._update_master_story_buttons()
        self._refresh_master_story_image_preview()
        self._refresh_story_export_card()

    def _refresh_master_story_image_preview(self):
        label = self._controls.get("master_story_image")
        if label is None:
            return
        story_id = self._selected_master_story_id()
        payload = self.storage.load_story(story_id) if story_id else {}
        image_path = str(payload.get("story_image_path") or payload.get("cover_image_path") or "").strip() if isinstance(payload, dict) else ""
        if story_id and not image_path:
            payload = self._ensure_master_story_image(dict(payload or {}), save_story=True)
            image_path = str(payload.get("story_image_path") or "").strip()
        self._set_master_story_image(label, image_path, payload if isinstance(payload, dict) else {})

    def _set_master_story_image(self, label, image_path: str, payload: dict[str, Any] | None = None) -> None:
        if label is None:
            return
        label.setText("")
        label.setStyleSheet("background: #111b28; border-radius: 6px; color: #9fb3c8;")
        path = Path(str(image_path or "").strip())
        if str(image_path or "").strip() and path.exists():
            pixmap = QtGui.QPixmap(str(path))
            if not pixmap.isNull():
                label.setPixmap(pixmap.scaled(180, 180, QtCore.Qt.KeepAspectRatioByExpanding, QtCore.Qt.SmoothTransformation))
                label.setToolTip(f"Story image: {path}")
                return
        label.setPixmap(QtGui.QPixmap())
        title = str((payload or {}).get("title") or "No story image").strip()
        label.setText(title[:80] or "No story image")
        label.setToolTip("No story image file is available yet.")

    def _ensure_master_story_image(self, payload: dict[str, Any], *, save_story: bool = False) -> dict[str, Any]:
        story = dict(payload or {})
        story_id = self.storage.story_id(story.get("id") or story.get("title") or "")
        if not story_id:
            return story
        existing = str(story.get("story_image_path") or story.get("cover_image_path") or "").strip()
        if existing and Path(existing).exists():
            story["story_image_path"] = existing
            return story
        image_path = self._create_master_story_cover_image(story)
        if image_path:
            story["story_image_path"] = image_path
            if save_story:
                self.storage.save_story(story)
        return story

    def _create_master_story_cover_image(self, payload: dict[str, Any]) -> str:
        story_id = self.storage.story_id(payload.get("id") or payload.get("title") or "story")
        if not story_id:
            return ""
        try:
            path = self.context.storage.resolve(f"stories/covers/{story_id}.png")
            path.parent.mkdir(parents=True, exist_ok=True)
            title = str(payload.get("title") or "Story").strip() or "Story"
            summary = str(payload.get("summary") or "").strip()
            session = dict(payload.get("session") or {}) if isinstance(payload.get("session"), dict) else {}
            mood_text = " ".join([title, summary, str(session.get("location") or ""), str(session.get("mood") or "")]).lower()
            top, bottom, accent = self._story_cover_colors(mood_text)
            pixmap = QtGui.QPixmap(180, 180)
            pixmap.fill(QtCore.Qt.transparent)
            painter = QtGui.QPainter(pixmap)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            gradient = QtGui.QLinearGradient(0, 0, 180, 180)
            gradient.setColorAt(0.0, QtGui.QColor(top))
            gradient.setColorAt(1.0, QtGui.QColor(bottom))
            painter.setBrush(QtGui.QBrush(gradient))
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawRoundedRect(0, 0, 180, 180, 10, 10)
            painter.setPen(QtGui.QPen(QtGui.QColor(accent), 3))
            painter.drawArc(112, 20, 42, 42, 20 * 16, 250 * 16)
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 92), 2))
            for offset in (0, 24, 48):
                painter.drawLine(22 + offset, 142, 54 + offset, 106)
                painter.drawLine(54 + offset, 106, 88 + offset, 142)
            painter.setPen(QtGui.QPen(QtGui.QColor(accent), 2))
            painter.drawRoundedRect(54, 80, 72, 70, 6, 6)
            painter.drawLine(66, 80, 66, 150)
            painter.drawLine(114, 80, 114, 150)
            painter.setPen(QtGui.QColor("#f8fafc"))
            font = painter.font()
            font.setBold(True)
            font.setPointSize(11)
            painter.setFont(font)
            text_rect = QtCore.QRect(14, 14, 152, 54)
            painter.drawText(text_rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop | QtCore.Qt.TextWordWrap, title[:70])
            font.setBold(False)
            font.setPointSize(8)
            painter.setFont(font)
            subtitle = str(session.get("location") or session.get("mood") or payload.get("mode") or "").strip()
            if subtitle:
                painter.drawText(QtCore.QRect(14, 154, 152, 18), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, subtitle[:36])
            painter.end()
            if pixmap.save(str(path), "PNG"):
                return str(path)
        except Exception as exc:
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[MPRC] Could not create story cover image: %s", exc)
        return ""

    @staticmethod
    def _story_cover_colors(text: str) -> tuple[str, str, str]:
        lowered = str(text or "").lower()
        if any(word in lowered for word in ("rain", "night", "mystery", "hotel", "noir")):
            return "#14213d", "#0f172a", "#60a5fa"
        if any(word in lowered for word in ("forest", "cave", "dragon", "magic", "fantasy", "castle")):
            return "#183a2c", "#111827", "#22c55e"
        if any(word in lowered for word in ("space", "cyber", "neon", "future", "star")):
            return "#20123a", "#0f172a", "#e879f9"
        if any(word in lowered for word in ("tavern", "warm", "sun", "desert")):
            return "#3b2f1b", "#111827", "#f59e0b"
        return "#172033", "#0f172a", "#38bdf8"

    def _set_master_story_status(self, message: str):
        label = self._controls.get("master_story_status")
        if label is not None:
            label.setText(str(message or ""))

    def _current_story_id(self) -> str:
        return self.storage.story_id(self.settings.get("last_master_story_id") or self.settings.get("last_master_story_title") or "")

    def _current_linked_persona_ids(self) -> list[str]:
        linked = [
            normalize_persona_id(item)
            for item in list(self.settings.get("master_story_linked_persona_ids") or [])
            if str(item or "").strip()
        ]
        if linked:
            return linked
        state = self.session.ar_state
        active = [normalize_persona_id(item) for item in list(getattr(state, "active_characters", []) or []) if str(item or "").strip()]
        if active:
            return active
        fallback = [item for item in (self.session.active_persona_id, self.session.current_speaker_id) if str(item or "").strip()]
        return list(dict.fromkeys(normalize_persona_id(item) for item in fallback if item))

    def _story_memory_snapshot_exists(self, story_id: str | None = None) -> bool:
        normalized = self.storage.story_id(story_id or self._current_story_id())
        if not normalized:
            return False
        try:
            return bool(self.context.storage.resolve(f"stories/{normalized}.memory.json").exists())
        except Exception:
            return bool(self.storage.load_story_memory(normalized))

    def _active_story_payload(self) -> dict[str, Any]:
        story_id = self._current_story_id()
        payload = self.storage.load_story(story_id) if story_id else {}
        return payload if isinstance(payload, dict) else {}

    def _refresh_reliability_panels(self):
        status = self._controls.get("story_status")
        if status is not None:
            status.setPlainText(self._story_runtime_status_text())
        routes = self._controls.get("story_voice_routes")
        if routes is not None:
            routes.setPlainText(self._build_voice_routing_inspector_text())
        validation = self._controls.get("story_validation")
        if validation is not None and self._validation_result:
            validation.setPlainText(self._validation_result)
        self._refresh_memory_browser()
        self._refresh_event_log_panel()

    def _story_runtime_status_text(self) -> str:
        story_id = self._current_story_id()
        story_title = str(self.settings.get("last_master_story_title") or story_id or "No active story").strip()
        narrator = self.selected_narrator_persona()
        linked = self._current_linked_persona_ids()
        known = {persona.id for persona in self.personas}
        valid_linked = [item for item in linked if item in known]
        voice_summary = self._voice_readiness_summary(valid_linked)
        visual_summary = self._visual_readiness_summary(valid_linked)
        audio_summary = self._audiofx_readiness_summary()
        memory_status = "loaded/saved" if story_id and self._story_memory_snapshot_exists(story_id) else "no saved memory snapshot"
        if not story_id:
            memory_status = "no active story"
        lines = [
            f"Active story: {story_title}",
            f"Story id: {story_id or 'none'}",
            f"Roleplay enabled: {'yes' if self.session.enabled else 'no'}",
            f"AR mode: {'on' if self.session.mode == AR_MODE else 'off'}",
            f"This story uses narrator: {narrator.display_name + ' (' + narrator.id + ')' if narrator else 'none'}",
            f"Narrator lock: {self._narrator_selection_mode()}",
            f"Active persona: {self.session.active_persona_id or 'none'}",
            f"Current speaker: {self.session.current_speaker_id or 'none'}",
            f"Active/linked personas: {', '.join(valid_linked) if valid_linked else 'none'}",
            f"Loaded memory status: {memory_status}",
            f"Voice/TTS readiness: {voice_summary}",
            f"Visual Reply readiness: {visual_summary}",
            f"AudioFX readiness: {audio_summary}",
            f"Last pre-apply backup: {'available' if self._last_pre_apply_backup_exists() else 'not found'}",
        ]
        return "\n".join(lines)

    def _voice_readiness_summary(self, persona_ids: list[str]) -> str:
        backend = self.current_tts_backend()
        if not backend:
            return "unknown TTS backend"
        ids = list(dict.fromkeys([self.selected_narrator_persona_id()] + list(persona_ids or [])))
        ids = [item for item in ids if item]
        if not ids:
            return "no routed personas"
        ready = 0
        configured = 0
        warnings = 0
        for persona_id in ids:
            route = self.voice_router.effective_voice_config({"persona_id": persona_id, "tts_backend": backend})
            if route.get("enabled"):
                configured += 1
            if route.get("supported") and route.get("sample_path"):
                ready += 1
            elif route.get("warning"):
                warnings += 1
        return f"{ready}/{len(ids)} ready, {configured} configured, backend={backend or 'unknown'}, warnings={warnings}"

    def _visual_readiness_summary(self, persona_ids: list[str]) -> str:
        service_ready = self.visual_reply_service is not None and hasattr(self.visual_reply_service, "request_generation")
        personas = [self.persona_by_id(item) for item in list(persona_ids or [])]
        personas = [item for item in personas if item is not None]
        enabled = sum(1 for persona in personas if bool(getattr(persona.visual, "enabled", False)))
        broken_images = sum(
            1
            for persona in personas
            if str(getattr(persona, "character_image_path", "") or "").strip()
            and not Path(str(persona.character_image_path)).exists()
        )
        return f"service={'ready' if service_ready else 'unavailable'}, {enabled}/{len(personas)} personas enabled, broken avatar paths={broken_images}"

    def _audiofx_readiness_summary(self) -> str:
        items = self._audiofx_items()
        ready = sum(1 for item in items if self._audiofx_file_ready(item))
        available = len(self.available_story_audio_files())
        return f"{ready}/{len(items)} AudioFX ready, {available} story cues indexed, Story Sounds={'on' if self.story_sounds_enabled() else 'off'}"

    def _build_voice_routing_inspector_text(self) -> str:
        backend = self.current_tts_backend()
        lines = [f"Active TTS backend: {backend or 'unknown'}"]
        narrator = self.selected_narrator_persona()
        if narrator is not None:
            lines.append(self._voice_route_line("[NARRATOR]", narrator, backend))
        else:
            lines.append("[NARRATOR] -> none -> missing narrator")
        for persona_id in self._current_linked_persona_ids():
            persona = self.persona_by_id(persona_id)
            if persona is None:
                lines.append(f"[CHARACTER: {persona_id}] -> missing persona -> no voice")
                continue
            display = str((self.story_prompt_persona(persona.id) or persona).display_name or persona.display_name)
            lines.append(self._voice_route_line(f"[CHARACTER: {display}]", persona, backend))
        return "\n".join(dict.fromkeys(lines))

    def _voice_route_line(self, label: str, persona: PersonaConfig, backend: str) -> str:
        route = self.voice_router.effective_voice_config({"persona_id": persona.id, "tts_backend": backend})
        sample = str(route.get("sample_path") or "").strip()
        voice_text = Path(sample).name if sample else (str(route.get("warning") or "").strip() or "voice not configured")
        return f"{label} -> {persona.display_name} ({persona.id}) -> {voice_text}"

    def _validate_story_setup_to_ui(self):
        result = self.validate_story_setup()
        self._validation_result = self._format_validation_result(result)
        widget = self._controls.get("story_validation")
        if widget is not None:
            widget.setPlainText(self._validation_result)
        self._record_story_event("Story setup validation completed.", severity="info", kind="validation", persist=True)
        self._refresh_reliability_panels()

    def validate_story_setup(self) -> dict[str, Any]:
        issues: list[dict[str, str]] = []

        def add(severity: str, message: str, kind: str = "validation") -> None:
            issues.append({"severity": severity, "kind": kind, "message": message})

        story_id = self._current_story_id()
        payload = self._active_story_payload()
        if story_id and not payload:
            add("error", f"Active story '{story_id}' could not be loaded.", "story")
        for note in list(payload.get("_migration_log") or []):
            add("warning", f"Story migration/fallback: {note}", "schema")
        if story_id and not self._story_memory_snapshot_exists(story_id):
            add("warning", f"Story memory snapshot is missing for '{story_id}'.", "memory")
        if self.session.mode == AR_MODE and self.selected_narrator_persona() is None:
            add("error", "AR mode is active but no narrator persona can be resolved.", "narrator")
        backend = self.current_tts_backend()
        if not backend:
            add("warning", "Active TTS backend is unknown.", "voice")
        elif backend not in VOICE_REFERENCE_BACKENDS:
            add("warning", f"Active TTS backend '{backend}' does not support persona voice samples.", "voice")
        known = {persona.id for persona in self.personas}
        linked = self._current_linked_persona_ids()
        for persona_id in linked:
            if persona_id not in known:
                add("error", f"Invalid linked persona id: {persona_id}", "persona")
        overrides = self._master_story_persona_overrides()
        for persona_id, override in overrides.items():
            if persona_id not in known:
                add("error", f"Persona override points to missing base persona: {persona_id}", "persona_override")
            if not isinstance(override, dict):
                add("error", f"Persona override for {persona_id} is not an object.", "persona_override")
        route_ids = list(dict.fromkeys([self.selected_narrator_persona_id()] + [item for item in linked if item in known]))
        for persona_id in route_ids:
            route = self.voice_router.effective_voice_config({"persona_id": persona_id, "tts_backend": backend})
            persona_name = str(route.get("display_name") or persona_id)
            voice = self.persona_by_id(persona_id).voice if self.persona_by_id(persona_id) is not None else None
            if voice is not None and bool(voice.enabled):
                sample = str(voice.sample_path or "").strip()
                if not sample:
                    add("warning", f"{persona_name} voice is enabled but no voice sample path is set.", "voice")
                elif not Path(sample).exists():
                    add("error", f"{persona_name} voice sample cannot be loaded: {sample}", "voice")
                elif route.get("warning"):
                    add("warning", str(route.get("warning")), "voice")
            elif persona_id == self.selected_narrator_persona_id():
                add("warning", f"Narrator {persona_name} has voice disabled.", "voice")
        story_persona_ids = list(dict.fromkeys(route_ids + linked + [self.session.active_persona_id, self.session.current_speaker_id]))
        for persona_id in story_persona_ids:
            persona = self.persona_by_id(persona_id)
            if persona is None:
                continue
            image = str(getattr(persona, "character_image_path", "") or "").strip()
            if image and not Path(image).exists():
                add("warning", f"Broken avatar image path for {persona.display_name}: {image}", "visual")
            if persona.visual.enabled and not (self.visual_reply_service is not None and hasattr(self.visual_reply_service, "request_generation")):
                add("warning", f"{persona.display_name} has Visual Reply enabled, but Visual Reply service is unavailable.", "visual")
        story_image = str(payload.get("story_image_path") or payload.get("cover_image_path") or "").strip() if payload else ""
        if story_image and not Path(story_image).exists():
            add("warning", f"Story image cannot be loaded: {story_image}", "story")
        for item in self._audiofx_items():
            file_path = str(item.get("file_path") or "").strip()
            label = str(item.get("description") or item.get("id") or "AudioFX")
            if not file_path:
                add("warning", f"AudioFX '{label}' has no audio file attached.", "audiofx")
            elif not Path(file_path).exists():
                add("error", f"AudioFX '{label}' file cannot be loaded: {file_path}", "audiofx")
        if self.story_sounds_enabled() and self._audiofx_items() and not self.available_story_audio_files():
            add("warning", "Story Sounds is enabled, but no ready AudioFX cues are indexed.", "audiofx")
        if not self.story_sounds_enabled() and self._audiofx_items():
            add("info", "Story Sounds is disabled, so LLM sound tags will be ignored.", "audiofx")
        if story_id:
            memory_payload = self.storage.load_story_memory(story_id)
            for note in list(memory_payload.get("_migration_log") or []):
                add("warning", f"Story memory migration/fallback: {note}", "schema")
        return {
            "ok": not any(item.get("severity") == "error" for item in issues),
            "issues": issues,
            "story_id": story_id,
            "checked_at": QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate),
        }

    def _format_validation_result(self, result: dict[str, Any]) -> str:
        issues = list(result.get("issues") or [])
        if not issues:
            return f"OK: Story setup validation passed for {result.get('story_id') or 'current session'}."
        counts: dict[str, int] = {}
        for item in issues:
            key = str(item.get("severity") or "info").lower()
            counts[key] = counts.get(key, 0) + 1
        lines = [
            f"Validation for {result.get('story_id') or 'current session'} at {result.get('checked_at') or ''}",
            f"Errors: {counts.get('error', 0)} | Warnings: {counts.get('warning', 0)} | Info: {counts.get('info', 0)}",
            "",
        ]
        for item in issues:
            severity = str(item.get("severity") or "info").upper()
            kind = str(item.get("kind") or "validation")
            lines.append(f"[{severity}] {kind}: {item.get('message') or ''}")
        return "\n".join(lines)

    def _clear_story_event_log(self):
        self._story_event_log = []
        self.settings["story_event_log"] = []
        self.storage.save_settings(self.settings)
        self._refresh_event_log_panel()

    def _pre_apply_backup_relative_path(self) -> str:
        return "backups/pre_apply_latest.json"

    def _last_pre_apply_backup_exists(self) -> bool:
        try:
            return bool(self.context.storage.resolve(self._pre_apply_backup_relative_path()).exists())
        except Exception:
            return bool(self.storage._read_json(self._pre_apply_backup_relative_path(), {}))

    def _save_pre_apply_backup(self, reason: str = "Apply Draft") -> bool:
        try:
            memory = self.long_memory.load()
        except Exception:
            memory = {}
        payload = {
            "schema_version": 1,
            "created_at": QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate),
            "reason": str(reason or "Apply Draft"),
            "active_story_id": self._current_story_id(),
            "active_story_payload": self._active_story_payload(),
            "personas": [persona.to_dict() for persona in self.personas],
            "session": self.session.to_dict(),
            "settings": copy.deepcopy(dict(self.settings or {})),
            "master_story_draft": copy.deepcopy(self._master_story_draft if isinstance(self._master_story_draft, dict) else {}),
            "long_memory": memory if isinstance(memory, dict) else {},
        }
        try:
            self.storage._write_json(self._pre_apply_backup_relative_path(), payload)
            self._record_story_event("pre-apply backup saved", severity="info", kind="recovery", persist=True)
            return True
        except Exception as exc:
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[MPRC] Failed to save pre-apply backup: %s", exc)
            self._record_story_event(f"backup skipped: {exc}", severity="warning", kind="recovery", persist=True)
            return False

    def _restore_last_pre_apply_backup(self):
        payload = self.storage._read_json(self._pre_apply_backup_relative_path(), {})
        if not isinstance(payload, dict) or not payload:
            self._warn("Restore Backup", "No pre-apply backup was found yet.")
            self._record_story_event("restore skipped: no pre-apply backup found", severity="warning", kind="recovery", persist=True)
            return
        personas = personas_from_payload(payload.get("personas"))
        if not personas:
            self._warn("Restore Backup", "The latest pre-apply backup does not contain a valid persona snapshot.")
            self._record_story_event("restore skipped: backup has no valid personas", severity="error", kind="recovery", persist=True)
            return
        session_payload = payload.get("session") if isinstance(payload.get("session"), dict) else {}
        settings_payload = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
        self.personas = personas
        self.session = RoleplaySessionState.from_dict(session_payload)
        self.settings = dict(settings_payload)
        self._story_event_log = self._load_story_event_log()
        draft = payload.get("master_story_draft")
        self._master_story_draft = copy.deepcopy(draft) if isinstance(draft, dict) else {}
        memory = payload.get("long_memory")
        if isinstance(memory, dict):
            self.long_memory.save(memory)
        self._ensure_session_persona()
        self.storage.save_settings(self.settings)
        self.save_state()
        self._story_audio_block_active = False
        self._story_audio_pending_text = ""
        self._last_story_audio_cues.clear()
        self._record_story_event("restored latest pre-apply backup", severity="info", kind="recovery", persist=True)
        self.refresh_ui()
        self._set_master_story_status("Restored latest pre-apply backup.")

    def _reset_current_story_only(self, _checked: bool = False, *, confirm: bool = True):
        story_id = self._current_story_id()
        if not story_id:
            self._warn("Reset Story", "No active story is loaded.")
            self._record_story_event("story reset skipped: no active story", severity="warning", kind="memory", persist=True)
            return
        if confirm:
            parent = self._widget.window() if self._widget is not None else None
            answer = QtWidgets.QMessageBox.question(
                parent,
                "Reset This Story",
                "Reset only this story's memory and runtime scene state?\n\n"
                "Personas, global app settings, and other saved stories will be kept.",
            )
            if answer != QtWidgets.QMessageBox.Yes:
                return
        payload = self._active_story_payload()
        linked_ids = self._current_linked_persona_ids()
        try:
            self.long_memory.clear()
        except Exception as exc:
            self._record_story_event(f"memory reset warning: {exc}", severity="warning", kind="memory", persist=True)
        session_payload = payload.get("session") if isinstance(payload.get("session"), dict) else {}
        if session_payload:
            self.session = RoleplaySessionState.from_dict(session_payload)
            self.session.enabled = True
            if str(payload.get("mode") or "") in SESSION_MODES:
                self.session.mode = str(payload.get("mode"))
            if linked_ids:
                self.session.active_persona_id = self._story_persona_id(self.session.active_persona_id, linked_ids)
                self.session.current_speaker_id = self._story_persona_id(self.session.current_speaker_id, linked_ids, fallback=self.session.active_persona_id)
        else:
            self.session.turn_index = 0
            self.session.recent_events = []
            self.session.character_state_summaries = self._story_character_summaries(linked_ids)
            self.session.last_visual_reply_at = 0.0
            self.session.auto_image_count = 0
            self.session.ar_state.recent_events = []
            self.session.ar_state.pending_choices = []
            self.session.ar_state.player_intent = ""
        self.settings["last_master_story_id"] = story_id
        if payload.get("title"):
            self.settings["last_master_story_title"] = payload.get("title")
        if linked_ids:
            self.settings["master_story_linked_persona_ids"] = linked_ids
        self._story_audio_block_active = False
        self._story_audio_pending_text = ""
        self._last_story_audio_cues.clear()
        self._ensure_session_persona()
        self._save_story_memory_snapshot(story_id)
        self.storage.save_settings(self.settings)
        self.save_state()
        self._record_story_event(f"reset only this story: {story_id}", severity="info", kind="memory", persist=True)
        self.refresh_ui()
        self._set_master_story_status(f"Reset only story '{self.settings.get('last_master_story_title') or story_id}'. Other stories and global settings were kept.")

    def _ensure_demo_voice_samples(self) -> dict[str, str]:
        base_dir = self.context.storage.resolve("demo_story")
        base_dir.mkdir(parents=True, exist_ok=True)
        paths = {
            "narrator": base_dir / "demo_narrator_reference.wav",
            "character": base_dir / "demo_mira_reference.wav",
        }
        if not paths["narrator"].exists():
            self._write_test_audio_file(paths["narrator"], "hum")
        if not paths["character"].exists():
            self._write_test_audio_file(paths["character"], "magic")
        return {key: str(path) for key, path in paths.items()}

    def _demo_story_payload(self, voice_paths: dict[str, str] | None = None) -> dict[str, Any]:
        voices = dict(voice_paths or {})
        now = QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate)
        return {
            "schema_version": RoleplayStorage.STORY_SCHEMA_VERSION,
            "id": "mprc_pipeline_demo",
            "title": "MPRC Pipeline Demo",
            "summary": "A compact built-in demo that exercises narrator routing, one character, Visual Reply story beats, AudioFX cues, and story memory.",
            "mode": AR_MODE,
            "updated_at": now,
            "active_persona_id": "mprc_demo_mira",
            "current_speaker_id": "mprc_demo_narrator",
            "avatar_visual_direction": "cinematic fantasy mystery portraits, warm lantern light, painterly realism, clear faces, no text",
            "session": {
                "enabled": True,
                "mode": AR_MODE,
                "scene_title": "The Lantern Door",
                "location": "A rain-soaked archive beneath an old inn",
                "time_of_day": "late night",
                "mood": "curious, tense, atmospheric",
                "objective": "Open the lantern-marked door and discover why it is humming.",
                "scene_summary": "The player and Mira stand before a lantern-marked archive door while rain taps through cracked stone above.",
                "ar_pacing": "Balanced",
                "ar_interaction_frequency": "Ask sometimes",
                "ar_state": {
                    "current_scene": "The lantern-marked door glows faintly at the end of the archive corridor.",
                    "location": "Rain-soaked archive",
                    "active_characters": ["mprc_demo_narrator", "mprc_demo_mira"],
                    "tension_level": 3,
                    "story_goal": "Learn what is behind the lantern-marked door.",
                    "recent_events": ["Mira found a wet key with a lantern symbol."],
                    "player_intent": "",
                    "pending_choices": ["Open the lantern door", "Ask Mira what she hears", "Wait and listen"],
                    "mood": "rainy mystery",
                    "time_of_day": "late night",
                },
            },
            "personas": [
                {
                    "id": "mprc_demo_narrator",
                    "display_name": "Demo Narrator",
                    "role": "narrator",
                    "description": "A clear cinematic narrator for the built-in MPRC demo story.",
                    "system_prompt": "Narrate the scene with concise audiobook pacing and clear consequences.",
                    "ar_profile_enabled": True,
                    "ar_description": "Primary narrator for the demo. Controls continuity, mood, camera-like framing, and pacing.",
                    "ar_system_prompt": "Use [NARRATOR] for scene framing. Characters only speak in their own [CHARACTER: Name] sections.",
                    "speaking_style": "calm, cinematic, atmospheric",
                    "behavior_mode": "narrator",
                    "memory_scope": "shared",
                    "tags": ["demo", "narrator"],
                    "voice": {
                        "enabled": True,
                        "backend": "chatterbox",
                        "sample_path": voices.get("narrator", ""),
                    },
                    "visual": {
                        "enabled": False,
                        "mode": "manual",
                        "provider": "inherit",
                        "size": "inherit",
                    },
                },
                {
                    "id": "mprc_demo_mira",
                    "display_name": "Mira",
                    "role": "archive guide",
                    "description": "A practical guide with a lantern and a dry sense of wonder.",
                    "system_prompt": "Speak as Mira only when the scene calls for her. Keep dialogue short and grounded.",
                    "ar_profile_enabled": True,
                    "ar_description": "Mira is the player's first companion in the demo: observant, brave, and lightly nervous.",
                    "ar_system_prompt": "Use [CHARACTER: Mira] only for Mira's dialogue or immediate reactions.",
                    "speaking_style": "warm, direct, quietly excited",
                    "behavior_mode": "group participant",
                    "memory_scope": "persona-only",
                    "tags": ["demo", "guide"],
                    "voice": {
                        "enabled": True,
                        "backend": "chatterbox",
                        "sample_path": voices.get("character", ""),
                    },
                    "visual": {
                        "enabled": True,
                        "mode": "auto_story_beat",
                        "provider": "inherit",
                        "size": "inherit",
                        "character_description": "young archive guide with a brass lantern, rain-damp cloak, expressive eyes, practical adventurer clothing",
                        "clothing_props": "brass lantern, wet cloak, leather satchel, old key",
                        "environment_style": "rain-soaked underground archive, warm lantern light, old stone, dust and water",
                        "negative_prompt": "text, watermark, logo, distorted hands, extra limbs",
                    },
                },
            ],
            "available_audio_cues": ["pub ambient", "rain storm", "magic shimmer", "danger stinger"],
        }

    def _load_demo_story(self):
        self._create_test_audiofx(show_status=False)
        voice_paths = self._ensure_demo_voice_samples()
        payload = self._normalize_master_story_payload(self._demo_story_payload(voice_paths))
        story_id = self.storage.save_story(payload)
        self._master_story_draft = payload
        self._set_master_story_sfw_from_payload(payload)
        draft_widget = self._controls.get("master_story_draft")
        if draft_widget is not None:
            draft_widget.setPlainText(json.dumps(payload, indent=2, ensure_ascii=True))
        actions: dict[str, str] = {}
        choices: dict[str, str] = {}
        for index, persona_payload in enumerate(list(payload.get("personas") or [])):
            persona_id = normalize_persona_id(persona_payload.get("id") or "")
            existing = self.persona_by_id(persona_id)
            actions[str(index)] = "reuse_update" if existing is not None else "__create__"
            choices[str(index)] = persona_id if existing is not None else "__create__"
        self._apply_master_story_payload(
            payload,
            apply_plan={
                "clear_memory": True,
                "auto_create": True,
                "auto_avatars": False,
                "backup_reason": "Load Demo Story",
                "persona_actions_by_row": actions,
                "persona_choices_by_row": choices,
            },
        )
        narrator = self.persona_by_id("mprc_demo_narrator")
        if narrator is not None:
            self.settings["narrator_persona_id"] = narrator.id
            self.settings["narrator_persona_mode"] = "explicit"
        try:
            self.long_memory.record_turn(
                session=self.session,
                personas=self.story_prompt_personas(),
                user_text="Demo story loaded.",
                assistant_text=(
                    "[NARRATOR]\nRain ticks through the cracked archive ceiling while the lantern-marked door hums.\n"
                    "[CHARACTER: Mira]\nIf it starts singing, I am blaming the key.\n"
                    "[AMBIENCE: rain storm]\n[CHOICES]\n- Open the lantern door\n- Ask Mira what she hears\n- Wait and listen"
                ),
            )
        except Exception as exc:
            self._record_story_event(f"demo memory warning: {exc}", severity="warning", kind="memory", persist=True)
        self._save_story_memory_snapshot(story_id)
        self.storage.save_settings(self.settings)
        self.save_state()
        self._populate_master_stories()
        combo = self._controls.get("master_story_list")
        if combo is not None:
            index = combo.findData(story_id)
            if index >= 0:
                combo.setCurrentIndex(index)
        self._record_story_event("demo story loaded with narrator, Mira, Visual Reply trigger, AudioFX, and memory", severity="info", kind="demo", persist=True)
        self.refresh_ui()
        self._set_master_story_status("Loaded MPRC Pipeline Demo. Press Continue to test narrator, Mira, memory, Visual Reply policy, and AudioFX cues.")

    def _story_template_choices(self) -> list[tuple[str, str]]:
        return [
            ("fantasy_mystery", "Fantasy mystery"),
            ("sci_fi_horror", "Sci-fi horror"),
            ("cozy_tavern", "Cozy tavern adventure"),
        ]

    def _story_template_payload(self, template_id: str, voice_paths: dict[str, str] | None = None) -> dict[str, Any]:
        voices = dict(voice_paths or {})
        now = QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate)
        specs = {
            "fantasy_mystery": {
                "id": "mprc_template_fantasy_mystery",
                "title": "The Lantern Ledger",
                "summary": "A fantasy mystery about a sealed inn cellar, a missing guest ledger, and a lantern that glows when someone lies.",
                "scene": "The Lantern Ledger",
                "location": "The cellar beneath the Rainwake Inn",
                "mood": "rainy, secretive, candlelit",
                "goal": "Discover who altered the guest ledger before dawn.",
                "character_id": "mprc_template_elara",
                "character": "Elara",
                "role": "innkeeper's sharp-eyed daughter",
                "character_description": "Elara carries a brass keyring and notices details others miss.",
                "voice_style": "quick, observant, quietly brave",
                "visual": "young fantasy innkeeper's daughter with brass keys, rain-dark hair, candlelit cellar, practical dress and leather apron",
                "audio": "rain storm",
                "recent": "Elara found wax on the ledger lock even though nobody lit candles near it.",
                "choice": "Ask Elara who had the cellar key",
            },
            "sci_fi_horror": {
                "id": "mprc_template_sci_fi_horror",
                "title": "Signal Under Deck Nine",
                "summary": "A sci-fi horror setup inside a damaged freighter where an impossible signal keeps answering before anyone speaks.",
                "scene": "Deck Nine Signal",
                "location": "A dark maintenance spine aboard the freighter Vesper",
                "mood": "claustrophobic, metallic, tense",
                "goal": "Find the source of the signal before the ship wakes something sealed below deck nine.",
                "character_id": "mprc_template_kade",
                "character": "Kade",
                "role": "ship engineer",
                "character_description": "Kade is a tired engineer who masks fear with procedure.",
                "voice_style": "low, clipped, technical, nervous",
                "visual": "sci-fi engineer in worn pressure jacket, handheld scanner, dark spaceship corridor, emergency red light, condensation on metal",
                "audio": "deep engine hum",
                "recent": "Kade heard the signal repeat the player's last breath pattern.",
                "choice": "Ask Kade to isolate the signal",
            },
            "cozy_tavern": {
                "id": "mprc_template_cozy_tavern",
                "title": "The Hearth That Remembered",
                "summary": "A cozy tavern adventure where the old hearth remembers every promise made beside it and one promise has gone missing.",
                "scene": "Remembering Hearth",
                "location": "The Amber Cup tavern during a gentle snowstorm",
                "mood": "warm, curious, comforting",
                "goal": "Learn which forgotten promise made the hearth dim.",
                "character_id": "mprc_template_brindle",
                "character": "Brindle",
                "role": "friendly tavern keeper",
                "character_description": "Brindle runs the tavern with warmth, humor, and a careful memory for regulars.",
                "voice_style": "warm, conversational, amused",
                "visual": "cozy fantasy tavern keeper with rolled sleeves, warm hearth glow, wooden mugs, snow outside the window, gentle smile",
                "audio": "pub ambient",
                "recent": "Brindle noticed the hearth went quiet when the old promise-stone cracked.",
                "choice": "Ask Brindle about the promise-stone",
            },
        }
        spec = specs.get(str(template_id or "").strip()) or specs["fantasy_mystery"]
        narrator_id = f"{spec['id']}_narrator"
        character_id = str(spec["character_id"])
        return {
            "schema_version": RoleplayStorage.STORY_SCHEMA_VERSION,
            "id": spec["id"],
            "title": spec["title"],
            "summary": spec["summary"],
            "mode": AR_MODE,
            "updated_at": now,
            "active_persona_id": character_id,
            "current_speaker_id": narrator_id,
            "narrator_persona_id": narrator_id,
            "narrator_persona_mode": "explicit",
            "avatar_visual_direction": "cinematic story portrait, expressive face, clear composition, no text, polished local adventure game style",
            "session": {
                "enabled": True,
                "mode": AR_MODE,
                "scene_title": spec["scene"],
                "location": spec["location"],
                "time_of_day": "opening scene",
                "mood": spec["mood"],
                "objective": spec["goal"],
                "scene_summary": spec["summary"],
                "ar_pacing": "Balanced",
                "ar_interaction_frequency": "Ask sometimes",
                "ar_state": {
                    "current_scene": spec["summary"],
                    "location": spec["location"],
                    "active_characters": [narrator_id, character_id],
                    "tension_level": 3,
                    "story_goal": spec["goal"],
                    "recent_events": [spec["recent"]],
                    "player_intent": "",
                    "pending_choices": [spec["choice"], "Continue listening", "Inspect the room"],
                    "mood": spec["mood"],
                    "time_of_day": "opening scene",
                },
            },
            "personas": [
                {
                    "id": narrator_id,
                    "display_name": f"{spec['title']} Narrator",
                    "role": "narrator",
                    "description": f"A cinematic narrator for {spec['title']}.",
                    "system_prompt": "Narrate with clear audiobook pacing, scene continuity, and visible consequences.",
                    "ar_profile_enabled": True,
                    "ar_description": "Story-owned narrator. Controls continuity, framing, pacing, and consequences.",
                    "ar_system_prompt": "Use [NARRATOR] for narration. Characters only speak in their own [CHARACTER: Name] sections.",
                    "speaking_style": "cinematic, clear, grounded",
                    "behavior_mode": "narrator",
                    "memory_scope": "shared",
                    "tags": ["template", "narrator"],
                    "voice": {"enabled": True, "backend": "chatterbox", "sample_path": voices.get("narrator", "")},
                    "visual": {"enabled": False, "mode": "manual", "provider": "inherit", "size": "inherit"},
                },
                {
                    "id": character_id,
                    "display_name": spec["character"],
                    "role": spec["role"],
                    "description": spec["character_description"],
                    "system_prompt": f"Speak as {spec['character']} only when the scene calls for direct dialogue.",
                    "ar_profile_enabled": True,
                    "ar_description": f"{spec['character']} is the first active character in this template. {spec['character_description']}",
                    "ar_system_prompt": f"Use [CHARACTER: {spec['character']}] only for direct spoken dialogue.",
                    "speaking_style": spec["voice_style"],
                    "behavior_mode": "group participant",
                    "memory_scope": "persona-only",
                    "tags": ["template", "story-character"],
                    "voice": {"enabled": True, "backend": "chatterbox", "sample_path": voices.get("character", "")},
                    "visual": {
                        "enabled": True,
                        "mode": "auto_story_beat",
                        "provider": "inherit",
                        "size": "inherit",
                        "character_description": spec["visual"],
                        "clothing_props": spec["visual"],
                        "environment_style": spec["location"],
                        "negative_prompt": "text, watermark, logo, distorted face, extra limbs",
                    },
                },
            ],
            "available_audio_cues": [spec["audio"], "magic shimmer", "danger stinger", "adventure music"],
        }

    def _load_selected_story_template(self):
        combo = self._controls.get("story_template")
        template_id = str(combo.currentData() if combo is not None else "fantasy_mystery").strip() or "fantasy_mystery"
        self._load_story_template(template_id)

    def _load_story_template(self, template_id: str):
        self._create_test_audiofx(show_status=False)
        voice_paths = self._ensure_demo_voice_samples()
        payload = self._normalize_master_story_payload(self._story_template_payload(template_id, voice_paths))
        story_id = self.storage.save_story(payload)
        self._master_story_draft = payload
        self._set_master_story_sfw_from_payload(payload)
        draft_widget = self._controls.get("master_story_draft")
        if draft_widget is not None:
            draft_widget.setPlainText(json.dumps(payload, indent=2, ensure_ascii=True))
        actions = {str(index): ("reuse_update" if self.persona_by_id(str(item.get("id") or "")) is not None else "__create__") for index, item in enumerate(payload.get("personas") or []) if isinstance(item, dict)}
        choices = {key: (normalize_persona_id((payload.get("personas") or [])[int(key)].get("id")) if action == "reuse_update" else "__create__") for key, action in actions.items()}
        self._apply_master_story_payload(
            payload,
            apply_plan={
                "clear_memory": True,
                "auto_create": True,
                "auto_avatars": False,
                "backup_reason": "Load Story Template",
                "persona_actions_by_row": actions,
                "persona_choices_by_row": choices,
            },
        )
        narrator_id = normalize_persona_id(payload.get("narrator_persona_id") or "")
        if narrator_id and self.persona_by_id(narrator_id) is not None:
            self.settings["narrator_persona_id"] = narrator_id
            self.settings["narrator_persona_mode"] = "explicit"
            self._persist_current_story_narrator_lock()
        try:
            self.long_memory.record_turn(
                session=self.session,
                personas=self.story_prompt_personas(),
                user_text="Story template loaded.",
                assistant_text=f"[NARRATOR]\n{payload.get('summary')}\n[AMBIENCE: {((payload.get('available_audio_cues') or ['pub ambient'])[0])}]\n[CHOICES]\n- Continue",
            )
        except Exception as exc:
            self._record_story_event(f"template memory warning: {exc}", severity="warning", kind="memory", persist=True)
        self._save_story_memory_snapshot(story_id)
        self.storage.save_settings(self.settings)
        self.save_state()
        self._populate_master_stories()
        self._record_story_event(f"template loaded: {payload.get('title')}", severity="info", kind="template", persist=True)
        self.refresh_ui()
        self._set_master_story_status(f"Loaded template '{payload.get('title')}'. Validate it, then press Continue.")

    def _start_demo_validate_continue(self):
        self._load_demo_story()
        self._validate_story_setup_to_ui()
        self._test_audiofx_from_status()
        self._test_visual_reply_from_status()
        self._queue_continue_story(
            "Continue. Include one short [NARRATOR] beat and one short [CHARACTER: Mira] line if Mira is present."
        )
        self._record_story_event("first-run demo path started: demo loaded, validated, AudioFX/Visual tested, Continue queued", severity="info", kind="demo", persist=True)
        self._set_master_story_status("Started demo, validated setup, tested AudioFX/Visual Reply, and queued Continue.")

    def _queue_continue_story(self, text: str = "Continue") -> bool:
        message = str(text or "Continue").strip() or "Continue"
        try:
            from core.engine_access import queue_typed_chat_message

            result = dict(queue_typed_chat_message(message, role="user") or {})
            if result.get("queued"):
                self._record_story_event(f"queued story input: {message[:120]}", severity="info", kind="runtime", persist=True)
                return True
            self._record_story_event(f"continue not queued: {result.get('reason', 'unknown')}", severity="warning", kind="runtime", persist=True)
        except Exception as exc:
            self._record_story_event(f"continue not queued: {exc}", severity="warning", kind="runtime", persist=True)
        try:
            QtWidgets.QApplication.clipboard().setText(message)
        except Exception:
            pass
        return False

    def _story_export_option_specs(self) -> list[dict[str, Any]]:
        return [
            {"key": "story_setup", "label": "Story setup / session state", "default": True, "file": "session.json"},
            {"key": "story_metadata", "label": "Story Library entry / story metadata", "default": True, "file": "story.json"},
            {"key": "personas", "label": "Personas used by this story", "default": True, "file": "personas.json"},
            {"key": "persona_visual", "label": "Persona visual settings", "default": True, "file": "persona_visual_settings.json"},
            {"key": "avatar_assets", "label": "Persona avatar image files", "default": True, "file": "assets/visuals/"},
            {"key": "persona_voice", "label": "Persona voice settings", "default": True, "file": "persona_voice_settings.json"},
            {"key": "voice_assets", "label": "Voice sample/audio files", "default": True, "file": "assets/voices/"},
            {"key": "story_memory", "label": "Story memory", "default": True, "file": "story_memory.json"},
            {"key": "story_events", "label": "Recent story events / story log", "default": True, "file": "story_events.json"},
            {"key": "audiofx", "label": "Sound effects / AudioFX settings", "default": True, "file": "audiofx.json"},
            {"key": "audiofx_assets", "label": "Sound effect audio files", "default": True, "file": "assets/audiofx/"},
            {"key": "visual_styles", "label": "Visual styles used by story", "default": True, "file": "visual_styles.json"},
            {"key": "master_story", "label": "Master Story draft/setup data if available", "default": True, "file": "master_story.json"},
            {"key": "templates", "label": "Story prompt/template data if available", "default": True, "file": "templates.json"},
        ]

    def _story_export_spec_by_key(self) -> dict[str, dict[str, Any]]:
        return {str(item.get("key") or ""): dict(item) for item in self._story_export_option_specs()}

    def _on_story_export_option_changed(self) -> None:
        if self._syncing:
            return
        self.settings["story_library_export_sections"] = self._story_export_selected_sections()
        self.storage.save_settings(self.settings)
        self._refresh_story_export_card()

    def _story_export_selected_sections(self) -> list[str]:
        controls = self._controls.get("story_export_options")
        if isinstance(controls, dict) and controls:
            selected = [
                str(key)
                for key, checkbox in controls.items()
                if hasattr(checkbox, "isChecked") and bool(checkbox.isChecked())
            ]
            return [item for item in self._story_export_spec_by_key() if item in set(selected)]
        raw = self.settings.get("story_library_export_sections")
        if isinstance(raw, list):
            selected = {str(item or "").strip() for item in raw}
            return [item for item in self._story_export_spec_by_key() if item in selected]
        return [str(item.get("key") or "") for item in self._story_export_option_specs() if bool(item.get("default", True))]

    def _story_export_story_id(self) -> str:
        selected = self._selected_master_story_id()
        return self.storage.story_id(selected or self._current_story_id() or "")

    def _story_export_story_payload(self) -> dict[str, Any]:
        story_id = self._story_export_story_id()
        payload = self.storage.load_story(story_id) if story_id else {}
        if isinstance(payload, dict) and payload:
            return payload
        snapshot = self._current_master_story_snapshot()
        return snapshot if isinstance(snapshot, dict) else {}

    def _story_export_persona_ids_from_story(self, story: dict[str, Any] | None = None) -> list[str]:
        story = dict(story or self._story_export_story_payload() or {})
        ids: list[str] = []

        def add(value: Any) -> None:
            persona_id = normalize_persona_id(value)
            if persona_id and persona_id not in ids:
                ids.append(persona_id)

        for key in ("narrator_persona_id", "active_persona_id", "current_speaker_id"):
            add(story.get(key))
        session = dict(story.get("session") or {}) if isinstance(story.get("session"), dict) else {}
        for key in ("narrator_persona_id", "active_persona_id", "current_speaker_id"):
            add(session.get(key))
        ar_state = dict(session.get("ar_state") or {}) if isinstance(session.get("ar_state"), dict) else {}
        for item in list(ar_state.get("active_characters") or []):
            add(item)
        for item in list(story.get("personas") or []):
            if isinstance(item, dict):
                add(item.get("id") or item.get("display_name"))
        overrides = story.get("persona_overrides")
        if isinstance(overrides, dict):
            for key in overrides:
                add(key)
        for item in [self.selected_narrator_persona_id(), *self._current_linked_persona_ids()]:
            add(item)
        return ids

    def _story_export_persona_configs(self, story: dict[str, Any] | None = None) -> list[PersonaConfig]:
        story = dict(story or self._story_export_story_payload() or {})
        ids = self._story_export_persona_ids_from_story(story)
        by_id = {persona.id: persona for persona in self.personas}
        result: list[PersonaConfig] = []
        seen: set[str] = set()
        for persona_id in ids:
            persona = by_id.get(persona_id)
            if persona is None:
                for item in list(story.get("personas") or []):
                    if isinstance(item, dict) and normalize_persona_id(item.get("id") or item.get("display_name")) == persona_id:
                        persona = PersonaConfig.from_dict(item)
                        break
            if persona is not None and persona.id not in seen:
                result.append(persona)
                seen.add(persona.id)
        if not result and self.personas:
            active = self.active_persona()
            if active is not None:
                result.append(active)
        return result

    def _story_export_visual_styles_for_personas(self, personas: list[PersonaConfig]) -> list[dict[str, str]]:
        used = {
            str(getattr(getattr(persona, "visual", None), "style_preset", "") or "").strip()
            for persona in list(personas or [])
        }
        used = {item for item in used if item}
        if not used:
            return []
        return [dict(item) for item in list(self.visual_styles or []) if str(item.get("id") or "").strip() in used]

    def _story_export_templates_payload(self) -> dict[str, Any]:
        templates = self.storage._read_json("roleplay_templates.json", {})
        payload: dict[str, Any] = {}
        if isinstance(templates, dict) and templates:
            payload["roleplay_templates"] = copy.deepcopy(templates)
        saved_prompts = self.settings.get("saved_audio_prompts")
        if isinstance(saved_prompts, list) and saved_prompts:
            payload["saved_audio_prompts"] = copy.deepcopy(saved_prompts)
        prompt = self._controls.get("master_story_prompt")
        if prompt is not None and hasattr(prompt, "toPlainText"):
            text = str(prompt.toPlainText() or "").strip()
            if text:
                payload["current_master_story_prompt"] = text
        return payload

    def _story_export_availability(self) -> dict[str, dict[str, Any]]:
        story = self._story_export_story_payload()
        story_id = self.storage.story_id(story.get("id") or self._story_export_story_id() or "")
        personas = self._story_export_persona_configs(story)
        voice_paths = [
            str(getattr(getattr(persona, "voice", None), "sample_path", "") or "").strip()
            for persona in personas
        ]
        audio_items = self._audiofx_items()
        available_audio = self.available_story_audio_files()
        memory = self.storage.load_story_memory(story_id) if story_id else {}
        if not memory:
            try:
                loaded = self.long_memory.load()
                memory = loaded if isinstance(loaded, dict) else {}
            except Exception:
                memory = {}
        story_events = list(self._story_event_log or [])
        ar_state = getattr(self.session, "ar_state", None)
        session_events = list(getattr(self.session, "recent_events", []) or []) + list(getattr(ar_state, "recent_events", []) or [])
        visual_styles = self._story_export_visual_styles_for_personas(personas)
        templates = self._story_export_templates_payload()
        draft = self._master_story_draft if isinstance(self._master_story_draft, dict) else {}

        def item(available: bool, count: int = 0, detail: str = "") -> dict[str, Any]:
            return {"available": bool(available), "count": int(count or 0), "detail": str(detail or "")}

        return {
            "story_setup": item(bool(self.session), 1, "Current roleplay session state"),
            "story_metadata": item(bool(story), 1 if story else 0, story.get("title") or story_id),
            "personas": item(bool(personas), len(personas), f"{len(personas)} linked persona(s)"),
            "persona_visual": item(
                any(
                    bool(getattr(persona.visual, "enabled", False))
                    or any(str(getattr(persona.visual, field, "") or "").strip() for field in ("style_preset", "character_description", "clothing_props", "environment_style", "negative_prompt"))
                    for persona in personas
                ),
                len(personas),
                "Visual profile data",
            ),
            "avatar_assets": item(
                any(
                    str(getattr(persona, "character_image_path", "") or "").strip()
                    and Path(str(persona.character_image_path)).exists()
                    for persona in personas
                ),
                len([
                    persona
                    for persona in personas
                    if str(getattr(persona, "character_image_path", "") or "").strip()
                    and Path(str(persona.character_image_path)).exists()
                ]),
                "Existing local character/avatar image files",
            ),
            "persona_voice": item(
                any(bool(getattr(persona.voice, "enabled", False)) or str(getattr(persona.voice, "sample_path", "") or "").strip() for persona in personas),
                len([persona for persona in personas if bool(getattr(persona.voice, "enabled", False)) or str(getattr(persona.voice, "sample_path", "") or "").strip()]),
                "Per-persona voice routing settings",
            ),
            "voice_assets": item(
                any(path and Path(path).exists() for path in voice_paths),
                len([path for path in voice_paths if path and Path(path).exists()]),
                "Existing local voice sample files",
            ),
            "story_memory": item(bool(memory), 1 if memory else 0, "Saved story memory or active long memory"),
            "story_events": item(bool(story_events or session_events), len(story_events) + len(session_events), "Recent story events and story log"),
            "audiofx": item(bool(audio_items or available_audio or self.settings.get("saved_audio_prompts")), len(audio_items), "AudioFX settings and saved audio prompts"),
            "audiofx_assets": item(
                any(self._audiofx_file_ready(item) for item in audio_items) or any(Path(str(item.get("file_path") or "")).exists() for item in available_audio if isinstance(item, dict)),
                sum(1 for item in audio_items if self._audiofx_file_ready(item)),
                "Existing local AudioFX files",
            ),
            "visual_styles": item(bool(visual_styles), len(visual_styles), "Style presets referenced by linked personas"),
            "master_story": item(bool(story or draft), 1 if story or draft else 0, "Saved story payload and current draft"),
            "templates": item(bool(templates), len(templates), "Roleplay templates, saved prompts, or current story prompt"),
        }

    def _refresh_story_export_card(self) -> None:
        controls = self._controls.get("story_export_options")
        status = self._controls.get("story_export_status")
        if not isinstance(controls, dict) or not controls:
            return
        availability = self._story_export_availability()
        selected = set(self._story_export_selected_sections())
        spec_by_key = self._story_export_spec_by_key()
        available_selected = 0
        selected_count = 0
        for key, checkbox in controls.items():
            info = availability.get(str(key), {})
            available = bool(info.get("available"))
            if str(key) in selected:
                selected_count += 1
                if available:
                    available_selected += 1
            label = str(spec_by_key.get(str(key), {}).get("label") or key)
            detail = str(info.get("detail") or "")
            count = int(info.get("count") or 0)
            checkbox.setToolTip(f"{label}\n{'Available' if available else 'No data detected'}" + (f": {detail}" if detail else ""))
            checkbox.setStyleSheet(
                _mprc_checkbox_stylesheet("#22c55e", "700")
                if available
                else _mprc_checkbox_stylesheet("#9fb3c8", "600")
            )
            checkbox.setText(f"{label} ({count})" if available and count > 1 else label)
        if status is not None:
            story = self._story_export_story_payload()
            title = str(story.get("title") or self._story_export_story_id() or "current story").strip()
            status.setText(
                f"{available_selected}/{selected_count or len(selected)} selected sections have data for '{title}'. "
                "Green rows have data available to save; neutral rows have no matching data right now."
            )

    def _preview_story_package_contents(self) -> None:
        availability = self._story_export_availability()
        selected = set(self._story_export_selected_sections())
        spec_by_key = self._story_export_spec_by_key()
        lines = ["Story Library Export preview:", ""]
        for key in spec_by_key:
            if key not in selected:
                continue
            info = availability.get(key, {})
            marker = "ready" if bool(info.get("available")) else "no data"
            detail = str(info.get("detail") or "").strip()
            lines.append(f"- {spec_by_key[key].get('label')}: {marker}" + (f" ({detail})" if detail else ""))
        parent = self._widget.window() if self._widget is not None else None
        QtWidgets.QMessageBox.information(parent, "Story Library Export", "\n".join(lines))

    def _story_bundle_settings(self) -> dict[str, Any]:
        keys = (
            "last_master_story_id",
            "last_master_story_title",
            "master_story_linked_persona_ids",
            "master_story_created_persona_ids",
            "master_story_persona_overrides",
            "master_story_avatar_style_sheets",
            "narrator_persona_id",
            "narrator_persona_mode",
            "story_sounds_enabled",
            "audio_fx_items",
            "available_audio_files",
            "saved_audio_prompts",
            "audiofx_volume",
            "audiofx_test_mode",
        )
        settings = {key: copy.deepcopy(self.settings.get(key)) for key in keys if key in self.settings}
        style_sheets = self._story_avatar_style_sheet_settings()
        if style_sheets:
            settings["persona_avatar_style_sheets"] = style_sheets
        return settings

    def _story_avatar_style_sheet_settings(self, story_id: str | None = None, persona_ids: list[str] | None = None) -> dict[str, Any]:
        raw = self.settings.get("persona_avatar_style_sheets")
        if not isinstance(raw, dict):
            return {}
        raw_story_id = str(story_id if story_id is not None else (self.settings.get("last_master_story_id") or self.settings.get("last_master_story_title") or "")).strip()
        normalized_story_id = self.storage.story_id(raw_story_id) if raw_story_id else ""
        linked = {
            normalize_persona_id(item)
            for item in list(persona_ids or self._current_linked_persona_ids())
            if str(item or "").strip()
        }
        result: dict[str, Any] = {}
        for persona_id, value in raw.items():
            normalized_persona_id = normalize_persona_id(persona_id)
            if not normalized_persona_id or not isinstance(value, dict):
                continue
            raw_item_story_id = str(value.get("story_id") or "").strip()
            item_story_id = self.storage.story_id(raw_item_story_id) if raw_item_story_id else ""
            if normalized_story_id and item_story_id == normalized_story_id:
                result[normalized_persona_id] = copy.deepcopy(value)
            elif normalized_persona_id in linked and not item_story_id:
                result[normalized_persona_id] = copy.deepcopy(value)
        return result

    def _merge_story_avatar_style_sheet_settings(self, value: Any) -> None:
        if not isinstance(value, dict):
            return
        current = self.settings.get("persona_avatar_style_sheets")
        merged: dict[str, Any] = dict(current or {}) if isinstance(current, dict) else {}
        changed = False
        for persona_id, item in value.items():
            normalized_persona_id = normalize_persona_id(persona_id)
            if not normalized_persona_id or not isinstance(item, dict):
                continue
            merged[normalized_persona_id] = copy.deepcopy(item)
            changed = True
        if changed:
            self.settings["persona_avatar_style_sheets"] = merged

    def _build_story_bundle(self) -> dict[str, Any]:
        story_id = self._current_story_id()
        story = self._active_story_payload() if story_id else self._current_master_story_snapshot()
        linked = self._current_linked_persona_ids()
        if not linked:
            linked = [persona.id for persona in self.personas]
        personas = [persona.to_dict() for persona in self.personas if persona.id in set(linked)]
        memory = self.storage.load_story_memory(story_id) if story_id else {}
        return {
            "schema_version": 1,
            "bundle_type": "mprc_story_bundle",
            "exported_at": QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate),
            "story_id": story_id or story.get("id"),
            "story": story,
            "personas": personas,
            "settings": self._story_bundle_settings(),
            "session": self.session.to_dict(),
            "memory_snapshot": memory,
            "prompts": {
                "master_story_draft": copy.deepcopy(self._master_story_draft),
                "debug_prompt": self._debug_prompt,
                "debug_visual_prompt": self._debug_visual_prompt,
            },
            "audiofx": {
                "items": list(self._audiofx_items()),
                "available_audio_files": list(self.available_story_audio_files()),
                "saved_audio_prompts": list(self.settings.get("saved_audio_prompts") or []),
            },
            "visual_settings": {
                persona.id: persona.visual.to_dict() for persona in self.personas if persona.id in set(linked)
            },
            "voice_routing": self._build_voice_routing_inspector_text(),
            "narrator": {
                "persona_id": self.selected_narrator_persona_id(),
                "mode": self._narrator_selection_mode(),
                "display_name": self.selected_narrator_persona().display_name if self.selected_narrator_persona() is not None else "",
            },
        }

    def _story_package_safe_name(self, value: Any, fallback: str = "asset") -> str:
        text = str(value or "").strip()
        safe = []
        previous = False
        for char in text:
            if char.isalnum() or char in {".", "_", "-"}:
                safe.append(char)
                previous = False
            elif not previous:
                safe.append("_")
                previous = True
        result = "".join(safe).strip("._-")
        return result[:96] or fallback

    def _story_package_scrub_runtime_paths(self, value: Any) -> Any:
        path_keys = {"sample_path", "file_path", "character_image_path", "story_image_path", "cover_image_path", "image_path"}
        if isinstance(value, list):
            return [self._story_package_scrub_runtime_paths(item) for item in value]
        if not isinstance(value, dict):
            return copy.deepcopy(value)
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text in path_keys and isinstance(item, str):
                text = str(item or "").strip().replace("\\", "/")
                cleaned[key] = text if text.startswith("assets/") else ""
            else:
                cleaned[key] = self._story_package_scrub_runtime_paths(item)
        return cleaned

    def _story_package_unique_asset_path(self, folder: str, key: str, source_path: Path, used: set[str]) -> str:
        stem = self._story_package_safe_name(key, "asset")
        name = self._story_package_safe_name(source_path.name, "file")
        candidate = f"assets/{folder}/{stem}_{name}"
        counter = 2
        while candidate.lower() in used:
            candidate = f"assets/{folder}/{stem}_{counter}_{name}"
            counter += 1
        used.add(candidate.lower())
        return candidate

    def _copy_package_asset(
        self,
        zip_handle: zipfile.ZipFile,
        source_path: str,
        asset_path: str,
        asset_key: str,
        asset_file_map: dict[str, Any],
        warnings: list[str],
    ) -> bool:
        raw = str(source_path or "").strip()
        if not raw:
            return False
        path = Path(raw)
        if not path.exists() or not path.is_file():
            warnings.append(f"Missing asset for {asset_key}: {raw}")
            return False
        try:
            zip_handle.write(str(path), asset_path)
            asset_file_map[asset_key] = {
                "asset_path": asset_path,
                "file_name": path.name,
                "source_path": str(path),
            }
            return True
        except Exception as exc:
            warnings.append(f"Could not copy asset for {asset_key}: {exc}")
            return False

    def _build_story_package_manifest(
        self,
        *,
        story: dict[str, Any],
        included_sections: list[str],
        asset_file_map: dict[str, Any],
        warnings: list[str],
    ) -> dict[str, Any]:
        manifest = getattr(self.context, "manifest", None)
        addon_version = ""
        try:
            addon_version = str(getattr(manifest, "version", "") or "")
        except Exception:
            addon_version = ""
        story_id = self.storage.story_id(story.get("id") or self._story_export_story_id() or "story")
        return {
            "package_schema_version": 1,
            "addon_id": "nc.multi_persona_roleplay",
            "addon_version": addon_version,
            "exported_at": QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate),
            "story_title": str(story.get("title") or story_id).strip() or story_id,
            "story_id": story_id,
            "included_sections": list(included_sections or []),
            "asset_file_map": copy.deepcopy(asset_file_map),
            "warnings": list(warnings or []),
            "source_paths": {
                key: str(value.get("source_path") or "")
                for key, value in asset_file_map.items()
                if isinstance(value, dict) and str(value.get("source_path") or "").strip()
            },
        }

    def _story_package_persona_payloads(
        self,
        personas: list[PersonaConfig],
        sections: set[str],
        voice_asset_paths: dict[str, str],
        avatar_asset_paths: dict[str, str] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
        include_visual = "persona_visual" in sections
        include_voice = "persona_voice" in sections
        avatar_asset_paths = dict(avatar_asset_paths or {})
        personas_payload: list[dict[str, Any]] = []
        visual_settings: dict[str, Any] = {}
        voice_settings: dict[str, Any] = {}
        for persona in list(personas or []):
            payload = persona.to_dict()
            visual_payload = copy.deepcopy(payload.get("visual") or {})
            voice_payload = copy.deepcopy(payload.get("voice") or {})
            avatar_asset_path = str(avatar_asset_paths.get(persona.id, "") or "")
            asset_path = voice_asset_paths.get(persona.id, "")
            if asset_path:
                voice_payload["sample_path"] = asset_path
            elif str(voice_payload.get("sample_path") or "").strip():
                voice_payload["sample_path"] = ""
            if include_visual:
                visual_settings[persona.id] = {
                    "visual": visual_payload,
                    "character_image_path": avatar_asset_path,
                }
            else:
                payload.pop("visual", None)
            payload["character_image_path"] = avatar_asset_path
            if include_voice:
                voice_settings[persona.id] = voice_payload
                payload["voice"] = voice_payload
            else:
                payload.pop("voice", None)
            personas_payload.append(payload)
        return personas_payload, visual_settings, voice_settings

    def _story_package_audiofx_payload(
        self,
        sections: set[str],
        audiofx_asset_paths: dict[str, str],
    ) -> dict[str, Any]:
        items = []
        for item in self._audiofx_items():
            payload = dict(item)
            key = str(payload.get("id") or self._audio_file_key(payload.get("file_path", "")) or "").strip()
            asset_path = audiofx_asset_paths.get(key, "")
            if asset_path:
                payload["file_path"] = asset_path
            elif str(payload.get("file_path") or "").strip():
                payload["file_path"] = ""
            items.append(payload)
        available = []
        for item in self.available_story_audio_files():
            payload = dict(item)
            key = str(payload.get("source_audiofx_id") or payload.get("id") or self._audio_file_key(payload.get("file_path", "")) or "").strip()
            asset_path = audiofx_asset_paths.get(key, "")
            if asset_path:
                payload["file_path"] = asset_path
                payload["ready"] = True
            elif str(payload.get("file_path") or "").strip():
                payload["file_path"] = ""
                payload["ready"] = False
            available.append(payload)
        return {
            "items": items,
            "available_audio_files": available,
            "saved_audio_prompts": copy.deepcopy(list(self.settings.get("saved_audio_prompts") or [])),
            "story_sounds_enabled": bool(self.settings.get("story_sounds_enabled", True)),
            "audiofx_volume": self.settings.get("audiofx_volume"),
        }

    def _write_story_package(self, path: str | Path, sections: list[str] | None = None) -> tuple[dict[str, Any], list[str]]:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        selected = list(sections or self._story_export_selected_sections())
        section_set = set(selected)
        story = self._story_export_story_payload()
        story_id = self.storage.story_id(story.get("id") or self._story_export_story_id() or "story")
        if not story:
            story = self._current_master_story_snapshot()
        personas = self._story_export_persona_configs(story)
        warnings: list[str] = []
        asset_file_map: dict[str, Any] = {}
        used_assets: set[str] = set()
        voice_asset_paths: dict[str, str] = {}
        avatar_asset_paths: dict[str, str] = {}
        audiofx_asset_paths: dict[str, str] = {}
        voice_asset_sources: list[tuple[str, str, str]] = []
        avatar_asset_sources: list[tuple[str, str, str]] = []
        audio_asset_sources: list[tuple[str, str, str]] = []

        if "voice_assets" in section_set:
            for persona in personas:
                sample_path = str(getattr(getattr(persona, "voice", None), "sample_path", "") or "").strip()
                if not sample_path:
                    continue
                source = Path(sample_path)
                if source.exists() and source.is_file():
                    asset_path = self._story_package_unique_asset_path("voices", persona.id, source, used_assets)
                    voice_asset_paths[persona.id] = asset_path
                    voice_asset_sources.append((f"voice:{persona.id}", sample_path, asset_path))
                else:
                    warnings.append(f"Missing voice sample for {persona.display_name}: {sample_path}")

        if "avatar_assets" in section_set:
            for persona in personas:
                image_path = str(getattr(persona, "character_image_path", "") or "").strip()
                if not image_path:
                    continue
                source = Path(image_path)
                if source.exists() and source.is_file():
                    asset_path = self._story_package_unique_asset_path("visuals", persona.id, source, used_assets)
                    avatar_asset_paths[persona.id] = asset_path
                    avatar_asset_sources.append((f"avatar:{persona.id}", image_path, asset_path))
                else:
                    warnings.append(f"Missing avatar image for {persona.display_name}: {image_path}")

        if "audiofx_assets" in section_set:
            for item in self._audiofx_items():
                file_path = str(item.get("file_path") or "").strip()
                if not file_path:
                    continue
                source = Path(file_path)
                key = str(item.get("id") or self._audio_file_key(file_path) or source.stem).strip()
                if source.exists() and source.is_file():
                    asset_path = self._story_package_unique_asset_path("audiofx", key, source, used_assets)
                    audiofx_asset_paths[key] = asset_path
                    audio_asset_sources.append((f"audiofx:{key}", file_path, asset_path))
                else:
                    warnings.append(f"Missing AudioFX file for {item.get('description') or key}: {file_path}")

        personas_payload, visual_settings, voice_settings = self._story_package_persona_payloads(personas, section_set, voice_asset_paths, avatar_asset_paths)
        package_story = self._story_package_scrub_runtime_paths(story)
        json_files: dict[str, Any] = {}
        if "story_setup" in section_set:
            json_files["session.json"] = self.session.to_dict()
        if "story_metadata" in section_set:
            json_files["story.json"] = package_story
        if "personas" in section_set:
            json_files["personas.json"] = personas_payload
        if "persona_visual" in section_set:
            json_files["persona_visual_settings.json"] = visual_settings
        if "avatar_assets" in section_set:
            json_files["avatar_images.json"] = {
                persona.id: {
                    "display_name": persona.display_name,
                    "character_image_path": avatar_asset_paths.get(persona.id, ""),
                }
                for persona in personas
                if avatar_asset_paths.get(persona.id)
            }
        if "persona_voice" in section_set:
            json_files["persona_voice_settings.json"] = voice_settings
        if "story_memory" in section_set:
            memory = self.storage.load_story_memory(story_id) if story_id else {}
            if not memory:
                try:
                    memory = self.long_memory.load()
                except Exception:
                    memory = {}
            json_files["story_memory.json"] = self._story_package_scrub_runtime_paths(memory if isinstance(memory, dict) else {})
        if "story_events" in section_set:
            ar_state = getattr(self.session, "ar_state", None)
            json_files["story_events.json"] = {
                "story_event_log": copy.deepcopy(list(self._story_event_log or [])),
                "session_recent_events": list(getattr(self.session, "recent_events", []) or []),
                "ar_recent_events": list(getattr(ar_state, "recent_events", []) or []),
            }
        if "audiofx" in section_set:
            json_files["audiofx.json"] = self._story_package_audiofx_payload(section_set, audiofx_asset_paths)
        if "visual_styles" in section_set:
            json_files["visual_styles.json"] = self._story_export_visual_styles_for_personas(personas)
        if "master_story" in section_set:
            json_files["master_story.json"] = {
                "draft": self._story_package_scrub_runtime_paths(self._master_story_draft if isinstance(self._master_story_draft, dict) else {}),
                "active_story": package_story,
                "generation_constraints": self._master_story_generation_constraints(),
            }
        if "templates" in section_set:
            json_files["templates.json"] = self._story_export_templates_payload()

        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as handle:
            for asset_key, source_path, asset_path in voice_asset_sources + avatar_asset_sources + audio_asset_sources:
                self._copy_package_asset(handle, source_path, asset_path, asset_key, asset_file_map, warnings)
            manifest = self._build_story_package_manifest(
                story=story,
                included_sections=selected,
                asset_file_map=asset_file_map,
                warnings=warnings,
            )
            handle.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=True))
            for file_name, payload in json_files.items():
                handle.writestr(file_name, json.dumps(payload, indent=2, ensure_ascii=True))
        return manifest, warnings

    def _export_story_package(self):
        story_id = self._story_export_story_id() or "mprc_story"
        default_path = Path.home() / f"{story_id}.mprcstory.zip"
        path = self._save_file(
            "Export Story Library package",
            str(default_path),
            "MPRC story packages (*.mprcstory.zip *.storypackage.zip);;Zip files (*.zip)",
        )
        if not path:
            self._set_master_story_status("Story Library Export cancelled.")
            return
        if not str(path).lower().endswith((".mprcstory.zip", ".storypackage.zip", ".zip")):
            path = str(path) + ".mprcstory.zip"
        try:
            manifest, warnings = self._write_story_package(path, self._story_export_selected_sections())
        except Exception as exc:
            self._warn("Story Library Export", f"Export failed:\n\n{exc}")
            self._set_master_story_status(f"Story Library Export failed: {exc}")
            return
        warning_note = f" with {len(warnings)} warning{'s' if len(warnings) != 1 else ''}" if warnings else ""
        self._record_story_event(f"exported story library package: {path}{warning_note}", severity="info", kind="package", persist=True)
        self._set_master_story_status(f"Exported Story Library package '{manifest.get('story_title')}' to {path}{warning_note}.")
        self._refresh_story_export_card()

    def _read_package_json(self, zip_handle: zipfile.ZipFile, file_name: str, fallback: Any) -> Any:
        try:
            if file_name not in zip_handle.namelist():
                return fallback
            return json.loads(zip_handle.read(file_name).decode("utf-8"))
        except Exception:
            return fallback

    def _read_story_package_manifest(self, path: str | Path) -> tuple[dict[str, Any], list[str]]:
        warnings: list[str] = []
        try:
            with zipfile.ZipFile(path, "r") as handle:
                manifest = self._read_package_json(handle, "manifest.json", {})
        except Exception as exc:
            raise ValueError(f"Could not open story package: {exc}") from exc
        if not isinstance(manifest, dict) or not manifest:
            raise ValueError("Package is missing manifest.json.")
        try:
            schema_version = int(manifest.get("package_schema_version", 0) or 0)
        except Exception:
            schema_version = 0
        if schema_version < 1:
            raise ValueError("Package manifest has no supported schema version.")
        if schema_version > 1:
            warnings.append(f"Package schema {schema_version} is newer than this addon; importing with v1 fallback.")
        if str(manifest.get("addon_id") or "") not in {"", "nc.multi_persona_roleplay"}:
            warnings.append(f"Package addon id is {manifest.get('addon_id')}; expected nc.multi_persona_roleplay.")
        return manifest, warnings

    def _confirm_story_package_import(self, manifest: dict[str, Any], warnings: list[str]) -> bool:
        parent = self._widget.window() if self._widget is not None else None
        sections = ", ".join(str(item) for item in list(manifest.get("included_sections") or [])) or "none"
        message = (
            f"Import story package '{manifest.get('story_title') or manifest.get('story_id') or 'Untitled'}'?\n\n"
            f"Included sections: {sections}\n"
            f"Assets: {len(dict(manifest.get('asset_file_map') or {}))}\n"
            "A recovery backup will be saved before applying the package."
        )
        if warnings:
            message += "\n\nWarnings:\n" + "\n".join(f"- {item}" for item in warnings[:8])
        answer = QtWidgets.QMessageBox.question(parent, "Import Story Library Package", message)
        return answer == QtWidgets.QMessageBox.Yes

    def _import_story_package(self):
        path = self._open_file(
            "Import Story Library package",
            str(Path.home()),
            "MPRC story packages (*.mprcstory.zip *.storypackage.zip);;Zip files (*.zip)",
        )
        if not path:
            self._set_master_story_status("Story Library Import cancelled.")
            return
        try:
            manifest, warnings = self._read_story_package_manifest(path)
        except Exception as exc:
            self._warn("Story Library Import", str(exc))
            self._set_master_story_status(f"Story Library Import failed: {exc}")
            return
        all_warnings = warnings + [str(item) for item in list(manifest.get("warnings") or []) if str(item or "").strip()]
        if not self._confirm_story_package_import(manifest, all_warnings):
            self._set_master_story_status("Story Library Import cancelled.")
            return
        try:
            result = self._apply_story_package(path, manifest=manifest)
        except Exception as exc:
            self._warn("Story Library Import", f"Import failed:\n\n{exc}")
            self._set_master_story_status(f"Story Library Import failed: {exc}")
            return
        warnings = list(result.get("warnings") or [])
        story_title = str(result.get("story_title") or result.get("story_id") or "story").strip()
        warning_note = f" with {len(warnings)} warning{'s' if len(warnings) != 1 else ''}" if warnings else ""
        self._record_story_event(f"imported story library package: {path}{warning_note}", severity="info", kind="package", persist=True)
        self.refresh_ui()
        self._set_master_story_status(f"Imported Story Library package '{story_title}'{warning_note}.")

    def _story_package_import_asset_root(self, manifest: dict[str, Any]) -> Path:
        story_id = self.storage.story_id((manifest or {}).get("story_id") or (manifest or {}).get("story_title") or "imported_story")
        return self.context.storage.resolve(f"assets/story_packages/imported/{story_id}")

    def _extract_package_assets(self, zip_handle: zipfile.ZipFile, manifest: dict[str, Any], warnings: list[str]) -> dict[str, str]:
        asset_file_map = manifest.get("asset_file_map")
        if not isinstance(asset_file_map, dict) or not asset_file_map:
            return {}
        root = self._story_package_import_asset_root(manifest)
        extracted: dict[str, str] = {}
        names = set(zip_handle.namelist())
        for asset_key, item in asset_file_map.items():
            if not isinstance(item, dict):
                continue
            asset_path = str(item.get("asset_path") or "").replace("\\", "/").strip()
            if not asset_path or asset_path.startswith("/") or ".." in Path(asset_path).parts:
                warnings.append(f"Skipped unsafe asset path for {asset_key}: {asset_path}")
                continue
            if asset_path not in names:
                warnings.append(f"Package asset missing for {asset_key}: {asset_path}")
                continue
            if asset_path.startswith("assets/voices/"):
                folder = "voices"
            elif asset_path.startswith("assets/audiofx/"):
                folder = "audiofx"
            elif asset_path.startswith("assets/visuals/"):
                folder = "visuals"
            else:
                folder = "misc"
            target = root / folder / self._story_package_safe_name(Path(asset_path).name, "asset")
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zip_handle.read(asset_path))
                extracted[asset_path] = str(target)
            except Exception as exc:
                warnings.append(f"Could not extract {asset_path}: {exc}")
        return extracted

    def _remap_imported_asset_paths(self, value: Any, extracted_assets: dict[str, str]) -> Any:
        if isinstance(value, str):
            return extracted_assets.get(value, value)
        if isinstance(value, list):
            return [self._remap_imported_asset_paths(item, extracted_assets) for item in value]
        if isinstance(value, dict):
            return {key: self._remap_imported_asset_paths(item, extracted_assets) for key, item in value.items()}
        return value

    def _remap_persona_id_value(self, value: Any, id_map: dict[str, str]) -> Any:
        normalized = normalize_persona_id(value)
        return id_map.get(normalized, value)

    def _remap_story_payload_persona_ids(self, payload: dict[str, Any], id_map: dict[str, str]) -> dict[str, Any]:
        story = copy.deepcopy(dict(payload or {}))
        if not id_map:
            return story
        for key in ("narrator_persona_id", "active_persona_id", "current_speaker_id"):
            if key in story:
                story[key] = self._remap_persona_id_value(story.get(key), id_map)
        session = dict(story.get("session") or {}) if isinstance(story.get("session"), dict) else {}
        for key in ("narrator_persona_id", "active_persona_id", "current_speaker_id"):
            if key in session:
                session[key] = self._remap_persona_id_value(session.get(key), id_map)
        ar_state = dict(session.get("ar_state") or {}) if isinstance(session.get("ar_state"), dict) else {}
        if isinstance(ar_state.get("active_characters"), list):
            ar_state["active_characters"] = [self._remap_persona_id_value(item, id_map) for item in ar_state.get("active_characters") or []]
        session["ar_state"] = ar_state
        if session:
            story["session"] = session
        personas = []
        for item in list(story.get("personas") or []):
            if isinstance(item, dict):
                persona = dict(item)
                old_id = normalize_persona_id(persona.get("id") or persona.get("display_name"))
                if old_id in id_map:
                    persona["id"] = id_map[old_id]
                personas.append(persona)
        if personas:
            story["personas"] = personas
        overrides = story.get("persona_overrides")
        if isinstance(overrides, dict):
            remapped = {}
            for key, value in overrides.items():
                remapped[str(self._remap_persona_id_value(key, id_map))] = copy.deepcopy(value)
            story["persona_overrides"] = remapped
        return story

    def _remap_story_memory_persona_ids(self, payload: dict[str, Any], id_map: dict[str, str], story_id: str) -> dict[str, Any]:
        memory = copy.deepcopy(dict(payload or {}))
        memory["story_id"] = story_id
        if not id_map:
            return memory
        session = memory.get("session")
        if isinstance(session, dict):
            remapped_story = self._remap_story_payload_persona_ids({"session": session}, id_map)
            memory["session"] = remapped_story.get("session", session)
        settings = memory.get("settings")
        if isinstance(settings, dict):
            for key in ("narrator_persona_id",):
                if key in settings:
                    settings[key] = self._remap_persona_id_value(settings.get(key), id_map)
            for key in ("master_story_linked_persona_ids", "master_story_created_persona_ids"):
                if isinstance(settings.get(key), list):
                    settings[key] = [self._remap_persona_id_value(item, id_map) for item in settings.get(key) or []]
            overrides = settings.get("master_story_persona_overrides")
            if isinstance(overrides, dict):
                settings["master_story_persona_overrides"] = {
                    str(self._remap_persona_id_value(key, id_map)): copy.deepcopy(value)
                    for key, value in overrides.items()
                }
        long_memory = memory.get("long_memory")
        if isinstance(long_memory, dict):
            for key in ("character_memory",):
                value = long_memory.get(key)
                if isinstance(value, dict):
                    long_memory[key] = {
                        str(self._remap_persona_id_value(persona_id, id_map)): copy.deepcopy(item)
                        for persona_id, item in value.items()
                    }
            active = long_memory.get("active_character_ids")
            if isinstance(active, list):
                long_memory["active_character_ids"] = [self._remap_persona_id_value(item, id_map) for item in active]
        return memory

    def _unique_story_id(self, story_id: str) -> str:
        base = self.storage.story_id(story_id or "imported_story")
        existing = {str(item.get("id") or "").strip() for item in self.storage.load_story_index()}
        if base not in existing:
            return base
        candidate = f"{base}_imported"
        counter = 2
        while candidate in existing:
            candidate = f"{base}_imported_{counter}"
            counter += 1
        return candidate

    def _apply_imported_personas(self, payload: Any, warnings: list[str]) -> dict[str, str]:
        imported = personas_from_payload(payload)
        if not imported:
            return {}
        existing_ids = {persona.id for persona in self.personas}
        id_map: dict[str, str] = {}
        for persona in imported:
            original_id = persona.id
            if persona.id in existing_ids:
                persona.id = unique_persona_id(f"{persona.id}_imported", existing_ids)
                if "(Imported)" not in persona.display_name:
                    persona.display_name = f"{persona.display_name} (Imported)"
                warnings.append(f"Persona id '{original_id}' already existed; imported as '{persona.id}'.")
            id_map[original_id] = persona.id
            existing_ids.add(persona.id)
            self.personas.append(persona)
        return id_map

    def _apply_imported_voice_settings(self, payload: Any, id_map: dict[str, str]) -> None:
        if not isinstance(payload, dict):
            return
        by_id = {persona.id: persona for persona in self.personas}
        for key, voice in payload.items():
            persona_id = str(self._remap_persona_id_value(key, id_map))
            persona = by_id.get(persona_id)
            if persona is None or not isinstance(voice, dict):
                continue
            updated = PersonaConfig.from_dict({**persona.to_dict(), "voice": voice})
            persona.voice = updated.voice

    def _apply_imported_visual_settings(self, payload: Any, id_map: dict[str, str]) -> None:
        if not isinstance(payload, dict):
            return
        by_id = {persona.id: persona for persona in self.personas}
        for key, visual_payload in payload.items():
            persona_id = str(self._remap_persona_id_value(key, id_map))
            persona = by_id.get(persona_id)
            if persona is None or not isinstance(visual_payload, dict):
                continue
            merged = persona.to_dict()
            if isinstance(visual_payload.get("visual"), dict):
                merged["visual"] = visual_payload.get("visual")
            if "character_image_path" in visual_payload:
                merged["character_image_path"] = str(visual_payload.get("character_image_path") or "")
            updated = PersonaConfig.from_dict(merged)
            persona.visual = updated.visual
            persona.character_image_path = updated.character_image_path

    def _apply_imported_avatar_images(self, payload: Any, id_map: dict[str, str]) -> None:
        if not isinstance(payload, dict):
            return
        by_id = {persona.id: persona for persona in self.personas}
        for key, item in payload.items():
            persona_id = str(self._remap_persona_id_value(key, id_map))
            persona = by_id.get(persona_id)
            if persona is None:
                continue
            image_path = ""
            if isinstance(item, dict):
                image_path = str(item.get("character_image_path") or "").strip()
            elif isinstance(item, str):
                image_path = str(item or "").strip()
            if image_path:
                persona.character_image_path = image_path

    def _merge_imported_audiofx(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        imported_items = [dict(item) for item in list(payload.get("items") or []) if isinstance(item, dict)]
        if not imported_items:
            return
        existing = self._audiofx_items()
        existing_ids = {str(item.get("id") or "").strip() for item in existing}
        merged = list(existing)
        for item in imported_items:
            base = str(item.get("id") or self._new_audiofx_id(merged)).strip() or self._new_audiofx_id(merged)
            item_id = base
            counter = 2
            while item_id in existing_ids:
                item_id = f"{base}_imported_{counter}"
                counter += 1
            item["id"] = item_id
            existing_ids.add(item_id)
            merged.append(item)
        if "story_sounds_enabled" in payload:
            self.settings["story_sounds_enabled"] = bool(payload.get("story_sounds_enabled"))
        if payload.get("audiofx_volume") is not None:
            self.settings["audiofx_volume"] = payload.get("audiofx_volume")
        saved = payload.get("saved_audio_prompts")
        if isinstance(saved, list) and saved:
            current = [item for item in list(self.settings.get("saved_audio_prompts") or []) if isinstance(item, dict)]
            current.extend(dict(item) for item in saved if isinstance(item, dict))
            self.settings["saved_audio_prompts"] = current[-100:]
        self._save_audiofx_items(merged)

    def _merge_imported_visual_styles(self, payload: Any) -> None:
        if not isinstance(payload, list):
            return
        current = [dict(item) for item in list(self.visual_styles or []) if isinstance(item, dict)]
        seen = {str(item.get("id") or "").strip() for item in current}
        changed = False
        for item in payload:
            if not isinstance(item, dict):
                continue
            style_id = str(item.get("id") or "").strip()
            if not style_id or style_id in seen:
                continue
            current.append(dict(item))
            seen.add(style_id)
            changed = True
        if changed:
            self.visual_styles = current
            self.storage._write_json("visual_styles.json", current)

    def _merge_imported_templates(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        templates = payload.get("roleplay_templates")
        if isinstance(templates, dict):
            current = self.storage._read_json("roleplay_templates.json", {})
            current = dict(current or {}) if isinstance(current, dict) else {}
            changed = False
            for key, value in templates.items():
                if key not in current:
                    current[key] = copy.deepcopy(value)
                    changed = True
            if changed:
                self.storage._write_json("roleplay_templates.json", current)
        saved = payload.get("saved_audio_prompts")
        if isinstance(saved, list) and saved:
            current = [item for item in list(self.settings.get("saved_audio_prompts") or []) if isinstance(item, dict)]
            current.extend(dict(item) for item in saved if isinstance(item, dict))
            self.settings["saved_audio_prompts"] = current[-100:]

    def _apply_story_package(self, path: str | Path, *, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
        warnings: list[str] = []
        if manifest is None:
            manifest, manifest_warnings = self._read_story_package_manifest(path)
            warnings.extend(manifest_warnings)
        warnings.extend(str(item) for item in list((manifest or {}).get("warnings") or []) if str(item or "").strip())
        included = {str(item or "").strip() for item in list((manifest or {}).get("included_sections") or []) if str(item or "").strip()}
        self._save_pre_apply_backup("Import Story Library Package")
        with zipfile.ZipFile(path, "r") as handle:
            extracted_assets = self._extract_package_assets(handle, manifest or {}, warnings)
            story_payload = self._remap_imported_asset_paths(self._read_package_json(handle, "story.json", {}), extracted_assets)
            session_payload = self._remap_imported_asset_paths(self._read_package_json(handle, "session.json", {}), extracted_assets)
            personas_payload = self._remap_imported_asset_paths(self._read_package_json(handle, "personas.json", []), extracted_assets)
            voice_payload = self._remap_imported_asset_paths(self._read_package_json(handle, "persona_voice_settings.json", {}), extracted_assets)
            visual_payload = self._remap_imported_asset_paths(self._read_package_json(handle, "persona_visual_settings.json", {}), extracted_assets)
            avatar_payload = self._remap_imported_asset_paths(self._read_package_json(handle, "avatar_images.json", {}), extracted_assets)
            memory_payload = self._remap_imported_asset_paths(self._read_package_json(handle, "story_memory.json", {}), extracted_assets)
            events_payload = self._read_package_json(handle, "story_events.json", {})
            audiofx_payload = self._remap_imported_asset_paths(self._read_package_json(handle, "audiofx.json", {}), extracted_assets)
            visual_styles_payload = self._read_package_json(handle, "visual_styles.json", [])
            master_story_payload = self._remap_imported_asset_paths(self._read_package_json(handle, "master_story.json", {}), extracted_assets)
            templates_payload = self._read_package_json(handle, "templates.json", {})

        id_map: dict[str, str] = {}
        if "personas" in included:
            id_map = self._apply_imported_personas(personas_payload, warnings)
        if "persona_voice" in included:
            self._apply_imported_voice_settings(voice_payload, id_map)
        if "persona_visual" in included:
            self._apply_imported_visual_settings(visual_payload, id_map)
        if "avatar_assets" in included:
            self._apply_imported_avatar_images(avatar_payload, id_map)

        story_id = ""
        story_title = str((manifest or {}).get("story_title") or "").strip()
        if "story_metadata" in included and isinstance(story_payload, dict) and story_payload:
            story = self._remap_story_payload_persona_ids(story_payload, id_map)
            original_story_id = self.storage.story_id(story.get("id") or (manifest or {}).get("story_id") or "imported_story")
            story_id = self._unique_story_id(original_story_id)
            if story_id != original_story_id:
                warnings.append(f"Story id '{original_story_id}' already existed; imported as '{story_id}'.")
            story["id"] = story_id
            story_title = str(story.get("title") or story_title or story_id).strip()
            story["updated_at"] = QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate)
            self.storage.save_story(story)
            self.settings["last_master_story_id"] = story_id
            self.settings["last_master_story_title"] = story_title or story_id
            self._master_story_draft = copy.deepcopy(story)

        if "story_setup" in included and isinstance(session_payload, dict) and session_payload:
            session_story = self._remap_story_payload_persona_ids({"session": session_payload}, id_map)
            self.session = RoleplaySessionState.from_dict(session_story.get("session") or session_payload)
            self.session.enabled = True
            self._ensure_session_persona()

        if "story_memory" in included and isinstance(memory_payload, dict) and memory_payload:
            target_story_id = story_id or self._unique_story_id(str((manifest or {}).get("story_id") or "imported_story"))
            memory = self._remap_story_memory_persona_ids(memory_payload, id_map, target_story_id)
            self.storage.save_story_memory(target_story_id, memory)
            if isinstance(memory.get("long_memory"), dict):
                self.long_memory.save(memory.get("long_memory"))
            self.settings["last_master_story_id"] = target_story_id
            if story_title:
                self.settings["last_master_story_title"] = story_title

        if "story_events" in included and isinstance(events_payload, dict):
            imported_events = [item for item in list(events_payload.get("story_event_log") or []) if isinstance(item, dict)]
            if imported_events:
                self._story_event_log = (self._story_event_log + imported_events)[-80:]
                self.settings["story_event_log"] = list(self._story_event_log)

        if "audiofx" in included:
            self._merge_imported_audiofx(audiofx_payload)
        if "visual_styles" in included:
            self._merge_imported_visual_styles(visual_styles_payload)
        if "templates" in included:
            self._merge_imported_templates(templates_payload)
        if "master_story" in included and isinstance(master_story_payload, dict):
            draft = master_story_payload.get("draft")
            active_story = master_story_payload.get("active_story")
            if isinstance(draft, dict) and draft:
                self._master_story_draft = self._remap_story_payload_persona_ids(draft, id_map)
            elif isinstance(active_story, dict) and active_story:
                self._master_story_draft = self._remap_story_payload_persona_ids(active_story, id_map)

        self.storage.save_settings(self.settings)
        self.save_state()
        self._populate_master_stories()
        self._story_audio_block_active = False
        self._story_audio_pending_text = ""
        self._last_story_audio_cues.clear()
        return {
            "story_id": story_id or self.settings.get("last_master_story_id") or (manifest or {}).get("story_id") or "",
            "story_title": story_title or self.settings.get("last_master_story_title") or (manifest or {}).get("story_title") or "",
            "warnings": warnings,
        }

    def _export_story_bundle(self):
        story_id = self._current_story_id() or "mprc_story"
        path = self._save_file("Export MPRC story bundle", str(Path.home() / f"{story_id}.mprc_story_bundle.json"), "MPRC story bundles (*.json)")
        if not path:
            return
        bundle = self._build_story_bundle()
        Path(path).write_text(json.dumps(bundle, indent=2, ensure_ascii=True), encoding="utf-8")
        self._record_story_event(f"exported story bundle: {path}", severity="info", kind="bundle", persist=True)
        self._set_master_story_status(f"Exported story bundle to {path}.")

    def _import_story_bundle(self):
        path = self._open_file("Import MPRC story bundle", str(Path.home()), "MPRC story bundles (*.json)")
        if not path:
            return
        try:
            bundle = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            self._warn("Import Story Bundle", f"Could not read bundle:\n\n{exc}")
            return
        if not isinstance(bundle, dict) or str(bundle.get("bundle_type") or "") != "mprc_story_bundle":
            self._warn("Import Story Bundle", "This file is not an MPRC story bundle.")
            return
        try:
            schema_version = int(bundle.get("schema_version", 1) or 1)
        except Exception:
            schema_version = 1
        if schema_version > 1:
            self._record_story_event(f"bundle schema {schema_version} loaded with v1 fallback", severity="warning", kind="schema", persist=True)
        self._save_pre_apply_backup("Import Story Bundle")
        imported = personas_from_payload(bundle.get("personas"))
        by_id = {persona.id: persona for persona in self.personas}
        for persona in imported:
            by_id[persona.id] = persona
        self.personas = list(by_id.values())
        story = self.storage._migrate_story_payload(dict(bundle.get("story") or {}), str(bundle.get("story_id") or "imported_story"))
        if not story:
            self._warn("Import Story Bundle", "The bundle did not contain a valid story payload.")
            return
        story_id = self.storage.save_story(story)
        settings = bundle.get("settings") if isinstance(bundle.get("settings"), dict) else {}
        for key, value in settings.items():
            if key in self._story_bundle_settings() or key in {
                "last_master_story_id",
                "last_master_story_title",
                "master_story_linked_persona_ids",
                "master_story_created_persona_ids",
                "master_story_persona_overrides",
                "master_story_avatar_style_sheets",
                "persona_avatar_style_sheets",
                "narrator_persona_id",
                "narrator_persona_mode",
                "story_sounds_enabled",
                "audio_fx_items",
                "available_audio_files",
                "saved_audio_prompts",
                "audiofx_volume",
                "audiofx_test_mode",
            }:
                if key == "persona_avatar_style_sheets":
                    self._merge_story_avatar_style_sheet_settings(value)
                else:
                    self.settings[key] = copy.deepcopy(value)
        self.settings["last_master_story_id"] = story_id
        self.settings["last_master_story_title"] = story.get("title") or story_id
        memory = bundle.get("memory_snapshot")
        if isinstance(memory, dict) and memory:
            memory = dict(memory)
            memory["story_id"] = story_id
            self.storage.save_story_memory(story_id, memory)
        prompts = bundle.get("prompts") if isinstance(bundle.get("prompts"), dict) else {}
        draft = prompts.get("master_story_draft")
        self._master_story_draft = copy.deepcopy(draft) if isinstance(draft, dict) else story
        self._apply_master_story_payload(story, apply_plan={"clear_memory": True, "auto_create": False, "skip_backup": True})
        self._restore_story_memory_snapshot(story_id)
        self.storage.save_settings(self.settings)
        self.save_state()
        self._populate_master_stories()
        self._record_story_event(f"imported story bundle: {path}", severity="info", kind="bundle", persist=True)
        self.refresh_ui()
        self._set_master_story_status(f"Imported story bundle '{story.get('title') or story_id}'.")

    def _test_narrator_voice_from_status(self):
        narrator = self.selected_narrator_persona()
        if narrator is None:
            self._warn("Test Narrator Voice", "No narrator persona is selected or available.")
            self._record_story_event("voice test skipped: missing narrator", severity="warning", kind="voice", persist=True)
            return
        self._queue_story_voice_test(narrator, "[NARRATOR]", "narrator")

    def _test_selected_character_voice_from_status(self):
        narrator_id = self.selected_narrator_persona_id()
        persona = self.active_persona()
        if persona is not None and persona.id == narrator_id:
            linked = [self.persona_by_id(item) for item in self._current_linked_persona_ids()]
            persona = next((item for item in linked if item is not None and item.id != narrator_id), persona)
        if persona is None:
            self._warn("Test Character Voice", "No character persona is available.")
            return
        self._queue_story_voice_test(persona, f"[CHARACTER: {persona.display_name}]", "character")

    def _queue_story_voice_test(self, persona: PersonaConfig, label: str, kind: str) -> None:
        route = self.voice_router.effective_voice_config({
            "persona_id": persona.id,
            "tts_backend": self.current_tts_backend(),
            "text": f"{label}\nVoice route test.",
        })
        sample = str(route.get("sample_path") or "").strip()
        if not sample:
            self._record_story_event(f"voice test queued with warning for {persona.display_name}: {route.get('warning') or 'no sample'}", severity="warning", kind="voice", persist=True)
        message = (
            "Voice route test. Reply with exactly these two lines and no extra text:\n"
            f"{label}\n"
            f"{kind.capitalize()} voice route test."
        )
        queued = self._queue_continue_story(message)
        if queued:
            self._set_master_story_status(f"Queued {kind} voice test for {persona.display_name}.")

    def _test_visual_reply_from_status(self):
        persona = self.active_persona()
        narrator_id = self.selected_narrator_persona_id()
        if persona is not None and persona.id == narrator_id:
            linked = [self.persona_by_id(item) for item in self._current_linked_persona_ids()]
            persona = next((item for item in linked if item is not None and item.id != narrator_id and item.visual.enabled), persona)
        if persona is None:
            self._warn("Test Visual Reply", "No persona is available for Visual Reply.")
            return
        self._debug_visual_prompt = json.dumps(
            {"queued": True, "message": "Visual Reply test queued for a background worker.", "persona_id": persona.id},
            indent=2,
            ensure_ascii=True,
        )
        self._refresh_debug()
        self._record_story_event(
            f"visual test queued for {persona.display_name}",
            severity="info",
            kind="visual",
            persist=True,
        )
        self._set_master_story_status(f"Queued Visual Reply test for {persona.display_name}.")
        if not self._queue_visual_worker(
            "mprc_status_visual_reply",
            lambda: self._run_manual_visual_reply_request(str(persona.id or ""), kind="status_visual_reply"),
        ):
            result = {"accepted": False, "message": "Visual Reply test could not start a background worker."}
            self._on_manual_visual_finished("status_visual_reply", str(persona.id or ""), result)

    def _test_audiofx_from_status(self):
        if not self.available_story_audio_files():
            self._create_test_audiofx(show_status=False)
        entries = self.available_story_audio_files()
        cue = str((entries[0] if entries else {}).get("id") or "").strip()
        if not cue:
            self._warn("Test AudioFX", "No ready AudioFX cue is available.")
            return
        ok = self._play_story_audio_cue(cue)
        self._record_story_event(f"AudioFX test {'played' if ok else 'skipped'}: {cue}", severity="info" if ok else "warning", kind="audiofx", persist=True)
        self._set_master_story_status(f"AudioFX test {'played' if ok else 'could not play'}: {cue}.")

    def _repair_choose_narrator(self):
        narrator = self.selected_narrator_persona() or self._auto_ar_narrator_persona() or self.active_persona()
        if narrator is None:
            self._warn("Choose Narrator", "No persona is available to use as narrator.")
            return
        self.settings["narrator_persona_id"] = narrator.id
        self.settings["narrator_persona_mode"] = "explicit"
        if not self._voice_follows_active():
            self.settings["voice_edit_persona_id"] = narrator.id
        self.storage.save_settings(self.settings)
        self._persist_current_story_narrator_lock()
        self._record_story_event(f"repair: narrator locked to {narrator.display_name}", severity="info", kind="repair", persist=True)
        self.refresh_ui()
        self._validate_story_setup_to_ui()

    def _repair_browse_voice_file(self):
        persona = self.selected_narrator_persona() if self.session.mode == AR_MODE else self._selected_voice_persona()
        persona = persona or self.active_persona()
        if persona is None:
            self._warn("Browse Voice File", "No persona is available for voice repair.")
            return
        path = self._open_file("Choose voice sample", str(Path.home()), "Audio files (*.wav *.mp3 *.flac *.ogg *.m4a);;All files (*.*)")
        if not path:
            return
        persona.voice.enabled = True
        persona.voice.sample_path = path
        if persona.voice.backend not in VOICE_BACKENDS:
            persona.voice.backend = "inherit"
        if not self._voice_follows_active():
            self.settings["voice_edit_persona_id"] = persona.id
            self.storage.save_settings(self.settings)
        self.save_state()
        self._record_story_event(f"repair: voice file set for {persona.display_name}", severity="info", kind="repair", persist=True)
        self.refresh_ui()
        self._validate_story_setup_to_ui()

    def _repair_disable_missing_audiofx(self):
        items = self._audiofx_items()
        kept = [item for item in items if self._audiofx_file_ready(item)]
        removed = len(items) - len(kept)
        self._save_audiofx_items(kept)
        self._record_story_event(f"repair: disabled {removed} missing AudioFX item(s)", severity="info", kind="repair", persist=True)
        self.refresh_ui()
        self._validate_story_setup_to_ui()

    def _repair_fix_broken_image_path(self):
        persona = next(
            (
                item for item in (self.persona_by_id(pid) for pid in self._current_linked_persona_ids())
                if item is not None and str(item.character_image_path or "").strip() and not Path(str(item.character_image_path)).exists()
            ),
            None,
        ) or self.active_persona()
        if persona is None:
            self._warn("Fix Image Path", "No persona is available for image repair.")
            return
        path = self._open_file("Choose character image", str(Path.home()), "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*.*)")
        if not path:
            return
        persona.character_image_path = path
        self.save_state()
        self._record_story_event(f"repair: image path set for {persona.display_name}", severity="info", kind="repair", persist=True)
        self.refresh_ui()
        self._validate_story_setup_to_ui()

    def _repair_create_memory_snapshot(self):
        story_id = self._current_story_id()
        if not story_id:
            self._warn("Create Memory Snapshot", "No active story is loaded.")
            return
        self._save_story_memory_snapshot(story_id)
        self._record_story_event(f"repair: memory snapshot created for {story_id}", severity="info", kind="repair", persist=True)
        self.refresh_ui()
        self._validate_story_setup_to_ui()

    def _repair_relink_personas(self):
        linked = self._current_linked_persona_ids()
        known = {persona.id for persona in self.personas}
        created = []
        for persona_id in linked:
            if persona_id in known:
                continue
            display = persona_id.replace("_", " ").title()
            persona = self.ensure_persona_for_character_label(display, context_text="Created by Story Setup repair for a missing persona link.", source="repair", save=False)
            if persona is not None:
                created.append(persona.id)
                known.add(persona.id)
        if created:
            self.save_state()
        self.settings["master_story_linked_persona_ids"] = [item for item in linked if item in known] + created
        self.storage.save_settings(self.settings)
        self._record_story_event(f"repair: relinked personas, created={', '.join(created) if created else 'none'}", severity="info", kind="repair", persist=True)
        self.refresh_ui()
        self._validate_story_setup_to_ui()

    def _repair_reset_invalid_overrides(self):
        overrides = self.settings.get("master_story_persona_overrides")
        if not isinstance(overrides, dict):
            self.settings["master_story_persona_overrides"] = {}
            removed = 1
        else:
            known = {persona.id for persona in self.personas}
            clean = {key: value for key, value in overrides.items() if normalize_persona_id(key) in known and isinstance(value, dict)}
            removed = len(overrides) - len(clean)
            self.settings["master_story_persona_overrides"] = clean
        self.storage.save_settings(self.settings)
        self._persist_current_story_narrator_lock()
        self._record_story_event(f"repair: reset {removed} invalid persona override(s)", severity="info", kind="repair", persist=True)
        self.refresh_ui()
        self._validate_story_setup_to_ui()

    def _memory_payload(self) -> dict[str, Any]:
        try:
            return self.long_memory.load()
        except Exception:
            return {}

    def _refresh_memory_browser(self):
        if "story_memory_list" not in self._controls:
            return
        payload = self._memory_payload()
        pinned = self._controls.get("story_pinned_facts")
        if pinned is not None and not bool(getattr(pinned, "hasFocus", lambda: False)()):
            pinned.setPlainText("\n".join(str(item) for item in list(payload.get("pinned_facts") or [])))
        memory_list = self._controls.get("story_memory_list")
        if memory_list is None:
            return
        current_id = ""
        item = memory_list.currentItem()
        if item is not None:
            current_id = str(item.data(32) or "")
        memory_list.blockSignals(True)
        memory_list.clear()
        for event in reversed(list(payload.get("events") or [])[-80:]):
            summary = str(event.get("summary") or event.get("assistant_text") or "").strip()
            label = f"{event.get('turn_index', '')}: {summary[:180]}"
            list_item = QtWidgets.QListWidgetItem(label)
            list_item.setData(32, str(event.get("id") or ""))
            list_item.setToolTip(json.dumps(event, indent=2, ensure_ascii=True)[:2000])
            memory_list.addItem(list_item)
            if current_id and current_id == str(event.get("id") or ""):
                memory_list.setCurrentItem(list_item)
        memory_list.blockSignals(False)

    def _save_pinned_facts(self):
        widget = self._controls.get("story_pinned_facts")
        if widget is None:
            return
        lines = [line.strip() for line in str(widget.toPlainText() or "").splitlines() if line.strip()]
        payload = self._memory_payload()
        payload["pinned_facts"] = lines[:80]
        self.long_memory.save(payload)
        self.save_active_story_memory_snapshot()
        self._record_story_event(f"memory edit: saved {len(lines[:80])} pinned fact(s)", severity="info", kind="memory", persist=True)
        self._refresh_memory_browser()

    def _delete_selected_memory(self):
        memory_list = self._controls.get("story_memory_list")
        item = memory_list.currentItem() if memory_list is not None else None
        event_id = str(item.data(32) or "") if item is not None else ""
        if not event_id:
            self._warn("Delete Memory", "Select a memory item first.")
            return
        payload = self._memory_payload()
        events = [event for event in list(payload.get("events") or []) if str(event.get("id") or "") != event_id]
        payload["events"] = events
        payload["chapters"] = self.long_memory._build_chapters(events)
        payload["character_memory"] = self.long_memory._build_character_memory(events, self.story_prompt_personas())
        payload["location_memory"] = self.long_memory._build_location_memory(events)
        self.long_memory.save(payload)
        self.save_active_story_memory_snapshot()
        self._record_story_event(f"memory edit: deleted event {event_id}", severity="info", kind="memory", persist=True)
        self._refresh_memory_browser()

    def _reset_character_memory_only(self):
        payload = self._memory_payload()
        payload["character_memory"] = {}
        self.long_memory.save(payload)
        self.save_active_story_memory_snapshot()
        self._record_story_event("memory edit: reset character memory only", severity="info", kind="memory", persist=True)
        self._refresh_memory_browser()

    def _reset_story_memory_only(self):
        self._clear_story_memory_preserving_pins()
        self._record_story_event("memory edit: reset story memory only", severity="info", kind="memory", persist=True)
        self._refresh_memory_browser()
        self._refresh_reliability_panels()

    def _clear_story_memory_preserving_pins(self) -> None:
        payload = self._memory_payload()
        pinned = list(payload.get("pinned_facts") or [])
        self.long_memory.save({"pinned_facts": pinned})
        self.save_active_story_memory_snapshot()

    def _preview_next_ar_request(self):
        widget = self._controls.get("story_next_inspector")
        if widget is not None:
            widget.setPlainText(self._next_ar_request_text())
        self._record_story_event("previewed next AR request", severity="info", kind="debug", persist=False)

    def _explain_next_routing(self):
        widget = self._controls.get("story_next_inspector")
        if widget is not None:
            widget.setPlainText(self._next_routing_explanation_text())
        self._record_story_event("explained next routing", severity="info", kind="debug", persist=False)

    def _next_ar_request_text(self) -> str:
        from . import prompting

        if self.session.mode != AR_MODE:
            return "AlternativeReality mode is not active. Enable AR to preview the next AR request."
        self.ensure_ar_state("Continue")
        prompt = prompting.build_alternative_reality_prompt(
            self.story_prompt_personas(),
            self.session,
            latest_user_text="Continue",
            available_audio=self.available_story_audio_files(),
            narrator_persona_id=self.selected_narrator_persona_id(),
        )
        memory = self.long_memory.prompt_context(session=self.session, personas=self.story_prompt_personas(), query="Continue", limit=8)
        sections = [
            "Next AR request preview",
            "",
            self._next_routing_explanation_text(),
            "",
            "Prompt:",
            prompt,
        ]
        if memory:
            sections.extend(["", "Memory included:", memory])
        return "\n".join(sections)

    def _next_routing_explanation_text(self) -> str:
        narrator = self.selected_narrator_persona()
        active = self.active_persona()
        memory = self._memory_payload()
        events = len(list(memory.get("events") or []))
        pinned = len(list(memory.get("pinned_facts") or []))
        visual = active.visual if active is not None else None
        visual_status = "no active persona"
        if active is not None and visual is not None:
            visual_status = f"{active.display_name}: enabled={bool(visual.enabled)}, mode={visual.mode}, service={'ready' if self.visual_reply_service is not None else 'unavailable'}"
        audio_ready = self.available_story_audio_files()
        lines = [
            "Next routing explanation",
            f"This story uses narrator: {narrator.display_name + ' (' + narrator.id + ')' if narrator else 'none'}",
            f"Active character: {active.display_name + ' (' + active.id + ')' if active else 'none'}",
            "",
            "Voice routes:",
            self._build_voice_routing_inspector_text(),
            "",
            f"Memory included: {events} remembered event(s), {pinned} pinned fact(s)",
            f"Visual Reply trigger status: {visual_status}",
            f"AudioFX trigger status: {len(audio_ready)} ready cue(s); Story Sounds={'on' if self.story_sounds_enabled() else 'off'}",
            f"Important prompt sections: narrator role, active characters, AR state, recent events, persona roster, available audio cues, pinned/long memory",
        ]
        return "\n".join(lines)

    def _persist_current_story_narrator_lock(self):
        story_id = self._current_story_id()
        if not story_id:
            return
        payload = self.storage.load_story(story_id)
        if not isinstance(payload, dict) or not payload:
            return
        payload["narrator_persona_id"] = self.selected_narrator_persona_id()
        payload["narrator_persona_mode"] = self._narrator_selection_mode()
        session_payload = dict(payload.get("session") or {}) if isinstance(payload.get("session"), dict) else {}
        session_payload["narrator_persona_id"] = payload["narrator_persona_id"]
        session_payload["narrator_persona_mode"] = payload["narrator_persona_mode"]
        payload["session"] = session_payload
        payload["updated_at"] = QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate)
        self.storage.save_story(payload)
        self._record_story_event(f"narrator routing locked for story: {payload['narrator_persona_id'] or 'auto'}", severity="info", kind="narrator", persist=True)

    def save_active_story_memory_snapshot(self) -> None:
        story_id = str(self.settings.get("last_master_story_id") or "").strip()
        if story_id:
            self._save_story_memory_snapshot(story_id)

    def _save_story_memory_snapshot(self, story_id: str) -> None:
        normalized = self.storage.story_id(story_id)
        if not normalized:
            return
        try:
            memory = self.long_memory.load()
        except Exception:
            memory = {}
        linked_persona_ids = list(self.settings.get("master_story_linked_persona_ids") or [])
        snapshot = {
            "schema_version": RoleplayStorage.MEMORY_SCHEMA_VERSION,
            "version": 1,
            "story_id": normalized,
            "updated_at": QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate),
            "long_memory": memory if isinstance(memory, dict) else {},
            "session": self.session.to_dict(),
            "settings": {
                "last_master_story_id": self.settings.get("last_master_story_id"),
                "last_master_story_title": self.settings.get("last_master_story_title"),
                "master_story_linked_persona_ids": linked_persona_ids,
                "master_story_created_persona_ids": list(self.settings.get("master_story_created_persona_ids") or []),
                "master_story_persona_overrides": dict(self.settings.get("master_story_persona_overrides") or {}),
                "master_story_avatar_style_sheets": self.settings.get("master_story_avatar_style_sheets", False),
                "persona_avatar_style_sheets": self._story_avatar_style_sheet_settings(normalized, linked_persona_ids),
                "narrator_persona_id": self.settings.get("narrator_persona_id"),
                "narrator_persona_mode": self.settings.get("narrator_persona_mode"),
                "story_sounds_enabled": self.settings.get("story_sounds_enabled", True),
                "audio_fx_items": list(self.settings.get("audio_fx_items") or []),
                "available_audio_files": list(self.settings.get("available_audio_files") or []),
                "saved_audio_prompts": list(self.settings.get("saved_audio_prompts") or []),
                "audiofx_volume": self.settings.get("audiofx_volume"),
                "audiofx_test_mode": self.settings.get("audiofx_test_mode"),
            },
        }
        self.storage.save_story_memory(normalized, snapshot)

    def _restore_story_memory_snapshot(self, story_id: str) -> bool:
        normalized = self.storage.story_id(story_id)
        if not normalized:
            return False
        snapshot = self.storage.load_story_memory(normalized)
        if not isinstance(snapshot, dict) or not snapshot:
            self._record_story_event(f"memory not loaded: no saved snapshot for {normalized}", severity="warning", kind="memory", persist=True)
            return False
        for note in list(snapshot.get("_migration_log") or []):
            self._record_story_event(f"memory migration/fallback: {note}", severity="warning", kind="schema", persist=True)
        memory = snapshot.get("long_memory")
        if isinstance(memory, dict):
            self.long_memory.save(memory)
        session_payload = snapshot.get("session")
        if isinstance(session_payload, dict):
            self.session = RoleplaySessionState.from_dict(session_payload)
            self.session.enabled = True
            self._ensure_session_persona()
        settings = snapshot.get("settings")
        if isinstance(settings, dict):
            for key in (
                "master_story_linked_persona_ids",
                "master_story_created_persona_ids",
                "master_story_persona_overrides",
                "master_story_avatar_style_sheets",
                "persona_avatar_style_sheets",
                "narrator_persona_id",
                "narrator_persona_mode",
                "story_sounds_enabled",
                "audio_fx_items",
                "available_audio_files",
                "saved_audio_prompts",
                "audiofx_volume",
                "audiofx_test_mode",
            ):
                if key in settings:
                    if key == "persona_avatar_style_sheets":
                        self._merge_story_avatar_style_sheet_settings(settings.get(key))
                    else:
                        self.settings[key] = settings.get(key)
        self.settings["last_master_story_id"] = normalized
        title = str(self.settings.get("last_master_story_title") or "").strip()
        snapshot_title = str((settings or {}).get("last_master_story_title") or "").strip() if isinstance(settings, dict) else ""
        if snapshot_title:
            self.settings["last_master_story_title"] = snapshot_title
        elif title:
            self.settings["last_master_story_title"] = title
        self._story_audio_block_active = False
        self._story_audio_pending_text = ""
        self._last_story_audio_cues.clear()
        self.storage.save_settings(self.settings)
        self.save_state()
        self._record_story_event(f"memory loaded: restored story snapshot for {normalized}", severity="info", kind="memory", persist=True)
        return True

    def _clear_master_story_runtime_state(self, *, clear_long_memory: bool, enabled: bool) -> None:
        if clear_long_memory:
            try:
                self.long_memory.clear()
            except Exception as exc:
                logger = getattr(self.context, "logger", None)
                if logger is not None:
                    logger.warning("[MPRC] Could not clear long memory: %s", exc)
        fallback = self.session.active_persona_id if self.session.active_persona_id else (self.personas[0].id if self.personas else "mentor")
        self.session = RoleplaySessionState(
            enabled=bool(enabled),
            active_persona_id=fallback,
            current_speaker_id=fallback,
        )
        self._story_audio_block_active = False
        self._story_audio_pending_text = ""
        self._last_story_audio_cues.clear()
        self._last_tts_visual_reply_at.clear()
        self._manual_character_image_inflight.clear()
        self._tts_persona_visual_inflight.clear()
        self._tts_visual_reply_inflight.clear()
        for key in (
            "last_master_story_id",
            "last_master_story_title",
            "master_story_linked_persona_ids",
            "master_story_created_persona_ids",
            "master_story_persona_overrides",
        ):
            self.settings.pop(key, None)

    def _restart_master_story(self):
        from PySide6 import QtWidgets

        parent = self._widget.window() if self._widget is not None else None
        answer = QtWidgets.QMessageBox.question(
            parent,
            "Clear / Restart Story",
            "Clear MPRC long memory, recent scene state, current Master Story links, and the draft editor?\n\n"
            "Saved personas and saved story files will be kept.",
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return
        self._clear_master_story_runtime_state(clear_long_memory=True, enabled=False)
        self._master_story_draft = {}
        draft = self._controls.get("master_story_draft")
        if draft is not None:
            draft.clear()
        self.storage.save_settings(self.settings)
        self.save_state()
        self.refresh_ui()
        self._set_master_story_status("Restarted Master Story state. Old MPRC long memory and current scene state were cleared.")

    def _generate_master_story(self):
        if self.is_shutdown():
            return
        generate_button = self._controls.get("master_story_generate")
        if generate_button is not None and bool(generate_button.property("_mprc_in_flight")):
            return
        prompt_widget = self._controls.get("master_story_prompt")
        prompt = str(prompt_widget.toPlainText() if prompt_widget is not None else "").strip()
        if not prompt:
            self._warn("Generate Story Setup", "Add a Master Story prompt first.")
            return
        self._commit_master_story_options()
        snapshot = self._master_story_generation_snapshot(prompt)
        token = self._new_worker_token("master_story")
        if not token:
            return
        if generate_button is not None:
            generate_button.setProperty("_mprc_in_flight", True)
            generate_button.setProperty("_mprc_worker_token", token)
            generate_button.setEnabled(False)
        self._set_master_story_status("Generating story setup with the current chat provider...")

        def worker():
            error = ""
            result = ""
            try:
                result = self._generate_master_story_payload(snapshot)
            except Exception as exc:
                error = str(exc) or repr(exc)
            if not self._worker_should_emit(token):
                return
            try:
                bridge = getattr(self, "_story_bridge", None)
                if bridge is not None:
                    bridge.finished.emit(token, result, error)
                else:
                    self._cancel_worker_token(token)
            except RuntimeError:
                self._cancel_worker_token(token)

        if not self._start_daemon_worker(token, worker, name="nc-mprc-master-story"):
            if generate_button is not None:
                generate_button.setProperty("_mprc_in_flight", False)
                generate_button.setProperty("_mprc_worker_token", "")
                generate_button.setEnabled(True)

    def _master_story_generation_snapshot(self, prompt: str) -> dict[str, Any]:
        visual_direction_widget = self._controls.get("master_story_visual_direction")
        visual_direction = str(visual_direction_widget.toPlainText() if visual_direction_widget is not None else "").strip()
        constraints = self._master_story_generation_constraints()
        use_ar = self._control_checked("master_story_use_ar", True)
        with self._state_lock:
            roster = [
                {
                    "id": persona.id,
                    "display_name": persona.display_name,
                    "role": persona.role,
                    "description": str(persona.description or persona.ar_description or "")[:300],
                    "tags": list(persona.tags or []),
                }
                for persona in list(self.personas or [])
            ] if constraints["use_existing_personas"] else []
        return {
            "prompt": str(prompt or "").strip(),
            "safe_prompt": self._master_story_safety_normalized_prompt(prompt, sfw=bool(constraints.get("sfw_mode", True))),
            "visual_direction": visual_direction,
            "constraints": constraints,
            "generation_notes": self._master_story_generation_constraints_text(constraints),
            "content_safety": self._master_story_content_safety_payload(bool(constraints.get("sfw_mode", True))),
            "safety_instruction": self._master_story_safety_instruction(bool(constraints.get("sfw_mode", True))),
            "use_ar": bool(use_ar),
            "roster": roster,
        }

    def _generate_master_story_payload(self, snapshot: dict[str, Any]) -> str:
        from core.engine_access import engine_module

        snapshot = dict(snapshot or {})
        engine = engine_module()
        model_name = str(getattr(engine, "RUNTIME_CONFIG", {}).get("model_name", "") or "").strip()
        if not model_name:
            raise RuntimeError("Choose a chat model before generating a Master Story.")
        prompt = str(snapshot.get("safe_prompt") or snapshot.get("prompt") or "").strip()
        visual_direction = str(snapshot.get("visual_direction") or "").strip()
        constraints = dict(snapshot.get("constraints") or {})
        content_safety = dict(snapshot.get("content_safety") or self._master_story_content_safety_payload(bool(constraints.get("sfw_mode", True))))
        safety_instruction = str(snapshot.get("safety_instruction") or self._master_story_safety_instruction(bool(content_safety.get("sfw", True))))
        roster = list(snapshot.get("roster") or []) if constraints.get("use_existing_personas") else []
        use_ar = bool(snapshot.get("use_ar", True))
        system = (
            "You create compact JSON story setup files for NeuralCompanion's Multi Persona Roleplay addon. "
            "Return one valid canonical story JSON object only, with no markdown and no wrapper unless the user explicitly asks for an envelope. "
            "Do not append a second fallback story object. Do not repeat top-level keys. Do not overwrite a populated personas array with an empty one. "
            "Reuse existing persona IDs when the user's requested character clearly matches an existing persona and existing-persona reuse is enabled. "
            "Create new persona objects only when needed. Keep all content fictional, consensual, adult-safe, and respectful of user agency. "
            f"{safety_instruction} "
            "Do not use DnD/tabletop rules, "
            "dice, stats, or classes unless the user explicitly asks for them. For every persona, create a useful visual profile "
            "for avatar portrait generation. If the story is fantasy, make the visual descriptions read as strong fantasy "
            "character portraits that still follow the user's story premise. Follow the requested persona count exactly when possible, "
            "and respect the configured character creation limit."
        )
        user = {
            "task": "Draft a Master Story setup from the user's prompt.",
            "schema": {
                "id": "short_lowercase_story_id",
                "title": "short title",
                "summary": "one paragraph",
                "mode": AR_MODE if use_ar else "Narrator + characters",
                "active_persona_id": "persona_id",
                "current_speaker_id": "persona_id",
                "session": {
                    "scene_title": "short scene title",
                    "location": "current location",
                    "time_of_day": "time/era/timing cue",
                    "mood": "atmosphere",
                    "objective": "clear opening objective",
                    "scene_summary": "compact visible continuity summary",
                    "ar_pacing": "Balanced",
                    "ar_interaction_frequency": "Ask sometimes",
                    "ar_state": {
                        "current_scene": "opening beat",
                        "location": "same or more specific location",
                        "active_characters": ["persona_id"],
                        "tension_level": 2,
                        "story_goal": "story goal",
                        "recent_events": ["opening event"],
                        "pending_choices": ["optional choice"],
                        "mood": "mood",
                        "time_of_day": "time",
                    },
                },
                "personas": [
                    {
                        "id": "persona_id",
                        "display_name": "Name",
                        "role": "archetype",
                        "description": "normal short description",
                        "system_prompt": "normal persona prompt",
                        "ar_description": "cinematic AR character description",
                        "ar_system_prompt": "AR persona instruction",
                        "speaking_style": "voice and phrasing",
                        "allowed_tone": "tone limits",
                        "behavior_mode": "group participant",
                        "memory_scope": "persona-only",
                        "tags": ["story"],
                        "visual": {
                            "enabled": True,
                            "mode": "manual",
                            "provider": "inherit",
                            "size": "inherit",
                            "style_preset": "",
                            "character_description": "detailed visual appearance for avatar portrait generation",
                            "clothing_props": "costume, gear, props, silhouette",
                            "environment_style": "background or world style",
                            "negative_prompt": "avoid text, watermark, extra limbs, distorted face",
                        },
                    }
                ],
                "content_safety": {
                    "sfw": True,
                    "allow_romance": True,
                    "allow_mature_themes": False,
                    "allow_explicit_sexual_content": False,
                },
                "generation": {
                    "source": "master_story_creator",
                    "requested_story_native_personas": constraints.get("native_personas_to_draft", 4),
                    "maximum_new_personas_to_create": constraints.get("maximum_new_personas_to_create", 8),
                    "use_existing_personas": constraints.get("use_existing_personas", True),
                    "auto_create_missing_personas": constraints.get("auto_create_missing_personas", True),
                    "sfw_mode": content_safety.get("sfw", True),
                },
                "updated_at": "ISO-8601 timestamp or empty string",
            },
            "existing_personas": roster,
            "generation_constraints": constraints,
            "content_safety": content_safety,
            "content_safety_instruction": safety_instruction,
            "canonical_json_rules": [
                "Return exactly one story object at the JSON root.",
                "Do not include a second top-level id/title/summary/personas/session block after the story.",
                "Do not include duplicate top-level keys.",
                "Keep generated personas in the single personas array.",
                "Keep metadata in generation and safety flags in content_safety.",
            ],
            "persona_count_contract": {
                "requested_story_native_personas": constraints.get("native_personas_to_draft", 4),
                "return_exact_persona_count_when_possible": True,
                "persona_array_is_validated_against_requested_count": True,
            },
            "generation_notes": str(snapshot.get("generation_notes") or ""),
            "avatar_visual_direction": visual_direction,
            "user_story_prompt": prompt,
            "original_user_story_prompt_note": "If SFW mode rewrote prompt wording, preserve the user's adventure intent using non-explicit relationship conflict and emotional stakes.",
        }
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=True, indent=2)},
        ]
        params = {
            "model": model_name,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        additional_params: dict[str, Any] = {}
        if hasattr(engine, "_apply_chat_provider_generation_fields"):
            engine._apply_chat_provider_generation_fields(params, additional_params)
        return self._run_master_story_generation_request(engine, params, additional_params)

    @staticmethod
    def _master_story_generation_error_is_provider_compatibility(exc: Exception) -> bool:
        message = str(exc or "").lower()
        if not message:
            return False
        return any(
            marker in message
            for marker in (
                "response_format",
                "json_object",
                "http error 400",
                "400 bad request",
                "bad request",
                "invalid request",
                "invalid parameter",
                "unknown parameter",
                "unsupported",
                "extra_body",
            )
        )

    @staticmethod
    def _master_story_relaxed_params(params: dict[str, Any]) -> dict[str, Any]:
        relaxed = dict(params or {})
        relaxed.pop("response_format", None)
        for key in ("max_tokens", "max_completion_tokens"):
            if key not in relaxed:
                continue
            try:
                if int(float(relaxed.get(key))) <= 0:
                    relaxed.pop(key, None)
            except Exception:
                pass
        return relaxed

    def _run_master_story_generation_request(self, engine, params: dict[str, Any], additional_params: dict[str, Any]) -> str:
        base_params = dict(params or {})
        base_additional = dict(additional_params or {})
        attempts: list[tuple[str, dict[str, Any], dict[str, Any]]] = [("strict JSON mode", base_params, base_additional)]
        relaxed_params = self._master_story_relaxed_params(base_params)
        if relaxed_params != base_params:
            attempts.append(("plain JSON instructions", relaxed_params, base_additional))
        if base_additional:
            attempts.append(("plain JSON instructions without provider extras", relaxed_params, {}))

        last_error: Exception | None = None
        for label, request_params, request_additional in attempts:
            try:
                return str(engine._chat_completion_create(dict(request_params), dict(request_additional)) or "").strip()
            except Exception as exc:
                last_error = exc
                if not self._master_story_generation_error_is_provider_compatibility(exc):
                    raise
                logger = getattr(getattr(self, "context", None), "logger", None)
                if logger is not None:
                    try:
                        logger.info("[MPRC] Master Story generation provider retry after %s failed: %s", label, exc)
                    except Exception:
                        pass
                continue
        if last_error is not None:
            raise RuntimeError(
                f"{last_error} (Master Story generation retried without JSON response_format"
                " and provider extra parameters.)"
            )
        return ""

    def _control_checked(self, key: str, default: bool = False) -> bool:
        widget = self._controls.get(key)
        if widget is None or not hasattr(widget, "isChecked"):
            return bool(default)
        return bool(widget.isChecked())

    def _master_story_allow_exceed_max_created_characters(self) -> bool:
        return self._control_checked("master_story_allow_exceed_max_created_characters", False)

    def _master_story_sfw_mode(self) -> bool:
        return self._control_checked("master_story_sfw_mode", True)

    def _control_int_value(self, key: str, default: int, minimum: int, maximum: int) -> int:
        widget = self._controls.get(key)
        try:
            value = int(widget.value()) if widget is not None and hasattr(widget, "value") else int(default)
        except Exception:
            value = int(default)
        return max(int(minimum), min(int(maximum), value))

    def _master_story_int_setting(self, key: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(float(self.settings.get(key, default)))
        except Exception:
            value = int(default)
        return max(int(minimum), min(int(maximum), value))

    def _commit_master_story_options(self):
        if self._syncing:
            return
        self.settings["master_story_native_persona_count"] = self._control_int_value("master_story_native_persona_count", 4, 0, 24)
        self.settings["master_story_max_created_characters"] = self._control_int_value("master_story_max_created_characters", 8, 1, 40)
        self.settings["master_story_allow_exceed_max_created_characters"] = self._control_checked("master_story_allow_exceed_max_created_characters", False)
        self.settings["master_story_sfw_mode"] = self._master_story_sfw_mode()
        for key in (
            "master_story_use_existing_personas",
            "master_story_use_ar",
            "master_story_auto_create",
            "master_story_update_existing",
            "master_story_auto_avatars",
            "master_story_clear_memory",
        ):
            self.settings[key] = self._control_checked(key, True)
        self.settings["master_story_avatar_style_sheets"] = self._control_checked("master_story_avatar_style_sheets", False)
        self.storage.save_settings(self.settings)

    def _master_story_generation_constraints(self) -> dict[str, Any]:
        native_count = self._control_int_value("master_story_native_persona_count", 4, 0, 24)
        max_created = self._control_int_value("master_story_max_created_characters", 8, 1, 40)
        return {
            "native_personas_to_draft": native_count,
            "maximum_new_personas_to_create": max_created,
            "allow_exceed_max_created_characters": self._master_story_allow_exceed_max_created_characters(),
            "sfw_mode": self._master_story_sfw_mode(),
            "use_existing_personas": self._control_checked("master_story_use_existing_personas", True),
            "auto_create_missing_personas": self._control_checked("master_story_auto_create", True),
        }

    def _master_story_content_safety_payload(self, sfw: bool | None = None) -> dict[str, Any]:
        sfw_enabled = self._master_story_sfw_mode() if sfw is None else bool(sfw)
        return {
            "sfw": sfw_enabled,
            "allow_romance": True,
            "allow_mature_themes": not sfw_enabled,
            "allow_explicit_sexual_content": False,
        }

    @staticmethod
    def _master_story_safety_instruction(sfw: bool) -> str:
        if bool(sfw):
            return (
                "Content safety: SFW mode is enabled. Keep the story suitable for general fantasy adventure. "
                "Romantic tension and mature emotional themes are allowed, but do not generate explicit sexual content, erotic descriptions, or graphic nudity. "
                "Rephrase sexual prompt elements into non-explicit relationship conflict, taboo, loyalty, intimacy, and emotional stakes."
            )
        return (
            "Content safety: SFW mode is disabled. Mature themes may be included when relevant, but do not generate illegal, underage, "
            "non-consensual, exploitative, or pornographic content. Keep story output narrative-focused and controllable."
        )

    @staticmethod
    def _master_story_safety_normalized_prompt(prompt: str, *, sfw: bool) -> str:
        text = str(prompt or "").strip()
        if not bool(sfw) or not text:
            return text
        replacements = (
            (r"\binter[\s-]?racial relationships?\s+and\s+sexual activity\b", "forbidden relationships, cultural taboos, and intimate bonds across enemy lines"),
            (r"\bsexual activity\b", "non-explicit intimate bonds and emotional stakes"),
            (r"\bexplicit sex(?:ual)?\b", "romantic tension and private emotional stakes"),
            (r"\berotic\b", "romantic"),
            (r"\bfetish(?:es|istic)?\b", "personal taboo"),
            (r"\bgraphic nudity\b", "vulnerable non-explicit intimacy"),
        )
        for pattern, replacement in replacements:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return text

    def _master_story_generation_constraints_text(self, constraints: dict[str, Any] | None = None) -> str:
        constraints = dict(constraints or self._master_story_generation_constraints())
        existing = "may reuse already created personas" if constraints["use_existing_personas"] else "should not rely on already created personas"
        native_count = int(constraints.get("native_personas_to_draft", 4) or 0)
        if native_count <= 0:
            persona_count_line = "- Do not draft story-native persona objects unless the user's prompt explicitly requires them."
        else:
            persona_count_line = (
                f"- Draft exactly {native_count} story-native persona/character profile(s) in the personas array when possible. "
                "If you cannot safely reach that count, return the closest complete cast and note the reason in the summary instead of adding weak filler."
            )
        max_line = (
            f"- Apply Draft will create no more than {constraints['maximum_new_personas_to_create']} new persona/character profile(s) by default; "
            "still keep the requested draft cast visible so the user can review, map, reuse, or enable the override."
        )
        if constraints.get("allow_exceed_max_created_characters"):
            max_line = (
                f"- The user has enabled the max-created override; Apply Draft may create more than "
                f"{constraints['maximum_new_personas_to_create']} new persona/character profile(s) when the requested draft cast needs it."
            )
        return (
            "Master Story generation constraints:\n"
            f"{persona_count_line}\n"
            f"{max_line}\n"
            f"- {self._master_story_safety_instruction(bool(constraints.get('sfw_mode', True)))}\n"
            f"- Existing personas: {existing}.\n"
            "- When reusing an existing persona, keep a clear separation between using that persona as-is and a story-only alternate profile."
        )

    def _on_master_story_generated(self, token: str, payload_text: str, error: str):
        if not self._finish_worker_token(str(token or "")):
            return
        button = self._controls.get("master_story_generate")
        if button is not None:
            button.setProperty("_mprc_in_flight", False)
            button.setProperty("_mprc_worker_token", "")
            button.setEnabled(True)
        if error:
            self._set_master_story_status(f"Generation failed: {error}")
            self._warn("Generate Story Setup", f"Master Story generation failed:\n\n{error}")
            return
        payload, parse_errors = self._parse_master_story_json_text(payload_text)
        if not isinstance(payload, dict):
            message = "Generation returned text, but not valid JSON. Review or regenerate before applying."
            if parse_errors:
                message += " " + parse_errors[0]
            self._set_master_story_status(message)
            draft = str(payload_text or "").strip()
            if draft:
                self._controls["master_story_draft"].setPlainText(draft)
            return
        canonical, canonical_errors = self._canonical_master_story_payload(payload)
        validation_errors = parse_errors + canonical_errors + self._validate_master_story_payload(canonical)
        if validation_errors:
            self._controls["master_story_draft"].setPlainText(str(payload_text or "").strip())
            self._set_master_story_status(self._master_story_validation_message(validation_errors).replace("\n", " "))
            return
        normalized = self._normalize_master_story_payload(canonical)
        normalized = self._sanitize_master_story_overrides_for_options(normalized)
        normalized = self._limit_generated_master_story_personas(normalized)
        self._master_story_draft = normalized
        self._set_master_story_visual_direction(normalized.get("avatar_visual_direction"))
        self._set_master_story_sfw_from_payload(normalized)
        self._controls["master_story_draft"].setPlainText(json.dumps(normalized, indent=2, ensure_ascii=True))
        status = "Story setup generated. Review it, then Apply Draft or Save Story."
        count_warning = self._master_story_persona_count_warning(normalized)
        if count_warning:
            status += " " + count_warning
        max_warning = self._master_story_generated_persona_limit_warning(normalized)
        if max_warning:
            status += " " + max_warning
        self._set_master_story_status(status)

    def _limit_generated_master_story_personas(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Keep the full generated draft visible. The max-created setting is enforced during Apply Draft.
        return payload

    def _master_story_persona_count_warning(self, payload: dict[str, Any]) -> str:
        requested = self._control_int_value("master_story_native_persona_count", 4, 0, 24)
        personas = [item for item in list((payload or {}).get("personas") or []) if isinstance(item, dict)]
        actual = len(personas)
        if actual == requested:
            return ""
        return (
            f"Requested {requested} story-native persona(s); draft returned {actual}. "
            "Review or regenerate before applying if the cast count matters."
        )

    def _master_story_generated_persona_limit_warning(self, payload: dict[str, Any]) -> str:
        if self._master_story_allow_exceed_max_created_characters():
            return ""
        max_created = self._control_int_value("master_story_max_created_characters", 8, 1, 40)
        personas = [item for item in list((payload or {}).get("personas") or []) if isinstance(item, dict)]
        if len(personas) <= max_created:
            return ""
        return (
            f"This draft contains {len(personas)} personas, but only {max_created} new personas will be created unless override is enabled."
        )

    def _set_master_story_visual_direction(self, value: Any) -> None:
        widget = self._controls.get("master_story_visual_direction")
        text = str(value or "").strip()
        if widget is not None and text and not str(widget.toPlainText() or "").strip():
            widget.setPlainText(text)

    def _set_master_story_sfw_from_payload(self, payload: dict[str, Any]) -> None:
        widget = self._controls.get("master_story_sfw_mode")
        if widget is None or not hasattr(widget, "setChecked"):
            return
        safety = payload.get("content_safety") if isinstance(payload.get("content_safety"), dict) else {}
        sfw = bool(safety.get("sfw", True))
        was_syncing = self._syncing
        self._syncing = True
        try:
            widget.setChecked(sfw)
        finally:
            self._syncing = was_syncing

    def _sanitize_master_story_overrides_for_options(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = dict(payload or {})
        if not self._control_checked("master_story_use_existing_personas", True):
            raw.pop("persona_overrides", None)
            return raw
        overrides = raw.get("persona_overrides")
        if not isinstance(overrides, dict):
            return raw
        allowed_ids = self._master_story_payload_persona_ids(raw)
        if not allowed_ids:
            raw.pop("persona_overrides", None)
            return raw
        clean: dict[str, dict[str, Any]] = {}
        for key, value in overrides.items():
            persona_id = normalize_persona_id(key)
            if persona_id in allowed_ids and isinstance(value, dict):
                clean[persona_id] = dict(value)
        if clean:
            raw["persona_overrides"] = clean
        else:
            raw.pop("persona_overrides", None)
        return raw

    def _master_story_payload_persona_ids(self, payload: dict[str, Any]) -> set[str]:
        ids: set[str] = set()
        for key in ("active_persona_id", "current_speaker_id", "narrator_persona_id", "selected_narrator_id"):
            persona_id = normalize_persona_id(payload.get(key))
            if persona_id:
                ids.add(persona_id)
        session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
        for key in ("active_persona_id", "current_speaker_id", "narrator_persona_id", "selected_narrator_id"):
            persona_id = normalize_persona_id(session.get(key))
            if persona_id:
                ids.add(persona_id)
        ar_state = session.get("ar_state") if isinstance(session.get("ar_state"), dict) else {}
        for item in list(ar_state.get("active_characters") or []):
            persona_id = normalize_persona_id(item)
            if persona_id:
                ids.add(persona_id)
        for item in list(payload.get("personas") or []):
            if not isinstance(item, dict):
                continue
            for key in ("id", "display_name"):
                persona_id = normalize_persona_id(item.get(key))
                if persona_id:
                    ids.add(persona_id)
        return ids

    def _parse_master_story_json_text(self, text: str) -> tuple[dict[str, Any] | None, list[str]]:
        raw = str(text or "").strip()
        if not raw:
            return None, ["Master Story draft is empty."]
        errors: list[str] = []

        def reject_duplicates(pairs):
            obj: dict[str, Any] = {}
            seen: set[str] = set()
            for key, value in pairs:
                key_text = str(key)
                if key_text in seen:
                    errors.append(f"Duplicate JSON key '{key_text}' was found. Remove duplicate keys before applying the draft.")
                seen.add(key_text)
                obj[key_text] = value
            return obj

        def load(candidate: str) -> dict[str, Any] | None:
            try:
                payload = json.loads(candidate, object_pairs_hook=reject_duplicates)
            except Exception as exc:
                errors.append(f"Invalid JSON: {exc}")
                return None
            if not isinstance(payload, dict):
                errors.append("Master Story draft must be a JSON object.")
                return None
            return payload

        payload = load(raw)
        if payload is None and "{" in raw and "}" in raw:
            errors.clear()
            start = raw.find("{")
            end = raw.rfind("}")
            payload = load(raw[start : end + 1])
        return payload, errors

    def _canonical_master_story_payload(self, payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        raw = dict(payload or {})
        errors: list[str] = []
        story_keys = {
            "id",
            "title",
            "summary",
            "mode",
            "active_persona_id",
            "current_speaker_id",
            "session",
            "personas",
            "content_safety",
        }
        if isinstance(raw.get("draft"), dict):
            mixed = sorted(key for key in story_keys if key in raw)
            if mixed:
                errors.append(
                    "Master Story JSON mixes wrapper fields with story fields at the same level: "
                    + ", ".join(mixed)
                    + ". Put the story only inside draft or return the story object directly."
                )
            draft = dict(raw.get("draft") or {})
            if isinstance(raw.get("generation_constraints"), dict) and not isinstance(draft.get("generation"), dict):
                draft["generation"] = dict(raw.get("generation_constraints") or {})
            return draft, errors
        return raw, errors

    def _validate_master_story_payload(self, payload: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        required = ("id", "title", "mode", "session", "personas")
        for key in required:
            if key not in payload:
                errors.append(f"Missing required field: {key}.")
        if "session" in payload and not isinstance(payload.get("session"), dict):
            errors.append("Field 'session' must be an object.")
        mode = str(payload.get("mode") or "").strip()
        if mode and mode not in SESSION_MODES:
            errors.append(f"Unsupported mode '{mode}'.")
        personas = payload.get("personas")
        if not isinstance(personas, list):
            errors.append("Field 'personas' must be an array.")
            personas = []
        requested = self._control_int_value("master_story_native_persona_count", 4, 0, 24)
        if requested > 0 and isinstance(personas, list) and not personas:
            errors.append(f"Draft requested {requested} story-native persona(s), but personas is empty.")
        ids: list[str] = []
        for index, item in enumerate(list(personas or []), start=1):
            if not isinstance(item, dict):
                errors.append(f"Persona {index} must be an object.")
                continue
            persona_id = normalize_persona_id(item.get("id"))
            if not persona_id:
                errors.append(f"Persona {index} is missing id.")
            else:
                ids.append(persona_id)
            if not str(item.get("display_name") or "").strip():
                errors.append(f"Persona {index} is missing display_name.")
            if not str(item.get("role") or "").strip():
                errors.append(f"Persona {index} is missing role.")
            if not str(item.get("system_prompt") or item.get("ar_system_prompt") or "").strip():
                errors.append(f"Persona {index} must include system_prompt or ar_system_prompt.")
        duplicates = sorted({persona_id for persona_id in ids if ids.count(persona_id) > 1})
        if duplicates:
            errors.append("Duplicate persona id(s) in draft: " + ", ".join(duplicates) + ".")
        known_ids = {persona.id for persona in self.personas}
        known_ids.update(ids)
        narrator_id = normalize_persona_id(payload.get("narrator_persona_id"))
        if narrator_id:
            known_ids.add(narrator_id)
        session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
        for key in ("active_persona_id", "current_speaker_id"):
            value = normalize_persona_id(payload.get(key) or session.get(key))
            if value and value not in known_ids:
                errors.append(f"{key} '{value}' does not match a draft persona, existing persona, or narrator id.")
        return errors

    def _master_story_validation_message(self, errors: list[str]) -> str:
        return "Master Story draft validation failed:\n\n" + "\n".join(f"- {item}" for item in errors[:12])

    def _normalize_master_story_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw, _errors = self._canonical_master_story_payload(payload)
        raw = dict(raw or {})
        title = str(raw.get("title") or raw.get("id") or "Master Story").strip() or "Master Story"
        story_id = self.storage.story_id(raw.get("id") or title)
        session = dict(raw.get("session") or {}) if isinstance(raw.get("session"), dict) else {}
        mode = str(raw.get("mode") or session.get("mode") or "").strip()
        if self._control_checked("master_story_use_ar", True):
            mode = AR_MODE
        elif mode not in SESSION_MODES:
            mode = "Narrator + characters"
        raw["id"] = story_id
        raw["title"] = title[:120]
        raw["summary"] = str(raw.get("summary") or session.get("scene_summary") or "").strip()
        if not str(raw.get("avatar_visual_direction") or "").strip():
            visual_direction_widget = self._controls.get("master_story_visual_direction")
            raw["avatar_visual_direction"] = str(visual_direction_widget.toPlainText() if visual_direction_widget is not None else "").strip()
        raw["mode"] = mode
        personas = []
        seen = set()
        for item in list(raw.get("personas") or []):
            if not isinstance(item, dict):
                continue
            persona_payload = dict(item)
            persona_id = normalize_persona_id(persona_payload.get("id") or persona_payload.get("display_name") or "story_persona")
            persona_id = unique_persona_id(persona_id, seen)
            seen.add(persona_id)
            persona_payload["id"] = persona_id
            if not str(persona_payload.get("display_name") or "").strip():
                persona_payload["display_name"] = persona_id.replace("_", " ").title()
            if not isinstance(persona_payload.get("visual"), dict):
                appearance = str(
                    persona_payload.get("visual_description")
                    or persona_payload.get("appearance")
                    or persona_payload.get("avatar_description")
                    or ""
                ).strip()
                if appearance:
                    persona_payload["visual"] = {
                        "enabled": True,
                        "mode": "manual",
                        "provider": "inherit",
                        "size": "inherit",
                        "character_description": appearance,
                        "negative_prompt": "text, watermark, logo, distorted face, extra limbs",
                    }
            personas.append(persona_payload)
        raw["personas"] = personas
        active_id = normalize_persona_id(raw.get("active_persona_id") or session.get("active_persona_id") or (personas[0]["id"] if personas else self.session.active_persona_id))
        speaker_id = normalize_persona_id(raw.get("current_speaker_id") or session.get("current_speaker_id") or active_id)
        raw["active_persona_id"] = active_id
        raw["current_speaker_id"] = speaker_id
        session["mode"] = mode
        raw["session"] = session
        content_safety = raw.get("content_safety") if isinstance(raw.get("content_safety"), dict) else {}
        sfw = bool(content_safety.get("sfw", True))
        raw["content_safety"] = {
            **self._master_story_content_safety_payload(sfw),
            **{key: value for key, value in content_safety.items() if key in {"sfw", "allow_romance", "allow_mature_themes", "allow_explicit_sexual_content"}},
        }
        raw["content_safety"]["allow_explicit_sexual_content"] = False
        generation = raw.get("generation") if isinstance(raw.get("generation"), dict) else {}
        raw["generation"] = {
            "source": "master_story_creator",
            "requested_story_native_personas": self._control_int_value("master_story_native_persona_count", 4, 0, 24),
            "maximum_new_personas_to_create": self._control_int_value("master_story_max_created_characters", 8, 1, 40),
            "use_existing_personas": self._control_checked("master_story_use_existing_personas", True),
            "auto_create_missing_personas": self._control_checked("master_story_auto_create", True),
            "sfw_mode": bool(raw["content_safety"].get("sfw", True)),
            **generation,
        }
        raw["updated_at"] = QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate)
        return raw

    def _parse_master_story_draft(self) -> dict[str, Any] | None:
        draft = str(self._controls.get("master_story_draft").toPlainText() if self._controls.get("master_story_draft") is not None else "").strip()
        if not draft and self._master_story_draft:
            return self._normalize_master_story_payload(self._master_story_draft)
        payload, parse_errors = self._parse_master_story_json_text(draft)
        if not isinstance(payload, dict):
            if parse_errors:
                self._set_master_story_status(self._master_story_validation_message(parse_errors).replace("\n", " "))
            return None
        canonical, canonical_errors = self._canonical_master_story_payload(payload)
        errors = parse_errors + canonical_errors + self._validate_master_story_payload(canonical)
        if errors:
            self._set_master_story_status(self._master_story_validation_message(errors).replace("\n", " "))
            return None
        normalized = self._normalize_master_story_payload(canonical)
        self._set_master_story_sfw_from_payload(normalized)
        return normalized

    def _apply_master_story_draft(self):
        payload = self._parse_master_story_draft()
        if not isinstance(payload, dict):
            self._warn("Apply Draft", "The Master Story draft is not valid or does not match the required story schema. Check the Master Story status message.")
            return
        payload = self._sanitize_master_story_overrides_for_options(payload)
        apply_plan = self._show_master_story_apply_dialog(payload)
        if apply_plan is None:
            self._set_master_story_status("Apply Draft cancelled.")
            return
        self._apply_master_story_payload(payload, apply_plan=apply_plan)

    def _show_master_story_apply_dialog(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        from PySide6 import QtCore, QtWidgets

        payload = self._normalize_master_story_payload(payload)
        personas = [dict(item) for item in list(payload.get("personas") or []) if isinstance(item, dict)]
        dialog = QtWidgets.QDialog(self._widget.window() if self._widget is not None else None)
        dialog.setWindowTitle("Apply Master Story")
        dialog.setModal(True)
        dialog.resize(1180, 780)
        layout = QtWidgets.QVBoxLayout(dialog)

        title = QtWidgets.QLabel("Apply Master Story Workflow")
        title_font = title.font()
        title_font.setPointSize(max(12, title_font.pointSize() + 3))
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        guide = QtWidgets.QLabel(
            "Review each drafted character, choose whether it becomes a new persona or reuses an existing one, "
            "then choose whether existing personas are used as-is, updated, or given a story-only alternate profile. "
            "Existing persona pictures are shown so you can recognize the cast before applying the story."
        )
        guide.setWordWrap(True)
        guide.setProperty("muted", True)
        layout.addWidget(guide)
        count_warning = self._master_story_generated_persona_limit_warning(payload)
        if count_warning:
            warning = QtWidgets.QLabel(count_warning)
            warning.setWordWrap(True)
            warning.setStyleSheet("color: #facc15; font-weight: 700;")
            layout.addWidget(warning)

        options_box, options_layout = self._group("Workflow Options")
        options_row = QtWidgets.QHBoxLayout()
        clean_start = QtWidgets.QCheckBox("Clean-start memory before applying")
        clean_start.setChecked(self._control_checked("master_story_clear_memory", True))
        update_existing = QtWidgets.QCheckBox("Update selected existing personas from draft")
        update_existing.setChecked(self._control_checked("master_story_update_existing", True))
        auto_avatars = QtWidgets.QCheckBox("Request avatar images for new personas")
        auto_avatars.setChecked(self._control_checked("master_story_auto_avatars", True))
        avatar_style_sheets = QtWidgets.QCheckBox("Request avatar style sheets")
        avatar_style_sheets.setChecked(self._control_checked("master_story_avatar_style_sheets", False))
        allow_exceed_max = QtWidgets.QCheckBox("Allow exceeding max created characters")
        allow_exceed_max.setChecked(self._master_story_allow_exceed_max_created_characters())
        allow_exceed_max.setToolTip(
            "Default off. When off, Apply Story creates no more new personas than Maximum created characters. "
            "Enable only when this draft intentionally needs a larger new cast."
        )
        avatar_style_sheets.setToolTip(
            "Optional. Requests a character reference sheet after a new persona has an avatar image. "
            "Best used with Visual Reply providers or workflows that support image-to-image/reference input."
        )
        options_row.addWidget(clean_start)
        options_row.addWidget(update_existing)
        options_row.addWidget(auto_avatars)
        options_row.addWidget(avatar_style_sheets)
        options_row.addWidget(allow_exceed_max)
        options_row.addStretch(1)
        options_layout.addLayout(options_row)
        layout.addWidget(options_box)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        left_panel = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_title = QtWidgets.QLabel("1. Draft Characters")
        left_title.setProperty("muted", True)
        draft_list = QtWidgets.QListWidget()
        draft_list.setIconSize(QtCore.QSize(58, 58))
        draft_list.setMinimumWidth(285)
        draft_list.setUniformItemSizes(False)
        draft_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        left_layout.addWidget(left_title)
        left_layout.addWidget(draft_list, 1)
        splitter.addWidget(left_panel)

        detail_panel = QtWidgets.QWidget()
        detail_layout = QtWidgets.QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(8, 0, 0, 0)

        top_row = QtWidgets.QHBoxLayout()
        draft_box, draft_layout = self._group("2. Draft Character")
        draft_header = QtWidgets.QHBoxLayout()
        draft_image = QtWidgets.QLabel("Draft")
        draft_image.setFixedSize(132, 160)
        draft_image.setProperty("_mprc_image_width", 132)
        draft_image.setProperty("_mprc_image_height", 160)
        draft_name = QtWidgets.QLabel("")
        draft_name.setWordWrap(True)
        draft_name.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        draft_header.addWidget(draft_image)
        draft_header.addWidget(draft_name, 1)
        draft_layout.addLayout(draft_header)
        draft_details = QtWidgets.QPlainTextEdit()
        draft_details.setReadOnly(True)
        draft_details.setMinimumHeight(145)
        draft_layout.addWidget(draft_details)

        mapping_box, mapping_layout = self._group("3. Persona Mapping")
        action_combo = QtWidgets.QComboBox()
        action_combo.addItem("Create new persona from draft", "__create__")
        action_combo.addItem("Use selected persona as-is", "reuse_as_is")
        action_combo.addItem("Use selected with story-only alternate profile", "story_profile")
        action_combo.addItem("Update selected existing persona from draft", "reuse_update")
        action_combo.setToolTip(
            "Choose whether this draft character creates a new persona, reuses an existing one unchanged, "
            "or stores a story-only alternate profile for the selected persona."
        )
        persona_combo = QtWidgets.QComboBox()
        persona_combo.setToolTip("Choose an existing persona to reuse, or create a fresh persona from the draft.")
        mapping_layout.addWidget(action_combo)
        mapping_layout.addWidget(persona_combo)
        selected_row = QtWidgets.QHBoxLayout()
        selected_image = QtWidgets.QLabel("New persona")
        selected_image.setFixedSize(132, 160)
        selected_image.setProperty("_mprc_image_width", 132)
        selected_image.setProperty("_mprc_image_height", 160)
        selected_summary = QtWidgets.QPlainTextEdit()
        selected_summary.setReadOnly(True)
        selected_summary.setMinimumHeight(160)
        selected_row.addWidget(selected_image)
        selected_row.addWidget(selected_summary, 1)
        mapping_layout.addLayout(selected_row)
        alternate_profile = QtWidgets.QPlainTextEdit()
        alternate_profile.setMinimumHeight(92)
        alternate_profile.setPlaceholderText("Optional story-only alternate persona notes for this character.")
        alternate_profile.setToolTip("Editable story-only persona info. Saved with this Master Story when mapping action is story-only alternate profile.")
        mapping_layout.addWidget(alternate_profile)
        gallery_label = QtWidgets.QLabel("Existing Persona Gallery")
        gallery_label.setProperty("muted", True)
        persona_gallery = QtWidgets.QListWidget()
        persona_gallery.setViewMode(QtWidgets.QListView.IconMode)
        persona_gallery.setMovement(QtWidgets.QListView.Static)
        persona_gallery.setResizeMode(QtWidgets.QListView.Adjust)
        persona_gallery.setFlow(QtWidgets.QListView.LeftToRight)
        persona_gallery.setWrapping(False)
        persona_gallery.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        persona_gallery.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        persona_gallery.setIconSize(QtCore.QSize(64, 64))
        persona_gallery.setFixedHeight(118)
        persona_gallery.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        mapping_layout.addWidget(gallery_label)
        mapping_layout.addWidget(persona_gallery)

        result_box, result_layout = self._group("4. Apply Result")
        result_summary = QtWidgets.QPlainTextEdit()
        result_summary.setReadOnly(True)
        result_summary.setMinimumHeight(170)
        result_layout.addWidget(result_summary)

        top_row.addWidget(draft_box, 1)
        top_row.addWidget(mapping_box, 1)
        top_row.addWidget(result_box, 1)
        detail_layout.addLayout(top_row)

        visual_box, visual_layout = self._group("5. Draft Avatar / Visual Prompt")
        visual_actions = QtWidgets.QHBoxLayout()
        draft_avatar_generate = QtWidgets.QPushButton("Generate Avatar Image")
        draft_avatar_regenerate = QtWidgets.QPushButton("Regenerate Avatar Image")
        draft_avatar_status = QtWidgets.QLabel("")
        draft_avatar_status.setWordWrap(True)
        draft_avatar_status.setProperty("muted", True)
        draft_avatar_generate.setToolTip("Request an avatar image for the selected draft persona through Visual Reply.")
        draft_avatar_regenerate.setToolTip("Request a fresh avatar image for the selected draft persona through Visual Reply.")
        visual_actions.addWidget(draft_avatar_generate)
        visual_actions.addWidget(draft_avatar_regenerate)
        visual_actions.addWidget(draft_avatar_status, 1)
        visual_layout.addLayout(visual_actions)
        visual_prompt = QtWidgets.QPlainTextEdit()
        visual_prompt.setMinimumHeight(150)
        visual_prompt.setPlaceholderText("Select a drafted character to edit the generated avatar prompt.")
        visual_prompt.setToolTip("Editable avatar prompt for the selected draft character. Right-click and choose Refine Avatar Visual Prompt to improve it.")
        self._install_refine_menu(
            visual_prompt,
            "Avatar Visual Prompt",
            "Refine into a concise image prompt for one avatar portrait. Preserve identity, role, clothing, mood, and story context. Keep it prompt-ready and avoid unrelated details.",
        )
        visual_layout.addWidget(visual_prompt)
        detail_layout.addWidget(visual_box)

        voice_box, voice_layout = self._group("6. Draft Voice")
        voice_form = QtWidgets.QFormLayout()
        voice_combo = QtWidgets.QComboBox()
        voice_combo.setMinimumWidth(360)
        voice_combo.setToolTip("Choose a .wav voice sample from the project voices folder for the selected draft character.")
        voice_combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self._populate_voice_file_combo(voice_combo, include_empty=True, empty_label="No voice selected")
        voice_preview_text = QtWidgets.QPlainTextEdit()
        voice_preview_text.setMinimumHeight(92)
        voice_preview_text.setPlainText(self._default_voice_preview_text())
        voice_preview_text.setToolTip("Editable TTS preview text. Use short emotional lines to hear how the selected voice handles different delivery.")
        preview_voice = QtWidgets.QPushButton("Preview Voice")
        preview_voice.setToolTip("Load the active NC TTS runtime if needed and play the preview text with the selected .wav voice sample.")
        voice_status = QtWidgets.QLabel("")
        voice_status.setWordWrap(True)
        voice_status.setProperty("muted", True)
        voice_button_row = QtWidgets.QHBoxLayout()
        voice_button_row.addWidget(preview_voice)
        voice_button_row.addWidget(voice_status, 1)
        voice_form.addRow("Voice sample", voice_combo)
        voice_form.addRow("Preview text", voice_preview_text)
        voice_form.addRow("", voice_button_row)
        voice_layout.addLayout(voice_form)
        detail_layout.addWidget(voice_box)
        splitter.addWidget(detail_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        draft_ids: list[str] = []
        choices_by_row: dict[int, str] = {}
        actions_by_row: dict[int, str] = {}
        alternates_by_row: dict[int, str] = {}
        draft_avatar_paths_by_row: dict[int, str] = {}
        draft_avatar_status_by_row: dict[int, str] = {}
        draft_avatar_prompts_by_row: dict[int, str] = {}
        draft_voice_paths_by_row: dict[int, str] = {}
        list_items: dict[int, Any] = {}
        active_row = {"value": -1}
        draft_avatar_pending_rows: set[int] = set()
        buttons = None

        def update_apply_button_state() -> None:
            if buttons is None:
                return
            ok_button = buttons.button(QtWidgets.QDialogButtonBox.Ok)
            if ok_button is not None:
                ok_button.setEnabled(not draft_avatar_pending_rows)

        def persona_for_choice(choice: str) -> PersonaConfig | None:
            if str(choice or "") == "__create__":
                return None
            return self.persona_by_id(str(choice or ""))

        def draft_label(row: int, item: dict[str, Any]) -> str:
            draft_id = draft_ids[row]
            name = str(item.get("display_name") or draft_id.replace("_", " ").title()).strip()
            role = str(item.get("role") or item.get("behavior_mode") or "No role").strip()
            action = str(actions_by_row.get(row, "__create__") or "__create__")
            choice = str(choices_by_row.get(row, "__create__") or "__create__")
            selected = persona_for_choice(choice)
            if action == "__create__" or selected is None:
                action_label = "Create new persona"
            elif action == "reuse_as_is":
                action_label = f"Use {selected.display_name} as-is"
            elif action == "reuse_update":
                action_label = f"Update {selected.display_name}"
            else:
                action_label = f"Story profile for {selected.display_name}"
            return f"{row + 1}. {name}\n{role}\n{action_label}"

        def refresh_draft_list_item(row: int):
            list_item = list_items.get(row)
            if list_item is None or row < 0 or row >= len(personas):
                return
            list_item.setText(draft_label(row, personas[row]))
            avatar_path = str(draft_avatar_paths_by_row.get(row) or personas[row].get("character_image_path") or "").strip()
            if avatar_path and Path(avatar_path).exists():
                list_item.setIcon(self._apply_dialog_path_icon(avatar_path, 58, fallback_text=str(personas[row].get("display_name") or draft_ids[row])))
                return
            selected = persona_for_choice(str(choices_by_row.get(row, "__create__") or "__create__"))
            if selected is not None:
                list_item.setIcon(self._apply_dialog_persona_icon(selected, 58))
            else:
                list_item.setIcon(self._apply_dialog_initial_icon(str(personas[row].get("display_name") or draft_ids[row]), 58))

        def set_voice_combo_path(sample_path: str) -> None:
            sample_path = str(sample_path or "").strip()
            voice_combo.blockSignals(True)
            target = self._normalized_path_text(sample_path)
            index = 0
            if target:
                for combo_row in range(voice_combo.count()):
                    candidate = self._normalized_path_text(voice_combo.itemData(combo_row))
                    if candidate and candidate == target:
                        index = combo_row
                        break
                else:
                    voice_combo.addItem(Path(sample_path).name, sample_path)
                    voice_combo.setItemData(voice_combo.count() - 1, sample_path, QtCore.Qt.ToolTipRole)
                    index = voice_combo.count() - 1
            voice_combo.setCurrentIndex(max(0, index))
            voice_combo.blockSignals(False)

        for row, item in enumerate(personas):
            draft_id = normalize_persona_id(item.get("id") or item.get("display_name") or f"story_persona_{row + 1}")
            draft_ids.append(draft_id)
            match = self._find_persona_for_story(item) if self._control_checked("master_story_use_existing_personas", True) else None
            choices_by_row[row] = match.id if match is not None else "__create__"
            actions_by_row[row] = "story_profile" if match is not None else "__create__"
            alternates_by_row[row] = self._apply_dialog_default_alternate_profile(item)
            voice_payload = item.get("voice") if isinstance(item.get("voice"), dict) else {}
            voice_path = str(voice_payload.get("sample_path") or item.get("voice_sample_path") or "").strip()
            if voice_path:
                draft_voice_paths_by_row[row] = voice_path
            list_item = QtWidgets.QListWidgetItem()
            list_item.setData(QtCore.Qt.UserRole, row)
            list_items[row] = list_item
            draft_list.addItem(list_item)
            refresh_draft_list_item(row)

        if not personas:
            empty = QtWidgets.QListWidgetItem("No personas in draft\nThe session can still be applied.")
            empty.setIcon(self._apply_dialog_initial_icon("Story", 58))
            draft_list.addItem(empty)

        persona_combo.addItem(self._apply_dialog_initial_icon("New", 30), "Create new persona from draft", "__create__")
        for persona in self.personas:
            persona_combo.addItem(self._apply_dialog_persona_icon(persona, 30), f"{persona.display_name} ({persona.id})", persona.id)
            gallery_item = QtWidgets.QListWidgetItem(self._apply_dialog_persona_icon(persona, 64), persona.display_name)
            gallery_item.setData(QtCore.Qt.UserRole, persona.id)
            gallery_item.setToolTip(self._apply_dialog_persona_summary(persona))
            persona_gallery.addItem(gallery_item)

        def refresh_current_row(row: int):
            active_row["value"] = row
            if row < 0 or row >= len(personas):
                draft_name.setText("No drafted personas")
                draft_details.setPlainText("This story draft does not include a persona list. Applying it can still update the session and AR state.")
                self._set_image_label(draft_image, "", fallback_text="No draft")
                selected_summary.setPlainText("")
                result_summary.setPlainText("")
                visual_prompt.setPlainText("")
                set_voice_combo_path("")
                voice_status.setText("")
                draft_avatar_generate.setEnabled(False)
                draft_avatar_regenerate.setEnabled(False)
                draft_avatar_status.setText("")
                return
            item = personas[row]
            draft_id = draft_ids[row]
            name = str(item.get("display_name") or draft_id.replace("_", " ").title()).strip()
            role = str(item.get("role") or item.get("behavior_mode") or "").strip()
            draft_name.setText(f"{name}\nDraft ID: {draft_id}\nRole: {role or 'Not specified'}")
            draft_details.setPlainText(self._apply_dialog_draft_summary(item, payload))
            self._set_image_label(draft_image, str(item.get("character_image_path") or ""), fallback_text="Draft")
            action = str(actions_by_row.get(row, "__create__") or "__create__")
            choice = str(choices_by_row.get(row, "__create__") or "__create__")
            action_combo.blockSignals(True)
            action_index = action_combo.findData(action)
            action_combo.setCurrentIndex(max(0, action_index))
            action_combo.blockSignals(False)
            persona_combo.blockSignals(True)
            index = persona_combo.findData(choice)
            persona_combo.setCurrentIndex(max(0, index))
            persona_combo.blockSignals(False)
            selected = None if action == "__create__" else persona_for_choice(choice)
            selected_summary.setPlainText(self._apply_dialog_persona_summary(selected))
            self._set_image_label(selected_image, str(getattr(selected, "character_image_path", "") or ""), fallback_text="New persona")
            alternate_profile.blockSignals(True)
            alternate_profile.setPlainText(str(alternates_by_row.get(row, "") or ""))
            alternate_profile.setEnabled(action == "story_profile" and selected is not None)
            alternate_profile.blockSignals(False)
            persona_gallery.blockSignals(True)
            persona_gallery.clearSelection()
            if selected is not None:
                for gallery_row in range(persona_gallery.count()):
                    gallery_item = persona_gallery.item(gallery_row)
                    if str(gallery_item.data(QtCore.Qt.UserRole) or "") == selected.id:
                        gallery_item.setSelected(True)
                        persona_gallery.scrollToItem(gallery_item)
                        break
            persona_gallery.blockSignals(False)
            result_summary.setPlainText(
                self._apply_dialog_effect_summary(
                    item,
                    payload,
                    choice=choice,
                    action=action,
                    update_existing=bool(update_existing.isChecked()),
                    clean_start=bool(clean_start.isChecked()),
                    auto_avatars=bool(auto_avatars.isChecked()),
                    avatar_style_sheets=bool(avatar_style_sheets.isChecked()),
                    allow_exceed_max=bool(allow_exceed_max.isChecked()),
                    draft_voice_path=str(draft_voice_paths_by_row.get(row, "") or ""),
                )
            )
            prompt_preview = str(draft_avatar_prompts_by_row.get(row) or item.get("avatar_prompt_override") or "").strip()
            if not prompt_preview:
                prompt_preview = self._draft_avatar_prompt_preview(item, payload)
                draft_avatar_prompts_by_row[row] = prompt_preview
            visual_prompt.blockSignals(True)
            visual_prompt.setPlainText(prompt_preview)
            visual_prompt.blockSignals(False)
            avatar_pending = row in draft_avatar_pending_rows
            draft_avatar_generate.setEnabled(bool(prompt_preview.strip()) and not avatar_pending)
            draft_avatar_regenerate.setEnabled(bool(prompt_preview.strip()) and not avatar_pending)
            set_voice_combo_path(str(draft_voice_paths_by_row.get(row, "") or ""))
            selected_voice = str(draft_voice_paths_by_row.get(row, "") or "").strip()
            if selected_voice:
                voice_status.setText(f"Selected voice: {Path(selected_voice).name}")
            else:
                voice_status.setText("No voice sample selected for this draft character.")
            status_text = str(draft_avatar_status_by_row.get(row, "") or "").strip()
            if avatar_pending:
                status_text = "Requesting draft avatar image..."
            if not status_text:
                image_path = str(item.get("character_image_path") or "").strip()
                if image_path and Path(image_path).exists():
                    status_text = "Draft avatar image is ready."
                elif image_path:
                    status_text = "Draft avatar path is set, but the file was not found."
                else:
                    status_text = "No draft avatar image yet."
            draft_avatar_status.setText(status_text)
            refresh_draft_list_item(row)

        def on_combo_changed(_index: int):
            row = int(active_row.get("value", -1))
            if row < 0 or row >= len(personas):
                return
            choice = str(persona_combo.currentData() or "__create__")
            choices_by_row[row] = choice
            if choice == "__create__":
                actions_by_row[row] = "__create__"
            elif actions_by_row.get(row) == "__create__":
                actions_by_row[row] = "story_profile"
            refresh_current_row(row)

        def on_action_changed(_index: int):
            row = int(active_row.get("value", -1))
            if row < 0 or row >= len(personas):
                return
            action = str(action_combo.currentData() or "__create__")
            actions_by_row[row] = action
            if action == "__create__":
                choices_by_row[row] = "__create__"
            elif choices_by_row.get(row) in {"", "__create__"} and self.personas:
                match = self._find_persona_for_story(personas[row])
                choices_by_row[row] = match.id if match is not None else self.personas[0].id
            refresh_current_row(row)

        def on_alternate_changed():
            row = int(active_row.get("value", -1))
            if row < 0 or row >= len(personas):
                return
            alternates_by_row[row] = alternate_profile.toPlainText().strip()

        def on_visual_prompt_changed():
            row = int(active_row.get("value", -1))
            if row < 0 or row >= len(personas):
                return
            text = str(visual_prompt.toPlainText() or "").strip()
            draft_avatar_prompts_by_row[row] = text
            avatar_pending = row in draft_avatar_pending_rows
            draft_avatar_generate.setEnabled(bool(text) and not avatar_pending)
            draft_avatar_regenerate.setEnabled(bool(text) and not avatar_pending)

        def on_voice_combo_changed(_index: int):
            row = int(active_row.get("value", -1))
            if row < 0 or row >= len(personas):
                return
            sample_path = str(voice_combo.currentData() or "").strip()
            if sample_path:
                draft_voice_paths_by_row[row] = sample_path
                voice_status.setText(f"Selected voice: {Path(sample_path).name}")
            else:
                draft_voice_paths_by_row.pop(row, None)
                voice_status.setText("No voice sample selected for this draft character.")
            refresh_current_row(row)

        def on_gallery_clicked(item):
            row = int(active_row.get("value", -1))
            if row < 0 or row >= len(personas) or item is None:
                return
            persona_id = str(item.data(QtCore.Qt.UserRole) or "")
            index = persona_combo.findData(persona_id)
            if index >= 0:
                persona_combo.setCurrentIndex(index)

        def set_draft_avatar_path(row: int, image_path: str) -> None:
            image_path = str(image_path or "").strip()
            if row < 0 or row >= len(personas) or not image_path:
                return
            personas[row]["character_image_path"] = image_path
            payload_personas = payload.get("personas")
            if isinstance(payload_personas, list) and row < len(payload_personas) and isinstance(payload_personas[row], dict):
                payload_personas[row]["character_image_path"] = image_path
            draft_avatar_paths_by_row[row] = image_path

        def finish_draft_avatar(row: int, result: Any) -> None:
            row = int(row)
            result_dict = dict(result or {}) if isinstance(result, dict) else {"ok": False, "message": str(result or "")}
            draft_avatar_pending_rows.discard(row)
            if row < 0 or row >= len(personas):
                update_apply_button_state()
                return
            image_path = str(result_dict.get("image_path") or "").strip()
            if image_path:
                set_draft_avatar_path(row, image_path)
            message = str(result_dict.get("message") or "").strip()
            draft_avatar_status_by_row[row] = message or ("Draft avatar image request accepted." if result_dict.get("ok") else "Draft avatar image request failed.")
            update_apply_button_state()
            refresh_draft_list_item(row)
            if int(active_row.get("value", -1)) == row:
                refresh_current_row(row)
            if not bool(result_dict.get("ok")):
                self._warn("Draft Avatar Image", draft_avatar_status_by_row[row])

        draft_avatar_bridge = _MprcObjectResultBridge(finish_draft_avatar, dialog)

        def request_draft_avatar(regenerate: bool = False):
            row = int(active_row.get("value", -1))
            if row < 0 or row >= len(personas):
                return
            if row in draft_avatar_pending_rows:
                return
            prompt_override = str(visual_prompt.toPlainText() or "").strip()
            if not prompt_override:
                self._warn("Draft Avatar Image", "This draft persona does not have a usable avatar prompt yet.")
                return
            draft_avatar_prompts_by_row[row] = prompt_override
            draft_avatar_pending_rows.add(row)
            draft_avatar_status_by_row[row] = "Requesting draft avatar image..."
            draft_avatar_generate.setEnabled(False)
            draft_avatar_regenerate.setEnabled(False)
            draft_avatar_status.setText(draft_avatar_status_by_row[row])
            update_apply_button_state()
            persona_payload = copy.deepcopy(personas[row])
            story_payload = copy.deepcopy(payload)

            def worker():
                try:
                    result = self._request_master_story_draft_avatar_image(
                        persona_payload,
                        story_payload,
                        regenerate=bool(regenerate),
                        prompt_override=prompt_override,
                    )
                except Exception as exc:
                    result = {"ok": False, "message": f"Draft avatar generation failed:\n\n{exc}"}
                try:
                    draft_avatar_bridge.finished.emit(row, result)
                except RuntimeError:
                    pass

            if not self._queue_visual_worker("mprc_draft_avatar_image", worker):
                finish_draft_avatar(row, {"ok": False, "message": "Draft avatar generation could not start a background worker."})

        draft_list.currentRowChanged.connect(refresh_current_row)
        persona_combo.currentIndexChanged.connect(on_combo_changed)
        action_combo.currentIndexChanged.connect(on_action_changed)
        alternate_profile.textChanged.connect(on_alternate_changed)
        visual_prompt.textChanged.connect(on_visual_prompt_changed)
        voice_combo.currentIndexChanged.connect(on_voice_combo_changed)
        persona_gallery.itemClicked.connect(on_gallery_clicked)
        draft_avatar_generate.clicked.connect(lambda *_args: request_draft_avatar(False))
        draft_avatar_regenerate.clicked.connect(lambda *_args: request_draft_avatar(True))
        preview_voice.clicked.connect(
            lambda *_args: self._preview_voice_sample(
                str(voice_combo.currentData() or ""),
                str(voice_preview_text.toPlainText() or ""),
                status_label=voice_status,
            )
        )
        for widget in (clean_start, update_existing, auto_avatars, avatar_style_sheets, allow_exceed_max):
            widget.toggled.connect(lambda *_args: refresh_current_row(int(active_row.get("value", -1))))
        if personas:
            draft_list.setCurrentRow(0)
            refresh_current_row(0)
        else:
            refresh_current_row(-1)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.Ok)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("Apply Story")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        update_apply_button_state()
        layout.addWidget(buttons)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return None
        choices: dict[str, str] = {}
        row_choices: dict[str, str] = {}
        row_actions: dict[str, str] = {}
        row_alternates: dict[str, str] = {}
        row_avatar_paths: dict[str, str] = {}
        row_avatar_prompts: dict[str, str] = {}
        row_voice_paths: dict[str, str] = {}
        for row, item in enumerate(personas):
            draft_id = normalize_persona_id(item.get("id") or item.get("display_name") or f"story_persona_{row + 1}")
            choice = str(choices_by_row.get(row, "__create__") or "__create__")
            choices[draft_id] = choice
            row_choices[str(row)] = choice
            row_actions[str(row)] = str(actions_by_row.get(row, "__create__") or "__create__")
            row_alternates[str(row)] = str(alternates_by_row.get(row, "") or "").strip()
            image_path = str(draft_avatar_paths_by_row.get(row) or item.get("character_image_path") or "").strip()
            if image_path:
                row_avatar_paths[str(row)] = image_path
            prompt_text = str(draft_avatar_prompts_by_row.get(row) or item.get("avatar_prompt_override") or "").strip()
            if prompt_text:
                row_avatar_prompts[str(row)] = prompt_text
            voice_path = str(draft_voice_paths_by_row.get(row) or "").strip()
            if voice_path:
                row_voice_paths[str(row)] = voice_path
        return {
            "persona_choices": choices,
            "persona_choices_by_row": row_choices,
            "persona_actions_by_row": row_actions,
            "persona_alternates_by_row": row_alternates,
            "draft_avatar_paths_by_row": row_avatar_paths,
            "draft_avatar_prompts_by_row": row_avatar_prompts,
            "draft_voice_paths_by_row": row_voice_paths,
            "clear_memory": bool(clean_start.isChecked()),
            "update_existing": bool(update_existing.isChecked()),
            "auto_avatars": bool(auto_avatars.isChecked()),
            "avatar_style_sheets": bool(avatar_style_sheets.isChecked()),
            "allow_exceed_max_created_characters": bool(allow_exceed_max.isChecked()),
        }

    def _apply_dialog_initial_icon(self, text: str, size: int = 64):
        from PySide6 import QtCore, QtGui

        size = max(24, int(size or 64))
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setBrush(QtGui.QColor("#162235"))
        painter.setPen(QtGui.QPen(QtGui.QColor("#36506d"), max(1, size // 28)))
        painter.drawRoundedRect(1, 1, size - 2, size - 2, max(6, size // 8), max(6, size // 8))
        initials = "".join(part[:1].upper() for part in str(text or "New").replace("_", " ").split()[:2]) or "?"
        font = painter.font()
        font.setBold(True)
        font.setPointSize(max(9, size // 4))
        painter.setFont(font)
        painter.setPen(QtGui.QColor("#dbeafe"))
        painter.drawText(pixmap.rect(), QtCore.Qt.AlignCenter, initials[:2])
        painter.end()
        return QtGui.QIcon(pixmap)

    def _apply_dialog_persona_icon(self, persona: PersonaConfig | None, size: int = 64):
        from PySide6 import QtCore, QtGui

        if persona is None:
            return self._apply_dialog_initial_icon("New", size)
        path = Path(str(getattr(persona, "character_image_path", "") or "").strip())
        if path.exists():
            pixmap = QtGui.QPixmap(str(path))
            if not pixmap.isNull():
                return QtGui.QIcon(pixmap.scaled(size, size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        return self._apply_dialog_initial_icon(str(persona.display_name or persona.id), size)

    def _apply_dialog_path_icon(self, image_path: str, size: int = 64, *, fallback_text: str = "Draft"):
        from PySide6 import QtCore, QtGui

        path = Path(str(image_path or "").strip())
        if path.exists():
            pixmap = QtGui.QPixmap(str(path))
            if not pixmap.isNull():
                return QtGui.QIcon(pixmap.scaled(size, size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        return self._apply_dialog_initial_icon(fallback_text, size)

    def _apply_dialog_default_alternate_profile(self, persona_payload: dict[str, Any]) -> str:
        draft_id = normalize_persona_id(persona_payload.get("id") or persona_payload.get("display_name") or "story_persona")
        lines = [
            f"Story name: {str(persona_payload.get('display_name') or draft_id.replace('_', ' ').title()).strip()}",
            f"Story role: {str(persona_payload.get('role') or persona_payload.get('behavior_mode') or '').strip()}",
        ]
        for label, key in (
            ("Story description", "description"),
            ("AR description", "ar_description"),
            ("Speaking style", "speaking_style"),
            ("Tone", "allowed_tone"),
        ):
            value = str(persona_payload.get(key) or "").strip()
            if value:
                lines.append(f"{label}: {value}")
        return "\n".join(line for line in lines if line.strip())

    def _apply_dialog_draft_summary(self, persona_payload: dict[str, Any], payload: dict[str, Any]) -> str:
        draft_id = normalize_persona_id(persona_payload.get("id") or persona_payload.get("display_name") or "story_persona")
        visual = persona_payload.get("visual") if isinstance(persona_payload.get("visual"), dict) else {}
        session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
        lines = [
            f"Name: {str(persona_payload.get('display_name') or draft_id.replace('_', ' ').title()).strip()}",
            f"Draft ID: {draft_id}",
            f"Role: {str(persona_payload.get('role') or persona_payload.get('behavior_mode') or 'Not specified').strip()}",
            f"Behavior: {str(persona_payload.get('behavior_mode') or 'default').strip()}",
            f"Memory scope: {str(persona_payload.get('memory_scope') or 'persona-only').strip()}",
        ]
        description = str(persona_payload.get("description") or "").strip()
        if description:
            lines.append(f"Description: {description[:360]}")
        ar_description = str(persona_payload.get("ar_description") or "").strip()
        if ar_description:
            lines.append(f"AR description: {ar_description[:360]}")
        if visual:
            visual_lines = []
            for label, key in (
                ("Visual", "character_description"),
                ("Clothing / props", "clothing_props"),
                ("Environment", "environment_style"),
            ):
                value = str(visual.get(key) or "").strip()
                if value:
                    visual_lines.append(f"{label}: {value[:240]}")
            if visual_lines:
                lines.append("Draft visual profile:")
                lines.extend(visual_lines)
        story_bits = []
        for key in ("scene_title", "location", "objective", "mood"):
            value = str(session.get(key) or payload.get(key) or "").strip()
            if value:
                story_bits.append(f"{key.replace('_', ' ').title()}: {value[:180]}")
        if story_bits:
            lines.append("Story context:")
            lines.extend(story_bits)
        return "\n".join(lines)

    def _apply_dialog_persona_summary(self, persona: PersonaConfig | None) -> str:
        if persona is None:
            return (
                "Action: Create a new persona from the drafted character.\n"
                "The new persona will receive the draft prompt, AR profile, visual profile, tags, and story link. "
                "It will not have a real voice sample until you add one in the Voice tab."
            )
        voice_sample = str(getattr(persona.voice, "sample_path", "") or "").strip()
        voice_ready = bool(getattr(persona.voice, "enabled", False) and voice_sample and Path(voice_sample).exists())
        image_path = str(getattr(persona, "character_image_path", "") or "").strip()
        image_ready = bool(image_path and Path(image_path).exists())
        lines = [
            f"Existing persona: {persona.display_name} ({persona.id})",
            f"Role: {persona.role or persona.behavior_mode or 'Not specified'}",
            f"Voice: {'ready' if voice_ready else ('enabled but missing sample' if getattr(persona.voice, 'enabled', False) else 'off')}",
            f"Avatar image: {'ready' if image_ready else 'missing'}",
            f"Memory: {persona.memory_scope or 'default'}",
            f"Behavior: {persona.behavior_mode or 'default'}",
        ]
        if persona.description:
            lines.append(f"Description: {persona.description[:320]}")
        involvement = self._current_character_story_text(persona)
        if involvement:
            lines.append(involvement)
        return "\n".join(lines)

    def _apply_dialog_effect_summary(
        self,
        persona_payload: dict[str, Any],
        payload: dict[str, Any],
        *,
        choice: str,
        action: str = "",
        update_existing: bool,
        clean_start: bool,
        auto_avatars: bool,
        avatar_style_sheets: bool = False,
        allow_exceed_max: bool = False,
        draft_voice_path: str = "",
    ) -> str:
        action = str(action or ("__create__" if str(choice or "") in {"", "__create__"} else "story_profile")).strip()
        selected = self.persona_by_id(choice) if action != "__create__" and str(choice or "") not in {"", "__create__"} else None
        draft_name = str(persona_payload.get("display_name") or persona_payload.get("id") or "Draft character").strip()
        lines = []
        if action == "__create__" or selected is None:
            lines.extend(
                [
                    f"Create: {draft_name}",
                    "A fresh persona will be created from the draft.",
                    "Prompt, AR profile, visual profile, tags, behavior, and story link come from the draft.",
                    f"Avatar request: {'will be requested through Visual Reply' if auto_avatars else 'will be skipped'} for the new persona.",
                    f"Avatar style sheet: {'will be requested after an avatar image exists' if avatar_style_sheets else 'will be skipped'} for the new persona.",
                ]
            )
        elif action == "reuse_as_is":
            lines.extend(
                [
                    f"Use as-is: {selected.display_name} ({selected.id})",
                    "The story will link this drafted character to the selected existing persona.",
                    "No base persona prompt, visual profile, avatar, or voice fields will be changed.",
                    "No story-only alternate profile will be stored for this character.",
                ]
            )
        elif action == "reuse_update":
            draft_has_image = bool(str(persona_payload.get("character_image_path") or "").strip())
            lines.extend(
                [
                    f"Update: {selected.display_name} ({selected.id})",
                    "The story will link this drafted character to the selected existing persona.",
                    "Voice sample: kept from the existing persona.",
                    "Avatar picture: kept from the existing persona unless the draft contains a non-empty replacement path.",
                    f"Draft has replacement picture path: {'yes' if draft_has_image else 'no'}.",
                    "Prompt/profile update: draft fields will update this persona.",
                ]
            )
        else:
            draft_has_image = bool(str(persona_payload.get("character_image_path") or "").strip())
            lines.extend(
                [
                    f"Story-only alternate profile: {selected.display_name} ({selected.id})",
                    "The story will link this drafted character to the selected existing persona.",
                    "Base persona fields, voice, and avatar image stay unchanged.",
                    "The draft role, descriptions, AR profile, visual prompt, and editable story-only notes are saved as story-specific persona info.",
                    f"Draft has replacement picture path: {'yes' if draft_has_image else 'no'}.",
                    "Prompt/profile update: story-only for this Master Story.",
                ]
            )
        story_title = str(payload.get("title") or payload.get("id") or "this Master Story").strip()
        lines.append(f"Story link: character will be linked to {story_title}.")
        lines.append(f"Memory: {'old MPRC story memory will be cleared first' if clean_start else 'existing MPRC memory will be kept'} before applying.")
        if action == "__create__" or selected is None:
            max_created = self._control_int_value("master_story_max_created_characters", 8, 1, 40)
            lines.append(
                f"Creation limit: {'override enabled' if allow_exceed_max else f'max {max_created} new persona(s)'} for this apply."
            )
        voice_path = str(draft_voice_path or "").strip()
        if voice_path:
            lines.append(f"Voice: {Path(voice_path).name} will be assigned to the resulting persona.")
        else:
            lines.append("Voice: no new voice sample selected for this draft character.")
        return "\n".join(lines)

    def _draft_avatar_prompt_preview(self, persona_payload: dict[str, Any], payload: dict[str, Any]) -> str:
        override = str((persona_payload or {}).get("avatar_prompt_override") or "").strip()
        if override:
            return override
        persona = PersonaConfig.from_dict(persona_payload)
        self._fill_story_visual_profile(persona, persona_payload)
        return self._story_avatar_prompt(persona, payload)

    def _request_master_story_draft_avatar_image(
        self,
        persona_payload: dict[str, Any],
        payload: dict[str, Any],
        *,
        regenerate: bool = False,
        prompt_override: str = "",
    ) -> dict[str, Any]:
        draft_id = normalize_persona_id(persona_payload.get("id") or persona_payload.get("display_name") or "story_persona")
        existing_path = str(persona_payload.get("character_image_path") or "").strip()
        if existing_path and Path(existing_path).exists() and not bool(regenerate):
            return {
                "ok": True,
                "image_path": existing_path,
                "message": "Draft avatar image is already ready. Use Regenerate to request a fresh one.",
            }
        service = self.visual_reply_service
        if service is None or not hasattr(service, "request_generation"):
            self._record_visual_debug(
                source="master_story_draft_avatar",
                reason="draft_avatar",
                accepted=False,
                message="Draft avatar generation skipped because the Visual Reply service is unavailable.",
            )
            return {
                "ok": False,
                "message": "Visual Reply generation service is unavailable. Open Visual Reply or choose an avatar image later.",
            }
        persona = PersonaConfig.from_dict(persona_payload)
        self._fill_story_visual_profile(persona, persona_payload)
        prompt = str(prompt_override or "").strip() or self._story_avatar_prompt(persona, payload)
        if not prompt:
            self._record_visual_debug(
                source="master_story_draft_avatar",
                reason="draft_avatar",
                persona=persona,
                accepted=False,
                message="Draft avatar generation skipped because the draft has no usable visual prompt.",
            )
            return {"ok": False, "message": "This draft persona does not have a usable avatar prompt yet."}
        self._record_visual_debug(
            source="master_story_draft_avatar",
            reason="draft_avatar",
            persona=persona,
            accepted=None,
            message="Master Story draft avatar request sent to Visual Reply.",
            prompt=prompt,
        )
        try:
            result = service.request_generation(
                prompt=prompt,
                caption=f"MPRC draft avatar: {persona.display_name}",
                provider=str(persona.visual.provider or "inherit"),
                model=str(persona.visual.model or ""),
                size="1024x1024",
                source="nc.multi_persona_roleplay.master_story_draft_avatar",
                metadata={
                    "draft_id": draft_id,
                    "story_id": str(payload.get("id") or ""),
                    "story_title": str(payload.get("title") or ""),
                    "purpose": "draft_story_avatar",
                    "regenerate": bool(regenerate),
                },
                auto_show=True,
            )
        except Exception as exc:
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[MPRC] Master Story draft avatar generation failed for %s: %s", draft_id, exc)
            self._record_visual_debug(
                source="master_story_draft_avatar",
                reason="draft_avatar",
                persona=persona,
                accepted=False,
                message=f"Master Story draft avatar generation failed: {exc}",
                prompt=prompt,
            )
            return {"ok": False, "message": f"Draft avatar generation failed:\n\n{exc}"}
        image_path = str(result.get("image_path") or "").strip() if isinstance(result, dict) else ""
        if image_path and Path(image_path).exists():
            self._record_visual_debug(
                source="master_story_draft_avatar",
                reason="draft_avatar",
                persona=persona,
                accepted=True,
                message=f"Master Story draft avatar generated: {image_path}",
                prompt=prompt,
            )
            return {"ok": True, "image_path": image_path, "message": "Draft avatar image generated."}
        if result:
            self._record_visual_debug(
                source="master_story_draft_avatar",
                reason="draft_avatar",
                persona=persona,
                accepted=True,
                message="Visual Reply accepted the draft avatar request, but no image path was returned yet.",
                prompt=prompt,
            )
            return {
                "ok": True,
                "image_path": "",
                "message": "Visual Reply accepted the draft avatar request, but no image path was returned yet.",
            }
        self._record_visual_debug(
            source="master_story_draft_avatar",
            reason="draft_avatar",
            persona=persona,
            accepted=False,
            message="Visual Reply did not accept the Master Story draft avatar request.",
            prompt=prompt,
        )
        return {"ok": False, "message": "Visual Reply did not accept the draft avatar request."}

    def _apply_master_story_payload(self, payload: dict[str, Any], apply_plan: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = self._normalize_master_story_payload(payload)
        apply_plan = dict(apply_plan or {})
        if not bool(apply_plan.get("skip_backup", False)):
            self._save_pre_apply_backup(str(apply_plan.get("backup_reason") or "Apply Draft"))
        auto_create = bool(apply_plan.get("auto_create", self._control_checked("master_story_auto_create", True)))
        update_existing = bool(apply_plan.get("update_existing", self._control_checked("master_story_update_existing", True)))
        auto_avatars = bool(apply_plan.get("auto_avatars", self._control_checked("master_story_auto_avatars", True)))
        avatar_style_sheets = bool(apply_plan.get("avatar_style_sheets", self._control_checked("master_story_avatar_style_sheets", False)))
        allow_exceed_max = bool(apply_plan.get("allow_exceed_max_created_characters", self._master_story_allow_exceed_max_created_characters()))
        if bool(apply_plan.get("clear_memory", self._control_checked("master_story_clear_memory", True))):
            self._clear_master_story_runtime_state(clear_long_memory=True, enabled=True)
        persona_choices = dict(apply_plan.get("persona_choices") or {})
        persona_choices_by_row = dict(apply_plan.get("persona_choices_by_row") or {})
        persona_actions_by_row = dict(apply_plan.get("persona_actions_by_row") or {})
        persona_alternates_by_row = dict(apply_plan.get("persona_alternates_by_row") or {})
        draft_avatar_paths_by_row = dict(apply_plan.get("draft_avatar_paths_by_row") or {})
        draft_avatar_prompts_by_row = dict(apply_plan.get("draft_avatar_prompts_by_row") or {})
        draft_voice_paths_by_row = dict(apply_plan.get("draft_voice_paths_by_row") or {})
        saved_overrides = payload.get("persona_overrides") if isinstance(payload.get("persona_overrides"), dict) else {}
        max_created = self._control_int_value("master_story_max_created_characters", 8, 1, 40)
        linked_ids: list[str] = []
        created_ids: list[str] = []
        story_id_map: dict[str, str] = {}
        story_overrides: dict[str, dict[str, Any]] = {}
        created = 0
        updated = 0
        voice_assigned = 0
        skipped: list[str] = []
        for row, item in enumerate(list(payload.get("personas") or [])):
            if not isinstance(item, dict):
                continue
            item = dict(item)
            payload_personas = payload.get("personas")
            draft_avatar_path = str(draft_avatar_paths_by_row.get(str(row)) or draft_avatar_paths_by_row.get(row) or "").strip()
            if draft_avatar_path:
                item["character_image_path"] = draft_avatar_path
                if isinstance(payload_personas, list) and row < len(payload_personas) and isinstance(payload_personas[row], dict):
                    payload_personas[row]["character_image_path"] = draft_avatar_path
            draft_avatar_prompt = str(draft_avatar_prompts_by_row.get(str(row)) or draft_avatar_prompts_by_row.get(row) or "").strip()
            if draft_avatar_prompt:
                item["avatar_prompt_override"] = draft_avatar_prompt
                if isinstance(payload_personas, list) and row < len(payload_personas) and isinstance(payload_personas[row], dict):
                    payload_personas[row]["avatar_prompt_override"] = draft_avatar_prompt
            draft_voice_path = str(draft_voice_paths_by_row.get(str(row)) or draft_voice_paths_by_row.get(row) or "").strip()
            if draft_voice_path:
                voice_payload = dict(item.get("voice") or {}) if isinstance(item.get("voice"), dict) else {}
                voice_payload["enabled"] = True
                voice_payload["sample_path"] = draft_voice_path
                voice_payload.setdefault("backend", "inherit")
                item["voice"] = voice_payload
                if isinstance(payload_personas, list) and row < len(payload_personas) and isinstance(payload_personas[row], dict):
                    payload_personas[row]["voice"] = dict(voice_payload)
            draft_id = normalize_persona_id(item.get("id") or item.get("display_name") or "")
            choice = str(persona_choices_by_row.get(str(row), persona_choices.get(draft_id, "")) or "").strip()
            action = str(persona_actions_by_row.get(str(row), "") or "").strip()
            if not action:
                action = "__create__" if choice == "__create__" else ("reuse_update" if update_existing else "story_profile")
            match = None if action == "__create__" or choice == "__create__" else self.persona_by_id(choice)
            if action != "__create__" and match is None and choice not in {"__create__", ""}:
                skipped.append(str(item.get("display_name") or item.get("id") or "persona"))
                continue
            if match is None and action != "__create__" and choice != "__create__":
                match = self._find_persona_for_story(item)
            if action == "reuse_update" and match is not None and isinstance(saved_overrides.get(match.id), dict):
                action = "story_profile"
            if match is not None:
                linked_ids.append(match.id)
                if draft_id:
                    story_id_map[draft_id] = match.id
                if action == "reuse_update":
                    self._merge_story_persona(match, item)
                    updated += 1
                elif action == "story_profile":
                    if isinstance(saved_overrides.get(match.id), dict):
                        story_overrides[match.id] = dict(saved_overrides.get(match.id) or {})
                    else:
                        story_overrides[match.id] = self._story_persona_override_from_draft(
                            match,
                            item,
                            payload,
                            alternate_text=str(persona_alternates_by_row.get(str(row), "") or ""),
                        )
                if draft_voice_path and self._apply_story_voice_sample(match, draft_voice_path):
                    voice_assigned += 1
                continue
            create_allowed = bool(auto_create or action == "__create__" or choice == "__create__")
            if not create_allowed:
                skipped.append(str(item.get("display_name") or item.get("id") or "persona"))
                continue
            if not allow_exceed_max and created >= max_created:
                skipped.append(f"{str(item.get('display_name') or item.get('id') or 'persona')} (creation limit)")
                continue
            persona_payload = dict(item)
            persona_payload["id"] = unique_persona_id(persona_payload.get("id") or persona_payload.get("display_name") or "story_persona", {p.id for p in self.personas})
            if payload.get("mode") == AR_MODE:
                persona_payload["ar_profile_enabled"] = True
            persona = PersonaConfig.from_dict(persona_payload)
            self._fill_story_visual_profile(persona, persona_payload)
            if draft_avatar_prompt:
                setattr(persona, "_mprc_avatar_prompt_override", draft_avatar_prompt)
            self.personas.append(persona)
            linked_ids.append(persona.id)
            created_ids.append(persona.id)
            if draft_voice_path and str(getattr(persona.voice, "sample_path", "") or "").strip():
                voice_assigned += 1
            if draft_id:
                story_id_map[draft_id] = persona.id
            created += 1
        payload_overrides = payload.get("persona_overrides")
        if isinstance(payload_overrides, dict):
            for key, value in payload_overrides.items():
                persona_id = normalize_persona_id(key)
                if persona_id and isinstance(value, dict) and persona_id in linked_ids:
                    story_overrides.setdefault(persona_id, dict(value))
        if not linked_ids and self.personas:
            linked_ids = [self.personas[0].id]

        session_payload = dict(payload.get("session") or {}) if isinstance(payload.get("session"), dict) else {}
        self.session.enabled = True
        self.session.mode = str(payload.get("mode") or session_payload.get("mode") or self.session.mode or "Narrator + characters")
        if self.session.mode not in SESSION_MODES:
            self.session.mode = AR_MODE if self._control_checked("master_story_use_ar", True) else "Narrator + characters"
        self.session.active_persona_id = self._story_persona_id(payload.get("active_persona_id"), linked_ids, id_map=story_id_map)
        self.session.current_speaker_id = self._story_persona_id(payload.get("current_speaker_id"), linked_ids, fallback=self.session.active_persona_id, id_map=story_id_map)
        for key in ("scene_title", "location", "time_of_day", "mood", "objective", "scene_summary"):
            value = str(session_payload.get(key) or "").strip()
            if value:
                setattr(self.session, key, value)
        if not self.session.scene_summary and str(payload.get("summary") or "").strip():
            self.session.scene_summary = str(payload.get("summary") or "").strip()
        self.session.auto_select_speaker = len(linked_ids) > 1
        self.session.keep_scene_continuity = True
        self.session.update_scene_after_reply = True
        self.session.character_state_summaries = self._story_character_summaries(linked_ids)

        if self.session.mode == AR_MODE:
            from .models import AlternativeRealityState

            self.session.ar_use_persona_profiles = True
            pacing = str(session_payload.get("ar_pacing") or "").strip()
            interaction = str(session_payload.get("ar_interaction_frequency") or "").strip()
            if pacing in AR_PACING_MODES:
                self.session.ar_pacing = pacing
            if interaction in AR_INTERACTION_FREQUENCIES:
                self.session.ar_interaction_frequency = interaction
            ar_payload = dict(session_payload.get("ar_state") or {}) if isinstance(session_payload.get("ar_state"), dict) else {}
            raw_characters = ar_payload.get("active_characters")
            if isinstance(raw_characters, list):
                ar_payload["active_characters"] = [
                    story_id_map.get(normalize_persona_id(item), normalize_persona_id(item))
                    for item in raw_characters
                    if str(item or "").strip()
                ]
            state = AlternativeRealityState.from_dict(ar_payload)
            if not state.active_characters:
                state.active_characters = linked_ids[:6]
            if not state.current_scene:
                state.current_scene = self.session.scene_title or self.session.scene_summary
            if not state.location:
                state.location = self.session.location
            if not state.story_goal:
                state.story_goal = self.session.objective
            if not state.mood:
                state.mood = self.session.mood
            if not state.time_of_day:
                state.time_of_day = self.session.time_of_day
            self.session.ar_state = state
            self.ensure_ar_state()

        narrator_raw = (
            payload.get("narrator_persona_id")
            or session_payload.get("narrator_persona_id")
            or payload.get("selected_narrator_id")
            or ""
        )
        narrator_id = story_id_map.get(normalize_persona_id(narrator_raw), normalize_persona_id(narrator_raw)) if str(narrator_raw or "").strip() else ""
        if not narrator_id or self.persona_by_id(narrator_id) is None:
            narrator_id = next(
                (
                    persona_id for persona_id in linked_ids
                    if self._persona_looks_like_narrator(self.persona_by_id(persona_id))
                ),
                "",
            )
        if not narrator_id and self.session.mode == AR_MODE and linked_ids:
            narrator_id = linked_ids[0]
        if narrator_id and self.persona_by_id(narrator_id) is not None:
            self.settings["narrator_persona_id"] = narrator_id
            self.settings["narrator_persona_mode"] = "explicit"
            payload["narrator_persona_id"] = narrator_id
            payload["narrator_persona_mode"] = "explicit"
            session_payload["narrator_persona_id"] = narrator_id
            session_payload["narrator_persona_mode"] = "explicit"
            payload["session"] = session_payload
        activation_result = self._sync_story_persona_activation(linked_ids, narrator_id=narrator_id)

        self._master_story_draft = payload
        self.settings["last_master_story_id"] = payload.get("id")
        self.settings["last_master_story_title"] = payload.get("title")
        self.settings["master_story_linked_persona_ids"] = linked_ids
        self.settings["master_story_created_persona_ids"] = created_ids
        self.settings["master_story_persona_overrides"] = story_overrides
        payload["persona_overrides"] = story_overrides
        self.storage.save_settings(self.settings)
        self.save_state()
        avatar_result = self._queue_story_avatar_generation(
            created_ids,
            payload,
            avatar_enabled=auto_avatars,
            style_sheet_enabled=avatar_style_sheets,
        )
        style_sheet_result = ""
        self.refresh_ui()
        message = f"Applied story '{payload.get('title')}'. Linked {len(linked_ids)} persona(s), created {created}, updated {updated}."
        if voice_assigned:
            message += f" Assigned {voice_assigned} voice sample(s)."
        if activation_result.get("voices_enabled"):
            message += f" Enabled {activation_result.get('voices_enabled')} existing story voice(s)."
        if activation_result.get("enabled") or activation_result.get("disabled"):
            message += (
                f" Story persona filter enabled {activation_result.get('enabled', 0)}"
                f" and disabled {activation_result.get('disabled', 0)} non-story persona(s)."
            )
        if avatar_result:
            message += " " + avatar_result
        if style_sheet_result:
            message += " " + style_sheet_result
        limit_skipped = [item for item in skipped if "(creation limit)" in item]
        other_skipped = [item for item in skipped if "(creation limit)" not in item]
        if limit_skipped:
            message += (
                f" Creation limit {max_created} skipped {len(limit_skipped)} draft persona(s). "
                "Enable Allow exceeding max created characters to create more."
            )
        if other_skipped:
            message += f" Skipped personas: {', '.join(other_skipped[:5])}."
        if skipped:
            self._record_story_event(f"persona skipped: {', '.join(skipped[:8])}", severity="warning", kind="persona", persist=True)
        self._set_master_story_status(message)
        logger = getattr(self.context, "logger", None)
        if logger is not None:
            logger.info("[MPRC] Applied Master Story id=%s linked=%s created=%s updated=%s", payload.get("id"), len(linked_ids), created, updated)
        return {"linked": linked_ids, "created": created, "updated": updated, "skipped": skipped}

    def _find_persona_for_story(self, persona_payload: dict[str, Any]) -> PersonaConfig | None:
        wanted_id = normalize_persona_id(persona_payload.get("id") or "")
        wanted_name = str(persona_payload.get("display_name") or "").strip().lower()
        for persona in self.personas:
            if wanted_id and persona.id == wanted_id:
                return persona
        if wanted_name:
            for persona in self.personas:
                if persona.display_name.strip().lower() == wanted_name:
                    return persona
        return None

    def _apply_story_voice_sample(self, persona: PersonaConfig | None, sample_path: str) -> bool:
        if persona is None:
            return False
        sample = str(sample_path or "").strip()
        if not sample:
            return False
        persona.voice.enabled = True
        persona.voice.sample_path = sample
        if persona.voice.backend not in VOICE_BACKENDS:
            persona.voice.backend = "inherit"
        return True

    def _sync_story_persona_activation(self, linked_ids: list[str], *, narrator_id: str = "") -> dict[str, int]:
        known = {persona.id for persona in self.personas}
        active_ids = [
            persona_id
            for persona_id in list(dict.fromkeys(normalize_persona_id(item) for item in list(linked_ids or []) if str(item or "").strip()))
            if persona_id in known
        ]
        narrator = normalize_persona_id(narrator_id or self.selected_narrator_persona_id())
        if narrator and narrator in known and narrator not in active_ids:
            active_ids.append(narrator)
        if not active_ids:
            return {"enabled": 0, "disabled": 0, "voices_enabled": 0}
        active_set = set(active_ids)
        enabled_count = 0
        disabled_count = 0
        voices_enabled = 0
        for persona in self.personas:
            desired_enabled = persona.id in active_set
            if bool(getattr(persona, "enabled", True)) != desired_enabled:
                persona.enabled = desired_enabled
                if desired_enabled:
                    enabled_count += 1
                else:
                    disabled_count += 1
            voice = getattr(persona, "voice", None)
            if persona.id in active_set and voice is not None:
                sample = str(getattr(voice, "sample_path", "") or "").strip()
                if sample and not bool(getattr(voice, "enabled", False)):
                    voice.enabled = True
                    voices_enabled += 1
                if sample and str(getattr(voice, "backend", "") or "").strip() not in VOICE_BACKENDS:
                    voice.backend = "inherit"
        if self.session.active_persona_id not in active_set:
            self.session.active_persona_id = active_ids[0]
        if self.session.current_speaker_id not in active_set:
            self.session.current_speaker_id = self.session.active_persona_id
        if self._voice_follows_active():
            self.settings["voice_edit_persona_id"] = self.session.active_persona_id
        self.settings["current_character_view_mode"] = "active_story"
        return {"enabled": enabled_count, "disabled": disabled_count, "voices_enabled": voices_enabled}

    def _merge_story_persona(self, target: PersonaConfig, persona_payload: dict[str, Any]) -> None:
        text_fields = (
            "display_name",
            "role",
            "description",
            "character_image_path",
            "system_prompt",
            "ar_description",
            "ar_system_prompt",
            "speaking_style",
            "allowed_tone",
            "response_length",
            "temperature_hint",
            "memory_scope",
            "behavior_mode",
        )
        for field in text_fields:
            if field not in persona_payload:
                continue
            value = str(persona_payload.get(field) or "").strip()
            if value:
                setattr(target, field, value)
        if "ar_profile_enabled" in persona_payload:
            target.ar_profile_enabled = bool(persona_payload.get("ar_profile_enabled"))
        elif self._control_checked("master_story_use_ar", True):
            target.ar_profile_enabled = True
        tags = persona_payload.get("tags")
        if isinstance(tags, list):
            cleaned = [str(item).strip().lower() for item in tags if str(item).strip()]
            if cleaned:
                target.tags = cleaned[:12]
        visual = persona_payload.get("visual")
        if isinstance(visual, dict):
            if any(str(visual.get(field) or "").strip() for field in ("character_description", "clothing_props", "environment_style")):
                target.visual.enabled = bool(visual.get("enabled", True))
                if not target.visual.mode or target.visual.mode == "off":
                    target.visual.mode = "manual"
            for field in ("character_description", "clothing_props", "environment_style", "negative_prompt", "style_preset"):
                value = str(visual.get(field) or "").strip()
                if value:
                    setattr(target.visual, field, value)

    def _fill_story_visual_profile(self, persona: PersonaConfig, persona_payload: dict[str, Any]) -> None:
        visual = persona_payload.get("visual")
        if isinstance(visual, dict) and any(str(visual.get(field) or "").strip() for field in ("character_description", "clothing_props", "environment_style")):
            persona.visual.enabled = bool(visual.get("enabled", True))
            if persona.visual.mode == "off":
                persona.visual.mode = "manual"
            return
        appearance = str(
            persona_payload.get("visual_description")
            or persona_payload.get("appearance")
            or persona_payload.get("avatar_description")
            or ""
        ).strip()
        if appearance:
            persona.visual.enabled = True
            persona.visual.mode = "manual"
            persona.visual.character_description = appearance

    def _queue_story_avatar_generation(
        self,
        created_ids: list[str],
        payload: dict[str, Any],
        *,
        avatar_enabled: bool,
        style_sheet_enabled: bool,
    ) -> str:
        persona_ids = [str(item or "").strip() for item in list(created_ids or []) if str(item or "").strip()]
        if not persona_ids or not (bool(avatar_enabled) or bool(style_sheet_enabled)):
            return ""
        service = self.visual_reply_service
        if service is None or not hasattr(service, "request_generation"):
            self._record_visual_debug(
                source="master_story_avatar",
                reason="story_avatar",
                accepted=False,
                message="Avatar generation skipped because the Visual Reply service is unavailable.",
            )
            return "Avatar generation skipped: Visual Reply service is unavailable."
        payload_snapshot = copy.deepcopy(payload)

        def worker():
            messages: list[str] = []
            accepted = False
            try:
                if avatar_enabled:
                    avatar_message = self._generate_story_avatar_images(persona_ids, payload_snapshot, enabled=True)
                    if avatar_message:
                        messages.append(avatar_message)
                        accepted = accepted or "failed" not in avatar_message.lower()
                if style_sheet_enabled:
                    sheet_message = self._generate_story_avatar_style_sheets(persona_ids, payload_snapshot, enabled=True)
                    if sheet_message:
                        messages.append(sheet_message)
                        accepted = accepted or "failed" not in sheet_message.lower()
            except Exception as exc:
                messages.append(f"Avatar generation failed: {exc}")
                accepted = False
            self._emit_manual_visual_finished(
                "story_avatar_batch",
                "",
                {
                    "accepted": accepted,
                    "message": " ".join(message for message in messages if message).strip() or "No avatar requests were needed.",
                },
            )

        if self._queue_visual_worker("mprc_story_avatar_batch", worker):
            queued = []
            if avatar_enabled:
                queued.append("avatar image")
            if style_sheet_enabled:
                queued.append("avatar style sheet")
            return f"Queued {' and '.join(queued)} generation in background."
        return "Avatar generation could not start a background worker."

    def _generate_story_avatar_images(self, created_ids: list[str], payload: dict[str, Any], *, enabled: bool | None = None) -> str:
        if enabled is None:
            enabled = self._control_checked("master_story_auto_avatars", True)
        if not created_ids or not bool(enabled):
            return ""
        service = self.visual_reply_service
        if service is None or not hasattr(service, "request_generation"):
            self._record_visual_debug(
                source="master_story_avatar",
                reason="story_avatar",
                accepted=False,
                message="Avatar generation skipped because the Visual Reply service is unavailable.",
            )
            return "Avatar generation skipped: Visual Reply service is unavailable."
        by_id = {persona.id: persona for persona in self.personas}
        generated = 0
        accepted = 0
        failed = 0
        for persona_id in created_ids[:6]:
            persona = by_id.get(persona_id)
            if persona is None or str(persona.character_image_path or "").strip():
                continue
            prompt = self._story_avatar_prompt(persona, payload)
            if not prompt:
                continue
            self._record_visual_debug(
                source="master_story_avatar",
                reason="story_avatar",
                persona=persona,
                accepted=None,
                message="Master Story avatar request sent to Visual Reply.",
                prompt=prompt,
            )
            try:
                result = service.request_generation(
                    prompt=prompt,
                    caption=f"MPRC avatar: {persona.display_name}",
                    provider=str(persona.visual.provider or "inherit"),
                    model=str(persona.visual.model or ""),
                    size="1024x1024",
                    source="nc.multi_persona_roleplay.master_story_avatar",
                    metadata={
                        "persona_id": persona.id,
                        "story_id": str(payload.get("id") or ""),
                        "purpose": "story_avatar",
                    },
                    auto_show=False,
                )
            except Exception as exc:
                failed += 1
                logger = getattr(self.context, "logger", None)
                if logger is not None:
                    logger.warning("[MPRC] Master Story avatar generation failed for %s: %s", persona.id, exc)
                self._record_visual_debug(
                    source="master_story_avatar",
                    reason="story_avatar",
                    persona=persona,
                    accepted=False,
                    message=f"Master Story avatar generation failed: {exc}",
                    prompt=prompt,
                )
                continue
            if not result:
                failed += 1
                self._record_visual_debug(
                    source="master_story_avatar",
                    reason="story_avatar",
                    persona=persona,
                    accepted=False,
                    message="Visual Reply did not accept the Master Story avatar request.",
                    prompt=prompt,
                )
                continue
            accepted += 1
            image_path = str(result.get("image_path") or "").strip() if isinstance(result, dict) else ""
            self._record_visual_debug(
                source="master_story_avatar",
                reason="story_avatar",
                persona=persona,
                accepted=True,
                message=f"Master Story avatar accepted{': ' + image_path if image_path else '; no image path returned yet'}.",
                prompt=prompt,
            )
            if image_path and Path(image_path).exists():
                persona.character_image_path = image_path
                generated += 1
        if generated:
            self.save_state()
            return f"Created {generated} avatar image(s) for new persona(s)."
        if accepted:
            return "Avatar image requests were accepted; choose generated images from Visual Reply if no file path was returned."
        if failed:
            return f"Avatar generation failed for {failed} new persona(s)."
        return ""

    def _generate_story_avatar_style_sheets(self, created_ids: list[str], payload: dict[str, Any], *, enabled: bool | None = None) -> str:
        if enabled is None:
            enabled = self._control_checked("master_story_avatar_style_sheets", False)
        if not created_ids or not bool(enabled):
            return ""
        service = self.visual_reply_service
        if service is None or not hasattr(service, "request_generation"):
            return "Avatar style sheets skipped: Visual Reply service is unavailable."
        by_id = {persona.id: persona for persona in self.personas}
        accepted = 0
        generated = 0
        failed = 0
        skipped_no_image = 0
        saved: dict[str, Any] = dict(self.settings.get("persona_avatar_style_sheets") or {}) if isinstance(self.settings.get("persona_avatar_style_sheets"), dict) else {}
        for persona_id in created_ids[:6]:
            persona = by_id.get(persona_id)
            if persona is None:
                continue
            image_path = str(persona.character_image_path or "").strip()
            if not image_path or not Path(image_path).exists():
                skipped_no_image += 1
                continue
            prompt = self._story_avatar_style_sheet_prompt(persona, payload, image_path=image_path)
            if not prompt:
                continue
            try:
                result = service.request_generation(
                    prompt=prompt,
                    caption=f"MPRC avatar style sheet: {persona.display_name}",
                    provider=str(persona.visual.provider or "inherit"),
                    model=str(persona.visual.model or ""),
                    size="inherit",
                    source="nc.multi_persona_roleplay.avatar_style_sheet",
                    metadata={
                        "persona_id": persona.id,
                        "story_id": str(payload.get("id") or ""),
                        "purpose": "character_reference_sheet",
                        "reference_image_path": image_path,
                        "requires_image_to_image": True,
                    },
                    auto_show=False,
                )
            except Exception as exc:
                failed += 1
                logger = getattr(self.context, "logger", None)
                if logger is not None:
                    logger.warning("[MPRC] Avatar style sheet generation failed for %s: %s", persona.id, exc)
                continue
            if not result:
                failed += 1
                continue
            accepted += 1
            result_path = str(result.get("image_path") or "").strip() if isinstance(result, dict) else ""
            saved[persona.id] = {
                "story_id": str(payload.get("id") or ""),
                "story_title": str(payload.get("title") or ""),
                "reference_image_path": image_path,
                "style_sheet_path": result_path,
                "prompt": prompt,
                "updated_at": QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate),
            }
            if result_path and Path(result_path).exists():
                generated += 1
        if accepted or generated:
            self.settings["persona_avatar_style_sheets"] = saved
            self.storage.save_settings(self.settings)
        if generated:
            return f"Created {generated} avatar style sheet(s) for new persona(s)."
        if accepted:
            return "Avatar style sheet requests were accepted; image-to-image quality depends on the Visual Reply provider/workflow."
        if skipped_no_image:
            return f"Avatar style sheets skipped for {skipped_no_image} new persona(s) without a ready avatar image."
        if failed:
            return f"Avatar style sheet generation failed for {failed} new persona(s)."
        return ""

    def _story_avatar_style_sheet_prompt(self, persona: PersonaConfig, payload: dict[str, Any], *, image_path: str = "") -> str:
        story_title = str(payload.get("title") or self.session.scene_title or "story").strip()
        visual_direction_widget = self._controls.get("master_story_visual_direction")
        visual_direction = str(visual_direction_widget.toPlainText() if visual_direction_widget is not None else "").strip()
        if not visual_direction:
            visual_direction = str(payload.get("avatar_visual_direction") or "").strip()
        description = ". ".join(
            str(item or "").strip(" .")
            for item in (
                persona.display_name,
                persona.role,
                persona.description,
                persona.ar_description,
                persona.visual.character_description,
                persona.visual.clothing_props,
                persona.visual.environment_style,
                visual_direction,
                f"story: {story_title}",
            )
            if str(item or "").strip()
        )
        reference_line = f"Main image reference path for image-to-image capable runtimes: {image_path}" if image_path else "Main image reference: use the current avatar image when the runtime supports image-to-image."
        prompt = f"""
Create a highly detailed, professional character reference sheet for an original avatar character.

The reference sheet must include at least 8 different facial expressions/emotions displayed clearly, plus multiple body angles.

Facial expressions, minimum 8:
- Neutral / calm
- Happy / smiling
- Grinning / playful
- Angry / furious
- Sad / tearful
- Surprised / shocked
- Smug / confident
- Disgusted / annoyed
- Bonus expressions if useful: flustered, seductive, determined, focused, wary, or embarrassed

Body and pose views:
- Front view, full body, standing naturally
- Side profile, left and right
- 3/4 angle, front and back
- Back view
- Dynamic/action pose

Visual requirements:
- Perfect consistency in character design across all angles and expressions
- Accurate hairstyle, hair color, eye color and shape, skin tone, facial features, markings, tattoos, scars, piercings, jewelry, clothing details, accessories, and signature items
- Clean close-up insets for important design elements such as eyes, unique accessories, clothing patterns, weapons, symbols, or props
- Clear color palette with excellent lighting

Style:
- Clean, modern anime/game/VTuber-style character reference sheet
- White or light neutral background
- Sharp lines, highly detailed, professional quality

Input provided:
- {reference_line}
- Short character description: {description}

Generate a comprehensive character card that fully showcases the avatar from every important angle while prominently featuring at least 8 distinct facial expressions and all unique design features.
""".strip()
        return prompt[:3600].rstrip(" \t\r\n,;:.-")

    def _story_avatar_prompt(self, persona: PersonaConfig, payload: dict[str, Any]) -> str:
        override = str(getattr(persona, "_mprc_avatar_prompt_override", "") or "").strip()
        if not override:
            override = self._story_avatar_prompt_override_for_persona(persona, payload)
        if override:
            return override[:1200].rstrip(" \t\r\n,;:.-")
        visual_direction_widget = self._controls.get("master_story_visual_direction")
        visual_direction = str(visual_direction_widget.toPlainText() if visual_direction_widget is not None else "").strip()
        if not visual_direction:
            visual_direction = str(payload.get("avatar_visual_direction") or "").strip()
        story_title = str(payload.get("title") or self.session.scene_title or "story").strip()
        story_summary = str(payload.get("summary") or self.session.scene_summary or "").strip()
        genre_hint = "fantasy character portrait" if self._looks_like_fantasy_story(payload) else "cinematic character portrait"
        pieces = [
            genre_hint,
            f"single avatar portrait of {persona.display_name}",
            persona.role,
            persona.visual.character_description or persona.description or persona.ar_description,
            persona.visual.clothing_props,
            persona.visual.environment_style,
            visual_direction,
            f"story: {story_title}",
            story_summary[:320],
            "clear face, expressive eyes, strong readable silhouette, cohesive costume, portrait framing",
            "no text, no watermark, no logo, no extra characters, no distorted hands or face",
        ]
        prompt = ". ".join(str(item or "").strip(" .") for item in pieces if str(item or "").strip())
        return prompt[:1200].rstrip(" \t\r\n,;:.-")

    def _story_avatar_prompt_override_for_persona(self, persona: PersonaConfig | None, payload: dict[str, Any]) -> str:
        if persona is None or not isinstance(payload, dict):
            return ""
        persona_id = normalize_persona_id(getattr(persona, "id", ""))
        display_name = str(getattr(persona, "display_name", "") or "").strip().lower()
        for item in list(payload.get("personas") or []):
            if not isinstance(item, dict):
                continue
            item_id = normalize_persona_id(item.get("id") or "")
            item_name = str(item.get("display_name") or "").strip().lower()
            if (persona_id and item_id == persona_id) or (display_name and item_name == display_name):
                return str(item.get("avatar_prompt_override") or "").strip()
        return ""

    @staticmethod
    def _looks_like_fantasy_story(payload: dict[str, Any]) -> bool:
        text = json.dumps(payload or {}, ensure_ascii=True).lower()
        markers = (
            "fantasy",
            "magic",
            "wizard",
            "sorcer",
            "dragon",
            "elf",
            "orc",
            "dwarf",
            "kingdom",
            "castle",
            "myth",
            "enchanted",
            "rune",
        )
        return any(marker in text for marker in markers)

    def _story_persona_id(self, value: Any, linked_ids: list[str], fallback: str = "", id_map: dict[str, str] | None = None) -> str:
        wanted = normalize_persona_id(value or "")
        mapped = dict(id_map or {}).get(wanted)
        if mapped:
            return mapped
        known_ids = {persona.id for persona in self.personas}
        if wanted in known_ids:
            return wanted
        wanted_name = str(value or "").strip().lower()
        for persona in self.personas:
            if wanted_name and persona.display_name.strip().lower() == wanted_name:
                return persona.id
        return str(fallback or (linked_ids[0] if linked_ids else self.session.active_persona_id) or "mentor").strip()

    def _story_persona_override_from_draft(
        self,
        target: PersonaConfig,
        persona_payload: dict[str, Any],
        payload: dict[str, Any],
        *,
        alternate_text: str = "",
    ) -> dict[str, Any]:
        draft_id = normalize_persona_id(persona_payload.get("id") or persona_payload.get("display_name") or target.id)
        override: dict[str, Any] = {
            "base_persona_id": target.id,
            "draft_id": draft_id,
            "story_id": self.storage.story_id(payload.get("id") or payload.get("title") or ""),
            "story_title": str(payload.get("title") or "").strip(),
            "mode": "story_profile",
        }
        for field in (
            "display_name",
            "role",
            "description",
            "system_prompt",
            "ar_description",
            "ar_system_prompt",
            "speaking_style",
            "allowed_tone",
            "response_length",
            "temperature_hint",
            "memory_scope",
            "behavior_mode",
            "character_image_path",
        ):
            value = str(persona_payload.get(field) or "").strip()
            if value:
                override[field] = value
        tags = persona_payload.get("tags")
        if isinstance(tags, list):
            cleaned = [str(item).strip().lower() for item in tags if str(item).strip()]
            if cleaned:
                override["tags"] = cleaned[:12]
        visual = persona_payload.get("visual")
        if isinstance(visual, dict):
            override["visual"] = {
                key: value
                for key, value in dict(visual).items()
                if isinstance(value, bool) or str(value or "").strip()
            }
        notes = str(alternate_text or "").strip()
        if notes:
            override["story_profile_notes"] = notes[:2400]
        return override

    def _master_story_persona_overrides(self) -> dict[str, dict[str, Any]]:
        raw = self.settings.get("master_story_persona_overrides")
        if not isinstance(raw, dict):
            draft_raw = self._master_story_draft.get("persona_overrides") if isinstance(self._master_story_draft, dict) else {}
            raw = draft_raw if isinstance(draft_raw, dict) else {}
        overrides: dict[str, dict[str, Any]] = {}
        for key, value in raw.items():
            persona_id = normalize_persona_id(key)
            if persona_id and isinstance(value, dict):
                overrides[persona_id] = dict(value)
        return overrides

    def story_prompt_personas(self) -> list[PersonaConfig]:
        return [self.story_prompt_persona(persona.id) or persona for persona in self.personas]

    def story_prompt_persona(self, persona_id: str) -> PersonaConfig | None:
        base = self.persona_by_id(persona_id)
        if base is None:
            return None
        override = self._master_story_persona_overrides().get(base.id)
        if not isinstance(override, dict) or not override:
            return base
        persona = copy.deepcopy(base)
        for field in (
            "display_name",
            "role",
            "description",
            "system_prompt",
            "ar_description",
            "ar_system_prompt",
            "speaking_style",
            "allowed_tone",
            "response_length",
            "temperature_hint",
            "memory_scope",
            "behavior_mode",
            "character_image_path",
        ):
            value = str(override.get(field) or "").strip()
            if value:
                setattr(persona, field, value)
        tags = override.get("tags")
        if isinstance(tags, list):
            cleaned = [str(item).strip().lower() for item in tags if str(item).strip()]
            if cleaned:
                persona.tags = cleaned[:12]
        visual = override.get("visual")
        if isinstance(visual, dict):
            if any(str(visual.get(field) or "").strip() for field in ("character_description", "clothing_props", "environment_style")):
                persona.visual.enabled = bool(visual.get("enabled", True))
                if persona.visual.mode == "off":
                    persona.visual.mode = "manual"
            for field in ("character_description", "clothing_props", "environment_style", "negative_prompt", "style_preset"):
                value = str(visual.get(field) or "").strip()
                if value:
                    setattr(persona.visual, field, value)
        notes = str(override.get("story_profile_notes") or "").strip()
        if notes:
            if notes not in persona.ar_description:
                persona.ar_description = ". ".join(part for part in (persona.ar_description, f"Story-only profile: {notes}") if part).strip()
            if notes not in persona.system_prompt:
                persona.system_prompt = "\n".join(part for part in (persona.system_prompt, f"Story-only persona notes for this Master Story:\n{notes}") if part).strip()
        return persona

    def resolve_story_persona_alias(self, value: Any) -> PersonaConfig | None:
        wanted = str(value or "").strip()
        if not wanted:
            return None
        wanted_id = normalize_persona_id(wanted)
        wanted_lower = wanted.lower()
        for persona_id, override in self._master_story_persona_overrides().items():
            candidates = [
                override.get("draft_id"),
                override.get("display_name"),
            ]
            for candidate in candidates:
                candidate_text = str(candidate or "").strip()
                if not candidate_text:
                    continue
                if normalize_persona_id(candidate_text) == wanted_id or candidate_text.lower() == wanted_lower:
                    return self.persona_by_id(persona_id)
        return None

    def _story_character_summaries(self, linked_ids: list[str]) -> dict[str, str]:
        by_id = {persona.id: persona for persona in self.story_prompt_personas()}
        summaries: dict[str, str] = {}
        for persona_id in linked_ids[:12]:
            persona = by_id.get(persona_id)
            if persona is None:
                continue
            summary = ". ".join(part for part in (persona.role, persona.description or persona.ar_description) if part)
            summaries[persona_id] = summary[:300]
        return summaries

    def _current_master_story_snapshot(self) -> dict[str, Any]:
        title = self.session.scene_title or "Current Roleplay Story"
        return self._normalize_master_story_payload({
            "id": self.storage.story_id(title),
            "title": title,
            "summary": self.session.scene_summary,
            "mode": self.session.mode,
            "active_persona_id": self.session.active_persona_id,
            "current_speaker_id": self.session.current_speaker_id,
            "narrator_persona_id": self.selected_narrator_persona_id(),
            "narrator_persona_mode": self._narrator_selection_mode(),
            "session": self.session.to_dict(),
            "personas": [persona.to_dict() for persona in self.personas],
            "persona_overrides": dict(self.settings.get("master_story_persona_overrides") or {}),
        })

    def _save_master_story(self):
        payload = self._parse_master_story_draft() or self._current_master_story_snapshot()
        payload = self._sanitize_master_story_overrides_for_options(payload)
        if (
            self._control_checked("master_story_use_existing_personas", True)
            and not isinstance(payload.get("persona_overrides"), dict)
            and isinstance(self.settings.get("master_story_persona_overrides"), dict)
        ):
            candidate = dict(payload)
            candidate["persona_overrides"] = dict(self.settings.get("master_story_persona_overrides") or {})
            payload = self._sanitize_master_story_overrides_for_options(candidate)
        payload["narrator_persona_id"] = self.selected_narrator_persona_id()
        payload["narrator_persona_mode"] = self._narrator_selection_mode()
        session_payload = dict(payload.get("session") or {}) if isinstance(payload.get("session"), dict) else {}
        session_payload["narrator_persona_id"] = payload["narrator_persona_id"]
        session_payload["narrator_persona_mode"] = payload["narrator_persona_mode"]
        payload["session"] = session_payload
        payload["updated_at"] = QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate)
        payload = self._ensure_master_story_image(payload)
        story_id = self.storage.save_story(payload)
        self._master_story_draft = payload
        self._set_master_story_sfw_from_payload(payload)
        self._controls["master_story_draft"].setPlainText(json.dumps(payload, indent=2, ensure_ascii=True))
        if self.storage.story_id(self.settings.get("last_master_story_id") or "") == story_id:
            self._save_story_memory_snapshot(story_id)
        self._populate_master_stories()
        combo = self._controls.get("master_story_list")
        if combo is not None:
            index = combo.findData(story_id)
            if index >= 0:
                combo.setCurrentIndex(index)
        self._set_master_story_status(f"Saved story '{payload.get('title')}' as {story_id}.")

    def _load_selected_master_story(self):
        story_id = self._selected_master_story_id()
        if not story_id:
            return
        self.save_active_story_memory_snapshot()
        payload = self.storage.load_story(story_id)
        if not payload:
            self._warn("Load Story", "The selected story could not be loaded.")
            return
        for note in list(payload.get("_migration_log") or []):
            self._record_story_event(f"story migration/fallback: {note}", severity="warning", kind="schema", persist=True)
        payload = self._normalize_master_story_payload(payload)
        payload = self._ensure_master_story_image(payload, save_story=True)
        self._master_story_draft = payload
        self._set_master_story_visual_direction(payload.get("avatar_visual_direction"))
        self._set_master_story_sfw_from_payload(payload)
        self._controls["master_story_draft"].setPlainText(json.dumps(payload, indent=2, ensure_ascii=True))
        self._apply_master_story_payload(payload, apply_plan={"clear_memory": True})
        restored = self._restore_story_memory_snapshot(story_id)
        if restored:
            self.storage.save_settings(self.settings)
            self.save_state()
            self.refresh_ui()
            self._set_master_story_status(f"Loaded story '{payload.get('title')}' and restored its saved story memory.")
        else:
            self._set_master_story_status(f"Loaded and applied story '{payload.get('title')}'. No saved story memory was found yet.")

    def _delete_selected_master_story(self):
        story_id = self._selected_master_story_id()
        if not story_id:
            return
        self.storage.delete_story(story_id)
        self._populate_master_stories()
        self._set_master_story_status(f"Deleted story {story_id}.")

    def _commit_audio_settings(self):
        if self._syncing:
            return
        c = self._controls
        if "audio_story_sounds" not in c:
            return
        self.settings["story_sounds_enabled"] = bool(c["audio_story_sounds"].isChecked())
        if "audiofx_volume" in c:
            self.settings["audiofx_volume"] = int(c["audiofx_volume"].value())
        self.settings["audio_prompt_type"] = c["audio_type"].currentText().strip() or "Auto"
        self.settings["audio_prompt_description"] = c["audio_sound_description"].toPlainText().strip()
        self.settings["audio_prompt_output"] = c["audio_prompt_output"].toPlainText().strip()
        self.storage.save_settings(self.settings)

    def _on_story_sounds_changed(self, checked: bool):
        if self._syncing:
            return
        self._commit_audio_settings()
        logger = getattr(self.context, "logger", None)
        if logger is not None:
            logger.info("[AR_MODE] Story Sounds enabled=%s", bool(checked))

    def _on_audiofx_volume_changed(self, value: int):
        if self._syncing:
            return
        volume = max(0, min(100, int(value or 0)))
        value_label = self._controls.get("audiofx_volume_value")
        if value_label is not None:
            value_label.setText(f"{volume}%")
        self.settings["audiofx_volume"] = volume
        self.storage.save_settings(self.settings)
        self._apply_audiofx_volume()

    def _on_audiofx_test_mode_changed(self, checked: bool):
        if self._syncing:
            return
        self.settings["audiofx_test_mode"] = bool(checked)
        if checked:
            self.settings["story_sounds_enabled"] = True
            self._create_test_audiofx(show_status=True)
        else:
            self.storage.save_settings(self.settings)
        self.refresh_ui()

    def _test_audiofx_specs(self) -> list[dict[str, str]]:
        return [
            {
                "id": "mprc_test_pub_ambient",
                "type": "Ambience",
                "description": "pub ambient",
                "prompt": "busy fantasy pub ambience, layered low crowd murmur, soft room tone, occasional glass clinks, seamless loop, no vocals",
                "file_name": "pub_ambient_test.wav",
                "profile": "pub",
            },
            {
                "id": "mprc_test_adventure_music",
                "type": "Music",
                "description": "adventure music",
                "prompt": "low fantasy adventure music bed, steady pulse, warm strings, subtle drums, seamless loop, no vocals",
                "file_name": "adventure_music_test.wav",
                "profile": "music",
            },
            {
                "id": "mprc_test_rain_storm",
                "type": "Ambience",
                "description": "rain storm",
                "prompt": "rain storm ambience, steady rainfall, distant thunder rumble, dark cinematic atmosphere, seamless loop, no vocals",
                "file_name": "rain_storm_test.wav",
                "profile": "rain",
            },
            {
                "id": "mprc_test_deep_engine_hum",
                "type": "Ambience",
                "description": "deep engine hum",
                "prompt": "deep submarine engine hum, low mechanical vibration, metal room resonance, seamless loop, no vocals",
                "file_name": "deep_engine_hum_test.wav",
                "profile": "hum",
            },
            {
                "id": "mprc_test_magic_shimmer",
                "type": "FX",
                "description": "magic shimmer",
                "prompt": "soft magic shimmer sound effect, sparkling arcane chimes, gentle fantasy energy, no vocals",
                "file_name": "magic_shimmer_test.wav",
                "profile": "magic",
            },
            {
                "id": "mprc_test_danger_stinger",
                "type": "Stinger",
                "description": "danger stinger",
                "prompt": "short danger stinger, cinematic hit, quick rising tension, no vocals",
                "file_name": "danger_stinger_test.wav",
                "profile": "stinger",
            },
        ]

    def _create_test_audiofx(self, *, show_status: bool = True):
        specs = self._test_audiofx_specs()
        base_dir = self.context.storage.resolve("test_audio")
        base_dir.mkdir(parents=True, exist_ok=True)
        items = [item for item in self._audiofx_items() if not str(item.get("id") or "").startswith("mprc_test_")]
        now = QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate)
        for spec in specs:
            path = base_dir / spec["file_name"]
            self._write_test_audio_file(path, spec["profile"])
            items.append({
                "id": spec["id"],
                "type": spec["type"],
                "description": spec["description"],
                "prompt": spec["prompt"],
                "file_path": str(path),
                "created_at": now,
                "updated_at": now,
            })
        self.settings["audiofx_test_mode"] = bool(self.settings.get("audiofx_test_mode", True))
        self.settings["story_sounds_enabled"] = True
        self._save_audiofx_items(items)
        self._populate_audiofx_items()
        if show_status:
            status = self._controls.get("audiofx_status")
            if status is not None:
                status.setText("Test sounds ready. Try [AMBIENCE: pub ambient], [MUSIC: adventure music], [FX: magic shimmer], or [STINGER: danger stinger].")
                status.setStyleSheet("color: #22c55e;")
        logger = getattr(self.context, "logger", None)
        if logger is not None:
            logger.info("[AR_MODE] Created %s MPRC AudioFX test sounds in %s", len(specs), base_dir)

    def _write_test_audio_file(self, path: Path, profile: str):
        sample_rate = 22050
        duration = 3.0
        total = int(sample_rate * duration)
        profile = str(profile or "pub")
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            frames = bytearray()
            seed = sum(ord(ch) for ch in profile) or 1
            noise = seed & 0x7fffffff
            for index in range(total):
                t = index / sample_rate
                noise = (1103515245 * noise + 12345) & 0x7fffffff
                n = ((noise / 0x7fffffff) * 2.0 - 1.0)
                if profile == "rain":
                    value = 0.16 * n + 0.08 * math.sin(2 * math.pi * 47 * t) + 0.04 * math.sin(2 * math.pi * 82 * t)
                    if int(t * 2) % 5 == 0:
                        value += 0.04 * math.sin(2 * math.pi * 31 * t)
                elif profile == "hum":
                    value = 0.34 * math.sin(2 * math.pi * 55 * t) + 0.15 * math.sin(2 * math.pi * 110 * t) + 0.04 * n
                elif profile == "music":
                    pulse = 0.5 + 0.5 * math.sin(2 * math.pi * 2.0 * t)
                    value = 0.16 * math.sin(2 * math.pi * 196 * t) + 0.12 * math.sin(2 * math.pi * 247 * t)
                    value += 0.10 * math.sin(2 * math.pi * 98 * t) * pulse + 0.03 * n
                elif profile == "magic":
                    value = 0.18 * math.sin(2 * math.pi * (440 + 60 * math.sin(2 * math.pi * 0.45 * t)) * t)
                    value += 0.12 * math.sin(2 * math.pi * 880 * t) * (0.5 + 0.5 * math.sin(2 * math.pi * 1.5 * t))
                    value += 0.03 * n
                elif profile == "stinger":
                    decay = max(0.0, 1.0 - (t / duration))
                    value = decay * (0.45 * math.sin(2 * math.pi * 82 * t) + 0.28 * math.sin(2 * math.pi * 330 * t))
                    value += 0.04 * n * decay
                else:
                    value = 0.12 * math.sin(2 * math.pi * 145 * t) + 0.08 * math.sin(2 * math.pi * 210 * t) + 0.06 * n
                    if (index % int(sample_rate * 0.7)) < 360:
                        value += 0.22 * math.sin(2 * math.pi * 1200 * t)
                sample = max(-0.85, min(0.85, value))
                frames.extend(struct.pack("<h", int(sample * 32767)))
            handle.writeframes(bytes(frames))

    def _play_test_ambience_tag(self):
        if not any(str(item.get("id") or "").startswith("mprc_test_") for item in self._audiofx_items()):
            self._create_test_audiofx(show_status=False)
        self.settings["story_sounds_enabled"] = True
        self.storage.save_settings(self.settings)
        self._trigger_story_audio_cues("pub ambient", warn_unmatched=True)

    def _create_audio_prompt(self, variant: str = ""):
        if self._syncing:
            return
        c = self._controls
        description = c["audio_sound_description"].toPlainText().strip()
        if not description:
            self._warn("Create Prompt for Audio", "Add a Sound Description first.")
            return
        prompt = create_audio_prompt(description, c["audio_type"].currentText(), variant=variant)
        c["audio_prompt_output"].setPlainText(prompt)
        self._commit_audio_settings()

    def _copy_audio_prompt(self):
        from PySide6 import QtWidgets

        prompt = self._controls["audio_prompt_output"].toPlainText().strip()
        QtWidgets.QApplication.clipboard().setText(prompt)

    def _save_audio_prompt(self):
        c = self._controls
        prompt = c["audio_prompt_output"].toPlainText().strip()
        if not prompt:
            self._warn("Save Prompt", "Create or enter an audio prompt before saving.")
            return
        self._commit_audio_settings()
        saved = self.settings.get("saved_audio_prompts")
        if not isinstance(saved, list):
            saved = []
        entry = {
            "created_at": QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate),
            "type": c["audio_type"].currentText().strip() or "Auto",
            "description": c["audio_sound_description"].toPlainText().strip(),
            "prompt": prompt,
        }
        saved = [item for item in saved if isinstance(item, dict)]
        saved.append(entry)
        self.settings["saved_audio_prompts"] = saved[-100:]
        self.storage.save_settings(self.settings)
        self._populate_audio_saved_prompts()
        logger = getattr(self.context, "logger", None)
        if logger is not None:
            logger.info("[AR_MODE] Saved audio prompt type=%s", entry["type"])

    def _load_saved_audio_prompt(self):
        index = self._selected_audio_prompt_index()
        prompts = self._saved_audio_prompts()
        if index < 0 or index >= len(prompts):
            return
        item = prompts[index]
        audio_type = str(item.get("type") or "Auto").strip()
        self._controls["audio_sound_description"].setPlainText(str(item.get("description") or ""))
        self._controls["audio_type"].setCurrentText(audio_type if audio_type in AUDIO_TYPES else "Auto")
        self._controls["audio_prompt_output"].setPlainText(str(item.get("prompt") or ""))
        self._commit_audio_settings()

    def _delete_saved_audio_prompt(self):
        index = self._selected_audio_prompt_index()
        prompts = self._saved_audio_prompts()
        if index < 0 or index >= len(prompts):
            return
        del prompts[index]
        self.settings["saved_audio_prompts"] = prompts
        self.storage.save_settings(self.settings)
        self._populate_audio_saved_prompts()

    def _audiofx_payload_from_builder(self) -> dict[str, str]:
        c = self._controls
        description = c["audio_sound_description"].toPlainText().strip()
        audio_type = c["audio_type"].currentText().strip() or "Auto"
        prompt = c["audio_prompt_output"].toPlainText().strip()
        if not description and not prompt:
            saved_index = self._selected_audio_prompt_index()
            saved = self._saved_audio_prompts()
            if 0 <= saved_index < len(saved):
                selected = saved[saved_index]
                description = str(selected.get("description") or "").strip()
                prompt = str(selected.get("prompt") or "").strip()
                audio_type = str(selected.get("type") or audio_type).strip() or audio_type
        if description and not prompt:
            prompt = create_audio_prompt(description, audio_type)
            c["audio_prompt_output"].setPlainText(prompt)
        if prompt and not description:
            description = prompt[:120]
        return {
            "type": audio_type if audio_type in AUDIO_TYPES else "Auto",
            "description": description,
            "prompt": prompt,
        }

    def _create_new_audiofx(self):
        payload = self._audiofx_payload_from_builder()
        if not payload["description"] and not payload["prompt"]:
            self._warn("Create New AudioFX", "Add a Sound Description or select a saved audio prompt first.")
            return
        items = self._audiofx_items()
        now = QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate)
        item = {
            "id": self._new_audiofx_id(items),
            "type": payload["type"],
            "description": payload["description"],
            "prompt": payload["prompt"],
            "file_path": "",
            "created_at": now,
            "updated_at": now,
        }
        items.append(item)
        self._save_audiofx_items(items)
        self._populate_audiofx_items()
        self._select_audiofx_index(len(items) - 1)

    def _update_selected_audiofx_from_builder(self) -> bool:
        index = self._selected_audiofx_index()
        items = self._audiofx_items()
        if index < 0 or index >= len(items):
            self._create_new_audiofx()
            return self._selected_audiofx_index() >= 0
        payload = self._audiofx_payload_from_builder()
        if not payload["description"] and not payload["prompt"]:
            return False
        items[index]["type"] = payload["type"]
        items[index]["description"] = payload["description"]
        items[index]["prompt"] = payload["prompt"]
        items[index]["updated_at"] = QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate)
        self._save_audiofx_items(items)
        self._populate_audiofx_items()
        self._select_audiofx_index(index)
        return True

    def _add_audiofx_file(self):
        index = self._selected_audiofx_index()
        if index < 0:
            self._create_new_audiofx()
            index = self._selected_audiofx_index()
        items = self._audiofx_items()
        if index < 0 or index >= len(items):
            return
        current_path = str(items[index].get("file_path") or "").strip()
        start = str(Path(current_path).parent) if current_path else str(Path.home())
        path = self._open_file(
            "Choose AudioFX sound file",
            start,
            "Audio files (*.wav *.mp3 *.flac *.ogg *.m4a);;All files (*.*)",
        )
        if not path:
            return
        items[index]["file_path"] = path
        items[index]["updated_at"] = QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate)
        self._save_audiofx_items(items)
        self._populate_audiofx_items()
        self._select_audiofx_index(index)
        logger = getattr(self.context, "logger", None)
        if logger is not None:
            logger.info("[AR_MODE] Indexed AudioFX file for story use: %s", path)

    def _load_selected_audiofx(self):
        index = self._selected_audiofx_index()
        items = self._audiofx_items()
        if index < 0 or index >= len(items):
            return
        item = items[index]
        audio_type = str(item.get("type") or "Auto").strip()
        self._controls["audio_sound_description"].setPlainText(str(item.get("description") or ""))
        self._controls["audio_type"].setCurrentText(audio_type if audio_type in AUDIO_TYPES else "Auto")
        self._controls["audio_prompt_output"].setPlainText(str(item.get("prompt") or ""))
        self._commit_audio_settings()

    def _delete_selected_audiofx(self):
        index = self._selected_audiofx_index()
        items = self._audiofx_items()
        if index < 0 or index >= len(items):
            return
        del items[index]
        self._save_audiofx_items(items)
        self._populate_audiofx_items()

    def _play_selected_audiofx(self):
        index = self._selected_audiofx_index()
        items = self._audiofx_items()
        if index < 0 or index >= len(items):
            return
        file_path = str(items[index].get("file_path") or "").strip()
        if not file_path or not Path(file_path).exists():
            self._warn("Play Sound", "Attach a valid local audio file before playing this AudioFX item.")
            return
        try:
            player = self._ensure_audiofx_player()
            self._apply_audiofx_volume()
            player.setSource(QtCore.QUrl.fromLocalFile(str(Path(file_path).resolve())))
            player.play()
        except Exception as exc:
            self._warn("Play Sound", f"AudioFX playback failed:\n\n{exc}")

    def _play_story_audio_entry(self, entry_obj):
        if self.is_shutdown():
            return
        entry = dict(entry_obj or {}) if isinstance(entry_obj, dict) else {}
        file_path = str(entry.get("file_path") or "").strip()
        if not file_path or not Path(file_path).exists():
            return
        try:
            player = self._ensure_audiofx_player()
            self._apply_audiofx_volume()
            player.setSource(QtCore.QUrl.fromLocalFile(str(Path(file_path).resolve())))
            player.play()
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.info("[AR_MODE] Playing story AudioFX cue %s: %s", entry.get("id") or "", file_path)
        except Exception as exc:
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[AR_MODE] Story AudioFX playback failed: %s", exc)

    def _ensure_audiofx_player(self):
        if self._audiofx_player is not None:
            return self._audiofx_player
        try:
            from PySide6 import QtMultimedia
        except Exception as exc:
            raise RuntimeError(f"Qt multimedia playback is unavailable: {exc}") from exc
        parent = self._widget if self._widget is not None else self._qt_application_instance()
        self._audiofx_output = QtMultimedia.QAudioOutput(parent)
        self._apply_audiofx_volume()
        self._audiofx_player = QtMultimedia.QMediaPlayer(parent)
        self._audiofx_player.setAudioOutput(self._audiofx_output)
        return self._audiofx_player

    def _save_audio_item_description(self):
        prompt = self._controls["audio_prompt_output"].toPlainText().strip()
        if not prompt:
            self._warn("Save as Audio Item Description", "Create or enter an audio prompt first.")
            return
        self._commit_audio_settings()
        self.settings["audio_item_description"] = prompt
        self.storage.save_settings(self.settings)
        self._update_selected_audiofx_from_builder()

    def _clear_audio_prompt(self):
        if self._syncing:
            return
        self._controls["audio_sound_description"].setPlainText("")
        self._controls["audio_prompt_output"].setPlainText("")
        self._controls["audio_type"].setCurrentText("Auto")
        self._commit_audio_settings()

    def _on_enabled_changed(self, checked: bool):
        if self._syncing:
            return
        self.session.enabled = bool(checked)
        self.save_state()
        self._refresh_debug()

    def _on_show_character_changed(self, checked: bool):
        if self._syncing:
            return
        self.settings["show_current_character_visual"] = bool(checked)
        self.storage.save_settings(self.settings)
        self._refresh_character_preview()

    def _on_current_character_view_mode_changed(self):
        if self._syncing:
            return
        combo = self._controls.get("current_character_view_mode")
        mode = str(combo.currentData() or "active_story").strip() if combo is not None and hasattr(combo, "currentData") else "active_story"
        if mode not in {"active_story", "all"}:
            mode = "active_story"
        self.settings["current_character_view_mode"] = mode
        self.storage.save_settings(self.settings)
        self._refresh_character_preview()

    def _on_ar_mode_changed(self, checked: bool):
        if self._syncing:
            return
        if checked:
            if self.session.mode != AR_MODE:
                self.settings["last_non_ar_mode"] = self.session.mode or "Narrator + characters"
            self.session.mode = AR_MODE
            self.session.enabled = True
            self.ensure_ar_state()
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.info("[AR_MODE] AlternativeReality Mode enabled")
        else:
            if self.session.mode == AR_MODE:
                fallback = str(self.settings.get("last_non_ar_mode") or "Narrator + characters").strip()
                self.session.mode = fallback if fallback and fallback != AR_MODE else "Narrator + characters"
                logger = getattr(self.context, "logger", None)
                if logger is not None:
                    logger.info("[AR_MODE] AlternativeReality Mode disabled; restored mode=%s", self.session.mode)
        self.storage.save_settings(self.settings)
        self.save_state()
        self.refresh_ui()

    def _on_active_persona_changed(self):
        if self._syncing:
            return
        combo = self._controls.get("active")
        persona_id = str(combo.currentData() or "").strip() if combo is not None else ""
        if persona_id:
            self.session.active_persona_id = persona_id
            self.session.current_speaker_id = persona_id
            if self._voice_follows_active():
                self.settings["voice_edit_persona_id"] = persona_id
                self.storage.save_settings(self.settings)
            self.save_state()
            self.refresh_ui()

    def _on_persona_list_changed(self):
        if self._syncing:
            return
        item = self._controls["persona_list"].currentItem()
        persona_id = str(item.data(32) if item is not None else "").strip()
        if persona_id:
            self.session.active_persona_id = persona_id
            self.session.current_speaker_id = persona_id
            if self._voice_follows_active():
                self.settings["voice_edit_persona_id"] = persona_id
                self.storage.save_settings(self.settings)
            self.save_state()
            self.refresh_ui()

    def _add_persona(self):
        new_id = unique_persona_id("custom_persona", {p.id for p in self.personas})
        persona = PersonaConfig(
            id=new_id,
            display_name="Custom Persona",
            role="custom",
            description="",
            system_prompt="Stay consistent with this persona and preserve user agency.",
            speaking_style="clear and consistent",
            allowed_tone="user-defined",
            tags=["custom"],
        )
        self.personas.append(persona)
        self.session.active_persona_id = persona.id
        self.session.current_speaker_id = persona.id
        self.save_state()
        self.refresh_ui()

    def _duplicate_persona(self):
        source = self._selected_persona()
        if source is None:
            return
        payload = source.to_dict()
        payload["id"] = unique_persona_id(source.id + "_copy", {p.id for p in self.personas})
        payload["display_name"] = source.display_name + " Copy"
        persona = PersonaConfig.from_dict(payload)
        self.personas.append(persona)
        self.session.active_persona_id = persona.id
        self.session.current_speaker_id = persona.id
        self.save_state()
        self.refresh_ui()

    def _delete_persona(self):
        if len(self.personas) <= 1:
            return
        persona = self._selected_persona()
        if persona is None:
            return
        if self._persona_is_master_narrator(persona):
            self._warn(
                "Delete persona",
                "This persona is marked as a Master narrator and is protected from deletion. Uncheck Master narrator in the Editor tab before deleting it.",
            )
            return
        self.personas = [item for item in self.personas if item.id != persona.id]
        self.session.active_persona_id = self.personas[0].id
        self.session.current_speaker_id = self.session.active_persona_id
        settings_changed = False
        if normalize_persona_id(self.settings.get("narrator_persona_id", "")) == persona.id:
            self.settings["narrator_persona_id"] = ""
            self.settings["narrator_persona_mode"] = "auto"
            settings_changed = True
        if normalize_persona_id(self.settings.get("voice_edit_persona_id", "")) == persona.id:
            self.settings["voice_edit_persona_id"] = self.session.active_persona_id
            settings_changed = True
        if settings_changed:
            self.storage.save_settings(self.settings)
        self.save_state()
        self.refresh_ui()

    def _reset_defaults(self):
        self.personas = [PersonaConfig.from_dict(item) for item in self.storage._default_json("personas.json", [])]
        self.session = self.storage.load_default_session()
        self.settings["narrator_persona_id"] = ""
        self.settings["narrator_persona_mode"] = "auto"
        self.settings["voice_edit_persona_id"] = ""
        self.settings["current_character_view_mode"] = "active_story"
        self.storage.save_settings(self.settings)
        self._ensure_session_persona()
        self.save_state()
        self.refresh_ui()

    def _load_default_scenario(self):
        self.session = self.storage.load_default_session()
        self._ensure_session_persona()
        self.save_state()
        self.refresh_ui()

    def _open_file(self, title: str, start: str, filter_text: str) -> str:
        service = self.dialog_service
        if service is not None and hasattr(service, "open_file"):
            path, _selected = service.open_file(title, start, filter_text)
            return str(path or "")
        return ""

    def _open_directory(self, title: str, start: str) -> str:
        service = self.dialog_service
        if service is not None and hasattr(service, "open_directory"):
            path = service.open_directory(title, start)
            if isinstance(path, tuple):
                path = path[0]
            return str(path or "")
        from PySide6 import QtWidgets

        parent = self._widget.window() if self._widget is not None else None
        return str(QtWidgets.QFileDialog.getExistingDirectory(parent, str(title or "Choose Folder"), str(start or Path.home())) or "")

    def _save_file(self, title: str, start: str, filter_text: str) -> str:
        service = self.dialog_service
        if service is not None and hasattr(service, "save_file"):
            path, _selected = service.save_file(title, start, filter_text)
            return str(path or "")
        from PySide6 import QtWidgets

        parent = self._widget.window() if self._widget is not None else None
        path, _selected = QtWidgets.QFileDialog.getSaveFileName(parent, str(title or "Save File"), str(start or Path.home()), str(filter_text or "All files (*.*)"))
        return str(path or "")

    def _import_personas(self):
        path = self._open_file("Import persona JSON", str(Path.home()), "JSON files (*.json)")
        if not path:
            return
        personas = self.storage.import_personas_from_path(path)
        self.personas = personas
        self.session.active_persona_id = personas[0].id
        self.session.current_speaker_id = personas[0].id
        self.save_state()
        self.refresh_ui()

    def _export_personas(self):
        path = self._save_file("Export persona JSON", str(Path.home() / "mprc_personas.json"), "JSON files (*.json)")
        if path:
            self.storage.export_personas_to_path(path, self.personas)

    def _browse_voice_sample(self):
        voices_dir = self._voice_sample_folder()
        start = voices_dir if voices_dir.exists() and voices_dir.is_dir() else Path(__file__).resolve().parents[2]
        path = self._open_file(
            "Choose voice sample",
            str(start),
            "WAV files (*.wav);;Audio files (*.wav *.mp3 *.flac *.ogg *.m4a);;All files (*.*)",
        )
        if path:
            self._controls["voice_sample"].setText(path)
            self._populate_voice_sample_picker()
            self._sync_voice_sample_picker(path)
            self._commit_voice_now()

    def _voice_sample_folder(self) -> Path:
        return Path(__file__).resolve().parents[2] / "voices"

    def _voice_sample_files(self) -> list[Path]:
        folder = self._voice_sample_folder()
        if not folder.exists() or not folder.is_dir():
            return []
        audio_suffixes = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".wma"}
        return sorted(
            (path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in audio_suffixes),
            key=lambda path: path.name.lower(),
        )

    def _voice_sample_wav_files(self) -> list[Path]:
        folder = self._voice_sample_folder()
        if not folder.exists() or not folder.is_dir():
            return []
        return sorted((path for path in folder.iterdir() if path.is_file() and path.suffix.lower() == ".wav"), key=lambda path: path.name.lower())

    def _populate_voice_file_combo(self, combo, *, include_empty: bool = True, empty_label: str = "No voice selected") -> None:
        if combo is None or not hasattr(combo, "addItem"):
            return
        current = str(combo.currentData() or "").strip() if hasattr(combo, "currentData") else ""
        combo.blockSignals(True)
        combo.clear()
        if include_empty:
            combo.addItem(str(empty_label or "No voice selected"), "")
        files = self._voice_sample_wav_files()
        for path in files:
            combo.addItem(path.name, str(path))
            combo.setItemData(combo.count() - 1, str(path), QtCore.Qt.ToolTipRole)
        if not files and not include_empty:
            combo.addItem("No .wav files in \\voices", "")
            combo.setEnabled(False)
        else:
            combo.setEnabled(True)
        if current:
            for index in range(combo.count()):
                if self._normalized_path_text(combo.itemData(index)) == self._normalized_path_text(current):
                    combo.setCurrentIndex(index)
                    break
        combo.blockSignals(False)

    @staticmethod
    def _default_voice_preview_text() -> str:
        return (
            "Neutral: This is the voice I will use for this character.\n"
            "Warm: I am glad you found me here.\n"
            "Concerned: Wait, something changed in the room.\n"
            "Excited: That is exactly the clue we needed.\n"
            "Whispered: Keep your voice low and listen closely."
        )

    def _preview_voice_sample(self, sample_path: str, text: str, *, status_label=None) -> bool:
        sample = str(sample_path or "").strip()
        if not sample:
            if status_label is not None and hasattr(status_label, "setText"):
                status_label.setText("Choose a .wav voice sample first.")
            return False
        path = Path(sample)
        if not path.exists() or not path.is_file():
            if status_label is not None and hasattr(status_label, "setText"):
                status_label.setText(f"Voice sample not found: {sample}")
            return False
        preview_text = str(text or "").strip() or self._default_voice_preview_text()
        token = self._new_worker_token("voice_preview")
        if not token:
            return False
        if status_label is not None and hasattr(status_label, "setText"):
            status_label.setProperty("_mprc_voice_preview_token", token)
            status_label.setText(f"Loading TTS preview for {path.name}...")
            try:
                self._voice_preview_status_widgets[token] = weakref.ref(status_label)
            except TypeError:
                self._voice_preview_status_widgets[token] = lambda status_label=status_label: status_label

        def worker():
            error = ""
            try:
                from core.engine_access import engine_module

                engine = engine_module()
                if getattr(engine, "tts_model", None) is None:
                    init_tts = getattr(engine, "init_tts", None)
                    if not callable(init_tts):
                        raise RuntimeError("The active NC runtime does not expose TTS initialization.")
                    with self._mprc_tts_lock:
                        if getattr(engine, "tts_model", None) is None and not bool(init_tts()):
                            raise RuntimeError("The active TTS runtime could not be loaded.")
                speak_async = getattr(engine, "speak_async", None)
                if not callable(speak_async):
                    raise RuntimeError("The active NC runtime does not expose TTS playback.")
                if self._worker_should_emit(token):
                    speak_async(preview_text, voice_path_override=str(path))
            except Exception as exc:
                error = str(exc) or repr(exc)
            if not self._worker_should_emit(token):
                return
            bridge = getattr(self, "_voice_preview_bridge", None)
            if bridge is not None:
                bridge.finished.emit(token, error)
            else:
                self._cancel_worker_token(token)

        if not self._start_daemon_worker(token, worker, name="nc-mprc-voice-preview"):
            self._voice_preview_status_widgets.pop(token, None)
            if status_label is not None and hasattr(status_label, "setText"):
                status_label.setText("Could not start voice preview worker.")
            return False
        return True

    def _on_voice_preview_finished(self, token: str, error: str) -> None:
        token = str(token or "")
        if not self._finish_worker_token(token):
            self._voice_preview_status_widgets.pop(token, None)
            return
        widget_ref = self._voice_preview_status_widgets.pop(token, None)
        widget = widget_ref() if callable(widget_ref) else None
        if widget is not None and hasattr(widget, "property"):
            current_token = str(widget.property("_mprc_voice_preview_token") or "")
            if current_token and current_token != token:
                widget = None
        if widget is not None and hasattr(widget, "setText"):
            widget.setProperty("_mprc_voice_preview_token", "")
            widget.setText(f"Voice preview failed: {error}" if str(error or "").strip() else "Voice preview queued.")
        if error:
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[MPRC] Voice preview failed: %s", error)

    def _populate_voice_sample_picker(self) -> None:
        combo = self._controls.get("voice_sample_picker")
        if combo is None or not hasattr(combo, "setModel"):
            return
        sample = self._controls.get("voice_sample")
        current_path = str(sample.text() if sample is not None and hasattr(sample, "text") else "").strip()
        combo.blockSignals(True)
        model = QtGui.QStandardItemModel(combo)
        model.setColumnCount(2)

        def add_voice_row(test_label: str, voice_label: str, full_path: str) -> None:
            test_item = QtGui.QStandardItem(test_label)
            voice_item = QtGui.QStandardItem(voice_label)
            for item in (test_item, voice_item):
                item.setEditable(False)
                item.setData(full_path, QtCore.Qt.UserRole)
                if full_path:
                    item.setData(full_path, QtCore.Qt.ToolTipRole)
            model.appendRow([test_item, voice_item])

        files = self._voice_sample_files()
        if files:
            add_voice_row("", "Choose from \\voices...", "")
            for path in files:
                add_voice_row("Test voice", path.name, str(path))
            combo.setEnabled(True)
        else:
            add_voice_row("", "No audio files in \\voices", "")
            combo.setEnabled(False)
        combo.setModel(model)
        combo.setModelColumn(1)
        view = combo.view()
        if hasattr(view, "setColumnWidth"):
            view.setColumnWidth(0, 92)
            view.setColumnWidth(1, 260)
        combo.blockSignals(False)
        self._sync_voice_sample_picker(current_path)

    def _sync_voice_sample_picker(self, sample_path: str) -> None:
        combo = self._controls.get("voice_sample_picker")
        if combo is None or not hasattr(combo, "count"):
            return
        target = self._normalized_path_text(sample_path)
        index = 0
        if target:
            for row in range(combo.count()):
                candidate = self._normalized_path_text(combo.itemData(row))
                if candidate and candidate == target:
                    index = row
                    break
        combo.blockSignals(True)
        combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def _select_voice_sample_from_picker(self) -> None:
        combo = self._controls.get("voice_sample_picker")
        sample = self._controls.get("voice_sample")
        if combo is None or sample is None or not hasattr(combo, "currentData") or not hasattr(sample, "setText"):
            return
        path = str(combo.currentData() or "").strip()
        if path:
            sample.setText(path)
            self._commit_voice_now()

    @staticmethod
    def _normalized_path_text(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        try:
            return str(Path(text).expanduser().resolve()).casefold()
        except Exception:
            return text.casefold()

    def _browse_character_image(self):
        path = self._open_file("Choose character picture", str(Path.home()), "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*.*)")
        if path:
            self._controls["character_image_path"].setText(path)
            self._commit_editor_now(include_identity=False)

    def _generate_character_image(self):
        persona = self._selected_persona()
        if persona is None:
            return
        key = str(persona.id or "").strip()
        if not key:
            return
        prompt = self._character_picture_prompt(persona)
        if not prompt:
            self._record_visual_debug(
                source="nc.multi_persona_roleplay.character_picture",
                reason="character_picture",
                persona=persona,
                accepted=False,
                message="Character picture skipped because the persona has no usable description or system prompt.",
            )
            self._warn("Create Character Picture", "Add a description or system prompt before generating a character picture.")
            return
        with self._state_lock:
            if key in self._manual_character_image_inflight:
                self._record_visual_debug(
                    source="nc.multi_persona_roleplay.character_picture",
                    reason="character_picture",
                    persona=persona,
                    accepted=None,
                    message="Character picture request is already running.",
                    prompt=prompt,
                )
                return
            self._manual_character_image_inflight.add(key)
        self._record_visual_debug(
            source="nc.multi_persona_roleplay.character_picture",
            reason="character_picture",
            persona=persona,
            accepted=None,
            message="Character picture request queued for a background worker.",
            prompt=prompt,
        )
        if not self._queue_visual_worker("mprc_manual_character_image", lambda: self._run_manual_character_image_request(key)):
            with self._state_lock:
                self._manual_character_image_inflight.discard(key)
            self._record_visual_debug(
                source="nc.multi_persona_roleplay.character_picture",
                reason="character_picture",
                persona=persona,
                accepted=False,
                message="Character picture request could not start a background worker.",
                prompt=prompt,
            )
            self._warn("Create Character Picture", "Character picture generation could not start a background worker.")

    def _run_manual_character_image_request(self, persona_id: str) -> None:
        key = str(persona_id or "").strip()
        result: dict[str, Any]
        try:
            persona = self.persona_by_id(key)
            if persona is None:
                result = {"ok": False, "message": f"No persona matched character picture request id '{key}'."}
            else:
                result = self._request_character_image_generation(
                    persona,
                    auto_show=True,
                    source="nc.multi_persona_roleplay.character_picture",
                )
        except Exception as exc:
            result = {"ok": False, "message": f"Character picture generation failed:\n\n{exc}"}
        self._emit_manual_visual_finished("character_picture", key, result)

    def _request_character_image_generation(self, persona: PersonaConfig, *, auto_show: bool, source: str) -> dict[str, Any]:
        visual_service = self.visual_reply_service
        if visual_service is None or not hasattr(visual_service, "request_generation"):
            self._record_visual_debug(
                source=str(source or "character_picture"),
                reason="character_picture",
                persona=persona,
                accepted=False,
                message="Visual Reply generation service is unavailable. Choose a picture from your drive instead.",
            )
            return {"ok": False, "message": "Visual Reply generation service is unavailable. Choose a picture from your drive instead."}
        prompt = self._character_picture_prompt(persona)
        if not prompt:
            self._record_visual_debug(
                source=str(source or "character_picture"),
                reason="character_picture",
                persona=persona,
                accepted=False,
                message="Character picture skipped because the persona has no usable description or system prompt.",
            )
            return {"ok": False, "message": "Add a description or system prompt before generating a character picture."}
        self._record_visual_debug(
            source=str(source or "character_picture"),
            reason="character_picture",
            persona=persona,
            accepted=None,
            message="Character picture request sent to Visual Reply.",
            prompt=prompt,
        )
        try:
            result = visual_service.request_generation(
                prompt=prompt,
                caption=f"Character picture: {persona.display_name}",
                provider=str(persona.visual.provider or "inherit"),
                model=str(persona.visual.model or ""),
                size=str(persona.visual.size or "inherit"),
                source=source,
                metadata={"persona_id": persona.id, "purpose": "character_picture"},
                auto_show=auto_show,
            )
        except Exception as exc:
            self._record_visual_debug(
                source=str(source or "character_picture"),
                reason="character_picture",
                persona=persona,
                accepted=False,
                message=f"Character picture generation failed: {exc}",
                prompt=prompt,
            )
            return {"ok": False, "message": f"Character picture generation failed:\n\n{exc}"}
        image_path = ""
        if isinstance(result, dict):
            image_path = str(result.get("image_path") or "").strip()
        if image_path and Path(image_path).exists():
            persona.character_image_path = image_path
            self.save_state()
            self._request_ui_refresh()
            self._record_visual_debug(
                source=str(source or "character_picture"),
                reason="character_picture",
                persona=persona,
                accepted=True,
                message=f"Character picture generated: {image_path}",
                prompt=prompt,
            )
            return {"ok": True, "image_path": image_path, "message": "Character picture generated."}
        if result:
            self._record_visual_debug(
                source=str(source or "character_picture"),
                reason="character_picture",
                persona=persona,
                accepted=True,
                message="Visual Reply accepted the character picture request, but no image path was returned yet.",
                prompt=prompt,
            )
            return {
                "ok": True,
                "image_path": "",
                "message": "Visual Reply was requested, but no image path was returned yet.",
            }
        self._record_visual_debug(
            source=str(source or "character_picture"),
            reason="character_picture",
            persona=persona,
            accepted=False,
            message="Visual Reply request was not accepted.",
            prompt=prompt,
        )
        return {"ok": False, "message": "Visual Reply request was not accepted."}

    def handle_tts_persona_visual(self, persona_id: str, spoken_text: str = "") -> None:
        with self._state_lock:
            if self._shutting_down:
                return
            persona = self.persona_by_id(persona_id)
            if persona is None:
                return
            before_characters = tuple(self.session.ar_state.active_characters or [])
            self._add_persona_to_active_character_state(persona.id)
            changed = before_characters != tuple(self.session.ar_state.active_characters or [])
            if self.session.current_speaker_id != persona.id:
                self.session.current_speaker_id = persona.id
                changed = True
            if changed:
                self.save_state()
            show_character_visual = bool(self.settings.get("show_current_character_visual", False))
        if show_character_visual and changed:
            self._request_ui_refresh()
        if show_character_visual:
            self._maybe_generate_character_image_during_tts(persona)
        self._maybe_generate_visual_reply_during_tts(persona, spoken_text)

    def _maybe_generate_character_image_during_tts(self, persona: PersonaConfig) -> None:
        if persona is None:
            return
        image_path = str(persona.character_image_path or "").strip()
        if image_path and Path(image_path).exists():
            return
        if not self._character_picture_prompt(persona):
            return
        key = str(persona.id or "").strip()
        with self._state_lock:
            if self._shutting_down or not key or key in self._tts_persona_visual_inflight:
                return
            self._tts_persona_visual_inflight.add(key)
        if not self._queue_visual_worker("mprc_tts_character_image", lambda: self._run_tts_character_image_request(key)):
            with self._state_lock:
                self._tts_persona_visual_inflight.discard(key)

    def _run_tts_character_image_request(self, persona_id: str) -> None:
        if self.is_shutdown():
            return
        key = str(persona_id or "").strip()
        persona = self.persona_by_id(key)
        if persona is None:
            with self._state_lock:
                self._tts_persona_visual_inflight.discard(key)
            return
        try:
            result = self._request_character_image_generation(
                persona,
                auto_show=False,
                source="nc.multi_persona_roleplay.tts_character_picture",
            )
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                if result.get("ok"):
                    logger.info("[MPRC] TTS persona image requested for %s", persona.display_name)
                else:
                    logger.info("[MPRC] TTS persona image skipped for %s: %s", persona.display_name, result.get("message", "not accepted"))
        finally:
            with self._state_lock:
                self._tts_persona_visual_inflight.discard(key)

    def _maybe_generate_visual_reply_during_tts(self, persona: PersonaConfig, spoken_text: str = "") -> None:
        if persona is None or not self.session.enabled:
            return
        if self.visual_reply_service is None:
            if bool(getattr(getattr(persona, "visual", None), "enabled", False)):
                self._record_visual_debug(
                    source="tts_visual_trigger",
                    reason="tts_reply",
                    persona=persona,
                    accepted=False,
                    message="TTS Visual Reply skipped because the Visual Reply service is unavailable.",
                )
            return
        visual = persona.visual
        if not bool(getattr(visual, "enabled", False)):
            return
        mode = str(getattr(visual, "mode", "off") or "off")
        if mode not in {"auto_every_reply", "auto_every_n_replies", "auto_scene_change", "auto_character_change", "auto_important_moment"}:
            self._record_visual_debug(
                source="tts_visual_trigger",
                reason="tts_reply",
                persona=persona,
                accepted=False,
                message=f"TTS Visual Reply skipped because mode '{mode}' is not a TTS-triggered mode.",
            )
            return
        key = str(persona.id or "").strip()
        with self._state_lock:
            if self._shutting_down or not key or key in self._tts_visual_reply_inflight:
                return
            now = time.time()
            cooldown = max(0, int(getattr(visual, "cooldown_seconds", 0) or 0))
            if now - float(self._last_tts_visual_reply_at.get(key, 0.0) or 0.0) < max(3, cooldown):
                self._record_visual_debug(
                    source="tts_visual_trigger",
                    reason="tts_reply",
                    persona=persona,
                    accepted=False,
                    message="TTS Visual Reply skipped because cooldown is active.",
                )
                return
            if visual.max_auto_images_per_session and self.session.auto_image_count >= visual.max_auto_images_per_session:
                self._record_visual_debug(
                    source="tts_visual_trigger",
                    reason="tts_reply",
                    persona=persona,
                    accepted=False,
                    message="TTS Visual Reply skipped because the auto image limit was reached.",
                )
                return
            self._last_tts_visual_reply_at[key] = now
            self._tts_visual_reply_inflight.add(key)
        self._record_visual_debug(
            source="tts_visual_trigger",
            reason="tts_reply",
            persona=persona,
            accepted=None,
            message="TTS Visual Reply request queued for a background worker.",
            prompt=str(spoken_text or "")[:800],
        )
        if not self._queue_visual_worker(
            "mprc_tts_visual_reply",
            lambda: self._run_tts_visual_reply_request(key, str(spoken_text or "")),
        ):
            with self._state_lock:
                self._tts_visual_reply_inflight.discard(key)
            self._record_visual_debug(
                source="tts_visual_trigger",
                reason="tts_reply",
                persona=persona,
                accepted=False,
                message="TTS Visual Reply request could not start a background worker.",
            )

    def _run_tts_visual_reply_request(self, persona_id: str, spoken_text: str = "") -> None:
        if self.is_shutdown():
            return
        key = str(persona_id or "").strip()
        persona = self.persona_by_id(key)
        if persona is None:
            with self._state_lock:
                self._tts_visual_reply_inflight.discard(key)
            self._record_visual_debug(
                source="tts_visual_request",
                reason="tts_reply",
                accepted=False,
                message=f"No persona matched TTS Visual Reply request id '{persona_id}'.",
            )
            return
        try:
            result = self.visual_reply.request_generation(persona=persona, reason="tts_reply", source_text=spoken_text)
            logger = getattr(self.context, "logger", None)
            if logger is not None and not bool(result.get("accepted")):
                logger.info("[MPRC] TTS Visual Reply skipped for %s: %s", persona.display_name, result.get("message", "not accepted"))
        finally:
            with self._state_lock:
                self._tts_visual_reply_inflight.discard(key)

    def _warn(self, title: str, message: str):
        from PySide6 import QtWidgets

        parent = self._widget.window() if self._widget is not None else None
        QtWidgets.QMessageBox.warning(parent, str(title or "MPRC"), str(message or ""))

    def _character_picture_prompt(self, persona: PersonaConfig) -> str:
        pieces = [
            f"Character portrait of {persona.display_name}",
            persona.description,
            persona.ar_description,
            persona.visual.character_description,
            persona.visual.clothing_props,
            persona.visual.environment_style,
            persona.speaking_style,
            persona.role,
        ]
        if persona.system_prompt:
            pieces.append("Persona essence: " + persona.system_prompt[:360])
        pieces.append("single character, clear face, neutral background, no text, no watermark")
        prompt = ". ".join(str(item or "").strip(" .") for item in pieces if str(item or "").strip())
        return prompting._compact(prompt, 760)

    def _set_image_label(self, label, image_path: str, *, fallback_text: str = "No picture") -> None:
        if label is None:
            return
        from PySide6 import QtCore, QtGui

        label.setText("")
        label.setStyleSheet(
            "border: 1px solid #36506d; border-radius: 8px; "
            "background: #0e1723; color: #9fb3c8; padding: 0px;"
        )
        label.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        path = Path(str(image_path or "").strip())
        if str(image_path or "").strip() and path.exists():
            pixmap = QtGui.QPixmap(str(path))
            if not pixmap.isNull():
                try:
                    width = int(label.property("_mprc_image_width") or 0)
                    height = int(label.property("_mprc_image_height") or 0)
                except Exception:
                    width = 0
                    height = 0
                width = max(width, label.minimumWidth(), label.width(), 120)
                height = max(height, label.minimumHeight(), label.height(), 120)
                target = QtCore.QSize(max(1, width - 10), max(1, height - 10))
                label.setPixmap(
                    pixmap.scaled(
                        target,
                        QtCore.Qt.KeepAspectRatio,
                        QtCore.Qt.SmoothTransformation,
                    )
                )
                return
        label.setPixmap(QtGui.QPixmap())
        label.setText(fallback_text)

    def _refresh_character_preview(self):
        panel = self._controls.get("character_preview_panel")
        if panel is None:
            return
        view_mode = self._current_character_view_mode()
        view_combo = self._controls.get("current_character_view_mode")
        if view_combo is not None and hasattr(view_combo, "findData"):
            view_combo.blockSignals(True)
            index = view_combo.findData(view_mode)
            view_combo.setCurrentIndex(max(0, index))
            view_combo.blockSignals(False)
        visible = bool(self.settings.get("show_current_character_visual", False))
        if visible:
            panel.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
            panel.setMinimumHeight(500)
            panel.setMaximumHeight(16777215)
        else:
            panel.setMinimumHeight(0)
            panel.setMaximumHeight(0)
            panel.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Ignored)
        panel.setVisible(visible)
        try:
            panel.updateGeometry()
            parent = panel.parentWidget()
            while parent is not None:
                parent.updateGeometry()
                parent = parent.parentWidget()
            self._sync_mprc_tab_stack_height()
        except Exception:
            pass
        if not visible:
            return
        active = self._current_character_preview_persona()
        if active is None:
            for key, value in (
                ("current_character_name", "No story persona"),
                ("current_character_role", ""),
                ("current_character_meta", ""),
                ("current_character_story", "Load or create a story to populate the active story roster."),
            ):
                widget = self._controls.get(key)
                if widget is not None and hasattr(widget, "setText"):
                    widget.setText(value)
            self._set_image_label(self._controls.get("current_character_image"), "", fallback_text="No picture")
            self._refresh_character_roster_strip()
            return
        self._controls["current_character_name"].setText(active.display_name)
        self._controls["current_character_role"].setText(
            f"{active.role or active.behavior_mode}\n{active.description}".strip()
        )
        self._refresh_current_character_quick_info(active)
        self._set_image_label(self._controls.get("current_character_image"), active.character_image_path, fallback_text="No picture")
        self._refresh_character_roster_strip()

    def _current_character_view_mode(self) -> str:
        mode = str(self.settings.get("current_character_view_mode") or "active_story").strip().lower()
        return mode if mode in {"active_story", "all"} else "active_story"

    def _current_character_active_story_persona_ids(self) -> list[str]:
        known = {persona.id for persona in self.personas}
        ids = [persona_id for persona_id in self._current_linked_persona_ids() if persona_id in known]
        if not ids:
            ids = [
                normalize_persona_id(item)
                for item in list(getattr(self.session.ar_state, "active_characters", []) or [])
                if normalize_persona_id(item) in known
            ]
        if not ids:
            ids = [
                persona_id
                for persona_id in (self.session.current_speaker_id, self.session.active_persona_id)
                if str(persona_id or "").strip() and persona_id in known
            ]
        return list(dict.fromkeys(ids))

    def _current_character_roster_personas(self) -> list[PersonaConfig]:
        if self._current_character_view_mode() == "all":
            return list(self.personas)
        ids = self._current_character_active_story_persona_ids()
        by_id = {persona.id: persona for persona in self.personas}
        return [by_id[persona_id] for persona_id in ids if persona_id in by_id]

    def _current_character_preview_persona(self) -> PersonaConfig | None:
        personas = self._current_character_roster_personas()
        if not personas:
            return None
        current = self.current_speaker_persona() or self.active_persona()
        if current is not None and any(persona.id == current.id for persona in personas):
            return current
        return personas[0]

    def _refresh_current_character_quick_info(self, persona: PersonaConfig) -> None:
        meta = self._controls.get("current_character_meta")
        story = self._controls.get("current_character_story")
        if meta is not None:
            meta.setText(self._current_character_meta_text(persona))
        if story is not None:
            story.setText(self._current_character_story_text(persona))

    def _current_character_meta_text(self, persona: PersonaConfig) -> str:
        voice = persona.voice
        voice_sample = str(getattr(voice, "sample_path", "") or "").strip()
        voice_ready = bool(getattr(voice, "enabled", False) and voice_sample and Path(voice_sample).exists())
        if getattr(voice, "enabled", False):
            voice_text = "ready" if voice_ready else "needs sample"
        else:
            voice_text = "off"
        visual_ready = "image ready" if str(persona.character_image_path or "").strip() and Path(str(persona.character_image_path)).exists() else "no avatar image"
        ar_text = "AR profile on" if bool(getattr(persona, "ar_profile_enabled", False)) else "AR profile off"
        narrator = "Narrator" if persona.id == self.selected_narrator_persona_id() else "Character"
        pieces = [
            f"ID: {persona.id}",
            f"Type: {narrator}",
            f"Behavior: {persona.behavior_mode or 'default'}",
            f"Memory: {persona.memory_scope or 'default'}",
            f"Voice: {voice_text}",
            f"Visual: {visual_ready}",
            ar_text,
        ]
        return " | ".join(pieces)

    def _current_character_story_text(self, persona: PersonaConfig) -> str:
        current = self._current_story_involvement(persona)
        saved = self._saved_story_involvement(persona)
        if current and saved:
            return f"Stories: {current}. Also in saved: {', '.join(saved[:4])}"
        if current:
            return f"Stories: {current}"
        if saved:
            return f"Stories: saved in {', '.join(saved[:5])}"
        return "Stories: not linked to a saved Master Story yet."

    def _current_story_involvement(self, persona: PersonaConfig) -> str:
        title = str(self.settings.get("last_master_story_title") or self.settings.get("last_master_story_id") or "").strip()
        if not title:
            return ""
        roles = []
        if persona.id == self.session.active_persona_id:
            roles.append("active")
        if persona.id == self.session.current_speaker_id:
            roles.append("speaking")
        if persona.id in self._master_story_linked_persona_ids():
            roles.append("linked")
        if persona.id in self._master_story_created_persona_ids():
            roles.append("new")
        if not roles:
            return ""
        return f"{title} ({', '.join(dict.fromkeys(roles))})"

    def _saved_story_involvement(self, persona: PersonaConfig) -> list[str]:
        matches = []
        for item in self.storage.load_story_index():
            story_id = str(item.get("id") or "").strip()
            payload = self.storage.load_story(story_id)
            if self._story_payload_includes_persona(payload, persona):
                matches.append(str(item.get("title") or story_id).strip() or story_id)
        return matches

    def _story_payload_includes_persona(self, payload: dict[str, Any], persona: PersonaConfig) -> bool:
        if not isinstance(payload, dict):
            return False
        wanted = {persona.id, normalize_persona_id(persona.display_name)}
        for key in ("active_persona_id", "current_speaker_id"):
            if normalize_persona_id(payload.get(key)) in wanted:
                return True
        session = dict(payload.get("session") or {}) if isinstance(payload.get("session"), dict) else {}
        ar_state = dict(session.get("ar_state") or {}) if isinstance(session.get("ar_state"), dict) else {}
        for item in list(ar_state.get("active_characters") or []):
            if normalize_persona_id(item) in wanted:
                return True
        for item in list(payload.get("personas") or []):
            if not isinstance(item, dict):
                continue
            if normalize_persona_id(item.get("id")) in wanted:
                return True
            if normalize_persona_id(item.get("display_name")) in wanted:
                return True
        overrides = payload.get("persona_overrides")
        if isinstance(overrides, dict):
            for key, value in overrides.items():
                if normalize_persona_id(key) in wanted:
                    return True
                if isinstance(value, dict) and normalize_persona_id(value.get("display_name")) in wanted:
                    return True
        return False

    def _current_character_persona(self) -> PersonaConfig | None:
        return self._current_character_preview_persona()

    def _set_current_character_quick_status(self, message: str) -> None:
        label = self._controls.get("current_character_quick_status")
        if label is not None:
            label.setText(str(message or ""))

    def _quick_change_avatar_image(self):
        persona = self._current_character_persona()
        if persona is None:
            return
        start = str(Path(persona.character_image_path).parent) if str(persona.character_image_path or "").strip() else str(Path.home())
        path = self._open_file("Choose avatar image", start, "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*.*)")
        if not path:
            return
        persona.character_image_path = path
        self.save_state()
        self.refresh_ui()
        self._set_current_character_quick_status(f"Avatar image updated for {persona.display_name}.")

    def _quick_save_persona(self):
        persona = self._current_character_persona()
        self.storage.save_settings(self.settings)
        self.save_state()
        self._notify_changed()
        self._set_current_character_quick_status(f"Saved {persona.display_name if persona else 'persona settings'}.")

    def _quick_import_persona(self):
        try:
            path = self._open_file("Import persona JSON", str(Path.home()), "JSON files (*.json)")
            if not path:
                return
            personas = self.storage.import_personas_from_path(path)
            self.personas = personas
            self.session.active_persona_id = personas[0].id
            self.session.current_speaker_id = personas[0].id
            self.save_state()
            self.refresh_ui()
            self._set_current_character_quick_status(f"Imported {len(personas)} persona(s).")
        except Exception as exc:
            self._warn("Import Persona", f"Import failed:\n\n{exc}")

    def _quick_duplicate_persona(self):
        source = self._current_character_persona()
        if source is None:
            return
        payload = source.to_dict()
        payload["id"] = unique_persona_id(source.id + "_copy", {p.id for p in self.personas})
        payload["display_name"] = source.display_name + " Copy"
        persona = PersonaConfig.from_dict(payload)
        self.personas.append(persona)
        self.session.active_persona_id = persona.id
        self.session.current_speaker_id = persona.id
        self.save_state()
        self.refresh_ui()
        self._set_current_character_quick_status(f"Duplicated {source.display_name} as {persona.display_name}.")

    def _quick_edit_persona(self):
        persona = self._current_character_persona()
        if persona is None:
            return
        self.session.active_persona_id = persona.id
        self.session.current_speaker_id = persona.id
        self.save_state()
        self.refresh_ui()
        self._select_mprc_tab(2)
        self._set_current_character_quick_status(f"Editing {persona.display_name}.")

    def _refresh_character_roster_strip(self):
        from PySide6 import QtCore, QtWidgets

        layout = self._controls.get("character_roster_layout")
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            child = item.widget()
            if child is not None:
                child.setParent(None)
                child.deleteLater()
        active_id = str(self.session.current_speaker_id or self.session.active_persona_id or "")
        tile_width = 132
        tile_height = 134
        tile_spacing = 12
        count = 0
        roster_personas = self._current_character_roster_personas()
        for persona in roster_personas:
            count += 1
            tile = QtWidgets.QFrame()
            tile.setObjectName("mprc_character_roster_tile")
            tile.setFixedSize(tile_width, tile_height)
            tile.setMinimumSize(tile_width, tile_height)
            tile.setMaximumSize(tile_width, tile_height)
            tile.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
            tile.setToolTip(f"Switch active persona to {persona.display_name}.")
            tile.setCursor(QtCore.Qt.PointingHandCursor)
            tile.setProperty("active", persona.id == active_id)
            tile.setStyleSheet(
                """
                QFrame#mprc_character_roster_tile {
                    border: 1px solid #36506d;
                    border-radius: 10px;
                    background: #101b27;
                }
                QFrame#mprc_character_roster_tile[active="true"] {
                    border: 2px solid #2d5f93;
                    background: #17263a;
                }
                QFrame#mprc_character_roster_tile:hover {
                    border: 1px solid #4e7ead;
                    background: #132234;
                }
                """
            )
            tile_layout = QtWidgets.QVBoxLayout(tile)
            tile_layout.setContentsMargins(5, 5, 5, 6)
            tile_layout.setSpacing(4)
            preview = QtWidgets.QLabel()
            preview.setFixedSize(120, 96)
            preview.setMinimumSize(120, 96)
            preview.setMaximumSize(120, 96)
            preview.setProperty("_mprc_image_width", 120)
            preview.setProperty("_mprc_image_height", 96)
            preview.setAlignment(QtCore.Qt.AlignCenter)
            self._set_image_label(preview, persona.character_image_path, fallback_text="No picture")
            tile_layout.addWidget(preview, 0, QtCore.Qt.AlignCenter)
            name = QtWidgets.QLabel(str(persona.display_name or persona.id).strip() or persona.id)
            name.setObjectName("mprc_character_roster_name")
            name.setAlignment(QtCore.Qt.AlignCenter)
            name.setWordWrap(False)
            name.setToolTip(str(persona.display_name or persona.id))
            name.setStyleSheet("QLabel#mprc_character_roster_name { color: #dbeafe; background: transparent; border: none; font-weight: 700; }")
            name.setFixedHeight(20)
            tile_layout.addWidget(name, 0)
            tile.mousePressEvent = lambda _event, pid=persona.id: self._select_persona_id(pid)
            layout.addWidget(tile, 0, QtCore.Qt.AlignTop)
        content = self._controls.get("character_roster_content")
        if content is not None:
            total_width = max(1, (tile_width * count) + (tile_spacing * max(0, count - 1)))
            content.setMinimumWidth(total_width)
            content.setFixedWidth(total_width)
            content.setFixedHeight(tile_height)
            content.setMinimumHeight(tile_height)
        layout.setSpacing(tile_spacing)

    def _character_thumbnail_icon(self, persona: PersonaConfig):
        from PySide6 import QtCore, QtGui

        path = Path(str(persona.character_image_path or "").strip())
        if path.exists():
            pixmap = QtGui.QPixmap(str(path))
            if not pixmap.isNull():
                return QtGui.QIcon(pixmap.scaled(220, 170, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        fallback = self._tab_icon("editor", "#a78bfa")
        return QtGui.QIcon(fallback.pixmap(QtCore.QSize(170, 170)))

    def _select_persona_id(self, persona_id: str):
        target = str(persona_id or "").strip()
        if not target:
            return
        self.session.active_persona_id = target
        self.session.current_speaker_id = target
        if self._voice_follows_active():
            self.settings["voice_edit_persona_id"] = target
            self.storage.save_settings(self.settings)
        self.save_state()
        self.refresh_ui()

    def _test_voice(self):
        self._update_voice_warning()
        warning_label = self._controls.get("voice_warning")
        warning = str(warning_label.text() if warning_label is not None and hasattr(warning_label, "text") else "").strip()
        persona = self._selected_voice_persona()
        if persona is None:
            if warning_label is not None and hasattr(warning_label, "setText"):
                warning_label.setText("No voice persona is selected.")
            return
        route = self.voice_router.effective_voice_config({
            "persona_id": persona.id,
            "tts_backend": self.current_tts_backend(),
            "text": f"[CHARACTER: {persona.display_name}]\nVoice preview.",
        })
        sample = str(route.get("sample_path") or getattr(persona.voice, "sample_path", "") or "").strip()
        if not sample:
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("Voice test skipped: %s", warning)
            if warning_label is not None and hasattr(warning_label, "setText"):
                warning_label.setText(warning or f"{persona.display_name} has no usable voice sample.")
            return
        self._preview_voice_sample(sample, f"[CHARACTER: {persona.display_name}]\n{self._default_voice_preview_text()}", status_label=warning_label)

    def _update_voice_warning(self):
        persona = self._selected_voice_persona()
        payload = {"tts_backend": self.current_tts_backend()}
        if persona is not None:
            payload["persona_id"] = persona.id
        route = self.voice_router.effective_voice_config(payload)
        warning = str(route.get("warning") or "")
        if not warning and route.get("enabled") and route.get("supported"):
            warning = "Voice sample will be routed to the active TTS backend for new assistant replies."
        narrator_status = self._narrator_voice_status_text()
        if narrator_status:
            warning = f"{narrator_status}\n{warning}".strip()
        self._controls["voice_warning"].setText(warning)
        self._debug_voice = json.dumps(route, indent=2)
        self._refresh_debug()

    def _narrator_voice_status_text(self) -> str:
        if self.session.mode != AR_MODE:
            return ""
        narrator = self.selected_narrator_persona()
        if narrator is None:
            return "AR narrator: Auto could not find a narrator persona. Add a narrator-tagged persona or choose one explicitly."
        mode = "Auto" if self._narrator_selection_mode() == "auto" else "Selected"
        payload = {
            "persona_id": narrator.id,
            "tts_backend": self.current_tts_backend(),
            "text": "[NARRATOR] Voice route check.",
        }
        route = self.voice_router.effective_voice_config(payload)
        sample = str(route.get("sample_path") or "").strip()
        if sample:
            return f"AR narrator ({mode}): {narrator.display_name} -> {Path(sample).name}"
        warning = str(route.get("warning") or "").strip()
        if warning:
            return f"AR narrator ({mode}): {narrator.display_name}. {warning}"
        return f"AR narrator ({mode}): {narrator.display_name}."

    def _reset_scene(self):
        active_id = self.session.active_persona_id
        mode = self.session.mode
        ar_pacing = self.session.ar_pacing
        ar_interaction = self.session.ar_interaction_frequency
        self.session = RoleplaySessionState(
            mode=mode,
            active_persona_id=active_id,
            current_speaker_id=active_id,
            ar_pacing=ar_pacing,
            ar_interaction_frequency=ar_interaction,
        )
        if self.session.mode == AR_MODE:
            self.ensure_ar_state()
        self.save_state()
        self.refresh_ui()

    def _export_session(self):
        path = self._save_file("Export roleplay session", str(Path.home() / "mprc_session.json"), "JSON files (*.json)")
        if path:
            Path(path).write_text(json.dumps(self.session.to_dict(), indent=2, ensure_ascii=True), encoding="utf-8")

    def _import_session(self):
        path = self._open_file("Import roleplay session", str(Path.home()), "JSON files (*.json)")
        if path:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            self.session = RoleplaySessionState.from_dict(payload if isinstance(payload, dict) else {})
            self._ensure_session_persona()
            self.save_state()
            self.refresh_ui()

    def _preview_visual_prompt(self):
        payload = self.visual_reply.build_prompt(persona=self._selected_persona(), reason="manual")
        self._debug_visual_prompt = json.dumps(payload, indent=2)
        self._refresh_debug()

    def _generate_visual_reply(self):
        persona = self._selected_persona()
        persona_id = str(getattr(persona, "id", "") or "")
        self._debug_visual_prompt = json.dumps(
            {"queued": True, "message": "Visual Reply request queued for a background worker.", "persona_id": persona_id},
            indent=2,
            ensure_ascii=True,
        )
        self._refresh_debug()
        if not self._queue_visual_worker(
            "mprc_manual_visual_reply",
            lambda: self._run_manual_visual_reply_request(persona_id, kind="manual_visual_reply"),
        ):
            result = {"accepted": False, "message": "Visual Reply request could not start a background worker."}
            self._on_manual_visual_finished("manual_visual_reply", persona_id, result)

    def _clear_debug(self):
        self._debug_prompt = ""
        self._debug_visual_prompt = ""
        self._chat_visual_prompt_debug = ""
        self._debug_voice = ""
        self._refresh_debug()

    def _refresh_debug(self):
        if not self._controls:
            return
        persona = self.active_persona()
        if persona is not None and not self._debug_prompt:
            context = self.roleplay_engine.chat_context({}) if self.session.enabled else None
            self._debug_prompt = str((context or {}).get("context") or "")
        state = self.session.to_dict()
        if "debug_prompt" in self._controls:
            self._controls["debug_prompt"].setPlainText(self._debug_prompt)
            self._controls["debug_visual"].setPlainText(self._debug_visual_prompt)
            self._controls["debug_voice"].setPlainText(self._debug_voice)
            self._controls["debug_state"].setPlainText(json.dumps(state, indent=2))
        if "debug_visual_calls" in self._controls:
            self._controls["debug_visual_calls"].setPlainText(self._visual_debug_log_text())
        if "chat_visual_prompt_debug" in self._controls:
            text = self._chat_visual_prompt_debug or "Visual prompt debug will appear here after an MPRC Visual Reply request."
            self._controls["chat_visual_prompt_debug"].setPlainText(text)
        self._refresh_chat_play_story_engine_cards()
