"""Audio playback helpers used by the runtime workers."""

from __future__ import annotations

import time


def play_audio_file(path: str, *, soundfile_module, sounddevice_module, stop_event, audio_playing_event, output_device=None, logger=print):
    audio_playing_event.set()
    try:
        data, sample_rate = soundfile_module.read(path)
        if output_device is None:
            sounddevice_module.play(data, sample_rate)
        else:
            sounddevice_module.play(data, sample_rate, device=output_device)
        while sounddevice_module.get_stream().active:
            if stop_event.is_set():
                sounddevice_module.stop()
                logger("⏸️  Playback interrupted!")
                break
            time.sleep(0.01)
    except Exception as exc:
        logger(f"Audio error: {exc}")
    finally:
        audio_playing_event.clear()
