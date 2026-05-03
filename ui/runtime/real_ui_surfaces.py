import importlib.util
from pathlib import Path

from PySide6 import QtCore, QtWidgets


def configure_real_ui_surfaces_dependencies(namespace):
    """Inject qt_app-owned globals used by the extracted real-UI surface mixin."""
    globals().update(dict(namespace or {}))


class MainUiRealSurfacesMixin:
    """Runtime surface redirection helpers for mounting hidden-backend widgets into main.ui."""

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

    def _build_ui_real_visual_reply_panel(self):
            panel_class = QtVisualReplyPanel
            capability_bridge = AddonCapabilityBridgeService(lambda: getattr(self.backend, "_addon_manager", None))
            controller_path = Path(__file__).resolve().parent / "addons" / "visual_reply" / "controller.py"
            try:
                spec = importlib.util.spec_from_file_location("nc_ui_real_visual_reply_controller", controller_path)
                if spec is None or spec.loader is None:
                    raise RuntimeError(f"Could not load Visual Reply controller from {controller_path}")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                loaded_class = getattr(module, "AddonVisualReplyPanel", None)
                if loaded_class is not None:
                    panel_class = loaded_class
            except Exception as exc:
                print(f"[UI Real] Visual Reply panel addon import failed, using fallback panel: {exc}")
            try:
                panel = panel_class(capability_bridge=capability_bridge)
            except TypeError:
                panel = panel_class()
            panel.setObjectName("visual_reply_panel")
            object_map = (
                ("status_label", "visual_reply_status"),
                ("storage_label", "visual_reply_storage_label"),
                ("prev_button", "visual_reply_previous_button"),
                ("load_button", "visual_reply_load_button"),
                ("next_button", "visual_reply_next_button"),
                ("load_story_button", "visual_reply_load_current_story_button"),
                ("use_style_button", "visual_reply_use_current_style_button"),
                ("caption_button", "visual_reply_caption_button"),
                ("delete_button", "visual_reply_delete_button"),
                ("clear_button", "visual_reply_clear_button"),
                ("delete_all_button", "visual_reply_delete_all_button"),
                ("image_label", "visual_reply_image_label"),
                ("caption_label", "visual_reply_caption_label"),
            )
            for attribute_name, object_name in object_map:
                widget = getattr(panel, attribute_name, None)
                if widget is not None and hasattr(widget, "setObjectName"):
                    widget.setObjectName(object_name)
            return panel

    def _redirect_backend_musetalk_preview_runtime_surface(self):
            frontend_dock = self._ui_object("PreviewDock")
            if frontend_dock is None or not hasattr(frontend_dock, "setWidget"):
                return
            panel = getattr(self.backend, "embedded_musetalk_preview", None)
            if panel is None:
                return
            old_widget = None
            try:
                old_widget = frontend_dock.widget()
            except Exception:
                old_widget = None
            container = QtWidgets.QWidget()
            container.setObjectName("preview_dock_content")
            layout = QtWidgets.QVBoxLayout(container)
            layout.setObjectName("previewDockLayout")
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            try:
                old_parent = panel.parentWidget()
                if old_parent is not None and old_parent.layout() is not None:
                    old_parent.layout().removeWidget(panel)
            except Exception:
                pass
            panel.setParent(None)
            layout.addWidget(panel)
            try:
                focus_signal = getattr(panel, "focusModeRequested", None)
                if focus_signal is not None:
                    focus_signal.disconnect()
                    focus_signal.connect(self._toggle_frontend_musetalk_avatar_focus)
            except Exception:
                pass
            try:
                show_interface_signal = getattr(panel, "showInterfaceRequested", None)
                if show_interface_signal is not None:
                    show_interface_signal.disconnect()
                    show_interface_signal.connect(self._show_frontend_main_interface_from_musetalk_focus)
            except Exception:
                pass
            stage_window = None
            try:
                stage_window = self.backend._ensure_musetalk_stage_window()
            except Exception:
                stage_window = None
            if stage_window is not None:
                try:
                    stage_window.closeRequested.connect(self._show_frontend_main_interface_from_musetalk_focus)
                except Exception:
                    pass
            try:
                frontend_dock.setWidget(container)
                self.backend.preview_dock = frontend_dock
                self.backend.preview_dock_container = container
                self.backend.preview_dock_layout = layout
                self.backend.embedded_musetalk_preview = panel
                self._frontend_musetalk_preview_panel = panel
                setattr(self.window, "show_musetalk_preview", self._show_frontend_musetalk_preview)
                setattr(self.window, "toggle_musetalk_avatar_focus", self._toggle_frontend_musetalk_avatar_focus)
                setattr(self.window, "show_main_interface_from_musetalk_focus", self._show_frontend_main_interface_from_musetalk_focus)
                setattr(self.window, "stop_musetalk_preview", self._stop_frontend_musetalk_preview)
                self._musetalk_preview_runtime_redirected = True
            except Exception as exc:
                print(f"[UI Real] MuseTalk preview runtime surface redirect failed: {exc}")
                return
            if old_widget is not None and old_widget is not container:
                try:
                    old_widget.deleteLater()
                except Exception:
                    pass

    def _redirect_backend_visual_reply_runtime_surface(self):
            frontend_dock = self._ui_object("VisualReplyDock")
            if frontend_dock is None or not hasattr(frontend_dock, "setWidget"):
                return
            addon_enabled = True
            checker = getattr(self, "_addon_effectively_enabled", None)
            if callable(checker):
                addon_enabled = bool(checker("nc.visual_reply"))
            backend_dock = getattr(self.backend, "visual_reply_dock", None)
            if backend_dock is not None and backend_dock is not frontend_dock:
                # The hidden legacy backend restores its own Visual Reply dock
                # before the real-UI surface redirect runs. If that saved dock
                # was visible/floating, Qt keeps it alive as a separate top-level
                # window. Hide it before replacing backend.visual_reply_dock with
                # the real main.ui dock so only one Visual Reply surface remains.
                try:
                    backend_dock.hide()
                except Exception:
                    pass
            if not addon_enabled:
                enforcer = getattr(self, "_enforce_disabled_frontend_workspace_docks", None)
                if callable(enforcer):
                    enforcer()
                else:
                    try:
                        frontend_dock.hide()
                    except Exception:
                        pass
                setattr(self.window, "show_visual_reply_dock", lambda *args, **kwargs: None)
                self._visual_reply_runtime_redirected = False
                return
            old_widget = None
            try:
                old_widget = frontend_dock.widget()
            except Exception:
                old_widget = None
            if old_widget is not None and hasattr(old_widget, "setObjectName"):
                try:
                    old_widget.setObjectName("visual_reply_panel_legacy")
                except Exception:
                    pass
                for legacy_name in (
                    "visual_reply_status",
                    "visual_reply_storage_label",
                    "visual_reply_previous_button",
                    "visual_reply_load_button",
                    "visual_reply_next_button",
                    "visual_reply_load_current_story_button",
                    "visual_reply_use_current_style_button",
                    "visual_reply_caption_button",
                    "visual_reply_delete_button",
                    "visual_reply_clear_button",
                    "visual_reply_delete_all_button",
                    "visual_reply_frame",
                    "visual_reply_image_label",
                ):
                    try:
                        child = old_widget.findChild(QtCore.QObject, legacy_name)
                    except Exception:
                        child = None
                    if child is not None and hasattr(child, "setObjectName"):
                        try:
                            child.setObjectName(f"{legacy_name}_legacy")
                        except Exception:
                            pass
            panel = self._build_ui_real_visual_reply_panel()
            try:
                load_signal = getattr(panel, "loadRequested", None)
                if load_signal is not None:
                    load_signal.connect(self.backend.prompt_visual_reply_image)
            except Exception:
                pass
            try:
                caption_signal = getattr(panel, "captionRequested", None)
                if caption_signal is not None:
                    caption_signal.connect(self.backend.prompt_visual_reply_caption)
            except Exception:
                pass
            try:
                clear_signal = getattr(panel, "clearRequested", None)
                if clear_signal is not None:
                    clear_signal.connect(lambda: self.backend.clear_visual_reply(auto_show=False))
            except Exception:
                pass
            try:
                frontend_dock.setWidget(panel)
                self.backend.visual_reply_dock = frontend_dock
                self.backend.visual_reply_panel = panel
                self._frontend_visual_reply_panel = panel
                setattr(self.window, "show_visual_reply_dock", self._show_frontend_visual_reply_dock)
                self._visual_reply_runtime_redirected = True
            except Exception as exc:
                print(f"[UI Real] Visual Reply runtime surface redirect failed: {exc}")
                return
            if old_widget is not None and old_widget is not panel:
                try:
                    old_widget.deleteLater()
                except Exception:
                    pass
