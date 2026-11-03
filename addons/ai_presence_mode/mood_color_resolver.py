from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class MoodColors:
    moodName: str
    primaryColor: str
    secondaryColor: str
    accentColor: str
    glowColor: str
    backgroundColor: str
    pulseSpeedMultiplier: float = 1.0
    glowIntensityMultiplier: float = 1.0
    particleIntensityMultiplier: float = 1.0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


MOOD_COLOR_PRESETS: dict[str, MoodColors] = {
    "neutral": MoodColors("neutral", "#38bdf8", "#22d3ee", "#a78bfa", "#67e8f9", "#030712", 1.0, 1.0, 1.0),
    "happy": MoodColors("happy", "#facc15", "#fde68a", "#fb923c", "#fef3c7", "#111827", 1.12, 1.12, 1.08),
    "sad": MoodColors("sad", "#2563eb", "#7c3aed", "#93c5fd", "#60a5fa", "#020617", 0.82, 0.72, 0.68),
    "angry": MoodColors("angry", "#ef4444", "#f97316", "#facc15", "#fb7185", "#12080a", 1.18, 1.24, 0.90),
    "calm": MoodColors("calm", "#14b8a6", "#86efac", "#67e8f9", "#99f6e4", "#031014", 0.76, 0.78, 0.58),
    "curious": MoodColors("curious", "#22d3ee", "#a78bfa", "#f0abfc", "#c084fc", "#06111f", 1.05, 1.0, 1.16),
    "excited": MoodColors("excited", "#fb7185", "#f97316", "#38bdf8", "#f0abfc", "#140a16", 1.28, 1.22, 1.22),
    "tension": MoodColors("tension", "#581c87", "#991b1b", "#f87171", "#7c2d12", "#08030d", 0.94, 0.86, 0.72),
    "fear": MoodColors("fear", "#581c87", "#991b1b", "#f87171", "#7c2d12", "#08030d", 0.94, 0.86, 0.72),
    "story": MoodColors("story", "#f59e0b", "#7c3aed", "#f5d0fe", "#fbbf24", "#100816", 1.02, 1.08, 0.96),
    "fantasy": MoodColors("fantasy", "#f59e0b", "#7c3aed", "#f5d0fe", "#fbbf24", "#100816", 1.02, 1.08, 0.96),
    "focus": MoodColors("focus", "#38bdf8", "#14b8a6", "#a78bfa", "#67e8f9", "#030b16", 0.88, 0.88, 0.74),
    "dark": MoodColors("dark", "#4c1d95", "#0f172a", "#38bdf8", "#7c3aed", "#020617", 0.86, 0.72, 0.62),
    "epic": MoodColors("epic", "#f59e0b", "#ef4444", "#38bdf8", "#fef3c7", "#10060a", 1.18, 1.16, 1.04),
    "energetic": MoodColors("energetic", "#fb7185", "#f97316", "#38bdf8", "#f0abfc", "#140a16", 1.24, 1.18, 1.18),
}


ALIASES = {
    "fear / tension": "tension",
    "afraid": "fear",
    "scared": "fear",
    "tense": "tension",
    "magic": "fantasy",
    "magical": "fantasy",
    "adventure": "story",
    "joy": "happy",
    "joyful": "happy",
    "pleased": "happy",
    "amused": "happy",
    "playful": "happy",
    "warm": "happy",
    "romantic": "happy",
    "loving": "happy",
    "melancholy": "sad",
    "lonely": "sad",
    "hurt": "sad",
    "grief": "sad",
    "relaxed": "calm",
    "peaceful": "calm",
    "soft": "calm",
    "shy": "curious",
    "bashful": "curious",
    "surprised": "excited",
    "surprise": "excited",
    "eager": "excited",
    "alert": "focus",
    "focused": "focus",
    "confident": "focus",
    "serious": "focus",
    "stern": "tension",
    "anxious": "tension",
    "worried": "tension",
    "danger": "tension",
    "sinister": "dark",
    "mysterious": "dark",
    "brooding": "dark",
    "heroic": "epic",
    "triumphant": "epic",
    "urgent": "energetic",
}


def normalize_mood_name(value) -> str:
    mood = str(value or "neutral").strip().lower().replace("_", " ").replace("-", " ")
    mood = " ".join(mood.split())
    mood = ALIASES.get(mood, mood)
    return mood if mood in MOOD_COLOR_PRESETS else "neutral"


def resolve_mood_colors(value) -> dict[str, object]:
    return MOOD_COLOR_PRESETS[normalize_mood_name(value)].to_dict()
