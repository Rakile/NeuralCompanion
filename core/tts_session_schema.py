from __future__ import annotations

import copy
from collections import OrderedDict
from collections.abc import Mapping


SESSION_KEY = "tts_runtime"

LEGACY_FIELD_PATHS = OrderedDict(
    (
        ("voice_file", ("core", "voice_file")),
        ("tts_backend", ("core", "backend")),
        ("tts_runtime_expanded", ("core", "expanded")),
        ("tts_seed", ("chatterbox", "seed")),
        ("tts_temperature", ("chatterbox", "temperature")),
        ("tts_top_p", ("chatterbox", "top_p")),
        ("tts_top_k", ("chatterbox", "top_k")),
        ("tts_repeat_penalty", ("chatterbox", "repeat_penalty")),
        ("tts_min_p", ("chatterbox", "min_p")),
        ("tts_normalize_loudness", ("chatterbox", "normalize_loudness")),
        ("tts_prewarm_on_start", ("chatterbox", "prewarm_on_start")),
        ("tts_use_cloned_voice", ("chatterbox", "use_cloned_voice")),
        ("tts_apply_watermark", ("chatterbox", "apply_watermark")),
        ("chatterbox_multilingual_language", ("chatterbox_multilingual", "language")),
        ("chatterbox_multilingual_seed", ("chatterbox_multilingual", "seed")),
        ("chatterbox_multilingual_temperature", ("chatterbox_multilingual", "temperature")),
        ("chatterbox_multilingual_top_p", ("chatterbox_multilingual", "top_p")),
        ("chatterbox_multilingual_top_k", ("chatterbox_multilingual", "top_k")),
        ("chatterbox_multilingual_repeat_penalty", ("chatterbox_multilingual", "repeat_penalty")),
        ("chatterbox_multilingual_normalize_loudness", ("chatterbox_multilingual", "normalize_loudness")),
        ("chatterbox_multilingual_prewarm_on_start", ("chatterbox_multilingual", "prewarm_on_start")),
        ("chatterbox_multilingual_use_cloned_voice", ("chatterbox_multilingual", "use_cloned_voice")),
        ("chatterbox_multilingual_apply_watermark", ("chatterbox_multilingual", "apply_watermark")),
        ("pocket_tts_python", ("pockettts", "python")),
        ("pocket_tts_temperature", ("pockettts", "temperature")),
        ("pocket_tts_lsd_decode_steps", ("pockettts", "lsd_decode_steps")),
        ("pocket_tts_eos_threshold", ("pockettts", "eos_threshold")),
        ("pocket_tts_frames_after_eos", ("pockettts", "frames_after_eos")),
        ("pocket_tts_builtin_voice", ("pockettts", "builtin_voice")),
        ("pocket_tts_use_cloned_voice", ("pockettts", "use_cloned_voice")),
        ("pocket_tts_prewarm_on_start", ("pockettts", "prewarm_on_start")),
        ("pocket_tts_multilingual_language", ("pockettts_multilingual", "language")),
        ("pocket_tts_multilingual_temperature", ("pockettts_multilingual", "temperature")),
        ("pocket_tts_multilingual_lsd_decode_steps", ("pockettts_multilingual", "lsd_decode_steps")),
        ("pocket_tts_multilingual_eos_threshold", ("pockettts_multilingual", "eos_threshold")),
        ("pocket_tts_multilingual_frames_after_eos", ("pockettts_multilingual", "frames_after_eos")),
        ("pocket_tts_multilingual_builtin_voice", ("pockettts_multilingual", "builtin_voice")),
        ("pocket_tts_multilingual_use_cloned_voice", ("pockettts_multilingual", "use_cloned_voice")),
        ("pocket_tts_multilingual_prewarm_on_start", ("pockettts_multilingual", "prewarm_on_start")),
        ("gemini_tts_preview_settings", ("gemini_tts_preview", "settings")),
    )
)

_MISSING = object()


def _mapping(value) -> dict:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _nested_get(payload: Mapping, path: tuple[str, str]):
    current = payload
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return _MISSING
        current = current.get(part)
    return current


def _nested_set(payload: dict, path: tuple[str, str], value) -> None:
    current = payload
    for part in path[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[path[-1]] = copy.deepcopy(value)


def normalize_tts_runtime_settings(session_or_settings) -> dict:
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


def flatten_tts_runtime_settings(session_or_settings) -> dict:
    grouped = normalize_tts_runtime_settings(session_or_settings)
    flattened = {}
    for legacy_key, path in LEGACY_FIELD_PATHS.items():
        value = _nested_get(grouped, path)
        if value is not _MISSING:
            flattened[legacy_key] = copy.deepcopy(value)
    return flattened


def tts_runtime_session_payload(flat_settings: Mapping) -> dict:
    return {SESSION_KEY: normalize_tts_runtime_settings(dict(flat_settings or {}))}


def tts_runtime_session_value(session_or_settings, legacy_key: str, default=None):
    path = LEGACY_FIELD_PATHS.get(str(legacy_key or ""))
    if path is None:
        return default
    grouped = normalize_tts_runtime_settings(session_or_settings)
    value = _nested_get(grouped, path)
    if value is _MISSING:
        return default
    return value


def group_tts_runtime_session(session: Mapping) -> dict:
    payload = dict(session or {})
    grouped = normalize_tts_runtime_settings(payload)
    for key in LEGACY_FIELD_PATHS:
        payload.pop(key, None)
    if grouped:
        payload[SESSION_KEY] = grouped
    else:
        payload.pop(SESSION_KEY, None)
    return payload


def with_flat_tts_runtime_settings(session: Mapping) -> dict:
    payload = dict(session or {})
    payload.update(flatten_tts_runtime_settings(payload))
    return payload
