"""Reusable native adapter for settings owned by RuntimeConfigCommands."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from ui.qml_bridge.native_contracts import NativeControl, NativeControlKind, NativeSurface
from ui.qml_bridge.native_registry import NativeSurfaceAdapter


class RuntimeConfigNativeAdapter(NativeSurfaceAdapter):
    """Expose an explicit control schema over the authoritative NC config."""

    def __init__(
        self,
        application_facade: Any,
        surface: NativeSurface,
        persist: Callable[[], object] | None = None,
        parent=None,
    ) -> None:
        super().__init__(surface.id, surface.addon_id, parent)
        self._application = application_facade
        self._surface = surface
        self._controls = {control.id: control for control in surface.controls}
        self._persist = persist
        self._revision = 0

    def snapshot(self) -> NativeSurface:
        controls = tuple(
            replace(
                control,
                value=self._application.config.get(
                    control.id,
                    control.default_value,
                ),
            )
            for control in self._surface.controls
        )
        return replace(self._surface, controls=controls, revision=self._revision)

    def set_value(self, control_id: str, value: Any) -> None:
        key = str(control_id or "").strip()
        control = self._controls.get(key)
        if control is None or control.kind is NativeControlKind.ACTION:
            raise KeyError(f"Unknown runtime setting '{control_id}'.")
        normalized = self._normalize(control, value)
        result = self._application.config.update(key, normalized)
        if not result.accepted:
            failure = getattr(result, "failure", None)
            raise RuntimeError(
                str(getattr(failure, "message", f"Could not update '{key}'."))
            )
        self._revision += 1
        if callable(self._persist):
            self._persist()
        self.changed.emit()

    @staticmethod
    def _normalize(control: NativeControl, value: Any) -> object:
        if control.kind is NativeControlKind.BOOLEAN:
            return bool(value)
        if control.kind is NativeControlKind.INTEGER:
            normalized: object = int(value)
        elif control.kind in {
            NativeControlKind.NUMBER,
            NativeControlKind.SLIDER,
        }:
            normalized = float(value)
        elif control.kind is NativeControlKind.CHOICE:
            allowed = {str(choice.value): choice.value for choice in control.choices}
            lookup = str(value)
            if lookup not in allowed:
                raise ValueError(f"'{value}' is not valid for '{control.label}'.")
            normalized = allowed[lookup]
        else:
            normalized = str(value or "")
        if isinstance(normalized, (int, float)) and not isinstance(normalized, bool):
            if control.minimum is not None and normalized < control.minimum:
                raise ValueError(f"'{control.label}' is below its minimum.")
            if control.maximum is not None and normalized > control.maximum:
                raise ValueError(f"'{control.label}' exceeds its maximum.")
        return normalized


__all__ = ["RuntimeConfigNativeAdapter"]
