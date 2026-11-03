"""Low-cost voice analysis for microphone-driven presence visuals."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Callable

from .audio_spectrum import VoiceAnalysisFrame, analyze_voice_block


@dataclass(frozen=True, slots=True)
class MicrophoneAnalysisResult:
    """One analyzed microphone block plus its adaptive voice gate state."""

    frame: VoiceAnalysisFrame
    active: bool


class MicrophonePresenceAnalyzer:
    """Analyze existing STT PCM reads without opening another input stream."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        hang_seconds: float = 0.18,
    ) -> None:
        self._clock = clock
        self._hang_seconds = max(0.05, float(hang_seconds))
        self._previous_spectrum = (0.0,) * 12
        self._noise_floor = 0.008
        self._last_voice_at = 0.0
        self._active = False

    def reset(self) -> None:
        self._previous_spectrum = (0.0,) * 12
        self._noise_floor = 0.008
        self._last_voice_at = 0.0
        self._active = False

    def analyze_pcm(
        self,
        data: object,
        sample_rate: object,
        sample_width: object,
    ) -> MicrophoneAnalysisResult | None:
        samples = _normalized_pcm(data, sample_width)
        if samples is None:
            return None
        try:
            frame = analyze_voice_block(
                samples,
                int(sample_rate or 16_000),
                previous_spectrum=self._previous_spectrum,
            )
        except Exception:
            return None
        self._previous_spectrum = tuple(frame.spectrum)

        now = float(self._clock())
        level = max(0.0, min(1.0, float(frame.level or 0.0)))
        if not self._active:
            # Follow the room floor slowly. A hard ceiling prevents a sustained
            # voice from teaching the gate that speech is background noise.
            observed = min(level, 0.12)
            self._noise_floor = self._noise_floor * 0.94 + observed * 0.06

        open_threshold = max(0.055, self._noise_floor * 2.35 + 0.014)
        close_threshold = max(0.030, self._noise_floor * 1.45 + 0.008)
        if level >= (close_threshold if self._active else open_threshold):
            self._active = True
            self._last_voice_at = now
        elif self._active and now - self._last_voice_at >= self._hang_seconds:
            self._active = False

        return MicrophoneAnalysisResult(frame=frame, active=self._active)


def _normalized_pcm(data: object, sample_width: object):
    try:
        import numpy as np
    except Exception:
        return None
    if not isinstance(data, (bytes, bytearray, memoryview)) or not data:
        return None
    try:
        width = int(sample_width or 2)
    except (TypeError, ValueError):
        width = 2
    if width == 1:
        dtype = np.uint8
        scale = 128.0
    elif width == 2:
        dtype = np.int16
        scale = 32768.0
    elif width == 4:
        dtype = np.int32
        scale = 2147483648.0
    else:
        return None
    try:
        samples = np.frombuffer(data, dtype=dtype)
    except (TypeError, ValueError):
        return None
    if samples.size <= 0:
        return None
    normalized = samples.astype(np.float32)
    if width == 1:
        normalized = normalized - 128.0
    normalized = normalized / float(scale)
    return np.nan_to_num(normalized, nan=0.0, posinf=0.0, neginf=0.0)


__all__ = ["MicrophoneAnalysisResult", "MicrophonePresenceAnalyzer"]
