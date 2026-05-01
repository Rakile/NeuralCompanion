from PySide6 import QtCore, QtWidgets


def configure_legacy_dock_title_dependencies(namespace):
    """Inject qt_app-owned theme/session/native-window helpers for legacy docks."""
    globals().update(dict(namespace or {}))


class LegacyDockTitleMixin:
    """Custom title bars and floating-panel flags for the Python-built GUI docks."""

    def _apply_legacy_dock_title_widgets(self):
        palette = _app_theme_palette(self.current_app_theme_preset())
        for dock in self.findChildren(QtWidgets.QDockWidget):
            title_bar = dock.titleBarWidget()
            if title_bar is None or not bool(title_bar.property("nc_legacy_custom_dock_title")):
                title_bar = self._create_legacy_dock_title_widget(dock)
                dock.setTitleBarWidget(title_bar)
                try:
                    dock.topLevelChanged.connect(lambda _floating=False, d=dock: self._update_legacy_dock_title_widget(d))
                except Exception:
                    pass
                try:
                    dock.windowTitleChanged.connect(lambda _title="", d=dock: self._update_legacy_dock_title_widget(d))
                except Exception:
                    pass
            title_bar.setProperty("nc_theme_palette", dict(palette or {}))
            self._update_legacy_dock_title_widget(dock)
            self._update_legacy_aux_dock_background(dock)

    def _create_legacy_dock_title_widget(self, dock):
        title_bar = QtWidgets.QWidget()
        title_bar.setObjectName("ncLegacyDockTitleBar")
        title_bar.setProperty("nc_legacy_custom_dock_title", True)
        layout = QtWidgets.QHBoxLayout(title_bar)
        layout.setContentsMargins(8, 3, 5, 3)
        layout.setSpacing(6)

        label = QtWidgets.QLabel(str(dock.windowTitle() or dock.objectName() or "Panel"))
        label.setObjectName("ncLegacyDockTitleLabel")
        label.setTextInteractionFlags(QtCore.Qt.NoTextInteraction)
        layout.addWidget(label, 1)

        float_button = QtWidgets.QToolButton()
        float_button.setObjectName("ncLegacyDockFloatButton")
        float_button.setAutoRaise(True)
        float_button.clicked.connect(lambda _checked=False, d=dock: self._toggle_legacy_dock_floating(d))
        layout.addWidget(float_button)

        pin_button = QtWidgets.QToolButton()
        pin_button.setObjectName("ncLegacyDockPinButton")
        pin_button.setCheckable(True)
        pin_button.setAutoRaise(True)
        pin_button.clicked.connect(lambda _checked=False, d=dock: self._toggle_legacy_dock_pinned(d))
        layout.addWidget(pin_button)

        top_button = QtWidgets.QToolButton()
        top_button.setObjectName("ncLegacyDockTopButton")
        top_button.setCheckable(True)
        top_button.setAutoRaise(True)
        top_button.clicked.connect(lambda _checked=False, d=dock: self._toggle_legacy_dock_always_on_top(d))
        layout.addWidget(top_button)

        close_button = QtWidgets.QToolButton()
        close_button.setObjectName("ncLegacyDockCloseButton")
        close_button.setText("X")
        close_button.setToolTip("Close panel")
        close_button.setAutoRaise(True)
        close_button.clicked.connect(dock.close)
        layout.addWidget(close_button)

        return title_bar

    def _toggle_legacy_dock_floating(self, dock):
        if dock is None:
            return
        try:
            dock.setFloating(not bool(dock.isFloating()))
            self._apply_legacy_dock_window_flags(dock)
            self._schedule_dock_owner_refresh(dock)
            dock.show()
            dock.raise_()
        except Exception:
            pass

    def _update_legacy_dock_title_widget(self, dock):
        title_bar = dock.titleBarWidget() if dock is not None else None
        if title_bar is None or not bool(title_bar.property("nc_legacy_custom_dock_title")):
            return
        palette = title_bar.property("nc_theme_palette") or {}
        header_bg = palette.get("header_bg", palette.get("field_bg", "#131a23"))
        panel_bg = palette.get("panel_bg", "#18202a")
        button_bg = palette.get("button_bg", "#223247")
        button_hover_bg = palette.get("button_hover_bg", "#29405b")
        border = palette.get("surface_border", "#273342")
        text = palette.get("text", "#e5e9f0")
        text_strong = palette.get("text_strong", "#f2f5f9")
        title_bar.setStyleSheet(
            f"""
QWidget#ncLegacyDockTitleBar {{
    background: {header_bg};
    border: 1px solid {border};
}}
QLabel#ncLegacyDockTitleLabel {{
    color: {text_strong};
    font-weight: 600;
    background: transparent;
    border: 0;
}}
QToolButton#ncLegacyDockFloatButton,
QToolButton#ncLegacyDockPinButton,
QToolButton#ncLegacyDockTopButton,
QToolButton#ncLegacyDockCloseButton {{
    color: {text};
    background: {button_bg};
    border: 1px solid {border};
    border-radius: 5px;
    padding: 1px 8px;
    min-width: 42px;
}}
QToolButton#ncLegacyDockFloatButton:hover,
QToolButton#ncLegacyDockPinButton:hover,
QToolButton#ncLegacyDockTopButton:hover,
QToolButton#ncLegacyDockCloseButton:hover {{
    background: {button_hover_bg};
}}
QToolButton#ncLegacyDockPinButton:checked,
QToolButton#ncLegacyDockTopButton:checked {{
    background: {button_hover_bg};
    border-color: {palette.get("accent", "#4d8dff")};
}}
QToolButton#ncLegacyDockCloseButton {{
    background: {panel_bg};
}}
"""
        )
        label = title_bar.findChild(QtWidgets.QLabel, "ncLegacyDockTitleLabel")
        if label is not None:
            label.setText(str(dock.windowTitle() or dock.objectName() or "Panel"))
        float_button = title_bar.findChild(QtWidgets.QToolButton, "ncLegacyDockFloatButton")
        if float_button is not None:
            floating = bool(dock.isFloating())
            float_button.setText("Dock" if floating else "Float")
            float_button.setToolTip("Dock panel" if floating else "Undock panel")
        object_name = str(dock.objectName() or "")
        pinned = object_name in getattr(self, "_pinned_floating_dock_names", set())
        always_on_top = object_name in getattr(self, "_always_on_top_floating_dock_names", set())
        pin_button = title_bar.findChild(QtWidgets.QToolButton, "ncLegacyDockPinButton")
        if pin_button is not None:
            pin_button.setText("Pinned" if pinned else "Pin")
            pin_button.setToolTip("Keep this floating panel visible when the main window is hidden")
            pin_button.setChecked(bool(pinned))
        top_button = title_bar.findChild(QtWidgets.QToolButton, "ncLegacyDockTopButton")
        if top_button is not None:
            top_button.setText("Top")
            top_button.setToolTip("Keep this floating panel above other windows")
            top_button.setChecked(bool(always_on_top))
        self._apply_legacy_dock_window_flags(dock)
        self._update_legacy_aux_dock_background(dock)

    def _legacy_dock_flag_set(self, key):
        attr = "_pinned_floating_dock_names" if key == "pinned_floating_docks" else "_always_on_top_floating_dock_names"
        return getattr(self, attr, set())

    def _set_legacy_dock_flag(self, dock, key, enabled):
        if dock is None:
            return
        object_name = str(dock.objectName() or "").strip()
        if not object_name:
            return
        names = self._legacy_dock_flag_set(key)
        if enabled:
            names.add(object_name)
        else:
            names.discard(object_name)
        update_runtime_config(key, sorted(names))
        self._apply_legacy_dock_window_flags(dock)
        self._schedule_dock_owner_refresh(dock)
        self._update_legacy_dock_title_widget(dock)
        self.save_session()

    def _toggle_legacy_dock_pinned(self, dock):
        object_name = str(dock.objectName() or "").strip() if dock is not None else ""
        self._set_legacy_dock_flag(dock, "pinned_floating_docks", object_name not in self._pinned_floating_dock_names)

    def _toggle_legacy_dock_always_on_top(self, dock):
        object_name = str(dock.objectName() or "").strip() if dock is not None else ""
        self._set_legacy_dock_flag(dock, "always_on_top_floating_docks", object_name not in self._always_on_top_floating_dock_names)

    def _apply_legacy_dock_window_flags(self, dock):
        if dock is None:
            return
        object_name = str(dock.objectName() or "").strip()
        always_on_top = bool(object_name and object_name in getattr(self, "_always_on_top_floating_dock_names", set()))
        try:
            was_visible = bool(dock.isVisible())
            dock.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, bool(always_on_top and dock.isFloating()))
            if was_visible and dock.isFloating():
                dock.show()
        except Exception:
            pass

    def _update_legacy_aux_dock_background(self, dock):
        if dock is None:
            return
        object_name = str(dock.objectName() or "")
        if object_name not in {"MuseTalkPreviewDock", "VisualReplyDock"}:
            return
        palette = _app_theme_palette(self.current_app_theme_preset())
        window_bg = palette.get("window_bg", "#11161d")
        panel_bg = palette.get("panel_bg", "#18202a")
        border = palette.get("surface_border", "#273342")
        text = palette.get("text", "#e5e9f0")
        dock.setStyleSheet(
            f"""
QDockWidget#{object_name} {{
    background: {window_bg};
    color: {text};
    border: 1px solid {border};
}}
QDockWidget#{object_name} > QWidget {{
    background: {panel_bg};
    color: {text};
}}
"""
        )
        content = dock.widget() if hasattr(dock, "widget") else None
        for widget in (content, getattr(self, "preview_dock_container", None) if object_name == "MuseTalkPreviewDock" else None):
            if widget is None:
                continue
            try:
                widget.setAutoFillBackground(True)
                widget.setStyleSheet(f"background: {panel_bg}; color: {text};")
            except Exception:
                pass

    def _relax_musetalk_preview_width_constraints(self):
        """Allow the preview dock to narrow without clipping its right-side controls."""
        widgets = (
            getattr(self, "preview_dock", None),
            getattr(self, "preview_dock_container", None),
            getattr(self, "embedded_musetalk_preview", None),
        )
        for widget in widgets:
            if widget is None:
                continue
            try:
                widget.setMinimumWidth(0)
                widget.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
            except Exception:
                pass
        panel = getattr(self, "embedded_musetalk_preview", None)
        if panel is None:
            return
        for attr in (
            "preview_label",
            "image_scroll",
            "image_label",
            "reset_zoom_button",
            "show_interface_button",
            "focus_mode_button",
        ):
            widget = getattr(panel, attr, None)
            if widget is None:
                continue
            try:
                widget.setMinimumWidth(0)
            except Exception:
                pass
        for attr in ("reset_zoom_button", "show_interface_button", "focus_mode_button"):
            button = getattr(panel, attr, None)
            if button is None:
                continue
            try:
                button.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)
            except Exception:
                pass
        self._update_legacy_aux_dock_background(getattr(self, "preview_dock", None))
        self._update_legacy_aux_dock_background(getattr(self, "visual_reply_dock", None))

    def _collect_pinned_floating_docks(self):
        pinned_names = set(getattr(self, "_pinned_floating_dock_names", set()) or set())
        panels = []
        seen = set()
        for dock in self.findChildren(QtWidgets.QDockWidget):
            object_name = str(dock.objectName() or "").strip()
            if not object_name or object_name not in pinned_names:
                continue
            if not dock.isFloating() or not dock.isVisible():
                continue
            key = id(dock)
            if key in seen:
                continue
            seen.add(key)
            panels.append(dock)
        return panels

    def _hide_main_preserving_pinned_floating_docks(self):
        self._pinned_floating_panels_preserved = self._collect_pinned_floating_docks()
        self.hide()
        self._restore_pinned_floating_panels_timer.start(0)

    def _restore_pinned_floating_panels_after_main_hide(self):
        preserved = list(getattr(self, "_pinned_floating_panels_preserved", []) or [])
        for dock in preserved:
            try:
                if dock is None or not isinstance(dock, QtWidgets.QDockWidget) or not dock.isFloating():
                    continue
                self._apply_legacy_dock_window_flags(dock)
                dock.showNormal()
                dock.show()
                dock.raise_()
            except Exception:
                continue
