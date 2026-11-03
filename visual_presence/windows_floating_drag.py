"""Windows-only right-button dragging for an input-transparent Presence window.

The hook owns only right gestures starting over the visible window. It runs on
its own message-pump thread; all window moves return to Qt's owner thread.
"""
from __future__ import annotations

import sys
import threading
from PySide6 import QtCore, QtGui

_RIGHT_DOWN = 0x0204
_RIGHT_UP = 0x0205
_MOVE = 0x0200
# Keep ctypes callbacks alive until their native hook has actually been removed.
_NATIVE_CALLBACKS = {}


class _WindowsMouseApi:
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.c = ctypes
        self.w = wintypes
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        class MouseInfo(ctypes.Structure):
            _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD),
                        ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("extra", ctypes.c_size_t)]
        self.mouse_info = MouseInfo
        signatures = {
            "SetWindowsHookExW": ([ctypes.c_int, self.callback_type, wintypes.HINSTANCE, wintypes.DWORD], wintypes.HANDLE),
            "UnhookWindowsHookEx": ([wintypes.HANDLE], wintypes.BOOL),
            "CallNextHookEx": ([wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM], ctypes.c_ssize_t),
            "GetWindowRect": ([wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            "IsWindowVisible": ([wintypes.HWND], wintypes.BOOL),
            "WindowFromPoint": ([wintypes.POINT], wintypes.HWND),
            "GetAncestor": ([wintypes.HWND, wintypes.UINT], wintypes.HWND),
            "GetWindow": ([wintypes.HWND, wintypes.UINT], wintypes.HWND),
            "SetWindowPos": ([wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT], wintypes.BOOL),
            "PostThreadMessageW": ([wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL),
            "PeekMessageW": ([ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT], wintypes.BOOL),
            "GetMessageW": ([ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT], ctypes.c_int),
            "TranslateMessage": ([ctypes.POINTER(wintypes.MSG)], wintypes.BOOL),
            "DispatchMessageW": ([ctypes.POINTER(wintypes.MSG)], ctypes.c_ssize_t),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.user, name)
            function.argtypes = arguments
            function.restype = result
        self.kernel.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self.kernel.GetModuleHandleW.restype = wintypes.HMODULE
        self.kernel.GetCurrentThreadId.restype = wintypes.DWORD
        self.thread = None
        self.thread_id = 0
        self.handle = None
        self.ready = threading.Event()
        self.error = None

    def install(self, handler):
        if self.thread is not None and self.thread.is_alive():
            raise RuntimeError("Previous right-drag hook is still finishing")
        self.thread_id = 0
        def run():
            native_callback = None
            try:
                self.thread_id = self.kernel.GetCurrentThreadId()
                message = self.w.MSG()
                self.user.PeekMessageW(self.c.byref(message), None, 0, 0, 0)
                def dispatch(code, message_type, pointer):
                    if code >= 0 and message_type in {_RIGHT_DOWN, _RIGHT_UP, _MOVE}:
                        try:
                            info = self.c.cast(pointer, self.c.POINTER(self.mouse_info)).contents
                            if handler(int(message_type), int(info.pt.x), int(info.pt.y)):
                                return 1
                        except Exception:
                            pass  # Native errors must leave unrelated applications usable.
                    return self.user.CallNextHookEx(None, code, message_type, pointer)
                native_callback = self.callback_type(dispatch)
                self.handle = self.user.SetWindowsHookExW(
                    14, native_callback, self.kernel.GetModuleHandleW(None), 0
                )
                if not self.handle:
                    raise self.c.WinError(self.c.get_last_error())
                _NATIVE_CALLBACKS[int(self.handle)] = native_callback
                self.ready.set()
                while self.user.GetMessageW(self.c.byref(message), None, 0, 0) > 0:
                    self.user.TranslateMessage(self.c.byref(message))
                    self.user.DispatchMessageW(self.c.byref(message))
            except Exception as exc:
                self.error = exc
            finally:
                handle = self.handle
                if handle and self.user.UnhookWindowsHookEx(handle):
                    _NATIVE_CALLBACKS.pop(int(handle), None)
                self.handle = None
                self.ready.set()
        self.ready.clear()
        self.error = None
        self.thread = threading.Thread(target=run, name="NC Presence right drag", daemon=True)
        self.thread.start()
        if not self.ready.wait(2.0) or self.error or not self.handle:
            if self.thread_id:
                self.user.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)
            raise RuntimeError(f"Windows right-drag could not start: {self.error or 'message pump unavailable'}")
        return int(self.handle)

    def uninstall(self, handle):
        thread = self.thread
        if thread is None:
            return True
        self.user.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)
        thread.join(2.0)
        return not thread.is_alive()

    def rect(self, handle):
        rectangle = self.w.RECT()
        if not self.user.IsWindowVisible(handle) or not self.user.GetWindowRect(handle, self.c.byref(rectangle)):
            return None
        return rectangle.left, rectangle.top, rectangle.right, rectangle.bottom

    def hit_window(self, x, y):
        hit = self.user.WindowFromPoint(self.w.POINT(x, y))
        return int(self.user.GetAncestor(hit, 2) or 0) if hit else 0

    def previous(self, handle):
        return int(self.user.GetWindow(handle, 3) or 0)

    def move(self, handle, x, y):
        if not self.user.SetWindowPos(handle, None, x, y, 0, 0, 0x0015):
            raise self.c.WinError(self.c.get_last_error())


class WindowsFloatingDrag(QtCore.QObject):
    _position_requested = QtCore.Signal(int, object, int, int)
    _cleanup_requested = QtCore.Signal()
    drag_finished = QtCore.Signal()

    def __init__(self, parent=None, *, api=None, logger=None):
        super().__init__(parent)
        self._logger = logger or (lambda message: None)
        self._api = api
        self._lock = threading.RLock()
        self._hook = None
        self._window = 0
        self._enabled = False
        self._closed = False
        self._offset = None
        self._generation = 0
        self._drag_generation = None
        self._warned = False
        if self._api is None and sys.platform == "win32" and QtGui.QGuiApplication.platformName() == "windows":
            try:
                self._api = _WindowsMouseApi()
            except Exception as exc:
                self._logger(f"AI Presence right-drag unavailable: {exc}")
        self._position_requested.connect(self._move_window, QtCore.Qt.ConnectionType.QueuedConnection)
        self._cleanup_requested.connect(self._cleanup_hook, QtCore.Qt.ConnectionType.QueuedConnection)

    def configure(self, window, enabled):
        with self._lock:
            enabled = bool(enabled and not self._closed)
            if self._window != window or self._enabled != enabled:
                self._generation += 1
            self._window = int(window)
            self._enabled = enabled
            start = enabled and self._hook is None and self._api is not None
            cleanup = not enabled and self._offset is None
        if start:
            try:
                self._hook = self._api.install(self.handle_mouse)
            except Exception as exc:
                if not self._warned:
                    self._logger(f"AI Presence right-drag unavailable; click-through remains active: {exc}")
                    self._warned = True
        elif cleanup:
            self._cleanup_hook()

    def _start_rectangle(self, window, x, y):
        bounds = self._api.rect(window)
        if not bounds or not (bounds[0] <= x < bounds[2] and bounds[1] <= y < bounds[3]):
            return None
        hit = self._api.hit_window(x, y)
        if not hit:
            return None
        above = self._api.previous(window)
        seen = set()
        while above:
            if above == hit or above in seen or len(seen) >= 1024:
                return None
            seen.add(above)
            above = self._api.previous(above)
        return bounds

    def handle_mouse(self, message, x, y):
        if message == _RIGHT_DOWN:
            with self._lock:
                if self._closed or not self._enabled or self._api is None:
                    return False
                window, generation = self._window, self._generation
            # Never hold the state lock across native hit testing: Windows may
            # consult another window thread while the GUI is reconfiguring us.
            try:
                bounds = self._start_rectangle(window, x, y)
            except Exception:
                return False
            with self._lock:
                if not bounds or self._closed or not self._enabled or window != self._window or generation != self._generation:
                    return False
                self._generation += 1
                self._offset = (x-bounds[0], y-bounds[1])
                self._drag_generation = self._generation
                return True
        with self._lock:
            if self._closed:
                return False
            if message == _RIGHT_UP and self._offset is not None:
                offset = self._offset
                self._offset = None
                if self._enabled and self._drag_generation == self._generation:
                    self._position_requested.emit(self._generation, self._window, x-offset[0], y-offset[1])
                self._drag_generation = None
                self.drag_finished.emit()
                if not self._enabled:
                    self._cleanup_requested.emit()
                return True
            if self._enabled and message == _MOVE and self._offset is not None and self._drag_generation == self._generation:
                self._position_requested.emit(self._generation, self._window, x-self._offset[0], y-self._offset[1])
            return False

    @QtCore.Slot(int, object, int, int)
    def _move_window(self, generation, window, x, y):
        with self._lock:
            if self._closed or not self._enabled or generation != self._generation or window != self._window:
                return
        try:
            self._api.move(window, x, y)
        except Exception as exc:
            self._logger(f"AI Presence right-drag stopped: {exc}")
            self.configure(self._window, False)

    @QtCore.Slot()
    def _cleanup_hook(self):
        with self._lock:
            if self._enabled or self._offset is not None:
                return
            hook = self._hook
            self._hook = None
        if hook is not None and not self._api.uninstall(hook):
            self._logger("AI Presence right-drag cleanup is still finishing.")

    def close(self):
        with self._lock:
            self._closed = True
            self._enabled = False
            self._offset = None
            self._generation += 1
        self._cleanup_hook()
