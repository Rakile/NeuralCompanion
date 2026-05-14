from __future__ import annotations

import copy
from collections import OrderedDict
from collections.abc import Mapping


SESSION_KEY = "ui"

LEGACY_FIELD_PATHS = OrderedDict(
    (
        ("first_run", ("onboarding", "first_run")),
        ("ui_theme_preset", ("theme", "preset")),
        ("geometry", ("window", "geometry")),
        ("window_state", ("window", "state")),
        ("right_dock_state", ("window", "right_dock_state")),
        ("main_splitter_sizes", ("layout", "main_splitter_sizes")),
        ("main_ui_real_layout", ("layout", "main_ui_real")),
        ("pinned_floating_docks", ("docks", "pinned_floating")),
        ("always_on_top_floating_docks", ("docks", "always_on_top")),
        ("preview_visible", ("docks", "preview_visible")),
        ("performance_guidance_visible", ("docks", "performance_guidance_visible")),
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


def normalize_ui_settings(session_or_settings) -> dict:
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


def flatten_ui_settings(session_or_settings) -> dict:
    grouped = normalize_ui_settings(session_or_settings)
    flattened = {}
    for legacy_key, path in LEGACY_FIELD_PATHS.items():
        value = _nested_get(grouped, path)
        if value is not _MISSING:
            flattened[legacy_key] = copy.deepcopy(value)
    return flattened


def group_ui_session(session: Mapping) -> dict:
    payload = dict(session or {})
    grouped = normalize_ui_settings(payload)
    for key in LEGACY_FIELD_PATHS:
        payload.pop(key, None)
    if grouped:
        payload[SESSION_KEY] = grouped
    else:
        payload.pop(SESSION_KEY, None)
    return payload


def with_flat_ui_settings(session: Mapping) -> dict:
    payload = dict(session or {})
    payload.update(flatten_ui_settings(payload))
    return payload
