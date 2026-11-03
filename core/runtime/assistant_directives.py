"""Strict, display-safe extraction of assistant-side runtime directives."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


_MARKER = "[[companion_orb_focus "
_TERMINAL_DIRECTIVE_RE = re.compile(
    r"(?:\r?\n)?\[\[companion_orb_focus (?P<payload>\{[^\r\n]{2,512}\})\]\]\.?[ \t]*\Z"
)
_REGION_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}\Z")
_ALLOWED_KEYS = frozenset({"region_id", "target", "action"})
_ALLOWED_ACTIONS = frozenset({"hover", "look", "move"})


@dataclass(frozen=True, slots=True)
class AssistantFocusDirective:
    region_id: str
    target: str
    action: str = "hover"


class CompanionOrbDirectiveStreamFilter:
    """Withhold only a possible terminal Orb marker from streamed speech."""

    def __init__(self) -> None:
        self._pending = ""
        self._capturing_marker = False
        self._finished = False

    def feed(self, value: object) -> str:
        if self._finished:
            return ""
        self._pending += str(value or "")
        if self._capturing_marker:
            return ""
        marker_index = self._pending.find(_MARKER)
        if marker_index >= 0:
            visible = self._pending[:marker_index]
            self._pending = self._pending[marker_index:]
            self._capturing_marker = True
            return visible
        retained = len(_MARKER) - 1
        safe_length = max(0, len(self._pending) - retained)
        visible = self._pending[:safe_length]
        self._pending = self._pending[safe_length:]
        return visible

    def finish(self) -> str:
        if self._finished:
            return ""
        self._finished = True
        pending = self._pending
        self._pending = ""
        if not self._capturing_marker:
            return pending
        cleaned, directive = extract_companion_orb_focus(pending)
        return cleaned if directive is not None else pending


def _clean_single_line(value: object, *, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[:limit]


def extract_companion_orb_focus(
    text: object,
) -> tuple[str, AssistantFocusDirective | None]:
    source = str(text or "").strip()
    if not source or source.count(_MARKER) != 1:
        return source, None
    match = _TERMINAL_DIRECTIVE_RE.search(source)
    if match is None:
        return source, None
    if source[: match.start()].count("```") % 2:
        return source, None
    raw_payload = match.group("payload")
    try:
        payload = json.loads(raw_payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return source, None
    if not isinstance(payload, dict) or set(payload) != _ALLOWED_KEYS:
        return source, None
    if not all(isinstance(payload.get(key), str) for key in _ALLOWED_KEYS):
        return source, None
    region_id = _clean_single_line(payload.get("region_id"), limit=80)
    target = _clean_single_line(payload.get("target"), limit=160)
    action = _clean_single_line(payload.get("action"), limit=16).lower()
    if (
        not region_id
        or _REGION_ID_RE.fullmatch(region_id) is None
        or not target
        or len(str(payload.get("target") or "")) > 160
        or "[[" in target
        or "]]" in target
        or action not in _ALLOWED_ACTIONS
    ):
        return source, None
    cleaned = source[: match.start()].rstrip()
    return cleaned, AssistantFocusDirective(region_id, target, action)


__all__ = [
    "AssistantFocusDirective",
    "CompanionOrbDirectiveStreamFilter",
    "extract_companion_orb_focus",
]
