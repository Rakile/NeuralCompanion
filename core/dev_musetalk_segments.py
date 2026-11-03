"""Bounded segment encoding shared by phone delivery and the offline fixture CLI."""
from pathlib import Path
import json
import subprocess
import time

from core.phone_media_tools import hidden, inspect_video, tools

MAX_BYTES = 16 * 1024 * 1024

def segment_ranges(frame_count, frames_per_segment):
    if type(frame_count) is not int or not 1 <= frame_count <= 1440:
        raise ValueError('Invalid fixture frame count')
    if type(frames_per_segment) is not int or frames_per_segment not in (12, 24):
        raise ValueError('Segment size must be 12 or 24 frames')
    return [(n, min(frames_per_segment, frame_count - n))
            for n in range(0, frame_count, frames_per_segment)]

def encode_range(ffmpeg, pattern, output, start, count, *, cancelled=lambda: False, quality=None, encoder='libx264'):
    if cancelled():
        return None
    if encoder not in ('libx264','h264_nvenc'):
        raise ValueError('Invalid segment encoder')
    if type(start) is not int or type(count) is not int or not 0 <= start < 1440 or not 1 <= count <= 24 or start + count > 1440:
        raise ValueError('Invalid segment range')
    output = Path(output)
    partial = output.with_suffix('.partial.mp4')
    if output.exists() or partial.exists():
        raise FileExistsError('Refusing to overwrite an existing segment')
    _, ffprobe = tools()
    command = [ffmpeg, '-nostdin', '-v', 'error', '-n', '-framerate', '24',
               '-start_number', str(start), '-i', str(pattern), '-an', '-map', '0:v:0',
               '-vf', "scale=w='min(iw,448)':h='min(ih,672)':force_original_aspect_ratio=decrease:force_divisible_by=2:in_range=full:out_range=tv:out_color_matrix=bt601,setsar=1",
               '-frames:v', str(count), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
               '-threads', '2', '-pix_fmt', 'yuv420p', '-colorspace', 'smpte170m', '-color_range', 'tv',
               '-movflags', '+faststart', str(partial)]
    fps, encoded_count = 24, count
    if quality is not None:
        # The source timeline remains 24 fps. Select original ticks (0,3,6,...
        # at 8 fps) rather than relabeling compressed ordinals as source frames.
        if (not isinstance(quality, dict) or set(quality) != {'video_kbps','video_width','video_fps'}
                or any(type(v) is not int for v in quality.values())
                or not 100 <= quality['video_kbps'] <= 2000
                or not 160 <= quality['video_width'] <= 448 or quality['video_width'] % 2
                or quality['video_fps'] not in (6,8,12,24)):
            raise ValueError('Invalid segment quality')
        fps, width = quality['video_fps'], quality['video_width']
        step = 24//fps
        encoded_count = (count+step-1)//step
        filters = (f"trim=end_frame={count},select='not(mod(n,{step}))',setpts=N/({fps}*TB),"
                   f"scale=w='min(iw,{width})':h='min(ih,{width*3//2})':"
                   "force_original_aspect_ratio=decrease:force_divisible_by=2:"
                   "in_range=full:out_range=tv:out_color_matrix=bt601,setsar=1")
        command = [ffmpeg, '-nostdin','-v','error','-n','-framerate','24','-start_number',str(start),
                   '-i',str(pattern),'-an','-map','0:v:0','-vf',filters,'-r',str(fps),
                   '-frames:v',str(encoded_count),'-c:v','libx264','-preset','veryfast',
                   '-profile:v','baseline','-b:v',str(quality['video_kbps']*1000),
                   '-threads','2','-pix_fmt','yuv420p','-colorspace','smpte170m','-color_range','tv',
                   '-movflags','+faststart',str(partial)]
    if encoder=='h264_nvenc':
        if fps!=24:raise ValueError('NVENC ordered segments require 24 fps')
        command[command.index('-c:v')+1]='h264_nvenc'
        command[command.index('-preset')+1]='p4'
        thread=command.index('-threads');del command[thread:thread+2]
        if '-crf' in command:
            crf=command.index('-crf');del command[crf:crf+2]
            command[-1:-1]=['-rc','vbr','-cq','23','-b:v','0','-profile:v','baseline']
        command[-1:-1]=['-bf','0']
    process = None
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, **hidden())
        deadline = time.monotonic() + 30
        while process.poll() is None:
            if cancelled():
                return None
            if time.monotonic() >= deadline:
                raise TimeoutError('Segment encode exceeded 30 seconds')
            if partial.exists() and partial.stat().st_size > MAX_BYTES:
                raise ValueError('Segment exceeds size cap')
            time.sleep(0.01)
        if process.returncode:
            raise RuntimeError('ordered_gpu_encode_failed' if encoder=='h264_nvenc' else 'Segment encode failed')
        if cancelled():
            return None
        if not 0 < partial.stat().st_size <= MAX_BYTES:
            raise ValueError('Invalid encoded size')
        info = inspect_video(ffprobe, partial)
        streams = info['streams']
        if (len(streams) != 1 or streams[0]['codec_type'] != 'video'
                or streams[0]['codec_name'] != 'h264' or streams[0]['r_frame_rate'] != f'{fps}/1'
                or int(streams[0]['nb_frames']) != encoded_count):
            raise ValueError('Encoded segment does not match its exact range')
        if cancelled():
            return None
        # Windows rename refuses an existing destination (unlike replace).
        if output.exists():
            raise FileExistsError('Segment appeared during encoding')
        partial.rename(output)
        return output
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        partial.unlink(missing_ok=True)




