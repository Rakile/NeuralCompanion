"""Widget-free Visual Reply capabilities consumed by the core runtime."""

from __future__ import annotations

from pathlib import Path
import time

from addons.visual_reply import generation, runtime_config, state
from core.runtime.contracts import CancellationToken, RuntimeFailure


class VisualReplyRuntimeCapabilities:
    VISUAL_REPLY_TAG_RE = runtime_config.VISUAL_REPLY_TAG_RE
    VISUAL_REPLY_TAG_START_RE = runtime_config.VISUAL_REPLY_TAG_START_RE
    VISUAL_REPLY_XAI_BASE_URL = runtime_config.VISUAL_REPLY_XAI_BASE_URL
    VISUAL_REPLY_STORY_THEME_PRESETS = runtime_config.VISUAL_REPLY_STORY_THEME_PRESETS

    def __init__(self, config_source, *, environ=None, output_dir=None, publication_gate=None) -> None:
        snapshot = getattr(config_source, "snapshot", None)
        if not callable(snapshot):
            raise TypeError("Visual Reply runtime configuration requires snapshot().")
        self._environ = environ
        self.runtime = runtime_config.VisualReplyRuntime(snapshot, environ=environ)
        self.generation_service = generation.VisualReplyGenerationService(
            self.runtime,
            output_dir=Path(output_dir) if output_dir is not None else generation.output_dir(),
        )
        self._publication_gate = publication_gate

    def default_story_theme_prompts(self): return runtime_config.default_story_theme_prompts()
    def mode(self): return self.runtime.mode()
    def enabled(self): return self.runtime.enabled()
    def generation_available(self): return self.runtime.generation_available()
    def story_mode_enabled(self): return self.runtime.story_mode_enabled()
    def story_max_images(self): return self.runtime.story_max_images()
    def story_continuity_strength(self): return self.runtime.story_continuity_strength()
    def story_theme_prompts(self): return self.runtime.story_theme_prompts()
    def story_theme_enabled(self): return self.runtime.story_theme_enabled()
    def story_theme_suffix(self): return self.runtime.story_theme_suffix()
    def master_style_prompt(self): return self.runtime.master_style_prompt()
    def master_style_suffix(self): return self.runtime.master_style_suffix()
    def master_prompt_safety_suffix(self): return self.runtime.master_prompt_safety_suffix()
    def no_speech_bubbles_suffix(self): return self.runtime.no_speech_bubbles_suffix()
    def apply_style_anchor(self, prompt_text: str): return self.runtime.apply_style_anchor(prompt_text)
    def next_request_id(self): return self.generation_service.next_request_id()
    def normalize_prompt_text(self, prompt_text: str) -> str: return runtime_config.normalize_prompt_text(prompt_text)
    def strip_visual_reply_tail(self, text: str): return runtime_config.strip_visual_reply_tail(text)
    def looks_like_visual_reply_tag_prefix(self, fragment): return runtime_config.looks_like_visual_reply_tag_prefix(fragment)
    def extract_visual_reply_prompt(self, text: str): return runtime_config.extract_visual_reply_prompt(text)

    def enabled_for(self, config):
        frozen = dict(config or {})
        return runtime_config.VisualReplyRuntime(lambda: frozen, environ=self._environ).enabled()

    def generation_available_for(self, config):
        frozen = dict(config or {})
        return runtime_config.VisualReplyRuntime(lambda: frozen, environ=self._environ).generation_available()

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

    def publish_requested(self, request) -> None:
        current = dict(getattr(state, "current_visual_reply_data", {}) or {})
        if request.keep_current_image and str(current.get("image_path") or "").strip():
            state.record_request_state({
                "status": "loading", "request_id": request.request_id,
                "updated_at": time.time(),
            }, binding_id=request.binding_id)
            return
        state.set_current_visual_reply_data({
            "status": "loading",
            "status_text": "Visual Reply generating...",
            "detail_text": "Preparing story image..." if request.keep_current_image else request.prompt,
            "image_path": "",
            "caption": request.prompt,
            "request_id": request.request_id,
            "keep_current_image": request.keep_current_image,
            "updated_at": time.time(),
        }, binding_id=request.binding_id)

    def generate(self, request, token: CancellationToken) -> Path | None:
        if token.cancelled:
            return None
        print(f"[VisualReply] Requested: {request.prompt}")
        service = self.generation_service
        if request.runtime_config is not None:
            frozen = dict(request.runtime_config)
            service = generation.VisualReplyGenerationService(
                runtime_config.VisualReplyRuntime(lambda: frozen, environ=self._environ),
                output_dir=generation.output_dir(),
            )
        output = service.generate_output(
            request.prompt,
            request_id=request.request_id,
            inputs=request.inputs,
        )
        if token.cancelled:
            return None
        allow_publication = getattr(self._publication_gate, "allow", None)
        if callable(allow_publication):
            allowed = allow_publication({
                "request_id": request.request_id,
                "prompt": request.prompt,
                "source_text": request.source_text,
                "keep_current_image": request.keep_current_image,
                "provider": service.runtime.provider(),
                "status": "ready",
                "image_path": str(output),
                "cancelled": lambda: token.cancelled,
            })
            if allowed is False or token.cancelled:
                return None
        return output

    @staticmethod
    def publish_result(result) -> None:
        state.set_current_visual_reply_data({
            "status": "ready",
            "status_text": "Visual Reply",
            "detail_text": result.source_text[:240],
            "image_path": str(result.output),
            "caption": result.prompt,
            "request_id": result.request_id,
            "updated_at": time.time(),
        }, binding_id=result.binding_id)
        print(f"[VisualReply] Ready: {result.output}")

    def publish_failure(self, request, failure: RuntimeFailure) -> None:
        state.set_current_visual_reply_data({
            "status": "error",
            "status_text": "Visual Reply failed",
            "detail_text": failure.message,
            "image_path": "",
            "caption": request.prompt,
            "request_id": request.request_id,
            "updated_at": time.time(),
        }, binding_id=request.binding_id)
        print(f"[VisualReply] Generation failed: {failure.message}")

    @staticmethod
    def retire_request(request, reason: str) -> None:
        state.retire_request_state(request.request_id, request.binding_id, reason)

    @staticmethod
    def current_state() -> dict:
        return dict(getattr(state, "current_visual_reply_data", {}) or {})


def create_runtime_capabilities(config_source, *, environ=None, output_dir=None, publication_gate=None):
    return VisualReplyRuntimeCapabilities(
        config_source,
        environ=environ,
        output_dir=output_dir,
        publication_gate=publication_gate,
    )


__all__ = ["VisualReplyRuntimeCapabilities", "create_runtime_capabilities"]
