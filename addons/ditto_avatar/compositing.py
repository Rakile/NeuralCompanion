"""Bounded cache of prepared-frame compositing mask regions."""
from collections import OrderedDict
import time

import cv2
import numpy as np

from core.utils.blend import blend_images_cy


class PreparedMaskCompositor:
    def __init__(self, original, budget_bytes=256*1024**2, max_entries=512, roi_blend=False):
        if type(budget_bytes) is not int or budget_bytes < 0 or type(max_entries) is not int or max_entries < 1:
            raise ValueError('Invalid mask-cache limits.')
        self.original = original
        self.template = original.mask_ori_float.copy()
        self.budget_bytes, self.max_entries, self.roi_blend = budget_bytes, max_entries, roi_blend
        self.regions = OrderedDict()
        self.cached_bytes = 0
        self.hits = self.misses = self.evictions = 0
        self.prepared_key = None

    def region(self, transform, width, height, allow_eviction=True):
        affine = np.asarray(transform)[:2, :]
        key = (width, height, affine.dtype.str, affine.shape, affine.tobytes())
        if key in self.regions:
            self.hits += 1
            region = self.regions.pop(key)
            self.regions[key] = region
            return region
        self.misses += 1
        full = cv2.warpAffine(self.template, affine, dsize=(width, height), flags=cv2.INTER_LINEAR).clip(0, 1)
        rows = np.flatnonzero(np.any(full != 0, axis=1))
        columns = np.flatnonzero(np.any(full != 0, axis=0))
        if len(rows):
            y, x = int(rows[0]), int(columns[0])
            # Own this allocation; a contiguous slice could otherwise retain the full-frame backing array.
            mask = full[y:int(rows[-1])+1, x:int(columns[-1])+1].copy(order='C')
        else:
            y = x = 0
            mask = np.empty((0, 0), dtype=full.dtype)
        region = (y, x, mask)
        if mask.nbytes <= self.budget_bytes:
            if not allow_eviction and (self.cached_bytes+mask.nbytes > self.budget_bytes
                                       or len(self.regions) >= self.max_entries):
                return region
            while self.regions and (self.cached_bytes+mask.nbytes > self.budget_bytes
                                    or len(self.regions) >= self.max_entries):
                _, old = self.regions.popitem(last=False)
                self.cached_bytes -= old[2].nbytes
                self.evictions += 1
            self.regions[key] = region
            self.cached_bytes += mask.nbytes
        return region

    def prepare(self, avatar_key, transforms, width, height):
        key = (avatar_key, width, height)
        if self.prepared_key == key:
            return 0.
        before = time.perf_counter()
        self.prepared_key = key
        for transform in transforms:
            misses, entries = self.misses, len(self.regions)
            self.region(transform, width, height, allow_eviction=False)
            if self.misses > misses and len(self.regions) == entries:
                break  # Full: let the playback-order LRU handle the remaining masks lazily.
        return time.perf_counter()-before

    def __call__(self, frame_rgb, render_image, transform):
        height, width = frame_rgb.shape[:2]
        y, x, mask = self.region(transform, width, height)
        rh, rw = mask.shape
        # Keep the original full-frame image warp: changing affine origin can change interpolation rounding.
        warped = cv2.warpAffine(render_image, transform[:2, :], dsize=(width, height), flags=cv2.INTER_LINEAR)
        if not self.roi_blend:
            full_mask = np.zeros((height, width), dtype=mask.dtype)
            full_mask[y:y+rh, x:x+rw] = mask
            result = np.empty((height, width, 3), dtype=np.uint8)
            blend_images_cy(full_mask, warped, frame_rgb, result)
        else:
            result = frame_rgb.copy()
            if mask.size:
                # The C blender requires contiguous output; never pass a strided result view.
                patch = np.empty((rh, rw, 3), dtype=np.uint8)
                blend_images_cy(mask, warped[y:y+rh, x:x+rw], frame_rgb[y:y+rh, x:x+rw], patch)
                result[y:y+rh, x:x+rw] = patch
        return result

    def summary(self):
        return dict(hits=self.hits, misses=self.misses, evictions=self.evictions,
                    cached_bytes=self.cached_bytes, entries=len(self.regions),
                    budget_bytes=self.budget_bytes, roi_blend=self.roi_blend)

    def clear(self):
        self.regions.clear()
        self.cached_bytes = 0
        self.prepared_key = None
