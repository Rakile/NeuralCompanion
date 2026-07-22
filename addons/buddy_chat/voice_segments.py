from __future__ import annotations

import re
from typing import Any

from .models import BuddyPersona


_BRACKET_LABEL_RE = re.compile(r"^\s*\[([^\]]{1,64})\]\s*$")
_BRACKET_INLINE_RE = re.compile(r"^\s*\[([^\]]{1,64})\]\s*(.+?)\s*$")
_COLON_LABEL_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 _'-]{1,48})\s*:\s*(.*)$")
_BRACKET_MARKER_RE = re.compile(r"\[([^\]]{1,64})\]")
_QUOTED_TEXT_RE = re.compile(r'"([^"]{1,1600})"|“([^”]{1,1600})”')


def _lookup_key(value: str) -> str:
    return str(value or "").strip().lower()


def _persona_lookup(personas: list[BuddyPersona]) -> dict[str, BuddyPersona]:
    lookup: dict[str, BuddyPersona] = {}
    for persona in list(personas or []):
        if not bool(persona.enabled):
            continue
        display_name = str(persona.display_name or "").strip()
        keys = {
            _lookup_key(persona.id),
            _lookup_key(display_name),
            _lookup_key(display_name.split(",", 1)[0]),
        }
        for key in keys:
            if key:
                lookup[key] = persona
    return lookup


def _narrative_speaker_from_line(raw_line: str, lookup: dict[str, BuddyPersona]) -> BuddyPersona | None:
    text = str(raw_line or "").strip()
    if not text.endswith(":"):
        return None
    without_colon = text[:-1].strip()
    lowered = without_colon.lower()
    for key in sorted(lookup.keys(), key=len, reverse=True):
        if not key or lowered == key:
            continue
        if not (lowered.startswith(key + " ") or lowered.startswith(key + "'") or lowered.startswith(key + ",")):
            continue
        return lookup.get(key)
    return None


def _initial_persona_from_line(raw_line: str, lookup: dict[str, BuddyPersona]) -> BuddyPersona | None:
    text = str(raw_line or "").strip()
    if not text:
        return None
    lowered = text.lower()
    for key in sorted(lookup.keys(), key=len, reverse=True):
        if not key:
            continue
        if lowered == key:
            return lookup.get(key)
        if lowered.startswith(key + " ") or lowered.startswith(key + "'") or lowered.startswith(key + ","):
            return lookup.get(key)
    return None


def _clean_spoken_line(raw_line: str) -> str:
    text = str(raw_line or "").strip()
    for _index in range(2):
        if len(text) >= 2 and text[0] == "*" and text[-1] == "*":
            text = text[1:-1].strip()
            continue
        if len(text) >= 2 and text[0] == "_" and text[-1] == "_":
            text = text[1:-1].strip()
            continue
        break
    if len(text) >= 2 and ((text[0] == '"' and text[-1] == '"') or (text[0] == "'" and text[-1] == "'")):
        text = text[1:-1].strip()
    return text


def _clean_spoken_text(value: str) -> str:
    lines = [_clean_spoken_line(line) for line in str(value or "").splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines).strip()


def _speaker_label_lines(value: str, lookup: dict[str, BuddyPersona]) -> list[str]:
    expanded: list[str] = []
    for raw_line in str(value or "").splitlines():
        markers = [
            match
            for match in _BRACKET_MARKER_RE.finditer(raw_line)
            if _lookup_key(match.group(1)) in lookup
        ]
        if not markers:
            expanded.append(raw_line)
            continue
        cursor = 0
        for index, marker in enumerate(markers):
            before = raw_line[cursor:marker.start()].strip()
            if before:
                expanded.append(before)
            end = markers[index + 1].start() if index + 1 < len(markers) else len(raw_line)
            expanded.append(raw_line[marker.start():end].strip())
            cursor = end
        trailing = raw_line[cursor:].strip()
        if trailing:
            expanded.append(trailing)
    return expanded


def _narrator_segment(body: str) -> dict[str, Any]:
    return {
        "text": body,
        "persona_id": "",
        "display_name": "",
        "voice_path": "",
        "voice_volume": 1.0,
        "voice_volume_percent": 100,
        "voice_route": {
            "enabled": False,
            "supported": False,
            "route_reason": "buddy_chat_narrator",
        },
    }


def _persona_segment(persona: BuddyPersona, body: str) -> dict[str, Any]:
    voice = persona.voice
    return {
        "text": body,
        "persona_id": persona.id,
        "display_name": persona.display_name,
        "voice_path": str(voice.sample_path or "") if bool(voice.enabled) else "",
        "voice_volume": float(voice.volume or 1.0),
        "voice_volume_percent": int(round(float(voice.volume or 1.0) * 100.0)),
        "voice_route": {
            "enabled": bool(voice.enabled),
            "persona_id": persona.id,
            "display_name": persona.display_name,
            "sample_path": str(voice.sample_path or ""),
            "supported": bool(voice.enabled and str(voice.sample_path or "").strip()),
            "route_reason": "buddy_chat_speaker_label",
        },
    }


def _inline_quoted_dialogue_segments(raw_line: str, persona: BuddyPersona) -> list[dict[str, Any]]:
    line = str(raw_line or "").strip()
    matches = list(_QUOTED_TEXT_RE.finditer(line))
    if not matches:
        return []
    result: list[dict[str, Any]] = []
    cursor = 0
    for match in matches:
        before = _clean_spoken_text(line[cursor : match.start()])
        if before:
            result.append(_narrator_segment(before))
        quoted = _clean_spoken_text(match.group(1) or match.group(2) or "")
        if quoted:
            result.append(_persona_segment(persona, quoted))
        cursor = match.end()
    after = _clean_spoken_text(line[cursor:])
    if after:
        result.append(_narrator_segment(after))
    return result


def split_buddy_voice_segments(text: str, *, personas: list[BuddyPersona]) -> dict[str, Any]:
    value = str(text or "")
    if not value.strip():
        return {"segments": [], "suppress_original": False}
    lookup = _persona_lookup(personas)
    if not lookup:
        return {"segments": [], "suppress_original": False}

    segments: list[dict[str, Any]] = []
    current: BuddyPersona | None = None
    current_lines: list[str] = []
    saw_label = False
    current_from_narrative = False
    narrative_dialogue_has_text = False

    def flush() -> None:
        nonlocal current_lines
        body = _clean_spoken_text("\n".join(current_lines))
        current_lines = []
        if not body:
            return
        if current is None:
            segments.append(_narrator_segment(body))
            return
        segments.append(_persona_segment(current, body))

    for raw_line in _speaker_label_lines(value, lookup):
        if current_from_narrative and narrative_dialogue_has_text and not str(raw_line or "").strip():
            flush()
            current = None
            current_from_narrative = False
            narrative_dialogue_has_text = False
            continue
        bracket = _BRACKET_LABEL_RE.match(raw_line)
        if bracket:
            candidate = lookup.get(str(bracket.group(1) or "").strip().lower())
            if candidate is not None:
                flush()
                current = candidate
                saw_label = True
                current_from_narrative = False
                narrative_dialogue_has_text = False
                continue
        bracket_inline = _BRACKET_INLINE_RE.match(raw_line)
        if bracket_inline:
            candidate = lookup.get(str(bracket_inline.group(1) or "").strip().lower())
            if candidate is not None:
                flush()
                current = candidate
                saw_label = True
                current_from_narrative = False
                narrative_dialogue_has_text = False
                current_lines.append(str(bracket_inline.group(2) or "").strip())
                continue
        colon = _COLON_LABEL_RE.match(raw_line)
        if colon:
            candidate = lookup.get(str(colon.group(1) or "").strip().lower())
            if candidate is not None:
                flush()
                current = candidate
                saw_label = True
                current_from_narrative = False
                narrative_dialogue_has_text = False
                tail = str(colon.group(2) or "").strip()
                if tail:
                    current_lines.append(tail)
                continue
        narrative_candidate = _narrative_speaker_from_line(raw_line, lookup)
        if narrative_candidate is not None:
            flush()
            current = None
            current_lines.append(raw_line)
            flush()
            current = narrative_candidate
            saw_label = True
            current_from_narrative = True
            narrative_dialogue_has_text = False
            continue
        inline_candidate = _initial_persona_from_line(raw_line, lookup)
        inline_segments = _inline_quoted_dialogue_segments(raw_line, inline_candidate) if inline_candidate is not None else []
        if inline_segments:
            flush()
            segments.extend(inline_segments)
            current = None
            saw_label = True
            current_from_narrative = False
            narrative_dialogue_has_text = False
            continue
        current_lines.append(raw_line)
        if current_from_narrative and str(raw_line or "").strip():
            narrative_dialogue_has_text = True
    flush()

    if not saw_label or not segments:
        return {"segments": [], "suppress_original": False}
    return {"segments": segments, "suppress_original": True}
