from __future__ import annotations

import copy
from collections import OrderedDict
from collections.abc import Mapping


SESSION_KEY = "chunking"

LEGACY_FIELD_PATHS = OrderedDict(
    (
        ("chunk_target_chars", ("default", "target_chars")),
        ("chunk_max_chars", ("default", "max_chars")),
        ("musetalk_chunk_target_chars", ("musetalk", "standard", "target_chars")),
        ("musetalk_chunk_max_chars", ("musetalk", "standard", "max_chars")),
        ("musetalk_quickstart_1_target_chars", ("musetalk", "quickstart_1", "target_chars")),
        ("musetalk_quickstart_1_max_chars", ("musetalk", "quickstart_1", "max_chars")),
        ("musetalk_quickstart_2_target_chars", ("musetalk", "quickstart_2", "target_chars")),
        ("musetalk_quickstart_2_max_chars", ("musetalk", "quickstart_2", "max_chars")),
        ("stream_chunk_target_chars", ("stream", "target_chars")),
        ("stream_chunk_max_chars", ("stream", "max_chars")),
        ("stream_first_chunk_min_chars", ("stream", "first_chunk_min_chars")),
        ("stream_force_flush_seconds", ("stream", "first_flush_seconds")),
        ("stream_force_flush_later_seconds", ("stream", "later_flush_seconds")),
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


def normalize_chunking_settings(session_or_settings) -> dict:
    source = _mapping(session_or_settings)
    if SESSION_KEY in source and isinstance(source.get(SESSION_KEY), Mapping):
        source = _mapping(source.get(SESSION_KEY))
    grouped = {}
    if any(key in source for key in LEGACY_FIELD_PATHS):
        for legacy_key, path in LEGACY_FIELD_PATHS.items():
            if legacy_key in source:
                _nested_set(grouped, path, source.get(legacy_key))
        for key, value in source.items():
            if key not in LEGACY_FIELD_PATHS:
                grouped[key] = copy.deepcopy(value)
        return grouped
    return copy.deepcopy(source)


def flatten_chunking_settings(session_or_settings) -> dict:
    grouped = normalize_chunking_settings(session_or_settings)
    flattened = {}
    for legacy_key, path in LEGACY_FIELD_PATHS.items():
        value = _nested_get(grouped, path)
        if value is not _MISSING:
            flattened[legacy_key] = copy.deepcopy(value)
    return flattened


def group_chunking_session(session: Mapping) -> dict:
    payload = dict(session or {})
    if SESSION_KEY in payload:
        grouped = normalize_chunking_settings(payload.get(SESSION_KEY))
        payload[SESSION_KEY] = grouped
    return payload


def with_flat_chunking_settings(session: Mapping) -> dict:
    payload = dict(session or {})
    if SESSION_KEY in payload:
        payload[SESSION_KEY] = flatten_chunking_settings(payload.get(SESSION_KEY))
    return payload
