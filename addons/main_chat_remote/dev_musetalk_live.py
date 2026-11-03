"""Private phone video producer, hosted by NC's backend. Never commands chat or audio.

The legacy module name is retained for existing clients and diagnostic tests.
"""
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
import json
import io
import logging
import math
import hashlib
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import wave

from core.dev_musetalk_live_readiness import BridgeReader, complete_png, signature, wav_identity
from core.dev_musetalk_segments import encode_range, segment_ranges
from core.phone_media_tools import hidden, inspect_video, tools
from .media_quality import load_quality, video_quality
from core.diagnostics.plan_trace import PlanTrace

_plan_diagnostics = PlanTrace()

SAFE = re.compile(r'[A-Za-z0-9_-]{1,160}')
MAX_MEDIA = 16*1024*1024
# Hash/duration/path records only, matching the audio bridge's 64 retained chunks.
# This does not reserve WAV bodies, encoded segments, or native video players.
MAX_SOURCE_IDENTITIES = 64
SPEECH_WINDOW = 4
SUCCESSOR_WINDOW = 3
FPS = 24
_UNSET = object()


class MuxedTrialBusyError(ValueError):
    """Valid opt-in arm may retry after the previous producer retires."""


def _failure_diagnostic(error):
    """Bounded categories and code locations only, never exception text/locals."""
    reasons = {
        'Frame exceeds cap': 'source_frame_size',
        'Source changed during snapshot': 'source_snapshot_changed',
        'Published media cap exceeded': 'published_media_cap',
        'Invalid segment range': 'invalid_segment_range',
        'Refusing to overwrite an existing segment': 'existing_segment',
        'Segment appeared during encoding': 'segment_publication_collision',
        'Segment encode exceeded 30 seconds': 'encoder_timeout',
        'Segment exceeds size cap': 'segment_size_cap',
        'Segment encode failed': 'encoder_process_failed',
        'Invalid encoded size': 'invalid_media_size',
        'Encoded segment does not match its exact range': 'encoded_range_mismatch',
        'Idle source changed during encode': 'idle_source_changed',
        'Ambiguous render identity': 'ambiguous_source',
        'Render duration mismatch': 'source_duration_mismatch',
        'Source identity cap exceeded': 'source_identity_cap',
        'Source audio exceeds size cap': 'source_audio_size',
        'Delivery metadata frame count is too short': 'source_frame_count',
        'Invalid idle chunk source': 'invalid_idle_source',
        'Idle chunk source changed': 'idle_chunk_source_changed',
    }
    known_types = (ValueError, RuntimeError, OSError, FileNotFoundError, FileExistsError,
                   PermissionError, TimeoutError, subprocess.CalledProcessError, subprocess.TimeoutExpired)
    kind = type(error)
    detail = {'exception': kind.__name__ if kind in known_types else 'Exception',
              'reason': reasons.get(str(error), 'unclassified') if kind in known_types else 'unclassified',
              'frames': []}
    for name in ('errno', 'winerror', 'returncode'):
        value = getattr(error, name, None)
        if type(value) is int:
            detail[name] = value
    root = Path(__file__).resolve().parents[2]
    locations = {str(path.resolve()): path.name for path in (
        Path(__file__), root/'core/dev_musetalk_segments.py',
        root/'core/dev_musetalk_live_readiness.py', root/'core/phone_media_tools.py',
        Path(__file__).with_name('idle_chunk_stream.py'), Path(__file__).with_name('muxed_trial_encoding.py'),
        Path(__file__).with_name('ordered_speech_source.py'), Path(__file__).with_name('idle_loop_catalog.py'))}
    trace = error.__traceback__
    while trace is not None:
        code = trace.tb_frame.f_code
        filename = locations.get(code.co_filename)
        if filename:
            detail['frames'].append({'file': filename, 'function': code.co_name, 'line': trace.tb_lineno})
        trace = trace.tb_next
    detail['frames'] = detail['frames'][-6:]
    return detail


def _non_negative_int(value):
    return type(value) is int and value >= 0


def load_delivery_metadata(source, renders, runtime):
    """Read the local render contract; absent initial metadata is not failure."""
    source = Path(source).resolve(strict=True)
    renders = Path(renders).resolve(strict=True)
    runtime = Path(runtime).resolve(strict=True)
    source.relative_to(renders)
    sidecar = source/'phone-delivery.json'
    # The adapter may recreate the render directory after publishing its initial
    # contract. During that narrow window the sibling is the only durable copy.
    if not sidecar.is_file():
        sidecar = renders/f'.phone-delivery-{source.name}.json'
    if not sidecar.exists():
        raise FileNotFoundError('Delivery metadata not published yet')
    if sidecar.is_symlink() or not sidecar.is_file() or sidecar.stat().st_size > 32768:
        raise ValueError('Delivery metadata unavailable')
    payload = json.loads(sidecar.read_text(encoding='utf-8'))
    required = {'version', 'chunkId', 'fps', 'trimStartFrames', 'avatarId',
                'sourceStartIndex', 'idleFrameDir', 'frameCount'}
    optional = {'anticipation', 'sourceTimeline', 'orderedOutput', 'remoteSource', 'sourceSpans'}
    if (not isinstance(payload, dict) or not required <= set(payload) or set(payload) - required - optional or payload['version'] != 1
            or payload['chunkId'] != source.name or payload['fps'] != FPS
            or not _non_negative_int(payload['trimStartFrames'])
            or not isinstance(payload['avatarId'], str) or not payload['avatarId']
            or ((payload['sourceStartIndex'] is None) != (payload['frameCount'] is None))
            or (payload['sourceStartIndex'] is not None and not _non_negative_int(payload['sourceStartIndex']))
            or (payload['frameCount'] is not None and not _non_negative_int(payload['frameCount']))):
        raise ValueError('Invalid final delivery metadata')
    idle = Path(payload['idleFrameDir'])
    if not idle.is_absolute() or idle.is_symlink():
        raise ValueError('Invalid idle frame directory')
    idle = idle.resolve(strict=True)
    allowed_roots = ((runtime/'MuseTalk/results').resolve(), (runtime/'avatar_packs').resolve())
    if not any(idle == root or idle.is_relative_to(root) for root in allowed_roots):
        raise ValueError('Idle frame directory outside MuseTalk results')
    if not idle.is_dir() or idle.name != 'full_imgs':
        raise ValueError('Invalid idle frame directory')
    if 'remoteSource' in payload:
        from core.avatar_output_contract import validate_remote_source
        payload['remoteSource'] = validate_remote_source(payload['remoteSource'])
    if 'sourceSpans' in payload:
        from core.avatar_output_contract import validate_source_spans
        payload['sourceSpans'] = validate_source_spans(payload['sourceSpans'],payload['frameCount'])
    if 'orderedOutput' in payload:
        from core.avatar_output_contract import validate_ordered_start
        payload['orderedOutput'] = validate_ordered_start(payload['orderedOutput'])
        first_motion=(payload['sourceSpans'][0]['timeline']['motionId'] if 'sourceSpans' in payload
                      else hashlib.sha256(str(idle).encode()).hexdigest())
        if payload['sourceStartIndex'] is not None and payload['orderedOutput']['motionId'] != first_motion:
            raise ValueError('ordered_output_source_mismatch')
    if 'sourceTimeline' in payload:
        from .relay.frame_handoff import validate_timeline
        try:
            timeline = validate_timeline(payload['sourceTimeline'])
            if (timeline['motionId'] != hashlib.sha256(str(idle).encode()).hexdigest()
                    or timeline['sourceFrameCount'] != len(idle_frames(idle))
                    or len(timeline['sourceIndices']) != payload['frameCount']):
                raise ValueError('Source timeline mismatch')
            payload['sourceTimeline'] = timeline
        except ValueError:
            # Optional visual metadata cannot invalidate otherwise valid audio.
            payload.pop('sourceTimeline', None)
    if 'orderedOutput' in payload and payload['sourceStartIndex'] is not None:
        from core.avatar_output_contract import validate_ordered_render
        validate_ordered_render(payload['orderedOutput'], payload.get('sourceTimeline'), payload['frameCount'],payload.get('sourceSpans'))
    return {**payload, 'idleFrameDir': idle, 'final': payload['sourceStartIndex'] is not None}


def idle_frames(idle_dir):
    """Accept only contiguous, real PNGs: ffmpeg then has no path expansion."""
    idle_dir = Path(idle_dir).resolve(strict=True)
    paths = sorted(idle_dir.glob('*.png'))
    if not 1 <= len(paths) <= 1440:
        raise ValueError('Invalid idle frame count')
    for index, path in enumerate(paths):
        if path.is_symlink() or path.name != f'{index:08d}.png':
            raise ValueError('Idle frames are not contiguous')
        path.resolve(strict=True).relative_to(idle_dir)
        if not 0 < path.stat().st_size <= 8*1024*1024:
            raise ValueError('Invalid idle frame')
    return paths


def encode_idle_cycle(ffmpeg, frames, output, *, cancelled=lambda: False, quality=None):
    """Encode the unrotated desktop cycle once; seek is a phone concern."""
    if cancelled():
        return None
    frames = list(frames)
    if not 1 <= len(frames) <= 1440:
        raise ValueError('Invalid idle frame count')
    output = Path(output); partial = output.with_suffix('.partial.mp4')
    if output.exists() or partial.exists():
        raise FileExistsError('Refusing to overwrite idle video')
    _, ffprobe = tools()
    command = [ffmpeg, '-nostdin', '-v', 'error', '-n', '-framerate', str(FPS),
               '-start_number', '0', '-i', str(frames[0].parent/'%08d.png'), '-an', '-map', '0:v:0',
               '-vf', "scale=w='min(iw,448)':h='min(ih,672)':force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1",
               '-frames:v', str(len(frames)), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
               '-threads', '2', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(partial)]
    fps, encoded_count = FPS, len(frames)
    if quality is not None:
        # Keep FFmpeg in this lightweight backend process. The cache's PyAV
        # encoder runs in a separate media environment; match its settings and
        # colour conversion without importing that environment here.
        settings = video_quality(quality)
        fps, width = settings['video_fps'], settings['video_width']
        step = FPS//fps
        encoded_count = (len(frames)+step-1)//step
        filters = (f"trim=end_frame={len(frames)},select='not(mod(n,{step}))',setpts=N/({fps}*TB),"
                   f"scale=w='min(iw,{width})':h='min(ih,{width*3//2})':"
                   "force_original_aspect_ratio=decrease:force_divisible_by=2:"
                   "in_range=full:out_range=tv:out_color_matrix=bt601,setsar=1")
        command = [ffmpeg, '-nostdin', '-v', 'error', '-n', '-framerate', str(FPS),
                   '-start_number', '0', '-i', str(frames[0].parent/'%08d.png'), '-an', '-map', '0:v:0',
                   '-vf', filters, '-r', str(fps), '-frames:v', str(encoded_count),
                   '-c:v', 'libx264', '-preset', 'veryfast', '-profile:v', 'baseline',
                   '-b:v', str(settings['video_kbps']*1000), '-threads', '2', '-pix_fmt', 'yuv420p',
                   '-colorspace', 'smpte170m', '-color_range', 'tv', '-movflags', '+faststart', str(partial)]
    process = None
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, **hidden())
        deadline = time.monotonic()+45
        while process.poll() is None:
            if cancelled(): return None
            if time.monotonic() >= deadline: raise TimeoutError('Idle encode exceeded 45 seconds')
            if partial.exists() and partial.stat().st_size > MAX_MEDIA: raise ValueError('Idle video exceeds cap')
            time.sleep(.01)
        if process.returncode or cancelled(): return None
        if not 0 < partial.stat().st_size <= MAX_MEDIA: raise ValueError('Invalid idle video size')
        info = inspect_video(ffprobe, partial); streams = info['streams']
        if (len(streams) != 1 or streams[0]['codec_type'] != 'video' or streams[0]['codec_name'] != 'h264'
                or streams[0]['r_frame_rate'] != f'{fps}/1' or int(streams[0]['nb_frames']) != encoded_count):
            raise ValueError('Idle video does not match source cycle')
        partial.rename(output); return output
    finally:
        if process is not None and process.poll() is None:
            process.kill(); process.wait(timeout=5)
        partial.unlink(missing_ok=True)


@dataclass
class PendingChunk:
    audio: dict
    sequence: int
    media_id: str
    digest: str
    duration: float
    claimed_at: float
    rows: list
    source: Path | None = None
    metadata: dict | None = None
    idle_source: Path | None = None
    idle_source_id: str = ''
    state: str = 'claimed'
    muxed_wav: Path | None = None
    muxed_samples: int = 0
    muxed_encoder: object | None = None


@dataclass
class IdleChunkLane:
    idle_chunk_request: dict | None = None
    idle_chunk_stream: object | None = None
    idle_chunk_unavailable: bool = False
    idle_chunk_cleanup_failed: bool = False
    retired_idle_chunk_requests: set = field(default_factory=set)


@dataclass
class Trial:
    id: str
    root: Path
    old_audio: set
    old_staged: set
    deadline: float
    stop: threading.Event = field(default_factory=threading.Event)
    audio: dict | None = None
    sequence: int = -1
    media_id: str = ''
    digest: str = ''
    duration: float = 0
    current: int = 0
    source: Path | None = None
    candidates: dict = field(default_factory=dict)
    rows: list = field(default_factory=list)
    state: str = 'armed'
    failure_stage: str = ''
    claimed_at: float = 0
    thread: threading.Thread | None = None
    pending: PendingChunk | None = None
    metadata: dict | None = None
    idle: dict | None = None
    idle_unavailable: bool = False
    warm_idle: Path | None = None
    warm_start: int = 0
    idle_cache: dict | None = None
    idle_source_version: int = 0
    idle_source: Path | None = None
    idle_source_id: str = ''
    anticipation: dict | None = None
    recovery_audio: dict | None = None
    arm_request_id: str | None = None
    loop_fade_ms: int = 180
    video_quality: dict | None = None
    chunked_idle: bool = False
    muxed_audio: bool = False
    muxed_wav: Path | None = None
    muxed_samples: int = 0
    muxed_encoder: object | None = None
    idle_chunk_request: dict | None = None
    retired_muxed_ids: set = field(default_factory=set)
    idle_chunk_stream: object | None = None
    idle_chunk_unavailable: bool = False
    idle_chunk_cleanup_failed: bool = False
    retired_idle_chunk_requests: set = field(default_factory=set)
    idle_chunk_return: IdleChunkLane = field(default_factory=IdleChunkLane)
    idle_chunk_sources: dict = field(default_factory=dict)
    idle_chunk_turn: int = 0


class DevMuseTalkLive:
    def __init__(self, runtime, output_root, *, reader=None, now=time.monotonic):
        self.runtime = Path(runtime).resolve(strict=True)
        self.staged = (self.runtime/'MuseTalk/runtime/staged_audio').resolve(strict=True)
        self.renders = (self.runtime/'MuseTalk/runtime/rendered_chunks').resolve(strict=True)
        self.output = Path(output_root).resolve(strict=True)
        if not self.output.is_dir() or self.output.is_relative_to(self.staged) or self.output.is_relative_to(self.renders):
            raise ValueError('Invalid private output root')
        self.reader = reader or BridgeReader(self.runtime)
        self.now = now
        self.ffmpeg, _ = tools()
        self.lock = threading.RLock()
        self.ready_condition = threading.Condition()
        self.ready_version = 0
        self.ready_waiters = 0
        self.trial = None
        self.retained_idle = None
        self.closed = False
        self.cancelled_arms = {}  # Bounded tombstones for cancel-before-ack races.
        # Recover only our marked, abandoned private artifacts after a crashed helper.
        for candidate in list(self.output.glob('nc-live-trial-*'))[:100]:
            try:
                resolved = candidate.resolve(strict=True)
                if resolved != candidate or resolved.parent != self.output or time.time()-resolved.stat().st_mtime <= 900:
                    continue
                marker = resolved/'owner.json'
                if marker.stat().st_size < 256 and json.loads(marker.read_text()).get('service') == 'nc-dev-musetalk-live-v1':
                    shutil.rmtree(resolved)
            except (OSError, ValueError):
                pass

    @property
    def busy(self):
        with self.lock:
            return bool(self.trial and self.trial.thread and self.trial.thread.is_alive())

    def _get(self, trial_id):
        t = self.trial
        if not t or trial_id != t.id or t.stop.is_set() or self.now() >= t.deadline:
            raise LookupError('Live trial unavailable')
        return t

    @staticmethod
    def _validate_arm_request(arm_request_id):
        if arm_request_id is not None and (not isinstance(arm_request_id, str)
                or not re.fullmatch(r'[A-Za-z0-9_-]{16,96}', arm_request_id)):
            raise ValueError('Invalid arm request identity')

    def _prune_cancelled_arms(self):
        now = self.now()
        self.cancelled_arms = {key: expiry for key, expiry in self.cancelled_arms.items() if expiry > now}

    @staticmethod
    def _arm_result(t):
        return {'trialId': t.id, 'state': 'armed', **({'idleChunks': True} if t.chunked_idle else {}),
                **({'muxedAudio': True, 'readyWaitVersion': 1} if t.muxed_audio else {})}

    def _notify_ready(self):
        # Never take the producer lock under this condition: bridge/disk work
        # can hold that lock longer than a control request's waiting budget.
        with self.ready_condition:
            self.ready_version += 1
            self.ready_condition.notify_all()

    def wait_ready(self, body):
        """Bounded read-only readiness wait for one exact muxed source."""
        def reject(message, checks):
            # Failure-only evidence, captured under the existing producer lock
            # where applicable. Never include incoming IDs, paths or audio data.
            try:
                session = body.get('trialId') if isinstance(body, dict) else None
                if not isinstance(session, str) or not re.fullmatch('[a-f0-9]{32}',session):
                    session = 'ready-wait-invalid'
                for condition, actual in checks.items():
                    _plan_diagnostics.observe(session,'backend.plan.wait_ready.reject',condition,
                        True if isinstance(actual,bool) else None,actual)
            except Exception:
                pass
            raise ValueError(message)
        if (not isinstance(body, dict) or set(body) != {'trialId', 'audio', 'mediaId', 'currentIndex'}
                or any(not isinstance(body[key], str) or not re.fullmatch('[a-f0-9]{32}', body[key])
                       for key in ('trialId', 'mediaId'))
                or type(body['currentIndex']) is not int or not 0 <= body['currentIndex'] < 60
                or not isinstance(body['audio'], dict)
                or set(body['audio']) != {'id', 'phone_request_id', 'url_path'}):
            value = body if isinstance(body,dict) else {}
            reject('Invalid ready wait identity', {
                'body_object':isinstance(body,dict),
                'keys_valid':set(value)=={'trialId','audio','mediaId','currentIndex'},
                'trial_id_valid':isinstance(value.get('trialId'),str) and bool(re.fullmatch('[a-f0-9]{32}',value['trialId'])),
                'media_id_valid':isinstance(value.get('mediaId'),str) and bool(re.fullmatch('[a-f0-9]{32}',value['mediaId'])),
                'index_valid':type(value.get('currentIndex')) is int and 0<=value['currentIndex']<60,
                'audio_shape_valid':isinstance(value.get('audio'),dict) and set(value['audio'])=={'id','phone_request_id','url_path'},
            })
        until = time.monotonic()+1
        def snapshot():
            if not self.lock.acquire(timeout=max(0, until-time.monotonic())):
                raise MuxedTrialBusyError('Ready wait producer busy')
            try:
                t = self._get(body['trialId'])
                if (not t.muxed_audio or body['audio'] != t.audio or body['mediaId'] != t.media_id
                        or not t.current <= body['currentIndex'] < len(t.rows)):
                    reject('Ready wait source changed', {
                        'muxed_audio':bool(t.muxed_audio),
                        'audio_matches':body['audio']==t.audio,
                        'media_matches':body['mediaId']==t.media_id,
                        'index_not_retired':t.current<=body['currentIndex'],
                        'index_in_rows':body['currentIndex']<len(t.rows),
                        'requested_index':body['currentIndex'],
                        'current_index':t.current,'row_count':len(t.rows),
                    })
                return t, self._status(t)
            except ValueError as error:
                try:
                    for index, frame in enumerate(_failure_diagnostic(error)['frames']):
                        for field, value in frame.items():
                            _plan_diagnostics.observe(body['trialId'],'backend.plan.wait_ready.reject',
                                f'validation_origin.{index}.{field}',None,value)
                except Exception:
                    pass
                raise
            finally:
                self.lock.release()
        with self.ready_condition:
            if self.ready_waiters >= 2:
                raise MuxedTrialBusyError('Ready wait capacity full')
            self.ready_waiters += 1
        try:
            while True:
                with self.ready_condition:
                    version = self.ready_version
                t, result = snapshot()
                row = result['segments'][body['currentIndex']]
                if (result['state'] == 'unavailable' or row['state'] == 'unavailable'
                        or (row['state'] == 'ready' and result['sourceState'] == 'matched'
                            and result.get('sourceTimeline') and result.get('idleChunkReturn'))):
                    return result
                with self.ready_condition:
                    remaining = min(until-time.monotonic(), t.deadline-self.now())
                    if remaining <= 0:
                        break
                    # Publication between snapshot and wait changes the version;
                    # recheck immediately instead of losing that notification.
                    if version == self.ready_version:
                        self.ready_condition.wait(remaining)
            # Do not return a stale snapshot if expiry/Stop/promotion won at
            # the timeout boundary. Outside the condition, the producer lock
            # is attempted nonblocking once the request budget has elapsed.
            return snapshot()[1]
        finally:
            with self.ready_condition:
                self.ready_waiters -= 1

    @staticmethod
    def _retired_pipeline_chunk(state, chunk, muxed_audio):
        # Pipeline telemetry can outlive cancellation. Exclude proven older
        # generations or explicitly cancelled preparation in this muxed lane,
        # never unknown/current pending work. Video-only admission is unchanged.
        actions = state.get('conversation_actions')
        current = actions.get('session_generation') if isinstance(actions, dict) else None
        previous = chunk.get('speech_session_generation')
        return (muxed_audio and type(current) is int and type(previous) is int
                and 0 <= previous <= current
                and (previous < current or chunk.get('status') == 'cancelled'))

    def arm(self, *, arm_request_id=None, idle_chunks=False, muxed_audio=False):
        with self.lock:
            self._validate_arm_request(arm_request_id)
            if type(idle_chunks) is not bool:
                raise ValueError('Invalid idle chunk mode')
            if type(muxed_audio) is not bool or (muxed_audio and not idle_chunks):
                raise ValueError('Muxed trial requires uncached idle chunks')
            self._prune_cancelled_arms()
            if arm_request_id in self.cancelled_arms:
                raise ValueError('Arm request was cancelled')
            t = self.trial
            if arm_request_id is not None and t and t.arm_request_id == arm_request_id:
                if t.chunked_idle != idle_chunks or t.muxed_audio != muxed_audio:
                    raise ValueError('Arm mode changed within its identity')
                if (not self.closed and not t.stop.is_set() and self.now() < t.deadline
                        and t.audio is None and self.busy):
                    return self._arm_result(t)
                raise ValueError('Arm request is no longer active')
            if arm_request_id is not None and len(self.cancelled_arms) >= 64:
                raise ValueError('Arm cancellation history full')
            if not self.closed and self.busy and muxed_audio:
                raise MuxedTrialBusyError('Live trial busy')
            if self.closed or self.busy:
                raise ValueError('Live trial busy or closed')
            state = json.loads(self.reader.get('/api/state'))['state']
            rejection = ('avatar_not_musetalk' if 'avatar musetalk' not in state.get('status_line', '').lower()
                else 'runtime_not_listening' if not state.get('runtime_status', {}).get('listening')
                else 'pipeline_pending' if any(c.get('status') != 'rendered' and not self._retired_pipeline_chunk(state, c, muxed_audio)
                    for c in state.get('musetalk', {}).get('pipeline', {}).get('chunks', [])) else None)
            if rejection:
                error = ValueError('MuseTalk must be idle and initialized')
                error.diagnostic_reason = rejection
                raise error
            old_audio = {item['id'] for item in self.reader.audio()}
            old_staged = {p.name for p in self.staged.glob('*.wav')}
            root = Path(tempfile.mkdtemp(prefix='nc-live-trial-', dir=self.output)).resolve()
            root.relative_to(self.output)
            (root/'owner.json').write_text(json.dumps({'service':'nc-dev-musetalk-live-v1'}), encoding='utf-8')
            t = Trial(secrets.token_hex(16), root, old_audio, old_staged, self.now()+(6000 if muxed_audio else 120))
            t.arm_request_id = arm_request_id
            t.chunked_idle = idle_chunks
            t.muxed_audio = muxed_audio
            t.loop_fade_ms = self._loop_fade(state)
            t.video_quality = video_quality(load_quality(self.runtime/'runtime/main_chat_remote'))
            if muxed_audio:
                t.video_quality = {**t.video_quality, 'video_fps': FPS}
            warmed = self._selected_idle_source(state)
            if warmed:
                t.warm_idle, t.warm_start = warmed
                self._set_idle_source(t, t.warm_idle)
            self.trial = t
            t.thread = threading.Thread(target=_plan_diagnostics.bind_operation(t.id,'backend.producer.run',self._run), args=(t,), name='nc-dev-live-video', daemon=True)
            t.thread.start()
            return self._arm_result(t)

    def _reject_recovery(self, reason):
        self._log_recovery('rejected', reason)
        raise ValueError('Recovery request rejected')

    @staticmethod
    def _log_recovery(category, reason):
        """Best-effort bounded diagnostics; logging cannot change recovery."""
        try:
            logging.getLogger(__name__).warning(
                'recovery_%s %s', category,
                json.dumps({'reason': reason}, separators=(',', ':')))
        except Exception:
            pass

    def _recovery_identity(self, audio):
        if not isinstance(audio, dict) or set(audio) != {'id', 'phone_request_id', 'url_path'}:
            self._reject_recovery('invalid_audio')
        if any(not isinstance(audio[key], str) or not SAFE.fullmatch(audio[key])
               for key in ('id', 'phone_request_id')):
            self._reject_recovery('invalid_audio')
        if audio['url_path'] != '/api/audio/file/'+audio['id']:
            self._reject_recovery('invalid_audio')
        return dict(audio)

    def _recovery_sources(self, previous, digest):
        """Preserve bounded source observations; audio admission still matches WAVs."""
        candidates = {}
        if previous:
            for name, candidate in previous.candidates.items():
                try:
                    source = candidate[2].resolve(strict=True)
                    source.relative_to(self.renders)
                except (OSError, ValueError):
                    self._reject_recovery('source_invalid')
                if not source.is_dir():
                    self._reject_recovery('source_invalid')
                if len(candidates) >= MAX_SOURCE_IDENTITIES:
                    self._reject_recovery('source_limit')
                candidates[name] = candidate
            # Preserve the original trial's observation window. Sources for later
            # chunks may already have lost their staging WAVs during rendering.
            return candidates, set(previous.old_staged)
        paths = list(self.staged.glob('*.wav'))
        if len(paths) > 256:
            self._reject_recovery('source_limit')
        old_staged = {path.name for path in paths}
        for path in paths:
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(self.staged)
                source = (self.renders/path.stem).resolve()
                source.relative_to(self.renders)
                if path.is_symlink() or not source.is_dir():
                    continue
                before = signature(path)
                if not 0 < before[0] <= MAX_MEDIA:
                    continue
                with path.open('rb') as handle:
                    body = handle.read(MAX_MEDIA+1)
                if len(body) > MAX_MEDIA or signature(path) != before:
                    continue
                candidate_digest, _ = wav_identity(body)
            except (FileNotFoundError, OSError, ValueError):
                continue
            if candidate_digest == digest:
                old_staged.discard(path.name)
        return candidates, old_staged

    def recover(self, audio):
        """Bind one interrupted opening without weakening the manual arm gate."""
        audio = self._recovery_identity(audio)
        with self.lock:
            previous = self.trial
            if self.closed:
                self._reject_recovery('closed')
            if previous and previous.thread and previous.thread.is_alive():
                if previous.recovery_audio == audio and not previous.stop.is_set():
                    return self._arm_result(previous)
                self._log_recovery('waiting', 'worker_busy')
                return {'state': 'waiting', 'reason': 'worker_busy'}
            items = self.reader.audio()
            matches = [item for item in items if all(item.get(key) == value for key, value in audio.items())]
            if len(matches) != 1:
                self._reject_recovery('audio_unavailable')
            if type(matches[0].get('sequence_index')) is not int or matches[0]['sequence_index'] != 0:
                self._reject_recovery('not_opening')
            if previous and audio['id'] in previous.old_audio:
                self._reject_recovery('old_audio')
            if (previous and previous.recovery_audio is None and previous.audio
                    and previous.audio.get('phone_request_id') == audio['phone_request_id']):
                self._reject_recovery('old_audio')
            try:
                digest, _ = wav_identity(self.reader.get(audio['url_path']))
            except (OSError, ValueError):
                self._reject_recovery('audio_unavailable')
            state = json.loads(self.reader.get('/api/state'))['state']
            if 'avatar musetalk' not in state.get('status_line', '').lower():
                self._reject_recovery('musetalk_unavailable')
            candidates, old_staged = self._recovery_sources(previous, digest)
            root = Path(tempfile.mkdtemp(prefix='nc-live-trial-', dir=self.output)).resolve()
            root.relative_to(self.output)
            (root/'owner.json').write_text(json.dumps({'service':'nc-dev-musetalk-live-v1'}), encoding='utf-8')
            old_audio = set(previous.old_audio) if previous else {
                item['id'] for item in items if isinstance(item.get('id'), str)
            }
            old_audio.discard(audio['id'])
            t = Trial(secrets.token_hex(16), root, old_audio, old_staged, self.now()+120,
                      candidates=candidates, recovery_audio=audio,
                      chunked_idle=previous.chunked_idle if previous else False)
            t.loop_fade_ms = self._loop_fade(state)
            t.video_quality = video_quality(load_quality(self.runtime/'runtime/main_chat_remote'))
            warmed = self._selected_idle_source(state)
            if warmed:
                t.warm_idle, t.warm_start = warmed
                self._set_idle_source(t, t.warm_idle)
            self.trial = t
            t.thread = threading.Thread(target=_plan_diagnostics.bind_operation(t.id,'backend.producer.run',self._run), args=(t,), name='nc-dev-live-video', daemon=True)
            t.thread.start()
            self._log_recovery('armed', 'exact_opening')
            return self._arm_result(t)

    @staticmethod
    def _loop_fade(state):
        value = state.get('musetalk', {}).get('loopFadeMs', 180)
        return value if type(value) is int and 0 <= value <= 5000 else 180

    def _selected_idle_source(self, state):
        """Return the one configured local prepared cycle, never a supplied path."""
        selected = state.get('musetalk', {}).get('state', {}) if isinstance(state, dict) else {}
        avatar_id = selected.get('avatar_id', '')
        if not isinstance(avatar_id, str) or not SAFE.fullmatch(avatar_id):
            return None
        packs = (self.runtime/'avatar_packs').resolve()
        candidates = list(packs.glob(f'*/{avatar_id}/full_imgs')) if packs.is_dir() else []
        legacy = self.runtime/'MuseTalk/results/v15/avatars'/avatar_id/'full_imgs'
        if legacy.is_dir(): candidates.append(legacy)
        if len(candidates) != 1 or candidates[0].is_symlink():
            return None
        try:
            source = candidates[0].resolve(strict=True)
            if not (source.is_relative_to(packs) or source.is_relative_to((self.runtime/'MuseTalk/results').resolve())):
                return None
            idle_frames(source)
            offset = selected.get('preview_source_index', selected.get('source_index', 0))
            return source, int(offset) if _non_negative_int(offset) else 0
        except (OSError, ValueError):
            return None

    def _refresh_armed_idle(self, t, state):
        if t.audio is not None:
            return
        quality = video_quality(load_quality(self.runtime/'runtime/main_chat_remote'))
        if t.muxed_audio:
            quality = {**quality, 'video_fps': FPS}
        if t.video_quality != quality:
            # A quality edit while idle must rebuild the same source too. Once
            # speech is claimed, its frozen file set keeps the prior quality.
            t.video_quality = quality
            self._set_idle_source(t, None)
        selected = self._selected_idle_source(state)
        source, start = selected if selected else (None, 0)
        if source == t.warm_idle and source == t.idle_source:
            t.warm_start = start
            return
        t.warm_idle, t.warm_start, t.idle_unavailable = source, start, False
        self._set_idle_source(t, source)

    def _set_idle_source(self, t, source, source_id=None):
        """Activate one validated avatar source; never retain a different cache."""
        if source is not None and source == t.idle_source and t.idle_source_id:
            return t.idle_source_id
        self._revoke_idle(t)
        request = t.idle_chunk_request
        pending_request = request is not None and request['source'] is None
        # Download-paced speech metadata can run ahead of heard audio. Its
        # prospective return must not cancel the separately displayed idle.
        preserve_displayed = t.chunked_idle and t.audio is not None and request and not pending_request
        if not preserve_displayed:
            if request and not pending_request:
                t.retired_idle_chunk_requests.add(request['id'])
            t.idle_chunk_request = None
            self._retire_idle_chunks(t)
            t.idle_chunk_unavailable = t.idle_chunk_cleanup_failed
        t.idle_source_version += 1
        t.idle_source, t.idle_source_id = source, (source_id or secrets.token_hex(16)) if source else ''
        if pending_request:
            # Availability must not erase the already fenced request owner.
            t.idle_chunk_request = {**request, 'source': source, 'version': t.idle_source_version}
        t.idle_cache = None
        self._idle_path(t).unlink(missing_ok=True)
        return t.idle_source_id

    def prepare(self, trial_id, audio, current_index):
        if type(current_index) is not int or not 0 <= current_index < 60:
            raise ValueError('Invalid current segment')
        if not isinstance(audio, dict) or set(audio) != {'id', 'phone_request_id', 'url_path'}:
            raise ValueError('Invalid audio identity')
        if any(not isinstance(audio[k], str) or not SAFE.fullmatch(audio[k]) for k in ('id','phone_request_id')):
            raise ValueError('Invalid audio identity')
        if audio['url_path'] != '/api/audio/file/'+audio['id']:
            raise ValueError('Invalid audio URL')
        with self.lock:
            t = self._get(trial_id)
            if t.audio is None and t.recovery_audio is not None and audio != t.recovery_audio:
                raise ValueError('Recovery trial is bound to different bound audio')
            if t.state == 'unavailable':
                raise ValueError('Failed trial must be cancelled before retrying')
            if t.pending and audio == t.pending.audio:
                if current_index != 0:
                    raise ValueError('Prefetched chunk must start at its opening')
                pending = t.pending
                self._retire_muxed_source(t)
                self._retire_anticipation(t)
                t.anticipation = None
                for row in t.rows:
                    self._media_path(t, row['index']).unlink(missing_ok=True)
                for name, candidate in list(t.candidates.items()):
                    if candidate[0] == t.digest:
                        t.old_staged.add(name)
                        del t.candidates[name]
                t.audio, t.sequence, t.media_id = pending.audio, pending.sequence, pending.media_id
                t.digest, t.duration, t.claimed_at = pending.digest, pending.duration, pending.claimed_at
                t.rows, t.source, t.current, t.state = pending.rows, pending.source, 0, pending.state
                t.metadata = pending.metadata
                t.muxed_wav, t.muxed_samples, t.muxed_encoder = pending.muxed_wav, pending.muxed_samples, pending.muxed_encoder
                self._set_idle_source(t, pending.idle_source, pending.idle_source_id)
                self._use_idle_cache(t)
                t.pending = None
                t.deadline = self.now()+90
                self._notify_ready()
                return self._status(t)
            if t.pending and audio != t.audio:
                raise ValueError('Pending successor must be promoted first')
            if audio != t.audio:
                if current_index != 0 or audio['id'] in t.old_audio:
                    raise ValueError('A fresh chunk is required')
                matches = [item for item in self.reader.audio()
                           if all(item.get(k) == v for k,v in audio.items())]
                if len(matches) != 1:
                    raise ValueError('Phone audio is unavailable')
                sequence = matches[0].get('sequence_index')
                if type(sequence) is not int or sequence < 0:
                    raise ValueError('Invalid chunk sequence')
                if t.audio is None:
                    if sequence != 0:
                        raise ValueError('A fresh first chunk is required')
                elif audio['phone_request_id'] != t.audio['phone_request_id'] or sequence <= t.sequence:
                    raise ValueError('Only a later chunk of the same reply is allowed')
                body = self.reader.get(audio['url_path'])
                digest, duration = wav_identity(body)
                count = math.floor(duration*24)
                if not 1 <= count <= 720:
                    raise ValueError('Unsupported duration')
                if t.muxed_audio:
                    self._muxed_sample_count(body, count)
                self._retire_muxed_source(t)
                self._retire_anticipation(t)
                t.anticipation = None
                # Give each chunk distinct media URLs. Old requests/encodes cannot
                # expose the new chunk at a reused segment URL.
                for row in t.rows:
                    self._media_path(t, row['index']).unlink(missing_ok=True)
                for name, candidate in list(t.candidates.items()):
                    if candidate[0] == t.digest:
                        t.old_staged.add(name)
                        del t.candidates[name]
                t.media_id = t.id if t.audio is None else secrets.token_hex(16)
                # Keep one old cache privately until this chunk's validated
                # metadata proves whether it is the same avatar source.
                self._revoke_idle(t)
                # This is an inactivity guard, not a maximum reply duration.
                # Only a validated new chunk or forward playback progress renews it.
                t.deadline = self.now()+90
                t.sequence, t.current, t.source, t.metadata = sequence, 0, None, None
                t.audio, t.digest, t.duration = dict(audio), digest, duration
                t.claimed_at = self.now()
                t.state = 'claimed'
                t.rows = [{'index': i, 'startFrame': start, 'frameCount': count, 'state': 'pending'}
                          for i, (start, count) in enumerate(segment_ranges(count, 12))]
                if t.muxed_audio:
                    self._capture_muxed_wav(t, t, body)
                self._notify_ready()
            if current_index >= len(t.rows):
                raise ValueError('Segment outside audio')
            # Old HTTP requests cannot move the admission window backward.
            if current_index > t.current:
                t.deadline = self.now()+90
            t.current = max(t.current, current_index)
            if t.current > 0 and t.anticipation:
                self._retire_anticipation(t)
            for row in t.rows[:t.current]:
                if row['state'] == 'ready':
                    self._media_path(t, row['index']).unlink(missing_ok=True)
                row.update(state='unavailable')
                row.pop('uri', None); row.pop('bytes', None)
            return self._status(t)

    def prefetch(self, trial_id, audio):
        if not isinstance(audio, dict) or set(audio) != {'id', 'phone_request_id', 'url_path'}:
            raise ValueError('Invalid audio identity')
        if any(not isinstance(audio[k], str) or not SAFE.fullmatch(audio[k]) for k in ('id','phone_request_id')):
            raise ValueError('Invalid audio identity')
        if audio['url_path'] != '/api/audio/file/'+audio['id']:
            raise ValueError('Invalid audio URL')
        with self.lock:
            t = self._get(trial_id)
            if t.state == 'unavailable' or not t.audio:
                raise ValueError('Active chunk unavailable')
            # A delayed network retry after promotion is a read-only poll of the
            # now-active chunk. It must never recreate or demote a successor.
            if audio == t.audio:
                return self._status(t)
            if t.pending:
                if audio != t.pending.audio:
                    raise ValueError('Only one successor may be prefetched')
                return self._pending_status(t)
            matches = [item for item in self.reader.audio()
                       if all(item.get(k) == v for k,v in audio.items())]
            if len(matches) != 1:
                raise ValueError('Phone audio is unavailable')
            sequence = matches[0].get('sequence_index')
            if (type(sequence) is not int or sequence != t.sequence+1
                    or audio['phone_request_id'] != t.audio['phone_request_id']):
                raise ValueError('Only the immediate successor of the same reply is allowed')
            body = self.reader.get(audio['url_path'])
            digest, duration = wav_identity(body)
            count = math.floor(duration*24)
            if not 1 <= count <= 720:
                raise ValueError('Unsupported duration')
            if t.muxed_audio:
                self._muxed_sample_count(body, count)
            rows = [{'index': i, 'startFrame': start, 'frameCount': size, 'state': 'pending'}
                    for i, (start, size) in enumerate(segment_ranges(count, 12))]
            t.pending = PendingChunk(dict(audio), sequence, secrets.token_hex(16), digest,
                                     duration, self.now(), rows)
            if t.muxed_audio:
                self._capture_muxed_wav(t, t.pending, body)
            # Keep the active four-clip window and up to three successor clips
            # ready, so the phone's lookahead can cross a speech-chunk boundary.
            return self._pending_status(t)

    def _status(self, t):
        result = {'trialId': t.id, 'mediaId': t.media_id, 'state': t.state, 'audio': dict(t.audio) if t.audio else None,
                'loopFadeMs': t.loop_fade_ms,
                'sourceState': 'matched' if t.source else 'awaiting_identity', 'failureStage': t.failure_stage,
                'durationSeconds': t.duration, 'frameCount': sum(r['frameCount'] for r in t.rows),
                'segments': [dict(row) for row in t.rows]}
        if t.muxed_audio:
            result['muxedAudio'] = True
            result['muxedSamples'] = t.muxed_samples
        if t.idle_source_id and ((t.audio is None and t.warm_idle == t.idle_source)
                                 or (t.metadata and t.metadata['idleFrameDir'] == t.idle_source)):
            result['idleSourceId'] = t.idle_source_id
            result['motionId'] = self._motion_id(t.idle_source)
        if t.idle:
            result['idle'] = dict(t.idle['descriptor'])
        elif t.idle_unavailable:
            result['idleUnavailable'] = True
        if t.anticipation:
            result['anticipation'] = self._anticipation_status(t)
        self._include_source_timeline(result, t.metadata)
        self._include_chunk_return(t, result, t)
        self._trace_plan_publication(t, result)
        return result

    @staticmethod
    def _trace_plan_publication(t, result):
        for field, condition in (('anticipation', 'anticipation_present'), ('sourceTimeline', 'timeline_present'),
                                 ('idleChunkReturn', 'return_plan_present')):
            _plan_diagnostics.observe(t.id, 'backend.plan.publish', condition, True, field in result)

    def _pending_status(self, t):
        pending = t.pending
        if pending is None:
            return self._status(t)
        result = {'trialId': t.id, 'mediaId': pending.media_id, 'state': pending.state,
                'audio': dict(pending.audio),
                'sourceState': 'matched' if pending.source else 'awaiting_identity',
                'failureStage': t.failure_stage, 'durationSeconds': pending.duration,
                'frameCount': sum(r['frameCount'] for r in pending.rows),
                'segments': [dict(row) for row in pending.rows]}
        if t.muxed_audio:
            result['muxedAudio'] = True
            result['muxedSamples'] = pending.muxed_samples
        if t.chunked_idle:
            result['loopFadeMs'] = t.loop_fade_ms
        if pending.idle_source_id:
            result['idleSourceId'] = pending.idle_source_id
            result['motionId'] = self._motion_id(pending.idle_source)
        self._include_source_timeline(result, pending.metadata)
        self._include_chunk_return(t, result, pending)
        self._trace_plan_publication(t, result)
        return result

    def _include_chunk_return(self, t, result, context):
        """Visual-only capability, bound to the validated final speech mapping."""
        metadata, timeline = context.metadata, result.get('sourceTimeline')
        if not t.chunked_idle or not context.audio or not metadata or not metadata['final'] or not timeline:
            return
        avatar = metadata['avatarId']
        if not isinstance(avatar, str) or not 0 < len(avatar) <= 256:
            return
        key = (context.media_id, context.digest, metadata['idleFrameDir'],
               timeline['motionId'], timeline['sourceFrameCount'], tuple(timeline['sourceIndices']))
        entry = next((entry for entry in t.idle_chunk_sources.values() if entry['key'] == key), None)
        if entry is None:
            if len(t.idle_chunk_sources) >= MAX_SOURCE_IDENTITIES:
                return  # Optional visual capacity cannot reject valid audio.
            source_id = secrets.token_hex(16)
            descriptor = {'version': 1, 'sourceId': source_id, 'mediaId': context.media_id,
                'audio': dict(context.audio), 'motionId': timeline['motionId'], 'avatarId': avatar,
                'sourceFrameCount': timeline['sourceFrameCount'], 'fps': FPS,
                'startFrame': (timeline['sourceIndices'][-1]+1) % timeline['sourceFrameCount'],
                'continuationReady': True, 'videoQuality': dict(t.video_quality)}
            entry = {'key': key, 'descriptor': descriptor, 'source': metadata['idleFrameDir'],
                     'quality': dict(t.video_quality), 'sequence': context.sequence}
            t.idle_chunk_sources[source_id] = entry
        result['idleChunkReturn'] = {**entry['descriptor'], 'audio': dict(entry['descriptor']['audio']),
                                    'videoQuality': dict(entry['descriptor']['videoQuality'])}

    @staticmethod
    def _include_source_timeline(result, metadata):
        from .relay.frame_handoff import validate_timeline
        if not metadata or 'sourceTimeline' not in metadata:
            return
        try:
            timeline = validate_timeline(metadata['sourceTimeline'])
            count = result['frameCount']
            if (timeline['motionId'] != result.get('motionId')
                    or not 0 < count <= len(timeline['sourceIndices'])):
                return
            timeline['sourceIndices'] = timeline['sourceIndices'][:count]
            result['sourceTimeline'] = timeline
        except ValueError:
            pass

    @staticmethod
    def _motion_id(source):
        # Visual equivalence only, never a media/read capability. Trial-scoped
        # random media IDs must still rotate, without triggering a mood fade.
        return hashlib.sha256(str(source).encode()).hexdigest() if source else ''

    def status(self, trial_id):
        with self.lock:
            return self._status(self._get(trial_id))

    def idle_chunks(self, body):
        """Opt-in control for complete idle files; independent of audio admission."""
        base = {'trialId', 'requestId', 'startFrame'}
        waiting_keys = {'waitingPlanId','waitingFirstIndex'}
        if (not isinstance(body, dict) or set(body) not in (base, base | {'purpose', 'sourceId'},base | waiting_keys)
                or not isinstance(body['requestId'], str) or not re.fullmatch(r'[a-f0-9]{32}', body['requestId'])
                or type(body['startFrame']) is not int or not 0 <= body['startFrame'] < 1440):
            raise ValueError('Invalid idle chunk request')
        waiting = 'waitingPlanId' in body
        if waiting and (not isinstance(body['waitingPlanId'],str) or not re.fullmatch('[a-f0-9]{32}',body['waitingPlanId'])
                or type(body['waitingFirstIndex']) is not int or not 0 <= body['waitingFirstIndex'] <= 10000):
            raise ValueError('Invalid idle waiting request')
        with self.lock:
            t = self._get(body['trialId'])
            if not t.chunked_idle:
                raise ValueError('Idle chunk mode not selected')
            returning = 'purpose' in body
            lane = t.idle_chunk_return if returning else t
            other = t if returning else t.idle_chunk_return
            source = t.warm_idle if t.audio is not None and t.warm_idle else t.idle_source
            quality, source_count, source_id = t.video_quality, None, None
            source_order = None
            if returning:
                source_id = body['sourceId']
                if (body['purpose'] != 'return' or not isinstance(source_id, str)
                        or not re.fullmatch(r'[a-f0-9]{32}', source_id) or source_id not in t.idle_chunk_sources):
                    raise ValueError('Idle return source unavailable')
                entry = t.idle_chunk_sources[source_id]
                if body['startFrame'] != entry['descriptor']['startFrame']:
                    raise ValueError('Idle return source frame changed')
                source, quality = entry['source'], entry['quality']
                source_count = entry['descriptor']['sourceFrameCount']
                source_order = entry['sequence']
                prior = lane.idle_chunk_request
                if prior and (source_order < prior['sourceOrder'] or
                        source_order == prior['sourceOrder'] and source_id != prior['sourceId']):
                    # A source capability may have been published before a
                    # delayed request arrives. Request-ID tombstones alone do
                    # not fence an older, previously unseen speech return.
                    raise ValueError('Idle return source order changed')
            if (body['requestId'] in lane.retired_idle_chunk_requests
                    or body['requestId'] in other.retired_idle_chunk_requests
                    or other.idle_chunk_request and body['requestId'] == other.idle_chunk_request['id']):
                raise ValueError('Idle chunk request retired')
            request = lane.idle_chunk_request
            if waiting and (not t.muxed_audio or not request or request['id'] != body['requestId']):
                raise ValueError('Idle waiting owner changed')
            if request and request['id'] == body['requestId']:
                if request['start'] != body['startFrame'] or request.get('sourceId') != source_id:
                    raise ValueError('Idle request identity changed')
            else:
                if sum(len(item.retired_idle_chunk_requests)+(1 if item.idle_chunk_request else 0)
                       for item in (t, t.idle_chunk_return)) >= 64:
                    raise ValueError('Idle chunk request capacity reached')
                if request:
                    lane.retired_idle_chunk_requests.add(request['id'])
                # Change identity before closing files so a late encoder cannot
                # publish against a replacement source/request.
                lane.idle_chunk_request = {'id': body['requestId'], 'start': body['startFrame'],
                    'source': source, 'version': t.idle_source_version, 'quality': dict(quality),
                    'sourceId': source_id, 'sourceFrameCount': source_count, 'sourceOrder': source_order}
                self._retire_idle_chunks(lane)
                lane.idle_chunk_unavailable = lane.idle_chunk_cleanup_failed
            if waiting:
                stream,plan=lane.idle_chunk_stream,t.anticipation
                if (not stream or not stream.muxed_audio or not plan or plan['state'] not in ('available','active')
                        or plan['planId'] != body['waitingPlanId'] or not plan['frames']
                        or stream.source.resolve() != Path(plan['frames'][0]).parent.resolve()):
                    raise ValueError('Desktop waiting plan unavailable')
                keys=('version','planId','avatarId','fps','sourceFrameCount','sourceIndices',
                      'speechEntryFrame','exitAfterFrame','repeat')
                authored={key:plan[key] for key in keys}
                if 'syncWaitSeconds' in plan: authored['syncWaitSeconds']=plan['syncWaitSeconds']
                if not stream.install_waiting_plan(authored,body['waitingFirstIndex']):
                    raise ValueError('Desktop waiting cut unavailable')
            result = {'trialId': t.id, 'requestId': body['requestId'],
                      'state': 'unavailable' if lane.idle_chunk_unavailable else 'pending'}
            if returning:
                result.update(purpose='return', sourceId=source_id)
            if lane.idle_chunk_stream:
                try:
                    result.update(lane.idle_chunk_stream.status(), state='ready')
                except (OSError, ValueError):
                    self._retire_idle_chunks(lane)
                    result['state'] = 'unavailable'
            return result

    @staticmethod
    def _retire_idle_chunks(t):
        t.idle_chunk_unavailable = True
        stream = t.idle_chunk_stream
        t.idle_chunk_stream = None
        if stream:
            try:
                stream.close()
            except OSError:
                # Closed stream cannot publish again. Final trial-root cleanup
                # owns any private output the OS temporarily refuses to remove.
                t.idle_chunk_cleanup_failed = True

    def idle_chunk_cursor(self, body):
        if not isinstance(body, dict) or set(body) != {'trialId', 'mediaId', 'cursor'}:
            raise ValueError('Invalid idle chunk cursor')
        with self.lock:
            t = self._get(body['trialId'])
            stream = next((lane.idle_chunk_stream for lane in (t, t.idle_chunk_return)
                if lane.idle_chunk_stream and lane.idle_chunk_stream.media_id == body['mediaId']), None)
            if not stream:
                raise ValueError('Idle chunk stream changed')
            stream.advance(body['cursor'])
            return {'ok': True, 'mediaId': stream.media_id, 'cursor': stream.status()['cursor']}

    def idle_chunk_bytes(self, media_id, index):
        with self.lock:
            t = self._get(self.trial.id) if self.trial else None
            stream = next((lane.idle_chunk_stream for lane in (t, t.idle_chunk_return)
                if lane.idle_chunk_stream and lane.idle_chunk_stream.media_id == media_id), None) if t else None
            if not stream:
                raise LookupError('Idle chunk stream unavailable')
            return stream.read(index)

    @staticmethod
    def _next_idle_chunk(t):
        """One existing optional encoder; alternate two finite publication windows."""
        lanes = (t, t.idle_chunk_return)
        for offset in range(2):
            index = (t.idle_chunk_turn+offset) % 2
            lane = lanes[index]
            request, stream = lane.idle_chunk_request, lane.idle_chunk_stream
            if (request and request['source'] is not None and not lane.idle_chunk_unavailable
                    and (stream is None or stream.has_pending)):
                t.idle_chunk_turn = (index+1) % 2
                return lane, request
        return None

    def _render_idle_chunk(self, t, request, lane=None):
        from .idle_chunk_stream import IdleChunkStream
        lane = lane or t
        def ended():
            return (self.closed or self.trial is not t or t.stop.is_set() or self.now() >= t.deadline
                    or lane.idle_chunk_unavailable or lane.idle_chunk_request is not request)
        if ended():
            return
        with self.lock:
            stream = lane.idle_chunk_stream
        if stream is None:
            # Full source validation and frame hashing stay off the control lock.
            stream = IdleChunkStream(request['source'], t.root,
                avatar_id=request['source'].parent.name, start_frame=request['start'],
                quality=request['quality'], cancelled=ended, muxed_audio=t.muxed_audio)
            expected_count = request.get('sourceFrameCount')
            if expected_count is not None and len(stream.frames) != expected_count:
                stream.close()
                raise ValueError('Idle return source frame count changed')
            with self.lock:
                if ended():
                    stream.close()
                    return
                lane.idle_chunk_stream = stream
        stream.render_next()

    def _anticipation_status(self, t):
        plan = t.anticipation
        result = {key: plan[key] for key in ('version', 'planId', 'avatarId', 'fps', 'sourceFrameCount',
                                               'sourceIndices', 'speechEntryFrame', 'exitAfterFrame', 'repeat')}
        if 'syncWaitSeconds' in plan:
            result['syncWaitSeconds'] = plan['syncWaitSeconds']
        result.update(cursor=plan['cursor'], state=plan['state'], mediaId=plan['mediaId'],
                      segments=[dict(row) for row in plan['segments']])
        if t.muxed_audio:
            result['muxedAudio'] = True
        return result

    def _retire_anticipation(self, t, state='ended'):
        plan = t.anticipation
        if not plan:
            return
        for row in plan['segments']:
            self._anticipation_path(t, plan['mediaId'], row['index']).unlink(missing_ok=True)
            row.update(state='unavailable' if state == 'unavailable' else 'ended')
            row.pop('uri', None); row.pop('bytes', None)
            for key in ('validSamples','delaySamples','paddingSamples','rawSamples','sampleRate'):
                row.pop(key, None)
        plan['state'] = state

    def _install_anticipation(self, t, metadata):
        raw = metadata.get('anticipation')
        def observe(condition, expected=True, actual=False):
            _plan_diagnostics.observe(t.id, 'backend.anticipation.install', condition, expected, actual,
                                      chunk_id=metadata.get('chunkId'))
        if raw is None:
            observe('metadata_missing')
            return
        if t.anticipation:
            observe('already_installed', True, True)
            return
        keys = {'version', 'planId', 'avatarId', 'fps', 'sourceFrameCount', 'sourceIndices',
                'speechEntryFrame', 'exitAfterFrame', 'repeat'}
        optional_keys = {'syncWaitSeconds'}
        if not isinstance(raw, dict) or set(raw) not in (keys, keys | optional_keys):
            observe('metadata_shape'); return
        if raw['version'] != 1:
            observe('version'); return
        if raw['fps'] != FPS:
            observe('fps'); return
        if raw['avatarId'] != metadata['avatarId']:
            observe('avatar_match'); return
        if not isinstance(raw['planId'], str) or not re.fullmatch(r'[0-9a-f]{32}', raw['planId']):
            observe('plan_id'); return
        if type(raw['sourceFrameCount']) is not int or not 1 <= raw['sourceFrameCount'] <= 1440:
            observe('frame_count'); return
        if not isinstance(raw['sourceIndices'], list) or not 1 <= len(raw['sourceIndices']) <= 1440:
            observe('indices_shape'); return
        if any(type(index) is not int or not 0 <= index < raw['sourceFrameCount'] for index in raw['sourceIndices']):
            observe('index_bounds'); return
        if ('syncWaitSeconds' in raw and (
                    isinstance(raw['syncWaitSeconds'], bool)
                    or not isinstance(raw['syncWaitSeconds'], (int, float))
                    or not math.isfinite(raw['syncWaitSeconds'])
                    or not 0.0 <= raw['syncWaitSeconds'] <= 2.5
                )):
            observe('sync_wait'); return
        if raw['speechEntryFrame'] != raw['sourceIndices'][0]:
            observe('entry_frame'); return
        if raw['exitAfterFrame'] != len(raw['sourceIndices'])-1:
            observe('exit_frame'); return
        if raw['repeat'] is not True:
            observe('repeat'); return
        try:
            frames = idle_frames(metadata['idleFrameDir'])
        except ValueError:
            observe('idle_frames_unavailable')
            return
        if len(frames) != raw['sourceFrameCount']:
            observe('idle_frame_count', raw['sourceFrameCount'], len(frames))
            return
        rows = [{'index': index, 'startFrame': start, 'frameCount': count, 'state': 'pending'}
                for index, (start, count) in enumerate(segment_ranges(len(raw['sourceIndices']), 12))]
        preserved_keys = keys | ({'syncWaitSeconds'} if 'syncWaitSeconds' in raw else set())
        t.anticipation = {**{key: (list(raw[key]) if key == 'sourceIndices' else raw[key]) for key in preserved_keys},
                          'cursor': None, 'state': 'available', 'mediaId': secrets.token_hex(16),
                          'frames': frames, 'segments': rows,
                          'quality': dict(t.video_quality) if t.video_quality else video_quality(load_quality(self.runtime/'runtime/main_chat_remote'))}
        observe('installed', True, True)

    def _set_anticipation_window(self, t):
        plan = t.anticipation
        count = len(plan['segments'])
        wanted = {plan['cursor'] % count, (plan['cursor'] + 1) % count}
        for row in plan['segments']:
            if row['index'] not in wanted:
                self._anticipation_path(t, plan['mediaId'], row['index']).unlink(missing_ok=True)
                row.update(state='pending'); row.pop('uri', None); row.pop('bytes', None)
                for key in ('validSamples','delaySamples','paddingSamples','rawSamples','sampleRate'):
                    row.pop(key, None)

    def anticipation_cursor(self, trial_id, audio, media_id, cursor):
        """Explicit opt-in cursor; it never changes speech admission or cursor state."""
        with self.lock:
            t = self._get(trial_id)
            if audio != t.audio or media_id != t.media_id:
                raise ValueError('Anticipation chunk identity is stale')
            plan = t.anticipation
            if not plan:
                return self._status(t)
            if cursor is None:
                if plan['state'] not in {'ended', 'unavailable'}:
                    self._retire_anticipation(t)
                return self._status(t)
            if type(cursor) is not int or not 0 <= cursor <= 10000:
                raise ValueError('Invalid anticipation cursor')
            if plan['state'] in {'ended', 'unavailable'}:
                return self._status(t)
            if plan['state'] == 'available':
                if cursor != 0 or t.sequence != 0 or t.current != 0:
                    raise ValueError('Anticipation may start only at the opening')
                plan['state'], plan['cursor'] = 'active', 0
                self._set_anticipation_window(t)
                # Reserve the bounded publication budget for anticipation plus speech opening.
                for row in t.rows[t.current+1:]:
                    self._media_path(t, row['index']).unlink(missing_ok=True)
                    row.update(state='pending'); row.pop('uri', None); row.pop('bytes', None)
                if t.pending:
                    for row in t.pending.rows:
                        if row['state'] == 'ready':
                            self._media_path(t, row['index'], t.pending.media_id).unlink(missing_ok=True)
                            row.update(state='pending'); row.pop('uri', None); row.pop('bytes', None)
            elif cursor > plan['cursor']:
                plan['cursor'] = cursor
                self._set_anticipation_window(t)
            return self._status(t)

    def _media_path(self, t, index, media_id=None):
        path = t.root/f'{media_id or t.media_id}-{index:08d}.mp4'
        path.resolve().relative_to(t.root)
        return path

    def _anticipation_path(self, t, media_id, index):
        path = t.root/f'anticipation-{media_id}-{index:08d}.mp4'
        path.resolve().relative_to(t.root)
        return path

    def anticipation_bytes(self, media_id, index):
        with self.lock:
            t = self._get(self.trial.id) if self.trial else None
            plan = t and t.anticipation
            if not plan or plan['mediaId'] != media_id or type(index) is not int or not 0 <= index < len(plan['segments']):
                raise LookupError('Anticipation media unavailable')
            row = plan['segments'][index]
            if row['state'] != 'ready':
                raise LookupError('Anticipation media unavailable')
            path = self._anticipation_path(t, media_id, index)
            body = path.read_bytes()
            if len(body) != row['bytes'] or len(body) > MAX_MEDIA:
                raise LookupError('Anticipation media changed')
            return body

    def _idle_path(self, t, media_id=None):
        path = t.root/'source-idle.mp4'
        path.resolve().relative_to(t.root)
        return path

    def _revoke_idle(self, t):
        # Revoke the old chunk URL, retaining at most one reusable source cycle.
        t.idle = None
        t.idle_unavailable = False

    def segment_bytes(self, media_id, index):
        with self.lock:
            if not self.trial:
                raise LookupError('Retired chunk media')
            t = self._get(self.trial.id)
            if media_id == t.media_id:
                rows = t.rows
            elif t.pending and media_id == t.pending.media_id:
                rows = t.pending.rows
            else:
                raise LookupError('Retired chunk media')
            if type(index) is not int or not 0 <= index < len(rows) or rows[index]['state'] != 'ready':
                raise LookupError('Segment unavailable')
            path = self._media_path(t, index, media_id)
            if path.stat().st_size != rows[index]['bytes']:
                raise LookupError('Segment changed')
            with path.open('rb') as handle:
                body = handle.read(MAX_MEDIA+1)
            if len(body) != rows[index]['bytes'] or len(body) > MAX_MEDIA:
                raise LookupError('Invalid segment size')
            return body

    def idle_bytes(self, media_id):
        with self.lock:
            retained = self.retained_idle
            if retained and retained['mediaId'] == media_id:
                return retained['body']
            if not self.trial:
                raise LookupError('Retired idle media')
            t = self._get(self.trial.id)
            if not t.idle or t.idle['mediaId'] != media_id:
                raise LookupError('Idle media unavailable')
            path = self._idle_path(t, media_id)
            if path.stat().st_size != t.idle['descriptor']['bytes']:
                raise LookupError('Idle media changed')
            body = path.read_bytes()
            if len(body) != t.idle['descriptor']['bytes'] or len(body) > MAX_MEDIA:
                raise LookupError('Invalid idle media')
            return body

    def cancel(self, trial_id, idle_media_id=_UNSET, *, arm_request_id=None):
        with self.lock:
            self._validate_arm_request(arm_request_id)
            if arm_request_id is not None:
                self._prune_cancelled_arms()
                # Keep room for the current arm even if unrelated cleanup arrives first.
                reserve_current = (self.trial and self.trial.arm_request_id
                    and self.trial.arm_request_id not in self.cancelled_arms
                    and self.trial.arm_request_id != arm_request_id)
                limit = 63 if reserve_current else 64
                if arm_request_id not in self.cancelled_arms and len(self.cancelled_arms) >= limit:
                    raise ValueError('Arm cancellation history full')
                self.cancelled_arms[arm_request_id] = self.now()+300
            matches = self.trial and (self.trial.id == trial_id if arm_request_id is None else
                self.trial.arm_request_id == arm_request_id and (trial_id is None or self.trial.id == trial_id))
            if matches:
                t = self.trial
                retain_current = idle_media_id is _UNSET
                if idle_media_id is not _UNSET:
                    if (self.retained_idle
                            and self.retained_idle['mediaId'] == idle_media_id):
                        retain_current = False
                    elif t.idle and t.idle['mediaId'] == idle_media_id:
                        retain_current = True
                if retain_current and t.idle:
                    try:
                        descriptor = t.idle['descriptor']
                        path = self._idle_path(t)
                        size = descriptor['bytes']
                        if type(size) is int and 0 < size <= MAX_MEDIA and path.stat().st_size == size:
                            body = path.read_bytes()
                            if len(body) == size:
                                self.retained_idle = {'mediaId': t.idle['mediaId'], 'body': body}
                    except (KeyError, OSError, ValueError):
                        pass
                self.trial.stop.set()
                self._notify_ready()
            if arm_request_id is not None:
                logging.getLogger(__name__).info('arm_cleanup matched=%s before_ack=%s', bool(matches), trial_id is None)

    def close(self):
        with self.lock:
            self.closed = True
            self.retained_idle = None
            t = self.trial
            if t:
                t.stop.set()
                self._notify_ready()
        if t and t.thread:
            t.thread.join(timeout=25)

    @staticmethod
    def _metadata_key(context, source):
        return (id(context), context.media_id, context.digest, context.duration, id(context.rows), source)

    def _metadata_snapshots(self, t):
        # Filesystem/timeline validation must not stall encoder cancellation,
        # publication or authenticated control requests sharing this lock.
        with self.lock:
            sources = {}
            for context in (t, t.pending):
                if context is None or not context.audio:
                    continue
                matches = [value for value in t.candidates.values() if value[0] == context.digest]
                if len(matches) == 1 and matches[0][1] == context.duration:
                    source = matches[0][2]
                    sources[self._metadata_key(context, source)] = (context, context.rows, source)
        results = {}
        for key, (context, rows, source) in sources.items():
            try:
                result = load_delivery_metadata(source, self.renders, self.runtime)
            except Exception as error:
                # Apply failures only if the same identity still owns this
                # result; Stop/promotion during IO must not fail its successor.
                result = error
            # Keep the actual owners alive too, preventing object-id reuse
            # while another thread promotes/replaces a context during IO.
            results[key] = (context, rows, result)
        return results

    def _source_metadata(self, context, source, snapshots):
        if snapshots is _UNSET:
            return load_delivery_metadata(source, self.renders, self.runtime)
        snapshot = snapshots.get(self._metadata_key(context, source), _UNSET)
        if snapshot is _UNSET or snapshot[0] is not context or snapshot[1] is not context.rows:
            raise FileNotFoundError('Metadata identity not yet observed')
        result = snapshot[2]
        if isinstance(result, Exception):
            raise result
        return result

    def _sources(self, t, metadata_snapshots=_UNSET):
        for path in self.staged.glob('*.wav'):
            if path.name in t.old_staged or path.name in t.candidates:
                continue
            try:
                resolved = path.resolve(strict=True)
                # On Windows, deletion during resolve can leave an extended-path
                # prefix. Recheck the resolved target before containment so normal
                # adapter cleanup takes the FileNotFoundError path below.
                resolved.stat()
                resolved.relative_to(self.staged)
                source = (self.renders/path.stem).resolve()
                source.relative_to(self.renders)
                # Overlap/transition preprocessing WAVs have no render directory
                # of their own. They cannot match a delivered frame source.
                if not source.is_dir():
                    continue
                before = signature(path)
                if before[0] > MAX_MEDIA:
                    raise ValueError('Source audio exceeds size cap')
                if len(t.candidates) >= MAX_SOURCE_IDENTITIES:
                    raise ValueError('Source identity cap exceeded')
                with path.open('rb') as handle:
                    body = handle.read(MAX_MEDIA+1)
                if len(body) > MAX_MEDIA or signature(path) != before:
                    continue
            except FileNotFoundError:
                # The adapter deletes staging WAVs immediately after rendering.
                # A normal listing/stat race must not retire the entire reply.
                continue
            try:
                digest, duration = wav_identity(body)
            except ValueError:
                continue
            t.candidates[path.name] = (digest, duration, source)
        if t.audio:
            matches = [value for value in t.candidates.values() if value[0] == t.digest]
            if len(matches) > 1:
                raise ValueError('Ambiguous render identity')
            if len(matches) == 1:
                if matches[0][1] != t.duration:
                    raise ValueError('Render duration mismatch')
                try:
                    metadata = self._source_metadata(t, matches[0][2], metadata_snapshots)
                except FileNotFoundError:
                    return  # Staging/overlap estimation precedes metadata; retry within the trial deadline.
                if metadata['final'] and metadata['frameCount'] < sum(row['frameCount'] for row in t.rows):
                    raise ValueError('Delivery metadata frame count is too short')
                changed = t.source != matches[0][2] or t.metadata != metadata
                t.source, t.metadata = matches[0][2], metadata
                self._set_idle_source(t, metadata['idleFrameDir'])
                self._use_idle_cache(t)
                self._install_anticipation(t, metadata)
                if (t.anticipation and metadata['final']
                        and metadata['sourceStartIndex'] % t.anticipation['sourceFrameCount']
                        != t.anticipation['speechEntryFrame']):
                    # sourceStartIndex already follows desktop-visible semantics;
                    # do not apply trim again when checking the planned join.
                    self._retire_anticipation(t, 'unavailable')
                if changed:
                    self._notify_ready()

        if t.pending:
            matches = [value for value in t.candidates.values() if value[0] == t.pending.digest]
            if len(matches) > 1:
                raise ValueError('Ambiguous render identity')
            if len(matches) == 1:
                if matches[0][1] != t.pending.duration:
                    raise ValueError('Render duration mismatch')
                try:
                    metadata = self._source_metadata(t.pending, matches[0][2], metadata_snapshots)
                except FileNotFoundError:
                    return
                if metadata['final'] and metadata['frameCount'] < sum(row['frameCount'] for row in t.pending.rows):
                    raise ValueError('Delivery metadata frame count is too short')
                t.pending.source, t.pending.metadata = matches[0][2], metadata
                source = metadata['idleFrameDir']
                t.pending.idle_source = source
                t.pending.idle_source_id = (t.idle_source_id if source == t.idle_source and t.idle_source_id
                                            else secrets.token_hex(16))

    def _encode_anticipation(self, t, row):
        with self.lock:
            plan = t.anticipation
            if not plan or plan['state'] != 'active' or row not in plan['segments'] or row['state'] != 'pending':
                return
            media_id, frames = plan['mediaId'], list(plan['frames'])
        paths, bodies, signatures = [], [], []
        selected = plan['sourceIndices'][row['startFrame']:row['startFrame']+row['frameCount']]
        for index in selected:
            path = frames[index]
            try:
                before = signature(path); body = path.read_bytes()
                if not 0 < before[0] <= 8*1024*1024 or signature(path) != before or not complete_png(body):
                    return
            except FileNotFoundError:
                return
            paths.append(path); bodies.append(body); signatures.append(before)
        def cancelled():
            with self.lock:
                return (t.stop.is_set() or self.now() >= t.deadline or t.anticipation is not plan
                        or plan['state'] != 'active' or t.current != 0 or t.sequence != 0
                        or row['index'] not in {plan['cursor'] % len(plan['segments']), (plan['cursor']+1) % len(plan['segments'])})
        with tempfile.TemporaryDirectory(prefix='anticipation-', dir=t.root) as private:
            private = Path(private).resolve(); private.relative_to(t.root)
            for index, body in enumerate(bodies):
                (private/f'{index:08d}.png').write_bytes(body)
            if any(signature(path) != before for path, before in zip(paths, signatures)):
                return
            encoded = encode_range(self.ffmpeg, private/'%08d.png', self._anticipation_path(t, media_id, row['index']),
                                   0, len(bodies), cancelled=cancelled, quality=plan['quality'])
            sample_metadata = None
            if encoded is not None and t.muxed_audio:
                from .muxed_trial_encoding import MuxedTrialSilence
                # Only silence is encoded here. Speech keeps its single,
                # authenticated continuous AAC parent. Short planned tails
                # retain their real duration and never acquire extra frames.
                silent = MuxedTrialSilence(self.ffmpeg, private/'silent', cancelled=cancelled)
                sample_metadata = silent.segment(encoded, row['index'], frame_count=len(bodies))
                muxed = silent.encoder.root/sample_metadata['file']
                if cancelled():
                    encoded.unlink(missing_ok=True); return
                encoded.unlink()
                muxed.rename(encoded)
        if encoded is None:
            return
        with self.lock:
            if cancelled():
                encoded.unlink(missing_ok=True); return
            size = encoded.stat().st_size
            existing = [r for r in t.rows if r['state'] == 'ready']
            if t.pending:
                existing += [r for r in t.pending.rows if r['state'] == 'ready']
            existing += [r for r in plan['segments'] if r['state'] == 'ready']
            if len(existing) >= 3 or sum(r['bytes'] for r in existing)+size > 128*1024*1024:
                encoded.unlink(missing_ok=True); return
            row.update(state='ready', uri=f'/api/dev/musetalk-live/anticipation/{media_id}/{row["index"]:08d}.mp4', bytes=size)
            if sample_metadata is not None:
                row.update(sampleRate=48000, **{key: sample_metadata[key] for key in
                           ('validSamples','delaySamples','paddingSamples','rawSamples')})

    @staticmethod
    def _muxed_sample_count(body, frames):
        """Reject unsupported PCM before changing the live reply identity."""
        if len(body) > 8*1024*1024:
            raise ValueError('Source audio exceeds size cap')
        with wave.open(io.BytesIO(body), 'rb') as source:
            rate = source.getframerate()
            if rate not in (24000, 48000) or source.getnchannels()!=1 or source.getsampwidth()!=2:
                raise ValueError('Unsupported muxed source PCM')
            samples = source.getnframes()*(48000//rate)
        if abs(samples-frames*2000)>=2000:
            raise ValueError('Muxed source duration mismatch')
        return samples

    def _capture_muxed_wav(self, t, context, body):
        """Retain only the WAV already authenticated by prepare/prefetch."""
        samples = self._muxed_sample_count(body, sum(row['frameCount'] for row in context.rows))
        path = t.root/f'muxed-source-{context.media_id}.wav'
        with path.open('xb') as handle:
            handle.write(body)
        context.muxed_wav, context.muxed_samples, context.muxed_encoder = path, samples, None

    @staticmethod
    def _retire_muxed_source(t):
        if t.muxed_audio and t.muxed_wav is not None:
            t.retired_muxed_ids.add(t.media_id)

    def _cleanup_muxed_sources(self, t):
        # Called only with no speech encoder in flight. A replaced context can
        # still be referenced by its cancelled job until that future settles.
        from .idle_loop_catalog import _confined
        with self.lock:
            active={t.media_id,t.pending.media_id if t.pending else ''}
            retired=set(t.retired_muxed_ids)-active
        root=_confined(t.root,[self.output])
        for media_id in retired:
            if not re.fullmatch(r'[a-f0-9]{32}',media_id):
                raise ValueError('Invalid retired muxed context')
            directory=root/f'muxed-{media_id}'
            if directory.exists():
                directory=_confined(directory,[root])
                for path in [directory/'continuous.m4a',*directory.glob('clip-*.mp4')]:
                    try:
                        target=_confined(path,[directory])
                    except FileNotFoundError:
                        continue
                    target.unlink(missing_ok=True)
                directory.rmdir()  # Unknown contents are never recursively removed.
            wav=root/f'muxed-source-{media_id}.wav'
            if wav.exists():
                _confined(wav,[root]).unlink(missing_ok=True)
            with self.lock:
                t.retired_muxed_ids.discard(media_id)

    def _encode(self, t, row, pending=None):
        index = row['index']
        with self.lock:
            context = pending or t
            if (pending is not None and t.pending is not pending) or not any(row is active for active in context.rows) or not context.source:
                return
            source, media_id, claimed_at = context.source, context.media_id, context.claimed_at
            trim = context.metadata['trimStartFrames']
            muxed_wav, muxed_samples, muxed_encoder = context.muxed_wav, context.muxed_samples, context.muxed_encoder
            muxed_frames = sum(item['frameCount'] for item in context.rows) if t.muxed_audio else 0
        paths = [source/f'{i:08d}.png' for i in range(row['startFrame']+trim, row['startFrame']+trim+row['frameCount'])]
        frames, signatures = [], []
        for path in paths:
            try:
                path.resolve(strict=True).relative_to(source)
                sig = signature(path)
                # Like desktop's _frame_ready, an empty PNG is still being
                # written. Keep this range pending for the next producer poll.
                if sig[0] == 0:
                    return
                if sig[0] > 8*1024*1024:
                    raise ValueError('Frame exceeds cap')
                body = path.read_bytes()
                if signature(path) != sig or not complete_png(body):
                    return
            except FileNotFoundError:
                return
            frames.append(body); signatures.append(sig)
        def cancelled():
            with self.lock:
                if t.stop.is_set() or t.state == 'unavailable' or self.now() >= t.deadline:
                    return True
                # Once opt-in anticipation is active, its current/next ranges and
                # this chunk's opening are the complete three-slot window. An
                # already-running lookahead (including a prefetched successor)
                # must not publish after the reservation takes effect.
                if t.anticipation and t.anticipation['state'] == 'active':
                    return pending is not None or index > t.current
                if pending is not None:
                    return t.pending is not pending or pending.media_id != media_id
                return t.media_id != media_id or t.current > index
        if cancelled():
            return
        ready_at = self.now()
        with tempfile.TemporaryDirectory(prefix='input-', dir=t.root) as private:
            private = Path(private).resolve(); private.relative_to(t.root)
            for i, body in enumerate(frames):
                (private/f'{i:08d}.png').write_bytes(body)
            if any(signature(path) != sig for path, sig in zip(paths, signatures)):
                raise ValueError('Source changed during snapshot')
            frames.clear()
            video_output = private/'video.mp4' if t.muxed_audio else self._media_path(t, index, media_id)
            _plan_diagnostics.observe(t.id, 'backend.encode.video', 'range_start_frame',
                                      None, row['startFrame'], chunk_id=f'{media_id}:{index}')
            _plan_diagnostics.observe(t.id, 'backend.encode.video', 'range_frame_count',
                                      None, row['frameCount'], chunk_id=f'{media_id}:{index}')
            with _plan_diagnostics.operation(t.id, 'backend.encode.video', chunk_id=f'{media_id}:{index}'):
                encoded = encode_range(self.ffmpeg, private/'%08d.png', video_output,
                                       0, row['frameCount'], cancelled=cancelled, quality=t.video_quality)
            _plan_diagnostics.observe(t.id, 'backend.encode.video', 'encoded_file_returned',
                                      True, encoded is not None, chunk_id=f'{media_id}:{index}')
            muxed = None
            if encoded is not None and t.muxed_audio and not cancelled():
                from .muxed_trial_encoding import MuxedTrialEncoder
                try:
                    if muxed_encoder is None:
                        with _plan_diagnostics.operation(t.id, 'backend.encode.audio', chunk_id=media_id):
                            muxed_encoder = MuxedTrialEncoder(self.ffmpeg, muxed_wav,
                                t.root/f'muxed-{media_id}', valid_samples=muxed_samples,
                                frame_count=muxed_frames, cancelled=cancelled)
                        with self.lock:
                            if cancelled():
                                return
                            context.muxed_encoder = muxed_encoder
                    # Each call has its own current admission fence; do not retain
                    # the opening segment's cursor closure for later ranges.
                    muxed_encoder.cancelled = cancelled
                    segment = (muxed_encoder.rematerialize if row['startFrame'] < muxed_encoder.next_frame
                               else muxed_encoder.segment)
                    with _plan_diagnostics.operation(t.id, 'backend.encode.mux_range', chunk_id=f'{media_id}:{index}'):
                        muxed = segment(encoded, row['startFrame'], row['frameCount'])
                except InterruptedError:
                    if cancelled():
                        return  # Ordinary retired work, not a failed source.
                    raise
                encoded = muxed_encoder.root/muxed['file']
                encoded.rename(self._media_path(t, index, media_id))
                encoded = self._media_path(t, index, media_id)
        if encoded is None:
            return
        with self.lock:
            if cancelled():
                encoded.unlink(missing_ok=True)
                return
            size = encoded.stat().st_size
            existing = [r for r in t.rows if r['state'] == 'ready']
            if t.pending:
                existing += [r for r in t.pending.rows if r['state'] == 'ready']
            if t.anticipation and t.anticipation['state'] == 'active':
                existing += [r for r in t.anticipation['segments'] if r['state'] == 'ready']
            # Anticipation keeps its original three-slot window. Normal speech
            # retains four active ranges plus at most three successor ranges.
            publication_limit = (3 if t.anticipation and t.anticipation['state'] == 'active'
                                 else SPEECH_WINDOW + (SUCCESSOR_WINDOW if t.pending else 0))
            if len(existing) >= publication_limit or sum(r['bytes'] for r in existing)+size > 128*1024*1024:
                encoded.unlink(missing_ok=True)
                if t.anticipation and t.anticipation['state'] == 'active':
                    return
                raise ValueError('Published media cap exceeded')
            row.update(state='ready', uri=f'/api/dev/musetalk-live/segment/{media_id}/{index:08d}.mp4', bytes=size,
                       sourceReadyAfterClaimMs=round((ready_at-claimed_at)*1000, 3),
                       encodeMs=round((self.now()-ready_at)*1000, 3),
                       publishedAfterClaimMs=round((self.now()-claimed_at)*1000, 3))
            if muxed:
                row.update(sampleRate=48000, **{key:muxed[key] for key in
                    ('validSamples','delaySamples','paddingSamples','rawSamples')})
            context.state = 'streaming'
            self._notify_ready()

    def _use_idle_cache(self, t):
        cache, metadata = t.idle_cache, t.metadata
        source = metadata['idleFrameDir'] if metadata else t.warm_idle
        if not cache or not source or source != t.idle_source or cache['source'] != source:
            return
        if any(signature(path) != before for path,before in zip(cache['frames'],cache['signatures'])):
            t.idle_cache = None
            return
        if t.audio is None:
            # Armed source idle has no speech timeline; publish a fresh opaque URL.
            if not t.idle:
                t.media_id = secrets.token_hex(16)
            start = t.warm_start % cache['frameCount']
            continuation_ready = True
        elif metadata and metadata['final']:
            delivered = math.floor(t.duration*FPS)
            timeline = metadata.get('sourceTimeline')
            if (timeline and timeline['motionId'] == self._motion_id(source)
                    and timeline['sourceFrameCount'] == cache['frameCount']
                    and 0 < delivered <= len(timeline['sourceIndices'])):
                # Match desktop's next-cycle-picture rule after the actual
                # rendered mapping, including trimmed or reversing sequences.
                start = (timeline['sourceIndices'][delivered-1] + 1) % cache['frameCount']
            else:
                start = (metadata['sourceStartIndex'] + delivered) % cache['frameCount']
            continuation_ready = True
        else:
            start = t.idle['descriptor']['startFrame'] if t.idle else 0
            continuation_ready = False
        t.idle = {'mediaId':t.idle_source_id,'descriptor':{
            'motionId':self._motion_id(source),
            'mediaId':t.idle_source_id,'uri':f'/api/dev/musetalk-live/idle/{t.idle_source_id}.mp4','bytes':cache['bytes'],
            'avatarId':metadata['avatarId'] if metadata else source.parent.name,
            'frameCount':cache['frameCount'],'fps':FPS,'startFrame':start,'continuationReady':continuation_ready}}

    def _encode_idle(self, t, expected_source=None, expected_version=None):
        with self.lock:
            source = t.metadata['idleFrameDir'] if t.metadata else t.warm_idle
            if (expected_source is not None and (t.idle_source != expected_source
                                                or t.idle_source_version != expected_version)):
                return
            if t.chunked_idle or not source or t.idle or (t.idle_cache and t.idle_cache['source'] == source):
                return
            source_id = t.idle_source_id
            source_version = t.idle_source_version
            # A different avatar may replace the one cached cycle only after its
            # descriptor is revoked. Never accumulate clips across emotions.
            t.idle_cache = None
            self._idle_path(t).unlink(missing_ok=True)
        frames = idle_frames(source)
        signatures = [signature(frame) for frame in frames]
        def cancelled():
            with self.lock:
                return (t.stop.is_set() or t.state == 'unavailable' or self.now() >= t.deadline
                        or t.idle_source != source or t.idle_source_id != source_id or t.idle is not None
                        or t.idle_source_version != source_version)
        encoded = encode_idle_cycle(self.ffmpeg, frames, self._idle_path(t), cancelled=cancelled, quality=t.video_quality)
        if encoded is None:
            return
        if cancelled():
            encoded.unlink(missing_ok=True)
            return
        if any(signature(frame) != before for frame, before in zip(frames, signatures)):
            encoded.unlink(missing_ok=True)
            raise ValueError('Idle source changed during encode')
        with self.lock:
            if cancelled():
                encoded.unlink(missing_ok=True)
                return
            size = encoded.stat().st_size
            frame_count = len(frames)
            t.idle_cache = {'source':source,'mediaId':source_id,'frames':frames,'signatures':signatures,
                            'bytes':size,'frameCount':frame_count}
            self._use_idle_cache(t)

    def _run(self, t):
        next_identity_check = 0
        next_idle_refresh = 0
        speech_encoder = ThreadPoolExecutor(max_workers=1, thread_name_prefix='nc-dev-live-encode')
        idle_encoder = ThreadPoolExecutor(max_workers=1, thread_name_prefix='nc-dev-live-idle')
        speech_encoding = None
        speech_job = None
        idle_encoding = None
        stage = 'source_scan'
        try:
            while not t.stop.is_set() and self.now() < t.deadline:
                if speech_encoding is not None and speech_encoding.done():
                    stage = 'encode'
                    speech_encoding.result()  # Surface failures; never leave a failed job pending.
                    speech_encoding = None
                    speech_job = None
                if speech_encoding is None and t.retired_muxed_ids:
                    self._cleanup_muxed_sources(t)
                if idle_encoding is not None and idle_encoding.done():
                    stage = 'idle_encode'
                    idle_encoding.result()  # Surface failures; never leave a failed job pending.
                    idle_encoding = None
                if self.now() >= next_identity_check:
                    stage = 'bridge_check'
                    self.reader.audio()  # Reader checks current bridge credentials before every GET.
                    next_identity_check = self.now()+.5
                refresh_state = None
                if t.audio is None and self.now() >= next_idle_refresh:
                    stage = 'idle_refresh'
                    try:
                        # This is local HTTP and may block; never hold the producer
                        # lock across it because prepare/cancel are audio-admission paths.
                        refresh_state = json.loads(self.reader.get('/api/state'))['state']
                    except Exception:
                        pass
                with self.lock:
                    if (refresh_state is not None and self.trial is t and not t.stop.is_set()
                            and t.audio is None and self.now() < t.deadline):
                        self._refresh_armed_idle(t, refresh_state)
                        t.loop_fade_ms = self._loop_fade(refresh_state)
                    if refresh_state is not None or self.now() >= next_idle_refresh:
                        next_idle_refresh = self.now()+1
                stage = 'source_scan'
                metadata_snapshots = self._metadata_snapshots(t)
                with self.lock:
                    if t.stop.is_set():
                        break
                    self._sources(t, metadata_snapshots)
                    # Keep observing short-lived staged WAVs while the one encoder
                    # works. No queued encodes: re-evaluate the current window
                    # after each completion so stale work cannot build up.
                    anticipating = bool(t.anticipation and t.anticipation['state'] == 'active')
                    active_limit = 1 if anticipating else SPEECH_WINDOW
                    rows = [(row, None) for row in t.rows[t.current:t.current+active_limit]
                             if row['state'] == 'pending'] if t.source else []
                    if not rows and not anticipating and t.pending and t.pending.source:
                        rows = [(row, t.pending) for row in t.pending.rows[:SUCCESSOR_WINDOW]
                                if row['state'] == 'pending']
                    if speech_encoding is None and rows:
                        row, pending = rows[0]
                        speech_job = {'sequenceIndex': (pending or t).sequence, 'segmentIndex': row['index'],
                                      'startFrame': row['startFrame'], 'frameCount': row['frameCount'],
                                      'prefetched': pending is not None}
                        speech_encoding = speech_encoder.submit(_plan_diagnostics.bind_operation(t.id,'backend.producer.speech_job',self._encode), t, rows[0][0], rows[0][1])
                    active_speech_ready = (t.audio is None or (t.source and t.current < len(t.rows)
                                           and t.rows[t.current]['state'] == 'ready'))
                    anticipation_rows = []
                    if t.anticipation and t.anticipation['state'] == 'active':
                        plan = t.anticipation
                        range_count = len(plan['segments'])
                        anticipation_rows = [plan['segments'][index] for index in
                                             (plan['cursor'] % range_count, (plan['cursor'] + 1) % range_count)
                                             if plan['segments'][index]['state'] == 'pending']
                    # Only submitted jobs consume the fairness turn. A pending
                    # anticipation range cannot preempt and erase a lane turn.
                    idle_chunk_job = self._next_idle_chunk(t) if (t.chunked_idle
                        and idle_encoding is None and not anticipation_rows) else None
                    if idle_encoding is None and anticipation_rows:
                        plan = t.anticipation
                        row = anticipation_rows[0]
                        def optional_anticipation(expected=plan):
                            try:
                                self._encode_anticipation(t, row)
                            except Exception:
                                # This lane is optional: an anticipation-video failure
                                # must never retire the independently valid speech reply.
                                with self.lock:
                                    if self.trial is t and t.anticipation is expected:
                                        self._retire_anticipation(t, 'unavailable')
                        idle_encoding = idle_encoder.submit(_plan_diagnostics.bind_operation(t.id,'backend.producer.anticipation_job',optional_anticipation))
                    elif idle_encoding is None and idle_chunk_job:
                        lane, request = idle_chunk_job
                        def optional_idle_chunk(expected=request, owner=lane):
                            try:
                                self._render_idle_chunk(t, expected, owner)
                            except Exception as error:
                                # An optional visual lane cannot reject independently
                                # authenticated audio or bypass a playback receipt.
                                with self.lock:
                                    if self.trial is t and owner.idle_chunk_request is expected and not t.stop.is_set():
                                        # Keep optional failure isolated, but make its
                                        # bounded category/location inspectable. Never
                                        # include source paths, owner IDs or raw text.
                                        try:
                                            detail = _failure_diagnostic(error)
                                            detail.update(stage='idle_chunk', lane='initial' if owner is t else 'return')
                                            logging.getLogger(__name__).warning('idle_chunk_failure %s', json.dumps(detail, separators=(',', ':')))
                                        except Exception:
                                            pass
                                        self._retire_idle_chunks(owner)
                        idle_encoding = idle_encoder.submit(_plan_diagnostics.bind_operation(t.id,'backend.producer.idle_chunk_job',optional_idle_chunk))
                    elif (idle_encoding is None and active_speech_ready and (t.metadata or t.warm_idle)
                          and not t.chunked_idle and not t.idle and not t.idle_unavailable
                          and (not t.idle_cache or t.idle_cache['source'] !=
                               (t.metadata['idleFrameDir'] if t.metadata else t.warm_idle))):
                        # One optional idle job may run beside the ordered speech lane.
                        # It never queues, and source/version/stop fences in _encode_idle
                        # discard it if the current source is no longer valid.
                        idle_source = t.idle_source
                        idle_source_version = t.idle_source_version
                        def optional_idle(source=idle_source, source_version=idle_source_version):
                            try:
                                self._encode_idle(t, expected_source=source, expected_version=source_version)
                            except Exception:
                                with self.lock:
                                    if (self.trial is t and not t.stop.is_set() and t.state != 'unavailable'
                                            and t.idle_source == source
                                            and t.idle_source_version == source_version):
                                        t.idle_unavailable = True
                        idle_encoding = idle_encoder.submit(_plan_diagnostics.bind_operation(t.id,'backend.producer.idle_job',optional_idle))
                t.stop.wait(.03)
        except Exception as error:
            with self.lock:
                t.state = 'unavailable'
                t.failure_stage = stage  # Bounded stage only; no paths, credentials or exception text.
                for row in t.rows:
                    row.update(state='unavailable')
                    row.pop('uri', None); row.pop('bytes', None)
                self._revoke_idle(t)
                if t.pending:
                    t.pending.state = 'unavailable'
                    for row in t.pending.rows:
                        row.update(state='unavailable')
                        row.pop('uri', None); row.pop('bytes', None)
                self._notify_ready()
            # Diagnostics cannot interfere with failure/cancellation cleanup.
            try:
                detail = _failure_diagnostic(error)
                detail.update(stage=stage, trialId=t.id, sequenceIndex=t.sequence,
                              currentIndex=t.current, job=speech_job if stage == 'encode' else None)
                if stage == 'source_scan':
                    detail.update(sourceCandidateCount=len(t.candidates),
                                  sourceCandidateLimit=MAX_SOURCE_IDENTITIES)
                logging.getLogger(__name__).warning('producer_failure %s', json.dumps(detail, separators=(',', ':')))
            except Exception:
                pass
            # Leave the error state readable, but stop creating work.
            t.stop.wait(max(0, min(90, t.deadline-self.now())))
        finally:
            # Attribute availability loss before cleanup sets the stop flag.
            # No capabilities, paths, chat content or exception text enter this event.
            try:
                with self.lock:
                    deadline_reached = self.now() >= t.deadline
                    reason = ('failed' if t.state == 'unavailable' else
                              'closed' if self.closed else
                              'replaced' if self.trial is not t else
                              'cancelled' if t.stop.is_set() else
                              'expired' if deadline_reached else 'ended')
                    detail = dict(reason=reason,
                                  trialHash=hashlib.sha256(t.id.encode()).hexdigest()[:16],
                                  deadlineReached=deadline_reached,
                                  idleInitial=t.idle_chunk_stream is not None,
                                  idleReturn=t.idle_chunk_return.idle_chunk_stream is not None,
                                  sequenceIndex=t.sequence, currentIndex=t.current)
                logging.getLogger(__name__).info('producer_ended %s',
                    json.dumps(detail, separators=(',', ':')))
            except Exception:
                pass  # Diagnostics must never interfere with real reader cleanup.
            t.stop.set()
            self._notify_ready()
            speech_encoder.shutdown(wait=True, cancel_futures=True)
            idle_encoder.shutdown(wait=True, cancel_futures=True)
            self._retire_idle_chunks(t)
            self._retire_idle_chunks(t.idle_chunk_return)
            # Only this freshly created trial directory can be removed.
            root = t.root.resolve(); root.relative_to(self.output)
            if root.parent == self.output and root.name.startswith('nc-live-trial-'):
                shutil.rmtree(root, ignore_errors=True)
