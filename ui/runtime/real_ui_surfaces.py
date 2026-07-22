from PySide6 import QtCore, QtWidgets

from core import long_term_memory


def configure_real_ui_surfaces_dependencies(namespace):
    """Inject qt_app-owned globals used by the extracted real-UI surface mixin."""
    globals().update(dict(namespace or {}))


class MainUiRealSurfacesMixin:
    """Runtime surface redirection helpers for mounting hidden-backend widgets into main.ui."""

    def _invoke_surface_addon_capability(self, addon_id, capability, payload=None, default=None):
            callback = getattr(self.backend, "_invoke_addon_capability", None)
            if not callable(callback):
                return default
            payload = dict(payload or {})
            payload.setdefault("bridge", self)
            return callback(addon_id, capability, payload, default=default)

    def _invoke_surface_avatar_capability(self, provider_id, capability, payload=None, default=None):
            callback = getattr(self.backend, "_invoke_addon_service_capability", None)
            if not callable(callback):
                return default
            payload = dict(payload or {})
            payload.setdefault("bridge", self)
            return callback(
                "avatar_provider_registry",
                capability,
                payload,
                default=default,
                provider_id=provider_id,
            )

    def _visual_reply_addon_id_for_surface(self):
            callback = getattr(self.backend, "_addon_id_for_ui_role", None)
            if callable(callback):
                return callback("visual_reply", fallback="")
            return ""

    def _disable_unwired_phase5_controls(self):
            tooltip = "Deferred in --ui-real Phase 5. This still belongs to a later runtime migration slice."
            for object_name in (
            ):
                widget = self._ui_object(object_name)
                if widget is None or not hasattr(widget, "setEnabled"):
                    continue
                widget.setEnabled(False)
                if hasattr(widget, "setToolTip"):
                    widget.setToolTip(tooltip)

    def _mark_frontend_widget_preview_only(self, object_name, reason, *, hide=True):
            widget = self._ui_object(object_name)
            if widget is None:
                return False
            legacy_name = str(object_name or "").strip()
            if legacy_name and not legacy_name.endswith("_legacy") and hasattr(widget, "setObjectName"):
                try:
                    widget.setObjectName(f"{legacy_name}_legacy")
                except Exception:
                    pass
            if hasattr(widget, "setProperty"):
                try:
                    widget.setProperty("nc_preview_only_non_target", True)
                except Exception:
                    pass
            for method_name in ("setToolTip", "setStatusTip", "setWhatsThis"):
                method = getattr(widget, method_name, None)
                if callable(method):
                    try:
                        method(reason)
                    except Exception:
                        pass
            if hasattr(widget, "setEnabled"):
                try:
                    widget.setEnabled(False)
                except Exception:
                    pass
            if hide and hasattr(widget, "hide"):
                try:
                    widget.hide()
                except Exception:
                    pass
            return True

    def _cleanup_frontend_preview_only_roots(self):
            adopted_report = dict(getattr(self, "_adopted_runtime_tabs", {}) or {})
            for entry in UI_REAL_PREVIEW_ONLY_ROOTS:
                object_name = str(entry.get("object_name") or "").strip()
                if not object_name:
                    continue
                runtime_flag = str(entry.get("runtime_flag") or "").strip()
                if runtime_flag and not bool(getattr(self, runtime_flag, False)):
                    continue
                adopted_target = str(entry.get("adopted_target") or "").strip()
                adopted_title = str(entry.get("adopted_title") or "").strip()
                if adopted_target and adopted_title:
                    adopted_titles = list(adopted_report.get(adopted_target) or [])
                    if adopted_title not in adopted_titles:
                        continue
                self._mark_frontend_widget_preview_only(
                    object_name,
                    str(entry.get("reason") or "Static Designer preview surface; not the live runtime owner."),
                )

    def _configure_phase5_placeholders(self):
            provider_placeholder = self._ui_object("chat_provider_fields_placeholder")
            if provider_placeholder is not None and hasattr(provider_placeholder, "setText"):
                provider_placeholder.setText(
                    "Phase 5 --ui-real note:\n"
                    "Provider-specific runtime editors are now rendered into the real Designer surface through the hidden backend."
                )
            generation_placeholder = self._ui_object("chat_provider_generation_fields_placeholder")
            if generation_placeholder is not None and hasattr(generation_placeholder, "setText"):
                generation_placeholder.setText(
                    "Phase 5 --ui-real note:\n"
                    "Provider generation-field editors are now rendered into the real Designer surface through the hidden backend."
                )

    def _apply_frontend_chat_tab_tooltips(self):
            tooltip_getter = getattr(self.backend, "_chat_tab_tooltip_map", None)
            if not callable(tooltip_getter):
                return
            for object_name, tooltip in dict(tooltip_getter() or {}).items():
                widget = self._ui_object(object_name)
                if widget is not None and hasattr(widget, "setToolTip"):
                    widget.setToolTip(str(tooltip or "").strip())

    def _redirect_backend_provider_runtime_surface(self):
            fields_layout = self._ui_object("chat_provider_fields_layout")
            generation_layout = self._ui_object("chat_provider_generation_fields_layout")
            fields_widget = self._ui_object("chat_provider_fields_widget")
            generation_widget = self._ui_object("chat_provider_generation_fields_widget")
            if fields_layout is None or generation_layout is None:
                return
            self.backend.chat_provider_fields_widget = fields_widget
            self.backend.chat_provider_fields_layout = fields_layout
            self.backend.chat_provider_generation_fields_widget = generation_widget
            self.backend.chat_provider_generation_fields_layout = generation_layout
            try:
                self.backend._refresh_chat_provider_card()
                self.backend._refresh_chat_runtime_summary()
                self._apply_frontend_chat_tab_tooltips()
                self._provider_runtime_redirected = True
            except Exception as exc:
                print(f"[UI Real] Provider runtime surface redirect failed: {exc}")

    def _ensure_frontend_long_term_memory_widgets(self):
            session_button = self._ui_object("btn_save_chat_session")
            if session_button is None:
                return
            session_box = session_button
            while session_box is not None and not isinstance(session_box, QtWidgets.QGroupBox):
                session_box = session_box.parentWidget()
            parent_widget = session_box.parentWidget() if session_box is not None else None
            parent_layout = parent_widget.layout() if parent_widget is not None and hasattr(parent_widget, "layout") else None
            if session_box is not None and hasattr(session_box, "setTitle"):
                try:
                    if str(session_box.title() or "").strip().lower() == "conversation memory":
                        session_box.setTitle("Chat context")
                except Exception:
                    pass

            def _ensure_export_button_in_archive(archive_box):
                if archive_box is None or self._ui_object("btn_export_session_memory") is not None:
                    return
                review_archive = self._ui_object("btn_review_long_term_memory_archive")
                anchor = review_archive if review_archive is not None else self._ui_object("btn_rebuild_long_term_memory_embeddings")
                button_parent = anchor.parentWidget() if anchor is not None else archive_box
                button_layout = button_parent.layout() if button_parent is not None and hasattr(button_parent, "layout") else None
                if button_layout is None or not hasattr(button_layout, "insertWidget"):
                    return
                export_button = QtWidgets.QPushButton("Export Session Memory...", button_parent)
                export_button.setObjectName("btn_export_session_memory")
                insert_index = button_layout.indexOf(review_archive) if review_archive is not None else -1
                button_layout.insertWidget(insert_index + 1 if insert_index >= 0 else button_layout.count(), export_button)

            def _ensure_archive_box():
                existing_archive_box = self._ui_object("long_term_memory_archive_group")
                if existing_archive_box is not None:
                    _ensure_export_button_in_archive(existing_archive_box)
                    return
                if parent_widget is None or parent_layout is None or not hasattr(parent_layout, "insertWidget"):
                    return

                def _backend_archive_checked(name, default=False):
                    widget = getattr(self.backend, name, None)
                    return bool(widget.isChecked()) if widget is not None and hasattr(widget, "isChecked") else bool(default)

                def _backend_archive_value(name, default=6):
                    widget = getattr(self.backend, name, None)
                    try:
                        return int(widget.value()) if widget is not None and hasattr(widget, "value") else int(default)
                    except Exception:
                        return int(default)

                def _backend_archive_text(name, default=""):
                    widget = getattr(self.backend, name, None)
                    try:
                        return str(widget.text() or "") if widget is not None and hasattr(widget, "text") else str(default)
                    except Exception:
                        return str(default)

                archive_box = QtWidgets.QGroupBox("Long-term archive", parent_widget)
                archive_box.setObjectName("long_term_memory_archive_group")
                archive_layout = QtWidgets.QVBoxLayout(archive_box)
                archive_layout.setContentsMargins(12, 14, 12, 12)
                archive_layout.setSpacing(8)
                archive_intro = QtWidgets.QLabel(
                    "Long-term archive saves older chat notes when you save conversation memory or after the archive interval. Matching archive notes can be added back into future chat requests.",
                    archive_box,
                )
                archive_intro.setWordWrap(True)
                archive_intro.setStyleSheet("color: #8ea3b8; font-size: 11px;")
                archive_layout.addWidget(archive_intro)

                retrieval_enabled = QtWidgets.QCheckBox("Use long-term archive in chat", archive_box)
                retrieval_enabled.setObjectName("long_term_memory_retrieval_enabled_checkbox")
                retrieval_enabled.setChecked(_backend_archive_checked("long_term_memory_retrieval_enabled_checkbox", False))
                archive_layout.addWidget(retrieval_enabled)

                image_review_enabled = QtWidgets.QCheckBox("Review recalled images before sending", archive_box)
                image_review_enabled.setObjectName("long_term_memory_image_review_enabled_checkbox")
                image_review_enabled.setChecked(_backend_archive_checked("long_term_memory_image_review_enabled_checkbox", False))
                archive_layout.addWidget(image_review_enabled)

                auto_archive_enabled = QtWidgets.QCheckBox("Enable long-term memory archiving", archive_box)
                auto_archive_enabled.setObjectName("long_term_memory_auto_archive_enabled_checkbox")
                auto_archive_enabled.setChecked(_backend_archive_checked("long_term_memory_auto_archive_enabled_checkbox", False))
                archive_layout.addWidget(auto_archive_enabled)

                retrieval_max_items = QtWidgets.QSpinBox(archive_box)
                retrieval_max_items.setObjectName("long_term_memory_retrieval_max_items_spin")
                retrieval_max_items.setRange(1, 12)
                retrieval_max_items.setSingleStep(1)
                retrieval_max_items.setValue(max(1, min(12, _backend_archive_value("long_term_memory_retrieval_max_items_spin", 6))))
                retrieval_max_items.setMinimumWidth(112)
                retrieval_max_items.setMaximumWidth(132)
                recall_text_budget = QtWidgets.QSpinBox(archive_box)
                recall_text_budget.setObjectName("long_term_memory_recall_text_budget_spin")
                recall_text_budget.setRange(-1, 2147483647)
                recall_text_budget.setSingleStep(500)
                recall_text_budget.setValue(long_term_memory.normalize_recall_text_budget(_backend_archive_value("long_term_memory_recall_text_budget_spin", -1), default=-1))
                recall_text_budget.setMinimumWidth(112)
                recall_text_budget.setMaximumWidth(132)
                recall_image_limit = QtWidgets.QSpinBox(archive_box)
                recall_image_limit.setObjectName("long_term_memory_recall_image_limit_spin")
                recall_image_limit.setRange(-1, 2147483647)
                recall_image_limit.setSingleStep(1)
                recall_image_limit.setValue(long_term_memory.normalize_image_recall_limit(_backend_archive_value("long_term_memory_recall_image_limit_spin", 1), default=1))
                recall_image_limit.setMinimumWidth(112)
                recall_image_limit.setMaximumWidth(132)
                archive_batch_turns = QtWidgets.QSpinBox(archive_box)
                archive_batch_turns.setObjectName("long_term_memory_archive_batch_turns_spin")
                archive_batch_turns.setRange(1, 10000)
                archive_batch_turns.setSingleStep(10)
                archive_batch_turns.setValue(max(1, min(10000, _backend_archive_value("long_term_memory_archive_batch_turns_spin", 120))))
                archive_batch_turns.setMinimumWidth(112)
                archive_batch_turns.setMaximumWidth(132)
                retrieval_form = QtWidgets.QFormLayout()
                retrieval_form.setLabelAlignment(QtCore.Qt.AlignLeft)
                retrieval_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldsStayAtSizeHint)
                retrieval_form.setFormAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
                retrieval_form.addRow("Archive every (messages)", archive_batch_turns)
                retrieval_form.addRow("Archive notes to use", retrieval_max_items)
                retrieval_form.addRow("Recall text budget (chars, -1 = no cap)", recall_text_budget)
                retrieval_form.addRow("Long-Term Memory recalled images to attach", recall_image_limit)
                embedding_model = QtWidgets.QComboBox(archive_box)
                embedding_model.setObjectName("long_term_memory_embedding_model_edit")
                embedding_model.setEditable(True)
                embedding_model.addItem(_backend_archive_text("long_term_memory_embedding_model_edit", "text-embedding-bge-m3"))
                embedding_model.setMinimumWidth(220)
                embedding_refresh = QtWidgets.QPushButton("Refresh", archive_box)
                embedding_refresh.setObjectName("btn_long_term_memory_embedding_model_refresh")
                embedding_context = QtWidgets.QSpinBox(archive_box)
                embedding_context.setObjectName("long_term_memory_embedding_context_length_spin")
                embedding_context.setRange(512, 262144)
                embedding_context.setSingleStep(512)
                embedding_context.setValue(max(512, min(262144, _backend_archive_value("long_term_memory_embedding_context_length_spin", 8192))))
                embedding_context.setMinimumWidth(112)
                embedding_context.setMaximumWidth(132)
                embedding_base_url = QtWidgets.QLineEdit(_backend_archive_text("long_term_memory_embedding_base_url_edit", "http://127.0.0.1:1234/v1"), archive_box)
                embedding_base_url.setObjectName("long_term_memory_embedding_base_url_edit")
                embedding_base_url.setMinimumWidth(220)
                embedding_model_row = QtWidgets.QHBoxLayout()
                embedding_model_row.setSpacing(8)
                embedding_model_row.addWidget(embedding_model, 1)
                embedding_model_row.addWidget(embedding_refresh)
                retrieval_form.addRow("Semantic search model", embedding_model_row)
                retrieval_form.addRow("Semantic search context", embedding_context)
                retrieval_form.addRow("Semantic search server", embedding_base_url)
                archive_layout.addLayout(retrieval_form)

                embedding_enabled = QtWidgets.QCheckBox("Use semantic search for archive matches", archive_box)
                embedding_enabled.setObjectName("long_term_memory_embedding_enabled_checkbox")
                embedding_enabled.setChecked(_backend_archive_checked("long_term_memory_embedding_enabled_checkbox", False))
                archive_layout.addWidget(embedding_enabled)

                archive_button_row = QtWidgets.QHBoxLayout()
                archive_button_row.setSpacing(8)
                search_archive = QtWidgets.QPushButton("Search Archive...", archive_box)
                search_archive.setObjectName("btn_search_long_term_memory_archive")
                review_archive = QtWidgets.QPushButton("Review Archive", archive_box)
                review_archive.setObjectName("btn_review_long_term_memory_archive")
                export_memory = QtWidgets.QPushButton("Export Session Memory...", archive_box)
                export_memory.setObjectName("btn_export_session_memory")
                rebuild_embeddings = QtWidgets.QPushButton("Rebuild Embeddings", archive_box)
                rebuild_embeddings.setObjectName("btn_rebuild_long_term_memory_embeddings")
                archive_button_row.addWidget(search_archive)
                archive_button_row.addWidget(review_archive)
                archive_button_row.addWidget(export_memory)
                archive_button_row.addWidget(rebuild_embeddings)
                archive_button_row.addStretch(1)
                archive_layout.addLayout(archive_button_row)
                archive_hint = QtWidgets.QLabel(archive_box)
                archive_hint.setObjectName("long_term_memory_archive_hint")
                archive_hint.setWordWrap(True)
                archive_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
                archive_layout.addWidget(archive_hint)
                anchor = self._ui_object("long_term_memory_group") or session_box
                insert_index = parent_layout.indexOf(anchor)
                parent_layout.insertWidget(insert_index + 1 if insert_index >= 0 else parent_layout.count(), archive_box)

            if self._ui_object("btn_save_chat_session_as") is None:
                button_parent = session_button.parentWidget()
                button_layout = button_parent.layout() if button_parent is not None and hasattr(button_parent, "layout") else None
                if button_layout is not None and hasattr(button_layout, "insertWidget"):
                    save_as = QtWidgets.QPushButton("Save Chat Context As...", button_parent)
                    save_as.setObjectName("btn_save_chat_session_as")
                    insert_index = button_layout.indexOf(session_button)
                    button_layout.insertWidget(insert_index + 1 if insert_index >= 0 else button_layout.count(), save_as)
            if self._ui_object("long_term_memory_enabled_checkbox") is not None:
                auto_checkbox = self._ui_object("long_term_memory_update_on_save_checkbox")
                if auto_checkbox is not None and hasattr(auto_checkbox, "setText"):
                    auto_checkbox.setText("Enable Conversation Memory summarization")
                update_button = self._ui_object("btn_update_long_term_memory")
                if update_button is not None:
                    update_button.setVisible(False)
                    update_button.setEnabled(False)
                if self._ui_object("btn_batch_update_long_term_memory") is None:
                    review_button = self._ui_object("btn_review_long_term_memory")
                    anchor_button = review_button or update_button
                    if anchor_button is not None:
                        button_parent = anchor_button.parentWidget()
                        button_layout = button_parent.layout() if button_parent is not None and hasattr(button_parent, "layout") else None
                        if button_layout is not None and hasattr(button_layout, "insertWidget"):
                            batch_update = QtWidgets.QPushButton("Update Memory...", button_parent)
                            batch_update.setObjectName("btn_batch_update_long_term_memory")
                            insert_index = button_layout.indexOf(anchor_button)
                            button_layout.insertWidget(insert_index + 1 if insert_index >= 0 else button_layout.count(), batch_update)
                _ensure_archive_box()
                return

            if session_box is None:
                return
            if parent_layout is None or not hasattr(parent_layout, "insertWidget"):
                return

            def _backend_checked(name, default=False):
                widget = getattr(self.backend, name, None)
                return bool(widget.isChecked()) if widget is not None and hasattr(widget, "isChecked") else bool(default)

            def _backend_value(name, default=3000):
                widget = getattr(self.backend, name, None)
                try:
                    return int(widget.value()) if widget is not None and hasattr(widget, "value") else int(default)
                except Exception:
                    return int(default)

            memory_box = QtWidgets.QGroupBox("Conversation memory", parent_widget)
            memory_box.setObjectName("long_term_memory_group")
            memory_layout = QtWidgets.QVBoxLayout(memory_box)
            memory_layout.setContentsMargins(12, 14, 12, 12)
            memory_layout.setSpacing(8)

            enabled = QtWidgets.QCheckBox("Remember a running conversation summary", memory_box)
            enabled.setObjectName("long_term_memory_enabled_checkbox")
            enabled.setChecked(_backend_checked("long_term_memory_enabled_checkbox", False))
            memory_layout.addWidget(enabled)

            update_on_save = QtWidgets.QCheckBox("Enable Conversation Memory summarization", memory_box)
            update_on_save.setObjectName("long_term_memory_update_on_save_checkbox")
            update_on_save.setChecked(_backend_checked("long_term_memory_update_on_save_checkbox", False))
            memory_layout.addWidget(update_on_save)

            inject = QtWidgets.QCheckBox("Use conversation memory in replies", memory_box)
            inject.setObjectName("long_term_memory_inject_checkbox")
            inject.setChecked(_backend_checked("long_term_memory_inject_checkbox", False))
            memory_layout.addWidget(inject)

            max_chars = QtWidgets.QSpinBox(memory_box)
            max_chars.setObjectName("long_term_memory_max_chars_spin")
            max_chars.setRange(500, 20000)
            max_chars.setSingleStep(250)
            max_chars.setValue(max(500, min(20000, _backend_value("long_term_memory_max_chars_spin", 3000))))
            max_chars.setMinimumWidth(112)
            max_chars.setMaximumWidth(132)
            auto_turns = QtWidgets.QSpinBox(memory_box)
            auto_turns.setObjectName("continuity_memory_auto_turns_spin")
            auto_turns.setRange(1, 10000)
            auto_turns.setSingleStep(10)
            auto_turns.setValue(max(1, min(10000, _backend_value("continuity_memory_auto_turns_spin", 120))))
            auto_turns.setMinimumWidth(112)
            auto_turns.setMaximumWidth(132)
            memory_form = QtWidgets.QFormLayout()
            memory_form.setLabelAlignment(QtCore.Qt.AlignLeft)
            memory_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldsStayAtSizeHint)
            memory_form.setFormAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
            memory_form.addRow("Update every (messages)", auto_turns)
            memory_form.addRow("Summary size (characters)", max_chars)
            memory_layout.addLayout(memory_form)

            button_row = QtWidgets.QHBoxLayout()
            button_row.setSpacing(8)
            review = QtWidgets.QPushButton("Review Memory", memory_box)
            review.setObjectName("btn_review_long_term_memory")
            batch_update = QtWidgets.QPushButton("Summarize Recent...", memory_box)
            batch_update.setObjectName("btn_batch_update_long_term_memory")
            forget = QtWidgets.QPushButton("Forget Memory", memory_box)
            forget.setObjectName("btn_forget_long_term_memory")
            button_row.addWidget(review)
            button_row.addWidget(batch_update)
            button_row.addWidget(forget)
            button_row.addStretch(1)
            memory_layout.addLayout(button_row)

            hint = QtWidgets.QLabel(memory_box)
            hint.setObjectName("long_term_memory_hint")
            hint.setWordWrap(True)
            hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
            memory_layout.addWidget(hint)

            insert_index = parent_layout.indexOf(session_box)
            parent_layout.insertWidget(insert_index if insert_index >= 0 else parent_layout.count(), memory_box)
            _ensure_archive_box()

    def _ensure_frontend_spellcheck_widgets(self):
            if (
                self._ui_object("spellcheck_enabled_checkbox") is not None
                and self._ui_object("spellcheck_language_combo") is not None
                and self._ui_object("btn_install_spellcheck_dependency") is not None
                and self._ui_object("spellcheck_dependency_hint") is not None
            ):
                return
            overflow_combo = self._ui_object("chat_overflow_policy_combo")
            if overflow_combo is None:
                return
            parent_widget = overflow_combo.parentWidget()
            root_layout = parent_widget.layout() if parent_widget is not None and hasattr(parent_widget, "layout") else None
            parent_layout = self._find_layout_containing_widget(root_layout, overflow_combo)
            if parent_layout is None or not isinstance(parent_layout, QtWidgets.QFormLayout):
                return
            try:
                from ui.runtime.engine_access import engine_module

                config = getattr(engine_module(), "RUNTIME_CONFIG", {}) or {}
            except Exception:
                config = {}
            selected_language = str((config or {}).get("spellcheck_language", "en_US") or "en_US").strip() or "en_US"

            language_combo = self._ui_object("spellcheck_language_combo")
            if language_combo is None:
                language_combo = QtWidgets.QComboBox(parent_widget)
                language_combo.setObjectName("spellcheck_language_combo")
                try:
                    from ui.runtime.spellcheck import available_languages

                    languages = available_languages()
                except Exception:
                    languages = []
                if selected_language not in languages:
                    languages.insert(0, selected_language)
                for language in languages or [selected_language]:
                    language_combo.addItem(str(language or "en_US"))
                language_combo.setCurrentText(selected_language)
                language_combo.setMinimumWidth(112)
                language_combo.setMaximumWidth(180)
                row = parent_layout.getWidgetPosition(overflow_combo)
                insert_row = row[0] + 1 if row and row[0] >= 0 else parent_layout.rowCount()
                parent_layout.insertRow(insert_row, "Dictionary language", language_combo)

            enabled = self._ui_object("spellcheck_enabled_checkbox")
            if enabled is None:
                enabled = QtWidgets.QCheckBox("Enable spell checking", parent_widget)
                enabled.setObjectName("spellcheck_enabled_checkbox")
                enabled.setChecked(bool((config or {}).get("spellcheck_enabled", True)))
                row = parent_layout.getWidgetPosition(language_combo)
                insert_row = row[0] + 1 if row and row[0] >= 0 else parent_layout.rowCount()
                parent_layout.insertRow(insert_row, "", enabled)

            install_button = self._ui_object("btn_install_spellcheck_dependency")
            dependency_hint = self._ui_object("spellcheck_dependency_hint")
            if install_button is None or dependency_hint is None:
                repair_widget = QtWidgets.QWidget(parent_widget)
                repair_layout = QtWidgets.QHBoxLayout(repair_widget)
                repair_layout.setContentsMargins(0, 0, 0, 0)
                repair_layout.setSpacing(8)
                if install_button is None:
                    install_button = QtWidgets.QPushButton("Install PyEnchant", repair_widget)
                    install_button.setObjectName("btn_install_spellcheck_dependency")
                    install_button.setVisible(False)
                if dependency_hint is None:
                    dependency_hint = QtWidgets.QLabel("", repair_widget)
                    dependency_hint.setObjectName("spellcheck_dependency_hint")
                    dependency_hint.setWordWrap(True)
                    dependency_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
                    dependency_hint.setVisible(False)
                repair_layout.addWidget(install_button)
                repair_layout.addWidget(dependency_hint, 1)
                row = parent_layout.getWidgetPosition(enabled)
                insert_row = row[0] + 1 if row and row[0] >= 0 else parent_layout.rowCount()
                parent_layout.insertRow(insert_row, "", repair_widget)
            try:
                self.backend._refresh_spellcheck_dependency_controls()
            except Exception:
                pass
            try:
                self._apply_frontend_chat_tab_tooltips()
            except Exception:
                pass

    def _find_layout_containing_widget(self, layout, widget):
            if layout is None:
                return None
            for index in range(layout.count()):
                item = layout.itemAt(index)
                if item is None:
                    continue
                if item.widget() is widget:
                    return layout
                nested_layout = item.layout()
                if nested_layout is not None:
                    found = self._find_layout_containing_widget(nested_layout, widget)
                    if found is not None:
                        return found
            return None

    def _redirect_backend_chat_session_runtime_surface(self):
            self._ensure_frontend_spellcheck_widgets()
            self._ensure_frontend_long_term_memory_widgets()
            system_prompt_group = self._ui_object("system_prompt_group")
            system_prompt_text = self._ui_object("system_prompt_text")
            install_prompt_library = getattr(self.backend, "_install_system_prompt_library_controls", None)
            if callable(install_prompt_library) and system_prompt_group is not None and system_prompt_text is not None:
                try:
                    install_prompt_library(system_prompt_group, system_prompt_text)
                except Exception as exc:
                    print(f"[UI Real] System prompt library controls failed: {exc}")
            frontend_widgets = {
                "allow_proactive_checkbox": self._ui_object("allow_proactive_checkbox"),
                "require_first_user_checkbox": self._ui_object("require_first_user_checkbox"),
                "listen_idle_window_spin": self._ui_object("listen_idle_window_spin"),
                "proactive_delay_spin": self._ui_object("proactive_delay_spin"),
                "chat_context_window_spin": self._ui_object("chat_context_window_spin"),
                "stored_chat_history_limit_spin": self._ui_object("stored_chat_history_limit_spin"),
                "chat_visual_batch_size_spin": self._ui_object("chat_visual_batch_size_spin"),
                "chat_overflow_policy_combo": self._ui_object("chat_overflow_policy_combo"),
                "spellcheck_enabled_checkbox": self._ui_object("spellcheck_enabled_checkbox"),
                "spellcheck_language_combo": self._ui_object("spellcheck_language_combo"),
                "btn_install_spellcheck_dependency": self._ui_object("btn_install_spellcheck_dependency"),
                "spellcheck_dependency_hint": self._ui_object("spellcheck_dependency_hint"),
                "long_term_memory_enabled_checkbox": self._ui_object("long_term_memory_enabled_checkbox"),
                "long_term_memory_update_on_save_checkbox": self._ui_object("long_term_memory_update_on_save_checkbox"),
                "long_term_memory_inject_checkbox": self._ui_object("long_term_memory_inject_checkbox"),
                "continuity_memory_auto_turns_spin": self._ui_object("continuity_memory_auto_turns_spin"),
                "long_term_memory_max_chars_spin": self._ui_object("long_term_memory_max_chars_spin"),
                "long_term_memory_hint": self._ui_object("long_term_memory_hint"),
                "btn_review_long_term_memory": self._ui_object("btn_review_long_term_memory"),
                "btn_batch_update_long_term_memory": self._ui_object("btn_batch_update_long_term_memory"),
                "btn_forget_long_term_memory": self._ui_object("btn_forget_long_term_memory"),
                "btn_search_long_term_memory_archive": self._ui_object("btn_search_long_term_memory_archive"),
                "btn_review_long_term_memory_archive": self._ui_object("btn_review_long_term_memory_archive"),
                "btn_export_session_memory": self._ui_object("btn_export_session_memory"),
                "btn_rebuild_long_term_memory_embeddings": self._ui_object("btn_rebuild_long_term_memory_embeddings"),
                "long_term_memory_retrieval_enabled_checkbox": self._ui_object("long_term_memory_retrieval_enabled_checkbox"),
                "long_term_memory_image_review_enabled_checkbox": self._ui_object("long_term_memory_image_review_enabled_checkbox"),
                "long_term_memory_auto_archive_enabled_checkbox": self._ui_object("long_term_memory_auto_archive_enabled_checkbox"),
                "long_term_memory_retrieval_max_items_spin": self._ui_object("long_term_memory_retrieval_max_items_spin"),
                "long_term_memory_recall_text_budget_spin": self._ui_object("long_term_memory_recall_text_budget_spin"),
                "long_term_memory_recall_image_limit_spin": self._ui_object("long_term_memory_recall_image_limit_spin"),
                "long_term_memory_archive_batch_turns_spin": self._ui_object("long_term_memory_archive_batch_turns_spin"),
                "long_term_memory_embedding_enabled_checkbox": self._ui_object("long_term_memory_embedding_enabled_checkbox"),
                "long_term_memory_embedding_model_edit": self._ui_object("long_term_memory_embedding_model_edit"),
                "btn_long_term_memory_embedding_model_refresh": self._ui_object("btn_long_term_memory_embedding_model_refresh"),
                "long_term_memory_embedding_context_length_spin": self._ui_object("long_term_memory_embedding_context_length_spin"),
                "long_term_memory_embedding_base_url_edit": self._ui_object("long_term_memory_embedding_base_url_edit"),
                "long_term_memory_archive_hint": self._ui_object("long_term_memory_archive_hint"),
                "btn_save_chat_session": self._ui_object("btn_save_chat_session"),
                "btn_save_chat_session_as": self._ui_object("btn_save_chat_session_as"),
                "btn_load_chat_session": self._ui_object("btn_load_chat_session"),
                "btn_reset_chat_session": self._ui_object("btn_reset_chat_session"),
                "chat_session_hint": self._ui_object("chat_session_hint"),
                "system_prompt_text": self._ui_object("system_prompt_text"),
                "system_prompt_library_combo": self._ui_object("system_prompt_library_combo"),
                "btn_system_prompt_save_as": self._ui_object("btn_system_prompt_save_as"),
                "btn_system_prompt_add_quick": self._ui_object("btn_system_prompt_add_quick"),
                "btn_system_prompt_remove_quick": self._ui_object("btn_system_prompt_remove_quick"),
                "system_prompt_refine_nsfw_checkbox": self._ui_object("system_prompt_refine_nsfw_checkbox"),
                "system_prompt_library_status_label": self._ui_object("system_prompt_library_status_label"),
            }
            for index in range(1, 7):
                frontend_widgets[f"system_prompt_quick_{index}_checkbox"] = self._ui_object(f"system_prompt_quick_{index}_checkbox")
            if frontend_widgets["chat_session_hint"] is None:
                return
            backend_widgets = {
                name: getattr(self.backend, name, None)
                for name in frontend_widgets
            }

            def _copy_checked(source, target):
                if source is None or target is None or not hasattr(source, "isChecked") or not hasattr(target, "setChecked"):
                    return
                blocker = QtCore.QSignalBlocker(target)
                try:
                    target.setChecked(bool(source.isChecked()))
                except Exception:
                    pass
                finally:
                    del blocker

            def _copy_value(source, target):
                if source is None or target is None or not hasattr(source, "value") or not hasattr(target, "setValue"):
                    return
                blocker = QtCore.QSignalBlocker(target)
                try:
                    target.setValue(source.value())
                except Exception:
                    pass
                finally:
                    del blocker

            def _copy_combo(source, target):
                if source is None or target is None or not hasattr(source, "currentText") or not hasattr(target, "setCurrentText"):
                    return
                blocker = QtCore.QSignalBlocker(target)
                try:
                    target.setCurrentText(str(source.currentText() or ""))
                except Exception:
                    pass
                finally:
                    del blocker

            def _copy_text(source, target):
                if source is None or target is None:
                    return
                blocker = QtCore.QSignalBlocker(target)
                try:
                    if hasattr(source, "currentText"):
                        text = str(source.currentText() or "")
                    elif hasattr(source, "text"):
                        text = str(source.text() or "")
                    else:
                        return
                    if hasattr(target, "setCurrentText"):
                        target.setCurrentText(text)
                    elif hasattr(target, "setText"):
                        target.setText(text)
                except Exception:
                    pass
                finally:
                    del blocker

            # Preserve values restored into the hidden backend before replacing
            # backend widget references with the live Designer controls.
            _copy_checked(backend_widgets.get("allow_proactive_checkbox"), frontend_widgets.get("allow_proactive_checkbox"))
            _copy_checked(backend_widgets.get("require_first_user_checkbox"), frontend_widgets.get("require_first_user_checkbox"))
            _copy_value(backend_widgets.get("listen_idle_window_spin"), frontend_widgets.get("listen_idle_window_spin"))
            _copy_value(backend_widgets.get("proactive_delay_spin"), frontend_widgets.get("proactive_delay_spin"))
            _copy_value(backend_widgets.get("chat_context_window_spin"), frontend_widgets.get("chat_context_window_spin"))
            _copy_value(backend_widgets.get("stored_chat_history_limit_spin"), frontend_widgets.get("stored_chat_history_limit_spin"))
            _copy_value(backend_widgets.get("chat_visual_batch_size_spin"), frontend_widgets.get("chat_visual_batch_size_spin"))
            _copy_combo(backend_widgets.get("chat_overflow_policy_combo"), frontend_widgets.get("chat_overflow_policy_combo"))
            _copy_checked(backend_widgets.get("spellcheck_enabled_checkbox"), frontend_widgets.get("spellcheck_enabled_checkbox"))
            _copy_combo(backend_widgets.get("spellcheck_language_combo"), frontend_widgets.get("spellcheck_language_combo"))
            _copy_checked(backend_widgets.get("long_term_memory_enabled_checkbox"), frontend_widgets.get("long_term_memory_enabled_checkbox"))
            _copy_checked(backend_widgets.get("long_term_memory_update_on_save_checkbox"), frontend_widgets.get("long_term_memory_update_on_save_checkbox"))
            _copy_checked(backend_widgets.get("long_term_memory_inject_checkbox"), frontend_widgets.get("long_term_memory_inject_checkbox"))
            _copy_value(backend_widgets.get("continuity_memory_auto_turns_spin"), frontend_widgets.get("continuity_memory_auto_turns_spin"))
            _copy_value(backend_widgets.get("long_term_memory_max_chars_spin"), frontend_widgets.get("long_term_memory_max_chars_spin"))
            _copy_checked(backend_widgets.get("long_term_memory_retrieval_enabled_checkbox"), frontend_widgets.get("long_term_memory_retrieval_enabled_checkbox"))
            _copy_checked(backend_widgets.get("long_term_memory_image_review_enabled_checkbox"), frontend_widgets.get("long_term_memory_image_review_enabled_checkbox"))
            _copy_checked(backend_widgets.get("long_term_memory_auto_archive_enabled_checkbox"), frontend_widgets.get("long_term_memory_auto_archive_enabled_checkbox"))
            _copy_value(backend_widgets.get("long_term_memory_retrieval_max_items_spin"), frontend_widgets.get("long_term_memory_retrieval_max_items_spin"))
            _copy_value(backend_widgets.get("long_term_memory_recall_text_budget_spin"), frontend_widgets.get("long_term_memory_recall_text_budget_spin"))
            _copy_value(backend_widgets.get("long_term_memory_recall_image_limit_spin"), frontend_widgets.get("long_term_memory_recall_image_limit_spin"))
            _copy_value(backend_widgets.get("long_term_memory_archive_batch_turns_spin"), frontend_widgets.get("long_term_memory_archive_batch_turns_spin"))
            _copy_checked(backend_widgets.get("long_term_memory_embedding_enabled_checkbox"), frontend_widgets.get("long_term_memory_embedding_enabled_checkbox"))
            _copy_text(backend_widgets.get("long_term_memory_embedding_model_edit"), frontend_widgets.get("long_term_memory_embedding_model_edit"))
            _copy_value(backend_widgets.get("long_term_memory_embedding_context_length_spin"), frontend_widgets.get("long_term_memory_embedding_context_length_spin"))
            _copy_text(backend_widgets.get("long_term_memory_embedding_base_url_edit"), frontend_widgets.get("long_term_memory_embedding_base_url_edit"))

            redirected = False
            for attribute_name, widget in frontend_widgets.items():
                if widget is None:
                    continue
                setattr(self.backend, attribute_name, widget)
                redirected = True
            if not redirected:
                return
            try:
                self.backend._refresh_chat_session_hint()
                self.backend._refresh_spellcheck_dependency_controls()
                self.backend._refresh_continuity_memory_hint()
                self.backend._refresh_long_term_memory_archive_hint()
                self.backend._refresh_chat_context_save_controls()
                apply_tooltips = getattr(self.backend, "_apply_chat_tab_tooltips", None)
                if callable(apply_tooltips):
                    apply_tooltips()
                self._apply_frontend_chat_tab_tooltips()
                self._chat_session_runtime_redirected = True
            except Exception as exc:
                print(f"[UI Real] Chat/session runtime surface redirect failed: {exc}")

    def _redirect_backend_pipeline_telemetry_surface(self):
            frontend_box = self._ui_object("pipeline_telemetry_box")
            if frontend_box is None:
                return
            # Keep the Designer-authored telemetry widgets in place. The legacy
            # runtime widget still exists on the hidden backend window, but the
            # main.ui surface owns simple QProgressBars that we mirror directly.
            self._frontend_pipeline_telemetry_box = frontend_box
            self._frontend_pipeline_telemetry_hint = self._ui_object("telemetry_hint")
            self._frontend_render_ready_bar = self._ui_object("render_ready_bar")
            self._frontend_preview_playback_bar = self._ui_object("preview_playback_bar")
            for bar in (self._frontend_render_ready_bar, self._frontend_preview_playback_bar):
                if bar is None:
                    continue
                try:
                    bar.setRange(0, 1000)
                    bar.setValue(0)
                    bar.setTextVisible(True)
                except Exception:
                    pass
            if self._frontend_render_ready_bar is not None and hasattr(self._frontend_render_ready_bar, "setStyleSheet"):
                self._frontend_render_ready_bar.setStyleSheet(
                    "QProgressBar { border: 1px solid #273342; border-radius: 6px; background: #10161f; color: #d8e6f2; text-align: center; }"
                    "QProgressBar::chunk { background: #4fc3f7; border-radius: 5px; }"
                )
            if self._frontend_preview_playback_bar is not None and hasattr(self._frontend_preview_playback_bar, "setStyleSheet"):
                self._frontend_preview_playback_bar.setStyleSheet(
                    "QProgressBar { border: 1px solid #273342; border-radius: 6px; background: #10161f; color: #d8e6f2; text-align: center; }"
                    "QProgressBar::chunk { background: #58d68d; border-radius: 5px; }"
                )

    def _redirect_backend_sensory_runtime_surface(self):
            frontend_tabs = self._ui_object("sensory_feedback_tabs")
            frontend_sources_widget = self._ui_object("sensory_feedback_sources_widget")
            frontend_sources_layout = self._ui_object("sensoryFeedbackSourcesWidgetLayout")
            frontend_interval_spin = self._ui_object("sensory_feedback_interval_spin")
            frontend_pingpong_checkbox = self._ui_object("sensory_pingpong_checkbox")
            frontend_hidden_proactive_checkbox = self._ui_object("sensory_allow_hidden_proactive_checkbox")
            frontend_hidden_visual_checkbox = self._ui_object("sensory_allow_hidden_visual_checkbox")
            frontend_history_spin = self._ui_object("sensory_pingpong_history_spin")
            frontend_prompt_text = self._ui_object("sensory_pingpong_prompt_text")
            frontend_hint_label = self._ui_object("sensory_feedback_hint")
            frontend_feedback_box = self._ui_object("sensory_feedback_box")
            frontend_prompt_box = self._ui_object("sensory_pingpong_prompt_box")
            frontend_prompt_reset = self._ui_object("btn_sensory_pingpong_prompt_reset")
            if frontend_sources_layout is None and frontend_sources_widget is not None and hasattr(frontend_sources_widget, "layout"):
                try:
                    frontend_sources_layout = frontend_sources_widget.layout()
                except Exception:
                    frontend_sources_layout = None
            if frontend_tabs is None or frontend_sources_widget is None or frontend_sources_layout is None:
                return

            def _set_widget_text(object_name, text):
                widget = self._ui_object(object_name)
                if widget is None:
                    return
                try:
                    if isinstance(widget, QtWidgets.QGroupBox):
                        widget.setTitle(str(text or ""))
                    elif hasattr(widget, "setText"):
                        widget.setText(str(text or ""))
                except Exception:
                    pass

            def _set_widget_tooltip(widget, text):
                if widget is None or not hasattr(widget, "setToolTip"):
                    return
                try:
                    widget.setToolTip(str(text or ""))
                except Exception:
                    pass

            _set_widget_text("sensory_feedback_box", "Background Awareness")
            _set_widget_text("sensory_pingpong_prompt_box", "Advanced / Developer Prompt")
            _set_widget_text("sensory_pingpong_checkbox", "Enable background review")
            _set_widget_text("sensory_allow_hidden_proactive_checkbox", "Allow NC to speak about observations")
            _set_widget_text("sensory_allow_hidden_visual_checkbox", "Use observations for Visual Reply images")
            _set_widget_text("sensory_include_label", "Sources to observe")
            _set_widget_text("sensory_refresh_label", "Review every")
            _set_widget_text("sensory_retain_label", "Keep recent observations")
            _set_widget_text("btn_sensory_pingpong_prompt_reset", "Restore recommended prompt")
            _set_widget_tooltip(
                frontend_pingpong_checkbox,
                "Lets NC quietly review selected sources while idle, then keep useful observation notes.",
            )
            _set_widget_tooltip(
                frontend_hidden_proactive_checkbox,
                "Allows a background observation to become a spoken proactive comment when the prompt marks it as worth saying.",
            )
            _set_widget_tooltip(
                frontend_hidden_visual_checkbox,
                "Allows selected sensory context to trigger automatic Visual Reply image generation when the prompt explicitly requests it.",
            )
            _set_widget_tooltip(frontend_interval_spin, "How many seconds may pass before NC reviews selected sources again.")
            _set_widget_tooltip(frontend_history_spin, "How many useful background observations NC may keep.")
            if frontend_prompt_text is not None and hasattr(frontend_prompt_text, "setPlaceholderText"):
                try:
                    frontend_prompt_text.setPlaceholderText("Advanced background review prompt")
                except Exception:
                    pass
            try:
                if frontend_tabs.count() > 0:
                    frontend_tabs.setTabText(0, "Overview")
                if frontend_tabs.count() > 1:
                    frontend_tabs.setTabText(1, "Sources")
            except Exception:
                pass

            def _apply_frontend_sensory_cards():
                if getattr(self, "_sensory_runtime_cards_applied", False):
                    return
                if frontend_feedback_box is None or not hasattr(frontend_feedback_box, "layout"):
                    return
                try:
                    feedback_layout = frontend_feedback_box.layout()
                except Exception:
                    feedback_layout = None
                if feedback_layout is None:
                    return
                while feedback_layout.count():
                    feedback_layout.takeAt(0)
                for object_name in ("sensory_include_label", "sensory_refresh_label", "sensory_retain_label"):
                    label_widget = self._ui_object(object_name)
                    if label_widget is not None and hasattr(label_widget, "setVisible"):
                        label_widget.setVisible(False)
                for widget in (
                    frontend_pingpong_checkbox,
                    frontend_interval_spin,
                    frontend_history_spin,
                    frontend_sources_widget,
                    frontend_hidden_proactive_checkbox,
                    frontend_hidden_visual_checkbox,
                    frontend_hint_label,
                ):
                    if widget is not None and hasattr(widget, "setParent"):
                        widget.setParent(None)

                def make_card(title):
                    card = QtWidgets.QGroupBox(title)
                    card.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Maximum)
                    card_layout = QtWidgets.QVBoxLayout(card)
                    card_layout.setContentsMargins(12, 14, 12, 12)
                    card_layout.setSpacing(8)
                    return card, card_layout

                def spin_row(widget, suffix=""):
                    container = QtWidgets.QWidget()
                    row = QtWidgets.QHBoxLayout(container)
                    row.setContentsMargins(0, 0, 0, 0)
                    row.setSpacing(6)
                    if widget is not None:
                        row.addWidget(widget, 0)
                    if suffix:
                        suffix_label = QtWidgets.QLabel(suffix)
                        suffix_label.setStyleSheet("color: #9fb3c8; font-size: 11px;")
                        row.addWidget(suffix_label, 0)
                    row.addStretch(1)
                    return container

                intro_label = QtWidgets.QLabel(
                    "Choose what NC may quietly observe in the background. Observations are added as context; they are not sent as user messages."
                )
                intro_label.setObjectName("sensory_feedback_intro")
                intro_label.setWordWrap(True)
                intro_label.setStyleSheet("color: #b8c8d9; font-size: 11px;")
                feedback_layout.addWidget(intro_label)

                review_card, review_layout = make_card("Background Review")
                if frontend_pingpong_checkbox is not None:
                    review_layout.addWidget(frontend_pingpong_checkbox)
                review_form = QtWidgets.QFormLayout()
                review_form.setLabelAlignment(QtCore.Qt.AlignLeft)
                review_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldsStayAtSizeHint)
                review_form.setFormAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
                review_form.addRow("Review every", spin_row(frontend_interval_spin, "seconds"))
                review_form.addRow("Keep recent observations", spin_row(frontend_history_spin))
                review_layout.addLayout(review_form)
                feedback_layout.addWidget(review_card)

                sources_card, sources_layout = make_card("Sources to observe")
                sources_hint = QtWidgets.QLabel("Select the background inputs NC may include when building context.")
                sources_hint.setWordWrap(True)
                sources_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
                sources_layout.addWidget(sources_hint)
                sources_layout.addWidget(frontend_sources_widget)
                feedback_layout.addWidget(sources_card)

                actions_card, actions_layout = make_card("Allowed Actions")
                if frontend_hidden_proactive_checkbox is not None:
                    actions_layout.addWidget(frontend_hidden_proactive_checkbox)
                if frontend_hidden_visual_checkbox is not None:
                    actions_layout.addWidget(frontend_hidden_visual_checkbox)
                feedback_layout.addWidget(actions_card)
                if frontend_hint_label is not None:
                    feedback_layout.addWidget(frontend_hint_label)
                self._sensory_runtime_cards_applied = True

            def _apply_frontend_prompt_collapse():
                if getattr(self, "_sensory_prompt_collapse_applied", False):
                    return
                if frontend_prompt_box is None or not isinstance(frontend_prompt_box, QtWidgets.QGroupBox):
                    return

                def set_prompt_expanded(expanded):
                    visible = bool(expanded)
                    for widget in (frontend_prompt_reset, frontend_prompt_text):
                        if widget is not None and hasattr(widget, "setVisible"):
                            widget.setVisible(visible)
                    try:
                        frontend_prompt_box.setMaximumHeight(16777215 if visible else 42)
                    except Exception:
                        pass

                try:
                    frontend_prompt_box.setCheckable(True)
                    frontend_prompt_box.setChecked(False)
                    frontend_prompt_box.toggled.connect(set_prompt_expanded)
                    set_prompt_expanded(False)
                    self._sensory_prompt_collapse_applied = True
                except Exception:
                    pass

            _apply_frontend_sensory_cards()
            _apply_frontend_prompt_collapse()

            backend_interval_spin = getattr(self.backend, "sensory_feedback_interval_spin", None)
            backend_pingpong_checkbox = getattr(self.backend, "sensory_pingpong_checkbox", None)
            backend_hidden_proactive_checkbox = getattr(self.backend, "sensory_allow_hidden_proactive_checkbox", None)
            backend_hidden_visual_checkbox = getattr(self.backend, "sensory_allow_hidden_visual_checkbox", None)
            backend_history_spin = getattr(self.backend, "sensory_pingpong_history_spin", None)
            backend_prompt_text = getattr(self.backend, "sensory_pingpong_prompt_text", None)

            def _copy_checked(source, target):
                if source is None or target is None or not hasattr(source, "isChecked") or not hasattr(target, "setChecked"):
                    return
                blocker = QtCore.QSignalBlocker(target)
                try:
                    target.setChecked(bool(source.isChecked()))
                except Exception:
                    pass
                finally:
                    del blocker

            def _copy_value(source, target):
                if source is None or target is None or not hasattr(source, "value") or not hasattr(target, "setValue"):
                    return
                blocker = QtCore.QSignalBlocker(target)
                try:
                    target.setValue(source.value())
                except Exception:
                    pass
                finally:
                    del blocker

            def _copy_plain_text(source, target):
                if source is None or target is None or not hasattr(source, "toPlainText") or not hasattr(target, "setPlainText"):
                    return
                blocker = QtCore.QSignalBlocker(target)
                try:
                    target.setPlainText(str(source.toPlainText() or ""))
                except Exception:
                    pass
                finally:
                    del blocker

            # Preserve values restored into the hidden backend before replacing
            # backend widget references with the live Designer controls.
            _copy_value(backend_interval_spin, frontend_interval_spin)
            _copy_checked(backend_pingpong_checkbox, frontend_pingpong_checkbox)
            _copy_checked(backend_hidden_proactive_checkbox, frontend_hidden_proactive_checkbox)
            _copy_checked(backend_hidden_visual_checkbox, frontend_hidden_visual_checkbox)
            _copy_value(backend_history_spin, frontend_history_spin)
            _copy_plain_text(backend_prompt_text, frontend_prompt_text)

            self.backend.sensory_feedback_tabs = frontend_tabs
            self.backend.sensory_feedback_sources_widget = frontend_sources_widget
            self.backend.sensory_feedback_sources_layout = frontend_sources_layout
            if frontend_interval_spin is not None:
                self.backend.sensory_feedback_interval_spin = frontend_interval_spin
            if frontend_pingpong_checkbox is not None:
                self.backend.sensory_pingpong_checkbox = frontend_pingpong_checkbox
            if frontend_hidden_proactive_checkbox is not None:
                self.backend.sensory_allow_hidden_proactive_checkbox = frontend_hidden_proactive_checkbox
            if frontend_hidden_visual_checkbox is not None:
                self.backend.sensory_allow_hidden_visual_checkbox = frontend_hidden_visual_checkbox
            if frontend_history_spin is not None:
                self.backend.sensory_pingpong_history_spin = frontend_history_spin
            if frontend_prompt_text is not None:
                self.backend.sensory_pingpong_prompt_text = frontend_prompt_text
            if frontend_hint_label is not None:
                self.backend.sensory_feedback_hint = frontend_hint_label
            try:
                self.backend.refresh_sensory_feedback_source_options()
                self.backend._refresh_sensory_feedback_hint()
                self._sensory_runtime_redirected = True
            except Exception as exc:
                print(f"[UI Real] Sensory runtime surface redirect failed: {exc}")

    def _clear_layout(self, layout):
            if layout is None:
                return
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                child_layout = item.layout()
                if widget is not None:
                    try:
                        widget.setParent(None)
                        widget.deleteLater()
                    except Exception:
                        pass
                elif child_layout is not None:
                    self._clear_layout(child_layout)

    def _redirect_backend_addons_management_surface(self):
            frontend_tab = self._ui_object("addons_tab")
            if frontend_tab is None:
                return
            layout = frontend_tab.layout()
            if layout is None:
                layout = QtWidgets.QVBoxLayout(frontend_tab)
                layout.setContentsMargins(12, 12, 12, 12)
                layout.setSpacing(10)
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                child_layout = item.layout()
                if widget is not None:
                    try:
                        widget.setParent(None)
                        widget.deleteLater()
                    except Exception:
                        pass
                elif child_layout is not None:
                    self._clear_layout(child_layout)

            intro = QtWidgets.QLabel(
                "Manage addon loading here. Category toggles act like parent switches: if a parent category is off, all child addons under it are effectively off too. Changes here are global and apply on next launch."
            )
            intro.setObjectName("addons_intro_label")
            intro.setWordWrap(True)
            intro.setStyleSheet("color: #9fb3c8;")
            layout.addWidget(intro)

            controls = QtWidgets.QHBoxLayout()
            refresh_button = QtWidgets.QPushButton("Refresh")
            refresh_button.setObjectName("btn_addons_refresh")
            restart_badge = QtWidgets.QLabel("Restart required")
            restart_badge.setObjectName("addons_restart_badge")
            restart_badge.setVisible(False)
            restart_badge.setStyleSheet(
                "color: #ffb4b4; background: rgba(216, 74, 74, 0.16); border: 1px solid #d84a4a; border-radius: 10px; padding: 4px 10px; font-weight: 700;"
            )
            controls.addWidget(refresh_button)
            controls.addWidget(restart_badge)
            controls.addStretch(1)
            layout.addLayout(controls)

            note = QtWidgets.QLabel(
                "These toggles are saved in the session, not in presets. Already loaded addons keep running until you restart Neural Companion."
            )
            note.setObjectName("addons_restart_note")
            note.setWordWrap(True)
            note.setStyleSheet("color: #8ea3b8; font-size: 11px;")
            layout.addWidget(note)

            scroll = QtWidgets.QScrollArea()
            scroll.setObjectName("addons_management_scroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
            layout.addWidget(scroll, 1)

            content = QtWidgets.QWidget()
            content.setObjectName("addons_management_content")
            scroll.setWidget(content)
            management_layout = QtWidgets.QVBoxLayout(content)
            management_layout.setContentsMargins(0, 0, 0, 0)
            management_layout.setSpacing(10)

            self.backend.btn_addons_refresh = refresh_button
            self.backend.addons_restart_badge = restart_badge
            self.backend.addons_restart_note = note
            self.backend.addons_management_layout = management_layout
            refresh_button.clicked.connect(self.backend._refresh_addons_management_ui)
            try:
                self.backend._refresh_addons_management_ui()
            except Exception as exc:
                print(f"[UI Real] Addons management surface redirect failed: {exc}")

    def _redirect_backend_musetalk_preview_runtime_surface(self):
            self._invoke_surface_avatar_capability(
                "musetalk",
                "real_ui.redirect_preview_runtime_surface",
            )

    def _redirect_backend_visual_reply_runtime_surface(self):
            self._invoke_surface_addon_capability(
                self._visual_reply_addon_id_for_surface(),
                "real_ui.redirect_runtime_surface",
            )

    def _redirect_backend_visual_reply_settings_surface(self):
            runtime_box = self._ui_object("visual_reply_runtime_box")
            host = self._ui_object("visual_reply_runtime_host")
            if runtime_box is None or host is None:
                return False
            try:
                self.backend.visual_reply_runtime_box = runtime_box
                self.backend.visual_reply_runtime_host = host
            except Exception:
                pass

            addon_id = self._visual_reply_addon_id_for_surface()
            if not addon_id or not self._addon_surface_runtime_available(addon_id):
                try:
                    runtime_box.hide()
                    self._set_runtime_group_header_visible(runtime_box, False)
                except Exception:
                    pass
                return False

            manager = getattr(self.backend, "_addon_manager", None)
            if manager is None:
                return False
            contribution = None
            for candidate in list(manager.get_tab_contributions(area="visual_reply_runtime") or []):
                metadata = dict(getattr(candidate, "metadata", {}) or {})
                if metadata.get("runtime_role") == "visual_reply" or str(getattr(candidate, "id", "") or "") == "visuals_host":
                    contribution = candidate
                    break
            if contribution is None:
                try:
                    runtime_box.hide()
                    self._set_runtime_group_header_visible(runtime_box, False)
                except Exception:
                    pass
                return False

            layout = host.layout()
            if layout is None:
                layout = QtWidgets.QVBoxLayout(host)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(8)
            try:
                placeholder = self._ui_object("visual_reply_runtime_placeholder")
                if placeholder is not None:
                    placeholder.setParent(None)
                    placeholder.deleteLater()
                widget = contribution.factory(None)
                if widget is None:
                    raise RuntimeError("Visual Reply settings contribution returned no widget.")
                widget.setProperty("addon_id", getattr(contribution, "addon_id", ""))
                widget.setProperty("addon_tab_id", getattr(contribution, "id", ""))
                widget.setProperty("addon_area", "visual_reply_runtime")
                layout.addWidget(widget)
                self.backend._mounted_host_settings_addon_tab_ids.add(contribution.id)
                runtime_box.show()
                self._set_runtime_group_header_visible(runtime_box, True)
                try:
                    self.backend._refresh_visual_reply_hint()
                except Exception:
                    pass
                return True
            except Exception as exc:
                print(f"[UI Real] Visual Reply settings surface redirect failed: {exc}")
                try:
                    runtime_box.hide()
                    self._set_runtime_group_header_visible(runtime_box, False)
                except Exception:
                    pass
                return False
