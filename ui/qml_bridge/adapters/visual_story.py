"""Native QML adapter for story-mode Visual Reply settings."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from addons.visual_reply.runtime_config import (
    VISUAL_REPLY_STORY_THEME_PRESETS,
    default_story_theme_prompts,
)
from ui.qml_bridge.adapters.card_layout import apply_card_layout
from ui.qml_bridge.adapters.config import RuntimeConfigNativeAdapter
from ui.qml_bridge.native_contracts import NativeControl, NativeControlKind, NativeSurface
from ui.qml_bridge.native_registry import NativeSurfaceAdapter


_THEMES = tuple(
    (
        str(item.get("id") or "").strip().lower(),
        str(item.get("label") or "").strip(),
    )
    for item in VISUAL_REPLY_STORY_THEME_PRESETS
    if str(item.get("id") or "").strip()
)


class VisualStoryNativeAdapter(NativeSurfaceAdapter):
    def __init__(self, application_facade: Any, *, persist=None, parent=None) -> None:
        surface = self._build_surface()
        super().__init__(surface.id, surface.addon_id, parent)
        self._application = application_facade
        self._surface = surface
        self._controls = {control.id: control for control in surface.controls}
        self._persist: Callable[[], object] | None = persist
        self._revision = 0

    @staticmethod
    def _build_surface() -> NativeSurface:
        controls: list[NativeControl] = [
            NativeControl(
                "visual_reply_story_mode",
                "Story mode",
                NativeControlKind.BOOLEAN,
                section="Story generation",
                description="Generate Visual Replies for spoken story chunks.",
                default_value=False,
            ),
            NativeControl(
                "visual_reply_story_max_images",
                "Maximum images per reply",
                NativeControlKind.INTEGER,
                section="Story generation",
                default_value=3,
                minimum=1,
                maximum=20,
            ),
            NativeControl(
                "visual_reply_story_continuity_strength",
                "Continuity strength",
                NativeControlKind.SLIDER,
                section="Story generation",
                description="How strongly successive images preserve visual continuity.",
                default_value=80,
                minimum=0,
                maximum=100,
                step=1,
            ),
        ]
        defaults = default_story_theme_prompts()
        for theme_id, label in _THEMES:
            controls.append(
                NativeControl(
                    f"theme_enabled:{theme_id}",
                    f"Use {label}",
                    NativeControlKind.BOOLEAN,
                    section="Story styles",
                    default_value=False,
                )
            )
            controls.append(
                NativeControl(
                    f"theme_prompt:{theme_id}",
                    f"{label} prompt",
                    NativeControlKind.TEXT,
                    section="Story styles",
                    default_value=defaults.get(theme_id, ""),
                )
            )
        controls.extend(
            (
                NativeControl(
                    "visual_reply_master_style_prompt",
                    "Master style prompt",
                    NativeControlKind.MULTILINE,
                    section="Master prompt",
                    description="Optional style anchor applied to every story image.",
                    default_value="",
                ),
                NativeControl(
                    "visual_reply_master_prompt_safe",
                    "Add safe-content guidance",
                    NativeControlKind.BOOLEAN,
                    section="Master prompt",
                    default_value=False,
                ),
                NativeControl(
                    "visual_reply_master_prompt_no_speech_bubbles",
                    "Prevent speech bubbles and visible text",
                    NativeControlKind.BOOLEAN,
                    section="Master prompt",
                    default_value=False,
                ),
                NativeControl(
                    "story_visual_summary",
                    "Current story setup",
                    NativeControlKind.DISPLAY,
                    section="Summary",
                    default_value="Story mode is off.",
                ),
            )
        )
        return NativeSurface(
            id="visual_story_settings_tab",
            addon_id="nc.visual_story_settings",
            title="Story Visuals",
            description="Story-mode image generation, continuity, and style guards.",
            sections=("Story generation", "Story styles", "Master prompt", "Summary"),
            controls=tuple(controls),
        )

    def _get(self, key: str, default=None):
        return self._application.config.get(key, default)

    def _write(self, key: str, value: object) -> None:
        result = self._application.config.update(key, value)
        if not result.accepted:
            failure = getattr(result, "failure", None)
            raise RuntimeError(str(getattr(failure, "message", f"Could not update '{key}'.")))

    def _theme_state(self) -> tuple[set[str], dict[str, str]]:
        raw_enabled = self._get("visual_reply_story_theme_enabled", [])
        if isinstance(raw_enabled, (str, bytes)):
            raw_enabled = [raw_enabled]
        enabled = {
            str(value or "").strip().lower()
            for value in list(raw_enabled or [])
            if str(value or "").strip()
        }
        defaults = default_story_theme_prompts()
        raw_prompts = self._get("visual_reply_story_theme_prompts", {})
        prompts = dict(raw_prompts or {}) if isinstance(raw_prompts, dict) else {}
        return enabled, {
            theme_id: str(prompts.get(theme_id, defaults.get(theme_id, "")) or "").strip()
            for theme_id, _label in _THEMES
        }

    def _summary(self, enabled: set[str]) -> str:
        story_enabled = bool(self._get("visual_reply_story_mode", False))
        max_images = max(1, int(self._get("visual_reply_story_max_images", 3) or 3))
        try:
            continuity = float(
                self._get("visual_reply_story_continuity_strength", 0.8) or 0.8
            )
        except (TypeError, ValueError):
            continuity = 0.8
        if continuity > 1.0:
            continuity /= 100.0
        labels = [label for theme_id, label in _THEMES if theme_id in enabled]
        styles = ", ".join(labels) if labels else "no style presets"
        return (
            f"Story mode is {'on' if story_enabled else 'off'}; up to {max_images} "
            f"image(s), {round(max(0.0, min(1.0, continuity)) * 100)}% continuity, "
            f"{styles}."
        )

    def snapshot(self) -> NativeSurface:
        enabled, prompts = self._theme_state()
        controls = []
        for control in self._surface.controls:
            if control.id.startswith("theme_enabled:"):
                value = control.id.partition(":")[2] in enabled
            elif control.id.startswith("theme_prompt:"):
                value = prompts.get(control.id.partition(":")[2], control.default_value)
            elif control.id == "visual_reply_story_continuity_strength":
                try:
                    strength = float(self._get(control.id, 0.8) or 0.8)
                except (TypeError, ValueError):
                    strength = 0.8
                value = round((strength / 100.0 if strength > 1.0 else strength) * 100)
            elif control.id == "story_visual_summary":
                value = self._summary(enabled)
            else:
                value = self._get(control.id, control.default_value)
            controls.append(replace(control, value=value))
        return replace(
            self._surface,
            controls=apply_card_layout(controls),
            revision=self._revision,
        )

    def set_value(self, control_id: str, value: Any) -> None:
        key = str(control_id or "").strip()
        control = self._controls.get(key)
        if control is None or control.kind is NativeControlKind.DISPLAY:
            raise KeyError(f"Unknown editable story setting '{control_id}'.")
        normalized = RuntimeConfigNativeAdapter._normalize(control, value)
        enabled, prompts = self._theme_state()
        if key.startswith("theme_enabled:"):
            theme_id = key.partition(":")[2]
            if bool(normalized):
                enabled.add(theme_id)
            else:
                enabled.discard(theme_id)
            ordered = [theme_id for theme_id, _label in _THEMES if theme_id in enabled]
            self._write("visual_reply_story_theme_enabled", ordered)
        elif key.startswith("theme_prompt:"):
            prompts[key.partition(":")[2]] = str(normalized or "").strip()
            self._write("visual_reply_story_theme_prompts", prompts)
        elif key == "visual_reply_story_continuity_strength":
            self._write(key, float(normalized) / 100.0)
        else:
            self._write(key, normalized)
        self._revision += 1
        if callable(self._persist):
            self._persist()
        self.changed.emit()


def build_visual_story_adapter(application_facade, *, persist=None):
    return VisualStoryNativeAdapter(application_facade, persist=persist)


__all__ = ["VisualStoryNativeAdapter", "build_visual_story_adapter"]
