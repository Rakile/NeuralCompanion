from __future__ import annotations

import copy
from collections.abc import Mapping


SESSION_KEY = "ua_companion_orb_overlay"
KEY_PREFIX = "ua_companion_orb_"


def _mapping(value) -> dict:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def normalize_ua_companion_orb_settings(session_or_settings) -> dict:
    source = _mapping(session_or_settings)
    grouped = copy.deepcopy(_mapping(source.get(SESSION_KEY)))
    for key, value in source.items():
        if isinstance(key, str) and key.startswith(KEY_PREFIX) and key not in grouped:
            grouped[key] = copy.deepcopy(value)
    return grouped


def flatten_ua_companion_orb_settings(session_or_settings) -> dict:
    return copy.deepcopy(normalize_ua_companion_orb_settings(session_or_settings))


def group_ua_companion_orb_session(session: Mapping) -> dict:
    payload = dict(session or {})
    grouped = normalize_ua_companion_orb_settings(payload)
    for key in list(payload):
        if isinstance(key, str) and key.startswith(KEY_PREFIX):
            payload.pop(key, None)
    if grouped:
        payload[SESSION_KEY] = grouped
    else:
        payload.pop(SESSION_KEY, None)
    return payload


def with_flat_ua_companion_orb_settings(session: Mapping) -> dict:
    payload = dict(session or {})
    payload.update(flatten_ua_companion_orb_settings(payload))
    return payload
