"""Cancellable local WAV playback acknowledged after the output device drains."""
import ctypes
import math
import sys
import threading
from contextlib import contextmanager


@contextmanager
def _audio_thread():
    if sys.platform != 'win32':
        yield
        return
    # WASAPI needs COM on every caller, not just the thread that first imported
    # PortAudio. Room HTTP requests use successive, short-lived threads.
    ole = ctypes.WinDLL('ole32')
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    result = ole.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED
    if result not in (0, 1, -2147417850):  # S_OK, S_FALSE, RPC_E_CHANGED_MODE
        raise OSError(f'Windows audio thread initialization failed: 0x{result & 0xffffffff:08x}')
    try:
        yield
    finally:
        if result in (0, 1):
            ole.CoUninitialize()  # Balance only this call; preserve an existing STA.


class CancellableWavPlayer:
    def __init__(self, *, sounddevice_module=None, soundfile_module=None):
        if sounddevice_module is None:
            import sounddevice as sounddevice_module
        if soundfile_module is None:
            import soundfile as soundfile_module
        self._sd = sounddevice_module
        self._sf = soundfile_module
        self.underruns = 0

    def _native_output(self, pcm, rate):
        """Stage PCM at the Windows mixer rate, outside the audio callback.

        Only translate an API's default to the same named WASAPI default.
        An explicitly selected different device must never be redirected.
        Device discovery/conversion is best effort; legacy output stays usable.
        """
        if sys.platform != 'win32':
            return pcm, rate, {}
        try:
            apis = self._sd.query_hostapis()
            device = self._sd.query_devices(kind='output')
            # 'high' is API-relative (e.g. MME 180 ms vs WASAPI 10 ms).
            # Preserve the original device's requested time margin when changing
            # API, rather than accidentally selecting a much smaller buffer.
            latency = self._sd.default.latency[1]
            if latency in ('low', 'high'):
                latency = device[f'default_{latency}_output_latency']
            latency = float(latency)
            if not math.isfinite(latency) or latency < 0:
                return pcm, rate, {}
            api = apis[device['hostapi']]
            if api['name'] != 'Windows WASAPI':
                if device['index'] != api['default_output_device']:
                    return pcm, rate, {}
                wasapi = next(item for item in apis if item['name'] == 'Windows WASAPI')
                candidate = self._sd.query_devices(wasapi['default_output_device'], kind='output')
                name = str(device['name']).strip().casefold()
                native_name = str(candidate['name']).strip().casefold()
                # MME truncates friendly device names to about 31 characters.
                if not name or not (name == native_name or (len(name) >= 30 and native_name.startswith(name))):
                    return pcm, rate, {}
                matches = [item for item in self._sd.query_devices()
                    if item['hostapi'] == candidate['hostapi'] and item['max_output_channels'] > 0
                    and (str(item['name']).strip().casefold() == name
                         or (len(name) >= 30 and str(item['name']).strip().casefold().startswith(name)))]
                if len(matches) != 1 or matches[0]['index'] != candidate['index']:
                    return pcm, rate, {}  # Friendly names cannot identify this device safely.
                device = candidate
            native_rate = int(round(float(device['default_samplerate'])))
            if native_rate <= 0 or device['max_output_channels'] < pcm.shape[1]:
                return pcm, rate, {}
            converted = pcm
            if native_rate != rate:
                from scipy.signal import resample_poly
                divisor = math.gcd(int(rate), native_rate)
                converted = resample_poly(pcm, native_rate // divisor, int(rate) // divisor, axis=0)
                converted = converted.astype('float32', copy=False)
            return converted, native_rate, {'device': device['index'], 'latency': latency}
        except Exception:
            return pcm, rate, {}  # Unavailable metadata/SciPy must not disable speech.

    def play(self, path, cancel):
        if cancel.is_set():
            return False
        with _audio_thread():
            return self._play(path, cancel)

    def _play(self, path, cancel):
        if cancel.is_set():
            return False
        pcm, rate = self._sf.read(str(path), dtype='float32', always_2d=True)
        if rate <= 0 or len(pcm) == 0:
            raise ValueError('The room audio file has no playable samples.')
        original_pcm, original_rate = pcm, rate
        pcm, rate, output_options = self._native_output(pcm, rate)
        if cancel.is_set():
            return False
        finished = threading.Event()
        offset = 0
        eof = False
        errors = []
        self.underruns = 0

        def callback(outdata, frames, _timing, status):
            nonlocal offset, eof
            try:
                outdata.fill(0)
                if cancel.is_set():
                    raise self._sd.CallbackAbort
                if getattr(status, 'output_underflow', False):
                    self.underruns += 1
                count = min(frames, len(pcm) - offset)
                outdata[:count] = pcm[offset:offset + count]
                offset += count
                if offset >= len(pcm):
                    eof = True
                    raise self._sd.CallbackStop
            except (self._sd.CallbackAbort, self._sd.CallbackStop):
                raise
            except Exception as error:
                errors.append(error)
                raise self._sd.CallbackAbort

        def open_stream():
            return self._sd.OutputStream(samplerate=rate, channels=pcm.shape[1], dtype='float32',
                                         callback=callback, finished_callback=finished.set, **output_options)

        try:
            stream = open_stream()
        except Exception:
            if not output_options:
                raise
            # Construction has not started playback: falling back cannot repeat
            # already-delivered speech. Never retry a callback/start failure.
            pcm, rate, output_options = original_pcm, original_rate, {}
            if cancel.is_set():
                return False
            stream = open_stream()
        with stream:
            while not finished.wait(.02):
                if cancel.is_set():
                    stream.abort()
                    break
        if errors:
            raise RuntimeError('Room audio output callback failed: ' + str(errors[0])) from errors[0]
        return eof and not cancel.is_set()
