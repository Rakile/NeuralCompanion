from __future__ import annotations

import copy
import json
import re
import threading
import time
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from . import instructor_adapter, structured_models
from .llm_runtime import BuddyProviderRuntime, CompletionHandler, ProviderCallConfig, list_lmstudio_models_for_base_url
from .models import (
    AVATAR_PROMPT_PRESETS,
    DEFAULT_AVATAR_PROMPT_PRESET,
    DEFAULT_SYSTEM_OVERRIDE_PROMPT,
    AvatarProfile,
    BuddyPersona,
    BuddySettings,
    ProviderOverride,
    PROVIDER_IDS,
    default_avatar_prompt,
)
from .prompting import buddy_context_prompt, build_persona_messages, compact_text
from .voice_segments import split_buddy_voice_segments


SETTINGS_PATH = "settings.json"


class _BuddyUiBridge(QtCore.QObject):
    test_finished = QtCore.Signal(str)
    model_catalog_finished = QtCore.Signal(str, object, str)
    avatar_finished = QtCore.Signal(int, object)
    active_persona_changed = QtCore.Signal(object)

    def __init__(self, controller: "BuddyChatController") -> None:
        super().__init__()
        self.controller = controller
        self.test_finished.connect(self._on_test_finished)
        self.model_catalog_finished.connect(self._on_model_catalog_finished)
        self.avatar_finished.connect(self._on_avatar_finished)
        self.active_persona_changed.connect(self._on_active_persona_changed)

    @QtCore.Slot(str)
    def _on_test_finished(self, message: str) -> None:
        label = self.controller._controls.get("status_label")
        if label is not None:
            label.setText(str(message or ""))

    @QtCore.Slot(str, object, str)
    def _on_model_catalog_finished(self, target_key: str, models: object, error: str) -> None:
        controller = self.controller
        if controller is not None:
            controller._on_model_catalog_finished(str(target_key or ""), list(models or []), str(error or ""))

    @QtCore.Slot(int, object)
    def _on_avatar_finished(self, row_index: int, result: object) -> None:
        controller = self.controller
        if controller is not None:
            controller._on_avatar_generation_finished(int(row_index), dict(result or {}))

    @QtCore.Slot(object)
    def _on_active_persona_changed(self, payload: object) -> None:
        controller = self.controller
        if controller is not None:
            controller._on_active_persona_changed(dict(payload or {}))


class ActivePersonaWindow(QtWidgets.QWidget):
    """Small non-modal display for the buddy that most recently spoke."""

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowTitle("Buddy Chat - Active Persona")
        self.setMinimumSize(380, 430)
        self.avatar_label = QtWidgets.QLabel("Avatar")
        self.avatar_label.setAlignment(QtCore.Qt.AlignCenter)
        self.avatar_label.setFixedSize(180, 180)
        self.avatar_label.setStyleSheet(
            "border: 1px solid #2d4661; border-radius: 8px; background: #0f1722; color: #9fb3c8;"
        )
        self.name_label = QtWidgets.QLabel("No active buddy")
        name_font = self.name_label.font()
        name_font.setPointSize(20)
        name_font.setBold(True)
        self.name_label.setFont(name_font)
        self.name_label.setAlignment(QtCore.Qt.AlignCenter)
        self.role_label = QtWidgets.QLabel("Waiting for Buddy Chat activity.")
        self.role_label.setAlignment(QtCore.Qt.AlignCenter)
        self.role_label.setWordWrap(True)
        self.style_label = QtWidgets.QLabel("")
        self.style_label.setAlignment(QtCore.Qt.AlignCenter)
        self.style_label.setWordWrap(True)
        self.details_label = QtWidgets.QLabel("")
        self.details_label.setAlignment(QtCore.Qt.AlignCenter)
        self.details_label.setWordWrap(True)
        self.last_line = QtWidgets.QPlainTextEdit()
        self.last_line.setReadOnly(True)
        self.last_line.setMaximumHeight(96)
        self.last_line.setPlaceholderText("The latest buddy line will appear here.")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(self.avatar_label, alignment=QtCore.Qt.AlignHCenter)
        layout.addWidget(self.name_label)
        layout.addWidget(self.role_label)
        layout.addWidget(self.style_label)
        layout.addWidget(self.details_label)
        layout.addWidget(self.last_line)
        self.setStyleSheet(
            """
            QWidget { background: #0b1017; color: #e8f2ff; }
            QPlainTextEdit {
                background: #101923;
                color: #e8f2ff;
                border: 1px solid #2d4661;
                border-radius: 6px;
                padding: 8px;
            }
            """
        )

    def set_on_top(self, enabled: bool) -> None:
        visible = self.isVisible()
        flags = QtCore.Qt.Window
        if bool(enabled):
            flags |= QtCore.Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        if visible:
            self.show()

    def update_persona(self, persona: BuddyPersona | None, *, text: str = "", reason: str = "") -> None:
        if persona is None:
            self.name_label.setText("No active buddy")
            self.role_label.setText("Waiting for Buddy Chat activity.")
            self.style_label.setText("")
            self.details_label.setText("")
            self.last_line.setPlainText("")
            self._set_avatar("")
            return
        self.name_label.setText(str(persona.display_name or persona.id or "Buddy"))
        self.role_label.setText(str(persona.role or persona.description or "Buddy persona"))
        style_parts = []
        if persona.speaking_style:
            style_parts.append("Style: " + str(persona.speaking_style))
        if reason:
            style_parts.append("Active from: " + str(reason))
        self.style_label.setText(" | ".join(style_parts))
        detail_parts = []
        if persona.voice.enabled and persona.voice.sample_path:
            detail_parts.append("Voice ready")
        if persona.provider.provider_id and persona.provider.provider_id not in {"inherit", "main"}:
            detail_parts.append("LLM: " + str(persona.provider.provider_id))
        self.details_label.setText(" | ".join(detail_parts))
        self.last_line.setPlainText(str(text or "").strip())
        self._set_avatar(str(persona.avatar.image_path or ""))

    def _set_avatar(self, image_path: str) -> None:
        path = Path(str(image_path or "").strip())
        if not path.exists() or not path.is_file():
            self.avatar_label.setPixmap(QtGui.QPixmap())
            self.avatar_label.setText("Avatar")
            return
        pixmap = QtGui.QPixmap(str(path))
        if pixmap.isNull():
            self.avatar_label.setPixmap(QtGui.QPixmap())
            self.avatar_label.setText("Avatar")
            return
        self.avatar_label.setText("")
        self.avatar_label.setPixmap(
            pixmap.scaled(self.avatar_label.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        )


class _BuddyTabButton(QtWidgets.QFrame):
    clicked = QtCore.Signal(int)

    def __init__(self, index: int, title: str, icon: QtGui.QIcon, color: str, tooltip: str, parent=None) -> None:
        super().__init__(parent)
        self._index = int(index)
        self._color = str(color or "#38bdf8")
        self._selected = False
        self.setObjectName("buddy_custom_tab_button")
        self.setProperty("buddy_tab_title", str(title or ""))
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip(str(tooltip or "").strip())
        self.setMinimumSize(88, 68)
        self.setMaximumSize(122, 68)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(7, 4, 7, 5)
        layout.setSpacing(1)

        self._title = QtWidgets.QLabel(str(title or ""))
        self._title.setObjectName("buddy_custom_tab_title")
        self._title.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self._title.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)
        title_font = self._title.font()
        title_font.setBold(True)
        self._title.setFont(title_font)
        self._title.setMinimumHeight(16)

        self._icon = QtWidgets.QLabel()
        self._icon.setObjectName("buddy_custom_tab_icon")
        self._icon.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self._icon.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)
        self._icon.setPixmap(icon.pixmap(QtCore.QSize(36, 36)))
        self._icon.setFixedHeight(38)

        layout.addWidget(self._title)
        layout.addWidget(self._icon)
        self._apply_style()

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self._apply_style()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit(self._index)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _apply_style(self) -> None:
        background = "#1c2d43" if self._selected else "#111b28"
        border = self._color if self._selected else "#36506d"
        self.setStyleSheet(
            f"""
            QFrame#buddy_custom_tab_button {{
                background: {background};
                border: 1px solid {border};
                border-radius: 9px;
            }}
            QLabel#buddy_custom_tab_title {{
                color: {self._color};
                background: transparent;
                border: none;
                font-size: 12px;
            }}
            QLabel#buddy_custom_tab_icon {{
                background: transparent;
                border: none;
            }}
            """
        )


class _BuddyCurrentPageStack(QtWidgets.QStackedWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.currentChanged.connect(lambda *_args: self.updateGeometry())

    def sizeHint(self):
        current = self.currentWidget()
        return current.sizeHint() if current is not None else super().sizeHint()

    def minimumSizeHint(self):
        current = self.currentWidget()
        return current.minimumSizeHint() if current is not None else super().minimumSizeHint()


class _BuddyTabNavScrollArea(QtWidgets.QScrollArea):
    def wheelEvent(self, event) -> None:
        event.ignore()


class BuddyChatController:
    _SUPPORTED_CAPABILITIES = frozenset(
        {
            "buddy_chat.assistant_reply",
            "buddy_chat.contextual_reply",
            "buddy_chat.status",
            "chat.user_text_command",
            "chat_context.collect",
            "tts.voice_segments",
            "tts.voice_segments.requires_full_text",
            "tts.voice_warmup_paths",
        }
    )

    def __init__(self, context, completion_handler: CompletionHandler | None = None) -> None:
        self.context = context
        self.settings = self._load_settings()
        self._state_lock = threading.RLock()
        self._shutting_down = False
        self._settings_write_lock = threading.RLock()
        self._pending_settings_payload: dict[str, Any] | None = None
        self._settings_write_thread: threading.Thread | None = None
        self._last_session_export_state: dict[str, Any] = self._session_export_payload_unlocked()
        self.llm_runtime = BuddyProviderRuntime(completion_handler=completion_handler)
        self.visual_reply_service = context.get_service("qt.visual_reply") if context is not None else None
        self._controls: dict[str, Any] = {}
        self._persona_rows_layout: QtWidgets.QVBoxLayout | None = None
        self._persona_voice_rows_layout: QtWidgets.QVBoxLayout | None = None
        self._persona_avatar_rows_layout: QtWidgets.QVBoxLayout | None = None
        self._persona_provider_rows_layout: QtWidgets.QVBoxLayout | None = None
        self._model_catalog_lock = threading.RLock()
        self._model_catalog_inflight: set[str] = set()
        self._ui_bridge = _BuddyUiBridge(self)
        self._active_persona_id = ""
        self._active_persona_text = ""
        self._active_persona_reason = ""
        self._stream_voice_persona_id = ""
        self._active_persona_window: ActivePersonaWindow | None = None
        self._last_provider_error = ""
        self._last_provider_error_at = 0.0

    def invoke_capability_threadsafe(self, capability: str, payload: dict[str, Any] | None = None):
        name = str(capability or "").strip().lower()
        if name.startswith("real_ui.") or name not in self._SUPPORTED_CAPABILITIES:
            return None
        data = dict(payload or {})
        with self._state_lock:
            if self._shutting_down:
                return None
        return self.invoke_capability(name, data)

    def invoke_capability(self, capability: str, payload: dict[str, Any] | None = None):
        name = str(capability or "").strip().lower()
        data = dict(payload or {})
        if name == "chat_context.collect":
            return self._chat_context(data)
        if name == "chat.user_text_command":
            return self._handle_user_text_command(data)
        if name == "buddy_chat.contextual_reply":
            return self._handle_contextual_reply(data)
        if name == "buddy_chat.assistant_reply":
            return self._record_completed_reply(data)
        if name == "tts.voice_segments":
            return self._voice_segments(data)
        if name == "tts.voice_segments.requires_full_text":
            return self._requires_full_text_voice_segments(data)
        if name == "tts.voice_warmup_paths":
            return self._voice_warmup_paths()
        if name == "buddy_chat.status":
            return self.status_snapshot()
        return None

    def status_snapshot(self) -> dict[str, Any]:
        personas = []
        per_persona_provider_count = 0
        active_persona = self._persona_by_id(self._active_persona_id)
        for persona in list(self.settings.personas or []):
            provider_id = str(persona.provider.provider_id or "inherit").strip().lower() or "inherit"
            if provider_id not in {"inherit", "main"}:
                per_persona_provider_count += 1
            personas.append(
                {
                    "id": str(persona.id or ""),
                    "display_name": str(persona.display_name or ""),
                    "enabled": bool(persona.enabled),
                    "source": str(persona.source or "buddy_chat"),
                    "provider_id": provider_id,
                    "model": str(persona.provider.model or ""),
                    "voice_enabled": bool(persona.voice.enabled),
                    "avatar_prompt_ready": bool(str(persona.avatar.prompt or "").strip()),
                    "avatar_image_path": str(persona.avatar.image_path or ""),
                }
            )
        return {
            "available": True,
            "enabled": bool(self.settings.enabled),
            "reply_mode": str(self.settings.reply_mode or "context_only"),
            "llm_mode": str(self.settings.llm_mode or "main"),
            "buddy_chat_instructor_structured_outputs_enabled": bool(self.settings.instructor_structured_outputs_enabled),
            "buddy_chat_instructor_available": bool(instructor_adapter.instructor_availability().available),
            "persona_count": len(list(self.settings.personas or [])),
            "active_persona_count": len(self.settings.enabled_personas()),
            "max_speakers": int(self.settings.max_speakers or 1),
            "forced_buddy_every": int(self.settings.forced_buddy_every or 0),
            "completed_reply_count": int(self.settings.completed_reply_count or 0),
            "forced_buddy_due_next": bool(self._forced_buddy_due()),
            "per_persona_provider_count": int(per_persona_provider_count),
            "voice_routing_requires_full_text": False,
            "voice_routing_preserves_stream_labels": bool(self._has_active_voice_routes()),
            "active_persona_window_enabled": bool(self.settings.active_persona_window_enabled),
            "active_persona_window_on_top": bool(self.settings.active_persona_window_on_top),
            "active_persona_id": str(self._active_persona_id or ""),
            "active_persona_name": str(active_persona.display_name if active_persona is not None else ""),
            "last_provider_error": str(self._last_provider_error or ""),
            "last_provider_error_at": float(self._last_provider_error_at or 0.0),
            "shared_provider": {
                "provider_id": str(self.settings.buddy_provider.provider_id or "inherit").strip().lower() or "inherit",
                "model": str(self.settings.buddy_provider.model or ""),
            },
            "personas": personas,
        }

    def _has_active_voice_routes(self) -> bool:
        if not self.settings.enabled:
            return False
        for persona in self.settings.enabled_personas():
            voice = getattr(persona, "voice", None)
            if bool(getattr(voice, "enabled", False)) and str(getattr(voice, "sample_path", "") or "").strip():
                return True
        return False

    def _voice_warmup_paths(self) -> dict[str, Any] | None:
        if not self.settings.enabled:
            return None
        paths: list[str] = []
        for persona in self.settings.enabled_personas():
            voice = getattr(persona, "voice", None)
            path = str(getattr(voice, "sample_path", "") or "").strip()
            if not bool(getattr(voice, "enabled", False)) or not path or path in paths:
                continue
            paths.append(path)
        if not paths:
            return None
        return {"addon": "nc.buddy_chat", "paths": paths}

    def _voice_segments(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        streaming = bool(payload.get("streaming", False))
        stream_start = bool(payload.get("stream_start", False))
        if not self.settings.enabled:
            if streaming:
                with self._state_lock:
                    self._stream_voice_persona_id = ""
            return None

        personas = self.settings.enabled_personas()
        with self._state_lock:
            if streaming and stream_start:
                self._stream_voice_persona_id = ""
            current_persona_id = str(self._stream_voice_persona_id or "")

        text = str(payload.get("text") or "")
        result = split_buddy_voice_segments(text, personas=personas)
        explicit_segments = [
            dict(item)
            for item in list(result.get("segments") or [])
            if isinstance(item, dict)
        ]
        if streaming and not explicit_segments and current_persona_id:
            current_persona = next(
                (
                    persona
                    for persona in personas
                    if str(persona.id or "").strip().lower() == current_persona_id.lower()
                ),
                None,
            )
            if current_persona is not None and text.strip():
                result = split_buddy_voice_segments(
                    f"[{current_persona.display_name}]\n{text}",
                    personas=personas,
                )

        segments = [
            dict(item)
            for item in list(result.get("segments") or [])
            if isinstance(item, dict)
        ]
        if streaming and segments:
            with self._state_lock:
                self._stream_voice_persona_id = str(segments[-1].get("persona_id") or "")

        if explicit_segments:
            self._record_voice_routing_debug(result, payload)
            self._update_active_persona_from_voice_segments(result)
        return result if segments else None

    def _persona_by_id(self, persona_id: str) -> BuddyPersona | None:
        target = str(persona_id or "").strip().lower()
        if not target:
            return None
        for persona in list(self.settings.personas or []):
            if str(persona.id or "").strip().lower() == target:
                return persona
        return None

    def _display_persona(self) -> BuddyPersona | None:
        return self._persona_by_id(self._active_persona_id) or next(iter(self.settings.enabled_personas()), None)

    def _set_active_persona(self, persona_id: str, *, reason: str = "", text: str = "") -> None:
        persona = self._persona_by_id(persona_id)
        if persona is None:
            return
        self._active_persona_id = str(persona.id or "")
        self._active_persona_text = str(text or "").strip()
        self._active_persona_reason = str(reason or "").strip()
        try:
            self._ui_bridge.active_persona_changed.emit(
                {
                    "persona_id": self._active_persona_id,
                    "reason": self._active_persona_reason,
                    "text": self._active_persona_text,
                }
            )
        except Exception:
            return

    def _update_active_persona_from_voice_segments(self, result: dict[str, Any] | None) -> None:
        if not isinstance(result, dict):
            return
        for segment in list(result.get("segments") or []):
            if not isinstance(segment, dict):
                continue
            persona_id = str(segment.get("persona_id") or "").strip()
            if persona_id:
                self._set_active_persona(
                    persona_id,
                    reason="TTS voice segment",
                    text=str(segment.get("text") or "").strip(),
                )
                return

    def _on_active_persona_changed(self, payload: dict[str, Any]) -> None:
        if not bool(self.settings.active_persona_window_enabled):
            window = self._active_persona_window
            if window is not None and window.isVisible():
                self._update_active_persona_window(payload)
            return
        self._open_active_persona_window(payload)

    def _on_active_persona_window_option_changed(self) -> None:
        self._commit_ui_settings()
        window = self._active_persona_window
        if window is not None:
            window.set_on_top(bool(self.settings.active_persona_window_on_top))
        if bool(self.settings.active_persona_window_enabled):
            self._open_active_persona_window()

    def _ensure_active_persona_window(self) -> ActivePersonaWindow:
        if self._active_persona_window is None:
            self._active_persona_window = ActivePersonaWindow()
        self._active_persona_window.set_on_top(bool(self.settings.active_persona_window_on_top))
        return self._active_persona_window

    def _open_active_persona_window(self, payload: dict[str, Any] | None = None) -> None:
        window = self._ensure_active_persona_window()
        self._update_active_persona_window(dict(payload or {}) if isinstance(payload, dict) else {})
        window.show()
        window.raise_()
        window.activateWindow()

    def _update_active_persona_window(self, payload: dict[str, Any] | None = None) -> None:
        window = self._ensure_active_persona_window()
        data = dict(payload or {})
        persona = self._persona_by_id(str(data.get("persona_id") or self._active_persona_id or "")) or self._display_persona()
        text = str(data.get("text") or self._active_persona_text or "").strip()
        reason = str(data.get("reason") or self._active_persona_reason or "Manual open").strip()
        window.update_persona(persona, text=text, reason=reason)

    def _requires_full_text_voice_segments(self, payload: dict[str, Any]) -> dict[str, Any]:
        streaming = bool(payload.get("streaming", False))
        active_voice_routes = bool(self._has_active_voice_routes())
        preserve_voice_labels = bool(streaming and active_voice_routes)
        if not self.settings.enabled:
            reason = "buddy_chat_disabled"
        elif not streaming:
            reason = "buddy_chat_not_streaming"
        elif not active_voice_routes:
            reason = "buddy_chat_no_active_voice_routes"
        else:
            reason = "buddy_chat_streaming_voice_routing"
        return {
            "requires_full_text": False,
            "preserve_voice_labels": preserve_voice_labels,
            "reason": reason,
            "addon": "nc.buddy_chat",
            "active_voice_personas": [
                persona.id
                for persona in self.settings.enabled_personas()
                if bool(persona.voice.enabled) and str(persona.voice.sample_path or "").strip()
            ],
        }

    def _record_voice_routing_debug(self, result: dict[str, Any] | None, payload: dict[str, Any]) -> None:
        if not isinstance(result, dict):
            return
        segments = [dict(item) for item in list(result.get("segments") or []) if isinstance(item, dict)]
        if not segments and not bool(result.get("suppress_original", False)):
            return
        matched_personas = []
        missing_voice_personas = []
        voice_paths = []
        for segment in segments:
            persona_id = str(segment.get("persona_id") or "").strip()
            if not persona_id:
                continue
            if persona_id not in matched_personas:
                matched_personas.append(persona_id)
            voice_path = str(segment.get("voice_path") or "").strip()
            if voice_path:
                if voice_path not in voice_paths:
                    voice_paths.append(voice_path)
            elif persona_id not in missing_voice_personas:
                missing_voice_personas.append(persona_id)
        state = "Done" if segments else "Skipped"
        label = f"Buddy voice routing: {len(segments)} segment(s)" if segments else "Buddy voice routing: no matched segments"
        try:
            from core import debug_inspector

            queue_id = "buddy_chat.voice_routing." + str(abs(hash(str(payload.get("text", "")))))[:12]
            debug_inspector.begin_queue_item(
                queue_id,
                owner="nc.buddy_chat",
                label=label,
                kind="tts_voice_routing",
                state=state,
                waiting_on="TTS voice sample routing",
                source="addons/buddy_chat/controller.py",
                metadata={
                    "streaming": bool(payload.get("streaming", False)),
                    "suppress_original": bool(result.get("suppress_original", False)),
                    "segment_count": len(segments),
                    "matched_personas": matched_personas,
                    "voice_paths": voice_paths,
                    "missing_voice_personas": missing_voice_personas,
                    "text_preview": str(payload.get("text") or "")[:500],
                },
            )
            debug_inspector.finish_queue_item(queue_id, state=state)
        except Exception:
            return

    def build_tab(self):
        root = QtWidgets.QWidget()
        root.setObjectName("buddy_chat_root")
        layout = QtWidgets.QVBoxLayout(root)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)

        header = QtWidgets.QLabel("Buddy Chat")
        header.setToolTip("Lets selected buddy personas join main chat naturally without always forcing every persona to answer.")
        font = header.font()
        font.setPointSize(16)
        font.setBold(True)
        header.setFont(font)
        subtitle = QtWidgets.QLabel("Natural buddy participation, routed voices, avatars, and optional per-buddy models.")
        subtitle.setProperty("muted", True)
        subtitle.setWordWrap(True)
        layout.addWidget(header)
        layout.addWidget(subtitle)

        tabs = QtWidgets.QWidget()
        tabs.setObjectName("buddy_inner_tabs")
        tabs_layout = QtWidgets.QVBoxLayout(tabs)
        tabs_layout.setContentsMargins(5, 5, 5, 5)
        tabs_layout.setSpacing(4)
        nav_row = QtWidgets.QWidget()
        nav_row.setObjectName("buddy_inner_tab_nav_row")
        nav_row_layout = QtWidgets.QHBoxLayout(nav_row)
        nav_row_layout.setContentsMargins(0, 0, 0, 0)
        nav_row_layout.setSpacing(4)
        nav_prev = QtWidgets.QToolButton()
        nav_prev.setObjectName("buddy_inner_tab_prev_button")
        nav_prev.setText("<")
        nav_prev.setToolTip("Show earlier Buddy Chat tabs")
        nav_prev.setFixedSize(22, 58)
        nav_next = QtWidgets.QToolButton()
        nav_next.setObjectName("buddy_inner_tab_next_button")
        nav_next.setText(">")
        nav_next.setToolTip("Show later Buddy Chat tabs")
        nav_next.setFixedSize(22, 58)
        nav_scroll = _BuddyTabNavScrollArea()
        nav_scroll.setObjectName("buddy_inner_tab_scroll")
        nav_scroll.setWidgetResizable(False)
        nav_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        nav_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        nav_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        nav_scroll.setFixedHeight(84)
        nav_scroll.setFocusPolicy(QtCore.Qt.NoFocus)
        nav = QtWidgets.QWidget()
        nav.setObjectName("buddy_inner_tab_nav")
        nav.setFixedHeight(80)
        nav_layout = QtWidgets.QHBoxLayout(nav)
        nav_layout.setContentsMargins(0, 4, 0, 8)
        nav_layout.setSpacing(5)
        stack = _BuddyCurrentPageStack()
        stack.setObjectName("buddy_inner_tab_stack")

        overview_page, overview_layout = self._new_buddy_tab_page("Overview")
        buddies_page, buddies_layout = self._new_buddy_tab_page("Buddies")
        voices_page, voices_layout = self._new_buddy_tab_page("Voices")
        avatars_page, avatars_layout = self._new_buddy_tab_page("Avatars")
        providers_page, providers_layout = self._new_buddy_tab_page("Providers")
        advanced_page, advanced_layout = self._new_buddy_tab_page("Advanced")

        behavior_box = QtWidgets.QGroupBox("Chat Behavior")
        behavior_box.setToolTip("Choose when Buddy Chat is active and how naturally buddies join the main assistant reply.")
        behavior_layout = QtWidgets.QFormLayout(behavior_box)
        enabled = QtWidgets.QCheckBox("Enable Buddy Chat")
        enabled.setToolTip("Allow selected buddy personas to participate naturally in the main chat.")
        enabled.setChecked(self.settings.enabled)
        reply_mode = QtWidgets.QComboBox()
        reply_mode.setToolTip("Choose whether buddies only add context or write the main reply.")
        reply_mode.addItem("Assist main LLM with buddy context", "context_only")
        reply_mode.addItem("Buddy replies as main answer", "main_answer")
        self._set_combo_data(reply_mode, self.settings.reply_mode)
        llm_mode = QtWidgets.QComboBox()
        llm_mode.setToolTip("Choose whether buddies use the main LLM, one shared buddy provider, or per-persona providers.")
        llm_mode.addItem("Use Main LLM Runtime", "main")
        llm_mode.addItem("Use Buddy Provider", "buddy")
        llm_mode.addItem("Use Per-Persona Providers", "per_persona")
        self._set_combo_data(llm_mode, self.settings.llm_mode)
        max_speakers = QtWidgets.QSpinBox()
        max_speakers.setToolTip("Limits how many buddy personas can speak in one assistant reply.")
        max_speakers.setRange(1, 4)
        max_speakers.setValue(max(1, min(4, int(self.settings.max_speakers or 1))))
        forced_buddy_every = QtWidgets.QSpinBox()
        forced_buddy_every.setToolTip(
            "Force a rotating enabled buddy to answer every N completed replies. Set to 0 to disable forced turns."
        )
        forced_buddy_every.setRange(0, 100)
        forced_buddy_every.setSpecialValueText("Off")
        forced_buddy_every.setValue(max(0, min(100, int(self.settings.forced_buddy_every or 0))))
        instructor_structured_outputs = QtWidgets.QCheckBox("Use Instructor structured Buddy replies")
        instructor_structured_outputs.setToolTip(
            "Optional: validate Buddy main-answer replies as exact speaker segments before TTS voice routing. "
            "If Instructor is unavailable or validation fails, Buddy Chat uses the normal reply path."
        )
        instructor_structured_outputs.setChecked(bool(self.settings.instructor_structured_outputs_enabled))
        behavior_layout.addRow("", enabled)
        behavior_layout.addRow("Reply mode", reply_mode)
        behavior_layout.addRow("LLM provider mode", llm_mode)
        behavior_layout.addRow("Max buddies per reply", max_speakers)
        behavior_layout.addRow("Force buddy every N replies", forced_buddy_every)
        behavior_layout.addRow("Structured replies", instructor_structured_outputs)
        overview_layout.addWidget(behavior_box)

        persona_window_box = QtWidgets.QGroupBox("Active Persona Window")
        persona_window_layout = QtWidgets.QVBoxLayout(persona_window_box)
        active_persona_window_enabled = QtWidgets.QCheckBox("Show active persona window")
        active_persona_window_enabled.setToolTip(
            "Automatically open and update a small window showing the buddy persona that most recently spoke."
        )
        active_persona_window_enabled.setChecked(bool(self.settings.active_persona_window_enabled))
        active_persona_window_on_top = QtWidgets.QCheckBox("Keep on top")
        active_persona_window_on_top.setToolTip("Keep the active persona window above the main NC window.")
        active_persona_window_on_top.setChecked(bool(self.settings.active_persona_window_on_top))
        active_persona_window_open = QtWidgets.QPushButton("Open Active Persona Window")
        active_persona_window_open.setToolTip("Open the active persona window manually. It will show the last active buddy or the first enabled buddy.")
        active_persona_window_row = QtWidgets.QHBoxLayout()
        active_persona_window_row.setContentsMargins(0, 0, 0, 0)
        active_persona_window_row.addWidget(active_persona_window_enabled)
        active_persona_window_row.addWidget(active_persona_window_on_top)
        active_persona_window_row.addStretch(1)
        active_persona_window_row.addWidget(active_persona_window_open)
        active_persona_window_widget = QtWidgets.QWidget()
        active_persona_window_widget.setLayout(active_persona_window_row)
        persona_window_layout.addWidget(active_persona_window_widget)
        overview_layout.addWidget(persona_window_box)

        actions_box = QtWidgets.QGroupBox("Quick Actions")
        actions_layout = QtWidgets.QVBoxLayout(actions_box)
        action_row = QtWidgets.QHBoxLayout()
        add_button = QtWidgets.QPushButton("Add Buddy")
        add_button.setToolTip("Add a new buddy persona row.")
        import_button = QtWidgets.QPushButton("Load MPRC Personas")
        import_button.setToolTip("Import personas from Multi Persona Roleplay when available.")
        save_button = QtWidgets.QPushButton("Save")
        save_button.setToolTip("Save Buddy Chat settings.")
        action_row.addWidget(add_button)
        action_row.addWidget(import_button)
        action_row.addStretch(1)
        action_row.addWidget(save_button)
        status_label = QtWidgets.QLabel("Default: buddies use the same provider and model as LLM Runtime.")
        status_label.setToolTip("Shows the latest Buddy Chat status or shared buddy provider test result.")
        status_label.setWordWrap(True)
        status_label.setProperty("muted", True)
        actions_layout.addLayout(action_row)
        actions_layout.addWidget(status_label)
        overview_layout.addWidget(actions_box)
        overview_layout.addStretch(1)

        personas_box = QtWidgets.QGroupBox("Buddy Personas")
        personas_box.setToolTip("Configure each buddy's identity and basic speaking style.")
        personas_layout = QtWidgets.QVBoxLayout(personas_box)
        hint = QtWidgets.QLabel(
            "Edit who each buddy is here. Voice, avatar, and provider details have dedicated tabs."
        )
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        personas_layout.addWidget(hint)
        self._persona_rows_layout = QtWidgets.QVBoxLayout()
        self._persona_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._persona_rows_layout.setSpacing(8)
        personas_layout.addLayout(self._persona_rows_layout)
        buddies_layout.addWidget(personas_box)
        buddies_layout.addStretch(1)

        voice_box = QtWidgets.QGroupBox("Buddy Voices")
        voice_box.setToolTip("Choose the TTS voice sample used when each buddy speaks.")
        voice_layout = QtWidgets.QVBoxLayout(voice_box)
        voice_hint = QtWidgets.QLabel("Enable a voice sample per buddy when your active TTS backend supports reference voices.")
        voice_hint.setWordWrap(True)
        voice_hint.setProperty("muted", True)
        voice_layout.addWidget(voice_hint)
        self._persona_voice_rows_layout = QtWidgets.QVBoxLayout()
        self._persona_voice_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._persona_voice_rows_layout.setSpacing(8)
        voice_layout.addLayout(self._persona_voice_rows_layout)
        voices_layout.addWidget(voice_box)
        voices_layout.addStretch(1)

        avatar_box = QtWidgets.QGroupBox("Buddy Avatars")
        avatar_box.setToolTip("Create or edit visual identity prompts for buddy avatars.")
        avatar_layout = QtWidgets.QVBoxLayout(avatar_box)
        avatar_hint = QtWidgets.QLabel("Avatar generation uses the existing Visual Reply service; this tab only stores prompt and generated image path.")
        avatar_hint.setWordWrap(True)
        avatar_hint.setProperty("muted", True)
        avatar_layout.addWidget(avatar_hint)
        self._persona_avatar_rows_layout = QtWidgets.QVBoxLayout()
        self._persona_avatar_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._persona_avatar_rows_layout.setSpacing(8)
        avatar_layout.addLayout(self._persona_avatar_rows_layout)
        avatars_layout.addWidget(avatar_box)
        avatars_layout.addStretch(1)

        providers_layout.addWidget(self._build_shared_provider_box())
        persona_provider_box = QtWidgets.QGroupBox("Per-Buddy Provider Overrides")
        persona_provider_box.setToolTip("Optional per-persona LLM provider and model settings.")
        persona_provider_layout = QtWidgets.QVBoxLayout(persona_provider_box)
        provider_hint = QtWidgets.QLabel("Use Inherit for normal setup. Choose LM Studio or another provider only when a specific buddy should use a different model.")
        provider_hint.setWordWrap(True)
        provider_hint.setProperty("muted", True)
        persona_provider_layout.addWidget(provider_hint)
        self._persona_provider_rows_layout = QtWidgets.QVBoxLayout()
        self._persona_provider_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._persona_provider_rows_layout.setSpacing(8)
        persona_provider_layout.addLayout(self._persona_provider_rows_layout)
        providers_layout.addWidget(persona_provider_box)
        providers_layout.addStretch(1)

        advanced_box = QtWidgets.QGroupBox("Buddy System Override")
        advanced_box.setToolTip("Advanced prompt override used only while Buddy Chat is enabled.")
        advanced_layout_inner = QtWidgets.QVBoxLayout(advanced_box)
        system_override_enabled = QtWidgets.QCheckBox("Override main persona instructions while Buddy Chat is enabled")
        system_override_enabled.setToolTip(
            "Adds a high-priority Buddy Chat system instruction after the main persona prompt, so selected buddies are allowed to speak naturally."
        )
        system_override_enabled.setChecked(bool(self.settings.system_override_enabled))
        system_override_reset = QtWidgets.QPushButton("Use Recommended")
        system_override_reset.setToolTip("Restore the recommended Buddy Chat override prompt.")
        system_override_row = QtWidgets.QHBoxLayout()
        system_override_row.setContentsMargins(0, 0, 0, 0)
        system_override_row.addWidget(system_override_enabled)
        system_override_row.addStretch(1)
        system_override_row.addWidget(system_override_reset)
        system_override_widget = QtWidgets.QWidget()
        system_override_widget.setLayout(system_override_row)
        system_override_prompt = QtWidgets.QPlainTextEdit()
        system_override_prompt.setToolTip(
            "System instruction injected only when Buddy Chat is enabled. Use this to stop the main persona prompt from suppressing buddy dialogue."
        )
        system_override_prompt.setPlainText(self.settings.system_override_prompt or DEFAULT_SYSTEM_OVERRIDE_PROMPT)
        system_override_prompt.setMinimumHeight(118)
        system_override_prompt.setPlaceholderText(DEFAULT_SYSTEM_OVERRIDE_PROMPT)
        advanced_layout_inner.addWidget(system_override_widget)
        advanced_layout_inner.addWidget(system_override_prompt)
        advanced_layout.addWidget(advanced_box)
        advanced_layout.addStretch(1)

        self._controls.update(
            {
                "enabled": enabled,
                "reply_mode": reply_mode,
                "llm_mode": llm_mode,
                "max_speakers": max_speakers,
                "forced_buddy_every": forced_buddy_every,
                "instructor_structured_outputs": instructor_structured_outputs,
                "active_persona_window_enabled": active_persona_window_enabled,
                "active_persona_window_on_top": active_persona_window_on_top,
                "active_persona_window_open": active_persona_window_open,
                "system_override_enabled": system_override_enabled,
                "system_override_prompt": system_override_prompt,
                "buddy_provider": self._controls["buddy_provider"],
                "buddy_model": self._controls["buddy_model"],
                "buddy_base_url": self._controls["buddy_base_url"],
                "buddy_api_key": self._controls["buddy_api_key"],
                "status_label": status_label,
            }
        )

        enabled.toggled.connect(lambda _value: self._commit_ui_settings())
        reply_mode.currentIndexChanged.connect(lambda _index: self._commit_ui_settings())
        llm_mode.currentIndexChanged.connect(lambda _index: self._commit_ui_settings())
        max_speakers.valueChanged.connect(lambda _value: self._commit_ui_settings())
        forced_buddy_every.valueChanged.connect(lambda _value: self._commit_ui_settings())
        instructor_structured_outputs.toggled.connect(lambda _value: self._commit_ui_settings())
        active_persona_window_enabled.toggled.connect(lambda _value: self._on_active_persona_window_option_changed())
        active_persona_window_on_top.toggled.connect(lambda _value: self._on_active_persona_window_option_changed())
        active_persona_window_open.clicked.connect(self._open_active_persona_window)
        system_override_enabled.toggled.connect(lambda _value: self._commit_ui_settings())
        system_override_reset.clicked.connect(self._reset_system_override_prompt)
        self._controls["buddy_provider"].currentIndexChanged.connect(lambda _index: self._on_model_source_changed("buddy_model"))
        self._controls["buddy_model"].currentTextChanged.connect(lambda _text: self._commit_ui_settings())
        for editor in (self._controls["buddy_base_url"], self._controls["buddy_api_key"]):
            editor.editingFinished.connect(self._commit_ui_settings)
            editor.editingFinished.connect(lambda target="buddy_model": self._refresh_model_catalog_for_key(target))
        save_button.clicked.connect(self._commit_ui_settings)
        add_button.clicked.connect(self._add_persona_from_ui)
        import_button.clicked.connect(self._load_mprc_personas_to_ui)
        self._controls["test_buddy_provider"].clicked.connect(self._test_buddy_provider)
        QtCore.QTimer.singleShot(0, self._refresh_visible_lmstudio_model_catalogs)

        self._rebuild_persona_rows()

        tab_specs = [
            ("overview", overview_page, "Overview", "Most-used Buddy Chat controls.", "#38bdf8"),
            ("buddies", buddies_page, "Buddies", "Buddy identity, role, speaking style, and add/remove actions.", "#22c55e"),
            ("voices", voices_page, "Voices", "Per-buddy TTS voice sample routing.", "#f59e0b"),
            ("avatars", avatars_page, "Avatars", "Visual Reply avatar prompt and generated image settings.", "#fb7185"),
            ("providers", providers_page, "Providers", "Shared and per-buddy LLM provider settings.", "#a78bfa"),
            ("advanced", advanced_page, "Advanced", "System override prompt and less common controls.", "#94a3b8"),
        ]
        buttons: list[_BuddyTabButton] = []
        for key, page, title, tooltip, color in tab_specs:
            index = stack.addWidget(page)
            button = _BuddyTabButton(index, title, self._buddy_tab_icon(key, color), color, tooltip)
            button.setProperty("buddy_tab_key", key)
            button.clicked.connect(self._select_buddy_tab)
            buttons.append(button)
            nav_layout.addWidget(button)
        nav_layout.addStretch(1)
        nav_scroll.setWidget(nav)
        nav_row_layout.addWidget(nav_prev, 0)
        nav_row_layout.addWidget(nav_scroll, 1)
        nav_row_layout.addWidget(nav_next, 0)
        tabs_layout.addWidget(nav_row)
        tabs_layout.addWidget(stack, 1)
        layout.addWidget(tabs, 1)
        self._controls["tabs"] = tabs
        self._controls["tab_stack"] = stack
        self._controls["tab_buttons"] = buttons
        self._controls["tab_nav_scroll"] = nav_scroll
        self._controls["tab_nav_prev"] = nav_prev
        self._controls["tab_nav_next"] = nav_next
        nav_prev.clicked.connect(lambda *_args: self._scroll_buddy_tab_nav(-1))
        nav_next.clicked.connect(lambda *_args: self._scroll_buddy_tab_nav(1))
        try:
            scrollbar = nav_scroll.horizontalScrollBar()
            scrollbar.valueChanged.connect(lambda *_args: self._update_buddy_tab_nav_buttons())
            scrollbar.rangeChanged.connect(lambda *_args: self._update_buddy_tab_nav_buttons())
            QtCore.QTimer.singleShot(0, self._update_buddy_tab_nav_buttons)
        except Exception:
            pass
        self._select_buddy_tab(0)
        self._apply_buddy_stylesheet(root)
        return root

    def _new_buddy_tab_page(self, title: str) -> tuple[QtWidgets.QScrollArea, QtWidgets.QVBoxLayout]:
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName(f"buddy_{self._safe_object_key(title)}_tab_scroll")
        page = QtWidgets.QWidget()
        page.setObjectName(f"buddy_{self._safe_object_key(title)}_tab")
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        scroll.setWidget(page)
        return scroll, layout

    def _build_shared_provider_box(self) -> QtWidgets.QGroupBox:
        provider_box = QtWidgets.QGroupBox("Shared LLM Provider")
        provider_box.setToolTip("Optional shared provider used when buddies should call a different LLM than the main runtime.")
        provider_layout = QtWidgets.QFormLayout(provider_box)
        buddy_provider = self._provider_combo(self.settings.buddy_provider.provider_id)
        buddy_provider.setToolTip("Provider used when LLM provider mode is set to Use Buddy Provider.")
        buddy_model = self._model_combo(self.settings.buddy_provider.model)
        buddy_model.setToolTip("Optional model override for the shared buddy provider. Leave blank to use the provider default.")
        buddy_base_url = QtWidgets.QLineEdit(self.settings.buddy_provider.base_url)
        buddy_base_url.setToolTip("Optional OpenAI-compatible base URL, including LAN LM Studio servers.")
        buddy_base_url.setPlaceholderText("Example: http://192.168.2.46:1234/v1")
        buddy_api_key = QtWidgets.QLineEdit(self.settings.buddy_provider.api_key)
        buddy_api_key.setToolTip("Optional key for providers that require one. Leave blank for local or LAN servers without auth.")
        buddy_api_key.setEchoMode(QtWidgets.QLineEdit.Password)
        test_button = QtWidgets.QPushButton("Test Buddy Provider")
        test_button.setToolTip("Send a tiny test request through the shared buddy provider.")
        provider_layout.addRow("Provider", buddy_provider)
        provider_layout.addRow("Model", buddy_model)
        provider_layout.addRow("Base URL", buddy_base_url)
        provider_layout.addRow("API key", buddy_api_key)
        provider_layout.addRow("", test_button)
        self._controls.update(
            {
                "buddy_provider": buddy_provider,
                "buddy_model": buddy_model,
                "buddy_base_url": buddy_base_url,
                "buddy_api_key": buddy_api_key,
                "test_buddy_provider": test_button,
            }
        )
        return provider_box

    def _select_buddy_tab(self, index: int) -> None:
        stack = self._controls.get("tab_stack")
        buttons = self._controls.get("tab_buttons") or []
        if stack is not None:
            stack.setCurrentIndex(int(index))
            try:
                stack.updateGeometry()
            except Exception:
                pass
        for button in buttons:
            if hasattr(button, "set_selected"):
                button.set_selected(int(getattr(button, "_index", -1)) == int(index))
        self._ensure_buddy_tab_button_visible(index)
        self._update_buddy_tab_nav_buttons()

    def _scroll_buddy_tab_nav(self, direction: int) -> None:
        nav_scroll = self._controls.get("tab_nav_scroll")
        if nav_scroll is None:
            return
        try:
            scrollbar = nav_scroll.horizontalScrollBar()
            step = max(90, int(nav_scroll.viewport().width() * 0.65))
            scrollbar.setValue(scrollbar.value() + (step if int(direction or 0) > 0 else -step))
            self._update_buddy_tab_nav_buttons()
        except Exception:
            pass

    def _ensure_buddy_tab_button_visible(self, index: int) -> None:
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

    def _update_buddy_tab_nav_buttons(self) -> None:
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

    def _buddy_tab_icon(self, kind: str, color: str) -> QtGui.QIcon:
        pixmap = QtGui.QPixmap(50, 50)
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        accent = QtGui.QColor(str(color or "#38bdf8"))
        painter.setPen(QtGui.QPen(accent, 3))
        painter.setBrush(QtGui.QColor(17, 27, 40))
        painter.drawRoundedRect(4, 4, 42, 42, 10, 10)
        painter.setBrush(accent)
        painter.setPen(QtGui.QPen(accent, 3))
        key = str(kind or "").lower()
        if key == "overview":
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawEllipse(13, 13, 24, 24)
            painter.drawLine(25, 25, 25, 15)
            painter.drawLine(25, 25, 34, 29)
        elif key == "buddies":
            painter.drawEllipse(14, 13, 9, 9)
            painter.drawEllipse(28, 13, 9, 9)
            painter.drawRoundedRect(11, 27, 14, 11, 4, 4)
            painter.drawRoundedRect(27, 27, 14, 11, 4, 4)
        elif key == "voices":
            painter.drawRect(14, 20, 7, 12)
            painter.drawArc(18, 15, 18, 22, -45 * 16, 90 * 16)
            painter.drawArc(24, 11, 18, 30, -45 * 16, 90 * 16)
        elif key == "avatars":
            painter.drawEllipse(17, 12, 16, 16)
            painter.drawRoundedRect(13, 30, 24, 9, 4, 4)
        elif key == "providers":
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRoundedRect(11, 14, 28, 22, 5, 5)
            painter.drawLine(17, 22, 33, 22)
            painter.drawLine(17, 29, 29, 29)
        else:
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawEllipse(14, 14, 22, 22)
            painter.drawEllipse(22, 22, 6, 6)
        painter.end()
        return QtGui.QIcon(pixmap)

    @staticmethod
    def _safe_object_key(value: str) -> str:
        return re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_") or "page"

    @staticmethod
    def _apply_buddy_stylesheet(root: QtWidgets.QWidget) -> None:
        root.setStyleSheet(
            """
            QWidget#buddy_chat_root { background: #101720; color: #f4f7fb; }
            QGroupBox { border: 1px solid #36506d; border-radius: 10px; margin-top: 10px; padding: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #dbeafe; font-weight: 700; }
            QLabel { color: #f4f7fb; }
            QLabel[muted="true"] { color: #9fb3c8; }
            QCheckBox { color: #f4f7fb; spacing: 8px; min-height: 22px; }
            QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {
                background: #182536; color: #f4f7fb; border: 1px solid #3d5a7c; border-radius: 8px; padding: 4px;
            }
            QPushButton { background: #1b2b40; color: #f4f7fb; border: 1px solid #416184; border-radius: 8px; padding: 6px 10px; font-weight: 600; }
            QPushButton:hover { background: #243956; }
            QToolButton#buddy_inner_tab_prev_button, QToolButton#buddy_inner_tab_next_button {
                background: #1b2b40; color: #f4f7fb; border: 1px solid #416184; border-radius: 8px; font-weight: 800;
            }
            QToolButton#buddy_inner_tab_prev_button:disabled, QToolButton#buddy_inner_tab_next_button:disabled {
                color: #6f8298; border-color: #2b4058;
            }
            QWidget#buddy_inner_tabs { background: #101720; border: none; border-radius: 12px; }
            QScrollArea#buddy_inner_tab_scroll {
                background: transparent;
                border: none;
                border-radius: 10px;
            }
            QScrollArea#buddy_inner_tab_scroll > QWidget,
            QScrollArea#buddy_inner_tab_scroll > QWidget > QWidget {
                background: transparent;
                border: none;
            }
            QWidget#buddy_inner_tab_nav { background: transparent; }
            QStackedWidget#buddy_inner_tab_stack {
                background: #122033;
                border: 1px solid #2d4561;
                border-top-color: #36506d;
                border-radius: 10px;
                padding: 3px;
            }
            """
        )

    def _build_persona_row(self, index: int, persona: BuddyPersona) -> dict[str, QtWidgets.QGroupBox]:
        enabled = QtWidgets.QCheckBox("Active")
        enabled.setToolTip("Enable or disable this buddy without deleting its settings.")
        enabled.setChecked(persona.enabled)
        name = QtWidgets.QLineEdit(persona.display_name)
        name.setToolTip("Display name used in buddy speaker labels and TTS routing.")
        role = QtWidgets.QLineEdit(persona.role)
        role.setToolTip("Short personality or purpose for this buddy.")
        style = QtWidgets.QLineEdit(persona.speaking_style)
        style.setToolTip("Speaking style used when this buddy joins a reply.")
        provider = self._provider_combo(persona.provider.provider_id)
        provider.setToolTip("Provider override for this buddy. Inherit follows the selected shared buddy mode.")
        model = self._model_combo(persona.provider.model)
        model.setToolTip("Optional model override for this buddy.")
        base_url = QtWidgets.QLineEdit(persona.provider.base_url)
        base_url.setToolTip("Optional provider URL for this buddy, useful for a LAN LM Studio server.")
        base_url.setPlaceholderText("http://192.168.2.46:1234/v1")
        api_key = QtWidgets.QLineEdit(persona.provider.api_key)
        api_key.setToolTip("Optional API key for this buddy's provider.")
        api_key.setEchoMode(QtWidgets.QLineEdit.Password)
        voice_path = QtWidgets.QLineEdit(persona.voice.sample_path)
        voice_path.setToolTip("Path to the voice sample used for this buddy.")
        voice_browse = QtWidgets.QPushButton("Voices")
        voice_browse.setToolTip("Browse the project voices folder and choose a voice sample for this buddy.")
        remove_button = QtWidgets.QPushButton("Remove Buddy")
        if len(list(self.settings.personas or [])) <= 1:
            remove_button.setEnabled(False)
            remove_button.setToolTip("Keep at least one buddy row. Disable Buddy Chat to turn all buddies off.")
        else:
            remove_button.setToolTip("Remove this buddy persona from Buddy Chat settings.")
        voice_enabled = QtWidgets.QCheckBox("Use voice sample")
        voice_enabled.setToolTip("Route this buddy to its voice sample when multi-voice TTS is available.")
        voice_enabled.setChecked(persona.voice.enabled)

        avatar_preset = QtWidgets.QComboBox()
        avatar_preset.setToolTip("Choose a ready-made avatar prompt style for this buddy.")
        for preset_name in AVATAR_PROMPT_PRESETS:
            avatar_preset.addItem(preset_name, preset_name)
        self._set_combo_data(avatar_preset, persona.avatar.preset or DEFAULT_AVATAR_PROMPT_PRESET)
        avatar_use_preset = QtWidgets.QPushButton("Use Prompt Preset")
        avatar_use_preset.setToolTip("Replace the avatar prompt with the selected ready-made prompt, using this buddy's name and role.")
        avatar_prompt = QtWidgets.QPlainTextEdit()
        avatar_prompt.setToolTip("Editable prompt used when generating this buddy's avatar through Visual Reply.")
        avatar_prompt.setMinimumHeight(150)
        avatar_prompt.setPlaceholderText(default_avatar_prompt(persona.display_name, persona.role, persona.speaking_style))
        avatar_prompt.setPlainText(
            str(persona.avatar.prompt or "").strip()
            or default_avatar_prompt(persona.display_name, persona.role, persona.speaking_style, persona.avatar.preset)
        )
        avatar_generate = QtWidgets.QPushButton("Generate avatar for persona")
        avatar_generate.setToolTip("Send this avatar prompt to the existing Visual Reply image generator.")
        avatar_image_path = QtWidgets.QLineEdit(persona.avatar.image_path)
        avatar_image_path.setToolTip("Path to the generated avatar image for this buddy.")
        avatar_image_path.setReadOnly(True)
        avatar_image_path.setPlaceholderText("No avatar image generated yet.")
        avatar_preview = QtWidgets.QLabel()
        avatar_preview.setToolTip("Preview of the generated avatar image when a local image path is available.")
        avatar_preview.setFixedSize(220, 220)
        avatar_preview.setAlignment(QtCore.Qt.AlignCenter)
        avatar_preview.setText("Avatar")
        avatar_preview.setStyleSheet("border: 1px solid #2d4661; border-radius: 6px; color: #9fb3c8; background: #0f1722;")
        self._refresh_avatar_preview(avatar_preview, persona.avatar.image_path)

        title = persona.display_name or f"Buddy {index + 1}"
        identity_box = QtWidgets.QGroupBox(title)
        identity_box.setToolTip("Identity and speaking style for one buddy persona.")
        identity_layout = QtWidgets.QGridLayout(identity_box)
        identity_layout.setContentsMargins(12, 14, 12, 12)
        identity_layout.setHorizontalSpacing(10)
        identity_layout.setVerticalSpacing(8)
        identity_layout.addWidget(enabled, 0, 0)
        identity_layout.addWidget(QtWidgets.QLabel("Name"), 0, 1)
        identity_layout.addWidget(name, 0, 2)
        identity_layout.addWidget(QtWidgets.QLabel("Role"), 0, 3)
        identity_layout.addWidget(role, 0, 4)
        identity_layout.addWidget(QtWidgets.QLabel("Style"), 1, 1)
        identity_layout.addWidget(style, 1, 2, 1, 3)
        identity_layout.addWidget(remove_button, 0, 5, 2, 1)
        identity_layout.setColumnStretch(2, 2)
        identity_layout.setColumnStretch(4, 2)

        avatar_box = QtWidgets.QGroupBox(title)
        avatar_box.setToolTip("Create or edit the visual identity used for this buddy's avatar image.")
        avatar_layout = QtWidgets.QGridLayout(avatar_box)
        avatar_layout.setContentsMargins(12, 14, 12, 12)
        avatar_layout.setHorizontalSpacing(10)
        avatar_layout.setVerticalSpacing(8)
        avatar_layout.addWidget(avatar_preview, 0, 0, 3, 1)
        avatar_layout.addWidget(QtWidgets.QLabel("Prompt preset"), 0, 1)
        avatar_layout.addWidget(avatar_preset, 0, 2)
        avatar_layout.addWidget(avatar_use_preset, 0, 3)
        avatar_layout.addWidget(QtWidgets.QLabel("Avatar prompt"), 1, 1)
        avatar_layout.addWidget(avatar_prompt, 1, 2, 1, 2)
        avatar_layout.addWidget(QtWidgets.QLabel("Image"), 2, 1)
        avatar_layout.addWidget(avatar_image_path, 2, 2)
        avatar_layout.addWidget(avatar_generate, 2, 3)
        avatar_layout.setColumnStretch(2, 1)

        voice_box = QtWidgets.QGroupBox(title)
        voice_box.setToolTip("Choose the TTS voice sample used when this buddy speaks.")
        voice_layout = QtWidgets.QGridLayout(voice_box)
        voice_layout.setContentsMargins(12, 14, 12, 12)
        voice_layout.setHorizontalSpacing(10)
        voice_layout.setVerticalSpacing(8)
        voice_layout.addWidget(voice_enabled, 0, 0)
        voice_layout.addWidget(voice_path, 0, 1)
        voice_layout.addWidget(voice_browse, 0, 2)
        voice_layout.setColumnStretch(1, 1)

        provider_box = QtWidgets.QGroupBox(title)
        provider_box.setToolTip("Optional per-persona LLM provider and model settings.")
        provider_layout = QtWidgets.QGridLayout(provider_box)
        provider_layout.setContentsMargins(12, 14, 12, 12)
        provider_layout.setHorizontalSpacing(10)
        provider_layout.setVerticalSpacing(8)
        provider_layout.addWidget(QtWidgets.QLabel("Provider"), 0, 0)
        provider_layout.addWidget(provider, 0, 1)
        provider_layout.addWidget(QtWidgets.QLabel("Model"), 0, 2)
        provider_layout.addWidget(model, 0, 3)
        provider_layout.addWidget(QtWidgets.QLabel("Base URL"), 1, 0)
        provider_layout.addWidget(base_url, 1, 1, 1, 3)
        provider_layout.addWidget(QtWidgets.QLabel("API key"), 2, 0)
        provider_layout.addWidget(api_key, 2, 1, 1, 3)
        provider_layout.setColumnStretch(1, 1)
        provider_layout.setColumnStretch(3, 1)

        self._controls[f"persona_{index}"] = {
            "enabled": enabled,
            "name": name,
            "role": role,
            "style": style,
            "avatar_preset": avatar_preset,
            "avatar_prompt": avatar_prompt,
            "avatar_use_preset": avatar_use_preset,
            "avatar_generate": avatar_generate,
            "avatar_image_path": avatar_image_path,
            "avatar_preview": avatar_preview,
            "provider": provider,
            "model": model,
            "base_url": base_url,
            "api_key": api_key,
            "voice_enabled": voice_enabled,
            "voice_path": voice_path,
            "voice_browse": voice_browse,
            "remove_buddy": remove_button,
        }
        for widget in (enabled, voice_enabled):
            widget.toggled.connect(lambda _value: self._commit_ui_settings())
        avatar_preset.currentIndexChanged.connect(lambda _index: self._commit_ui_settings())
        avatar_prompt.textChanged.connect(lambda: self._commit_ui_settings())
        avatar_use_preset.clicked.connect(lambda _checked=False, row_index=index: self._apply_avatar_preset_to_persona(row_index))
        avatar_generate.clicked.connect(lambda _checked=False, row_index=index: self._generate_avatar_for_persona(row_index))
        provider.currentIndexChanged.connect(lambda _index, target=f"persona_{index}.model": self._on_model_source_changed(target))
        model.currentTextChanged.connect(lambda _text: self._commit_ui_settings())
        for editor in (name, role, style, base_url, api_key, voice_path):
            editor.editingFinished.connect(self._commit_ui_settings)
        base_url.editingFinished.connect(lambda target=f"persona_{index}.model": self._refresh_model_catalog_for_key(target))
        api_key.editingFinished.connect(lambda target=f"persona_{index}.model": self._refresh_model_catalog_for_key(target))
        voice_browse.clicked.connect(lambda _checked=False, row_index=index: self._browse_voice_sample_for_persona(row_index))
        remove_button.clicked.connect(lambda _checked=False, row_index=index: self._remove_persona_from_ui(row_index))
        return {
            "identity": identity_box,
            "voice": voice_box,
            "avatar": avatar_box,
            "provider": provider_box,
        }

    @staticmethod
    def _model_combo(current: str) -> QtWidgets.QComboBox:
        combo = QtWidgets.QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(24)
        value = str(current or "").strip()
        if value:
            combo.addItem(value)
            combo.setCurrentText(value)
        else:
            combo.setCurrentText("")
        return combo

    @staticmethod
    def _provider_combo(current: str) -> QtWidgets.QComboBox:
        combo = QtWidgets.QComboBox()
        labels = {
            "inherit": "Inherit",
            "main": "Main LLM Runtime",
            "lmstudio": "LM Studio",
            "ollama": "Ollama",
            "openai": "OpenAI",
            "xai": "xAI / Grok",
            "deepseek": "DeepSeek",
            "claude": "Claude",
        }
        for provider_id in PROVIDER_IDS:
            combo.addItem(labels.get(provider_id, provider_id), provider_id)
        BuddyChatController._set_combo_data(combo, current or "inherit")
        return combo

    @staticmethod
    def _combo_data(combo: QtWidgets.QComboBox, fallback: str = "") -> str:
        value = combo.currentData()
        return str(value if value is not None else combo.currentText() or fallback).strip()

    @staticmethod
    def _editor_text(widget: Any) -> str:
        if isinstance(widget, QtWidgets.QComboBox):
            return str(widget.currentText() or "").strip()
        if hasattr(widget, "text"):
            return str(widget.text() or "").strip()
        return ""

    @staticmethod
    def _set_combo_data(combo: QtWidgets.QComboBox, value: str) -> None:
        target = str(value or "").strip()
        for index in range(combo.count()):
            if str(combo.itemData(index) or "").strip() == target:
                combo.setCurrentIndex(index)
                return

    def _chat_context(self, _payload: dict[str, Any]):
        if not self.settings.enabled or self.settings.reply_mode != "context_only":
            return None
        context = buddy_context_prompt(self.settings)
        if not context:
            return None
        return {
            "context": context,
            "debug": {
                "sources": ["buddy_chat"],
                "reply_mode": self.settings.reply_mode,
                "llm_mode": self.settings.llm_mode,
            },
        }

    def _handle_user_text_command(self, payload: dict[str, Any]):
        if not self.settings.enabled:
            return None
        forced_buddy = self.settings.reply_mode == "context_only" and self._forced_buddy_due()
        if self.settings.reply_mode != "main_answer" and not forced_buddy:
            return None
        user_text = str(payload.get("text") or "").strip()
        if not user_text or self._looks_like_other_addon_command(user_text):
            return None
        selected = self._select_speakers(user_text)
        if not selected:
            return None
        history = self._current_conversation_history()
        external_contexts = self._external_contexts(history)
        contextual_text = str(payload.get("context") or "").strip()
        if contextual_text:
            external_contexts.insert(0, contextual_text)
        contextual_source = str(payload.get("source") or "").strip().lower()
        fallback_model = self._current_model_name()
        replies: list[tuple[BuddyPersona, str]] = []
        provider_debug: list[dict[str, str]] = []
        errors: list[str] = []
        instructor_enabled = structured_models.structured_feature_enabled(self.settings)
        instructor_attempted = False
        instructor_used = False
        instructor_fallback = False
        for persona in selected:
            messages = build_persona_messages(
                persona=persona,
                settings=self.settings,
                user_text=user_text,
                history=history,
                external_contexts=external_contexts,
                previous_replies=replies,
            )
            try:
                config = self.llm_runtime.resolve_call_config(persona=persona, settings=self.settings, fallback_model=fallback_model)
                provider_debug.append(
                    {
                        "persona_id": persona.id,
                        "provider_id": config.provider_id,
                        "model": config.model,
                        "base_url": config.base_url,
                        "uses_main_runtime": str(bool(config.uses_main_runtime)),
                    }
                )
                reply = ""
                if instructor_enabled:
                    instructor_attempted = True
                    reply = self._complete_structured_persona_reply(persona=persona, messages=messages, fallback_model=fallback_model)
                    if reply:
                        instructor_used = True
                    else:
                        instructor_fallback = True
                if not reply:
                    reply = self.llm_runtime.complete_for_persona(
                        persona=persona,
                        settings=self.settings,
                        messages=messages,
                        fallback_model=fallback_model,
                    )
            except Exception as exc:
                self._record_provider_error(persona, exc, messages)
                errors.append(f"{persona.display_name}: {exc}")
                continue
            normalized = self._ensure_persona_label(persona, reply)
            if normalized:
                replies.append((persona, normalized))
        if not replies:
            if errors:
                if forced_buddy and selected:
                    persona = selected[0]
                    replies.append(
                        (
                            persona,
                            f"[{persona.display_name}]\nI couldn't form a full reply because my language model provider is unavailable.",
                        )
                    )
                else:
                    return {
                        "handled": True,
                        "response_text": "Buddy Chat could not reach the selected persona provider: " + "; ".join(errors[:2]),
                        "debug": {"sources": ["buddy_chat"], "errors": errors},
                    }
            else:
                return None
        self.settings.turn_index += 1
        first_persona, first_reply = replies[0]
        self._set_active_persona(
            first_persona.id,
            reason="Buddy reply",
            text=self._strip_visible_persona_label(first_persona, first_reply),
        )
        self._save_settings(defer_write=True)
        return {
            "handled": True,
            "response_text": "\n\n".join(reply for _persona, reply in replies),
            "use_llm_response": False,
            "prefer_low_latency_tts": True,
            "debug": {
                "sources": ["buddy_chat"],
                "forced_buddy": bool(forced_buddy),
                "contextual_source": contextual_source,
                "selected_personas": [persona.id for persona, _reply in replies],
                "providers": provider_debug,
                "errors": errors,
                "instructor_structured_outputs": self._instructor_debug_status(
                    enabled=instructor_enabled,
                    attempted=instructor_attempted,
                    used=instructor_used,
                    fallback=instructor_fallback,
                ),
                "memory_store": "engine.finalize_assistant_reply",
                "memory_note": "NC finalization records handled replies through the existing assistant-reply and continuity-memory hooks.",
            },
        }

    def _record_provider_error(self, persona: BuddyPersona, exc: Exception, messages: list[dict[str, str]]) -> None:
        error = compact_text(exc, 2000) or exc.__class__.__name__
        self._last_provider_error = f"{persona.display_name}: {error}"
        self._last_provider_error_at = time.time()
        try:
            path = Path(self.context.app_root) / "runtime" / "addons" / "nc.buddy_chat" / "buddy_chat_debug.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "timestamp": self._last_provider_error_at,
                "persona": persona.display_name,
                "provider_mode": self.settings.llm_mode,
                "error": error,
                "message_roles": [str(item.get("role") or "") for item in messages],
            }
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")
        except OSError:
            pass

    def _handle_contextual_reply(self, payload: dict[str, Any]):
        if not self.settings.enabled:
            return None
        if self.settings.reply_mode == "context_only" and not self._forced_buddy_due():
            return None
        return self._handle_user_text_command(payload)

    def _complete_structured_persona_reply(self, *, persona: BuddyPersona, messages: list[dict[str, Any]], fallback_model: str) -> str:
        logger = getattr(self.context, "logger", None)
        payload = instructor_adapter.generate_buddy_structured_reply(
            llm_runtime=self.llm_runtime,
            persona=persona,
            settings=self.settings,
            messages=messages,
            fallback_model=fallback_model,
            logger=logger,
        )
        clean = structured_models.sanitize_structured_buddy_reply(
            payload,
            personas=self.settings.enabled_personas(),
            max_speakers=1,
            allowed_persona_ids={persona.id},
        )
        return structured_models.structured_buddy_reply_to_text(clean)

    @staticmethod
    def _instructor_debug_status(*, enabled: bool, attempted: bool, used: bool, fallback: bool) -> str:
        if not bool(enabled):
            return "disabled"
        if bool(used) and bool(fallback):
            return "partial"
        if bool(used):
            return "used"
        if bool(attempted) or bool(fallback):
            return "fallback"
        return "disabled"

    def _select_speakers(self, user_text: str) -> list[BuddyPersona]:
        personas = self.settings.enabled_personas()
        if not personas:
            return []
        lowered = str(user_text or "").lower()
        max_speakers = max(1, min(int(self.settings.max_speakers or 1), len(personas)))
        mentioned = [
            persona
            for persona in personas
            if self._name_mentioned(lowered, persona.display_name) or self._name_mentioned(lowered, persona.id)
        ]
        if mentioned:
            selected = mentioned[:max_speakers]
        else:
            start = int(self.settings.turn_index or 0) % len(personas)
            selected = [personas[start]]
        if (
            bool(self.settings.allow_buddy_to_buddy)
            and max_speakers > 1
            and len(selected) < max_speakers
            and (self._asks_group(lowered) or self._natural_second_speaker_due())
        ):
            for persona in personas:
                if persona.id not in {item.id for item in selected}:
                    selected.append(persona)
                    break
        return selected[:max_speakers]

    @staticmethod
    def _name_mentioned(text: str, name: str) -> bool:
        clean = re.escape(str(name or "").strip().lower())
        return bool(clean and re.search(rf"(?<![a-z0-9_]){clean}(?![a-z0-9_])", text))

    @staticmethod
    def _asks_group(text: str) -> bool:
        return any(phrase in text for phrase in ("both of you", "you two", "all of you", "everyone", "what do you both"))

    def _natural_second_speaker_due(self) -> bool:
        interval = int(self.settings.natural_second_speaker_every or 0)
        return bool(interval > 0 and (int(self.settings.turn_index or 0) + 1) % interval == 0)

    def _forced_buddy_due(self) -> bool:
        interval = int(self.settings.forced_buddy_every or 0)
        return bool(interval > 0 and (int(self.settings.completed_reply_count or 0) + 1) % interval == 0)

    def _record_completed_reply(self, payload: dict[str, Any]):
        if not self.settings.enabled or not str(payload.get("text") or "").strip():
            return None
        self.settings.completed_reply_count = int(self.settings.completed_reply_count or 0) + 1
        self._save_settings(defer_write=True)
        return {
            "recorded": True,
            "completed_reply_count": int(self.settings.completed_reply_count),
        }

    @staticmethod
    def _looks_like_other_addon_command(text: str) -> bool:
        lowered = str(text or "").strip().lower()
        if not lowered:
            return False
        return bool(
            re.search(r"^(play|pause|stop|next|previous|prev|resume)\b.*\b(music|spotify|track|song|playlist|album)\b", lowered)
            or re.search(r"^(play|pause|stop|next|previous|prev|resume)\b", lowered)
            or lowered.startswith("spotify ")
        )

    @staticmethod
    def _ensure_persona_label(persona: BuddyPersona, reply: str) -> str:
        text = str(reply or "").strip()
        if not text:
            return ""
        label = f"[{persona.display_name}]"
        first = text.splitlines()[0].strip() if text.splitlines() else ""
        if first.lower() == label.lower():
            return text
        if re.match(r"^\s*\[[^\]]+\]", first):
            return text
        return f"{label}\n{text}"

    @staticmethod
    def _strip_visible_persona_label(persona: BuddyPersona, reply: str) -> str:
        text = str(reply or "").strip()
        if not text:
            return ""
        name = re.escape(str(persona.display_name or "").strip())
        if name:
            text = re.sub(rf"^\s*\[{name}\]\s*", "", text, flags=re.IGNORECASE).strip()
        return text

    @staticmethod
    def _current_conversation_history() -> list[dict[str, Any]]:
        try:
            import engine

            return [dict(item) for item in list(getattr(engine, "conversation_history", []) or []) if isinstance(item, dict)]
        except Exception:
            return []

    @staticmethod
    def _current_model_name() -> str:
        try:
            import engine

            return str(engine.RUNTIME_CONFIG.get("model_name", "") or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _external_contexts(history: list[dict[str, Any]]) -> list[str]:
        try:
            import engine

            collector = getattr(engine, "_collect_addon_chat_contexts", None)
            if not callable(collector):
                return []
            contexts = []
            for item in list(collector(history) or []):
                if isinstance(item, dict) and str(item.get("context") or "").strip():
                    contexts.append(str(item.get("context") or "").strip())
            return contexts
        except Exception:
            return []

    def _load_settings(self) -> BuddySettings:
        try:
            payload = self.context.storage.read_json(SETTINGS_PATH)
            return BuddySettings.from_dict(payload if isinstance(payload, dict) else {})
        except Exception:
            return BuddySettings.default()

    def _write_settings_payload(self, payload: dict[str, Any]) -> None:
        try:
            self.context.storage.write_json(SETTINGS_PATH, dict(payload or {}))
        except Exception:
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[BuddyChat] Could not save settings.", exc_info=True)

    def _save_settings(self, *, defer_write: bool = False) -> None:
        with self._state_lock:
            if self._shutting_down:
                return
            self._last_session_export_state = self._session_export_payload_unlocked()
            payload = copy.deepcopy(self._last_session_export_state["buddy_chat"]["settings"])
        if defer_write:
            self._queue_settings_payload(payload)
            return
        self._write_settings_payload(payload)

    def _queue_settings_payload(self, payload: dict[str, Any]) -> None:
        with self._settings_write_lock:
            self._pending_settings_payload = copy.deepcopy(dict(payload or {}))
            worker = self._settings_write_thread
            if worker is not None and worker.is_alive():
                return
            worker = threading.Thread(
                target=self._settings_write_worker,
                name="BuddyChatSettingsWriter",
                daemon=True,
            )
            self._settings_write_thread = worker
            worker.start()

    def _settings_write_worker(self) -> None:
        while True:
            with self._settings_write_lock:
                payload = self._pending_settings_payload
                self._pending_settings_payload = None
                if payload is None:
                    self._settings_write_thread = None
                    return
            self._write_settings_payload(payload)

    def _commit_ui_settings(self) -> None:
        if not self._controls:
            return
        self.settings.enabled = bool(self._controls["enabled"].isChecked())
        self.settings.reply_mode = self._combo_data(self._controls["reply_mode"], "context_only")
        self.settings.llm_mode = self._combo_data(self._controls["llm_mode"], "main")
        self.settings.max_speakers = int(self._controls["max_speakers"].value())
        self.settings.forced_buddy_every = int(self._controls["forced_buddy_every"].value())
        self.settings.instructor_structured_outputs_enabled = bool(self._controls["instructor_structured_outputs"].isChecked())
        self.settings.active_persona_window_enabled = bool(self._controls["active_persona_window_enabled"].isChecked())
        self.settings.active_persona_window_on_top = bool(self._controls["active_persona_window_on_top"].isChecked())
        self.settings.system_override_enabled = bool(self._controls["system_override_enabled"].isChecked())
        prompt_editor = self._controls.get("system_override_prompt")
        if isinstance(prompt_editor, QtWidgets.QPlainTextEdit):
            self.settings.system_override_prompt = str(prompt_editor.toPlainText() or "").strip() or DEFAULT_SYSTEM_OVERRIDE_PROMPT
        self.settings.buddy_provider = ProviderOverride(
            provider_id=self._combo_data(self._controls["buddy_provider"], "inherit"),
            model=self._editor_text(self._controls["buddy_model"]),
            base_url=str(self._controls["buddy_base_url"].text() or "").strip(),
            api_key=str(self._controls["buddy_api_key"].text() or "").strip(),
        )
        for index, persona in enumerate(list(self.settings.personas or [])):
            row = self._controls.get(f"persona_{index}")
            if not isinstance(row, dict):
                continue
            persona.enabled = bool(row["enabled"].isChecked())
            persona.display_name = str(row["name"].text() or persona.display_name).strip() or persona.display_name
            persona.role = str(row["role"].text() or "").strip()
            persona.speaking_style = str(row["style"].text() or "").strip()
            avatar_prompt = row.get("avatar_prompt")
            avatar_image_path = row.get("avatar_image_path")
            persona.avatar.preset = self._combo_data(row["avatar_preset"], DEFAULT_AVATAR_PROMPT_PRESET)
            persona.avatar.prompt = (
                str(avatar_prompt.toPlainText() or "").strip()
                if isinstance(avatar_prompt, QtWidgets.QPlainTextEdit)
                else str(persona.avatar.prompt or "").strip()
            )
            persona.avatar.image_path = (
                str(avatar_image_path.text() or "").strip()
                if isinstance(avatar_image_path, QtWidgets.QLineEdit)
                else str(persona.avatar.image_path or "").strip()
            )
            persona.provider = ProviderOverride(
                provider_id=self._combo_data(row["provider"], "inherit"),
                model=self._editor_text(row["model"]),
                base_url=str(row["base_url"].text() or "").strip(),
                api_key=str(row["api_key"].text() or "").strip(),
            )
            persona.voice.enabled = bool(row["voice_enabled"].isChecked())
            persona.voice.sample_path = str(row["voice_path"].text() or "").strip()
        self._save_settings()

    def _reset_system_override_prompt(self) -> None:
        editor = self._controls.get("system_override_prompt")
        enabled = self._controls.get("system_override_enabled")
        if isinstance(editor, QtWidgets.QPlainTextEdit):
            editor.setPlainText(DEFAULT_SYSTEM_OVERRIDE_PROMPT)
        if isinstance(enabled, QtWidgets.QCheckBox):
            enabled.setChecked(True)
        self._commit_ui_settings()
        self._set_status("Buddy Chat override prompt reset to the recommended default.")

    def _apply_avatar_preset_to_persona(self, index: int) -> None:
        row = self._controls.get(f"persona_{int(index)}")
        if not isinstance(row, dict):
            return
        preset = self._combo_data(row["avatar_preset"], DEFAULT_AVATAR_PROMPT_PRESET)
        name = str(row["name"].text() or "Buddy").strip() if isinstance(row.get("name"), QtWidgets.QLineEdit) else "Buddy"
        role = str(row["role"].text() or "").strip() if isinstance(row.get("role"), QtWidgets.QLineEdit) else ""
        style = str(row["style"].text() or "").strip() if isinstance(row.get("style"), QtWidgets.QLineEdit) else ""
        prompt = default_avatar_prompt(name, role, style, preset)
        editor = row.get("avatar_prompt")
        if isinstance(editor, QtWidgets.QPlainTextEdit):
            editor.setPlainText(prompt)
        self._commit_ui_settings()
        self._set_status(f"Avatar prompt preset applied for {name}.")

    def _generate_avatar_for_persona(self, index: int) -> None:
        row_index = int(index)
        self._commit_ui_settings()
        row = self._controls.get(f"persona_{row_index}")
        if isinstance(row, dict) and isinstance(row.get("avatar_generate"), QtWidgets.QPushButton):
            row["avatar_generate"].setEnabled(False)
        self._set_status("Generating buddy avatar through Visual Reply...")

        def worker() -> None:
            try:
                result = self._request_persona_avatar_generation(row_index, auto_show=True)
            except Exception as exc:
                result = {"ok": False, "message": f"Buddy avatar generation failed: {exc}"}
            self._ui_bridge.avatar_finished.emit(row_index, result)

        threading.Thread(target=worker, name="nc-buddy-avatar-generation", daemon=True).start()

    def _visual_reply_generation_service(self):
        service = self.visual_reply_service
        if service is None and self.context is not None:
            try:
                service = self.context.get_service("qt.visual_reply")
                self.visual_reply_service = service
            except Exception:
                service = None
        return service

    def _request_persona_avatar_generation(self, index: int, *, auto_show: bool = True) -> dict[str, Any]:
        personas = list(self.settings.personas or [])
        row_index = int(index)
        if row_index < 0 or row_index >= len(personas):
            return {"ok": False, "message": "No buddy persona matched that avatar request."}
        persona = personas[row_index]
        prompt = str(persona.avatar.prompt or "").strip()
        if not prompt:
            prompt = default_avatar_prompt(persona.display_name, persona.role, persona.speaking_style, persona.avatar.preset)
            persona.avatar.prompt = prompt
        if not prompt:
            return {"ok": False, "message": "Add an avatar prompt before generating a buddy avatar."}
        service = self._visual_reply_generation_service()
        generator = getattr(service, "request_generation", None)
        if not callable(generator):
            return {"ok": False, "message": "Visual Reply generation service is unavailable."}
        try:
            result = generator(
                prompt=prompt,
                caption=f"Buddy avatar: {persona.display_name}",
                provider="inherit",
                model="",
                size="1024x1024",
                source="nc.buddy_chat.avatar",
                metadata={
                    "persona_id": persona.id,
                    "display_name": persona.display_name,
                    "purpose": "buddy_avatar",
                    "preset": persona.avatar.preset,
                },
                auto_show=bool(auto_show),
            )
        except Exception as exc:
            return {"ok": False, "message": f"Buddy avatar generation failed:\n\n{exc}", "prompt": prompt}
        image_path = str(result.get("image_path") or "").strip() if isinstance(result, dict) else ""
        if image_path and Path(image_path).exists():
            persona.avatar.image_path = image_path
            self._save_settings()
            return {"ok": True, "image_path": image_path, "message": f"Buddy avatar generated: {Path(image_path).name}", "prompt": prompt}
        if result:
            self._save_settings()
            return {
                "ok": True,
                "image_path": "",
                "message": "Visual Reply accepted the buddy avatar request, but no image path was returned yet.",
                "prompt": prompt,
            }
        return {"ok": False, "message": "Visual Reply did not accept the buddy avatar request.", "prompt": prompt}

    def _on_avatar_generation_finished(self, index: int, result: dict[str, Any]) -> None:
        row = self._controls.get(f"persona_{int(index)}")
        if isinstance(row, dict):
            button = row.get("avatar_generate")
            if isinstance(button, QtWidgets.QPushButton):
                button.setEnabled(True)
            image_path = str((result or {}).get("image_path") or "").strip()
            if image_path:
                image_edit = row.get("avatar_image_path")
                preview = row.get("avatar_preview")
                if isinstance(image_edit, QtWidgets.QLineEdit):
                    image_edit.setText(image_path)
                if isinstance(preview, QtWidgets.QLabel):
                    self._refresh_avatar_preview(preview, image_path)
        self._commit_ui_settings()
        self._set_status(str((result or {}).get("message") or "Buddy avatar request finished."))

    @staticmethod
    def _refresh_avatar_preview(label: QtWidgets.QLabel, image_path: str) -> None:
        path = Path(str(image_path or "").strip())
        if not path.exists() or not path.is_file():
            label.setPixmap(QtGui.QPixmap())
            label.setText("Avatar")
            return
        pixmap = QtGui.QPixmap(str(path))
        if pixmap.isNull():
            label.setPixmap(QtGui.QPixmap())
            label.setText("Avatar")
            return
        label.setText("")
        label.setPixmap(pixmap.scaled(label.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

    def _add_persona_from_ui(self) -> None:
        self._commit_ui_settings()
        index = len(self.settings.personas) + 1
        display_name = f"Buddy {index}"
        self.settings.personas.append(
            BuddyPersona(
                id=f"buddy_{index}",
                display_name=display_name,
                avatar=AvatarProfile(
                    prompt=default_avatar_prompt(display_name),
                    preset=DEFAULT_AVATAR_PROMPT_PRESET,
                ),
            )
        )
        self._save_settings()
        self._rebuild_persona_rows()
        self._set_status(f"Added Buddy {index}.")

    def _load_mprc_personas_to_ui(self) -> None:
        self._commit_ui_settings()
        path = Path(self.context.app_root) / "runtime" / "addons" / "nc.multi_persona_roleplay" / "personas.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._set_status(f"Could not load MPRC personas: {exc}")
            return
        imported = []
        for item in list(payload or []):
            if isinstance(item, dict):
                persona = BuddyPersona.from_dict({**item, "source": "multi_persona_roleplay"})
                imported.append(persona)
        if not imported:
            self._set_status("No MPRC personas found.")
            return
        existing_by_id = {persona.id: persona for persona in self.settings.personas}
        for persona in imported:
            existing_by_id[persona.id] = persona
        self.settings.personas = list(existing_by_id.values())
        self._save_settings()
        self._rebuild_persona_rows()
        self._set_status(f"Loaded {len(imported)} MPRC persona(s). Buddy rows refreshed.")

    def _rebuild_persona_rows(self) -> None:
        layouts = [
            self._persona_rows_layout,
            self._persona_voice_rows_layout,
            self._persona_avatar_rows_layout,
            self._persona_provider_rows_layout,
        ]
        if not any(layout is not None for layout in layouts):
            return
        for key in [name for name in self._controls if name.startswith("persona_")]:
            self._controls.pop(key, None)
        for layout in layouts:
            if layout is None:
                continue
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.setParent(None)
                    widget.deleteLater()
                nested = item.layout()
                if nested is not None:
                    self._clear_layout(nested)
        for index, persona in enumerate(self.settings.personas):
            cards = self._build_persona_row(index, persona)
            if self._persona_rows_layout is not None:
                self._persona_rows_layout.addWidget(cards["identity"])
            if self._persona_voice_rows_layout is not None:
                self._persona_voice_rows_layout.addWidget(cards["voice"])
            if self._persona_avatar_rows_layout is not None:
                self._persona_avatar_rows_layout.addWidget(cards["avatar"])
            if self._persona_provider_rows_layout is not None:
                self._persona_provider_rows_layout.addWidget(cards["provider"])
        self._refresh_visible_lmstudio_model_catalogs()

    def _clear_layout(self, layout: QtWidgets.QLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
            nested = item.layout()
            if nested is not None:
                self._clear_layout(nested)

    def _model_context_for_key(self, target_key: str) -> tuple[QtWidgets.QComboBox, QtWidgets.QComboBox, QtWidgets.QLineEdit, QtWidgets.QLineEdit] | None:
        key = str(target_key or "").strip()
        if key == "buddy_model":
            provider = self._controls.get("buddy_provider")
            model = self._controls.get("buddy_model")
            base_url = self._controls.get("buddy_base_url")
            api_key = self._controls.get("buddy_api_key")
        elif key.startswith("persona_") and key.endswith(".model"):
            row_key = key.split(".", 1)[0]
            row = self._controls.get(row_key)
            if not isinstance(row, dict):
                return None
            provider = row.get("provider")
            model = row.get("model")
            base_url = row.get("base_url")
            api_key = row.get("api_key")
        else:
            return None
        if not isinstance(provider, QtWidgets.QComboBox) or not isinstance(model, QtWidgets.QComboBox):
            return None
        if not isinstance(base_url, QtWidgets.QLineEdit) or not isinstance(api_key, QtWidgets.QLineEdit):
            return None
        return provider, model, base_url, api_key

    def _on_model_source_changed(self, target_key: str) -> None:
        self._commit_ui_settings()
        self._refresh_model_catalog_for_key(target_key)

    def _refresh_visible_lmstudio_model_catalogs(self) -> None:
        for target_key in ["buddy_model"] + [f"persona_{index}.model" for index, _persona in enumerate(self.settings.personas)]:
            self._refresh_model_catalog_for_key(target_key)

    def _refresh_model_catalog_for_key(self, target_key: str) -> None:
        context = self._model_context_for_key(target_key)
        if context is None:
            return
        provider_combo, _model_combo, base_url_edit, api_key_edit = context
        provider_id = self._combo_data(provider_combo, "inherit")
        if provider_id != "lmstudio":
            return
        base_url = str(base_url_edit.text() or "").strip()
        api_key = str(api_key_edit.text() or "").strip()
        lock_key = f"{target_key}|{base_url}|{api_key}"
        with self._model_catalog_lock:
            if lock_key in self._model_catalog_inflight:
                return
            self._model_catalog_inflight.add(lock_key)
        self._set_status("Fetching LM Studio models for Buddy Chat...")

        def worker() -> None:
            error = ""
            models: list[str] = []
            try:
                models = list_lmstudio_models_for_base_url(base_url, api_key=api_key)
            except Exception as exc:
                error = str(exc)
            finally:
                with self._model_catalog_lock:
                    self._model_catalog_inflight.discard(lock_key)
            self._ui_bridge.model_catalog_finished.emit(str(target_key or ""), models, error)

        threading.Thread(target=worker, name="nc-buddy-chat-model-catalog", daemon=True).start()

    def _on_model_catalog_finished(self, target_key: str, models: list[Any], error: str) -> None:
        context = self._model_context_for_key(target_key)
        if context is None:
            return
        _provider_combo, model_combo, _base_url_edit, _api_key_edit = context
        current = self._editor_text(model_combo)
        clean_models = []
        seen = set()
        for item in list(models or []):
            value = str(item.get("id") if isinstance(item, dict) else item or "").strip()
            if value and value not in seen:
                seen.add(value)
                clean_models.append(value)
        model_combo.blockSignals(True)
        try:
            model_combo.clear()
            if current:
                model_combo.addItem(current)
            for model_id in clean_models:
                if model_id != current:
                    model_combo.addItem(model_id)
            model_combo.setCurrentText(current)
        finally:
            model_combo.blockSignals(False)
        if error:
            self._set_status(f"Could not load LM Studio models: {error}")
        elif clean_models:
            self._set_status(f"Loaded {len(clean_models)} LM Studio model(s) for Buddy Chat.")
        else:
            self._set_status("No LM Studio models found for Buddy Chat.")

    def _voice_sample_folder(self) -> Path:
        root = Path(getattr(self.context, "app_root", Path.cwd()) or Path.cwd())
        return root / "voices"

    def _open_voice_sample_file(self, start_dir: Path) -> str:
        path, _selected_filter = QtWidgets.QFileDialog.getOpenFileName(
            None,
            "Choose Buddy voice sample",
            str(start_dir),
            "Audio files (*.wav *.mp3 *.flac *.ogg *.m4a);;All files (*.*)",
        )
        return str(path or "").strip()

    def _browse_voice_sample_for_persona(self, index: int) -> None:
        row = self._controls.get(f"persona_{int(index)}")
        if not isinstance(row, dict):
            return
        start_dir = self._voice_sample_folder()
        try:
            start_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        selected = self._open_voice_sample_file(start_dir)
        if not selected:
            return
        voice_path = row.get("voice_path")
        voice_enabled = row.get("voice_enabled")
        if isinstance(voice_path, QtWidgets.QLineEdit):
            voice_path.setText(str(selected))
        if isinstance(voice_enabled, QtWidgets.QCheckBox):
            voice_enabled.setChecked(True)
        self._commit_ui_settings()
        self._set_status(f"Voice sample selected: {Path(selected).name}")

    def _remove_persona_from_ui(self, index: int) -> None:
        personas = list(self.settings.personas or [])
        if len(personas) <= 1:
            self._set_status("Keep at least one buddy row. Disable Buddy Chat to turn all buddies off.")
            return
        row_index = int(index)
        if row_index < 0 or row_index >= len(personas):
            return
        self._commit_ui_settings()
        removed = self.settings.personas.pop(row_index)
        self._save_settings()
        self._rebuild_persona_rows()
        self._set_status(f"Removed buddy: {removed.display_name or removed.id}")

    def _test_buddy_provider(self) -> None:
        self._commit_ui_settings()
        provider = BuddyPersona(
            id="test_buddy",
            display_name="Test Buddy",
            provider=self.settings.buddy_provider,
        )

        def worker() -> None:
            try:
                text = self.llm_runtime.complete_for_persona(
                    persona=provider,
                    settings=BuddySettings(
                        enabled=True,
                        llm_mode="buddy",
                        buddy_provider=self.settings.buddy_provider,
                        personas=[provider],
                    ),
                    messages=[
                        {"role": "system", "content": "Reply with one short sentence."},
                        {"role": "user", "content": "Say Buddy Chat provider test ok."},
                    ],
                    fallback_model=self._current_model_name(),
                )
                message = "Provider test ok: " + (text[:160] if text else "empty response")
            except Exception as exc:
                message = f"Provider test failed: {exc}"
            self._ui_bridge.test_finished.emit(message)

        threading.Thread(target=worker, name="nc-buddy-provider-test", daemon=True).start()
        self._set_status("Testing provider...")

    def _set_status(self, message: str) -> None:
        label = self._controls.get("status_label")
        if label is not None:
            label.setText(str(message or ""))

    def _rebuild_hint(self) -> None:
        self._set_status("Settings saved. Reopen the Buddy Chat tab to refresh the persona rows.")

    def _session_export_payload_unlocked(self) -> dict[str, Any]:
        return {"buddy_chat": {"settings": self.settings.to_dict()}}

    def export_session_state(self) -> dict[str, Any]:
        acquired = self._state_lock.acquire(blocking=False)
        if not acquired:
            return copy.deepcopy(self._last_session_export_state)
        try:
            if self._shutting_down:
                return copy.deepcopy(self._last_session_export_state)
            self._last_session_export_state = self._session_export_payload_unlocked()
            return copy.deepcopy(self._last_session_export_state)
        finally:
            self._state_lock.release()

    def import_session_state(self, session: dict[str, Any] | None) -> None:
        root = dict(session or {})
        grouped = root.get("buddy_chat")
        payload = dict(grouped or {}).get("settings") if isinstance(grouped, dict) else None
        if not isinstance(payload, dict):
            payload = root.get("settings")
        if isinstance(payload, dict):
            incoming_epoch = int(payload.get("settings_epoch", 0) or 0)
            incoming_settings = BuddySettings.from_dict(payload)
            with self._state_lock:
                if self._shutting_down:
                    return
                if incoming_epoch < int(self.settings.settings_epoch or 0):
                    return
                self.settings = incoming_settings
                self._last_session_export_state = self._session_export_payload_unlocked()
                settings_payload = copy.deepcopy(self._last_session_export_state["buddy_chat"]["settings"])
            self._write_settings_payload(settings_payload)

    def shutdown(self) -> None:
        with self._state_lock:
            if self._shutting_down:
                return
            self._shutting_down = True
        window = self._active_persona_window
        if window is not None:
            try:
                window.close()
                window.deleteLater()
            except Exception:
                pass
            self._active_persona_window = None
        try:
            self._ui_bridge.controller = None
            self._ui_bridge.deleteLater()
        except Exception:
            pass
        self._controls.clear()
