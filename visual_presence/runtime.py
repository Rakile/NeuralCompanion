"""Thread-safe event bridge from engine workers to the Qt presence overlay."""

from __future__ import annotations

import math
import threading
import time
import weakref

from .audio_reactive_meter import clamp_level
from .system_audio_meter import SystemAudioLevelMeter

_LOCK = threading.RLock()
_CONTROLLER_REF = None
_ORB_CONTROLLER_REFS = []
_LAST_STATE = "idle"
_LAST_LEVEL = 0.0
_LAST_ORB_LEVEL = 0.0
_LAST_MUSIC_LEVEL = 0.0
_MUSIC_SPECTRUM_BANDS = 12
_LAST_MUSIC_SPECTRUM = (0.0,) * _MUSIC_SPECTRUM_BANDS
_LAST_VOICE_SPECTRUM = (0.0,) * _MUSIC_SPECTRUM_BANDS
_LAST_SPECTRAL_FLUX = 0.0
_LAST_SPECTRAL_CENTROID = 0.0
_LAST_USER_VOICE_LEVEL = 0.0
_LAST_USER_VOICE_PEAK = 0.0
_LAST_USER_VOICE_SPECTRUM = (0.0,) * _MUSIC_SPECTRUM_BANDS
_LAST_USER_SPECTRAL_FLUX = 0.0
_LAST_USER_SPECTRAL_CENTROID = 0.0
_LAST_USER_VOICE_ACTIVE = False
_LAST_MOOD = "neutral"
_LAST_SETTINGS = {}
_SYSTEM_AUDIO_METER = None
_VALID_STATES = {"idle", "listening", "thinking", "speaking"}
_LAST_LEVEL_DISPATCH_AT = 0.0
_LAST_ORB_LEVEL_DISPATCH_AT = 0.0
_LAST_MUSIC_LEVEL_DISPATCH_AT = 0.0
_LAST_MUSIC_SPECTRUM_DISPATCH_AT = 0.0
_AUDIO_LEVEL_MIN_INTERVAL_SECONDS = 1.0 / 18.0
_MUSIC_LEVEL_MIN_INTERVAL_SECONDS = 1.0 / 12.0
_MUSIC_SPECTRUM_MIN_INTERVAL_SECONDS = 1.0 / 24.0
_AUDIO_LEVEL_MIN_DELTA = 0.018


def _normalize_state(state) -> str:
    value = str(state or "idle").strip().lower()
    return value if value in _VALID_STATES else "idle"


def _controller():
    global _CONTROLLER_REF
    ref = _CONTROLLER_REF
    if ref is None:
        return None
    try:
        controller = ref()
    except Exception:
        controller = None
    if controller is None:
        _CONTROLLER_REF = None
    return controller


def _orb_controllers():
    global _ORB_CONTROLLER_REFS
    keep = []
    controllers = []
    for ref in list(_ORB_CONTROLLER_REFS or []):
        try:
            controller = ref()
        except Exception:
            controller = None
        if controller is None:
            continue
        keep.append(ref)
        controllers.append(controller)
    _ORB_CONTROLLER_REFS = keep
    return controllers


def register_controller(controller) -> None:
    global _CONTROLLER_REF
    with _LOCK:
        _CONTROLLER_REF = weakref.ref(controller)
        state = _LAST_STATE
        level = _LAST_LEVEL
        music_level = _LAST_MUSIC_LEVEL
        music_spectrum = _LAST_MUSIC_SPECTRUM
        voice_spectrum = _LAST_VOICE_SPECTRUM
        spectral_flux = _LAST_SPECTRAL_FLUX
        spectral_centroid = _LAST_SPECTRAL_CENTROID
        user_voice_level = _LAST_USER_VOICE_LEVEL
        user_voice_peak = _LAST_USER_VOICE_PEAK
        user_voice_spectrum = _LAST_USER_VOICE_SPECTRUM
        user_spectral_flux = _LAST_USER_SPECTRAL_FLUX
        user_spectral_centroid = _LAST_USER_SPECTRAL_CENTROID
        user_voice_active = _LAST_USER_VOICE_ACTIVE
        mood = _LAST_MOOD
        settings = dict(_LAST_SETTINGS)
    try:
        controller.request_settings(settings)
        controller.request_ai_state(state)
        controller.request_audio_level(level)
        controller.request_music_level(music_level)
        controller.request_music_spectrum(music_spectrum)
        controller.request_voice_analysis(
            voice_spectrum,
            spectral_flux,
            spectral_centroid,
        )
        request_user_voice_analysis = getattr(
            controller,
            "request_user_voice_analysis",
            None,
        )
        if callable(request_user_voice_analysis):
            request_user_voice_analysis(
                user_voice_spectrum,
                user_voice_level,
                user_voice_peak,
                user_spectral_flux,
                user_spectral_centroid,
                user_voice_active,
            )
        controller.request_presence_mood(mood)
    except Exception:
        pass
    _sync_system_audio_meter(settings)


def register_orb_controller(controller) -> None:
    global _ORB_CONTROLLER_REFS
    if controller is None:
        return
    with _LOCK:
        _ORB_CONTROLLER_REFS = [ref for ref in list(_ORB_CONTROLLER_REFS or []) if ref() is not controller]
        _ORB_CONTROLLER_REFS.append(weakref.ref(controller))
        state = _LAST_STATE
        level = _LAST_ORB_LEVEL
        music_level = _LAST_MUSIC_LEVEL
        mood = _LAST_MOOD
        settings = dict(_LAST_SETTINGS)
    try:
        controller.request_settings(settings)
        controller.request_ai_state(state)
        controller.request_audio_level(level)
        controller.request_music_level(music_level)
        controller.request_presence_mood(mood)
    except Exception:
        pass


def unregister_orb_controller(controller) -> None:
    global _ORB_CONTROLLER_REFS
    with _LOCK:
        _ORB_CONTROLLER_REFS = [ref for ref in list(_ORB_CONTROLLER_REFS or []) if ref() is not controller and ref() is not None]


def unregister_controller(controller) -> None:
    global _CONTROLLER_REF
    with _LOCK:
        current = _controller()
        if current is controller:
            _CONTROLLER_REF = None
    _sync_system_audio_meter({})


def set_ai_state(state) -> None:
    global _LAST_STATE
    normalized = _normalize_state(state)
    with _LOCK:
        _LAST_STATE = normalized
        controller = _controller()
        orb_controllers = _orb_controllers()
    if controller is not None:
        try:
            controller.request_ai_state(normalized)
        except Exception:
            pass
    for orb_controller in orb_controllers:
        try:
            orb_controller.request_ai_state(normalized)
        except Exception:
            pass


def set_audio_level(level) -> None:
    global _LAST_LEVEL, _LAST_LEVEL_DISPATCH_AT
    normalized = clamp_level(level)
    with _LOCK:
        previous = _LAST_LEVEL
        now = time.monotonic()
        if normalized > 0.0 and (now - _LAST_LEVEL_DISPATCH_AT) < _AUDIO_LEVEL_MIN_INTERVAL_SECONDS:
            return
        if normalized > 0.0 and abs(normalized - previous) < _AUDIO_LEVEL_MIN_DELTA:
            return
        _LAST_LEVEL = normalized
        _LAST_LEVEL_DISPATCH_AT = now
        controller = _controller()
    if controller is not None:
        try:
            controller.request_audio_level(normalized)
        except Exception:
            pass


def set_companion_orb_audio_level(level) -> None:
    global _LAST_ORB_LEVEL, _LAST_ORB_LEVEL_DISPATCH_AT
    normalized = clamp_level(level)
    with _LOCK:
        previous = _LAST_ORB_LEVEL
        now = time.monotonic()
        if normalized > 0.0 and (now - _LAST_ORB_LEVEL_DISPATCH_AT) < _AUDIO_LEVEL_MIN_INTERVAL_SECONDS:
            return
        if normalized > 0.0 and abs(normalized - previous) < _AUDIO_LEVEL_MIN_DELTA:
            return
        _LAST_ORB_LEVEL = normalized
        _LAST_ORB_LEVEL_DISPATCH_AT = now
        orb_controllers = _orb_controllers()
    for orb_controller in orb_controllers:
        try:
            orb_controller.request_audio_level(normalized)
        except Exception:
            pass


def set_music_level(level) -> None:
    global _LAST_MUSIC_LEVEL, _LAST_MUSIC_LEVEL_DISPATCH_AT
    normalized = clamp_level(level)
    with _LOCK:
        previous = _LAST_MUSIC_LEVEL
        now = time.monotonic()
        if normalized > 0.0 and (now - _LAST_MUSIC_LEVEL_DISPATCH_AT) < _MUSIC_LEVEL_MIN_INTERVAL_SECONDS:
            return
        if normalized > 0.0 and abs(normalized - previous) < _AUDIO_LEVEL_MIN_DELTA:
            return
        _LAST_MUSIC_LEVEL = normalized
        _LAST_MUSIC_LEVEL_DISPATCH_AT = now
        controller = _controller()
        orb_controllers = _orb_controllers()
    if controller is not None:
        try:
            controller.request_music_level(normalized)
        except Exception:
            pass
    for orb_controller in orb_controllers:
        try:
            orb_controller.request_music_level(normalized)
        except Exception:
            pass


def _normalize_music_spectrum(values) -> tuple[float, ...]:
    try:
        source = list(values or ())
    except Exception:
        source = []
    normalized: list[float] = []
    for index in range(_MUSIC_SPECTRUM_BANDS):
        try:
            value = float(source[index])
        except (IndexError, TypeError, ValueError):
            value = 0.0
        if not math.isfinite(value):
            value = 0.0
        normalized.append(clamp_level(value))
    return tuple(normalized)


def set_music_spectrum(values) -> None:
    """Publish the bounded 12-band desktop/output audio spectrum."""

    global _LAST_MUSIC_SPECTRUM, _LAST_MUSIC_SPECTRUM_DISPATCH_AT
    normalized = _normalize_music_spectrum(values)
    active = max(normalized, default=0.0) > 0.0
    with _LOCK:
        previous = _LAST_MUSIC_SPECTRUM
        now = time.monotonic()
        if active and (now - _LAST_MUSIC_SPECTRUM_DISPATCH_AT) < _MUSIC_SPECTRUM_MIN_INTERVAL_SECONDS:
            return
        if active and max((abs(a - b) for a, b in zip(normalized, previous)), default=0.0) < 0.012:
            return
        _LAST_MUSIC_SPECTRUM = normalized
        _LAST_MUSIC_SPECTRUM_DISPATCH_AT = now
        controller = _controller()
    if controller is not None:
        try:
            controller.request_music_spectrum(normalized)
        except Exception:
            pass


def set_voice_analysis(frame) -> None:
    """Publish one bounded TTS analysis frame to the queued Qt controller."""

    global _LAST_VOICE_SPECTRUM, _LAST_SPECTRAL_FLUX, _LAST_SPECTRAL_CENTROID
    if frame is None:
        spectrum = (0.0,) * _MUSIC_SPECTRUM_BANDS
        flux = 0.0
        centroid = 0.0
    else:
        spectrum = _normalize_music_spectrum(getattr(frame, "spectrum", ()))
        flux = clamp_level(getattr(frame, "spectral_flux", 0.0))
        centroid = clamp_level(getattr(frame, "spectral_centroid", 0.0))
    with _LOCK:
        _LAST_VOICE_SPECTRUM = spectrum
        _LAST_SPECTRAL_FLUX = flux
        _LAST_SPECTRAL_CENTROID = centroid
        controller = _controller()
    if controller is not None:
        try:
            controller.request_voice_analysis(spectrum, flux, centroid)
        except Exception:
            pass


def set_user_voice_analysis(frame, active=False) -> None:
    """Publish one microphone frame independently from companion TTS."""

    global _LAST_USER_VOICE_LEVEL, _LAST_USER_VOICE_PEAK
    global _LAST_USER_VOICE_SPECTRUM, _LAST_USER_SPECTRAL_FLUX
    global _LAST_USER_SPECTRAL_CENTROID, _LAST_USER_VOICE_ACTIVE
    if frame is None:
        level = 0.0
        peak = 0.0
        spectrum = (0.0,) * _MUSIC_SPECTRUM_BANDS
        flux = 0.0
        centroid = 0.0
        voice_active = False
    else:
        level = clamp_level(getattr(frame, "level", 0.0))
        peak = clamp_level(getattr(frame, "peak", 0.0))
        spectrum = _normalize_music_spectrum(getattr(frame, "spectrum", ()))
        flux = clamp_level(getattr(frame, "spectral_flux", 0.0))
        centroid = clamp_level(getattr(frame, "spectral_centroid", 0.0))
        voice_active = bool(active)
    with _LOCK:
        _LAST_USER_VOICE_LEVEL = level
        _LAST_USER_VOICE_PEAK = peak
        _LAST_USER_VOICE_SPECTRUM = spectrum
        _LAST_USER_SPECTRAL_FLUX = flux
        _LAST_USER_SPECTRAL_CENTROID = centroid
        _LAST_USER_VOICE_ACTIVE = voice_active
        controller = _controller()
    if controller is not None:
        try:
            controller.request_user_voice_analysis(
                spectrum,
                level,
                peak,
                flux,
                centroid,
                voice_active,
            )
        except Exception:
            pass


def set_presence_mood(mood) -> None:
    global _LAST_MOOD
    value = str(mood or "neutral").strip().lower() or "neutral"
    with _LOCK:
        _LAST_MOOD = value
        controller = _controller()
        orb_controllers = _orb_controllers()
    if controller is not None:
        try:
            controller.request_presence_mood(value)
        except Exception:
            pass
    for orb_controller in orb_controllers:
        try:
            orb_controller.request_presence_mood(value)
        except Exception:
            pass


def snapshot_state() -> dict[str, object]:
    """Return the latest presentation inputs without waking an overlay.

    The desktop shells use this read-only snapshot to mirror the same AI state,
    TTS audio level, and mood already delivered to AI Presence and Companion
    Orb.  Runtime ownership remains with this module and its existing setters.
    """

    with _LOCK:
        return {
            "ai_state": str(_LAST_STATE or "idle"),
            "audio_level": float(_LAST_LEVEL or 0.0),
            "companion_orb_audio_level": float(_LAST_ORB_LEVEL or 0.0),
            "music_level": float(_LAST_MUSIC_LEVEL or 0.0),
            "music_spectrum": list(_LAST_MUSIC_SPECTRUM),
            "voice_spectrum": list(_LAST_VOICE_SPECTRUM),
            "spectral_flux": float(_LAST_SPECTRAL_FLUX or 0.0),
            "spectral_centroid": float(_LAST_SPECTRAL_CENTROID or 0.0),
            "user_voice_level": float(_LAST_USER_VOICE_LEVEL or 0.0),
            "user_voice_peak": float(_LAST_USER_VOICE_PEAK or 0.0),
            "user_voice_spectrum": list(_LAST_USER_VOICE_SPECTRUM),
            "user_spectral_flux": float(_LAST_USER_SPECTRAL_FLUX or 0.0),
            "user_spectral_centroid": float(_LAST_USER_SPECTRAL_CENTROID or 0.0),
            "user_voice_active": bool(_LAST_USER_VOICE_ACTIVE),
            "mood": str(_LAST_MOOD or "neutral"),
        }


def apply_settings(settings) -> None:
    global _LAST_SETTINGS
    payload = dict(settings or {})
    with _LOCK:
        _LAST_SETTINGS = payload
        controller = _controller()
        orb_controllers = _orb_controllers()
    if controller is not None:
        try:
            controller.request_settings(payload)
        except Exception:
            pass
    for orb_controller in orb_controllers:
        try:
            orb_controller.request_settings(payload)
        except Exception:
            pass
    _sync_system_audio_meter(payload)


def reset_ai_presence_floating_position() -> None:
    with _LOCK:
        controller = _controller()
    if controller is not None:
        try:
            controller.request_reset_floating_position()
        except Exception:
            pass


def set_companion_orb_edit_mode(enabled) -> None:
    with _LOCK:
        orb_controllers = _orb_controllers()
    for orb_controller in orb_controllers:
        try:
            orb_controller.request_edit_mode(bool(enabled))
        except Exception:
            pass


def set_companion_orb_placement_mode(enabled) -> None:
    with _LOCK:
        orb_controllers = _orb_controllers()
    for orb_controller in orb_controllers:
        try:
            orb_controller.request_placement_mode(bool(enabled))
        except Exception:
            pass


def set_companion_orb_click_through(enabled) -> None:
    with _LOCK:
        orb_controllers = _orb_controllers()
    for orb_controller in orb_controllers:
        try:
            orb_controller.request_click_through(bool(enabled))
        except Exception:
            pass


def clear_companion_orb_target() -> None:
    with _LOCK:
        orb_controllers = _orb_controllers()
    for orb_controller in orb_controllers:
        try:
            orb_controller.request_clear_target()
        except Exception:
            pass


def reset_companion_orb_position() -> None:
    with _LOCK:
        orb_controllers = _orb_controllers()
    for orb_controller in orb_controllers:
        try:
            orb_controller.request_reset_position()
        except Exception:
            pass


def set_companion_orb_comment_focus(payload) -> None:
    data = dict(payload or {})
    with _LOCK:
        orb_controllers = _orb_controllers()
    for orb_controller in orb_controllers:
        try:
            orb_controller.request_comment_focus(data)
        except Exception:
            pass


def _sync_system_audio_meter(settings) -> None:
    global _SYSTEM_AUDIO_METER
    payload = dict(settings or {})
    should_run = _system_audio_meter_should_run(payload)
    fps = _meter_fps(payload)
    with _LOCK:
        meter = _SYSTEM_AUDIO_METER
        has_controller = _controller() is not None
    if not has_controller:
        should_run = False

    if should_run:
        if meter is None:
            meter = SystemAudioLevelMeter(
                set_music_level,
                fps=fps,
                logger=print,
                spectrum_callback=set_music_spectrum,
                spectrum_bands=_MUSIC_SPECTRUM_BANDS,
            )
            with _LOCK:
                _SYSTEM_AUDIO_METER = meter
            meter.start()
        elif meter.is_running():
            meter.set_fps(fps)
        elif not str(getattr(meter, "error", "") or "").strip():
            meter.start()
        return

    if meter is not None:
        meter.stop()
        with _LOCK:
            if _SYSTEM_AUDIO_METER is meter:
                _SYSTEM_AUDIO_METER = None
    set_music_level(0.0)
    set_music_spectrum((0.0,) * _MUSIC_SPECTRUM_BANDS)


def _system_audio_meter_should_run(settings) -> bool:
    if not bool((settings or {}).get("ai_presence_music_reactivity_enabled", False)):
        return False
    if not bool((settings or {}).get("ai_presence_enabled", False)):
        return False
    mode = str((settings or {}).get("ai_presence_display_mode", "fullscreen") or "fullscreen").strip().lower()
    return mode != "off"


def _meter_fps(settings) -> int:
    try:
        return max(5, min(120, int((settings or {}).get("ai_presence_audio_refresh_hz", 30) or 30)))
    except Exception:
        return 30
