"""Bounded, sample-contiguous PCM scheduling for one local output stream.

The queue deliberately owns no device; the session owns one lazy stream.
``put`` is the sole producer and ``fill`` is the sole audio consumer.
The queue relies on CPython's GIL for atomic
reference/index publication between those two threads; it is not hard-real-
time safe and must not be shared by multiple producers or consumers.
"""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from core.audio_playback import PreparedPlaybackAudio, local_output_guard


_ENTRY_CAPACITY = 3  # Maximum: current candidate plus at most two later candidates.
_MARKER_CAPACITY = 128
_MISSING_PERMIT = object()


@dataclass(frozen=True, slots=True)
class OutputMarker:
    kind: str
    key: int | None
    dac_time: float
    media_frame: int
    output_frame: int
    monotonic_time: float | None = None


@dataclass(frozen=True, slots=True)
class AudioClockSample:
    key: int | None
    media_seconds: float
    sampled_monotonic: float
    scheduled_through_seconds: float
    running: bool


def continuous_pending_frame(state: Mapping[str, object]) -> tuple[str, int, int] | None:
    """Bounded held cursor for a continuous chunk awaiting its matching clock."""
    if ("audio_chunk_index" not in state or not state.get("audio_start_pending", False)
            or state.get("loop", False)):
        return None
    paths = state.get("frame_paths") or ()
    index = max(0, int(state.get("audio_pending_frame_index", 0) or 0))
    source = int(state.get("audio_pending_source_index", state.get("start_index", 0)) or 0)
    path = str(state.get("audio_pending_frame_path") or (paths[0] if paths else ""))
    return path, index, source


def continuous_media_seconds(state: Mapping[str, object], now_monotonic: float) -> float | None:
    """Project validated transient device media, never past submitted PCM."""
    try:
        media = float(state["audio_media_seconds"])
        sampled = float(state["audio_clock_monotonic"])
        scheduled = float(state["audio_scheduled_through_seconds"])
        running = state["audio_clock_running"]
        now = float(now_monotonic)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if (not isinstance(running, bool) or not all(math.isfinite(v) for v in (media, sampled, scheduled, now))
            or media < 0 or sampled < 0 or scheduled < media):
        return None
    return min(media + (max(0.0, now - sampled) if running else 0.0), scheduled)


class ContinuousAudioQueue:
    """A fixed-capacity SPSC PCM handoff with bounded lifecycle records.

    PCM arrays are accepted only when immutable, C-contiguous float32 frames
    already match this queue's format.  The callback retains finished arrays
    in preallocated retirement slots; control-side calls reclaim them.
    """

    def __init__(
        self,
        *,
        sample_rate: int,
        channels: int,
        stop_event: Any,
        max_future_chunks: int = 2,
        max_future_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        if not isinstance(sample_rate, int) or isinstance(sample_rate, bool) or sample_rate <= 0:
            raise ValueError("sample_rate must be a positive finite integer")
        if not isinstance(channels, int) or isinstance(channels, bool) or channels <= 0:
            raise ValueError("channels must be a positive integer")
        if not isinstance(max_future_chunks, int) or isinstance(max_future_chunks, bool) or not 0 <= max_future_chunks <= 2:
            raise ValueError("max_future_chunks must be between zero and two")
        if not isinstance(max_future_bytes, int) or max_future_bytes < 0:
            raise ValueError("max_future_bytes must be a non-negative integer")
        self.sample_rate = sample_rate
        self.channels = channels
        self.stop_event = stop_event
        self.max_future_chunks = max_future_chunks
        self.max_future_bytes = max_future_bytes

        self._entries: list[tuple[int, np.ndarray, int, int] | None] = [None] * _ENTRY_CAPACITY
        self._write = 0
        self._read = 0
        # Control publishes only tiny scheduling permits after a complete slot
        # exists.  The callback's dict.pop claim is the cancellation/submission
        # linearization point; permits deliberately retain no PCM references.
        self._permits: dict[int, bool] = {}
        # Producer and callback each own one monotonic byte cursor.  Pending
        # future bytes are derived, never updated through a shared ``+=/-=``.
        self._accepted_bytes = 0
        self._claimed_bytes = 0
        self._current: tuple[int, np.ndarray, int, int] | None = None
        self._media_offset = 0
        # Callback writes retirement slots; control reads/reclaims them.  The
        # cursors have one writer each, so neither side clears a slot the
        # callback may still be publishing.
        self._retired: list[np.ndarray | None] = [None] * _ENTRY_CAPACITY
        self._retired_write = 0
        self._retired_read = 0

        self._marker_kind: list[str | None] = [None] * _MARKER_CAPACITY
        self._marker_key: list[int | None] = [None] * _MARKER_CAPACITY
        self._marker_dac: list[float] = [0.0] * _MARKER_CAPACITY
        self._marker_media: list[int] = [0] * _MARKER_CAPACITY
        self._marker_output: list[int] = [0] * _MARKER_CAPACITY
        self._marker_write = 0
        self._marker_read = 0
        self._lifecycle_marker_write = 0
        self._lifecycle_marker_read = 0
        # Control owns reservations.  The callback never performs a shared
        # reservation read-modify-write; published lifecycle records are
        # acknowledged and released only by take_markers().
        self._marker_reservations = 0

        self._known_keys: set[int] = set()
        self._paused = False
        self._finished_input = False
        self._revoked = False
        self._failed = False
        self._error: str | None = None
        self._idle_kind: str | None = None
        self._output_frame = 0
        self._media_frame = 0
        self._clock_key: int | None = None
        self._clock_running = False
        self._fill_active = False
        self._revoke_epoch = 0
        self._revoke_ack_epoch = 0

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def revoked(self) -> bool:
        return self._revoked

    @property
    def idle_reason(self) -> str | None:
        """Latest coalesced callback reason, read by control code without a marker."""
        return self._idle_kind

    def _reclaim_retired(self) -> None:
        """Run only on the producer/control side, never from ``fill``."""
        # Snapshot the callback-only writer before checking callback activity.
        # A callback which begins after this snapshot cannot have its newly
        # retired PCM cleared by this pass, even if the activity read was stale.
        retired_limit = self._retired_write
        # The callback's local PCM variable can outlive the retirement-slot
        # write.  Its final local release is therefore acknowledged by the
        # callback becoming inactive before control clears any retired slot.
        if self._fill_active:
            return
        while self._retired_read != retired_limit:
            slot = self._retired_read % _ENTRY_CAPACITY
            self._retired[slot] = None
            self._retired_read += 1

    def _reclaim_revoked(self) -> None:
        """Release cancellation-owned references only after consumer acknowledgement."""
        if not self._revoked or self._fill_active or self._revoke_ack_epoch < self._revoke_epoch:
            return
        cancelled = 0
        for index in range(self._read, self._write):
            slot = index % _ENTRY_CAPACITY
            if self._entries[slot] is not None:
                self._entries[slot] = None
                cancelled += 1
        self._marker_reservations -= cancelled * 2
        self._read = self._write
        self._current = None

    def _entry_count(self) -> int:
        return self._write - self._read

    def _marker_count(self) -> int:
        return self._marker_write - self._marker_read

    def _optional_marker_count(self) -> int:
        """Return physical idle/error records not already promised by reservations.

        Callback publication orders the general marker cursor before its
        lifecycle cursor; control acknowledgement orders the lifecycle cursor
        before the general read cursor.  An interleaved snapshot can therefore
        only over-count optional occupancy, which is safe backpressure.
        """
        lifecycle_pending = self._lifecycle_marker_write - self._lifecycle_marker_read
        return self._marker_count() - lifecycle_pending

    def _validate(self, key: int, audio: PreparedPlaybackAudio) -> tuple[np.ndarray, int]:
        if not isinstance(key, int) or isinstance(key, bool):
            raise ValueError("key must be an integer")
        if key in self._known_keys:
            raise ValueError("key has already been used in this queue epoch")
        if not isinstance(audio, PreparedPlaybackAudio):
            raise TypeError("audio must be PreparedPlaybackAudio")
        if not isinstance(audio.sample_rate, (int, float)) or not math.isfinite(audio.sample_rate):
            raise ValueError("audio sample rate must be finite")
        if int(audio.sample_rate) != audio.sample_rate or int(audio.sample_rate) != self.sample_rate:
            raise ValueError("audio sample rate is incompatible with the queue")
        pcm = audio.decoded_pcm
        if not isinstance(pcm, np.ndarray) or pcm.ndim != 2:
            raise ValueError("PCM must be a two-dimensional numpy array")
        if pcm.shape[0] <= 0:
            raise ValueError("PCM must contain at least one frame")
        if pcm.shape[1] != self.channels:
            raise ValueError("PCM channel count is incompatible with the queue")
        if pcm.dtype != np.float32 or not pcm.flags.c_contiguous or pcm.flags.writeable:
            raise ValueError("PCM must be immutable contiguous float32")
        if not bool(np.isfinite(pcm).all()):
            raise ValueError("PCM must contain only finite samples")
        return pcm, int(pcm.nbytes)

    def put(self, key: int, audio: PreparedPlaybackAudio) -> bool:
        """Publish one fully validated immutable chunk, or report backpressure."""
        self._reclaim_retired()
        self._reclaim_revoked()
        pcm, byte_count = self._validate(key, audio)
        if self._revoked or self._failed or self._finished_input:
            return False
        # Each admitted chunk also reserves one retirement slot until control
        # reclaims it.  A producer may run between chunks of an active fill.
        if self._write - self._retired_read >= _ENTRY_CAPACITY:
            return False
        entry_count = self._entry_count()
        has_current = self._current is not None
        if entry_count + int(has_current) >= self.max_future_chunks + 1:
            return False
        # An oversize first candidate is allowed; it cannot be future work yet.
        has_preceding = has_current or entry_count > 0
        pending_bytes = self._accepted_bytes - self._claimed_bytes
        if has_preceding and pending_bytes + byte_count > self.max_future_bytes:
            return False
        if self._optional_marker_count() + self._marker_reservations + 2 > _MARKER_CAPACITY:
            self._fail("lifecycle marker capacity exhausted")
            return False

        sequence = self._write
        slot = sequence % _ENTRY_CAPACITY
        self._entries[slot] = (key, pcm, len(pcm), byte_count)
        self._accepted_bytes += byte_count
        self._marker_reservations += 2
        self._known_keys.add(key)
        self._permits[sequence] = True
        self._write = sequence + 1  # Publish only after slot and permit are complete.
        return True

    def _fail(self, reason: str) -> None:
        self._failed = True
        self.revoke()
        self._error = reason
        self._idle_kind = "error"

    def _publish_marker(
        self, kind: str, key: int | None, dac_time: float, media_frame: int, output_frame: int,
    ) -> bool:
        if self._marker_count() >= _MARKER_CAPACITY:
            self._fail("lifecycle marker ring overflow")
            return False
        slot = self._marker_write % _MARKER_CAPACITY
        self._marker_kind[slot] = kind
        self._marker_key[slot] = key
        self._marker_dac[slot] = dac_time
        self._marker_media[slot] = media_frame
        self._marker_output[slot] = output_frame
        self._marker_write += 1
        if kind in ("scheduled_start", "scheduled_end"):
            self._lifecycle_marker_write += 1
        return True

    def _record_idle(self, kind: str, dac_time: float, output_frame: int) -> None:
        if self._idle_kind != kind:
            # Optional idle reports may never consume space reserved for a
            # required start/end pair.  The coalesced state below still keeps
            # the reason visible to control code when the marker ring is full.
            if self._marker_reservations == 0 and self._marker_count() < _MARKER_CAPACITY:
                self._publish_marker(kind, None, dac_time, self._media_frame, output_frame)
            self._idle_kind = kind

    def _take_next(self, dac_time: float, output_frame: int) -> bool:
        if self._revoked:
            self._idle_kind = "revoked"
            return False
        if self._failed:
            self._idle_kind = "error"
            return False
        if self._is_stopped():
            self._idle_kind = "stopped"
            return False
        if self._current is not None:
            return True
        if self._paused:
            self._record_idle("paused", dac_time, output_frame)
            return False
        if self._read == self._write:
            self._record_idle("waiting", dac_time, output_frame)
            return False
        slot = self._read % _ENTRY_CAPACITY
        entry = self._entries[slot]
        if entry is None:  # Cancellation can clear an entry concurrently.
            self._record_idle("waiting", dac_time, output_frame)
            return False
        if not self._commit_entry(self._read, entry):
            return False
        self._entries[slot] = None
        self._read += 1
        self._claimed_bytes += entry[3]
        self._media_offset = 0
        self._clock_key = entry[0]
        self._clock_running = True
        self._idle_kind = None
        return self._publish_marker("scheduled_start", entry[0], dac_time, self._media_frame, output_frame)

    def _commit_entry(self, sequence: int, entry: tuple[int, np.ndarray, int, int]) -> bool:
        """Atomically claim the control-issued permit for callback submission.

        The final stop check is advisory.  ``dict.pop`` is the CPython/GIL
        linearization operation: revoke clears permits, so a claim before the
        clear is in-flight and a claim after the clear cannot schedule a start.
        """
        if self._is_stopped():
            self._idle_kind = "stopped"
            return False
        if self._permits.pop(sequence, _MISSING_PERMIT) is _MISSING_PERMIT:
            self._idle_kind = "revoked" if self._revoked else "error"
            return False
        self._current = entry
        return True

    def _is_stopped(self) -> bool:
        try:
            return bool(self.stop_event.is_set())
        except Exception:
            return False

    def _retire_pcm(self, pcm: np.ndarray) -> bool:
        if self._retired_write - self._retired_read >= _ENTRY_CAPACITY:
            self._fail("retirement capacity exhausted")
            return False
        slot = self._retired_write % _ENTRY_CAPACITY
        self._retired[slot] = pcm
        self._retired_write += 1
        return True

    def fill(self, outdata: Any, *, dac_time: float) -> None:
        """Copy bounded PCM into one callback buffer without blocking or allocating PCM."""
        self._fill_active = True
        current = None
        pcm = None
        try:
            frames = len(outdata)
            outdata[...] = 0.0
            output_offset = 0
            if not math.isfinite(dac_time):
                self._fail("invalid DAC time")
            while output_offset < frames and not self._revoked and not self._failed:
                frame_time = dac_time + output_offset / self.sample_rate
                if not self._take_next(frame_time, self._output_frame + output_offset):
                    break
                current = self._current
                if current is None:
                    break
                key, pcm, total_frames, _byte_count = current
                count = min(frames - output_offset, total_frames - self._media_offset)
                outdata[output_offset:output_offset + count] = pcm[self._media_offset:self._media_offset + count]
                output_offset += count
                self._media_offset += count
                self._media_frame += count
                if self._media_offset == total_frames:
                    end_time = dac_time + output_offset / self.sample_rate
                    self._publish_marker(
                        "scheduled_end", key, end_time, self._media_frame, self._output_frame + output_offset,
                    )
                    if not self._retire_pcm(pcm):
                        break
                    self._current = None
                    self._media_offset = 0
                    self._clock_key = None
                    self._clock_running = False
                    # Pause/revoke are checked by _take_next before another acquire.
            self._output_frame += frames
        finally:
            # Do not acknowledge cancellation until callback-local PCM refs
            # have been relinquished; control may then release queue refs.
            current = None
            pcm = None
            self._fill_active = False
            self._revoke_ack_epoch = self._revoke_epoch

    def take_markers(self, *, limit: int | None = None) -> tuple[OutputMarker, ...]:
        """Reclaim lifecycle records outside the callback in FIFO order."""
        markers: list[OutputMarker] = []
        stop = self._marker_write if limit is None else min(limit, self._marker_write)
        while self._marker_read < stop:
            slot = self._marker_read % _MARKER_CAPACITY
            kind = self._marker_kind[slot]
            if kind is not None:
                markers.append(OutputMarker(
                    kind, self._marker_key[slot], self._marker_dac[slot],
                    self._marker_media[slot], self._marker_output[slot],
                ))
                if kind in ("scheduled_start", "scheduled_end"):
                    self._marker_reservations -= 1
                    self._lifecycle_marker_read += 1
            self._marker_kind[slot] = None
            self._marker_key[slot] = None
            self._marker_read += 1
        self._reclaim_retired()
        self._reclaim_revoked()
        return tuple(markers)

    def clock_sample(self) -> AudioClockSample:
        """Return scheduled-media state, never an audible/device-time assertion.

        Task 3 maps DAC marker times to monotonic observations and keeps
        underflow spans separate; this queue advances this value only for PCM
        copied into an output callback.
        """
        seconds = self._media_frame / self.sample_rate
        return AudioClockSample(
            self._clock_key, seconds, time.monotonic(), seconds, self._clock_running and not self._paused,
        )

    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)
        if not self._paused:
            self._idle_kind = None

    def finish_input(self) -> None:
        self._finished_input = True

    def revoke(self) -> None:
        """Idempotently prevent all later scheduling; the next fill is silent."""
        self._permits.clear()
        if self._revoked:
            return
        self._revoked = True
        self._revoke_epoch += 1
        if not self._fill_active:
            self._revoke_ack_epoch = self._revoke_epoch


class SoundDeviceSpeechSession:
    """Control-thread owner of one lazy stream and its SPSC audio callback.

    False from put means backpressure unless error/aborted/finished is set.
    DAC times are software estimates, not acoustic measurements.  All public
    methods must be serialized by the owner, outside PlaybackService locks.
    """

    def __init__(self, *, sounddevice_module, stop_event, output_device=None,
                 clock=None, diagnostics=None):
        self._sd, self._stop_event, self._device = sounddevice_module, stop_event, output_device
        self._clock = clock or time.monotonic
        self._diagnostics = diagnostics
        self._queue = self._stream = self._guard = None
        self._closed = self._aborted = self._finished = self._paused = False
        self._callback_active = self._stream_finished = self._submitted = False
        self._error = None
        self._anchor = self._latency = 0.0
        self._timing_source = "portaudio_dac"
        self._outstanding = set()
        self._known_keys = set()
        self._pending = []
        self._ready = []
        self._base_seconds = self._media_seconds = self._scheduled_seconds = 0.0
        self._clock_key = None
        self._span_start = [0.0] * _MARKER_CAPACITY
        self._span_end = [0.0] * _MARKER_CAPACITY
        self._span_media = [0.0] * _MARKER_CAPACITY
        self._span_write = self._span_read = 0
        self._valid_marker_write = 0
        self._last_buffer_end = None
        self._last_control_time = None
        self._underflows = self._reported_underflows = 0
        self.abort_cutoff = None

    @property
    def error(self):
        return self._error or (self._queue.error if self._queue else None)

    @property
    def timing_source(self):
        return self._timing_source

    @property
    def submitted_any(self):
        return self._submitted

    def _emit(self, kind, **fields):
        if callable(self._diagnostics):
            try:
                self._diagnostics(kind, fields)
            except Exception:
                pass  # Diagnostic observers cannot break output ownership.

    def _fail(self, reason):
        self._error = reason
        if self._queue is not None:
            self._queue.revoke()

    def _normalize(self, audio):
        if not isinstance(audio, PreparedPlaybackAudio):
            raise TypeError("audio must be PreparedPlaybackAudio")
        rate = audio.sample_rate
        if isinstance(rate, bool) or not isinstance(rate, (float, int)) or not math.isfinite(rate) or rate <= 0 or int(rate) != rate:
            raise ValueError("sample rate must be a positive integer")
        pcm = np.asarray(audio.decoded_pcm)
        if pcm.ndim == 1:
            pcm = pcm.reshape(-1, 1)
        if pcm.ndim != 2 or not pcm.shape[0] or not pcm.shape[1]:
            raise ValueError("PCM must contain frames and channels")
        if pcm.dtype != np.float32 or not pcm.flags.c_contiguous or pcm.flags.writeable:
            pcm = np.array(pcm, dtype=np.float32, order="C", copy=True)
            pcm.setflags(write=False)
        return replace(audio, decoded_pcm=pcm, sample_rate=int(rate))

    def put(self, key, audio):
        if self._closed or self._aborted or self._finished or self.error or self._stop_event.is_set():
            return False
        if not isinstance(key, int) or isinstance(key, bool) or key in self._known_keys:
            raise ValueError("key must be a new integer")
        self._collect(self._clock())
        if self.error:
            return False
        if len(self._outstanding) >= _ENTRY_CAPACITY or len(self._ready) >= _MARKER_CAPACITY - 2:
            return False
        audio = self._normalize(audio)
        rate, channels = audio.sample_rate, audio.decoded_pcm.shape[1]
        if self._queue and (rate, channels) != (self._queue.sample_rate, self._queue.channels):
            if self._outstanding:
                return False
            self._close_stream()
            if self.error:
                self.close()
                return False
            self._base_seconds = self._scheduled_seconds
            self._queue = None
        if self._queue is None:
            queue = ContinuousAudioQueue(sample_rate=rate, channels=channels, stop_event=self._stop_event)
            queue.set_paused(self._paused)
            if not queue.put(key, audio):
                return False
            self._queue = queue
            self._valid_marker_write = 0
            self._last_buffer_end = None
            self._outstanding.add(key)
            self._known_keys.add(key)
            try:
                if self._guard is None:
                    guard = local_output_guard(stop_event=self._stop_event)
                    try:
                        guard.__enter__()
                    except InterruptedError:
                        self.abort(); self.close()
                        return False
                    self._guard = guard
                if self._stop_event.is_set():
                    self.abort(); self.close()
                    return False
                self._stream_finished = False
                self._stream = self._sd.OutputStream(samplerate=rate, channels=channels, dtype="float32",
                    device=self._device, callback=self._make_callback(queue),
                    finished_callback=lambda: self._finished_callback(queue))
                before = self._clock()
                if not self._accept_control_time(before):
                    raise ValueError("invalid calibration clock")
                stream_time = float(self._stream.time)
                after = self._clock()
                if not self._accept_control_time(after) or not math.isfinite(stream_time):
                    raise ValueError("invalid stream clock")
                self._anchor = (before + after) / 2 - stream_time
                self._latency = float(self._stream.latency)
                self._emit("stream_open", monotonic_time=after, clock_uncertainty_seconds=(after-before)/2)
                self._stream.start()
            except Exception as exc:
                self._fail(f"stream open/start failed: {type(exc).__name__}")
                self.close()
                return False
            return True
        if not self._queue.put(key, audio):
            return False
        self._known_keys.add(key)
        self._outstanding.add(key)
        return True

    def _finished_callback(self, queue):
        if queue is self._queue:
            self._stream_finished = True

    def _make_callback(self, queue):
        def callback(outdata, frames, time_info, status):
            outdata[...] = 0.0
            if self._closed or self._aborted or queue is not self._queue or self.error:
                return
            self._callback_active = True
            marker_write, lifecycle_write = queue._marker_write, queue._lifecycle_marker_write
            try:
                if status and getattr(status, "output_underflow", False):
                    self._underflows += 1
                dac = float(time_info.outputBufferDacTime)
                if not math.isfinite(dac) or dac <= 0:
                    current = float(time_info.currentTime)
                    if not math.isfinite(current) or not math.isfinite(self._latency) or self._latency < 0:
                        raise ValueError("unusable DAC clock and latency")
                    dac = current + self._latency
                    self._timing_source = "reported_latency_fallback"
                if self._span_write - self._span_read >= _MARKER_CAPACITY:
                    raise RuntimeError("media span capacity exhausted")
                if self._last_buffer_end is not None:
                    # Device DAC estimates can jitter/overlap (notably Windows
                    # MME). The samples are sequential: don't abort valid PCM or
                    # let its delivery clock precede the previous buffer's end.
                    # Keep forward gaps so underflow time isn't counted as speech.
                    dac = max(dac, self._last_buffer_end)
                before = queue._media_frame
                queue.fill(outdata, dac_time=dac)
                if queue.error:
                    raise RuntimeError("queue failed")
                count = queue._media_frame - before
                if count:
                    slot = self._span_write % _MARKER_CAPACITY
                    self._span_start[slot] = dac + self._anchor
                    self._span_end[slot] = dac + self._anchor + count / queue.sample_rate
                    self._span_media[slot] = self._base_seconds + before / queue.sample_rate
                    self._span_write += 1
                    self._scheduled_seconds = self._base_seconds + queue._media_frame / queue.sample_rate
                    self._submitted = True
                self._last_buffer_end = dac + frames / queue.sample_rate
                self._valid_marker_write = queue._marker_write
            except Exception:
                outdata[...] = 0.0
                # This callback returns silence: never expose its partial
                # scheduled markers as if their PCM had reached the device.
                queue._marker_write = marker_write
                queue._lifecycle_marker_write = lifecycle_write
                self._fail("audio callback failed")
            finally:
                self._callback_active = False
        return callback

    def _accept_control_time(self, now):
        """Validate all clock observations, including both calibration edges."""
        if not math.isfinite(now) or (self._last_control_time is not None and now < self._last_control_time):
            self._fail("invalid monotonic clock")
            return False
        self._last_control_time = now
        return True

    def _collect(self, now):
        if not self._accept_control_time(now):
            return
        queue = self._queue
        if queue is not None and not self._callback_active:
            for marker in queue.take_markers(limit=self._valid_marker_write):
                if marker.kind in ("scheduled_start", "scheduled_end"):
                    self._pending.append(replace(marker,
                        kind="started" if marker.kind == "scheduled_start" else "ended",
                        monotonic_time=marker.dac_time + self._anchor))
        while self._span_read < self._span_write:
            slot = self._span_read % _MARKER_CAPACITY
            start, end, media = self._span_start[slot], self._span_end[slot], self._span_media[slot]
            if now < start:
                break
            self._media_seconds = max(self._media_seconds, media + min(now, end) - start)
            if now < end:
                break
            self._span_read += 1
        future = []
        for marker in self._pending:
            if marker.monotonic_time <= now:
                self._ready.append(marker)
                if marker.kind == "ended":
                    self._outstanding.discard(marker.key)
                    self._clock_key = None
                else:
                    self._clock_key = marker.key
            else:
                future.append(marker)
        self._pending = future

    def poll(self):
        if self._aborted:
            result, self._ready = tuple(self._ready), []
            return result
        self._collect(self._clock())
        if self._underflows != self._reported_underflows:
            self._emit("underflow", underflow=self._underflows)
            self._reported_underflows = self._underflows
        if self._stream_finished and self._outstanding and not self.error:
            self._fail("stream finished before DAC drain")
        if self.error or self._stop_event.is_set():
            return self.abort()
        result, self._ready = tuple(self._ready), []
        return result

    def clock_sample(self):
        now = self._clock()
        if not self._aborted:
            self._collect(now)
        else:
            self._accept_control_time(now)
        running = False
        if not self._aborted and not self.error and self._span_read < self._span_write:
            slot = self._span_read % _MARKER_CAPACITY
            running = self._span_start[slot] <= now < self._span_end[slot]
        return AudioClockSample(self._clock_key, min(self._media_seconds, self._scheduled_seconds),
            now, self._scheduled_seconds, running)

    def set_paused(self, paused):
        self._paused = bool(paused)
        if self._queue:
            self._queue.set_paused(paused)

    def finish_input(self):
        self._finished = True
        if self._queue:
            self._queue.finish_input()

    @property
    def drained(self):
        return bool(self._finished and not self.error and not self._outstanding
                    and not self._pending and not self._ready and self._span_read == self._span_write)

    def abort(self):
        if self._aborted:
            return ()
        if self._queue:
            self._queue.revoke()
        self._aborted = True
        self.abort_cutoff = self._clock()
        if self._stream:
            try:
                self._stream.abort()
            except Exception:
                self._fail("stream abort failed")
        self._collect(self.abort_cutoff)
        result = tuple(marker for marker in self._ready if marker.kind == "started")
        self._ready.clear()
        self._pending.clear()
        self._outstanding.clear()
        self._span_read = self._span_write
        self._emit("abort", monotonic_time=self.abort_cutoff, timing_source=self.timing_source,
            limitation="software DAC estimate; driver buffering and acoustic stop are unmeasured")
        return result

    def _close_stream(self):
        stream, self._stream = self._stream, None
        if stream is not None:
            if self._queue:
                self._queue.revoke()
            try:
                stream.close()
            except Exception:
                self._fail("stream close failed")

    def close(self):
        if self._closed:
            return
        if not self.drained and not self._aborted:
            self._ready.extend(self.abort())
        self._closed = True
        try:
            self._close_stream()
        finally:
            if self._guard is not None:
                guard, self._guard = self._guard, None
                guard.__exit__(None, None, None)
