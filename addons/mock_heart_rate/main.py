"""Widget-free mock heart-rate source for the native QML application."""

from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6 import QtCore

from core.addons import BaseAddon


def _load_sensory_metadata(root_dir: Path) -> dict:
    path = root_dir / "sensory_metadata.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return dict(payload or {}) if isinstance(payload, dict) else {}


class _Subscriber:
    __slots__ = ("callback", "interval_seconds", "last_emitted_at")

    def __init__(self, callback: object, interval_seconds: float) -> None:
        self.callback = callback
        self.interval_seconds = float(interval_seconds)
        self.last_emitted_at = 0.0


class MockHeartRateService:
    def __init__(self, addon: "Addon") -> None:
        self._addon = addon
        self._subscribers: dict[int, _Subscriber] = {}
        self._next_token = 1

    def current_bpm(self) -> int:
        return int(self._addon.current_bpm)

    def snapshot(self) -> dict:
        return {
            "bpm": int(self._addon.current_bpm),
            "updated_at": float(self._addon.last_updated_at),
            "window_visible": bool(self._addon.monitor_visible),
            "source": "heart_rate",
        }

    def set_bpm(self, value: int) -> int:
        return self._addon.set_bpm(value)

    def subscribe(
        self,
        callback,
        *,
        interval_seconds: float | None = None,
        per_second: float | None = None,
    ) -> int:
        if not callable(callback):
            raise ValueError("MockHeartRateService.subscribe requires a callable callback.")
        raw_interval = interval_seconds if interval_seconds is not None else per_second
        try:
            interval = max(0.05, float(raw_interval if raw_interval is not None else 0.5))
        except (TypeError, ValueError):
            interval = 0.5
        token = self._next_token
        self._next_token += 1
        self._subscribers[token] = _Subscriber(callback, interval)
        return token

    def unsubscribe(self, token: int) -> bool:
        return self._subscribers.pop(int(token), None) is not None

    def emit_if_due(self, *, force: bool = False) -> None:
        now = time.time()
        payload = self.snapshot()
        for token, subscriber in list(self._subscribers.items()):
            if not force and now - subscriber.last_emitted_at < subscriber.interval_seconds:
                continue
            try:
                subscriber.callback(dict(payload))
                subscriber.last_emitted_at = now
            except Exception:
                self._addon.logger.exception(
                    "Mock heart-rate subscriber failed for token %s", token
                )


class Addon(BaseAddon):
    """Publishes a bounded mock physiological stream without a QWidget monitor."""

    def initialize(self, context) -> None:
        super().initialize(context)
        self.logger = context.logger
        self._events = context.events
        self._sensory_targets = context.capabilities.sensory_targets
        self.current_bpm = 72
        self.last_updated_at = time.time()
        self.monitor_visible = False
        self.service = MockHeartRateService(self)

        context.services.register(
            "heart_rate.mock",
            self.service,
            metadata={"kind": "physiology", "unit": "bpm", "range": [0, 200]},
        )
        if self._sensory_targets is not None:
            metadata = _load_sensory_metadata(Path(context.manifest.root_dir))
            self._sensory_targets.register_provider(
                provider_id="heart_rate",
                label=str(metadata.get("label") or "Heart Rate"),
                instruction=str(metadata.get("instruction") or ""),
                description=str(metadata.get("description") or ""),
                order=int(metadata.get("order", 280) or 280),
                capture_handler=self._capture_sensory_snapshot,
                metadata=dict(metadata.get("metadata") or {}),
            )

        self._tick_timer = QtCore.QTimer()
        self._tick_timer.setInterval(100)
        self._tick_timer.timeout.connect(self.service.emit_if_due)
        self._tick_timer.start()
        context.logger.info("Mock heart-rate native service initialized.")

    def _capture_sensory_snapshot(self, capture_context=None) -> dict:
        _ = capture_context
        bpm = int(self.current_bpm)
        return {
            "source": "heart_rate",
            "captured_at": time.time(),
            "content": "This is the user's current heart rate in BPM",
            "metadata": {
                "kind": "physiology",
                "metric": "heart_rate_bpm",
                "unit": "bpm",
                "value": bpm,
            },
        }

    def set_bpm(self, value: int) -> int:
        bpm = max(0, min(200, int(value)))
        self.current_bpm = bpm
        self.last_updated_at = time.time()
        self.service.emit_if_due(force=True)
        self._events.publish(
            "sensor.heart_rate.updated",
            {"source": "heart_rate", "bpm": bpm, "updated_at": self.last_updated_at},
        )
        return bpm

    def _set_monitor_visible(self, visible: object) -> bool:
        self.monitor_visible = bool(visible)
        self._events.publish(
            "sensor.heart_rate.monitor_visibility_changed",
            {"visible": self.monitor_visible, "bpm": int(self.current_bpm)},
        )
        return self.monitor_visible

    def export_session_state(self) -> dict:
        return {
            "mock_heart_rate_bpm": int(self.current_bpm),
            "mock_heart_rate_window_visible": bool(self.monitor_visible),
        }

    def export_preset_state(self) -> dict:
        return self.export_session_state()

    def import_session_state(self, session) -> None:
        state = dict(session or {})
        self.set_bpm(state.get("mock_heart_rate_bpm", self.current_bpm))
        self._set_monitor_visible(state.get("mock_heart_rate_window_visible", False))

    def import_preset_state(self, preset) -> None:
        self.import_session_state(preset)

    def invoke_capability(self, capability, payload=None):
        name = str(capability or "").strip()
        request = dict(payload or {})
        if name == "runtime.session.export":
            return self.export_session_state()
        if name == "runtime.session.import":
            self.import_session_state(dict(request.get("state") or {}))
            return {"accepted": True}
        if name == "runtime.mock_heart_rate.snapshot":
            return self.service.snapshot()
        if name == "runtime.mock_heart_rate.set_bpm":
            return {"bpm": self.set_bpm(request.get("bpm", self.current_bpm))}
        if name == "runtime.mock_heart_rate.set_monitor_visible":
            return {"visible": self._set_monitor_visible(request.get("visible", False))}
        return None

    def shutdown(self) -> None:
        timer = getattr(self, "_tick_timer", None)
        if timer is not None:
            timer.stop()
        if self._sensory_targets is not None:
            try:
                self._sensory_targets.unregister_provider("heart_rate")
            except Exception:
                self.logger.exception("Failed to unregister mock heart-rate sensory source.")
        self.monitor_visible = False
        self.service._subscribers.clear()
