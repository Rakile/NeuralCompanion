from addons.visual_reply.providers import (
    default_model_for_provider,
    model_override_for_provider,
    normalize_model_for_provider,
    provider_label_from_value,
    provider_labels,
    provider_setting_from_config,
    provider_settings_from_config,
    provider_value_from_label,
    updated_provider_settings,
)
from addons.visual_reply.runtime_config import (
    is_valid_visual_reply_size,
    normalize_visual_reply_size,
    size_labels_for_provider,
)


class _UiShellVisualReplyService:
    """Shell-only visual reply service: render settings UI without image/runtime side effects."""

    _THEME_PRESETS = (
        {"id": "realistic", "label": "Realistic", "prompt": "realistic cinematic lighting, natural textures, grounded detail"},
        {"id": "cartoon", "label": "Cartoon", "prompt": "cartoon illustration, bold shapes, clean outlines"},
        {"id": "retro", "label": "Retro", "prompt": "retro halftone print texture, vintage color palette"},
        {"id": "cyberpunk", "label": "Cyberpunk", "prompt": "neon atmosphere, vivid contrast, futuristic detail"},
        {"id": "anime", "label": "Anime", "prompt": "anime key art, expressive characters, dynamic framing"},
        {"id": "storybook", "label": "Storybook", "prompt": "illustrated fantasy look, painterly storybook texture"},
    )

    def __init__(self, window):
        self._window = window
        self._state = self._initial_state()
        self._hint_label = None
        self._settings_widgets = {}
        self._panel = None

    def _session_snapshot(self):
        from ui.runtime.shell_addon_reports import _read_ui_shell_session_snapshot

        return _read_ui_shell_session_snapshot()

    def _initial_state(self):
        session = self._session_snapshot()
        provider = str(session.get("visual_reply_provider", "openai") or "openai").strip().lower()
        default_model = self.default_model_for_provider(provider)
        state = {
            "visual_reply_mode": str(session.get("visual_reply_mode", "off") or "off"),
            "visual_reply_provider": provider,
            "visual_reply_provider_settings": provider_settings_from_config(session),
            "visual_reply_size": str(provider_setting_from_config(session, provider, "size", session.get("visual_reply_size", "1024x1024")) or "1024x1024"),
            "visual_reply_model": str(provider_setting_from_config(session, provider, "model", session.get("visual_reply_model", default_model)) or default_model),
            "visual_reply_auto_show_dock": bool(session.get("visual_reply_auto_show_dock", True)),
            "visual_reply_story_mode": bool(session.get("visual_reply_story_mode", False)),
            "visual_reply_story_max_images": session.get("visual_reply_story_max_images", 3),
            "visual_reply_story_continuity_strength": session.get("visual_reply_story_continuity_strength", 0.8),
            "visual_reply_story_theme_prompts": dict(session.get("visual_reply_story_theme_prompts") or {}),
            "visual_reply_story_theme_enabled": list(session.get("visual_reply_story_theme_enabled") or []),
            "visual_reply_master_style_prompt": str(session.get("visual_reply_master_style_prompt", "") or ""),
            "visual_reply_master_prompt_safe": bool(session.get("visual_reply_master_prompt_safe", False)),
            "visual_reply_master_prompt_no_speech_bubbles": bool(session.get("visual_reply_master_prompt_no_speech_bubbles", False)),
        }
        if str(state["visual_reply_provider"]).strip().lower() not in {"openai", "xai", "runware", "comfyui"}:
            state["visual_reply_provider"] = "openai"
        return state

    def _theme_prompts(self):
        raw = dict(self._state.get("visual_reply_story_theme_prompts") or {})
        prompts = {}
        for theme in self._THEME_PRESETS:
            theme_id = str(theme.get("id") or "").strip().lower()
            if theme_id:
                prompts[theme_id] = str(raw.get(theme_id, theme.get("prompt", "")) or theme.get("prompt", "")).strip()
        return prompts

    def _theme_enabled(self):
        raw = self._state.get("visual_reply_story_theme_enabled", [])
        if isinstance(raw, (str, bytes)):
            raw = [raw]
        if not isinstance(raw, (list, tuple, set)):
            raw = []
        valid = {str(theme.get("id") or "").strip().lower() for theme in self._THEME_PRESETS}
        enabled = []
        seen = set()
        for item in raw:
            theme_id = str(item or "").strip().lower()
            if theme_id in valid and theme_id not in seen:
                enabled.append(theme_id)
                seen.add(theme_id)
        return enabled

    def _story_continuity_strength(self):
        try:
            value = float(self._state.get("visual_reply_story_continuity_strength", 0.8) or 0.8)
        except Exception:
            value = 0.8
        if value > 1.0:
            value = value / 100.0
        return max(0.0, min(1.0, value))

    def _story_max_images(self):
        try:
            return max(1, int(self._state.get("visual_reply_story_max_images", 3) or 3))
        except Exception:
            return 3

    def story_theme_presets(self):
        return [dict(theme) for theme in self._THEME_PRESETS]

    def get_runtime_config(self, key, default=None):
        return self._state.get(str(key), default)

    def update_runtime_config(self, key, value):
        self._set_state(str(key), value)

    def export_session_state(self):
        snapshot = self.settings_snapshot()
        provider = str(snapshot.get("provider_value", "openai") or "openai")
        return {
            "visual_reply_mode": str(snapshot.get("mode_value", "off") or "off"),
            "visual_reply_provider": provider,
            "visual_reply_auto_show_dock": bool(snapshot.get("auto_show", True)),
            "visual_reply_provider_settings": provider_settings_from_config(self._state),
        }

    def export_preset_state(self):
        return {}

    def import_session_state(self, session):
        payload = dict(session or {})
        for key in (
            "visual_reply_mode",
            "visual_reply_provider",
            "visual_reply_size",
            "visual_reply_model",
            "visual_reply_provider_settings",
            "visual_reply_auto_show_dock",
        ):
            if key in payload:
                self._state[key] = payload.get(key)
        self._state["visual_reply_provider_settings"] = provider_settings_from_config(payload)
        self.refresh_hint()

    def import_preset_state(self, preset):
        return None

    def settings_snapshot(self):
        prompts = self._theme_prompts()
        enabled = set(self._theme_enabled())
        provider = str(self._state.get("visual_reply_provider", "openai") or "openai").strip().lower()
        default_model = self.default_model_for_provider(provider)
        return {
            "mode_value": str(self._state.get("visual_reply_mode", "off") or "off"),
            "provider_value": provider,
            "size_value": str(provider_setting_from_config(self._state, provider, "size", self._state.get("visual_reply_size", "1024x1024")) or "1024x1024"),
            "model_name": normalize_model_for_provider(
                provider,
                provider_setting_from_config(self._state, provider, "model", self._state.get("visual_reply_model", default_model)),
            ),
            "auto_show": bool(self._state.get("visual_reply_auto_show_dock", True)),
            "comfyui_cleanup_label": self._comfyui_cleanup_label(),
            "master_style_prompt": str(self._state.get("visual_reply_master_style_prompt", "") or ""),
            "master_prompt_safe": bool(self._state.get("visual_reply_master_prompt_safe", False)),
            "master_prompt_no_speech_bubbles": bool(self._state.get("visual_reply_master_prompt_no_speech_bubbles", False)),
            "story_mode": bool(self._state.get("visual_reply_story_mode", False)),
            "story_max_images": self._story_max_images(),
            "story_continuity_strength": self._story_continuity_strength(),
            "story_themes": [
                {
                    "id": str(theme.get("id") or "").strip().lower(),
                    "label": str(theme.get("label") or theme.get("id") or "").strip(),
                    "prompt": prompts.get(str(theme.get("id") or "").strip().lower(), ""),
                    "enabled": str(theme.get("id") or "").strip().lower() in enabled,
                }
                for theme in self._THEME_PRESETS
            ],
        }

    def mode_labels(self):
        return ["Off", "Auto"]

    def provider_labels(self):
        return provider_labels()

    def size_labels(self, provider=None):
        provider = provider or self._state.get("visual_reply_provider", "openai")
        return size_labels_for_provider(provider)

    def comfyui_cleanup_labels(self):
        return ["Keep cache", "Free memory", "Unload models + free memory"]

    def _comfyui_cleanup_label(self):
        value = str(provider_setting_from_config(self._state, "comfyui", "cleanup_mode", "keep_cache") or "keep_cache").strip().lower()
        if value == "unload_models":
            return "Unload models + free memory"
        if value == "free_memory":
            return "Free memory"
        return "Keep cache"

    def default_model_for_provider(self, provider):
        return default_model_for_provider(provider)

    def mode_label_from_value(self, value):
        return "Off" if str(value or "").strip().lower() == "off" else "Auto"

    def provider_label_from_value(self, value):
        return provider_label_from_value(value)

    def size_label_from_value(self, value, provider=None):
        size = self.normalize_size(value, provider)
        return "Auto" if size == "auto" else size

    def normalize_size(self, value, provider=None):
        provider = provider or self._state.get("visual_reply_provider", "openai")
        return normalize_visual_reply_size(value, provider)

    def _sync_size_combo_for_provider(self, provider=None):
        provider = str(provider or self._state.get("visual_reply_provider", "openai") or "openai").strip().lower()
        size_combo = self._settings_widgets.get("size_combo")
        if size_combo is None:
            return
        current_text = str(size_combo.currentText() if hasattr(size_combo, "currentText") else "").strip()
        previous = False
        try:
            if hasattr(size_combo, "blockSignals"):
                previous = bool(size_combo.blockSignals(True))
            if hasattr(size_combo, "setEditable"):
                size_combo.setEditable(provider == "comfyui")
            if hasattr(size_combo, "clear") and hasattr(size_combo, "addItems"):
                size_combo.clear()
                size_combo.addItems(self.size_labels(provider))
            size = self.normalize_size(current_text or provider_setting_from_config(self._state, provider, "size", "1024x1024"), provider)
            if hasattr(size_combo, "setCurrentText"):
                size_combo.setCurrentText(self.size_label_from_value(size, provider))
        finally:
            try:
                size_combo.blockSignals(previous)
            except Exception:
                pass

    def attach_settings_widgets(self, **widgets):
        self._settings_widgets = dict(widgets or {})
        self._hint_label = widgets.get("hint_label")
        for widget in widgets.values():
            if widget is not None and hasattr(widget, "setToolTip"):
                widget.setToolTip("Shell-local Visual Reply preview. Changes are not saved and no image generation is started.")
        self._sync_size_combo_for_provider()
        self.sync_api_key_field()

    def _set_state(self, key, value):
        self._state[str(key)] = value
        self.refresh_hint()

    def apply_mode(self, choice):
        self._set_state("visual_reply_mode", "off" if str(choice or "").strip().lower() == "off" else "auto")

    def apply_provider(self, choice):
        previous_provider = str(self._state.get("visual_reply_provider", "openai") or "openai").strip().lower()
        size_combo = self._settings_widgets.get("size_combo")
        if size_combo is not None and hasattr(size_combo, "currentText"):
            self._state["visual_reply_provider_settings"] = updated_provider_settings(
                self._state,
                previous_provider,
                "size",
                self.normalize_size(size_combo.currentText(), previous_provider),
            )
        edit = self._settings_widgets.get("model_edit")
        if edit is not None and hasattr(edit, "text"):
            current_model = str(edit.text() or "").strip()
            self._state["visual_reply_provider_settings"] = updated_provider_settings(
                self._state,
                previous_provider,
                "model",
                model_override_for_provider(previous_provider, current_model),
            )
        provider = provider_value_from_label(choice)
        self._set_state("visual_reply_provider", provider)
        if size_combo is not None and hasattr(size_combo, "setCurrentText"):
            size = self.normalize_size(provider_setting_from_config(self._state, provider, "size", "1024x1024"), provider)
            self._sync_size_combo_for_provider(provider)
            size_combo.setCurrentText(self.size_label_from_value(size, provider))
            self._state["visual_reply_provider_settings"] = updated_provider_settings(self._state, provider, "size", size)
            self._state["visual_reply_size"] = size
        if edit is not None and hasattr(edit, "text") and hasattr(edit, "setText"):
            model = str(provider_setting_from_config(self._state, provider, "model", "") or "").strip() or self.default_model_for_provider(provider)
            edit.setText(model)
            self._state["visual_reply_model"] = model
        self.sync_api_key_field(provider)

    def apply_size(self, choice):
        provider = str(self._state.get("visual_reply_provider", "openai") or "openai").strip().lower()
        raw_choice = str(choice or "").strip()
        if provider == "comfyui" and raw_choice and not is_valid_visual_reply_size(raw_choice, provider):
            return
        size = self.normalize_size(choice, provider)
        self._state["visual_reply_provider_settings"] = updated_provider_settings(self._state, provider, "size", size)
        self._set_state("visual_reply_size", size)

    def apply_model(self):
        edit = self._settings_widgets.get("model_edit")
        text = str(edit.text() if edit is not None and hasattr(edit, "text") else "").strip()
        provider = str(self._state.get("visual_reply_provider", "openai") or "openai").strip().lower()
        default_model = self.default_model_for_provider(provider)
        if text:
            model = normalize_model_for_provider(provider, text)
            self._state["visual_reply_provider_settings"] = updated_provider_settings(self._state, provider, "model", model_override_for_provider(provider, model))
            self._set_state("visual_reply_model", model)
        else:
            self._state["visual_reply_provider_settings"] = updated_provider_settings(self._state, provider, "model", "")
            self._set_state("visual_reply_model", default_model)

    def apply_api_key(self):
        edit = self._settings_widgets.get("api_key_edit")
        provider = str(self._state.get("visual_reply_provider", "openai") or "openai").strip().lower()
        self._set_state(
            "visual_reply_provider_settings",
            updated_provider_settings(self._state, provider, "api_key", str(edit.text() if edit is not None and hasattr(edit, "text") else "").strip()),
        )

    def apply_comfyui_cleanup(self, choice):
        text = str(choice or "").strip().lower()
        if "unload" in text:
            mode = "unload_models"
        elif "free" in text:
            mode = "free_memory"
        else:
            mode = "keep_cache"
        self._set_state(
            "visual_reply_provider_settings",
            updated_provider_settings(self._state, "comfyui", "cleanup_mode", mode),
        )

    def sync_api_key_field(self, provider=None):
        edit = self._settings_widgets.get("api_key_edit")
        if edit is None or not hasattr(edit, "setText"):
            return
        provider = str(provider or self._state.get("visual_reply_provider", "openai") or "openai").strip().lower()
        label = self.provider_label_from_value(provider)
        edit.setText(str(provider_setting_from_config(self._state, provider, "api_key", "") or ""))
        if hasattr(edit, "setPlaceholderText"):
            if provider == "comfyui":
                edit.setPlaceholderText("http://127.0.0.1:8188")
            else:
                edit.setPlaceholderText(f"{label} API key (optional)")
        if hasattr(edit, "setToolTip"):
            if provider == "comfyui":
                edit.setToolTip("Shell-local ComfyUI server URL preview. No network call is made.")
            else:
                edit.setToolTip(f"Shell-local {label} API key preview. No network call is made.")

    def apply_auto_show(self, checked):
        self._set_state("visual_reply_auto_show_dock", bool(checked))

    def apply_story_mode(self, checked):
        self._set_state("visual_reply_story_mode", bool(checked))

    def apply_story_max_images(self, value):
        try:
            self._set_state("visual_reply_story_max_images", max(1, int(value or 1)))
        except Exception:
            self._set_state("visual_reply_story_max_images", 3)

    def apply_story_continuity_strength(self, value):
        try:
            strength = max(0.0, min(1.0, float(value or 0) / 100.0))
        except Exception:
            strength = 0.8
        self._set_state("visual_reply_story_continuity_strength", strength)

    def apply_story_theme_toggle(self, theme_id, checked):
        enabled = set(self._theme_enabled())
        theme_id = str(theme_id or "").strip().lower()
        if checked:
            enabled.add(theme_id)
        else:
            enabled.discard(theme_id)
        self._set_state("visual_reply_story_theme_enabled", sorted(enabled))

    def apply_story_theme_text(self, theme_id, text):
        prompts = self._theme_prompts()
        theme_id = str(theme_id or "").strip().lower()
        if theme_id:
            prompts[theme_id] = str(text or "").strip()
        self._set_state("visual_reply_story_theme_prompts", prompts)

    def refresh_hint(self):
        label = self._hint_label
        if label is None or not hasattr(label, "setText"):
            return
        snapshot = self.settings_snapshot()
        mode = str(snapshot.get("mode_value") or "off")
        provider = self.provider_label_from_value(snapshot.get("provider_value"))
        model = str(snapshot.get("model_name") or self.default_model_for_provider(snapshot.get("provider_value")))
        label.setText(
            "Shell-local Visual Reply settings preview. "
            f"Mode: {mode}; Provider: {provider}; Model: {model}. "
            "No image generation, dock replacement, or session save is connected."
        )

    def replace_panel(self, panel):
        self._panel = panel
        try:
            timer = getattr(panel, "poll_timer", None)
            if timer is not None and hasattr(timer, "stop"):
                timer.stop()
        except Exception:
            pass
        try:
            panel.setParent(self._window)
            panel.hide()
        except Exception:
            pass
        for name in (
            "prev_button",
            "load_button",
            "next_button",
            "load_story_button",
            "use_style_button",
            "caption_button",
            "delete_button",
            "clear_button",
            "delete_all_button",
        ):
            try:
                button = getattr(panel, name, None)
                if button is not None:
                    button.setEnabled(False)
                    button.setToolTip("Disabled in the main.ui shell preview; Visual Reply dock/image history remains Designer-owned.")
            except Exception:
                pass
        return False

    def show(self):
        return None

    def hide(self):
        return None

    def clear(self, *args, **kwargs):
        return False

    def set_loading(self, *args, **kwargs):
        return False

    def show_image(self, *args, **kwargs):
        return False
