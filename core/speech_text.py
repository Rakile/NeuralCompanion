"""Speech-facing text cleanup helpers."""

from __future__ import annotations

import re
from typing import Callable


def sanitize_assistant_text_for_speech(
    text: str,
    *,
    preserve_emotion_tags: bool = False,
    strip_visual_tail: Callable[[str], tuple[str, str | None]],
    visual_reply_tag_re,
    normalize_bracket_tag: Callable[[str], str | None],
    is_sound_tag: Callable[[str | None], bool],
    is_emotion_tag: Callable[[str | None], bool],
) -> str:
    value = str(text or "")
    if not value:
        return ""

    protected_bracket_tokens: dict[str, str] = {}
    value, _ignored_visual_prompt = strip_visual_tail(value)
    value = visual_reply_tag_re.sub("", value)

    def _protect_bracket_token(match):
        token = f"BRACKETTOKEN{len(protected_bracket_tokens)}X"
        protected_bracket_tokens[token] = match.group(0)
        return token

    # Remove markdown that sounds awkward when spoken, while optionally keeping
    # runtime control tags needed by downstream playback/avatar systems.
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", value)
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(
        r"\[([^\]\n]+)\]",
        lambda match: (
            _protect_bracket_token(match)
            if is_sound_tag(normalize_bracket_tag(match.group(0)))
            else (
                _protect_bracket_token(match)
                if preserve_emotion_tags and is_emotion_tag(normalize_bracket_tag(match.group(0)))
                else (
                    ""
                    if is_emotion_tag(normalize_bracket_tag(match.group(0)))
                    else _protect_bracket_token(match)
                )
            )
        ),
        value,
    )
    value = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", value)
    value = re.sub(r"(?m)^\s*>\s*", "", value)
    value = re.sub(r"(?m)^\s*[-*+]\s+", "", value)

    # Remove emphasis markers while preserving their contents.
    value = value.replace("**", "")
    value = value.replace("__", "")
    value = re.sub(r"(?<!\[)\*(?!\s)(.+?)(?<!\s)\*(?!\])", r"\1", value)
    value = re.sub(r"(?<!\[)_(?!\s)(.+?)(?<!\s)_(?!\])", r"\1", value)

    for token, original in protected_bracket_tokens.items():
        value = value.replace(token, original)

    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = re.sub(r"[ \t]{2,}", " ", value)
    return value.strip()
