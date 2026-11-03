"""Isolated phone-bound Opus encoding; not yet wired into peer playback.

Own each encoder on one media worker, never Qt or the asyncio network thread.
Consume the iterators incrementally: they retain at most the current input frame
and a sub-packet PCM remainder. Cancellation may use a threading.Event.is_set.
Packets are media, not playback receipts or authorization to send them.
"""
from fractions import Fraction

import av


RATE = 48000
PACKET_SAMPLES = 960
TIME_BASE = Fraction(1, RATE)


class OpusSpeechEncoder:
    def __init__(self, *, cancelled=lambda: False, bitrate=32000, codec_context=None):
        if type(bitrate) is not int or not 16000 <= bitrate <= 96000:
            raise ValueError('Unsupported Opus bitrate')
        self._cancelled = cancelled
        self._closed = False
        self._busy = False
        self.valid_samples = 0
        self._fifo = av.AudioFifo()
        # A file muxer can own the context so its codec parameters (including
        # Opus pre-skip) come from the very encoder producing these packets.
        self._codec = codec_context if codec_context is not None else av.CodecContext.create('libopus', 'w')
        if self._codec.name != 'libopus' or self._codec.is_open:
            raise ValueError('Expected an unopened libopus encoder')
        self._codec.sample_rate = RATE
        self._codec.layout = 'mono'
        self._codec.format = 's16'
        self._codec.bit_rate = bitrate
        self._codec.time_base = TIME_BASE
        self._codec.options = {'application': 'audio', 'frame_duration': '20', 'vbr': 'on'}
        self._codec.open()
        header = self._codec.extradata or b''
        if self._codec.frame_size != PACKET_SAMPLES or len(header) < 19 or header[:8] != b'OpusHead' or header[9] != 1:
            raise RuntimeError('Unsupported Opus encoder configuration')
        # libopus's reported CodecContext.delay is zero in the installed build;
        # OpusHead pre-skip is the actual encoder lookahead, not a guessed constant.
        self.leading_samples = int.from_bytes(header[10:12], 'little')
        self._next_packet = 0

    def _enter(self):
        if self._closed:
            raise RuntimeError('Opus encoder is closed')
        if self._busy:
            raise RuntimeError('Consume the previous chunk before starting another')
        self._busy = True

    def _cancel(self):
        if self._closed or self._cancelled():
            self._closed = True
            self._fifo = None
            return True
        return False

    def _pack(self, packets):
        for packet in packets:
            if self._cancel():
                return
            if packet.pts is None or packet.time_base != TIME_BASE or packet.pts + self.leading_samples != self._next_packet:
                raise RuntimeError('Discontinuous Opus encoder timeline')
            # RTP starts at zero; valid speech begins after leading_samples.
            # The final decoded packet can extend beyond valid_samples: callers
            # must map/trim padding using these bounds, not packet duration.
            packet.pts = self._next_packet
            packet.dts = self._next_packet
            self._next_packet += PACKET_SAMPLES
            yield packet

    def encode_chunk(self, frames):
        self._enter()
        try:
            resampler = av.AudioResampler(format='s16', layout='mono', rate=RATE)
            for frame in frames:
                if self._cancel():
                    return
                yield from self._append(resampler.resample(frame))
            if not self._cancel():
                yield from self._append(resampler.resample(None))
        except BaseException:
            self._closed = True
            self._fifo = None
            raise
        finally:
            self._busy = False

    def _append(self, frames):
        for frame in frames:
            if self._cancel():
                return
            frame.pts = self.valid_samples
            frame.time_base = TIME_BASE
            self.valid_samples += frame.samples
            self._fifo.write(frame)
            while not self._cancel() and self._fifo.samples >= PACKET_SAMPLES:
                yield from self._pack(self._codec.encode(self._fifo.read(PACKET_SAMPLES)))

    def finish(self):
        self._enter()
        try:
            if self._cancel() or not self.valid_samples:
                return
            if self._fifo.samples:
                yield from self._pack(self._codec.encode(self._fifo.read(self._fifo.samples)))
            if not self._cancel():
                yield from self._pack(self._codec.encode(None))
        finally:
            self._closed = True
            self._busy = False
            self._fifo = None
