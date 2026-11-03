"""Ditto's saved namespace and compatibility with legacy root settings."""
from __future__ import annotations

import copy
from collections.abc import Mapping

from addons.ditto_avatar.config import DEFAULTS

SESSION_KEY = 'ditto'


def _grouped(payload):
    grouped = payload.get(SESSION_KEY, {})
    if not isinstance(grouped, Mapping):
        raise ValueError("The saved 'ditto' settings group must be an object.")
    return grouped


def flatten_ditto_settings(session_or_settings):
    """Read either layout; grouped values win, including false/zero/empty values."""
    payload = dict(session_or_settings or {})
    values = {key: copy.deepcopy(payload[key]) for key in DEFAULTS if key in payload}
    values.update({key: copy.deepcopy(value) for key, value in _grouped(payload).items()
                   if key in DEFAULTS})
    return values


def with_grouped_ditto_settings(session):
    """Copy legacy values into their namespace before contract-driven alias removal.

    Keep aliases here so the session merger can record their removal. Preserve
    values even when Ditto is unloaded and supplies no config or contribution.
    """
    payload = copy.deepcopy(dict(session or {}))
    grouped = dict(_grouped(payload))
    for key in DEFAULTS:
        if key in payload and key not in grouped:
            grouped[key] = copy.deepcopy(payload[key])
    if grouped or SESSION_KEY in payload:
        payload[SESSION_KEY] = grouped
    return payload
