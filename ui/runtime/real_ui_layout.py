import base64
import json

from PySide6 import QtCore, QtWidgets

from core.ui_session_schema import group_ui_session, with_flat_ui_settings


def configure_real_ui_layout_dependencies(namespace):
    """Inject qt_app-owned globals used by the extracted real-UI layout mixin."""
    globals().update(dict(namespace or {}))


class MainUiRealLayoutMixin:
    """Layout, docking, and collapsible-card helpers for the runtime-backed main.ui bridge."""

    def _normalize_frontend_tts_runtime_layout(self):
            tts_box = self._ui("tts_runtime_box", QtWidgets.QGroupBox)
            tabs = self._ui("tts_runtime_addon_tabs", QtWidgets.QTabWidget)
            hint = self._ui("tts_runtime_hint_label", QtWidgets.QLabel)
            combo = self._ui("tts_backend_combo", QtWidgets.QComboBox)

            if tts_box is not None and tts_box.layout() is not None:
                layout = tts_box.layout()
                try:
                    layout.setAlignment(QtCore.Qt.AlignTop)
                    for index in range(layout.count()):
                        item = layout.itemAt(index)
                        if item is not None:
                            layout.setAlignment(item, QtCore.Qt.AlignTop)
                    for index in range(layout.count()):
                        layout.setStretch(index, 0)
                    layout.setSizeConstraint(QtWidgets.QLayout.SetMinimumSize)
                except Exception:
                    pass

            for widget in (combo, hint):
                if widget is None or not hasattr(widget, "sizePolicy"):
                    continue
                try:
                    policy = widget.sizePolicy()
                    policy.setVerticalPolicy(QtWidgets.QSizePolicy.Maximum)
                    widget.setSizePolicy(policy)
                    widget.setMinimumHeight(0 if widget is hint else widget.minimumHeight())
                    widget.updateGeometry()
                except Exception:
                    pass

            if tabs is None:
                return
            try:
                policy = tabs.sizePolicy()
                policy.setVerticalPolicy(QtWidgets.QSizePolicy.Maximum)
                tabs.setSizePolicy(policy)
                tabs.setMinimumHeight(0)
                active_page = tabs.currentWidget()
                if active_page is not None:
                    if active_page.layout() is not None:
                        active_page.layout().invalidate()
                        active_page.layout().activate()
                    active_page.adjustSize()
                    active_page.updateGeometry()
                    wanted = active_page.sizeHint().height() + tabs.tabBar().sizeHint().height() + 44
                    tabs.setMaximumHeight(max(160, min(900, int(wanted))))
                tabs.adjustSize()
                tabs.updateGeometry()
            except Exception:
                pass

    def _fix_system_shaping_scroll_content_size(self):
            if self._normalize_system_shaping_fixed_tab_layout():
                tabs = self._ui("host_settings_tabs", QtWidgets.QTabWidget)
                if tabs is not None:
                    try:
                        tabs.setMinimumHeight(0)
                        tabs.setMaximumHeight(16777215)
                        tabs.updateGeometry()
                    except Exception:
                        pass
                self._normalize_frontend_tts_runtime_layout()
                return

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

            self._normalize_frontend_tts_runtime_layout()

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

    def _normalize_system_shaping_fixed_tab_layout(self):
            tabs = self._ui("host_settings_tabs", QtWidgets.QTabWidget)
            panel = self._ui("system_shaping_panel", QtWidgets.QWidget)
            if tabs is None or panel is None:
                return False

            self._place_preset_buttons_under_selector()
            self._wrap_host_settings_tab_pages(tabs)

            if bool(tabs.property("_nc_fixed_system_shaping_tabs")):
                return True

            scroll = self._ui("system_shaping_scroll", QtWidgets.QScrollArea)
            content = self._ui("system_shaping_content", QtWidgets.QWidget)
            mic_row = self._ui("micStatusRow", QtWidgets.QWidget)
            operational_content = self._ui("operational_content", QtWidgets.QWidget)
            right_tabs = self._ui("right_tabs", QtWidgets.QTabWidget)
            panel_layout = panel.layout()
            content_layout = content.layout() if content is not None and hasattr(content, "layout") else None
            operational_layout = operational_content.layout() if operational_content is not None and hasattr(operational_content, "layout") else None
            if scroll is None or panel_layout is None or content_layout is None:
                return False

            style = str(scroll.styleSheet() or "").strip()
            if style and not bool(panel.property("_nc_system_shaping_scroll_style_applied")):
                try:
                    existing = str(panel.styleSheet() or "").strip()
                    panel.setStyleSheet(f"{existing}\n{style}".strip() if existing else style)
                    panel.setProperty("_nc_system_shaping_scroll_style_applied", True)
                except Exception:
                    pass

            for widget in (mic_row, tabs):
                if widget is None:
                    continue
                try:
                    content_layout.removeWidget(widget)
                    widget.setParent(operational_content if widget is mic_row and operational_content is not None else panel)
                except Exception:
                    pass

            try:
                panel_layout.removeWidget(scroll)
                scroll.hide()
            except Exception:
                pass

            try:
                panel_layout.setContentsMargins(14, 14, 14, 14)
                panel_layout.setSpacing(12)
                panel_layout.addWidget(tabs, 1)
                if mic_row is not None and operational_layout is not None:
                    insert_index = operational_layout.indexOf(right_tabs) if right_tabs is not None else 1
                    operational_layout.insertWidget(max(0, insert_index), mic_row, 0)
                    operational_layout.setAlignment(mic_row, QtCore.Qt.AlignTop)
            except Exception:
                pass

            try:
                policy = tabs.sizePolicy()
                policy.setHorizontalPolicy(QtWidgets.QSizePolicy.Expanding)
                policy.setVerticalPolicy(QtWidgets.QSizePolicy.Expanding)
                tabs.setSizePolicy(policy)
                tabs.setMinimumHeight(0)
                tabs.setMaximumHeight(16777215)
                tabs.setProperty("_nc_fixed_system_shaping_tabs", True)
                tabs.updateGeometry()
            except Exception:
                pass
            return True

    def _place_preset_buttons_under_selector(self):
            host_tab = self._ui("host_settings_host_tab", QtWidgets.QWidget)
            if host_tab is None or bool(host_tab.property("_nc_preset_buttons_near_selector")):
                return
            host_layout = host_tab.layout()
            if host_layout is None:
                return
            form = host_tab.findChild(QtWidgets.QFormLayout, "hostRuntimeForm")
            button_row = host_tab.findChild(QtWidgets.QHBoxLayout, "presetButtonRow")
            if form is None or button_row is None:
                return

            form_index = -1
            button_index = -1
            for index in range(host_layout.count()):
                item = host_layout.itemAt(index)
                if item is None:
                    continue
                if item.layout() is form:
                    form_index = index
                if item.layout() is button_row:
                    button_index = index
            if form_index < 0 or button_index < 0 or button_index == form_index + 1:
                try:
                    host_tab.setProperty("_nc_preset_buttons_near_selector", True)
                except Exception:
                    pass
                return

            try:
                item = host_layout.takeAt(button_index)
                row_layout = item.layout() if item is not None else button_row
                insert_index = form_index + 1
                if button_index < insert_index:
                    insert_index -= 1
                host_layout.insertLayout(insert_index, row_layout)
                host_layout.invalidate()
                host_layout.activate()
                host_tab.setProperty("_nc_preset_buttons_near_selector", True)
                host_tab.updateGeometry()
            except Exception:
                pass

    def _wrap_host_settings_tab_pages(self, tabs):
            if tabs is None or not hasattr(tabs, "count"):
                return
            current_index = -1
            try:
                current_index = int(tabs.currentIndex())
            except Exception:
                current_index = -1
            index = 0
            while index < tabs.count():
                page = tabs.widget(index)
                if page is None:
                    index += 1
                    continue
                if isinstance(page, QtWidgets.QAbstractScrollArea) and bool(page.property("_nc_host_settings_page_scroll")):
                    index += 1
                    continue

                title = ""
                tooltip = ""
                data = None
                icon = None
                try:
                    title = str(tabs.tabText(index) or "")
                    tooltip = str(tabs.tabToolTip(index) or "")
                    icon = tabs.tabIcon(index)
                    tab_bar = tabs.tabBar()
                    if tab_bar is not None:
                        data = tab_bar.tabData(index)
                except Exception:
                    pass

                scroll = QtWidgets.QScrollArea()
                object_name = str(page.objectName() or f"host_settings_page_{index}").strip()
                scroll.setObjectName(f"{object_name}_scroll")
                scroll.setProperty("_nc_host_settings_page_scroll", True)
                scroll.setWidgetResizable(True)
                scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
                scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
                scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
                scroll.setStyleSheet("QScrollArea { background: transparent; border: 0; } QScrollArea > QWidget > QWidget { background: transparent; }")
                try:
                    scroll.viewport().setAutoFillBackground(False)
                except Exception:
                    pass

                try:
                    tabs.removeTab(index)
                    page.setParent(None)
                    if hasattr(page, "layout") and page.layout() is not None:
                        page.layout().setAlignment(QtCore.Qt.AlignTop)
                    page.setMinimumHeight(0)
                    scroll.setWidget(page)
                    tabs.insertTab(index, scroll, title)
                    if icon is not None and not icon.isNull():
                        tabs.setTabIcon(index, icon)
                    if tooltip:
                        tabs.setTabToolTip(index, tooltip)
                    tab_bar = tabs.tabBar()
                    if tab_bar is not None and data is not None:
                        tab_bar.setTabData(index, data)
                except Exception:
                    try:
                        scroll.deleteLater()
                    except Exception:
                        pass
                index += 1
            if current_index >= 0:
                try:
                    tabs.setCurrentIndex(min(current_index, tabs.count() - 1))
                except Exception:
                    pass

    def _resync_frontend_runtime_cards(self):
            backend = getattr(self, "backend", None)
            if backend is not None:
                for callback_name in ("_sync_chat_provider_generation_fields_height", "_sync_tts_runtime_fields_height"):
                    callback = getattr(backend, callback_name, None)
                    if callable(callback):
                        try:
                            callback()
                        except Exception:
                            pass
            self._fix_system_shaping_scroll_content_size()
            try:
                QtCore.QTimer.singleShot(75, self._fix_system_shaping_scroll_content_size)
                QtCore.QTimer.singleShot(200, self._fix_system_shaping_scroll_content_size)
            except Exception:
                pass

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

    def _fix_workspace_tab_content_layouts(self):
            """Keep sparse workspace tabs packed at the top instead of stretched apart."""
            def widget(name, cls=None):
                return self._ui(name, cls or QtWidgets.QWidget)

            def set_policy(target, *, vertical=QtWidgets.QSizePolicy.Preferred, horizontal=QtWidgets.QSizePolicy.Expanding):
                if target is None or not hasattr(target, "sizePolicy"):
                    return
                try:
                    policy = target.sizePolicy()
                    policy.setHorizontalPolicy(horizontal)
                    policy.setVerticalPolicy(vertical)
                    target.setSizePolicy(policy)
                    target.setMinimumHeight(0)
                    target.updateGeometry()
                except Exception:
                    pass

            def align_layout(name):
                owner = widget(name)
                layout = owner.layout() if owner is not None and hasattr(owner, "layout") else None
                if layout is None:
                    return
                try:
                    layout.setAlignment(QtCore.Qt.AlignTop)
                    layout.invalidate()
                    layout.activate()
                except Exception:
                    pass

            def align_named_layout(owner_name, layout_name):
                owner = widget(owner_name)
                if owner is None:
                    return
                layout = owner.findChild(QtWidgets.QLayout, layout_name)
                if layout is None:
                    return
                try:
                    layout.setAlignment(QtCore.Qt.AlignTop)
                    layout.invalidate()
                    layout.activate()
                except Exception:
                    pass

            for name in (
                "chunking_tab",
                "dry_run_tab",
                "vseeface_tab",
                "body_tab",
                "dynamics_tab",
            ):
                align_layout(name)
                set_policy(widget(name), vertical=QtWidgets.QSizePolicy.Preferred)

            for owner_name, layout_name in (
                ("chunking_tab", "chunkingLayout"),
                ("dry_run_tab", "dryRunLayout"),
                ("vseeface_tab", "vseefaceLayout"),
                ("body_tab", "bodyTabLayout"),
                ("body_tab", "bodyPresetsLayout"),
                ("body_tab", "bodyPoseSlidersSectionLayout"),
                ("dynamics_tab", "dynamicsTabLayout"),
            ):
                align_named_layout(owner_name, layout_name)

            for name in (
                "standard_chunking_box",
                "musetalk_chunking_box",
                "streaming_chunking_box",
                "chunking_profiles_box",
                "performance_profiles_box",
            ):
                box = widget(name, QtWidgets.QGroupBox)
                set_policy(box, vertical=QtWidgets.QSizePolicy.Maximum)

            dry_run_summary = widget("dry_run_summary", QtWidgets.QPlainTextEdit)
            if dry_run_summary is not None:
                set_policy(dry_run_summary, vertical=QtWidgets.QSizePolicy.Preferred)
                try:
                    dry_run_summary.setMinimumHeight(180)
                    dry_run_summary.setMaximumHeight(360)
                except Exception:
                    pass

            vseeface_tabs = widget("vseeface_tabs", QtWidgets.QTabWidget)
            if vseeface_tabs is not None:
                set_policy(vseeface_tabs, vertical=QtWidgets.QSizePolicy.Preferred)
                try:
                    vseeface_tabs.setMinimumHeight(0)
                    vseeface_tabs.setMaximumHeight(720)
                except Exception:
                    pass
                for index in range(vseeface_tabs.count()):
                    page = vseeface_tabs.widget(index)
                    set_policy(page, vertical=QtWidgets.QSizePolicy.Preferred)
                    if page is not None and page.layout() is not None:
                        try:
                            page.layout().setAlignment(QtCore.Qt.AlignTop)
                            page.layout().invalidate()
                            page.layout().activate()
                        except Exception:
                            pass

            for name in (
                "body_combo",
                "emotion_combo",
                "btn_hand_doctor",
                "btn_vseeface_hide_interface",
                "btn_reset_chunking_defaults",
            ):
                set_policy(widget(name), vertical=QtWidgets.QSizePolicy.Maximum)

            for name in ("left_tabs", "vseeface_tabs"):
                tabs = widget(name, QtWidgets.QTabWidget)
                if tabs is None:
                    continue
                try:
                    tabs.adjustSize()
                    tabs.updateGeometry()
                    current = tabs.currentWidget()
                    if current is not None:
                        current.adjustSize()
                        current.updateGeometry()
                except Exception:
                    pass

    def _load_frontend_session_payload(self):
            if not SESSION_PATH.exists():
                return {}
            try:
                payload = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    return {}
                return with_flat_ui_settings(payload)
            except Exception:
                return {}

    def _write_frontend_session_payload(self, payload):
            try:
                SESSION_PATH.write_text(json.dumps(group_ui_session(payload or {}), indent=4), encoding="utf-8")
            except Exception as exc:
                print(f"[UI Real] Failed to save frontend layout: {exc}")

    def _frontend_dock_layout_snapshot(self):
            docks = {}
            for dock in self.window.findChildren(QtWidgets.QDockWidget):
                object_name = str(dock.objectName() or "").strip()
                if not object_name:
                    continue
                if not self._frontend_dock_addon_enabled(object_name):
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
                ui_settings = dict(payload.get("ui") or {})
                layout_settings = dict(ui_settings.get("layout") or {})
                layout_settings["main_ui_real"] = layout_state
                ui_settings["layout"] = layout_settings
                payload["ui"] = ui_settings
                payload.pop(self.FRONTEND_LAYOUT_SESSION_KEY, None)
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
                        if not self._frontend_dock_addon_enabled(str(object_name)):
                            dock = self._ui_object(str(object_name))
                            if dock is not None and isinstance(dock, QtWidgets.QDockWidget):
                                try:
                                    dock.hide()
                                except Exception:
                                    pass
                            continue
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
                    if not self._frontend_dock_addon_enabled(str(object_name)):
                        dock = self._ui_object(str(object_name))
                        if dock is not None and isinstance(dock, QtWidgets.QDockWidget):
                            try:
                                dock.hide()
                            except Exception:
                                pass
                        continue
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
            names = [
                "SystemShapingDock",
                "WorkspaceTabsDock",
                "OperationalViewDock",
                "MuseTalkPreviewDock",
                "PreviewDock",
            ]
            if self._frontend_dock_addon_enabled("VisualReplyDock"):
                names.append("VisualReplyDock")
            docks = []
            for object_name in names:
                dock = self._ui_object(object_name)
                if dock is not None and isinstance(dock, QtWidgets.QDockWidget):
                    docks.append(dock)
            return docks

    def _frontend_dock_addon_enabled(self, object_name):
            object_name = str(object_name or "").strip()
            if object_name != "VisualReplyDock":
                return True
            checker = getattr(self, "_visual_reply_addon_enabled", None)
            return True if not callable(checker) else bool(checker())

    def _enforce_disabled_frontend_workspace_docks(self):
            if self._frontend_dock_addon_enabled("VisualReplyDock"):
                return
            dock = self._ui_object("VisualReplyDock")
            if dock is None or not isinstance(dock, QtWidgets.QDockWidget):
                return
            try:
                dock.hide()
            except Exception:
                pass
            try:
                action = dock.toggleViewAction()
                if action is not None:
                    action.setVisible(False)
                    action.setEnabled(False)
            except Exception:
                pass
            button = self._ui_object("btn_visual_reply")
            if button is not None:
                try:
                    button.setVisible(False)
                    button.setEnabled(False)
                except Exception:
                    pass

    def _begin_frontend_workspace_layout_operation(self, label):
            if bool(getattr(self, "_frontend_workspace_layout_busy", False)):
                print(f"[UI Real] Ignored {label}; workspace layout is still settling.")
                return False
            self._frontend_workspace_layout_busy = True
            # Dock mutations emit several Qt layout/visibility signals. Keep a
            # short settle window so rapid Reset/Show-All clicks do not stack
            # addDockWidget/tabifyDockWidget operations on top of each other.
            QtCore.QTimer.singleShot(450, self._end_frontend_workspace_layout_operation)
            return True

    def _end_frontend_workspace_layout_operation(self):
            self._frontend_workspace_layout_busy = False

    def _move_frontend_workspace_dock(self, dock, area):
            dock.setFloating(False)
            self.window.addDockWidget(area, dock)
            dock.show()

    def show_all_frontend_workspace_panels(self):
            if not self._begin_frontend_workspace_layout_operation("Show All Panels"):
                return
            for dock in self._frontend_workspace_docks():
                try:
                    dock.show()
                    dock.raise_()
                except Exception:
                    pass
            self._enforce_disabled_frontend_workspace_docks()
            self._apply_frontend_workspace_view_constraints()
            self._schedule_frontend_layout_save()
            print("[UI Real] Workspace panels shown.")

    def reset_frontend_workspace_layout(self):
            if not self._begin_frontend_workspace_layout_operation("Reset Workspace Layout"):
                return
            self._restoring_frontend_layout = True
            try:
                system_dock = self._ui_object("SystemShapingDock")
                workspace_dock = self._ui_object("WorkspaceTabsDock")
                operational_dock = self._ui_object("OperationalViewDock")
                preview_dock = self._ui_object("MuseTalkPreviewDock") or self._ui_object("PreviewDock")
                visual_dock = None
                checker = getattr(self, "_visual_reply_addon_enabled", None)
                if not callable(checker) or bool(checker()):
                    visual_dock = self._ui_object("VisualReplyDock")

                left_docks = [dock for dock in (system_dock, workspace_dock) if isinstance(dock, QtWidgets.QDockWidget)]
                right_docks = [dock for dock in (operational_dock, preview_dock, visual_dock) if isinstance(dock, QtWidgets.QDockWidget)]

                for dock in left_docks:
                    self._move_frontend_workspace_dock(dock, QtCore.Qt.LeftDockWidgetArea)
                for dock in right_docks:
                    self._move_frontend_workspace_dock(dock, QtCore.Qt.RightDockWidgetArea)

                # Avoid forcing tab groups during reset. With Designer-loaded
                # docks and live adopted widgets, rapid re-tabification can
                # crash in Qt's native docking code. Users can still dock/tab
                # panels manually after reset.
                for dock in left_docks + right_docks:
                    try:
                        dock.raise_()
                    except Exception:
                        pass
            finally:
                self._restoring_frontend_layout = False

            self._apply_frontend_workspace_view_constraints()
            self._enforce_disabled_frontend_workspace_docks()
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
            self._enforce_disabled_frontend_workspace_docks()
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

            QtCore.QTimer.singleShot(0, self._apply_frontend_workspace_view_constraints)
            QtCore.QTimer.singleShot(10, self._resync_frontend_runtime_cards)

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
                group_box.setProperty("nc_collapsible_base_title", title)
                group_box.setProperty("nc_collapsible_summary", summary)
                group_box.setToolTip("")
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
                    group_box.setToolTip("")
                    group_box.toggled.connect(
                        lambda checked, box=group_box: self._apply_frontend_collapsible_group_state(box, checked)
                    )
                except Exception:
                    continue
                self._apply_frontend_collapsible_group_state(group_box, True)
