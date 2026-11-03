"""Optional, versioned media senders on the EXISTING authorized NC peer."""
import asyncio
import av
from aiortc import RTCRtpSender
from aiortc.sdp import SessionDescription

from .av_control import AVControl
from .media_clock import MediaEpoch, PacedSpeechTrack, LatestAvatarTrack
from .sender_binding import SenderClockBinding


class PeerMedia:
    def __init__(self, peer, quality=None, *, frame_handoff=False):
        self.control = None
        self.closed = False
        self._frame_handoff = frame_handoff
        self._closing_peer = None
        epoch = MediaEpoch()
        self.audio = PacedSpeechTrack(epoch, bitrate=(quality or {}).get('opus_kbps', 32)*1000)
        self.video = LatestAvatarTrack(epoch, quality=quality)

        def media_ended():
            if not self.closed:
                self.close()
                # A terminal clock/encoder cannot accept another reservation.
                # Hand off to authenticated peer recovery; never keep a healthy
                # data channel advertising a permanently silent audio lifetime.
                self._closing_peer = asyncio.create_task(peer.close())
        self.audio.on('ended', media_ended)
        self.video.on('ended', media_ended)
        senders = []
        for track, mime in ((self.audio, 'audio/opus'), (self.video, 'video/H264')):
            transceiver = peer.addTransceiver(track, direction='sendonly')
            transceiver.setCodecPreferences([codec for codec in RTCRtpSender.getCapabilities(track.kind).codecs
                                             if codec.mimeType == mime])
            senders.append(transceiver.sender)
        self.binding = SenderClockBinding(*senders, self.video)
        # One content-free bootstrap frame exposes the real RTP origin. Native
        # presentation still remains closed until separately authorized metadata.
        frame = av.VideoFrame(64, 64, 'yuv420p')
        for index, plane in enumerate(frame.planes):
            plane.update(bytes([16 if index == 0 else 128]) * plane.buffer_size)
        self.video.offer(frame, 9000)

        @peer.on('connectionstatechange')
        def state_changed():
            if peer.connectionState in {'failed', 'closed'}:
                self.close()

    def bind(self, forward):
        if self.closed or self.control is not None:
            raise ValueError('NC media already belongs to a channel')
        self.control = AVControl(self.audio, self.video, self.binding, forward,
                                 frame_handoff=self._frame_handoff)

    async def request(self, method, path, body):
        if self.closed or self.control is None or method != 'POST':
            raise ValueError('NC media unavailable')
        actions = {'/api/av/negotiate': self.control.negotiate,
                   '/api/av/prepare': self.control.prepare, '/api/av/commit': self.control.commit,
                   '/api/av/prepare-visual': self.control.prepare_visual,
                   '/api/av/visual': self.control.visual,
                   '/api/av/idle': self.control.idle,
                   '/api/av/stop': self.control.stop, '/api/av/retire': self.control.retire}
        action = actions.get(path)
        if action is None:
            raise ValueError('Unknown NC media control')
        return await action(body)

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.control:
            self.control.close()
        else:
            self.audio.stop()
            self.video.stop()
            self.binding.close()


def attach_peer_media(peer, offer_sdp, *, enabled=False, quality=None, frame_handoff=False):
    """Call before setRemoteDescription: codec preferences participate in SDP.

    No media transceivers are added for a legacy/data-only offer. Missing support
    retains the existing file path. The release opt-in remains OFF until complete
    native enrollment/app integration has passed; this is not a JS-only toggle.
    """
    if not enabled:
        return None
    offer = SessionDescription.parse(offer_sdp)
    sections = [section for section in offer.media if section.kind in {'audio', 'video'}]
    if len(sections) != 2 or {s.kind for s in sections} != {'audio', 'video'}:
        return None
    for section in sections:
        mime = 'audio/opus' if section.kind == 'audio' else 'video/H264'
        if (section.port == 0 or section.direction != 'recvonly'
                or not any(c.mimeType == mime for c in section.rtp.codecs)):
            return None
    return PeerMedia(peer, quality, frame_handoff=frame_handoff)
