"""Addon-local Creator preview output using NC's device-clock session."""
from __future__ import annotations


def _resolve_output_device(sounddevice_module, output_device):
    """Resolve configured labels exactly as chat playback does."""
    if not isinstance(output_device, str):
        return output_device
    wanted = output_device.strip().casefold()
    if not wanted or wanted == "default output":
        return None
    try:
        outputs = [
            (index, str(device.get("name", "") or "").strip().casefold())
            for index, device in enumerate(sounddevice_module.query_devices() or ())
            if int(device.get("max_output_channels", 0) or 0) > 0
        ]
        for index, name in outputs:
            if name == wanted:
                return index
        for index, name in outputs:
            if wanted in name or name in wanted:
                return index
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "Could not enumerate preview audio outputs; using default output."
        )
        return None
    import logging
    logging.getLogger(__name__).warning(
        "Preview audio output %r was not found; using default output.", output_device
    )
    return None

class _MutedOutputDevice:
    """Wrap stream creation without changing sounddevice's global output."""

    def __init__(self, sounddevice_module, muted_event):
        self._sounddevice = sounddevice_module
        self._muted_event = muted_event

    def OutputStream(self, *args, **kwargs):
        callback = kwargs["callback"]
        muted_event = self._muted_event

        def muted_callback(outdata, *callback_args):
            callback(outdata, *callback_args)
            if muted_event.is_set():
                outdata[...] = 0.0

        kwargs["callback"] = muted_callback
        return self._sounddevice.OutputStream(*args, **kwargs)


class PreviewAudioPlayer:
    """Own one preview stream; call lifecycle methods on its owner thread.

    Mute is safe to toggle through the supplied event from another thread.
    The session consumes unchanged PCM while muted, keeping its DAC clock.
    """

    def __init__(self, path, *, stop_event, muted_event, output_device=None,
                 sounddevice_module=None, soundfile_module=None):
        self._path = path
        self._stop_event = stop_event
        self._muted_event = muted_event
        self._output_device = output_device
        self._sounddevice = sounddevice_module
        self._soundfile = soundfile_module
        self._session = None
        self._error = None
        self._started = False
        self._closed = False

    def start(self):
        if self._started or self._closed:
            raise RuntimeError("Preview audio player cannot be restarted")
        self._started = True
        try:
            from core.audio_playback import PreparedPlaybackAudio
            from core.continuous_audio import SoundDeviceSpeechSession
            soundfile = self._soundfile
            if soundfile is None:
                import soundfile
            sounddevice = self._sounddevice
            if sounddevice is None:
                import sounddevice
            pcm, rate = soundfile.read(str(self._path), dtype="float32", always_2d=True)
            audio = PreparedPlaybackAudio(pcm, rate, 1.0, 30, (), (), False, False)
            self._session = SoundDeviceSpeechSession(
                sounddevice_module=_MutedOutputDevice(sounddevice, self._muted_event),
                stop_event=self._stop_event,
                output_device=_resolve_output_device(sounddevice, self._output_device),
            )
            if not self._session.put(0, audio):
                raise RuntimeError(self._session.error or "Preview audio admission cancelled")
            self._session.finish_input()
        except Exception as exc:
            self._error = str(exc) or type(exc).__name__
            self.close()
            raise

    def poll(self):
        return self._session.poll() if self._session is not None else ()

    def clock_sample(self):
        return self._session.clock_sample() if self._session is not None else None

    @property
    def drained(self):
        return self._session.drained if self._session is not None else False

    @property
    def error(self):
        return self._error or (self._session.error if self._session is not None else None)

    def close(self):
        self._closed = True
        if self._session is not None:
            self._session.close()
