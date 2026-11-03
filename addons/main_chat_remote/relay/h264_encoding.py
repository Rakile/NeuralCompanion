"""Worker-owned low-delay avatar encoding; deliberately not wired to live peers.

The caller supplies an admitted 90 kHz presentation timeline and paces delivery.
This codec has no frame queue, auth policy, network I/O or playback acknowledgments.
"""
from fractions import Fraction

import av


TIME_BASE = Fraction(1, 90000)


class AvatarVideoEncoder:
    def __init__(self, *, cancelled=lambda: False, bitrate=500000, width=448, fps=24):
        if (type(bitrate) is not int or not 100000 <= bitrate <= 2000000 or type(width) is not int
                or not 160 <= width <= 448 or width % 2 or type(fps) is not int or fps not in (6, 8, 12, 24)):
            raise ValueError('Unsupported H.264 quality')
        self.bitrate, self.width, self.fps = bitrate, width, fps
        self._cancelled = cancelled
        self._closed = False
        self._codec = None
        self._last_timestamp = -1

    def encode(self, frame, timestamp, *, force_keyframe=False):
        if self._closed:
            raise RuntimeError('Avatar encoder is closed')
        if self._cancelled():
            self._closed = True
            self._codec = None
            return []
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp <= self._last_timestamp:
            raise ValueError('Avatar timestamp must increase on the 90 kHz timeline')
        if frame.width < 2 or frame.height < 2:
            raise ValueError('Avatar frame is too small for YUV420')
        scale = min(1, self.width / frame.width, self.width * 1.5 / frame.height)
        width = max(2, int(frame.width * scale) // 2 * 2)
        height = max(2, int(frame.height * scale) // 2 * 2)
        try:
            if self._codec is None or (self._codec.width, self._codec.height) != (width, height):
                self._codec = av.CodecContext.create('libx264', 'w')
                self._codec.width = width
                self._codec.height = height
                self._codec.pix_fmt = 'yuv420p'
                self._codec.bit_rate = self.bitrate
                self._codec.framerate = Fraction(self.fps, 1)
                self._codec.time_base = TIME_BASE
                self._codec.max_b_frames = 0
                self._codec.gop_size = self.fps * 2
                self._codec.profile = 'Baseline'
                self._codec.options = {
                    'tune': 'zerolatency', 'preset': 'veryfast', 'level': '31',
                    'forced-idr': '1', 'x264-params': 'repeat-headers=1:open-gop=0',
                }
                self._codec.open()
                force_keyframe = True
            converted = frame.reformat(width=width, height=height, format='yuv420p')
            converted.pts = timestamp
            converted.time_base = TIME_BASE
            converted.pict_type = av.video.frame.PictureType.I if force_keyframe else av.video.frame.PictureType.NONE
            packets = self._codec.encode(converted)
            if self._cancelled():
                self._closed = True
                self._codec = None
                return []
            if len(packets) != 1 or packets[0].pts != timestamp or packets[0].dts != timestamp:
                raise RuntimeError('Avatar codec buffered or reordered a frame')
            self._last_timestamp = timestamp
            return packets
        except BaseException:
            self._closed = True
            self._codec = None
            raise
