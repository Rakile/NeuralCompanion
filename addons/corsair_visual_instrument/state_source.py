from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from typing import Any

from visual_presence.audio_spectrum import smooth_spectrum

from .models import AI_STATES, LightingSettings, RuntimeSnapshot


def _level(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


class VoiceLevelRouter:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic, freshness_s: float = 0.35) -> None:
        self._clock = clock
        self._freshness_s = max(0.05, float(freshness_s))
        self._native_level = 0.0
        self._native_at = float("-inf")
        self._loopback_level = 0.0

    def accept_native(self, value: Any) -> None:
        self._native_level = _level(value)
        self._native_at = self._clock()

    def accept_loopback(self, value: Any) -> None:
        self._loopback_level = _level(value)

    def resolve(self, state: str) -> tuple[float, str]:
        if state != "speaking":
            return 0.0, "state"
        if (self._clock() - self._native_at) <= self._freshness_s:
            return self._native_level, "native"
        return self._loopback_level, "loopback"

    def native_freshness_remaining(self) -> float:
        return max(0.0, self._freshness_s - (self._clock() - self._native_at))


class PresenceStateSource:
    """Read-only adapter for NeuralCompanion visual state and speech energy."""

    def __init__(
        self,
        on_snapshot: Callable[[RuntimeSnapshot], None],
        *,
        runtime_module: Any = None,
        meter_factory: Callable[..., Any] | None = None,
        timer_factory: Callable[[float, Callable[[], None]], Any] = threading.Timer,
        clock: Callable[[], float] = time.monotonic,
        settings: LightingSettings | None = None,
        logger: Any = None,
    ) -> None:
        if runtime_module is None:
            from visual_presence import runtime as runtime_module
        if meter_factory is None:
            from visual_presence.system_audio_meter import SystemAudioLevelMeter

            meter_factory = SystemAudioLevelMeter
        self._on_snapshot = on_snapshot
        self._runtime = runtime_module
        self._meter_factory = meter_factory
        self._timer_factory = timer_factory
        self._clock = clock
        self._logger = logger
        self._settings = settings or LightingSettings()
        self._router = VoiceLevelRouter(clock=clock)
        self._lock = threading.RLock()
        self._state = "idle"
        self._mood = "neutral"
        self._smoothed_level = 0.0
        self._smoothed_spectrum: tuple[float, ...] = ()
        self._meter = None
        self._fallback_failed = False
        self._freshness_timer = None
        self._started = False

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        try:
            self._runtime.register_orb_controller(self)
        except Exception:
            with self._lock:
                self._started = False
            raise

    def stop(self) -> None:
        with self._lock:
            was_started = self._started
            self._started = False
            self._smoothed_spectrum = ()
            meter = self._meter
            self._meter = None
            timer = self._freshness_timer
            self._freshness_timer = None
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass
        if was_started:
            try:
                self._runtime.unregister_orb_controller(self)
            except Exception as exc:
                self._log_warning("Presence unregister failed: %s", exc)
        if meter is not None:
            threading.Thread(
                target=self._stop_meter_instance,
                args=(meter,),
                daemon=True,
                name="nc-corsair-audio-stop",
            ).start()

    def apply_settings(self, settings: LightingSettings) -> None:
        with self._lock:
            self._settings = settings
            meter = self._meter
        if meter is not None:
            try:
                meter.set_fps(settings.frame_rate_hz)
            except Exception as exc:
                self._log_warning("Fallback audio meter FPS update failed: %s", exc)

    def request_ai_state(self, state: Any) -> None:
        normalized = str(state or "idle").strip().lower()
        if normalized not in AI_STATES:
            normalized = "idle"
        with self._lock:
            self._state = normalized
            if normalized != "speaking":
                self._smoothed_spectrum = ()
        if normalized == "speaking":
            self._start_meter()
        else:
            self._stop_meter()
        self._emit()

    def request_audio_level(self, value: Any) -> None:
        with self._lock:
            self._router.accept_native(value)
            fallback_failed = self._fallback_failed
        if fallback_failed:
            self._schedule_freshness_recheck()
        self._emit()

    def request_music_level(self, _value: Any) -> None:
        return None

    def request_presence_mood(self, mood: Any) -> None:
        with self._lock:
            self._mood = str(mood or "neutral").strip().lower() or "neutral"
        self._emit()

    def request_settings(self, _settings: Any) -> None:
        return None

    def _start_meter(self) -> None:
        with self._lock:
            meter = self._meter
            if meter is None:
                meter = self._meter_factory(
                    self._accept_loopback,
                    fps=self._settings.frame_rate_hz,
                    logger=self._meter_log,
                    spectrum_callback=self._accept_loopback_spectrum,
                    spectrum_bands=48,
                )
                self._meter = meter
        try:
            if not meter.is_running():
                with self._lock:
                    self._fallback_failed = False
                meter.start()
        except Exception as exc:
            self._log_warning("Fallback audio meter could not start: %s", exc)

    def _stop_meter(self) -> None:
        with self._lock:
            meter = self._meter
        if meter is not None:
            try:
                if meter.is_running():
                    meter.stop()
            except Exception as exc:
                self._log_warning("Fallback audio meter could not stop: %s", exc)

    def _accept_loopback(self, value: Any) -> None:
        with self._lock:
            if not self._started:
                return
            self._router.accept_loopback(value)
        self._emit()

    def _accept_loopback_spectrum(self, value: Any) -> None:
        try:
            target = tuple(float(part) for part in value)
        except (TypeError, ValueError):
            target = ()
        if len(target) != 48 or any(not math.isfinite(part) for part in target):
            target = ()
        else:
            target = tuple(max(0.0, min(1.0, part)) for part in target)
        with self._lock:
            if not self._started or self._state != "speaking":
                return
            if target:
                previous = self._smoothed_spectrum or ((0.0,) * 48)
                self._smoothed_spectrum = smooth_spectrum(
                    previous,
                    target,
                    self._settings.smoothing,
                )
            else:
                self._smoothed_spectrum = ()
        self._emit()

    def _stop_meter_instance(self, meter: Any) -> None:
        try:
            meter.stop()
        except Exception as exc:
            self._log_warning("Fallback audio meter stop failed: %s", exc)

    def _emit(self) -> None:
        with self._lock:
            target, source = self._router.resolve(self._state)
            if source == "loopback" and self._fallback_failed:
                target, source = 0.0, "state"
            if self._state != "speaking":
                self._smoothed_level = 0.0
            else:
                smoothing = self._settings.smoothing
                coefficient = 1.0 if smoothing <= 0.0 else (
                    max(0.08, 1.0 - smoothing)
                    if target >= self._smoothed_level
                    else max(0.03, (1.0 - smoothing) * 0.45)
                )
                self._smoothed_level += (target - self._smoothed_level) * coefficient
            snapshot = RuntimeSnapshot(
                state=self._state,
                mood=self._mood,
                level=_level(self._smoothed_level),
                level_source=source,
                spectrum=(
                    self._smoothed_spectrum if self._state == "speaking" else ()
                ),
            )
        try:
            self._on_snapshot(snapshot)
        except Exception as exc:
            self._log_warning("Snapshot callback failed: %s", exc)

    def _meter_log(self, message: str) -> None:
        with self._lock:
            self._fallback_failed = True
            self._smoothed_spectrum = ()
        self._schedule_freshness_recheck()
        self._emit()

    def _schedule_freshness_recheck(self) -> None:
        with self._lock:
            previous = self._freshness_timer
            remaining = self._router.native_freshness_remaining()
            if previous is not None:
                try:
                    previous.cancel()
                except Exception:
                    pass
            if remaining <= 0.0 or not self._started:
                self._freshness_timer = None
                return
            timer = self._timer_factory(remaining + 0.01, self._freshness_elapsed)
            try:
                timer.daemon = True
            except Exception:
                pass
            self._freshness_timer = timer
        timer.start()

    def _freshness_elapsed(self) -> None:
        with self._lock:
            self._freshness_timer = None
            started = self._started
        if started:
            self._emit()

    def _log_warning(self, message: str, *args: Any) -> None:
        logger = self._logger
        if logger is not None:
            try:
                logger.warning("[Corsair LEDs] " + message, *args)
            except Exception:
                pass
