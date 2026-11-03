from __future__ import annotations

import ctypes
import os
import struct
import threading
import time
from ctypes import wintypes
from typing import Optional


PIPE_NAME = r"\\.\pipe\ua_companion_orb_overlay_matrix_face"
FRAME_MAGIC = 0x55434F4D  # UCOM
FRAME_VERSION = 1
FRAME_HEADER_FORMAT = "<IHHIIIQdII"
FRAME_HEADER_SIZE = struct.calcsize(FRAME_HEADER_FORMAT)
MAX_FRAME_DIMENSION = 2048
PIXEL_FORMAT_GRAY8 = 0
PIXEL_FORMAT_BGRA8 = 1


def _bytes_per_pixel(pixel_format: int) -> int:
    return 4 if int(pixel_format) == PIXEL_FORMAT_BGRA8 else 1


def pack_frame_message(
    pixels: bytes | bytearray | memoryview,
    *,
    width: int,
    height: int,
    frame_index: int = 0,
    timestamp_seconds: Optional[float] = None,
    pixel_format: int = PIXEL_FORMAT_GRAY8,
    stride: Optional[int] = None,
    flags: Optional[int] = None,
) -> bytes:
    width = int(width)
    height = int(height)
    if width <= 0 or height <= 0 or width > MAX_FRAME_DIMENSION or height > MAX_FRAME_DIMENSION:
        raise ValueError(f"Invalid Ua Companion Orb frame dimensions: {width}x{height}")
    pixel_format = int(pixel_format)
    bytes_per_pixel = _bytes_per_pixel(pixel_format)
    stride = int(stride or (width * bytes_per_pixel))
    if stride < width * bytes_per_pixel:
        raise ValueError(f"Invalid Ua Companion Orb frame stride: {stride}")
    payload = bytes(pixels)
    expected = stride * height
    if len(payload) != expected:
        raise ValueError(f"Invalid Ua Companion Orb frame payload size: {len(payload)} != {expected}")
    timestamp = time.time() if timestamp_seconds is None else float(timestamp_seconds)
    frame_flags = pixel_format if flags is None else int(flags)
    header = struct.pack(
        FRAME_HEADER_FORMAT,
        FRAME_MAGIC,
        FRAME_VERSION,
        FRAME_HEADER_SIZE,
        width,
        height,
        stride,
        int(frame_index) & 0xFFFFFFFFFFFFFFFF,
        timestamp,
        len(payload),
        frame_flags & 0xFFFFFFFF,
    )
    return header + payload


class NamedPipeFrameWriter:
    """Best-effort Windows named-pipe client for live Matrix face masks."""

    def __init__(self, pipe_name: str = PIPE_NAME, connect_timeout_ms: int = 4):
        self.pipe_name = str(pipe_name or PIPE_NAME)
        self.connect_timeout_ms = max(0, int(connect_timeout_ms))
        self._handle = None
        self._lock = threading.Lock()
        self._kernel32 = ctypes.windll.kernel32 if os.name == "nt" else None
        if self._kernel32 is not None:
            self._kernel32.CreateFileW.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.LPVOID,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.HANDLE,
            ]
            self._kernel32.CreateFileW.restype = wintypes.HANDLE
            self._kernel32.WriteFile.argtypes = [
                wintypes.HANDLE,
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD),
                wintypes.LPVOID,
            ]
            self._kernel32.WriteFile.restype = wintypes.BOOL
            self._kernel32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
            self._kernel32.WaitNamedPipeW.restype = wintypes.BOOL
            self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            self._kernel32.CloseHandle.restype = wintypes.BOOL

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def _close_locked(self) -> None:
        handle = self._handle
        self._handle = None
        handle_value = getattr(handle, "value", handle)
        if handle_value and self._kernel32 is not None:
            try:
                self._kernel32.CloseHandle(handle)
            except Exception:
                pass

    def _connect_locked(self) -> bool:
        if self._kernel32 is None:
            return False
        if self._handle:
            return True
        self._kernel32.WaitNamedPipeW(self.pipe_name, self.connect_timeout_ms)
        generic_write = 0x40000000
        open_existing = 3
        file_attribute_normal = 0x80
        handle = self._kernel32.CreateFileW(
            self.pipe_name,
            generic_write,
            0,
            None,
            open_existing,
            file_attribute_normal,
            None,
        )
        invalid_handle = ctypes.c_void_p(-1).value
        handle_value = getattr(handle, "value", handle)
        if not handle_value or int(handle_value) == int(invalid_handle):
            self._handle = None
            return False
        self._handle = handle
        return True

    def send_gray_frame(
        self,
        gray8_pixels: bytes | bytearray | memoryview,
        *,
        width: int,
        height: int,
        frame_index: int = 0,
        timestamp_seconds: Optional[float] = None,
    ) -> bool:
        message = pack_frame_message(
            gray8_pixels,
            width=width,
            height=height,
            frame_index=frame_index,
            timestamp_seconds=timestamp_seconds,
            pixel_format=PIXEL_FORMAT_GRAY8,
        )
        return self._send_message(message)

    def send_bgra_frame(
        self,
        bgra8_pixels: bytes | bytearray | memoryview,
        *,
        width: int,
        height: int,
        frame_index: int = 0,
        timestamp_seconds: Optional[float] = None,
    ) -> bool:
        message = pack_frame_message(
            bgra8_pixels,
            width=width,
            height=height,
            frame_index=frame_index,
            timestamp_seconds=timestamp_seconds,
            pixel_format=PIXEL_FORMAT_BGRA8,
        )
        return self._send_message(message)

    def _send_message(self, message: bytes) -> bool:
        with self._lock:
            if not self._connect_locked():
                return False
            written = wintypes.DWORD(0)
            buffer = ctypes.create_string_buffer(message)
            ok = bool(
                self._kernel32.WriteFile(
                    self._handle,
                    buffer,
                    len(message),
                    ctypes.byref(written),
                    None,
                )
            )
            if not ok or int(written.value) != len(message):
                self._close_locked()
                return False
            return True
