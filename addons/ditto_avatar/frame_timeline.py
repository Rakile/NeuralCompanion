"""Frame identity and conditioning across queued NC speech chunks."""
from bisect import bisect_right
from copy import copy
from dataclasses import dataclass
import inspect
import threading
import types

import numpy as np

try:
    from .emotions import NATIVE_EMOTIONS
except ImportError:
    from emotions import NATIVE_EMOTIONS


@dataclass(frozen=True)
class FrameRef:
    frame: int
    source_key: str
    source_index: int
    epoch: int


@dataclass
class SourceEpoch:
    number: int
    start: int
    end: int
    key: tuple
    source_key: str
    order: list
    motion: list
    source_info: dict
    setup: dict
    condition_handler: object
    stitch: object
    initial_state: bool = False
    seed: int | None = None

    def setup_motion(self, model):
        if self.seed is not None:
            # Run on motion admission, never reseed an earlier active window
            # from the command thread while a later chunk is queued.
            from inference import seed_everything
            seed_everything(self.seed)
        keys = ('overlap_v2','fix_kp_cond','fix_kp_cond_dim','sampling_timesteps',
                'online_mode','v_min_max_for_clip','smo_k_d')
        kwargs = {key:self.setup[key] for key in keys if key in self.setup}
        kwargs['online_mode'] = False
        model.setup(self.condition_handler.x_s_info_0, **kwargs)


class IndexedImages:
    def __init__(self, images, indices):
        self.images, self.indices = images, indices
    def __len__(self):
        return len(self.indices)
    def __getitem__(self,index):
        return self.images[self.indices[index]]


class FrameSourceSequence:
    """The SDK keeps its list contract while frame refs select their own source."""
    def __init__(self, sources, timeline, field, initial):
        self.sources, self.timeline, self.field, self.initial = sources, timeline, field, initial
    def __len__(self):
        return len(self.initial)
    def __getitem__(self, index):
        if not isinstance(index, FrameRef):
            return self.initial[index]
        if self.field == 'img_rgb_lst':
            return self.sources.image(index.source_key,index.source_index)
        if self.field == 'x_s_info_lst':
            return self.timeline.epochs[index.epoch].motion[index.source_index]
        return self.sources.get(index.source_key)[self.field][index.source_index]


class ConditionTimeline:
    def __init__(self, sources, *, sdk=None, start_index=0, initial_source_key=None,
                 initial_source_info=None, settings=None, source_cursors=None):
        from gui_controls import DEFAULTS
        self.sources, self.sdk = sources, sdk
        self.spans, self._starts, self.epochs = [], [], {}
        self.accepted = 0
        self._epoch_count = 0
        self._last_epoch = None
        self.cursors = dict(source_cursors or {})
        if initial_source_key is not None:
            self.cursors.setdefault(initial_source_key,start_index)
        self.initial_source_key, self.initial_source_info = initial_source_key, initial_source_info
        self.initial_settings = {**DEFAULTS,'conditioning':'Source face',**(settings or {})}
        self._lock = threading.RLock()
        self._emotion_rows = {}

    def _new_epoch(self, start, source_key, cursor, choice, key):
        from gui_controls import make_kwargs, parse_seed
        from core.atomic_components.condition_handler import ConditionHandler
        manifest = self.sources.manifest(source_key)
        source = self.sources.get(source_key)
        order = list(manifest['source_order'])
        if manifest['prepare_options']['loop_mode'] == 'pingpong' and len(order)>1:
            order += order[::-1]
        values = {'conditioning':'Source face', **dict(choice.settings)}
        setup = {**(getattr(self.sdk,'default_kwargs',{}) if self.sdk else {}),
                 **make_kwargs(values,is_video=not manifest['is_image'])['setup_kwargs']}
        for name in ('delta_eye_arr','v_min_max_for_clip'):
            if isinstance(setup.get(name),list):
                setup[name] = np.asarray(setup[name],dtype=np.float32)
        motion = source['x_s_info_lst']
        if len(motion)>1 and setup.get('smo_k_s',13)>1:
            from core.atomic_components.avatar_registrar import smooth_x_s_info_lst
            motion = smooth_x_s_info_lst(motion,smo_k=setup.get('smo_k_s',13))
        indices = [order[(cursor+i)%len(order)] for i in range(len(order))]
        info = {name:[array[i] for i in indices] for name,array in source.items()
                if name.endswith('_lst') and name != 'img_rgb_lst'}
        info.update(x_s_info_lst=[motion[i] for i in indices], sc=source['sc'],
                    is_image_flag=source['is_image_flag'], img_rgb_lst=IndexedImages(source['img_rgb_lst'],indices))
        reuse = (self._epoch_count == 0 and self.sdk is not None
                 and source_key == self.initial_source_key
                 and all(self.initial_settings.get(name) == value for name,value in choice.settings if name != 'emotion')
                 and hasattr(self.sdk.condition_handler,'x_s_info_0')
                 and hasattr(self.sdk.motion_stitch,'N_d'))
        if reuse:
            # Reuse the already-seeded first setup, including its blink sequence.
            handler, stitch = copy(self.sdk.condition_handler), copy(self.sdk.motion_stitch)
            info = self.initial_source_info or info
        else:
            handler = copy(self.sdk.condition_handler) if self.sdk else ConditionHandler()
            # Worker.setup's injected bound closure targets the prototype; use the
            # original class method on this private handler instead.
            handler.__dict__.pop('setup',None)
            ch_info = setup.get('ch_info')
            if ch_info is None:
                ch_info = {name:info[name] for name in ('x_s_info_lst','sc','eye_open_lst','eye_ball_lst')}
            handler.setup(info, NATIVE_EMOTIONS.index(choice.native_emotion),
                          eye_f0_mode=setup.get('eye_f0_mode',False),ch_info=ch_info)
            stitch = None
            if self.sdk is not None:
                stitch = copy(self.sdk.motion_stitch)
                names = inspect.signature(type(stitch).setup).parameters
                kwargs = {name:setup[name] for name in names if name in setup}
                kwargs.update(N_d=-1,is_image_flag=manifest['is_image'],x_s_info=info['x_s_info_lst'][0],d0=None)
                stitch.setup(**kwargs)
        call = type(handler).__call__
        wrapped = types.FunctionType(call.__code__,{**call.__globals__,'_mirror_index':lambda i,n:i%n},
                                     call.__name__,call.__defaults__,call.__closure__)
        handler.__class__ = type('FrameLoopCondition',(type(handler),),{'__call__':wrapped})
        number = self._epoch_count
        self._epoch_count += 1
        return SourceEpoch(number,start,start,key,source_key,order,motion,info,setup,handler,stitch,reuse,
                           seed=parse_seed(values.get('seed', '')))

    def append(self,start,count,choice,*,fade_offset=None,fade_frame_count=None):
        if type(start) is not int or start != self.accepted or type(count) is not int or count < 1:
            raise ValueError('Chunk timeline must append positive consecutive real frames.')
        if fade_offset is not None and (type(fade_offset) is not int or fade_offset < 0):
            raise ValueError('Logical fade offset must be a nonnegative integer.')
        if fade_frame_count is not None and (fade_offset is None or type(fade_frame_count) is not int
                or fade_frame_count < fade_offset+count):
            raise ValueError('Logical fade frame count must contain this window.')
        source_key = self.sources.register(choice.avatar_path)
        key = (source_key,tuple((name,value) for name,value in choice.settings if name != 'emotion'))
        with self._lock:
            cursor = self.cursors.get(source_key,0)
            epoch = self._last_epoch
            if epoch is None or epoch.key != key:
                epoch = self._new_epoch(start,source_key,cursor,choice,key)
                self.epochs[epoch.number] = epoch
                self._last_epoch = epoch
            epoch.end = start+count
            span = dict(start=start,end=start+count,epoch=epoch.number,choice=choice,source_start=cursor)
            if fade_offset is not None:
                span.update(fade_offset=fade_offset,fade_frame_count=fade_frame_count)
            self.spans.append(span)
            self._starts.append(start)
            self.cursors[source_key] = cursor+count
            self.accepted += count

    def _span(self,frame):
        index = bisect_right(self._starts,frame)-1
        if index < 0 or frame >= self.spans[index]['end']:
            raise ValueError('Frame identity is not retained by this reply.')
        return self.spans[index]

    def frame_controls(self, frame, control):
        """Apply SDK-compatible fades over the captured logical speech span."""
        with self._lock:
            span = self._span(frame)
            settings = dict(span['choice'].settings)
            index, count = frame-span['start'], span['end']-span['start']
            if span.get('fade_offset') is not None:
                index += span['fade_offset']
                count = span['fade_frame_count']
        fade_in, fade_out = int(settings.get('fade_in', 0)), int(settings.get('fade_out', 0))
        alpha = None
        if fade_in > 0 and index < fade_in:
            alpha = index/fade_in
        # Match SDK.setup_Nd: fade-out wins if the two windows overlap.
        if fade_out > 0 and count is not None and index >= count-fade_out-1:
            alpha = max(0.0, min(1.0, (count-1-index)/fade_out))
        return control if alpha is None else {**control, 'fade_alpha': alpha}

    def ref(self,frame):
        with self._lock:
            span = self._span(frame)
            epoch = self.epochs[span['epoch']]
            index = epoch.order[(span['source_start']+frame-span['start'])%len(epoch.order)]
            return FrameRef(frame,epoch.source_key,index,epoch.number)

    def condition(self,features,position,*,epoch_end=None):
        with self._lock:
            span = self._span(position)
            epoch = self.epochs[span['epoch']]
            end = min(self.accepted,epoch.end,epoch_end if epoch_end is not None else self.accepted)
            real = min(len(features),end-position)
            if real < 1:
                raise ValueError('No real audio frames available for conditioning.')
            emotions = []
            for frame in range(position,position+real):
                target = self._span(frame)['choice'].native_emotion
                if target not in self._emotion_rows:
                    self._emotion_rows[target] = epoch.condition_handler._parse_emo_seq(NATIVE_EMOTIONS.index(target))[0]
                emotions.append(self._emotion_rows[target])
            result = epoch.condition_handler(features[:real],position-epoch.start,emo=np.stack(emotions))
            if real < len(features):
                result = np.concatenate([result,np.repeat(result[-1:],len(features)-real,axis=0)])
            return result

    def retire_before(self,frame):
        with self._lock:
            while len(self.spans)>1 and self.spans[0]['end']<=frame:
                self.spans.pop(0)
                self._starts.pop(0)
            alive = {span['epoch'] for span in self.spans}
            for number in list(self.epochs):
                if number not in alive:
                    del self.epochs[number]
