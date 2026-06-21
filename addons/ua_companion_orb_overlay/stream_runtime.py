from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Optional

from addons.ua_companion_orb_overlay.named_pipe_transport import (
    MAX_FRAME_DIMENSION,
    NamedPipeFrameWriter,
)


SETTING_KEY = "ua_companion_orb_send_musetalk_face_mask"
MASK_SIZE_KEY = "ua_companion_orb_mask_size"
DEFAULT_MASK_SIZE = 1024

_writer_lock = threading.Lock()
_writer: Optional[NamedPipeFrameWriter] = None


def is_enabled(runtime_config: dict | None) -> bool:
    return bool((runtime_config or {}).get(SETTING_KEY, False))


def should_suppress_musetalk_preview(runtime_config: dict | None) -> bool:
    return is_enabled(runtime_config)


def target_mask_size(runtime_config: dict | None) -> int:
    raw_value = (runtime_config or {}).get(MASK_SIZE_KEY, DEFAULT_MASK_SIZE)
    try:
        value = int(raw_value or DEFAULT_MASK_SIZE)
    except (TypeError, ValueError):
        value = DEFAULT_MASK_SIZE
    return max(64, min(value, MAX_FRAME_DIMENSION))


def _writer_instance() -> NamedPipeFrameWriter:
    global _writer
    with _writer_lock:
        if _writer is None:
            _writer = NamedPipeFrameWriter()
        return _writer


def shutdown() -> None:
    global _writer
    with _writer_lock:
        writer = _writer
        _writer = None
    if writer is not None:
        writer.close()


def publish_gray_frame(
    gray8_pixels: bytes | bytearray | memoryview,
    *,
    width: int,
    height: int,
    frame_index: int = 0,
    runtime_config: dict | None = None,
    timestamp_seconds: Optional[float] = None,
    writer=None,
) -> bool:
    if not is_enabled(runtime_config):
        return False
    active_writer = writer if writer is not None else _writer_instance()
    return bool(
        active_writer.send_gray_frame(
            gray8_pixels,
            width=int(width),
            height=int(height),
            frame_index=int(frame_index or 0),
            timestamp_seconds=time.time() if timestamp_seconds is None else float(timestamp_seconds),
        )
    )


def _center_crop_square_array(array):
    height, width = array.shape[:2]
    side = min(width, height)
    x0 = max(0, (width - side) // 2)
    y0 = max(0, (height - side) // 2)
    return array[y0 : y0 + side, x0 : x0 + side]


def _load_with_cv2(frame_path: str, size: int):
    try:
        import cv2
    except Exception:
        return None
    image = cv2.imread(frame_path, cv2.IMREAD_COLOR)
    if image is None:
        return None
    image = _center_crop_square_array(image)
    if image.shape[0] != size or image.shape[1] != size:
        image = cv2.resize(image, (size, size), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return gray.tobytes(), size, size


def _load_with_qimage(frame_path: str, size: int):
    try:
        from PySide6 import QtCore, QtGui
    except Exception:
        return None
    image = QtGui.QImage(frame_path)
    if image.isNull():
        return None
    side = min(image.width(), image.height())
    if side <= 0:
        return None
    crop = image.copy((image.width() - side) // 2, (image.height() - side) // 2, side, side)
    scaled = crop.scaled(size, size, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation)
    gray = scaled.convertToFormat(QtGui.QImage.Format_Grayscale8)
    bytes_per_line = gray.bytesPerLine()
    ptr = gray.constBits()
    byte_count = int(gray.sizeInBytes())
    try:
        data = ptr.tobytes()
    except AttributeError:
        try:
            data = bytes(ptr[:byte_count])
        except Exception:
            try:
                ptr.setsize(byte_count)
            except Exception:
                pass
            data = bytes(ptr)
    rows = []
    for row in range(size):
        start = row * bytes_per_line
        rows.append(data[start : start + size])
    return b"".join(rows), size, size


def load_frame_as_gray8(frame_path: str | os.PathLike, *, runtime_config: dict | None = None):
    path = str(Path(frame_path))
    if not path or not os.path.isfile(path):
        return None
    size = target_mask_size(runtime_config)
    return _load_with_cv2(path, size) or _load_with_qimage(path, size)


def publish_frame_path(
    frame_path: str | os.PathLike,
    *,
    frame_index: int = 0,
    runtime_config: dict | None = None,
    timestamp_seconds: Optional[float] = None,
    writer=None,
) -> bool:
    if not is_enabled(runtime_config):
        return False
    loaded = load_frame_as_gray8(frame_path, runtime_config=runtime_config)
    if loaded is None:
        return False
    pixels, width, height = loaded
    return publish_gray_frame(
        pixels,
        width=width,
        height=height,
        frame_index=frame_index,
        runtime_config=runtime_config,
        timestamp_seconds=timestamp_seconds,
        writer=writer,
    )
