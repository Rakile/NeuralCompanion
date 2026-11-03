"""Owned Windows event for cancellation without a background stdin reader."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import math
import uuid


class NamedCancellation:
    def __init__(self, handle, name, kernel):
        self.handle, self.name, self.kernel = handle, name, kernel

    @staticmethod
    def _kernel():
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateEventW.restype = wintypes.HANDLE
        kernel.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.OpenEventW.restype = wintypes.HANDLE
        for name in ('SetEvent', 'ResetEvent', 'CloseHandle'):
            function = getattr(kernel, name)
            function.argtypes = [wintypes.HANDLE]
            function.restype = wintypes.BOOL
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        return kernel

    @classmethod
    def create(cls):
        kernel = cls._kernel()
        name = 'Local\\NC.LiquidAITTS.' + uuid.uuid4().hex
        handle = kernel.CreateEventW(None, True, False, name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return cls(handle, name, kernel)

    @classmethod
    def open(cls, name):
        kernel = cls._kernel()
        handle = kernel.OpenEventW(0x00100000, False, str(name))  # synchronize only
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return cls(handle, str(name), kernel)

    def set(self):
        if not self.kernel.SetEvent(self.handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def reset(self):
        if not self.kernel.ResetEvent(self.handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def wait(self, timeout=None):
        milliseconds = 0xFFFFFFFF if timeout is None else min(0xFFFFFFFE, math.ceil(max(0., timeout)*1000))
        result = self.kernel.WaitForSingleObject(self.handle, milliseconds)
        if result == 0:
            return True
        if result == 258:
            return False
        raise ctypes.WinError(ctypes.get_last_error())

    def is_set(self):
        return self.wait(0.)

    def close(self):
        if self.handle:
            if not self.kernel.CloseHandle(self.handle):
                raise ctypes.WinError(ctypes.get_last_error())
            self.handle = None
