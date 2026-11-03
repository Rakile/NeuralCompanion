"""Native QML controls for the Visual Reply runtime host surface."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from addons.visual_reply.providers import (
    default_model_for_provider,
    provider_setting_from_config,
    provider_spec,
    updated_provider_settings,
)
from ui.qml_bridge.native_contracts import (
    NativeControl,
    NativeControlKind,
    NativeSurface,
)
from ui.qml_bridge.native_registry import NativeSurfaceAdapter


class VisualReplyCoreNativeAdapter(NativeSurfaceAdapter):
    """Expose the three host-only Visual Reply settings without widgets."""

    def __init__(
        self,
        application_facade: Any,
        surface: NativeSurface,
        *,
        persist: Callable[[], object] | None = None,
        parent=None,
    ) -> None:
        super().__init__(surface.id, surface.addon_id, parent)
        self._application = application_facade
        self._surface = surface
        self._persist = persist
        self._revision = 0

    def _config(self) -> dict[str, object]:
        return dict(self._application.config.snapshot().values)

    def snapshot(self) -> NativeSurface:
        config = self._config()
        provider = str(config.get("visual_reply_provider") or "openai").strip().lower()
        spec = provider_spec(provider)
        model = provider_setting_from_config(
            config,
            provider,
            "model",
            config.get("visual_reply_model") or default_model_for_provider(provider),
        )
        api_value = provider_setting_from_config(config, provider, "api_key", "")
        if provider == "comfyui" and not api_value:
            api_value = spec.default_base_url
        controls = []
        for control in self._surface.controls:
            if control.id == "visual_reply_model":
                control = replace(
                    control,
                    label="Workflow" if provider == "comfyui" else "Image model",
                    value=str(model or default_model_for_provider(provider)),
                )
            elif control.id == "visual_reply_api_key":
                control = replace(
                    control,
                    label="Server URL" if provider == "comfyui" else "API key",
                    value=str(api_value or ""),
                    secret=provider != "comfyui",
                )
            elif control.id == "visual_reply_auto_show_dock":
                control = replace(
                    control,
                    value=bool(config.get("visual_reply_auto_show_dock", True)),
                )
            controls.append(control)
        return replace(
            self._surface,
            controls=tuple(controls),
            revision=self._revision,
        )

    def set_value(self, control_id: str, value: Any) -> None:
        key = str(control_id or "").strip()
        config = self._config()
        provider = str(config.get("visual_reply_provider") or "openai").strip().lower()
        if key == "visual_reply_model":
            normalized = str(value or "").strip() or default_model_for_provider(provider)
            settings = updated_provider_settings(config, provider, "model", normalized)
            updates = (
                ("visual_reply_provider_settings", settings),
                ("visual_reply_model", normalized),
            )
        elif key == "visual_reply_api_key":
            normalized = str(value or "").strip()
            settings = updated_provider_settings(config, provider, "api_key", normalized)
            updates = (("visual_reply_provider_settings", settings),)
        elif key == "visual_reply_auto_show_dock":
            updates = (("visual_reply_auto_show_dock", bool(value)),)
        else:
            raise KeyError(f"Unknown Visual Reply setting '{control_id}'.")

        for config_key, normalized_value in updates:
            result = self._application.config.update(config_key, normalized_value)
            if not result.accepted:
                failure = getattr(result, "failure", None)
                raise RuntimeError(
                    str(
                        getattr(
                            failure,
                            "message",
                            f"Could not update '{config_key}'.",
                        )
                    )
                )
        self._revision += 1
        if callable(self._persist):
            self._persist()
        self.changed.emit()


def build_visual_reply_core_adapter(
    application_facade: Any,
    *,
    persist: Callable[[], object] | None = None,
) -> VisualReplyCoreNativeAdapter:
    surface = NativeSurface(
        id="visuals_host",
        title="Visual Reply",
        addon_id="nc.visual_reply",
        sections=("Generation", "Display"),
        description="Configure the selected image provider and Visual Reply display behavior.",
        controls=(
            NativeControl(
                "visual_reply_model",
                "Image model",
                NativeControlKind.TEXT,
                "Generation",
            ),
            NativeControl(
                "visual_reply_api_key",
                "API key",
                NativeControlKind.TEXT,
                "Generation",
                secret=True,
            ),
            NativeControl(
                "visual_reply_auto_show_dock",
                "Automatically show a completed visual reply",
                NativeControlKind.BOOLEAN,
                "Display",
                default_value=True,
            ),
        ),
    )
    return VisualReplyCoreNativeAdapter(
        application_facade,
        surface,
        persist=persist,
    )


__all__ = ["VisualReplyCoreNativeAdapter", "build_visual_reply_core_adapter"]
