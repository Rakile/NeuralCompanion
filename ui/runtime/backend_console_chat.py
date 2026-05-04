import re

from PySide6 import QtCore, QtGui


def _engine():
    import engine as engine_module

    return engine_module


def _replace_chat_conversation_history(entries, *, allow_pending_loaded_user):
    from engine import replace_chat_conversation_history

    return replace_chat_conversation_history(
        entries,
        allow_pending_loaded_user=allow_pending_loaded_user,
    )


class BackendConsoleChatMixin:
    """Console/chat mirroring and editable chat transcript behavior."""

    def _connect_console_bridge(self):
        self._console_bridge.text_ready.connect(self._append_console_text)
        self._console_bridge.chat_ready.connect(self._append_chat_text)
        self._console_bridge.status_ready.connect(self._update_console_status)
        self._console_bridge.chat_status_ready.connect(self._update_chat_status)
        self._console_bridge.rebuild_chat_ready.connect(self._on_chat_rebuild_requested)

    def _on_chat_rebuild_requested(self):
        scroll_state = self._capture_vertical_scroll_state(self.chat_edit) if hasattr(self, "chat_edit") else None
        self._rebuild_chat_view_from_history(force=True, preserve_scroll_state=scroll_state)

    def _update_readonly_text_safely(self, widget, text):
        current_text = widget.toPlainText()
        if current_text == text:
            return
        scrollbar = widget.verticalScrollBar()
        old_value = scrollbar.value()
        old_maximum = scrollbar.maximum()
        cursor = widget.textCursor()
        has_selection = cursor.hasSelection()
        if widget.hasFocus() or has_selection:
            return
        widget.setPlainText(text)
        new_scrollbar = widget.verticalScrollBar()
        if old_value >= max(old_maximum - 2, 0):
            new_scrollbar.setValue(new_scrollbar.maximum())
        else:
            new_scrollbar.setValue(min(old_value, new_scrollbar.maximum()))

    def _append_console_text(self, text):
        cursor = self.console_edit.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        cursor.insertText(text)
        for raw_line in str(text or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if "✓ Connected to LM Studio" in line:
                self._tutorial_lm_studio_running = True
                self.emit_tutorial_event("lm_studio_connected", {"line": line})
            elif "✗ Could not connect to LM Studio" in line:
                self._tutorial_lm_studio_running = False
                self.emit_tutorial_event("lm_studio_disconnected", {"line": line})
                self.emit_tutorial_event("error_detected", {"line": line})
            elif "VOICE ASSISTANT READY" in line:
                self.emit_tutorial_event("engine_initialized", {"line": line})
            elif "✓ PocketTTS backend loaded successfully" in line or "✓ ChatterboxTurboTTS loaded successfully" in line:
                self.emit_tutorial_event("tts_initialized", {"line": line})
            elif "✅ [MuseTalk] Avatar prepared:" in line:
                self.emit_tutorial_event("avatar_initialized", {"line": line})
            elif any(marker in line for marker in ("ERROR", "Error", "Failed", "CRITICAL", "Traceback", "✗", "Exception")):
                self.emit_tutorial_event("error_detected", {"line": line})
        if self.console_auto_scroll:
            self.console_edit.setTextCursor(cursor)
            self.console_edit.ensureCursorVisible()
            QtCore.QTimer.singleShot(0, lambda w=self.console_edit: self._force_scroll_to_bottom(w))

    def _force_scroll_to_bottom(self, widget):
        scrollbar = widget.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _capture_vertical_scroll_state(self, widget):
        scrollbar = widget.verticalScrollBar()
        maximum = max(1, int(scrollbar.maximum()))
        value = int(scrollbar.value())
        return {"value": value, "ratio": float(value) / float(maximum)}

    def _restore_vertical_scroll_state(self, widget, state):
        if not state:
            return
        scrollbar = widget.verticalScrollBar()
        if not scrollbar:
            return
        value = int(state.get("value", 0) or 0)
        ratio = float(state.get("ratio", 0.0) or 0.0)
        maximum = int(scrollbar.maximum())
        target = min(max(value, 0), maximum)
        if maximum > 0:
            target = min(max(target, 0), maximum)
        scrollbar.setValue(target)
        if maximum > 0 and target == 0 and ratio > 0.0:
            scrollbar.setValue(int(round(maximum * ratio)))

    def _restore_system_shaping_scroll_state(self, state):
        if not state or not hasattr(self, "system_shaping_scroll"):
            return
        self._restore_vertical_scroll_state(self.system_shaping_scroll, state)

    def _append_chat_text(self, text):
        if getattr(self, "chat_edit_mode", False):
            return
        text = re.sub(r"(?<!\n)(💬 You(?: \([^)]*\))?:|🤖 Assistant:)", r"\n\1", text)
        if not self.chat_edit.toPlainText():
            text = text.lstrip()
        cursor = self.chat_edit.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        default_format = QtGui.QTextCharFormat()
        default_format.setForeground(QtGui.QColor("#e5e9f0"))
        default_format.setFont(QtGui.QFont("Segoe UI", self._current_chat_font_size()))
        speaker_format = QtGui.QTextCharFormat()
        speaker_format.setForeground(QtGui.QColor("#f2f5f9"))
        speaker_format.setFont(QtGui.QFont("Segoe UI", self._current_chat_font_size()))
        speaker_format.setFontWeight(QtGui.QFont.Bold)

        for chunk in re.split(r"(\n)", text):
            if chunk == "":
                continue
            if chunk == "\n":
                cursor.insertText(chunk, default_format)
                continue
            speaker_match = re.match(r"(💬 You(?: \([^)]*\))?:)", chunk)
            if speaker_match:
                speaker = speaker_match.group(1)
                cursor.insertText(speaker, speaker_format)
                remainder = chunk[len(speaker):]
                if remainder:
                    cursor.insertText(remainder, default_format)
                continue
            if chunk.startswith("🤖 Assistant:"):
                cursor.insertText("🤖 Assistant:", speaker_format)
                remainder = chunk[len("🤖 Assistant:"):]
                if remainder:
                    cursor.insertText(remainder, default_format)
                continue
            cursor.insertText(chunk, default_format)
        if self.chat_auto_scroll:
            self.chat_edit.setTextCursor(cursor)
            self.chat_edit.ensureCursorVisible()
            QtCore.QTimer.singleShot(0, lambda w=self.chat_edit: self._force_scroll_to_bottom(w))

    def _update_console_status(self, lines, _auto_scroll):
        state = "on" if self.console_auto_scroll else "off"
        self.console_status.setText(f"{lines} lines | autoscroll {state}")
        self.console_autoscroll_button.setText(f"Autoscroll: {'On' if self.console_auto_scroll else 'Off'}")

    def _update_chat_status(self, lines, _auto_scroll):
        state = "on" if self.chat_auto_scroll else "off"
        edit_suffix = " | edit mode" if getattr(self, "chat_edit_mode", False) else ""
        context_text, capped = self._chat_context_usage_label() if hasattr(self, "chat_status") else ("", False)
        context_suffix = f" | {context_text}" if context_text else ""
        self.chat_status.setText(f"autoscroll {state}{context_suffix}{edit_suffix}")
        self.chat_status.setStyleSheet("color: #ff6b6b;" if capped else "")
        self.chat_autoscroll_button.setText(f"Autoscroll: {'On' if self.chat_auto_scroll else 'Off'}")

    def toggle_console_autoscroll(self):
        self.console_auto_scroll = not self.console_auto_scroll
        self._update_console_status(self._console_redirect.line_count, int(self.console_auto_scroll))
        if self.console_auto_scroll:
            QtCore.QTimer.singleShot(0, lambda w=self.console_edit: self._force_scroll_to_bottom(w))

    def toggle_chat_autoscroll(self):
        self.chat_auto_scroll = not self.chat_auto_scroll
        self._update_chat_status(self._console_redirect.chat_line_count, int(self.chat_auto_scroll))
        if self.chat_auto_scroll:
            QtCore.QTimer.singleShot(0, lambda w=self.chat_edit: self._force_scroll_to_bottom(w))

    def _on_right_tab_changed(self, index):
        if not hasattr(self, "right_tabs"):
            return
        tab_text = str(self.right_tabs.tabText(index) or "").strip().lower()
        if tab_text == "system console" and self.console_auto_scroll:
            QtCore.QTimer.singleShot(0, lambda w=self.console_edit: self._force_scroll_to_bottom(w))
        elif tab_text == "chat" and self.chat_auto_scroll:
            QtCore.QTimer.singleShot(0, lambda w=self.chat_edit: self._force_scroll_to_bottom(w))

    def clear_console(self):
        self.console_edit.clear()
        self._console_redirect.line_count = 0
        self._update_console_status(0, int(self.console_auto_scroll))

    def clear_chat(self):
        self.chat_edit.clear()
        self._console_redirect.chat_line_count = 0
        self._update_chat_status(0, int(self.chat_auto_scroll))

    def _chat_label_for_entry(self, entry):
        role = str((entry or {}).get("role", "") or "").strip().lower()
        origin = str((entry or {}).get("origin", "") or "").strip().lower()
        if role == "assistant" and origin != "assistant_reply":
            return "💬 You (assistant):"
        if role == "assistant":
            return "🤖 Assistant:"
        if role == "system":
            return "💬 You (system):"
        return "💬 You:"

    def _chat_entry_specs(self):
        return [
            ("💬 You (system):", {"role": "system", "origin": "input"}),
            ("💬 You (assistant):", {"role": "assistant", "origin": "input"}),
            ("🤖 Assistant:", {"role": "assistant", "origin": "assistant_reply"}),
            ("💬 You:", {"role": "user", "origin": "input"}),
        ]

    def _parse_chat_display_entries_with_spans(self, raw_text):
        entries = []
        current_entry = None
        current_lines = []
        current_start = 0
        raw = str(raw_text or "")
        offset = 0

        def _flush(end_offset):
            nonlocal current_entry, current_lines, current_start
            if current_entry is None:
                return
            content = "\n".join(current_lines).strip()
            if content:
                entry = dict(current_entry)
                entry["content"] = content
                entry["_start"] = int(current_start)
                entry["_end"] = int(end_offset)
                entries.append(entry)
            current_entry = None
            current_lines = []
            current_start = 0

        for segment in raw.splitlines(keepends=True):
            line = segment.rstrip("\r\n")
            matched = None
            for label, template in self._chat_entry_specs():
                if line.startswith(label):
                    matched = (label, template)
                    break
            if matched is not None:
                _flush(offset)
                label, template = matched
                current_entry = dict(template)
                current_lines = [line[len(label):].lstrip()]
                current_start = offset
            elif current_entry is not None:
                current_lines.append(line)
            offset += len(segment)

        _flush(len(raw))
        return entries

    def _assistant_replay_index_for_chat_position(self, position):
        entries = self._parse_chat_display_entries_with_spans(self.chat_edit.toPlainText())
        replay_index = 0
        total_entries = len(entries)
        for idx, entry in enumerate(entries):
            is_replayable = (
                str(entry.get("role", "") or "") == "assistant"
                and str(entry.get("origin", "") or "") == "assistant_reply"
            )
            if is_replayable:
                replay_index += 1
            start = int(entry.get("_start", 0) or 0)
            end = int(entry.get("_end", start) or start)
            in_entry = start <= position < end
            if not in_entry and idx == total_entries - 1:
                in_entry = start <= position <= end
            if in_entry:
                return replay_index if is_replayable else None
        return None

    def _show_chat_context_menu(self, point):
        menu = self.chat_edit.createStandardContextMenu()
        if not getattr(self, "chat_edit_mode", False):
            cursor = self.chat_edit.cursorForPosition(point)
            replay_index = self._assistant_replay_index_for_chat_position(cursor.position())
            if replay_index is not None:
                menu.addSeparator()
                replay_action = menu.addAction(f"Start Playing From This Message (#{replay_index})")
                replay_action.triggered.connect(lambda _checked=False, idx=replay_index: self.trigger_replay_from_assistant_index(idx))
        menu.exec(self.chat_edit.viewport().mapToGlobal(point))

    def _set_chat_edit_mode(self, enabled):
        self.chat_edit_mode = bool(enabled)
        if hasattr(self, "chat_edit"):
            self.chat_edit.setReadOnly(not self.chat_edit_mode)
        if hasattr(self, "chat_edit_mode_button"):
            self.chat_edit_mode_button.setVisible(not self.chat_edit_mode)
        if hasattr(self, "chat_apply_edit_button"):
            self.chat_apply_edit_button.setVisible(self.chat_edit_mode)
        if hasattr(self, "chat_cancel_edit_button"):
            self.chat_cancel_edit_button.setVisible(self.chat_edit_mode)
        self._update_chat_status(self._console_redirect.chat_line_count, int(self.chat_auto_scroll))

    def enter_chat_edit_mode(self):
        if getattr(self, "chat_edit_mode", False):
            return
        scroll_state = self._capture_vertical_scroll_state(self.chat_edit)
        current_font = QtGui.QFont(self.chat_edit.font())
        self._chat_edit_snapshot_text = self.chat_edit.toPlainText()
        self.chat_edit.setPlainText(self._chat_edit_snapshot_text)
        self.chat_edit.setFont(current_font)
        self.chat_edit.setCurrentFont(current_font)
        self._set_chat_edit_mode(True)
        self._restore_vertical_scroll_state(self.chat_edit, scroll_state)
        QtCore.QTimer.singleShot(0, lambda state=scroll_state: self._restore_vertical_scroll_state(self.chat_edit, state))
        print("[QtGUI] Chat edit mode enabled.")

    def cancel_chat_edit_mode(self):
        if not getattr(self, "chat_edit_mode", False):
            return
        scroll_state = self._capture_vertical_scroll_state(self.chat_edit)
        self._set_chat_edit_mode(False)
        self._rebuild_chat_view_from_history(force=True, preserve_scroll_state=scroll_state)
        print("[QtGUI] Chat edit mode cancelled.")

    def _parse_chat_edit_text(self, raw_text):
        entries = []
        current_entry = None
        current_lines = []
        specs = self._chat_entry_specs()
        for line_no, line in enumerate(str(raw_text or "").splitlines(), start=1):
            matched = None
            for label, template in specs:
                if line.startswith(label):
                    matched = (label, template)
                    break
            if matched is not None:
                if current_entry is not None:
                    content = "\n".join(current_lines).strip()
                    if content:
                        entry = dict(current_entry)
                        entry["content"] = content
                        entries.append(entry)
                label, template = matched
                current_entry = dict(template)
                current_lines = [line[len(label):].lstrip()]
                continue
            if current_entry is None:
                if not line.strip():
                    continue
                raise ValueError(f"Line {line_no} must start with a chat speaker label.")
            current_lines.append(line)
        if current_entry is not None:
            content = "\n".join(current_lines).strip()
            if content:
                entry = dict(current_entry)
                entry["content"] = content
                entries.append(entry)
        return entries

    def apply_chat_edit_mode(self):
        if not getattr(self, "chat_edit_mode", False):
            return
        scroll_state = self._capture_vertical_scroll_state(self.chat_edit)
        try:
            entries = self._parse_chat_edit_text(self.chat_edit.toPlainText())
            result = _replace_chat_conversation_history(entries, allow_pending_loaded_user=False)
        except Exception as exc:
            print(f"[QtGUI] Chat edit apply failed: {exc}")
            return
        self._set_chat_edit_mode(False)
        self._rebuild_chat_view_from_history(force=True, preserve_scroll_state=scroll_state)
        print(f"[QtGUI] Chat context edited in place ({int(result.get('conversation_turns', 0))} turn(s)).")

    def _rebuild_chat_view_from_history(self, force=False, preserve_scroll_state=None):
        if getattr(self, "chat_edit_mode", False) and not force:
            return
        entries = list(getattr(_engine(), "conversation_history", []) or [])
        lines = []
        for entry in entries:
            content = str((entry or {}).get("content", "") or "").strip()
            attachment_image_path = str((entry or {}).get("attachment_image_path", "") or "").strip()
            if not content and not attachment_image_path:
                continue
            if attachment_image_path:
                content = (content or "Please respond to the image I just sent you.") + " [Image attached]"
            lines.append(f"{self._chat_label_for_entry(entry)} {content}")
        self.chat_edit.clear()
        if lines:
            self._append_chat_text("\n".join(lines))
        self._console_redirect.chat_line_count = len(lines)
        self._update_chat_status(len(lines), int(self.chat_auto_scroll))
        self._update_control_action_buttons()
        if preserve_scroll_state is not None:
            QtCore.QTimer.singleShot(0, lambda state=preserve_scroll_state, widget=self.chat_edit: self._restore_vertical_scroll_state(widget, state))
        if self.chat_auto_scroll:
            QtCore.QTimer.singleShot(0, lambda w=self.chat_edit: self._force_scroll_to_bottom(w))
