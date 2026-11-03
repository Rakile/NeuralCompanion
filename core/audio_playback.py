"""Audio playback helpers used by the runtime workers."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from core.musetalk_timing import start_musetalk_timing, trace_musetalk_timing

try:
    from visual_presence.audio_reactive_meter import (
        build_audio_level_sequence,
        build_audio_reactive_sequence,
    )
    from visual_presence.audio_spectrum import VoiceAnalysisFrame, analyze_voice_block
except Exception:  # pragma: no cover - visual presence is optional.
    build_audio_level_sequence = None
    build_audio_reactive_sequence = None
    VoiceAnalysisFrame = Any
    analyze_voice_block = None


_sounddevice_playback_lock = threading.Lock()


@contextmanager
def local_output_guard(*, stop_event=None):
    """Serialize local output; optionally cancel only the waiting acquisition.

    The no-argument legacy path keeps its blocking behavior. Cancellation never
    releases another owner's lock or stops its output stream.
    """
    if stop_event is None:
        with _sounddevice_playback_lock:
            yield
        return
    while not stop_event.is_set():
        if _sounddevice_playback_lock.acquire(timeout=0.01):
            break
    else:
        raise InterruptedError("Local output acquisition was cancelled")
    try:
        if stop_event.is_set():
            raise InterruptedError("Local output acquisition was cancelled")
        yield
    finally:
        _sounddevice_playback_lock.release()


@dataclass(frozen=True, slots=True)
class PreparedPlaybackAudio:
    """Decoded, volume-adjusted playback data with optional visual analysis."""

    decoded_pcm: Any
    sample_rate: int
    volume: float
    level_fps: int
    levels: tuple[float, ...]
    voice_frames: tuple[VoiceAnalysisFrame, ...]
    has_level_callback: bool
    has_analysis_callback: bool
    first_voice_block: Any = None


class VoiceAnalysisPlaybackState:
    """Retain flux history across streamed files owned by one stop event."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owner: object | None = None
        self._previous_spectrum: tuple[float, ...] | None = None

    @property
    def previous_spectrum(self) -> tuple[float, ...] | None:
        with self._lock:
            return self._previous_spectrum

    def begin(self, owner: object) -> None:
        try:
            stopped = bool(owner.is_set())
        except Exception:
            stopped = False
        with self._lock:
            if stopped or owner is not self._owner:
                self._previous_spectrum = None
            self._owner = owner

    def record(self, frame: VoiceAnalysisFrame) -> None:
        spectrum = tuple(getattr(frame, "spectrum", ()) or ())
        with self._lock:
            self._previous_spectrum = spectrum if len(spectrum) == 12 else None

    def reset(self) -> None:
        with self._lock:
            self._owner = None
            self._previous_spectrum = None


def stop_audio_playback(sounddevice_module) -> None:
    """Stop the shared convenience stream without racing another playback owner."""
    with _sounddevice_playback_lock:
        sounddevice_module.stop()


def _normalized_volume(value) -> float:
    try:
        volume = float(value)
    except Exception:
        return 1.0
    if not volume >= 0.0:
        return 1.0
    return max(0.0, min(4.0, volume))


def _normalized_level_fps(value) -> int:
    try:
        return max(1, int(value or 30))
    except Exception:
        return 30


def _apply_volume(data, volume_factor: float, logger):
    if abs(volume_factor - 1.0) > 0.001:
        try:
            return data * volume_factor
        except Exception as exc:
            logger(f"Audio volume error: {exc}")
    return data


def _first_voice_block(data, sample_rate: int, level_fps: int):
    try:
        return data[:max(1, int(sample_rate or 1) // max(1, int(level_fps or 30)))]
    except Exception:
        return None


def prepare_audio_file(
    path: str,
    *,
    soundfile_module,
    volume=1.0,
    level_callback=None,
    analysis_callback=None,
    level_fps=30,
    logger=print,
) -> PreparedPlaybackAudio:
    """Decode and analyze one file without touching device or playback state."""
    data, sample_rate = soundfile_module.read(path)
    return prepare_pcm_audio(data, sample_rate, volume=volume,
        level_callback=level_callback, analysis_callback=analysis_callback,
        level_fps=level_fps, logger=logger)


def prepare_pcm_audio(
    data,
    sample_rate,
    volume=1.0,
    level_callback=None,
    analysis_callback=None,
    level_fps=30,
    logger=print,
) -> PreparedPlaybackAudio:
    """Prepare decoded PCM using the same volume and analysis policy as files."""
    volume_factor = _normalized_volume(volume)
    data = _apply_volume(data, volume_factor, logger)
    fps = _normalized_level_fps(level_fps)
    has_level_callback = callable(level_callback)
    has_analysis_callback = callable(analysis_callback)
    levels: tuple[float, ...] = ()
    voice_frames: tuple[VoiceAnalysisFrame, ...] = ()
    first_voice_block = None
    if has_analysis_callback and callable(build_audio_reactive_sequence):
        try:
            sequence = build_audio_reactive_sequence(data, sample_rate, fps=fps)
            levels = tuple(sequence.levels)
            voice_frames = tuple(sequence.voice_frames)
            first_voice_block = _first_voice_block(data, sample_rate, fps)
        except Exception as exc:
            logger(f"Voice analysis error: {exc}")
    elif has_level_callback and callable(build_audio_level_sequence):
        try:
            levels = tuple(build_audio_level_sequence(data, sample_rate, fps=fps))
        except Exception as exc:
            logger(f"Audio level meter error: {exc}")
    return PreparedPlaybackAudio(
        decoded_pcm=data,
        sample_rate=sample_rate,
        volume=volume_factor,
        level_fps=fps,
        levels=levels,
        voice_frames=voice_frames,
        has_level_callback=has_level_callback,
        has_analysis_callback=has_analysis_callback,
        first_voice_block=first_voice_block,
    )


def _prepared_audio_is_compatible(prepared, volume, level_callback, analysis_callback, level_fps) -> bool:
    return isinstance(prepared, PreparedPlaybackAudio) and (
        prepared.volume == _normalized_volume(volume)
        and prepared.level_fps == _normalized_level_fps(level_fps)
        and prepared.has_level_callback == callable(level_callback)
        and prepared.has_analysis_callback == callable(analysis_callback)
    )


def play_audio_file(
    path: str,
    *,
    soundfile_module,
    sounddevice_module,
    stop_event,
    audio_playing_event,
    output_device=None,
    volume=1.0,
    level_callback=None,
    analysis_callback=None,
    analysis_state: VoiceAnalysisPlaybackState | None = None,
    level_fps=30,
    logger=print,
    trace_musetalk=False,
    prepared_audio: PreparedPlaybackAudio | None = None,
    on_started=None,
):
    level_stop = threading.Event()
    level_thread = None
    timing_started = start_musetalk_timing() if trace_musetalk else None
    timing_chunk = Path(path).stem if timing_started is not None else ""
    output_guard = local_output_guard()
    output_guard.__enter__()
    try:
        trace_musetalk_timing("audio_lock_acquired", timing_started, chunk=timing_chunk)
        if stop_event.is_set():
            return None
        audio_playing_event.set()
        volume_factor = _normalized_volume(volume)
        use_prepared = _prepared_audio_is_compatible(
            prepared_audio, volume, level_callback, analysis_callback, level_fps,
        )
        if use_prepared:
            data = prepared_audio.decoded_pcm
            sample_rate = prepared_audio.sample_rate
            levels = list(prepared_audio.levels)
            voice_frames = tuple(prepared_audio.voice_frames)
        else:
            data, sample_rate = soundfile_module.read(path)
            data = _apply_volume(data, volume_factor, logger)
            levels = []
            voice_frames = ()
        trace_musetalk_timing("audio_read", timing_started, chunk=timing_chunk)

        if not use_prepared and callable(analysis_callback) and callable(build_audio_reactive_sequence):
            try:
                state = analysis_state or VoiceAnalysisPlaybackState()
                state.begin(stop_event)
                sequence = build_audio_reactive_sequence(
                    data,
                    sample_rate,
                    fps=level_fps,
                    previous_spectrum=state.previous_spectrum,
                )
                levels = list(sequence.levels)
                voice_frames = tuple(sequence.voice_frames)
                analysis_state = state
            except Exception as exc:
                logger(f"Voice analysis error: {exc}")
        elif not use_prepared and callable(level_callback) and callable(build_audio_level_sequence):
            try:
                levels = build_audio_level_sequence(data, sample_rate, fps=level_fps)
            except Exception as exc:
                logger(f"Audio level meter error: {exc}")

        trace_musetalk_timing("audio_analysis", timing_started, chunk=timing_chunk)
        if stop_event.is_set():
            return None
        if output_device is None:
            sounddevice_module.play(data, sample_rate)
        else:
            sounddevice_module.play(data, sample_rate, device=output_device)
        trace_musetalk_timing("audio_device_started", timing_started, chunk=timing_chunk)
        if not stop_event.is_set() and callable(on_started):
            try:
                on_started()
            except Exception as exc:
                logger(f"Audio started callback error: {exc}")

        if use_prepared and callable(analysis_callback) and voice_frames:
            try:
                state = analysis_state or VoiceAnalysisPlaybackState()
                state.begin(stop_event)
                if callable(analyze_voice_block) and prepared_audio.first_voice_block is not None:
                    voice_frames = (
                        analyze_voice_block(
                            prepared_audio.first_voice_block,
                            sample_rate,
                            state.previous_spectrum,
                        ),
                        *voice_frames[1:],
                    )
                analysis_state = state
            except Exception as exc:
                logger(f"Voice analysis error: {exc}")

        if (callable(level_callback) or callable(analysis_callback)) and levels:
            def _pump_audio_levels():
                interval = 1.0 / max(1, int(level_fps or 30))
                next_at = time.monotonic()
                try:
                    for index, level in enumerate(levels):
                        if level_stop.is_set() or stop_event.is_set():
                            break
                        try:
                            stream = sounddevice_module.get_stream()
                            if stream is not None and not stream.active:
                                break
                        except Exception:
                            pass
                        if callable(level_callback):
                            try:
                                level_callback(level)
                            except Exception:
                                break
                        if callable(analysis_callback) and index < len(voice_frames):
                            frame = voice_frames[index]
                            if analysis_state is not None:
                                analysis_state.record(frame)
                            try:
                                analysis_callback(frame)
                            except Exception:
                                break
                        next_at += interval
                        level_stop.wait(max(0.001, next_at - time.monotonic()))
                finally:
                    try:
                        if callable(level_callback):
                            level_callback(0.0)
                    except Exception:
                        pass
                    try:
                        if callable(analysis_callback):
                            analysis_callback(None)
                    except Exception:
                        pass

            level_thread = threading.Thread(target=_pump_audio_levels, daemon=True, name="nc-audio-level-meter")
            level_thread.start()

        while sounddevice_module.get_stream().active:
            if stop_event.is_set():
                sounddevice_module.stop()
                logger("Playback interrupted.")
                break
            time.sleep(0.01)
    except Exception as exc:
        logger(f"Audio error: {exc}")
    finally:
        try:
            level_stop.set()
            if level_thread is not None:
                level_thread.join(timeout=0.1)
        except Exception:
            pass
        if callable(level_callback):
            try:
                level_callback(0.0)
            except Exception:
                pass
        if callable(analysis_callback):
            try:
                analysis_callback(None)
            except Exception:
                pass
        if analysis_state is not None and stop_event.is_set():
            analysis_state.reset()
        audio_playing_event.clear()
        output_guard.__exit__(None, None, None)
        trace_musetalk_timing("audio_finished", timing_started, chunk=timing_chunk,
                             interrupted=stop_event.is_set())


def play_prepared_audio_chunk(
    chunk,
    *,
    soundfile_module,
    sounddevice_module,
    stop_event,
    audio_playing_event,
    output_device=None,
    volume=1.0,
    level_callback=None,
    analysis_callback=None,
    analysis_state: VoiceAnalysisPlaybackState | None = None,
    level_fps=30,
    logger=print,
):
    """Play one prepared runtime chunk through the existing direct device path."""

    return play_audio_file(
        str(getattr(chunk, "audio_path", "")),
        soundfile_module=soundfile_module,
        sounddevice_module=sounddevice_module,
        stop_event=stop_event,
        audio_playing_event=audio_playing_event,
        output_device=output_device,
        volume=volume,
        level_callback=level_callback,
        analysis_callback=analysis_callback,
        analysis_state=analysis_state,
        level_fps=level_fps,
        logger=logger,
    )
