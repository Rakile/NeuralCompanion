"""One reply's bounded motion/render pipeline; NC still supplies every audio chunk."""
import queue
import threading
import time
import types
from pathlib import Path

import numpy as np


_MOTION_FLUSH = object()


def validate_frame_geometry(paths, expected):
    from PIL import Image
    for path in paths:
        with Image.open(path) as image:
            if image.size != expected:
                raise ValueError('Prepared live source frames must have the same dimensions.')


class MotionWindows:
    """Retain Ditto's overlap across inputs and emit real frames as windows finish."""
    def __init__(self, model, condition, publish, cancelled=lambda: False):
        self.model, self.condition, self.publish = model, condition, publish
        self.cancelled = cancelled
        self.features = None
        self.history = None
        self.cursor = 0
        self.position = 0

    def append(self, features):
        self.features = features if self.features is None else np.concatenate([self.features, features])
        self._drain(False)

    def flush(self):
        self._drain(True)

    def _drain(self, partial):
        while self.features is not None and len(self.features) and not self.cancelled():
            size = self.model.seq_frames
            if len(self.features) < size and not partial:
                break
            real = min(len(self.features), self.model.valid_clip_len)
            features = self.features[:size]
            if len(features) < size:
                features = np.concatenate([features, np.repeat(features[-1:], size-len(features), axis=0)])
            prediction = self.model(self.condition(features, self.position)[None], self.history)
            if self.cancelled():
                return
            self.publish(prediction[:, self.cursor:self.cursor+real], self.position)
            self.cursor += real
            # Discard padded predictions but retain the next overlap. Subsequent
            # windows fuse at the real cursor, even after a short starved input.
            self.history = prediction[:, :self.cursor+self.model.overlap_v2].copy()
            self.model._update_kp_cond(self.history, self.cursor)
            if self.history.shape[1] > size*2:
                cut = self.history.shape[1] - size*2
                self.history = self.history[:, cut:]
                self.cursor -= cut
            self.features = self.features[real:]
            self.position += real


class TimelineMotionWindows:
    """Keep overlap across WAVs; reset only at a source/setup epoch boundary."""
    def __init__(self, model, timeline, publish, cancelled=lambda: False):
        self.model, self.timeline, self.publish, self.cancelled = model, timeline, publish, cancelled
        self.windows, self.epoch = None, None

    @property
    def features(self):
        return self.windows.features if self.windows is not None else None

    def append(self, features, position):
        epoch = self.timeline.epochs[self.timeline.ref(position).epoch]
        if self.epoch is None or self.epoch.number != epoch.number:
            self.flush()
            if self.cancelled():
                return
            if not epoch.initial_state:
                epoch.setup_motion(self.model)
            self.epoch = epoch
            condition = lambda audio, index: self.timeline.condition(audio,index,epoch_end=epoch.end)
            self.windows = MotionWindows(self.model,condition,self.publish,self.cancelled)
            self.windows.position = position
        self.windows.append(features)

    def flush(self):
        if self.windows is not None:
            self.windows.flush()


class MappedImages:
    def __init__(self, images, indices):
        self.images, self.indices = images, indices
    def __len__(self):
        return len(self.indices)
    def __getitem__(self, index):
        return self.images[self.indices[index]]


class ReplyPipeline:
    def __init__(self, worker, session_id, root, manifest, paths, settings, start_index,
                 frame_transport=None, pixel_budget=None, source_cursors=None):
        from gui_controls import make_kwargs, parse_seed
        from core.atomic_components.avatar_registrar import smooth_x_s_info_lst
        self.worker, self.sdk = worker, worker.sdk
        self.session_id, self.root = session_id, root
        self.manifest, self.paths = manifest, paths
        self.segments = []
        self.lock = threading.RLock()
        self.accepted = self.written = 0
        self.started = time.perf_counter()
        self.first_written = None
        self.last_written = None
        self.png_seconds = 0.
        self.motion_seconds = 0.
        self.feature_seconds = 0.
        self.starved_flushes = 0
        self.stage_seconds = {}
        self.stage_originals = {}
        kwargs = make_kwargs({'conditioning': 'Source face', **settings}, is_video=not manifest['is_image'])
        setup = kwargs['setup_kwargs']
        for key in ('delta_eye_arr', 'v_min_max_for_clip'):
            if isinstance(setup.get(key), list):
                setup[key] = np.asarray(setup[key], dtype=np.float32)
        seed = parse_seed(settings.get('seed', ''))
        if seed is not None:
            from inference import seed_everything
            seed_everything(seed)
        unique, self.cache_reused = worker.cached_source(root, paths)
        self.pool = None
        self.mask_compositor = None
        self.mask_prepare_seconds = 0.
        if frame_transport is not None:
            from frame_memory import FramePool, ChunkFramePools, TRANSPORT
            if frame_transport != TRANSPORT:
                raise ValueError('Unsupported live frame transport.')
            height, width = unique['img_rgb_lst'][0].shape[:2]
            if unique.get('memory_geometry') != (width, height):
                validate_frame_geometry(paths, (width, height))
                unique['memory_geometry'] = (width, height)
            prepare_masks = getattr(self.sdk.putback, 'prepare', None)
            if prepare_masks is not None:
                self.mask_compositor = self.sdk.putback
                self.mask_prepare_seconds = prepare_masks(str(root), unique['M_c2o_lst'], width, height)
                self.mask_stats_start = self.mask_compositor.summary()
            self.pool = (ChunkFramePools(width, height, session_id) if pixel_budget is None
                         else FramePool(width, height, session_id, pixel_budget))
        order = manifest['source_order']
        if manifest['prepare_options']['loop_mode'] == 'pingpong' and len(order) > 1:
            order = order + order[::-1]
        self.start_index = start_index
        self.order = order
        indices = [order[(start_index+i) % len(order)] for i in range(len(order))]
        motion = unique['x_s_info_lst']
        smoothing = setup.pop('smo_k_s', 13)
        if len(motion) > 1 and smoothing > 1:
            motion = smooth_x_s_info_lst(motion, smo_k=smoothing)
        ordered = {key: [value[i] for i in indices] for key, value in unique.items()
                   if key.endswith('_lst') and key != 'img_rgb_lst'}
        ordered.update(x_s_info_lst=[motion[i] for i in indices], sc=unique['sc'],
                       is_image_flag=unique['is_image_flag'], img_rgb_lst=MappedImages(unique['img_rgb_lst'], indices))
        self.sdk.avatar_registrar = lambda *a, **kw: ordered
        self.original_motion_worker = self.sdk._audio2motion_offline
        self.sdk._audio2motion_offline = self.motion_worker
        self.original_stitch_worker = self.sdk._motion_stitch_worker
        self.sdk._motion_stitch_worker = self.stitch_worker
        self.renderer = None
        if self.pool is not None:
            from render_batches import FrameBatchRenderer
            self.renderer = FrameBatchRenderer(self.sdk)
            self.renderer.install()
        # This source list already includes the requested forward/pingpong map.
        # Use modulo for eye conditioning, too, without patching SDK globals.
        handler = self.sdk.condition_handler
        self.original_handler_class = type(handler)
        call = self.original_handler_class.__call__
        call_globals = {**call.__globals__, '_mirror_index': lambda i, n: i % n}
        wrapped_call = types.FunctionType(call.__code__, call_globals, call.__name__, call.__defaults__, call.__closure__)
        handler.__class__ = type('PreparedLoopCondition', (self.original_handler_class,), {'__call__': wrapped_call})
        worker.active_render = {'stream': self}
        setup['online_mode'] = False
        from frame_timeline import ConditionTimeline, FrameSourceSequence
        self.timeline = ConditionTimeline(worker.sources, sdk=self.sdk, start_index=start_index,
            initial_source_key=str(root), initial_source_info=ordered, settings=settings,
            source_cursors=source_cursors)
        # setup() starts upstream queue threads immediately. Publish the empty
        # timeline before those threads can enter our motion worker.
        self.sdk.setup(str(root), str(root / 'unused-stream'), smo_k_s=1, **setup)
        if self.renderer is not None:
            self.renderer.configure_queues()
        self.sdk.setup_Nd(-1, ctrl_info=kwargs['run_kwargs'].get('ctrl_info', {}))
        self.default_settings = settings
        self.sdk.source_info = {name:(FrameSourceSequence(worker.sources,self.timeline,name,value)
                                if name.endswith('_lst') else value) for name,value in ordered.items()}
        for name in ('warp_f3d', 'decode_f3d', 'putback'):
            original = getattr(self.sdk, name)
            self.stage_originals[name] = original
            def measured(*args, _name=name, _original=original, **kw):
                before = time.perf_counter()
                result = _original(*args, **kw)
                self.stage_seconds[_name] = self.stage_seconds.get(_name, 0.) + time.perf_counter()-before
                return result
            setattr(self.sdk, name, measured)
        def watch_failure():
            self.sdk.stop_event.wait()
            if self.sdk.worker_exception is not None:
                worker.emit('stream_failed', session_id=session_id, message=str(self.sdk.worker_exception))
        threading.Thread(target=watch_failure, name='ditto-stream-health', daemon=True).start()

    def push(self, chunk_id, audio_path, output_dir=None, frame_dir=None, minimum_buffer_frames=0, choice=None,
             trim_start_frames=0, valid_frame_count=None, logical_frame_offset=None, logical_frame_count=None):
        # The command loop must stay free to process frame releases and Stop.
        # It is the only input producer, so a queue with space cannot fill while
        # this call prepares features; the motion thread can only drain it.
        if self.sdk.audio2motion_queue.full():
            return {'accepted': False, 'backpressure': True}
        import librosa
        import math
        before = time.perf_counter()
        audio, _ = librosa.load(str(audio_path), sr=16000)
        context_count = math.ceil(len(audio)/640)
        if not context_count:
            raise ValueError('Audio is empty.')
        if type(trim_start_frames) is not int or trim_start_frames < 0:
            raise ValueError('Context frame offset must be a nonnegative integer.')
        count = context_count-trim_start_frames if valid_frame_count is None else valid_frame_count
        if type(count) is not int or count <= 0 or trim_start_frames+count > context_count:
            raise ValueError('Valid frames must be a positive integer range inside the context audio.')
        if logical_frame_offset is not None and (type(logical_frame_offset) is not int or logical_frame_offset < 0):
            raise ValueError('Logical fade offset must be a nonnegative integer.')
        if logical_frame_count is not None and (logical_frame_offset is None or type(logical_frame_count) is not int
                or logical_frame_count < logical_frame_offset+count):
            raise ValueError('Logical fade frame count must contain this window.')
        folder = None
        if self.pool is not None:
            required = min(count, max(1, int(minimum_buffer_frames)))
            chunk_pool = self.pool.pools.get(chunk_id) if hasattr(self.pool, 'pools') else None
            capacity = chunk_pool.capacity if chunk_pool is not None else self.pool.capacity
            if count > capacity and chunk_pool is not None:
                raise ValueError('Audio exceeds its chunk RAM reservation.')
            if required > capacity:
                raise ValueError(f'Ditto needs {required} initial frames but the RAM buffer holds '
                                 f'{self.pool.capacity}; shorten the speech chunk or enlarge the buffer.')
        else:
            output, folder = Path(output_dir).resolve(), Path(frame_dir).resolve()
            if not folder.is_relative_to(output):
                raise ValueError('Frame directory must be inside the render output directory.')
            folder.mkdir(parents=True)
        features = self.sdk.wav2feat.wav2feat(audio)
        if len(features) < context_count:
            features = np.concatenate([features, np.repeat(features[-1:], context_count-len(features), axis=0)])
        # HuBERT sees the complete context WAV. Only speech features enter the
        # continuous motion history, timeline and source-frame cursor.
        features = features[trim_start_frames:trim_start_frames+count]
        self.feature_seconds += time.perf_counter()-before
        from emotions import ChunkChoice
        if choice is None:
            choice = ChunkChoice('__standalone__',str(self.root),self.default_settings.get('emotion','Neutral'),
                                 tuple(sorted(self.default_settings.items())))
        else:
            choice = ChunkChoice.from_wire(choice)
        source_key = self.worker.sources.register(choice.avatar_path)
        if self.pool is not None and self.worker.sources.get(source_key)['memory_geometry'] != (self.pool.width,self.pool.height):
            raise ValueError('All package avatars must use the same output canvas.')
        with self.lock:
            segment = dict(chunk_id=chunk_id, frame_dir=folder, count=count, start=self.accepted,
                           queued=time.perf_counter(), first_written=None, png_seconds=0.)
            self.segments.append(segment)
            if logical_frame_offset is None and logical_frame_count is None:
                self.timeline.append(self.accepted,count,choice)
            else:
                self.timeline.append(self.accepted,count,choice,fade_offset=logical_frame_offset,
                                     fade_frame_count=logical_frame_count)
            self.accepted += count
        first_ref = self.timeline.ref(segment['start'])
        source_epoch = self.timeline.epochs[first_ref.epoch]
        source_start = self.timeline._span(segment['start'])['source_start']
        item = (features,segment['start'])
        if logical_frame_offset is not None:
            more_expected = logical_frame_count is None or logical_frame_offset+count < logical_frame_count
            item += (more_expected,)
        self.sdk.audio2motion_queue.put_nowait(item)
        return {'accepted': True, 'session_id': self.session_id, 'frame_count': count,
                'start_index': source_start % len(source_epoch.order),
                'next_index': (source_start+count) % len(source_epoch.order),
                'variant_id': choice.variant_id,
                'prepared_cache_reused': self.cache_reused}

    def request_motion_flush(self):
        """Queue a pressure-relief flush without blocking frame release/Stop."""
        try:
            self.sdk.audio2motion_queue.put_nowait(_MOTION_FLUSH)
        except queue.Full:
            return {'accepted': False, 'backpressure': True}
        return {'accepted': True}

    def stitch_worker(self):
        from render_batches import put_unless_stopped
        sdk = self.sdk
        while not sdk.stop_event.is_set():
            try:
                item = sdk.motion_stitch_queue.get(timeout=.05)
            except queue.Empty:
                continue
            if item is None:
                put_unless_stopped(sdk.warp_f3d_queue,None,sdk.stop_event)
                return
            ref, driving, control = item
            epoch = self.timeline.epochs[ref.epoch]
            control = self.timeline.frame_controls(ref.frame, control)
            source, target = epoch.stitch(epoch.motion[ref.source_index],driving,**control)
            if not put_unless_stopped(sdk.warp_f3d_queue,(ref,source,target),sdk.stop_event):
                return

    def motion_worker(self):
        sdk = self.sdk
        def publish(motion, position):
            for index, info in enumerate(sdk.audio2motion.cvt_fmt(motion)):
                frame = position+index
                while not sdk.stop_event.is_set():
                    try:
                        sdk.motion_stitch_queue.put([self.timeline.ref(frame), info,
                                                    sdk._get_ctrl_info(frame)], timeout=.1)
                        break
                    except queue.Full:
                        pass
        windows = TimelineMotionWindows(sdk.audio2motion, self.timeline, publish, sdk.stop_event.is_set)
        more_input_expected = False
        try:
            while not sdk.stop_event.is_set():
                try:
                    item = sdk.audio2motion_queue.get(timeout=.2)
                except queue.Empty:
                    # Progressive input gaps are not speech boundaries. Keep
                    # accumulating normal model windows while more is expected;
                    # known final tails and legacy inputs retain starvation flush.
                    if not more_input_expected and windows.features is not None and len(windows.features):
                        self.starved_flushes += 1
                        before = time.perf_counter()
                        windows.flush()
                        self.motion_seconds += time.perf_counter()-before
                    continue
                before = time.perf_counter()
                if item is None:
                    windows.flush()
                    sdk.motion_stitch_queue.put(None)
                    break
                if item is _MOTION_FLUSH:
                    # A RAM-pressure request drains pending real frames while
                    # keeping motion history and the expectation of later input.
                    windows.flush()
                else:
                    more_input_expected = item[2] if len(item) > 2 else False
                    windows.append(item[0], item[1])
                self.motion_seconds += time.perf_counter()-before
        except Exception as error:
            sdk.worker_exception = error
            sdk.stop_event.set()
            self.worker.emit('stream_failed', session_id=self.session_id, message=str(error))

    def write(self, frame):
        with self.lock:
            segment = next(item for item in self.segments if item['start'] <= self.written < item['start']+item['count'])
            index = self.written-segment['start']
        before = time.perf_counter()
        if self.pool is not None:
            if frame.shape != (self.pool.height, self.pool.width, 3) or frame.dtype != np.uint8:
                raise ValueError('Generated RGB frame does not match the shared-memory pool.')
            try:
                data = self.pool.publish(frame.tobytes(), segment['chunk_id'], index)
            except RuntimeError:
                if self.sdk.stop_event.is_set():
                    return
                raise
        else:
            from PIL import Image
            path = segment['frame_dir'] / f'{index:08d}.png'
            temporary = path.with_suffix('.pending.png')
            Image.fromarray(frame).save(temporary, compress_level=1)
            temporary.replace(path)
            data = dict(path=str(path))
        now = time.perf_counter()
        if self.pool is None:
            segment['png_seconds'] += now-before
            self.png_seconds += now-before
        if segment['first_written'] is None:
            segment['first_written'] = now
            segment['first_pool_wait'] = self.pool.wait_seconds if self.pool is not None else 0.
        if self.first_written is None:
            self.first_written = now
            self.first_pool_wait = self.pool.wait_seconds if self.pool is not None else 0.
        self.last_pool_wait = self.pool.wait_seconds if self.pool is not None else 0.
        self.last_written = now
        self.written += 1
        data.update(session_id=self.session_id, chunk_id=segment['chunk_id'], index=index,
                    source_index=self.order[(self.start_index+self.written-1) % len(self.order)])
        if getattr(self,'timeline',None) is not None:
            ref = self.timeline.ref(self.written-1)
            data.update(source_index=ref.source_index,variant_id=self.timeline._span(ref.frame)['choice'].variant_id)
            self.timeline.retire_before(self.written)
        if self.pool is not None:
            data['buffer_wait_seconds'] = self.pool.wait_seconds
        if index+1 == segment['count']:
            from frame_memory import delivery_timing
            data['completed'] = True
            data['timing'] = {'queued_to_complete_seconds': now-segment['queued'],
                              'frame_output_seconds': now-segment['first_written'],
                              'png_write_seconds': segment['png_seconds'],
                              **delivery_timing(segment['count'], now-segment['first_written'],
                                                self.last_pool_wait-segment['first_pool_wait'])}
        self.worker.emit('stream_frame', **data)
        if data.get('completed') and hasattr(self.pool, 'mark_complete'):
            self.pool.mark_complete(segment['chunk_id'])

    def stop(self):
        sdk = self.sdk
        sdk.stop_event.set()
        if self.pool is not None:
            self.pool.stop()
        deadline = time.perf_counter()+5
        while any(t.is_alive() for t in sdk.thread_list) and time.perf_counter() < deadline:
            # Unblock a producer already inside a bounded queue.put during cancel.
            for name in ('audio2motion', 'motion_stitch', 'warp_f3d', 'decode_f3d', 'putback', 'writer'):
                q = getattr(sdk, name+'_queue')
                try:
                    q.get_nowait()
                except queue.Empty:
                    pass
            for thread in sdk.thread_list:
                thread.join(.02)
        if any(t.is_alive() for t in sdk.thread_list):
            raise RuntimeError('Ditto pipeline did not retire safely; worker must be unloaded.')
        sdk.writer.close()
        sdk.writer_pbar.close()
        sdk._audio2motion_offline = self.original_motion_worker
        sdk._motion_stitch_worker = self.original_stitch_worker
        for name, original in self.stage_originals.items():
            setattr(sdk, name, original)
        if self.renderer is not None:
            self.renderer.restore()
        sdk.condition_handler.__class__ = self.original_handler_class
        self.worker.active_render = None
        memory_timing = {}
        if self.pool is not None:
            memory_timing = dict(pixel_copy_seconds=self.pool.copy_seconds,
                                 buffer_wait_seconds=self.pool.wait_seconds,
                                 buffer_high_water=self.pool.high_water,
                                 buffer_capacity=self.pool.capacity)
            self.pool.close()
        span = (self.last_written-self.first_written) if self.first_written is not None else 0.
        from frame_memory import delivery_timing
        waits = getattr(self, 'last_pool_wait', 0.)-getattr(self, 'first_pool_wait', 0.)
        masks = {}
        if self.mask_compositor is not None:
            stats = self.mask_compositor.summary()
            stats.update(session_hits=stats['hits']-self.mask_stats_start['hits'],
                         session_misses=stats['misses']-self.mask_stats_start['misses'])
            masks = dict(mask_prepare_seconds=self.mask_prepare_seconds, mask_cache=stats)
        return dict(session_id=self.session_id, accepted_frames=self.accepted, written_frames=self.written,
                    **delivery_timing(self.written, span, waits),
                    **(self.renderer.summary() if self.renderer is not None else {'renderer_batch': 1}),
                    feature_seconds=self.feature_seconds, motion_seconds=self.motion_seconds,
                    png_seconds=self.png_seconds, stage_seconds=self.stage_seconds,
                    starved_flushes=self.starved_flushes, **memory_timing, **masks)
