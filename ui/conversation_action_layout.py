"""Normalization for the configurable Conversation response-action rail."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


CONVERSATION_RESPONSE_ACTION_ZONES = ("left", "center", "right")
DEFAULT_CONVERSATION_RESPONSE_ACTION_LAYOUT = {
    "left": (),
    "center": (
        "pause_speech",
        "skip_speech",
        "skip_user_reply",
    ),
    "right": ("copy", "replay", "edit", "regenerate", "delete"),
}
CONVERSATION_RESPONSE_ACTION_KEYS = frozenset(
    action
    for zone in CONVERSATION_RESPONSE_ACTION_ZONES
    for action in DEFAULT_CONVERSATION_RESPONSE_ACTION_LAYOUT[zone]
)

DEFAULT_CONVERSATION_USER_ACTION_LAYOUT = {
    "left": (),
    "center": (),
    "right": ("copy", "edit_draft", "retry_user_input", "delete"),
}
CONVERSATION_USER_ACTION_KEYS = frozenset(
    action
    for zone in CONVERSATION_RESPONSE_ACTION_ZONES
    for action in DEFAULT_CONVERSATION_USER_ACTION_LAYOUT[zone]
)


def _normalize_action_layout(
    value: Any,
    *,
    defaults: Mapping[str, Iterable[str]],
    allowed_actions: frozenset[str],
) -> dict[str, list[str]]:
    source = value if isinstance(value, Mapping) else {}
    normalized = {zone: [] for zone in CONVERSATION_RESPONSE_ACTION_ZONES}
    seen: set[str] = set()

    for zone in CONVERSATION_RESPONSE_ACTION_ZONES:
        configured = source.get(zone, ())
        if isinstance(configured, (str, bytes)) or not isinstance(
            configured, Iterable
        ):
            continue
        for raw_action in configured:
            action = str(raw_action or "").strip()
            if action not in allowed_actions or action in seen:
                continue
            normalized[zone].append(action)
            seen.add(action)

    for zone in CONVERSATION_RESPONSE_ACTION_ZONES:
        for action in defaults[zone]:
            if action not in seen:
                normalized[zone].append(action)
                seen.add(action)
    return normalized


def normalize_conversation_response_action_layout(
    value: Any,
) -> dict[str, list[str]]:
    return _normalize_action_layout(
        value,
        defaults=DEFAULT_CONVERSATION_RESPONSE_ACTION_LAYOUT,
        allowed_actions=CONVERSATION_RESPONSE_ACTION_KEYS,
    )


def normalize_conversation_user_action_layout(
    value: Any,
) -> dict[str, list[str]]:
    return _normalize_action_layout(
        value,
        defaults=DEFAULT_CONVERSATION_USER_ACTION_LAYOUT,
        allowed_actions=CONVERSATION_USER_ACTION_KEYS,
    )
