"""Bounded Desktop-authored output order, independent of playback time.

This ledger allocates no media and confers no output/audio permission. Its caller
owns authenticated reply finality and reader-join evidence. Native admission must
still validate those authorities independently.
"""
from collections import OrderedDict, deque
from dataclasses import dataclass
import re
import threading

MAX_SAFE_INTEGER = (1 << 53) - 1
MAX_CHUNKS = 60
MAX_BYTES = 128 * 1024 * 1024
MAX_MEDIA_BYTES = 16 * 1024 * 1024
STOP_UNAVAILABLE_REASONS = frozenset(('no_rendered_frame', 'render_callback_pending', 'render_callback_capacity',
    'frame_pts_unmapped', 'render_callback_unmapped', 'render_callback_ambiguous', 'codec_owner_changed_pending',
    'render_listener_unavailable', 'render_pts_reused', 'render_release_failed', 'codec_reset_pending',
    'render_listener_missing', 'render_source_released'))
_IDENTITY = re.compile(r'[A-Za-z0-9_-]{1,160}\Z')
_HEX32 = re.compile(r'[a-f0-9]{32}\Z')
_HEX64 = re.compile(r'[a-f0-9]{64}\Z')


def _integer(value, low=0, high=MAX_SAFE_INTEGER):
    return type(value) is int and low <= value <= high


def _identity(value):
    return isinstance(value, str) and _IDENTITY.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class FrameProvenance:
    source_id: str
    frame: int
    source_frame_count: int

    def __post_init__(self):
        if (not _identity(self.source_id) or not _integer(self.source_frame_count, 1)
                or not _integer(self.frame, 0, self.source_frame_count - 1)):
            raise ValueError('output_frame_invalid')


@dataclass(frozen=True, slots=True)
class SourceRange:
    start: int
    total_frames: int
    frames: tuple[FrameProvenance, ...]

    def __post_init__(self):
        if (not _integer(self.total_frames, 1) or not _integer(self.start)
                or type(self.frames) is not tuple or not 1 <= len(self.frames) <= 12
                or any(type(frame) is not FrameProvenance for frame in self.frames)
                or self.end > self.total_frames
                or len(self.frames) != min(12, self.total_frames - self.start)):
            raise ValueError('output_source_range_invalid')

    @property
    def end(self):
        return self.start + len(self.frames)


@dataclass(frozen=True, slots=True)
class OutputChunk:
    stream_id: str
    generation: int
    ordinal: int
    predecessor: int | None
    kind: str
    source_id: str
    source_range: SourceRange
    media_id: str
    frame_count: int
    fps: int
    sample_count: int
    reply_id: str | None
    sequence_index: int | None
    sha256: str
    byte_length: int

    def __post_init__(self):
        if (not isinstance(self.stream_id, str) or not _HEX32.fullmatch(self.stream_id)
                or not _integer(self.generation) or not _integer(self.ordinal)
                or (self.predecessor is not None and not _integer(self.predecessor))
                or self.predecessor != (self.ordinal - 1 if self.ordinal else None)
                or self.kind not in ('idle', 'transition', 'speech')
                or not _identity(self.source_id) or type(self.source_range) is not SourceRange
                or not isinstance(self.media_id, str) or not _HEX32.fullmatch(self.media_id)
                or not _integer(self.frame_count, 1, 12)
                or self.frame_count != len(self.source_range.frames)
                or type(self.fps) is not int or self.fps != 24
                or not _integer(self.sample_count, 1, 25999)
                or not isinstance(self.sha256, str) or not _HEX64.fullmatch(self.sha256)
                or not _integer(self.byte_length, 1, MAX_MEDIA_BYTES)):
            raise ValueError('output_chunk_invalid')
        if self.kind == 'speech':
            if not _identity(self.reply_id) or not _integer(self.sequence_index) or not self.sample_count:
                raise ValueError('output_speech_invalid')
            terminal = self.source_range.end == self.source_range.total_frames
            if ((not terminal and self.sample_count != self.frame_count * 2000)
                    or abs(self.sample_count - self.frame_count * 2000) >= 2000):
                raise ValueError('output_audio_range_invalid')
        elif (self.sample_count != self.frame_count * 2000
              or self.reply_id is not None or self.sequence_index is not None):
            raise ValueError('output_visual_invalid')

    def to_wire(self):
        return dict(version=1, streamId=self.stream_id, generation=self.generation,
                    ordinal=self.ordinal, predecessor=self.predecessor, kind=self.kind,
                    sourceId=self.source_id, sourceRange=dict(start=self.source_range.start,
                    totalFrames=self.source_range.total_frames, frames=[dict(sourceId=f.source_id,
                    frame=f.frame, sourceFrameCount=f.source_frame_count) for f in self.source_range.frames]),
                    mediaId=self.media_id, frameCount=self.frame_count, fps=self.fps,
                    sampleCount=self.sample_count, replyId=self.reply_id, sequenceIndex=self.sequence_index,
                    sha256=self.sha256, byteLength=self.byte_length)

    @classmethod
    def from_wire(cls, value):
        fields = {'version', 'streamId', 'generation', 'ordinal', 'predecessor', 'kind',
                  'sourceId', 'sourceRange', 'mediaId', 'frameCount', 'fps', 'sampleCount',
                  'replyId', 'sequenceIndex', 'sha256', 'byteLength'}
        if (type(value) is not dict or set(value) != fields
                or type(value['version']) is not int or value['version'] != 1):
            raise ValueError('output_wire_invalid')
        source = value['sourceRange']
        if (type(source) is not dict or set(source) != {'start', 'totalFrames', 'frames'}
                or type(source['frames']) is not list or not 1 <= len(source['frames']) <= 12
                or any(type(frame) is not dict or set(frame) != {'sourceId', 'frame', 'sourceFrameCount'}
                       for frame in source['frames'])):
            raise ValueError('output_wire_range_invalid')
        return cls(stream_id=value['streamId'], generation=value['generation'], ordinal=value['ordinal'],
                   predecessor=value['predecessor'], kind=value['kind'], source_id=value['sourceId'],
                   source_range=SourceRange(source['start'], source['totalFrames'], tuple(
                       FrameProvenance(f['sourceId'], f['frame'], f['sourceFrameCount']) for f in source['frames'])),
                   media_id=value['mediaId'], frame_count=value['frameCount'], fps=value['fps'],
                   sample_count=value['sampleCount'], reply_id=value['replyId'],
                   sequence_index=value['sequenceIndex'], sha256=value['sha256'], byte_length=value['byteLength'])


@dataclass(frozen=True, slots=True)
class OutputFrontier:
    stream_id: str
    generation: int
    next_ordinal: int
    revision: int
    last_frame: FrameProvenance | None
    reply_id: str | None


class OutputRejected(ValueError):
    def __init__(self, reason, *, expected_ordinal, actual_ordinal):
        super().__init__('output_' + reason)
        self.reason = reason
        self.expected_ordinal = expected_ordinal
        self.actual_ordinal = actual_ordinal


class OutputSequence:
    def __init__(self, stream_id, *, max_chunks=MAX_CHUNKS, max_bytes=MAX_BYTES,
                 observer=None):
        if (not isinstance(stream_id, str) or not _HEX32.fullmatch(stream_id)
                or not _integer(max_chunks, 1, MAX_CHUNKS)
                or not _integer(max_bytes, 1, MAX_BYTES)):
            raise ValueError('output_sequence_invalid')
        self._stream_id = stream_id
        self._max_chunks = max_chunks
        self._max_bytes = max_bytes
        self._observer = observer
        self._lock = threading.RLock()
        self._generation = self._ordinal = self._revision = self._bytes = 0
        self._retired_through = -1
        self._last_frame = None
        self._reply = None
        self._speech = None
        # Recent duplicate detection, not authority: the reply protocol owns
        # replay protection. Bounded history must not become a session timeout.
        self._completed_replies = deque(maxlen=64)
        self._rows = OrderedDict()

    def _event(self, reason, actual_ordinal=None):
        event = dict(reason=reason, generation=self._generation,
                     expected_ordinal=self._ordinal, actual_ordinal=actual_ordinal)
        try:
            if self._observer is not None:
                self._observer(event)
            else:
                from core.diagnostics.plan_trace import PlanTrace
                if not hasattr(self, '_trace'):
                    self._trace = PlanTrace(component='desktop')
                site = 'desktop.plan.output.reject' if reason not in (
                    'committed', 'reserved', 'finished', 'invalidated', 'released', 'restarted') else 'desktop.plan.output'
                for condition, value in event.items():
                    self._trace.observe(self._stream_id, site, condition, None, value)
        except Exception:
            pass  # Recording never changes publication or reader ownership.

    def _reject(self, reason, actual_ordinal=None):
        self._event(reason, actual_ordinal)
        raise OutputRejected(reason, expected_ordinal=self._ordinal,
                             actual_ordinal=actual_ordinal)

    def _frontier(self):
        return OutputFrontier(self._stream_id, self._generation, self._ordinal,
                              self._revision, self._last_frame, self._reply)

    def frontier(self):
        with self._lock:
            return self._frontier()

    def planning_snapshot(self):
        with self._lock:
            last = self._last_frame
            return dict(version=1, streamId=self._stream_id, generation=self._generation,
                        nextOrdinal=self._ordinal, revision=self._revision, replyId=self._reply,
                        lastFrame=None if last is None else dict(sourceId=last.source_id,
                            frame=last.frame, sourceFrameCount=last.source_frame_count))

    def _expect(self, expected):
        if type(expected) is not OutputFrontier or expected.generation != self._generation:
            self._reject('generation_changed')
        if expected != self._frontier():
            self._reject('frontier_changed', expected.next_ordinal)
        if self._revision == MAX_SAFE_INTEGER or self._ordinal == MAX_SAFE_INTEGER:
            self._reject('sequence_exhausted')

    def reserve_visual_boundary(self, expected_frontier):
        """Fence speculative idle encoding without minting media or receipts."""
        with self._lock:
            self._expect(expected_frontier)
            if self._reply is not None or self._last_frame is None or self._ordinal == 0:
                raise ValueError('ordered_cached_idle_frontier')
            self._revision += 1
            self._event('cached_boundary_reserved')
            return self._frontier()

    def reserve_speech(self, reply_id, expected_frontier):
        with self._lock:
            self._expect(expected_frontier)
            if not _identity(reply_id):
                self._reject('reply_invalid')
            if self._reply is not None or reply_id in self._completed_replies:
                self._reject('reply_conflict')
            self._reply, self._speech = reply_id, None
            self._revision += 1
            self._event('reserved')
            return self._frontier()

    def _check_speech(self, chunk):
        if self._reply != chunk.reply_id:
            self._reject('reply_mismatch', chunk.ordinal)
        previous = self._speech
        if previous is None:
            valid = chunk.sequence_index == 0 and chunk.source_range.start == 0
        elif chunk.sequence_index == previous.sequence_index:
            valid = (chunk.source_id == previous.source_id
                     and chunk.source_range.total_frames == previous.source_range.total_frames
                     and chunk.source_range.start == previous.source_range.end)
        else:
            valid = (chunk.sequence_index == previous.sequence_index + 1
                     and previous.source_range.end == previous.source_range.total_frames
                     and chunk.source_id != previous.source_id and chunk.source_range.start == 0)
        if not valid:
            self._reject('source_gap', chunk.ordinal)

    def next_speech_sequence(self, expected_frontier):
        """Producer cursor, independent of playback and reclaimed media rows."""
        with self._lock:
            self._expect(expected_frontier)
            if self._reply is None:
                self._reject('reply_missing')
            if self._speech is None:
                return 0
            if self._speech.source_range.end != self._speech.source_range.total_frames:
                self._reject('source_not_complete')
            return self._speech.sequence_index + 1

    def commit(self, chunk, expected_frontier):
        with self._lock:
            if type(chunk) is not OutputChunk:
                self._reject('descriptor_invalid')
            if chunk.stream_id != self._stream_id or chunk.generation != self._generation:
                self._reject('generation_changed', chunk.ordinal)
            existing = self._rows.get((chunk.generation, chunk.ordinal))
            if existing is not None:
                if chunk != existing:
                    self._reject('publication_conflict', chunk.ordinal)
                return self._frontier()  # Retried publication changes nothing.
            self._expect(expected_frontier)
            if chunk.ordinal != self._ordinal:
                self._reject('ordinal_gap', chunk.ordinal)
            if chunk.kind == 'idle' and self._reply is not None:
                self._reject('idle_during_reply', chunk.ordinal)
            if chunk.kind == 'speech':
                self._check_speech(chunk)
            if len(self._rows) >= self._max_chunks or self._bytes + chunk.byte_length > self._max_bytes:
                self._reject('capacity', chunk.ordinal)
            self._rows[(chunk.generation, chunk.ordinal)] = chunk
            self._bytes += chunk.byte_length
            self._ordinal += 1
            self._revision += 1
            self._last_frame = chunk.source_range.frames[-1]
            if chunk.kind == 'speech':
                self._speech = chunk
            self._event('committed', chunk.ordinal)
            return self._frontier()

    def finish_reply(self, reply_id, final_sequence_index):
        """Caller supplies authenticated finality, never a timeout or empty queue."""
        with self._lock:
            if self._reply is None or self._reply != reply_id:
                self._reject('reply_mismatch')
            empty = final_sequence_index is None and self._speech is None
            if (not empty and (not _integer(final_sequence_index) or self._speech is None
                    or self._speech.sequence_index != final_sequence_index
                    or self._speech.source_range.end != self._speech.source_range.total_frames)):
                self._reject('reply_not_drained')
            self._completed_replies.append(reply_id)
            self._reply = self._speech = None
            self._revision += 1
            self._event('finished')
            return self._frontier()

    def restart_from_stop(self, stopped):
        """Authenticated caller forwards a native stop receipt, never a plan.

        Resolve the frame from our own retained descriptor before invalidating.
        An explicit unknown receipt seeds no frame; the idle planner can only
        produce fresh initial idle, not claim a seamless stopped-frame successor.
        This neither joins/deletes media nor grants a new speech permission.
        """
        if type(stopped) is not dict or type(stopped.get('known')) is not bool:
            raise ValueError('output_stopped_shape')
        fields = {'version', 'streamId', 'generation', 'known'} | (
            {'ordinal', 'frameOffset', 'provenance'} if stopped['known'] else {'reason'})
        if (set(stopped) != fields or type(stopped['version']) is not int or stopped['version'] != 1
                or stopped['streamId'] != self._stream_id or not _integer(stopped['generation'])):
            raise ValueError('output_stopped_shape')
        with self._lock:
            if stopped['generation'] != self._generation: self._reject('generation_changed')
            frame = None
            if stopped['known']:
                if (stopped['provenance'] != 'codec_surface' or not _integer(stopped['ordinal'])
                        or not _integer(stopped['frameOffset'], 0, 11)):
                    raise ValueError('output_stopped_shape')
                row = self._rows.get((self._generation, stopped['ordinal']))
                if row is None: self._reject('stopped_frame_unretained', stopped['ordinal'])
                if stopped['frameOffset'] >= row.frame_count: self._reject('stopped_frame_outside', stopped['ordinal'])
                frame = row.source_range.frames[stopped['frameOffset']]
            elif type(stopped['reason']) is not str or stopped['reason'] not in STOP_UNAVAILABLE_REASONS:
                raise ValueError('output_stopped_shape')
            self.invalidate(self._generation, 'interruption')
            self._last_frame = frame
            self._event('restarted', stopped.get('ordinal'))
            if frame is None: self._event('stopped_frame_unavailable_' + stopped['reason'])
            return self._frontier()

    def invalidate(self, generation, cause):
        with self._lock:
            if not _integer(generation) or generation != self._generation:
                self._reject('generation_changed')
            if cause not in ('interruption', 'disconnect', 'replacement', 'regeneration', 'failure'):
                self._reject('cause_invalid')
            if generation == MAX_SAFE_INTEGER:
                self._reject('sequence_exhausted')
            self._generation += 1
            self._ordinal = self._revision = 0
            self._retired_through = -1
            self._reply = self._speech = self._last_frame = None
            self._completed_replies.clear()
            # Old media still counts against capacity until its readers join.
            self._event('invalidated')
            return self._frontier()

    def acknowledge(self, generation, ordinal, *, readers_closed):
        """Exact joined range, not cumulative ACK or a playback-time estimate."""
        with self._lock:
            if readers_closed is not True:
                self._reject('reader_not_closed', ordinal)
            if not _integer(generation) or not _integer(ordinal):
                self._reject('ack_invalid')
            row = self._rows.get((generation, ordinal))
            if row is None:
                self._reject('ack_unknown', ordinal)
            if generation == self._generation and ordinal != self._retired_through + 1:
                self._reject('ack_gap', ordinal)
            del self._rows[(generation, ordinal)]
            self._bytes -= row.byte_length
            if generation == self._generation:
                self._retired_through = ordinal
            self._event('released', ordinal)

    def snapshot(self, after_ordinal):
        with self._lock:
            if not _integer(after_ordinal, -1):
                self._reject('snapshot_invalid')
            if after_ordinal < self._retired_through:
                self._reject('snapshot_retired', after_ordinal)
            if after_ordinal >= self._ordinal:
                self._reject('snapshot_ahead', after_ordinal)
            return tuple(row for (generation, ordinal), row in self._rows.items()
                         if generation == self._generation and ordinal > after_ordinal)

    def retained_chunk(self, generation, ordinal):
        """Private publication reconciliation, including retired generations."""
        with self._lock:
            if not _integer(generation) or not _integer(ordinal):
                self._reject('descriptor_invalid', ordinal)
            return self._rows.get((generation, ordinal))
