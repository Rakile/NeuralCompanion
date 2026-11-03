"""Audio-level helpers for AI Presence Mode."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .audio_spectrum import VoiceAnalysisFrame, analyze_voice_block

try:
    import numpy as _np
except Exception:  # pragma: no cover - numpy is optional for this helper.
    _np = None


def clamp_level(value) -> float:
    try:
        numeric = float(value)
    except Exception:
        return 0.0
    if not numeric >= 0.0:
        return 0.0
    return max(0.0, min(1.0, numeric))


@dataclass(frozen=True, slots=True)
class AudioReactiveSequence:
    """Playback-cadence scalar levels and voice frames with matching indexes."""

    levels: tuple[float, ...]
    voice_frames: tuple[VoiceAnalysisFrame, ...]


def _frames_per_step(sample_rate, fps) -> int:
    try:
        rate = max(1, int(sample_rate or 1))
        return max(1, int(rate / max(1, int(fps or 30))))
    except Exception:
        return 800


def build_audio_level_sequence(data, sample_rate, *, fps=30) -> list[float]:
    """Return a compact RMS/peak envelope for an outgoing TTS buffer."""
    frames_per_step = _frames_per_step(sample_rate, fps)

    if _np is not None:
        try:
            audio = _np.asarray(data, dtype=_np.float32)
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            if audio.size <= 0:
                return [0.0]
            levels: list[float] = []
            smoothed = 0.0
            for start in range(0, int(audio.shape[0]), frames_per_step):
                window = audio[start : start + frames_per_step]
                if window.size <= 0:
                    continue
                rms = float(_np.sqrt(_np.mean(_np.square(window))))
                peak = float(_np.max(_np.abs(window)))
                level = clamp_level((rms * 5.5) + (peak * 0.2))
                response = 0.72 if level > smoothed else 0.24
                smoothed += (level - smoothed) * response
                if level < 0.002 and smoothed < 0.003:
                    smoothed = 0.0
                levels.append(clamp_level(smoothed))
            return levels or [0.0]
        except Exception:
            pass

    try:
        values = list(data or [])
    except Exception:
        return [0.0]
    if not values:
        return [0.0]

    levels: list[float] = []
    smoothed = 0.0
    for start in range(0, len(values), frames_per_step):
        window = values[start : start + frames_per_step]
        if not window:
            continue
        total = 0.0
        peak = 0.0
        count = 0
        for sample in window:
            if isinstance(sample, (list, tuple)):
                sample_value = sum(float(part or 0.0) for part in sample) / max(1, len(sample))
            else:
                sample_value = float(sample or 0.0)
            abs_value = abs(sample_value)
            peak = max(peak, abs_value)
            total += sample_value * sample_value
            count += 1
        rms = math.sqrt(total / max(1, count))
        level = clamp_level((rms * 5.5) + (peak * 0.2))
        response = 0.72 if level > smoothed else 0.24
        smoothed += (level - smoothed) * response
        if level < 0.002 and smoothed < 0.003:
            smoothed = 0.0
        levels.append(clamp_level(smoothed))
    return levels or [0.0]


def build_audio_reactive_sequence(
    data,
    sample_rate,
    *,
    fps=30,
    previous_spectrum=None,
) -> AudioReactiveSequence:
    """Build voice frames beside the existing level sequence at one cadence.

    Analysis is prepared by the existing playback worker before device
    playback. If NumPy or FFT analysis fails, scalar levels remain available
    and the richer visual contract fails silent.
    """

    levels = tuple(build_audio_level_sequence(data, sample_rate, fps=fps))
    zero = VoiceAnalysisFrame(0.0, 0.0, (0.0,) * 12, 0.0, 0.0)
    if _np is None:
        return AudioReactiveSequence(levels, tuple(zero for _ in levels))

    frames_per_step = _frames_per_step(sample_rate, fps)
    try:
        audio = _np.asarray(data, dtype=_np.float32)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        audio = _np.nan_to_num(
            audio.reshape(-1),
            nan=0.0,
            posinf=0.0,
            neginf=0.0,
        )
        previous = previous_spectrum
        frames: list[VoiceAnalysisFrame] = []
        for start in range(0, int(audio.shape[0]), frames_per_step):
            window = audio[start : start + frames_per_step]
            if window.size <= 0:
                continue
            frame = analyze_voice_block(window, sample_rate, previous)
            frames.append(frame)
            previous = frame.spectrum
    except Exception:
        frames = []

    if len(frames) != len(levels):
        frames = [zero for _ in levels]
    return AudioReactiveSequence(levels, tuple(frames))
