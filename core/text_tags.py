"""Reusable bracket tag parsing for speech, emotion, and visual directives."""

from __future__ import annotations

import re
from collections.abc import Mapping


SOUND_TAGS = {
    "[clear throat]", "[sigh]", "[shush]", "[groan]",
    "[sniff]", "[gasp]", "[chuckle]", "[laugh]"
}
SOUND_TAG_NAMES = {tag.strip()[1:-1].strip().lower() for tag in SOUND_TAGS}
CONTROL_TAG_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def persona_mood_names(config: Mapping[str, object]) -> set[str]:
    """Return registered portrait tags, excluding reserved vocal actions."""
    raw = config.get("persona_mood_tags", {})
    if not isinstance(raw, Mapping):
        return set()
    return {str(name).strip().lower() for name in raw
            if is_single_word_control_tag(name) and not is_sound_tag(name)}


def persona_mood_instructions(config: Mapping[str, object]) -> str:
    names = sorted(persona_mood_names(config))
    if not names:
        return ""
    descriptions = config.get("persona_mood_tags", {})
    lines = ["", "PERSONA MOOD PORTRAITS: These additional visual mood tags are available. "
             "Use them when appropriate; they remain active until the next mood tag. "
             "Voice sound tags do not change the portrait."]
    for name in names:
        hint = str(descriptions.get(name) or "").strip()
        lines.append(f"[{name}]" + (f": {hint}" if hint else ""))
    return "\n".join(lines)


def normalize_bracket_tag(tag_text):
    stripped = str(tag_text or "").strip()
    if not (stripped.startswith("[") and stripped.endswith("]")):
        return None
    inner = stripped[1:-1].strip().lower()
    return inner or None


def is_single_word_control_tag(tag_name):
    value = str(tag_name or "").strip()
    return bool(value and CONTROL_TAG_TOKEN_RE.fullmatch(value))


def is_sound_tag(tag_name):
    return str(tag_name or "").strip().lower() in SOUND_TAG_NAMES


def is_emotion_tag(tag_name, available_emotion_names):
    normalized = str(tag_name or "").strip().lower()
    if not is_single_word_control_tag(normalized):
        return False
    if is_sound_tag(normalized):
        return False
    return normalized in set(str(name or "").strip().lower() for name in available_emotion_names or [])


def parse_text_segments(text, available_emotion_names, supported_sound_tag_names=None):
    """Split reply text into emotion-tagged speech segments."""
    sound_names = SOUND_TAG_NAMES if supported_sound_tag_names is None else {
        str(name or "").strip().lower()
        for name in supported_sound_tag_names or []
        if str(name or "").strip()
    }
    current_emotion = "neutral"
    segments = []
    current_buffer = []
    parts = re.split(r"(\[[^\]]+\])", text)
    for part in parts:
        if not part:
            continue
        clean_part = part.strip()
        if clean_part.startswith("[") and clean_part.endswith("]"):
            normalized_tag = normalize_bracket_tag(clean_part)
            if str(normalized_tag or "").strip().lower() in sound_names:
                current_buffer.append(part)
            elif is_emotion_tag(normalized_tag, available_emotion_names):
                if current_buffer:
                    full_segment = "".join(current_buffer)
                    if full_segment.strip():
                        segments.append((current_emotion, full_segment))
                    current_buffer = []
                current_emotion = normalized_tag
            else:
                current_buffer.append(" ")
        else:
            current_buffer.append(part)
    if current_buffer:
        full_segment = "".join(current_buffer)
        if full_segment.strip():
            segments.append((current_emotion, full_segment))
    return segments


def parse_speech_action_segments(
    text,
    available_emotion_names,
    supported_sound_tag_names=None,
    *,
    initial_emotion="neutral",
):
    """Split action boundaries while carrying an explicit expression."""

    sound_names = SOUND_TAG_NAMES if supported_sound_tag_names is None else {
        str(name or "").strip().lower()
        for name in supported_sound_tag_names or []
        if str(name or "").strip()
    }
    current_expression = "neutral"
    current_action = None
    current_buffer = []
    parsed = []

    def flush_buffer():
        nonlocal current_action, current_buffer
        segment_text = "".join(current_buffer)
        if segment_text.strip():
            parsed.append((current_expression, current_action, segment_text))
        current_action = None
        current_buffer = []

    for part in re.split(r"(\[[^\]]+\])", str(text or "")):
        if not part:
            continue
        clean_part = part.strip()
        if clean_part.startswith("[") and clean_part.endswith("]"):
            normalized = normalize_bracket_tag(clean_part)
            normalized_name = str(normalized or "").strip().lower()
            if normalized_name in sound_names:
                flush_buffer()
                current_action = normalized_name
                current_buffer.append(part)
            elif is_emotion_tag(normalized, available_emotion_names):
                flush_buffer()
                current_expression = normalized_name
            else:
                current_buffer.append(" ")
        else:
            current_buffer.append(part)
    flush_buffer()

    active = str(initial_emotion or "neutral").strip().lower() or "neutral"
    first_emotion_tag = ""
    for match in re.findall(r"(\[[^\]]+\])", str(text or "")):
        normalized = normalize_bracket_tag(match)
        if is_emotion_tag(normalized, available_emotion_names):
            first_emotion_tag = str(normalized or "").strip().lower()
            break
    carrying = active != "neutral" and first_emotion_tag != "neutral"
    segments = []
    for expression, action, segment_text in parsed:
        clean_expression = str(expression or "neutral").strip().lower() or "neutral"
        if carrying and clean_expression == "neutral":
            clean_expression = active
        else:
            carrying = False
        segments.append((clean_expression, action, segment_text))
    return segments


def get_last_emotion_tag(text, available_emotion_names):
    matches = re.findall(r"(\[[^\]]+\])", text or "")
    for match in reversed(matches):
        normalized_tag = normalize_bracket_tag(match)
        if is_emotion_tag(normalized_tag, available_emotion_names):
            return normalized_tag
    return None


def looks_like_control_tag_prefix(fragment):
    value = str(fragment or "").strip()
    if not value:
        return False
    if len(value) > 32:
        return False
    if re.fullmatch(r"[A-Za-z0-9_-]*", value):
        return True
    value_lower = value.lower()
    for sound_name in SOUND_TAG_NAMES:
        if sound_name.startswith(value_lower):
            return True
    return False
