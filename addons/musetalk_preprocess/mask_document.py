"""CPU-only MuseTalk mask editing document.

The native creator model owns this document.  It intentionally contains no Qt
types. Cropping and overlay arithmetic follow the retired QWidget editor;
add strokes accumulate mask strength once per drag.
"""

from __future__ import annotations

import copy
from typing import Any

import numpy as np


class MaskDocument:
    """Editable full-frame mask bound to one authoritative preview identity."""

    def __init__(self) -> None:
        self.clear()

    @property
    def identity(self) -> tuple[Any, ...] | None:
        return copy.deepcopy(self._identity)

    def clear(self) -> None:
        self._base_bgr: np.ndarray | None = None
        self._full_mask: np.ndarray | None = None
        self._bbox: tuple[int, int, int, int] | None = None
        self._crop_box: tuple[int, int, int, int] | None = None
        self._identity: tuple[Any, ...] | None = None
        self._stroke_base: np.ndarray | None = None
        self._stroke_accumulator: np.ndarray | None = None
        self._stroke_add = True

    @staticmethod
    def _box(value: Any, name: str) -> tuple[int, int, int, int]:
        try:
            items = tuple(int(item) for item in value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{name} must contain four integers.") from error
        if len(items) != 4:
            raise ValueError(f"{name} must contain four integers.")
        return items

    def load(
        self,
        *,
        base_bgr: np.ndarray,
        crop_mask: np.ndarray,
        bbox: Any,
        crop_box: Any,
        identity: tuple,
    ) -> None:
        self.clear()
        base = np.asarray(base_bgr)
        mask = np.asarray(crop_mask)
        if base.dtype != np.uint8 or base.ndim != 3 or base.shape[2] != 3:
            raise ValueError("base_bgr must be a uint8 BGR image.")
        if mask.dtype != np.uint8 or mask.ndim != 2:
            raise ValueError("crop_mask must be a uint8 grayscale image.")
        if not isinstance(identity, tuple):
            raise TypeError("identity must be a tuple.")
        bbox_values = self._box(bbox, "bbox")
        crop_values = self._box(crop_box, "crop_box")

        full_mask = np.zeros(base.shape[:2], dtype=np.uint8)
        x_s, y_s, x_e, y_e = crop_values
        dest_x1 = max(0, x_s)
        dest_y1 = max(0, y_s)
        dest_x2 = min(base.shape[1], x_e)
        dest_y2 = min(base.shape[0], y_e)
        if dest_x2 > dest_x1 and dest_y2 > dest_y1:
            src_x1 = dest_x1 - x_s
            src_y1 = dest_y1 - y_s
            src_x2 = min(mask.shape[1], src_x1 + (dest_x2 - dest_x1))
            src_y2 = min(mask.shape[0], src_y1 + (dest_y2 - dest_y1))
            dest_x2 = dest_x1 + (src_x2 - src_x1)
            dest_y2 = dest_y1 + (src_y2 - src_y1)
            if src_x2 > src_x1 and src_y2 > src_y1 and dest_x2 > dest_x1 and dest_y2 > dest_y1:
                full_mask[dest_y1:dest_y2, dest_x1:dest_x2] = mask[src_y1:src_y2, src_x1:src_x2]

        self._base_bgr = base.copy()
        self._full_mask = full_mask
        self._bbox = bbox_values
        self._crop_box = crop_values
        self._identity = copy.deepcopy(tuple(identity))
        self.end_stroke()

    def _require_loaded(self) -> tuple[np.ndarray, np.ndarray]:
        if self._base_bgr is None or self._full_mask is None:
            raise RuntimeError("No mask document is loaded.")
        return self._base_bgr, self._full_mask

    def begin_stroke(self, *, add: bool) -> None:
        _base, full_mask = self._require_loaded()
        self._stroke_base = full_mask.copy()
        self._stroke_accumulator = np.zeros_like(full_mask, dtype=np.uint8)
        self._stroke_add = bool(add)

    def paint(
        self,
        x: float,
        y: float,
        *,
        radius: int,
        feather: int,
        transparency: int,
    ) -> bool:
        _base, full_mask = self._require_loaded()
        if self._bbox is None or self._stroke_base is None or self._stroke_accumulator is None:
            return False
        image_x = float(x)
        image_y = float(y)
        if not np.isfinite(image_x) or not np.isfinite(image_y):
            return False
        x1, y1, x2, y2 = self._bbox
        if image_x < x1 or image_x > x2 or image_y < y1 or image_y > y2:
            return False

        radius_value = max(1, int(radius))
        feather_value = max(0, int(feather))
        transparency_value = max(0, min(99, int(transparency)))
        strength = max(1, 100 - transparency_value) / 100.0
        outer_radius = float(radius_value)
        inner_radius = max(0.0, float(radius_value - feather_value))
        x_start = max(0, int(image_x - radius_value), x1)
        y_start = max(0, int(image_y - radius_value), y1)
        x_end = min(full_mask.shape[1], int(image_x + radius_value + 1), x2 + 1)
        y_end = min(full_mask.shape[0], int(image_y + radius_value + 1), y2 + 1)
        if x_end <= x_start or y_end <= y_start:
            return False

        yy, xx = np.ogrid[y_start:y_end, x_start:x_end]
        distances = np.sqrt((xx - image_x) ** 2 + (yy - image_y) ** 2)
        alpha = np.zeros((y_end - y_start, x_end - x_start), dtype=np.float32)
        alpha[distances <= inner_radius] = 1.0
        if outer_radius > inner_radius:
            ring = (distances > inner_radius) & (distances <= outer_radius)
            alpha[ring] = (
                (outer_radius - distances[ring]) / max(0.001, outer_radius - inner_radius)
            ).astype(np.float32)
        elif inner_radius <= 0:
            alpha[distances <= outer_radius] = 1.0

        brush_values = np.clip(alpha * 255.0 * strength, 0, 255)
        # Round add strength so two half-strength strokes reach full coverage.
        # Keep the established subtraction quantization unchanged.
        brush_patch = (np.rint(brush_values) if self._stroke_add else brush_values).astype(np.uint8)
        acc_patch = self._stroke_accumulator[y_start:y_end, x_start:x_end]
        self._stroke_accumulator[y_start:y_end, x_start:x_end] = np.maximum(acc_patch, brush_patch)
        acc_patch = self._stroke_accumulator[y_start:y_end, x_start:x_end]
        if self._stroke_add:
            base_patch = self._stroke_base[y_start:y_end, x_start:x_end].astype(np.uint16)
            full_mask[y_start:y_end, x_start:x_end] = np.minimum(base_patch + acc_patch, 255).astype(np.uint8)
        else:
            base_patch = self._stroke_base[y_start:y_end, x_start:x_end].astype(np.float64)
            alpha_mask = acc_patch.astype(np.float64) / 255.0
            full_mask[y_start:y_end, x_start:x_end] = np.clip(
                base_patch * (1.0 - alpha_mask), 0, 255
            ).astype(np.uint8)
        return True

    def end_stroke(self) -> None:
        self._stroke_base = None
        self._stroke_accumulator = None

    def crop_mask(self) -> np.ndarray:
        _base, full_mask = self._require_loaded()
        if self._crop_box is None:
            raise RuntimeError("No mask document is loaded.")
        x_s, y_s, x_e, y_e = self._crop_box
        crop_width = max(1, x_e - x_s)
        crop_height = max(1, y_e - y_s)
        crop = np.zeros((crop_height, crop_width), dtype=np.uint8)
        source_x1 = max(0, x_s)
        source_y1 = max(0, y_s)
        source_x2 = min(full_mask.shape[1], x_e)
        source_y2 = min(full_mask.shape[0], y_e)
        if source_x2 > source_x1 and source_y2 > source_y1:
            dest_x1 = source_x1 - x_s
            dest_y1 = source_y1 - y_s
            dest_x2 = dest_x1 + (source_x2 - source_x1)
            dest_y2 = dest_y1 + (source_y2 - source_y1)
            crop[dest_y1:dest_y2, dest_x1:dest_x2] = full_mask[
                source_y1:source_y2, source_x1:source_x2
            ]
        return crop

    def overlay_rgb(self) -> np.ndarray:
        base_bgr, full_mask = self._require_loaded()
        alpha = (full_mask.astype(np.float32) / 255.0)[:, :, None] * 0.75
        overlay_color = np.zeros_like(base_bgr)
        overlay_color[:, :, 2] = 255
        overlay_color[:, :, 1] = 40
        overlay_bgr = (
            base_bgr.astype(np.float32) * (1.0 - alpha)
            + overlay_color.astype(np.float32) * alpha
        ).clip(0, 255).astype(np.uint8)
        return overlay_bgr[:, :, ::-1].copy()


__all__ = ["MaskDocument"]
