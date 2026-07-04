from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtWidgets

_REPLAY_TOOLTIP_MAX_CHARS = 4000
_REPLAY_SIGNATURE_EDGE_CHARS = 160


def _bounded_text(value, limit):
    text = str(value or "")
    if len(text) <= int(limit):
        return text
    return text[: int(limit)] + "\n..."


def _replay_content_signature(content):
    text = str(content or "")
    edge = int(_REPLAY_SIGNATURE_EDGE_CHARS)
    if len(text) <= edge * 2:
        return text
    return (len(text), text[:edge], text[-edge:])


class ChatSessionPlayerController(QtCore.QObject):
    def __init__(self, context=None):
        super().__init__()
        self.context = context
        self.dialogs = context.get_service("qt.dialogs") if context is not None else None
        self.replay_service = context.get_service("qt.chat_replay") if context is not None else None
        self.runtime_config = context.get_service("qt.runtime_config") if context is not None else None
        self.shell = context.get_service("qt.shell") if context is not None else None
        self.chat_player_tab_widget = None
        self._refresh_timer = None
        self._last_replay_signature = None
        self._selected_replay_index_value = None
        self._voice_combo_refreshing = False
        self.chat_player_assistant_voice_combo = None
        self.chat_player_user_voice_combo = None

    def bind_designer_tab(self, scroll):
        self._bind_ui_objects(scroll)
        return self._finalize_tab_widget(scroll)

    def _bind_ui_objects(self, root):
        required = {
            "chat_player_summary_label": QtWidgets.QLabel,
            "btn_chat_player_load": QtWidgets.QPushButton,
            "btn_chat_player_quick_load": QtWidgets.QPushButton,
            "btn_chat_player_refresh": QtWidgets.QPushButton,
            "chat_player_message_list": QtWidgets.QListWidget,
            "btn_chat_player_prev": QtWidgets.QPushButton,
            "btn_chat_player_next": QtWidgets.QPushButton,
            "btn_chat_player_replay_selected": QtWidgets.QPushButton,
            "btn_chat_player_replay_latest": QtWidgets.QPushButton,
            "btn_chat_player_replay_chat": QtWidgets.QPushButton,
            "chat_player_status_label": QtWidgets.QLabel,
        }
        missing = []
        for name, widget_type in required.items():
            child = root.findChild(widget_type, name)
            if child is None:
                missing.append(name)
            setattr(self, name, child)
        if missing:
            raise RuntimeError(f"Chat Player UI is missing required object(s): {', '.join(missing)}")
        self.btn_chat_player_load.clicked.connect(self._load_chat_context)
        self.btn_chat_player_quick_load.clicked.connect(self._quick_load_chat_context)
        self.btn_chat_player_refresh.clicked.connect(self.refresh_state)
        self.chat_player_message_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.chat_player_message_list.itemSelectionChanged.connect(self._on_message_selection_changed)
        self.chat_player_message_list.itemDoubleClicked.connect(lambda _item: self._replay_selected())
        self.btn_chat_player_prev.clicked.connect(lambda: self._select_relative(-1))
        self.btn_chat_player_next.clicked.connect(lambda: self._select_relative(1))
        self.btn_chat_player_replay_selected.clicked.connect(self._replay_selected)
        self.btn_chat_player_replay_latest.clicked.connect(self._replay_latest)
        self.btn_chat_player_replay_chat.clicked.connect(self._replay_chat)
        self._install_role_voice_panel(root)
        self._refresh_role_voice_combos()

    def _voice_folder(self):
        return Path.cwd() / "voices"

    def _voice_files(self):
        folder = self._voice_folder()
        try:
            return sorted((item.name for item in folder.glob("*.wav") if item.is_file()), key=str.lower)
        except Exception:
            return []

    def _role_voice_settings(self):
        if self.runtime_config is None:
            return {}
        try:
            payload = self.runtime_config.get("chat_replay_role_voices", {}) or {}
            return dict(payload) if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _voice_label_for_path(self, path):
        raw = str(path or "").strip()
        if not raw:
            return ""
        return Path(raw).name

    def _combo_voice_path(self, combo):
        if combo is None:
            return ""
        try:
            data = combo.currentData()
            return str(data or "").strip()
        except Exception:
            return ""

    def _current_role_voice_settings(self):
        return {
            "assistant": self._combo_voice_path(getattr(self, "chat_player_assistant_voice_combo", None)),
            "user": self._combo_voice_path(getattr(self, "chat_player_user_voice_combo", None)),
        }

    def _set_combo_to_voice_path(self, combo, value):
        if combo is None:
            return
        label = self._voice_label_for_path(value)
        target_data = f"voices/{label}" if label else ""
        for index in range(combo.count()):
            if str(combo.itemData(index) or "") == target_data:
                combo.setCurrentIndex(index)
                return
        combo.setCurrentIndex(0 if combo.count() else -1)

    def _refresh_role_voice_combos(self):
        assistant_combo = getattr(self, "chat_player_assistant_voice_combo", None)
        user_combo = getattr(self, "chat_player_user_voice_combo", None)
        if assistant_combo is None or user_combo is None:
            return
        settings = self._role_voice_settings()
        voices = self._voice_files()
        self._voice_combo_refreshing = True
        try:
            for combo in (assistant_combo, user_combo):
                combo.blockSignals(True)
                combo.clear()
                combo.addItem("Use current TTS voice", "")
                for voice_name in voices:
                    combo.addItem(voice_name, f"voices/{voice_name}")
            self._set_combo_to_voice_path(assistant_combo, settings.get("assistant", ""))
            self._set_combo_to_voice_path(user_combo, settings.get("user", ""))
        finally:
            for combo in (assistant_combo, user_combo):
                try:
                    combo.blockSignals(False)
                except Exception:
                    pass
            self._voice_combo_refreshing = False

    def _on_role_voice_changed(self):
        if self._voice_combo_refreshing or self.runtime_config is None:
            return
        settings = self._current_role_voice_settings()
        try:
            self.runtime_config.update("chat_replay_role_voices", settings)
        except Exception:
            pass
        if self.shell is not None and hasattr(self.shell, "notify_settings_changed"):
            try:
                self.shell.notify_settings_changed()
            except Exception:
                pass

    def _install_role_voice_panel(self, root):
        contents = root.findChild(QtWidgets.QWidget, "chat_player_scroll_contents")
        layout = contents.layout() if contents is not None else None
        if layout is None or getattr(self, "chat_player_role_voice_panel", None) is not None:
            return
        panel = QtWidgets.QFrame(contents)
        panel.setObjectName("Panel")
        panel.setProperty("nc_id", "chat_player_role_voice_panel")
        self.chat_player_role_voice_panel = panel
        panel_layout = QtWidgets.QVBoxLayout(panel)
        panel_layout.setContentsMargins(14, 12, 14, 12)
        panel_layout.setSpacing(10)

        title = QtWidgets.QLabel("Replay Voices", panel)
        title.setStyleSheet("font-size: 13px; font-weight: 700; color: #f2f5f9;")
        panel_layout.addWidget(title)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignLeft)
        form.setFormAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        self.chat_player_assistant_voice_combo = QtWidgets.QComboBox(panel)
        self.chat_player_assistant_voice_combo.setObjectName("chat_player_assistant_voice_combo")
        self.chat_player_assistant_voice_combo.setToolTip("Voice reference used for assistant messages during chat replay. Leave on current TTS voice to use the normal Voice Clone setting.")
        self.chat_player_assistant_voice_combo.currentIndexChanged.connect(lambda _index: self._on_role_voice_changed())
        form.addRow("Assistant Voice", self.chat_player_assistant_voice_combo)

        self.chat_player_user_voice_combo = QtWidgets.QComboBox(panel)
        self.chat_player_user_voice_combo.setObjectName("chat_player_user_voice_combo")
        self.chat_player_user_voice_combo.setToolTip("Voice reference used for user messages during chat replay. Leave on current TTS voice to use the normal Voice Clone setting.")
        self.chat_player_user_voice_combo.currentIndexChanged.connect(lambda _index: self._on_role_voice_changed())
        form.addRow("User Voice", self.chat_player_user_voice_combo)
        panel_layout.addLayout(form)

        refresh_row = QtWidgets.QHBoxLayout()
        self.btn_chat_player_voice_refresh = QtWidgets.QPushButton("Refresh Voices", panel)
        self.btn_chat_player_voice_refresh.setObjectName("btn_chat_player_voice_refresh")
        self.btn_chat_player_voice_refresh.setToolTip("Refresh .wav voice references from the voices folder.")
        self.btn_chat_player_voice_refresh.clicked.connect(self._refresh_role_voice_combos)
        refresh_row.addWidget(self.btn_chat_player_voice_refresh, 0)
        refresh_row.addStretch(1)
        panel_layout.addLayout(refresh_row)

        helper = QtWidgets.QLabel("Replay alternates voices by message role when Chatterbox or another voice-reference TTS backend is active. Normal live chat voice settings are not changed.", panel)
        helper.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        helper.setWordWrap(True)
        panel_layout.addWidget(helper)

        insert_index = layout.count()
        messages_panel = root.findChild(QtWidgets.QFrame, "messages_panel")
        if messages_panel is not None:
            for index in range(layout.count()):
                item = layout.itemAt(index)
                if item is not None and item.widget() is messages_panel:
                    insert_index = index
                    break
        layout.insertWidget(insert_index, panel)

    def export_session_state(self):
        settings = self._current_role_voice_settings() if getattr(self, "chat_player_assistant_voice_combo", None) is not None else self._role_voice_settings()
        return {"chat_replay_role_voices": dict(settings or {})}

    def import_session_state(self, session):
        payload = dict(session or {}).get("chat_replay_role_voices", {})
        if isinstance(payload, dict) and self.runtime_config is not None:
            try:
                self.runtime_config.update("chat_replay_role_voices", payload)
            except Exception:
                pass
        self._refresh_role_voice_combos()

    def _finalize_tab_widget(self, widget):
        self.chat_player_tab_widget = widget
        self._refresh_timer = QtCore.QTimer(widget)
        self._refresh_timer.setInterval(1000)
        self._refresh_timer.timeout.connect(self.refresh_state)
        self._refresh_timer.start()
        self.refresh_state()
        return widget

    def _snapshot(self):
        if self.replay_service is None:
            return {"conversation_history": []}, []
        payload = dict(self.replay_service.snapshot_chat_session() or {})
        if hasattr(self.replay_service, "replayable_chat_entries"):
            replayable = list(self.replay_service.replayable_chat_entries() or [])
        else:
            replayable = list(self.replay_service.replayable_assistant_entries() or [])
        normalized = []
        for entry in replayable:
            if not isinstance(entry, dict):
                continue
            normalized.append(
                {
                    "replay_index": int(entry.get("replay_index", 0) or 0),
                    "preview": str(entry.get("preview", "") or ""),
                    "content": str(entry.get("content", "") or ""),
                }
            )
        return payload, normalized

    def _selected_replay_index(self):
        item = self.chat_player_message_list.currentItem() if hasattr(self, "chat_player_message_list") else None
        if item is None:
            return None
        try:
            return int(item.data(QtCore.Qt.UserRole) or 0) or None
        except Exception:
            return None

    def _rebuild_message_list(self, replayable):
        selected_index = self._selected_replay_index() or self._selected_replay_index_from_state(replayable)
        widget = self.chat_player_message_list
        previous_updates = widget.updatesEnabled()
        previous_signals = widget.blockSignals(True)
        widget.setUpdatesEnabled(False)
        try:
            while widget.count() > len(replayable):
                widget.takeItem(widget.count() - 1)
            for row, entry in enumerate(replayable):
                replay_index = int(entry.get("replay_index", 0) or 0)
                preview = str(entry.get("preview", "") or "").strip()
                text = f"#{replay_index:02d}  {preview}"
                item = widget.item(row)
                if item is None:
                    item = QtWidgets.QListWidgetItem(text)
                    widget.addItem(item)
                elif item.text() != text:
                    item.setText(text)
                item.setData(QtCore.Qt.UserRole, replay_index)
                item.setToolTip(_bounded_text(entry.get("content", ""), _REPLAY_TOOLTIP_MAX_CHARS))
            if replayable:
                target = selected_index if selected_index is not None else int(replayable[-1].get("replay_index", 1) or 1)
                for row in range(widget.count()):
                    item = widget.item(row)
                    if int(item.data(QtCore.Qt.UserRole) or 0) == int(target):
                        widget.setCurrentRow(row)
                        break
        finally:
            widget.setUpdatesEnabled(previous_updates)
            widget.blockSignals(previous_signals)

    def _selected_replay_index_from_state(self, replayable):
        try:
            if self._selected_replay_index_value is not None:
                replay_indexes = {int(entry.get("replay_index", 0) or 0) for entry in replayable}
                if int(self._selected_replay_index_value) in replay_indexes:
                    return int(self._selected_replay_index_value)
        except Exception:
            pass
        return None

    def refresh_state(self):
        payload, replayable = self._snapshot()
        history = list(payload.get("conversation_history") or [])
        total_turns = len(history)
        assistant_turns = sum(1 for item in history if str((item or {}).get("role", "") or "") == "assistant")
        replayable_turns = len(replayable)
        running = bool(self.replay_service.is_engine_running()) if self.replay_service is not None else False
        offline_mode = bool(self.replay_service.is_offline_replay_only()) if self.replay_service is not None else False
        runtime_text = "offline replay runtime active" if offline_mode else ("live runtime active" if running else "runtime stopped")
        if hasattr(self, "chat_player_summary_label"):
            self.chat_player_summary_label.setText(
                f"Conversation turns: {total_turns}\n"
                f"Assistant turns: {assistant_turns}\n"
                f"Replayable messages: {replayable_turns}\n"
                f"Runtime state: {runtime_text}"
            )

        signature = tuple(
            (int(entry.get("replay_index", 0) or 0), _replay_content_signature(entry.get("content", "")))
            for entry in replayable
        )
        if signature != self._last_replay_signature:
            self._last_replay_signature = signature
            if hasattr(self, "chat_player_message_list"):
                self._rebuild_message_list(replayable)

        self._on_message_selection_changed()

    def _on_message_selection_changed(self):
        selected_index = self._selected_replay_index()
        self._selected_replay_index_value = selected_index
        count = self.chat_player_message_list.count() if hasattr(self, "chat_player_message_list") else 0
        has_selection = selected_index is not None and count > 0
        has_any = count > 0
        if hasattr(self, "btn_chat_player_prev"):
            self.btn_chat_player_prev.setEnabled(has_any and has_selection and self.chat_player_message_list.currentRow() > 0)
        if hasattr(self, "btn_chat_player_next"):
            self.btn_chat_player_next.setEnabled(has_any and has_selection and self.chat_player_message_list.currentRow() < count - 1)
        if hasattr(self, "btn_chat_player_replay_selected"):
            self.btn_chat_player_replay_selected.setEnabled(has_selection)
        if hasattr(self, "btn_chat_player_replay_latest"):
            self.btn_chat_player_replay_latest.setEnabled(has_any)
        if hasattr(self, "btn_chat_player_replay_chat"):
            self.btn_chat_player_replay_chat.setEnabled(has_any)
        if hasattr(self, "chat_player_status_label"):
            if has_selection:
                self.chat_player_status_label.setText(
                    f"Selected message #{selected_index}. Use Previous / Next to jump between messages, or start replay from here."
                )
            elif has_any:
                self.chat_player_status_label.setText("Select a message to start replay from that point.")
            else:
                self.chat_player_status_label.setText("Load a chat context or build up a conversation before replaying.")

    def _select_relative(self, delta):
        if not hasattr(self, "chat_player_message_list") or self.chat_player_message_list.count() <= 0:
            return
        row = self.chat_player_message_list.currentRow()
        if row < 0:
            row = self.chat_player_message_list.count() - 1 if delta < 0 else 0
        else:
            row = max(0, min(self.chat_player_message_list.count() - 1, row + int(delta)))
        self.chat_player_message_list.setCurrentRow(row)
        self._on_message_selection_changed()

    def _load_chat_context(self):
        if self.replay_service is None:
            return
        self.replay_service.load_chat_context()
        self.refresh_state()

    def _quick_load_chat_context(self):
        if self.replay_service is None:
            return
        self.replay_service.quick_load_chat_context()
        self.refresh_state()

    def _replay_latest(self):
        if self.replay_service is None:
            return
        self.replay_service.replay_latest_reply()
        self.refresh_state()

    def _replay_selected(self):
        if self.replay_service is None:
            return
        selected_index = self._selected_replay_index()
        if selected_index is None:
            return
        self.replay_service.replay_chat_session_from_index(selected_index)
        self.refresh_state()

    def _replay_chat(self):
        if self.replay_service is None:
            return
        self.replay_service.replay_chat_session()
        self.refresh_state()
