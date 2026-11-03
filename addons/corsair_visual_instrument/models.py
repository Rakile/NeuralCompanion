from __future__ import annotations

from dataclasses import dataclass, field

RgbColor = tuple[int, int, int]
AI_STATES = ("idle", "listening", "thinking", "speaking")


@dataclass(frozen=True, slots=True)
class LedPoint:
    led_id: int
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class DeviceDescriptor:
    device_id: str
    model: str
    led_points: tuple[LedPoint, ...] = ()


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    state: str = "idle"
    mood: str = "neutral"
    level: float = 0.0
    level_source: str = "state"
    spectrum: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class WavePulse:
    started_at: float
    amplitude: float
    bass: float
    mid: float
    treble: float


@dataclass(frozen=True, slots=True)
class K65AnimationProfile:
    effect: str
    speed: float = 1.0
    intensity: float = 1.0
    size: float = 1.0
    trail: float = 0.5
    audio_reactivity: float = 1.0
    detail: float = 0.5


@dataclass(frozen=True, slots=True)
class LightingSettings:
    enabled: bool = True
    k55_device_id: str = ""
    k65_device_id: str = ""
    k55_mode: str = "state_lanes"
    k65_speaking_mode: str = "equalizer"
    k65_idle_animation: K65AnimationProfile = field(
        default_factory=lambda: K65AnimationProfile(effect="classic_idle")
    )
    k65_listening_animation: K65AnimationProfile = field(
        default_factory=lambda: K65AnimationProfile(effect="classic_listening")
    )
    k65_thinking_animation: K65AnimationProfile = field(
        default_factory=lambda: K65AnimationProfile(effect="classic_thinking")
    )
    k65_speaking_animation: K65AnimationProfile = field(
        default_factory=lambda: K65AnimationProfile(effect="equalizer")
    )
    idle_color: RgbColor = (15, 100, 105)
    listening_color: RgbColor = (25, 165, 255)
    thinking_color: RgbColor = (150, 70, 255)
    speaking_color: RgbColor = (255, 145, 35)
    mood_tint_enabled: bool = True
    mood_tint_strength: float = 0.25
    brightness: float = 0.75
    sensitivity: float = 0.80
    smoothing: float = 0.55
    animation_speed: float = 1.0
    frame_rate_hz: int = 24
    sdk_dll_path: str = ""
