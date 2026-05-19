from PySide6 import QtCore, QtWidgets


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
                self._provider_runtime_redirected = True
            except Exception as exc:
                print(f"[UI Real] Provider runtime surface redirect failed: {exc}")

    def _redirect_backend_chat_session_runtime_surface(self):
            frontend_widgets = {
                "allow_proactive_checkbox": self._ui_object("allow_proactive_checkbox"),
                "require_first_user_checkbox": self._ui_object("require_first_user_checkbox"),
                "listen_idle_window_spin": self._ui_object("listen_idle_window_spin"),
                "proactive_delay_spin": self._ui_object("proactive_delay_spin"),
                "chat_context_window_spin": self._ui_object("chat_context_window_spin"),
                "stored_chat_history_limit_spin": self._ui_object("stored_chat_history_limit_spin"),
                "chat_overflow_policy_combo": self._ui_object("chat_overflow_policy_combo"),
                "chat_session_hint": self._ui_object("chat_session_hint"),
                "system_prompt_text": self._ui_object("system_prompt_text"),
            }
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

            # Preserve values restored into the hidden backend before replacing
            # backend widget references with the live Designer controls.
            _copy_checked(backend_widgets.get("allow_proactive_checkbox"), frontend_widgets.get("allow_proactive_checkbox"))
            _copy_checked(backend_widgets.get("require_first_user_checkbox"), frontend_widgets.get("require_first_user_checkbox"))
            _copy_value(backend_widgets.get("listen_idle_window_spin"), frontend_widgets.get("listen_idle_window_spin"))
            _copy_value(backend_widgets.get("proactive_delay_spin"), frontend_widgets.get("proactive_delay_spin"))
            _copy_value(backend_widgets.get("chat_context_window_spin"), frontend_widgets.get("chat_context_window_spin"))
            _copy_value(backend_widgets.get("stored_chat_history_limit_spin"), frontend_widgets.get("stored_chat_history_limit_spin"))
            _copy_combo(backend_widgets.get("chat_overflow_policy_combo"), frontend_widgets.get("chat_overflow_policy_combo"))

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
            if frontend_sources_layout is None and frontend_sources_widget is not None and hasattr(frontend_sources_widget, "layout"):
                try:
                    frontend_sources_layout = frontend_sources_widget.layout()
                except Exception:
                    frontend_sources_layout = None
            if frontend_tabs is None or frontend_sources_widget is None or frontend_sources_layout is None:
                return
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
