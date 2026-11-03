"""Registration and command routing for native QML surface adapters."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from PySide6 import QtCore

from ui.qml_bridge.native_commands import NativeCommandRunner
from ui.qml_bridge.native_contracts import NativeSurface


class NativeSurfaceAdapter(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self, surface_id: str, addon_id: str, parent=None) -> None:
        super().__init__(parent)
        self.surface_id = str(surface_id or "").strip()
        self.addon_id = str(addon_id or "").strip()
        if not self.surface_id or not self.addon_id:
            raise ValueError("Native surface adapters require surface and addon ids.")

    def snapshot(self) -> NativeSurface:
        raise NotImplementedError

    def set_value(self, control_id: str, value: Any) -> None:
        raise NotImplementedError

    def trigger(self, control_id: str) -> None:
        raise KeyError(f"Native surface '{self.surface_id}' has no action '{control_id}'.")

    def trigger_with_payload(self, control_id: str, payload: Any) -> None:
        _ = payload
        self.trigger(control_id)


class NativeSurfaceRegistry(QtCore.QObject):
    surfacesChanged = QtCore.Signal()
    surfaceChanged = QtCore.Signal(str)
    actionCompleted = QtCore.Signal(str, str, bool, str)

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._adapters: dict[str, NativeSurfaceAdapter] = {}
        self._commands = NativeCommandRunner(self)
        self._ui_actions_pending: set[str] = set()
        self._commands.completed.connect(self._action_completed)

    def register(self, adapter: NativeSurfaceAdapter) -> None:
        if not isinstance(adapter, NativeSurfaceAdapter):
            raise TypeError("Native surface registry accepts NativeSurfaceAdapter values.")
        if adapter.surface_id in self._adapters:
            raise ValueError(f"Native surface '{adapter.surface_id}' is already registered.")
        adapter.setParent(self)
        adapter.changed.connect(
            lambda surface_id=adapter.surface_id: self.surfaceChanged.emit(surface_id)
        )
        self._adapters[adapter.surface_id] = adapter
        self.surfacesChanged.emit()

    def register_many(self, adapters: Iterable[NativeSurfaceAdapter]) -> None:
        for adapter in adapters:
            self.register(adapter)

    def adapter(self, surface_id: str) -> NativeSurfaceAdapter | None:
        return self._adapters.get(str(surface_id or "").strip())

    def adapter_for_addon(self, addon_id: str) -> NativeSurfaceAdapter | None:
        target = str(addon_id or "").strip()
        return next(
            (adapter for adapter in self._adapters.values() if adapter.addon_id == target),
            None,
        )

    def surface(self, surface_id: str) -> NativeSurface | None:
        adapter = self.adapter(surface_id)
        return adapter.snapshot() if adapter is not None else None

    def set_value(self, surface_id: str, control_id: str, value: Any) -> None:
        adapter = self.adapter(surface_id)
        if adapter is None:
            raise KeyError(f"Unknown native surface '{surface_id}'.")
        adapter.set_value(str(control_id or ""), value)

    def trigger(self, surface_id: str, control_id: str) -> None:
        adapter = self.adapter(surface_id)
        if adapter is None:
            raise KeyError(f"Unknown native surface '{surface_id}'.")
        adapter.trigger(str(control_id or ""))

    def trigger_async(
        self,
        surface_id: str,
        control_id: str,
        payload: Any = None,
    ) -> bool:
        normalized_surface = str(surface_id or "").strip()
        normalized_control = str(control_id or "").strip()
        adapter = self.adapter(normalized_surface)
        if adapter is None:
            raise KeyError(f"Unknown native surface '{surface_id}'.")
        command_key = f"{normalized_surface}::{normalized_control}"
        surface = adapter.snapshot()
        action = next(
            (item for item in surface.controls if item.id == normalized_control),
            None,
        )
        if action is not None and str(action.metadata.get("execution") or "") == "ui":
            if command_key in self._ui_actions_pending:
                return False
            self._ui_actions_pending.add(command_key)

            def invoke_ui_action() -> None:
                try:
                    adapter.trigger_with_payload(normalized_control, payload)
                except (KeyError, RuntimeError, TypeError, ValueError) as error:
                    self.actionCompleted.emit(
                        normalized_surface,
                        normalized_control,
                        False,
                        str(error),
                    )
                    return
                else:
                    self.actionCompleted.emit(
                        normalized_surface,
                        normalized_control,
                        True,
                        "",
                    )
                    self.surfaceChanged.emit(normalized_surface)
                finally:
                    self._ui_actions_pending.discard(command_key)

            QtCore.QTimer.singleShot(0, invoke_ui_action)
            return True
        return self._commands.submit(
            command_key,
            lambda: adapter.trigger_with_payload(normalized_control, payload),
        )

    @QtCore.Slot(str, bool, object, str)
    def _action_completed(
        self,
        command_key: str,
        accepted: bool,
        _result: object,
        error: str,
    ) -> None:
        surface_id, _separator, control_id = str(command_key).partition("::")
        self.actionCompleted.emit(surface_id, control_id, bool(accepted), error)
        if accepted:
            self.surfaceChanged.emit(surface_id)

    def coverage(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    def close(self) -> None:
        self._ui_actions_pending.clear()
        self._commands.close()


__all__ = ["NativeSurfaceAdapter", "NativeSurfaceRegistry"]
