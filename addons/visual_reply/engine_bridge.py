from __future__ import annotations

from pathlib import Path

from addons.visual_reply import generation, runtime_config


class VisualReplyEngineBridge:
    VISUAL_REPLY_TAG_RE = runtime_config.VISUAL_REPLY_TAG_RE
    VISUAL_REPLY_TAG_START_RE = runtime_config.VISUAL_REPLY_TAG_START_RE
    VISUAL_REPLY_XAI_BASE_URL = runtime_config.VISUAL_REPLY_XAI_BASE_URL
    VISUAL_REPLY_STORY_THEME_PRESETS = runtime_config.VISUAL_REPLY_STORY_THEME_PRESETS

    def __init__(self, config_getter, *, environ=None, output_dir=None):
        self.runtime = runtime_config.VisualReplyRuntime(config_getter, environ=environ)
        self.generation_service = generation.VisualReplyGenerationService(
            self.runtime,
            output_dir=Path(output_dir) if output_dir is not None else generation.output_dir(),
        )

    def default_story_theme_prompts(self):
        return runtime_config.default_story_theme_prompts()

    def mode(self):
        return self.runtime.mode()

    def enabled(self):
        return self.runtime.enabled()

    def generation_available(self):
        return self.runtime.generation_available()

    def story_mode_enabled(self):
        return self.runtime.story_mode_enabled()

    def story_max_images(self):
        return self.runtime.story_max_images()

    def story_continuity_strength(self):
        return self.runtime.story_continuity_strength()

    def story_theme_prompts(self):
        return self.runtime.story_theme_prompts()

    def story_theme_enabled(self):
        return self.runtime.story_theme_enabled()

    def story_theme_suffix(self):
        return self.runtime.story_theme_suffix()

    def master_style_prompt(self):
        return self.runtime.master_style_prompt()

    def master_style_suffix(self):
        return self.runtime.master_style_suffix()

    def master_prompt_safety_suffix(self):
        return self.runtime.master_prompt_safety_suffix()

    def no_speech_bubbles_suffix(self):
        return self.runtime.no_speech_bubbles_suffix()

    def apply_style_anchor(self, prompt_text: str):
        return self.runtime.apply_style_anchor(prompt_text)

    def ensure_story_worker(self):
        return self.generation_service._ensure_story_worker()

    def begin_story_session(self):
        return self.generation_service.begin_story_session()

    def clear_story_queue(self):
        return self.generation_service.clear_story_queue()

    def enqueue_story_generation(self, prompt: str, *, source_text: str = "", session_id: int | None = None, request_id: str | None = None):
        return self.generation_service.enqueue_story_generation(
            prompt,
            source_text=source_text,
            session_id=session_id,
            request_id=request_id,
        )

    def perform_generation(self, prompt_text: str, *, source_text: str = "", request_id: str | None = None, keep_current_image: bool = False):
        return self.generation_service.perform_generation(
            prompt_text,
            source_text=source_text,
            request_id=request_id,
            keep_current_image=keep_current_image,
        )

    def story_style_guide_from_text(self, story_text: str, continuity_strength: float = 0.8):
        return self.generation_service.story_style_guide_from_text(
            story_text,
            continuity_strength=continuity_strength,
        )

    def story_prompt_from_text(self, prompt_text: str, emotion: str = "", story_style_guide: str = ""):
        return self.generation_service.story_prompt_from_text(
            prompt_text,
            emotion=emotion,
            story_style_guide=story_style_guide,
        )

    def next_request_id(self):
        return self.generation_service.next_request_id()

    def normalize_prompt_text(self, prompt_text: str) -> str:
        return runtime_config.normalize_prompt_text(prompt_text)

    def strip_visual_reply_tail(self, text: str):
        return runtime_config.strip_visual_reply_tail(text)

    def extract_visual_reply_prompt(self, text: str):
        return runtime_config.extract_visual_reply_prompt(text)


def create_engine_bridge(config_getter, *, environ=None, output_dir=None):
    return VisualReplyEngineBridge(config_getter, environ=environ, output_dir=output_dir)
