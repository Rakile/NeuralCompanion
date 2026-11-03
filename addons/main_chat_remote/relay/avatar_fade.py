"""Display-only crossfade before H.264 encoding; never an audio clock/receipt.

Uses the existing FFmpeg dependency, not Python per-pixel work. Two source frames
and one filter graph are retained only for the configured transition duration.
Called exclusively on the avatar frame worker.
"""
from fractions import Fraction
import av


class AvatarFade:
    def __init__(self):
        self.clear()

    def clear(self):
        self.identity = self.last = self.outgoing = self.graph = None
        self.a = self.b = self.sink = None
        self.start = self.duration = 0

    @staticmethod
    def _copy(frame, stamp, width, height):
        source = frame.reformat(width=width, height=height, format='yuv420p')
        result = av.VideoFrame(width, height, 'yuv420p')
        for target, plane in zip(result.planes, source.planes):
            raw = bytes(plane)
            target.update(b''.join(raw[row*plane.line_size:row*plane.line_size+plane.width] +
                                  bytes(target.line_size-plane.width) for row in range(plane.height)))
        result.pts, result.time_base = stamp, Fraction(1, 90000)
        return result

    def apply(self, frame, identity, stamp, duration_ms):
        if identity != self.identity:
            self.identity = identity
            self.outgoing = self.last
            self.start, self.duration, self.graph = stamp, max(0, min(5000, duration_ms))*90, None
        result = frame
        elapsed = stamp - self.start
        if self.outgoing is not None and self.duration > 0 and 0 <= elapsed < self.duration:
            old = self._copy(self.outgoing, elapsed, frame.width, frame.height)
            new = self._copy(frame, elapsed, frame.width, frame.height)
            if self.graph is None:
                self.graph = av.filter.Graph()
                self.a = self.graph.add_buffer(template=old)
                self.b = self.graph.add_buffer(template=new)
                blend = self.graph.add('blend', f'all_expr=A*(1-min(T/{self.duration/90000},1))+B*min(T/{self.duration/90000},1)')
                self.sink = self.graph.add('buffersink')
                self.a.link_to(blend, 0, 0); self.b.link_to(blend, 0, 1); blend.link_to(self.sink)
                self.graph.configure()
            self.a.push(old); self.b.push(new)
            result = self.sink.pull()
        else:
            self.outgoing = self.graph = None
        self.last = result
        return result
