"""Bounded media-clock primitives, not an authorization or playback receipt layer.

Each peer owns its tracks and epoch. Codec/timeline work runs serially off the
asyncio/Qt threads. The control layer must admit native source bounds before
committing speech; successful packet production never means it was heard.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
from dataclasses import dataclass, field
import logging
import itertools
import threading
import time

import av
from aiortc import MediaStreamTrack
from aiortc.mediastreams import MediaStreamError

from .opus_encoding import OpusSpeechEncoder, PACKET_SAMPLES, RATE, TIME_BASE
from .h264_encoding import AvatarVideoEncoder
from .media_diagnostics import avatar_event


MAX_PCM_BYTES = 64 * 1024 * 1024
MAX_LATENESS = 0.1
_log = logging.getLogger(__name__)
_video_ids = itertools.count(1)


class MediaEpoch:
    def __init__(self, start: float | None = None):
        self._start = start

    @property
    def start(self):
        # Arm only when media starts, never while ICE/DTLS is still negotiating.
        if self._start is None:
            self._start = time.monotonic()
        return self._start

    def deadline(self, timestamp: int, rate: int) -> float:
        return self.start + timestamp / rate


@dataclass
class _Reservation:
    first: int
    samples: int
    pcm: bytes
    state: str = 'prepared'
    revoked: threading.Event = field(default_factory=threading.Event)


class SpeechTimeline:
    """Single-worker PCM schedule. Integer lifetime keys must strictly increase."""

    def __init__(self, *, cancelled=lambda: False, bitrate=32000):
        self.encoder = OpusSpeechEncoder(cancelled=cancelled, bitrate=bitrate)
        self.leading_samples = self.encoder.leading_samples
        self.next_sample = 0
        self._last_key = 0
        self._reservations: dict[int, _Reservation] = {}

    def _descriptor(self, entry):
        return {'first_sample': entry.first + self.leading_samples,
                'end_sample': entry.first + entry.samples + self.leading_samples}

    def reserve(self, key: int, pcm: bytes, first: int, revoked=None) -> dict:
        if (type(key) is not int or key <= 0 or type(first) is not int or first < 0
                or not isinstance(pcm, bytes) or not pcm or len(pcm) % 2
                or len(pcm) > MAX_PCM_BYTES):
            raise ValueError('Invalid speech reservation')
        existing = self._reservations.get(key)
        if existing:
            if existing.state == 'prepared' and existing.first == first and existing.pcm == pcm:
                return self._descriptor(existing)
            raise ValueError('Conflicting speech reservation')
        if key <= self._last_key or first < self.next_sample or first > self.next_sample + 600 * RATE:
            raise ValueError('Stale speech reservation')
        if (len(self._reservations) >= 2
                or len(pcm) + sum(len(r.pcm) for r in self._reservations.values()) > MAX_PCM_BYTES):
            raise ValueError('Speech reservation capacity')
        end = first + len(pcm) // 2
        if any(first < r.first + r.samples and end > r.first for r in self._reservations.values()):
            raise ValueError('Overlapping speech reservations')
        entry = _Reservation(first, len(pcm) // 2, pcm)
        if revoked is not None:
            entry.revoked = revoked
        self._reservations[key] = entry
        self._last_key = key
        return self._descriptor(entry)

    def commit(self, key: int):
        entry = self._reservations[key]
        if entry.state == 'admitted':
            return
        if entry.state != 'prepared' or entry.first < self.next_sample:
            raise ValueError('Speech admission deadline or lifetime ended')
        entry.state = 'admitted'

    def cancel(self, key: int):
        entry = self._reservations.get(key)
        if entry:
            entry.revoked.set()
            entry.state = 'stopped'
            entry.pcm = b''

    def retire(self, key: int):
        entry = self._reservations.pop(key, None)
        if entry:
            entry.revoked.set()

    def state(self, key: int) -> str:
        return self._reservations[key].state

    def transmission_allowed(self, first: int, count: int) -> bool:
        # Opus output includes encoder lookahead. A produced reservation retains
        # its bounds until retirement so its final delayed samples can be sent.
        return any(not event.is_set() for event in self.transmission_permissions(first, count))

    def transmission_permissions(self, first, count):
        return tuple(entry.revoked for entry in self._reservations.values()
                   if entry.state in {'admitted', 'produced'}
                   # NetEq pulls 10ms output blocks; a partial last block can
                   # otherwise be marked PLC even with all source RTP received.
                   # One bounded packet drains it. This is not idle keepalive;
                   # source/heard bounds stay unchanged and revocation still wins.
                   and first < entry.first + entry.samples + self.leading_samples + PACKET_SAMPLES
                   and first + count > entry.first + self.leading_samples)

    def packet_with_permission(self):
        packet = self.packet()
        return packet, self.transmission_permissions(packet.pts, PACKET_SAMPLES)

    def packet(self):
        first = self.next_sample
        end = first + PACKET_SAMPLES
        pcm = bytearray(PACKET_SAMPLES * 2)
        for entry in self._reservations.values():
            if entry.state == 'prepared' and entry.first < end:
                entry.state = 'expired'
                entry.pcm = b''
            if entry.state != 'admitted':
                continue
            begin = max(first, entry.first)
            finish = min(end, entry.first + entry.samples)
            if begin < finish:
                pcm[(begin-first)*2:(finish-first)*2] = entry.pcm[(begin-entry.first)*2:(finish-entry.first)*2]
            if end >= entry.first + entry.samples:
                entry.state = 'produced'
                entry.pcm = b''
        frame = av.AudioFrame(format='s16', layout='mono', samples=PACKET_SAMPLES)
        frame.planes[0].update(pcm)
        frame.sample_rate = RATE
        frame.time_base = TIME_BASE
        frame.pts = first
        packets = list(self.encoder.encode_chunk([frame]))
        if len(packets) != 1 or packets[0].pts != first:
            raise RuntimeError('Continuous Opus clock failed')
        self.next_sample = end
        return packets[0]


class PacedSpeechTrack(MediaStreamTrack):
    kind = 'audio'

    def __init__(self, epoch: MediaEpoch, *, bitrate=32000):
        super().__init__()
        self.epoch = epoch
        self.bitrate = bitrate
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='nc-opus')
        self._cancelled = threading.Event()
        self._stopped = asyncio.Event()
        self._timeline = None
        self._next_sample = 0
        self._receiving = False
        self._revocations = {}
        self._last_delivery = None

    def _invoke(self, name, args):
        if self._cancelled.is_set():
            raise MediaStreamError
        if self._timeline is None:
            self._timeline = SpeechTimeline(cancelled=self._cancelled.is_set, bitrate=self.bitrate)
        return getattr(self._timeline, name)(*args)

    async def _call(self, name, *args):
        if self.readyState != 'live':
            raise MediaStreamError
        try:
            result = await asyncio.get_running_loop().run_in_executor(self._executor, self._invoke, name, args)
        except Exception:
            if self.readyState != 'live':
                raise MediaStreamError from None
            raise
        if self.readyState != 'live':
            raise MediaStreamError
        return result

    async def reserve(self, key, pcm, first):
        # Tokens are revoked on the event loop before any queued worker work.
        # The worker returns only immutable bounds-derived tokens, never mutable
        # timeline state. A cancelled in-flight encode cannot leak its packet.
        existing = self._revocations.get(key)
        token = existing if existing is not None else threading.Event()
        self._revocations[key] = token
        try:
            result = await self._call('reserve', key, pcm, first, token)
            _log.info('audio_reservation key=%d first=%d samples=%d', key, result['first_sample'], len(pcm) // 2)
            return result
        except BaseException:
            if existing is None:
                token.set()
                self._revocations.pop(key, None)
            raise

    async def commit(self, key):
        await self._call('commit', key)
        _log.info('audio_commit key=%d', key)

    async def cancel(self, key):
        if key in self._revocations:
            self._revocations[key].set()
        await self._call('cancel', key)
        _log.info('audio_cancel key=%d', key)

    async def retire(self, key):
        if key in self._revocations:
            self._revocations[key].set()
        await self._call('retire', key)
        self._revocations.pop(key, None)

    def _transmission_allowed(self, permissions):
        return any(not token.is_set() for token in permissions)

    async def recv(self):
        if self.readyState != 'live' or self._receiving:
            raise MediaStreamError
        self._receiving = True
        try:
            while self.readyState == 'live':
                deadline = self.epoch.deadline(self._next_sample, RATE)
                # Windows may wake early; never advance RTP on that wake.
                while self.readyState == 'live' and (delay := deadline - time.monotonic()) > 0:
                    try:
                        await asyncio.wait_for(self._stopped.wait(), delay)
                    except asyncio.TimeoutError:
                        pass
                if self.readyState != 'live':
                    raise MediaStreamError
                lateness = time.monotonic() - deadline
                if lateness > MAX_LATENESS:
                    _log.warning('audio_deadline_missed phase=pacing late_ms=%.1f sample=%d',
                                 lateness * 1000, self._next_sample)
                    raise MediaStreamError
                packet, permissions = await self._call('packet_with_permission')
                allowed = self._transmission_allowed(permissions)
                lateness = time.monotonic() - deadline
                if lateness > MAX_LATENESS:
                    _log.warning('audio_deadline_missed phase=encoding late_ms=%.1f sample=%d',
                                 lateness * 1000, self._next_sample)
                    raise MediaStreamError
                self._next_sample += PACKET_SAMPLES
                if allowed:
                    delivered_at = time.monotonic()
                    if self._last_delivery is not None:
                        previous_sample, previous_at = self._last_delivery
                        gap = delivered_at - previous_at
                        if packet.pts == previous_sample + PACKET_SAMPLES and gap > .04:
                            _log.warning('audio_delivery_gap gap_ms=%.1f sample=%d', gap * 1000, packet.pts)
                    self._last_delivery = (packet.pts, delivered_at)
                    return packet
            raise MediaStreamError
        except BaseException:
            self.stop()
            raise
        finally:
            self._receiving = False

    def stop(self):
        if self.readyState == 'ended':
            return
        _log.info('audio_track_stopped sample=%d', self._next_sample)
        self._cancelled.set()
        for token in self._revocations.values():
            token.set()
        self._revocations.clear()
        self._stopped.set()
        super().stop()
        self._executor.shutdown(wait=False, cancel_futures=True)


class LatestAvatarTrack(MediaStreamTrack):
    """One replaceable input frame plus one in-flight encode; audio never waits."""
    kind = 'video'

    def __init__(self, epoch: MediaEpoch, *, quality=None):
        super().__init__()
        self.epoch = epoch
        self.diagnostic_id = next(_video_ids)
        self._diag_at = 0
        self._diag_encode_ms = 0
        self._diag_counts = dict(offered=0, encoded=0, late=0, overwritten=0, thinned=0)
        self.quality = quality or dict(video_kbps=500, video_width=448, video_fps=24)
        self._last_selected = -90000
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='nc-h264')
        self._cancelled = threading.Event()
        self._changed = asyncio.Event()
        self._pending = None
        self._last_offered = -3750
        self._keyframe_generation = 1
        self._encoded_keyframe_generation = 0
        self._encoder = None
        self._receiving = False

    def offer(self, frame: av.VideoFrame, timestamp: int):
        if self.readyState != 'live':
            raise MediaStreamError
        if (not isinstance(frame, av.VideoFrame) or type(timestamp) is not int or timestamp < 0
                or timestamp - self._last_offered < 3750):
            raise ValueError('Avatar timestamp must increase at no more than 24fps')
        # Ownership of this frame transfers to the track. Producers must not
        # modify/reuse its planes after this call.
        self._last_offered = timestamp
        self._diag_counts['offered'] += 1
        if timestamp - self._last_selected < 90000 // self.quality['video_fps']:
            self._diag_counts['thinned'] += 1
            return  # Thin frames, never retime them or change the speech clock.
        self._last_selected = timestamp
        if self._pending is not None:
            self._diag_counts['overwritten'] += 1
        self._pending = (frame, timestamp)
        self._changed.set()

    def request_keyframe(self):
        self._keyframe_generation += 1

    def _diagnose(self, event='video_sample'):
        now = time.monotonic()
        if event == 'video_sample' and now-self._diag_at < 2:
            return
        self._diag_at = now
        avatar_event(_log, event, peer=self.diagnostic_id, stamp=max(0,self._last_offered),
                     elapsed_ms=round(self._diag_encode_ms,2), pending=int(self._pending is not None),
                     **self._diag_counts)

    def _encode(self, frame, timestamp, force_keyframe):
        if self._cancelled.is_set():
            raise MediaStreamError
        if self._encoder is None:
            self._encoder = AvatarVideoEncoder(cancelled=self._cancelled.is_set,
                bitrate=self.quality['video_kbps']*1000, width=self.quality['video_width'], fps=self.quality['video_fps'])
        return self._encoder.encode(frame, timestamp, force_keyframe=force_keyframe)

    async def recv(self):
        if self.readyState != 'live' or self._receiving:
            raise MediaStreamError
        self._receiving = True
        try:
            while self.readyState == 'live':
                self._diagnose()
                try:
                    await asyncio.wait_for(self._changed.wait(),2)
                except asyncio.TimeoutError:
                    continue  # Record source starvation without fabricating frames.
                if self.readyState != 'live':
                    break
                selected = self._pending
                frame, timestamp = selected
                deadline = self.epoch.deadline(timestamp, 90000)
                self._changed.clear()
                while self.readyState == 'live' and (delay := deadline - time.monotonic()) > 0:
                    try:
                        await asyncio.wait_for(self._changed.wait(), delay)
                        break
                    except asyncio.TimeoutError:
                        pass
                if self.readyState != 'live':
                    break
                if self._pending is not selected:
                    continue
                self._pending = None
                if time.monotonic() - deadline > MAX_LATENESS:
                    self._diag_counts['late'] += 1
                    continue
                requested = self._keyframe_generation
                encode_started = time.monotonic()
                packets = await asyncio.get_running_loop().run_in_executor(
                    self._executor, self._encode, frame, timestamp,
                    requested != self._encoded_keyframe_generation)
                self._diag_encode_ms = (time.monotonic()-encode_started)*1000
                if self.readyState != 'live':
                    break
                if time.monotonic() - deadline > MAX_LATENESS:
                    # A discarded encoded reference frame must not leave the
                    # receiver depending on an image it never received.
                    self.request_keyframe()
                    self._diag_counts['late'] += 1
                    continue
                if len(packets) != 1:
                    raise MediaStreamError
                self._encoded_keyframe_generation = requested
                self._diag_counts['encoded'] += 1
                return packets[0]
            raise MediaStreamError
        except BaseException:
            self.stop()
            raise
        finally:
            self._receiving = False

    def stop(self):
        if self.readyState == 'ended':
            return
        self._diagnose('video_end')
        self._cancelled.set()
        self._pending = None
        self._changed.set()
        super().stop()
        self._executor.shutdown(wait=False, cancel_futures=True)
