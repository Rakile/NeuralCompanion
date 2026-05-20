"""Visual Reply configuration and prompt helper runtime.

Threaded image generation still lives in the engine for now. This module owns
the safe, deterministic Visual Reply settings and tag parsing logic.
"""

from __future__ import annotations

import os
import re
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
VISUAL_REPLY_PROVIDER_VALUES = provider_ids()
VISUAL_REPLY_XAI_BASE_URL = PROVIDERS_BY_ID["xai"].default_base_url

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
        return config if isinstance(config, dict) else {}

    def api_key(self) -> str:
        provider = self.provider()
        spec = provider_spec(provider)
        env = self._environ
        config = self._config()
        configured_key = str(provider_setting_from_config(config, provider, "api_key", "") or "").strip()
        if configured_key:
            return configured_key
        return env_value(spec.api_key_env_names, env)

    def base_url(self) -> str:
        spec = provider_spec(self.provider())
        return env_value(spec.base_url_env_names, self._environ) or spec.default_base_url

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

    def image_size(self) -> str:
        allowed = {"auto", "1024x1024", "1024x1536", "1536x1024"}
        provider = self.provider()
        spec = provider_spec(provider)
        value = str(
            provider_setting_from_config(self._config(), provider, "size", "")
            or self._config().get("visual_reply_size")
            or env_value(spec.size_env_names, self._environ)
            or "1024x1024"
        ).strip().lower()
        return value if value in allowed else "1024x1024"

    def xai_extra_body(self) -> dict[str, str]:
        size = self.image_size()
        if size == "1024x1536":
            return {"aspect_ratio": "2:3", "resolution": "1k"}
        if size == "1536x1024":
            return {"aspect_ratio": "3:2", "resolution": "1k"}
        if size == "1024x1024":
            return {"aspect_ratio": "1:1", "resolution": "1k"}
        return {"aspect_ratio": "auto", "resolution": "1k"}


def normalize_prompt_text(prompt_text: str) -> str:
    prompt = str(prompt_text or "")
    if not prompt:
        return ""
    prompt = re.sub(r"\[[^\]]+\]", " ", prompt)
    prompt = prompt.replace("]", " ")
    prompt = re.sub(r"\s+", " ", prompt).strip()
    prompt = prompt.strip(" \t\r\n'\"`.,;:()[]{}")
    return prompt


def strip_visual_reply_tail(text: str):
    value = str(text or "")
    if not value:
        return "", None
    matches = list(VISUAL_REPLY_TAG_START_RE.finditer(value))
    if not matches:
        return value, None
    last_match = matches[-1]
    start_index = int(last_match.start())
    cleaned = value[:start_index]
    raw_tail = value[start_index:]
    colon_index = raw_tail.find(":")
    prompt_text = raw_tail[colon_index + 1:] if colon_index >= 0 else ""
    prompt_text = normalize_prompt_text(prompt_text)
    return cleaned, (prompt_text or None)


def looks_like_visual_reply_tag_prefix(fragment):
    value = str(fragment or "").strip().lower()
    if not value:
        return False
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
