"""MuseTalk-local immutable WAV windows and atomic parent PNG publication.

Only the parent is a logical speech chunk. Physical render requests remain on
its supervised bridge worker and hold the existing render-order turn until EOF.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import uuid
import wave


def _record_window_event(event, driver, window, **fields):
    """Optional metadata capture must never interrupt inference or publication."""
    try:
        from core.speech_performance import record_event
        record_event(event, speech_id=getattr(driver.source, 'speech_id', ''),
            sequence=getattr(driver.source, 'chunk_index', driver.binding.sequence_index),
            chunk_id=driver.bridge.chunk_id, window_start=window.start_frame,
            frames=window.frame_count, fps=driver.adapter.fps, **fields)
    except Exception:
        pass


def _worker_timing(result, timings):
    try:
        seconds = float(result['render_seconds'])
        if math.isfinite(seconds) and seconds >= 0:
            timings['worker_render_ms'] = seconds * 1000.
    except (KeyError, TypeError, ValueError, OverflowError):
        pass


@dataclass(frozen=True)
class RenderBinding:
    avatar_id: str
    previous_avatar_id: str
    emotion: str
    sequence_index: int
    generation: int
    render_order: int
    first: bool
    reset_timeline: bool


class RenderReservation:
    """One existing render-order turn; queued cancellation cannot leave a hole."""
    def __init__(self, adapter, binding, cancelled, *, fallback=False):
        self.adapter, self.binding, self.cancelled = adapter, binding, cancelled
        self.fallback = fallback
        self.claimed = self.released = self.slot = False
        self._lock = threading.Lock()

    def acquire(self, *, cancel_tokens=()):
        condition = self.adapter.render_order_condition
        def wake():
            with condition:
                condition.notify_all()
        unsubscribers = [token.subscribe(wake) for token in cancel_tokens]
        try:
            if self.fallback:
                with self._lock:
                    self.claimed = not self.released
                    return self.claimed
            with condition:
                condition.wait_for(lambda: self.released or self.cancelled()
                    or any(t.cancelled for t in cancel_tokens)
                    or self.binding.render_order == self.adapter.active_render_order)
                if self.released or self.cancelled() or any(t.cancelled for t in cancel_tokens):
                    self.release()
                    return False
            while not self.adapter.render_slots.acquire(timeout=.1):
                if self.cancelled() or any(t.cancelled for t in cancel_tokens):
                    self.release()
                    return False
            with self._lock:
                if self.released:
                    self.adapter.render_slots.release()
                    return False
                self.slot = self.claimed = True
            return True
        finally:
            for unsubscribe in unsubscribers:
                unsubscribe()

    def release(self):
        with self._lock:
            if self.released:
                return
            self.released = True
            slot, self.slot = self.slot, False
        if slot:
            self.adapter.render_slots.release()
        self.adapter._finish_render_order(self.binding.generation, self.binding.render_order)

    def discard_unclaimed(self):
        with self._lock:
            claimed = self.claimed
        if not claimed:
            self.release()


class _CompletedChanges:
    def subscribe(self, callback):
        callback()
        return lambda: None


class _PNGFrames:
    """Completed child frontier; closing retires bookkeeping, never replay PNGs."""
    width = height = 0
    def __init__(self, paths):
        self.paths = tuple(paths)
        self.capacity = len(paths)
        self.retired = 0
        self.closed = False

    @property
    def available_count(self):
        return 0 if self.closed else len(self.paths) - self.retired

    def read(self, index):
        if self.closed or not self.retired <= index < len(self.paths):
            return None
        return self.paths[index].read_bytes()

    def retire_before(self, index):
        self.retired = min(len(self.paths), max(self.retired, int(index)))

    def close(self):
        self.closed = True


class _OwnedWorkers:
    def __init__(self, adapter):
        self.adapter = adapter

    def spawn(self, *, name, lease, target, on_cancel):
        return self.adapter._spawn_worker(name=name, target=target,
            work_lease=lease, on_cancel=on_cancel)


class MuseTalkWindows:
    def __init__(self, adapter, source, text, binding, parent_dir, *,
                 work_lease, cancelled, fallback):
        self.adapter, self.source, self.text = adapter, source, text
        self.binding, self.parent_dir = binding, Path(parent_dir)
        self.work_lease, self.cancelled, self.fallback = work_lease, cancelled, fallback
        self.bridge = None
        self.start_index = None
        self.playback_admitted_event = threading.Event()
        self._first = True
        self._prepared = False
        self._progress_marker = None
        self._previous_window_end = None
        self._unsubscribe_progress = None

    def publish_progress(self):
        # Reuse bridge notifications: no timer, filesystem scan or inference work.
        closed = self.bridge.closed
        holder = dict(self.bridge.result['result_holder'])
        if closed and self._unsubscribe_progress is not None:
            self._unsubscribe_progress()
            self._unsubscribe_progress = None
        if self.cancelled() or self.source.error is not None:
            return
        # Final frames can drain between _refresh and its following notification.
        # Preserve that successful terminal snapshot even after normal retirement.
        if closed and holder.get('status') != 'rendered':
            return
        finished = self.source.finished
        total = self.source.frame_count
        expected = math.ceil(total * self.adapter.fps / self.source.sample_rate)
        if not finished:
            expected = max(expected, math.ceil(self.source.estimated_duration_seconds * self.adapter.fps))
        rendered = int(holder.get('rendered_frame_count', 0))
        complete = finished and holder.get('status') == 'rendered'
        marker = (expected, rendered, complete)
        if marker == self._progress_marker:
            return
        self._progress_marker = marker
        from addons.musetalk_avatar import state
        state.update_musetalk_pipeline_chunk(self.binding.sequence_index,
            status='rendered' if complete else 'rendering',
            progressive_audio=True, progressive_render_complete=complete,
            rendered_frame_count=rendered, expected_frame_count=expected,
            chunk_id=self.bridge.chunk_id)

    def _check(self):
        if self.cancelled() or self.source.closed or self.source.cancelled or self.bridge.closed:
            raise InterruptedError('Progressive MuseTalk parent was retired.')

    def _prepare(self):
        if not self._prepared:
            self._check()
            self.adapter._ensure_avatar_prepared(self.binding.avatar_id, allow_missing=False)
            self._prepared = True

    def __call__(self, window):
        started = time.perf_counter()
        timings = {'input_wait_ms': window.input_wait_ms,
                   'between_window_wait_ms': max(0., (started-self._previous_window_end)*1000.) if self._previous_window_end is not None else 0.}
        outcome = 'error'
        _record_window_event('muse_window_start', self, window)
        try:
            result = self._render_window(window, timings)
            outcome = 'ok'
            return result
        except InterruptedError:
            outcome = 'cancelled'
            raise
        finally:
            ended = time.perf_counter()
            self._previous_window_end = ended
            _record_window_event('muse_window_end', self, window,
                outcome=outcome, duration_ms=(ended - started) * 1000., **timings)

    def _render_window(self, window, timings):
        self._check()
        self._prepare()
        staging_started = time.perf_counter()
        root = Path(self.adapter.root_dir).resolve() / 'runtime' / 'progressive_musetalk'
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='window-', dir=root) as directory:
            directory = Path(directory)
            path = directory / 'audio.wav'
            prefix = window.prefix_frames
            with wave.open(str(window.audio_path), 'rb') as audio:
                rate, channels, width = audio.getframerate(), audio.getnchannels(), audio.getsampwidth()
                pcm = audio.readframes(audio.getnframes())
            if self._first and not self.fallback:
                previous = self.adapter.previous_audio_tail
                if previous is not None and len(previous):
                    previous = previous.set_frame_rate(rate).set_channels(channels).set_sample_width(width)
                    # Whole-frame prefix alignment preserves the window's visible cursor.
                    extra = math.ceil(len(previous.raw_data) / (channels * width) * self.adapter.fps / rate)
                    phase = self.adapter.fps // math.gcd(50, self.adapter.fps)
                    extra = math.ceil(extra / phase) * phase
                    extra_samples = math.ceil(extra * rate / self.adapter.fps)
                    pcm = bytes(extra_samples * channels * width - len(previous.raw_data)) + previous.raw_data + pcm
                    prefix += extra
            samples = len(pcm) // (channels * width)
            padded_samples = math.ceil(math.ceil(samples * self.adapter.fps / rate) * rate / self.adapter.fps)
            pcm += bytes((padded_samples - samples) * channels * width)
            with wave.open(str(path), 'wb') as output:
                output.setnchannels(channels); output.setsampwidth(width); output.setframerate(rate)
                output.writeframes(pcm)
            timings['staging_ms'] = (time.perf_counter() - staging_started) * 1000.
            self._check()
            if self.fallback:
                child = self.adapter.process_audio_chunk(str(path), self.text,
                    output_filename='progressive_' + uuid.uuid4().hex + '.json',
                    cancel_check=lambda: self.cancelled() or self.source.closed or self.bridge.closed,
                    work_lease=self.work_lease, emotion_name=self.binding.emotion,
                    _progressive_binding=self.binding,
                    _progressive_output_root=str(directory / 'fallback'),
                    _progressive_frame_count=window.frame_count)
                event = child.get('ready_event')
                if event is None:
                    raise RuntimeError('MuseTalk complete renderer did not return a readiness event')
                # Keep private output alive until the owned full renderer drains,
                # even when this parent's audio has already been retired.
                event.wait()
                self._check()
                result = dict(child)
                result.update(child.get('result_holder', {}))
                _worker_timing(result, timings)
                if not result.get('ok', True) or result.get('cancelled'):
                    raise RuntimeError(str(result.get('error') or 'MuseTalk pose rendering failed'))
                prefix = int(result.get('trim_start_frames', 0) or 0)
                self.start_index = int(result.get('start_index', 0) or 0)
                for key in ('start_index', 'source_spans', 'source_indices'):
                    if key in result:
                        self.bridge.result[key] = result[key]
                        self.bridge.result['result_holder'][key] = result[key]
                # Physical fallback output is private; only parent copies survive.
                child_dir = Path(result['frame_dir'])
            else:
                if self._first:
                    if self.binding.first:
                        self.start_index = self.adapter._plan_first_chunk_idle_window(
                            self.binding.avatar_id, playback_admitted_event=self.playback_admitted_event,
                            cancel_check=lambda: self.cancelled() or self.source.closed or self.bridge.closed,
                            work_lease=self.work_lease)
                visible_start = None if self.start_index is None else self.start_index + window.start_frame
                result = self.adapter.bridge.request(dict(action='render_audio',
                    avatar_id=self.binding.avatar_id,
                    avatar_path_override=self.adapter._avatar_path_override_for_id(self.binding.avatar_id),
                    audio_path=str(path), chunk_id=uuid.uuid4().hex, fps=self.adapter.fps,
                    output_root=str(directory / 'frames'), reset_timeline=self._first and self.binding.reset_timeline,
                    overlap_prefix_frames=0, start_timeline_idx=visible_start,
                    skip_audio_prefix_frames=prefix, max_frames=window.frame_count), timeout=180)
                _worker_timing(result, timings)
                self._check()
                if result.get('skip_audio_prefix_frames') != prefix:
                    raise RuntimeError('MuseTalk worker needs a restart for progressive context-window rendering')
                # Context remains in the WAV/Whisper encoder, but only visible images are generated.
                prefix = 0
                if not result.get('ok', True):
                    raise RuntimeError(str(result.get('error') or 'MuseTalk render failed'))
                child_dir = Path(result['frame_dir'])
                if self._first:
                    self.start_index = int(result.get('start_index', 0) or 0)
            # Validate the entire completed contiguous span before exposing any PNG.
            paths = [child_dir / f'{prefix + i:08d}.png' for i in range(window.frame_count)]
            if any(not is_complete_png(path) for path in paths):
                raise RuntimeError('MuseTalk renderer completed with missing contiguous PNG frames')
            self._check()
            publication_started = time.perf_counter()
            published = []
            for index, source_path in enumerate(paths):
                destination = self.parent_dir / f'{window.start_frame + index:08d}.png'
                temporary = self.parent_dir / (destination.name + '.' + uuid.uuid4().hex + '.tmp')
                try:
                    shutil.copy2(source_path, temporary)
                    self._check()
                    os.replace(temporary, destination)
                finally:
                    temporary.unlink(missing_ok=True)
                published.append(destination)
            timings['publication_ms'] = (time.perf_counter() - publication_started) * 1000.
            self._first = False
            ready = threading.Event(); ready.set()
            if self.source.finished:
                count = min(self.source.frame_count, math.ceil(.15 * self.source.sample_rate))
                from pydub import AudioSegment
                self.adapter.previous_audio_tail = AudioSegment(
                    data=self.source.read_frames(self.source.frame_count - count, count),
                    sample_width=2, frame_rate=self.source.sample_rate, channels=self.source.channels)
            return dict(ok=True, frame_buffer=_PNGFrames(published), frame_changes=_CompletedChanges(),
                ready_event=ready, start_index=self.start_index,
                result_holder=dict(ok=True, frame_count=window.frame_count, status='rendered'))


def is_complete_png(path):
    """Match the native preview's complete-file frontier before admitting PCM."""
    try:
        with Path(path).open('rb') as image:
            if image.read(8) != bytes.fromhex('89504e470d0a1a0a'):
                return False
            image.seek(-12, 2)
            return image.read() == bytes.fromhex('0000000049454e44ae426082')
    except (OSError, ValueError):
        return False


def pad_wav_for_frames(path, frame_count, fps):
    """Pad renderer input only; pydub millisecond splits can lose a video frame."""
    with wave.open(str(path), 'rb') as audio:
        params = audio.getparams()
        pcm = audio.readframes(audio.getnframes())
    needed = math.ceil(frame_count * params.framerate / fps)
    if needed > params.nframes:
        pcm += bytes((needed - params.nframes) * params.nchannels * params.sampwidth)
        with wave.open(str(path), 'wb') as output:
            output.setparams(params)
            output.writeframes(pcm)


def process_audio_stream(adapter, audio_source, text, *, work_lease,
                         emotion_name='neutral', chunk_index=0, cancel_check=None):
    from core.progressive_avatar import ProgressiveAvatarBridge
    if work_lease is None:
        raise RuntimeError('Progressive MuseTalk requires owned runtime workers.')
    with adapter._stop_lock:
        if adapter._shutdown_requested() or adapter._stopped:
            raise RuntimeError('MuseTalk avatar is stopped.')
        emotion = str(emotion_name or 'neutral').strip().lower() or 'neutral'
        requested = adapter._resolve_avatar_id_for_emotion(emotion)
        avatar = requested or adapter.avatar_id or adapter.last_queued_avatar_id or adapter.default_avatar_id
        if (requested and requested not in adapter.prepared_avatars
                and not Path(adapter._prepared_avatar_root(requested)).is_dir()):
            avatar = adapter.default_avatar_id
        with adapter.render_order_condition:
            previous = adapter.last_queued_avatar_id
            binding = RenderBinding(avatar, previous, emotion, adapter.reply_chunk_index,
                adapter.reply_generation, adapter.next_render_order, adapter.reply_chunk_index == 0,
                avatar == 'angry_avatar' and previous != avatar)
            adapter.reply_chunk_index += 1
            adapter.next_render_order += 1
            adapter.last_queued_avatar_id = avatar
        adapter._set_active_avatar(avatar)
    def cancelled():
        return (adapter._shutdown_requested() or binding.generation != adapter.reply_generation
            or bool(cancel_check and cancel_check()))
    reservation = RenderReservation(adapter, binding, cancelled)
    bridge = None
    try:
        fallback = previous != avatar and bool(adapter.get_transition_rule(previous, avatar))
        reservation.fallback = fallback
        chunk_id = 'progressive_' + uuid.uuid4().hex
        parent_dir = Path(adapter.root_dir).resolve() / 'runtime' / 'rendered_chunks' / chunk_id
        parent_dir.mkdir(parents=True, exist_ok=True)
        driver = MuseTalkWindows(adapter, audio_source, str(text or ''), binding, parent_dir,
            work_lease=work_lease, cancelled=cancelled, fallback=fallback)
        phase = adapter.fps // math.gcd(50, adapter.fps)
        context = math.ceil(max(.15 * adapter.fps, 1) / phase) * phase
        from addons.musetalk_avatar.progressive_settings import initial_frame_count
        # Freeze the live setting once per logical parent. Later windows stay 2s.
        initial_frames = initial_frame_count(adapter.progressive_buffer_seconds(), adapter.fps)
        bridge = ProgressiveAvatarBridge(audio_source, submit_window=driver,
            directory=Path(adapter.root_dir).resolve() / 'runtime' / 'staged_audio',
            fps=adapter.fps, frame_alignment=phase,
            window_frames=2**30 * adapter.fps if fallback else 2 * adapter.fps,
            initial_window_frames=None if fallback else initial_frames,
            buffer_requirement=None if fallback else (lambda ticket, streaming: initial_frames),
            context_frames=0 if fallback else context, submission_reservation=reservation,
            parent_id=chunk_id, kind='musetalk', frame_transport='png')
        driver.bridge = bridge
        driver._unsubscribe_progress = bridge.subscribe(driver.publish_progress)
        result = bridge.result
        result.update(frame_dir=str(parent_dir), frame_paths=[], progressive_audio=True,
            avatar_id=avatar, emotion=emotion, sequence_index=binding.sequence_index,
            playback_admitted_event=driver.playback_admitted_event)
        result['result_holder'].update(frame_dir=str(parent_dir), progressive_audio=True,
            avatar_id=avatar, emotion=emotion, sequence_index=binding.sequence_index,
            generation=binding.generation, text=str(text or ''), trim_start_frames=0,
            parent_chunk_index=int(chunk_index))
        with adapter._stop_lock:
            if cancelled():
                raise InterruptedError('Progressive MuseTalk parent was retired.')
            adapter._progressive_bridges.add(bridge)
        bridge.start(_OwnedWorkers(adapter), work_lease)
        return result
    except BaseException:
        reservation.discard_unclaimed()
        if bridge is not None:
            bridge.close()
        raise
