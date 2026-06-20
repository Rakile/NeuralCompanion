"""Thread-safe event bridge from engine workers to the Qt presence overlay."""

from __future__ import annotations

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
_LAST_MOOD = "neutral"
_LAST_SETTINGS = {}
_SYSTEM_AUDIO_METER = None
_VALID_STATES = {"idle", "listening", "thinking", "speaking"}
_LAST_LEVEL_DISPATCH_AT = 0.0
_LAST_ORB_LEVEL_DISPATCH_AT = 0.0
_LAST_MUSIC_LEVEL_DISPATCH_AT = 0.0
_AUDIO_LEVEL_MIN_INTERVAL_SECONDS = 1.0 / 18.0
_MUSIC_LEVEL_MIN_INTERVAL_SECONDS = 1.0 / 12.0
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
        if meter is None or not meter.is_running():
            meter = SystemAudioLevelMeter(set_music_level, fps=fps, logger=print)
            with _LOCK:
                _SYSTEM_AUDIO_METER = meter
            meter.start()
        else:
            meter.set_fps(fps)
        return

    if meter is not None:
        meter.stop()
        with _LOCK:
            if _SYSTEM_AUDIO_METER is meter:
                _SYSTEM_AUDIO_METER = None
    set_music_level(0.0)


def _system_audio_meter_should_run(settings) -> bool:
    if not bool((settings or {}).get("ai_presence_music_reactivity_enabled", False)):
        return False
    if not bool((settings or {}).get("ai_presence_enabled", False)):
        return False
    mode = str((settings or {}).get("ai_presence_display_mode", "fullscreen") or "fullscreen").strip().lower()
    return mode != "off"


def _meter_fps(settings) -> int:
    try:
        return max(5, min(30, int((settings or {}).get("ai_presence_audio_refresh_hz", 30) or 30)))
    except Exception:
        return 30
