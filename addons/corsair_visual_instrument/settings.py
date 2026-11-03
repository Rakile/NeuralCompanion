from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from .models import K65AnimationProfile, LightingSettings, RgbColor

SETTINGS_FILE = "settings.json"
_K55_MODES = {"state_lanes", "unified"}
_K65_EFFECTS = {
    "classic_idle",
    "classic_listening",
    "classic_thinking",
    "equalizer",
    "living_wave",
    "center_ripple",
    "dual_comet",
    "plasma_field",
    "audio_columns",
    "center_shockwave",
    "twin_voicefront",
    "voice_bloom",
}


def _float_value(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _int_value(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _color(value: Any, default: RgbColor) -> RgbColor:
    if isinstance(value, str):
        text = value.strip().lstrip("#")
        if len(text) == 6:
            try:
                return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]
            except ValueError:
                return default
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            return tuple(max(0, min(255, int(part))) for part in value)  # type: ignore[return-value]
        except (TypeError, ValueError):
            return default
    return default


def _animation_profile(value: Any, default: K65AnimationProfile) -> K65AnimationProfile:
    if isinstance(value, K65AnimationProfile):
        data: Mapping[str, Any] = {
            "effect": value.effect,
            "speed": value.speed,
            "intensity": value.intensity,
            "size": value.size,
            "trail": value.trail,
            "audio_reactivity": value.audio_reactivity,
            "detail": value.detail,
        }
    elif isinstance(value, Mapping):
        data = value
    else:
        data = {}
    effect = str(data.get("effect", default.effect)).strip().lower()
    effect = effect if effect in _K65_EFFECTS else default.effect
    reactivity_maximum = 4.0 if effect == "equalizer" else 2.0
    return K65AnimationProfile(
        effect=effect,
        speed=_float_value(data.get("speed"), default.speed, 0.0, 3.0),
        intensity=_float_value(data.get("intensity"), default.intensity, 0.0, 2.0),
        size=_float_value(data.get("size"), default.size, 0.2, 2.0),
        trail=_float_value(data.get("trail"), default.trail, 0.0, 1.0),
        audio_reactivity=_float_value(
            data.get("audio_reactivity"),
            default.audio_reactivity,
            0.0,
            reactivity_maximum,
        ),
        detail=_float_value(data.get("detail"), default.detail, 0.0, 1.0),
    )


def normalize_settings(payload: Mapping[str, Any] | None) -> LightingSettings:
    data = dict(payload or {})
    defaults = LightingSettings()
    k55_mode = str(data.get("k55_mode", defaults.k55_mode)).strip().lower()
    k65_mode = str(data.get("k65_speaking_mode", defaults.k65_speaking_mode)).strip().lower()
    if k65_mode not in _K65_EFFECTS:
        k65_mode = defaults.k65_speaking_mode
    idle_animation = _animation_profile(
        data.get("k65_idle_animation"), defaults.k65_idle_animation
    )
    listening_animation = _animation_profile(
        data.get("k65_listening_animation"), defaults.k65_listening_animation
    )
    thinking_animation = _animation_profile(
        data.get("k65_thinking_animation"), defaults.k65_thinking_animation
    )
    speaking_animation = _animation_profile(
        data.get("k65_speaking_animation"), defaults.k65_speaking_animation
    )
    has_speaking_animation = "k65_speaking_animation" in data
    has_legacy_speaking_mode = "k65_speaking_mode" in data
    if not has_speaking_animation or (
        has_legacy_speaking_mode and speaking_animation.effect != k65_mode
    ):
        speaking_animation = K65AnimationProfile(
            effect=k65_mode,
            speed=speaking_animation.speed,
            intensity=speaking_animation.intensity,
            size=speaking_animation.size,
            trail=speaking_animation.trail,
            audio_reactivity=speaking_animation.audio_reactivity,
            detail=speaking_animation.detail,
        )
    return LightingSettings(
        enabled=bool(data.get("enabled", defaults.enabled)),
        k55_device_id=str(data.get("k55_device_id", defaults.k55_device_id) or "").strip(),
        k65_device_id=str(data.get("k65_device_id", defaults.k65_device_id) or "").strip(),
        k55_mode=k55_mode if k55_mode in _K55_MODES else defaults.k55_mode,
        k65_speaking_mode=speaking_animation.effect,
        k65_idle_animation=idle_animation,
        k65_listening_animation=listening_animation,
        k65_thinking_animation=thinking_animation,
        k65_speaking_animation=speaking_animation,
        idle_color=_color(data.get("idle_color"), defaults.idle_color),
        listening_color=_color(data.get("listening_color"), defaults.listening_color),
        thinking_color=_color(data.get("thinking_color"), defaults.thinking_color),
        speaking_color=_color(data.get("speaking_color"), defaults.speaking_color),
        mood_tint_enabled=bool(data.get("mood_tint_enabled", defaults.mood_tint_enabled)),
        mood_tint_strength=_float_value(
            data.get("mood_tint_strength"), defaults.mood_tint_strength, 0.0, 0.45
        ),
        brightness=_float_value(data.get("brightness"), defaults.brightness, 0.0, 1.0),
        sensitivity=_float_value(data.get("sensitivity"), defaults.sensitivity, 0.0, 1.0),
        smoothing=_float_value(data.get("smoothing"), defaults.smoothing, 0.0, 1.0),
        animation_speed=_float_value(
            data.get("animation_speed"), defaults.animation_speed, 0.25, 3.0
        ),
        frame_rate_hz=_int_value(data.get("frame_rate_hz"), defaults.frame_rate_hz, 5, 30),
        sdk_dll_path=str(data.get("sdk_dll_path", defaults.sdk_dll_path) or "").strip(),
    )


def settings_to_dict(settings: LightingSettings) -> dict[str, Any]:
    payload = asdict(settings)
    payload["k65_speaking_mode"] = settings.k65_speaking_animation.effect
    for key in ("idle_color", "listening_color", "thinking_color", "speaking_color"):
        payload[key] = list(payload[key])
    return payload


def load_settings(storage: Any, logger: Any = None) -> LightingSettings:
    try:
        payload = storage.read_json(SETTINGS_FILE)
    except (FileNotFoundError, OSError, ValueError, TypeError) as exc:
        if logger is not None and not isinstance(exc, FileNotFoundError):
            logger.warning("[Corsair LEDs] Settings could not be read: %s", exc)
        return LightingSettings()
    return normalize_settings(payload if isinstance(payload, Mapping) else None)


def save_settings(storage: Any, settings: LightingSettings) -> Path:
    return Path(storage.write_json(SETTINGS_FILE, settings_to_dict(settings)))
