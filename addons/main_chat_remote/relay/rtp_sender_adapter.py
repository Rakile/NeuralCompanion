"""Peer-local clock enrollment for the audited aiortc 1.15.0 sender.

The RTP loop is adapted from aiortc (BSD-3-Clause, Jeremy Laine and contributors).
Only origin allocation moves outside the loop; packetization, history, counters
and RTCP remain aiortc's. Never enroll an already started or modified sender.
"""
# Copyright (c) Jeremy Lainé. All rights reserved.
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# * Redistributions of source code must retain the above copyright notice,
#   this list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
# * Neither the name of aiortc nor the names of its contributors may be used
#   to endorse or promote products derived from this software without specific
#   prior written permission.
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
import asyncio
import hashlib
import inspect
import secrets
import traceback
from types import MethodType

import aiortc
from aiortc import RTCRtpSender, clock
from aiortc.mediastreams import MediaStreamError
from aiortc.rtcrtpsender import random_sequence_number
from aiortc.rtp import RTP_HISTORY_SIZE, RtpPacket
from aiortc.utils import uint16_add, uint32_add

_UPSTREAM_SHA256 = 'ff597a1d554cb373e73b21775c5bf564e7dba1eab6058eeabd902e09794872a3'


class SenderClockAdapter:
    def __init__(self, sender, kind):
        if aiortc.__version__ != '1.15.0':
            raise RuntimeError('NC media requires audited aiortc 1.15.0')
        try:
            source = inspect.getsource(RTCRtpSender._run_rtp).replace('\r\n', '\n')
        except (OSError, TypeError):
            raise RuntimeError('NC sender source verification unavailable') from None
        if hashlib.sha256(source.encode()).hexdigest() != _UPSTREAM_SHA256:
            raise RuntimeError('NC sender implementation changed')
        if (kind not in {'audio', 'video'} or not isinstance(sender, RTCRtpSender)
                or sender.kind != kind or sender._RTCRtpSender__started
                or sender._run_rtp.__func__ is not RTCRtpSender._run_rtp):
            raise ValueError('NC sender is already enrolled, started or incompatible')
        self._sender = sender
        self._origin = secrets.randbits(32)
        self._rate = 48000 if kind == 'audio' else 90000
        self._closed = False
        self._original = sender._run_rtp

        async def run(selected, codec):
            await self._run(selected, codec)
        self._replacement = MethodType(run, sender)
        sender._run_rtp = self._replacement

    def clock(self):
        if self._closed:
            raise ConnectionError('NC sender clock ended')
        return {'ssrc': self._sender._ssrc, 'origin': self._origin, 'clock_rate': self._rate}

    async def _run(self, sender, codec):
        sender._RTCRtpSender__log_debug('- RTP started')
        sender._RTCRtpSender__rtp_started.set()
        sequence_number = random_sequence_number()
        try:
            while not self._closed:
                if not sender._RTCRtpSender__track:
                    await asyncio.sleep(.02)
                    continue
                enc_frame = await sender._next_encoded_frame(codec)
                if self._closed:
                    break
                if enc_frame is None:
                    continue
                timestamp = uint32_add(self._origin, enc_frame.timestamp)
                for i, payload in enumerate(enc_frame.payloads):
                    if self._closed:
                        break
                    packet = RtpPacket(payload_type=codec.payloadType,
                                       sequence_number=sequence_number, timestamp=timestamp)
                    packet.ssrc = sender._ssrc
                    packet.payload = payload
                    packet.marker = (i == len(enc_frame.payloads) - 1) and 1 or 0
                    packet.extensions.abs_send_time = (clock.current_ntp_time() >> 14) & 0xffffff
                    packet.extensions.mid = sender._RTCRtpSender__mid
                    if enc_frame.audio_level is not None:
                        packet.extensions.audio_level = (False, -enc_frame.audio_level)
                    sender._RTCRtpSender__log_debug('> %s', packet)
                    sender._RTCRtpSender__rtp_history[packet.sequence_number % RTP_HISTORY_SIZE] = packet
                    data = packet.serialize(sender._RTCRtpSender__rtp_header_extensions_map)
                    await sender.transport._send_rtp(data)
                    sender._RTCRtpSender__ntp_timestamp = clock.current_ntp_time()
                    sender._RTCRtpSender__rtp_timestamp = packet.timestamp
                    sender._RTCRtpSender__octet_count += len(payload)
                    sender._RTCRtpSender__packet_count += 1
                    sequence_number = uint16_add(sequence_number, 1)
        except (asyncio.CancelledError, ConnectionError, MediaStreamError):
            pass
        except Exception:
            sender._RTCRtpSender__log_warning(traceback.format_exc())
        finally:
            try:
                if sender._RTCRtpSender__track:
                    sender._RTCRtpSender__track.stop()
                    sender._RTCRtpSender__track = None
                sender._RTCRtpSender__encoder = None
                sender._RTCRtpSender__log_debug('- RTP finished')
            finally:
                sender._RTCRtpSender__rtp_exited.set()

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._sender._run_rtp is self._replacement:
            self._sender._run_rtp = self._original


def install_sender_clock(sender, kind: str) -> SenderClockAdapter:
    return SenderClockAdapter(sender, kind)
