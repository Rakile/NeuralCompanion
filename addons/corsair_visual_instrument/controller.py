from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6 import QtCore

from .lighting_worker import LightingWorker
from .models import DeviceDescriptor, LightingSettings
from .settings import load_settings, normalize_settings, save_settings, settings_to_dict
from .state_source import PresenceStateSource


class CorsairVisualInstrumentController(QtCore.QObject):
    status_changed = QtCore.Signal(str, str)
    devices_changed = QtCore.Signal(object)
    settings_changed = QtCore.Signal(object)

    def __init__(
        self,
        context: Any,
        *,
        worker_factory: Callable[..., Any] = LightingWorker,
        state_source_factory: Callable[..., Any] = PresenceStateSource,
    ) -> None:
        super().__init__()
        self.context = context
        self.settings = load_settings(context.storage, context.logger)
        self.devices: tuple[DeviceDescriptor, ...] = ()
        self.status_state = "starting" if self.settings.enabled else "disabled"
        self.status_detail = "Preparing iCUE lighting…" if self.settings.enabled else "Lighting output is disabled."
        addon_root = Path(context.manifest.root_dir)
        self._worker = worker_factory(
            addon_root,
            status_callback=self._worker_status,
            devices_callback=self._worker_devices,
        )
        self._source = state_source_factory(
            self._worker.apply_snapshot,
            settings=self.settings,
            logger=context.logger,
        )
        self._shutdown = False
        self.status_changed.connect(self._accept_status)
        self.devices_changed.connect(self._accept_devices)
        self._worker.apply_settings(self.settings)
        if self.settings.enabled:
            self._worker.start()
            try:
                self._source.start()
            except Exception as exc:
                context.logger.warning("[Corsair LEDs] Presence state adapter could not start: %s", exc)

    @QtCore.Slot(str, str)
    def _accept_status(self, state: str, detail: str) -> None:
        self.status_state = str(state)
        self.status_detail = str(detail)

    @QtCore.Slot(object)
    def _accept_devices(self, devices: object) -> None:
        self.devices = tuple(devices or ())  # type: ignore[arg-type]

    def _worker_status(self, state: str, detail: str) -> None:
        self.status_changed.emit(str(state), str(detail))

    def _worker_devices(self, devices: tuple[DeviceDescriptor, ...]) -> None:
        self.devices_changed.emit(tuple(devices))

    def update_settings(self, **changes: Any) -> LightingSettings:
        payload = settings_to_dict(self.settings)
        payload.update(changes)
        previous_enabled = self.settings.enabled
        self.settings = normalize_settings(payload)
        try:
            save_settings(self.context.storage, self.settings)
        except Exception as exc:
            self.context.logger.warning("[Corsair LEDs] Settings could not be saved: %s", exc)
        self._source.apply_settings(self.settings)
        self._worker.apply_settings(self.settings)
        if self.settings.enabled:
            self._worker.start()
            if not previous_enabled:
                try:
                    self._source.start()
                except Exception as exc:
                    self.context.logger.warning("[Corsair LEDs] Presence state adapter could not start: %s", exc)
        elif previous_enabled:
            self._source.stop()
        self.settings_changed.emit(self.settings)
        return self.settings

    def rescan(self) -> None:
        if self.settings.enabled:
            self._worker.start()
            self._worker.rescan()

    def preview_state(self, state: str) -> None:
        if self.settings.enabled:
            self._worker.preview_state(state)

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        try:
            self._source.stop()
        except Exception:
            pass
        self._worker.request_stop()
