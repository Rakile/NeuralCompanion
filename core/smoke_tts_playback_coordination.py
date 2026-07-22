"""Regression probes for process-wide TTS playback coordination."""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path


os.environ.setdefault("PYTHONUTF8", "1")

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = str(Path(__file__).resolve().parent)
sys.path[:] = [entry for entry in sys.path if str(Path(entry or ".").resolve()) != SCRIPT_DIR]
sys.path[:] = [entry for entry in sys.path if str(Path(entry or ".").resolve()) != str(ROOT)]
sys.path.insert(0, str(ROOT))


class _AudioData:
    def __mul__(self, _value):
        return self


class _SoundFile:
    @staticmethod
    def read(_path):
        return _AudioData(), 24000


class _PlaybackEvent:
    def __init__(self):
        self._event = threading.Event()

    def set(self):
        self._event.set()

    def clear(self):
        self._event.clear()


class _Stream:
    def __init__(self, owner):
        self._owner = owner

    @property
    def active(self):
        with self._owner.lock:
            return self._owner.active


class _SoundDevice:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = False
        self.play_calls = 0
        self.stop_threads: list[str] = []
        self.first_play_started = threading.Event()
        self.second_play_started = threading.Event()
        self.stream = _Stream(self)

    def play(self, _data, _sample_rate, device=None):
        del device
        with self.lock:
            self.play_calls += 1
            self.active = True
            if self.play_calls == 1:
                self.first_play_started.set()
            elif self.play_calls == 2:
                self.second_play_started.set()

    def get_stream(self):
        return self.stream

    def stop(self):
        with self.lock:
            self.stop_threads.append(threading.current_thread().name)
            self.active = False


def test_sounddevice_playback_is_process_wide_serialized() -> None:
    from core import audio_playback

    output = _SoundDevice()
    first_stop = threading.Event()
    second_stop = threading.Event()

    def play(stop_event: threading.Event) -> None:
        audio_playback.play_audio_file(
            "fake.wav",
            soundfile_module=_SoundFile(),
            sounddevice_module=output,
            stop_event=stop_event,
            audio_playing_event=_PlaybackEvent(),
            logger=lambda *_args: None,
        )

    first = threading.Thread(target=play, args=(first_stop,), daemon=True)
    second = threading.Thread(target=play, args=(second_stop,), daemon=True)
    first.start()
    assert output.first_play_started.wait(1.0)
    second.start()
    try:
        time.sleep(0.10)
        assert output.play_calls == 1, "A second worker entered sounddevice.play while playback was active"
        first_stop.set()
        assert output.second_play_started.wait(1.0), "Queued playback did not start after the first route stopped"
    finally:
        first_stop.set()
        second_stop.set()
        first.join(timeout=1.0)
        second.join(timeout=1.0)
    assert not first.is_alive()
    assert not second.is_alive()


def test_registering_latest_tts_route_cancels_previous_controller() -> None:
    import engine
    from core.tts_runtime import TTSController

    first = TTSController()
    second = TTSController()
    with engine._active_tts_controllers_lock:
        engine._active_tts_controllers.clear()
    try:
        engine._register_active_tts_controller(first)
        engine._register_active_tts_controller(second)
        assert first.cancel_requested.is_set(), "The superseded TTS route remained active"
        assert not second.cancel_requested.is_set()
    finally:
        with engine._active_tts_controllers_lock:
            engine._active_tts_controllers.clear()


def test_external_sounddevice_stop_waits_for_playback_owner() -> None:
    from core import audio_playback

    output = _SoundDevice()
    stop_event = threading.Event()
    playback_done = threading.Event()

    def play() -> None:
        try:
            audio_playback.play_audio_file(
                "fake.wav",
                soundfile_module=_SoundFile(),
                sounddevice_module=output,
                stop_event=stop_event,
                audio_playing_event=_PlaybackEvent(),
                logger=lambda *_args: None,
            )
        finally:
            playback_done.set()

    playback = threading.Thread(target=play, daemon=True, name="playback-owner")
    playback.start()
    assert output.first_play_started.wait(1.0)
    stop_event.set()

    external = threading.Thread(
        target=lambda: audio_playback.stop_audio_playback(output),
        daemon=True,
        name="external-stopper",
    )
    external.start()
    external.join(timeout=1.0)
    playback.join(timeout=1.0)
    assert not external.is_alive()
    assert playback_done.is_set()
    assert output.stop_threads[-1] == "external-stopper"


def test_controller_cancellation_reaches_current_audio_chunk() -> None:
    import engine
    from core.tts_runtime import TTSController

    controller = TTSController()
    stop_event = engine._tts_controller_playback_stop_event(controller, "")
    assert not stop_event.is_set()
    controller.cancel()
    assert stop_event.is_set(), "Cancelling a TTS controller did not interrupt its active audio chunk"


def main() -> None:
    test_sounddevice_playback_is_process_wide_serialized()
    test_registering_latest_tts_route_cancels_previous_controller()
    test_external_sounddevice_stop_waits_for_playback_owner()
    test_controller_cancellation_reaches_current_audio_chunk()
    print("TTS playback coordination regression probes passed.")


if __name__ == "__main__":
    main()
