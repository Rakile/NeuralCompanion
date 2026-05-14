from __future__ import annotations

import copy
from collections import OrderedDict
from collections.abc import Mapping


SESSION_KEY = "musetalk"

LEGACY_FIELD_PATHS = OrderedDict(
    (
        ("musetalk_avatar_pack_id", ("runtime", "avatar_pack_id")),
        ("musetalk_vram_mode", ("runtime", "vram_mode")),
        ("musetalk_loop_fade_ms", ("runtime", "loop_fade_ms")),
        ("musetalk_use_frame_cache", ("runtime", "use_frame_cache")),
        ("musetalk_enabled_pack_emotions", ("runtime", "enabled_pack_emotions")),
        ("musetalk_source_path", ("preprocess", "source_path")),
        ("musetalk_preprocess_target_pack_id", ("preprocess", "target_pack_id")),
        ("musetalk_avatar_id", ("preprocess", "avatar_id")),
        ("musetalk_bbox_shift", ("preprocess", "bbox_shift")),
        ("musetalk_debug_frame_index", ("preprocess", "debug_frame_index")),
        ("musetalk_debug_show_mask_overlay", ("preprocess", "debug_show_mask_overlay")),
        ("musetalk_debug_brush_size", ("preprocess", "debug_brush_size")),
        ("musetalk_debug_brush_feather", ("preprocess", "debug_brush_feather")),
        ("musetalk_parsing_mode", ("preprocess", "parsing_mode")),
        ("musetalk_extra_margin", ("preprocess", "extra_margin")),
        ("musetalk_left_cheek_width", ("preprocess", "left_cheek_width")),
        ("musetalk_right_cheek_width", ("preprocess", "right_cheek_width")),
        ("musetalk_mask_ranges", ("preprocess", "mask_ranges")),
        ("musetalk_mask_overrides", ("preprocess", "mask_overrides")),
        ("musetalk_recreate", ("preprocess", "recreate")),
        ("musetalk_create_frame_cache", ("preprocess", "create_frame_cache")),
        ("musetalk_emotion_tags", ("preprocess", "emotion_tags")),
        ("musetalk_test_audio", ("preprocess", "test_audio")),
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


def normalize_musetalk_settings(session_or_settings) -> dict:
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


def flatten_musetalk_settings(session_or_settings) -> dict:
    grouped = normalize_musetalk_settings(session_or_settings)
    flattened = {}
    for legacy_key, path in LEGACY_FIELD_PATHS.items():
        value = _nested_get(grouped, path)
        if value is not _MISSING:
            flattened[legacy_key] = copy.deepcopy(value)
    return flattened


def musetalk_session_payload(flat_settings: Mapping) -> dict:
    return {SESSION_KEY: normalize_musetalk_settings(dict(flat_settings or {}))}


def musetalk_session_value(session_or_settings, legacy_key: str, default=None):
    path = LEGACY_FIELD_PATHS.get(str(legacy_key or ""))
    if path is None:
        return default
    grouped = normalize_musetalk_settings(session_or_settings)
    value = _nested_get(grouped, path)
    if value is _MISSING:
        return default
    return value


def group_musetalk_session(session: Mapping) -> dict:
    payload = dict(session or {})
    grouped = normalize_musetalk_settings(payload)
    for key in LEGACY_FIELD_PATHS:
        payload.pop(key, None)
    if grouped:
        payload[SESSION_KEY] = grouped
    else:
        payload.pop(SESSION_KEY, None)
    return payload


def with_flat_musetalk_settings(session: Mapping) -> dict:
    payload = dict(session or {})
    payload.update(flatten_musetalk_settings(payload))
    return payload
