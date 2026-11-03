"""Bounded, private PCM sources for negotiated audio-only phone replies.

The gateway authenticates each read before entering this store. These cursors
are delivery positions, never proof that the phone has played any audio.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import threading
import time

from core.incremental_audio import IncrementalAudioSource

MAX_FRAMES = 1_440_000
READ_FRAMES = 12_000
MAX_SOURCES = 8
LEASE_SECONDS = 900


@dataclass
class _Source:
    request_id: str
    sequence: int
    pcm: IncrementalAudioSource
    deadline: float
    finalized: bool = False


class ProgressivePhoneAudioStore:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.RLock()
        self._sources: dict[str, _Source] = {}

    def _expire(self):
        for key, entry in tuple(self._sources.items()):
            if self._clock() >= entry.deadline:
                del self._sources[key]
                entry.pcm.close()

    def admit(self, request_id, audio_id, sequence, source) -> bool:
        if (not isinstance(source, IncrementalAudioSource) or source.sample_rate != 24000
                or source.channels != 1 or not source.ready or source.cancelled
                or source.error is not None or source.frame_count > MAX_FRAMES):
            return False
        with self._lock:
            self._expire()
            if audio_id in self._sources or len(self._sources) >= MAX_SOURCES:
                return False
            self._sources[audio_id] = _Source(request_id, sequence, source, self._clock()+LEASE_SECONDS)
            return True

    def matches(self, request_id, audio_id, sequence, source) -> bool:
        with self._lock:
            self._expire()
            entry = self._sources.get(audio_id)
            return bool(entry and entry.request_id == request_id and entry.sequence == sequence
                        and entry.pcm is source)

    def finalize(self, request_id, audio_id, sequence, source):
        with self._lock:
            if not self.matches(request_id, audio_id, sequence, source) or not source.succeeded:
                raise ValueError('Progressive audio unavailable')
            self._sources[audio_id].finalized = True

    def read(self, request_id, audio_id, sequence, cursor):
        if type(cursor) is not int or not 0 <= cursor <= MAX_FRAMES:
            raise ValueError('Invalid progressive cursor')
        with self._lock:
            self._expire()
            entry = self._sources.get(audio_id)
            if not entry or entry.request_id != request_id or entry.sequence != sequence:
                raise ValueError('Progressive audio unavailable')
            source = entry.pcm
            if source.cancelled or source.closed or source.error is not None:
                raise ValueError('Progressive audio failed')
            frames = source.frame_count
            if frames > MAX_FRAMES or cursor > frames:
                raise ValueError('Invalid progressive cursor')
            pcm = source.read_frames(cursor, READ_FRAMES)
            next_cursor = cursor + len(pcm)//2
            return dict(version=1, sample_rate=24000, channels=1, cursor=cursor,
                        next_cursor=next_cursor, pcm_base64=base64.b64encode(pcm).decode('ascii'),
                        finished=bool(entry.finalized and source.succeeded and next_cursor == frames),
                        total_frames=frames if entry.finalized else None)

    def release_reply(self, request_id, completed_sequence=None):
        with self._lock:
            for key, entry in tuple(self._sources.items()):
                if entry.request_id == request_id and (completed_sequence is None or entry.sequence <= completed_sequence):
                    del self._sources[key]
                    entry.pcm.close()

    def close(self):
        with self._lock:
            for entry in self._sources.values():
                entry.pcm.close()
            self._sources.clear()
