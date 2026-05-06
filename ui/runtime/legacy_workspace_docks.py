from PySide6 import QtCore, QtWidgets


def configure_legacy_workspace_dock_dependencies(namespace):
    """Inject qt_app-owned native-window and workspace-constraint helpers."""
    globals().update(dict(namespace or {}))


class LegacyWorkspaceDockMixin:
    """Workspace dock registration, menu, reset, and floating restore helpers."""

    def _register_workspace_dock(self, dock):
        if dock is None:
            return
        try:
            dock.topLevelChanged.connect(lambda _floating, d=dock: self._schedule_dock_owner_refresh(d))
        except Exception:
            pass
        try:
            dock.topLevelChanged.connect(lambda _floating, d=dock: self._update_legacy_dock_title_widget(d))
        except Exception:
            pass
        try:
            dock.topLevelChanged.connect(lambda _floating: QtCore.QTimer.singleShot(0, self._apply_workspace_view_constraints))
        except Exception:
            pass
        self._schedule_dock_owner_refresh(dock)
        QtCore.QTimer.singleShot(0, self._apply_workspace_view_constraints)

    def _apply_workspace_view_constraints(self):
        _apply_workspace_view_constraints(
            self,
            extra_widgets=(
                getattr(self, "embedded_musetalk_preview", None),
                getattr(self, "visual_reply_panel", None),
            ),
        )
        self._relax_musetalk_preview_width_constraints()

    def _schedule_dock_owner_refresh(self, dock):
        if dock is None or not bool(globals().get("_WIN32_DOCK_OWNER_SUPPORTED", False)):
            return
        QtCore.QTimer.singleShot(0, lambda d=dock: self._refresh_native_dock_owner(d))

    def _refresh_native_dock_owner(self, dock):
        if dock is None or not bool(globals().get("_WIN32_DOCK_OWNER_SUPPORTED", False)):
            return
        try:
            object_name = str(dock.objectName() or "").strip()
            pinned = bool(object_name and object_name in getattr(self, "_pinned_floating_dock_names", set()))
            owner = 0 if dock.isFloating() and pinned else int(self.winId())
            setter = globals().get("_win32_set_window_owner")
            ctypes_module = globals().get("ctypes")
            if setter is None or ctypes_module is None:
                return
            setter(int(dock.winId()), int(globals().get("_WIN32_GWLP_HWNDPARENT", -8)), ctypes_module.c_void_p(owner))
        except Exception:
            pass

    def changeEvent(self, event):
        try:
            if event.type() == QtCore.QEvent.WindowStateChange:
                if bool(self.windowState() & QtCore.Qt.WindowMinimized):
                    self._capture_floating_panels_for_minimize()
                    self._restore_floating_panels_timer.start(0)
                    QtCore.QTimer.singleShot(250, self._restore_floating_panels_after_minimize)
                    QtCore.QTimer.singleShot(900, self._restore_floating_panels_after_minimize)
        except Exception:
            pass
        super().changeEvent(event)

    def _collect_preservable_floating_panels(self):
        panels = []
        seen = set()
        for dock in self.findChildren(QtWidgets.QDockWidget):
            if not dock.isFloating() or not dock.isVisible():
                continue
            key = id(dock)
            if key in seen:
                continue
            seen.add(key)
            panels.append(dock)
        stage = getattr(self, "_musetalk_stage_window", None)
        if stage is not None and stage.isVisible():
            panels.append(stage)
        external_return = getattr(self, "_external_avatar_return_window", None)
        if external_return is not None and external_return.isVisible():
            panels.append(external_return)
        return panels

    def _capture_floating_panels_for_minimize(self):
        pinned = self._collect_pinned_floating_docks()
        self._floating_panels_preserved = pinned if pinned else []

    def _restore_floating_panels_after_minimize(self):
        preserved = list(getattr(self, "_floating_panels_preserved", []) or [])
        if not preserved:
            return
        for panel in preserved:
            try:
                if panel is None:
                    continue
                if isinstance(panel, QtWidgets.QDockWidget) and not panel.isFloating():
                    continue
                panel.setWindowState(panel.windowState() & ~QtCore.Qt.WindowMinimized)
                panel.showNormal()
                panel.show()
                panel.raise_()
                panel.activateWindow()
            except Exception:
                continue

    def _build_workspace_menu(self):
        menu_bar = self.menuBar()
        self.workspace_menu = menu_bar.addMenu("Workspace")
        if hasattr(self, "system_shaping_dock"):
            self.workspace_menu.addAction(self.system_shaping_dock.toggleViewAction())
        if hasattr(self, "workspace_tabs_dock"):
            self.workspace_menu.addAction(self.workspace_tabs_dock.toggleViewAction())
        if hasattr(self, "operational_dock"):
            self.workspace_menu.addAction(self.operational_dock.toggleViewAction())
        self.workspace_menu.addSeparator()
        reset_action = self.workspace_menu.addAction("Reset Workspace Layout")
        reset_action.triggered.connect(self.reset_workspace_layout)
        show_all_action = self.workspace_menu.addAction("Show All Panels")
        show_all_action.triggered.connect(self.show_all_workspace_panels)

    def show_all_workspace_panels(self):
        if hasattr(self, "system_shaping_dock"):
            self.system_shaping_dock.show()
            self.system_shaping_dock.raise_()
        if hasattr(self, "workspace_tabs_dock"):
            self.workspace_tabs_dock.show()
            self.workspace_tabs_dock.raise_()
        if hasattr(self, "operational_dock"):
            self.operational_dock.show()
            self.operational_dock.raise_()
        if hasattr(self, "preview_dock"):
            self.preview_dock.show()
        if hasattr(self, "visual_reply_dock") and self._visual_reply_addon_enabled():
            self.visual_reply_dock.show()
        print("[QtGUI] Workspace panels shown.")

    def reset_workspace_layout(self):
        if getattr(self, "_musetalk_avatar_focus_active", False):
            self.exit_musetalk_avatar_focus(raise_main=False)
        if getattr(self, "_external_avatar_focus_active", False):
            self.exit_external_avatar_focus(raise_main=False)
        if hasattr(self, "system_shaping_dock"):
            self.system_shaping_dock.setFloating(False)
            self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.system_shaping_dock)
            self.system_shaping_dock.show()
        if hasattr(self, "workspace_tabs_dock"):
            self.workspace_tabs_dock.setFloating(False)
            self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.workspace_tabs_dock)
            self.workspace_tabs_dock.show()
            if hasattr(self, "system_shaping_dock"):
                try:
                    self.tabifyDockWidget(self.system_shaping_dock, self.workspace_tabs_dock)
                except Exception:
                    pass
        if hasattr(self, "operational_dock"):
            self.operational_dock.setFloating(False)
            self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.operational_dock)
            self.operational_dock.show()
        if hasattr(self, "preview_dock"):
            self.preview_dock.setFloating(False)
            self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.preview_dock)
            self.preview_dock.hide()
        visual_reply_enabled = self._visual_reply_addon_enabled()
        if hasattr(self, "visual_reply_dock") and visual_reply_enabled:
            self.visual_reply_dock.setFloating(False)
            self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.visual_reply_dock)
            self.visual_reply_dock.hide()
        elif hasattr(self, "visual_reply_dock"):
            self.visual_reply_dock.hide()
        if hasattr(self, "preview_dock") and hasattr(self, "visual_reply_dock") and visual_reply_enabled:
            try:
                self.tabifyDockWidget(self.preview_dock, self.visual_reply_dock)
            except Exception:
                pass
        try:
            self.resizeDocks(
                [self.system_shaping_dock, self.operational_dock],
                [520, 720],
                QtCore.Qt.Horizontal,
            )
        except Exception:
            pass
        print("[QtGUI] Workspace layout reset.")
