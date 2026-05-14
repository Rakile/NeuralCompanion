from __future__ import annotations

import copy
from collections import OrderedDict
from collections.abc import Mapping


SESSION_KEY = "vam"

LEGACY_FIELD_PATHS = OrderedDict(
    (
        ("vam_root", ("paths", "root")),
        ("vam_bridge_root", ("paths", "bridge_root")),
        ("vam_target_atom_uid", ("target", "atom_uid")),
        ("vam_target_storable_id", ("target", "storable_id")),
        ("vam_vmc_host", ("vmc", "host")),
        ("vam_vmc_port", ("vmc", "port")),
        ("vam_vmc_enabled", ("vmc", "enabled")),
        ("vam_bridge_enabled", ("bridge", "enabled")),
        ("vam_play_audio_in_vam", ("audio", "play_audio_in_vam")),
        ("vam_timeline_auto_resume", ("timeline", "auto_resume")),
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


def normalize_vam_settings(session_or_settings) -> dict:
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


def flatten_vam_settings(session_or_settings) -> dict:
    grouped = normalize_vam_settings(session_or_settings)
    flattened = {}
    for legacy_key, path in LEGACY_FIELD_PATHS.items():
        value = _nested_get(grouped, path)
        if value is not _MISSING:
            flattened[legacy_key] = copy.deepcopy(value)
    return flattened


def vam_session_value(session_or_settings, legacy_key: str, default=None):
    path = LEGACY_FIELD_PATHS.get(str(legacy_key or ""))
    if path is None:
        return default
    grouped = normalize_vam_settings(session_or_settings)
    value = _nested_get(grouped, path)
    if value is _MISSING:
        return default
    return value


def group_vam_session(session: Mapping) -> dict:
    payload = dict(session or {})
    grouped = normalize_vam_settings(payload)
    for key in LEGACY_FIELD_PATHS:
        payload.pop(key, None)
    if grouped:
        payload[SESSION_KEY] = grouped
    else:
        payload.pop(SESSION_KEY, None)
    return payload


def with_flat_vam_settings(session: Mapping) -> dict:
    payload = dict(session or {})
    payload.update(flatten_vam_settings(payload))
    return payload
