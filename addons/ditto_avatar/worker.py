"""Isolated Ditto JSON-lines worker. Protocol stdout is kept separate from native SDK logs."""
import argparse
import gc
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import traceback
import types
import uuid

from media_cache import (FPS, SCHEMA, numeric_pngs, deduplicate_frames, playback_indices,
                         prepare_options, save_features, load_features, model_signature, read_manifest,
                         legacy_model_signature)


class Worker:
    def __init__(self, repo, cache_root, emit):
        self.repo = Path(repo).resolve()
        self.cache_root = Path(cache_root).resolve()
        self.emit = emit
        self.sdk = None
        self.registrar = None
        self._crop_analyzer = None
        self.signature = None
        self.legacy_signature = None
        self.compatible_signatures = ()
        self.compatible_legacy_signatures = ()
        self.avatar = None
        self.sources = None
        self.active_render = None
        self.stream = None

    def load(self):
        if self.sdk is not None:
            return {'loaded': True, 'reused': True, 'fps': FPS}
        # Release face-only preview models before loading the complete SDK.
        self._crop_analyzer = None
        self.emit('progress', message='Loading Ditto models...')
        from stream_pipeline_offline import StreamSDK
        worker = self

        class PNGWriter:
            def __init__(self, unused_path):
                self.context = worker.active_render
                self.count = 0
                self.write_seconds = 0.0
                self.first_written = None
                self.last_written = None

            def __call__(self, frame, fmt='rgb'):
                from PIL import Image
                context = self.context
                if 'stream' in context:
                    context['stream'].write(frame)
                    self.count += 1
                    return
                index = self.count
                path = context['frame_dir'] / f'{index:08d}.png'
                temporary = path.with_suffix('.pending.png')
                writing = time.perf_counter()
                Image.fromarray(frame).save(temporary, compress_level=1)
                temporary.replace(path)
                self.write_seconds += time.perf_counter() - writing
                self.count += 1
                self.last_written = time.perf_counter()
                if self.first_written is None:
                    self.first_written = self.last_written
                worker.emit('frame', path=str(path), index=index, fps=FPS,
                            source_index=context['source_indices'][index])

            def close(self):
                pass

        # Inject a writer only into this SDK's setup function. No source edits or global patches.
        setup_globals = {**StreamSDK.setup.__globals__, 'VideoWriterByImageIO': PNGWriter}
        setup = types.FunctionType(StreamSDK.setup.__code__, setup_globals,
                                   StreamSDK.setup.__name__, StreamSDK.setup.__defaults__,
                                   StreamSDK.setup.__closure__)
        class PreparedSDK(StreamSDK):
            pass
        PreparedSDK.setup = setup
        self.sdk = PreparedSDK(str(self.repo / 'checkpoints/ditto_cfg/v0.4_hubert_cfg_pytorch.pkl'),
                               str(self.repo / 'checkpoints/ditto_pytorch'))
        from compositing import PreparedMaskCompositor
        self.sdk.putback = PreparedMaskCompositor(self.sdk.putback, roi_blend=True)
        self.registrar = self.sdk.avatar_registrar
        self.signature = self.legacy_signature = None
        self.cache_signature()
        # The upstream handler deep-copies setup_info; exclude image/feature arrays from that copy.
        original_setup = self.sdk.condition_handler.setup
        def condition_setup(info, emo, eye_f0_mode=False, ch_info=None):
            if ch_info is None:
                ch_info = {key: info[key] for key in
                           ('x_s_info_lst', 'sc', 'eye_open_lst', 'eye_ball_lst')}
            return original_setup(info, emo, eye_f0_mode=eye_f0_mode, ch_info=ch_info)
        self.sdk.condition_handler.setup = condition_setup
        return {'loaded': True, 'reused': False, 'fps': FPS}

    def unload(self):
        if self.stream is not None:
            self.stream_stop()
        if self.sources is not None:
            self.sources.close()
            self.sources = None
        self.sdk = self.registrar = self.avatar = self.active_render = None
        self._crop_analyzer = None
        self.signature = None
        self.legacy_signature = None
        self.compatible_signatures = ()
        self.compatible_legacy_signatures = ()
        gc.collect()
        if 'torch' in sys.modules:
            sys.modules['torch'].cuda.empty_cache()
        return {'loaded': False}

    def release_sources(self):
        # Worker requests are serialized; stop pipeline threads before closing
        # mapped arrays so Windows can replace/delete the prepared directory.
        self.stream_stop()
        if self.sources is not None:
            self.sources.close()
            self.sources = None
        self.avatar = self.active_render = None
        if self.sdk is not None:
            self.sdk.avatar_registrar = self.registrar
            self.sdk.source_info = None
            self.sdk.source_info_frames = 0
        return {'sources_released': True}

    def cache_signature(self):
        if self.signature is None:
            signatures = model_signature(self.repo, include_compatible=True)
            self.signature, self.compatible_signatures = signatures[0], signatures[1:]
        if self.legacy_signature is None:
            signatures = legacy_model_signature(self.repo, include_compatible=True)
            self.legacy_signature, self.compatible_legacy_signatures = signatures[0], signatures[1:]
        return dict(portable_signature=self.signature, legacy_signature=self.legacy_signature,
                    source_portable_signature=self.signature,
                    compatible_signatures=list(self.compatible_signatures),
                    compatible_legacy_signatures=list(self.compatible_legacy_signatures))

    def cached_source(self, root, frame_paths):
        from variant_sources import VariantSources
        if self.sources is None:
            self.sources = VariantSources(self)
        reused = str(Path(root).resolve()) in self.sources.entries
        key = self.sources.register(root)
        self.avatar = (root, self.sources.get(key))
        return self.avatar[1], reused

    def select_sources(self, avatar_paths):
        from variant_sources import VariantSources
        if self.sources is None:
            self.sources = VariantSources(self)
        self.avatar = None
        self.sources.retain(avatar_paths)
        keys = list(dict.fromkeys(self.sources.register(path) for path in avatar_paths))
        geometry = {tuple(self.sources.get(key)['memory_geometry']) for key in keys}
        if len(geometry) != 1:
            raise ValueError('Every enabled package avatar must have the same prepared canvas.')
        return keys

    def prewarm_variants(self, avatar_paths, settings=None):
        from copy import deepcopy
        from emotions import ChunkChoice, native_emotion
        from frame_timeline import ConditionTimeline
        self.stream_stop()
        self.load()
        keys = self.select_sources(avatar_paths)
        values = dict(settings or {})
        target = native_emotion(values.get('emotion')) or 'Neutral'
        for key in keys:
            timeline = ConditionTimeline(self.sources, sdk=self.sdk)
            timeline.append(0,1,ChunkChoice('prewarm',key,target,tuple(sorted(values.items()))))
            epoch = timeline.epochs[0]
            source = self.sources.get(key)
            xs,xd = epoch.stitch(deepcopy(epoch.motion[0]),deepcopy(epoch.motion[0]))
            features = self.sdk.warp_f3d(source['f_s_lst'][0],xs,xd)
            rendered = self.sdk.decode_f3d(features)
            self.sdk.putback(self.sources.image(key,0),rendered,source['M_c2o_lst'][0])
        return dict(ready=len(keys), variants=keys)

    def stream_begin(self, session_id, avatar_path, settings=None, start_index=0,
                     frame_transport=None, pixel_budget=None, variants=None, source_cursors=None):
        from continuous import ReplyPipeline
        self.stream_stop()
        self.load()
        self.select_sources([avatar_path, *(variants or [])])
        root, manifest, paths = read_manifest(avatar_path, self.signature, legacy_signature=self.legacy_signature,
            compatible_signatures=self.compatible_signatures,
            compatible_legacy_signatures=self.compatible_legacy_signatures)
        if type(start_index) is not int or start_index < 0:
            raise ValueError('start_index must be a nonnegative integer.')
        self.stream = ReplyPipeline(self, session_id, root, manifest, paths, settings or {}, start_index,
                                    frame_transport, pixel_budget, source_cursors)
        return {'session_id': session_id, 'started': True, 'prepared_cache_reused': self.stream.cache_reused,
                'renderer_batch': self.stream.renderer.batch_size if self.stream.renderer is not None else 1,
                **({'frame_pool': self.stream.pool.descriptor,
                    'chunk_pools': hasattr(self.stream.pool, 'reserve')} if self.stream.pool is not None else {})}

    def stream_reserve(self, session_id, chunk_id, frame_count):
        if self.stream is None or self.stream.session_id != session_id or self.stream.pool is None:
            raise ValueError('Ditto stream is no longer current.')
        return self.stream.pool.reserve(chunk_id, frame_count)

    def stream_release(self, session_id, slot, generation, chunk_id=None):
        if self.stream is not None and self.stream.session_id == session_id and self.stream.pool is not None:
            pool = self.stream.pool
            if hasattr(pool, 'reserve'):
                pool.release(slot, generation, chunk_id)
            else:
                pool.release(slot, generation)

    def stream_push(self, session_id, **payload):
        if self.stream is None or self.stream.session_id != session_id:
            raise ValueError('Ditto stream is no longer current.')
        if self.sdk.worker_exception:
            raise RuntimeError(str(self.sdk.worker_exception))
        return self.stream.push(**payload)

    def stream_flush(self, session_id):
        if self.stream is None or self.stream.session_id != session_id:
            raise ValueError('Ditto stream is no longer current.')
        if self.sdk.worker_exception:
            raise RuntimeError(str(self.sdk.worker_exception))
        return self.stream.request_motion_flush()

    def stream_stop(self, session_id=None):
        if self.stream is None or (session_id is not None and self.stream.session_id != session_id):
            return {'stopped': True}
        result = self.stream.stop()
        self.stream = None
        return result

    def crop_preview(self, source_path, prepare_options=None):
        from crop_preview import preview_crop
        return preview_crop(self, source_path, prepare_options)

    def prepare(self, source_path, output_dir='', prepare_options=None):
        import cv2
        import filetype
        import numpy as np
        options = globals()['prepare_options'](prepare_options)
        source = Path(source_path).expanduser().resolve()
        if not source.exists():
            raise ValueError(f'Source does not exist: {source}')
        paths, order, reader = None, None, None
        source_video_fps = None
        convert_video = False
        if source.is_dir():
            if options['sequence_fps'] != FPS:
                raise ValueError('PNG sequences must be sampled at 25 FPS before preparation.')
            sequence = numeric_pngs(source)
            if options['source_frames'] > 0:
                sequence = sequence[:options['source_frames']]
            paths, order = deduplicate_frames(sequence)
            # Existing MuseTalk packs often already contain forward + reverse files.
            if len(order) > 1 and len(order) % 2 == 0 and order == order[::-1]:
                options['loop_mode'] = 'forward'
            is_image = len(order) == 1
            frame_count = len(paths)
        elif filetype.is_image(str(source)):
            paths, order, is_image, frame_count = [source], [0], True, 1
        elif filetype.is_video(str(source)):
            reader = cv2.VideoCapture(str(source))
            fps = reader.get(cv2.CAP_PROP_FPS)
            if not reader.isOpened() or not math.isfinite(fps) or fps <= 0:
                reader.release()
                raise ValueError('Could not read source video frame rate.')
            source_video_fps = fps
            if abs(fps - FPS) > .01:
                if options['video_fps_policy'] == 'ask':
                    reader.release()
                    return {'needs_fps_choice': True, 'source_fps': fps, 'target_fps': FPS,
                            'playback_speed': FPS / fps}
                convert_video = options['video_fps_policy'] == 'convert'
            is_image = False
            frame_count = int(reader.get(cv2.CAP_PROP_FRAME_COUNT))
            if options['source_frames'] > 0:
                frame_count = min(frame_count, options['source_frames'])
            order = []
        else:
            raise ValueError('Source must be a still image, video, or numeric PNG directory.')
        destination = Path(output_dir).expanduser().resolve() if output_dir else self.cache_root / uuid.uuid4().hex
        if destination.exists():
            if reader:
                reader.release()
            raise ValueError(f'Avatar output already exists: {destination}')
        temporary = destination.with_name(destination.name + '.preparing-' + uuid.uuid4().hex)
        temporary.mkdir(parents=True)
        (temporary / 'frames').mkdir()
        try:
            if convert_video:
                reader.release()
                reader = None
                executable = self.repo / '.venv/Scripts/ffmpeg.exe'
                ffmpeg = str(executable) if executable.is_file() else shutil.which('ffmpeg')
                if not ffmpeg:
                    raise ValueError('FFmpeg was not found in the Ditto environment or PATH. Choose original frames or install FFmpeg there.')
                converted = temporary / 'converted'
                converted.mkdir()
                command = [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-n',
                           '-i', str(source), '-map', '0:v:0', '-an', '-vf', f'fps={FPS}']
                if options['source_frames'] > 0:
                    command += ['-frames:v', str(options['source_frames'])]
                command += ['-start_number', '0', '-compression_level', '2',
                            str(converted / '%08d.png')]
                self.emit('progress', message=f'Converting {source_video_fps:g} FPS video to 25 FPS with FFmpeg…')
                conversion = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                    text=True, encoding='utf-8', errors='replace',
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                if conversion.returncode:
                    raise RuntimeError('FFmpeg conversion failed: ' + conversion.stderr[-2000:])
                paths = numeric_pngs(converted)
                order = list(range(len(paths)))
                frame_count = len(paths)
            self.load()
            from crop_preview import fit_source_frame
            info = {key: [] for key in ('x_s_info_lst', 'f_s_lst', 'M_c2o_lst', 'eye_open_lst', 'eye_ball_lst')}
            last_landmarks = None
            index = 0
            crop = {key: value for key, value in options.items() if key.startswith('crop_')}
            while True:
                if reader:
                    if options['source_frames'] > 0 and index >= options['source_frames']:
                        break
                    ok, bgr = reader.read()
                    if not ok:
                        break
                    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                    order.append(index)
                elif index < len(paths):
                    bgr = cv2.imdecode(np.fromfile(paths[index], dtype=np.uint8), cv2.IMREAD_COLOR)
                    if bgr is None:
                        raise ValueError(f'Cannot decode {paths[index]}')
                    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                else:
                    break
                rgb = fit_source_frame(rgb, options)
                # Keep unique PNGs and unique features; tracked landmarks remain transient.
                result = self.registrar.source2info(rgb, last_landmarks, **crop)
                last_landmarks = result['lmk203']
                for key in info:
                    info[key].append(result[key[:-4]])
                from PIL import Image
                Image.fromarray(rgb).save(temporary / 'frames' / f'{index:08d}.png')
                index += 1
                self.emit('progress', message=f'Prepared frame {index}/{frame_count}',
                          current=index, total=frame_count)
            if not index:
                raise ValueError('No source frames were decoded.')
            info['sc'] = info['x_s_info_lst'][0]['kp'].flatten()
            info['is_image_flag'] = is_image
            save_features(temporary / 'features', info)
            manifest = {'schema_version': SCHEMA, 'fps': FPS, 'model_signature': self.signature,
                        'signature_kind': 'content-v1',
                        'prepare_options': options, 'source_path': str(source),
                        'source_order': order, 'unique_frame_count': index,
                        'frame_paths': [f'frames/{i:08d}.png' for i in range(index)],
                        'is_image': is_image, 'source_video_fps': source_video_fps}
            (temporary / 'avatar.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
            if convert_video:
                shutil.rmtree(temporary / 'converted')
            temporary.rename(destination)
            return {'avatar_path': str(destination), 'frame_count': index, 'fps': FPS,
                    'timeline_frames': len(order) * (2 if options['loop_mode'] == 'pingpong' and len(order) > 1 else 1),
                    'prepare_options': options}
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        finally:
            if reader:
                reader.release()

    def render(self, avatar_path, audio_path, output_dir, settings=None, start_index=0, frame_dir=None):
        self.stream_stop()
        started = time.perf_counter()
        import librosa
        import numpy as np
        from PIL import Image
        from gui_controls import make_kwargs, parse_seed
        from core.atomic_components.avatar_registrar import smooth_x_s_info_lst
        if not isinstance(start_index, int) or start_index < 0:
            raise ValueError('start_index must be a nonnegative integer.')
        self.cache_signature()
        root, manifest, frame_paths = read_manifest(avatar_path, self.signature, legacy_signature=self.legacy_signature,
            compatible_signatures=self.compatible_signatures,
            compatible_legacy_signatures=self.compatible_legacy_signatures)
        settings = {'conditioning': 'Source face', **(settings or {})}
        kwargs = make_kwargs(settings, is_video=not manifest['is_image'])
        setup, run = kwargs['setup_kwargs'], kwargs['run_kwargs']
        # Crops are a preparation-time property. The cached registrar ignores setup crop values.
        for key in ('delta_eye_arr', 'v_min_max_for_clip'):
            if isinstance(setup.get(key), list):
                setup[key] = np.asarray(setup[key], dtype=np.float32)
        seed = parse_seed(settings.get('seed', ''))
        audio, _ = librosa.load(str(audio_path), sr=16000)
        count = math.ceil(len(audio) / 16000 * FPS)
        if count < 1:
            raise ValueError('Audio is empty.')
        self.load()
        loaded_at = time.perf_counter()
        if seed is not None:
            from inference import seed_everything
            seed_everything(seed)
        output = Path(output_dir).expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)
        frame_dir = Path(frame_dir).resolve() if frame_dir else output / ('frames-' + uuid.uuid4().hex)
        if not frame_dir.is_relative_to(output):
            raise ValueError('Frame directory must be inside the render output directory.')
        frame_dir.mkdir()
        indices = playback_indices(manifest['source_order'], start_index, count,
                                   manifest['prepare_options']['loop_mode'])
        unique, cache_reused = self.cached_source(root, frame_paths)
        cached_at = time.perf_counter()
        motion = unique['x_s_info_lst']
        smoothing = setup.pop('smo_k_s', 13)
        if len(motion) > 1 and smoothing > 1:
            motion = smooth_x_s_info_lst(motion, smo_k=smoothing)
        # Expand lightweight references only for this audio chunk; stock mirror indices now
        # traverse 0..count-1 exactly once, and eye conditioning uses the same source order.
        ordered = {key: [value[i] for i in indices] for key, value in unique.items()
                   if key.endswith('_lst')}
        ordered['x_s_info_lst'] = [motion[i] for i in indices]
        ordered['sc'] = unique['sc']
        ordered['is_image_flag'] = unique['is_image_flag']
        self.sdk.avatar_registrar = lambda *args, **kw: ordered
        self.active_render = {'frame_dir': frame_dir, 'source_indices': indices}
        self.sdk.setup(str(root), str(output / 'unused'), smo_k_s=1, **setup)
        setup_at = time.perf_counter()
        self.sdk.setup_Nd(count, fade_in=run.get('fade_in', 0), fade_out=run.get('fade_out', 0),
                          ctrl_info=run.get('ctrl_info', {}))
        features = self.sdk.wav2feat.wav2feat(audio)
        audio_at = time.perf_counter()
        self.sdk.audio2motion_queue.put(features)
        self.sdk.close()
        if self.sdk.writer.count != count:
            raise RuntimeError(f'Expected {count} frames; generated {self.sdk.writer.count}.')
        cycle_length = len(manifest['source_order'])
        if manifest['prepare_options']['loop_mode'] == 'pingpong' and cycle_length > 1:
            cycle_length *= 2
        self.active_render = None
        return {'frame_dir': str(frame_dir), 'frame_count': count, 'fps': FPS,
                'duration_seconds': len(audio) / 16000, 'source_indices': indices,
                'source_frame_count': len(frame_paths), 'start_index': start_index,
                'prepared_cache_reused': cache_reused,
                'timing': {'load_audio_seconds': loaded_at-started, 'avatar_cache_seconds': cached_at-loaded_at,
                           'setup_seconds': setup_at-cached_at, 'audio_features_seconds': audio_at-setup_at,
                           'generate_write_seconds': time.perf_counter()-audio_at,
                           'png_write_seconds': getattr(self.sdk.writer, 'write_seconds', 0),
                           'frame_output_seconds': ((self.sdk.writer.last_written-self.sdk.writer.first_written)
                               if getattr(self.sdk.writer, 'first_written', None) is not None else 0),
                           'total_seconds': time.perf_counter()-started},
                'next_index': (start_index + count) % cycle_length}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', required=True)
    parser.add_argument('--cache-root', required=True)
    args = parser.parse_args()
    # Native extensions may write directly to fd 1. Keep a duplicate for protocol,
    # then route BOTH Python prints and native stdout to the parent's stderr pipe.
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), 'w', encoding='utf-8', buffering=1)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr
    lock = threading.Lock()
    current_id = None
    def emit(event, **data):
        with lock:
            protocol.write(json.dumps({'id': current_id, 'event': event, **data}, allow_nan=False) + '\n')
            protocol.flush()
    sys.path.insert(0, str(Path(args.repo).resolve()))
    os.chdir(args.repo)
    worker = Worker(args.repo, args.cache_root, emit)
    for line in sys.stdin:
        action = None
        try:
            request = json.loads(line)
            if request.get('action') == 'stream_release':
                worker.stream_release(request['session_id'], request['slot'], request['generation'], request.get('chunk_id'))
                continue
            current_id = request.pop('id')
            action = request.pop('action')
            if action not in ('load', 'prepare', 'render', 'unload', 'stream_begin', 'stream_reserve', 'stream_push', 'stream_flush', 'stream_stop', 'cache_signature', 'prewarm_variants', 'crop_preview', 'release_sources'):
                raise ValueError(f'Unknown worker action: {action}')
            emit('result', result=getattr(worker, action)(**request))
        except Exception as exc:
            traceback.print_exc()
            fatal = action in ('render', 'load', 'stream_begin', 'stream_push', 'stream_stop', 'release_sources')
            emit('error', message=str(exc), fatal=fatal)
            if fatal:
                # An upstream failure can leave non-daemon queue threads blocked. Exit the
                # entire worker rather than poisoning the warmed SDK for the next request.
                protocol.flush()
                os._exit(1)
    worker.unload()


if __name__ == '__main__':
    main()
