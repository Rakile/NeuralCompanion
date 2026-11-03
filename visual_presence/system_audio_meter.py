"""Best-effort desktop/output audio meter for AI Presence music sync."""

from __future__ import annotations

import inspect
import math
import threading
import time
import warnings

from .audio_reactive_meter import clamp_level
from .audio_spectrum import (
    SpectrumAnalysisUnavailable,
    analyze_spectrum,
    smooth_spectrum,
)


class SystemAudioLevelMeter:
    """Poll Windows WASAPI loopback audio without touching the Qt UI thread."""

    def __init__(
        self,
        callback,
        *,
        fps=30,
        logger=print,
        spectrum_callback=None,
        spectrum_bands=48,
    ):
        self._callback = callback
        self._fps = max(5, min(120, int(fps or 30)))
        self._logger = logger if callable(logger) else print
        self._spectrum_callback = (
            spectrum_callback if callable(spectrum_callback) else None
        )
        self._spectrum_bands = max(1, int(spectrum_bands or 48))
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._pending_level = 0.0
        self._pending_audio = None
        self._pending_audio_sequence = 0
        self._thread = None
        self.error = ""
        self.backend = ""
        self._reported_backend = ""

    def start(self) -> None:
        if self.is_running():
            return
        with self._lock:
            self._pending_audio = None
            self._pending_audio_sequence = 0
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="nc-ai-presence-system-audio")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.6)
        self._thread = None
        self._emit(0.0)
        self._emit_spectrum((0.0,) * self._spectrum_bands)

    def is_running(self) -> bool:
        thread = self._thread
        return bool(thread is not None and thread.is_alive())

    def set_fps(self, fps) -> None:
        try:
            self._fps = max(5, min(120, int(fps or 30)))
        except Exception:
            self._fps = 30

    def _emit(self, level) -> None:
        try:
            self._callback(clamp_level(level))
        except Exception:
            pass

    def _emit_spectrum(self, values) -> None:
        callback = self._spectrum_callback
        if callback is None:
            return
        try:
            normalized = tuple(float(value) for value in values)
        except (TypeError, ValueError):
            normalized = ()
        if len(normalized) != self._spectrum_bands or any(
            not math.isfinite(value) for value in normalized
        ):
            normalized = (0.0,) * self._spectrum_bands
        else:
            normalized = tuple(clamp_level(value) for value in normalized)
        try:
            callback(normalized)
        except Exception:
            pass

    def _store_level(self, level) -> None:
        with self._lock:
            self._pending_level = clamp_level(level)

    def _read_level(self) -> float:
        with self._lock:
            return float(self._pending_level)

    def _store_audio_samples(self, samples) -> None:
        if self._spectrum_callback is None:
            return
        with self._lock:
            self._pending_audio = samples
            self._pending_audio_sequence += 1

    def _read_audio_samples(self, previous_sequence: int):
        with self._lock:
            sequence = self._pending_audio_sequence
            if sequence == previous_sequence or self._pending_audio is None:
                return sequence, None
            return sequence, self._pending_audio

    def _run(self) -> None:
        smoothed = 0.0
        smoothed_spectrum = (0.0,) * self._spectrum_bands
        audio_sequence = 0
        spectrum_error_reported = False
        soundcard_module = None
        soundcard_import_error = None
        soundcard_capture_error = None
        try:
            # SoundCard 0.4.6 initializes COM at import time. Import it before
            # PortAudio touches WASAPI on this worker, otherwise SoundCard can
            # mistake COM's harmless S_FALSE result for a fatal error and its
            # loopback fallback never starts inside the full NC process.
            try:
                import soundcard as soundcard_module
            except Exception as exc:
                soundcard_import_error = exc

            import sounddevice as sd

            try:
                import numpy as np
            except Exception:
                np = None

            extra_settings = _sounddevice_loopback_settings(sd)
            if extra_settings is not None:
                device_index, device_info = _default_wasapi_output_device(sd)
                channel_key = "max_output_channels"
            else:
                # A driver Stereo Mix endpoint may belong to a different sound
                # card than Windows' default output and silently capture nothing.
                # Prefer true default-output loopback before legacy virtual inputs.
                if soundcard_module is not None:
                    try:
                        self._run_soundcard(soundcard_module)
                    except Exception as exc:
                        soundcard_capture_error = exc
                    else:
                        return
                device_index, device_info = _sounddevice_virtual_output_input_device(sd)
                channel_key = "max_input_channels"
            sample_rate = int(float(device_info.get("default_samplerate") or 48000))
            channels = max(1, min(2, int(device_info.get(channel_key) or 2)))
            blocksize = max(256, int(sample_rate / max(5, self._fps)))

            def _audio_callback(indata, _frames, _time_info, _status):
                try:
                    if indata is None:
                        self._store_level(0.0)
                        return
                    if np is not None:
                        audio = np.asarray(indata, dtype=np.float32)
                        if audio.size <= 0:
                            self._store_level(0.0)
                            return
                        rms = float(np.sqrt(np.mean(np.square(audio))))
                        peak = float(np.max(np.abs(audio)))
                        mono = (
                            np.mean(audio, axis=1)
                            if audio.ndim > 1
                            else audio.reshape(-1)
                        )
                        self._store_audio_samples(mono.astype(np.float32, copy=True))
                    else:
                        values = list(indata or [])
                        if not values:
                            self._store_level(0.0)
                            return
                        total = 0.0
                        peak = 0.0
                        count = 0
                        for frame in values:
                            if isinstance(frame, (list, tuple)):
                                sample = sum(float(part or 0.0) for part in frame) / max(1, len(frame))
                            else:
                                sample = float(frame or 0.0)
                            absolute = abs(sample)
                            peak = max(peak, absolute)
                            total += sample * sample
                            count += 1
                        rms = (total / max(1, count)) ** 0.5
                    self._store_level((rms * 5.2) + (peak * 0.22))
                except Exception:
                    self._store_level(0.0)

            stream_kwargs = {
                "samplerate": sample_rate,
                "blocksize": blocksize,
                "device": device_index,
                "channels": channels,
                "dtype": "float32",
                "callback": _audio_callback,
            }
            if extra_settings is not None:
                stream_kwargs["extra_settings"] = extra_settings

            with sd.InputStream(**stream_kwargs):
                self._report_backend_ready(
                    "PortAudio loopback",
                    str(device_info.get("name") or "default output"),
                )
                next_at = time.monotonic()
                while not self._stop.is_set():
                    raw = self._read_level()
                    attack = 0.50 if raw > smoothed else 0.18
                    smoothed = (smoothed * (1.0 - attack)) + (raw * attack)
                    self._emit(smoothed)
                    if self._spectrum_callback is not None:
                        audio_sequence, samples = self._read_audio_samples(audio_sequence)
                        if samples is not None:
                            try:
                                target_spectrum = analyze_spectrum(
                                    samples,
                                    sample_rate,
                                    self._spectrum_bands,
                                )
                                smoothed_spectrum = smooth_spectrum(
                                    smoothed_spectrum,
                                    target_spectrum,
                                    0.46,
                                )
                                self._emit_spectrum(smoothed_spectrum)
                            except SpectrumAnalysisUnavailable as exc:
                                if not spectrum_error_reported:
                                    spectrum_error_reported = True
                                    self._logger(
                                        f"[AI Presence] Computer audio spectrum unavailable: {exc}"
                                    )
                            except Exception as exc:
                                if not spectrum_error_reported:
                                    spectrum_error_reported = True
                                    self._logger(
                                        f"[AI Presence] Computer audio spectrum failed: {exc}"
                                    )
                    interval = 1.0 / max(5, min(120, int(self._fps or 30)))
                    next_at += interval
                    self._stop.wait(max(0.002, next_at - time.monotonic()))
        except Exception as sounddevice_exc:
            try:
                if soundcard_capture_error is not None:
                    raise soundcard_capture_error
                self._run_soundcard(
                    soundcard_module,
                    import_error=soundcard_import_error,
                )
            except Exception as soundcard_exc:
                self.error = (
                    f"sounddevice: {sounddevice_exc}; SoundCard: {soundcard_exc}"
                )
                try:
                    self._logger(
                        "[AI Presence] Optional computer-audio reaction is unavailable "
                        "for this session; TTS voice reaction remains active. "
                        f"Details: {self.error}"
                    )
                except Exception:
                    pass
        finally:
            self._emit(0.0)

    def _report_backend_ready(self, backend: str, device: str) -> None:
        self.error = ""
        self.backend = str(backend or "").strip()
        report_key = f"{self.backend}:{str(device or '').strip()}"
        if report_key == self._reported_backend:
            return
        self._reported_backend = report_key
        try:
            self._logger(
                "[AI Presence] Desktop audio sync active via "
                f"{self.backend}: {str(device or 'default output').strip()}."
            )
        except Exception:
            pass

    def _run_soundcard(self, sc=None, *, import_error=None) -> None:
        """Capture the default Windows output through SoundCard's WASAPI loopback."""
        import ctypes

        # SoundCard 0.4.6 initializes COM while its Windows backend is imported.
        # It incorrectly treats COM's S_FALSE (already initialized) success code
        # as a fatal error, so it must perform the first initialization on this
        # capture thread.  Initializing COM before this import causes both the
        # misleading ``Error 0x100000001`` and its broken destructor traceback.
        if sc is None and import_error is None:
            try:
                import soundcard as sc
            except Exception as exc:
                import_error = exc
        if sc is None:
            exc = import_error
            if isinstance(exc, ModuleNotFoundError):
                raise RuntimeError(
                    "SoundCard loopback backend is not installed; reinstall "
                    "NC requirements (soundcard==0.4.6)"
                ) from exc
            raise RuntimeError(
                f"SoundCard loopback backend could not initialize: {exc}"
            ) from exc

        # SoundCard may already have been imported by another component. Ensure
        # this capture worker also owns a COM apartment before enumerating its
        # MMDevice endpoints. S_FALSE and RPC_E_CHANGED_MODE are both safe here.
        # WinDLL returns the raw HRESULT. OleDLL raises before we can accept
        # RPC_E_CHANGED_MODE, which is harmless when another audio component
        # already initialized this worker in the opposite COM apartment.
        ole32 = ctypes.WinDLL("ole32", use_last_error=True)
        ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        ole32.CoInitializeEx.restype = ctypes.c_long
        result = int(ole32.CoInitializeEx(None, 0))
        changed_mode = -2147417850  # RPC_E_CHANGED_MODE
        if result < 0 and result != changed_mode:
            raise OSError(
                f"SoundCard COM initialization failed: 0x{result & 0xFFFFFFFF:08X}"
            )
        should_uninitialize = result in (0, 1)
        try:
            self._run_soundcard_initialized(sc)
        finally:
            if should_uninitialize:
                ole32.CoUninitialize()

    def _run_soundcard_initialized(self, sc) -> None:
        import numpy as np

        speaker = sc.default_speaker()
        if speaker is None:
            raise RuntimeError("no default output device")
        speaker_id = getattr(speaker, "id", None)
        if speaker_id is None:
            raise RuntimeError("default output device has no SoundCard identifier")
        microphone = sc.get_microphone(speaker_id, include_loopback=True)
        if microphone is None or not bool(getattr(microphone, "isloopback", True)):
            raise RuntimeError("no SoundCard WASAPI loopback device found")

        sample_rate = 48_000
        blocksize = max(256, int(sample_rate / max(5, self._fps)))
        smoothed = 0.0
        smoothed_spectrum = (0.0,) * self._spectrum_bands
        spectrum_error_reported = False

        # SoundCard documents unreliable Windows data for single-channel capture.
        # Use the first stereo pair and mix it to mono only for spectrum analysis.
        with microphone.recorder(
            samplerate=sample_rate,
            channels=[0, 1],
            blocksize=blocksize,
        ) as recorder:
            self._report_backend_ready(
                "SoundCard WASAPI loopback",
                str(getattr(speaker, "name", "") or "default output"),
            )
            discontinuity_warning = getattr(
                sc, "SoundcardRuntimeWarning", RuntimeWarning
            )
            while not self._stop.is_set():
                # WASAPI can report a harmless discontinuity while the shared
                # stream starts or the default device changes clocks. SoundCard
                # recovers internally; avoid flooding NC's system console.
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", discontinuity_warning)
                    audio = np.asarray(
                        recorder.record(numframes=blocksize),
                        dtype=np.float32,
                    )
                if audio.size <= 0:
                    raw = 0.0
                    mono = np.zeros(0, dtype=np.float32)
                else:
                    rms = float(np.sqrt(np.mean(np.square(audio))))
                    peak = float(np.max(np.abs(audio)))
                    raw = clamp_level((rms * 5.2) + (peak * 0.22))
                    mono = (
                        np.mean(audio, axis=1)
                        if audio.ndim > 1
                        else audio.reshape(-1)
                    )

                attack = 0.50 if raw > smoothed else 0.18
                smoothed = (smoothed * (1.0 - attack)) + (raw * attack)
                self._emit(smoothed)

                if self._spectrum_callback is not None and mono.size:
                    try:
                        target_spectrum = analyze_spectrum(
                            mono,
                            sample_rate,
                            self._spectrum_bands,
                        )
                        smoothed_spectrum = smooth_spectrum(
                            smoothed_spectrum,
                            target_spectrum,
                            0.46,
                        )
                        self._emit_spectrum(smoothed_spectrum)
                    except SpectrumAnalysisUnavailable as exc:
                        if not spectrum_error_reported:
                            spectrum_error_reported = True
                            self._logger(
                                f"[AI Presence] Computer audio spectrum unavailable: {exc}"
                            )
                    except Exception as exc:
                        if not spectrum_error_reported:
                            spectrum_error_reported = True
                            self._logger(
                                f"[AI Presence] Computer audio spectrum failed: {exc}"
                            )


def _default_wasapi_output_device(sd):
    devices = list(sd.query_devices() or [])
    hostapis = list(sd.query_hostapis() or [])

    def _is_wasapi_device(index) -> bool:
        try:
            hostapi = hostapis[int(devices[int(index)].get("hostapi", -1))]
            return "wasapi" in str(hostapi.get("name", "")).lower()
        except Exception:
            return False

    def _valid_output(index) -> bool:
        try:
            info = devices[int(index)]
            return int(info.get("max_output_channels") or 0) > 0
        except Exception:
            return False

    try:
        default_device = sd.default.device
        default_output = int(default_device[1] if isinstance(default_device, (list, tuple)) else default_device)
        if _valid_output(default_output) and _is_wasapi_device(default_output):
            return default_output, devices[default_output]
    except Exception:
        pass

    for api_index, hostapi in enumerate(hostapis):
        if "wasapi" not in str(hostapi.get("name", "")).lower():
            continue
        try:
            index = int(hostapi.get("default_output_device", -1))
            if _valid_output(index):
                return index, devices[index]
        except Exception:
            pass
        for index, info in enumerate(devices):
            if int(info.get("hostapi", -1)) == api_index and int(info.get("max_output_channels") or 0) > 0:
                return index, info

    raise RuntimeError("no WASAPI output device found for loopback capture")


def _sounddevice_loopback_settings(sd):
    settings_cls = getattr(sd, "WasapiSettings", None)
    if settings_cls is None:
        return None
    try:
        signature = inspect.signature(settings_cls)
        if "loopback" in signature.parameters:
            return settings_cls(loopback=True)
    except Exception:
        pass
    return None


def _sounddevice_virtual_output_input_device(sd):
    devices = list(sd.query_devices() or [])
    # These are genuine recording endpoints exposed by a driver. Do not treat
    # arbitrary devices containing "speaker" or "output" as loopback sources:
    # PortAudio may report input channels for virtual/bridge endpoints that
    # cannot actually be opened, producing PaErrorCode -9996 and no audio.
    preferred_terms = (
        "loopback",
        "stereo mix",
        "what u hear",
        "what you hear",
        "wave out",
        "output monitor",
        "monitor of",
    )
    candidates = []
    for index, info in enumerate(devices):
        try:
            if int(info.get("max_input_channels") or 0) <= 0:
                continue
        except Exception:
            continue
        name = str(info.get("name", "") or "").lower()
        if "steam streaming" in name:
            continue
        if any(term in name for term in preferred_terms) and "microphone" not in name:
            score = 0
            if "loopback" in name:
                score += 50
            if (
                "stereo mix" in name
                or "what u hear" in name
                or "what you hear" in name
            ):
                score += 45
            if "monitor" in name or "wave out" in name:
                score += 20
            candidates.append((score, index, info))
    if candidates:
        _score, index, info = sorted(candidates, reverse=True)[0]
        return index, info
    raise RuntimeError("no loopback/stereo-mix input device found for computer audio sync")
