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
FRAME_FIT_KEY = "ua_companion_orb_frame_fit"
FRAME_FIT_NATIVE = "native"
FRAME_FIT_SQUARE = "square"
DEFAULT_MASK_SIZE = 1024

_writer_lock = threading.Lock()
_writer: Optional[NamedPipeFrameWriter] = None


def is_enabled(runtime_config: dict | None) -> bool:
    return bool((runtime_config or {}).get(SETTING_KEY, False))


def should_suppress_musetalk_preview(runtime_config: dict | None) -> bool:
    return is_enabled(runtime_config)


def target_mask_size() -> int:
    """Return the private transport cap used by the Orb frame bridge.

    Mask dimensions are an implementation detail of the named-pipe transport,
    not a user-facing runtime preference. Keeping the cap internal prevents
    stale presets from changing the memory cost of every streamed frame.
    """

    return min(DEFAULT_MASK_SIZE, MAX_FRAME_DIMENSION)


def frame_fit_mode(runtime_config: dict | None) -> str:
    raw_value = str((runtime_config or {}).get(FRAME_FIT_KEY, FRAME_FIT_NATIVE) or FRAME_FIT_NATIVE).strip().lower()
    if raw_value in {"square", "crop", "square_crop", "square-crop"}:
        return FRAME_FIT_SQUARE
    return FRAME_FIT_NATIVE


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


def publish_bgra_frame(
    bgra8_pixels: bytes | bytearray | memoryview,
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
        active_writer.send_bgra_frame(
            bgra8_pixels,
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


def _native_target_size(width: int, height: int, max_size: int) -> tuple[int, int]:
    width = max(1, int(width))
    height = max(1, int(height))
    max_size = max(1, int(max_size))
    largest = max(width, height)
    if largest <= max_size:
        return width, height
    scale = float(max_size) / float(largest)
    return max(1, round(width * scale)), max(1, round(height * scale))


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


def _load_bgra_with_cv2(frame_path: str, size: int, *, fit_mode: str = FRAME_FIT_NATIVE):
    try:
        import cv2
    except Exception:
        return None
    image = cv2.imread(frame_path, cv2.IMREAD_UNCHANGED)
    if image is None:
        return None
    if fit_mode == FRAME_FIT_SQUARE:
        image = _center_crop_square_array(image)
        target_width, target_height = size, size
    else:
        target_width, target_height = _native_target_size(image.shape[1], image.shape[0], size)
    if image.shape[0] != target_height or image.shape[1] != target_width:
        image = cv2.resize(image, (target_width, target_height), interpolation=cv2.INTER_AREA)
    if len(image.shape) == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGRA)
    elif image.shape[2] == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
    elif image.shape[2] != 4:
        return None
    return image.tobytes(), target_width, target_height


def _load_with_pillow(frame_path: str, size: int):
    try:
        from PIL import Image
    except Exception:
        return None
    try:
        image = Image.open(frame_path)
    except Exception:
        return None
    side = min(image.width, image.height)
    if side <= 0:
        return None
    left = (image.width - side) // 2
    top = (image.height - side) // 2
    resampling = getattr(Image, "Resampling", Image).LANCZOS
    gray = image.crop((left, top, left + side, top + side)).resize(
        (size, size),
        resampling,
    ).convert("L")
    return gray.tobytes(), size, size


def _load_bgra_with_pillow(frame_path: str, size: int, *, fit_mode: str = FRAME_FIT_NATIVE):
    try:
        from PIL import Image
    except Exception:
        return None
    try:
        image = Image.open(frame_path)
    except Exception:
        return None
    if fit_mode == FRAME_FIT_SQUARE:
        side = min(image.width, image.height)
        if side <= 0:
            return None
        left = (image.width - side) // 2
        top = (image.height - side) // 2
        image = image.crop((left, top, left + side, top + side))
        target_width, target_height = size, size
    else:
        target_width, target_height = _native_target_size(image.width, image.height, size)
    resampling = getattr(Image, "Resampling", Image).LANCZOS
    bgra = image.resize((target_width, target_height), resampling).convert("RGBA")
    return bgra.tobytes("raw", "BGRA"), target_width, target_height


def load_frame_as_gray8(frame_path: str | os.PathLike, *, runtime_config: dict | None = None):
    path = str(Path(frame_path))
    if not path or not os.path.isfile(path):
        return None
    size = target_mask_size()
    return _load_with_cv2(path, size) or _load_with_pillow(path, size)


def load_frame_as_bgra8(frame_path: str | os.PathLike, *, runtime_config: dict | None = None):
    path = str(Path(frame_path))
    if not path or not os.path.isfile(path):
        return None
    size = target_mask_size()
    fit_mode = frame_fit_mode(runtime_config)
    return _load_bgra_with_cv2(path, size, fit_mode=fit_mode) or _load_bgra_with_pillow(path, size, fit_mode=fit_mode)


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
    loaded = load_frame_as_bgra8(frame_path, runtime_config=runtime_config)
    if loaded is not None:
        pixels, width, height = loaded
        return publish_bgra_frame(
            pixels,
            width=width,
            height=height,
            frame_index=frame_index,
            runtime_config=runtime_config,
            timestamp_seconds=timestamp_seconds,
            writer=writer,
        )
    loaded_gray = load_frame_as_gray8(frame_path, runtime_config=runtime_config)
    if loaded_gray is None:
        return False
    pixels, width, height = loaded_gray
    return publish_gray_frame(
        pixels,
        width=width,
        height=height,
        frame_index=frame_index,
        runtime_config=runtime_config,
        timestamp_seconds=timestamp_seconds,
        writer=writer,
    )
