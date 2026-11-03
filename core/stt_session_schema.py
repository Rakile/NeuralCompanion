from __future__ import annotations

import copy
from collections import OrderedDict
from collections.abc import Mapping


SESSION_KEY = "stt_runtime"
LEGACY_TTS_SESSION_KEY = "tts_runtime"

LEGACY_FIELD_PATHS = OrderedDict(
    (
        ("stt_runtime_expanded", ("ui", "expanded")),
        ("stt_backend", ("core", "backend")),
        ("stt_model_size", ("core", "model_size")),
        ("stt_language", ("core", "language")),
        ("stt_backend_settings", ("backend_settings",)),
    )
)

OLD_TTS_STT_PATHS = {
    "stt_runtime_expanded": ("expanded",),
    "stt_backend": ("backend",),
    "stt_model_size": ("model_size",),
    "stt_language": ("language",),
    "stt_backend_settings": ("backend_settings",),
}

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


def normalize_stt_runtime_settings(session_or_settings) -> dict:
    source = _mapping(session_or_settings)
    has_top_level = SESSION_KEY in source
    grouped = _mapping(source.get(SESSION_KEY))
    old_tts_runtime = _mapping(source.get(LEGACY_TTS_SESSION_KEY))
    old_tts_stt = _mapping(old_tts_runtime.get("stt"))
    if has_top_level:
        grouped = copy.deepcopy(grouped)
    elif old_tts_stt or any(key in source for key in LEGACY_FIELD_PATHS):
        grouped = {}
    else:
        grouped = {}

    if has_top_level:
        return grouped

    for legacy_key, path in LEGACY_FIELD_PATHS.items():
        if _nested_get(grouped, path) is not _MISSING:
            continue
        if legacy_key in source:
            _nested_set(grouped, path, source.get(legacy_key))
            continue
        old_path = OLD_TTS_STT_PATHS.get(legacy_key)
        old_value = _nested_get(old_tts_stt, old_path) if old_path is not None else _MISSING
        if old_value is not _MISSING:
            _nested_set(grouped, path, old_value)

    return grouped


def flatten_stt_runtime_settings(session_or_settings) -> dict:
    grouped = normalize_stt_runtime_settings(session_or_settings)
    flattened = {}
    for legacy_key, path in LEGACY_FIELD_PATHS.items():
        value = _nested_get(grouped, path)
        if value is not _MISSING:
            flattened[legacy_key] = copy.deepcopy(value)
    return flattened


def group_stt_runtime_session(session: Mapping) -> dict:
    payload = dict(session or {})
    grouped = normalize_stt_runtime_settings(payload)
    for key in LEGACY_FIELD_PATHS:
        payload.pop(key, None)
    if grouped:
        payload[SESSION_KEY] = grouped
    else:
        payload.pop(SESSION_KEY, None)
    return payload


def with_flat_stt_runtime_settings(session: Mapping) -> dict:
    payload = dict(session or {})
    payload.update(flatten_stt_runtime_settings(payload))
    return payload
