"""Shared addon-owned worker lifetime, preparation jobs and desktop preview."""
import json
import math
import queue
from pathlib import Path
import shutil
import tempfile
import threading
import time
import uuid
import wave
from collections import OrderedDict
from dataclasses import replace

from core.tts_latency_diagnostics import print_speech_debug

from .backend import DittoWorkerClient
from .config import DEFAULTS, AVATAR_TUNING_KEYS, PACKAGE_TUNING_KEYS, avatar_tuning, package_tuning, prepare_settings, render_settings, validate_setting
from .frame_memory import FrameBuffer, TRANSPORT
from .emotions import bind_chunk_choice
from .notifications import ChangeNotifications, notify_after


def fps_choice_message(result):
    speed = result['playback_speed']
    change = f'{abs(speed-1)*100:.2f}% {"faster" if speed > 1 else "slower"}'
    return (f"The source is {result['source_fps']:g} FPS. Convert with FFmpeg to 25 FPS "
            f"to preserve duration, or use the original frames ({change} playback at 25 FPS)?")


class DittoService:
    def __init__(self, context=None):
        self._config = getattr(getattr(context, 'capabilities', None), 'runtime_config', None)
        paths = getattr(context, 'paths', None)
        self.app_root = Path(getattr(paths, 'app_root', Path(__file__).resolve().parents[2]))
        self._values = dict(DEFAULTS)
        self._lock = threading.RLock()
        self._operation = threading.Lock()
        self.changes = ChangeNotifications()
        self._client = None
        self._resource_unloading = False
        self._deleting_package = False
        self.status = 'Ready. Ditto uses its own environment; load models when GPU memory is available.'
        self.loaded = False
        self._crop_models_loaded = False
        self.busy = False
        self.progress = 0.0
        self.last_result = {}
        self.preview_path = ''
        self._idle_paths = []
        self._idle_started = time.monotonic()
        self._idle_offset = 0
        self._active = None
        self.next_index = 0
        self._generation = 0
        self._warmed_key = None
        self._fps_choice = None
        self.session_running = False
        self._test_preview_active = False
        self._clock_fields = {}
        self._render_ticket = None
        self._pipeline = []
        self._queue = queue.Queue()
        self._render_thread = None
        self._render_spf = None
        self._warm_render_spf = None
        self._stream_id = uuid.uuid4().hex
        self._stream_active = None
        self._stream_tickets = {}
        self._stream_cancel = {}
        self._stream_retired = False
        self._stream_pool = None
        self._preview_images = OrderedDict()
        self._preview_url = ''
        self._creator_preview_url = ''
        self._preview_audio_stop = threading.Event()
        self._preview_muted = threading.Event()
        self._visible_choice = None
        self._active_avatar_id = None
        self._last_queued_avatar_id = None
        self._source_cursors = {}
        self._creator = None
        self._package_state_cache = None
        self._tuning_cache = {}

    def _base_settings(self):
        current = dict(self._config.snapshot() or {}) if self._config else {}
        result = {key: current.get(key, value) for key, value in self._values.items()}
        repository = Path(str(result['ditto_repo_path'] or '').strip() or DEFAULTS['ditto_repo_path']).expanduser()
        if not repository.is_absolute():
            result['ditto_repo_path'] = str((self.app_root / repository).resolve())
        return result

    def _settings_for_package(self, cfg, pack_id, variant_id=None):
        from .packages import DittoPackageStore
        result = {**cfg, 'ditto_pack_id': pack_id}
        if pack_id:
            store = DittoPackageStore(self.app_root)
            stat = (store.package_root(pack_id) / 'manifest.json').stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
            cached = self._tuning_cache.get(pack_id)
            if cached is None or cached[0] != stamp:
                pack = store.load(pack_id)
                profile = pack.metadata.get('ditto_render_settings')
                cached = (stamp, package_tuning(profile) if profile is not None else None,
                          {key:variant.metadata.get('ditto_render_settings') for key, variant in pack.variants.items()},
                          pack.default_variant)
                self._tuning_cache[pack_id] = cached
            if cached[1] is not None:
                result.update(cached[1])
            if variant_id is not None:
                # Removal can briefly leave the configured avatar stale while
                # Creator repairs the selection. Match runtime's base fallback.
                identifier = variant_id if variant_id in cached[2] else cached[3]
                profile = cached[2].get(identifier)
                if profile is not None:
                    result.update(avatar_tuning(profile, result))
        return result

    def settings_for_package(self, pack_id):
        with self._lock:
            return self._settings_for_package(self._base_settings(), pack_id)

    def settings_for_variant(self, pack_id, variant_id):
        with self._lock:
            return self._settings_for_package(self._base_settings(), pack_id, variant_id)

    @notify_after
    def update_variant_tuning(self, pack_id, variant_id, key, value):
        if key not in AVATAR_TUNING_KEYS:
            raise KeyError(key)
        value = validate_setting(key, value)
        with self._lock:
            if self._deleting_package:
                raise RuntimeError('Wait for package deletion to finish.')
            if not pack_id:
                return self.update(key, value)
            from .packages import DittoPackageStore
            values = {**self.settings_for_variant(pack_id, variant_id), key:value}
            pack = self.selected_package({'ditto_pack_id':pack_id})
            identifier = variant_id or pack.default_variant
            DittoPackageStore(self.app_root).save_variant_tuning(pack_id, identifier, avatar_tuning(values))
            self._tuning_cache.pop(pack_id, None)
        return {'ok': True}

    def _ensure_package_tuning(self, pack_id, values):
        from .packages import DittoPackageStore
        store = DittoPackageStore(self.app_root)
        if 'ditto_render_settings' not in store.load(pack_id).metadata:
            store.save_tuning(pack_id, package_tuning(values))
            self._tuning_cache.pop(pack_id, None)

    def settings(self):
        with self._lock:
            cfg = self._base_settings()
            return self._settings_for_package(cfg, cfg['ditto_pack_id'], cfg['ditto_variant_id'])

    def selected_package(self, cfg=None):
        from .packages import DittoPackageStore
        cfg = cfg or self.settings()
        return DittoPackageStore(self.app_root).load(cfg['ditto_pack_id']) if cfg.get('ditto_pack_id') else None

    def available_pack_emotion_names(self, default_names=()):
        from .packages import effective_emotion_avatar_map
        from .emotions import NATIVE_EMOTIONS
        cfg = self.settings()
        pack = self.selected_package(cfg)
        names = {'neutral', *default_names}
        if pack:
            names.update(effective_emotion_avatar_map(pack, cfg))
        if cfg['ditto_emotion_selection'] == 'From reply emotion':
            names.update('surprised' if name == 'Surprise' else name.lower() for name in NATIVE_EMOTIONS)
            if pack:
                names.update(pack.metadata.get('ditto_emotion_map', {}))
        return sorted(names)

    def package_state(self):
        from .packages import DittoPackageStore, effective_emotion_avatar_map
        cfg = self.settings()
        key = (cfg['ditto_pack_id'], cfg['ditto_variant_id'], repr(cfg['ditto_enabled_pack_emotions']))
        now = time.monotonic()
        if self._package_state_cache and self._package_state_cache[:1] == (key,) and now-self._package_state_cache[1] < 2:
            return self._package_state_cache[2]
        pack = self.selected_package(cfg)
        result = dict(packages=DittoPackageStore(self.app_root).catalog(),
            variants=[dict(id=k, display_name=v.display_name or k) for k,v in pack.variants.items()] if pack else [],
            package_emotions=sorted(pack.emotion_avatar_map()) if pack else [],
            enabled_package_emotions=sorted(effective_emotion_avatar_map(pack,cfg)) if pack else [])
        self._package_state_cache = (key, now, result)
        return result

    def creator(self):
        if self._creator is None:
            from addons.ditto_preprocess.package_controller import CreatorPackageController
            self._creator = CreatorPackageController(self)
        return self._creator

    def package_sources(self, cfg=None):
        from .packages import enabled_variant_ids
        cfg = cfg or self.settings()
        pack = self.selected_package(cfg)
        return [pack.variants[key].avatar_path for key in enabled_variant_ids(pack, cfg)] if pack else []

    def bind_choice(self, emotion_name):
        with self._lock:
            base = self._base_settings()
            cfg = self._settings_for_package(base, base['ditto_pack_id'])
            pack = self.selected_package(cfg)
            choice = bind_chunk_choice(cfg, pack, emotion_name,
                active_avatar_id=self._active_avatar_id, last_queued_avatar_id=self._last_queued_avatar_id)
            if pack:
                self._last_queued_avatar_id = pack.variants[choice.variant_id].avatar_id
            return choice

    def _show_choice(self, choice):
        if choice is None:
            return
        previous_path = self._visible_choice.avatar_path if self._visible_choice else self.settings()['ditto_avatar_path']
        if previous_path != choice.avatar_path:
            self.load_idle(choice.avatar_path)
            self._idle_offset = self._source_cursors.get(choice.avatar_path, 0)
        self._visible_choice = choice
        pack = self.selected_package()
        variant = pack.variants.get(choice.variant_id) if pack else None
        self._active_avatar_id = variant.avatar_id if variant and variant.avatar_path == choice.avatar_path else None

    def _record_source_progress(self, result, shown):
        choice = result.get('choice')
        if choice is not None:
            self._source_cursors[choice.avatar_path] = result.get('start_index', 0) + shown

    @notify_after
    def update(self, key, value):
        with self._lock:
            if self._deleting_package:
                raise RuntimeError('Wait for package deletion to finish.')
        if key.startswith('ditto_enable_'):
            if type(value) is not bool:
                raise ValueError('Emotion enabled must be true or false.')
            cfg = self.settings()
            pack = self.selected_package(cfg)
            tag = key.removeprefix('ditto_enable_')
            if not pack or tag not in pack.emotion_avatar_map():
                raise ValueError('Choose a package emotion.')
            from .packages import effective_emotion_avatar_map
            enabled = set(effective_emotion_avatar_map(pack, cfg))
            enabled.add(tag) if value else enabled.discard(tag)
            return self.update('ditto_enabled_pack_emotions', {**cfg['ditto_enabled_pack_emotions'], pack.pack_id:sorted(enabled)})
        value = validate_setting(key, value)
        with self._lock:
            source_keys = ('ditto_repo_path', 'ditto_python_path', 'ditto_avatar_path', 'ditto_pack_id', 'ditto_variant_id')
            if self.session_running and key in source_keys:
                raise RuntimeError('Unload Ditto before changing its avatar, repository, or Python environment.')
            if self.busy and key in source_keys:
                raise RuntimeError('Wait for the current Ditto operation to finish.')
            selected_pack = None
            selected_variant = None
            if key == 'ditto_pack_id' and value:
                selected_pack = self.selected_package({**self.settings(), key:value})
                if not selected_pack.default_variant_config or any(
                        not (Path(v.avatar_path)/'avatar.json').is_file() for v in selected_pack.variants.values()):
                    raise ValueError('Prepare every avatar in this package before selecting it for chat.')
            elif key == 'ditto_variant_id' and self.settings()['ditto_pack_id']:
                selected_pack = self.selected_package()
                selected_variant = selected_pack.variants.get(value)
                if selected_variant is None:
                    raise ValueError('Choose an avatar from this package.')
            base = self._base_settings()
            if key in AVATAR_TUNING_KEYS and base['ditto_pack_id']:
                return self.update_variant_tuning(base['ditto_pack_id'], base['ditto_variant_id'], key, value)
            if key in PACKAGE_TUNING_KEYS and base['ditto_pack_id']:
                from .packages import DittoPackageStore
                values = {**self.settings_for_package(base['ditto_pack_id']), key: value}
                DittoPackageStore(self.app_root).save_tuning(base['ditto_pack_id'], values)
                self._tuning_cache.pop(base['ditto_pack_id'], None)
                return {'ok': True}
            if key == 'ditto_pack_id':
                if base['ditto_pack_id']:
                    self._ensure_package_tuning(base['ditto_pack_id'], base)
                if value:
                    self._ensure_package_tuning(value, base)
            if key in ('ditto_repo_path', 'ditto_python_path') and self._client:
                self._client.close()
                self._client = None
                self.loaded = False
                self._crop_models_loaded = False
            if key == 'ditto_avatar_path':
                self.load_idle(value)
                self._active = None
                self.next_index = 0
            if key in source_keys:
                self._visible_choice = None
                self._active_avatar_id = None
                self._last_queued_avatar_id = None
                self._source_cursors.clear()
            if key == 'ditto_source_path':
                self._fps_choice = None
            self._values[key] = value
            if self._config:
                self._config.update(key, value)
            self._package_state_cache = None
            if key == 'ditto_pack_id' and value:
                self.update('ditto_variant_id', selected_pack.default_variant)
            elif key == 'ditto_variant_id' and self.settings()['ditto_pack_id']:
                self.update('ditto_avatar_path', selected_variant.avatar_path)
        return {'ok': True}

    @notify_after
    def restore_settings(self, payload):
        # Package data wins over a session's historical copy of render tuning.
        # Migrate legacy payload tuning only if that package has no profile yet.
        values = {key: validate_setting(key, value) for key, value in dict(payload or {}).items()
                  if key in DEFAULTS}
        with self._lock:
            base = self._base_settings()
            pack_id = values.get('ditto_pack_id', base['ditto_pack_id'])
            if pack_id:
                self._ensure_package_tuning(pack_id, {**base, **values})
            if 'ditto_pack_id' in values:
                self.update('ditto_pack_id', pack_id)
            for key, value in values.items():
                if key == 'ditto_pack_id' or (pack_id and key in PACKAGE_TUNING_KEYS):
                    continue
                # The selected package/variant resolves its own portable path.
                if pack_id and key == 'ditto_avatar_path':
                    continue
                self.update(key, value)

    @notify_after
    def _worker_progress(self, event):
        with self._lock:
            self.status = str(event.get('message') or 'Working…')
            total = float(event.get('total') or 0)
            self.progress = min(1, float(event.get('current') or 0)/total) if total else 0

    def client(self):
        with self._lock:
            if self._resource_unloading:
                raise RuntimeError('Ditto resources are being unloaded.')
            if self._client is None:
                cfg = self.settings()
                client = DittoWorkerClient(cfg['ditto_repo_path'], cfg['ditto_python_path'],
                    str(self.app_root / 'runtime/ditto'), progress_callback=self._worker_progress,
                    frame_callback=lambda event: self._frame_ready(event) if self._client is client else None)
                self._client = client
            return self._client

    def _frame_ready(self, event):
        # Wake consumers after descriptor handling has released buffer locks.
        tickets = ()
        try:
            with self._lock:
                session_id = event.get('session_id')
                if event.get('event') == 'stream_failed':
                    tickets = tuple(ticket for (session, _), ticket in self._stream_tickets.items()
                                    if session_id is None or session == session_id)
                else:
                    ticket = self._stream_tickets.get((session_id, event.get('chunk_id')))
                    tickets = (ticket,) if ticket is not None else ()
                self._apply_frame_event(event)
        finally:
            for ticket in tickets:
                changes = ticket.get('frame_changes')
                if changes is not None:
                    changes.notify()

    def _apply_frame_event(self, event):
        with self._lock:
            if str(event.get('event', '')).startswith('stream_'):
                session_id = event.get('session_id')
                if event['event'] == 'stream_failed':
                    if not session_id and event.get('message') == 'Ditto worker exited.':
                        self.loaded = False
                        self.status = 'Ditto worker exited.'
                    self.changes.notify()
                    for (session, _), ticket in list(self._stream_tickets.items()):
                        if session_id is None or session == session_id:
                            ticket['result_holder'].update(status='failed', ok=False, error=event.get('message', 'Ditto stream failed.'))
                            ticket['ready_event'].set()
                            self._close_buffer(ticket)
                    return
                ticket = self._stream_tickets.get((session_id, event.get('chunk_id')))
                if ticket is None or ticket['ready_event'].is_set():
                    if event.get('frame_transport') == TRANSPORT and self._client:
                        self._client.release_frame(event)
                    return
                holder = ticket['result_holder']
                if event.get('frame_transport') == TRANSPORT:
                    try:
                        buffer = ticket['frame_buffer']
                        # Retired audio still needs render completion/rate
                        # accounting, but must never retain obsolete pixels.
                        if (holder.get('playback_state') == 'completed'
                                or buffer.closed or int(event['index']) < buffer.retired):
                            if self._client:
                                self._client.release_frame(event)
                        else:
                            buffer.append(event)
                        if ticket.get('warmup'):
                            buffer.retire_before(int(event['index'])+1)
                    except Exception as error:
                        holder.update(status='failed', ok=False, error=str(error))
                        ticket['ready_event'].set()
                        self._close_buffer(ticket)
                        if self._client:
                            self._client.release_frame(event)
                        return
                holder['rendered_frame_count'] = int(event['index'])+1
                if event.get('frame_transport') == TRANSPORT:
                    now = time.monotonic()
                    wait = float(event.get('buffer_wait_seconds', 0))
                    holder.setdefault('_delivery_first', now)
                    holder.setdefault('_delivery_first_wait', wait)
                    span = now-holder['_delivery_first']-max(0., wait-holder['_delivery_first_wait'])
                    count = holder['rendered_frame_count']
                    if count >= 8 and span >= .2:
                        holder['delivery_fps'] = (count-1)/span
                if event.get('completed'):
                    holder.update(status='rendered', timing=event.get('timing', {}))
                    ticket['ready_event'].set()
                    timing = holder['timing']
                    span = timing.get('frame_output_seconds')
                    count = holder['rendered_frame_count']
                    if holder.get('delivery_fps'):
                        self._render_spf = max(self._render_spf or 0., 1/holder['delivery_fps'])
                    elif span and count > 1:
                        self._render_spf = span/(count-1)
                    if not ticket.get('warmup'):
                        print_speech_debug(f"[Ditto] Chunk {ticket['chunk_id']}: {count} frames complete in continuous pipeline; "
                              f"output span={span or 0:.2f}s (queue/setup excluded); "
                              f"RAM-buffer wait={timing.get('output_buffer_wait_seconds', 0):.2f}s; "
                              f"delivery excluding that wait={timing.get('delivery_fps_excluding_buffer_wait', 0):.2f} FPS.", flush=True)
                return
            ticket = self._render_ticket
            if ticket:
                ticket['result_holder']['rendered_frame_count'] = int(event['index']) + 1

    def submit_audio(self, audio_path, text, chunk_id, sequence_index, cancel_check, *, choice=None, creator_preview=False, package_id=None,
                     trim_start_frames=0, valid_frame_count=None, duration_seconds=None,
                     logical_frame_offset=None, logical_frame_count=None):
        with self._lock:
            choice = choice or self.bind_choice('neutral')
            if package_id is None:
                package_id = self.settings()['ditto_pack_id']
        generation = self._generation
        session_id = self._stream_id
        original_cancel = cancel_check
        cancel_check = lambda: generation != self._generation or session_id != self._stream_id or original_cancel()
        if cancel_check():
            raise RuntimeError('Ditto render cancelled.')
        with wave.open(str(audio_path), 'rb') as audio:
            context_duration = audio.getnframes() / audio.getframerate()
        context_count = math.ceil(context_duration*25)
        if type(trim_start_frames) is not int or trim_start_frames < 0:
            raise ValueError('Context frame offset must be a nonnegative integer.')
        count = context_count-trim_start_frames if valid_frame_count is None else valid_frame_count
        if (type(count) is not int or count < 0
                or (count == 0 and (context_count or valid_frame_count is not None))
                or trim_start_frames+count > context_count):
            raise ValueError('Valid frames must be a positive integer range inside the context audio.')
        if logical_frame_offset is not None and (type(logical_frame_offset) is not int or logical_frame_offset < 0):
            raise ValueError('Logical fade offset must be a nonnegative integer.')
        if logical_frame_count is not None and (logical_frame_offset is None or type(logical_frame_count) is not int
                or logical_frame_count < logical_frame_offset+count):
            raise ValueError('Logical fade frame count must contain this window.')
        duration = context_duration if duration_seconds is None else duration_seconds
        if duration_seconds is not None and (not isinstance(duration, (int, float))
                or isinstance(duration, bool) or not math.isfinite(duration) or duration <= 0):
            raise ValueError('Audio duration must be finite and positive.')
        root = self.app_root / 'runtime/ditto/renders' / uuid.uuid4().hex
        root.mkdir(parents=True)
        staged = root / 'speech.wav'
        shutil.copy2(audio_path, staged)
        holder = {'sequence_index': sequence_index, 'text': text, 'status': 'queued',
                  'playback_state': 'pending', 'rendered_frame_count': 0,
                  'frame_transport': TRANSPORT, 'audio_start_pending': True,
                  'expected_frame_count': count, 'duration_seconds': duration}
        ticket = {'ok': True, 'kind': 'ditto', 'frame_transport': TRANSPORT, 'fps': 25,
                  'choice': choice,
                  'trim_start_frames': trim_start_frames, 'valid_frame_count': valid_frame_count,
                  'progressive_window': valid_frame_count is not None,
                  'logical_frame_offset': logical_frame_offset, 'logical_frame_count': logical_frame_count,
                  'frame_changes': ChangeNotifications(),
                  'creator_preview': creator_preview, 'package_id': package_id,
                  'frame_count': holder['expected_frame_count'], 'chunk_id': chunk_id,
                  'stream_token': uuid.uuid4().hex,
                  'uses_device_clock': True,
                  'worker_generation': generation,
                  'sequence_index': sequence_index, 'duration_seconds': duration,
                  'ready_event': threading.Event(), 'result_holder': holder}
        ticket['required_buffer_frames'] = lambda streaming: self.required_buffer_frames(ticket, streaming)
        # NC reevaluates the lead through required_buffer_frames. Do not freeze
        # a warmup estimate here: the actual bounded RAM pool is not attached yet.
        with self._lock:
            if not ticket['progressive_window']:
                self._pipeline.append(holder)
            self._stream_tickets[(session_id, ticket['stream_token'])] = ticket
            self._stream_cancel[(session_id, ticket['stream_token'])] = cancel_check
            self._queue.put((ticket, staged, cancel_check, session_id))
            if self._render_thread is None or not self._render_thread.is_alive():
                self._render_thread = threading.Thread(target=self._render_jobs, name='ditto-render-queue', daemon=True)
                self._render_thread.start()
        return ticket

    def required_buffer_frames(self, ticket, streaming):
        """Re-evaluated by NC's gate; queued chunks must not freeze a warmup guess."""
        with self._lock:
            count = ticket['frame_count']
            if ticket.get('complete_before_playback'):
                return count
            limit = min(count, getattr(ticket.get('frame_buffer'), 'capacity', count))
            rates = []
            if self._render_spf:
                rates.append(1/self._render_spf)
            observed = ticket.get('result_holder', {}).get('delivery_fps')
            if observed:
                rates.append(observed)
            if not rates:
                return min(limit, 25 if streaming else 62)
            # Reserve one second of lead and allow a 15% delivery-rate drop.
            # This changes only avatar admission, never NC's speech chunk sizes.
            rate = min(rates)*.85
            required = math.ceil(count*max(0., 1-rate/25)+25)
            base = 12 if streaming else 62
            # A long chunk can need more lead than the fixed pixel budget fits.
            # Start once that pool fills; existing clock/idle handling covers a
            # later underrun without discarding the speech or growing memory.
            return min(limit, max(base, required))

    def _render_jobs(self):
        while True:
            try:
                item = self._queue.get(timeout=.1)
            except queue.Empty:
                active = self._stream_active
                if active and (active != self._stream_id or self._stream_retired
                               or any(check() for (session, _), check in list(self._stream_cancel.items()) if session == active)):
                    try:
                        with self._operation:
                            client = self._client
                            if client and self._stream_active == active:
                                result = client.request('stream_stop', session_id=active)
                                print_speech_debug(f"[Ditto] Continuous session stopped: {result.get('written_frames', 0)} frames; "
                                      f"output={result.get('output_fps', 0):.2f} FPS; "
                                      f"RAM-buffer wait={result.get('output_buffer_wait_seconds', 0):.2f}s; "
                                      f"delivery excluding that wait={result.get('delivery_fps_excluding_buffer_wait', 0):.2f} FPS; "
                                      f"input tail flushes={result.get('starved_flushes', 0)}.", flush=True)
                                stages = result.get('stage_seconds', {})
                                print_speech_debug(f"[Ditto] Stage wall times (overlap, not additive): motion={result.get('motion_seconds', 0):.2f}s; "
                                      f"warp={stages.get('warp_f3d', 0):.2f}s; decoder={stages.get('decode_f3d', 0):.2f}s; "
                                      f"composition={stages.get('putback', 0):.2f}s; "
                                      f"RAM high-water={result.get('buffer_high_water', 0)}/{result.get('buffer_capacity', 0)} frames.", flush=True)
                                masks = result.get('mask_cache')
                                if masks:
                                    print_speech_debug(f"[Ditto] Prepared mask cache: {masks.get('session_hits', 0)} hits, "
                                          f"{masks.get('session_misses', 0)} misses; "
                                          f"RAM={masks.get('cached_bytes', 0)/1024**2:.1f}/"
                                          f"{masks.get('budget_bytes', 0)/1024**2:.0f} MiB; masked-region blending active.", flush=True)
                                self._stream_active = None
                    except Exception as error:
                        self._frame_ready({'event': 'stream_failed', 'session_id': active, 'message': str(error)})
                        self.unload()
                continue
            ticket, staged, cancelled, session_id = item
            holder = ticket['result_holder']
            try:
                if cancelled():
                    raise RuntimeError('Ditto render cancelled.')
                holder['status'] = 'rendering'
                with self._operation:
                    # A played/retired window may still be queued behind other
                    # work. Skip just this job without stopping its reply stream.
                    if ticket.get('progressive_window') and holder.get('playback_state') == 'completed':
                        holder['status'] = 'retired'
                        ticket['ready_event'].set()
                        self._close_buffer(ticket)
                        with self._lock:
                            self._stream_cancel.pop((session_id, ticket['stream_token']), None)
                        continue
                    if cancelled():
                        raise RuntimeError('Ditto render cancelled.')
                    # Logical windows retain their parent's captured settings
                    # so tuning/fades cannot reset motion at a physical boundary.
                    # Ordinary chunks still refresh parameters at admission.
                    with self._lock:
                        if ticket.get('logical_frame_offset') is not None:
                            settings = dict(ticket['choice'].settings)
                        else:
                            settings = render_settings(self.settings_for_variant(
                                ticket['package_id'], ticket['choice'].variant_id))
                        settings['emotion'] = ticket['choice'].native_emotion
                        ticket['choice'] = replace(ticket['choice'],
                            settings=tuple(sorted(settings.items())))
                    client = self.client()
                    # Superseding speech retires the stream after this short RPC
                    # returns. Only explicit unload/worker replacement kills CUDA.
                    worker_cancelled = lambda: ticket['worker_generation'] != self._generation
                    def check_reply():
                        if cancelled():
                            if not worker_cancelled():
                                client.request('stream_stop', session_id=session_id, cancel_check=worker_cancelled)
                            self._stream_active = None
                            raise RuntimeError('Ditto render cancelled.')
                    if self._stream_active != session_id:
                        begun = client.request('stream_begin', session_id=session_id,
                            avatar_path=ticket['choice'].avatar_path, settings=settings,
                            # Creator tests one source; chat retains its enabled package variants.
                            variants=[] if ticket.get('creator_preview') else self.package_sources(),
                            source_cursors=dict(self._source_cursors),
                            start_index=self._source_cursors.get(ticket['choice'].avatar_path, self.next_index), frame_transport=TRANSPORT,
                            cancel_check=worker_cancelled)
                        self._stream_pool = begun['frame_pool']
                        self._chunk_pools = bool(begun.get('chunk_pools'))
                        self._stream_active = session_id
                        check_reply()
                        self.loaded = True
                        self.changes.notify()
                        print_speech_debug(f"[Ditto] Continuous reply pipeline started; prepared features retained; "
                              f"sampling steps={settings.get('steps')}; render batch={begun.get('renderer_batch', 1)}; " +
                              ('RAM storage follows audio chunk sizes and available system memory.'
                               if self._chunk_pools else f"RAM capacity={self._stream_pool['capacity']} frames."), flush=True)
                    descriptor = self._stream_pool
                    if getattr(self, '_chunk_pools', False):
                        waiting_memory = False
                        motion_flushed = False
                        while True:
                            reservation = client.request('stream_reserve', session_id=session_id,
                                chunk_id=ticket['stream_token'], frame_count=ticket['frame_count']+1,
                                cancel_check=worker_cancelled)
                            check_reply()
                            if not reservation.get('backpressure'):
                                descriptor = reservation['frame_pool']
                                if waiting_memory:
                                    holder['waiting_for_memory'] = False
                                    ticket['frame_changes'].notify()
                                    self.status = 'RAM available. Preparing the next Ditto speech chunk…'
                                    self.changes.notify()
                                break
                            if not waiting_memory:
                                waiting_memory = True
                                holder['waiting_for_memory'] = True
                                ticket['frame_changes'].notify()
                                self.status = 'Waiting for available system RAM for the next Ditto speech chunk…'
                                self.changes.notify()
                                print('[Ditto] Waiting for system RAM; speech remains buffered.', flush=True)
                            if ticket.get('progressive_window') and not motion_flushed:
                                # A partial motion batch may hold the only RAM
                                # pool; render it so playback can release that pool.
                                flushed = client.request('stream_flush', session_id=session_id,
                                                         cancel_check=worker_cancelled)
                                check_reply()
                                motion_flushed = bool(flushed.get('accepted'))
                            # Only active, cancellable memory-pressure waits retry;
                            # no system-memory checks run while the addon is idle.
                            time.sleep(.1)
                        ticket['complete_before_playback'] = not ticket.get('creator_preview')
                        print_speech_debug(f"[Ditto] Chunk {ticket['sequence_index']} RAM reserved: "
                              f"{descriptor['capacity']} frames, {descriptor['size']/1024**2:.1f} MiB.", flush=True)
                    with self._lock:
                        ticket['frame_buffer'] = FrameBuffer(descriptor, ticket['stream_token'], client.release_frame)
                        # Parent retirement can happen during begin/reserve, before
                        # it has a mapping to close. Close a late attachment here.
                        # This reservation must still render: late descriptors are
                        # released by _frame_ready so the worker frees its pool.
                        if ticket.get('progressive_window') and holder.get('playback_state') == 'completed':
                            holder['status'] = 'retired'
                            ticket['ready_event'].set()
                            self._close_buffer(ticket)
                            self._stream_cancel.pop((session_id, ticket['stream_token']), None)
                    ticket['frame_changes'].notify()
                    window = {}
                    if ticket.get('progressive_window') or ticket.get('trim_start_frames'):
                        window = dict(trim_start_frames=ticket['trim_start_frames'],
                                      valid_frame_count=ticket['valid_frame_count'])
                    if ticket.get('logical_frame_offset') is not None:
                        window.update(logical_frame_offset=ticket['logical_frame_offset'],
                                      logical_frame_count=ticket['logical_frame_count'])
                    while True:
                        result = client.request('stream_push', session_id=session_id,
                            chunk_id=ticket['stream_token'], audio_path=str(staged),
                            choice=ticket['choice'].to_wire(), **window,
                            minimum_buffer_frames=min(descriptor['capacity'],
                                self.required_buffer_frames(ticket, True)),
                            cancel_check=worker_cancelled)
                        check_reply()
                        if not result.get('backpressure'):
                            break
                        time.sleep(.05)
                    check_reply()
                    ticket['frame_count'] = int(result['frame_count'])
                    holder['expected_frame_count'] = ticket['frame_count']
                    ticket['start_index'] = result['start_index']
                    self.next_index = result['next_index']
                    holder.update(prepared_cache_reused=result.get('prepared_cache_reused', True))
                    self.loaded = True
                print_speech_debug(f"[Ditto] Fed NC chunk {ticket['sequence_index']} ({result['frame_count']} frames) "
                      'without waiting for earlier frames to finish.', flush=True)
            except Exception as error:
                holder.update(ok=False, error=str(error), status='failed', cancelled=bool(cancelled()))
                with self._lock:
                    self._close_buffer(ticket)
                if not cancelled():
                    self.status = f'Ditto render failed: {error}'
                    print(f'[Ditto] Render failed: {error}', flush=True)
                ticket['ready_event'].set()
                ticket['frame_changes'].notify()
                if not cancelled():
                    self.unload()
            finally:
                staged.unlink(missing_ok=True)
                self._queue.task_done()

    @notify_after
    def begin_reply(self):
        with self._lock:
            self._preview_audio_stop.set()
            self._test_preview_active = False
            self.idle()
            for ticket in self._stream_tickets.values():
                self._close_buffer(ticket)
                if not ticket['ready_event'].is_set():
                    ticket['result_holder'].update(ok=False, status='cancelled', error='Ditto reply superseded.')
                    ticket['ready_event'].set()
                    changes = ticket.get('frame_changes')
                    if changes is not None:
                        changes.notify()
            self._stream_id = uuid.uuid4().hex
            self._stream_retired = False
            self._stream_tickets = {}
            self._stream_cancel = {}
            self._pipeline = []
            self._render_spf = self._warm_render_spf or self._render_spf
            self._preview_images.clear()
            self._preview_url = ''
            self._creator_preview_url = ''

    def end_reply(self):
        self._stream_retired = True

    @notify_after
    def register_progressive_parent(self, ticket):
        """Expose one live logical speech row while child windows render."""
        holder = ticket['result_holder']
        with self._lock:
            if not any(item is holder for item in self._pipeline):
                self._pipeline.append(holder)

    def pipeline_snapshot(self):
        with self._lock:
            return {'active': self.session_running and any(c.get('playback_state') not in ('completed', 'failed') for c in self._pipeline),
                    'chunks': [dict(chunk) for chunk in self._pipeline]}

    def load_idle(self, avatar_path):
        if not avatar_path:
            with self._lock:
                self._idle_paths = []
                self.preview_path = ''
            return
        root = Path(avatar_path).expanduser().resolve()
        manifest = json.loads((root / 'avatar.json').read_text(encoding='utf-8'))
        unique = [(root / relative).resolve() for relative in manifest['frame_paths']]
        if any(not path.is_relative_to(root) or not path.is_file() for path in unique):
            raise ValueError('Invalid prepared avatar frame paths')
        order = manifest.get('source_order', list(range(len(unique))))
        if any(type(index) is not int or not 0 <= index < len(unique) for index in order):
            raise ValueError('Invalid avatar playback indices')
        if manifest.get('prepare_options', {}).get('loop_mode') == 'pingpong' and len(order) > 1:
            order = order + order[::-1]
        with self._lock:
            self._idle_paths = [str(unique[index]) for index in order]
            self._idle_started = time.monotonic()
            self._idle_offset = 0
            if self._idle_paths:
                self.preview_path = self._idle_paths[0]

    def snapshot(self, *, playback_only=False):
        with self._lock:
            now = time.monotonic()
            if self._active:
                result, started = self._active
                if started is None:
                    self._show_idle(now)
                    return self._snapshot_values(playback_only=playback_only)
                from core.continuous_audio import continuous_media_seconds
                media = continuous_media_seconds(self._clock_fields, now)
                if result.get('uses_device_clock') and media is None:
                    self._show_idle(now)
                    return self._snapshot_values(playback_only=playback_only)
                elapsed = media if media is not None else now-started
                self._record_source_progress(result, min(result['frame_count'], max(0, int(elapsed*25))))
                count = result.get('result_holder', {}).get('rendered_frame_count', result['frame_count'])
                target = max(0, min(result['frame_count']-1, int(elapsed*25)))
                if result.get('progressive_audio') and count > 0:
                    # The held DAC boundary can equal the next window's first
                    # frame. Keep the last rendered RGB frame until it arrives.
                    target = min(target, count-1)
                if result.get('frame_transport') == TRANSPORT:
                    if target >= count or not self._select_memory_frame(result, target):
                        holder = result.get('result_holder', {})
                        if not holder.get('visual_starved'):
                            print(f'[Ditto] Speech-frame underrun at frame {target}; showing idle until matching frames arrive.', flush=True)
                        holder['visual_starved'] = True
                        self._preview_url = ''
                        buffer = result.get('frame_buffer')
                        if buffer is not None:
                            buffer.retire_before(target)
                        self._show_idle(now, result.get('start_index', 0)+target)
                    else:
                        result['result_holder'].update(preview_frame_index=target, visual_starved=False)
                        if result.get('progressive_audio'):
                            played = min(count, max(0, int(elapsed*25)))
                            if played > target:
                                # RGB is already copied in the preview cache. Free
                                # its consumed pool even while holding that image.
                                result['frame_buffer'].retire_before(played)
                else:
                    index = max(0, min(count-1, target))
                    result.get('result_holder', {})['preview_frame_index'] = index
                    candidate = Path(result['frame_dir']) / f'{index:08d}.png'
                    if candidate.is_file():
                        self.preview_path = str(candidate)
            elif self._idle_paths:
                self._show_idle(now)
            return self._snapshot_values(playback_only=playback_only)

    def _show_idle(self, now, source_cursor=None):
        if self._idle_paths:
            cursor = self._idle_offset + int((now-self._idle_started)*25) if source_cursor is None else source_cursor
            self.preview_path = self._idle_paths[cursor % len(self._idle_paths)]

    @staticmethod
    def _close_buffer(ticket):
        buffer = ticket.get('frame_buffer')
        if buffer is not None:
            buffer.close()
        changes = ticket.get('frame_changes')
        if changes is not None:
            changes.notify()

    def _select_memory_frame(self, result, index):
        buffer = result.get('frame_buffer')
        if buffer is None:
            return False
        name = f'{buffer.session_id}/{buffer.chunk_id}/{index}'
        if name not in self._preview_images:
            pixels = buffer.read(index)
            if pixels is not None:
                self._preview_images[name] = (buffer.width, buffer.height, pixels)
                while len(self._preview_images) > 2:
                    self._preview_images.popitem(last=False)
        if name in self._preview_images:
            self._preview_url = 'image://ditto/' + name
            if self._test_preview_active:
                self._creator_preview_url = self._preview_url
        buffer.retire_before(index)
        return name in self._preview_images

    def preview_image(self, name):
        with self._lock:
            return self._preview_images.get(name)

    def _snapshot_values(self, *, playback_only=False):
        if playback_only:
            # The image/audio clock needs frame state, never control descriptors,
            # package catalogs, deletion checks or per-avatar tuning reads.
            values = (self._config.snapshot() or {}) if self._config else self._values
            return {'preview_path':self.preview_path,
                    'ditto_avatar_path':values.get('ditto_avatar_path',self._values['ditto_avatar_path'])}
        process = getattr(self._client, 'process', None)
        live = process is not None and process.poll() is None
        return {**self.settings(), 'status': self.status, 'loaded': self.loaded and live,
                    **self.package_state(),
                    'worker_running': live,
                    'session_running': self.session_running,
                    'test_preview_active': self._test_preview_active,
                    'crop_models_loaded': self._crop_models_loaded and live,
                    'preview_muted': self._preview_muted.is_set(),
                    'creator_preview_url': self._creator_preview_url,
                    'busy': self.busy, 'progress': self.progress,
                    'fps_choice': dict(self._fps_choice) if self._fps_choice else None,
                    'preview_path': self.preview_path, 'last_result': dict(self.last_result)}

    def _resource_use_labels(self):
        # Called under _lock. The operation lock is checked separately because
        # unload_resource itself reserves it before rechecking these users.
        users = []
        if self.busy:
            users.append('Ditto loading or avatar preparation')
        if self.session_running or self._test_preview_active:
            users.append('Ditto preview' if self._test_preview_active else 'Ditto avatar session')
        if self._active is not None or self._stream_active is not None or self._queue.unfinished_tasks:
            users.append('Ditto avatar rendering')
        return users

    def resource_users(self):
        with self._lock:
            users = self._resource_use_labels()
            if self._operation.locked() and not users:
                users.append('Ditto worker operation')
            return users

    def resources_snapshot(self):
        # Never call client(), snapshot(), or a worker RPC from inspection.
        with self._lock:
            process = getattr(self._client, 'process', None)
            if process is None or process.poll() is not None:
                return []
            return [{'id': f'{process.pid}:{id(process)}', 'name': 'Ditto',
                     'model': 'Avatar engine and prepared features' if self.loaded else 'Avatar worker',
                     'owner': 'NC · Ditto avatar and creator', 'device': 'Ditto worker',
                     'processId': process.pid, 'processLabel': 'Ditto worker',
                     'processIncludeChildren': True,
                     'users': self.resource_users(), 'canUnload': True}]

    @notify_after
    def unload_resource(self, instance_id):
        # A busy worker is refused immediately, rather than waiting for inference
        # and then unloading a resource the user may still be using.
        if not self._operation.acquire(blocking=False):
            return False
        try:
            with self._lock:
                client = self._client
                process = getattr(client, 'process', None)
                if (process is None or process.poll() is not None
                        or str(instance_id) != f'{process.pid}:{id(process)}'
                        or self._resource_use_labels()):
                    return False
                self.busy = self._resource_unloading = True
            try:
                # Do not detach the client or clear residency until exit is
                # confirmed. Failed cleanup stays visible and can be retried.
                # Pipe shutdown must run outside _lock: frame callbacks use it.
                client.close_strict()
                self.unload()
                return True
            finally:
                with self._lock:
                    self.busy = self._resource_unloading = False
        finally:
            self._operation.release()

    @notify_after
    def unload(self):
        with self._lock:
            self._preview_audio_stop.set()
            self._frame_ready({'event': 'stream_failed', 'message': 'Ditto unloaded.'})
            self._generation += 1
            self._stream_active = None
            self._stream_pool = None
            self._stream_tickets = {}
            self._stream_cancel = {}
            client = self._client
            self._client = None
            self.loaded = False
            self._crop_models_loaded = False
            self.session_running = False
            self._test_preview_active = False
            self._active = None
            self._warmed_key = None
            self._preview_images.clear()
            self._preview_url = ''
            self._creator_preview_url = ''
        if client:
            client.close()
        self.status = 'Models unloaded. Ditto GPU memory released.'
        return {'ok': True}

    def preview_state(self):
        """Read-only publication for NC's shared Avatar Preview window."""
        with self._lock:
            state = self.snapshot(playback_only=True)
            active = self._active is not None
            path = state['preview_path'] if self.session_running else ''
            active_result = self._active[0] if self._active else {}
            holder = active_result.get('result_holder', {})
            return {'frame_path': path, 'fps': 25, 'provider_id': 'ditto',
                    'creator_preview_active': bool(self._test_preview_active and self.session_running),
                    'image_url': self._preview_url if self.session_running and active else '',
                    'sequence_index': active_result.get('sequence_index'),
                    'preview_frame_index': holder.get('preview_frame_index', -1),
                    'expected_frame_count': active_result.get('frame_count', 0),
                    'avatar_id': 'ditto:' + (self._visible_choice.avatar_path if self._visible_choice else state['ditto_avatar_path']), 'loop': not active or not self._preview_url,
                    'status': ('buffering' if active and (holder.get('visual_starved') or self._active[1] is None)
                               else 'speaking' if active else ('idle' if state['preview_path'] else 'disconnected')),
                    'status_text': self.status}

    @notify_after
    def warm_up(self):
        """Prime the continuous stages and measure delivery before accepting speech."""
        generation = self._generation
        with self._operation:
            if generation != self._generation:
                raise RuntimeError('Ditto warmup cancelled.')
            cfg = self.settings()
            client = self.client()
            choice = self.bind_choice('neutral')
            settings = dict(choice.settings)
            variants = self.package_sources(cfg)
            process = getattr(client, 'process', None)
            key = (client, getattr(process, 'pid', None), choice.avatar_path, tuple(variants),
                   json.dumps(settings, sort_keys=True))
            if self._warmed_key == key:
                return True
            self.busy = True
            self.status = 'Warming Ditto inference before the first chat message…'
            self.changes.notify()
            try:
                cancelled = lambda: generation != self._generation
                if variants:
                    client.request('prewarm_variants', avatar_paths=variants, settings=settings, cancel_check=cancelled)
                warmup_root = self.app_root / 'runtime/ditto/warmup'
                warmup_root.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix='startup-', dir=warmup_root) as folder:
                    audio = Path(folder) / 'silence.wav'
                    with wave.open(str(audio), 'wb') as wav:
                        wav.setnchannels(1)
                        wav.setsampwidth(2)
                        wav.setframerate(16000)
                        wav.writeframes(b'\0\0' * (160*640))
                    print('[Ditto] Warming the prepared avatar before chat becomes ready…', flush=True)
                    session_id = 'warmup-'+uuid.uuid4().hex
                    ticket = {'warmup': True, 'chunk_id': 'warmup', 'ready_event': threading.Event(),
                              'result_holder': {'rendered_frame_count': 0}}
                    self._stream_tickets[(session_id, 'warmup')] = ticket
                    cancelled = lambda: generation != self._generation
                    try:
                        begun = client.request('stream_begin', session_id=session_id, avatar_path=choice.avatar_path,
                            settings=settings, variants=variants, start_index=0, frame_transport=TRANSPORT, cancel_check=cancelled)
                        ticket['frame_buffer'] = FrameBuffer(begun['frame_pool'], 'warmup', client.release_frame)
                        client.request('stream_push', session_id=session_id, chunk_id='warmup',
                            audio_path=str(audio), choice=choice.to_wire(), cancel_check=cancelled)
                        deadline = time.monotonic()+120
                        while not ticket['ready_event'].wait(.1):
                            if cancelled():
                                raise RuntimeError('Ditto warmup cancelled.')
                            if time.monotonic() >= deadline:
                                raise RuntimeError('Ditto continuous warmup timed out.')
                        if ticket['result_holder'].get('error'):
                            raise RuntimeError(ticket['result_holder']['error'])
                        result = client.request('stream_stop', session_id=session_id, cancel_check=cancelled)
                        if result.get('output_fps', 0) > 0:
                            self._render_spf = 1/result['output_fps']
                            self._warm_render_spf = self._render_spf
                        print('[Ditto] Startup warmup complete.', flush=True)
                        print_speech_debug(f"[Ditto] Startup warmup complete; continuous delivery {result.get('output_fps', 0):.2f} FPS. "
                              f"Render batch={result.get('renderer_batch', 1)}. Prepared features and models retained.", flush=True)
                    finally:
                        self._close_buffer(ticket)
                        self._stream_tickets.pop((session_id, 'warmup'), None)
                if generation != self._generation:
                    raise RuntimeError('Ditto warmup cancelled.')
                self._warmed_key = key
                self.loaded = True
                return True
            finally:
                self.busy = False

    @notify_after
    def _run(self, action, payload, generation=None, *, operation_held=False):
        if not operation_held and not self._operation.acquire(blocking=False):
            raise RuntimeError('Another Ditto operation is running.')
        self.busy = True
        self.changes.notify()
        try:
            if generation is None:
                generation = self._generation
            cancelled = lambda: generation != self._generation
            if cancelled():
                raise RuntimeError('Ditto operation cancelled.')
            cfg = self.settings()
            if action == 'load':
                result = self.client().request('load', cancel_check=cancelled)
                self.loaded = True
                if cfg['ditto_avatar_path']:
                    self.load_idle(cfg['ditto_avatar_path'])
                self.status = 'Models loaded and retained between replies.'
            elif action in ('prepare', 'prepare_convert', 'prepare_keep'):
                if not cfg['ditto_source_path']:
                    raise ValueError('Choose an image, video, or numeric PNG sequence folder.')
                options = prepare_settings(cfg)
                if action != 'prepare':
                    if not self._fps_choice or self._fps_choice['source_path'] != cfg['ditto_source_path']:
                        raise ValueError('Source changed. Click Prepare avatar to check its frame rate again.')
                    options['video_fps_policy'] = 'convert' if action == 'prepare_convert' else 'keep'
                self._fps_choice = None
                output = cfg['ditto_output_path'] or str(self.app_root / 'runtime/ditto/avatars' / uuid.uuid4().hex)
                result = self.client().request('prepare', source_path=cfg['ditto_source_path'],
                    output_dir=output, prepare_options=options, cancel_check=cancelled)
                if result.get('needs_fps_choice'):
                    message = fps_choice_message(result)
                    self._fps_choice = {**result, 'source_path': cfg['ditto_source_path'], 'message': message}
                    self.status = message
                    self.last_result = {}
                    return result
                self.loaded = True
                # Busy path update intentionally bypasses the user's path-edit guard.
                self._values['ditto_avatar_path'] = result['avatar_path']
                if self._config:
                    self._config.update('ditto_avatar_path', result['avatar_path'])
                self.load_idle(result['avatar_path'])
                self.next_index = 0
                self.status = f"Prepared {result['frame_count']} unique source frames."
            elif action == 'test_render':
                self.begin_reply()
                preview_stop = threading.Event()
                self._preview_audio_stop = preview_stop
                audio = cfg['ditto_test_audio'] or str(Path(__file__).parents[1] / 'ditto_preprocess/assets/preview.wav')
                if not Path(audio).is_file():
                    raise ValueError('Choose a WAV file for the speaking preview in Advanced settings.')
                ticket = self.submit_audio(audio, '', 'test-preview', 0, lambda: False,
                                           choice=payload.get('choice') or self.bind_choice(cfg['ditto_test_emotion']),
                                           creator_preview=True, package_id=payload.get('package_id'))
                self.session_running = True
                self._test_preview_active = True
                threading.Thread(target=self._play_preview_ticket,
                    args=(ticket, generation, self._stream_id, audio, preview_stop),
                    name='ditto-speaking-preview', daemon=True).start()
                result = {'started': True, 'frame_count': ticket['frame_count'], 'fps': 25}
                self.status = 'Rendering to RAM; preview audio starts after its initial frame buffer is ready.'
            else:
                raise KeyError(action)
            self.last_result = result
            return result
        except Exception as exc:
            # Cancellation already retired this generation and closed its worker.
            # Do not unload twice or overwrite the cancellation status with failure.
            if generation == self._generation:
                self.status = str(exc)
                self.unload()
                self.status = f'Ditto failed: {exc}'
            raise
        finally:
            self.busy = False
            self._operation.release()

    @notify_after
    def delete_package(self, payload):
        from .packages import DittoPackageStore, _MANIFEST_LOCK
        from addons.musetalk_avatar.package_files import package_deletion_info, delete_package_files
        data = dict(payload or {})
        if data.get('confirmed') is not True:
            raise ValueError('Confirm permanent package deletion first.')
        if not self._operation.acquire(blocking=False):
            raise RuntimeError('Wait for the current Ditto operation to finish.')
        previous = {}
        changed = []
        try:
            with self._lock:
                process = getattr(self._client, 'process', None)
                if self._resource_use_labels() or self._resource_unloading or (process is not None and process.poll() is None):
                    raise RuntimeError('Stop chat or preview and unload Ditto before deleting a package.')
                cfg = self._base_settings()
                pack_id = data.get('pack_id')
                if not pack_id or cfg['ditto_pack_id'] != pack_id:
                    raise ValueError('Selected package changed. Review deletion again.')
                store = DittoPackageStore(self.app_root)
                manifest = store.package_root(pack_id) / 'manifest.json'
                info = package_deletion_info(store.root, manifest, pack_id, 'ditto')
                if not data.get('token') or data['token'] != info['token']:
                    raise ValueError('Package changed since confirmation. Review deletion again.')
                self.busy = self._deleting_package = True
                updates = {'ditto_pack_id':'', 'ditto_variant_id':'', 'ditto_avatar_path':'',
                    'ditto_enabled_pack_emotions':{key:value for key,value in cfg['ditto_enabled_pack_emotions'].items() if key != pack_id}}
                previous = {key:cfg[key] for key in updates}
                try:
                    for key, value in updates.items():
                        if self._config:
                            result = self._config.update(key, value)
                            if result is False or getattr(result, 'accepted', True) is False:
                                failure = getattr(result, 'failure', None)
                                raise RuntimeError(str(getattr(failure, 'message', 'Could not clear package selection.')))
                        self._values[key] = value
                        changed.append(key)
                    # Creator and runtime manifest writes share this lock.
                    with _MANIFEST_LOCK:
                        delete_package_files(store.root, manifest, pack_id, 'ditto', data['token'])
                except Exception:
                    for key in reversed(changed):
                        self._values[key] = previous[key]
                        if self._config:
                            self._config.update(key, previous[key])
                    raise
                self.load_idle('')
                self._visible_choice = None
                self._active_avatar_id = self._last_queued_avatar_id = None
                self._source_cursors.clear()
                self._preview_images.clear()
                self._preview_url = self._creator_preview_url = ''
                self.last_result = {}
                self._tuning_cache.pop(pack_id, None)
                self._package_state_cache = None
                if self._creator is not None:
                    self._creator._catalog_cache = (0, [])
                    if self._creator.pack is not None and self._creator.pack.pack_id == pack_id:
                        self._creator.pack = None
                        self._creator.selected_variant = ''
                        self._creator._wizard_source = self._creator._wizard_emotion = ''
                        self._creator._wizard_draft = False
                        self._creator._crop_preview = None
                        self._creator._fields.update(ditto_package_name='',ditto_variant_name='',ditto_variant_tags='',ditto_variant_default=False)
                self.status = f'Package {info["display_name"]} permanently deleted.'
            return {'ok':True}
        finally:
            with self._lock:
                if self._deleting_package:
                    self.busy = self._deleting_package = False
            self._operation.release()

    @notify_after
    def action(self, action, payload=None):
        if action == 'delete_package':
            return self.delete_package(payload)
        if action == 'set_preview_muted':
            muted = (payload or {}).get('muted')
            if type(muted) is not bool:
                raise ValueError('Preview mute must be true or false.')
            self._preview_muted.set() if muted else self._preview_muted.clear()
            return {'ok':True}
        if action == 'stop_preview':
            with self._lock:
                if self.session_running and not self._test_preview_active:
                    raise RuntimeError('Stop preview cannot interrupt an active chat.')
                self.begin_reply()
                self.session_running = self._test_preview_active = False
                self.status = 'Preview stopped. Ditto models remain loaded for another test.'
            return {'ok':True}
        if action == 'prepare_cancel':
            self._fps_choice = None
            self.status = 'Preparation cancelled. Choose another source or click Prepare avatar to try again.'
            return {'ok': True}
        if action in ('unload', 'cancel'):
            return self.unload()
        if action == 'activate':
            if self._config is None:
                raise RuntimeError('Host runtime configuration unavailable')
            self._config.update('avatar_mode', 'ditto')
            self.status = 'Ditto selected. Start chat to use the provider.'
            return {'ok': True}
        if action not in ('load', 'prepare', 'prepare_convert', 'prepare_keep', 'test_render'):
            raise KeyError(action)
        with self._lock:
            if self.busy:
                raise RuntimeError('Another Ditto operation is running.')
            # Stream cleanup also owns this lock, without setting busy. Reserve it
            # before publishing a new job so a rejected start cannot latch busy.
            if not self._operation.acquire(blocking=False):
                self.status = 'Previous Ditto work is still finishing. Try again shortly, or cancel and unload.'
                return {'ok': False, 'error': self.status}
            self.busy = True
            generation = self._generation
            self.status = f'{action.replace("_", " ").capitalize()}…'
        def job():
            try:
                self._run(action, payload or {}, generation, operation_held=True)
            except Exception:
                pass  # The action's error is retained in the native status surface.
        try:
            threading.Thread(target=job, name='ditto-addon-job', daemon=True).start()
        except Exception as exc:
            with self._lock:
                self.busy = False
                self.status = f'Could not start Ditto operation: {exc}'
            self._operation.release()
            raise
        return {'ok': True, 'started': True}

    def render_audio(self, audio_path, emotion='neutral', cancel_check=None, own_operation=True,
                     ticket=None, settings_override=None, choice=None):
        # Legacy local callers also use the asynchronous RAM ticket; explicit
        # offline exports use the worker's render RPC directly.
        return self.submit_audio(audio_path, '', uuid.uuid4().hex, 0, cancel_check or (lambda: False),
                                 choice=choice or self.bind_choice(emotion))

    def _play_preview_ticket(self, ticket, generation, session_id, audio_path, stop_event):
        from .preview_audio import PreviewAudioPlayer
        audio = None
        try:
            while not ticket['ready_event'].wait(.02):
                if stop_event.is_set() or generation != self._generation or session_id != self._stream_id:
                    return
                buffer = ticket.get('frame_buffer')
                if buffer and buffer.available_count >= self.required_buffer_frames(ticket, True):
                    break
            with self._lock:
                if stop_event.is_set() or generation != self._generation or session_id != self._stream_id:
                    return
                if ticket['result_holder'].get('error'):
                    raise RuntimeError(ticket['result_holder']['error'])
                ticket['uses_device_clock'] = True
                self.play(ticket, None)
                self.status = 'Playing speaking preview with audio (25 FPS).'
            self.changes.notify()
            config = dict(self._config.snapshot() or {}) if self._config else {}
            device = str(config.get('audio_output_device') or 'Default Output').strip()
            audio = PreviewAudioPlayer(audio_path, stop_event=stop_event, muted_event=self._preview_muted,
                                       output_device=None if device.casefold() == 'default output' else device)
            audio.start()
            while not stop_event.is_set():
                audio.poll()
                if audio.error:
                    raise RuntimeError(audio.error)
                sample = audio.clock_sample()
                with self._lock:
                    if (generation != self._generation or session_id != self._stream_id
                            or self._active is None or self._active[0] is not ticket):
                        return
                    if ticket['result_holder'].get('error'):
                        raise RuntimeError(ticket['result_holder']['error'])
                    self.update_audio_clock(sample)
                    self.snapshot(playback_only=True)
                    if audio.drained:
                        ticket['result_holder']['playback_state'] = 'completed'
                        self.status = 'Speaking preview complete. Preview again or use this avatar in chat.'
                        return
                time.sleep(.02)
        except Exception as error:
            with self._lock:
                if generation == self._generation and session_id == self._stream_id:
                    self.status = f'Speaking preview failed: {error}'
        finally:
            if audio is not None:
                audio.close()
            with self._lock:
                if generation == self._generation and session_id == self._stream_id:
                    self.idle()
                    self.end_reply()
                    self.session_running = False
                    self._test_preview_active = False
            self.changes.notify()

    def play(self, result, started):
        with self._lock:
            if self._active and self._active[0] is not result:
                self._active[0].get('result_holder', {})['playback_state'] = 'completed'
                self._close_buffer(self._active[0])
                self._preview_url = ''
            self._active = (result, started)
            if started is not None:
                self._show_choice(result.get('choice'))
            self._clock_fields = {}
            holder = result.get('result_holder', {})
            holder.update(playback_state='playing' if started is not None else 'buffered', audio_started_at=time.time(),
                          audio_start_pending=started is None, visual_starved=False)

    def update_audio_clock(self, sample):
        with self._lock:
            if not self._active:
                return
            if sample.sampled_monotonic < self._clock_fields.get('audio_clock_monotonic', 0):
                return
            self._clock_fields = dict(audio_media_seconds=sample.media_seconds,
                audio_clock_monotonic=sample.sampled_monotonic,
                audio_scheduled_through_seconds=sample.scheduled_through_seconds,
                audio_clock_running=sample.running)
            result, started = self._active
            if started is None:
                self._active = (result, sample.sampled_monotonic)
                self._show_choice(result.get('choice'))
            result.get('result_holder', {})['playback_state'] = 'playing'
            result.get('result_holder', {}).update(self._clock_fields, audio_start_pending=False,
                                                   frame_transport=result.get('frame_transport'))
            # Retirement follows device progress even when the preview is hidden.
            self.snapshot(playback_only=True)

    def hold_audio_clock(self):
        """Hold a progressive parent at its current device position on pause."""
        with self._lock:
            if not self._active or not self._active[0].get('progressive_audio'):
                return
            from core.continuous_audio import continuous_media_seconds
            now = time.monotonic()
            media = continuous_media_seconds(self._clock_fields, now)
            if media is None:
                return
            self._clock_fields.update(audio_media_seconds=media,
                                      audio_clock_monotonic=now, audio_clock_running=False)
            self._active[0].get('result_holder', {}).update(self._clock_fields)
            self.snapshot(playback_only=True)

    def idle(self, retire=True):
        with self._lock:
            if self._active and self._active[1] is not None and self._idle_paths:
                result, started = self._active
                from core.continuous_audio import continuous_media_seconds
                media = continuous_media_seconds(self._clock_fields, time.monotonic())
                shown = min(result['frame_count'], max(0, int((media if media is not None else time.monotonic()-started)*25)))
                self._record_source_progress(result, shown)
                self._idle_offset = (result.get('start_index', 0) + shown) % len(self._idle_paths)
            if self._active and retire:
                self._close_buffer(self._active[0])
            self._active = None
            self._preview_url = ''
            self._clock_fields = {}
            self._idle_started = time.monotonic()


_service = None
def get_service(context=None):
    global _service
    if _service is None:
        if context is None:
            raise RuntimeError('Ditto addon is not initialized.')
        _service = DittoService(context)
    return _service
