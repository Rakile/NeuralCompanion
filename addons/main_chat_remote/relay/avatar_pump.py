"""One bounded, optional MuseTalk producer for a peer's H264 track.

Local HTTP/segment decoding and incremental idle decoding have separate bounded
workers. Scheduling alone runs on asyncio; Qt is never involved. Audio admission/receipts are not this object's
responsibility. Missing/late visual frames are dropped, never allowed to stall it.
"""
import asyncio
import concurrent.futures
import logging
import math
import secrets
import time

from .avatar_source import AvatarSource, source_timestamp, _hex, PREFIX
from .avatar_fade import AvatarFade
from .media_diagnostics import avatar_event

_log = logging.getLogger(__name__)


class AvatarPump:
    def __init__(self, track, forward):
        self.track, self.forward = track, forward
        self._closed, self._enabled = False, False
        self._revision, self._until, self._last_stamp = 0, 0, 9000
        self._entries = {}
        self._trial, self._request, self._arm = None, None, None
        self._segment_key, self._frames = None, None
        self._idle_data, self._idle_frames = None, None
        self._idle_checked = 0
        self._cache, self._prepared_key = {}, None
        self._loading = self._refreshing = None
        self._retry_at = 0
        self._fade = AvatarFade()
        self._cached_idle_until = 0
        self.failure = None
        self._visual = None
        self._speech_tail = False
        self._diag_at = 0
        self._frame_diag_at = {}
        self._diag_counts = {'offered':0,'late':0,'pending':0}
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='nc-av-avatar')
        self._frames_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='nc-av-frames')
        self.source = AvatarSource(forward, cancelled=lambda: self._closed)
        self.source.diagnostic_id = getattr(track,'diagnostic_id',0)
        self._task = asyncio.create_task(self._run())

    def present(self, enabled):
        if self._closed or type(enabled) is not bool:
            raise ValueError('Avatar presentation ended')
        self._revision += 1
        self._enabled = enabled
        first = max(self._last_stamp + 3750, math.ceil((time.monotonic() - self.track.epoch.start + .25) * 90000))
        self._until = first / 90000 + 600 if enabled else 0
        if enabled:
            self.track.request_keyframe()
        else:
            self._cached_idle_until = 0
            self._release_trial()
        return first, 600 * 48000

    @property
    def cached_idle_ready(self):
        return not self._closed and self._enabled and time.monotonic() < self._cached_idle_until

    def cache_idle(self, ready):
        self._cached_idle_until = time.monotonic() + 6 if ready and self._enabled else 0
        if not ready:
            self.track.request_keyframe()

    def add(self, key, body, descriptor):
        staged = self._entries.get(key)
        if staged is not None and staged.get('staging') and staged['body'] == body:
            staged.update(descriptor=dict(descriptor), staging=False)
            return
        if self._closed or key in self._entries or len(self._entries) >= 2:
            raise ValueError('Avatar admission capacity exceeded')
        self._entries[key] = {'body': dict(body), 'descriptor': dict(descriptor), 'admitted': False}

    def stage(self, key, body, offset, count):
        self.add(key, body, {'first_sample': 0, 'offset_samples': offset, 'sample_count': count})
        self._entries[key]['staging'] = True

    async def prepare_visual(self, key, deadline, cancelled):
        entry = self._entries[key]
        revision = self._revision
        segment = math.ceil(entry['descriptor']['offset_samples']/2000)//12
        while True:
            if self._closed or cancelled() or self._entries.get(key) is not entry:
                raise ValueError('Avatar staging cancelled')
            if not self._active(revision):
                return {'outcome': 'hidden', 'source_timeline': None}
            frames = self._cache.get((key, segment))
            anticipation = self.source.anticipations.get(entry['body']['chunk_id'])
            if anticipation and (anticipation['trialId'] != self._trial
                                 or anticipation['audio'] != self._audio(entry)):
                anticipation = None
            extra = {'anticipation': anticipation} if anticipation else {}
            if frames:
                timeline = self.source.source_timelines.get(entry['body']['chunk_id'])
                opening = self.source.openings.get((entry['body']['chunk_id'], segment))
                if (opening and opening['trialId'] == self._trial
                        and opening['audio'] == self._audio(entry)
                        and opening['sourceTimeline'] == timeline):
                    extra['opening'] = opening
                return {'outcome': 'ready' if timeline else 'unmapped', 'source_timeline': timeline, **extra}
            if anticipation:
                return {'outcome': 'anticipating', 'source_timeline': None, **extra}
            # This deadline bounds an RPC wait, not the lifetime of prepared
            # media. A later probe can use a ready opening on another loop pass.
            if time.monotonic() >= deadline:
                return {'outcome': 'alignment_timeout', 'source_timeline': None}
            await asyncio.sleep(.01)

    def commit(self, key):
        if key in self._entries:
            self._entries[key]['admitted'] = True

    def cancel(self, key):
        entry = self._entries.pop(key, None)
        if entry:
            self.source.retire_metadata(entry['body']['chunk_id'])
        self._cache = {k: v for k, v in self._cache.items() if k[0] != key}
        if self._segment_key and self._segment_key[0] == key:
            self._segment_key, self._frames = None, None

    def _active(self, revision):
        return not self._closed and self._enabled and revision == self._revision

    async def _work(self, revision, callback, *args):
        result = await asyncio.get_running_loop().run_in_executor(self._executor, callback, *args)
        if not self._active(revision):
            raise ValueError('Avatar presentation changed')
        return result

    def _release_trial(self, *, keep_idle=False):
        self.source.retire_metadata()
        trial, arm = self._trial, self._arm
        self._trial, self._arm, self._request = None, None, None
        self._segment_key, self._frames = None, None
        self._cache.clear()
        self._prepared_key = None
        self._idle_checked = 0
        if not keep_idle:
            self._speech_tail = False
            self._visual = None
            self._frames_executor.submit(self._fade.clear)
            self._idle_data = None
            iterator, self._idle_frames = self._idle_frames, None
            if iterator is not None:
                self._frames_executor.submit(iterator.close)
        def release():
            if trial or arm:
                body = {}
                if trial: body['trialId'] = trial
                if arm: body['armRequestId'] = arm
                try:
                    self.forward({'method': 'POST', 'path': PREFIX + 'cancel', 'body': body})
                except Exception:
                    pass  # The existing service also has an inactivity expiry.
        self._executor.submit(release)

    async def _ensure_trial(self, revision, entry):
        request = entry['body']['request_id'] if entry else None
        if self._trial and self._request and request and self._request != request:
            self._release_trial(keep_idle=True)
        if self._trial:
            return
        if entry:
            b = entry['body']
            # The existing recovery gate is intentionally not weakened. A later
            # chunk without its opening trial is audio-only until a new reply.
            if b['sequence_index'] != 0:
                raise ValueError('Avatar opening unavailable for resumed chunk')
            result = await self._work(revision, self.source.json, 'POST', 'recover', {'audio': self._audio(entry)})
        else:
            self._arm = secrets.token_hex(16)
            result = await self._work(revision, self.source.json, 'POST', 'arm', {'armRequestId': self._arm})
        if result.get('state') != 'armed' or not _hex(result.get('trialId')):
            raise ValueError('Avatar source is not ready')
        self._trial = result['trialId']
        self._request = request

    @staticmethod
    def _audio(entry):
        b = entry['body']
        return {'id': b['chunk_id'], 'phone_request_id': b['request_id'],
                'url_path': '/api/audio/file/' + b['chunk_id']}

    def _choose(self, now):
        candidates = [(key, e) for key, e in self._entries.items() if e['admitted'] and
                      now >= e['descriptor']['first_sample'] / 48000 - .05 and
                      now < (e['descriptor']['first_sample'] + e['descriptor']['sample_count']) / 48000]
        return min(candidates, key=lambda pair: pair[1]['descriptor']['first_sample'], default=(None, None))

    async def _speech(self, revision, key, entry):
        d = entry['descriptor']
        now = time.monotonic() - self.track.epoch.start
        # Source frame time stays tied to audio, never to fetch completion.
        minimum = max(d['offset_samples'], d['offset_samples'] + int((now - d['first_sample'] / 48000) * 48000))
        index = max(0, math.ceil(minimum / 2000))
        if not entry.get('opening_offered'):
            # A scheduler wakeup 1ms after the start is still within frame 0's
            # display interval. Rounding up here used to skip that opening.
            # Resume offsets remain a hard lower bound; after the first offer,
            # retain the existing ahead-of-time pacing for subsequent frames.
            index = max(math.ceil(d['offset_samples'] / 2000), minimum // 2000)
        stamp = source_timestamp(d['first_sample'], d['offset_samples'], index)
        if stamp is None or index * 2000 >= d['offset_samples'] + d['sample_count']:
            return
        segment = index // 12
        frames = self._cache.get((key, segment))
        if frames is None or index % 12 >= len(frames):
            self._diag_counts['pending'] += 1
            return False
        frame = frames[index % 12]
        shown = await self._offer(revision, frame, stamp, key, entry,
                          identity=('motion', self.source.source_ids.get(entry['body']['chunk_id'], key)), frame_index=index)
        if shown:
            self._speech_tail = True
            entry['opening_offered'] = True
        return True

    async def _load(self, revision):
        """At most current+next segment and one successor opening (36 frames)."""
        now = time.monotonic() - self.track.epoch.start
        rows = sorted(((key, e) for key, e in self._entries.items() if e.get('staging') or (e['admitted'] and
                       now < (e['descriptor']['first_sample'] + e['descriptor']['sample_count']) / 48000)),
                      key=lambda row: (bool(row[1].get('staging')), row[1]['descriptor']['first_sample']))
        key, entry = rows[0] if rows else (None, None)
        work_key, work_entry, operation, segment = key, entry, 'trial', 0
        try:
            await self._ensure_trial(revision, entry)
            if entry is None:
                return
            if self._entries.get(key) is not entry:
                return
            if self._prepared_key != key:
                operation = 'prepare'
                await self._work(revision, self.source.json, 'POST', 'prepare',
                                 {'trialId': self._trial, 'audio': self._audio(entry), 'currentIndex': 0})
                if self._entries.get(key) is not entry:
                    return
                self._prepared_key, self._request = key, entry['body']['request_id']
            d = entry['descriptor']
            sample = d['offset_samples'] if entry.get('staging') else max(
                d['offset_samples'], d['offset_samples'] + int((now-d['first_sample']/48000)*48000))
            segment = max(0, math.ceil(sample/2000)) // 12
            wanted = [(key, entry, i, False) for i in ((segment,) if entry.get('staging') else (segment, segment+1))
                      if i*24000 < d['offset_samples'] + d['sample_count']]
            if len(rows) > 1:
                next_key, next_entry = rows[1]
                if (next_entry['body']['request_id'] == entry['body']['request_id'] and
                        next_entry['body']['sequence_index'] == entry['body']['sequence_index'] + 1):
                    wanted.append((next_key, next_entry, 0, True))
            keep = {(k, i) for k, _, i, _ in wanted}
            self._cache = {k: v for k, v in self._cache.items() if k in keep}
            for k, e, i, pending in wanted:
                if (k, i) in self._cache or self._entries.get(k) is not e:
                    continue
                work_key, work_entry, segment = k, e, i
                operation = 'prefetch' if pending else 'segment'
                # Never promote a successor while the current chunk is speaking.
                frames = await self._work(revision, lambda: self.source.segment(
                    self._trial, self._audio(e), i, **({'prefetch': True} if pending else {})))
                if frames is None:
                    # Advancing prepare's cursor retires older backend clips.
                    # Never advance past an opening that is still rendering.
                    break
                if self._entries.get(k) is e and frames is not None:
                    self._cache[k, i] = frames
            self.failure = None
        except Exception as error:
            if self._active(revision):
                category = type(error).__name__
                discarded = work_entry is not None and self._entries.get(work_key) is not work_entry
                avatar_event(_log,'pump_error',peer=getattr(self.track,'diagnostic_id',0),
                             reason='cancelled' if discarded else 'worker_error', operation=operation,
                             error=category if category in {'ValueError','TimeoutError','OSError','RuntimeError'} else 'other',
                             key=work_key or 0, segment=segment,
                             sequence=work_entry['body']['sequence_index'] if work_entry else 0)
                if discarded:
                    # A retired/replaced chunk's worker is no longer allowed to
                    # invalidate the trial or decoded frames of surviving chunks.
                    return
                if self.failure != category:
                    logging.getLogger(__name__).warning('NC track avatar preparation unavailable (%s)', category)
                self.failure = category
                self._release_trial()
                self._retry_at = time.monotonic() + 1

    async def _refresh_idle(self, revision, trial):
        try:
            return trial, await self._work(revision, self.source.idle, trial), None
        except Exception as error:
            return trial, None, error

    async def _poll_idle(self, revision):
        if self._refreshing is not None and self._refreshing.done():
            task, self._refreshing = self._refreshing, None
            trial, latest, error = task.result()
            if trial == self._trial and error is not None:
                raise error
            # Temporary absence while the next mood is prepared does not revoke
            # the validated cycle. Explicit disable/error still clears it.
            if trial == self._trial and latest is not None:
                if self._idle_data is None or latest[:2] != self._idle_data[:2] or latest[3] != self._idle_data[3]:
                    self.cache_idle(False)
                    iterator, self._idle_frames = self._idle_frames, None
                    if iterator is not None:
                        await asyncio.get_running_loop().run_in_executor(self._frames_executor, iterator.close)
                # Continuation phase can change while encoded loop bytes do not.
                # Retain it for the speech tail, without restarting active idle.
                self._idle_data = latest
        if self._trial and self._refreshing is None and time.monotonic() - self._idle_checked >= 2:
            self._idle_checked = time.monotonic()
            self._refreshing = asyncio.create_task(self._refresh_idle(revision, self._trial))

    async def _idle(self, revision):
        await self._poll_idle(revision)
        if self.cached_idle_ready:
            await asyncio.sleep(.02)
            return
        if self._idle_data is None:
            await asyncio.sleep(.01)
            return
        data, count, start, source_id = self._idle_data
        if self._speech_tail and not self._choose(time.monotonic()-self.track.epoch.start)[1]:
            self._speech_tail = False
            iterator,self._idle_frames=self._idle_frames,None
            if iterator is not None:
                await asyncio.get_running_loop().run_in_executor(self._frames_executor,iterator.close)
            avatar_event(_log,'idle_phase',peer=getattr(self.track,'diagnostic_id',0),idle_start=start)
        def next_frame():
            if self._idle_frames is None:
                self._idle_frames = self.source.decode(data, count)
                for _ in range(start): next(self._idle_frames)
            frame = next(self._idle_frames, None)
            if frame is None:
                self._idle_frames = self.source.decode(data, count)
                frame = next(self._idle_frames)
            return frame
        started=time.monotonic()
        frame = await asyncio.get_running_loop().run_in_executor(self._frames_executor, next_frame)
        self._frame_diagnose('idle_decode',started)
        stamp = max(self._last_stamp + 3750, math.ceil((time.monotonic() - self.track.epoch.start + .02) * 90000))
        # Idle and lip-sync are two renderings of the same motion source. A
        # chunk boundary or temporary idle gap is not a mood transition.
        await self._offer(revision, frame, stamp, identity=('motion', source_id))

    async def _offer(self, revision, frame, stamp, key=None, entry=None, identity=None, frame_index=0):
        # The latest-frame sender has a one-frame mailbox. Do not enqueue the
        # whole future segment into it, which would discard the opening frames.
        deadline = self.track.epoch.start + stamp / 90000 - .02
        while (delay := deadline - time.monotonic()) > 0:
            await asyncio.sleep(min(delay, .05))
            if not self._active(revision) or (key is not None and self._entries.get(key) is not entry):
                return False
        if (not self._active(revision) or stamp - self._last_stamp < 3750
                or time.monotonic() - deadline > .1
                or (key is not None and self._entries.get(key) is not entry)):
            self._diag_counts['late'] += 1
            return False
        started=time.monotonic()
        frame = await asyncio.get_running_loop().run_in_executor(
            self._frames_executor, self._fade.apply, frame, identity, stamp, self.source.loop_fade_ms)
        self._frame_diagnose('fade',started)
        # Stop/owner changes may happen while FFmpeg runs on the worker.
        if not self._active(revision) or (key is not None and self._entries.get(key) is not entry):
            return False
        self.track.offer(frame, stamp)
        self._last_stamp = stamp
        self._diag_counts['offered'] += 1
        visual=('speech' if entry else 'idle', key, identity)
        if visual != self._visual:
            avatar_event(_log,'handoff',peer=getattr(self.track,'diagnostic_id',0),mode=visual[0],
                         key=key or 0,frame=frame_index,stamp=stamp,
                         same_motion=self._visual is not None and self._visual[2]==identity)
            self._visual=visual
        return True

    def _frame_diagnose(self, phase, started):
        now=time.monotonic()
        if now-self._frame_diag_at.get(phase,-10)>=2:
            self._frame_diag_at[phase]=now
            avatar_event(_log,'frame_work',peer=getattr(self.track,'diagnostic_id',0),phase=phase,
                         elapsed_ms=round(max(0,now-started)*1000,2))

    async def _run(self):
        while not self._closed:
            if not self._enabled:
                await asyncio.sleep(.05)
                continue
            revision = self._revision
            if time.monotonic()-self._diag_at >= 2:
                self._diag_at=time.monotonic()
                avatar_event(_log,'pump_sample',peer=getattr(self.track,'diagnostic_id',0),
                             stamp=self._last_stamp,cache_frames=sum(len(v) for v in self._cache.values()),
                             ready=self.cached_idle_ready,**self._diag_counts)
            if time.monotonic() - self.track.epoch.start >= self._until:
                self.present(False)
                continue
            key, entry = self._choose(time.monotonic() - self.track.epoch.start)
            try:
                await self._poll_idle(revision)
                if self._loading is None or self._loading.done():
                    if self._loading is not None:
                        self._loading.result()
                    if time.monotonic() >= self._retry_at:
                        self._loading = asyncio.create_task(self._load(revision))
                if not entry or not await self._speech(revision, key, entry):
                    await self._idle(revision)
                self.failure = None
                await asyncio.sleep(.005 if entry else .001)
            except asyncio.CancelledError:
                return
            except Exception as error:
                if self._active(revision):
                    avatar_event(_log,'pump_error',peer=getattr(self.track,'diagnostic_id',0),reason='invalid_source')
                    # No response text/credentials/media identifiers in logs.
                    category = type(error).__name__
                    if self.failure != category:
                        logging.getLogger(__name__).warning('NC track avatar unavailable (%s)', category)
                    self.failure = category
                    # The local producer has a shorter inactivity expiry than
                    # our presentation lease. Never retry an expired trial ID
                    # forever. Re-arming still uses its unchanged admission
                    # checks; this cannot grant or restart speech playback.
                    self._release_trial()
                    await asyncio.sleep(1)

    def close(self):
        if self._closed:
            return
        self._closed, self._enabled = True, False
        self._entries.clear()
        self._task.cancel()
        for task in (self._loading, self._refreshing):
            if task is not None:
                task.cancel()
        self._release_trial()
        self._executor.shutdown(wait=False, cancel_futures=False)
        self._frames_executor.shutdown(wait=False, cancel_futures=False)
