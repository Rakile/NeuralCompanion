"""Package phone-bound speech for download ahead of local playback.

Call on a media worker, never Qt or the network event loop. A completed file
means delivery is possible, not that anybody has heard the speech. Containers
must still pass the native player probe before being advertised to a phone.
"""
import os
from pathlib import Path
import tempfile

import av

from .opus_encoding import OpusSpeechEncoder, RATE, TIME_BASE


def encode_opus_file(frames, output, *, bitrate=32000, container,
                     cancelled=lambda: False):
    if container != 'ogg':
        raise ValueError('Unsupported Opus file container')
    target = Path(output)
    if target.exists():
        raise FileExistsError(target)

    def check_cancelled():
        if cancelled():
            raise RuntimeError('Opus file encoding cancelled')

    check_cancelled()
    descriptor, name = tempfile.mkstemp(prefix='.nc-opus-', suffix='.part', dir=target.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        with av.open(str(temporary), 'w', format=container) as media:
            stream = media.add_stream('libopus', rate=RATE)
            stream.time_base = TIME_BASE
            encoder = OpusSpeechEncoder(bitrate=bitrate, cancelled=cancelled,
                                        codec_context=stream.codec_context)

            def mux(packets):
                for packet in packets:
                    check_cancelled()
                    # The shared encoder normalizes timestamps for RTP. Files
                    # need the original negative lookahead and final duration
                    # so the demuxer can trim both encoder delay and padding.
                    packet.pts -= encoder.leading_samples
                    packet.dts -= encoder.leading_samples
                    packet.stream = stream
                    media.mux(packet)

            mux(encoder.encode_chunk(frames))
            check_cancelled()
            if not encoder.valid_samples:
                raise ValueError('Empty Opus source audio')
            mux(encoder.finish())
        check_cancelled()
        result = {'container': container, 'bytes': temporary.stat().st_size,
                  'sample_rate': RATE, 'valid_samples': encoder.valid_samples,
                  'leading_samples': encoder.leading_samples}
        # Publish complete bytes atomically without replacing another owner's
        # file, including a target created while we were encoding.
        os.link(temporary, target)
        return result
    finally:
        temporary.unlink(missing_ok=True)
