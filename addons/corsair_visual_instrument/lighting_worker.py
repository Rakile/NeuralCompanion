from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .device_layout import normalize_layout
from .effects import _animation_profile_for_state, render_k55_frame, render_k65_frame
from .icue_sdk import IcueSdkBridge, locate_sdk_dll
from .models import DeviceDescriptor, LightingSettings, RuntimeSnapshot
from .wave_engine import AudioWaveTracker


class LightingWorker:
    """Own the blocking iCUE connection and coalesce updates into bounded-rate frames."""

    def __init__(
        self,
        addon_root: Path,
        *,
        bridge_factory: Callable[[LightingSettings], Any] | None = None,
        status_callback: Callable[[str, str], None] | None = None,
        devices_callback: Callable[[tuple[DeviceDescriptor, ...]], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._addon_root = Path(addon_root)
        self._bridge_factory = bridge_factory or self._create_bridge
        self._status_callback = status_callback
        self._devices_callback = devices_callback
        self._clock = clock
        self._condition = threading.Condition(threading.RLock())
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._settings = LightingSettings()
        self._snapshot = RuntimeSnapshot()
        self._preview: tuple[RuntimeSnapshot, float] | None = None
        self._bridge: Any = None
        self._devices: tuple[DeviceDescriptor, ...] = ()
        self._layouts: dict[str, tuple] = {}
        self._active_device_ids: set[str] = set()
        self._scan_requested = True
        self._reconnect_requested = False
        self._last_status: tuple[str, str] | None = None
        self._wave_tracker = AudioWaveTracker()

    def _create_bridge(self, settings: LightingSettings) -> IcueSdkBridge:
        dll_path = locate_sdk_dll(self._addon_root, settings.sdk_dll_path)
        return IcueSdkBridge(dll_path, connection_timeout_s=1.5)

    def start(self) -> None:
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                daemon=True,
                name="nc-corsair-lighting",
            )
            self._thread.start()

    def stop(self, *, timeout: float = 2.0) -> bool:
        self.request_stop()
        with self._condition:
            thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.0, float(timeout)))
        stopped = bool(thread is None or not thread.is_alive())
        if stopped:
            with self._condition:
                self._thread = None
        return stopped

    def request_stop(self) -> None:
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()

    def apply_settings(self, settings: LightingSettings) -> None:
        with self._condition:
            previous = self._settings
            self._settings = settings
            if previous.sdk_dll_path != settings.sdk_dll_path:
                self._reconnect_requested = True
            self._condition.notify_all()

    def apply_snapshot(self, snapshot: RuntimeSnapshot) -> None:
        with self._condition:
            self._snapshot = snapshot
            self._condition.notify_all()

    def rescan(self) -> None:
        with self._condition:
            # iCUE fixes SDK/device-control permissions at session startup.
            # Reopening the shared session lets newly enabled devices appear.
            self._reconnect_requested = True
            self._condition.notify_all()

    def preview_state(self, state: str, *, duration_s: float = 2.5) -> None:
        value = str(state or "idle").strip().lower()
        if value not in {"idle", "listening", "thinking", "speaking"}:
            value = "idle"
        with self._condition:
            self._preview = (
                RuntimeSnapshot(
                    state=value,
                    mood=self._snapshot.mood,
                    level=0.78 if value == "speaking" else 0.0,
                    level_source="preview",
                ),
                self._clock() + max(0.1, float(duration_s)),
            )
            self._condition.notify_all()

    def _run(self) -> None:
        reconnect_delay = 0.4
        next_frame_at = 0.0
        disabled_reported = False
        try:
            while not self._stop_event.is_set():
                with self._condition:
                    settings = self._settings
                    reconnect = self._reconnect_requested
                    if reconnect:
                        self._reconnect_requested = False

                if not settings.enabled:
                    if self._bridge is not None:
                        self._clear_and_disconnect(settings)
                    if not disabled_reported:
                        self._report("disabled", "Lighting output is disabled.")
                        disabled_reported = True
                    self._wait(0.5)
                    continue
                disabled_reported = False

                if reconnect and self._bridge is not None:
                    self._clear_and_disconnect(settings)

                if self._bridge is None:
                    try:
                        self._report("connecting", "Connecting to iCUE SDK…")
                        bridge = self._bridge_factory(settings)
                        self._bridge = bridge
                        bridge.connect()
                        self._scan_devices()
                        reconnect_delay = 0.4
                        self._report("connected", self._connected_detail())
                    except Exception as exc:
                        self._disconnect_without_clear()
                        self._report("error", str(exc))
                        self._wait(reconnect_delay)
                        reconnect_delay = min(5.0, reconnect_delay * 1.8)
                        continue

                try:
                    with self._condition:
                        scan_requested = self._scan_requested
                        self._scan_requested = False
                    if scan_requested:
                        self._scan_devices()
                    now = self._clock()
                    if now < next_frame_at:
                        self._wait(min(0.2, next_frame_at - now))
                        continue
                    self._render_frame(settings, now)
                    next_frame_at = now + (1.0 / max(5, min(30, settings.frame_rate_hz)))
                except Exception as exc:
                    self._report("error", str(exc))
                    self._disconnect_without_clear()
        finally:
            with self._condition:
                settings = self._settings
            self._clear_and_disconnect(settings)
            self._report("stopped", "Lighting worker stopped.")

    def _wait(self, timeout: float) -> None:
        with self._condition:
            if not self._stop_event.is_set():
                self._condition.wait(timeout=max(0.002, float(timeout)))

    def _scan_devices(self) -> None:
        bridge = self._bridge
        if bridge is None:
            return
        if getattr(bridge, "connected", True) is False:
            raise RuntimeError("iCUE SDK connection was lost.")
        devices = tuple(bridge.list_keyboards())
        layouts = {device.device_id: normalize_layout(device.led_points) for device in devices}
        with self._condition:
            self._devices = devices
            self._layouts = layouts
        callback = self._devices_callback
        if callback is not None:
            try:
                callback(devices)
            except Exception:
                pass

    @staticmethod
    def _automatic_renderer(device: DeviceDescriptor) -> str:
        """Choose the legacy zone renderer only for coarse lighting layouts."""

        return "zones" if 0 < len(device.led_points) <= 8 else "spatial"

    def _resolved_devices(
        self, settings: LightingSettings
    ) -> tuple[tuple[DeviceDescriptor, str], ...]:
        with self._condition:
            devices = self._devices
        by_id = {device.device_id: device for device in devices}
        configured_zone = by_id.get(settings.k55_device_id)
        configured_spatial = by_id.get(settings.k65_device_id)
        resolved: list[tuple[DeviceDescriptor, str]] = []
        assigned: set[str] = set()
        for device, renderer in (
            (configured_zone, "zones"),
            (configured_spatial, "spatial"),
        ):
            if (
                device is None
                or not device.led_points
                or device.device_id in assigned
            ):
                continue
            resolved.append((device, renderer))
            assigned.add(device.device_id)

        for device in devices:
            if not device.led_points or device.device_id in assigned:
                continue
            renderer = self._automatic_renderer(device)
            if renderer == "zones" and settings.k55_device_id:
                continue
            if renderer == "spatial" and settings.k65_device_id:
                continue
            resolved.append((device, renderer))
            assigned.add(device.device_id)
        return tuple(resolved)

    def _render_frame(self, settings: LightingSettings, now: float) -> None:
        bridge = self._bridge
        if bridge is None:
            return
        if getattr(bridge, "connected", True) is False:
            raise RuntimeError("iCUE SDK connection was lost.")
        with self._condition:
            preview = self._preview
            if preview is not None and now >= preview[1]:
                self._preview = None
                preview = None
            snapshot = preview[0] if preview is not None else self._snapshot
            layouts = dict(self._layouts)
        profile = _animation_profile_for_state(settings, snapshot.state)
        wave_pulses = self._wave_tracker.update(snapshot, now, profile)
        resolved_devices = self._resolved_devices(settings)
        assigned_ids = {device.device_id for device, _renderer in resolved_devices}
        self._clear_device_ids(self._active_device_ids - assigned_ids)
        self._active_device_ids = assigned_ids
        errors: list[str] = []
        for device, renderer in resolved_devices:
            layout = layouts.get(device.device_id, ())
            if not layout:
                continue
            try:
                if renderer == "zones":
                    frame = render_k55_frame(
                        layout, snapshot, settings, now_s=now
                    )
                else:
                    frame = render_k65_frame(
                        layout,
                        snapshot,
                        settings,
                        now_s=now,
                        wave_pulses=wave_pulses,
                    )
                bridge.set_led_colors(device.device_id, frame)
            except Exception as exc:
                errors.append(f"{device.model or device.device_id}: {exc}")
        if errors:
            self._report("degraded", "; ".join(errors))
        else:
            self._report("connected", self._connected_detail())

    def _connected_detail(self) -> str:
        with self._condition:
            devices = self._devices
        count = len(devices)
        addressable = sum(1 for device in devices if device.led_points)
        label = f"{count} Corsair keyboard{'s' if count != 1 else ''} found"
        if count and not addressable:
            return f"Connected to iCUE; {label}, but none expose controllable LEDs."
        return f"Connected to iCUE; {label}; {addressable} ready for lighting output."

    def _clear_and_disconnect(self, settings: LightingSettings) -> None:
        del settings
        bridge = self._bridge
        if bridge is None:
            return
        self._clear_device_ids(set(self._active_device_ids))
        self._active_device_ids.clear()
        self._disconnect_without_clear()

    def _clear_device_ids(self, device_ids: set[str]) -> None:
        bridge = self._bridge
        if bridge is None or not device_ids:
            return
        with self._condition:
            devices = tuple(device for device in self._devices if device.device_id in device_ids)
        for device in devices:
            try:
                bridge.clear_device(device)
            except Exception:
                pass

    def _disconnect_without_clear(self) -> None:
        bridge = self._bridge
        self._bridge = None
        self._active_device_ids.clear()
        if bridge is not None:
            try:
                bridge.disconnect()
            except Exception:
                pass

    def _report(self, state: str, detail: str) -> None:
        status = (str(state), str(detail))
        if status == self._last_status:
            return
        self._last_status = status
        callback = self._status_callback
        if callback is not None:
            try:
                callback(*status)
            except Exception:
                pass
