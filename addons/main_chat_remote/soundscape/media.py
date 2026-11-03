"""Worker-only bounded stereo Opus conversion, separate from the speech encoder."""
from __future__ import annotations

from fractions import Fraction
import hashlib
import os
from pathlib import Path
import tempfile
import time
from typing import Callable

MAX_BYTES = 100 * 1024 * 1024
MAX_SECONDS = 30 * 60
BLOCK = 256 * 1024


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(BLOCK), b''):
            digest.update(block)
    return digest.hexdigest()


def convert_sound(source: Path, destination: Path, cancelled: Callable[[], bool] = lambda: False,
                  *, max_seconds: float = MAX_SECONDS, deadline_seconds: float = 300) -> dict:
    import av  # Optional runtime dependency, imported only on a conversion worker.
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    if source.is_symlink() or not source.is_file() or not 0 < source.stat().st_size <= MAX_BYTES:
        raise ValueError('Choose a regular audio file up to 100 MiB.')
    deadline = time.monotonic() + deadline_seconds

    def check():
        if cancelled():
            raise RuntimeError('Sound conversion cancelled.')
        if time.monotonic() > deadline:
            raise RuntimeError('Sound conversion timed out.')

    check()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.sound-', suffix='.part', dir=destination.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        # No playlists, network protocols, or arbitrary FFmpeg input URLs.
        with source.open('rb') as local, av.open(local, options={
                'format_whitelist': 'wav,flac,mp3,mov,ogg,aac', 'protocol_whitelist': 'file'}) as input_media:
            if not input_media.streams.audio:
                raise ValueError('The file contains no audio.')
            stream = input_media.streams.audio[0]
            channels = 1 if len(stream.codec_context.layout.channels) == 1 else 2
            layout = 'mono' if channels == 1 else 'stereo'
            rate = stream.codec_context.sample_rate
            if rate and not 8000 <= rate <= 384000:
                raise ValueError('Unsupported audio sample rate.')
            resampler = av.AudioResampler(format='flt', layout=layout, rate=48000)
            count = 0
            with av.open(str(temporary), 'w', format='ogg') as output:
                encoder = output.add_stream('libopus', rate=48000)
                encoder.layout = layout
                encoder.bit_rate = 64000 if channels == 1 else 96000
                encoder.time_base = Fraction(1, 48000)

                def encode(frame):
                    nonlocal count
                    check()
                    if count + frame.samples > max_seconds * 48000:
                        raise ValueError('Audio must be no longer than 30 minutes.')
                    frame.pts = count; frame.time_base = Fraction(1, 48000)
                    count += frame.samples
                    for packet in encoder.encode(frame):
                        check(); output.mux(packet)

                for frame in input_media.decode(stream):
                    check()
                    frame.pts = None
                    for converted in resampler.resample(frame): encode(converted)
                for converted in resampler.resample(None): encode(converted)
                if count == 0: raise ValueError('The audio is empty.')
                for packet in encoder.encode(None):
                    check(); output.mux(packet)
        check()
        size = temporary.stat().st_size
        if not 0 < size <= MAX_BYTES:
            raise ValueError('Encoded sound is too large.')
        result = {'sha256': file_hash(temporary), 'byte_length': size, 'duration_ms': round(count/48),
                  'channels': channels, 'sample_rate': 48000, 'content_type': 'audio/ogg',
                  'profile': 'opus48-mono64-v1' if channels == 1 else 'opus48-stereo96-v1'}
        check()
        os.link(temporary, destination)  # Atomic, no overwrite of another worker's completed file.
        return result
    except av.error.FFmpegError as exc:
        raise ValueError('The audio could not be decoded or converted.') from exc
    finally:
        temporary.unlink(missing_ok=True)
