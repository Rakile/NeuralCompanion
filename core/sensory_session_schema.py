from __future__ import annotations

import copy
from collections import OrderedDict
from collections.abc import Mapping


SESSION_KEY = "sensory"

LEGACY_FIELD_PATHS = OrderedDict(
    (
        ("sensory_feedback_source", ("core", "feedback_source")),
        ("sensory_feedback_interval_seconds", ("core", "feedback_interval_seconds")),
        ("sensory_pingpong_enabled", ("core", "pingpong_enabled")),
        ("sensory_allow_hidden_proactive_speech", ("core", "allow_hidden_proactive_speech")),
        ("sensory_allow_hidden_visual_generation", ("core", "allow_hidden_visual_generation")),
        ("sensory_pingpong_history_depth", ("core", "pingpong_history_depth")),
        ("sensory_pingpong_prompt", ("core", "pingpong_prompt")),
        ("sensory_pingpong_source_prompts", ("core", "source_prompts")),
        ("sensory_provider_metadata_overrides", ("core", "provider_metadata_overrides")),
        ("clipboard_source_auto_attach_next_user_turn", ("sources", "clipboard", "auto_attach_next_user_turn")),
        ("clipboard_source_auto_send_immediately", ("sources", "clipboard", "auto_send_immediately")),
        ("clipboard_source_hidden_loop_enabled", ("sources", "clipboard", "hidden_loop_enabled")),
        ("screen_source_max_width", ("sources", "screen", "max_width")),
        ("screen_source_max_height", ("sources", "screen", "max_height")),
        ("screen_source_max_side", ("sources", "screen", "max_side")),
        ("screen_source_jpeg_quality", ("sources", "screen", "jpeg_quality")),
        ("screen_source_capture_mode", ("sources", "screen", "capture_mode")),
        ("screen_source_capture_region", ("sources", "screen", "capture_region")),
        ("screen_source_auto_attach_next_user_turn", ("sources", "screen", "auto_attach_next_user_turn")),
        ("screen_source_full_max_width", ("sources", "screen", "full_max_width")),
        ("screen_source_full_max_height", ("sources", "screen", "full_max_height")),
        ("mock_heart_rate_bpm", ("sources", "mock_heart_rate", "bpm")),
        ("mock_heart_rate_window_visible", ("sources", "mock_heart_rate", "window_visible")),
        ("clipboard_supervisor_enabled", ("supervisors", "clipboard", "enabled")),
        ("clipboard_supervisor_prompt_template", ("supervisors", "clipboard", "prompt_template")),
        ("clipboard_supervisor_personas", ("supervisors", "clipboard", "personas")),
        ("clipboard_supervisor_selected_persona_id", ("supervisors", "clipboard", "selected_persona_id")),
        ("screen_supervisor_enabled", ("supervisors", "screen", "enabled")),
        ("screen_supervisor_prompt_template", ("supervisors", "screen", "prompt_template")),
        ("screen_supervisor_personas", ("supervisors", "screen", "personas")),
        ("screen_supervisor_selected_persona_id", ("supervisors", "screen", "selected_persona_id")),
        ("webcam_supervisor_enabled", ("supervisors", "webcam", "enabled")),
        ("webcam_supervisor_prompt_template", ("supervisors", "webcam", "prompt_template")),
        ("webcam_supervisor_personas", ("supervisors", "webcam", "personas")),
        ("webcam_supervisor_selected_persona_id", ("supervisors", "webcam", "selected_persona_id")),
        ("heart_rate_behavior_enabled", ("supervisors", "heart_rate", "enabled")),
        ("heart_rate_behavior_prompt_template", ("supervisors", "heart_rate", "prompt_template")),
        ("heart_rate_behavior_personas", ("supervisors", "heart_rate", "personas")),
        ("heart_rate_behavior_selected_persona_id", ("supervisors", "heart_rate", "selected_persona_id")),
    )
)

_MISSING = object()


def _mapping(value) -> dict:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _nested_get(payload: Mapping, path: tuple[str, ...]):
    current = payload
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return _MISSING
        current = current.get(part)
    return current


def _nested_set(payload: dict, path: tuple[str, ...], value) -> None:
    current = payload
    for part in path[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[path[-1]] = copy.deepcopy(value)


def normalize_sensory_settings(session_or_settings) -> dict:
    source = _mapping(session_or_settings)
    grouped = _mapping(source.get(SESSION_KEY))
    if not grouped and any(key in source for key in LEGACY_FIELD_PATHS):
        grouped = {}
    else:
        grouped = copy.deepcopy(grouped)

    for legacy_key, path in LEGACY_FIELD_PATHS.items():
        if legacy_key in source and _nested_get(grouped, path) is _MISSING:
            _nested_set(grouped, path, source.get(legacy_key))

    return grouped


def flatten_sensory_settings(session_or_settings) -> dict:
    grouped = normalize_sensory_settings(session_or_settings)
    flattened = {}
    for legacy_key, path in LEGACY_FIELD_PATHS.items():
        value = _nested_get(grouped, path)
        if value is not _MISSING:
            flattened[legacy_key] = copy.deepcopy(value)
    return flattened


def sensory_session_value(session_or_settings, legacy_key: str, default=None):
    path = LEGACY_FIELD_PATHS.get(str(legacy_key or ""))
    if path is None:
        return default
    grouped = normalize_sensory_settings(session_or_settings)
    value = _nested_get(grouped, path)
    if value is _MISSING:
        return default
    return value


def group_sensory_session(session: Mapping) -> dict:
    payload = dict(session or {})
    grouped = normalize_sensory_settings(payload)
    for key in LEGACY_FIELD_PATHS:
        payload.pop(key, None)
    if grouped:
        payload[SESSION_KEY] = grouped
    else:
        payload.pop(SESSION_KEY, None)
    return payload


def with_flat_sensory_settings(session: Mapping) -> dict:
    payload = dict(session or {})
    payload.update(flatten_sensory_settings(payload))
    return payload
