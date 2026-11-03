from __future__ import annotations

from typing import Any


CLICK_THROUGH_KEY = "companion_orb_click_through_default"
RIGHT_DRAG_FOCUS_KEY = "companion_orb_right_drag_focus_enabled"
INTERACTION_DEFAULTS_VERSION_KEY = "companion_orb_interaction_defaults_version"
CLICK_THROUGH_EXPLICIT_KEY = "companion_orb_click_through_explicit"
CURRENT_INTERACTION_DEFAULTS_VERSION = 2


def boolish(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        return bool(default)
    if value is None:
        return bool(default)
    return bool(value)


def _interaction_defaults_version(settings: dict[str, Any]) -> int:
    try:
        return int(settings.get(INTERACTION_DEFAULTS_VERSION_KEY, 0) or 0)
    except Exception:
        return 0


def normalize_interaction_settings(settings: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    normalized = dict(settings or {})
    click_through = boolish(normalized.get(CLICK_THROUGH_KEY, False), default=False)
    right_drag_focus = boolish(normalized.get(RIGHT_DRAG_FOCUS_KEY, True), default=True)
    explicit_click_through = boolish(normalized.get(CLICK_THROUGH_EXPLICIT_KEY, False), default=False)
    version = _interaction_defaults_version(normalized)
    if click_through and not right_drag_focus and not explicit_click_through:
        normalized[CLICK_THROUGH_KEY] = False
        normalized[RIGHT_DRAG_FOCUS_KEY] = True
        normalized[INTERACTION_DEFAULTS_VERSION_KEY] = CURRENT_INTERACTION_DEFAULTS_VERSION
        normalized[CLICK_THROUGH_EXPLICIT_KEY] = False
        return normalized, True
    if version <= 0 and (CLICK_THROUGH_KEY not in normalized or RIGHT_DRAG_FOCUS_KEY not in normalized):
        normalized.setdefault(CLICK_THROUGH_KEY, False)
        normalized.setdefault(RIGHT_DRAG_FOCUS_KEY, True)
    return normalized, False


def right_drag_focus_enabled(settings: dict[str, Any]) -> bool:
    return boolish(dict(settings or {}).get(RIGHT_DRAG_FOCUS_KEY, True), default=True)


def effective_click_through(
    settings: dict[str, Any],
    *,
    edit_mode: bool = False,
    placement_mode: bool = False,
) -> bool:
    settings = dict(settings or {})
    if bool(edit_mode) or bool(placement_mode) or right_drag_focus_enabled(settings):
        return False
    return boolish(settings.get(CLICK_THROUGH_KEY, False), default=False)
