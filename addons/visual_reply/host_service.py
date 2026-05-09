from __future__ import annotations


class QtVisualReplyService:
    _STATE_KEYS = (
        "visual_reply_mode",
        "visual_reply_provider",
        "visual_reply_size",
        "visual_reply_model",
        "visual_reply_auto_show_dock",
    )

    def __init__(self, window):
        self._window = window

    def get_runtime_config(self, key, default=None):
        import engine

        return (getattr(engine, "RUNTIME_CONFIG", {}) or {}).get(str(key), default)

    def update_runtime_config(self, key, value):
        import engine

        return engine.update_runtime_config(str(key), value)

    def export_session_state(self):
        snapshot = self.settings_snapshot()
        return {
            "visual_reply_mode": str(snapshot.get("mode_value", "auto") or "auto"),
            "visual_reply_provider": str(snapshot.get("provider_value", "openai") or "openai"),
            "visual_reply_size": str(snapshot.get("size_value", "1024x1024") or "1024x1024"),
            "visual_reply_model": str(snapshot.get("model_name", "gpt-image-1") or "gpt-image-1"),
            "visual_reply_auto_show_dock": bool(snapshot.get("auto_show", True)),
        }

    def export_preset_state(self):
        return self.export_session_state()

    def _set_combo_text_quietly(self, widget, text):
        if widget is None:
            return
        previous = False
        try:
            previous = bool(widget.blockSignals(True))
            widget.setCurrentText(str(text or ""))
        finally:
            try:
                widget.blockSignals(previous)
            except Exception:
                pass

    def _set_widget_text_quietly(self, widget, text):
        if widget is None:
            return
        previous = False
        try:
            previous = bool(widget.blockSignals(True))
            widget.setText(str(text or ""))
        finally:
            try:
                widget.blockSignals(previous)
            except Exception:
                pass

    def _set_checked_quietly(self, widget, checked):
        if widget is None:
            return
        previous = False
        try:
            previous = bool(widget.blockSignals(True))
            widget.setChecked(bool(checked))
        finally:
            try:
                widget.blockSignals(previous)
            except Exception:
                pass

    def _sync_core_widgets_from_runtime(self):
        window = self._window
        self._set_combo_text_quietly(
            getattr(window, "visual_reply_mode_combo", None),
            self.mode_label_from_value(self.get_runtime_config("visual_reply_mode", "auto")),
        )
        self._set_combo_text_quietly(
            getattr(window, "visual_reply_provider_combo", None),
            self.provider_label_from_value(self.get_runtime_config("visual_reply_provider", "openai")),
        )
        self._set_combo_text_quietly(
            getattr(window, "visual_reply_size_combo", None),
            self.size_label_from_value(self.get_runtime_config("visual_reply_size", "1024x1024")),
        )
        self._set_widget_text_quietly(
            getattr(window, "visual_reply_model_edit", None),
            str(self.get_runtime_config("visual_reply_model", "gpt-image-1") or "gpt-image-1"),
        )
        self._set_checked_quietly(
            getattr(window, "visual_reply_auto_show_checkbox", None),
            bool(self.get_runtime_config("visual_reply_auto_show_dock", True)),
        )
        self.refresh_hint()

    def import_session_state(self, session):
        payload = dict(session or {})
        for key in self._STATE_KEYS:
            if key in payload:
                self.update_runtime_config(key, payload.get(key))
        if "visual_reply_mode" in payload:
            self.update_runtime_config("visual_replies_enabled", str(payload.get("visual_reply_mode") or "auto").strip().lower() != "off")
        self._sync_core_widgets_from_runtime()

    def import_preset_state(self, preset):
        return self.import_session_state(preset)

    def settings_snapshot(self):
        import engine

        runtime = getattr(engine, "RUNTIME_CONFIG", {}) or {}
        theme_presets = list(getattr(engine, "VISUAL_REPLY_STORY_THEME_PRESETS", ()) or ())
        raw_theme_prompts = runtime.get("visual_reply_story_theme_prompts", {})
        if not isinstance(raw_theme_prompts, dict):
            raw_theme_prompts = {}
        raw_theme_enabled = runtime.get("visual_reply_story_theme_enabled", [])
        if isinstance(raw_theme_enabled, (str, bytes)):
            raw_theme_enabled = [raw_theme_enabled]
        if not isinstance(raw_theme_enabled, (list, tuple, set)):
            raw_theme_enabled = []
        theme_enabled = {str(item or "").strip().lower() for item in raw_theme_enabled}
        try:
            story_max_images = max(1, int(runtime.get("visual_reply_story_max_images", 3) or 3))
        except Exception:
            story_max_images = 3
        try:
            story_continuity_strength = float(runtime.get("visual_reply_story_continuity_strength", 0.8) or 0.8)
        except Exception:
            story_continuity_strength = 0.8
        if story_continuity_strength > 1.0:
            story_continuity_strength = story_continuity_strength / 100.0
        story_continuity_strength = max(0.0, min(1.0, story_continuity_strength))
        return {
            "mode_value": str(runtime.get("visual_reply_mode", "auto") or "auto"),
            "provider_value": str(runtime.get("visual_reply_provider", "openai") or "openai"),
            "size_value": str(runtime.get("visual_reply_size", "1024x1024") or "1024x1024"),
            "model_name": str(runtime.get("visual_reply_model", "gpt-image-1") or "gpt-image-1"),
            "auto_show": bool(runtime.get("visual_reply_auto_show_dock", True)),
            "master_prompt_safe": bool(runtime.get("visual_reply_master_prompt_safe", False)),
            "master_prompt_no_speech_bubbles": bool(runtime.get("visual_reply_master_prompt_no_speech_bubbles", False)),
            "story_mode": bool(runtime.get("visual_reply_story_mode", False)),
            "story_max_images": story_max_images,
            "story_continuity_strength": story_continuity_strength,
            "story_themes": [
                {
                    "id": str(theme.get("id") or "").strip().lower(),
                    "label": str(theme.get("label") or theme.get("id") or "").strip(),
                    "prompt": str(raw_theme_prompts.get(str(theme.get("id") or "").strip().lower(), theme.get("prompt", "")) or theme.get("prompt", "")).strip(),
                    "enabled": str(theme.get("id") or "").strip().lower() in theme_enabled,
                }
                for theme in theme_presets
                if str(theme.get("id") or "").strip()
            ],
        }

    def mode_labels(self):
        return ["Off", "Auto"]

    def provider_labels(self):
        return ["OpenAI", "xAI / Grok"]

    def size_labels(self):
        return ["Auto", "1024x1024", "1024x1536", "1536x1024"]

    def mode_label_from_value(self, value: str):
        return self._window._visual_reply_mode_label_from_value(value)

    def provider_label_from_value(self, value: str):
        return self._window._visual_reply_provider_label_from_value(value)

    def size_label_from_value(self, value: str):
        return self._window._visual_reply_size_label_from_value(value)

    def normalize_size(self, value: str):
        return self._window._normalize_visual_reply_size(value)

    def attach_settings_widgets(
        self,
        *,
        mode_combo,
        provider_combo,
        size_combo,
        model_edit,
        auto_show_checkbox,
        hint_label,
        story_mode_button=None,
        story_max_images_spin=None,
        story_continuity_slider=None,
        story_continuity_value_label=None,
        story_theme_buttons=None,
        story_theme_edits=None,
    ) -> None:
        self._window.visual_reply_mode_combo = mode_combo
        self._window.visual_reply_provider_combo = provider_combo
        self._window.visual_reply_size_combo = size_combo
        self._window.visual_reply_model_edit = model_edit
        self._window.visual_reply_auto_show_checkbox = auto_show_checkbox
        self._window.visual_reply_hint = hint_label
        if story_mode_button is not None:
            self._window.visual_reply_story_mode_button = story_mode_button
        if story_max_images_spin is not None:
            self._window.visual_reply_story_max_images_spin = story_max_images_spin
        if story_continuity_slider is not None:
            self._window.visual_reply_story_continuity_slider = story_continuity_slider
        if story_continuity_value_label is not None:
            self._window.visual_reply_story_continuity_value_label = story_continuity_value_label
        if story_theme_buttons is not None:
            self._window.visual_reply_story_theme_buttons = dict(story_theme_buttons or {})
        if story_theme_edits is not None:
            self._window.visual_reply_story_theme_edits = dict(story_theme_edits or {})

    def apply_mode(self, choice: str) -> None:
        self._window.on_visual_reply_mode_changed(choice)

    def apply_provider(self, choice: str) -> None:
        self._window.on_visual_reply_provider_changed(choice)

    def apply_size(self, choice: str) -> None:
        self._window.on_visual_reply_size_changed(choice)

    def apply_model(self) -> None:
        self._window.on_visual_reply_model_changed()

    def apply_auto_show(self, checked: bool) -> None:
        self._window.on_visual_reply_auto_show_changed(bool(checked))

    def apply_story_mode(self, checked: bool) -> None:
        self._window.on_visual_reply_story_mode_changed(bool(checked))

    def apply_story_max_images(self, value: int) -> None:
        self._window.on_visual_reply_story_max_images_changed(int(value))

    def apply_story_continuity_strength(self, value: int) -> None:
        self._window.on_visual_reply_story_continuity_strength_changed(int(value))

    def apply_story_theme_toggle(self, theme_id: str, checked: bool) -> None:
        self._window.on_visual_reply_story_theme_toggled(str(theme_id or ""), bool(checked))

    def apply_story_theme_text(self, theme_id: str, text: str) -> None:
        self._window.on_visual_reply_story_theme_text_changed(str(theme_id or ""), str(text or ""))

    def refresh_hint(self) -> None:
        self._window._refresh_visual_reply_hint()

    def replace_panel(self, panel) -> bool:
        dock = getattr(self._window, "visual_reply_dock", None)
        if dock is None or panel is None:
            return False
        old_widget = dock.widget()
        try:
            load_signal = getattr(panel, "loadRequested", None)
            if load_signal is not None:
                load_signal.connect(self._window.prompt_visual_reply_image)
        except Exception:
            pass
        try:
            caption_signal = getattr(panel, "captionRequested", None)
            if caption_signal is not None:
                caption_signal.connect(self._window.prompt_visual_reply_caption)
        except Exception:
            pass
        try:
            clear_signal = getattr(panel, "clearRequested", None)
            if clear_signal is not None:
                clear_signal.connect(lambda: self._window.clear_visual_reply(auto_show=False))
        except Exception:
            pass
        dock.setWidget(panel)
        self._window.visual_reply_panel = panel
        if old_widget is not None and old_widget is not panel:
            try:
                old_widget.deleteLater()
            except Exception:
                pass
        return True

    def show(self) -> None:
        self._window.show_visual_reply_dock()

    def hide(self) -> None:
        dock = getattr(self._window, 'visual_reply_dock', None)
        if dock is not None:
            dock.hide()

    def clear(self, status_text: str = "Visual Reply idle", detail_text: str = "No visual reply yet.\nWhen NC creates an image, it will appear here.", auto_show: bool = False) -> bool:
        return bool(self._window.clear_visual_reply(status_text=status_text, detail_text=detail_text, auto_show=auto_show))

    def set_loading(self, status_text: str = "Visual Reply generating...", detail_text: str = "Preparing image...", auto_show: bool = True) -> bool:
        return bool(self._window.set_visual_reply_loading(status_text=status_text, detail_text=detail_text, auto_show=auto_show))

    def show_image(self, image_path: str, caption: str = "", status_text: str = "Visual Reply", auto_show: bool = True) -> bool:
        return bool(self._window.show_visual_reply_image(image_path, caption=caption, status_text=status_text, auto_show=auto_show))
