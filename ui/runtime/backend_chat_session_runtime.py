import threading

from PySide6 import QtCore, QtGui, QtWidgets


from ui.runtime.engine_access import engine_module as _engine


def _update_runtime_config(key, value):
    from ui.runtime.engine_access import update_runtime_config

    return update_runtime_config(key, value)


class _ContinuityMemoryWorkerBridge(QtCore.QObject):
    finished = QtCore.Signal(object, object)


class BackendChatSessionRuntimeMixin:
    """Chat session controls, context-window hints, and chat font sizing."""

    def _register_continuity_memory_update_callback(self):
        if bool(getattr(self, "_continuity_memory_update_callback_registered", False)):
            return
        register = getattr(_engine(), "register_continuity_memory_update_callback", None)
        if not callable(register):
            return

        def _callback(_payload=None):
            try:
                QtCore.QMetaObject.invokeMethod(self, "continuity_memory_updated", QtCore.Qt.QueuedConnection)
            except RuntimeError:
                pass
            except Exception as exc:
                print(f"[QtGUI] Continuity Memory UI refresh signal failed: {exc}")

        self._continuity_memory_update_callback = _callback
        register(_callback)
        self._continuity_memory_update_callback_registered = True

    @QtCore.Slot()
    def continuity_memory_updated(self):
        self._refresh_continuity_memory_hint()

    def _continuity_memory_batch_locked_widgets(self):
        names = (
            "btn_batch_update_long_term_memory",
            "btn_review_long_term_memory",
            "btn_forget_long_term_memory",
            "btn_save_chat_session",
            "btn_save_chat_session_as",
            "btn_load_chat_session",
            "btn_reset_chat_session",
        )
        widgets = []
        for name in names:
            widget = getattr(self, name, None)
            if widget is not None and hasattr(widget, "setEnabled") and widget not in widgets:
                widgets.append(widget)
        return widgets

    def _set_continuity_memory_batch_controls_locked(self, locked):
        if locked:
            previous = {}
            for widget in self._continuity_memory_batch_locked_widgets():
                try:
                    previous[widget] = bool(widget.isEnabled())
                    widget.setEnabled(False)
                except Exception:
                    pass
            self._continuity_memory_batch_previous_enabled = previous
            return
        previous = getattr(self, "_continuity_memory_batch_previous_enabled", {}) or {}
        for widget, was_enabled in list(previous.items()):
            try:
                widget.setEnabled(bool(was_enabled))
            except Exception:
                pass
        self._continuity_memory_batch_previous_enabled = {}
        refresh_save_controls = getattr(self, "_refresh_chat_context_save_controls", None)
        if callable(refresh_save_controls):
            refresh_save_controls()

    def _long_term_memory_archive_locked_widgets(self):
        names = (
            "btn_search_long_term_memory_archive",
            "btn_review_long_term_memory_archive",
        )
        widgets = []
        for name in names:
            widget = getattr(self, name, None)
            if widget is not None and hasattr(widget, "setEnabled") and widget not in widgets:
                widgets.append(widget)
        return widgets

    def _set_long_term_memory_archive_controls_locked(self, locked):
        for widget in self._long_term_memory_archive_locked_widgets():
            try:
                widget.setEnabled(not bool(locked))
            except Exception:
                pass

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

    def _refresh_continuity_memory_hint(self):
        if not hasattr(self, "long_term_memory_hint"):
            return
        try:
            engine = _engine()
            payload = engine.continuity_memory_snapshot()
            config = getattr(engine, "RUNTIME_CONFIG", {}) or {}
        except Exception:
            payload = {}
            config = {}
        summary_chars = len(str((payload or {}).get("summary", "") or ""))
        source_turns = int((payload or {}).get("source_turn_count", 0) or 0)
        total_turns = len(list(getattr(engine, "conversation_history", []) or []))
        summarized_turns = max(0, min(source_turns, total_turns))
        unsummarized_turns = max(0, total_turns - summarized_turns)
        if unsummarized_turns:
            unsummarized_text = (
                f"Un-summarized messages: {unsummarized_turns} "
                f"(messages {summarized_turns + 1}-{total_turns})."
            )
        else:
            unsummarized_text = "Un-summarized messages: 0."
        progress_text = f"Summarized messages: {summarized_turns}/{total_turns}. {unsummarized_text}"
        active_name = str(config.get("active_chat_context_name", "") or "").strip()
        memory_id = str((payload or {}).get("memory_id") or config.get("continuity_memory_id", "") or "").strip()
        target = active_name or memory_id or "unsaved chat"
        auto_enabled = bool(config.get("continuity_memory_auto_summarize", config.get("continuity_memory_update_on_save", True)))
        active_path = str(config.get("active_chat_context_path", "") or "").strip()
        try:
            batch_size = int(getattr(getattr(engine, "continuity_memory", None), "DEFAULT_UPDATE_BATCH_TURNS", 120) or 120)
        except Exception:
            batch_size = 120
        auto_pending_turns = unsummarized_turns
        if auto_enabled and active_path:
            auto_text = "Auto summary is armed for 120-239 new messages."
            if auto_pending_turns >= batch_size * 2:
                next_summary_text = (
                    "Messages until next summarization: Automatic summarization is disabled because "
                    f"{auto_pending_turns} new messages are waiting. Use Summarize Recent... to catch up; "
                    "automatic updates will resume afterward."
                )
            elif auto_pending_turns >= batch_size:
                next_summary_text = "Messages until next summarization: 0 (eligible on the next completed reply)."
            else:
                next_summary_text = f"Messages until next summarization: {batch_size - auto_pending_turns}"
        elif auto_enabled:
            auto_text = "Auto summary starts after this chat has been saved once."
            next_summary_text = "Messages until next summarization: Save this chat once to enable automatic summarization."
        else:
            auto_text = "Auto summary is off."
            next_summary_text = "Messages until next summarization: Automatic summarization is off."
        if summary_chars:
            self.long_term_memory_hint.setText(
                f"Continuity summary for {target}: {summary_chars} character(s).\n{progress_text}\n{auto_text}\n{next_summary_text}"
            )
        else:
            self.long_term_memory_hint.setText(
                f"Continuity summary for {target} is empty. Continue chatting or use Summarize Recent... to create it.\n{progress_text}\n{auto_text}\n{next_summary_text}"
            )

    def _refresh_long_term_memory_hint(self):
        self._refresh_continuity_memory_hint()

    def _refresh_long_term_memory_archive_hint(self):
        if not hasattr(self, "long_term_memory_archive_hint"):
            return
        try:
            engine = _engine()
            store = engine.initialize_long_term_memory_store()
            active_records = engine.list_long_term_memory_records(limit=1000)
            deleted_records = engine.list_long_term_memory_records(status="deleted", include_deleted=True, limit=1000)
            active_chunks = engine.list_long_term_memory_chunks(limit=1000)
            deleted_chunks = engine.list_long_term_memory_chunks(status="deleted", include_deleted=True, limit=1000)
            embedding_status = engine.long_term_memory_embedding_status()
            path = str((store or {}).get("path", "") or "")
        except Exception as exc:
            self.long_term_memory_archive_hint.setText(f"Long-Term Memory archive is unavailable: {exc}")
            return
        embedding_text = "Embeddings off."
        if bool((embedding_status or {}).get("enabled", False)):
            warning = str((embedding_status or {}).get("warning", "") or "").strip()
            embedding_text = (
                f"Embeddings: {int((embedding_status or {}).get('model_embeddings', 0) or 0)} indexed for "
                f"{str((embedding_status or {}).get('model', '') or 'selected model')} "
                f"at context {int((embedding_status or {}).get('context_length', 0) or 0)}; "
                f"{int((embedding_status or {}).get('missing_for_model', 0) or 0)} missing."
            )
            if warning:
                embedding_text += f"\nEmbedding warning: {warning}"
        self.long_term_memory_archive_hint.setText(
            "Long-Term Memory archive: "
            f"{len(active_records)} active record(s), {len(active_chunks)} raw chunk(s). "
            f"Deleted: {len(deleted_records)} record(s), {len(deleted_chunks)} chunk(s).\n"
            f"{embedding_text}\n"
            f"Storage: {path}"
        )

    def _continuity_memory_text(self):
        try:
            payload = _engine().continuity_memory_snapshot()
        except Exception:
            payload = {}
        return str((payload or {}).get("summary", "") or "").strip()

    def _long_term_memory_text(self):
        return self._continuity_memory_text()

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

    def on_continuity_memory_enabled_changed(self, checked):
        _update_runtime_config("continuity_memory_enabled", bool(checked))
        self._refresh_continuity_memory_hint()
        self.save_session()

    def on_long_term_memory_enabled_changed(self, checked):
        self.on_continuity_memory_enabled_changed(checked)

    def on_continuity_memory_update_on_save_changed(self, checked):
        _update_runtime_config("continuity_memory_auto_summarize", bool(checked))
        self.save_session()

    def on_long_term_memory_update_on_save_changed(self, checked):
        self.on_continuity_memory_update_on_save_changed(checked)

    def on_continuity_memory_inject_changed(self, checked):
        _update_runtime_config("continuity_memory_inject", bool(checked))
        self.save_session()

    def on_long_term_memory_inject_changed(self, checked):
        self.on_continuity_memory_inject_changed(checked)

    def on_continuity_memory_max_chars_changed(self, value):
        _update_runtime_config("continuity_memory_max_chars", max(500, min(20000, int(value))))
        self._refresh_continuity_memory_hint()
        self.save_session()

    def on_long_term_memory_max_chars_changed(self, value):
        self.on_continuity_memory_max_chars_changed(value)

    def on_long_term_memory_retrieval_enabled_changed(self, checked):
        _update_runtime_config("long_term_memory_retrieval_enabled", bool(checked))
        self.save_session()

    def on_long_term_memory_retrieval_max_items_changed(self, value):
        _update_runtime_config("long_term_memory_retrieval_max_items", max(1, min(12, int(value))))
        self.save_session()

    def on_long_term_memory_embedding_enabled_changed(self, checked):
        _update_runtime_config("long_term_memory_embedding_enabled", bool(checked))
        self._refresh_long_term_memory_archive_hint()
        self.save_session()

    def on_long_term_memory_embedding_model_changed(self):
        text = ""
        if hasattr(self, "long_term_memory_embedding_model_edit"):
            text = str(self.long_term_memory_embedding_model_edit.text() or "").strip()
        _update_runtime_config("long_term_memory_embedding_model", text or "text-embedding-bge-m3")
        self._refresh_long_term_memory_archive_hint()
        self.save_session()

    def on_long_term_memory_embedding_context_length_changed(self, value):
        _update_runtime_config("long_term_memory_embedding_context_length", max(512, min(262144, int(value))))
        self._refresh_long_term_memory_archive_hint()
        self.save_session()

    def on_long_term_memory_embedding_base_url_changed(self):
        text = ""
        if hasattr(self, "long_term_memory_embedding_base_url_edit"):
            text = str(self.long_term_memory_embedding_base_url_edit.text() or "").strip()
        _update_runtime_config("long_term_memory_embedding_base_url", text or "http://127.0.0.1:1234/v1")
        self._refresh_long_term_memory_archive_hint()
        self.save_session()

    def rebuild_long_term_memory_embeddings_now(self):
        if bool(getattr(self, "_long_term_memory_embedding_rebuild_running", False)):
            return
        self.on_long_term_memory_embedding_model_changed()
        if hasattr(self, "long_term_memory_embedding_context_length_spin"):
            self.on_long_term_memory_embedding_context_length_changed(self.long_term_memory_embedding_context_length_spin.value())
        self.on_long_term_memory_embedding_base_url_changed()
        self._long_term_memory_embedding_rebuild_running = True
        self._set_long_term_memory_archive_controls_locked(True)
        if hasattr(self, "long_term_memory_archive_hint"):
            self.long_term_memory_archive_hint.setText(f"{self.long_term_memory_archive_hint.text()}\nBuilding missing embeddings...")

        bridge = _ContinuityMemoryWorkerBridge()
        bridge.finished.connect(self._on_long_term_memory_embeddings_rebuild_finished)
        self._long_term_memory_embedding_bridge = bridge

        def worker():
            result = None
            error = None
            try:
                result = _engine().rebuild_long_term_memory_embeddings(limit=500)
            except Exception as exc:
                error = exc
            bridge.finished.emit(result, error)

        threading.Thread(target=worker, name="nc-long-term-memory-embeddings", daemon=True).start()

    def _on_long_term_memory_embeddings_rebuild_finished(self, result, error):
        self._long_term_memory_embedding_rebuild_running = False
        self._set_long_term_memory_archive_controls_locked(False)
        self._long_term_memory_embedding_bridge = None
        self._refresh_long_term_memory_archive_hint()
        if error is not None:
            QtWidgets.QMessageBox.warning(self, "Long-Term Memory Embeddings", f"Could not build embeddings:\n{error}")
            return
        result = result or {}
        QtWidgets.QMessageBox.information(
            self,
            "Long-Term Memory Embeddings",
            (
                "Embedding build complete.\n\n"
                f"Selected items: {int(result.get('selected', 0) or 0)}\n"
                f"Embedded: {int(result.get('embedded', 0) or 0)}\n"
                f"Failed: {int(result.get('failed', 0) or 0)}"
            ),
        )

    def update_continuity_memory_now(self):
        try:
            result = _engine().update_continuity_memory_from_current_chat()
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Continuity Memory", f"Could not update memory:\n{exc}")
            return
        self._refresh_continuity_memory_hint()
        QtWidgets.QMessageBox.information(
            self,
            "Continuity Memory",
            f"Memory updated.\n\nStored {int(result.get('summary_chars', 0))} character(s).",
        )

    def update_long_term_memory_now(self):
        self.update_continuity_memory_now()

    def batch_update_continuity_memory_now(self):
        if bool(getattr(self, "_continuity_memory_batch_running", False)):
            return
        total_turns = len(list(getattr(_engine(), "conversation_history", []) or []))
        if total_turns <= 0:
            QtWidgets.QMessageBox.information(self, "Continuity Memory", "There are no chat messages to summarize.")
            return
        default_turns = min(500, total_turns)
        requested_turns, accepted = QtWidgets.QInputDialog.getInt(
            self,
            "Summarize Recent Messages",
            (
                "Summarize the latest N chat messages for Continuity Memory.\n"
                "Older messages will be marked as already handled for continuity."
            ),
            default_turns,
            1,
            total_turns,
            1,
        )
        if not accepted:
            return
        self._continuity_memory_batch_running = True
        self._set_continuity_memory_batch_controls_locked(True)
        if hasattr(self, "long_term_memory_hint"):
            self.long_term_memory_hint.setText(f"{self.long_term_memory_hint.text()}\nSummarizing latest {requested_turns} message(s)...")

        bridge = _ContinuityMemoryWorkerBridge()
        bridge.finished.connect(self._on_continuity_memory_batch_finished)
        self._continuity_memory_batch_bridge = bridge

        def worker():
            result = None
            error = None
            try:
                result = _engine().summarize_recent_continuity_memory_from_current_chat(requested_turns)
            except Exception as exc:
                error = exc
            bridge.finished.emit(result, error)

        threading.Thread(target=worker, name="nc-continuity-memory-batch", daemon=True).start()

    def _on_continuity_memory_batch_finished(self, result, error):
        self._continuity_memory_batch_running = False
        self._set_continuity_memory_batch_controls_locked(False)
        self._refresh_continuity_memory_hint()
        self._continuity_memory_batch_bridge = None
        if error is not None:
            QtWidgets.QMessageBox.warning(self, "Continuity Memory", f"Could not batch summarize memory:\n{error}")
            return
        result = result or {}
        QtWidgets.QMessageBox.information(
            self,
            "Continuity Memory",
            (
                "Recent summary complete.\n\n"
                f"Summarized latest messages: {int(result.get('processed_turns', 0) or 0)}\n"
                f"Remaining un-summarized messages: {int(result.get('remaining_turns', 0) or 0)}"
            ),
        )

    def batch_update_long_term_memory_now(self):
        self.batch_update_continuity_memory_now()

    def review_continuity_memory(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Continuity Memory")
        dialog.resize(720, 420)
        layout = QtWidgets.QVBoxLayout(dialog)
        text_edit = QtWidgets.QPlainTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(self._continuity_memory_text() or "Continuity Memory is empty.")
        layout.addWidget(text_edit)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def review_long_term_memory(self):
        self.review_continuity_memory()

    def forget_continuity_memory(self):
        response = QtWidgets.QMessageBox.question(
            self,
            "Forget Continuity Memory",
            "Clear the stored continuity summary for this chat?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if response != QtWidgets.QMessageBox.Yes:
            return
        try:
            _engine().clear_continuity_memory()
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Continuity Memory", f"Could not clear memory:\n{exc}")
            return
        self._refresh_continuity_memory_hint()

    def forget_long_term_memory(self):
        self.forget_continuity_memory()

    def extract_long_term_memory_archive_now(self):
        if bool(getattr(self, "_long_term_memory_archive_extract_running", False)):
            return
        total_turns = len(list(getattr(_engine(), "conversation_history", []) or []))
        if total_turns <= 0:
            QtWidgets.QMessageBox.information(self, "Long-Term Memory Archive", "There are no chat messages to extract from.")
            return
        default_turns = min(120, total_turns)
        requested_turns, accepted = QtWidgets.QInputDialog.getInt(
            self,
            "Extract Long-Term Memory",
            "Extract structured Long-Term Memory records from the latest N chat messages.",
            default_turns,
            1,
            total_turns,
            1,
        )
        if not accepted:
            return
        self._long_term_memory_archive_extract_running = True
        self._set_long_term_memory_archive_controls_locked(True)
        if hasattr(self, "long_term_memory_archive_hint"):
            self.long_term_memory_archive_hint.setText(
                f"{self.long_term_memory_archive_hint.text()}\nExtracting from latest {requested_turns} message(s)..."
            )

        bridge = _ContinuityMemoryWorkerBridge()
        bridge.finished.connect(self._on_long_term_memory_archive_extract_finished)
        self._long_term_memory_archive_bridge = bridge

        def worker():
            result = None
            error = None
            try:
                result = _engine().extract_long_term_memory_records_from_current_chat(
                    turn_count=requested_turns,
                    max_records=12,
                )
            except Exception as exc:
                error = exc
            bridge.finished.emit(result, error)

        threading.Thread(target=worker, name="nc-long-term-memory-extract", daemon=True).start()

    def _on_long_term_memory_archive_extract_finished(self, result, error):
        self._long_term_memory_archive_extract_running = False
        self._set_long_term_memory_archive_controls_locked(False)
        self._long_term_memory_archive_bridge = None
        self._refresh_long_term_memory_archive_hint()
        if error is not None:
            QtWidgets.QMessageBox.warning(self, "Long-Term Memory Archive", f"Could not extract memory records:\n{error}")
            return
        result = result or {}
        QtWidgets.QMessageBox.information(
            self,
            "Long-Term Memory Archive",
            (
                "Extraction complete.\n\n"
                f"Selected messages: {int(result.get('selected_turns', 0) or 0)}\n"
                f"Archived raw chunks: {int(result.get('archived_chunks', 0) or 0)}\n"
                f"Stored records: {int(result.get('stored_records', 0) or 0)}"
            ),
        )

    def review_long_term_memory_archive(self):
        try:
            records = _engine().list_long_term_memory_records(limit=200)
            chunks = _engine().list_long_term_memory_chunks(limit=50)
            store = _engine().initialize_long_term_memory_store()
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Long-Term Memory Archive", f"Could not load archive records:\n{exc}")
            return
        lines = [f"Storage: {str((store or {}).get('path', '') or '')}", ""]
        if not records and not chunks:
            lines.append("Long-Term Memory archive is empty.")
        if chunks:
            lines.extend(["Raw Archived Chat Chunks", ""])
            for index, chunk in enumerate(chunks, start=1):
                preview = str(chunk.get("text", "") or "").strip()
                if len(preview) > 700:
                    preview = preview[:697].rstrip() + "..."
                lines.extend([
                    f"{index}. {chunk.get('id', '')}",
                    f"   Source: {chunk.get('source_chat_id', '')} messages {chunk.get('source_message_start', '')}-{chunk.get('source_message_end', '')}",
                    f"   Text: {preview}",
                    "",
                ])
        if records:
            lines.extend(["Extracted Memory Records", ""])
        for index, record in enumerate(records, start=1):
            tags = ", ".join(list(record.get("tags") or []))
            lines.extend([
                f"{index}. {record.get('title', '')}",
                f"   ID: {record.get('id', '')}",
                f"   Type: {record.get('type', '')} | Importance: {record.get('importance', 0):.2f} | Confidence: {record.get('confidence', 0):.2f}",
                f"   Source: {record.get('source_chat_id', '')} messages {record.get('source_message_start', '')}-{record.get('source_message_end', '')}",
                f"   Tags: {tags}",
                f"   Summary: {record.get('summary', '')}",
                "",
            ])
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Long-Term Memory Archive")
        dialog.resize(820, 520)
        layout = QtWidgets.QVBoxLayout(dialog)
        text_edit = QtWidgets.QPlainTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText("\n".join(lines).strip())
        layout.addWidget(text_edit)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def search_long_term_memory_archive(self):
        query, accepted = QtWidgets.QInputDialog.getText(
            self,
            "Search Long-Term Memory Archive",
            "Search extracted memory records and raw archived chat chunks:",
        )
        if not accepted:
            return
        query = str(query or "").strip()
        if not query:
            QtWidgets.QMessageBox.information(self, "Long-Term Memory Archive", "Enter a search query first.")
            return
        try:
            results = _engine().retrieve_long_term_memory(query, record_limit=8, chunk_limit=5)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Long-Term Memory Archive", f"Could not search archive:\n{exc}")
            return
        lines = [f"Query: {query}", f"Matches: {len(results)}", ""]
        if not results:
            lines.append("No archive matches found.")
        for index, item in enumerate(results, start=1):
            tags = ", ".join(list(item.get("tags") or []))
            label = "Memory Record" if item.get("kind") == "record" else "Raw Chat Chunk"
            lines.extend([
                f"{index}. {label}: {item.get('title', '')}",
                f"   ID: {item.get('id', '')}",
                f"   Type: {item.get('type', '')}",
                f"   Source: {item.get('source_chat_id', '')} messages {item.get('source_message_start', '')}-{item.get('source_message_end', '')}",
                f"   Tags: {tags}",
                f"   Snippet: {item.get('snippet', '')}",
                "",
            ])
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Search Long-Term Memory Archive")
        dialog.resize(820, 520)
        layout = QtWidgets.QVBoxLayout(dialog)
        text_edit = QtWidgets.QPlainTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText("\n".join(lines).strip())
        layout.addWidget(text_edit)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def on_chat_font_size_changed(self, _index):
        if not hasattr(self, "chat_font_size_combo"):
            return
        size = self.chat_font_size_combo.currentData()
        if size is None:
            return
        self._apply_chat_font_size(size, update_combo=False)
        self.save_session()
