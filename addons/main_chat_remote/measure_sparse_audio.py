"""Isolated real encrypted loopback: continuous baseline vs sparse production.

No accounts, signaling service, user session, playback receipts or microphone.
Only probe-owned instances are instrumented. Actual RTP and protected datagram
lengths are counted once at separate layers. IP/UDP, STUN and TURN are excluded.
"""
from __future__ import annotations

import argparse
import array
import asyncio
import contextvars
import hashlib
import json
import math
from pathlib import Path

import av
from aiortc import RTCConfiguration, RTCPeerConnection, RTCRtpSender
from aiortc.mediastreams import MediaStreamError
from aiortc.rtp import RtpPacket, is_rtcp

from .relay.media_clock import MediaEpoch, PacedSpeechTrack
from .relay.rtp_sender_adapter import install_sender_clock


def tone_pcm(samples):
    return array.array('h', (int(6000 * math.sin(2 * math.pi * 330 * n / 48000))
                             for n in range(samples))).tobytes()


class _ContinuousBaseline(PacedSpeechTrack):
    """Probe only: identical production clock/encoder, ungated pre-change output."""
    def _transmission_allowed(self, permissions):
        return True


async def _observe(pcm, idle_seconds, sparse):
    sender_pc, receiver_pc = (RTCPeerConnection(RTCConfiguration(iceServers=[])) for _ in range(2))
    epoch = MediaEpoch()
    track = (PacedSpeechTrack if sparse else _ContinuousBaseline)(epoch)
    transceiver = sender_pc.addTransceiver(track, direction='sendonly')
    transceiver.setCodecPreferences([c for c in RTCRtpSender.getCapabilities('audio').codecs if c.mimeType == 'audio/opus'])
    sender = transceiver.sender
    clock = install_sender_clock(sender, 'audio')
    origin = clock.clock()['origin']
    dtls, ice = sender.transport, sender.transport.transport
    original_rtp, original_wire = dtls._send_rtp, ice._send
    layer = contextvars.ContextVar('nc_probe_layer', default='dtls')
    counters = dict(rtp_payload_bytes=0, rtp_header_bytes=0, rtp_packets=0,
                    idle_rtp_packets=0, speech_rtp_packets=0, speech_payload_bytes=0,
                    decoder_drain_packets=0, decoder_drain_payload_bytes=0,
                    srtp_bytes=0, srtcp_bytes=0, dtls_bytes=0)
    # Round windows to the actual 20ms source clock; both modes use these values.
    first = math.ceil(idle_seconds * 50) * 960 + 4800
    samples = len(pcm) // 2
    descriptor = await track.reserve(1, pcm, first)
    await track.commit(1)
    decoded_samples = 0
    decoder = av.CodecContext.create('libopus', 'r')
    decoder.sample_rate = 48000; decoder.layout = 'mono'; decoder.format = 's16'
    # Decoder observation is source evidence only, not receiver/OS completion.
    async def capture_rtp(raw):
        nonlocal decoded_samples
        rtcp = is_rtcp(raw)
        packet = None if rtcp else RtpPacket.parse(raw)
        token = layer.set('srtcp' if rtcp else 'srtp')
        try:
            await original_rtp(raw)
        finally:
            layer.reset(token)
        if packet is not None:
            stamp = (packet.timestamp - origin) & 0xffffffff
            counters['rtp_packets'] += 1
            counters['rtp_payload_bytes'] += len(packet.payload)
            counters['rtp_header_bytes'] += len(raw) - len(packet.payload)
            spoken = stamp < descriptor['end_sample'] and stamp + 960 > descriptor['first_sample']
            drain = not spoken and descriptor['end_sample'] <= stamp < descriptor['end_sample'] + 960
            counters['speech_rtp_packets' if spoken else 'decoder_drain_packets' if drain else 'idle_rtp_packets'] += 1
            if drain:
                counters['decoder_drain_payload_bytes'] += len(packet.payload)
            if spoken:
                counters['speech_payload_bytes'] += len(packet.payload)
                decoded_samples += sum(frame.samples for frame in decoder.decode(av.Packet(packet.payload)))

    async def capture_wire(raw):
        await original_wire(raw)
        counters[layer.get() + '_bytes'] += len(raw)

    dtls._send_rtp, ice._send = capture_rtp, capture_wire
    drains = []
    @receiver_pc.on('track')
    def received(remote):
        async def drain():
            try:
                while True:
                    await remote.recv()
            except (MediaStreamError, asyncio.CancelledError):
                pass
        drains.append(asyncio.create_task(drain()))

    connected = asyncio.Event()
    @sender_pc.on('connectionstatechange')
    def changed():
        if sender_pc.connectionState == 'connected':
            connected.set()

    try:
        await sender_pc.setLocalDescription(await sender_pc.createOffer())
        await receiver_pc.setRemoteDescription(sender_pc.localDescription)
        await receiver_pc.setLocalDescription(await receiver_pc.createAnswer())
        await sender_pc.setRemoteDescription(receiver_pc.localDescription)
        await asyncio.wait_for(connected.wait(), 5)
        # Watch the production source clock, never assume a sleep means it sent.
        end = math.ceil((descriptor['end_sample'] + idle_seconds * 48000) / 960) * 960
        async def until_source(target):
            while track._next_sample < target:
                if track.readyState != 'live':
                    raise RuntimeError('Probe media clock ended; measurement invalid')
                await asyncio.sleep(.01)
        await asyncio.wait_for(until_source(end), end / 48000 + 5)
        await track.cancel(1); await track.retire(1)
        # A committed but immediately cancelled future reply must send no media.
        cancel_first = track._next_sample + 9600
        await track.reserve(2, pcm, cancel_first)
        await track.commit(2); await track.cancel(2)
        await asyncio.wait_for(until_source(cancel_first + samples + 1920), samples / 48000 + 5)
        await track.retire(2)
        counters['observed_source_samples'] = track._next_sample
    finally:
        track.stop()
        await sender_pc.close(); await receiver_pc.close()
        for task in drains:
            task.cancel()
        await asyncio.gather(*drains, return_exceptions=True)
        dtls._send_rtp, ice._send = original_rtp, original_wire
        clock.close()
    counters['decoded_speech_samples'] = decoded_samples
    counters['transport_bytes'] = sum(counters[k] for k in ('srtp_bytes', 'srtcp_bytes', 'dtls_bytes'))
    counters['overhead_bytes'] = counters['transport_bytes'] - counters['rtp_payload_bytes']
    counters['encoded_speech_bps'] = round(counters['speech_payload_bytes'] * 8 * 48000 / samples, 1)
    return counters


async def measure(pcm, *, idle_seconds=60):
    if (not isinstance(pcm, bytes) or not pcm or len(pcm) % 2 or len(pcm) > 16 * 1024 * 1024
            or not math.isfinite(idle_seconds) or not 0 <= idle_seconds <= 120):
        raise ValueError('Use bounded mono 48k s16 PCM and a finite 0..120 second idle window')
    digest = hashlib.sha256(pcm).hexdigest()
    windows = [idle_seconds, .12]
    async def sequence(sparse):
        runs = [await _observe(pcm, gap, sparse) for gap in windows]
        # Rates and durations are not additive counters.
        totals = {key: sum(run[key] for run in runs) for key in runs[0]
                  if key not in {'encoded_speech_bps', 'observed_source_samples'}}
        return dict(source_sha256=digest, windows=windows, connections=runs, totals=totals)
    # Compare one isolated media workload at a time. Concurrent baseline and
    # candidate encoders can distort the scheduling/overhead being measured.
    before, after = await sequence(False), await sequence(True)
    return dict(source_samples=len(pcm)//2, baseline=before, candidate=after,
                physical_playback_verified=False, decoded_observation='Captured emitted Opus, not OS consumption',
                unavailable=['IP/UDP headers', 'STUN/ICE consent traffic', 'TURN framing and retransmission',
                             'physical Android/iPhone output'],
                transport_scope='Outbound loopback SRTP + SRTCP + DTLS; no account/signaling service used')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--idle-seconds', type=float, default=60)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(measure(tone_pcm(96000), idle_seconds=args.idle_seconds))
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({key: result[key]['totals'] for key in ('baseline', 'candidate')}))


if __name__ == '__main__':
    main()
