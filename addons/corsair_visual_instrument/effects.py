from __future__ import annotations

import math
from dataclasses import replace

from .device_layout import group_k55_zones
from .models import (
    K65AnimationProfile,
    LedPoint,
    LightingSettings,
    RgbColor,
    RuntimeSnapshot,
    WavePulse,
)
from .wave_engine import WAVE_EFFECTS

_MOOD_COLORS: dict[str, RgbColor] = {
    "happy": (255, 205, 65),
    "excited": (255, 80, 145),
    "calm": (55, 205, 185),
    "curious": (80, 145, 255),
    "sad": (45, 80, 175),
    "angry": (255, 45, 30),
    "affectionate": (255, 90, 155),
    "neutral": (150, 150, 150),
}


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _scale(color: RgbColor, amount: float) -> RgbColor:
    factor = _clamp(amount)
    return tuple(max(0, min(255, int(round(channel * factor)))) for channel in color)  # type: ignore[return-value]


def _blend(first: RgbColor, second: RgbColor, amount: float) -> RgbColor:
    ratio = _clamp(amount)
    return tuple(
        max(0, min(255, int(round((left * (1.0 - ratio)) + (right * ratio)))))
        for left, right in zip(first, second)
    )  # type: ignore[return-value]


def _state_color(snapshot: RuntimeSnapshot, settings: LightingSettings) -> RgbColor:
    colors = {
        "idle": settings.idle_color,
        "listening": settings.listening_color,
        "thinking": settings.thinking_color,
        "speaking": settings.speaking_color,
    }
    color = colors.get(snapshot.state, settings.idle_color)
    mood_name = snapshot.mood.strip().lower()
    if (
        settings.mood_tint_enabled
        and mood_name in _MOOD_COLORS
        and mood_name != "neutral"
    ):
        mood_color = _MOOD_COLORS[mood_name]
        color = _blend(color, mood_color, min(0.45, settings.mood_tint_strength))
    return _scale(color, settings.brightness)


def _band_at(bands: tuple[float, ...], position: float) -> float:
    if not bands:
        return 0.0
    location = _clamp(position) * (len(bands) - 1)
    left = int(math.floor(location))
    right = min(len(bands) - 1, left + 1)
    ratio = location - left
    return _clamp((bands[left] * (1.0 - ratio)) + (bands[right] * ratio))


def _region_energy(values: tuple[float, ...]) -> float:
    if not values:
        return 0.0
    mean_square = sum(value * value for value in values) / len(values)
    return _clamp(math.sqrt(mean_square))


def _spectrum_regions(
    bands: tuple[float, ...],
) -> tuple[float, float, float]:
    padded = tuple(bands[:48]) + ((0.0,) * max(0, 48 - len(bands)))
    return (
        _region_energy(padded[:16]),
        _region_energy(padded[16:34]),
        _region_energy(padded[34:48]),
    )


def _spectrum_centroid(bands: tuple[float, ...]) -> float:
    total = sum(bands)
    if total <= 0.0 or len(bands) < 2:
        return 0.5
    weighted = sum(index * value for index, value in enumerate(bands))
    return _clamp(weighted / (total * (len(bands) - 1)))


def _blend_frames(
    rest: dict[int, RgbColor],
    live: dict[int, RgbColor],
    activity: float,
) -> dict[int, RgbColor]:
    ratio = _clamp(activity)
    return {
        led_id: _blend(rest[led_id], live.get(led_id, rest[led_id]), ratio)
        for led_id in rest
    }


def _valid_spectrum(value: tuple[float, ...]) -> tuple[float, ...]:
    if len(value) != 48:
        return ()
    try:
        bands = tuple(float(part) for part in value)
    except (TypeError, ValueError):
        return ()
    if any(not math.isfinite(part) for part in bands):
        return ()
    return tuple(_clamp(part) for part in bands)


def _equalizer_display_bands(
    bands: tuple[float, ...],
    level: float,
    detail: float,
) -> tuple[float, ...]:
    """Preserve spectral shape while mapping speech loudness to five rows."""
    peak = max(bands, default=0.0)
    if peak <= 0.0:
        return (0.0,) * len(bands)
    envelope = _clamp(math.sqrt(max(_clamp(level), peak)) * 1.10)
    contrast = 0.65 + (_clamp(detail) * 0.75)
    return tuple(
        _clamp(math.pow(_clamp(value / peak), contrast) * envelope)
        for value in bands
    )


def render_k55_frame(
    layout: tuple[LedPoint, ...],
    snapshot: RuntimeSnapshot,
    settings: LightingSettings,
    *,
    now_s: float,
) -> dict[int, RgbColor]:
    active_color = _state_color(snapshot, settings)
    zones = group_k55_zones(layout)
    if settings.k55_mode == "unified":
        if snapshot.state == "speaking":
            source_level = snapshot.level
            if snapshot.level_source == "state":
                source_level = 0.20 + (
                    0.06
                    * ((math.sin(now_s * settings.animation_speed * 3.2) + 1.0) * 0.5)
                )
            progress = _clamp(source_level * (0.55 + settings.sensitivity)) * 3.0
            amounts = tuple(_clamp(progress - zone_index) for zone_index in range(3))
        elif snapshot.state == "thinking":
            active_zone = int(now_s * settings.animation_speed * 2.0) % 3
            amounts = tuple(
                1.0 if zone_index == active_zone else 0.10 for zone_index in range(3)
            )
        elif snapshot.state == "listening":
            pulse = 0.78 + (
                0.22 * ((math.sin(now_s * settings.animation_speed * 4.0) + 1.0) * 0.5)
            )
            amounts = (pulse * 0.48, pulse, pulse * 0.48)
        else:
            breath = 0.38 + (
                0.22 * ((math.sin(now_s * settings.animation_speed * 1.6) + 1.0) * 0.5)
            )
            amounts = (breath, breath, breath)
        frame: dict[int, RgbColor] = {}
        for zone_index, led_ids in enumerate(zones):
            frame.update(
                {
                    led_id: _scale(active_color, amounts[zone_index])
                    for led_id in led_ids
                }
            )
        return frame

    if snapshot.state == "idle":
        return {point.led_id: active_color for point in layout}

    active_zone = {"listening": 0, "thinking": 1, "speaking": 2}.get(snapshot.state)
    inactive_color = _scale(settings.idle_color, settings.brightness * 0.10)
    frame: dict[int, RgbColor] = {}
    for zone_index, led_ids in enumerate(zones):
        color = active_color if zone_index == active_zone else inactive_color
        frame.update({led_id: color for led_id in led_ids})
    return frame


def _equalizer_frame(
    layout: tuple[LedPoint, ...],
    color: RgbColor,
    level: float,
    profile: K65AnimationProfile,
    now_s: float,
    speed: float,
    bands: tuple[float, ...] = (),
) -> dict[int, RgbColor]:
    del now_s, speed
    frame: dict[int, RgbColor] = {}
    for point in layout:
        local_level = _band_at(bands, point.x) if bands else level
        strength = max(
            _clamp(local_level * profile.audio_reactivity * profile.size),
            _clamp(0.08 * profile.size),
        )
        amount = (
            profile.intensity
            if point.y >= (1.0 - strength)
            else 0.0
        )
        frame[point.led_id] = _scale(color, amount)
    return frame


def _living_wave_frame(
    layout: tuple[LedPoint, ...],
    color: RgbColor,
    level: float,
    profile: K65AnimationProfile,
    now_s: float,
    speed: float,
    bands: tuple[float, ...] = (),
) -> dict[int, RgbColor]:
    cycles = 1.0 + profile.detail
    frame: dict[int, RgbColor] = {}
    for point in layout:
        local_level = _band_at(bands, point.x) if bands else level
        strength = _clamp(local_level * profile.audio_reactivity)
        phase = (
            (point.x * math.tau * cycles / profile.size)
            - (point.y * math.pi)
            - (now_s * speed * profile.speed * 5.0)
        )
        glow = 0.10 + (0.90 * strength * ((math.sin(phase) + 1.0) * 0.5))
        frame[point.led_id] = _scale(color, glow * profile.intensity)
    return frame


def _center_ripple_frame(
    layout: tuple[LedPoint, ...],
    color: RgbColor,
    level: float,
    profile: K65AnimationProfile,
    now_s: float,
    speed: float,
    bands: tuple[float, ...] = (),
) -> dict[int, RgbColor]:
    phase_time = now_s * speed * profile.speed
    bass, mid, treble = (
        _spectrum_regions(bands) if bands else (level, level, level)
    )
    ring_frequency = (12.0 + (profile.detail * 24.0)) / profile.size
    exponent = 1.2 + ((1.0 - profile.trail) * 2.2)
    frame: dict[int, RgbColor] = {}
    for point in layout:
        radius = math.hypot((point.x - 0.5) * 1.55, point.y - 0.5)
        region_level = bass if radius < 0.30 else mid if radius < 0.62 else treble
        strength = _clamp(region_level * profile.audio_reactivity)
        ring = (math.sin((radius * ring_frequency) - (phase_time * 6.0)) + 1.0) * 0.5
        glow = 0.04 + (math.pow(ring, exponent) * (0.45 + (strength * 0.55)))
        frame[point.led_id] = _scale(color, glow * profile.intensity)
    return frame


def _dual_comet_frame(
    layout: tuple[LedPoint, ...],
    color: RgbColor,
    level: float,
    profile: K65AnimationProfile,
    now_s: float,
    speed: float,
    bands: tuple[float, ...] = (),
) -> dict[int, RgbColor]:
    phase_time = now_s * speed * profile.speed
    bass, mid, treble = (
        _spectrum_regions(bands) if bands else (level, level, level)
    )
    bass_strength = _clamp((bass + (mid * 0.25)) * profile.audio_reactivity)
    treble_strength = _clamp((treble + (mid * 0.25)) * profile.audio_reactivity)
    head_a = (phase_time * 0.28) % 1.4 - 0.2
    head_b = 1.2 - ((phase_time * 0.28) % 1.4)
    tail_length = (0.05 + (profile.detail * 0.38)) * profile.size
    softness = 0.5 + (profile.trail * 1.5)
    frame: dict[int, RgbColor] = {}
    for point in layout:
        comet_a = max(0.0, 1.0 - (abs(point.x - head_a) / tail_length))
        comet_b = max(0.0, 1.0 - (abs(point.x - head_b) / tail_length))
        comet_a *= 1.0 - (abs(point.y - 0.25) * 0.8)
        comet_b *= 1.0 - (abs(point.y - 0.75) * 0.8)
        comet_a = math.pow(max(0.0, comet_a), softness) * bass_strength
        comet_b = math.pow(max(0.0, comet_b), softness) * treble_strength
        glow = 0.03 + (max(comet_a, comet_b) * 0.97)
        frame[point.led_id] = _scale(color, glow * profile.intensity)
    return frame


def _plasma_field_frame(
    layout: tuple[LedPoint, ...],
    color: RgbColor,
    level: float,
    profile: K65AnimationProfile,
    now_s: float,
    speed: float,
    bands: tuple[float, ...] = (),
) -> dict[int, RgbColor]:
    phase_time = now_s * speed * profile.speed
    complexity = (1.4 + (profile.detail * 3.6)) / profile.size
    contrast = 0.65 + ((1.0 - profile.trail) * 1.1)
    frame: dict[int, RgbColor] = {}
    for point in layout:
        local_level = _band_at(bands, point.x) if bands else level
        strength = _clamp(local_level * profile.audio_reactivity)
        field = (
            math.sin((point.x * 7.0 + phase_time) * complexity)
            + math.cos((point.y * 5.0 - phase_time * 0.8) * complexity)
            + math.sin(((point.x + point.y) * 9.0) - (phase_time * 1.7))
        )
        normalized = math.pow(_clamp((field + 3.0) / 6.0), contrast)
        glow = 0.05 + (normalized * (0.4 + strength * 0.6))
        frame[point.led_id] = _scale(color, glow * profile.intensity)
    return frame


def _audio_columns_frame(
    layout: tuple[LedPoint, ...],
    color: RgbColor,
    level: float,
    profile: K65AnimationProfile,
    now_s: float,
    speed: float,
    bands: tuple[float, ...] = (),
) -> dict[int, RgbColor]:
    phase_time = now_s * speed * profile.speed
    frequency = (18.0 + (profile.detail * 22.0)) / profile.size
    frame: dict[int, RgbColor] = {}
    for point in layout:
        local_level = _band_at(bands, point.x) if bands else level
        strength = _clamp(local_level * profile.audio_reactivity)
        band_wave = (math.sin((point.x * frequency) + (phase_time * 7.0)) + 1.0) * 0.5
        column_height = _clamp(0.08 + (strength * (0.35 + (band_wave * 0.65))))
        if point.y >= (1.0 - column_height):
            separation = 0.55 + (band_wave * (0.45 + profile.trail * 0.25))
            amount = separation * (0.35 + strength * 0.65) * profile.intensity
        else:
            amount = 0.0
        frame[point.led_id] = _scale(color, amount)
    return frame


def _wave_rest_frame(
    layout: tuple[LedPoint, ...],
    color: RgbColor,
    profile: K65AnimationProfile,
) -> dict[int, RgbColor]:
    """Return a fixed, dim frame while a wave effect has no audio transient."""
    rest_color = _scale(color, 0.025 * profile.intensity)
    return {point.led_id: rest_color for point in layout}


def _active_wave_pulses(
    wave_pulses: tuple[WavePulse, ...],
    now_s: float,
) -> tuple[tuple[WavePulse, float], ...]:
    active: list[tuple[WavePulse, float]] = []
    for pulse in wave_pulses[-8:]:
        age = now_s - pulse.started_at
        if 0.0 <= age <= 2.0:
            active.append((pulse, age))
    return tuple(active)


def _wave_radius(age: float, profile: K65AnimationProfile) -> float:
    speed = 0.35 + (0.85 * max(0.0, profile.speed))
    travel = 0.78 + (0.22 * max(0.0, profile.size))
    return age * speed * travel


def _wave_width(profile: K65AnimationProfile) -> float:
    return (
        0.030
        + (0.050 * max(0.0, profile.size))
        + (0.095 * _clamp(profile.trail))
    )


def _wave_decay(age: float, profile: K65AnimationProfile) -> float:
    decay_rate = 0.65 + ((1.0 - _clamp(profile.trail)) * 2.25)
    return math.exp(-age * decay_rate)


def _gaussian_wave(distance: float, radius: float, width: float) -> float:
    normalized = (distance - radius) / max(0.001, width)
    return math.exp(-(normalized * normalized))


def _center_shockwave_frame(
    layout: tuple[LedPoint, ...],
    color: RgbColor,
    profile: K65AnimationProfile,
    wave_pulses: tuple[WavePulse, ...],
    now_s: float,
) -> dict[int, RgbColor]:
    active = _active_wave_pulses(wave_pulses, now_s)
    if not active:
        return _wave_rest_frame(layout, color, profile)

    width = _wave_width(profile)
    sharpness = 0.65 + (1.55 * _clamp(profile.detail))
    frame: dict[int, RgbColor] = {}
    for point in layout:
        distance = math.hypot((point.x - 0.5) * 1.05, (point.y - 0.5) * 0.72)
        energy = 0.0
        for pulse, age in active:
            radius = _wave_radius(age, profile)
            ring = math.pow(
                _gaussian_wave(distance, radius, width),
                sharpness,
            )
            spectrum_weight = (
                0.35 + (0.28 * pulse.bass) + (0.22 * pulse.mid) + (0.15 * pulse.treble)
            )
            energy += (
                ring
                * pulse.amplitude
                * spectrum_weight
                * _wave_decay(age, profile)
                * max(0.0, profile.audio_reactivity)
            )
        amount = (0.025 + (0.78 * energy)) * profile.intensity
        frame[point.led_id] = _scale(color, amount)
    return frame


def _twin_voicefront_frame(
    layout: tuple[LedPoint, ...],
    color: RgbColor,
    profile: K65AnimationProfile,
    wave_pulses: tuple[WavePulse, ...],
    now_s: float,
) -> dict[int, RgbColor]:
    active = _active_wave_pulses(wave_pulses, now_s)
    if not active:
        return _wave_rest_frame(layout, color, profile)

    width = _wave_width(profile) * (0.75 + (0.35 * _clamp(profile.detail)))
    frame: dict[int, RgbColor] = {}
    for point in layout:
        distance = abs(point.x - 0.5)
        middle_weight = max(0.0, 1.0 - (abs(point.y - 0.5) * 2.0))
        energy = 0.0
        for pulse, age in active:
            radius = _wave_radius(age, profile) * 0.72
            front = _gaussian_wave(distance, radius, width)
            vertical_spectrum = (
                (pulse.treble * (1.0 - point.y))
                + (pulse.bass * point.y)
                + (pulse.mid * middle_weight * 0.55)
            )
            energy += (
                front
                * pulse.amplitude
                * (0.22 + (0.78 * _clamp(vertical_spectrum)))
                * _wave_decay(age, profile)
                * max(0.0, profile.audio_reactivity)
            )
        amount = (0.025 + (0.82 * energy)) * profile.intensity
        frame[point.led_id] = _scale(color, amount)
    return frame


def _voice_bloom_frame(
    layout: tuple[LedPoint, ...],
    color: RgbColor,
    profile: K65AnimationProfile,
    wave_pulses: tuple[WavePulse, ...],
    now_s: float,
) -> dict[int, RgbColor]:
    active = _active_wave_pulses(wave_pulses, now_s)
    if not active:
        return _wave_rest_frame(layout, color, profile)

    width = _wave_width(profile) * 1.15
    detail = _clamp(profile.detail)
    frame: dict[int, RgbColor] = {}
    for point in layout:
        distance = math.hypot((point.x - 0.5) * 0.92, (point.y - 0.5) * 0.92)
        middle_weight = max(0.0, 1.0 - (abs(point.y - 0.5) * 2.0))
        energy = 0.0
        for pulse, age in active:
            radius = _wave_radius(age, profile) * 0.82
            main_bloom = _gaussian_wave(distance, radius, width)
            inner_bloom = _gaussian_wave(
                distance,
                max(0.0, radius - (width * 1.45)),
                width * 1.35,
            )
            center_glow = math.exp(-distance * (5.6 - (2.0 * detail)))
            layers = main_bloom + (inner_bloom * detail * 0.55) + (center_glow * detail * 0.24)
            vertical_spectrum = (
                (pulse.treble * (1.0 - point.y))
                + (pulse.bass * point.y)
                + (pulse.mid * middle_weight * 0.45)
            )
            energy += (
                layers
                * pulse.amplitude
                * (0.28 + (0.72 * _clamp(vertical_spectrum)))
                * _wave_decay(age, profile)
                * max(0.0, profile.audio_reactivity)
            )
        amount = (0.025 + (0.70 * energy)) * profile.intensity
        frame[point.led_id] = _scale(color, amount)
    return frame


def _render_wave_effect_frame(
    layout: tuple[LedPoint, ...],
    color: RgbColor,
    profile: K65AnimationProfile,
    wave_pulses: tuple[WavePulse, ...],
    *,
    now_s: float,
) -> dict[int, RgbColor]:
    renderers = {
        "center_shockwave": _center_shockwave_frame,
        "twin_voicefront": _twin_voicefront_frame,
        "voice_bloom": _voice_bloom_frame,
    }
    renderer = renderers.get(profile.effect)
    if renderer is None:
        return _wave_rest_frame(layout, color, profile)
    return renderer(layout, color, profile, wave_pulses, now_s)


def _animation_profile_for_state(
    settings: LightingSettings, state: str
) -> K65AnimationProfile:
    profiles = {
        "idle": settings.k65_idle_animation,
        "listening": settings.k65_listening_animation,
        "thinking": settings.k65_thinking_animation,
        "speaking": settings.k65_speaking_animation,
    }
    profile = profiles.get(state, settings.k65_idle_animation)
    if state == "speaking" and settings.k65_speaking_mode != profile.effect:
        return replace(profile, effect=settings.k65_speaking_mode)
    return profile


def _render_classic_k65_frame(
    layout: tuple[LedPoint, ...],
    color: RgbColor,
    effect: str,
    now_s: float,
    speed: float,
) -> dict[int, RgbColor]:
    if effect == "classic_thinking":
        scan_x = ((now_s * speed * 0.55) % 1.4) - 0.2
        return {
            point.led_id: _scale(
                color, 0.08 + (0.92 * max(0.0, 1.0 - abs(point.x - scan_x) * 5.0))
            )
            for point in layout
        }
    if effect == "classic_listening":
        pulse = 0.65 + (0.35 * ((math.sin(now_s * speed * 4.0) + 1.0) * 0.5))
        return {
            point.led_id: _scale(
                color, pulse * (0.45 + (0.55 * (1.0 - abs(point.x - 0.5))))
            )
            for point in layout
        }
    breath = 0.35 + (0.20 * ((math.sin(now_s * speed * 1.6) + 1.0) * 0.5))
    return {point.led_id: _scale(color, breath) for point in layout}


def _render_classic_speaking_frame(
    layout: tuple[LedPoint, ...],
    color: RgbColor,
    profile: K65AnimationProfile,
    bands: tuple[float, ...],
    *,
    now_s: float,
    speed: float,
) -> dict[int, RgbColor]:
    bass, mid, treble = _spectrum_regions(bands)
    phase_time = now_s * speed * profile.speed
    frame: dict[int, RgbColor] = {}
    if profile.effect == "classic_thinking":
        scan_x = _spectrum_centroid(bands)
        overall = _region_energy(bands)
        for point in layout:
            local = _band_at(bands, point.x)
            highlight = max(0.0, 1.0 - (abs(point.x - scan_x) * 5.0))
            glow = 0.08 + (
                (0.55 * local + 0.37 * overall)
                * highlight
                * profile.audio_reactivity
            )
            frame[point.led_id] = _scale(color, glow * profile.intensity)
        return frame
    if profile.effect == "classic_listening":
        pulse = 0.72 + (
            0.28 * ((math.sin(phase_time * 4.0) + 1.0) * 0.5)
        )
        for point in layout:
            local = _band_at(bands, point.x)
            center_weight = 0.45 + (0.55 * (1.0 - abs(point.x - 0.5)))
            glow = 0.08 + (
                0.92
                * local
                * center_weight
                * pulse
                * profile.audio_reactivity
            )
            frame[point.led_id] = _scale(color, glow * profile.intensity)
        return frame

    breath = 0.72 + (0.28 * ((math.sin(phase_time * 1.6) + 1.0) * 0.5))
    for point in layout:
        mid_weight = max(0.0, 1.0 - (abs(point.y - 0.5) * 2.0))
        vertical = (treble * (1.0 - point.y)) + (bass * point.y)
        region = max(vertical, mid * mid_weight)
        local = (region * 0.65) + (_band_at(bands, point.x) * 0.35)
        glow = 0.08 + (
            0.92 * local * breath * profile.audio_reactivity
        )
        frame[point.led_id] = _scale(color, glow * profile.intensity)
    return frame


def _render_effect_frame(
    layout: tuple[LedPoint, ...],
    color: RgbColor,
    level: float,
    profile: K65AnimationProfile,
    bands: tuple[float, ...],
    *,
    now_s: float,
    speed: float,
) -> dict[int, RgbColor]:
    if profile.effect.startswith("classic_"):
        return _render_classic_speaking_frame(
            layout,
            color,
            profile,
            bands,
            now_s=now_s,
            speed=speed,
        )
    renderers = {
        "equalizer": _equalizer_frame,
        "living_wave": _living_wave_frame,
        "center_ripple": _center_ripple_frame,
        "dual_comet": _dual_comet_frame,
        "plasma_field": _plasma_field_frame,
        "audio_columns": _audio_columns_frame,
    }
    renderer = renderers.get(profile.effect, _center_ripple_frame)
    return renderer(
        layout,
        color,
        level,
        profile,
        now_s,
        speed,
        bands,
    )


def render_k65_frame(
    layout: tuple[LedPoint, ...],
    snapshot: RuntimeSnapshot,
    settings: LightingSettings,
    *,
    now_s: float,
    wave_pulses: tuple[WavePulse, ...] = (),
) -> dict[int, RgbColor]:
    color = _state_color(snapshot, settings)
    speed = settings.animation_speed
    profile = _animation_profile_for_state(settings, snapshot.state)
    if profile.effect in WAVE_EFFECTS:
        return _render_wave_effect_frame(
            layout,
            color,
            profile,
            wave_pulses,
            now_s=now_s,
        )
    if snapshot.state != "speaking" and profile.effect.startswith("classic_"):
        return _render_classic_k65_frame(layout, color, profile.effect, now_s, speed)

    source_level = snapshot.level
    if snapshot.level_source == "state":
        source_level = 0.20 + (
            0.06 * ((math.sin(now_s * speed * profile.speed * 3.2) + 1.0) * 0.5)
        )
    gain = 0.55 + settings.sensitivity
    level = _clamp(source_level * gain)
    if snapshot.state != "speaking":
        return _render_effect_frame(
            layout,
            color,
            level,
            profile,
            (),
            now_s=now_s,
            speed=speed,
        )

    captured_bands = _valid_spectrum(snapshot.spectrum)
    if captured_bands:
        gained_bands = tuple(_clamp(value * gain) for value in captured_bands)
        if profile.effect == "equalizer":
            bands = _equalizer_display_bands(
                gained_bands,
                level,
                profile.detail,
            )
        else:
            bands = gained_bands
    else:
        bands = (level,) * 48
    activity = _clamp(max(bands, default=0.0) * profile.audio_reactivity)
    resting_bands = (0.0,) * 48
    rest = _render_effect_frame(
        layout,
        color,
        0.0,
        profile,
        resting_bands,
        now_s=0.0,
        speed=speed,
    )
    if activity <= 0.0:
        return rest
    live = _render_effect_frame(
        layout,
        color,
        level,
        profile,
        bands,
        now_s=now_s,
        speed=speed,
    )
    if profile.effect == "equalizer":
        return live
    return _blend_frames(rest, live, activity)
