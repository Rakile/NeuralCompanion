"""Per-peer AV admission over authenticated NC RPC, never relay signaling.

This controller schedules authorized source media. Only the existing native
playback owner can supply heard/drained receipts; no method here manufactures one.
Caller owns the peer and calls close on actual peer loss or authorization expiry.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
from dataclasses import dataclass, field
import json
import logging
import math
import re
import secrets
import threading
import time

from .speech_source import load_speech, _authorize
from .avatar_pump import AvatarPump
from ..media_quality import video_quality
from .media_diagnostics import avatar_event

_log = logging.getLogger(__name__)


@dataclass
class _Entry:
    body: dict
    cancelled: threading.Event = field(default_factory=threading.Event)
    state: str = 'loading'
    descriptor: dict | None = None
    timeline_end: int = 0
    source: object | None = None
    visual: dict | None = None
    visual_deadline: float = 0


class AVControl:
    def __init__(self, audio, video, binding, forward, *, frame_handoff=False):
        self.audio, self.video, self.binding, self.forward = audio, video, binding, forward
        self.generation = secrets.token_hex(16)
        self._closed = False
        self._clocks = None
        self._handoff = False
        # Integration gate: production callers leave this off until BOTH native
        # surfaces and their anticipation/presentation contract pass acceptance.
        self._handoff_available = frame_handoff
        self._entries: dict[int, _Entry] = {}
        self._history: dict[int, _Entry] = {}
        self._last_key = 0
        self._preparing = asyncio.Lock()
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix='nc-av-source')
        self.avatar = AvatarPump(video, forward)

    async def visual(self, body):
        if (self._closed or self._clocks is None or not isinstance(body, dict)
                or set(body) != {'generation', 'enabled'} or body['generation'] != self.generation
                or type(body['enabled']) is not bool):
            raise ValueError('Invalid avatar presentation lifetime')
        first, count = self.avatar.present(body['enabled'])
        return {'generation': self.generation, 'enabled': body['enabled'], 'first_timestamp': first,
                'first_rtp': (self._clocks['video']['origin'] + first) & 0xffffffff, 'sample_count': count}

    async def negotiate(self, body):
        base = {'version': 1, 'native_audio': 1, 'native_video': 1, 'sparse_audio': 1}
        if (self._closed or body not in (base, {**base, 'frame_handoff_version': 1})
                or any(type(v) is not int for v in body.values())):
            raise ValueError('Unsupported NC native AV capability')
        handoff = body.get('frame_handoff_version') == 1
        if handoff and not self._handoff_available:
            raise ValueError('Frame handoff integration is not available')
        if self._clocks is not None and handoff != self._handoff:
            raise ValueError('NC media capability changed within a peer')
        if self._clocks is None:
            clocks = await asyncio.wait_for(self.binding.ready(), 5)
            if self._closed:
                raise ValueError('NC media peer ended')
            self._clocks = clocks
            self._handoff = handoff
        return {'version': 1, 'sparse_audio': 1, 'idle_cache': 1, 'generation': self.generation,
                **({'frame_handoff_version': 1} if self._handoff else {}),
                'video_quality': video_quality(self.video.quality),
                'audio': 'opus', 'video': 'H264', 'clocks': {k: dict(v) for k, v in self._clocks.items()}}

    async def idle(self, body):
        if (self._closed or self._clocks is None or not isinstance(body, dict)
                or set(body) != {'generation','avatar_generation','revision','loop_id','ready'}
                or body['generation'] != self.generation or type(body['ready']) is not bool
                or any(not isinstance(body[k], str) or not re.fullmatch('[a-f0-9]{64}', body[k])
                       for k in ('avatar_generation','revision'))):
            raise ValueError('Invalid idle presentation lifetime')
        if not body['ready']:
            self.avatar.cache_idle(False)
            return {'ready':False}
        if not self.avatar._enabled:
            raise ValueError('Idle presentation disabled')
        revision = self.avatar._revision
        status, data, content_type = await self._worker(self.forward, {'method':'GET','path':'/api/idle-cache/manifest'})
        if (self._closed or not self.avatar._active(revision) or status != 200
                or 'json' not in content_type or len(data) > 128*1024):
            raise ValueError('Idle inventory unavailable')
        manifest = json.loads(data)
        if ('video_quality' in manifest and manifest['video_quality'] != video_quality(self.video.quality)):
            self.avatar.cache_idle(False)
            raise ValueError('Idle quality requires reconnect')
        if (manifest.get('generation') != body['avatar_generation'] or manifest.get('revision') != body['revision']
                or manifest.get('active_loop') != body['loop_id'] or not body['loop_id']
                or not any(row.get('id') == body['loop_id'] and row.get('status') == 'ready' for row in manifest.get('loops',[]))):
            self.avatar.cache_idle(False)
            raise ValueError('Idle selection changed')
        self.avatar.cache_idle(True)
        return {'ready':True}

    def _validate(self, body):
        fields = {'generation', 'key', 'auth', 'request_id', 'chunk_id', 'sequence_index', 'offset_samples'}
        if (self._closed or self._clocks is None or not isinstance(body, dict) or set(body) != fields
                or body['generation'] != self.generation or type(body['key']) is not int
                or not 0 < body['key'] <= 0x7fffffff or not isinstance(body['auth'], dict)):
            raise ValueError('Invalid NC media lifetime')
        # Freeze mutable caller input, retaining only a small, peer-local control.
        try:
            encoded = json.dumps(body, allow_nan=False)
            if len(encoded) > 8192:
                raise ValueError
            return json.loads(encoded)
        except (ValueError, TypeError):
            raise ValueError('Invalid NC media identity') from None

    def _find(self, body):
        body = self._validate(body)
        entry = self._entries.get(body['key']) or self._history.get(body['key'])
        if entry is None or entry.body != body:
            raise ValueError('Stale or conflicting NC media identity')
        return entry

    def _live(self, entry):
        if self._closed or entry.cancelled.is_set():
            raise ValueError('NC media lifetime ended')

    async def _worker(self, callback, *args):
        return await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(self._executor, callback, *args), 30)

    def _new_entry(self, body):
        key = body['key']
        if key <= self._last_key or len(self._entries) >= 2:
            raise ValueError('NC media key or capacity exceeded')
        if any((e.body['request_id'], e.body['chunk_id']) == (body['request_id'], body['chunk_id'])
               for e in self._entries.values()):
            raise ValueError('NC chunk already has a playback lifetime')
        entry = _Entry(body)
        self._entries[key] = entry
        self._last_key = key
        return entry

    async def _load_source(self, entry):
        body = entry.body
        self._live(entry)
        if entry.source is None:
            entry.source = await self._worker(
                lambda: load_speech(self.forward, body['auth'], body['request_id'], body['chunk_id'],
                                    body['sequence_index'], offset_samples=body['offset_samples'],
                                    cancelled=entry.cancelled.is_set))
        else:
            # A staged source is not a reusable authorization capability.
            await self._worker(_authorize, self.forward, body['auth'], body['request_id'],
                               body['chunk_id'], body['sequence_index'])
        self._live(entry)
        return entry.source

    def _visual_result(self, entry):
        result = json.loads(json.dumps(entry.visual))
        result['remaining_ms'] = max(0, min(2000, math.floor((entry.visual_deadline-time.monotonic())*1000)))
        return result

    async def prepare_visual(self, body):
        """Bounded source preparation BEFORE any PCM reservation or delivery.

        The reply carries source readiness, not receiver presentation evidence.
        It neither commits audio nor extends the budget on a duplicate request.
        """
        body = self._validate(body)
        if not self._handoff:
            raise ValueError('Frame handoff was not negotiated')
        entry = self._entries.get(body['key'])
        if entry is not None:
            self._live(entry)
            if entry.body != body or entry.visual is None:
                raise ValueError('Conflicting or pending visual preparation')
            async with self._preparing:
                self._live(entry)
                if entry.state == 'visual_ready':
                    try:
                        # Repeated probes neither renew the wait budget nor
                        # inherit authorization from an earlier successful load.
                        await self._load_source(entry)
                        value = await self.avatar.prepare_visual(body['key'], entry.visual_deadline,
                                                                 entry.cancelled.is_set)
                        self._live(entry)
                        previous = entry.visual['outcome']
                        entry.visual = dict(generation=self.generation, key=body['key'], **value)
                        if value['outcome'] != previous:
                            avatar_event(_log, 'handoff_prepare', peer=getattr(self.video, 'diagnostic_id', 0),
                                         key=body['key'], outcome=value['outcome'],
                                         remaining_ms=self._visual_result(entry)['remaining_ms'])
                    except BaseException:
                        entry.cancelled.set()
                        self.avatar.cancel(body['key'])
                        self._archive(body['key'], entry)
                        raise
            return self._visual_result(entry)
        entry = self._new_entry(body)
        try:
            async with self._preparing:
                source = await self._load_source(entry)
                entry.visual_deadline = time.monotonic()+2
                self.avatar.stage(body['key'], body, source.offset_samples, len(source.pcm)//2)
                value = await self.avatar.prepare_visual(body['key'], entry.visual_deadline,
                                                         entry.cancelled.is_set)
                self._live(entry)
                entry.visual = dict(generation=self.generation, key=body['key'], **value)
                entry.state = 'visual_ready'
                result = self._visual_result(entry)
                avatar_event(_log, 'handoff_prepare', peer=getattr(self.video, 'diagnostic_id', 0),
                             key=body['key'], outcome=value['outcome'], remaining_ms=result['remaining_ms'],
                             elapsed_ms=round((time.monotonic()-entry.visual_deadline+2)*1000, 2))
                return result
        except BaseException:
            avatar_event(_log, 'handoff_prepare', peer=getattr(self.video, 'diagnostic_id', 0),
                         key=body['key'], outcome='cancelled')
            entry.source = None
            entry.cancelled.set()
            self.avatar.cancel(body['key'])
            self._archive(body['key'], entry)
            raise

    async def prepare(self, body):
        received_at = time.monotonic()
        visual_delay = None
        if isinstance(body, dict) and 'visual_start_delay_ms' in body:
            body = dict(body)
            visual_delay = body.pop('visual_start_delay_ms')
            if (not self._handoff or type(visual_delay) is not int
                    or not 500 <= visual_delay <= 2000):
                raise ValueError('Invalid native handoff scheduling delay')
        body = self._validate(body)
        key = body['key']
        entry = self._entries.get(key)
        if visual_delay is not None and (entry is None or entry.visual is None
                or entry.visual.get('outcome') != 'ready'):
            raise ValueError('Native boundary requires prepared visual media')
        if entry:
            self._live(entry)
            if entry.body != body or entry.state not in {'visual_ready', 'prepared', 'admitted'}:
                raise ValueError('Conflicting or pending NC media preparation')
            if entry.descriptor is not None:
                return json.loads(json.dumps(entry.descriptor))
            entry.state = 'loading'
        else:
            entry = self._new_entry(body)
        try:
            # Preserve numeric reservation order even if local fetches finish out
            # of order. Stop/close never acquire this lock or wait for decoding.
            async with self._preparing:
                self._live(entry)
                source = await self._load_source(entry)
                self._live(entry)
                now = time.monotonic()
                target = now + 2
                visual_start = None
                if visual_delay is not None:
                    # A ready opening can target a later loop pass. The expired
                    # source-preparation wait must not move this new boundary.
                    boundary = received_at + visual_delay/1000
                    # A boundary already missed during authorization cannot be
                    # reported as scheduled. No extra PCM buffering is allowed.
                    visual_start = 'missed'
                    if boundary-now >= .15:
                        target = boundary
                        visual_start = 'scheduled'
                first = max(0, math.ceil((target - self.audio.epoch.start) * 48000))
                after_queue = max(first, *(e.timeline_end for e in self._entries.values()))
                if after_queue != first and visual_start is not None:
                    visual_start = 'missed'
                first = after_queue
                descriptor = await self.audio.reserve(key, source.pcm, first)
                self._live(entry)
                entry.timeline_end = first + len(source.pcm) // 2
                entry.descriptor = {
                    'generation': self.generation, 'key': key,
                    'request_id': body['request_id'], 'chunk_id': body['chunk_id'],
                    'sequence_index': body['sequence_index'],
                    'first_sample': descriptor['first_sample'],
                    'first_rtp': (self._clocks['audio']['origin'] + descriptor['first_sample']) & 0xffffffff,
                    'sample_count': len(source.pcm) // 2, 'offset_samples': source.offset_samples,
                    'total_samples': source.total_samples,
                    'video_first_rtp': (self._clocks['video']['origin'] +
                                        descriptor['first_sample'] * 90000 // 48000) & 0xffffffff,
                }
                if entry.visual is not None:
                    entry.descriptor['source_timeline'] = entry.visual.get('source_timeline')
                if visual_start is not None:
                    entry.descriptor['visual_start'] = visual_start
                entry.state = 'prepared'
                self.avatar.add(key, body, entry.descriptor)
                entry.source = None
                return json.loads(json.dumps(entry.descriptor))
        except BaseException:
            entry.cancelled.set()
            entry.source = None
            entry.state = 'stopped'
            self.avatar.cancel(key)
            if not self._closed:
                await self.audio.cancel(key)
            self._archive(key, entry)
            raise

    async def commit(self, body):
        entry = self._find(body)
        self._live(entry)
        if entry.state == 'admitted':
            return {'state': 'admitted'}
        if entry.state != 'prepared':
            raise ValueError('NC media is not prepared')
        try:
            b = entry.body
            await self._worker(_authorize, self.forward, b['auth'], b['request_id'], b['chunk_id'], b['sequence_index'])
            self._live(entry)
            await self.audio.commit(b['key'])
            self._live(entry)
            entry.state = 'admitted'
            self.avatar.commit(b['key'])
            return {'state': 'admitted'}
        except BaseException:
            entry.cancelled.set()
            entry.state = 'stopped'
            if not self._closed:
                await self.audio.cancel(entry.body['key'])
            raise

    def _archive(self, key, entry):
        entry.source = None
        self._entries.pop(key, None)
        if self._closed:
            return
        # Never keep PCM or unlimited old credentials in the idempotency window.
        self._history[key] = entry
        while len(self._history) > 32:
            self._history.pop(next(iter(self._history)))

    async def stop(self, body):
        entry = self._find(body)
        entry.cancelled.set()
        entry.state = 'stopped'
        entry.source = None
        self.avatar.cancel(entry.body['key'])
        await self.audio.cancel(entry.body['key'])
        return {'state': 'stopped'}

    async def retire(self, body):
        entry = self._find(body)
        entry.cancelled.set()
        entry.state = 'retired'
        self.avatar.cancel(entry.body['key'])
        await self.audio.cancel(entry.body['key'])
        await self.audio.retire(entry.body['key'])
        self._archive(entry.body['key'], entry)
        return {'state': 'retired'}

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.avatar.close()
        for entry in self._entries.values():
            entry.cancelled.set()
        self.audio.stop()
        self.video.stop()
        self.binding.close()
        self._entries.clear()
        self._history.clear()
        self._executor.shutdown(wait=False, cancel_futures=True)
