from __future__ import annotations

import math

from .models import K65AnimationProfile, RuntimeSnapshot, WavePulse

WAVE_EFFECTS = frozenset(
    {
        "center_shockwave",
        "twin_voicefront",
        "voice_bloom",
    }
)


def _clamp(value: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return max(0.0, min(1.0, number))


def _spectrum(value) -> tuple[float, ...]:
    try:
        bands = tuple(float(part) for part in value)
    except (TypeError, ValueError):
        return ()
    if len(bands) != 48 or any(not math.isfinite(part) for part in bands):
        return ()
    return tuple(_clamp(part) for part in bands)


def _region_level(values: tuple[float, ...]) -> float:
    if not values:
        return 0.0
    return _clamp(math.sqrt(sum(value * value for value in values) / len(values)))


class AudioWaveTracker:
    """Turn bounded Speaking envelope changes into a tiny immutable pulse history."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._pulses: list[WavePulse] = []
        self._previous_level = 0.0
        self._previous_spectrum: tuple[float, ...] = ()
        self._last_pulse_at = float("-inf")
        self._last_state = "idle"

    def update(
        self,
        snapshot: RuntimeSnapshot,
        now_s: float,
        profile: K65AnimationProfile,
    ) -> tuple[WavePulse, ...]:
        try:
            now = float(now_s)
        except (TypeError, ValueError):
            now = 0.0
        if not math.isfinite(now):
            now = 0.0

        state = str(snapshot.state or "idle").strip().lower()
        active = state == "speaking" and profile.effect in WAVE_EFFECTS
        if not active:
            self.reset()
            self._last_state = state
            return ()
        if self._last_state != "speaking":
            self.reset()
        self._last_state = "speaking"

        max_age = min(2.0, 0.35 + (1.65 * _clamp(profile.trail)))
        self._pulses = [
            pulse
            for pulse in self._pulses
            if 0.0 <= now - pulse.started_at <= max_age
        ][-8:]

        bands = _spectrum(snapshot.spectrum)
        envelope = max(_clamp(snapshot.level), max(bands, default=0.0))
        reactivity = _clamp(profile.audio_reactivity / 2.0)
        if snapshot.level_source == "state" or reactivity <= 0.0:
            self._pulses.clear()
            self._previous_level = envelope
            self._previous_spectrum = bands
            return ()

        rise = max(0.0, envelope - self._previous_level)
        flux = 0.0
        if bands and len(self._previous_spectrum) == len(bands):
            flux = sum(
                max(0.0, current - previous)
                for current, previous in zip(bands, self._previous_spectrum)
            ) / len(bands)
        trigger_signal = max(rise, flux * 2.5)
        threshold = 0.012 + (0.025 * (1.0 - reactivity))

        if (
            envelope >= 0.015
            and trigger_signal >= threshold
            and now - self._last_pulse_at >= 0.07
        ):
            amplitude = _clamp(
                (envelope * (0.65 + (reactivity * 0.35)))
                + (trigger_signal * 1.25)
            )
            padded = bands or ((envelope,) * 48)
            self._pulses.append(
                WavePulse(
                    started_at=now,
                    amplitude=amplitude,
                    bass=_region_level(padded[:16]),
                    mid=_region_level(padded[16:34]),
                    treble=_region_level(padded[34:48]),
                )
            )
            self._pulses = self._pulses[-8:]
            self._last_pulse_at = now

        self._previous_level = envelope
        self._previous_spectrum = bands
        return tuple(self._pulses)
