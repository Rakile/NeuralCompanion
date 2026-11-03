"""Bounded RGB transition composition using the backend's existing FFmpeg.

Desktop supplies duration/order. This helper does not select frames, retime
speech, or require Desktop-only image packages in the minimal phone environment.
"""
from pathlib import Path
import struct
import subprocess
import time

from core.dev_musetalk_live_readiness import complete_png
from core.phone_media_tools import hidden


def _size(body):
    if (not 33 <= len(body) <= 8*1024*1024 or not complete_png(body)
            or body[8:16] != b'\x00\x00\x00\rIHDR'):
        raise ValueError('ordered_transition_image_size')
    width, height = struct.unpack_from('>II', body, 16)
    if not width or not height or width*height > 16*1024*1024:
        raise ValueError('ordered_transition_image_size')
    return width, height


def composite_range(ffmpeg, private, count, fade, *, cancelled):
    """Replace private snapshots only; return the actual composited final PNG.

One process per same-size range, not per frame. A size change is handled as a
new range without resetting fade time. All inputs/outputs remain private until
the normal encoder, validator and atomic Desktop publication accept the chunk.
"""
    origin, offset, duration = fade
    if (type(count) is not int or not 1 <= count <= 12
            or type(offset) is not int or not 0 <= offset <= 120
            or type(duration) is not int or not 1 <= duration <= 5000):
        raise ValueError('ordered_transition_range')
    old_width, old_height = _size(origin)
    private = Path(private)
    origin_file = private / 'transition-origin.png'
    origin_file.write_bytes(origin)
    output = private / 'composited'
    output.mkdir()
    sizes = [_size((private / f'{i:08d}.png').read_bytes()) for i in range(count)]
    start = 0
    while start < count and (offset+start)*1000 < 24*duration:
        if cancelled():
            raise InterruptedError('ordered_encode_cancelled')
        width, height = sizes[start]
        end = start+1
        while end < count and sizes[end] == sizes[start] and (offset+end)*1000 < 24*duration:
            end += 1
        ratio = min(width/old_width, height/old_height)
        fit_width, fit_height = max(1, round(old_width*ratio)), max(1, round(old_height*ratio))
        # Opacity depends only on frame number, not on pixel coordinates. The
        # generic all_expr path re-evaluates it for every colour component of
        # every pixel. Use the optimized normal blend and update its weight
        # AFTER each output frame, so framesync cannot apply future weights early.
        opacity = lambda frame: max(0.0, 1.0-frame*1000/(24*duration))
        commands = ';'.join(
            f'{(i*1000000//24)/1000000:.6f} blend@orderedfade all_opacity {opacity(offset+start+i+1):.12f}'
            for i in range(end-start-1))
        control = f"sendcmd=c='{commands}'," if commands else ''
        graph = (f'[0:v]scale={fit_width}:{fit_height}:flags=lanczos,format=gbrp,'
                 f'pad={width}:{height}:{(width-fit_width)//2}:{(height-fit_height)//2}[old];'
                 f'[1:v]format=gbrp[new];[old][new]blend@orderedfade=all_mode=normal:'
                 f'all_opacity={opacity(offset+start):.12f},{control}format=rgb24[out]')
        command = [str(ffmpeg), '-nostdin', '-v', 'error', '-n',
                   '-loop', '1', '-framerate', '24', '-i', str(origin_file),
                   '-framerate', '24', '-start_number', str(start), '-i', str(private/'%08d.png'),
                   '-filter_complex_threads', '1', '-filter_complex', graph, '-map', '[out]',
                   '-frames:v', str(end-start), '-threads', '1', '-start_number', str(start),
                   str(output/'%08d.png')]
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, **hidden())
        deadline = time.monotonic()+30
        paths = [output/f'{i:08d}.png' for i in range(start, end)]
        try:
            while process.poll() is None:
                if cancelled():
                    raise InterruptedError('ordered_encode_cancelled')
                if time.monotonic() >= deadline:
                    raise TimeoutError('ordered_transition_encode_timeout')
                if any(path.exists() and path.stat().st_size > 8*1024*1024 for path in paths):
                    raise ValueError('ordered_transition_image_size')
                time.sleep(.01)
            if cancelled():
                raise InterruptedError('ordered_encode_cancelled')
            if process.returncode:
                raise ValueError('ordered_transition_encode_failed')
            for path in paths:
                if not path.is_file() or not 0 < path.stat().st_size <= 8*1024*1024:
                    raise ValueError('ordered_transition_image_size')
                if _size(path.read_bytes()) != (width, height):
                    raise ValueError('ordered_transition_image_size')
            for path in paths:
                path.replace(private/path.name)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
        start = end
    return (private/f'{count-1:08d}.png').read_bytes()
