from __future__ import annotations

from addons.visual_reply.runtime import (
    configure_visual_reply_size_field,
    normalize_visual_reply_size,
    on_visual_reply_api_key_changed,
    on_visual_reply_comfyui_cleanup_changed,
    sync_visual_reply_api_key_field,
    sync_visual_reply_comfyui_cleanup_field,
    visual_reply_comfyui_cleanup_label_from_value,
    visual_reply_comfyui_cleanup_value_from_label,
    visual_reply_model_override_for_provider,
)
from addons.visual_reply.providers import (
    default_model_for_provider,
    normalize_model_for_provider,
    provider_label_from_value,
    provider_setting_from_config,
    provider_settings_from_config,
    provider_labels,
    provider_value_from_label,
    updated_provider_settings,
)
from core.addons.qt_host_services import QtRuntimeConfigService

try:
    import shiboken6
except Exception:  # pragma: no cover
    shiboken6 = None


class QtVisualReplyService:
    _STATE_KEYS = (
        "visual_reply_mode",
        "visual_reply_provider",
        "visual_reply_size",
        "visual_reply_model",
        "visual_reply_provider_settings",
        "visual_reply_auto_show_dock",
    )
    _SESSION_KEYS = _STATE_KEYS

    def __init__(self, window):
        self._window = window
        self._runtime_config = QtRuntimeConfigService(window)

    def get_runtime_config(self, key, default=None):
        return self._runtime_config.get(str(key), default)

    def update_runtime_config(self, key, value):
        return self._runtime_config.update(str(key), value)

    def _widget_alive(self, widget):
        if widget is None:
            return False
        if shiboken6 is None:
            return True
        try:
            return bool(shiboken6.isValid(widget))
        except Exception:
            return False

    def _window_widget(self, name):
        widget = getattr(self._window, str(name or ""), None)
        return widget if self._widget_alive(widget) else None

    def _provider_from_runtime(self, runtime=None):
        runtime = runtime if isinstance(runtime, dict) else self._runtime_config.snapshot()
        provider = str(runtime.get("visual_reply_provider", "openai") or "openai").strip().lower()
        if provider == "openai":
            openai_model = str(
                provider_setting_from_config(runtime, "openai", "model", "")
                or runtime.get("visual_reply_model", "")
                or ""
            ).strip().lower()
            comfy_workflow = str(provider_setting_from_config(runtime, "comfyui", "model", "") or "").strip()
            if comfy_workflow and openai_model.endswith(".json"):
                return "comfyui"
        return provider

    def _provider_from_live_combo(self):
        provider_combo = self._window_widget("visual_reply_provider_combo")
        if provider_combo is not None and hasattr(provider_combo, "currentText"):
            provider = provider_value_from_label(str(provider_combo.currentText() or ""))
            if provider:
                return str(provider).strip().lower()
        return ""

    def _live_provider(self):
        provider = self._provider_from_live_combo()
        if provider:
            return provider
        return str(
            self._provider_from_runtime()
            or getattr(self._window, "_visual_reply_active_provider", "")
            or "openai"
        ).strip().lower()

    def _capture_provider_resolution(self, runtime):
        window = self._window
        runtime_provider = str(self._provider_from_runtime(runtime) or "").strip().lower()
        active_provider = str(getattr(window, "_visual_reply_active_provider", "") or "").strip().lower()
        combo_provider = self._provider_from_live_combo()
        restoring = bool(
            getattr(window, "_restoring_session", False)
            or getattr(window, "_suspend_session_save", False)
            or getattr(window, "_visual_reply_syncing_widgets", False)
        )
        fallback_provider = runtime_provider or active_provider or combo_provider or "openai"
        resolution = {
            "runtime_provider": runtime_provider,
            "active_provider": active_provider,
            "combo_provider": combo_provider,
            "restoring": restoring,
        }
        if restoring and runtime_provider:
            resolution["reason"] = "restore_or_sync_active"
            return runtime_provider, False, resolution
        if combo_provider and combo_provider == active_provider:
            resolution["reason"] = "combo_matches_active"
            return combo_provider, True, resolution
        if combo_provider and combo_provider == runtime_provider:
            resolution["reason"] = "combo_matches_runtime"
            return combo_provider, True, resolution
        if combo_provider and runtime_provider and active_provider == runtime_provider:
            resolution["reason"] = "combo_disagrees_with_runtime_and_active"
            return runtime_provider, False, resolution
        if combo_provider:
            resolution["reason"] = "combo_only"
            return combo_provider, True, resolution
        resolution["reason"] = "runtime_fallback"
        return fallback_provider, False, resolution

    def _capture_live_provider_settings(self):
        window = self._window
        before = self._runtime_config.snapshot()
        provider, trust_widgets, _resolution = self._capture_provider_resolution(before)
        if provider:
            if trust_widgets:
                window._visual_reply_active_provider = provider
            self.update_runtime_config("visual_reply_provider", provider)
        if not trust_widgets:
            return
        size_combo = self._window_widget("visual_reply_size_combo")
        if size_combo is not None and hasattr(size_combo, "currentText"):
            size = self.normalize_size(str(size_combo.currentText() or ""), provider)
            self.update_runtime_config(
                "visual_reply_provider_settings",
                updated_provider_settings(self._runtime_config.snapshot(), provider, "size", size),
            )
            self.update_runtime_config("visual_reply_size", size)
        model_edit = self._window_widget("visual_reply_model_edit")
        if model_edit is not None and hasattr(model_edit, "text"):
            raw_model = str(model_edit.text() or "").strip()
            model = self.normalize_model_for_provider(provider, raw_model)
            self.update_runtime_config(
                "visual_reply_provider_settings",
                updated_provider_settings(
                    self._runtime_config.snapshot(),
                    provider,
                    "model",
                    visual_reply_model_override_for_provider(provider, raw_model),
                ),
            )
            self.update_runtime_config("visual_reply_model", model)
        api_key_edit = self._window_widget("visual_reply_api_key_edit")
        if api_key_edit is not None and hasattr(api_key_edit, "text"):
            self.update_runtime_config(
                "visual_reply_provider_settings",
                updated_provider_settings(self._runtime_config.snapshot(), provider, "api_key", str(api_key_edit.text() or "").strip()),
            )
        cleanup_combo = self._window_widget("visual_reply_comfyui_cleanup_combo")
        if cleanup_combo is not None and hasattr(cleanup_combo, "currentText"):
            self.update_runtime_config(
                "visual_reply_provider_settings",
                updated_provider_settings(
                    self._runtime_config.snapshot(),
                    "comfyui",
                    "cleanup_mode",
                    visual_reply_comfyui_cleanup_value_from_label(str(cleanup_combo.currentText() or "Keep cache")),
                ),
            )

    def export_session_state(self):
        self._capture_live_provider_settings()
        snapshot = self.settings_snapshot()
        payload = {
            "visual_reply_mode": str(snapshot.get("mode_value", "off") or "off"),
            "visual_reply_provider": str(snapshot.get("provider_value", "openai") or "openai"),
            "visual_reply_auto_show_dock": bool(snapshot.get("auto_show", True)),
        }
        payload["visual_reply_provider_settings"] = provider_settings_from_config(self._runtime_config.snapshot())
        return payload

    def export_preset_state(self):
        return {}

    def _set_combo_text_quietly(self, widget, text):
        if not self._widget_alive(widget):
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
        if not self._widget_alive(widget):
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
        if not self._widget_alive(widget):
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
        active_provider = self._provider_from_runtime()
        window._visual_reply_active_provider = active_provider
        previous_syncing = bool(getattr(window, "_visual_reply_syncing_widgets", False))
        window._visual_reply_syncing_widgets = True
        try:
            configure_visual_reply_size_field(self._window_widget("visual_reply_size_combo"), active_provider)
            self._set_combo_text_quietly(
                self._window_widget("visual_reply_mode_combo"),
                self.mode_label_from_value(self.get_runtime_config("visual_reply_mode", "off")),
            )
            self._set_combo_text_quietly(
                self._window_widget("visual_reply_provider_combo"),
                self.provider_label_from_value(active_provider),
            )
            self._set_combo_text_quietly(
                self._window_widget("visual_reply_size_combo"),
                self.size_label_from_value(
                    provider_setting_from_config(
                        self._runtime_config.snapshot(),
                        active_provider,
                        "size",
                        self.get_runtime_config("visual_reply_size", "1024x1024"),
                    ),
                    active_provider,
                ),
            )
            self._set_widget_text_quietly(
                self._window_widget("visual_reply_model_edit"),
                self.normalize_model_for_provider(
                    active_provider,
                    provider_setting_from_config(
                        self._runtime_config.snapshot(),
                        active_provider,
                        "model",
                        self.get_runtime_config("visual_reply_model", ""),
                    ),
                ),
            )
            sync_visual_reply_api_key_field(window, active_provider)
            sync_visual_reply_comfyui_cleanup_field(window, active_provider)
            self._set_checked_quietly(
                self._window_widget("visual_reply_auto_show_checkbox"),
                bool(self.get_runtime_config("visual_reply_auto_show_dock", True)),
            )
            self.refresh_hint()
        finally:
            window._visual_reply_syncing_widgets = previous_syncing

    def import_session_state(self, session):
        payload = dict(session or {})
        for key in self._SESSION_KEYS:
            if key in payload:
                self.update_runtime_config(key, payload.get(key))
        self.update_runtime_config("visual_reply_provider_settings", provider_settings_from_config(payload))
        if "visual_reply_mode" in payload:
            self.update_runtime_config("visual_replies_enabled", str(payload.get("visual_reply_mode") or "off").strip().lower() != "off")
        self._sync_core_widgets_from_runtime()

    def import_preset_state(self, preset):
        return None

    def settings_snapshot(self):
        runtime = self._runtime_config.snapshot()
        theme_presets = list(self._runtime_config.engine_attr("VISUAL_REPLY_STORY_THEME_PRESETS", ()) or ())
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
        provider_value = self._provider_from_runtime(runtime)
        default_model = self.default_model_for_provider(provider_value)
        return {
            "mode_value": str(runtime.get("visual_reply_mode", "off") or "off"),
            "provider_value": provider_value,
            "size_value": str(provider_setting_from_config(runtime, provider_value, "size", runtime.get("visual_reply_size", "1024x1024")) or "1024x1024"),
            "model_name": self.normalize_model_for_provider(
                provider_value,
                provider_setting_from_config(runtime, provider_value, "model", runtime.get("visual_reply_model", default_model)),
            ),
            "auto_show": bool(runtime.get("visual_reply_auto_show_dock", True)),
            "comfyui_cleanup_label": visual_reply_comfyui_cleanup_label_from_value(
                provider_setting_from_config(runtime, "comfyui", "cleanup_mode", "keep_cache")
            ),
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
        return provider_labels()

    def size_labels(self, provider=None):
        from addons.visual_reply.runtime_config import size_labels_for_provider

        return size_labels_for_provider(provider or self._provider_from_runtime())

    def comfyui_cleanup_labels(self):
        return ["Keep cache", "Free memory", "Unload models + free memory"]

    def default_model_for_provider(self, provider):
        return default_model_for_provider(provider)

    def normalize_model_for_provider(self, provider, model):
        return normalize_model_for_provider(provider, model)

    def mode_label_from_value(self, value: str):
        return self._window._visual_reply_mode_label_from_value(value)

    def provider_label_from_value(self, value: str):
        return provider_label_from_value(value)

    def size_label_from_value(self, value: str, provider=None):
        return self._window._visual_reply_size_label_from_value(value, provider)

    def normalize_size(self, value: str, provider=None):
        return normalize_visual_reply_size(value, provider or self._provider_from_runtime())

    def attach_settings_widgets(
        self,
        *,
        mode_combo,
        provider_combo,
        size_combo,
        model_edit,
        auto_show_checkbox,
        hint_label,
        api_key_edit=None,
        model_label=None,
        api_key_label=None,
        comfyui_cleanup_label=None,
        comfyui_cleanup_combo=None,
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
        if api_key_edit is not None:
            self._window.visual_reply_api_key_edit = api_key_edit
        if model_label is not None:
            self._window.visual_reply_model_label = model_label
        if api_key_label is not None:
            self._window.visual_reply_api_key_label = api_key_label
        if comfyui_cleanup_label is not None:
            self._window.visual_reply_comfyui_cleanup_label = comfyui_cleanup_label
        if comfyui_cleanup_combo is not None:
            self._window.visual_reply_comfyui_cleanup_combo = comfyui_cleanup_combo
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
        self._sync_core_widgets_from_runtime()

    def apply_mode(self, choice: str) -> None:
        self._window.on_visual_reply_mode_changed(choice)

    def apply_provider(self, choice: str) -> None:
        self._window.on_visual_reply_provider_changed(choice)

    def apply_size(self, choice: str) -> None:
        self._window.on_visual_reply_size_changed(choice)

    def apply_model(self) -> None:
        self._window.on_visual_reply_model_changed()

    def apply_api_key(self) -> None:
        on_visual_reply_api_key_changed(self._window)

    def apply_comfyui_cleanup(self, choice: str) -> None:
        on_visual_reply_comfyui_cleanup_changed(self._window, choice)

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
