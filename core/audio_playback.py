"""Audio playback helpers used by the runtime workers."""

from __future__ import annotations

import threading
import time

try:
    from visual_presence.audio_reactive_meter import build_audio_level_sequence
except Exception:  # pragma: no cover - visual presence is optional.
    build_audio_level_sequence = None


_sounddevice_playback_lock = threading.Lock()


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
    level_fps=30,
    logger=print,
):
    level_stop = threading.Event()
    level_thread = None
    _sounddevice_playback_lock.acquire()
    try:
        audio_playing_event.set()
        data, sample_rate = soundfile_module.read(path)
        volume_factor = _normalized_volume(volume)
        if abs(volume_factor - 1.0) > 0.001:
            try:
                data = data * volume_factor
            except Exception as exc:
                logger(f"Audio volume error: {exc}")

        levels = []
        if callable(level_callback) and callable(build_audio_level_sequence):
            try:
                levels = build_audio_level_sequence(data, sample_rate, fps=level_fps)
            except Exception as exc:
                logger(f"Audio level meter error: {exc}")

        if output_device is None:
            sounddevice_module.play(data, sample_rate)
        else:
            sounddevice_module.play(data, sample_rate, device=output_device)

        if callable(level_callback) and levels:
            def _pump_audio_levels():
                interval = 1.0 / max(1, int(level_fps or 30))
                next_at = time.monotonic()
                try:
                    for level in levels:
                        if level_stop.is_set() or stop_event.is_set():
                            break
                        try:
                            stream = sounddevice_module.get_stream()
                            if stream is not None and not stream.active:
                                break
                        except Exception:
                            pass
                        try:
                            level_callback(level)
                        except Exception:
                            break
                        next_at += interval
                        level_stop.wait(max(0.001, next_at - time.monotonic()))
                finally:
                    try:
                        level_callback(0.0)
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
        audio_playing_event.clear()
        _sounddevice_playback_lock.release()
