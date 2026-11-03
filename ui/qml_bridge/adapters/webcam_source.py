"""Native QML camera discovery and selection for Webcam sensory capture."""

from __future__ import annotations

import threading
from dataclasses import replace
from typing import Any, Callable, Mapping

from ui.qml_bridge.adapters.card_layout import apply_card_layout
from ui.qml_bridge.adapters.config import RuntimeConfigNativeAdapter
from ui.qml_bridge.native_contracts import (
    NativeChoice,
    NativeControl,
    NativeControlKind,
    NativeSurface,
)


class WebcamSourceNativeAdapter(RuntimeConfigNativeAdapter):
    _READ_ONLY_IDS = {"webcam_source_status"}

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._devices: tuple[dict[str, object], ...] = ()
        self._discovery_error = ""
        self._discovery_started = False
        self._refreshing = False
        self._state_lock = threading.RLock()

    def _invoke(self, capability: str, payload=None) -> object:
        result = self._application.addons.invoke_addon_capability(
            self.addon_id, capability, dict(payload or {})
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            raise RuntimeError(
                str(getattr(failure, "message", "Webcam Source is unavailable."))
            )
        return result.value

    def _refresh_catalog(self) -> None:
        try:
            raw = self._invoke("runtime.webcam.discover_devices")
            devices = tuple(
                dict(item)
                for item in (raw or ())
                if isinstance(item, Mapping) and str(item.get("id") or "").strip()
            )
            error = ""
        except BaseException as exc:
            devices = ()
            error = str(exc).strip() or "Camera discovery failed."
        with self._state_lock:
            self._devices = devices
            self._discovery_error = error
            self._discovery_started = True
            self._refreshing = False
            self._revision += 1
        self.changed.emit()

    def snapshot(self) -> NativeSurface:
        surface = super().snapshot()
        selected = str(
            self._application.config.get("webcam_source_device_id", "0") or "0"
        ).strip()
        with self._state_lock:
            devices = tuple(self._devices)
            error = self._discovery_error
            discovery_started = self._discovery_started
            refreshing = self._refreshing
        by_id = {str(item.get("id")): item for item in devices}
        choice_items = [NativeChoice("", "Choose an available camera...")]
        choice_items.extend(
            NativeChoice(str(item["id"]), str(item.get("label") or item["id"]))
            for item in devices
        )
        if selected and selected not in by_id:
            choice_items.append(NativeChoice(selected, f"Saved camera {selected}"))

        if refreshing:
            status = "Discovering cameras..."
        elif error:
            status = f"Camera discovery error: {error}"
        elif not discovery_started:
            status = "Press Refresh cameras to discover connected devices."
        elif not devices:
            status = "No available cameras were detected."
        elif selected not in by_id:
            status = "The saved camera is unavailable. Choose an available camera."
        else:
            status = f"Ready: {by_id[selected].get('label') or selected}"

        controls = []
        for control in surface.controls:
            if control.id == "webcam_source_device_id":
                control = replace(
                    control,
                    value=selected,
                    choices=tuple(choice_items),
                )
            elif control.id == "webcam_source_status":
                control = replace(control, value=status)
            controls.append(control)
        return replace(
            surface,
            controls=apply_card_layout(tuple(controls)),
            revision=self._revision,
        )

    def set_value(self, control_id: str, value: Any) -> None:
        key = str(control_id or "").strip()
        if key in self._READ_ONLY_IDS:
            raise KeyError(f"Webcam display '{key}' is read-only.")
        if key == "webcam_source_device_id":
            selected = str(value or "").strip()
            with self._state_lock:
                known = {str(item.get("id")) for item in self._devices}
            if selected and known and selected not in known:
                raise ValueError(f"Camera '{selected}' is not currently available.")
            result = self._application.config.update(key, selected)
            if not result.accepted:
                failure = getattr(result, "failure", None)
                raise RuntimeError(
                    str(getattr(failure, "message", "Could not save camera selection."))
                )
            self._revision += 1
            if callable(self._persist):
                self._persist()
            self.changed.emit()
            return
        super().set_value(key, value)

    def trigger(self, control_id: str) -> None:
        if str(control_id or "").strip() != "webcam_source_refresh_devices":
            raise KeyError(f"Unknown Webcam Source action '{control_id}'.")
        with self._state_lock:
            if self._refreshing:
                return
            self._refreshing = True
            self._revision += 1
        self.changed.emit()
        threading.Thread(
            target=self._refresh_catalog,
            name="NCWebcamDiscovery",
            daemon=True,
        ).start()


def build_webcam_source_adapter(
    application_facade: Any,
    *,
    persist: Callable[[], object] | None = None,
) -> WebcamSourceNativeAdapter:
    surface = NativeSurface(
        id="webcam_source_tab",
        title="Webcam",
        addon_id="nc.webcam_source",
        sections=("Camera",),
        description="Discover and select the camera used for hidden sensory snapshots.",
        controls=(
            NativeControl(
                "webcam_source_status",
                "Camera status",
                NativeControlKind.DISPLAY,
                "Camera",
            ),
            NativeControl(
                "webcam_source_device_id",
                "Capture camera",
                NativeControlKind.CHOICE,
                "Camera",
                default_value="0",
                choices=(NativeChoice("0", "Saved camera 0"),),
            ),
            NativeControl(
                "webcam_source_refresh_devices",
                "Refresh cameras",
                NativeControlKind.ACTION,
                "Camera",
                metadata={"execution": "ui"},
            ),
        ),
    )
    return WebcamSourceNativeAdapter(application_facade, surface, persist=persist)


__all__ = ["WebcamSourceNativeAdapter", "build_webcam_source_adapter"]
