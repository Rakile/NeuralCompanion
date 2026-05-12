"""RealUiActionsChatSensoryMixin extracted from real_ui_actions.py."""

import threading

from PySide6 import QtCore, QtGui, QtWidgets


def configure_real_ui_actions_chat_sensory_dependencies(namespace):
    globals().update(dict(namespace or {}))


class RealUiActionsChatSensoryMixin:
    def _on_frontend_sensory_feedback_source_changed(self, _index=None):
            self._sync_single_combo_to_backend("sensory_feedback_source_combo")
            self._refresh_musetalk_visual_runtime_frontend()

    def _on_frontend_chat_font_size_changed(self, _index=None):
            self._sync_single_combo_to_backend("chat_font_size_combo")
            try:
                self.backend.on_chat_font_size_changed(_index)
            except Exception:
                pass
            self._apply_frontend_chat_font_size()
            self._refresh_chat_session_runtime_frontend()

    def _apply_frontend_chat_font_size(self):
            chat_edit = self._ui_object("chat_edit")
            combo = self._ui_object("chat_font_size_combo")
            if chat_edit is None or combo is None:
                return
            try:
                size = combo.currentData() if hasattr(combo, "currentData") else None
                if size is None:
                    size = int(str(combo.currentText() or "12").strip())
                font = QtGui.QFont("Segoe UI", max(8, min(20, int(size))))
            except Exception:
                return
            try:
                chat_edit.setFont(font)
                if hasattr(chat_edit, "document"):
                    chat_edit.document().setDefaultFont(font)
                    cursor = chat_edit.textCursor() if hasattr(chat_edit, "textCursor") else None
                    scrollbar = chat_edit.verticalScrollBar() if hasattr(chat_edit, "verticalScrollBar") else None
                    scroll_value = scrollbar.value() if scrollbar is not None else None
                    full_cursor = QtGui.QTextCursor(chat_edit.document())
                    full_cursor.select(QtGui.QTextCursor.Document)
                    text_format = QtGui.QTextCharFormat()
                    text_format.setFontFamily("Segoe UI")
                    text_format.setFontPointSize(font.pointSize())
                    full_cursor.mergeCharFormat(text_format)
                    if cursor is not None and hasattr(chat_edit, "setTextCursor"):
                        chat_edit.setTextCursor(cursor)
                    if scrollbar is not None and scroll_value is not None:
                        scrollbar.setValue(scroll_value)
            except Exception:
                pass

    def _refresh_chat_session_runtime_frontend(self):
            try:
                self.backend._refresh_chat_session_hint()
            except Exception:
                pass
            try:
                self.backend._update_chat_status(self.backend._console_redirect.chat_line_count, int(self.backend.chat_auto_scroll))
            except Exception:
                pass
            QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))
            QtCore.QTimer.singleShot(300, lambda: self._sync_backend_to_ui(force=True))

    def _on_frontend_allow_proactive_changed(self, checked):
            try:
                self.backend.on_allow_proactive_replies_changed(bool(checked))
            finally:
                self._refresh_chat_session_runtime_frontend()

    def _on_frontend_require_first_user_changed(self, checked):
            try:
                self.backend.on_require_first_user_before_proactive_changed(bool(checked))
            finally:
                self._refresh_chat_session_runtime_frontend()

    def _on_frontend_listen_idle_window_changed(self, value):
            try:
                self.backend.on_listen_idle_window_changed(value)
            finally:
                self._refresh_chat_session_runtime_frontend()

    def _on_frontend_proactive_delay_changed(self, value):
            try:
                self.backend.on_proactive_delay_changed(value)
            finally:
                self._refresh_chat_session_runtime_frontend()

    def _on_frontend_chat_context_window_changed(self, value):
            try:
                self.backend.on_chat_context_window_changed(int(value))
            finally:
                self._refresh_chat_session_runtime_frontend()

    def _on_frontend_stored_chat_history_limit_changed(self, value):
            try:
                self.backend.on_stored_chat_history_limit_changed(int(value))
            finally:
                self._refresh_chat_session_runtime_frontend()

    def _on_frontend_chat_overflow_policy_changed(self, choice):
            try:
                self.backend.on_chat_overflow_policy_changed(str(choice or ""))
            finally:
                self._refresh_chat_session_runtime_frontend()

    def _show_frontend_system_prompt_context_menu(self, point):
            system_prompt_text = self._ui_object("system_prompt_text")
            if system_prompt_text is None:
                return
            try:
                menu = system_prompt_text.createStandardContextMenu()
            except Exception:
                menu = QtWidgets.QMenu(system_prompt_text)
            menu.addSeparator()
            refine_action = menu.addAction("Refine")
            try:
                current_text = str(system_prompt_text.toPlainText() or "").strip()
            except Exception:
                current_text = ""
            refine_action.setEnabled(bool(current_text) and not bool(getattr(self, "_system_prompt_refine_in_flight", False)))
            refine_action.triggered.connect(lambda _checked=False: self._refine_frontend_system_prompt())
            try:
                menu.exec(system_prompt_text.viewport().mapToGlobal(point))
            except Exception:
                pass

    def _refine_frontend_system_prompt(self):
            if bool(getattr(self, "_system_prompt_refine_in_flight", False)):
                return
            system_prompt_text = self._ui_object("system_prompt_text")
            if system_prompt_text is None or not hasattr(system_prompt_text, "toPlainText"):
                return
            original = str(system_prompt_text.toPlainText() or "").strip()
            if not original:
                return
            self._commit_frontend_system_prompt_to_runtime()
            self._system_prompt_refine_in_flight = True

            def worker():
                result = ""
                error = ""
                try:
                    from ui.runtime import engine_access as engine

                    result = str(engine.refine_system_prompt_text(original) or "").strip()
                except Exception as exc:
                    error = str(exc)
                try:
                    self.system_prompt_refined.emit(result, error)
                except RuntimeError:
                    pass

            threading.Thread(target=worker, name="nc-system-prompt-refine", daemon=True).start()

    def _on_frontend_system_prompt_refined(self, refined_prompt, error):
            self._system_prompt_refine_in_flight = False
            system_prompt_text = self._ui_object("system_prompt_text")
            error_text = str(error or "").strip()
            if error_text:
                try:
                    QtWidgets.QMessageBox.warning(self.window, "Refine System Prompt", f"Prompt refinement failed:\n\n{error_text}")
                except Exception:
                    pass
                return
            refined = str(refined_prompt or "").strip()
            if not refined or system_prompt_text is None or not hasattr(system_prompt_text, "setPlainText"):
                return
            try:
                system_prompt_text.setPlainText(refined)
                self._commit_frontend_system_prompt_to_runtime()
            except Exception:
                pass

    def _on_frontend_system_prompt_changed(self):
            if bool(getattr(self, "_frontend_system_prompt_change_in_progress", False)):
                return
            system_prompt_text = None
            try:
                sender = getattr(self, "sender", lambda: None)()
            except Exception:
                sender = None
            if sender is not None and hasattr(sender, "toPlainText"):
                system_prompt_text = sender
            else:
                system_prompt_text = self._ui_object("system_prompt_text")
            if system_prompt_text is None or not hasattr(system_prompt_text, "toPlainText"):
                return
            text = str(system_prompt_text.toPlainText() or "")
            try:
                self._frontend_system_prompt_change_in_progress = True
                update_runtime_config("system_prompt", text.strip())
                backend_text = self._backend_widget("system_prompt_text")
                if backend_text is not None and backend_text is not system_prompt_text and hasattr(backend_text, "setPlainText"):
                    current = str(backend_text.toPlainText() or "") if hasattr(backend_text, "toPlainText") else ""
                    if current != text:
                        was_blocked = bool(backend_text.blockSignals(True)) if hasattr(backend_text, "blockSignals") else False
                        try:
                            backend_text.setPlainText(text)
                        finally:
                            if hasattr(backend_text, "blockSignals"):
                                backend_text.blockSignals(was_blocked)
            except Exception:
                pass
            finally:
                self._frontend_system_prompt_change_in_progress = False

    def _commit_frontend_system_prompt_to_runtime(self):
            system_prompt_text = self._ui_object("system_prompt_text")
            if system_prompt_text is None or not hasattr(system_prompt_text, "toPlainText"):
                return
            try:
                update_runtime_config("system_prompt", str(system_prompt_text.toPlainText() or "").strip())
                self._sync_plain_text_to_backend("system_prompt_text")
                self.backend.save_session()
            finally:
                QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))

    def _on_frontend_emotional_text_changed(self):
            emotional_text = self._ui_object("emotional_text")
            if emotional_text is None or not hasattr(emotional_text, "toPlainText"):
                return
            try:
                update_runtime_config("emotional_instructions", str(emotional_text.toPlainText() or "").strip())
                self._sync_plain_text_to_backend("emotional_text")
            except Exception:
                pass

    def _refresh_sensory_runtime_frontend(self):
            try:
                self.backend._refresh_sensory_feedback_hint()
            except Exception:
                pass
            QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))
            QtCore.QTimer.singleShot(300, lambda: self._sync_backend_to_ui(force=True))

    def _on_frontend_sensory_interval_changed(self, value):
            try:
                self.backend.on_sensory_feedback_interval_changed(value)
            finally:
                self._refresh_sensory_runtime_frontend()

    def _on_frontend_sensory_pingpong_toggled(self, checked):
            try:
                self.backend.on_sensory_pingpong_enabled_changed(bool(checked))
            finally:
                self._refresh_sensory_runtime_frontend()

    def _on_frontend_sensory_hidden_proactive_toggled(self, checked):
            try:
                self.backend.on_sensory_allow_hidden_proactive_changed(bool(checked))
            finally:
                self._refresh_sensory_runtime_frontend()

    def _on_frontend_sensory_hidden_visual_toggled(self, checked):
            try:
                self.backend.on_sensory_allow_hidden_visual_changed(bool(checked))
            finally:
                self._refresh_sensory_runtime_frontend()

    def _on_frontend_sensory_history_changed(self, value):
            try:
                self.backend.on_sensory_pingpong_history_depth_changed(int(value))
            finally:
                self._refresh_sensory_runtime_frontend()

    def _on_frontend_sensory_prompt_changed(self):
            try:
                self.backend.on_sensory_pingpong_prompt_changed()
            finally:
                self._refresh_sensory_runtime_frontend()

    def _reset_frontend_sensory_prompt_to_default(self):
            try:
                self.backend.reset_sensory_pingpong_prompt_to_default()
            finally:
                self._refresh_sensory_runtime_frontend()

    def _on_frontend_chat_provider_changed(self, _index=None):
            frontend_combo = self._ui_object("chat_provider_combo")
            backend_combo = self._backend_widget("chat_provider_combo")
            if frontend_combo is None or backend_combo is None:
                return
            self._sync_combo_like_widget(frontend_combo, backend_combo)
            self._refresh_backend_preset_dirty_state()
            QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))
            QtCore.QTimer.singleShot(300, lambda: self._sync_backend_to_ui(force=True))
            QtCore.QTimer.singleShot(1200, lambda: self._sync_backend_to_ui(force=True))
            QtCore.QTimer.singleShot(50, self._resync_frontend_runtime_cards)
            QtCore.QTimer.singleShot(350, self._resync_frontend_runtime_cards)

    def _on_frontend_model_selection_changed(self, _index=None):
            frontend_combo = self._ui_object("model_combo")
            backend_combo = self._backend_widget("model_combo")
            if frontend_combo is None or backend_combo is None:
                return
            self._sync_combo_like_widget(frontend_combo, backend_combo)
            self._refresh_backend_preset_dirty_state()
            QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))
            QtCore.QTimer.singleShot(50, self._resync_frontend_runtime_cards)

    def _on_frontend_model_requires_vision_changed(self, checked):
            backend_checkbox = self._backend_widget("model_requires_vision_checkbox")
            if backend_checkbox is None or not hasattr(backend_checkbox, "setChecked"):
                return
            try:
                backend_checkbox.setChecked(bool(checked))
            except Exception:
                return
            self._refresh_backend_preset_dirty_state()
            QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))
            QtCore.QTimer.singleShot(300, lambda: self._sync_backend_to_ui(force=True))

    def _on_frontend_preset_selection_changed(self, _index=None):
            frontend_combo = self._ui_object("preset_combo")
            backend_combo = self._backend_widget("preset_combo")
            if frontend_combo is None or backend_combo is None:
                return
            self._sync_combo_like_widget(frontend_combo, backend_combo)
            self._refresh_backend_preset_dirty_state()
            QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))

    def _enter_chat_edit_mode_from_ui_real(self):
            self._sync_backend_to_ui(force=True)
            try:
                self.backend.enter_chat_edit_mode()
            finally:
                self._sync_backend_to_ui(force=True)

    def _cancel_chat_edit_mode_from_ui_real(self):
            try:
                self.backend.cancel_chat_edit_mode()
            finally:
                self._sync_backend_to_ui(force=True)

    def _apply_chat_edit_mode_from_ui_real(self):
            frontend_chat = self._ui_object("chat_edit")
            backend_chat = self._backend_widget("chat_edit")
            if frontend_chat is not None and backend_chat is not None and hasattr(frontend_chat, "toPlainText") and hasattr(backend_chat, "setPlainText"):
                try:
                    backend_chat.setPlainText(str(frontend_chat.toPlainText() or ""))
                except Exception:
                    pass
            try:
                self.backend.apply_chat_edit_mode()
            finally:
                self._sync_backend_to_ui(force=True)
