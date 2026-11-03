"""Headless Visual Reply addon used by the native QML shell."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from addons.visual_reply import generation, runtime_config, state
from addons.visual_reply.library import VisualReplyLibrary
from core.addons.base import BaseAddon


_SESSION_KEYS = (
    "visual_reply_mode",
    "visual_reply_provider",
    "visual_reply_size",
    "visual_reply_model",
    "visual_reply_provider_settings",
    "visual_reply_auto_show_dock",
    "visual_reply_toolbar_expanded",
)


class Addon(BaseAddon):
    """Expose generation/state operations without constructing a QWidget panel."""

    def initialize(self, context):
        super().initialize(context)
        self._runtime_config = context.capabilities.runtime_config
        self._library = VisualReplyLibrary(
            generation.output_dir(),
            self.current_state,
            self.set_state,
            state.update_current_visual_reply_data,
        )
        context.logger.info("Visual Reply native runtime addon initialized.")

    def _config_snapshot(self) -> dict:
        service = getattr(self, "_runtime_config", None)
        return dict(service.snapshot() or {}) if service is not None else {}

    def export_session_state(self):
        config = self._config_snapshot()
        return {key: config[key] for key in _SESSION_KEYS if key in config}

    def export_preset_state(self):
        return self.export_session_state()

    def import_session_state(self, payload):
        service = getattr(self, "_runtime_config", None)
        if service is None:
            return None
        for key in _SESSION_KEYS:
            if key in dict(payload or {}):
                service.update(key, dict(payload or {}).get(key))
        return None

    def import_preset_state(self, payload):
        return self.import_session_state(payload)

    @staticmethod
    def generation(config):
        runtime = runtime_config.VisualReplyRuntime(lambda: dict(config or {}))
        provider = generation.provider(runtime)
        return {
            "api_key": generation.api_key(runtime),
            "base_url": generation.base_url(runtime),
            "provider": provider,
            "enabled": generation.enabled(runtime),
            "generation_available": generation.generation_available(runtime),
            "model": generation.model_name(runtime),
            "size": generation.image_size(runtime),
            "extra_body": generation.xai_extra_body(runtime),
            "response_format": "base64Data" if provider == "runware" else "b64_json",
        }

    @staticmethod
    def current_state():
        return dict(getattr(state, "current_visual_reply_data", {}) or {})

    @staticmethod
    def set_state(value):
        state.set_current_visual_reply_data(dict(value or {}))
        return True

    @staticmethod
    def output_base(prefix="visual_reply", index=0):
        safe_prefix = str(prefix or "visual_reply").strip() or "visual_reply"
        return generation.output_dir() / (
            f"{safe_prefix}_{int(time.time())}_{int(index or 0)}_{uuid.uuid4().hex[:8]}"
        )

    @staticmethod
    def client(config):
        return generation.client(runtime_config.VisualReplyRuntime(lambda: dict(config or {})))

    @staticmethod
    def apply_style_anchor(config, prompt):
        runtime = runtime_config.VisualReplyRuntime(lambda: dict(config or {}))
        return generation.apply_style_anchor(runtime, str(prompt or ""))

    @staticmethod
    def story_style_guide(config, text, continuity_strength=0.8):
        runtime = runtime_config.VisualReplyRuntime(lambda: dict(config or {}))
        service = generation.VisualReplyGenerationService(runtime, output_dir=generation.output_dir())
        return service.story_style_guide_from_text(
            str(text or ""),
            continuity_strength=float(continuity_strength or 0.8),
        )

    @staticmethod
    def story_prompt(config, text, emotion="", story_style_guide=""):
        runtime = runtime_config.VisualReplyRuntime(lambda: dict(config or {}))
        service = generation.VisualReplyGenerationService(runtime, output_dir=generation.output_dir())
        return service.story_prompt_from_text(
            str(text or ""),
            emotion=str(emotion or ""),
            story_style_guide=str(story_style_guide or ""),
        )

    @staticmethod
    def normalize_prompt(prompt):
        return runtime_config.normalize_prompt_text(str(prompt or ""))

    @staticmethod
    def write_image_from_response(config, response, output_base_path):
        runtime = runtime_config.VisualReplyRuntime(lambda: dict(config or {}))
        service = generation.VisualReplyGenerationService(runtime, output_dir=generation.output_dir())
        return service.write_image_from_response(response, Path(output_base_path))

    def invoke_capability(self, capability, payload=None):
        name, request = str(capability or "").strip(), dict(payload or {})
        config = request.get("runtime_config")
        if name == "runtime.generation":
            return self.generation(config)
        if name == "runtime.current_state":
            return self._library.snapshot()
        if name == "runtime.set_state":
            return self.set_state(request.get("state"))
        if name == "runtime.clear_state":
            return self._library.clear(
                status_text=str(request.get("status_text") or "Visual Reply idle"),
                detail_text=str(request.get("detail_text") or "No visual reply yet."),
            )
        if name == "runtime.ensure_storage":
            return str(self._library.ensure_storage())
        if name == "runtime.load_image":
            return self._library.load_image(request.get("image_path", ""))
        if name == "runtime.navigate_storage":
            return self._library.navigate(int(request.get("offset", 0) or 0))
        if name == "runtime.set_caption":
            return self._library.set_caption(str(request.get("caption") or ""))
        if name == "runtime.delete_current_image":
            return self._library.delete_current(expected_path=request.get("expected_path"))
        if name == "runtime.delete_all_images":
            return self._library.delete_all()
        if name == "runtime.output_base":
            return self.output_base(request.get("prefix", "visual_reply"), request.get("index", 0))
        if name == "runtime.client":
            return self.client(config)
        if name == "runtime.apply_style_anchor":
            return self.apply_style_anchor(config, request.get("prompt", ""))
        if name == "runtime.story_style_guide":
            return self.story_style_guide(config, request.get("text", ""), request.get("continuity_strength", 0.8))
        if name == "runtime.story_prompt":
            return self.story_prompt(config, request.get("text", ""), request.get("emotion", ""), request.get("story_style_guide", ""))
        if name == "runtime.normalize_prompt":
            return self.normalize_prompt(request.get("prompt", ""))
        if name == "runtime.write_image_from_response":
            return self.write_image_from_response(config, request.get("response"), request.get("output_base_path"))
        if name in {"ui.panel_class", "visual_reply.build_runtime_panel"}:
            return None
        return None

    def shutdown(self):
        return None
