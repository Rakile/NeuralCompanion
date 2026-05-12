from __future__ import annotations

import re
from typing import Any

from addons.audio_story_mode.story_memory import NEEDS_CLARIFICATION


_COMMON_CAPITALIZED = {
    "A",
    "An",
    "And",
    "As",
    "At",
    "But",
    "For",
    "He",
    "Her",
    "His",
    "I",
    "If",
    "In",
    "It",
    "She",
    "So",
    "The",
    "They",
    "This",
    "To",
    "We",
    "When",
    "You",
}
_LOCATION_WORDS = ("room", "house", "street", "forest", "castle", "ship", "station", "city", "village", "cave", "hall", "kitchen")
_PROP_WORDS = ("lantern", "rifle", "gun", "sword", "book", "ring", "key", "phone", "knife", "torch", "bag", "door")
_STYLE_MOOD_WORDS = ("dark", "tense", "quiet", "cold", "warm", "noir", "cinematic", "stormy", "night", "fog", "bright")


def _slug(text: str, *, prefix: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", str(text or "").strip().lower()).strip("_")
    return f"{prefix}_{value[:40]}" if value else f"{prefix}_unknown"


def _sentences(text: str) -> list[str]:
    value = re.sub(r"\s+", " ", str(text or "").strip())
    if not value:
        return []
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", value) if part.strip()]


def _summary(text: str, limit: int = 220) -> str:
    sentence = " ".join(_sentences(text)[:2]) or str(text or "").strip()
    sentence = re.sub(r"\s+", " ", sentence).strip()
    return sentence[:limit].rstrip(" \t\r\n,;:.-")


def _capitalized_names(text: str) -> list[str]:
    candidates = []
    for match in re.finditer(r"\b[A-Z][a-zA-Z']{1,28}\b", str(text or "")):
        name = match.group(0).strip()
        if name in _COMMON_CAPITALIZED:
            continue
        candidates.append(name)
    result = []
    seen = set()
    for name in candidates:
        if name.lower() in seen:
            continue
        result.append(name)
        seen.add(name.lower())
    return result[:6]


def _keyword_hits(text: str, words) -> list[str]:
    lowered = str(text or "").lower()
    return [word for word in words if re.search(rf"\b{re.escape(word)}\b", lowered)]


class StoryAnalyzer:
    """Small fallback analyzer for story-bible mode.

    It intentionally does not invent visual traits. Unknown visual fields remain
    empty or "Needs clarification" so a later explicit transcript detail can win.
    """

    def analyze(self, transcript_text: str, *, chunk_index: int | None = None, timestamp: float | None = None, memory: dict[str, Any] | None = None) -> dict[str, Any]:
        text = str(transcript_text or "").strip()
        names = _capitalized_names(text)
        location_hits = _keyword_hits(text, _LOCATION_WORDS)
        prop_hits = _keyword_hits(text, _PROP_WORDS)
        mood_hits = _keyword_hits(text, _STYLE_MOOD_WORDS)
        characters = {}
        for name in names:
            key = _slug(name, prefix="character")
            characters[key] = {
                "display_name": name,
                "aliases": [name],
                "visual_identity": NEEDS_CLARIFICATION,
                "face": "",
                "hair": "",
                "eyes": "",
                "body": "",
                "clothing": "",
                "unique_markers": "",
                "personality_impression": "",
                "do_not_change": ["face", "age", "hair", "body type", "clothing language", "unique marks"],
                "confidence": 0.35,
                "first_seen_chunk": chunk_index,
                "last_seen_chunk": chunk_index,
            }
        locations = {}
        for word in location_hits[:3]:
            key = _slug(word, prefix="location")
            locations[key] = {
                "display_name": word,
                "visual_description": NEEDS_CLARIFICATION,
                "mood": ", ".join(mood_hits[:3]),
                "recurring_details": [],
                "confidence": 0.3,
            }
        props = {}
        for word in prop_hits[:4]:
            key = _slug(word, prefix="prop")
            props[key] = {
                "display_name": word,
                "visual_description": NEEDS_CLARIFICATION,
                "mood": "",
                "confidence": 0.3,
            }
        style = {}
        if mood_hits:
            style = {
                "global_visual_style": ", ".join(mood_hits[:4]),
                "camera_language": "cinematic audiobook stills",
                "color_palette": "",
                "negative_style_rules": ["no text overlays", "no redesigning recurring characters"],
                "confidence": 0.25,
            }
        scene = {
            "chunk_index": chunk_index,
            "timestamp": timestamp,
            "summary": _summary(text),
            "character_keys": list(characters.keys()),
            "location_key": next(iter(locations.keys()), ""),
            "prop_keys": list(props.keys()),
        }
        return {
            "characters": characters,
            "locations": locations,
            "props": props,
            "style": style,
            "recent_scenes": [scene],
            "scene": scene,
        }
