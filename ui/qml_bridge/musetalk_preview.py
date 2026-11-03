"""Read-only frame selection for the native MuseTalk preview.

The runtime owns playback and its audio clock. This reader only follows that
clock and discovers frames appended to a streaming render's directory.
"""

from __future__ import annotations

import math
import time
from pathlib import Path

from core.runtime_files import list_png_frames
from core.musetalk_timing import start_musetalk_timing, trace_musetalk_timing


def _number(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _frame_ready(path):
    if not path:
        return False
    try:
        candidate = Path(path)
        if not candidate.is_file() or candidate.stat().st_size <= 0:
            return False
        if candidate.suffix.lower() == ".png":
            # MuseTalk writes PNGs while the speech buffer is growing. Reading
            # only the end marker avoids giving QML a still-incomplete image.
            with candidate.open("rb") as handle:
                handle.seek(-12, 2)
                return handle.read() == b"\x00\x00\x00\x00IEND\xaeB`\x82"
        return True
    except (OSError, ValueError):
        return False


class MuseTalkPreview:
    def __init__(self):
        self._key = None
        self._paths = []
        self._next_scan = 0.0
        self._last_frame = ("", 0)
        self._last_avatar_id = None
        self._timing_started = None
        self._hold_logged = False

    def current_frame(self, state, now, *, now_monotonic=None):
        from core.continuous_audio import continuous_media_seconds, continuous_pending_frame
        paths = list(state.get("frame_paths") or [])
        directory = str(state.get("frame_dir") or "")
        loop = bool(state.get("loop", False))
        pending = bool(state.get("audio_start_pending", False))
        avatar_id = state.get("avatar_id")
        trim = max(0, int(_number(state.get("trim_start_frames"))))
        key = (state.get("chunk_id"), state.get("sync_time"), directory, loop, trim, tuple(paths))
        if key != self._key:
            retain_last = (
                pending
                and self._last_avatar_id == avatar_id
                and _frame_ready(self._last_frame[0])
            )
            self._key = key
            self._paths = paths
            self._next_scan = 0.0
            if not retain_last:
                self._last_frame = ("", 0)
            self._timing_started = start_musetalk_timing()
            self._hold_logged = False
            trace_musetalk_timing("preview_state", self._timing_started, chunk=state.get("chunk_id"),
                                 state_age_ms=f"{max(0.0, now - _number(state.get('sync_time'), now)) * 1000:.1f}")

        expected = max(len(self._paths), int(_number(state.get("expected_frame_count"))))
        needs_progressive_frame = False
        if directory and state.get("progressive_audio", False) and not loop and not pending:
            media = continuous_media_seconds(
                state, time.monotonic() if now_monotonic is None else now_monotonic)
            fps = max(1, _number(state.get("fps"), 24) or 24)
            needs_progressive_frame = media is not None and int(media * fps) >= len(self._paths)
        # Explicit idle paths may be rotated or ping-pong ordered. Never sort
        # them again. Speech lists, however, may contain only the initial buffer.
        # A progressive parent outgrows its initial count; scan only when the
        # admitted audio clock needs a frame beyond the current cached window.
        if directory and (not self._paths or (not loop and len(self._paths) < expected)
                          or needs_progressive_frame) and now >= self._next_scan:
            scanned = list_png_frames(directory)
            if scanned:
                self._paths = scanned[min(trim, len(scanned) - 1):]
            self._next_scan = now + 0.04

        if not self._paths:
            path = str(state.get("frame_path") or state.get("image_path") or state.get("path") or "")
            return (path if _frame_ready(path) else "", 0)

        if pending:
            held = continuous_pending_frame(state)
            if held is not None and _frame_ready(held[0]):
                self._last_frame = held[:2]
                self._last_avatar_id = avatar_id
                return self._last_frame
            if _frame_ready(self._last_frame[0]):
                return self._last_frame
            for index, candidate in enumerate(self._paths):
                path = str(candidate or "")
                if _frame_ready(path):
                    self._last_frame = (path, index)
                    self._last_avatar_id = avatar_id
                    return self._last_frame
            return ("", 0)

        fps = max(1, _number(state.get("fps"), 24) or 24)
        sync_time = _number(state.get("sync_time"))
        elapsed = max(0.0, now - sync_time) if sync_time else 0.0
        media = None if loop else continuous_media_seconds(
            state, time.monotonic() if now_monotonic is None else now_monotonic)
        if media is not None:
            elapsed = media
        duration = _number(state.get("duration_seconds"))
        if not loop and duration > 0 and elapsed > duration + 0.1 and not self._hold_logged:
            self._hold_logged = True
            trace_musetalk_timing("preview_final_hold", self._timing_started, chunk=state.get("chunk_id"),
                                 overrun_ms=f"{(elapsed - duration) * 1000:.1f}",
                                 available=len(self._paths), expected=expected)
        if loop:
            index = int(elapsed * fps) % len(self._paths)
        elif media is not None:
            index = min(int(elapsed * fps), len(self._paths) - 1)
        elif duration > 0:
            count = max(expected, len(self._paths), 1)
            index = min(int(min(elapsed / duration, 1.0) * max(count - 1, 1)), len(self._paths) - 1)
        else:
            index = min(int(elapsed * fps), len(self._paths) - 1)
        path = str(self._paths[index] or "")
        if _frame_ready(path):
            self._last_frame = (path, index)
            self._last_avatar_id = avatar_id
            return self._last_frame
        # Hold only within the same playback state; reset/next chunk must not
        # resurrect the previous avatar. Retry this frame on the next tick.
        if _frame_ready(self._last_frame[0]):
            return self._last_frame
        return ("", index)

    @staticmethod
    def interval_ms(state):
        fps = min(120, max(1, _number(state.get("fps"), 24) or 24))
        return max(8, round(1000 / fps))
