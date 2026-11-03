"""Reversible, process-owned window-affinity leases. No screenshot or UI policy."""
from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import sys
import threading

WDA_EXCLUDEFROMCAPTURE = 0x11

@dataclass(frozen=True)
class CaptureWindow:
    hwnd: int
    process_id: int
    thread_id: int

@dataclass(frozen=True)
class CaptureExclusionLease:
    token: int
    windows: tuple[CaptureWindow, ...]

class WindowAffinityBackend:
    def __init__(self):
        if sys.platform != 'win32' or sys.getwindowsversion().build < 19041:
            raise OSError('Window exclusion requires Windows 10 version 2004 or newer.')
        self.api = ctypes.WinDLL('user32', use_last_error=True)
        self.api.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        self.api.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.api.GetWindowDisplayAffinity.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        self.api.GetWindowDisplayAffinity.restype = wintypes.BOOL
        self.api.SetWindowDisplayAffinity.argtypes = (wintypes.HWND, wintypes.DWORD)
        self.api.SetWindowDisplayAffinity.restype = wintypes.BOOL

    def identity(self, hwnd):
        pid = wintypes.DWORD()
        tid = self.api.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return CaptureWindow(hwnd, pid.value, tid) if tid else None

    def get_affinity(self, hwnd):
        value = wintypes.DWORD()
        if not self.api.GetWindowDisplayAffinity(hwnd, ctypes.byref(value)):
            raise ctypes.WinError(ctypes.get_last_error())
        return value.value

    def set_affinity(self, hwnd, value):
        if not self.api.SetWindowDisplayAffinity(hwnd, value):
            raise ctypes.WinError(ctypes.get_last_error())

class CaptureExclusionManager:
    def __init__(self, backend, process_id):
        self.backend, self.process_id = backend, process_id
        self._lock = threading.RLock()
        self._windows = {}  # identity -> [prior affinity, reference count]
        self._leases = {}
        self._serial = 0

    def acquire(self, windows):
        with self._lock:
            acquired = []
            try:
                for window in dict.fromkeys(windows):
                    if window.process_id != self.process_id or self.backend.identity(window.hwnd) != window:
                        raise OSError('Capture exclusion window ownership changed.')
                    if window not in self._windows:
                        prior = self.backend.get_affinity(window.hwnd)
                        self.backend.set_affinity(window.hwnd, WDA_EXCLUDEFROMCAPTURE)
                        self._windows[window] = [prior, 0]
                    self._windows[window][1] += 1
                    acquired.append(window)
            except Exception:
                # Keep failed restorations registered for shutdown/retry.
                self._release_windows(acquired)
                raise
            self._serial += 1
            lease = CaptureExclusionLease(self._serial, tuple(acquired))
            self._leases[lease.token] = lease
            return lease

    def _restore(self, window):
        prior, count = self._windows[window]
        if count:
            return
        if self.backend.identity(window.hwnd) == window:
            self.backend.set_affinity(window.hwnd, prior)
        del self._windows[window]

    def _release_windows(self, windows):
        errors = []
        for window in reversed(windows):
            if window not in self._windows:
                continue
            self._windows[window][1] = max(0, self._windows[window][1] - 1)
            try:
                self._restore(window)
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise OSError(f'NC affinity restoration failed for {len(errors)} window(s).') from errors[0]

    def release(self, lease):
        with self._lock:
            saved = self._leases.pop(lease.token, None)
            if saved:
                self._release_windows(saved.windows)

    def retire_window(self, window):
        """Qt reports this native incarnation is ending; never touch its successor."""
        with self._lock:
            self._windows.pop(window, None)
            for token, lease in tuple(self._leases.items()):
                if window in lease.windows:
                    self._leases[token] = CaptureExclusionLease(token,
                        tuple(item for item in lease.windows if item != window))

    def restore_all(self):
        with self._lock:
            self._leases.clear()
            for state in self._windows.values():
                state[1] = 0
            self._release_windows(tuple(self._windows))
