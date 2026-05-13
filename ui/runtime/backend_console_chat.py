import json
import re
import time
from pathlib import Path

from PySide6 import QtCore, QtGui

from core.addons.qt_host_services import QtDialogService


from ui.runtime.engine_access import engine_module as _engine


def _replace_chat_conversation_history(entries, *, allow_pending_loaded_user):
    from ui.runtime.engine_access import replace_chat_conversation_history

    return replace_chat_conversation_history(
        entries,
        allow_pending_loaded_user=allow_pending_loaded_user,
    )


def _capture_musetalk_preview_snapshot(backend=None):
    try:
        state = {}
        if backend is not None and hasattr(backend, "_invoke_addon_service_capability"):
            state = backend._invoke_addon_service_capability(
                "avatar_provider_registry",
                "runtime.preview.current_state",
                {},
                default={},
                provider_id="musetalk",
            )
        state = dict(state or {})
    except Exception:
        return None
    if not state.get("frame_paths") and not state.get("frame_dir"):
        return None
    return state


def _restore_musetalk_preview_snapshot(snapshot, backend=None):
    if not snapshot:
        return
    try:
        if backend is not None and hasattr(backend, "_invoke_addon_service_capability"):
            backend._invoke_addon_service_capability(
                "avatar_provider_registry",
                "runtime.preview.set_state",
                {"state": dict(snapshot)},
                default=None,
                provider_id="musetalk",
            )
            backend._invoke_addon_service_capability(
                "avatar_provider_registry",
                "runtime.preview.prime_frame",
                {"playback_state": dict(snapshot), "runtime_config": getattr(_engine(), "RUNTIME_CONFIG", {})},
                default=None,
                provider_id="musetalk",
            )
    except Exception as exc:
        print(f"⚠️ [MuseTalkPreview] Could not preserve preview during chat context load: {exc}")


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

    def send_typed_chat_message(self, text=None):
        if getattr(self, "chat_edit_mode", False):
            print("[QtGUI] Exit chat edit mode before sending a typed message.")
            return False
        if text is None:
            widget = getattr(self, "chat_message_input", None)
            text = widget.text() if widget is not None and hasattr(widget, "text") else ""
        message = str(text or "").strip()
        if not message:
            return False
        thread = getattr(self, "thread", None)
        if thread is None or not thread.is_alive():
            print("[QtGUI] Initialize the system before sending a typed chat message.")
            return False
        result = _engine().queue_typed_chat_message(message, role="user")
        if not bool(dict(result or {}).get("queued", False)):
            print(f"[QtGUI] Typed chat message was not queued: {dict(result or {}).get('reason', 'unknown')}")
            return False
        widget = getattr(self, "chat_message_input", None)
        if widget is not None and hasattr(widget, "clear"):
            widget.clear()
        print("[QtGUI] Queued typed chat message.")
        return True

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
        addon_id = self._addon_id_for_ui_role("chat_replay", fallback="")
        self._invoke_addon_capability(
            addon_id,
            "backend.add_replay_context_menu_action",
            {"backend": self, "menu": menu, "chat_edit": self.chat_edit, "point": point},
        )
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

    def _is_replay_control_action(self, action):
        raw = str(action or "").strip()
        engine = _engine()
        return (
            raw in {"replay_last_assistant", "replay_chat_session"}
            or engine.parse_replay_chat_session_start_index(raw) is not None
        )

    def trigger_replay_from_assistant_index(self, replay_index):
        engine = _engine()
        replayable_entries = list(engine.collect_replayable_assistant_entries() or [])
        if not replayable_entries:
            print("[QtGUI] Replay ignored: no assistant replies in current chat context.")
            return
        try:
            resolved_index = int(replay_index)
        except Exception:
            resolved_index = 1
        resolved_index = max(1, min(resolved_index, len(replayable_entries)))
        self.trigger_control_action(engine.build_replay_chat_session_from_action(resolved_index))

    def trigger_control_action(self, action):
        engine = _engine()
        if self._dry_run_is_active():
            print(f"[QtGUI] Control action '{action}' ignored while Dry Run is active.")
            return
        if not self.thread or not self.thread.is_alive():
            if self._is_replay_control_action(action):
                replayable = engine.collect_replayable_assistant_messages()
                if not replayable:
                    print("[QtGUI] Replay ignored: no assistant replies in current chat context.")
                    return
                engine.trigger_manual_action(action)
                print(f"[QtGUI] Control action: {action} (offline replay bootstrap)")
                self.start_engine(offline_replay_only=True)
                return
            print("[QtGUI] Control panel ignored: engine not running.")
            return
        if self._engine_is_offline_replay_only() and action not in {"pause_speech", "skip_speech"} and not self._is_replay_control_action(action):
            print(f"[QtGUI] Control action '{action}' is unavailable during offline replay mode.")
            return
        engine.trigger_manual_action(action)
        print(f"[QtGUI] Control action: {action}")

    def reset_chat_session(self):
        _engine().reset_session_state()
        self.clear_chat()
        print("[QtGUI] Chat memory reset.")

    def _default_chat_context_path(self):
        chat_dir = Path("runtime") / "chat_contexts"
        chat_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d-%Hh%Mm%Ss")
        return chat_dir / f"chat_context_{stamp}.json"

    def _quick_chat_context_path(self):
        runtime_dir = Path("runtime")
        runtime_dir.mkdir(parents=True, exist_ok=True)
        return runtime_dir / "chat_context_quick_save.json"

    def save_chat_context(self):
        default_path = self._default_chat_context_path()
        path, _ = QtDialogService(self).save_file(
            "Save Chat Context",
            str(default_path),
            "Chat Context (*.json);;JSON (*.json);;All Files (*.*)",
        )
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != ".json":
            target = target.with_suffix(".json")
        payload = _engine().export_chat_session_state()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"[QtGUI] Chat context saved: {target}")

    def quick_save_chat_context(self):
        target = self._quick_chat_context_path()
        payload = _engine().export_chat_session_state()
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"[QtGUI] Quick chat context saved: {target}")

    def load_chat_context(self):
        path, _ = QtDialogService(self).open_file(
            "Load Chat Context",
            str(Path("runtime") / "chat_contexts"),
            "Chat Context (*.json);;JSON (*.json);;All Files (*.*)",
        )
        if not path:
            return
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        musetalk_preview_snapshot = _capture_musetalk_preview_snapshot(self)
        result = _engine().import_chat_session_state(payload)
        _restore_musetalk_preview_snapshot(musetalk_preview_snapshot, self)
        self._set_chat_edit_mode(False)
        self._rebuild_chat_view_from_history(force=True)
        print(f"[QtGUI] Chat context loaded: {path} ({int(result.get('conversation_turns', 0))} turn(s))")

    def quick_load_chat_context(self):
        path = self._quick_chat_context_path()
        if not path.exists():
            print(f"[QtGUI] Quick chat context not found: {path}")
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        musetalk_preview_snapshot = _capture_musetalk_preview_snapshot(self)
        result = _engine().import_chat_session_state(payload)
        _restore_musetalk_preview_snapshot(musetalk_preview_snapshot, self)
        self._set_chat_edit_mode(False)
        self._rebuild_chat_view_from_history(force=True)
        print(f"[QtGUI] Quick chat context loaded: {path} ({int(result.get('conversation_turns', 0))} turn(s))")
