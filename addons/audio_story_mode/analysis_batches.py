"""Bounded, provider-independent helpers for Audio Story LLM analysis."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ContinuityContextLimits:
    characters: int = 12
    locations: int = 8
    props: int = 8
    recent_scenes: int = 4


@dataclass(frozen=True)
class StoryAnalysisBatch:
    batch_index: int
    chunk_start_index: int
    chunks: tuple[dict[str, object], ...]
    serialized_input_characters: int


def _serialized_chunk_characters(chunks: Sequence[Mapping[str, object]]) -> int:
    return len(
        json.dumps(
            {"chunks": list(chunks)},
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def _fit_single_chunk(
    chunk: Mapping[str, object],
    input_character_budget: int,
) -> dict[str, object]:
    fitted = copy.deepcopy(dict(chunk))
    text = str(fitted.get("text") or "")
    if _serialized_chunk_characters((fitted,)) <= input_character_budget:
        return fitted
    low = 0
    high = len(text)
    while low < high:
        candidate_length = (low + high + 1) // 2
        fitted["text"] = text[:candidate_length].rstrip()
        if _serialized_chunk_characters((fitted,)) <= input_character_budget:
            low = candidate_length
        else:
            high = candidate_length - 1
    fitted["text"] = text[:low].rstrip()
    if _serialized_chunk_characters((fitted,)) > input_character_budget:
        raise ValueError("Audio Story analysis chunk metadata exceeds its input budget")
    return fitted


def partition_analysis_chunks(
    image_chunks: Sequence[Mapping[str, object]],
    *,
    max_chunks: int = 8,
    input_character_budget: int = 12_000,
) -> tuple[StoryAnalysisBatch, ...]:
    """Copy and partition chunks without exceeding either configured bound."""
    chunk_limit = max(1, int(max_chunks))
    character_limit = max(256, int(input_character_budget))
    completed: list[StoryAnalysisBatch] = []
    current: list[dict[str, object]] = []
    current_start_index = 0

    def finish() -> None:
        nonlocal current
        if not current:
            return
        completed.append(
            StoryAnalysisBatch(
                batch_index=len(completed),
                chunk_start_index=current_start_index,
                chunks=tuple(current),
                serialized_input_characters=_serialized_chunk_characters(current),
            )
        )
        current = []

    for source_index, value in enumerate(image_chunks):
        if not isinstance(value, Mapping):
            continue
        indexed_value = copy.deepcopy(dict(value))
        indexed_value.setdefault("chunk_index", source_index)
        chunk = _fit_single_chunk(indexed_value, character_limit)
        if not current:
            current_start_index = source_index
        candidate = [*current, chunk]
        if current and (
            len(candidate) > chunk_limit
            or _serialized_chunk_characters(candidate) > character_limit
        ):
            finish()
            current_start_index = source_index
            candidate = [chunk]
        current = candidate
    finish()
    return tuple(completed)


def _entity_search_values(entity_id: str, entry: Mapping[str, object]) -> tuple[str, ...]:
    aliases = entry.get("aliases")
    alias_values = (
        aliases
        if isinstance(aliases, Sequence)
        and not isinstance(aliases, (str, bytes, bytearray))
        else ()
    )
    values = (
        entity_id,
        entry.get("label"),
        entry.get("display_name"),
        *alias_values,
    )
    return tuple(
        text.casefold()
        for text in (str(value or "").strip() for value in values)
        if text
    )


def _numeric_sort_value(value: object, default: float = -1.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bounded_entities(
    source: object,
    *,
    haystack: str,
    limit: int,
) -> dict[str, object]:
    entities = source if isinstance(source, Mapping) else {}
    matching: list[tuple[str, dict[str, object]]] = []
    fallback: list[tuple[str, dict[str, object]]] = []
    for raw_id, raw_entry in entities.items():
        if not isinstance(raw_entry, Mapping):
            continue
        entity_id = str(raw_id or "").strip()
        if not entity_id:
            continue
        entry = copy.deepcopy(dict(raw_entry))
        target = (entity_id, entry)
        if any(value and value in haystack for value in _entity_search_values(entity_id, entry)):
            matching.append(target)
        else:
            fallback.append(target)

    rank = lambda item: (
        -_numeric_sort_value(item[1].get("last_seen_chunk")),
        -_numeric_sort_value(item[1].get("confidence"), 0.0),
        item[0],
    )
    matching.sort(key=rank)
    fallback.sort(key=rank)
    selected = [*matching, *fallback][: max(0, int(limit))]
    return {entity_id: entry for entity_id, entry in selected}


def compact_continuity_context(
    memory: Mapping[str, object],
    batch_chunks: Sequence[Mapping[str, object]],
    *,
    limits: ContinuityContextLimits = ContinuityContextLimits(),
) -> dict[str, object]:
    """Return the relevant bounded view of authoritative project continuity."""
    source = memory if isinstance(memory, Mapping) else {}
    text_parts: list[str] = []
    for chunk in batch_chunks:
        if not isinstance(chunk, Mapping):
            continue
        text_parts.append(str(chunk.get("text") or ""))
        for field in (
            "active_character_ids",
            "character_ids",
            "location_id",
            "prop_ids",
        ):
            value = chunk.get(field)
            if isinstance(value, Sequence) and not isinstance(
                value, (str, bytes, bytearray)
            ):
                text_parts.extend(str(item or "") for item in value)
            elif value:
                text_parts.append(str(value))
    recent = source.get("recent_scenes")
    recent_values = (
        [
            copy.deepcopy(dict(item))
            for item in recent
            if isinstance(item, Mapping)
        ]
        if isinstance(recent, Sequence)
        and not isinstance(recent, (str, bytes, bytearray))
        else []
    )
    for scene in recent_values:
        text_parts.append(
            json.dumps(scene, ensure_ascii=False, separators=(",", ":"))
        )
    haystack = " ".join(text_parts).casefold()
    return {
        "characters": _bounded_entities(
            source.get("characters"),
            haystack=haystack,
            limit=limits.characters,
        ),
        "locations": _bounded_entities(
            source.get("locations"),
            haystack=haystack,
            limit=limits.locations,
        ),
        "props": _bounded_entities(
            source.get("props"),
            haystack=haystack,
            limit=limits.props,
        ),
        "style": copy.deepcopy(
            dict(source.get("style") or {})
            if isinstance(source.get("style"), Mapping)
            else {}
        ),
        "recent_scenes": recent_values[-max(0, int(limits.recent_scenes)) :],
    }


def _payload_characters(payload: Mapping[str, object]) -> int:
    return len(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def _longest_reducible_text(payload: dict[str, object]) -> tuple[dict, str] | None:
    candidates: list[tuple[int, dict, str]] = []
    chunks = payload.get("chunks")
    if isinstance(chunks, list):
        for chunk in chunks:
            if isinstance(chunk, dict):
                text = str(chunk.get("text") or "")
                if len(text) > 120:
                    candidates.append((len(text), chunk, "text"))
    style_guide = str(payload.get("current_visual_style_guide") or "")
    if len(style_guide) > 120:
        candidates.append((len(style_guide), payload, "current_visual_style_guide"))
    continuity = payload.get("committed_story_bible")
    if isinstance(continuity, dict):
        style = continuity.get("style")
        if isinstance(style, dict):
            for key, value in style.items():
                text = str(value or "")
                if len(text) > 120:
                    candidates.append((len(text), style, str(key)))
        for section_name in ("characters", "locations", "props"):
            section = continuity.get(section_name)
            if not isinstance(section, dict):
                continue
            for entry in section.values():
                if not isinstance(entry, dict):
                    continue
                for key, value in entry.items():
                    if isinstance(value, str) and len(value) > 120:
                        candidates.append((len(value), entry, str(key)))
    if not candidates:
        return None
    _length, owner, key = max(candidates, key=lambda item: item[0])
    return owner, key


def bounded_story_prompt_payload(
    *,
    batch: StoryAnalysisBatch,
    continuity_context: Mapping[str, object],
    story_style_guide: str,
    continuity_strength: float,
    max_serialized_characters: int = 12_000,
) -> dict[str, object]:
    """Build a bounded provider payload while preserving chunks and context."""
    limit = max(1_024, int(max_serialized_characters))
    payload: dict[str, object] = {
        "task": "Analyze audiobook transcript chunks for visual continuity.",
        "continuity_strength": round(float(continuity_strength), 3),
        "current_visual_style_guide": str(story_style_guide or "").strip(),
        "chunks": [copy.deepcopy(dict(item)) for item in batch.chunks],
        "committed_story_bible": copy.deepcopy(dict(continuity_context or {})),
    }
    while _payload_characters(payload) > limit:
        reducible = _longest_reducible_text(payload)
        if reducible is not None:
            owner, key = reducible
            text = str(owner.get(key) or "")
            owner[key] = text[: max(120, len(text) // 2)].rstrip()
            continue
        continuity = payload.get("committed_story_bible")
        if isinstance(continuity, dict):
            recent = continuity.get("recent_scenes")
            if isinstance(recent, list) and recent:
                recent.pop(0)
                continue
            removed_entity = False
            for section_name in ("props", "locations", "characters"):
                section = continuity.get(section_name)
                if isinstance(section, dict) and section:
                    section.pop(next(reversed(section)))
                    removed_entity = True
                    break
            if removed_entity:
                continue
        raise ValueError("Audio Story fixed analysis prompt data exceeds its limit")
    return payload
