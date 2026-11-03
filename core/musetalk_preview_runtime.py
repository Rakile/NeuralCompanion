"""Compatibility facade for MuseTalk preview-frame playback helpers."""

from __future__ import annotations

import importlib


def _preview_runtime():
    return importlib.import_module("addons.musetalk_avatar.preview_runtime")


def stream_musetalk_preview_frames(*args, **kwargs):
    return _preview_runtime().stream_musetalk_preview_frames(*args, **kwargs)


def stream_delegated_audio_progress(*args, **kwargs):
    return _preview_runtime().stream_delegated_audio_progress(*args, **kwargs)


def prime_musetalk_preview_frame(*args, **kwargs):
    return _preview_runtime().prime_musetalk_preview_frame(*args, **kwargs)


def estimate_displayed_musetalk_frames(*args, **kwargs):
    return _preview_runtime().estimate_displayed_musetalk_frames(*args, **kwargs)


def get_current_musetalk_source_index(*args, **kwargs):
    return _preview_runtime().get_current_musetalk_source_index(*args, **kwargs)


__all__ = [
    "estimate_displayed_musetalk_frames",
    "get_current_musetalk_source_index",
    "prime_musetalk_preview_frame",
    "stream_delegated_audio_progress",
    "stream_musetalk_preview_frames",
]
