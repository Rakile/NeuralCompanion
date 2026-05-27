from __future__ import annotations

import re
from typing import Iterable


AUDIO_TYPES = ("Auto", "Music", "Ambience", "FX", "Stinger")


_VOCAL_WORDS = {
    "choir",
    "chant",
    "chanting",
    "singer",
    "singing",
    "vocal",
    "vocals",
    "voice",
    "voices",
    "lyrics",
    "lyrical",
}


def create_audio_prompt(description: str, audio_type: str = "Auto", variant: str = "") -> str:
    clean = _clean_description(description)
    if not clean:
        return ""
    resolved_type = _resolve_type(clean, audio_type, variant)
    variant_terms = _variant_terms(variant)
    if resolved_type == "Music":
        parts = _music_prompt(clean)
    elif resolved_type == "FX":
        parts = _fx_prompt(clean)
    elif resolved_type == "Stinger":
        parts = _stinger_prompt(clean)
    else:
        parts = _ambience_prompt(clean)
    parts.extend(variant_terms)
    if resolved_type in {"Music", "Ambience", "Stinger"} and not _requests_vocals(clean):
        parts.append("no vocals")
    return ", ".join(_dedupe(parts))


def infer_audio_type(description: str) -> str:
    text = _clean_description(description).lower()
    if not text:
        return "Auto"
    if _has_any(text, ("ambience", "ambient", "soundscape", "environment", "room tone", "rain city")):
        return "Ambience"
    if _has_any(text, ("stinger", "sting", "transition", "reveal", "dramatic hit", "impact cue")):
        return "Stinger"
    if _has_any(text, ("sound effect", "sfx", "fx", "effect", "portal", "spell", "charging", "door", "explosion", "laser", "whoosh", "hit")):
        return "FX"
    if _has_any(text, ("music", "song", "theme", "score", "battle", "boss", "combat", "orchestral", "synthwave")):
        return "Music"
    if _has_any(text, ("forest", "cave", "tavern", "city", "street", "dungeon", "ocean", "wind", "storm", "night")):
        return "Ambience"
    return "Ambience"


def _resolve_type(description: str, audio_type: str, variant: str = "") -> str:
    if str(variant or "").strip().lower() in {"ambience", "ambience variation"}:
        return "Ambience"
    wanted = str(audio_type or "Auto").strip().lower()
    for item in AUDIO_TYPES:
        if item.lower() == wanted:
            return infer_audio_type(description) if item == "Auto" else item
    return infer_audio_type(description)


def _music_prompt(description: str) -> list[str]:
    text = description.lower()
    style = _music_style(text)
    parts = [
        f"{style} music",
        _instrument_hint(text),
        _mood_hint(text),
        "cinematic energy",
        _tension_hint(text),
        "emotional tone",
        "seamless loop",
    ]
    if "dragon" in text:
        parts.insert(1, "dragon encounter atmosphere")
    if "boss" in text:
        parts.insert(1, "final boss battle energy")
    return parts


def _ambience_prompt(description: str) -> list[str]:
    text = description.lower()
    environment = _environment_hint(text)
    parts = [
        f"{environment} ambience",
        *_environment_details(text),
        _mood_hint(text),
        "cinematic atmosphere",
        "realistic environmental soundscape",
        "layered textures",
        _tension_hint(text),
        "seamless loop",
    ]
    return parts


def _fx_prompt(description: str) -> list[str]:
    text = description.lower()
    if "portal" in text:
        return [
            "magical portal activation sound effect",
            "mystical energy surge",
            "shimmering resonance",
            "fantasy arcane transition",
            "isolated cinematic sound",
        ]
    if "spell" in text or "magic" in text:
        return [
            "magic spell charging sound effect",
            "focused arcane energy build",
            "shimmering resonance",
            "short isolated fantasy sound",
            "punchy cinematic finish",
        ]
    if "door" in text:
        return [
            "door opening sound effect",
            "close detailed texture",
            "subtle tension",
            "isolated cinematic sound",
        ]
    return [
        f"{_clean_fx_subject(description)} sound effect",
        "short isolated sound",
        "specific texture",
        "punchy cinematic detail",
    ]


def _stinger_prompt(description: str) -> list[str]:
    text = description.lower()
    parts = [
        f"{_clean_fx_subject(description)} stinger",
        "short dramatic transition",
        "cinematic impact",
        _tension_hint(text),
        "clean ending",
    ]
    return parts


def _music_style(text: str) -> str:
    if _has_any(text, ("dragon", "fantasy", "boss", "battle", "combat")):
        return "epic fantasy battle"
    if _has_any(text, ("cyberpunk", "neon", "synth", "rain city")):
        return "cyberpunk synthwave"
    if _has_any(text, ("tavern", "inn")):
        return "peaceful fantasy tavern"
    if _has_any(text, ("horror", "dark", "scary", "haunted")):
        return "dark cinematic horror"
    if _has_any(text, ("peaceful", "calm", "gentle", "soft")):
        return "peaceful cinematic"
    return "cinematic instrumental"


def _instrument_hint(text: str) -> str:
    if _has_any(text, ("dragon", "fantasy", "boss", "battle", "combat")):
        return "massive orchestral drums, aggressive strings, heroic brass"
    if _has_any(text, ("cyberpunk", "neon", "synth")):
        return "analog synths, pulsing bass, metallic percussion"
    if _has_any(text, ("tavern", "inn")):
        return "lute, fiddle, soft hand drums, warm room tone"
    if _has_any(text, ("peaceful", "calm", "gentle", "soft")):
        return "soft strings, gentle piano, warm pads"
    if _has_any(text, ("horror", "dark", "scary", "haunted")):
        return "low drones, sparse strings, distant percussion"
    return "cinematic drums, textured pads, melodic instrumental layers"


def _environment_hint(text: str) -> str:
    if "forest" in text:
        return "dark fantasy forest" if _has_any(text, ("dark", "hunting", "hunt", "creature")) else "forest"
    if "cave" in text:
        return "dark cave"
    if _has_any(text, ("cyberpunk", "rain city", "city", "neon")):
        return "cyberpunk rain city"
    if _has_any(text, ("tavern", "inn")):
        return "peaceful fantasy tavern"
    if "dungeon" in text:
        return "ancient dungeon"
    if _has_any(text, ("ocean", "sea", "shore")):
        return "coastal ocean"
    if _has_any(text, ("storm", "rain", "thunder")):
        return "stormy weather"
    return _clean_fx_subject(text)


def _environment_details(text: str) -> list[str]:
    details: list[str] = []
    if "forest" in text:
        details.extend(["distant creature movement", "subtle branches cracking"])
    if "cave" in text:
        details.extend(["distant water drops", "low stone resonance", "deep creature echoes"])
    if _has_any(text, ("cyberpunk", "rain city", "city", "neon")):
        details.extend(["neon rain texture", "distant traffic", "soft electrical hum"])
    if _has_any(text, ("tavern", "inn")):
        details.extend(["fireplace crackle", "wooden room tone", "soft background crowd texture"])
    if _has_any(text, ("storm", "rain", "thunder")):
        details.extend(["layered rain", "distant thunder", "wet air movement"])
    if not details:
        details.append("detailed environmental textures")
    return details[:5]


def _mood_hint(text: str) -> str:
    if _has_any(text, ("hunting", "hunt", "danger", "boss", "battle", "combat", "dark", "horror")):
        return "high tension mood"
    if _has_any(text, ("peaceful", "calm", "gentle", "safe", "tavern")):
        return "warm calm mood"
    if _has_any(text, ("sad", "lonely", "melancholy")):
        return "melancholic mood"
    if _has_any(text, ("epic", "heroic", "dragon")):
        return "heroic dramatic mood"
    return "immersive mood"


def _tension_hint(text: str) -> str:
    if _has_any(text, ("hunting", "hunt", "dark", "horror", "nearby")):
        return "slow tension build"
    if _has_any(text, ("boss", "battle", "combat", "dragon", "action")):
        return "high tension"
    if _has_any(text, ("peaceful", "calm", "gentle")):
        return "slow gentle pacing"
    return "controlled cinematic pacing"


def _variant_terms(variant: str) -> list[str]:
    key = str(variant or "").strip().lower()
    if key in {"", "default"}:
        return []
    if key in {"ambience", "ambience variation"}:
        return ["environment-first mix", "minimal musical elements"]
    if key in {"horror", "horror version"}:
        return ["darker horror tone", "low unease", "subtle dread"]
    if key in {"calmer", "calmer version"}:
        return ["gentler pacing", "softer dynamics", "reduced tension"]
    if key in {"action", "action version"}:
        return ["faster pacing", "more impact", "rising action tension"]
    return [key]


def _clean_description(description: str) -> str:
    text = re.sub(r"\s+", " ", str(description or "").strip())
    return text.strip(" \t\r\n,;:.")


def _clean_fx_subject(description: str) -> str:
    text = _clean_description(description).lower()
    text = re.sub(r"\b(sound|audio|effect|sfx|fx|prompt|music|ambience|ambient)\b", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ,;:.")
    return text or "cinematic audio"


def _requests_vocals(description: str) -> bool:
    words = set(re.findall(r"[a-zA-Z]+", description.lower()))
    return bool(words & _VOCAL_WORDS)


def _has_any(text: str, needles: Iterable[str]) -> bool:
    return any(needle in text for needle in needles)


def _dedupe(parts: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    clean_parts: list[str] = []
    for part in parts:
        clean = re.sub(r"\s+", " ", str(part or "").strip(" \t\r\n,;:."))
        key = clean.lower()
        if clean and key not in seen:
            clean_parts.append(clean)
            seen.add(key)
    return clean_parts
