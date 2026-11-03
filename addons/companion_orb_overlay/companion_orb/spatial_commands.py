from __future__ import annotations

import re
from dataclasses import dataclass


_COMMAND_RE = re.compile(
    r"^\s*(?:(?P<address>orb|companion\s+orb)\s*[,;:\-]?\s+)?"
    r"(?P<verb>react\s+to|look\s+at|move\s+to|hover\s+near|read|describe|explain|summarize)"
    r"\s+(?P<target>.+?)\s*[.!]?\s*$",
    re.IGNORECASE,
)
_VISIBLE_TARGET_RE = re.compile(
    r"\b(this|that|picture|photo|image|window|panel|button|control|icon|"
    r"text|area|region|media|video|on\s+the\s+(?:left|right|top|bottom))\b",
    re.IGNORECASE,
)
_ACTIONS = {
    "react to": "react",
    "look at": "look",
    "move to": "move",
    "hover near": "hover",
    "read": "read",
    "describe": "describe",
    "explain": "explain",
    "summarize": "summarize",
}


@dataclass(frozen=True, slots=True)
class SpatialCommand:
    action: str
    target_text: str


def parse_spatial_command(text: object) -> SpatialCommand | None:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value or len(value) > 400 or value.endswith("?"):
        return None
    match = _COMMAND_RE.fullmatch(value)
    if match is None:
        return None
    target = re.sub(r"\s+", " ", match.group("target") or "").strip(" ,.;:-")
    if not target or len(target) > 240:
        return None
    if not match.group("address") and _VISIBLE_TARGET_RE.search(target) is None:
        return None
    verb = re.sub(r"\s+", " ", match.group("verb").casefold()).strip()
    action = _ACTIONS.get(verb)
    if action == "react" and target.casefold().startswith("the "):
        target = target[4:].strip()
    return SpatialCommand(action, target) if action else None


__all__ = ["SpatialCommand", "parse_spatial_command"]
