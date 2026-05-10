"""Reusable bracket tag parsing for speech, emotion, and visual directives."""

from __future__ import annotations

import re


SOUND_TAGS = {
    "[clear throat]", "[sigh]", "[shush]", "[groan]",
    "[sniff]", "[gasp]", "[chuckle]", "[laugh]"
}
SOUND_TAG_NAMES = {tag.strip()[1:-1].strip().lower() for tag in SOUND_TAGS}
CONTROL_TAG_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")


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
    return normalized in set(str(name or "").strip().lower() for name in available_emotion_names or [])


def parse_text_segments(text, available_emotion_names):
    """Split reply text into emotion-tagged speech segments."""
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
            if is_sound_tag(normalized_tag):
                current_buffer.append(part)
            elif is_emotion_tag(normalized_tag, available_emotion_names):
                if current_buffer:
                    full_segment = "".join(current_buffer)
                    if full_segment.strip():
                        segments.append((current_emotion, full_segment))
                    current_buffer = []
                current_emotion = normalized_tag
            else:
                current_buffer.append(part)
        else:
            current_buffer.append(part)
    if current_buffer:
        full_segment = "".join(current_buffer)
        if full_segment.strip():
            segments.append((current_emotion, full_segment))
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

