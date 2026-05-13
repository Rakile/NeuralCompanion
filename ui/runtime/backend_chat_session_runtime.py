from PySide6 import QtGui


from ui.runtime.engine_access import engine_module as _engine


def _update_runtime_config(key, value):
    from ui.runtime.engine_access import update_runtime_config

    return update_runtime_config(key, value)


class BackendChatSessionRuntimeMixin:
    """Chat session controls, context-window hints, and chat font sizing."""

    def _chat_overflow_policy_value_from_label(self, label):
        text = str(label or "").strip().lower()
        if text == "truncate middle":
            return "truncate_middle"
        if text == "stop at limit":
            return "stop_at_limit"
        return "rolling_window"

    def _chat_overflow_policy_label_from_value(self, value):
        policy = str(value or "rolling_window").strip().lower()
        if policy == "truncate_middle":
            return "Truncate Middle"
        if policy == "stop_at_limit":
            return "Stop At Limit"
        return "Rolling Window"

    def _chat_font_size_choices(self):
        return [8, 10, 12, 14, 16, 18, 20]

    def _current_chat_font_size(self):
        if hasattr(self, "chat_font_size_combo"):
            data = self.chat_font_size_combo.currentData()
            if data is not None:
                try:
                    return max(8, min(20, int(data)))
                except Exception:
                    pass
        if hasattr(self, "chat_edit"):
            size = int(self.chat_edit.font().pointSize() or 0)
            if size > 0:
                return size
        return 12

    def _apply_chat_font_size(self, size, *, update_combo=True):
        font_size = max(8, min(20, int(size)))
        font = QtGui.QFont("Segoe UI", font_size)
        if hasattr(self, "chat_edit"):
            self.chat_edit.setFont(font)
            if hasattr(self.chat_edit, "document"):
                self.chat_edit.document().setDefaultFont(font)
                cursor = self.chat_edit.textCursor()
                scrollbar = self.chat_edit.verticalScrollBar() if hasattr(self.chat_edit, "verticalScrollBar") else None
                scroll_value = scrollbar.value() if scrollbar is not None else None
                try:
                    full_cursor = QtGui.QTextCursor(self.chat_edit.document())
                    full_cursor.select(QtGui.QTextCursor.Document)
                    text_format = QtGui.QTextCharFormat()
                    text_format.setFontFamily("Segoe UI")
                    text_format.setFontPointSize(font_size)
                    full_cursor.mergeCharFormat(text_format)
                finally:
                    if hasattr(self.chat_edit, "setTextCursor"):
                        self.chat_edit.setTextCursor(cursor)
                    if scrollbar is not None and scroll_value is not None:
                        scrollbar.setValue(scroll_value)
        if update_combo and hasattr(self, "chat_font_size_combo"):
            index = self.chat_font_size_combo.findData(font_size)
            if index >= 0 and self.chat_font_size_combo.currentIndex() != index:
                previous = self.chat_font_size_combo.blockSignals(True)
                try:
                    self.chat_font_size_combo.setCurrentIndex(index)
                finally:
                    self.chat_font_size_combo.blockSignals(previous)

    def _chat_context_usage_label(self):
        engine = _engine()
        config = engine.RUNTIME_CONFIG
        used = len(list(getattr(engine, "conversation_history", []) or []))
        limit = int(config.get("chat_context_window_messages", 20) or 20)
        capped = used > limit
        text = f"context {used}/{limit}"
        if capped:
            policy = self._chat_overflow_policy_label_from_value(config.get("chat_context_overflow_policy", "rolling_window"))
            text = f"{text} ({policy})"
        return text, capped

    def _refresh_chat_session_hint(self):
        if not hasattr(self, "chat_session_hint"):
            return
        proactive_enabled = self.allow_proactive_checkbox.isChecked() if hasattr(self, "allow_proactive_checkbox") else False
        require_first = self.require_first_user_checkbox.isChecked() if hasattr(self, "require_first_user_checkbox") else False
        idle_window = float(self.listen_idle_window_spin.value()) if hasattr(self, "listen_idle_window_spin") else 5.0
        proactive_delay = float(self.proactive_delay_spin.value()) if hasattr(self, "proactive_delay_spin") else 10.0
        context_window = int(self.chat_context_window_spin.value()) if hasattr(self, "chat_context_window_spin") else 20
        stored_limit = int(self.stored_chat_history_limit_spin.value()) if hasattr(self, "stored_chat_history_limit_spin") else 0
        stored_limit_text = "unlimited" if stored_limit <= 0 else f"{stored_limit} message(s)"
        overflow_policy = self._chat_overflow_policy_label_from_value(self._chat_overflow_policy_value_from_label(self.chat_overflow_policy_combo.currentText())) if hasattr(self, "chat_overflow_policy_combo") else "Rolling Window"
        if not proactive_enabled:
            summary = "The assistant will wait for user input and will not speak first on silence."
        else:
            first_turn = "after the first user message" if require_first else "even at the very start of a session"
            summary = (
                f"The assistant checks for speech every {idle_window:.1f}s and may speak first after about "
                f"{proactive_delay:.1f}s of silence, {first_turn}. "
                f"Current model window: about {context_window} message(s) using {overflow_policy}. "
                f"Stored chat history: {stored_limit_text}."
            )
        self.chat_session_hint.setText(summary)

    def on_allow_proactive_replies_changed(self, checked):
        _update_runtime_config("allow_proactive_replies", bool(checked))
        self._refresh_chat_session_hint()
        self.save_session()

    def on_require_first_user_before_proactive_changed(self, checked):
        _update_runtime_config("require_first_user_before_proactive", bool(checked))
        self._refresh_chat_session_hint()
        self.save_session()

    def on_listen_idle_window_changed(self, value):
        _update_runtime_config("listen_idle_window_seconds", round(float(value), 1))
        self._refresh_chat_session_hint()
        self.save_session()

    def on_proactive_delay_changed(self, value):
        _update_runtime_config("proactive_delay_seconds", round(float(value), 1))
        self._refresh_chat_session_hint()
        self.save_session()

    def on_chat_context_window_changed(self, value):
        _update_runtime_config("chat_context_window_messages", max(4, int(value)))
        self._refresh_chat_session_hint()
        self._update_chat_status(self._console_redirect.chat_line_count, int(self.chat_auto_scroll))
        self.save_session()

    def on_stored_chat_history_limit_changed(self, value):
        _update_runtime_config("stored_chat_history_limit", max(0, int(value)))
        self._refresh_chat_session_hint()
        self._update_chat_status(self._console_redirect.chat_line_count, int(self.chat_auto_scroll))
        self.save_session()

    def on_chat_overflow_policy_changed(self, choice):
        _update_runtime_config("chat_context_overflow_policy", self._chat_overflow_policy_value_from_label(choice))
        self._refresh_chat_session_hint()
        self.save_session()

    def on_chat_font_size_changed(self, _index):
        if not hasattr(self, "chat_font_size_combo"):
            return
        size = self.chat_font_size_combo.currentData()
        if size is None:
            return
        self._apply_chat_font_size(size, update_combo=False)
        self.save_session()
