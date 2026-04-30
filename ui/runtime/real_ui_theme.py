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
            if self.window is not None and hasattr(self.window, "setStyleSheet"):
                try:
                    self.window.setStyleSheet(stylesheet)
                except Exception:
                    pass
                try:
                    _apply_inline_theme_styles(self.window, palette)
                    _apply_readable_input_palettes(self.window, palette)
                    _apply_engine_action_button_accents(self.window)
                except Exception:
                    pass

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
