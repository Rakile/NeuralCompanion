"""Validated settings only; execution and queue are never restored at startup."""
from __future__ import annotations
from dataclasses import asdict, dataclass, replace
import json
import math
import os
from pathlib import Path
import tempfile
from .continuous_guidance import GUIDANCE_PRESETS


@dataclass(frozen=True)
class ContinuousSettings:
    mode: str = "off"
    default_reply: str = "Continue"
    guidance: str = ""
    guidance_strength: int = 60
    use_premade: bool = False
    guidance_preset: str = "progress"
    separate_model: bool = False
    provider_id: str = ""
    model_id: str = ""
    context_chars: int = 16000
    recent_turns: int = 6
    max_output_tokens: int = 512
    temperature: float = 0.7
    delay_seconds: float = 1.0
    max_turns: int = 10  # 0 is explicitly selected Unlimited
    fallback: bool = True
    speak_user_messages: bool = False
    speak_guidance_and_example: bool = False
    user_voice: str = ""  # Opaque desktop voice ID; never a phone voice index.

    def updated(self, patch: dict) -> ContinuousSettings:
        if not isinstance(patch, dict) or set(patch) - set(asdict(self)):
            raise ValueError("Unknown Continuous setting")
        value = replace(self, **patch)
        if value.mode not in {"off", "simple", "ai_guided"}: raise ValueError("Invalid mode")
        for name, limit in (("default_reply", 8000), ("guidance", 8000), ("provider_id", 128), ("model_id", 256), ("user_voice", 64)):
            if type(getattr(value, name)) is not str or len(getattr(value, name)) > limit:
                raise ValueError(f"Invalid {name}")
        for name in ("separate_model", "fallback", "speak_user_messages", "speak_guidance_and_example", "use_premade"):
            if type(getattr(value, name)) is not bool: raise ValueError(f"Invalid {name}")
        if type(value.guidance_preset) is not str or value.guidance_preset not in {p[0] for p in GUIDANCE_PRESETS}:
            raise ValueError("Invalid guidance_preset")
        for name, minimum, maximum in (("guidance_strength", 0, 100), ("context_chars", 1000, 64000), ("recent_turns", 1, 30),
                                        ("max_output_tokens", 16, 1000), ("max_turns", 0, 10000)):
            number = getattr(value, name)
            if type(number) is not int or not minimum <= number <= maximum: raise ValueError(f"Invalid {name}")
        for name, maximum in (("temperature", 2), ("delay_seconds", 30)):
            number = getattr(value, name)
            if type(number) not in (int, float) or not math.isfinite(number) or not 0 <= number <= maximum:
                raise ValueError(f"Invalid {name}")
        return value


class SettingsStore:
    def __init__(self, path: Path): self.path = path

    def load(self) -> ContinuousSettings:
        try:
            if self.path.stat().st_size > 100000: return ContinuousSettings()
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and type(data.get("user_voice")) is int:
                data["user_voice"] = ""  # Old Kitten selection needs an explicit desktop voice.
            return ContinuousSettings().updated(data)
        except (OSError, ValueError, TypeError): return ContinuousSettings()

    def save(self, settings: ContinuousSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=".continuous-", suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(asdict(settings), handle, ensure_ascii=False)
                handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
