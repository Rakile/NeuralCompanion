"""Speech-facing text cleanup helpers."""

from __future__ import annotations

import re
from typing import Any, Callable

from core import text_chunking


def resolve_addon_voice_stream_policy(results) -> dict[str, bool]:
    requires_full_text = False
    preserve_voice_labels = False
    for result in list(results or []):
        if not isinstance(result, dict):
            continue
        item_requires_full_text = bool(result.get("requires_full_text", False))
        requires_full_text = requires_full_text or item_requires_full_text
        preserve_voice_labels = (
            preserve_voice_labels
            or item_requires_full_text
            or bool(result.get("preserve_voice_labels", False))
        )
    return {
        "requires_full_text": requires_full_text,
        "preserve_voice_labels": preserve_voice_labels,
    }


def prepare_stream_tts_chunk(
    text: str,
    *,
    preserve_voice_labels: bool,
    sanitizer: Callable[[str], str],
) -> str:
    value = str(text or "")
    if preserve_voice_labels:
        return value.strip()
    return str(sanitizer(value) or "").strip()


def join_stream_tts_chunks(chunks) -> str:
    return "\n".join(str(chunk or "").strip() for chunk in chunks if str(chunk or "").strip()).strip()


def chunk_voice_segments_for_fast_start(
    segments,
    *,
    first_target_chars: int,
    first_max_chars: int,
    target_chars: int,
    max_chars: int,
    min_chunk_size: int = 10,
) -> list[dict[str, Any]]:
    min_size = max(1, int(min_chunk_size or 1))
    steady_target = max(min_size, int(target_chars or min_size))
    steady_max = max(steady_target + 1, int(max_chars or steady_target + 1))
    first_target = max(min_size, min(int(first_target_chars or min_size), steady_target))
    first_max = max(first_target + 1, min(int(first_max_chars or first_target + 1), steady_max))

    def _limits(chunk_index: int) -> tuple[int, int]:
        if chunk_index == 0:
            return first_target, first_max
        return steady_target, steady_max

    prepared: list[dict[str, Any]] = []
    for raw_segment in list(segments or []):
        if isinstance(raw_segment, dict):
            template = dict(raw_segment)
            value = str(raw_segment.get("text", "") or "")
        else:
            template = {}
            value = str(raw_segment or "")
        value = re.sub(r"\s+", " ", value).strip()
        if not value:
            continue

        chunks = text_chunking.progressive_chunk_text(
            value,
            start_chunk_index=0,
            limit_getter=_limits,
            min_chunk_size=min_size,
            logger=lambda _message: None,
        )
        if not chunks:
            chunks = [value]
        for chunk in chunks:
            item = dict(template)
            item["text"] = str(chunk or "").strip()
            if item["text"]:
                prepared.append(item)
    return prepared


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
                else " "
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
