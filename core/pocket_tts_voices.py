"""Lightweight PocketTTS built-in voice catalog."""

from __future__ import annotations


POCKET_TTS_BUILTIN_VOICE_AUTO = "auto"

POCKET_TTS_DEFAULT_VOICE_BY_LANGUAGE = {
    "en": "alba",
    "english": "alba",
    "english_2026-01": "alba",
    "english_2026-04": "alba",
    "fr": "estelle",
    "french": "estelle",
    "french_24l": "estelle",
    "de": "juergen",
    "german": "juergen",
    "german_24l": "juergen",
    "es": "lola",
    "spanish": "lola",
    "spanish_24l": "lola",
    "pt": "rafael",
    "portuguese": "rafael",
    "portuguese_24l": "rafael",
    "it": "giovanni",
    "italian": "giovanni",
    "italian_24l": "giovanni",
}

POCKET_TTS_BUILTIN_VOICE_CHOICES = (
    ("Auto (language default)", POCKET_TTS_BUILTIN_VOICE_AUTO),
    ("Alba MacKenna", "alba"),
    ("Anna", "anna"),
    ("Azelma", "azelma"),
    ("Bill Boerst", "bill_boerst"),
    ("Caro Davy", "caro_davy"),
    ("Charles", "charles"),
    ("Cosette", "cosette"),
    ("Eponine", "eponine"),
    ("Estelle", "estelle"),
    ("Eve", "eve"),
    ("Fantine", "fantine"),
    ("George", "george"),
    ("Giovanni", "giovanni"),
    ("Jane", "jane"),
    ("Javert", "javert"),
    ("Jean", "jean"),
    ("Juergen", "juergen"),
    ("Lola", "lola"),
    ("Marius", "marius"),
    ("Mary", "mary"),
    ("Michael", "michael"),
    ("Paul", "paul"),
    ("Peter Yearsley", "peter_yearsley"),
    ("Rafael", "rafael"),
    ("Stuart Bell", "stuart_bell"),
    ("Vera", "vera"),
)

_BUILTIN_VOICE_VALUES = {value for _label, value in POCKET_TTS_BUILTIN_VOICE_CHOICES}


def normalize_pocket_tts_builtin_voice(value: str | None) -> str:
    text = str(value or "").strip().lower()
    return text if text in _BUILTIN_VOICE_VALUES else POCKET_TTS_BUILTIN_VOICE_AUTO


def default_pocket_tts_voice_for_language(language: str | None) -> str:
    text = str(language or "").strip().lower()
    return POCKET_TTS_DEFAULT_VOICE_BY_LANGUAGE.get(text, "alba")


def resolve_pocket_tts_builtin_voice(selection: str | None, language: str | None) -> str:
    voice = normalize_pocket_tts_builtin_voice(selection)
    if voice == POCKET_TTS_BUILTIN_VOICE_AUTO:
        return default_pocket_tts_voice_for_language(language)
    return voice
