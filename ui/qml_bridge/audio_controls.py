"""Native QML audio device and meter controls."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from PySide6 import QtCore

from visual_presence import runtime as presence_runtime


def _clamp_unit(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 1.0
    return max(0.0, min(1.0, number))


def _deduplicated(values) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        label = str(value or "").strip()
        key = label.casefold()
        if not label or key in seen:
            continue
        seen.add(key)
        result.append(label)
    return result


def enumerate_audio_devices() -> tuple[list[str], list[str], str]:
    """Enumerate NC-compatible labels away from the Qt UI thread."""

    input_names: list[str] = ["Default Input"]
    output_names: list[str] = ["Default Output"]
    errors: list[str] = []
    try:
        import speech_recognition as sr

        input_names.extend(sr.Microphone.list_microphone_names() or ())
    except Exception as exc:
        errors.append(f"input devices: {exc}")
    try:
        import sounddevice as sd

        output_names.extend(
            str(device.get("name") or "")
            for device in list(sd.query_devices() or ())
            if int(device.get("max_output_channels", 0) or 0) > 0
        )
    except Exception as exc:
        errors.append(f"output devices: {exc}")
    return (
        _deduplicated(input_names),
        _deduplicated(output_names),
        "; ".join(errors),
    )


class AudioControlsBridge(QtCore.QObject):
    """Expose existing NC audio configuration and read-only live meters."""

    changed = QtCore.Signal()
    devicesChanged = QtCore.Signal()
    metersChanged = QtCore.Signal()
    _devicesReady = QtCore.Signal(object, object, str)
    _configurationChanged = QtCore.Signal(object)

    def __init__(
        self,
        application: Any,
        *,
        persist: Callable[[], object] | None = None,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._application = application
        self._persist = persist
        self._inputs = ["Default Input"]
        self._outputs = ["Default Output"]
        self._refreshing = False
        self._status = "Select the devices used by NC."
        self._output_level = 0.0
        self._input_level = 0.0
        self._input_voice_active = False
        self._closing = False
        self._config_subscription = None
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="nc-audio-devices",
        )
        self._devicesReady.connect(
            self._apply_devices,
            QtCore.Qt.ConnectionType.QueuedConnection,
        )
        self._configurationChanged.connect(
            self._on_configuration_changed,
            QtCore.Qt.ConnectionType.QueuedConnection,
        )
        subscriptions = getattr(application, "subscriptions", None)
        subscribe = getattr(subscriptions, "config", None)
        if callable(subscribe):
            self._config_subscription = subscribe(
                lambda event: self._configurationChanged.emit(event)
            )
        self._meter_timer = QtCore.QTimer(self)
        self._meter_timer.setInterval(50)
        self._meter_timer.timeout.connect(self._refresh_meters)
        self._meter_timer.start()
        self._save_timer = QtCore.QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(350)
        self._save_timer.timeout.connect(self._persist_now)
        self.refreshDevices()

    @QtCore.Property("QVariantList", notify=devicesChanged)
    def inputDevices(self) -> list[str]:
        return list(self._inputs)

    @QtCore.Property("QVariantList", notify=devicesChanged)
    def outputDevices(self) -> list[str]:
        return list(self._outputs)

    @QtCore.Property(str, notify=changed)
    def selectedInputDevice(self) -> str:
        return str(
            self._application.config.get("audio_input_device", "Default Input")
            or "Default Input"
        )

    @QtCore.Property(str, notify=changed)
    def selectedOutputDevice(self) -> str:
        return str(
            self._application.config.get("audio_output_device", "Default Output")
            or "Default Output"
        )

    @QtCore.Property(float, notify=changed)
    def outputVolume(self) -> float:
        return _clamp_unit(self._application.config.get("audio_output_volume", 1.0))

    @QtCore.Property(bool, notify=changed)
    def microphonePresenceEnabled(self) -> bool:
        return bool(
            self._application.config.get(
                "ai_presence_microphone_reactivity_enabled",
                False,
            )
        )

    @QtCore.Property(float, notify=metersChanged)
    def outputLevel(self) -> float:
        return self._output_level

    @QtCore.Property(float, notify=metersChanged)
    def inputLevel(self) -> float:
        return self._input_level

    @QtCore.Property(bool, notify=metersChanged)
    def inputVoiceActive(self) -> bool:
        return self._input_voice_active

    @QtCore.Property(bool, notify=changed)
    def refreshing(self) -> bool:
        return self._refreshing

    @QtCore.Property(str, notify=changed)
    def statusMessage(self) -> str:
        return self._status

    @QtCore.Slot()
    def refreshDevices(self) -> None:
        if self._closing or self._refreshing:
            return
        self._refreshing = True
        self._status = "Scanning audio devices…"
        self.changed.emit()
        future = self._executor.submit(enumerate_audio_devices)
        future.add_done_callback(self._device_refresh_finished)

    def _device_refresh_finished(self, future: Future) -> None:
        if self._closing:
            return
        try:
            inputs, outputs, error = future.result()
        except Exception as exc:
            inputs, outputs, error = [], [], str(exc)
        self._devicesReady.emit(inputs, outputs, error)

    @QtCore.Slot(object, object, str)
    def _apply_devices(self, inputs: object, outputs: object, error: str) -> None:
        self._refreshing = False
        selected_input = self.selectedInputDevice
        selected_output = self.selectedOutputDevice
        self._inputs = _deduplicated(
            ["Default Input", *(list(inputs or ())), selected_input]
        )
        self._outputs = _deduplicated(
            ["Default Output", *(list(outputs or ())), selected_output]
        )
        self._status = (
            f"Some devices could not be listed: {error}"
            if error
            else "Audio devices are ready."
        )
        self.devicesChanged.emit()
        self.changed.emit()

    @QtCore.Slot(str)
    def setInputDevice(self, value: str) -> None:
        selected = str(value or "Default Input").strip() or "Default Input"
        if selected == self.selectedInputDevice:
            return
        if not self._update("audio_input_device", selected):
            return
        self._status = "Input device saved; an open microphone uses it next time it opens."
        self._persist_now()
        self.changed.emit()

    @QtCore.Slot(str)
    def setOutputDevice(self, value: str) -> None:
        selected = str(value or "Default Output").strip() or "Default Output"
        if selected == self.selectedOutputDevice:
            return
        if not self._update("audio_output_device", selected):
            return
        self._status = "Output device saved for the next NC playback segment."
        self._persist_now()
        self.changed.emit()

    @QtCore.Slot(float)
    def setOutputVolume(self, value: float) -> None:
        selected = _clamp_unit(value)
        if abs(selected - self.outputVolume) < 0.002:
            return
        if not self._update("audio_output_volume", selected):
            return
        self._save_timer.start()
        self.changed.emit()

    @QtCore.Slot(bool)
    def setMicrophonePresenceEnabled(self, enabled: bool) -> None:
        selected = bool(enabled)
        if selected == self.microphonePresenceEnabled:
            return
        if not self._update(
            "ai_presence_microphone_reactivity_enabled",
            selected,
        ):
            return
        self._status = (
            "Microphone voice will drive the separate user thread."
            if selected
            else "Microphone-to-presence reaction is off."
        )
        if not selected:
            presence_runtime.set_user_voice_analysis(None, False)
        self._persist_now()
        self.changed.emit()

    def _update(self, key: str, value: object) -> bool:
        result = self._application.config.update(str(key), value)
        if bool(getattr(result, "accepted", False)):
            return True
        failure = getattr(result, "failure", None)
        self._status = str(
            getattr(failure, "message", "The audio setting was not changed.")
        )
        self.changed.emit()
        return False

    @QtCore.Slot(object)
    def _on_configuration_changed(self, event: object) -> None:
        if self._closing:
            return
        changed_keys = tuple(getattr(event, "changed_keys", ()) or ())
        if changed_keys and not {
            "audio_input_device",
            "audio_output_device",
            "audio_output_volume",
            "ai_presence_microphone_reactivity_enabled",
        }.intersection(str(key) for key in changed_keys):
            return
        if not self.microphonePresenceEnabled:
            presence_runtime.set_user_voice_analysis(None, False)
        self.changed.emit()

    @QtCore.Slot()
    def _refresh_meters(self) -> None:
        snapshot = presence_runtime.snapshot_state()
        output_level = _clamp_unit(snapshot.get("audio_level", 0.0))
        input_level = _clamp_unit(snapshot.get("user_voice_level", 0.0))
        input_active = bool(snapshot.get("user_voice_active", False))
        if (
            abs(output_level - self._output_level) < 0.003
            and abs(input_level - self._input_level) < 0.003
            and input_active == self._input_voice_active
        ):
            return
        self._output_level = output_level
        self._input_level = input_level
        self._input_voice_active = input_active
        self.metersChanged.emit()

    def _persist_now(self) -> None:
        if callable(self._persist):
            try:
                self._persist()
            except Exception:
                pass

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._meter_timer.stop()
        self._save_timer.stop()
        subscription = self._config_subscription
        self._config_subscription = None
        if subscription is not None:
            try:
                subscription.close()
            except Exception:
                pass
        self._executor.shutdown(wait=False, cancel_futures=True)


__all__ = ["AudioControlsBridge", "enumerate_audio_devices"]
