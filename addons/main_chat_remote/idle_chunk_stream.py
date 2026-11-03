"""Bounded pre-rendered idle chunks; no audio or playback authority."""
import hashlib
import math
import re
from pathlib import Path
import secrets
import shutil
import tempfile
import threading

from core.dev_musetalk_segments import encode_range
from core.phone_media_tools import tools
from .idle_loop_catalog import _confined, _frames, _digest
from .media_quality import video_quality

WINDOW = 6
TICKS = 12
MAX_FILE = 16*1024*1024


def _signature(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


class IdleChunkStream:
    def __init__(self, source, output, *, avatar_id, start_frame, quality, cancelled, muxed_audio=False):
        if type(muxed_audio) is not bool:
            raise ValueError('Invalid idle mux mode')
        self.muxed_audio=muxed_audio
        self._silent=None
        self._file_muxed={}
        self.source = Path(source).absolute()
        self.output = _confined(output, [Path(output).absolute()])
        self.cancelled = cancelled
        self.frame_digests = []
        self.frames, _ = _frames(self.source, [self.source], cancelled, frame_hashes=self.frame_digests)
        self.signatures = [_signature(path) for path in self.frames]
        if (not isinstance(avatar_id, str) or not avatar_id or len(avatar_id) > 256
                or type(start_frame) is not int or not 0 <= start_frame < len(self.frames)):
            raise ValueError('Invalid idle chunk source')
        self.avatar_id, self.start_frame = avatar_id, start_frame
        self.quality = video_quality(quality)
        self.media_id = secrets.token_hex(16)
        self.motion_id = hashlib.sha256(str(self.source.resolve()).encode()).hexdigest()
        self.ffmpeg, _ = tools()
        self._lock = threading.RLock()
        self._closed = False
        self._encoding = False
        self._encoding_index = None
        self._published_through = -1
        self._waiting_plan = None
        self._cursor = 0
        self._files = {}
        self._file_signatures = {}
        self._file_digests = {}

    def _ended(self):
        return self._closed or self.cancelled()

    def _path(self, index):
        return self.output/f'idle-chunk-{self.media_id}-{index:08d}.mp4'

    def _indices(self, index):
        waiting = self._waiting_plan
        if waiting and index >= waiting['firstIndex']:
            order = waiting['sourceIndices']
            offset = (index-waiting['firstIndex'])*TICKS
            return [order[(offset+tick)%len(order)] for tick in range(TICKS)]
        return [(self.start_frame+index*TICKS+tick)%len(self.frames) for tick in range(TICKS)]

    def install_waiting_plan(self, plan, first_index):
        """Copy desktop order at an unpublished boundary; no new authority.

        The caller must authenticate the plan and negotiate the native cut.
        This method only fences immutable producer frame order and retention.
        """
        keys = {'version','planId','avatarId','fps','sourceFrameCount','sourceIndices',
                'speechEntryFrame','exitAfterFrame','repeat'}
        if (not isinstance(plan, dict) or set(plan) not in (keys,keys|{'syncWaitSeconds'})
                or type(plan['version']) is not int or plan['version'] != 1
                or type(plan['fps']) is not int or plan['fps'] != 24
                or not isinstance(plan['planId'],str) or not re.fullmatch('[a-f0-9]{32}',plan['planId'])
                or plan['avatarId'] != self.avatar_id
                or type(plan['sourceFrameCount']) is not int or plan['sourceFrameCount'] != len(self.frames)
                or not isinstance(plan['sourceIndices'],list) or not 2 <= len(plan['sourceIndices']) <= 1440
                or any(type(n) is not int or not 0 <= n < len(self.frames) for n in plan['sourceIndices'])
                or type(plan['speechEntryFrame']) is not int or plan['speechEntryFrame'] != plan['sourceIndices'][0]
                or type(plan['exitAfterFrame']) is not int or plan['exitAfterFrame'] != len(plan['sourceIndices'])-1
                or plan['repeat'] is not True or type(first_index) is not int):
            return False
        if 'syncWaitSeconds' in plan:
            value=plan['syncWaitSeconds']
            if (isinstance(value,bool) or not isinstance(value,(int,float))
                    or not math.isfinite(value) or not 0 <= value <= 2.5):
                return False
        order=plan['sourceIndices']
        if any((order[(i+1)%len(order)]-n)%len(self.frames) not in (1,len(self.frames)-1)
               for i,n in enumerate(order)):
            return False
        frozen={key:(list(value) if key=='sourceIndices' else value) for key,value in plan.items()}
        frozen['firstIndex']=first_index
        with self._lock:
            if self._ended(): return False
            if self._waiting_plan is not None:
                return self._waiting_plan == frozen
            boundary=max(self._cursor,self._published_through+1,
                         self._encoding_index+1 if self._encoding_index is not None else 0)
            if not boundary <= first_index <= min(10000,self._cursor+WINDOW):
                return False
            self._waiting_plan=frozen
            return True

    @property
    def has_pending(self):
        # Scheduling metadata only. Never perform file IO in the outer speech
        # worker's control path; optional IO failures belong to the idle lane.
        with self._lock:
            return not self._ended() and any(i not in self._files for i in range(self._cursor, self._cursor+WINDOW))

    def _row(self, index):
        path = self._files.get(index)
        return {'index': index, 'startFrame': index*TICKS, 'frameCount': TICKS,
                'sourceIndices': self._indices(index), 'state': 'ready' if path else 'pending',
                **({'uri': f'/api/dev/musetalk-live/idle-chunk/{self.media_id}/{index:08d}.mp4',
                    'bytes': path.stat().st_size, 'sha256': self._file_digests[index],
                    **self._file_muxed.get(index,{})} if path else {})}

    def render_next(self):
        # Called by one bounded media worker. No encoding or snapshot IO under
        # the control lock, and no job queue tied to a playback clock.
        with self._lock:
            index = next((i for i in range(self._cursor, self._cursor+WINDOW) if i not in self._files), None)
            if self._ended() or self._encoding or index is None:
                return False
            self._encoding = True
            self._encoding_index = index
            indices = self._indices(index)
        target = self._path(index)
        published = False
        muxed = None
        try:
            with tempfile.TemporaryDirectory(prefix='idle-chunk-snapshot-', dir=self.output) as raw:
                snapshot = Path(raw)
                for tick, frame_index in enumerate(indices):
                    if self._ended():
                        return False
                    source = _confined(self.frames[frame_index], [self.source])
                    if _signature(source) != self.signatures[frame_index]:
                        raise ValueError('Idle chunk source changed')
                    shutil.copyfile(source, snapshot/f'{tick:08d}.png')
                    if (_signature(source) != self.signatures[frame_index]
                            or _digest(snapshot/f'{tick:08d}.png', self._ended) != self.frame_digests[frame_index]):
                        raise ValueError('Idle chunk source changed')
                video=snapshot/'video.mp4' if self.muxed_audio else target
                result = encode_range(self.ffmpeg, snapshot/'%08d.png', video, 0, TICKS,
                                      cancelled=self._ended, quality=self.quality)
                if not self._ended():
                    for frame_index in set(indices):
                        source = _confined(self.frames[frame_index], [self.source])
                        if (_signature(source) != self.signatures[frame_index]
                                or _digest(source, self._ended) != self.frame_digests[frame_index]):
                            raise ValueError('Idle chunk source changed')
                if result is not None and self.muxed_audio and not self._ended():
                    from .muxed_trial_encoding import MuxedTrialSilence
                    if self._silent is None:
                        self._silent=MuxedTrialSilence(self.ffmpeg,self.output/f'idle-mux-{self.media_id}',cancelled=self._ended)
                    muxed=self._silent.segment(result,index)
                    (self._silent.encoder.root/muxed['file']).rename(target)
            if result is None or self._ended():
                return False
            signature = _signature(target)
            if not 0 < signature[2] <= MAX_FILE:
                raise ValueError('Idle chunk file exceeds cap')
            digest = _digest(target, self._ended)
            with self._lock:
                if self._ended() or not self._cursor <= index < self._cursor+WINDOW:
                    return False
                if _signature(target) != signature:
                    raise ValueError('Idle chunk changed before publication')
                self._files[index] = target
                self._published_through = max(self._published_through,index)
                self._file_signatures[index] = signature
                self._file_digests[index] = digest
                if muxed:
                    self._file_muxed[index]={'sampleRate':48000,**{key:muxed[key] for key in
                        ('validSamples','delaySamples','paddingSamples','rawSamples')}}
                published = True
                return True
        except (ValueError,InterruptedError):
            if self._ended():
                return False
            raise
        finally:
            if not published:
                target.unlink(missing_ok=True)
            with self._lock:
                self._encoding = False
                self._encoding_index = None
                if self._ended():
                    self._cleanup_silent()

    def status(self):
        with self._lock:
            if self._ended():
                raise ValueError('Idle chunk owner ended')
            return {'version': 1, 'mediaId': self.media_id, 'motionId': self.motion_id,
                    'avatarId': self.avatar_id, 'sourceFrameCount': len(self.frames),
                    'fps': 24, 'startFrame': self.start_frame, 'cursor': self._cursor,
                    'videoQuality': dict(self.quality),
                    **({'muxedAudio':True} if self.muxed_audio else {}),
                    **({'waitingPlan':{key:(list(self._waiting_plan[key]) if key=='sourceIndices' else self._waiting_plan[key])
                         for key in ('version','planId','firstIndex','sourceIndices')}} if self._waiting_plan else {}),
                    'segments': [self._row(i) for i in range(self._cursor, self._cursor+WINDOW)]}

    def advance(self, cursor):
        """Reclaim only explicitly retained complete files, never acknowledge playback."""
        with self._lock:
            if (self._ended() or type(cursor) is not int
                    or not self._cursor <= cursor <= min(10000, self._cursor+WINDOW)
                    or any(index not in self._files for index in range(self._cursor, cursor))):
                raise ValueError('Invalid retained idle cursor')
            for index in range(self._cursor, cursor):
                self._files.pop(index).unlink(missing_ok=True)
                self._file_signatures.pop(index)
                self._file_digests.pop(index)
                self._file_muxed.pop(index,None)
            self._cursor = cursor

    def read(self, index):
        with self._lock:
            if self._ended() or type(index) is not int or index not in self._files:
                raise LookupError('Idle chunk unavailable')
            path = _confined(self._files[index], [self.output])
            expected = self._file_signatures[index]
            if _signature(path) != expected:
                raise LookupError('Idle chunk changed')
            size = path.stat().st_size
            if not 0 < size <= MAX_FILE:
                raise LookupError('Idle chunk file exceeds cap')
            with path.open('rb') as source:
                body = source.read(MAX_FILE+1)
            if (self._ended() or len(body) != size or _signature(path) != expected
                    or hashlib.sha256(body).hexdigest() != self._file_digests[index]):
                raise LookupError('Idle chunk changed')
            return body

    def close(self):
        with self._lock:
            self._closed = True
            for path in self._files.values():
                path.unlink(missing_ok=True)
            self._files.clear()
            self._file_signatures.clear()
            self._file_digests.clear()
            self._file_muxed.clear()
            if not self._encoding:
                self._cleanup_silent()

    def _cleanup_silent(self):
        # Only this epoch's generated parent and clip files. Unknown contents
        # are not removed; rmdir fails closed and outer trial cleanup owns them.
        root=self.output/f'idle-mux-{self.media_id}'
        if root.exists():
            root=_confined(root,[self.output])
            for path in [root/'continuous.m4a',*root.glob('clip-*.mp4')]:
                try:
                    confined=_confined(path,[root])
                except FileNotFoundError:
                    continue
                confined.unlink(missing_ok=True)
            root.rmdir()
        self._silent=None
