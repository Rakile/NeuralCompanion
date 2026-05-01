import base64
import json

from PySide6 import QtCore, QtWidgets


def configure_real_ui_layout_dependencies(namespace):
    """Inject qt_app-owned globals used by the extracted real-UI layout mixin."""
    globals().update(dict(namespace or {}))


class MainUiRealLayoutMixin:
    """Layout, docking, and collapsible-card helpers for the runtime-backed main.ui bridge."""

    def _fix_system_shaping_scroll_content_size(self):
            scroll = self._ui("system_shaping_scroll", QtWidgets.QScrollArea)
            content = self._ui("system_shaping_content", QtWidgets.QWidget)
            tabs = self._ui("host_settings_tabs", QtWidgets.QTabWidget)
            host_tab = self._ui("host_settings_host_tab", QtWidgets.QWidget)

            chat_box = self._ui("chat_runtime_box", QtWidgets.QGroupBox)
            tts_box = self._ui("tts_runtime_box", QtWidgets.QGroupBox)
            perf_box = self._ui("performance_guidance_box", QtWidgets.QGroupBox)

            if scroll is not None:
                scroll.setWidgetResizable(True)
                scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
                scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)

            for w in (content, tabs, host_tab, chat_box, tts_box, perf_box):
                if w is None:
                    continue

                w.setMinimumHeight(0)
                w.setMaximumHeight(16777215)

                policy = w.sizePolicy()
                policy.setHorizontalPolicy(QtWidgets.QSizePolicy.Expanding)
                policy.setVerticalPolicy(QtWidgets.QSizePolicy.Preferred)
                w.setSizePolicy(policy)

            for w in (content, host_tab):
                if w is None or w.layout() is None:
                    continue

                layout = w.layout()
                layout.setSizeConstraint(QtWidgets.QLayout.SetMinAndMaxSize)
                layout.setAlignment(QtCore.Qt.AlignTop)
                layout.invalidate()
                layout.activate()

            if host_tab is not None:
                host_tab.adjustSize()
                host_tab.updateGeometry()

            if tabs is not None:
                page = tabs.currentWidget()
                if page is not None:
                    if page.layout() is not None:
                        page.layout().invalidate()
                        page.layout().activate()

                    page.adjustSize()
                    page.updateGeometry()

                    wanted = (
                            page.sizeHint().height()
                            + tabs.tabBar().sizeHint().height()
                            + 24
                    )

                    tabs.setMinimumHeight(wanted)
                    tabs.setMaximumHeight(16777215)

                tabs.adjustSize()
                tabs.updateGeometry()

            if content is not None:
                content.adjustSize()
                content.updateGeometry()

            if scroll is not None:
                scroll.updateGeometry()
                scroll.viewport().update()

    def _fix_sensory_feedback_initial_alignment(self):
            tabs = self._ui("sensory_feedback_tabs", QtWidgets.QTabWidget)
            if tabs is None:
                return
            parent = tabs.parentWidget()
            layout = parent.layout() if parent is not None and hasattr(parent, "layout") else None
            if layout is not None:
                try:
                    # Vertical-only alignment keeps startup from centering the Core tab,
                    # while still letting the tab widget consume the full row width.
                    layout.setAlignment(tabs, QtCore.Qt.AlignTop)
                except Exception:
                    pass
            available_width = 0
            if parent is not None:
                try:
                    margins = layout.contentsMargins() if layout is not None else QtCore.QMargins()
                    available_width = max(0, parent.width() - margins.left() - margins.right())
                except Exception:
                    available_width = 0
            for widget in (tabs, tabs.currentWidget()):
                if widget is None:
                    continue
                try:
                    policy = widget.sizePolicy()
                    policy.setHorizontalPolicy(QtWidgets.QSizePolicy.Expanding)
                    policy.setVerticalPolicy(QtWidgets.QSizePolicy.Preferred)
                    widget.setSizePolicy(policy)
                    if available_width > 0:
                        widget.setMinimumWidth(available_width)
                    widget.setMinimumHeight(0)
                    widget.setMaximumWidth(16777215)
                    widget.adjustSize()
                    widget.updateGeometry()
                except Exception:
                    pass
            try:
                self.backend._sync_tab_widget_height(tabs)
            except Exception:
                pass

    def _load_frontend_session_payload(self):
            if not SESSION_PATH.exists():
                return {}
            try:
                payload = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
                return payload if isinstance(payload, dict) else {}
            except Exception:
                return {}

    def _write_frontend_session_payload(self, payload):
            try:
                SESSION_PATH.write_text(json.dumps(payload or {}, indent=4), encoding="utf-8")
            except Exception as exc:
                print(f"[UI Real] Failed to save frontend layout: {exc}")

    def _frontend_dock_layout_snapshot(self):
            docks = {}
            for dock in self.window.findChildren(QtWidgets.QDockWidget):
                object_name = str(dock.objectName() or "").strip()
                if not object_name:
                    continue
                geometry = dock.geometry()
                floating_geometry = dock.frameGeometry()
                docks[object_name] = {
                    "visible": bool(dock.isVisible()),
                    "floating": bool(dock.isFloating()),
                    "geometry": [geometry.x(), geometry.y(), geometry.width(), geometry.height()],
                    "floating_geometry": [
                        floating_geometry.x(),
                        floating_geometry.y(),
                        floating_geometry.width(),
                        floating_geometry.height(),
                    ],
                }
            return docks

    def _save_frontend_layout_state(self):
            if bool(getattr(self, "_session_read_only", False)):
                return
            if bool(getattr(self, "_restoring_frontend_layout", False)):
                return
            if self.window is None:
                return
            if self._frontend_dock_drag_active():
                self._schedule_frontend_layout_save(delay_ms=1200)
                return
            try:
                geometry = self.window.geometry()
                layout_state = {
                    "version": 1,
                    "ui_path": str(self.ui_path),
                    "geometry": [geometry.x(), geometry.y(), geometry.width(), geometry.height()],
                    "window_geometry": base64.b64encode(self.window.saveGeometry().data()).decode("ascii"),
                    "window_state": base64.b64encode(self.window.saveState().data()).decode("ascii"),
                    "docks": self._frontend_dock_layout_snapshot(),
                }
                payload = self._load_frontend_session_payload()
                payload[self.FRONTEND_LAYOUT_SESSION_KEY] = layout_state
                self._write_frontend_session_payload(payload)
            except Exception as exc:
                print(f"[UI Real] Failed to capture frontend layout: {exc}")

    def _restore_frontend_layout_state(self):
            payload = self._load_frontend_session_payload()
            layout_state = payload.get(self.FRONTEND_LAYOUT_SESSION_KEY)
            if not isinstance(layout_state, dict):
                return
            self._pending_frontend_layout_state = dict(layout_state)
            self._restoring_frontend_layout = True
            try:
                window_geometry = str(layout_state.get("window_geometry") or "").strip()
                if window_geometry:
                    try:
                        self.window.restoreGeometry(QtCore.QByteArray.fromBase64(window_geometry.encode("ascii")))
                    except Exception:
                        pass
                else:
                    geometry = layout_state.get("geometry")
                    if isinstance(geometry, list) and len(geometry) == 4:
                        try:
                            self.window.setGeometry(*[int(item) for item in geometry])
                        except Exception:
                            pass
                window_state = str(layout_state.get("window_state") or "").strip()
                if window_state:
                    try:
                        self.window.restoreState(QtCore.QByteArray.fromBase64(window_state.encode("ascii")))
                    except Exception:
                        pass
                docks = layout_state.get("docks")
                if isinstance(docks, dict):
                    for object_name, dock_state in docks.items():
                        dock = self._ui_object(str(object_name))
                        if dock is None or not isinstance(dock, QtWidgets.QDockWidget) or not isinstance(dock_state, dict):
                            continue
                        try:
                            dock.setFloating(bool(dock_state.get("floating", False)))
                            if dock.isFloating():
                                geometry = dock_state.get("floating_geometry") or dock_state.get("geometry")
                                if isinstance(geometry, list) and len(geometry) == 4:
                                    dock.setGeometry(*[int(item) for item in geometry])
                            dock.setVisible(bool(dock_state.get("visible", True)))
                        except Exception:
                            continue
                QtCore.QTimer.singleShot(0, self._ensure_frontend_window_on_screen)
                QtCore.QTimer.singleShot(100, self._ensure_frontend_window_on_screen)
                QtCore.QTimer.singleShot(0, self._restore_frontend_dock_geometry_pass)
                QtCore.QTimer.singleShot(250, self._restore_frontend_dock_geometry_pass)
                QtCore.QTimer.singleShot(900, self._restore_frontend_dock_geometry_pass)
            finally:
                self._restoring_frontend_layout = False

    def _saved_frontend_dock_states(self):
            layout_state = getattr(self, "_pending_frontend_layout_state", None)
            if not isinstance(layout_state, dict):
                payload = self._load_frontend_session_payload()
                layout_state = payload.get(self.FRONTEND_LAYOUT_SESSION_KEY)
            if not isinstance(layout_state, dict):
                return {}
            docks = layout_state.get("docks")
            return docks if isinstance(docks, dict) else {}

    def _restore_frontend_dock_geometry_pass(self):
            docks = self._saved_frontend_dock_states()
            if not docks:
                return
            self._restoring_frontend_layout = True
            try:
                visible_docked = []
                for object_name, dock_state in docks.items():
                    dock = self._ui_object(str(object_name))
                    if dock is None or not isinstance(dock, QtWidgets.QDockWidget) or not isinstance(dock_state, dict):
                        continue
                    try:
                        visible = bool(dock_state.get("visible", True))
                        floating = bool(dock_state.get("floating", False))
                        dock.setVisible(visible)
                        dock.setFloating(floating)
                        if floating:
                            geometry = dock_state.get("floating_geometry") or dock_state.get("geometry")
                            if isinstance(geometry, list) and len(geometry) == 4:
                                dock.setGeometry(*[int(item) for item in geometry])
                        elif visible:
                            visible_docked.append((dock, dock_state))
                    except Exception:
                        continue
                self._resize_frontend_docks_from_saved_geometry(visible_docked)
            finally:
                self._restoring_frontend_layout = False

    def _resize_frontend_docks_from_saved_geometry(self, dock_entries):
            if not dock_entries:
                return
            horizontal = []
            vertical = []
            for dock, dock_state in dock_entries:
                geometry = dock_state.get("geometry")
                if not isinstance(geometry, list) or len(geometry) != 4:
                    continue
                try:
                    width = max(1, int(geometry[2]))
                    height = max(1, int(geometry[3]))
                except Exception:
                    continue
                horizontal.append((dock, width))
                vertical.append((dock, height))
            if len(horizontal) >= 2:
                try:
                    self.window.resizeDocks(
                        [dock for dock, _width in horizontal],
                        [width for _dock, width in horizontal],
                        QtCore.Qt.Horizontal,
                    )
                except Exception:
                    pass
            if len(vertical) >= 2:
                try:
                    self.window.resizeDocks(
                        [dock for dock, _height in vertical],
                        [height for _dock, height in vertical],
                        QtCore.Qt.Vertical,
                    )
                except Exception:
                    pass

    def _ensure_frontend_window_on_screen(self):
            if self.window is None:
                return
            screen = self.window.screen() or QtWidgets.QApplication.primaryScreen()
            if screen is None:
                return
            available = screen.availableGeometry()
            frame = self.window.frameGeometry()
            client = self.window.geometry()
            width = min(max(client.width(), 320), max(available.width(), 320))
            height = min(max(client.height(), 240), max(available.height(), 240))
            x = frame.x()
            y = frame.y()
            if x < available.left():
                x = available.left()
            if y < available.top():
                y = available.top()
            if x + width > available.right() + 1:
                x = max(available.left(), available.right() - width + 1)
            if y + height > available.bottom() + 1:
                y = max(available.top(), available.bottom() - height + 1)
            self.window.setGeometry(x, y, width, height)
            self.window.move(x, y)

    def _frontend_dock_drag_active(self):
            try:
                buttons = QtWidgets.QApplication.mouseButtons()
                return bool(buttons & (QtCore.Qt.LeftButton | QtCore.Qt.RightButton | QtCore.Qt.MiddleButton))
            except Exception:
                return False

    def _schedule_frontend_layout_save(self, delay_ms=None):
            if (
                bool(getattr(self, "_session_read_only", False))
                or bool(getattr(self, "_restoring_frontend_layout", False))
                or bool(getattr(self, "_closing", False))
            ):
                return
            timer = getattr(self, "_frontend_layout_save_timer", None)
            if timer is not None:
                if delay_ms is not None:
                    timer.setInterval(max(650, int(delay_ms)))
                elif self._frontend_dock_drag_active():
                    timer.setInterval(1200)
                else:
                    timer.setInterval(650)
                timer.start()

    def _bind_frontend_layout_persistence_hooks(self):
            for dock in self.window.findChildren(QtWidgets.QDockWidget):
                try:
                    dock.installEventFilter(self)
                except Exception:
                    pass
                for signal_name in ("topLevelChanged", "visibilityChanged", "dockLocationChanged"):
                    signal = getattr(dock, signal_name, None)
                    if signal is None:
                        continue
                    try:
                        signal.connect(lambda *args: self._schedule_frontend_layout_save(delay_ms=1200))
                    except Exception:
                        pass
            self._bind_frontend_workspace_menu_actions()

    def _bind_frontend_workspace_menu_actions(self):
            action_map = {
                "actionShowAllPanels": self.show_all_frontend_workspace_panels,
                "actionResetWorkspaceLayout": self.reset_frontend_workspace_layout,
            }
            for object_name, handler in action_map.items():
                action = self.window.findChild(QtCore.QObject, object_name)
                if action is None or not hasattr(action, "triggered"):
                    continue
                try:
                    action.triggered.connect(handler)
                except Exception:
                    pass

    def _frontend_workspace_docks(self):
            names = (
                "SystemShapingDock",
                "WorkspaceTabsDock",
                "OperationalViewDock",
                "MuseTalkPreviewDock",
                "PreviewDock",
                "VisualReplyDock",
            )
            docks = []
            for object_name in names:
                dock = self._ui_object(object_name)
                if dock is not None and isinstance(dock, QtWidgets.QDockWidget):
                    docks.append(dock)
            return docks

    def show_all_frontend_workspace_panels(self):
            for dock in self._frontend_workspace_docks():
                try:
                    dock.show()
                    dock.raise_()
                except Exception:
                    pass
            self._apply_frontend_workspace_view_constraints()
            self._schedule_frontend_layout_save()
            print("[UI Real] Workspace panels shown.")

    def reset_frontend_workspace_layout(self):
            self._restoring_frontend_layout = True
            try:
                system_dock = self._ui_object("SystemShapingDock")
                workspace_dock = self._ui_object("WorkspaceTabsDock")
                operational_dock = self._ui_object("OperationalViewDock")
                preview_dock = self._ui_object("MuseTalkPreviewDock") or self._ui_object("PreviewDock")
                visual_dock = self._ui_object("VisualReplyDock")

                left_docks = [dock for dock in (system_dock, workspace_dock) if isinstance(dock, QtWidgets.QDockWidget)]
                right_docks = [dock for dock in (operational_dock, preview_dock, visual_dock) if isinstance(dock, QtWidgets.QDockWidget)]

                for dock in left_docks:
                    dock.setFloating(False)
                    self.window.addDockWidget(QtCore.Qt.LeftDockWidgetArea, dock)
                    dock.show()
                for dock in right_docks:
                    dock.setFloating(False)
                    self.window.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
                    dock.show()

                if len(left_docks) >= 2:
                    self.window.tabifyDockWidget(left_docks[0], left_docks[1])
                    left_docks[0].raise_()
                if len(right_docks) >= 2:
                    base = right_docks[0]
                    for dock in right_docks[1:]:
                        self.window.tabifyDockWidget(base, dock)
                    base.raise_()
            finally:
                self._restoring_frontend_layout = False

            self._apply_frontend_workspace_view_constraints()
            self._save_frontend_layout_state()
            print("[UI Real] Workspace layout reset.")

    def _bind_frontend_workspace_constraint_hooks(self):
            for object_name in ("SystemShapingDock", "WorkspaceTabsDock", "OperationalViewDock", "PreviewDock", "VisualReplyDock"):
                dock = self._ui_object(object_name)
                if dock is None or not hasattr(dock, "topLevelChanged"):
                    continue
                try:
                    dock.topLevelChanged.connect(lambda _floating: QtCore.QTimer.singleShot(900, self._apply_frontend_workspace_view_constraints))
                except Exception:
                    continue

    def _apply_frontend_workspace_view_constraints(self):
            if self._frontend_dock_drag_active():
                QtCore.QTimer.singleShot(900, self._apply_frontend_workspace_view_constraints)
                return
            _apply_workspace_view_constraints(
                self.window,
                extra_widgets=(
                    getattr(self.backend, "embedded_musetalk_preview", None),
                    getattr(self.backend, "visual_reply_panel", None),
                    getattr(self, "_frontend_visual_reply_panel", None),
                ),
            )

    def _normalize_frontend_chat_runtime_editor_widths(self):
            for object_name in ("chat_provider_combo", "model_combo", "preset_combo"):
                widget = self._ui_object(object_name)
                if widget is None:
                    continue
                try:
                    widget.setMinimumWidth(260 if object_name != "preset_combo" else 320)
                    widget.setMaximumWidth(16777215)
                    if hasattr(widget, "setSizeAdjustPolicy"):
                        widget.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
                    if hasattr(widget, "setMinimumContentsLength"):
                        widget.setMinimumContentsLength(18 if object_name == "chat_provider_combo" else 34)
                except Exception:
                    pass
            for layout_name in ("chat_provider_fields_layout", "chat_provider_generation_fields_layout"):
                layout = self._ui_object(layout_name)
                if layout is None:
                    continue
                try:
                    layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
                except Exception:
                    pass

    def _set_layout_item_tree_visible(self, layout, visible):
            if layout is None:
                return
            for index in range(layout.count()):
                item = layout.itemAt(index)
                if item is None:
                    continue
                widget = item.widget()
                if widget is not None:
                    try:
                        widget.setVisible(bool(visible))
                    except Exception:
                        pass
                    continue
                child_layout = item.layout()
                if child_layout is not None:
                    self._set_layout_item_tree_visible(child_layout, visible)

    def _update_frontend_collapsible_group_title(self, group_box):
            if group_box is None or not hasattr(group_box, "setTitle"):
                return
            try:
                base_title = str(group_box.property("nc_collapsible_base_title") or group_box.title() or "").strip()
            except Exception:
                base_title = str(group_box.title() or "").strip()
            try:
                summary = str(group_box.property("nc_collapsible_summary") or "").strip()
            except Exception:
                summary = ""
            expanded = True
            if hasattr(group_box, "isChecked"):
                try:
                    expanded = bool(group_box.isChecked())
                except Exception:
                    expanded = True
            arrow = "▼" if expanded else "▶"
            title = f"{arrow} {base_title}".strip()
            if summary:
                title = f"{title}  -  {summary}"
            try:
                group_box.setTitle(title)
            except Exception:
                pass

    def _apply_frontend_collapsible_group_state(self, group_box, expanded):
            if group_box is None:
                return

            layout = getattr(group_box, "layout", lambda: None)()
            self._set_layout_item_tree_visible(layout, bool(expanded))

            try:
                group_box.setFlat(not bool(expanded))
            except Exception:
                pass

            self._update_frontend_collapsible_group_title(group_box)

            # Original call
            QtCore.QTimer.singleShot(0, self._apply_frontend_workspace_view_constraints)

            # NEW: Re-trigger our custom dynamic height math when expanding cards
            backend = getattr(self, "backend", self)  # Fallback to self if backend not found

            chat_sync = getattr(backend, "_sync_chat_provider_generation_fields_height", None)
            if chat_sync:
                print(f"[UI Real] chat_sync")
                QtCore.QTimer.singleShot(10, chat_sync)

            tts_sync = getattr(backend, "_sync_tts_runtime_fields_height", None)
            if tts_sync:
                print(f"[UI Real] tts_sync")
                QtCore.QTimer.singleShot(10, tts_sync)

    def _apply_frontend_collapsible_group_state_old(self, group_box, expanded):
            if group_box is None:
                return
            layout = getattr(group_box, "layout", lambda: None)()
            self._set_layout_item_tree_visible(layout, bool(expanded))
            try:
                group_box.setFlat(not bool(expanded))
            except Exception:
                pass
            self._update_frontend_collapsible_group_title(group_box)
            QtCore.QTimer.singleShot(0, self._apply_frontend_workspace_view_constraints)

    def _set_frontend_collapsible_group_summary(self, group_box, text, fallback_title):
            if group_box is None:
                return
            title, summary = _split_collapsible_section_text(text, fallback_title)
            try:
                object_name = str(group_box.objectName() or "").strip()
            except Exception:
                object_name = ""
            if object_name == "tts_runtime_box" and summary:
                summary = str(summary.split("/", 1)[0] or summary).strip()
            try:
                group_box.setProperty("nc_collapsible_base_title", title)
                group_box.setProperty("nc_collapsible_summary", summary)
                group_box.setToolTip(str(text or title or "").strip())
            except Exception:
                pass
            self._update_frontend_collapsible_group_title(group_box)

    def _configure_frontend_runtime_group_boxes(self):
            group_specs = (
                ("chat_runtime_box", "Chat Runtime"),
                ("tts_runtime_box", "TTS Runtime"),
            )
            for object_name, fallback_title in group_specs:
                group_box = self._ui_object(object_name)
                if group_box is None:
                    continue
                try:
                    group_box.setCheckable(True)
                    group_box.setChecked(True)
                    group_box.setProperty("nc_collapsible_base_title", fallback_title)
                    group_box.setProperty("nc_collapsible_summary", "")
                    group_box.setToolTip(f"Click to collapse or expand {fallback_title.lower()}.")
                    group_box.toggled.connect(
                        lambda checked, box=group_box: self._apply_frontend_collapsible_group_state(box, checked)
                    )
                except Exception:
                    continue
                self._apply_frontend_collapsible_group_state(group_box, True)
