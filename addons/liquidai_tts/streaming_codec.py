"""Private incremental Liquid codec decoding; no host/model imports at discovery."""
from __future__ import annotations

import importlib


class StreamingAudioCodec:
    """Decode four code frames at a time, retaining the codec's streaming cache."""

    def __init__(self, codec, emit_pcm):
        module = importlib.import_module(type(codec).__module__)
        self._codec = codec
        self._cache = module.LiquidCodecStreamingCache(codec.config)
        self._emit_pcm = emit_pcm
        self._pending = []
        self._last = None
        self._ended = False
        self.samples = 0

    def put(self, codes):
        if self._ended:
            raise RuntimeError('LiquidAI received audio codes after the stream ended.')
        if codes.ndim != 1 or not codes.numel():
            raise RuntimeError('LiquidAI returned an invalid audio code frame.')
        owned = codes.detach().clone()
        self._pending.append(owned)
        self._last = owned
        if len(self._pending) >= 4:
            self._flush(False)

    def _flush(self, final):
        import torch
        import numpy as np
        if self._pending:
            codes = torch.stack(self._pending, dim=-1).unsqueeze(0)
            self._pending.clear()
        elif self._last is not None:
            codes = self._last.new_empty((1, self._last.numel(), 0))
        else:
            return
        audio = self._codec.decode(codes, streaming_cache=self._cache,
                                   finalize=final).audio_values[0]
        if not audio.numel():
            return
        samples = audio.float().cpu().numpy()
        if samples.ndim > 1 and any(size != 1 for size in samples.shape[:-1]):
            raise RuntimeError('LiquidAI codec returned audio with unexpected channels.')
        samples = samples.reshape(-1)
        if not np.isfinite(samples).all():
            raise RuntimeError('LiquidAI codec returned invalid speech audio.')
        pcm = (np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes()
        self.samples += len(samples)
        self._emit_pcm(pcm)

    def end(self):
        if not self._ended:
            self._ended = True
            self._flush(True)
