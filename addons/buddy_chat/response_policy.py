from __future__ import annotations

import re
from typing import Any

from .models import BuddyPersona, normalize_persona_id


GROUP_PHRASES = (
    "both of you",
    "you two",
    "all of you",
    "everyone",
    "what do you both",
)
RECENCY_PENALTIES = (60, 35, 20)
BUDDY_PASS_TOKEN = "[[BUDDY_PASS]]"


def asks_group(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return any(phrase in lowered for phrase in GROUP_PHRASES)


def recent_speaker_ids(
    history: list[dict[str, Any]],
    personas: list[BuddyPersona],
) -> list[str]:
    lookup = {
        str(item.display_name or "").strip().lower(): normalize_persona_id(item.id)
        for item in personas
        if str(item.display_name or "").strip()
    }
    found: list[str] = []
    for message in reversed(list(history or [])):
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").strip().lower() != "assistant":
            continue
        labels = re.findall(
            r"(?m)^\s*\[([^\]]{1,80})\]",
            str(message.get("content") or ""),
        )
        for label in reversed(labels):
            persona_id = lookup.get(label.strip().lower())
            if persona_id and persona_id not in found:
                found.append(persona_id)
        if len(found) >= len(RECENCY_PENALTIES):
            break
    return found


def select_speakers(
    *,
    personas: list[BuddyPersona],
    user_text: str,
    max_speakers: int,
    allow_buddy_to_buddy: bool,
    second_speaker_due: bool,
    turn_index: int,
    history: list[dict[str, Any]],
) -> list[BuddyPersona]:
    enabled = [item for item in personas if bool(item.enabled)]
    if not enabled:
        return []

    limit = max(1, min(int(max_speakers or 1), len(enabled)))
    lowered = str(user_text or "").lower()
    mentioned = [
        item
        for item in enabled
        if _name_mentioned(lowered, item.display_name)
        or _name_mentioned(lowered, item.id)
    ]
    if mentioned:
        return mentioned[:limit]

    recent = recent_speaker_ids(history, enabled)
    rotation_start = int(turn_index or 0) % len(enabled)

    def ranking(item: BuddyPersona) -> tuple[int, int, int]:
        index = enabled.index(item)
        weight = (
            int(item.behavior.participation_weight)
            if item.behavior is not None
            else 50
        )
        persona_id = normalize_persona_id(item.id)
        penalty = (
            RECENCY_PENALTIES[recent.index(persona_id)]
            if persona_id in recent
            else 0
        )
        rotation_distance = (index - rotation_start) % len(enabled)
        return (weight - penalty, -rotation_distance, -index)

    ranked = sorted(enabled, key=ranking, reverse=True)
    multiple_allowed = bool(allow_buddy_to_buddy) and limit > 1
    if asks_group(lowered) and multiple_allowed:
        candidate_count = limit
    elif bool(second_speaker_due) and multiple_allowed:
        candidate_count = min(2, limit)
    else:
        candidate_count = 1
    return ranked[:candidate_count]


def normalize_persona_reply(
    persona: BuddyPersona,
    reply: str,
    personas: list[BuddyPersona],
) -> str:
    text = str(reply or "").strip()
    if not text or text.upper() == BUDDY_PASS_TOKEN:
        return ""

    known_labels = {
        str(item.display_name or "").strip().lower()
        for item in personas
        if str(item.display_name or "").strip()
    }
    first = re.match(r"^\s*\[([^\]]{1,80})\]\s*(.*)$", text, flags=re.DOTALL)
    if first:
        first_label = first.group(1).strip().lower()
        if first_label not in known_labels:
            return ""
        text = first.group(2).strip()
    if not text:
        return ""

    remaining_labels = [
        match.group(1).strip().lower()
        for match in re.finditer(r"\[([^\]]{1,80})\]", text)
    ]
    if any(label in known_labels for label in remaining_labels):
        return ""
    return f"[{persona.display_name}] {text}".strip()


def is_repetitive_secondary(previous: list[str], candidate: str) -> bool:
    candidate_tokens = _reply_tokens(candidate)
    if len(candidate_tokens) < 6:
        return False
    for value in list(previous or []):
        prior_tokens = _reply_tokens(value)
        union = candidate_tokens | prior_tokens
        if union and len(candidate_tokens & prior_tokens) / len(union) >= 0.72:
            return True
    return False


def _reply_tokens(value: str) -> set[str]:
    text = re.sub(r"^\s*\[[^\]]{1,80}\]\s*", "", str(value or "").strip())
    return set(re.findall(r"[a-z0-9']+", text.lower()))


def _name_mentioned(text: str, name: str) -> bool:
    clean = re.escape(str(name or "").strip().lower())
    return bool(clean and re.search(rf"(?<![a-z0-9_]){clean}(?![a-z0-9_])", text))


__all__ = [
    "BUDDY_PASS_TOKEN",
    "asks_group",
    "is_repetitive_secondary",
    "normalize_persona_reply",
    "recent_speaker_ids",
    "select_speakers",
]
