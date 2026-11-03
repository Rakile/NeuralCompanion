"""Worker-only selected-avatar inventory; no paths or authority on the wire."""
from __future__ import annotations
from dataclasses import dataclass, field
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import time
from addons.musetalk_avatar.avatar_packs import (load_avatar_pack_manifest, build_implicit_avatar_pack,
    build_legacy_avatar_pack, build_standalone_avatar_pack)
from addons.musetalk_avatar.pack_runtime import enabled_pack_emotions
from .media_quality import video_quality

MAX_FILE = 16 * 1024 * 1024
MAX_CACHE = 128 * 1024 * 1024
SAFE = re.compile(r'[A-Za-z0-9_-]{1,128}')


@dataclass
class IdleCatalog:
    manifest: dict
    files: dict[str, Path]
    avatar_loops: dict[str, str] = field(default_factory=dict)
    # Private producer bindings. Identical encoded files may serve several
    # source paths; do not confuse content deduplication with motion identity.
    source_bindings: dict[str, dict] = field(default_factory=dict)


def _identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _check(cancelled):
    if cancelled():
        raise ValueError('Idle catalog cancelled')


def _confined(path, roots):
    """Reject symlink/junction ancestors as well as resolved path escapes."""
    raw = Path(os.path.abspath(path))
    root = next((r for r in roots if raw.is_relative_to(r)), None)
    if root is None:
        raise ValueError('unsafe_source')
    for part in (raw, *raw.parents):
        if part.exists() or part.is_symlink():
            stat = part.lstat()
            if part.is_symlink() or getattr(stat, 'st_file_attributes', 0) & 0x400:
                raise ValueError('unsafe_source')
        if part == root:
            break
    resolved = raw.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError('unsafe_source')
    return resolved


def _digest(path, cancelled):
    result = hashlib.sha256()
    with path.open('rb') as source:
        while chunk := source.read(256 * 1024):
            _check(cancelled)
            result.update(chunk)
    return result.hexdigest()


def _frames(source, roots, cancelled, *, frame_hashes=None):
    source = _confined(source, roots)
    frames = sorted(source.glob('*.png'))
    if not 1 <= len(frames) <= 1440:
        raise ValueError('frame_count')
    hashes = []
    for index, path in enumerate(frames):
        _check(cancelled)
        if path.name != f'{index:08d}.png' or not 0 < path.stat().st_size <= 8 * 1024 * 1024:
            raise ValueError('invalid_frames')
        _confined(path, roots)
        digest = _digest(path, cancelled)
        hashes.append(digest)
        if frame_hashes is not None:
            frame_hashes.append(digest)
    return frames, _identity(hashes)


def _inspect(path, cancelled):
    import av
    if not 0 < path.stat().st_size <= MAX_FILE:
        raise ValueError('file_limit')
    with av.open(str(path), options={'enable_drefs': '0'}) as clip:
        if len(clip.streams.video) != 1 or clip.streams.audio:
            raise ValueError('invalid_format')
        video = clip.streams.video[0]
        if (video.codec_context.name != 'h264' or not 0 < video.width <= 448
                or not 0 < video.height <= 672 or video.average_rate not in (6, 8, 12, 24)):
            raise ValueError('invalid_format')
        frames = 0
        for frame in clip.decode(video):
            _check(cancelled)
            frames += 1
            if frames > 1440 or (frame.width, frame.height) != (video.width, video.height):
                raise ValueError('invalid_frames')
        if frames == 0:
            raise ValueError('invalid_frames')
        return dict(sha256=_digest(path, cancelled), bytes=path.stat().st_size,
                    width=video.width, height=video.height, fps=int(video.average_rate), frames=frames)


def _encode_nvenc(frames, target, settings, cancelled):
    """Feed the complete numbered PNG sequence to one FFmpeg process."""
    from core.phone_media_tools import tools, hidden
    _check(cancelled)
    if not 1 <= len(frames) <= 1440:
        raise ValueError('frame_count')
    source = frames[0].parent
    expected = None
    for index, path in enumerate(frames):
        _check(cancelled)
        if path != source/f'{index:08d}.png':
            raise ValueError('invalid_frames')
        # Preserve dimension admission without creating a decoder/converter for
        # every PNG. FFmpeg validates/decompresses the actual image payloads.
        with path.open('rb') as image:
            header = image.read(24)
        if len(header)!=24 or header[:16]!=b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR':
            raise ValueError('invalid_frames')
        width,height = struct.unpack('>II',header[16:24])
        if not 0<width<=4096 or not 0<height<=4096 or width*height>4096*2160:
            raise ValueError('invalid_dimensions')
        scale = min(1,settings['video_width']/width,settings['video_width']*1.5/height)
        dimensions = max(2,int(width*scale)//2*2),max(2,int(height*scale)//2*2)
        if expected is not None and dimensions!=expected:
            raise ValueError('changing_dimensions')
        expected = dimensions
    try:
        ffmpeg,_ = tools()
    except RuntimeError as error:
        raise ValueError('gpu_encoder_unavailable') from error
    fd,raw = tempfile.mkstemp(prefix='idle-',suffix='.partial.mp4',dir=target.parent)
    os.close(fd)
    temporary = Path(raw)
    width,height = expected
    command = [ffmpeg,'-nostdin','-hide_banner','-v','error','-xerror','-y','-framerate','24',
        '-start_number','0','-i',str(source/'%08d.png'),'-an','-map','0:v:0',
        '-frames:v',str(len(frames)),'-vf',
        f'scale={width}:{height}:in_range=full:out_range=tv:out_color_matrix=bt601,setsar=1',
        '-r','24','-c:v','h264_nvenc','-preset','p4','-profile:v','baseline',
        '-b:v',str(settings['video_kbps']*1000),'-bf','0','-pix_fmt','yuv420p',
        '-colorspace','smpte170m','-color_range','tv','-movflags','+faststart',str(temporary)]
    process = None
    try:
        try:
            process = subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,**hidden())
        except OSError as error:
            raise ValueError('gpu_encoder_unavailable') from error
        deadline = time.monotonic()+120
        while process.poll() is None:
            _check(cancelled)
            if time.monotonic()>=deadline:
                raise ValueError('gpu_encode_timeout')
            if temporary.stat().st_size>MAX_FILE:
                raise ValueError('file_limit')
            time.sleep(.02)
        if process.returncode:
            raise ValueError('gpu_encode_failed')
        _check(cancelled)
        metadata = _inspect(temporary,cancelled)
        if (metadata['width'],metadata['height'],metadata['fps'],metadata['frames'])!=(width,height,24,len(frames)):
            raise ValueError('invalid_frames')
        _check(cancelled)
        os.replace(temporary,target)
        return metadata
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        temporary.unlink(missing_ok=True)


def _encode(frames, target, preset, cancelled, *, encoder='libx264'):
    import av
    settings = video_quality(preset)
    fps = settings['video_fps']
    if encoder not in ('libx264','h264_nvenc') or encoder=='h264_nvenc' and fps!=24:
        raise ValueError('Invalid idle encoder or GPU frame rate')
    if encoder=='h264_nvenc':
        return _encode_nvenc(frames,target,settings,cancelled)
    fd, raw = tempfile.mkstemp(prefix='idle-', suffix='.partial.mp4', dir=target.parent)
    os.close(fd)
    temporary = Path(raw)
    try:
        with av.open(str(temporary), 'w', format='mp4', options={'movflags': '+faststart'}) as output:
            stream = None
            for index, path in enumerate(frames[::24 // fps]):
                _check(cancelled)
                with av.open(str(path), format='image2', options={'enable_drefs': '0'}) as image:
                    frame = next(image.decode(video=0))
                if not 0 < frame.width <= 4096 or not 0 < frame.height <= 4096 or frame.width * frame.height > 4096 * 2160:
                    raise ValueError('invalid_dimensions')
                scale = min(1, settings['video_width'] / frame.width, settings['video_width'] * 1.5 / frame.height)
                width = max(2, int(frame.width * scale) // 2 * 2)
                height = max(2, int(frame.height * scale) // 2 * 2)
                if stream is None:
                    stream = output.add_stream('libx264', rate=fps)
                    stream.width, stream.height = width, height
                    stream.pix_fmt = 'yuv420p'
                    # Signal the existing BT.601 limited-range conversion in H.264/MP4.
                    stream.codec_context.colorspace = 6  # SMPTE170M / BT.601 matrix
                    stream.codec_context.color_range = 1  # MPEG / limited range
                    stream.bit_rate = settings['video_kbps'] * 1000
                    stream.codec_context.thread_count = 2
                    stream.options = {'preset':'veryfast','profile':'baseline'}
                if (width, height) != (stream.width, stream.height):
                    raise ValueError('changing_dimensions')
                # PNG is full-range RGB. Match the limited-range YUV conversion
                # used by the streamed segment encoder, not just its pixel format.
                frame = frame.reformat(width=width, height=height, format='yuv420p',
                                       src_color_range='JPEG', dst_color_range='MPEG', dst_colorspace='ITU601')
                # PNG decoding marks every image as I. Let x264 choose video
                # picture types instead of spending the whole budget on intra frames.
                frame.pict_type = av.video.frame.PictureType.NONE
                frame.pts = index
                frame.time_base = Fraction(1, fps)
                for packet in stream.encode(frame):
                    output.mux(packet)
                if temporary.stat().st_size > MAX_FILE:
                    raise ValueError('file_limit')
            for packet in stream.encode():
                output.mux(packet)
        metadata = _inspect(temporary, cancelled)
        _check(cancelled)
        os.replace(temporary, target)
        return metadata
    finally:
        temporary.unlink(missing_ok=True)


def _cached_metadata(target, cancelled):
    import av
    """A decodable replacement is not necessarily the content we encoded."""
    receipt = target.with_suffix('.sha256')
    try:
        _confined(target, [target.parent])
        _confined(receipt, [target.parent])
        if receipt.stat().st_size != 64:
            return None
        digest = receipt.read_text('ascii')
        metadata = _inspect(target, cancelled)
        return metadata if metadata['sha256'] == digest else None
    except (OSError, ValueError, UnicodeError, av.FFmpegError):
        _check(cancelled)
        return None


def _save_digest(target, digest):
    fd, name = tempfile.mkstemp(prefix='idle-', suffix='.partial.sha256', dir=target.parent)
    try:
        with os.fdopen(fd, 'w', encoding='ascii') as output:
            output.write(digest)
        os.replace(name, target.with_suffix('.sha256'))
    finally:
        Path(name).unlink(missing_ok=True)


def build_idle_catalog(runtime_config: dict, *, runtime_root, cache_root, cancelled,
                       preset='balanced', current_avatar=None, legacy_map=None, quality=None, encoder='libx264'):
    import av
    _check(cancelled)
    settings = video_quality(quality if quality is not None else preset)
    if encoder not in ('libx264','h264_nvenc') or encoder=='h264_nvenc' and settings['video_fps']!=24:
        raise ValueError('Invalid idle encoder or GPU frame rate')
    config = dict(runtime_config)
    raw_variants = {}
    root = Path(runtime_root).resolve(strict=True)
    roots = [root/'avatar_packs', root/'MuseTalk/results/v15/avatar_packs', root/'MuseTalk/results/v15/avatars']
    selected = str(config.get('musetalk_avatar_pack_id', ''))
    default = str(config.get('musetalk_avatar_id', 'default_avatar'))
    if not SAFE.fullmatch(default) or (selected and not SAFE.fullmatch(selected)):
        raise ValueError('Invalid selected avatar')
    if selected == 'legacy':
        pack = build_legacy_avatar_pack(default, legacy_map=legacy_map, avatars_dir=roots[2])
    elif not selected or selected == 'single__' + default:
        pack = build_standalone_avatar_pack(default, avatars_dir=roots[2])
    else:
        folder = next((r/selected for r in roots[:2] if (r/selected).is_dir()), None)
        if folder is None:
            raise ValueError('Selected avatar pack unavailable')
        _confined(folder, roots)
        manifest = folder/'manifest.json'
        if manifest.is_file():
            _confined(manifest, roots)
            if manifest.stat().st_size > 256 * 1024:
                raise ValueError('Invalid avatar manifest')
            # Check raw paths before the existing reader resolves away links.
            payload = json.loads(manifest.read_text('utf-8'))
            raw_variants = payload.get('variants', {})
            if not isinstance(raw_variants, dict) or not 1 <= len(raw_variants) <= 128:
                raise ValueError('Invalid avatar manifest')
            pack = load_avatar_pack_manifest(manifest, avatars_dir=roots[2])
        else:
            raw_variants = {}
            pack = build_implicit_avatar_pack(folder)
        if pack is None:
            raise ValueError('Selected avatar pack unavailable')
    if len(pack.variants) > 128:
        raise ValueError('Avatar inventory limit')
    destination = Path(cache_root).absolute()
    destination.mkdir(parents=True, exist_ok=True)
    _confined(destination, [destination])
    allowed = enabled_pack_emotions(config, pack.pack_id)
    rows, files, sources, active, total, avatar_loops = {}, {}, [], None, 0, {}
    source_bindings = {}
    for variant in pack.variants.values():
        _check(cancelled)
        tags = sorted(variant.normalized_tags())
        is_default = variant.avatar_id == pack.default_avatar_id
        if allowed is not None and not is_default:
            tags = [t for t in tags if t in allowed]
        include = is_default or allowed is None or bool(tags)
        if len(tags) > 128 or any(len(t) > 64 or '/' in t or '\\' in t for t in tags):
            raise ValueError('Invalid mood tags')
        unavailable_id = _identity([pack.pack_id, variant.variant_id])
        source_digest, created = 'unavailable', None
        try:
            if pack.source in {'manifest', 'implicit_pack'}:
                raw_variant = raw_variants.get(variant.variant_id, {})
                raw_path = str(raw_variant.get('avatar_path') or '')
                candidate = (folder / raw_path if raw_path else folder / variant.variant_id)
                if not raw_path and not candidate.exists():
                    candidate = folder / variant.avatar_id
                if raw_path or candidate.exists():
                    _confined(candidate, roots)
            source = Path(variant.avatar_path) if variant.avatar_path else roots[2]/variant.avatar_id
            frames, digest = _frames(source/'full_imgs', roots, cancelled)
            source_digest = digest
            if not include:
                sources.append([variant.avatar_id, source_digest])
                continue
            identity = _identity(['h264-mp4-nvenc-ffmpeg-v2' if encoder=='h264_nvenc' else 'h264-mp4-v4', digest, settings['video_kbps'],
                                  settings['video_width'], settings['video_fps']])
            if identity not in rows:
                target = destination/(identity+'.mp4')
                metadata = _cached_metadata(target, cancelled) if target.exists() else None
                if metadata is None:
                    created = target
                    metadata = (_encode(frames,target,settings,cancelled,encoder=encoder) if encoder=='h264_nvenc'
                                else _encode(frames,target,settings,cancelled))
                if _frames(source/'full_imgs', roots, cancelled)[1] != digest:
                    raise ValueError('source_changed')
                if total + metadata['bytes'] > MAX_CACHE:
                    raise ValueError('cache_capacity')
                _save_digest(target, metadata['sha256'])
                total += metadata['bytes']
                rows[identity] = dict(id=identity, tags=[], status='ready', **metadata)
                files[identity] = target
            rows[identity]['tags'] = sorted(set(rows[identity]['tags'] + tags))
            avatar_loops[variant.avatar_id] = identity
            source_bindings[variant.avatar_id] = {
                'motion_id': hashlib.sha256(str((source/'full_imgs').resolve()).encode()).hexdigest(),
                'source_frame_count': len(frames)}
            if variant.avatar_id == (current_avatar or pack.default_avatar_id):
                active = identity
        except (OSError, ValueError, av.FFmpegError, StopIteration) as error:
            if created is not None:
                # Only this job's newly generated cache file, never a source asset.
                created.unlink(missing_ok=True)
                created.with_suffix('.sha256').unlink(missing_ok=True)
            _check(cancelled)
            reason = str(error) if str(error) in {'unsafe_source','file_limit','frame_count','invalid_frames','source_changed','cache_capacity','gpu_encoder_unavailable','gpu_encode_failed','gpu_encode_timeout'} else 'source_unavailable'
            if include:
                rows[unavailable_id] = dict(id=unavailable_id, tags=tags, status='unavailable', reason=reason)
        sources.append([variant.avatar_id, source_digest])
    # The existing pack reader deliberately drops missing implicit paths when
    # local variants exist. Inventory must report them, not invent a fallback.
    for variant_id, row in raw_variants.items():
        if variant_id in pack.variants:
            continue
        if not SAFE.fullmatch(variant_id) or not isinstance(row, dict):
            raise ValueError('Invalid avatar variant')
        tags = row.get('tags', row.get('emotion_tags', []))
        if not isinstance(tags, list) or len(tags) > 128 or any(not isinstance(t, str) or len(t) > 64 or '/' in t or '\\' in t for t in tags):
            raise ValueError('Invalid mood tags')
        tags = sorted({t.strip().strip('[]').lower() for t in tags if t.strip()})
        sources.append([str(row.get('avatar_id') or variant_id), 'unavailable'])
        if allowed is not None:
            tags = [t for t in tags if t in allowed]
        if allowed is None or tags:
            identity = _identity([pack.pack_id, variant_id])
            rows[identity] = dict(id=identity, tags=tags, status='unavailable', reason='source_unavailable')
    generation = _identity([pack.pack_id, pack.default_avatar_id, sorted(sources)])
    loops = sorted(rows.values(), key=lambda row: row['id'])
    revision = _identity([generation, settings, loops])
    fade = config.get('musetalk_loop_fade_ms', 180)
    if type(fade) is not int or not 0 <= fade <= 5000:
        fade = 180
    return IdleCatalog(dict(version=1, generation=generation, avatar=_identity([pack.pack_id, pack.default_avatar_id]),
                            revision=revision, active_loop=active, fade_ms=fade, loops=loops,
                            video_quality=settings), files, avatar_loops, source_bindings)


def _worker_main():
    import sys
    try:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise ValueError('Idle input limit')
        request = json.loads(raw)
        if request.get('video_encoder')=='h264_nvenc':
            from .idle_encoder_process import contain_encoder_children
            _encoder_job = contain_encoder_children()  # Owned until this private process exits.
        result = build_idle_catalog(request['config'], runtime_root=request['runtime_root'],
            cache_root=request['cache_root'], cancelled=lambda:False, preset=request.get('preset','balanced'),
            current_avatar=request.get('current_avatar'), legacy_map=request.get('legacy_map'), quality=request.get('quality'),
            encoder=request.get('video_encoder','libx264'))
        # The parent rebuilds paths from allowlisted IDs; no path from this
        # private process output is trusted as a file destination.
        encoded = json.dumps({'manifest':result.manifest,'ids':list(result.files), 'avatar_loops':result.avatar_loops,
                              'source_bindings':result.source_bindings}).encode()
        if len(encoded) > 128*1024:
            raise ValueError('Idle inventory limit')
        sys.stdout.buffer.write(encoded)
    except Exception as error:
        reason = ('Idle encoder containment unavailable' if type(error) is ValueError
            and str(error)=='Idle encoder containment unavailable' else 'Idle inventory unavailable')
        sys.stderr.write(reason+'\n')
        raise SystemExit(1)


if __name__ == '__main__':
    _worker_main()
