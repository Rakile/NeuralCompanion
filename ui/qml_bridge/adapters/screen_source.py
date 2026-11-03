"""Native Screen Source settings and region-selection actions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Callable

from ui.qml_bridge.adapters.addon_session import AddonSessionNativeAdapter
from ui.qml_bridge.native_contracts import (
    NativeChoice,
    NativeControl,
    NativeControlKind,
    NativeSurface,
    choices,
)


def _region_text(value: object) -> str:
    region = dict(value or {}) if isinstance(value, Mapping) else {}
    if not region:
        return "No region selected"
    return (
        f"{int(region.get('width', 0) or 0)} x "
        f"{int(region.get('height', 0) or 0)} px at "
        f"{int(region.get('x', 0) or 0)}, {int(region.get('y', 0) or 0)}"
    )


class ScreenSourceNativeAdapter(AddonSessionNativeAdapter):
    CATALOG_CAPABILITY = "runtime.screen.catalog"
    SELECT_CAPABILITY = "runtime.screen.select_region"

    def snapshot(self) -> NativeSurface:
        surface = super().snapshot()
        catalog_value = self._invoke(self.CATALOG_CAPABILITY)
        catalog = tuple(
            NativeChoice(
                value=dict(item or {}).get("value"),
                label=str(dict(item or {}).get("label") or "Screen"),
            )
            for item in list(catalog_value or [])
        ) or (NativeChoice(value=-1, label="All screens"),)
        state = self._state()
        controls = []
        for control in surface.controls:
            if control.id == "screen_source_capture_screen_index":
                control = replace(control, choices=catalog)
            elif control.id == "screen_source_capture_region":
                control = replace(
                    control,
                    value=_region_text(state.get(control.id)),
                )
            controls.append(control)
        return replace(surface, controls=tuple(controls))

    def trigger(self, control_id: str) -> None:
        action = str(control_id or "").strip()
        if action not in {"select_region", "select_square"}:
            raise KeyError(f"Unknown Screen Source action '{control_id}'.")
        self._invoke(
            self.SELECT_CAPABILITY,
            {"square": action == "select_square"},
        )
        self._revision += 1
        if callable(self._persist):
            self._persist()
        self.changed.emit()


def build_screen_source_adapter(
    application_facade: Any,
    *,
    persist: Callable[[], object] | None = None,
) -> ScreenSourceNativeAdapter:
    surface = NativeSurface(
        id="screen_source_capture_tab",
        title="Screen Source",
        addon_id="nc.screen_source",
        sections=("Capture area", "Image detail", "Capture actions", "Current selection"),
        description="Choose the monitor or region sent through screen awareness.",
        controls=(
            NativeControl(
                id="screen_source_capture_mode",
                label="Capture area",
                kind=NativeControlKind.CHOICE,
                section="Capture area",
                default_value="full",
                choices=choices(
                    (("full", "Whole screen"), ("region", "Selected region"), ("square", "Selected square"))
                ),
            ),
            NativeControl(
                id="screen_source_capture_screen_index",
                label="Screen",
                kind=NativeControlKind.CHOICE,
                section="Capture area",
                default_value=-1,
                choices=(NativeChoice(value=-1, label="All screens"),),
            ),
            NativeControl(
                id="screen_source_max_width",
                label="Max width",
                kind=NativeControlKind.INTEGER,
                section="Image detail",
                default_value=5120,
                minimum=256,
                maximum=5120,
                step=128,
                metadata={"suffix": " px"},
            ),
            NativeControl(
                id="screen_source_max_height",
                label="Max height",
                kind=NativeControlKind.INTEGER,
                section="Image detail",
                default_value=2880,
                minimum=256,
                maximum=5120,
                step=128,
                metadata={"suffix": " px"},
            ),
            NativeControl(
                id="screen_source_jpeg_quality",
                label="JPEG quality",
                kind=NativeControlKind.INTEGER,
                section="Image detail",
                default_value=85,
                minimum=40,
                maximum=95,
                step=1,
                metadata={"suffix": "%"},
            ),
            NativeControl(
                id="screen_source_auto_attach_next_user_turn",
                label="Attach screen capture to every next user turn",
                kind=NativeControlKind.BOOLEAN,
                section="Capture actions",
                default_value=False,
            ),
            NativeControl(
                id="select_region",
                label="Select region",
                kind=NativeControlKind.ACTION,
                section="Capture actions",
                metadata={"execution": "ui"},
            ),
            NativeControl(
                id="select_square",
                label="Select square",
                kind=NativeControlKind.ACTION,
                section="Capture actions",
                metadata={"execution": "ui"},
            ),
            NativeControl(
                id="screen_source_capture_region",
                label="Current region",
                kind=NativeControlKind.DISPLAY,
                section="Current selection",
                default_value="No region selected",
            ),
        ),
    )
    return ScreenSourceNativeAdapter(
        application_facade,
        surface,
        persist=persist,
    )


__all__ = ["ScreenSourceNativeAdapter", "build_screen_source_adapter"]
