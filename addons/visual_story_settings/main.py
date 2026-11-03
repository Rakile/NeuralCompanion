from core.addons.base import BaseAddon


_KEYS = (
    "visual_reply_story_mode",
    "visual_reply_story_max_images",
    "visual_reply_story_continuity_strength",
    "visual_reply_story_theme_enabled",
    "visual_reply_story_theme_prompts",
    "visual_reply_master_style_prompt",
    "visual_reply_master_prompt_safe",
    "visual_reply_master_prompt_no_speech_bubbles",
)


class Addon(BaseAddon):
    """Persist story-visual settings without constructing a settings widget."""

    def initialize(self, context):
        super().initialize(context)
        self._runtime_config = context.capabilities.runtime_config

    def export_session_state(self):
        if self._runtime_config is None:
            return {}
        snapshot = dict(self._runtime_config.snapshot() or {})
        return {key: snapshot[key] for key in _KEYS if key in snapshot}

    def import_session_state(self, payload):
        if self._runtime_config is None:
            return None
        source = dict(payload or {})
        for key in _KEYS:
            if key in source:
                self._runtime_config.update(key, source[key])
        return None

    def shutdown(self):
        self._runtime_config = None
