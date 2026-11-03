"""Small, optional helpers for bounded real-time audio spectrum analysis."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

class SpectrumAnalysisUnavailable(RuntimeError):
    """Raised when the optional numerical analysis runtime is unavailable."""


VOICE_SPECTRUM_BANDS = 12
_FLUX_GAIN = 4.0


@dataclass(frozen=True, slots=True)
class VoiceAnalysisFrame:
    """One immutable, bounded analysis frame synchronized with TTS playback."""

    level: float
    peak: float
    spectrum: tuple[float, ...]
    spectral_flux: float
    spectral_centroid: float


def _clamped_finite(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return max(0.0, min(1.0, number))


def _sanitized_mono(samples: Any):
    try:
        import numpy as np
    except Exception as exc:
        raise SpectrumAnalysisUnavailable("NumPy is unavailable") from exc

    try:
        audio = np.asarray(samples, dtype=np.float32)
    except Exception:
        return np.asarray((), dtype=np.float32)
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)
    return np.nan_to_num(
        audio.reshape(-1),
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )


def _level_and_peak(audio: Any) -> tuple[float, float]:
    try:
        import numpy as np
    except Exception as exc:
        raise SpectrumAnalysisUnavailable("NumPy is unavailable") from exc

    if int(getattr(audio, "size", 0) or 0) <= 0:
        return 0.0, 0.0
    rms = float(np.sqrt(np.mean(np.square(audio))))
    peak = float(np.max(np.abs(audio)))
    return (
        _clamped_finite((rms * 5.2) + (peak * 0.22)),
        _clamped_finite(peak),
    )


def analyze_spectrum(
    samples: Any,
    sample_rate: int,
    band_count: int = 48,
) -> tuple[float, ...]:
    """Return amplitude-weighted logarithmic FFT bands for one audio block."""

    count = max(1, int(band_count or 48))
    zeros = (0.0,) * count
    try:
        import numpy as np
    except Exception as exc:
        raise SpectrumAnalysisUnavailable("NumPy is unavailable") from exc

    rate = int(sample_rate or 0)
    if rate <= 80:
        return zeros
    audio = _sanitized_mono(samples)
    if audio.size < 2:
        return zeros

    block_level, _peak = _level_and_peak(audio)
    if block_level <= 0.002:
        return zeros

    windowed = audio * np.hanning(audio.size).astype(np.float32)
    magnitudes = np.abs(np.fft.rfft(windowed))
    frequencies = np.fft.rfftfreq(audio.size, 1.0 / rate)
    upper_hz = min(20_000.0, rate / 2.0)
    if upper_hz <= 40.0:
        return zeros
    edges = np.geomspace(40.0, upper_hz, count + 1)
    energies = np.zeros(count, dtype=np.float32)
    for index in range(count):
        bins = np.flatnonzero(
            (frequencies >= edges[index]) & (frequencies < edges[index + 1])
        )
        if bins.size:
            energies[index] = np.sqrt(
                np.mean(np.square(magnitudes[bins]))
            )

    compressed = np.log1p(energies)
    strongest = float(np.max(compressed))
    if not math.isfinite(strongest) or strongest <= 0.0:
        return zeros
    normalized = np.clip(
        (compressed / strongest) * block_level,
        0.0,
        1.0,
    )
    return tuple(float(value) for value in normalized)


def analyze_voice_block(
    samples: Any,
    sample_rate: int,
    previous_spectrum: Any = None,
) -> VoiceAnalysisFrame:
    """Return a finite 12-band voice frame for one decoded PCM block.

    The function has no retained state. Callers explicitly pass the previous
    spectrum so streaming and replay owners control flux history and resets.
    """

    try:
        import numpy as np
    except Exception as exc:
        raise SpectrumAnalysisUnavailable("NumPy is unavailable") from exc

    audio = _sanitized_mono(samples)
    level, peak = _level_and_peak(audio)
    spectrum = tuple(
        _clamped_finite(value)
        for value in analyze_spectrum(
            audio,
            sample_rate,
            band_count=VOICE_SPECTRUM_BANDS,
        )
    )
    if len(spectrum) != VOICE_SPECTRUM_BANDS:
        spectrum = (0.0,) * VOICE_SPECTRUM_BANDS

    has_previous = previous_spectrum is not None
    try:
        previous_values = list(previous_spectrum or ())
    except Exception:
        previous_values = []
    previous = np.asarray(
        [
            _clamped_finite(
                previous_values[index] if index < len(previous_values) else 0.0
            )
            for index in range(VOICE_SPECTRUM_BANDS)
        ],
        dtype=np.float32,
    )
    current = np.asarray(spectrum, dtype=np.float32)
    positive_delta = np.maximum(0.0, current - previous)
    spectral_flux = (
        _clamped_finite(float(np.mean(positive_delta)) * _FLUX_GAIN)
        if has_previous
        else 0.0
    )

    total = float(np.sum(current))
    if total <= 1e-8:
        spectral_centroid = 0.0
    else:
        positions = np.linspace(0.0, 1.0, VOICE_SPECTRUM_BANDS, dtype=np.float32)
        spectral_centroid = _clamped_finite(float(np.dot(current, positions) / total))

    return VoiceAnalysisFrame(
        level=_clamped_finite(level),
        peak=_clamped_finite(peak),
        spectrum=spectrum,
        spectral_flux=spectral_flux,
        spectral_centroid=spectral_centroid,
    )


def smooth_spectrum(
    previous: tuple[float, ...],
    target: tuple[float, ...],
    smoothing: float,
) -> tuple[float, ...]:
    """Apply the existing NC fast-attack, slower-release smoothing convention."""

    if len(previous) != len(target):
        previous = (0.0,) * len(target)
    amount = _clamped_finite(smoothing)
    values: list[float] = []
    for old, new in zip(previous, target):
        old_value = _clamped_finite(old)
        new_value = _clamped_finite(new)
        if amount <= 0.0:
            coefficient = 1.0
        elif new_value >= old_value:
            coefficient = max(0.08, 1.0 - amount)
        else:
            coefficient = max(0.03, (1.0 - amount) * 0.45)
        values.append(
            _clamped_finite(
                old_value + ((new_value - old_value) * coefficient)
            )
        )
    return tuple(values)
