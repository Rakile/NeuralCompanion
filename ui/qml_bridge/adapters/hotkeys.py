"""Native QML presentation adapter for the Hotkeys addon."""

from __future__ import annotations

from typing import Any

from ui.qml_bridge.native_contracts import (
    NativeControl,
    NativeControlKind,
    NativeSurface,
)
from ui.qml_bridge.native_registry import NativeSurfaceAdapter


_SECTION_BY_CATEGORY = {
    "input": "Input",
    "manual_controls": "Conversation controls",
    "ui_actions": "Window controls",
}


class HotkeysNativeAdapter(NativeSurfaceAdapter):
    """Render and edit hotkeys through the addon's finite capability API."""

    def __init__(self, application_facade: Any, parent=None) -> None:
        super().__init__("hotkeys_tab", "nc.hotkeys", parent)
        self._application = application_facade
        self._revision = 0

    def snapshot(self) -> NativeSurface:
        catalog = self._invoke("runtime.backend.hotkey_catalog")
        rows = list(catalog or []) if isinstance(catalog, (list, tuple)) else []
        controls = []
        for row in rows:
            payload = dict(row or {})
            action = str(payload.get("action") or "").strip()
            if not action:
                continue
            category = str(payload.get("category") or "").strip().lower()
            section = _SECTION_BY_CATEGORY.get(category, "Overview")
            scope = str(payload.get("scope") or "").strip().lower()
            scope_key = scope or "application"
            scope_title = "Global shortcuts" if scope == "global" else "Application shortcuts"
            controls.append(
                NativeControl(
                    id=action,
                    label=str(payload.get("label") or action),
                    kind=NativeControlKind.TEXT,
                    section=section,
                    description=str(payload.get("description") or ""),
                    value=str(payload.get("binding") or ""),
                    default_value=str(payload.get("default_binding") or ""),
                    metadata={
                        "groupKey": f"{category or 'general'}_{scope_key}",
                        "groupTitle": scope_title,
                        "groupColumnSpan": 1,
                        "scope": scope,
                    },
                )
            )
        controls.append(
            NativeControl(
                id="reset_hotkeys",
                label="Restore default hotkeys",
                kind=NativeControlKind.ACTION,
                section="Window controls",
                description="Restore all input, conversation, and window shortcuts to their defaults.",
                metadata={
                    "destructive": True,
                    "groupKey": "reset",
                    "groupTitle": "Restore defaults",
                    "groupColumnSpan": 1,
                },
            )
        )
        return NativeSurface(
            id=self.surface_id,
            addon_id=self.addon_id,
            title="Hotkeys",
            description="Configure input and NeuralCompanion action shortcuts.",
            sections=("Input", "Conversation controls", "Window controls"),
            controls=tuple(controls),
            revision=self._revision,
        )

    def set_value(self, control_id: str, value: Any) -> None:
        action = str(control_id or "").strip()
        if not action or action == "reset_hotkeys":
            raise KeyError(f"Unknown hotkey control '{control_id}'.")
        self._invoke(
            "runtime.backend.set_hotkey_binding",
            {"args": [action, str(value or "")]},
        )
        self._revision += 1
        self.changed.emit()

    def trigger(self, control_id: str) -> None:
        if str(control_id or "").strip() != "reset_hotkeys":
            raise KeyError(f"Unknown hotkey action '{control_id}'.")
        self._invoke("runtime.backend.reset_hotkey_bindings")
        self._revision += 1
        self.changed.emit()

    def _invoke(self, capability: str, payload=None) -> Any:
        result = self._application.addons.invoke_addon_capability(
            self.addon_id,
            capability,
            dict(payload or {}),
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            raise RuntimeError(
                str(getattr(failure, "message", "Hotkeys addon is unavailable."))
            )
        return result.value


__all__ = ["HotkeysNativeAdapter"]
