"""Visual Reply configuration and prompt helper runtime.

Threaded image generation still lives in the engine for now. This module owns
the safe, deterministic Visual Reply settings and tag parsing logic.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any, Callable

from addons.visual_reply.providers import (
    PROVIDERS_BY_ID,
    default_model_for_provider,
    env_value,
    normalize_model_for_provider,
    provider_setting_from_config,
    provider_ids,
    provider_spec,
)


VISUAL_REPLY_TAG_RE = re.compile(r"\[(?:visualize|image):\s*([^\]]+?)\]", re.IGNORECASE)
VISUAL_REPLY_TAG_START_RE = re.compile(r"\[(visualize|image):", re.IGNORECASE)
PERSONA_SELF_DIRECTIVE_RE = re.compile(
    r"(?ims)^[ \t]*@self(?:[ \t]*[:\-])?[ \t]+(.+?)"
    r"(?=(?:\r?\n){2,}|\r?\n[ \t]*\[[^\]\r\n]+\]|\Z)"
)
USER_DIRECTIVE_RE = re.compile(
    r"(?ims)^[ \t]*@user(?:[ \t]*[:\-])?[ \t]+(.+?)"
    r"(?=(?:\r?\n){2,}|\r?\n[ \t]*\[[^\]\r\n]+\]|\Z)"
)
VISUAL_REPLY_PROVIDER_VALUES = provider_ids()
VISUAL_REPLY_XAI_BASE_URL = PROVIDERS_BY_ID["xai"].default_base_url
HOSTED_VISUAL_REPLY_SIZE_VALUES = ("auto", "1024x1024", "1024x1536", "1536x1024")
COMFYUI_VISUAL_REPLY_SIZE_VALUES = (
    "auto",
    "512x512",
    "768x768",
    "1024x1024",
    "1024x1536",
    "1536x1024",
    "1216x832",
    "832x1216",
    "1344x768",
    "768x1344",
    "1280x720",
    "720x1280",
    "1536x1536",
)
RUNWARE_IMAGE_TO_IMAGE_MODEL_OPTIONS = (
    "runware:z-image@turbo",
    "runware:z-image@0",
    "runware:101@1",
)
RUNWARE_DEFAULT_IMAGE_TO_IMAGE_MODEL = RUNWARE_IMAGE_TO_IMAGE_MODEL_OPTIONS[0]
XAI_IMAGE_TO_IMAGE_MODEL_OPTIONS = ("grok-imagine-image-2.0",)
XAI_DEFAULT_IMAGE_TO_IMAGE_MODEL = XAI_IMAGE_TO_IMAGE_MODEL_OPTIONS[0]

VISUAL_REPLY_STORY_THEME_PRESETS = (
    {"id": "realistic", "label": "Realistic", "prompt": "realistic cinematic lighting, natural textures, grounded detail"},
    {"id": "cartoon", "label": "Cartoon", "prompt": "cartoon illustration, bold shapes, clean outlines"},
    {"id": "retro", "label": "Retro", "prompt": "retro pulp illustration, vintage color palette, halftone print texture"},
    {"id": "cyberpunk", "label": "Cyberpunk", "prompt": "cyberpunk neon glow, high-tech city atmosphere, vivid contrast"},
    {"id": "anime", "label": "Anime", "prompt": "anime illustration, expressive character design, dynamic framing"},
    {"id": "storybook", "label": "Storybook", "prompt": "storybook painting, whimsical detail, illustrated fantasy look"},
)


def default_story_theme_prompts() -> dict[str, str]:
    return {
        str(item.get("id") or ""): str(item.get("prompt") or "").strip()
        for item in VISUAL_REPLY_STORY_THEME_PRESETS
        if str(item.get("id") or "").strip()
    }


class VisualReplyRuntime:
    def __init__(self, config_getter: Callable[[], dict[str, Any]], environ=None):
        self._config_getter = config_getter
        self._environ = environ if environ is not None else os.environ

    def _config(self) -> dict[str, Any]:
        try:
            config = self._config_getter()
        except Exception:
            config = {}
        return dict(config) if isinstance(config, Mapping) else {}

    def api_key(self) -> str:
        provider = self.provider()
        config = self._config()
        return str(
            provider_setting_from_config(config, provider, "api_key", "") or ""
        ).strip()

    def base_url(self) -> str:
        provider = self.provider()
        spec = provider_spec(provider)
        configured = str(provider_setting_from_config(self._config(), provider, "base_url", "") or "").strip()
        if not configured and provider == "comfyui":
            configured = str(provider_setting_from_config(self._config(), provider, "api_key", "") or "").strip()
        return configured or env_value(spec.base_url_env_names, self._environ) or spec.default_base_url

    def provider(self) -> str:
        provider = str(self._config().get("visual_reply_provider", "openai") or "openai").strip().lower()
        return provider if provider in VISUAL_REPLY_PROVIDER_VALUES else "openai"

    def mode(self) -> str:
        mode = str(self._config().get("visual_reply_mode", "off") or "off").strip().lower()
        return mode if mode in {"off", "auto"} else "off"

    def enabled(self) -> bool:
        if not bool(self._config().get("visual_replies_enabled", True)):
            return False
        return self.mode() != "off"

    def generation_available(self) -> bool:
        if not self.enabled():
            return False
        if self.provider() == "comfyui":
            return bool(self.base_url() and self.workflow_path())
        if provider_spec(self.provider()).requires_api_key:
            return bool(self.api_key())
        return bool(self.api_key() or self.base_url())

    def story_mode_enabled(self) -> bool:
        return bool(self._config().get("visual_reply_story_mode", False)) and self.enabled()

    def story_max_images(self) -> int:
        try:
            return max(1, int(self._config().get("visual_reply_story_max_images", 3) or 3))
        except Exception:
            return 3

    def story_continuity_strength(self) -> float:
        try:
            strength = float(self._config().get("visual_reply_story_continuity_strength", 0.8) or 0.8)
        except Exception:
            strength = 0.8
        if strength > 1.0:
            strength = strength / 100.0
        return max(0.0, min(1.0, strength))

    def story_theme_prompts(self) -> dict[str, str]:
        raw = self._config().get("visual_reply_story_theme_prompts", {})
        if not isinstance(raw, dict):
            raw = {}
        defaults = default_story_theme_prompts()
        prompts = {}
        for item in VISUAL_REPLY_STORY_THEME_PRESETS:
            theme_id = str(item.get("id") or "").strip().lower()
            if not theme_id:
                continue
            prompt = str(raw.get(theme_id, defaults.get(theme_id, item.get("prompt", ""))) or "").strip()
            prompts[theme_id] = prompt or defaults.get(theme_id, str(item.get("prompt") or "").strip())
        return prompts

    def story_theme_enabled(self) -> list[str]:
        raw = self._config().get("visual_reply_story_theme_enabled", [])
        if isinstance(raw, (str, bytes)):
            raw = [raw]
        if not isinstance(raw, (list, tuple, set)):
            raw = []
        valid_ids = {str(item.get("id") or "").strip().lower() for item in VISUAL_REPLY_STORY_THEME_PRESETS}
        enabled = []
        seen = set()
        for value in raw:
            theme_id = str(value or "").strip().lower()
            if not theme_id or theme_id not in valid_ids or theme_id in seen:
                continue
            enabled.append(theme_id)
            seen.add(theme_id)
        return enabled

    def story_theme_suffix(self) -> str:
        prompts = self.story_theme_prompts()
        parts = []
        for theme_id in self.story_theme_enabled():
            prompt = str(prompts.get(theme_id, "") or "").strip()
            if prompt:
                parts.append(prompt)
        if not parts:
            return ""
        return "Visual style: " + "; ".join(parts)

    def master_style_prompt(self) -> str:
        prompt = normalize_prompt_text(self._config().get("visual_reply_master_style_prompt", ""))
        if len(prompt) > 420:
            prompt = prompt[:420].rstrip(" \t\r\n,;:.-")
        return prompt

    def master_style_suffix(self) -> str:
        prompt = self.master_style_prompt()
        if not prompt:
            return ""
        return (
            "Preserve the same art direction, recurring character identity, clothing, props, "
            f"and world details from this reference image prompt: {prompt}"
        )

    def master_prompt_safety_suffix(self) -> str:
        if not bool(self._config().get("visual_reply_master_prompt_safe", False)):
            return ""
        return (
            "Depict only clearly adult people aged 21 or older. "
            "Do not depict children, minors, teenagers, school-age people, or underage-looking persons."
        )

    def no_speech_bubbles_suffix(self) -> str:
        if not bool(self._config().get("visual_reply_master_prompt_no_speech_bubbles", False)):
            return ""
        if self.provider() == "comfyui":
            # The unwanted objects belong in ComfyUI's negative conditioning.
            return "One continuous visual scene, uninterrupted composition."
        return (
            "No speech bubbles, dialogue balloons, comic bubbles, captions, subtitles, text overlays, or written text in the image."
        )

    def apply_style_anchor(self, prompt_text: str) -> str:
        prompt = str(prompt_text or "").strip()
        if not prompt:
            return ""
        suffixes = [
            self.master_style_suffix(),
            self.master_prompt_safety_suffix(),
            self.no_speech_bubbles_suffix(),
        ]
        suffixes = [item for item in suffixes if str(item or "").strip()]
        if suffixes:
            prompt = f"{prompt}. {' '.join(suffixes)}"
        if len(prompt) > 760:
            prompt = prompt[:760].rstrip(" \t\r\n,;:.-")
        return prompt

    def model_name(self) -> str:
        provider = self.provider()
        spec = provider_spec(provider)
        env = self._environ
        model = str(
            provider_setting_from_config(self._config(), provider, "model", "")
            or self._config().get("visual_reply_model")
            or env_value(spec.model_env_names, env)
            or default_model_for_provider(provider)
        ).strip()
        return normalize_model_for_provider(provider, model)

    def image_to_image_enabled(self) -> bool:
        """Return the selected provider's opt-in image-to-image policy."""

        provider = self.provider()
        if provider not in {"runware", "xai"}:
            return False
        value = provider_setting_from_config(
            self._config(), provider, "image_to_image_enabled", False
        )
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
        return bool(value)

    def image_to_image_model(self) -> str:
        provider = self.provider()
        if provider not in {"runware", "xai"}:
            return ""
        default_model = (
            XAI_DEFAULT_IMAGE_TO_IMAGE_MODEL
            if provider == "xai"
            else RUNWARE_DEFAULT_IMAGE_TO_IMAGE_MODEL
        )
        configured = str(
            provider_setting_from_config(
                self._config(),
                provider,
                "image_to_image_model",
                default_model,
            )
            or default_model
        ).strip()
        return configured or default_model

    def image_to_image_strength(self) -> float:
        if self.provider() != "runware":
            return 0.8
        raw = provider_setting_from_config(
            self._config(), "runware", "image_to_image_strength", 0.8
        )
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 0.8
        return max(0.0, min(1.0, value))

    def request_scoped_reference_board(self) -> bool:
        """Return the private multi-reference fallback for one frozen request."""

        if self.provider() != "runware":
            return False
        value = provider_setting_from_config(
            self._config(), "runware", "request_scoped_reference_board", False
        )
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
        return bool(value)

    def workflow_path(self) -> str:
        if self.provider() != "comfyui":
            return ""
        provider = self.provider()
        spec = provider_spec(provider)
        path = str(
            provider_setting_from_config(self._config(), provider, "workflow_path", "")
            or provider_setting_from_config(self._config(), provider, "model", "")
            or self._config().get("visual_reply_model")
            or env_value(spec.model_env_names, self._environ)
            or default_model_for_provider(provider)
        ).strip()
        return path

    def comfyui_generation_settings(self) -> dict:
        from addons.visual_reply.comfyui_settings import profile_for

        return profile_for(self._config(), self.base_url(), self.workflow_path())

    def comfyui_negative_prompt(self) -> str:
        return str(
            self.comfyui_generation_settings().get("negative_prompt")
            or provider_setting_from_config(self._config(), "comfyui", "negative_prompt", "")
            or self._environ.get("NC_VISUAL_REPLY_COMFYUI_NEGATIVE_PROMPT", "")
            or ""
        ).strip()

    def comfyui_prompting_rules(self) -> str:
        """Return the ComfyUI-only rule selection, defaulting to Auto Detect."""
        from addons.visual_reply.comfyui_prompting import normalize_rules

        if self.provider() != "comfyui":
            return "auto"
        return normalize_rules(
            provider_setting_from_config(self._config(), "comfyui", "prompting_rules", "auto")
        )

    def comfyui_timeout_seconds(self) -> float:
        profile = self.comfyui_generation_settings()
        if "timeout_seconds" in profile:
            from addons.visual_reply.comfyui_settings import validate_field

            return float(validate_field("timeout_seconds", profile["timeout_seconds"]))
        raw = (
            provider_setting_from_config(self._config(), "comfyui", "timeout_seconds", "")
            or self._environ.get("NC_VISUAL_REPLY_COMFYUI_TIMEOUT", "")
            or 180
        )
        try:
            return max(5.0, float(raw or 180))
        except Exception:
            return 180.0

    def comfyui_cleanup_mode(self) -> str:
        raw = (
            self.comfyui_generation_settings().get("cleanup_mode")
            or provider_setting_from_config(self._config(), "comfyui", "cleanup_mode", "")
            or self._environ.get("NC_VISUAL_REPLY_COMFYUI_CLEANUP", "")
            or "keep_cache"
        )
        mode = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
        if mode in {"off", "none", "keep", "keep_loaded", "keep_models", "keep_cache"}:
            return "keep_cache"
        if mode in {"free", "free_memory", "empty_cache", "soft_empty_cache"}:
            return "free_memory"
        if mode in {"unload", "unload_models", "full", "full_cleanup", "unload_models_free_memory"}:
            return "unload_models"
        return "keep_cache"

    def image_size(self) -> str:
        provider = self.provider()
        spec = provider_spec(provider)
        value = str(
            provider_setting_from_config(self._config(), provider, "size", "")
            or self._config().get("visual_reply_size")
            or env_value(spec.size_env_names, self._environ)
            or "1024x1024"
        ).strip().lower()
        return normalize_visual_reply_size(value, provider)

    def xai_extra_body(self) -> dict[str, str]:
        if self.source_image_edit():
            return {"resolution": "1k"}  # The first input controls the output aspect ratio.
        size = self.image_size()
        if size == "1024x1536":
            return {"aspect_ratio": "2:3", "resolution": "1k"}
        if size == "1536x1024":
            return {"aspect_ratio": "3:2", "resolution": "1k"}
        if size == "1024x1024":
            return {"aspect_ratio": "1:1", "resolution": "1k"}
        return {"aspect_ratio": "auto", "resolution": "1k"}

    def source_image_edit(self) -> bool:
        return self._config().get("_visual_reply_source_edit") is True

    def source_image_edit_error(self) -> str:
        return str(self._config().get("_visual_reply_source_edit_error", "") or "")


def normalize_prompt_text(prompt_text: str) -> str:
    prompt = str(prompt_text or "")
    if not prompt:
        return ""
    prompt = re.sub(r"\[[^\]]+\]", " ", prompt)
    prompt = prompt.replace("]", " ")
    prompt = re.sub(r"\s+", " ", prompt).strip()
    prompt = prompt.strip(" \t\r\n'\"`.,;:()[]{}")
    return prompt


def size_labels_for_provider(provider: str | None) -> list[str]:
    provider_id = str(provider or "openai").strip().lower()
    values = COMFYUI_VISUAL_REPLY_SIZE_VALUES if provider_id == "comfyui" else HOSTED_VISUAL_REPLY_SIZE_VALUES
    return ["Auto" if value == "auto" else value for value in values]


def _normalize_size_text(value: str | None) -> str:
    size = str(value or "1024x1024").strip().lower()
    size = size.replace(" ", "").replace("*", "x").replace("×", "x")
    return size


def _valid_comfyui_dimension(value: int) -> bool:
    return 64 <= int(value) <= 8192 and int(value) % 8 == 0


def normalize_visual_reply_size(value: str | None, provider: str | None = None) -> str:
    size = _normalize_size_text(value)
    provider_id = str(provider or "openai").strip().lower()
    if size == "auto":
        return "auto"
    if provider_id == "comfyui":
        match = re.fullmatch(r"(\d{2,5})x(\d{2,5})", size)
        if match:
            width = int(match.group(1))
            height = int(match.group(2))
            if _valid_comfyui_dimension(width) and _valid_comfyui_dimension(height):
                return f"{width}x{height}"
        return "1024x1024"
    return size if size in HOSTED_VISUAL_REPLY_SIZE_VALUES else "1024x1024"


def is_valid_visual_reply_size(value: str | None, provider: str | None = None) -> bool:
    size = _normalize_size_text(value)
    provider_id = str(provider or "openai").strip().lower()
    if size == "auto":
        return True
    if provider_id == "comfyui":
        match = re.fullmatch(r"(\d{2,5})x(\d{2,5})", size)
        if not match:
            return False
        return _valid_comfyui_dimension(int(match.group(1))) and _valid_comfyui_dimension(int(match.group(2)))
    return size in HOSTED_VISUAL_REPLY_SIZE_VALUES


def strip_visual_reply_tail(text: str):
    value = str(text or "")
    if not value:
        return "", None
    start_matches = list(VISUAL_REPLY_TAG_START_RE.finditer(value))
    if not start_matches:
        for marker, directive_re in (
            ("@self", PERSONA_SELF_DIRECTIVE_RE),
            ("@user", USER_DIRECTIVE_RE),
        ):
            directive_match = directive_re.search(value)
            if directive_match is None:
                continue
            prompt_text = normalize_prompt_text(directive_match.group(1))
            cleaned = value[: directive_match.start()] + value[directive_match.end() :]
            return cleaned, (f"{marker} {prompt_text}" if prompt_text else None)
        return value, None
    matches = list(VISUAL_REPLY_TAG_RE.finditer(value))
    last_start = start_matches[-1]
    if not any(match.start() == last_start.start() for match in matches):
        prompt_text = normalize_prompt_text(value[last_start.end():])
        cleaned = VISUAL_REPLY_TAG_RE.sub("", value[: last_start.start()])
        return cleaned, (prompt_text or None)
    prompt_text = normalize_prompt_text(matches[-1].group(1))
    cleaned = VISUAL_REPLY_TAG_RE.sub("", value)
    return cleaned, (prompt_text or None)


def looks_like_visual_reply_tag_prefix(fragment):
    value = str(fragment or "").strip().lower()
    if not value:
        return False
    if "@self".startswith(value):
        return True
    if value.startswith("@self"):
        return bool(re.fullmatch(r"@self(?:\s*[:\-]?\s*[^\n]*)?", value))
    if "@user".startswith(value):
        return True
    if value.startswith("@user"):
        return bool(re.fullmatch(r"@user(?:\s*[:\-]?\s*[^\n]*)?", value))
    for starter in ("visualize", "image"):
        if starter.startswith(value):
            return True
        if value.startswith(starter):
            remainder = value[len(starter):]
            if not remainder:
                return True
            if re.fullmatch(r"\s*:\s*[^\]\n]*", remainder):
                return True
    return False


def extract_visual_reply_prompt(text: str):
    value = str(text or "")
    cleaned, prompt = strip_visual_reply_tail(value)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = cleaned.strip()
    if prompt and not cleaned:
        cleaned = "Let me show you."
    return cleaned, (prompt or None)
