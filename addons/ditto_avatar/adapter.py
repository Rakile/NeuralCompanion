"""Local desktop adapter using host TTS chunks and real playback admission."""
from collections import deque
from pathlib import Path
import threading
import time

from core.avatar_runtime import AvatarAdapter
from core.synthesis_order import SynthesisOrder


class DittoAdapter(AvatarAdapter):
    avatar_provider_id = 'ditto'
    supports_frame_buffer = True
    supports_progressive_audio = True

    def __init__(self, service, construction_input):
        self.service = service
        self.context = construction_input
        self.emotion = 'neutral'
        self._pending = deque()
        self._lock = threading.Lock()
        self._epoch = 0
        self._stopped = True
        self._admitted = set()
        self._active_owner = None
        self._live = {}
        self._current = None
        self._progressive_bridges = {}
        self._progressive_order = SynthesisOrder()

    def start(self):
        self._stopped = True
        choice = self.service.bind_choice('neutral')
        path = choice.avatar_path
        if not path or not (Path(path) / 'avatar.json').is_file():
            raise RuntimeError('Prepare or select a Ditto avatar in Ditto Avatar Creator before starting chat.')
        self.service.load_idle(path)
        self.service._show_choice(choice)
        try:
            self.service.client().request('load')
            self.service.warm_up()
        except Exception:
            self.service.unload()
            raise
        self._stopped = False
        self.service.session_running = True
        self.service.status = 'Ditto warmed and ready for local TTS playback at 25 FPS.'
        self.service.changes.notify()
        return True

    def warm_up(self):
        if not self._stopped:
            return True
        return self.start()

    def stop(self):
        self._stopped = True
        self.service.session_running = False
        self.begin_reply()
        self.service.idle()
        self.service.unload()

    stop_strict = stop

    def begin_reply(self, *args, **kwargs):
        with self._lock:
            retired_bridges = tuple(self._progressive_bridges.values())
            self._progressive_bridges.clear()
            self._progressive_order = SynthesisOrder()
            self._epoch += 1
            self._pending.clear()
            self._admitted.clear()
            self._live.clear()
            self._current = None
            self._active_owner = None
            self.service.begin_reply()
            self.service.idle()
        for bridge in retired_bridges:
            bridge.close()

    def set_emotion(self, emotion_name):
        # Playback notifications cannot change already-bound render choices.
        self.emotion = str(emotion_name or 'neutral').lower()

    def prepare_emotion(self, emotion_name):
        self.set_emotion(emotion_name)

    def set_speaking_state(self, is_speaking):
        if not is_speaking:
            self.service.idle(retire=False)

    def process_audio_stream(self, audio_source, text, *, work_lease,
                             emotion_name='neutral', chunk_index=0, cancel_check=None):
        from core.progressive_avatar import ProgressiveAvatarBridge
        workers = getattr(self.context, 'worker_supervisor', None)
        if workers is None or work_lease is None:
            raise RuntimeError('Progressive Ditto requires owned runtime workers.')
        with self._lock:
            if self._stopped:
                raise RuntimeError('Ditto avatar is stopped.')
            epoch = self._epoch
            choice = self.service.bind_choice(emotion_name or 'neutral')
            reservation = self._progressive_order.reserve(1)[0]
        def epoch_cancelled():
            return self._stopped or epoch != self._epoch or bool(cancel_check and cancel_check())
        bridge = None
        def submit(window):
            # Serialize staging admission with begin_reply; no model runs here.
            with self._lock:
                if epoch_cancelled() or bridge.closed or audio_source.cancelled:
                    raise InterruptedError('Progressive Ditto window was retired.')
                import uuid
                result = self.service.submit_audio(window.audio_path,
                    str(text or '') if window.start_frame == 0 else '', uuid.uuid4().hex,
                    int(chunk_index), epoch_cancelled, choice=choice,
                    trim_start_frames=window.prefix_frames, valid_frame_count=window.frame_count,
                    duration_seconds=window.duration_seconds,
                    logical_frame_offset=window.start_frame,
                    logical_frame_count=((audio_source.frame_count+959)//960
                                         if audio_source.finished else None))
                result.get('result_holder', {}).update(parent_chunk_index=int(chunk_index),
                    render_window_start_frame=window.start_frame)
                return result
        try:
            # A fade-out needs the true ending. Retain enough future audio so
            # a window cannot commit pixels that later belong to the fade tail.
            fade_out = max(0, int(dict(choice.settings).get('fade_out', 0)))
            context_frames = max(5, ((fade_out+4)//5)*5)
            bridge = ProgressiveAvatarBridge(audio_source, submit_window=submit,
                directory=self.service.app_root/'runtime/temp/ditto_progressive',
                context_frames=context_frames, submission_reservation=reservation,
                buffer_requirement=self.service.required_buffer_frames)
            result = bridge.result
            result.update(choice=choice, sequence_index=int(chunk_index),
                worker_generation=self.service._generation, progressive_audio=True)
            result['result_holder'].update(sequence_index=int(chunk_index), text=str(text or ''))
            with self._lock:
                if epoch_cancelled():
                    raise InterruptedError('Progressive Ditto chunk was retired.')
                self._live[(work_lease, int(chunk_index))] = (epoch, result)
                self._progressive_bridges[(work_lease, int(chunk_index))] = bridge
                self.service.register_progressive_parent(result)
            bridge.start(workers, work_lease)
            return result
        except BaseException:
            reservation.discard_unclaimed()
            if bridge is not None:
                bridge.close()
            raise

    def process_audio_chunk(self, audio_path, text, output_filename,
                            dry_run_reply_id=None, cancel_check=None, work_lease=None,
                            emotion_name=None, chunk_index=None):
        if self._stopped:
            raise RuntimeError('Ditto avatar is stopped.')
        self.service.session_running = True
        epoch = self._epoch
        lease_factory = getattr(self.context, 'worker_lease_factory', None)
        lease = work_lease if work_lease is not None else (lease_factory() if lease_factory else None)
        def cancelled():
            return self._stopped or epoch != self._epoch or bool(cancel_check and cancel_check())
        if cancelled():
            raise RuntimeError('Ditto chunk was cancelled.')
        choice = self.service.bind_choice(emotion_name or 'neutral')
        if work_lease is not None:
            index = int(chunk_index) if chunk_index is not None else len(self._live)
            result = self.service.submit_audio(audio_path, str(text or ''), Path(output_filename).stem,
                                               index, cancelled, choice=choice)
            with self._lock:
                if cancelled():
                    raise RuntimeError('Ditto chunk was cancelled.')
                self._live[(lease, index)] = (epoch, result)
            return result
        result = self.service.render_audio(audio_path, emotion_name or 'neutral', cancel_check=cancelled, choice=choice)
        if cancelled():
            raise RuntimeError('Ditto chunk was cancelled.')
        result = {**result, 'ok': True, 'kind': 'ditto', 'text': str(text or ''),
                  'chunk_id': Path(output_filename).stem}
        with self._lock:
            if cancelled():
                raise RuntimeError('Ditto chunk was cancelled.')
            self._pending.append((epoch, result, lease))
        return result

    def on_playback_started(self, chunk):
        owner = (getattr(chunk, 'lease', None), getattr(chunk, 'owner_generation', None))
        key = (*owner, getattr(chunk, 'index', None))
        with self._lock:
            if key in self._admitted:
                return
            live = self._live.get((owner[0], key[-1]))
            if live is not None and live[0] == self._epoch:
                result = live[1]
            else:
                result = None
            while self._pending and self._pending[0][0] != self._epoch:
                self._pending.popleft()
            if result is None and not self._pending:
                return
            if result is None and self._pending[0][2] is not None and self._pending[0][2] != owner[0]:
                return
            self._admitted.add(key)
            if result is None:
                _, result, _ = self._pending.popleft()
            self._current = (key, result)
            self._active_owner = owner
            started = getattr(chunk, 'audio_started_monotonic', None)
            if getattr(chunk, 'audio_start_pending', False) or started is None:
                self.service.status = 'Buffered speech frames; waiting for the actual local audio-start timestamp.'
                self.service.changes.notify()
                self.service.play(result, None)
                return
            self.service.play(result, float(started))
            sample = getattr(chunk, 'audio_clock_sample', None)
            if sample is not None and sample.key == key[-1]:
                self.service.update_audio_clock(sample)

    def on_audio_started(self, chunk):
        with self._lock:
            key = (chunk.lease, chunk.owner_generation, chunk.index)
            if self._current is None or self._current[0] != key:
                return
            self.service.play(self._current[1], chunk.audio_started_monotonic or time.monotonic())
            sample = getattr(chunk, 'audio_clock_sample', None)
            if sample is not None:
                self.service.update_audio_clock(sample)

    def on_audio_progress(self, chunk, sample):
        with self._lock:
            key = (chunk.lease, chunk.owner_generation, chunk.index)
            if self._current is not None and self._current[0] == key and sample.key == chunk.index:
                if self._current[1].get('result_holder', {}).get('playback_state') == 'completed':
                    return
                if self.service._active is None:
                    if not sample.running:
                        return
                    self.service.play(self._current[1], sample.sampled_monotonic)
                self.service.update_audio_clock(sample)

    def on_playback_waiting(self, owner):
        with self._lock:
            if (owner.lease, owner.generation) == self._active_owner:
                if self._current and self._current[1].get('progressive_audio'):
                    bridge = self._current[1].get('frame_buffer')
                    if bridge is not None and not bridge.closed:
                        # A visual underrun holds the existing DAC clock/frame.
                        # Retiring here would prevent pending frames from arriving.
                        return
                if self._current:
                    self._current[1].get('result_holder', {})['playback_state'] = 'completed'
                self.service.idle()

    def on_playback_paused(self, owner):
        with self._lock:
            if (owner.lease, owner.generation) != self._active_owner:
                return
            if self._current and self._current[1].get('progressive_audio'):
                bridge = self._current[1].get('frame_buffer')
                if bridge is not None and not bridge.closed:
                    self.service.hold_audio_clock()
                    return
            self.service.idle(retire=False)

    def on_playback_finished(self, receipt):
        with self._lock:
            owner = getattr(receipt, 'owner', None)
            if owner is not None:
                key = (getattr(owner, 'lease', None), getattr(owner, 'generation', None))
                if key != self._active_owner:
                    return
            self.service.idle()
            for _, result in self._live.values():
                result.get('result_holder', {})['playback_state'] = 'completed'
            self._current = None
            self._active_owner = None
            self.service.end_reply()

