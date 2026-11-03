"""Audited aiortc 1.15 packet-path bridge, scoped to one peer's senders.

Allocate auditable peer-local origins without sending bootstrap audio. aiortc
only applies PLI to raw Frame encoding, not preencoded Packet delivery, so retain
that isolated instance hook. No content or capabilities enter signaling.
"""
from .rtp_sender_adapter import install_sender_clock


class SenderClockBinding:
    def __init__(self, audio_sender, video_sender, video_track):
        self._closed = False
        self._clocks = {}
        self._adapters = []
        self._restores = []
        senders = {'audio': audio_sender, 'video': video_sender}
        self._ssrcs = {sender._ssrc: kind for kind, sender in senders.items()}
        if len(self._ssrcs) != 2:
            raise RuntimeError('NC media sender identities overlap')
        try:
            for sender in senders.values():
                kind = self._ssrcs[sender._ssrc]
                adapter = install_sender_clock(sender, kind)
                self._adapters.append(adapter)
                self._clocks[kind] = adapter.clock()

            def keyframe():
                if not self._closed:
                    video_track.request_keyframe()
            self._replace(video_sender, '_send_keyframe', keyframe)
        except BaseException:
            self.close()
            raise

    def _replace(self, target, name, replacement):
        self._restores.append((target, name, getattr(target, name), replacement))
        setattr(target, name, replacement)

    async def ready(self):
        if self._closed:
            raise ConnectionError('NC media peer ended')
        return {kind: dict(clock) for kind, clock in self._clocks.items()}

    def close(self):
        if self._closed:
            return
        self._closed = True
        for adapter in reversed(self._adapters):
            adapter.close()
        self._adapters.clear()
        for target, name, original, replacement in reversed(self._restores):
            if getattr(target, name) is replacement:
                setattr(target, name, original)
        self._restores.clear()
        self._clocks.clear()
