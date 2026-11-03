"""Owned, bounded handoffs between the playback worker and local PCM output.

The callback never receives prepared files or effect callbacks. Public control
calls are serialized here; file retirement has its own supervised owner.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
import threading
import time
from typing import TYPE_CHECKING, Callable

from core.continuous_audio import AudioClockSample, SoundDeviceSpeechSession
from core.runtime.contracts import RuntimeFailure
from core.runtime.lifecycle import WorkerSupervisor

if TYPE_CHECKING:
    from core.audio_playback import PreparedPlaybackAudio
    from core.runtime.playback import AudioFilePlaybackCapabilities, PlaybackOwner


def _record_performance(event, **fields):
    """Optional metadata capture must never affect speech ownership or output."""
    try:
        from core.speech_performance import record_event
        record_event(event, **fields)
    except BaseException:
        pass


@dataclass(frozen=True, slots=True)
class LocalPlaybackEvent:
    kind: str
    prepared: object | None
    monotonic_time: float


@dataclass(frozen=True, slots=True)
class LocalRevocation:
    events: tuple[LocalPlaybackEvent, ...]
    unstarted: tuple[object, ...]


@dataclass(slots=True)
class LocalPlaybackFeeder:
    """One route-scoped reservation, guarded by the playback condition.

    The worker keeps file ownership until control transfers a completed result.
    Cancelling output never requires waiting for this worker's blocking I/O.
    """
    prepared: object = None
    audio: object = None
    ready: bool = False
    done: bool = False
    failure: object = None
    cancelled: bool = False
    worker: object = None
    cleanup: object = None


class _LocalPlaybackCleanup:
    """One route-owned deletion lane shared across replacement output epochs."""

    def __init__(self, owner, delete_audio):
        self.owner, self._delete_audio = owner, delete_audio
        self._condition = threading.Condition()
        self._paths = deque()
        self._users = 1
        self._pending = 0
        self.failure = None
        self._supervisor = WorkerSupervisor()
        self._worker = None

    def retain(self):
        with self._condition:
            if not self._users:
                raise RuntimeError("cleanup ownership has ended")
            self._users += 1

    def release(self):
        with self._condition:
            self._users -= 1
            self._condition.notify_all()

    @property
    def pending(self):
        with self._condition:
            return self._pending

    def put(self, path):
        with self._condition:
            if not self._users:
                raise RuntimeError("retirement requires cleanup ownership")
            self._paths.append(path)
            self._pending += 1
            # A replacement session creates no thread before joining this lane.
            if self._worker is None:
                self._worker = self._supervisor.spawn(
                    name=f"nc-local-cleanup-{self.owner.generation}", lease=self.owner.lease,
                    owner_token=self, target=self._run, daemon=False)
            self._condition.notify_all()

    def _run(self, _token):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._paths or not self._users)
                if not self._paths:
                    return
                path = self._paths.popleft()
            try:
                if callable(path):
                    path()
                elif path:
                    self._delete_audio(path)
            except BaseException as exc:
                self.failure = RuntimeFailure("local_playback_cleanup_error", str(exc), exc)
            finally:
                with self._condition:
                    self._pending -= 1
                    self._condition.notify_all()

    def join(self):
        with self._condition:
            # Retired epochs relinquish responsibility to the still-live epoch.
            # The last epoch must remain owned by the playback worker until join.
            worker = self._worker if not self._users else None
        if worker is not None and threading.current_thread() is not worker.thread:
            worker.thread.join()


def _incremental_audio(audio):
    if getattr(audio, "source", None) is None:
        return False
    from core.incremental_playback import IncrementalPlaybackAudio
    return isinstance(audio, IncrementalPlaybackAudio)


def _audio_bytes(audio):
    if _incremental_audio(audio):
        return audio.retained_bytes
    return int(audio.decoded_pcm.nbytes) if audio is not None else 0


def _audio_duration(audio):
    if _incremental_audio(audio):
        return audio.duration_seconds
    return audio.decoded_pcm.shape[0] / audio.sample_rate


class LocalPlaybackSession:
    def __init__(self, *, owner: PlaybackOwner, stop_event: object,
                 output: SoundDeviceSpeechSession,
                 prepare_audio: Callable[[object], PreparedPlaybackAudio],
                 effects: AudioFilePlaybackCapabilities,
                 audio_bytes_for: Callable[[object], int] | None = None,
                 state_callback=None, progress_callback=None, clock_progress_callback=None):
        self.owner, self.stop_event = owner, stop_event
        self._output, self._prepare_audio, self._effects = output, prepare_audio, effects
        self._audio_bytes_for = audio_bytes_for
        self._state_callback, self._progress_callback = state_callback, progress_callback
        self._clock_progress_callback = clock_progress_callback
        self._progress_audio = {}
        self._progress_start = {}
        self._clock_offsets = {}
        self._clock_media_through = 0.0
        self._clock_last_ended = None
        self._lock = threading.RLock()
        self._entries: dict[int, object] = {}
        self._audio: dict[int, PreparedPlaybackAudio] = {}
        self._enqueued: set[int] = set()
        self._seen: set[int] = set()
        self._starts: dict[int, LocalPlaybackEvent] = {}
        self._started_keys: set[int] = set()
        self._revocation = None
        self._closed = False
        self._paused = False
        self._idle_kind = None
        self._failure = None
        self._ducked = False
        self._speaking = False
        self._effect_starts = {}
        self._performance_segments = {}
        self._performance_end_times = {}
        self._cleanup_lane = _LocalPlaybackCleanup(owner, effects.delete_audio)

    def _validate(self, prepared):
        if getattr(prepared, "lease", None) is not self.owner.lease:
            raise ValueError("local handoff must carry the exact owner lease")
        key = getattr(prepared, "index", None)
        if not isinstance(key, int) or isinstance(key, bool):
            raise ValueError("local handoff index must be an integer")
        return key

    def owns(self, prepared):
        with self._lock:
            return self._entries.get(getattr(prepared, "index", None)) is prepared

    def acknowledge_start(self, prepared):
        with self._lock:
            self._starts.pop(prepared.index, None)

    def share_cleanup(self, predecessor):
        """Retain the exact route's deletion owner before retiring its epoch."""
        with self._lock, predecessor._lock:
            if (self.owner is not predecessor.owner or self._closed or predecessor._closed
                    or self._entries or self._enqueued or self._cleanup_lane.pending):
                raise ValueError("cleanup transfer requires a fresh replacement of the same owner")
            predecessor._cleanup_lane.retain()
            self._cleanup_lane.release()
            self._cleanup_lane = predecessor._cleanup_lane

    def adopt(self, prepared, audio):
        """Accept a file/PCM transfer from a revoked predecessor, without I/O."""
        with self._lock:
            key = self._validate(prepared)
            if key in self._seen or len(self._entries) >= 3 or self._closed:
                raise ValueError("invalid replacement handoff")
            self._seen.add(key)
            self._entries[key], self._audio[key] = prepared, audio

    def notify_started(self, prepared):
        self.notify_state("speaking")
        metadata = dict(getattr(prepared, "source_metadata", {}) or {})
        payload = {"source": "tts_playback", "text": prepared.text,
                   "emotion": getattr(prepared, "expression", ""),
                   "sequence_index": prepared.index,
                   "persona_id": str(metadata.get("persona_id", "") or ""),
                   "display_name": str(metadata.get("display_name", "") or ""),
                   "replay": bool(metadata.get("tts_replay", False)),
                   "replay_index": int(metadata.get("replay_index", 0) or 0)}
        if not self.stop_event.is_set():
            try:
                self._effects.segment_started(payload)
            except BaseException:
                pass
        if self.stop_event.is_set():
            return
        with self._lock:
            already_ducked = self._ducked
        ducked = not already_ducked and bool(self._effect(self._effects.duck_start, payload))
        with self._lock:
            retired = self._closed or self._revocation is not None or self.stop_event.is_set()
            audio = self._audio.get(prepared.index)
            if not retired:
                if ducked:
                    self._ducked = True
                self._effect_starts[prepared.index] = (time.perf_counter(), metadata, audio)
            duration_seconds = (_audio_duration(audio) if _incremental_audio(audio)
                                else self._clock_offsets.get(prepared.index, (0.0, 0.0))[1])
        if retired:
            if ducked:
                self._effect(self._effects.duck_end, {"source": "tts_playback", "reason": "cancelled"})
            return
        source = getattr(prepared, 'audio_source', None)
        fields = {'speech_id': str(getattr(prepared, 'speech_id', '')
                                  or getattr(source, 'speech_id', '')),
                  'sequence': prepared.index,
                  'audio_duration_seconds': source.duration_seconds if source is not None else duration_seconds}
        if source is not None:
            fields.update(sample_rate=source.sample_rate,
                          startup_buffer_seconds=source.startup_seconds)
        with self._lock:
            actual_start = self._progress_start.get(prepared.index)
            if actual_start is not None:
                fields['started_monotonic'] = actual_start
            self._performance_segments[prepared.index] = {
                'fields': fields, 'source': source, 'state': None}
        _record_performance('speech_playback_start', **fields)
        self._trace("tts_chunk_playback_start", {
            "trace_id": str(metadata.get("tts_trace_id", "") or ""),
            "text": prepared.text, "sequence": prepared.index,
            "duration_seconds": duration_seconds,
            "replay": payload["replay"], "replay_index": payload["replay_index"],
            "owner_generation": self.owner.generation})

    @staticmethod
    def _effect(callback, payload):
        try:
            return callback(dict(payload))
        except BaseException:
            return None

    def _trace(self, event, fields):
        try:
            self._effects.trace(event, fields)
        except BaseException:
            pass

    def notify_ended(self, key, reason="completed"):
        with self._lock:
            self._progress_audio.pop(key, None)
            self._progress_start.pop(key, None)
            started = self._effect_starts.pop(key, None)
            segment = self._performance_segments.pop(key, None)
            actual_end = self._performance_end_times.pop(key, None)
        if segment is not None:
            fields = dict(segment['fields'])
            source = segment['source']
            if source is not None:
                fields['audio_duration_seconds'] = source.duration_seconds
            if actual_end is not None:
                fields['ended_monotonic'] = actual_end
            fields['outcome'] = reason if reason != 'completed' or source is None or source.succeeded else 'failed'
            fields['playback_reason'] = fields['outcome']
            _record_performance('speech_playback_end', **fields)
        if started is not None:
            timestamp, metadata, audio = started
            source = getattr(audio, "source", None) if _incremental_audio(audio) else None
            self._trace("tts_chunk_playback_end", {
                "trace_id": str(metadata.get("tts_trace_id", "") or ""),
                "sequence": key, "replay": bool(metadata.get("tts_replay", False)),
                "replay_index": int(metadata.get("replay_index", 0) or 0),
                "duration_ms": round(max(0.0, time.perf_counter() - timestamp) * 1000, 3),
                **({"duration_seconds": source.duration_seconds,
                    "playback_reason": reason if reason != "completed" or source.succeeded else "failed"}
                   if source is not None else {})})

    def prepare(self, prepared):
        with self._lock:
            key = self._validate(prepared)
            if key in self._seen:
                raise ValueError("duplicate local handoff index")
            if self._revocation is not None or self._closed or self.stop_event.is_set():
                raise RuntimeError("local playback epoch is revoked")
            if not self.can_prepare:
                raise RuntimeError("local handoff capacity exhausted")
            self._entries[key] = prepared
            self._seen.add(key)
            audio = self._prepare_audio(prepared)
            self._audio[key] = audio
            return audio

    def prepare_detached(self, prepared):
        """Decode on the supervised feeder, before transfer to this epoch."""
        audio = self._prepare_audio(prepared)
        return audio if _incremental_audio(audio) else self._output._normalize(audio)

    def estimated_audio_bytes(self, prepared):
        audio = getattr(prepared, "playback_audio", None)
        if audio is not None:
            return _audio_bytes(audio)
        source = getattr(prepared, "audio_source", None)
        if source is not None:
            return source.retained_bytes
        if self._audio_bytes_for is not None:
            return max(0, int(self._audio_bytes_for(prepared)))
        # Unknown formats cannot expand decoded lookahead. They may be current.
        return 64 * 1024 * 1024 + 1

    def can_prepare_bytes(self, size):
        with self._lock:
            if not self.can_prepare:
                return False
            # The oldest entry is current, including before its first callback.
            # An oversized candidate is allowed once all predecessors retire.
            future = tuple(self._audio.values())[1:]
            used = sum(_audio_bytes(audio) for audio in future)
            return not self._entries or used + size <= 64 * 1024 * 1024

    def enqueue(self, prepared, audio):
        with self._lock:
            key = self._validate(prepared)
            if self._revocation is not None or self._closed or self.stop_event.is_set():
                return False
            if key in self._enqueued:
                raise ValueError("duplicate local device admission")
            if key not in self._entries:
                if key in self._seen:
                    raise ValueError("duplicate local handoff index")
                if not self.can_prepare:
                    return False
                self._seen.add(key)
                self._entries[key] = prepared
                self._audio[key] = audio
            if self._entries[key] is not prepared or self._audio[key] is not audio:
                raise ValueError("local handoff identity changed")
            if not self._output.put(key, audio):
                return False
            self._enqueued.add(key)
            duration = _audio_duration(audio)
            self._clock_offsets[key] = (self._clock_media_through, duration)
            self._clock_media_through += duration
            self._progress_audio[key] = audio
            return True

    def notify_state(self, state):
        with self._lock:
            speaking = state == "speaking"
            if speaking and (self.stop_event.is_set() or self._closed or self._revocation is not None):
                return
            if speaking == self._speaking:
                return  # Preparation and adjacent ready chunks have no idle effects.
            self._speaking = speaking
            ducked = self._ducked if not speaking else False
            if not speaking:
                self._ducked = False
        if ducked:
            self._effect(self._effects.duck_end, {"source": "tts_playback", "reason": state})
        try:
            if callable(self._state_callback):
                self._state_callback(state)
        except BaseException:
            pass

    def notify_progress(self):
        with self._lock:
            clock = self.chunk_clock_sample()
            audio = self._progress_audio.get(clock.key) if clock is not None else None
            start = self._progress_start.get(clock.key) if clock is not None else None
            prepared = self._entries.get(clock.key) if clock is not None else None
            segment = self._performance_segments.get(clock.key) if clock is not None else None
            transition = None
            if (segment is not None and audio is not None and start is not None
                    and not self.stop_event.is_set()):
                source = segment['source']
                # A final stopped sample is completion, not a buffer underrun.
                complete = (source is not None and source.succeeded
                            and clock.media_seconds >= source.duration_seconds - 1e-7)
                state = ('running' if clock.running else 'paused' if self._paused
                         else 'buffering' if not complete else None)
                if state is not None and state != segment['state']:
                    segment['state'] = state
                    transition = {**segment['fields'], 'state': state,
                        'sampled_monotonic': clock.sampled_monotonic,
                        'media_seconds': clock.media_seconds,
                        'scheduled_through_seconds': clock.scheduled_through_seconds}
        if transition is not None:
            # Read readiness only on observed state changes, on the existing
            # playback owner. An optional avatar gate cannot affect progress.
            try:
                if _incremental_audio(audio):
                    source = audio.source
                    transition.update(pcm_ready_seconds=source.frame_count / source.sample_rate,
                                      source_finished=source.finished)
                    gate = audio.avatar_gate
                    if gate is not None:
                        transition.update(
                            avatar_ready_seconds=gate.playable_frame_count / source.sample_rate,
                            required_lead_seconds=gate.required_audio_buffer_frames / source.sample_rate)
            except BaseException:
                pass
            _record_performance('speech_clock_state', **transition)
        if audio is not None and start is not None and not self.stop_event.is_set():
            if callable(self._progress_callback):
                try:
                    self._progress_callback(audio, clock.media_seconds)
                except BaseException:
                    pass
            if prepared is not None and callable(self._clock_progress_callback):
                try:
                    self._clock_progress_callback(prepared, audio, clock)
                except BaseException:
                    pass

    @property
    def can_prepare(self):
        with self._lock:
            return len(self._entries) < 3 and self._cleanup_lane.pending < 3

    def _translate(self, markers):
        events = []
        for marker in markers:
            prepared = self._entries.get(marker.key)
            if prepared is None:
                continue
            event = LocalPlaybackEvent(marker.kind, prepared, marker.monotonic_time)
            if marker.kind == "started":
                self._progress_start[marker.key] = marker.monotonic_time
                self._starts[marker.key] = event
                self._started_keys.add(marker.key)
            elif marker.kind == 'ended':
                self._performance_end_times[marker.key] = marker.monotonic_time
            events.append(event)
        return tuple(events)

    def poll(self):
        with self._lock:
            events = self._translate(self._output.poll())
            # Due end markers have been relinquished by the callback. Queue
            # deletion, never run file retries on the playback boundary.
            for event in events:
                if event.kind == "ended":
                    self._retire(event.prepared)
            clock = self._output.clock_sample()
            kind = None
            if self.failure is not None:
                kind = "error"
            elif not clock.running and clock.media_seconds >= clock.scheduled_through_seconds - 1e-7:
                if self._paused:
                    kind = "paused"
                elif not self._entries and not self._output.drained:
                    kind = "waiting"
            if kind is not None and kind != self._idle_kind:
                events += (LocalPlaybackEvent(kind, None, clock.sampled_monotonic),)
            self._idle_kind = kind
            return events

    def clock_sample(self) -> AudioClockSample:
        with self._lock:
            return self._output.clock_sample()

    def chunk_clock_sample(self, key: int | None = None) -> AudioClockSample | None:
        """Project this output epoch's PCM clock without changing the raw clock API.

        Live offsets follow the bounded entry lifetime. One numeric ended offset
        permits the final hold sample after its PCM and file have been retired.
        """
        with self._lock:
            projection = getattr(self._output, "chunk_clock_sample", None)
            if callable(projection):
                return projection(key)
            sample = self._output.clock_sample()
            if key is not None and sample.key != key:
                return None  # Start admission requires the active key, never the ended fallback.
            if key is None:
                key = sample.key
                if key is None and self._clock_last_ended is not None:
                    key = self._clock_last_ended[0]
            if sample.key not in (None, key):
                return None
            offset = self._clock_offsets.get(key)
            if offset is None and self._clock_last_ended is not None and self._clock_last_ended[0] == key:
                offset = self._clock_last_ended[1]
            if offset is None:
                return None
            start, duration = offset
            return replace(sample, key=key,
                media_seconds=min(duration, max(0.0, sample.media_seconds - start)),
                scheduled_through_seconds=min(duration, max(0.0, sample.scheduled_through_seconds - start)))

    def set_wakeup(self, callback):
        setter = getattr(self._output, "set_wakeup", None)
        if callable(setter):
            setter(callback)

    @property
    def next_wakeup_seconds(self):
        return getattr(self._output, "next_wakeup_seconds", .005)

    def set_paused(self, paused):
        with self._lock:
            self._paused = bool(paused)
            self._output.set_paused(paused)

    def finish_input(self):
        with self._lock:
            self._output.finish_input()

    @property
    def drained(self):
        with self._lock:
            return self._output.drained

    @property
    def submitted_any(self):
        with self._lock:
            return self._output.submitted_any

    @property
    def has_pending_output(self):
        with self._lock:
            return bool(self._entries) and self._revocation is None

    @property
    def failure(self):
        with self._lock:
            error = self._output.error
            return self._failure or self._cleanup_lane.failure or (
                RuntimeFailure("local_playback_error", str(error)) if error else None)

    def revoke(self, reason):
        with self._lock:
            if self._revocation is not None:
                return self._revocation
            self._translate(self._output.abort())
            # abort synchronously relinquishes callback references. Preserve
            # already-consumed starts for a poll/terminal publication race.
            self._revocation = LocalRevocation(tuple(self._starts.values()),
                tuple(value for key, value in self._entries.items() if key not in self._started_keys))
            return self._revocation

    def release_unstarted(self):
        """Transfer revoked FIFO handoffs to a replacement stop-token epoch."""
        with self._lock:
            if self._revocation is None:
                raise RuntimeError("revoke before transferring handoffs")
            result = tuple((chunk, self._audio.get(chunk.index)) for chunk in self._revocation.unstarted)
            for chunk, _audio in result:
                self._entries.pop(chunk.index, None)
                self._audio.pop(chunk.index, None)
            return result

    def _retire(self, prepared):
        key = prepared.index
        if self._entries.pop(key, None) is None:
            return
        offset = self._clock_offsets.pop(key, None)
        if offset is not None:
            self._clock_last_ended = (key, offset)
        self._audio.pop(key, None)
        self._enqueued.discard(key)
        source = getattr(prepared, "audio_source", None)
        if source is not None:
            if source.finished:
                source.close()
            else:
                self._cleanup_lane.put(source.close)
        self._cleanup_lane.put(str(getattr(prepared, "audio_path", "") or ""))

    def retire(self):
        """Relinquish resources without invoking externally supplied end effects."""
        with self._lock:
            if not self._closed:
                self.revoke("closed")
                self._output.close()
                for prepared in tuple(self._entries.values()):
                    self._retire(prepared)
                self._progress_audio.clear()
                self._progress_start.clear()
                self._closed = True
                self._cleanup_lane.release()

    def flush_retired_effects(self):
        """Dispatch once, after service ownership transitions have been published."""
        with self._lock:
            if not self._closed:
                return
            effects = tuple(self._effect_starts)
        for key in effects:
            self.notify_ended(key, "closed")
        self.notify_state("idle")

    def close(self):
        self.retire()
        self.flush_retired_effects()
        # The owning playback worker remains alive through cleanup. Its normal
        # bounded stop/join therefore also gates restart while deletion is slow.
        self._cleanup_lane.join()
