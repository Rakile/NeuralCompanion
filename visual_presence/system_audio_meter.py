"""Best-effort desktop/output audio meter for AI Presence music sync."""

from __future__ import annotations

import threading
import time
import inspect

from .audio_reactive_meter import clamp_level


class SystemAudioLevelMeter:
    """Poll Windows WASAPI loopback audio without touching the Qt UI thread."""

    def __init__(self, callback, *, fps=30, logger=print):
        self._callback = callback
        self._fps = max(5, min(30, int(fps or 30)))
        self._logger = logger if callable(logger) else print
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._pending_level = 0.0
        self._thread = None
        self.error = ""

    def start(self) -> None:
        if self.is_running():
            return
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

    def is_running(self) -> bool:
        thread = self._thread
        return bool(thread is not None and thread.is_alive())

    def set_fps(self, fps) -> None:
        try:
            self._fps = max(5, min(30, int(fps or 30)))
        except Exception:
            self._fps = 30

    def _emit(self, level) -> None:
        try:
            self._callback(clamp_level(level))
        except Exception:
            pass

    def _store_level(self, level) -> None:
        with self._lock:
            self._pending_level = clamp_level(level)

    def _read_level(self) -> float:
        with self._lock:
            return float(self._pending_level)

    def _run(self) -> None:
        smoothed = 0.0
        try:
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
                next_at = time.monotonic()
                while not self._stop.is_set():
                    raw = self._read_level()
                    attack = 0.50 if raw > smoothed else 0.18
                    smoothed = (smoothed * (1.0 - attack)) + (raw * attack)
                    self._emit(smoothed)
                    interval = 1.0 / max(5, min(30, int(self._fps or 30)))
                    next_at += interval
                    self._stop.wait(max(0.002, next_at - time.monotonic()))
        except Exception as exc:
            self.error = str(exc)
            try:
                self._logger(f"[AI Presence] Computer audio sync unavailable: {exc}")
            except Exception:
                pass
        finally:
            self._emit(0.0)


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
    preferred_terms = (
        "loopback",
        "stereo mix",
        "what u hear",
        "wave out",
        "monitor",
        "speaker",
        "speakers",
        "output",
    )
    candidates = []
    for index, info in enumerate(devices):
        try:
            if int(info.get("max_input_channels") or 0) <= 0:
                continue
        except Exception:
            continue
        name = str(info.get("name", "") or "").lower()
        if any(term in name for term in preferred_terms) and "microphone" not in name:
            score = 0
            if "loopback" in name:
                score += 50
            if "stereo mix" in name or "what u hear" in name:
                score += 45
            if "speaker" in name or "speakers" in name:
                score += 25
            if "monitor" in name or "output" in name or "wave out" in name:
                score += 20
            candidates.append((score, index, info))
    if candidates:
        _score, index, info = sorted(candidates, reverse=True)[0]
        return index, info
    raise RuntimeError("no loopback/stereo-mix input device found for computer audio sync")
