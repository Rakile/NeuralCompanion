from __future__ import annotations

from PySide6 import QtCore, QtWidgets


class ChatSessionPlayerController(QtCore.QObject):
    def __init__(self, context=None):
        super().__init__()
        self.context = context
        self.dialogs = context.get_service("qt.dialogs") if context is not None else None
        self.replay_service = context.get_service("qt.chat_replay") if context is not None else None
        self.chat_player_tab_widget = None
        self._refresh_timer = None
        self._last_replay_signature = None
        self._selected_replay_index_value = None

    def build_tab(self):
        existing = self.chat_player_tab_widget
        if existing is not None:
            return existing

        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        intro = QtWidgets.QLabel(
            "Replay saved or loaded chat sessions through the active TTS/avatar pipeline without needing fresh LLM generation. "
            "This panel is intentionally separate from the live chat controls so session playback can evolve as its own workflow."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #cbd5e1;")
        layout.addWidget(intro)

        summary_box = QtWidgets.QFrame()
        summary_box.setObjectName("Panel")
        summary_layout = QtWidgets.QVBoxLayout(summary_box)
        summary_layout.setContentsMargins(14, 12, 14, 12)
        summary_layout.setSpacing(6)
        summary_title = QtWidgets.QLabel("Session Summary")
        summary_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #f2f5f9;")
        summary_layout.addWidget(summary_title)
        self.chat_player_summary_label = QtWidgets.QLabel("No chat session loaded.")
        self.chat_player_summary_label.setWordWrap(True)
        self.chat_player_summary_label.setStyleSheet("color: #9fb3c8;")
        summary_layout.addWidget(self.chat_player_summary_label)
        layout.addWidget(summary_box)

        session_box = QtWidgets.QFrame()
        session_box.setObjectName("Panel")
        session_layout = QtWidgets.QVBoxLayout(session_box)
        session_layout.setContentsMargins(14, 12, 14, 12)
        session_layout.setSpacing(10)
        session_title = QtWidgets.QLabel("Session Actions")
        session_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #f2f5f9;")
        session_layout.addWidget(session_title)

        top_row = QtWidgets.QHBoxLayout()
        self.btn_chat_player_load = QtWidgets.QPushButton("Load Chat Context")
        self.btn_chat_player_load.clicked.connect(self._load_chat_context)
        top_row.addWidget(self.btn_chat_player_load)
        self.btn_chat_player_quick_load = QtWidgets.QPushButton("Quick Load")
        self.btn_chat_player_quick_load.clicked.connect(self._quick_load_chat_context)
        top_row.addWidget(self.btn_chat_player_quick_load)
        self.btn_chat_player_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_chat_player_refresh.clicked.connect(self.refresh_state)
        top_row.addWidget(self.btn_chat_player_refresh)
        top_row.addStretch(1)
        session_layout.addLayout(top_row)
        layout.addWidget(session_box)

        messages_box = QtWidgets.QFrame()
        messages_box.setObjectName("Panel")
        messages_layout = QtWidgets.QVBoxLayout(messages_box)
        messages_layout.setContentsMargins(14, 12, 14, 12)
        messages_layout.setSpacing(10)
        messages_title = QtWidgets.QLabel("Assistant Messages")
        messages_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #f2f5f9;")
        messages_layout.addWidget(messages_title)

        self.chat_player_message_list = QtWidgets.QListWidget()
        self.chat_player_message_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.chat_player_message_list.itemSelectionChanged.connect(self._on_message_selection_changed)
        self.chat_player_message_list.itemDoubleClicked.connect(lambda _item: self._replay_selected())
        messages_layout.addWidget(self.chat_player_message_list, 1)

        nav_row = QtWidgets.QHBoxLayout()
        self.btn_chat_player_prev = QtWidgets.QPushButton("Previous")
        self.btn_chat_player_prev.clicked.connect(lambda: self._select_relative(-1))
        nav_row.addWidget(self.btn_chat_player_prev)
        self.btn_chat_player_next = QtWidgets.QPushButton("Next")
        self.btn_chat_player_next.clicked.connect(lambda: self._select_relative(1))
        nav_row.addWidget(self.btn_chat_player_next)
        self.btn_chat_player_replay_selected = QtWidgets.QPushButton("Start Playing From Selected")
        self.btn_chat_player_replay_selected.clicked.connect(self._replay_selected)
        nav_row.addWidget(self.btn_chat_player_replay_selected)
        nav_row.addStretch(1)
        messages_layout.addLayout(nav_row)

        helper = QtWidgets.QLabel(
            "Right-clicking an assistant message in the main Chat tab also lets you start replay from that exact message. "
            "Replay bootstraps its own offline playback runtime when needed, so MuseTalk/Chatterbox can play the loaded context without LM Studio."
        )
        helper.setWordWrap(True)
        helper.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        messages_layout.addWidget(helper)
        layout.addWidget(messages_box, 1)

        playback_box = QtWidgets.QFrame()
        playback_box.setObjectName("Panel")
        playback_layout = QtWidgets.QVBoxLayout(playback_box)
        playback_layout.setContentsMargins(14, 12, 14, 12)
        playback_layout.setSpacing(10)
        playback_title = QtWidgets.QLabel("Playback")
        playback_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #f2f5f9;")
        playback_layout.addWidget(playback_title)

        playback_row = QtWidgets.QHBoxLayout()
        self.btn_chat_player_replay_latest = QtWidgets.QPushButton("Replay Latest Reply")
        self.btn_chat_player_replay_latest.clicked.connect(self._replay_latest)
        playback_row.addWidget(self.btn_chat_player_replay_latest)
        self.btn_chat_player_replay_chat = QtWidgets.QPushButton("Replay Full Chat")
        self.btn_chat_player_replay_chat.clicked.connect(self._replay_chat)
        playback_row.addWidget(self.btn_chat_player_replay_chat)
        playback_row.addStretch(1)
        playback_layout.addLayout(playback_row)
        layout.addWidget(playback_box)

        self.chat_player_status_label = QtWidgets.QLabel("")
        self.chat_player_status_label.setWordWrap(True)
        self.chat_player_status_label.setStyleSheet("color: #9fb3c8;")
        layout.addWidget(self.chat_player_status_label)

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
        replayable = list(self.replay_service.replayable_assistant_entries() or [])
        return payload, replayable

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
        self.chat_player_message_list.clear()
        for entry in replayable:
            replay_index = int(entry.get("replay_index", 0) or 0)
            preview = str(entry.get("preview", "") or "").strip()
            item = QtWidgets.QListWidgetItem(f"#{replay_index:02d}  {preview}")
            item.setData(QtCore.Qt.UserRole, replay_index)
            item.setToolTip(str(entry.get("content", "") or ""))
            self.chat_player_message_list.addItem(item)
        if replayable:
            target = selected_index if selected_index is not None else int(replayable[-1].get("replay_index", 1) or 1)
            for row in range(self.chat_player_message_list.count()):
                item = self.chat_player_message_list.item(row)
                if int(item.data(QtCore.Qt.UserRole) or 0) == int(target):
                    self.chat_player_message_list.setCurrentRow(row)
                    break

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
        running = bool(self.replay_service.is_engine_running()) if self.replay_service is not None else False
        offline_mode = bool(self.replay_service.is_offline_replay_only()) if self.replay_service is not None else False
        runtime_text = "offline replay runtime active" if offline_mode else ("live runtime active" if running else "runtime stopped")
        if hasattr(self, "chat_player_summary_label"):
            self.chat_player_summary_label.setText(
                f"Conversation turns: {total_turns}\n"
                f"Assistant turns: {assistant_turns}\n"
                f"Replayable assistant replies: {len(replayable)}\n"
                f"Runtime state: {runtime_text}"
            )

        signature = tuple((int(entry.get("replay_index", 0) or 0), str(entry.get("content", "") or "")) for entry in replayable)
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
                    f"Selected assistant reply #{selected_index}. Use Previous / Next to jump between replies, or start replay from here."
                )
            elif has_any:
                self.chat_player_status_label.setText("Select an assistant message to start replay from that point.")
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
