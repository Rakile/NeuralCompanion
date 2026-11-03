"""Bounded local MuseTalk source. Only encoded RTP leaves the desktop.

The existing live service owns WAV-hash/render correlation and selected idle
source validation. This worker-side client accepts only its exact scoped routes;
it never accepts a phone-supplied media URL, path, or decoder format.
"""
import io
import json
import math
import re
import logging
import time
import threading

import av
from .media_diagnostics import avatar_event
from .frame_handoff import validate_timeline, validate_anticipation

_log = logging.getLogger(__name__)

PREFIX = '/api/dev/musetalk-live/'
MAX_MEDIA = 16 * 1024 * 1024


def source_timestamp(first_sample, offset_samples, frame_index):
    relative = frame_index * 2000 - offset_samples  # 48kHz / 24fps
    return None if relative < 0 else (first_sample + relative) * 90000 // 48000


def _hex(value):
    return isinstance(value, str) and re.fullmatch(r'[a-f0-9]{32}', value) is not None


def _motion(value, fallback):
    return value if isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value) else fallback


class AvatarSource:
    def __init__(self, forward, *, cancelled=lambda: False):
        self.forward, self.cancelled = forward, cancelled
        self.loop_fade_ms = 180
        self.source_ids = {}
        self.source_timelines = {}
        self.anticipations = {}
        self.openings = {}
        self._metadata_lock = threading.Lock()
        # Tokens live only for outstanding loads, not for every historical chunk.
        self._metadata_loads = {}
        self.diagnostic_id = 0
        self._diagnostic_at = {}

    def _diagnose(self, event, route, **fields):
        now=time.monotonic()
        key=(event,route,fields.get('status'))
        if now-self._diagnostic_at.get(key,-10)<2:
            return
        self._diagnostic_at[key]=now
        avatar_event(_log,event,peer=self.diagnostic_id,route=route,**fields)

    def _forward(self, request, route):
        started=time.monotonic()
        self._diagnose('source_wait',route)
        try:
            result=self.forward(request)
        except Exception:
            self._diagnose('source_error',route,status=0,elapsed_ms=round((time.monotonic()-started)*1000,2))
            raise
        status=result[0]
        self._diagnose('source_ready' if status==200 else 'source_error',route,
                       status=status if type(status) is int and 0<=status<=599 else 0,
                       elapsed_ms=round((time.monotonic()-started)*1000,2))
        return result

    def check(self):
        if self.cancelled():
            raise ValueError('Avatar source lifetime ended')

    def json(self, method, route, body=None):
        self.check()
        request = {'method': method, 'path': PREFIX + route}
        if body is not None:
            request['body'] = body
        status, data, ctype = self._forward(request,route.split('/')[0])
        self.check()
        if status != 200 or 'json' not in ctype or len(data) > 512 * 1024:
            raise ValueError('Avatar source unavailable')
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError('Invalid avatar response')
        return result

    def media(self, path, size):
        self.check()
        if type(size) is not int or not 0 < size <= MAX_MEDIA:
            raise ValueError('Avatar clip size invalid')
        status, data, ctype = self._forward({'method': 'GET', 'path': path},'media')
        self.check()
        if status != 200 or len(data) != size or ctype.split(';')[0] != 'video/mp4':
            raise ValueError('Avatar clip unavailable')
        return data

    def decode(self, data, count):
        """Incremental decoder; caller must not accumulate an idle cycle in RAM."""
        self.check()
        try:
            with av.open(io.BytesIO(data), format='mp4', options={'enable_drefs': '0'}) as container:
                if (len(container.streams.video) != 1 or container.streams.audio
                        or container.streams.video[0].codec_context.name != 'h264'):
                    raise ValueError('Unexpected avatar clip codec')
                stream = container.streams.video[0]
                if (not 0 < stream.width <= 4096 or not 0 < stream.height <= 4096
                        or stream.width * stream.height > 4096 * 2160 or stream.average_rate != 24):
                    raise ValueError('Avatar clip dimensions or rate invalid')
                index = 0
                for frame in container.decode(stream):
                    self.check()
                    if index >= count or frame.width != stream.width or frame.height != stream.height:
                        raise ValueError('Avatar clip frame bounds invalid')
                    scale = min(1, 448 / frame.width, 672 / frame.height)
                    width, height = max(2, int(frame.width * scale) // 2 * 2), max(2, int(frame.height * scale) // 2 * 2)
                    yield frame.reformat(width=width, height=height, format='yuv420p')
                    index += 1
                if index != count:
                    raise ValueError('Avatar clip truncated')
        except av.FFmpegError:
            raise ValueError('Avatar clip cannot be decoded') from None

    def retire_metadata(self, chunk=None):
        with self._metadata_lock:
            for token, owner in list(self._metadata_loads.items()):
                if chunk is None or owner == chunk:
                    self._metadata_loads.pop(token, None)
            for table in (self.anticipations, self.source_timelines):
                if chunk is None:
                    table.clear()
                else:
                    table.pop(chunk, None)
            for key in list(self.openings):
                if chunk is None or key[0] == chunk:
                    self.openings.pop(key, None)

    def segment(self, trial, audio, index, *, prefetch=False):
        if not _hex(trial) or type(index) is not int or not 0 <= index < 60:
            raise ValueError('Invalid avatar segment identity')
        token = object()
        with self._metadata_lock:
            self._metadata_loads[token] = audio['id']
            self.openings.pop((audio['id'], index), None)
            self.anticipations.pop(audio['id'], None)
        try:
            return self._segment(trial, audio, index, prefetch, token)
        finally:
            with self._metadata_lock:
                self._metadata_loads.pop(token, None)

    def _segment(self, trial, audio, index, prefetch, token):
        body = {'trialId': trial, 'audio': audio}
        if not prefetch:
            body['currentIndex'] = index
        result = self.json('POST', 'prefetch' if prefetch else 'prepare', body)
        with self._metadata_lock:
            if token not in self._metadata_loads:
                raise ValueError('Avatar metadata lifetime ended')
        duration, total = result.get('durationSeconds'), result.get('frameCount')
        if (result.get('trialId') != trial or not _hex(result.get('mediaId')) or result.get('audio') != audio
                or result.get('state') not in {'claimed', 'streaming'}
                or type(duration) not in {int, float} or not 0 < duration <= 30
                or not math.isfinite(duration) or type(total) is not int or not 1 <= total <= 720
                or total != math.floor(duration * 24) or index * 12 >= total):
            raise ValueError('Avatar chunk identity or bounds invalid')
        rows = result.get('segments')
        source_id = result.get('idleSourceId')
        if not isinstance(rows, list) or len(rows) > 60:
            raise ValueError('Invalid avatar segment list')
        matches = [row for row in rows if isinstance(row, dict) and row.get('index') == index]
        if len(matches) != 1:
            raise ValueError('Avatar segment unavailable')
        row = matches[0]
        count = min(12, total - index * 12)
        if (type(row.get('index')) is not int or row.get('startFrame') != index * 12
                or type(row.get('frameCount')) is not int or row['frameCount'] != count):
            raise ValueError('Avatar segment bounds invalid')
        # Optional producer metadata follows the same checked chunk/motion,
        # never a free-standing phone-provided capability. Absence revokes it.
        timeline, plan = None, None
        if 'sourceTimeline' in result:
            try:
                timeline = validate_timeline(result['sourceTimeline'])
            except ValueError:
                pass
        if 'anticipation' in result:
            try:
                plan = validate_anticipation(result['anticipation'])
            except ValueError:
                pass  # Optional visual metadata never invalidates authorized speech.
        # Validation may overlap retirement on the control thread. Publish all
        # metadata atomically only while this particular chunk load is owned.
        with self._metadata_lock:
            if token not in self._metadata_loads:
                raise ValueError('Avatar metadata lifetime ended')
            if _hex(source_id):
                self.source_ids[audio['id']] = _motion(result.get('motionId'), source_id)
            self.source_timelines.pop(audio['id'], None)
            if (timeline and timeline['motionId'] == self.source_ids.get(audio['id'])
                    and timeline['motionId'] == result.get('motionId')
                    and len(timeline['sourceIndices']) == total):
                self.source_timelines[audio['id']] = timeline
            if plan:
                self.anticipations[audio['id']] = dict(trialId=trial, mediaId=result['mediaId'],
                                                     audio=dict(audio), plan=plan)
            for table in (self.source_ids, self.source_timelines, self.anticipations):
                while len(table) > 4:
                    table.pop(next(iter(table)))
        if row.get('state') == 'pending':
            self._diagnose('segment_pending','prefetch' if prefetch else 'prepare',segment=index)
            return None
        expected = PREFIX + f"segment/{result['mediaId']}/{index:08d}.mp4"
        if row.get('state') != 'ready' or row.get('uri') != expected:
            raise ValueError('Avatar segment route invalid')
        # A segment is at most twelve scaled frames. The final count check runs
        # before any of them can enter the sender.
        data=self.media(expected,row.get('bytes'))
        started=time.monotonic()
        frames=list(self.decode(data,count))
        # Publish only after complete bounded decoding, fenced against Stop on
        # the control thread. This descriptor grants no playback authority.
        with self._metadata_lock:
            if token not in self._metadata_loads:
                raise ValueError('Avatar metadata lifetime ended')
            timeline = self.source_timelines.get(audio['id'])
            if timeline:
                self.openings[(audio['id'],index)] = json.loads(json.dumps(dict(
                    trialId=trial,mediaId=result['mediaId'],audio=audio,
                    segment=row,sourceTimeline=timeline)))
                while len(self.openings) > 8:
                    self.openings.pop(next(iter(self.openings)))
        self._diagnose('frame_work','media',phase='speech_decode',segment=index,
                       elapsed_ms=round((time.monotonic()-started)*1000,2))
        return frames

    def idle(self, trial):
        if not _hex(trial):
            raise ValueError('Invalid avatar idle identity')
        result = self.json('GET', 'status/' + trial)
        idle = result.get('idle')
        if result.get('trialId') != trial:
            raise ValueError('Avatar idle owner changed')
        fade = result.get('loopFadeMs', 180)
        if type(fade) is int and 0 <= fade <= 5000:
            self.loop_fade_ms = fade
        if idle is None:
            return None
        if not isinstance(idle, dict):
            raise ValueError('Invalid avatar idle descriptor')
        # Idle has its own validated identity before any speech is claimed.
        media = idle.get('mediaId', result.get('mediaId'))
        count, start = idle.get('frameCount'), idle.get('startFrame')
        expected = PREFIX + f'idle/{media}.mp4'
        if (not _hex(media) or idle.get('uri') != expected or idle.get('fps') != 24
                or type(count) is not int or not 1 <= count <= 1440
                or type(start) is not int or not 0 <= start < count):
            raise ValueError('Avatar idle bounds invalid')
        return self.media(expected, idle.get('bytes')), count, start, _motion(idle.get('motionId'), media)
