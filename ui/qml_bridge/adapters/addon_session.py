"""Native adapters for state owned by one initialized addon."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from ui.qml_bridge.adapters.config import RuntimeConfigNativeAdapter
from ui.qml_bridge.native_contracts import NativeControlKind, NativeSurface
from ui.qml_bridge.native_registry import NativeSurfaceAdapter


class AddonSessionNativeAdapter(NativeSurfaceAdapter):
    """Read and update explicit addon state through finite capabilities."""

    EXPORT_CAPABILITY = "runtime.session.export"
    IMPORT_CAPABILITY = "runtime.session.import"

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
        self._controls = {control.id: control for control in surface.controls}
        self._persist = persist
        self._revision = 0

    def _invoke(self, capability: str, payload=None) -> object:
        result = self._application.addons.invoke_addon_capability(
            self.addon_id,
            capability,
            dict(payload or {}),
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            raise RuntimeError(
                str(getattr(failure, "message", "Addon state operation failed."))
            )
        return result.value

    def _state(self) -> dict[str, object]:
        value = self._invoke(self.EXPORT_CAPABILITY)
        if not isinstance(value, dict):
            try:
                value = dict(value or {})
            except (TypeError, ValueError) as error:
                raise RuntimeError("Addon state export is not a mapping.") from error
        return dict(value)

    def snapshot(self) -> NativeSurface:
        state = self._state()
        controls = tuple(
            replace(
                control,
                value=state.get(control.id, control.default_value),
            )
            for control in self._surface.controls
        )
        return replace(self._surface, controls=controls, revision=self._revision)

    def set_value(self, control_id: str, value: Any) -> None:
        key = str(control_id or "").strip()
        control = self._controls.get(key)
        if control is None or control.kind in {
            NativeControlKind.ACTION,
            NativeControlKind.DISPLAY,
            NativeControlKind.IMAGE,
            NativeControlKind.PROGRESS,
        }:
            raise KeyError(f"Unknown editable addon state '{control_id}'.")
        state = self._state()
        state[key] = RuntimeConfigNativeAdapter._normalize(control, value)
        self._invoke(self.IMPORT_CAPABILITY, {"state": state})
        self._revision += 1
        if callable(self._persist):
            self._persist()
        self.changed.emit()


__all__ = ["AddonSessionNativeAdapter"]
