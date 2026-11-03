"""Event-driven progressive PCM windows and their composite avatar frame buffer.

The renderer callback stages an immutable context WAV synchronously. Child
notifications only wake this supervised owner; they never read renderer state.
PCM and frame cursors remain absolute across child-buffer retirement.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import logging
import math
from pathlib import Path
import shutil
import tempfile
import threading
import time
import uuid
import wave

from core.runtime.contracts import CancellationToken


@dataclass(frozen=True, slots=True)
class AvatarRenderWindow:
    audio_path: Path
    start_frame: int
    frame_count: int
    prefix_frames: int
    duration_seconds: float
    input_wait_ms: float = 0.


@dataclass(eq=False)
class _WindowFrames:
    window: AvatarRenderWindow
    ticket: dict
    lock: object = field(default_factory=threading.RLock)
    unsubscribe: Callable | None = None
    buffer: object | None = None
    retired: int = 0
    ready: int = 0
    complete: bool = False
    disposed: bool = False


class ProgressiveAvatarBridge:
    """Own one logical speech chunk and adapt its physical render windows."""

    def __init__(self, source, *, submit_window: Callable[[AvatarRenderWindow], dict],
                 directory: Path, fps=25, window_frames=25, context_frames=5,
                 submission_reservation=None, parent_id=None, buffer_requirement=None, clock=time.monotonic,
                 frame_alignment=5, kind="ditto", frame_transport="shared_rgb", initial_window_frames=None):
        if source.sample_rate != 24000 or source.channels != 1:
            raise ValueError('Progressive avatar requires mono 24kHz s16le PCM')
        if type(fps) is not int or not 0 < fps <= source.sample_rate:
            raise ValueError('Progressive avatar requires a positive integral frame rate')
        if type(frame_alignment) is not int or frame_alignment <= 0:
            raise ValueError('Feature frame alignment must be a positive integer')
        if (type(window_frames) is not int or window_frames <= 0 or window_frames % frame_alignment
                or window_frames*source.sample_rate % fps):
            raise ValueError('Render windows must align with feature and PCM sample boundaries')
        if initial_window_frames is None:
            initial_window_frames = window_frames
        if (type(initial_window_frames) is not int or initial_window_frames <= 0
                or initial_window_frames % frame_alignment or initial_window_frames*source.sample_rate % fps):
            raise ValueError('Initial render window must align with feature and PCM sample boundaries')
        if type(context_frames) is not int or context_frames < 0 or context_frames % frame_alignment:
            raise ValueError('Render context must align with the feature stride')
        if not callable(submit_window):
            raise TypeError('Window renderer must be callable')
        self.source = source
        self._submit_window = submit_window
        self._buffer_requirement = buffer_requirement
        self._buffer_streaming = True
        self._clock = clock
        self._delivery_started = None
        self._delivery_start_frame = 0
        self.fps = fps
        self._window_frames = window_frames
        self._initial_window_frames = initial_window_frames
        self._context_frames = context_frames
        self._sample_rate = source.sample_rate
        self._reservation = submission_reservation
        self._condition = threading.Condition(threading.RLock())
        self._revision = 0
        self._windows = []
        self._retired = 0
        self._rendered_through = 0
        self._playable_samples = 0
        self._closed = False
        self._cancelled = False
        self._error = None
        self._started = False
        self._handle = None
        self._cleaned = False
        self._subscribers = {}
        self._next_subscriber = 0
        self._stop = CancellationToken()
        self.width = self.height = 0
        self.capacity = window_frames  # Preflight runs before the first pool is attached.
        self.session_id = 'progressive-' + uuid.uuid4().hex
        self.chunk_id = str(parent_id) if parent_id is not None else uuid.uuid4().hex
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self._staging = Path(tempfile.mkdtemp(prefix='progressive-avatar-', dir=str(directory)))
        holder = dict(ok=True, status='rendering', playback_state='pending',
                      rendered_frame_count=0, expected_frame_count=0,
                      duration_seconds=0., frame_transport=frame_transport, audio_start_pending=True)
        self.result = dict(ok=True, kind=kind, frame_transport=frame_transport,
                           uses_device_clock=True, fps=fps, frame_count=0,
                           duration_seconds=0., ready_event=threading.Event(),
                           result_holder=holder, frame_buffer=self, chunk_id=self.chunk_id,
                           required_buffer_frames=self._required_buffer_frames)
        self._unsubscribe_source = source.subscribe(self._source_changed)
        source.avatar_gate = self

    def _required_buffer_frames(self, streaming=True):
        with self._condition:
            self._buffer_streaming = streaming
            ticket = dict(self.result)
            ticket['result_holder'] = dict(self.result['result_holder'])
            available = max(0, self._rendered_through-self._retired)
        # Provider policy takes its own lock; never call it under the bridge lock.
        required = (self._buffer_requirement(ticket, streaming)
                    if self._buffer_requirement is not None else self._window_frames)
        startup = math.ceil(self.source.startup_seconds * self.fps)
        required = max(startup, int(required))
        if ticket['result_holder'].get('waiting_for_memory') and available:
            # Consume safe ready frames so their RAM can fund the next pool.
            required = min(required, available)
        return max(1, min(ticket['frame_count'], required))

    @property
    def required_audio_buffer_frames(self):
        """PCM sample frames to rebuild after an actual output underrun."""
        return max(1, self._required_buffer_frames(self._buffer_streaming)*self._sample_rate//self.fps)

    def _source_changed(self):
        # Source notifications run outside its lock. Wake a queued reservation
        # too, without treating successful TTS EOF as cancellation.
        if self.source.closed or self.source.error is not None:
            self._stop.cancel('progressive_source_unavailable')
            if self._started:
                # Invalidate promptly; the supervised owner cleans staging after
                # any in-flight synchronous renderer has returned.
                if self.source.error is not None and not self.source.cancelled:
                    self._fail(self.source.error)
                elif self.source.cancelled:
                    self.cancel(self.source.token.reason or 'avatar_cancelled')
                else:
                    self.close()
        self._wake()

    def _wake(self):
        # Safe under renderer locks: never call subscribers or inspect a child.
        with self._condition:
            self._revision += 1
            self._condition.notify_all()

    def subscribe(self, callback):
        if not callable(callback):
            raise TypeError('Avatar subscriber must be callable')
        with self._condition:
            key = self._next_subscriber
            self._next_subscriber += 1
            self._subscribers[key] = callback
        callback()
        def unsubscribe():
            with self._condition:
                self._subscribers.pop(key, None)
        return unsubscribe

    def _notify(self):
        with self._condition:
            callbacks = tuple(self._subscribers.values())
        for callback in callbacks:
            try:
                callback()
            except Exception:
                logging.getLogger(__name__).exception('Progressive avatar subscriber failed')

    @property
    def playable_frame_count(self):
        with self._condition:
            return self._playable_samples

    @property
    def available_count(self):
        with self._condition:
            return 0 if self._closed else max(0, self._rendered_through - self._retired)

    @property
    def closed(self):
        with self._condition:
            return self._closed

    @property
    def cancelled(self):
        with self._condition:
            return self._cancelled

    @property
    def error(self):
        with self._condition:
            return self._error

    def start(self, workers, lease):
        with self._condition:
            if self._closed:
                raise RuntimeError('Progressive avatar bridge is closed')
            if self._started:
                raise RuntimeError('Progressive avatar bridge already started')
            self._started = True
        try:
            self._handle = workers.spawn(name='progressive-avatar-' + self.chunk_id,
                lease=lease, target=self._run, on_cancel=self.cancel)
            return self._handle
        except BaseException:
            if self._reservation is not None:
                self._reservation.discard_unclaimed()
            self.close()
            self._cleanup()
            raise

    def _release_reservation(self):
        if self._reservation is not None:
            self._reservation.release()

    def _run(self, token):
        unsubscribe_token = token.subscribe(self._wake)
        cursor = 0
        submissions_finished = False
        input_wait_started = None
        try:
            if self._reservation is not None:
                if not self._reservation.acquire(cancel_tokens=(self._stop, token, self.source.token)):
                    if not self.closed:
                        if self.source.error is not None and not self.source.cancelled:
                            raise self.source.error
                        if self.source.closed and not self.source.cancelled:
                            self.close()
                        else:
                            self.cancel(self.source.token.reason or token.reason or 'avatar_cancelled')
                    return
            while True:
                with self._condition:
                    observed = self._revision
                    closed = self._closed
                if closed:
                    break
                if token.cancelled or self.source.cancelled:
                    self.cancel(self.source.token.reason or token.reason or 'avatar_cancelled')
                    break
                if self.source.error is not None:
                    raise self.source.error
                if self.source.closed:
                    self.close()
                    break
                # Read EOF first: once true the sample count is immutable.
                # Reading count first could combine a stale count with new EOF
                # and split the last tail at a non-aligned window boundary.
                finished = self.source.finished
                total = self.source.frame_count
                self._refresh(total, finished)
                self._notify()
                if self.closed:
                    break
                window_frames = self._initial_window_frames if cursor == 0 else self._window_frames
                samples_per_window = window_frames*self._sample_rate//self.fps
                right_context = math.ceil(self._context_frames*self._sample_rate/self.fps)
                if cursor < total and (finished or total >= cursor + samples_per_window + right_context):
                    valid_samples = min(samples_per_window, total - cursor)
                    input_wait_ms = max(0., (self._clock()-input_wait_started)*1000.) if input_wait_started is not None else 0.
                    input_wait_started = None
                    self._submit(cursor, valid_samples, total, input_wait_ms=input_wait_ms)
                    cursor += valid_samples
                    continue
                if finished and cursor >= total and not submissions_finished:
                    submissions_finished = True
                    self._release_reservation()
                if not finished and input_wait_started is None:
                    input_wait_started = self._clock()
                with self._condition:
                    self._condition.wait_for(lambda: self._revision != observed or self._closed)
        except Exception as error:
            self._fail(error)
        finally:
            self._release_reservation()
            unsubscribe_token()
            self._cleanup()
            self._notify()

    def _submit(self, cursor, valid_samples, total, *, input_wait_ms=0.):
        start_frame = cursor*self.fps//self._sample_rate
        prefix = min(self._context_frames, start_frame)
        context_start = cursor - math.ceil(prefix*self._sample_rate/self.fps)
        context_stop = min(total, cursor + valid_samples + math.ceil(self._context_frames*self._sample_rate/self.fps))
        path = self._staging / (str(start_frame) + '.wav')
        window = AvatarRenderWindow(path, start_frame,
            (valid_samples*self.fps+self._sample_rate-1)//self._sample_rate, prefix,
            valid_samples / self.source.sample_rate, input_wait_ms)
        try:
            with wave.open(str(path), 'wb') as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(self.source.sample_rate)
                output.writeframes(self.source.read_frames(context_start, context_stop - context_start))
            # No bridge condition may span renderer staging or child operations.
            if self.closed:
                return
            ticket = self._submit_window(window)
        finally:
            path.unlink(missing_ok=True)
        mapping = _WindowFrames(window, ticket)
        changes = ticket.get('frame_changes')
        if changes is None:
            self._dispose(mapping)
            raise RuntimeError('Progressive renderer did not provide frame notifications')
        mapping.unsubscribe = changes.subscribe(self._wake)
        with self._condition:
            closed = self._closed
            if not closed:
                self._windows.append(mapping)
        if closed:
            self._dispose(mapping)
        self._wake()  # Observe frames/errors produced before the subscription.

    def _refresh(self, total, finished):
        with self._condition:
            mappings = tuple(self._windows)
        frontier = 0
        all_complete = True
        waiting_for_memory = False
        geometry = None
        capacity = self._window_frames
        start_index = None
        for mapping in mappings:
            with mapping.lock:
                ticket = mapping.ticket
                if mapping.window.start_frame == 0:
                    start_index = ticket.get('start_index')
                if not mapping.disposed:
                    holder = ticket.get('result_holder', {})
                    waiting_for_memory = waiting_for_memory or bool(holder.get('waiting_for_memory'))
                    error = holder.get('error') or ticket.get('error')
                    if error or holder.get('ok') is False or ticket.get('ok') is False:
                        raise RuntimeError(str(error or 'Progressive avatar rendering failed'))
                    buffer = ticket.get('frame_buffer')
                    if buffer is not None:
                        mapping.buffer = buffer
                        if not getattr(buffer, 'closed', False):
                            available = int(buffer.available_count)
                            if mapping.retired <= mapping.ready:
                                mapping.ready = max(mapping.ready,
                                    min(mapping.window.frame_count, mapping.retired + available))
                            geometry = (buffer.width, buffer.height)
                            capacity = max(capacity, buffer.capacity)
                    ready_event = ticket.get('ready_event')
                    mapping.complete = (mapping.ready == mapping.window.frame_count
                                        and ready_event is not None and ready_event.is_set())
                    if ready_event is not None and ready_event.is_set() and not mapping.complete:
                        raise RuntimeError('Progressive renderer completed with missing frames')
                ready = mapping.ready
                complete = mapping.complete
            if mapping.window.start_frame == frontier:
                frontier += ready
            all_complete = all_complete and complete
        frame_count = (total*self.fps+self._sample_rate-1)//self._sample_rate
        with self._condition:
            self._rendered_through = max(self._rendered_through, frontier)
            self._playable_samples = min(total, self._rendered_through*self._sample_rate//self.fps)
            self.result.update(frame_count=frame_count, duration_seconds=total / self.source.sample_rate)
            holder = self.result['result_holder']
            if frontier > holder['rendered_frame_count']:
                now = self._clock()
                if self._delivery_started is None:
                    self._delivery_started, self._delivery_start_frame = now, frontier
                elif now > self._delivery_started:
                    # Include gaps between physical windows, not just fast bursts.
                    holder['delivery_fps'] = (frontier-self._delivery_start_frame)/(now-self._delivery_started)
            # This composite can retain all known frames across its child pools.
            self.capacity = max(capacity, frame_count)
            holder.update(waiting_for_memory=waiting_for_memory, rendered_frame_count=self._rendered_through,
                          expected_frame_count=frame_count,
                          duration_seconds=total / self.source.sample_rate)
            if geometry is not None:
                self.width, self.height = geometry
            if start_index is not None:
                self.result['start_index'] = start_index
            if finished and frontier >= frame_count and all_complete:
                holder.update(status='rendered', ok=True)
                self.result['ready_event'].set()

    def read(self, parent_frame_index):
        with self._condition:
            if self._closed or parent_frame_index < self._retired:
                return None
            mapping = next((item for item in self._windows
                if item.window.start_frame <= parent_frame_index < item.window.start_frame + item.window.frame_count), None)
        if mapping is None:
            return None
        with mapping.lock:
            if mapping.disposed or mapping.buffer is None:
                return None
            return mapping.buffer.read(parent_frame_index - mapping.window.start_frame)

    def retire_before(self, parent_frame_index):
        with self._condition:
            self._retired = max(self._retired, int(parent_frame_index))
            mappings = tuple(self._windows)
        for mapping in mappings:
            local = max(0, min(mapping.window.frame_count, self._retired - mapping.window.start_frame))
            if not local:
                continue
            with mapping.lock:
                if mapping.disposed:
                    continue
                if mapping.buffer is not None:
                    mapping.buffer.retire_before(local)
                mapping.retired = max(mapping.retired, local)
                if local == mapping.window.frame_count:
                    mapping.complete = mapping.ready == mapping.window.frame_count
                    self._dispose(mapping)
        self._wake()

    @staticmethod
    def _dispose(mapping):
        with mapping.lock:
            if mapping.disposed:
                return
            mapping.disposed = True
            # Retirement is local; it must not cancel the continuous model epoch.
            mapping.ticket.setdefault('result_holder', {})['playback_state'] = 'completed'
            if mapping.unsubscribe is not None:
                mapping.unsubscribe()
                mapping.unsubscribe = None
            buffer = mapping.buffer or mapping.ticket.get('frame_buffer')
            if buffer is not None:
                buffer.close()
            mapping.buffer = None

    def _fail(self, error):
        with self._condition:
            if self._closed:
                return
            self._error = error
            self.result['ok'] = False
            self.result['result_holder'].update(ok=False, status='failed', error=str(error))
            self.result['ready_event'].set()
        self.close()
        self.source.fail(error)

    def cancel(self, reason='avatar_cancelled'):
        with self._condition:
            if self._closed:
                return
            self._cancelled = True
            self._error = InterruptedError(reason)
            self.result['ok'] = False
            self.result['result_holder'].update(ok=False, status='cancelled', error=str(reason))
            self.result['ready_event'].set()
        self.source.cancel(reason)
        self.close()

    def close(self):
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self.result['result_holder']['playback_state'] = 'completed'
            started = self._started
            mappings = tuple(self._windows)
            self._condition.notify_all()
        for mapping in mappings:
            # Stop retaining late pixels even while another submit is in flight.
            mapping.ticket.setdefault('result_holder', {})['playback_state'] = 'completed'
            self._dispose(mapping)
        self._stop.cancel('progressive_bridge_closed')
        if self._reservation is not None:
            self._reservation.discard_unclaimed()
        if not started:
            self._cleanup()
            self._notify()

    def _cleanup(self):
        with self._condition:
            if self._cleaned:
                return
            self._cleaned = True
            self._closed = True
            mappings = tuple(self._windows)
        self._unsubscribe_source()
        for mapping in mappings:
            self._dispose(mapping)
        shutil.rmtree(self._staging)
