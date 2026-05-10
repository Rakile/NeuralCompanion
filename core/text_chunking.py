"""Reusable text chunking helpers for speech and avatar pipelines."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Callable


PUNCTUATION_SPLIT_STRONGLY = {".", "!", "?"}
PUNCTUATION_SPLIT_WEAKLY = {",", ";", ":"}
PUNCTUATION_ALL = PUNCTUATION_SPLIT_STRONGLY.union(PUNCTUATION_SPLIT_WEAKLY)


def _fallback_sentence_split(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"(?<=[.!?])\s+", str(text or "")) if item.strip()]


@lru_cache(maxsize=1024)
def find_intelligent_split_point(text_segment: str, target_chars: int, max_chars: int, *, min_chunk_size: int = 10) -> int:
    try:
        segment_len = len(text_segment)
        if segment_len <= max_chars:
            return segment_len
        search_end = min(segment_len - 1, max_chars - 1)
        search_start = max(0, target_chars - (max_chars - target_chars) // 2)
        search_start = max(0, min(search_start, search_end - 1))
        for i in range(search_end, search_start - 1, -1):
            if text_segment[i] in PUNCTUATION_SPLIT_STRONGLY:
                if i + 1 < segment_len and text_segment[i + 1].isspace():
                    return i + 1
                elif i == segment_len - 1:
                    return i + 1
        for i in range(search_end, search_start - 1, -1):
            if text_segment[i] in PUNCTUATION_SPLIT_WEAKLY:
                if i + 1 < segment_len and text_segment[i + 1].isspace():
                    return i + 1
                elif i == segment_len - 1:
                    return i + 1
        whitespace_end = min(segment_len - 1, max_chars - 1)
        whitespace_start = max(0, min_chunk_size - 1)
        if whitespace_end > whitespace_start:
            space_pos = text_segment.rfind(" ", whitespace_start, whitespace_end + 1)
            if space_pos != -1:
                return space_pos + 1
        return min(segment_len, max_chars)
    except Exception:
        return min(len(text_segment), max_chars)


def chunk_text(
    long_text: str,
    target_chars: int,
    max_chars: int,
    *,
    min_chunk_size: int = 10,
    sentence_splitter: Callable[[str], list[str]] | None = None,
    logger=print,
) -> list[str]:
    try:
        if not long_text or not long_text.strip():
            return []
        long_text = re.sub(r"\s+", " ", long_text).strip()
        if not (min_chunk_size <= target_chars < max_chars):
            return [long_text[i:i + max_chars] for i in range(0, len(long_text), max_chars)]
        splitter = sentence_splitter or _fallback_sentence_split
        sentences = splitter(long_text)
        if not sentences:
            return [long_text] if len(long_text) <= max_chars else [long_text[i:i + max_chars] for i in range(0, len(long_text), max_chars)]
        chunks = []
        current_buffer = []
        current_buffer_length = 0
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            sentence_length = len(sentence)
            if sentence_length > max_chars:
                if current_buffer:
                    chunks.append(" ".join(current_buffer).strip())
                    current_buffer = []
                    current_buffer_length = 0
                temp_segment_start_idx = 0
                while temp_segment_start_idx < sentence_length:
                    remaining_sentence_part = sentence[temp_segment_start_idx:]
                    if not remaining_sentence_part.strip():
                        break
                    if len(remaining_sentence_part) <= max_chars:
                        chunks.append(remaining_sentence_part.strip())
                        break
                    split_at = find_intelligent_split_point(
                        remaining_sentence_part,
                        target_chars,
                        max_chars,
                        min_chunk_size=min_chunk_size,
                    )
                    chunk_to_add = remaining_sentence_part[:split_at].strip()
                    if chunk_to_add:
                        chunks.append(chunk_to_add)
                    temp_segment_start_idx += split_at
                    while temp_segment_start_idx < sentence_length and sentence[temp_segment_start_idx].isspace():
                        temp_segment_start_idx += 1
            else:
                if current_buffer_length + (1 if current_buffer else 0) + sentence_length > max_chars:
                    if current_buffer:
                        chunks.append(" ".join(current_buffer).strip())
                    current_buffer = [sentence]
                    current_buffer_length = sentence_length
                else:
                    current_buffer.append(sentence)
                    current_buffer_length += (1 if len(current_buffer) > 1 else 0) + sentence_length
                if current_buffer_length >= target_chars:
                    chunks.append(" ".join(current_buffer).strip())
                    current_buffer = []
                    current_buffer_length = 0
        if current_buffer:
            chunks.append(" ".join(current_buffer).strip())
        valid_chunks = [chunk for chunk in chunks if min_chunk_size <= len(chunk.strip()) <= max_chars]
        if not valid_chunks and long_text:
            if min_chunk_size <= len(long_text) <= max_chars:
                return [long_text]
        return valid_chunks
    except Exception as exc:
        logger(f"Error chunking text: {exc}")
        try:
            return [long_text[i:i + max_chars] for i in range(0, len(long_text), max_chars) if long_text[i:i + max_chars].strip()]
        except Exception:
            return []


def progressive_chunk_text(
    long_text: str,
    *,
    start_chunk_index: int = 0,
    limit_getter: Callable[[int], tuple[int, int]],
    min_chunk_size: int = 10,
    sentence_splitter: Callable[[str], list[str]] | None = None,
    logger=print,
) -> list[str]:
    try:
        if not long_text or not long_text.strip():
            return []
        remaining_text = re.sub(r"\s+", " ", long_text).strip()
        chunks = []
        local_index = 0
        while remaining_text:
            target_chars, max_chars = limit_getter(start_chunk_index + local_index)
            if len(remaining_text) <= max_chars:
                final_chunk = remaining_text.strip()
                if final_chunk:
                    chunks.append(final_chunk)
                break

            split_at = find_intelligent_split_point(
                remaining_text,
                target_chars,
                max_chars,
                min_chunk_size=min_chunk_size,
            )
            chunk_text_value = remaining_text[:split_at].strip()
            if chunk_text_value:
                chunks.append(chunk_text_value)
            remaining_text = remaining_text[split_at:].lstrip()
            local_index += 1

        return [chunk for chunk in chunks if len(chunk) >= min_chunk_size]
    except Exception as exc:
        logger(f"Error progressive chunking text: {exc}")
        target_chars, max_chars = limit_getter(start_chunk_index)
        return chunk_text(
            long_text,
            target_chars,
            max_chars,
            min_chunk_size=min_chunk_size,
            sentence_splitter=sentence_splitter,
            logger=logger,
        )
