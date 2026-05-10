"""Compatibility facade for MuseTalk preview-frame playback helpers."""

from __future__ import annotations

from addons.musetalk_avatar.preview_runtime import (
    estimate_displayed_musetalk_frames,
    get_current_musetalk_source_index,
    prime_musetalk_preview_frame,
    stream_delegated_audio_progress,
    stream_musetalk_preview_frames,
)

__all__ = [
    "estimate_displayed_musetalk_frames",
    "get_current_musetalk_source_index",
    "prime_musetalk_preview_frame",
    "stream_delegated_audio_progress",
    "stream_musetalk_preview_frames",
]
