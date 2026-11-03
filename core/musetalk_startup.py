"""Shared bounded timing policy for MuseTalk first-chunk handoff."""
from __future__ import annotations

from core.streaming_text import STREAM_FIRST_CHUNK_PLAN_SYNC_MAX_SECONDS


def first_chunk_plan_sync_wait_seconds(*, stream: bool, predicted_delay: float) -> float:
    if stream:
        return STREAM_FIRST_CHUNK_PLAN_SYNC_MAX_SECONDS
    return max(0.75, min(2.5, predicted_delay))
