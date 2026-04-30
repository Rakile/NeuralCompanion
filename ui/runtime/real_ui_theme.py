from PySide6 import QtCore, QtWidgets


def configure_real_ui_theme_dependencies(namespace):
    """Inject qt_app-owned theme globals used by the extracted real-UI theme mixin."""
    globals().update(dict(namespace or {}))


class MainUiRealThemeMixin:
    """Theme binding and runtime-panel restyling helpers for the runtime-backed main.ui bridge."""

    def _bind_frontend_theme_controls(self):
            for preset_id, button_name, _edit_name in APP_THEME_PRESET_WIDGETS:
                button = self._ui_object(button_name)
                if button is None or not hasattr(button, "clicked"):
                    continue
                if hasattr(button, "setCheckable"):
                    try:
                        button.setCheckable(True)
                    except Exception:
                        pass
                button.clicked.connect(lambda _checked=False, wanted=preset_id: self._apply_frontend_theme_preset(wanted))

    def _theme_stylesheet_for_current_preset(self):
            current_preset = _normalize_app_theme_preset_id(
                getattr(self.backend, "_active_app_theme_preset", RUNTIME_CONFIG.get("ui_theme_preset", DEFAULT_APP_THEME_PRESET))
            )
            return _build_app_stylesheet_for_preset(current_preset)

    def _apply_theme_to_frontend_window(self):
            stylesheet = self._theme_stylesheet_for_current_preset()
            palette = _app_theme_palette(
                getattr(self.backend, "_active_app_theme_preset", RUNTIME_CONFIG.get("ui_theme_preset", DEFAULT_APP_THEME_PRESET))
            )
            dock_stylesheet = self._frontend_dock_title_stylesheet(palette)
            tab_stylesheet = self._frontend_horizontal_tab_stylesheet()
            if self.window is not None and hasattr(self.window, "setStyleSheet"):
                try:
                    self.window.setStyleSheet(f"{stylesheet}\n{dock_stylesheet}\n{tab_stylesheet}")
                except Exception:
                    pass
                try:
                    _apply_inline_theme_styles(self.window, palette)
                    _apply_readable_input_palettes(self.window, palette)
                    _apply_engine_action_button_accents(self.window)
                    self._apply_frontend_dock_title_widgets(palette)
                except Exception:
                    pass

    def _frontend_dock_title_stylesheet(self, palette):
            window_bg = palette.get("window_bg", "#11161d")
            panel_bg = palette.get("panel_bg", "#18202a")
            header_bg = palette.get("header_bg", palette.get("field_bg", "#131a23"))
            border = palette.get("surface_border", "#273342")
            text = palette.get("text", "#e5e9f0")
            text_strong = palette.get("text_strong", "#f2f5f9")
            return f"""
QDockWidget {{
    background: {window_bg};
    color: {text};
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}}
QDockWidget::title {{
    background: {header_bg};
    color: {text_strong};
    border: 1px solid {border};
    padding: 4px 8px;
    text-align: left;
}}
QDockWidget::close-button,
QDockWidget::float-button {{
    background: {panel_bg};
    border: 1px solid {border};
    border-radius: 4px;
    width: 14px;
    height: 14px;
}}
QDockWidget::close-button:hover,
QDockWidget::float-button:hover {{
    background: {palette.get("button_hover_bg", "#29405b")};
}}
"""

    def _apply_frontend_dock_title_widgets(self, palette):
            if self.window is None:
                return
            for dock in self.window.findChildren(QtWidgets.QDockWidget):
                title_bar = dock.titleBarWidget()
                if title_bar is None or not bool(title_bar.property("nc_custom_dock_title")):
                    title_bar = self._create_frontend_dock_title_widget(dock)
                    dock.setTitleBarWidget(title_bar)
                    try:
                        dock.topLevelChanged.connect(lambda _floating=False, d=dock: self._update_frontend_dock_title_widget(d))
                    except Exception:
                        pass
                    try:
                        dock.windowTitleChanged.connect(lambda _title="", d=dock: self._update_frontend_dock_title_widget(d))
                    except Exception:
                        pass
                title_bar.setProperty("nc_theme_palette", dict(palette or {}))
                self._update_frontend_dock_title_widget(dock)

    def _create_frontend_dock_title_widget(self, dock):
            title_bar = QtWidgets.QWidget()
            title_bar.setObjectName("ncDockTitleBar")
            title_bar.setProperty("nc_custom_dock_title", True)
            layout = QtWidgets.QHBoxLayout(title_bar)
            layout.setContentsMargins(8, 3, 5, 3)
            layout.setSpacing(6)

            label = QtWidgets.QLabel(str(dock.windowTitle() or dock.objectName() or "Panel"))
            label.setObjectName("ncDockTitleLabel")
            label.setTextInteractionFlags(QtCore.Qt.NoTextInteraction)
            layout.addWidget(label, 1)

            float_button = QtWidgets.QToolButton()
            float_button.setObjectName("ncDockFloatButton")
            float_button.setAutoRaise(True)
            float_button.clicked.connect(lambda _checked=False, d=dock: self._toggle_frontend_dock_floating(d))
            layout.addWidget(float_button)

            close_button = QtWidgets.QToolButton()
            close_button.setObjectName("ncDockCloseButton")
            close_button.setText("X")
            close_button.setToolTip("Close panel")
            close_button.setAutoRaise(True)
            close_button.clicked.connect(dock.close)
            layout.addWidget(close_button)

            return title_bar

    def _toggle_frontend_dock_floating(self, dock):
            if dock is None:
                return
            try:
                dock.setFloating(not bool(dock.isFloating()))
                dock.show()
                dock.raise_()
            except Exception:
                pass

    def _update_frontend_dock_title_widget(self, dock):
            title_bar = dock.titleBarWidget() if dock is not None else None
            if title_bar is None or not bool(title_bar.property("nc_custom_dock_title")):
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
QWidget#ncDockTitleBar {{
    background: {header_bg};
    border: 1px solid {border};
}}
QLabel#ncDockTitleLabel {{
    color: {text_strong};
    font-weight: 600;
    background: transparent;
    border: 0;
}}
QToolButton#ncDockFloatButton,
QToolButton#ncDockCloseButton {{
    color: {text};
    background: {button_bg};
    border: 1px solid {border};
    border-radius: 5px;
    padding: 1px 8px;
    min-width: 42px;
}}
QToolButton#ncDockFloatButton:hover,
QToolButton#ncDockCloseButton:hover {{
    background: {button_hover_bg};
}}
QToolButton#ncDockCloseButton {{
    background: {panel_bg};
}}
"""
            )
            label = title_bar.findChild(QtWidgets.QLabel, "ncDockTitleLabel")
            if label is not None:
                label.setText(str(dock.windowTitle() or dock.objectName() or "Panel"))
            float_button = title_bar.findChild(QtWidgets.QToolButton, "ncDockFloatButton")
            if float_button is not None:
                floating = bool(dock.isFloating())
                float_button.setText("Dock" if floating else "Float")
                float_button.setToolTip("Dock panel" if floating else "Undock panel")

    def _frontend_horizontal_tab_stylesheet(self):
            # The Designer/runtime theme intentionally keeps icon-sidebar tabs narrow,
            # but text tabs need enough width after dynamic addon pages are adopted.
            return """
QTabWidget#sensory_feedback_tabs QTabBar::tab,
QTabWidget#vseeface_tabs QTabBar::tab,
QTabWidget#musetalk_tabs QTabBar::tab,
QTabWidget#tts_runtime_addon_tabs QTabBar::tab,
QTabWidget#vam_setup_tabs QTabBar::tab {
    min-width: 96px;
    max-width: 220px;
    padding-left: 14px;
    padding-right: 14px;
}
QTabWidget#right_tabs QTabBar::tab {
    min-width: 118px;
    max-width: 240px;
    padding-left: 14px;
    padding-right: 14px;
}
"""

    def _apply_theme_to_runtime_panels(self):
            palette = _app_theme_palette(
                getattr(self.backend, "_active_app_theme_preset", RUNTIME_CONFIG.get("ui_theme_preset", DEFAULT_APP_THEME_PRESET))
            )
            preview_bg = palette.get("preview_bg", palette.get("panel_bg", palette.get("field_bg", "#18202a")))
            field_bg = palette.get("field_bg", "#0f141b")
            border = palette.get("surface_border", "#273342")
            text = palette.get("text", "#e5e9f0")
            text_strong = palette.get("text_strong", "#f2f5f9")

            for panel in (
                getattr(self, "_frontend_musetalk_preview_panel", None),
                getattr(self.backend, "embedded_musetalk_preview", None),
            ):
                if panel is None:
                    continue
                label = getattr(panel, "preview_label", None)
                if label is not None and hasattr(label, "setStyleSheet"):
                    try:
                        label.setStyleSheet(f"font-weight: 600; color: {text_strong};")
                    except Exception:
                        pass
                scroll = getattr(panel, "image_scroll", None)
                if scroll is not None and hasattr(scroll, "setStyleSheet"):
                    try:
                        focus_mode = bool(getattr(panel, "focus_mode_active", False))
                        if focus_mode:
                            scroll.setStyleSheet(
                                f"QScrollArea {{ background: {palette.get('window_bg', '#11161d')}; border: 0; border-radius: 0; }}"
                            )
                        else:
                            scroll.setStyleSheet(
                                f"QScrollArea {{ background: {preview_bg}; border: 1px solid {border}; border-radius: 10px; }}"
                            )
                    except Exception:
                        pass

            for panel in (
                getattr(self, "_frontend_visual_reply_panel", None),
                getattr(self.backend, "visual_reply_panel", None),
            ):
                if panel is None:
                    continue
                status_label = getattr(panel, "status_label", None)
                if status_label is not None and hasattr(status_label, "setStyleSheet"):
                    try:
                        status_label.setStyleSheet(f"font-weight: 600; color: {text_strong};")
                    except Exception:
                        pass
                storage_label = getattr(panel, "storage_label", None)
                if storage_label is not None and hasattr(storage_label, "setStyleSheet"):
                    try:
                        storage_label.setStyleSheet(f"color: {text}; font-size: 11px;")
                    except Exception:
                        pass
                caption_label = getattr(panel, "caption_label", None)
                if caption_label is not None and hasattr(caption_label, "setStyleSheet"):
                    try:
                        caption_label.setStyleSheet(f"color: {text}; font-size: 11px; padding: 2px 2px 0 2px;")
                    except Exception:
                        pass
                placeholder = getattr(panel, "placeholder", None)
                if placeholder is not None and hasattr(placeholder, "setStyleSheet"):
                    try:
                        placeholder.setStyleSheet(
                            f"background: {preview_bg}; border: 1px solid {border}; border-radius: 10px; color: {text}; padding: 18px;"
                        )
                    except Exception:
                        pass
                scroll = getattr(panel, "image_scroll", None)
                if scroll is not None and hasattr(scroll, "setStyleSheet"):
                    try:
                        scroll.setStyleSheet(
                            f"QScrollArea {{ background: {preview_bg}; border: 1px solid {border}; border-radius: 10px; }}"
                        )
                    except Exception:
                        pass
            audio_story_controller = self._audio_story_controller()
            if audio_story_controller is not None and hasattr(audio_story_controller, "apply_theme_palette"):
                try:
                    audio_story_controller.apply_theme_palette(palette)
                except Exception:
                    pass

    def _refresh_frontend_theme_controls(self):
            active_preset = _normalize_app_theme_preset_id(
                getattr(self.backend, "_active_app_theme_preset", RUNTIME_CONFIG.get("ui_theme_preset", DEFAULT_APP_THEME_PRESET))
            )
            for preset_id, button_name, edit_name in APP_THEME_PRESET_WIDGETS:
                button = self._ui_object(button_name)
                edit = self._ui_object(edit_name)
                if edit is not None and hasattr(edit, "setToolTip"):
                    edit.setToolTip("Theme note for this preset. The Apply button now switches the live app theme.")
                if button is None:
                    continue
                label = APP_THEME_PRESET_LABELS.get(preset_id, preset_id.replace("_", " ").title())
                if hasattr(button, "blockSignals"):
                    button.blockSignals(True)
                try:
                    if hasattr(button, "setCheckable"):
                        button.setCheckable(True)
                    if hasattr(button, "setChecked"):
                        button.setChecked(preset_id == active_preset)
                    if hasattr(button, "setText"):
                        button.setText(f"Applied {label}" if preset_id == active_preset else f"Apply {label}")
                    if hasattr(button, "setToolTip"):
                        button.setToolTip(
                            f"Currently active theme preset: {label}." if preset_id == active_preset else f"Apply the {label} theme preset."
                        )
                finally:
                    if hasattr(button, "blockSignals"):
                        button.blockSignals(False)

    def _apply_frontend_theme_preset(self, preset_id):
            if bool(getattr(self, "_frontend_theme_apply_in_progress", False)):
                return
            self._frontend_theme_apply_in_progress = True
            callback = getattr(self.backend, "apply_app_theme_preset", None)
            try:
                if callable(callback):
                    callback(preset_id, save_session=True)
                self._apply_theme_to_frontend_window()
                self._apply_theme_to_runtime_panels()
                self._refresh_frontend_theme_controls()
            finally:
                self._frontend_theme_apply_in_progress = False
