"""Grouped shell-preview services extracted from shell_services.py."""

import json
from collections import OrderedDict
from pathlib import Path

from addons.hotkeys.shell_service import _UiShellHotkeyService


def configure_shell_services_providers_dependencies(namespace):
    globals().update(dict(namespace or {}))


class _UiShellSensoryService:
    """Shell-only sensory registry: accept metadata without capturing input."""

    def __init__(self):
        self._providers = OrderedDict()
        self._contributors = OrderedDict()

    def register_provider(
        self,
        *,
        provider_id: str,
        label: str,
        instruction: str = "",
        description: str = "",
        order: int = 1000,
        capture_handler=None,
        metadata: dict | None = None,
    ):
        provider_id = str(provider_id or "").strip()
        if not provider_id:
            raise RuntimeError("Sensory provider id is required.")
        summary = {
            "id": provider_id,
            "label": str(label or provider_id).strip() or provider_id,
            "instruction": str(instruction or "").strip(),
            "description": str(description or "").strip(),
            "order": int(order or 1000),
            "metadata": dict(metadata or {}),
            "has_capture_handler": callable(capture_handler),
            "shell_mode": True,
        }
        self._providers[provider_id] = summary
        return dict(summary)

    def unregister_provider(self, provider_id: str) -> bool:
        return self._providers.pop(str(provider_id or "").strip(), None) is not None

    def list_providers(self):
        return [
            dict(item)
            for item in sorted(self._providers.values(), key=lambda row: (int(row.get("order", 1000)), str(row.get("label") or row.get("id") or "")))
        ]

    def register_prompt_contributor(
        self,
        *,
        contributor_id: str,
        source_id: str,
        label: str,
        prompt: str = "",
        order: int = 1000,
        metadata: dict | None = None,
    ):
        contributor_id = str(contributor_id or "").strip()
        if not contributor_id:
            raise RuntimeError("Sensory prompt contributor id is required.")
        summary = {
            "id": contributor_id,
            "source_id": str(source_id or "").strip(),
            "label": str(label or contributor_id).strip() or contributor_id,
            "prompt": str(prompt or ""),
            "order": int(order or 1000),
            "metadata": dict(metadata or {}),
            "shell_mode": True,
        }
        self._contributors[contributor_id] = summary
        return dict(summary)

    def unregister_prompt_contributor(self, contributor_id: str) -> bool:
        return self._contributors.pop(str(contributor_id or "").strip(), None) is not None

    def list_prompt_contributors(self, source_id: str | None = None):
        source = str(source_id or "").strip()
        rows = list(self._contributors.values())
        if source:
            rows = [row for row in rows if str(row.get("source_id") or "").strip() == source]
        return [
            dict(item)
            for item in sorted(rows, key=lambda row: (int(row.get("order", 1000)), str(row.get("label") or row.get("id") or "")))
        ]


class _UiShellAvatarProviderService:
    """Shell-only avatar provider registry: keep factories inert."""

    def __init__(self):
        self._providers = OrderedDict()

    def register_provider(
        self,
        *,
        provider_id: str,
        label: str,
        factory,
        description: str = "",
        order: int = 1000,
        metadata: dict | None = None,
    ):
        provider_id = str(provider_id or "").strip()
        if not provider_id:
            raise RuntimeError("Avatar provider id is required.")
        summary = {
            "id": provider_id,
            "label": str(label or provider_id).strip() or provider_id,
            "description": str(description or "").strip(),
            "order": int(order or 1000),
            "metadata": dict(metadata or {}),
            "has_factory": callable(factory),
            "shell_mode": True,
        }
        self._providers[provider_id] = summary
        return dict(summary)

    def unregister_provider(self, provider_id: str) -> bool:
        return self._providers.pop(str(provider_id or "").strip(), None) is not None

    def list_providers(self):
        return [
            dict(item)
            for item in sorted(self._providers.values(), key=lambda row: (int(row.get("order", 1000)), str(row.get("label") or row.get("id") or "")))
        ]


class _UiShellChatProviderRegistry:
    """Shell-only provider registry: accept addon metadata without invoking handlers."""

    def __init__(self):
        self._providers = OrderedDict()
        self._registrations = {}

    def register_provider(
        self,
        *,
        provider_id,
        label,
        description="",
        order=1000,
        client_factory=None,
        model_list_handler=None,
        completion_handler=None,
        stream_handler=None,
        connection_check_handler=None,
        api_key_getter=None,
        base_url_getter=None,
        metadata=None,
    ):
        provider_id = str(provider_id or "").strip()
        if not provider_id:
            raise RuntimeError("Chat provider id is required.")
        summary = {
            "id": provider_id,
            "label": str(label or provider_id).strip() or provider_id,
            "description": str(description or "").strip(),
            "order": int(order or 1000),
            "metadata": dict(metadata or {}),
            "has_model_list_handler": callable(model_list_handler),
            "has_completion_handler": callable(completion_handler),
            "has_stream_handler": callable(stream_handler),
            "has_connection_check_handler": callable(connection_check_handler),
            "has_api_key_getter": callable(api_key_getter),
            "has_base_url_getter": callable(base_url_getter),
        }
        self._providers[provider_id] = summary
        self._registrations[provider_id] = {
            "client_factory": client_factory,
            "model_list_handler": model_list_handler,
            "completion_handler": completion_handler,
            "stream_handler": stream_handler,
            "connection_check_handler": connection_check_handler,
            "api_key_getter": api_key_getter,
            "base_url_getter": base_url_getter,
        }
        return dict(summary)

    def unregister_provider(self, provider_id):
        provider_id = str(provider_id or "").strip()
        existed = provider_id in self._providers
        self._providers.pop(provider_id, None)
        self._registrations.pop(provider_id, None)
        return existed

    def list_providers(self):
        return [
            dict(item)
            for item in sorted(
                self._providers.values(),
                key=lambda provider: (int(provider.get("order", 1000)), str(provider.get("label", ""))),
            )
        ]

    def provider_ids(self):
        return set(self._providers.keys())

    def get_provider_settings(self, provider_id=None):
        if provider_id:
            return {}
        return {provider_id: {} for provider_id in self._providers}

    def get_provider_setting(self, provider_id, field_id):
        return ""


class _UiShellShellService:
    """Shell-preview service: allow addon UI refresh notifications without saving state."""

    def open_local_path(self, path):
        return False

    def notify_settings_changed(self):
        return None


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

    def _initial_state(self):
        session = _read_ui_shell_session_snapshot()
        state = {
            "visual_reply_mode": str(session.get("visual_reply_mode", "auto") or "auto"),
            "visual_reply_provider": str(session.get("visual_reply_provider", "openai") or "openai"),
            "visual_reply_size": str(session.get("visual_reply_size", "1024x1024") or "1024x1024"),
            "visual_reply_model": str(session.get("visual_reply_model", "gpt-image-1") or "gpt-image-1"),
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
        if str(state["visual_reply_provider"]).strip().lower() not in {"openai", "xai"}:
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

    def settings_snapshot(self):
        prompts = self._theme_prompts()
        enabled = set(self._theme_enabled())
        return {
            "mode_value": str(self._state.get("visual_reply_mode", "auto") or "auto"),
            "provider_value": str(self._state.get("visual_reply_provider", "openai") or "openai"),
            "size_value": str(self._state.get("visual_reply_size", "1024x1024") or "1024x1024"),
            "model_name": str(self._state.get("visual_reply_model", "gpt-image-1") or "gpt-image-1"),
            "auto_show": bool(self._state.get("visual_reply_auto_show_dock", True)),
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
        return ["OpenAI", "xAI / Grok"]

    def size_labels(self):
        return ["Auto", "1024x1024", "1024x1536", "1536x1024"]

    def mode_label_from_value(self, value):
        return "Off" if str(value or "").strip().lower() == "off" else "Auto"

    def provider_label_from_value(self, value):
        provider = str(value or "").strip().lower()
        return "xAI / Grok" if provider == "xai" else "OpenAI"

    def size_label_from_value(self, value):
        size = self.normalize_size(value)
        return "Auto" if size == "auto" else size

    def normalize_size(self, value):
        size = str(value or "1024x1024").strip().lower().replace(" ", "")
        if size in {"auto", "1024x1024", "1024x1536", "1536x1024"}:
            return size
        if size in {"1024 1024", "1024*1024"}:
            return "1024x1024"
        return "1024x1024"

    def attach_settings_widgets(self, **widgets):
        self._settings_widgets = dict(widgets or {})
        self._hint_label = widgets.get("hint_label")
        for widget in widgets.values():
            if widget is not None and hasattr(widget, "setToolTip"):
                widget.setToolTip("Shell-local Visual Reply preview. Changes are not saved and no image generation is started.")

    def _set_state(self, key, value):
        self._state[str(key)] = value
        self.refresh_hint()

    def apply_mode(self, choice):
        self._set_state("visual_reply_mode", "off" if str(choice or "").strip().lower() == "off" else "auto")

    def apply_provider(self, choice):
        label = str(choice or "").strip().lower()
        self._set_state("visual_reply_provider", "xai" if "grok" in label or "xai" in label else "openai")

    def apply_size(self, choice):
        self._set_state("visual_reply_size", self.normalize_size(choice))

    def apply_model(self):
        edit = self._settings_widgets.get("model_edit")
        text = str(edit.text() if edit is not None and hasattr(edit, "text") else "").strip()
        self._set_state("visual_reply_model", text or "gpt-image-1")

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
        mode = str(snapshot.get("mode_value") or "auto")
        provider = self.provider_label_from_value(snapshot.get("provider_value"))
        model = str(snapshot.get("model_name") or "gpt-image-1")
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
