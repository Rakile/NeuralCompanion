"""Independent backend range production for the Desktop-owned output sequence.

The authenticated Desktop bridge supplies immutable plans. This worker never
selects transitions, commands chat, waits for phone preparation, or grants audio.
One backend media worker calls step; Stop is safe from its control thread.
"""
from dataclasses import dataclass, field, replace
import hashlib
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import uuid

from core.dev_musetalk_live_readiness import complete_png
from core.dev_musetalk_segments import encode_range, hidden
from core.diagnostics.plan_trace import PlanTrace
from core.diagnostics.policy import site_enabled
from .encoding_timing import measure, timed
from .media_quality import video_quality
from .muxed_trial_encoding import MuxedTrialEncoder, MuxedTrialSilence
from .ordered_output_producer import PreparedOutput
from .output_sequence import FrameProvenance, SourceRange, OutputRejected, OutputFrontier
from .ordered_output_bridge import OrderedBridgeRejected
from .ordered_output_composite import composite_range
from .ordered_idle_assets import IdleAsset, IdleAssetKey
from .ordered_video_encoder import OrderedNVENCVideo


def _identity(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def decode_ordered_frame(ffmpeg, media, offset):
    """Snapshot the authenticated retained clip's native-observed output frame.

    Required after interruption: raw motion provenance is not the displayed
    lip-sync/composited pixel image. Decode before the old reader ACK releases it.
    """
    if type(offset) is not int or not 0 <= offset < 12 or type(media) is not bytes or not 0 < len(media) <= 16*1024*1024:
        raise ValueError('ordered_stopped_decode_input')
    try:
        result=subprocess.run([str(ffmpeg),'-v','error','-i','pipe:0','-vf',f'select=eq(n\\,{offset})',
            '-frames:v','1','-f','image2pipe','-vcodec','png','pipe:1'],input=media,
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=10,**hidden())
    except (OSError,subprocess.TimeoutExpired):
        raise ValueError('ordered_stopped_decode_failed') from None
    if result.returncode or not 0<len(result.stdout)<=8*1024*1024 or not complete_png(result.stdout):
        raise ValueError('ordered_stopped_decode_failed')
    return result.stdout


@dataclass(frozen=True, slots=True)
class OrderedFrame:
    path: Path
    provenance: FrameProvenance
    signature: tuple = field(init=False, repr=False)

    def __post_init__(self):
        path = Path(self.path)
        if path.is_symlink() or type(self.provenance) is not FrameProvenance:
            raise ValueError('ordered_frame_identity')
        path = path.resolve(strict=True)
        signature = _identity(path)
        if not path.is_file() or not 0 < signature[2] <= 8*1024*1024:
            raise ValueError('ordered_frame_size')
        object.__setattr__(self, 'path', path)
        object.__setattr__(self, 'signature', signature)


@dataclass(frozen=True, slots=True)
class OrderedSourcePlan:
    kind: str
    source_id: str
    media_id: str
    frames: tuple[OrderedFrame, ...]
    samples: int
    wav: Path | None = None
    reply_id: str | None = None
    sequence_index: int | None = None
    entry_fade_ms: int | None = None
    wav_signature: tuple | None = field(init=False, default=None, repr=False)

    @classmethod
    def from_wire(cls, value):
        if (type(value) is not dict or set(value) != {'kind', 'sourceId', 'mediaId', 'frames', 'samples', 'wav', 'replyId', 'sequenceIndex', 'entryFadeMs'}
                or type(value['frames']) is not list or not 1 <= len(value['frames']) <= 720):
            raise ValueError('ordered_source_wire')
        frames = []
        for frame in value['frames']:
            if (type(frame) is not dict or set(frame) != {'path', 'provenance'} or not isinstance(frame['path'], str)
                    or type(frame['provenance']) is not dict or set(frame['provenance']) != {'sourceId', 'frame', 'sourceFrameCount'}):
                raise ValueError('ordered_source_wire_frame')
            provenance = frame['provenance']
            frames.append(OrderedFrame(Path(frame['path']), FrameProvenance(provenance['sourceId'], provenance['frame'], provenance['sourceFrameCount'])))
        return cls(value['kind'], value['sourceId'], value['mediaId'], tuple(frames), value['samples'],
                   value['wav'], value['replyId'], value['sequenceIndex'], value['entryFadeMs'])

    def __post_init__(self):
        if (self.kind not in ('idle', 'transition', 'speech')
                or not isinstance(self.source_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', self.source_id)
                or not isinstance(self.media_id, str) or not re.fullmatch('[a-f0-9]{32}', self.media_id)
                or type(self.frames) is not tuple or not 1 <= len(self.frames) <= 720
                or any(type(frame) is not OrderedFrame for frame in self.frames)
                or type(self.samples) is not int):
            raise ValueError('ordered_source_plan')
        if self.entry_fade_ms is not None and (type(self.entry_fade_ms) is not int or not 0 <= self.entry_fade_ms <= 5000):
            raise ValueError('ordered_transition_duration')
        if self.kind == 'speech':
            if (not isinstance(self.reply_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', self.reply_id)
                    or type(self.sequence_index) is not int or not 0 <= self.sequence_index <= 63
                    or not 0 < self.samples <= 1441999
                    or abs(self.samples - len(self.frames)*2000) >= 2000
                    or self.samples <= ((len(self.frames)-1)//12)*24000 or self.wav is None):
                raise ValueError('ordered_speech_range')
            wav = Path(self.wav)
            if wav.is_symlink():
                raise ValueError('ordered_audio_identity')
            wav = wav.resolve(strict=True)
            signature = _identity(wav)
            if not wav.is_file() or not 0 < signature[2] <= 4*1024*1024:
                raise ValueError('ordered_audio_size')
            object.__setattr__(self, 'wav', wav)
            object.__setattr__(self, 'wav_signature', signature)
        elif (self.reply_id is not None or self.sequence_index is not None or self.wav is not None
              or self.samples != len(self.frames)*2000):
            raise ValueError('ordered_visual_range')


@dataclass(frozen=True, slots=True)
class OrderedSourceAdmission:
    """Private Desktop response: same visual frontier, newly admitted reply."""
    plan: OrderedSourcePlan
    frontier: OutputFrontier


class OrderedOutputWorker:
    """One in-flight encode and one bounded result awaiting storage capacity.

    A step publishes a chunk as soon as encoded, never a whole-segment batch.
    supply(frontier) is Desktop scheduling input, not a mobile prepare request.
    It returns None during rendering gaps; those gaps generate no idle output.
    """
    def __init__(self, producer, *, ffmpeg, source_roots, supply, quality=None, on_event=None,
                 initial_frame=None, initial_generation=0, idle_assets=None, cache_epoch=lambda: 0,
                 verify_media=True):
        if type(verify_media) is not bool: raise ValueError('Invalid ordered validation selection')
        self.verify_media=verify_media
        self.producer, self.ffmpeg, self.supply = producer, ffmpeg, supply
        self.roots = tuple(Path(root).resolve(strict=True) for root in source_roots)
        if not self.roots or any(not root.is_dir() for root in self.roots):
            raise ValueError('ordered_input_roots')
        self.quality = video_quality('balanced' if quality is None else quality)
        if self.quality['video_fps'] != 24:
            raise ValueError('ordered_fps')
        self._on_event = on_event
        self._trace = None
        self._last_event = None
        self._stop = threading.Event()
        self._step_lock = threading.Lock()
        self._plan = None; self._start = 0; self._generation = None
        self._encoder = None; self._silent = None; self._silent_index = 0
        self._video = None; self._video_start = 0
        self._pending = None; self._failure = None
        self._timings = None; self._capacity_since = None
        if initial_frame is not None and (type(initial_frame) is not bytes
                or not 0<len(initial_frame)<=8*1024*1024 or not complete_png(initial_frame)
                or type(initial_generation) is not int or not 0<=initial_generation<=(1<<53)-1):
            raise ValueError('ordered_transition_initial_frame')
        self._pixel_tail = None if initial_frame is None else (initial_generation,0,initial_frame)
        self._fade = None
        self._stage = 'created'
        self._source_validation = None
        self._idle_assets, self._cache_epoch = idle_assets, cache_epoch
        self.defer_speech = False
        self._media_reservation = None

    def _event(self, reason, frontier, **details):
        event = dict(reason=reason, generation=None if frontier is None else frontier.generation,
                     ordinal=None if frontier is None else frontier.next_ordinal)
        event.update(details)
        if event == self._last_event:
            return
        self._last_event = event
        try:
            if self._on_event is not None:
                self._on_event(event)
            else:
                if self._trace is None: self._trace = PlanTrace()
                site='backend.encode.ordered.failure' if reason=='failed' else 'backend.encode.ordered'
                for condition, value in event.items():
                    self._trace.observe(self.producer.sequence.stream_id if frontier is None else frontier.stream_id,
                        site, condition, None, value)
        except Exception:
            pass  # Logging is observational; it cannot grant or stop production.

    def _confined(self, path):
        if path.is_symlink() or path.resolve(strict=True) != path or not any(path.is_relative_to(root) for root in self.roots):
            raise ValueError('ordered_input_path')

    def _encoded_event(self, expected, started):
        timings = self._timings
        if timings is None:
            self._event('encoded', expected,media_probes_enabled=self.verify_media if self._plan.kind=='speech' else True)
            return
        timings['encode_total_ms'] = (time.perf_counter_ns()-started)/1000000
        details = dict(media_probes_enabled=self.verify_media if self._plan.kind=='speech' else True,
            sequence_index=self._plan.sequence_index, source_frame_start=self._start,
            source_frame_count=len(self._plan.frames), frame_count=min(12,len(self._plan.frames)-self._start))
        details.update({k:round(v,3) if type(v) is float else v for k,v in timings.items()})
        self._event('encoded', expected, **details)

    def _backpressure(self, expected, kind):
        details = {}
        if self._timings is not None:
            if self._capacity_since is None: self._capacity_since = time.perf_counter_ns()
            details['capacity_kind'] = kind
        self._event('backpressure', expected, **details)

    def _changed(self, expected):
        return self._stop.is_set() or self.producer.frontier() != expected

    def _new_source(self, plan, expected):
        if type(plan) is not OrderedSourcePlan:
            raise ValueError('ordered_source_plan')
        if plan.kind == 'speech' and plan.reply_id != expected.reply_id:
            raise ValueError('ordered_source_reply')
        if plan.kind == 'idle' and expected.reply_id is not None:
            raise ValueError('ordered_idle_during_reply')
        kind = plan.kind if plan.kind in ('idle', 'speech') else 'unknown'
        for index, frame in enumerate(plan.frames):
            self._source_validation = (kind, 'frame', index)
            self._confined(frame.path)
        if plan.wav is not None:
            self._source_validation = (kind, 'audio', None)
            self._confined(plan.wav)
        self._plan, self._start, self._generation = plan, 0, expected.generation

    def _forget_source(self):
        # Native readers open only the final MP4s. The parent AAC is encoder-only.
        if self._video is not None:
            self._video.close()
            self._video = None
        if self._encoder is not None:
            self._encoder.audio.unlink(missing_ok=True)
        self._plan = self._encoder = None
        self._start = 0

    def _discard_pending(self):
        if self._pending is not None:
            # This is exactly the worker-created, NOT committed range. Published
            # files can only be released by the producer's reader-joined ACK.
            if not self.producer.owns_file(self._pending[0].file):
                self._pending[0].file.unlink(missing_ok=True)
            self._pending = None

    def _encode(self, expected):
        plan, start = self._plan, self._start
        timings = self._timings
        started = time.perf_counter_ns() if timings is not None else None
        frames = plan.frames[start:start+12]
        fade = self._fade
        if start == 0 and plan.entry_fade_ms is not None:
            fade = None
            if plan.entry_fade_ms:
                if self._pixel_tail is None or self._pixel_tail[:2] != (expected.generation, expected.next_ordinal):
                    raise ValueError('ordered_transition_origin_missing')
                fade = self._pixel_tail[2], 0, plan.entry_fade_ms
        # FFmpeg checks this at 100 Hz. Generation/frontier is checked once
        # after encoding and atomically at Desktop commit, not over HTTP here.
        cancelled = self._stop.is_set
        cache = self._idle_assets if plan.kind == 'idle' and fade is None else None
        cache_key = None
        cache_epoch = self._cache_epoch() if cache is not None else None
        with tempfile.TemporaryDirectory(prefix='ordered-input-', dir=self.producer.root) as directory:
            private = Path(directory)
            self._stage = 'frame_snapshot'
            cache_frames = []
            with measure(timings,'frame_snapshot_ms'):
                for i, frame in enumerate(frames):
                    self._confined(frame.path)
                    before = _identity(frame.path)
                    if before != frame.signature:
                        raise ValueError('ordered_frame_changed')
                    body = frame.path.read_bytes()
                    if _identity(frame.path) != before or not complete_png(body):
                        raise ValueError('ordered_frame_changed')
                    (private / f'{i:08d}.png').write_bytes(body)
                    last_pixels = body
                    if cache is not None: cache_frames.append(hashlib.sha256(body).hexdigest())
            if cache is not None:
                # Revision 2 is the NVENC generation; CPU-produced predecessor
                # bytes must not bypass the required hardware encode on a miss.
                cache_key = IdleAssetKey.from_digests(cache_frames, self.quality, revision=2)
                del cache_frames
                path = self.producer.root / ('clip-cached-' + uuid.uuid4().hex + '.mp4')
                try:
                    cache.set_epoch(cache_epoch)
                    hit = cache.lookup(cache_key, tail=last_pixels, epoch=cache_epoch)
                    if hit is not None:
                        cache.materialize(hit, path)
                        if cancelled():
                            path.unlink(missing_ok=True)
                            raise InterruptedError('ordered_encode_cancelled')
                        self._pending = (PreparedOutput(plan.kind, plan.source_id,
                            SourceRange(start, len(plan.frames), tuple(frame.provenance for frame in frames)),
                            plan.media_id, hit.trim['validSamples'], plan.reply_id, plan.sequence_index, path),
                            expected, dict(hit.trim), hit.tail, None)
                        self._event('idle_cache_hit', expected)
                        self._encoded_event(expected, started)
                        return
                    self._event('idle_cache_' + cache.reason, expected)
                except OSError:
                    path.unlink(missing_ok=True)
                    cache = None
                    self._event('idle_cache_storage_unavailable', expected)
            if fade is not None:
                self._stage = 'frame_composite'
                last_pixels = timed(timings,'frame_composite_ms',composite_range,self.ffmpeg,private,len(frames),fade,cancelled=cancelled)
            if cancelled(): raise InterruptedError('ordered_encode_cancelled')
            self._stage = 'h264_encode'
            if plan.kind == 'speech' and fade is None:
                if self._video is None:
                    # Pin this source and offset for the asynchronous feeder.
                    # Faded prefixes keep the existing exact composite path.
                    offset = start
                    def read_frame(index):
                        frame = plan.frames[offset+index]
                        self._confined(frame.path)
                        if _identity(frame.path) != frame.signature:
                            raise ValueError('ordered_frame_changed')
                        body = frame.path.read_bytes()
                        if _identity(frame.path) != frame.signature:
                            raise ValueError('ordered_frame_changed')
                        return body
                    self._video = timed(timings,'h264_context_ms',OrderedNVENCVideo,self.ffmpeg,self.producer.root,
                        len(plan.frames)-start,read_frame,quality=self.quality,cancelled=cancelled,
                        measure_timings=timings is not None)
                    self._video_start = start
                video = timed(timings,'h264_wait_ms',self._video.next_chunk,start-self._video_start,len(frames))
                if timings is not None: timings.update(self._video.timing_snapshot(start-self._video_start))
            else:
                video = timed(timings,'h264_wait_ms',encode_range,self.ffmpeg,private / '%08d.png',private / 'video.mp4',
                                     0, len(frames), cancelled=cancelled, quality=self.quality, encoder='h264_nvenc')
            if video is None or cancelled(): raise InterruptedError('ordered_encode_cancelled')
            if plan.kind == 'speech':
                if self._encoder is None:
                    self._stage = 'audio_snapshot'
                    with measure(timings,'audio_snapshot_ms'):
                        if _identity(plan.wav) != plan.wav_signature:
                            raise ValueError('ordered_audio_changed')
                        # Snapshot one continuous authenticated PCM source before
                        # AAC encoding; never re-encode audio at 0.5-second edges.
                        body = plan.wav.read_bytes()
                        if _identity(plan.wav) != plan.wav_signature:
                            raise ValueError('ordered_audio_changed')
                        wav = private / 'audio.wav'; wav.write_bytes(body)
                    self._stage = 'aac_encode'
                    self._encoder = MuxedTrialEncoder(self.ffmpeg, wav,
                        self.producer.root / ('ordered-speech-' + uuid.uuid4().hex),
                        valid_samples=plan.samples,frame_count=len(plan.frames),cancelled=cancelled,timings=timings,
                        verify_media=self.verify_media)
                self._encoder.cancelled = cancelled
                self._stage = 'speech_mux'
                row = timed(timings,'speech_mux_ms',self._encoder.segment,video,start,len(frames),timings=timings)
                path = self._encoder.root / row['file']
            else:
                # Amortize silence encoding, without a cumulative session/file
                # count limit. Each finite batch remains within encoder caps.
                if self._silent is None or self._silent_index == 60:
                    self._stage = 'silent_aac_encode'
                    if self._silent is not None: self._silent.encoder.audio.unlink(missing_ok=True)
                    self._silent = MuxedTrialSilence(self.ffmpeg,
                        self.producer.root / ('ordered-silent-' + uuid.uuid4().hex), cancelled=cancelled)
                    self._silent_index = 0
                self._silent.encoder.cancelled = cancelled
                self._stage = 'silent_mux'
                row = self._silent.segment(video, self._silent_index, frame_count=len(frames))
                self._silent_index += 1
                path = self._silent.encoder.root / row['file']
        trim = {key: row[key] for key in ('validSamples', 'delaySamples', 'paddingSamples', 'rawSamples')}
        trim['sampleRate'] = 48000
        if cache is not None and not cancelled():
            try:
                cache.set_epoch(self._cache_epoch())
                cache.remember(cache_key, IdleAsset(path, trim, last_pixels), epoch=cache_epoch)
                self._event('idle_cache_' + cache.reason, expected)
            except OSError:
                self._event('idle_cache_storage_unavailable', expected)
        prepared = PreparedOutput(plan.kind, plan.source_id,
            SourceRange(start, len(plan.frames), tuple(frame.provenance for frame in frames)),
            plan.media_id, row['validSamples'], plan.reply_id, plan.sequence_index, path)
        next_fade = None if fade is None or (fade[1]+len(frames))*1000 >= 24*fade[2] else (fade[0],fade[1]+len(frames),fade[2])
        self._pending = prepared, expected, trim, last_pixels, next_fade
        self._encoded_event(expected, started)

    def step(self):
        budget=getattr(self.producer,'budget',None)
        if budget is not None and self._media_reservation is None and not self._stop.is_set():
            self._media_reservation=budget.try_reserve()
            if self._media_reservation is None:return 'backpressure'
        try:
            return self._step()
        finally:
            if budget is not None and self._pending is not None and self._media_reservation is not None:
                budget.resize(self._media_reservation,self._pending[0].file.stat().st_size)
            if budget is not None and self._pending is None and self._media_reservation is not None:
                token=self._media_reservation;self._media_reservation=None
                if token.state not in ('retained','uncertain'):budget.release(token)

    def _step(self):
        with self._step_lock:
            if self._stop.is_set():
                self._discard_pending(); self._forget_source()
                if self._silent is not None: self._silent.encoder.audio.unlink(missing_ok=True)
                return 'cancelled'
            if self._failure is not None: raise self._failure
            expected = None
            self._source_validation = None
            if self._pending is None:
                self._timings = {} if self._on_event is not None or site_enabled('backend.encode.ordered') else None
                self._capacity_since = None
            self._stage = 'desktop_frontier'
            try:
                expected = timed(self._timings,'frontier_lookup_ms',self.producer.frontier)
                if self._generation is not None and expected.generation != self._generation:
                    self._discard_pending(); self._forget_source()
                if self._pending is None:
                    if self._plan is None:
                        self._stage = 'desktop_plan'
                        plan = timed(self._timings,'source_lookup_ms',self.supply,expected)
                        if plan is None:
                            self._event('waiting', expected); return 'waiting'
                        if type(plan) is OrderedSourceAdmission:
                            admitted, plan = plan.frontier, plan.plan
                            if (type(plan) is not OrderedSourcePlan or plan.kind != 'speech'
                                    or plan.sequence_index != 0 or expected.reply_id is not None
                                    or type(admitted) is not OutputFrontier
                                    or admitted != replace(expected, reply_id=plan.reply_id,
                                                           revision=expected.revision+1)):
                                raise ValueError('ordered_source_admission')
                            expected = admitted
                        self._stage = 'source_validation'
                        timed(self._timings,'source_validation_ms',self._new_source,plan,expected)
                        if plan.kind != 'speech': self._timings = None
                        elif self._timings is not None:
                            self._timings['render_ready_age_known'] = False
                            try:
                                # Atomic final sidecar mtime is a wall-clock
                                # reference, not a GPU/inference duration.
                                age = time.time()*1000-(plan.frames[0].path.parent/'phone-delivery.json').stat().st_mtime_ns/1000000
                                if age >= 0: self._timings.update(render_ready_age_known=True,render_ready_age_ms=age)
                            except OSError: pass
                    if self.defer_speech and self._plan.kind=='speech':return 'speech_ready'
                    self._encode(expected)
                prepared, retained_frontier, trim, last_pixels, next_fade = self._pending
                if timed(self._timings,'frontier_recheck_ms',self._changed,retained_frontier):
                    self._discard_pending(); self._forget_source()
                    self._event('stale', retained_frontier); return 'stale'
                try:
                    self._stage = 'desktop_commit'
                    # Reader retention limits PUBLICATION, not the one bounded
                    # speculative encode. Keep its exact frontier until release;
                    # reservation/Stop still discard it before any publication.
                    if prepared.kind == 'idle' and not self.producer.can_prepare_idle():
                        self._backpressure(retained_frontier,'idle_lookahead'); return 'backpressure'
                    timed(self._timings,'publication_ms',self.producer.publish_encoded,prepared,retained_frontier,
                        source_samples=self._plan.samples,trim=trim,timings=self._timings,
                        reservation=self._media_reservation)
                except OutputRejected as error:
                    if error.reason == 'capacity':
                        self._backpressure(retained_frontier,'retained_media'); return 'backpressure'
                    if error.reason in ('generation_changed', 'frontier_changed'):
                        self._discard_pending(); self._forget_source()
                        self._event('stale', retained_frontier); return 'stale'
                    raise
                self._pending = None
                # Speculative pixels never change a later transition. Promote
                # the bounded tail/fade state only after Desktop committed it.
                self._pixel_tail = retained_frontier.generation, retained_frontier.next_ordinal+1, last_pixels
                self._fade = next_fade
                self._start += len(prepared.source_range.frames)
                if self._start == len(self._plan.frames): timed(self._timings,'post_publish_cleanup_ms',self._forget_source)
                details = {}
                if self._timings is not None:
                    if self._capacity_since is not None:
                        self._timings['capacity_wait_ms'] = (time.perf_counter_ns()-self._capacity_since)/1000000
                    keys = ('frontier_recheck_ms','publication_ms','publish_hash_ms','desktop_commit_ms',
                            'capacity_wait_ms','post_publish_cleanup_ms')
                    details = {k:round(self._timings[k],3) for k in keys if k in self._timings}
                self._event('published', retained_frontier, **details)
                return 'published'
            except InterruptedError:
                self._discard_pending(); self._forget_source()
                self._event('stale', expected)
                return 'cancelled' if self._stop.is_set() else 'stale'
            except Exception as error:
                if (isinstance(error,OutputRejected) and expected is not None
                        and error.reason in ('frontier_changed','generation_changed')):
                    self._discard_pending(); self._forget_source()
                    self._event('stale',expected)
                    return 'stale'
                self._failure = error
                if self._video is not None:
                    try:
                        self._video.close()
                        self._video = None
                    except Exception as cleanup_error:
                        # Preserve the first production failure and the handle
                        # for explicit Stop to retry joining private resources.
                        error.add_note('ordered_video_cleanup: '+type(cleanup_error).__name__)
                code = str(error)
                rejection = code if re.fullmatch(r'(?:ordered|output)_[a-z_]{1,80}', code) else None
                details=dict(stage=self._stage,errorType=type(error).__name__,rejection=rejection)
                if self._stage == 'source_validation' and self._source_validation is not None:
                    # Bounded source role only; never disclose paths or exception text.
                    kind, role, index = self._source_validation
                    details.update(sourceKind=kind, sourceRole=role, sourceFrameIndex=index)
                if isinstance(error,OrderedBridgeRejected):
                    details.update(rejection=error.rejection,bridgeMethod=error.method,httpStatus=error.http_status)
                self._event('failed', expected, **details)
                raise

    def stop(self):
        self._stop.set()  # Does not wait for FFmpeg, take the work lock or unlink readers.

    def snapshot(self):
        return dict(stopped=self._stop.is_set(), pending=self._pending is not None,
                    source_active=self._plan is not None, failure=self._failure)


@dataclass(frozen=True, slots=True)
class _CodecWorkspace:
    root: Path


class OrderedClipEncoder(OrderedOutputWorker):
    """Local-only adapter over the SAME snapshot/NVENC/AAC/mux implementation.

    Its workspace deliberately has no frontier/commit/announcement interface.
    Only the private preparation cursor advances here; the publisher owns ACKs.
    """
    def __init__(self,*,ffmpeg,root,source_roots,quality,cancelled,verify_media,
                 initial_frame=None,initial_generation=0,on_event=None):
        super().__init__(_CodecWorkspace(Path(root).resolve(strict=True)),ffmpeg=ffmpeg,
            source_roots=source_roots,supply=None,quality=quality,on_event=on_event,
            initial_frame=initial_frame,initial_generation=initial_generation,verify_media=verify_media)
        self._cancelled=cancelled; self._ticket=None; self._cursor=None; self._complete=True
        self._unhanded=None

    def step(self):
        raise ValueError('ordered_encoder_has_no_publication_authority')

    def seed_tail(self,tail):
        if self._ticket is not None:raise ValueError('ordered_encoder_tail_already_started')
        self._pixel_tail=tail

    def begin(self,ticket):
        from .ordered_prepared import SourceTicket
        if type(ticket) is not SourceTicket or not self._complete:
            raise ValueError('ordered_preparation_source_busy')
        cursor=ticket.cursor
        if self._cursor is not None:
            previous=self._cursor
            if ((cursor.stream_id,cursor.generation,cursor.reply_id,cursor.ordinal,cursor.revision,cursor.predecessor_frame)
                    !=(previous.stream_id,previous.generation,previous.reply_id,previous.ordinal,previous.revision,previous.predecessor_frame)
                    or cursor.sequence_index!=previous.sequence_index+1):
                raise ValueError('ordered_preparation_source_gap')
        if self._cancelled() or self._stop.is_set():raise InterruptedError('ordered_encode_cancelled')
        self._ticket,self._cursor,self._complete=ticket,cursor,False
        self._new_source(ticket.plan,cursor)

    def prepare_next(self,reservation):
        from .ordered_prepared import PreparedClip
        if self._complete:return None
        if self._cancelled():self._stop.set()
        if self._stop.is_set():raise InterruptedError('ordered_encode_cancelled')
        cursor=self._cursor
        self._timings={} if self._on_event is not None or site_enabled('backend.encode.ordered') else None
        try:
            self._encode(cursor)
            prepared,_,trim,pixels,fade=self._pending
            self._unhanded=prepared.file,reservation
            clip=PreparedClip(self._ticket,cursor,prepared,trim,reservation)
            self._pending=None
            self._start+=len(prepared.source_range.frames)
            self._pixel_tail=cursor.generation,cursor.ordinal+1,pixels
            self._fade=fade
            self._cursor=replace(cursor,ordinal=cursor.ordinal+1,revision=cursor.revision+1,
                predecessor_frame=prepared.source_range.frames[-1])
            if self._start==len(self._plan.frames):
                self._complete=True; self._forget_source()
            self._unhanded=None
            return clip
        except BaseException as error:
            if self._pending is not None:
                self._unhanded=self._pending[0].file,reservation;self._pending=None
            try:self._discard_unhanded()
            except BaseException as cleanup_error:error.add_note('ordered_private_cleanup: '+type(cleanup_error).__name__)
            raise

    def source_complete(self):return self._complete

    def tail_state(self):return self._pixel_tail

    def owns_private(self,reservation):
        return self._unhanded is not None and self._unhanded[1] is reservation

    def _discard_unhanded(self):
        if self._unhanded is not None:
            path,token=self._unhanded
            path.unlink(missing_ok=True);token.budget.release(token)
            self._unhanded=None

    def close(self):
        self.stop()
        self._discard_unhanded()
        if self._pending is not None:
            self._pending[0].file.unlink(missing_ok=True); self._pending=None
        self._forget_source()
        if self._silent is not None:self._silent.encoder.audio.unlink(missing_ok=True)
