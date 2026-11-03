"""Map retained streaming PCM to the existing device session's logical chunks.

Only its serialized control owner calls this adapter. Source notifications wake
that owner; decoding, analysis and pumping never run in the audio callback.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
import logging
import numpy as np

from core import audio_playback
from core.audio_playback import PreparedPlaybackAudio, prepare_pcm_audio
from core.continuous_audio import AudioClockSample
from core.incremental_audio import IncrementalAudioSource


class IncrementalPlaybackAudio:
    def __init__(self, source, volume=1., level_fps=30, level_callback=None,
                 analysis_callback=None, logger=print):
        if not isinstance(source, IncrementalAudioSource):
            raise TypeError('Incremental playback requires a typed PCM source')
        self.source = source
        self.volume = audio_playback._normalized_volume(volume)
        self.level_fps = audio_playback._normalized_level_fps(level_fps)
        self.has_level_callback = callable(level_callback)
        self.has_analysis_callback = callable(analysis_callback)
        self.first_voice_block = None
        self.levels = ()
        self.voice_frames = ()
        self._level_callback = level_callback
        self._analysis_callback = analysis_callback
        self._logger = logger
        self._recorded_frames = 0
        self._analysis_pending = None
        self._analysis_finalized = False
        self._smoothed_level = 0.

    @property
    def avatar_gate(self):
        return getattr(self.source, 'avatar_gate', None)

    @property
    def sample_rate(self):
        return self.source.sample_rate

    @property
    def duration_seconds(self):
        actual = self.source.duration_seconds
        return actual if self.source.succeeded else max(actual, self.source.estimated_duration_seconds)

    @property
    def retained_bytes(self):
        return self.source.retained_bytes

    def _record_analysis(self, pcm, offset):
        # Retained audio can enter a replacement epoch at cursor zero. Analysis
        # belongs to the logical segment and is never appended twice on replay.
        skip = max(0, self._recorded_frames - offset)
        new = pcm[skip:]
        if not len(new):
            return
        self._recorded_frames = offset + len(pcm)
        if not (self.has_level_callback or self.has_analysis_callback):
            return
        pending = self._analysis_pending
        pending = new if pending is None else np.concatenate((pending, new))
        step = max(1, self.sample_rate // self.level_fps)
        complete = len(pending) // step * step
        if complete:
            self._append_analysis(pending[:complete])
        self._analysis_pending = pending[complete:].copy() if complete < len(pending) else None

    def _append_analysis(self, pcm):
        prepared = prepare_pcm_audio(pcm, self.sample_rate, level_fps=self.level_fps,
            level_callback=self._level_callback, analysis_callback=self._analysis_callback,
            logger=self._logger)
        frames = prepared.voice_frames
        if frames and self.voice_frames and callable(audio_playback.analyze_voice_block):
            try:
                first = audio_playback.analyze_voice_block(
                    pcm[:max(1, self.sample_rate // self.level_fps)], self.sample_rate,
                    self.voice_frames[-1].spectrum)
                frames = (first, *frames[1:])
            except Exception as exc:
                self._logger(f"Voice analysis error: {exc}")
        if self.first_voice_block is None and prepared.first_voice_block is not None:
            self.first_voice_block = prepared.first_voice_block
        # The file helper starts a fresh envelope per call. Retain the same
        # RMS/peak response across pieces so the logical cadence never resets.
        mono = np.asarray(pcm, dtype=np.float32)
        if mono.ndim > 1:
            mono = mono.mean(axis=1)
        levels = []
        step = max(1, self.sample_rate // self.level_fps)
        for start in range(0, len(mono), step):
            window = mono[start:start + step]
            rms = float(np.sqrt(np.mean(np.square(window))))
            peak = float(np.max(np.abs(window)))
            level = max(0., min(1., rms * 5.5 + peak * .2))
            response = .72 if level > self._smoothed_level else .24
            self._smoothed_level += (level - self._smoothed_level) * response
            if level < .002 and self._smoothed_level < .003:
                self._smoothed_level = 0.
            levels.append(max(0., min(1., self._smoothed_level)))
        self.levels += tuple(levels)
        self.voice_frames += frames

    def prepare_piece(self, data, offset):
        pcm = np.frombuffer(data, dtype='<i2').astype(np.float32).reshape(-1, self.source.channels)
        pcm /= 32768.
        prepared = prepare_pcm_audio(pcm, self.sample_rate, volume=self.volume, logger=self._logger)
        self._record_analysis(prepared.decoded_pcm, offset)
        return prepared

    def finish_analysis(self):
        if self._analysis_finalized:
            return
        if self._analysis_pending is not None:
            self._append_analysis(self._analysis_pending)
            self._analysis_pending = None
        self._analysis_finalized = True


@dataclass
class _LogicalEntry:
    key: int
    audio: object
    cursor: int = 0
    input_done: bool = False
    started: bool = False
    pending: set = field(default_factory=set)
    cached: object = None
    start_seconds: float | None = None
    last_end: object = None
    unsubscribe: object = None
    gate_unsubscribe: object = None
    rebuffering: bool = False

    @property
    def source(self):
        return self.audio.source if isinstance(self.audio, IncrementalPlaybackAudio) else None

    @property
    def duration(self):
        return (self.source.duration_seconds if self.source is not None
                else len(self.audio.decoded_pcm) / self.audio.sample_rate)


class IncrementalSpeechSession:
    """One logical start/end per item, regardless of its number of PCM pieces."""

    def __init__(self, output, wakeup=None):
        self._output = output
        self._wakeup = wakeup
        self._changed = False
        self._entries = {}
        self._pump_queue = deque()
        self._pieces = {}
        self._piece_ends = {}
        self._consumed_seconds = 0.
        self._known_keys = set()
        self._next_piece = 0
        self._submitted_seconds = 0.
        self._current_key = None
        self._last_ended = None
        self._finished = self._base_finished = False
        self._closed = self._aborted = self._paused = False
        self._error = None

    def _wake(self):
        if callable(self._wakeup):
            try:
                self._wakeup()
            except Exception:
                logging.getLogger(__name__).exception('Incremental playback wakeup failed')

    def set_wakeup(self, callback):
        self._wakeup = callback
        self._wake()

    def _source_changed(self):
        # Publish the predicate before waking the caller's condition. poll()
        # clears it before observing source data, so an intervening append or
        # terminal notification cannot be lost before the caller starts waiting.
        self._changed = True
        self._wake()

    def _normalize(self, audio):
        if isinstance(audio, IncrementalPlaybackAudio):
            return audio
        return self._output._normalize(audio)

    def put(self, key, audio):
        if self._closed or self._aborted or self._finished or self.error:
            return False
        if not isinstance(key, int) or isinstance(key, bool) or key in self._known_keys:
            raise ValueError('key must be a new logical integer')
        if len(self._entries) >= 3:
            return False
        entry = _LogicalEntry(key, self._normalize(audio))
        self._entries[key] = entry
        self._pump_queue.append(entry)
        self._known_keys.add(key)
        if entry.source is not None:
            entry.unsubscribe = entry.source.subscribe(self._source_changed)
            gate = entry.audio.avatar_gate
            if gate is not None:
                entry.gate_unsubscribe = gate.subscribe(self._source_changed)
        self._source_changed()
        if entry.source is None:
            try:
                # Completed files historically open output during enqueue. A
                # typed predecessor still waits for the regular control poll.
                self._pump(completed_only=True)
            except Exception as exc:
                self._error = exc
                return False
        return True

    def _pump(self, *, completed_only=False):
        while self._pump_queue:
            entry = self._pump_queue[0]
            source = entry.source
            if completed_only and source is not None:
                return
            if (source is not None and source.succeeded and entry.cursor == source.frame_count
                    and entry.cached is None):
                entry.audio.finish_analysis()
                entry.input_done = True
                self._pump_queue.popleft()
                continue
            if self._paused and source is not None:
                return
            if source is not None:
                if source.error is not None:
                    raise source.error
                if source.closed:
                    raise InterruptedError('PCM source closed before playback drain')
                gate = entry.audio.avatar_gate
                if gate is not None and gate.error is not None:
                    raise gate.error
                if not source.ready:
                    return
                if gate is not None:
                    if entry.started:
                        clock = self._output.clock_sample()
                        if not clock.running and clock.media_seconds >= self._submitted_seconds-1e-7:
                            entry.rebuffering = True
                    if entry.rebuffering:
                        required = max(0, int(getattr(gate, 'required_audio_buffer_frames', 0)))
                        if source.finished:
                            required = min(required, source.frame_count-entry.cursor)
                        if gate.playable_frame_count-entry.cursor < required:
                            return
                        entry.rebuffering = False
                if entry.cached is None:
                    # Bound each device handoff, without treating a piece as a
                    # new linguistic chunk or advancing progress through gaps.
                    limit = max(1, source.sample_rate // 5)
                    if gate is not None:
                        limit = min(limit, max(0, gate.playable_frame_count-entry.cursor))
                        if not limit:
                            return
                    data = source.read_frames(entry.cursor, limit)
                    if data:
                        frames = len(data) // (2 * source.channels)
                        entry.cached = (entry.audio.prepare_piece(data, entry.cursor), frames)
                    elif source.succeeded:
                        entry.audio.finish_analysis()
                        entry.input_done = True
                        self._pump_queue.popleft()
                        continue
                    else:
                        return
            elif entry.cached is None:
                entry.cached = (entry.audio, len(entry.audio.decoded_pcm))
            audio, frames = entry.cached
            piece_key = self._next_piece
            if not self._output.put(piece_key, audio):
                if self._output.error:
                    raise RuntimeError(str(self._output.error))
                return
            self._next_piece += 1
            if entry.start_seconds is None:
                entry.start_seconds = self._submitted_seconds
            self._submitted_seconds += frames / audio.sample_rate
            self._pieces[piece_key] = entry
            self._piece_ends[piece_key] = self._submitted_seconds
            entry.pending.add(piece_key)
            entry.cursor += frames
            entry.cached = None
            if source is None:
                entry.input_done = True
                self._pump_queue.popleft()
        if self._finished and not self._pump_queue and not self._base_finished:
            self._output.finish_input()
            self._base_finished = True

    def _translate(self, markers):
        result = []
        for marker in markers:
            entry = self._pieces.get(marker.key)
            if entry is None:
                continue
            if marker.kind == 'started':
                self._current_key = entry.key
                if not entry.started:
                    entry.started = True
                    result.append(replace(marker, key=entry.key))
            elif marker.kind == 'ended':
                entry.last_end = marker
                entry.pending.discard(marker.key)
                self._pieces.pop(marker.key, None)
                self._consumed_seconds = max(self._consumed_seconds, self._piece_ends.pop(marker.key))
                if self._is_complete(entry):
                    result.append(self._finish_entry(entry))
        return result

    def _is_complete(self, entry):
        return (entry.input_done and not entry.pending and entry.last_end is not None
                and (entry.source is None or entry.source.succeeded))

    def _finish_entry(self, entry):
        marker = replace(entry.last_end, key=entry.key)
        sample = self._output.clock_sample()
        self._last_ended = AudioClockSample(entry.key, entry.duration, sample.sampled_monotonic,
            entry.duration, False)
        if self._current_key == entry.key:
            self._current_key = None
        if entry.unsubscribe is not None:
            entry.unsubscribe()
            entry.unsubscribe = None
        if entry.gate_unsubscribe is not None:
            entry.gate_unsubscribe()
            entry.gate_unsubscribe = None
        self._entries.pop(entry.key)
        return marker

    def _complete(self):
        result = []
        for entry in tuple(self._entries.values()):
            if self._is_complete(entry):
                result.append(self._finish_entry(entry))
        return result

    def poll(self):
        if self._closed or self._aborted:
            return ()
        self._changed = False
        result = self._translate(self._output.poll())
        try:
            if self._error is not None:
                raise self._error
            if self._output.error:
                raise RuntimeError(str(self._output.error))
            for entry in self._entries.values():
                if entry.source is not None and entry.source.error is not None:
                    raise entry.source.error
            self._pump()
            result.extend(self._complete())
        except Exception as exc:
            self._error = exc
            result.extend(self.abort())
        return tuple(result)

    def clock_sample(self):
        sample = self._output.clock_sample()
        entry = self._pieces.get(sample.key)
        key = entry.key if entry is not None else self._current_key
        return replace(sample, key=key)

    def chunk_clock_sample(self, key=None):
        sample = self.clock_sample()
        if key is None:
            key = sample.key
            if key is None:
                return self._last_ended
        elif sample.key not in (None, key):
            return None
        entry = self._entries.get(key)
        if entry is None:
            return self._last_ended if self._last_ended is not None and self._last_ended.key == key else None
        if entry.start_seconds is None or not entry.started:
            return None
        start, duration = entry.start_seconds, entry.duration
        return replace(sample, key=key,
            media_seconds=min(duration, max(0., sample.media_seconds - start)),
            scheduled_through_seconds=min(duration, max(0., sample.scheduled_through_seconds - start)))

    @property
    def next_wakeup_seconds(self):
        if self._closed or self._aborted:
            return None
        if self._changed:
            return 0.
        if not self._pieces:
            return None
        if self._paused:
            sample = self._output.clock_sample()
            if (not sample.running and sample.media_seconds >= sample.scheduled_through_seconds - 1e-7
                    and sample.media_seconds <= self._consumed_seconds + 1e-7):
                return None
        return 1. / 60.

    def set_paused(self, paused):
        paused = bool(paused)
        if paused == self._paused:
            return
        self._paused = paused
        self._output.set_paused(paused)
        self._source_changed()

    def finish_input(self):
        if self._finished:
            return
        self._finished = True
        self._source_changed()

    @property
    def drained(self):
        return bool(self._finished and not self._entries and not self.error and self._output.drained)

    @property
    def submitted_any(self):
        return self._output.submitted_any

    @property
    def error(self):
        return self._error or self._output.error

    @property
    def timing_source(self):
        return self._output.timing_source

    @property
    def abort_cutoff(self):
        return self._output.abort_cutoff

    def _unsubscribe(self):
        for entry in self._entries.values():
            if entry.unsubscribe is not None:
                entry.unsubscribe()
                entry.unsubscribe = None
            if entry.gate_unsubscribe is not None:
                entry.gate_unsubscribe()
                entry.gate_unsubscribe = None

    def abort(self):
        if self._aborted:
            return ()
        # A failed eager device opening may already have aborted the base
        # session while retaining prior starts in its ready queue. Reconcile
        # them before the idempotent abort, so fallback cannot replay speech.
        result = self._translate(marker for marker in self._output.poll() if marker.kind == 'started')
        result.extend(self._translate(self._output.abort()))
        self._aborted = True
        self._unsubscribe()
        return tuple(result)

    def close(self):
        if self._closed:
            return
        if not self.drained:
            self.abort()
        self._closed = True
        self._unsubscribe()
        self._output.close()
        self._pump_queue.clear()
        self._pieces.clear()
        self._piece_ends.clear()
        self._entries.clear()
