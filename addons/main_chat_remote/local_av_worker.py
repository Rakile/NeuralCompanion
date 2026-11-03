"""Isolated LAN media worker. Private pipes only; no relay, account or HTTP port."""
from __future__ import annotations

import asyncio
import json
import secrets
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from aiortc.sdp import candidate_from_sdp

from .relay.peer import PeerBridge
from .traffic_usage import TrafficTotals
from .relay.traffic import PeerTraffic
from .relay.media_diagnostics import install_media_diagnostics

MAX_FRAME = 100_000


@dataclass
class Session:
    peer: RTCPeerConnection
    owner: str
    credential: str
    deadline: float
    media: object
    bridge: PeerBridge | None = None
    candidates: int = 0


class LocalAVWorker:
    def __init__(self, bridge_info: Path):
        self.bridge_info = bridge_info
        self.traffic = TrafficTotals(bridge_info.parent, 'lan-media')
        self.sessions: dict[str, Session] = {}
        self.identity = self.read_identity()

    def read_identity(self):
        try:
            value = json.loads(self.bridge_info.read_text(encoding='utf-8'))
            return value.get('url'), value.get('token')
        except (OSError, ValueError, AttributeError):
            return None

    async def retire(self, key):
        session = self.sessions.pop(key, None)
        if session:
            if session.bridge:
                session.bridge.close()
            if session.media:
                session.media.close()
            await session.peer.close()

    async def expire(self):
        if self.read_identity() != self.identity:
            await self.close()
            raise PermissionError('Desktop instance changed')
        for key, value in list(self.sessions.items()):
            if value.peer.connectionState in {'failed', 'closed'} or (
                value.peer.connectionState != 'connected' and time.monotonic() > value.deadline
            ):
                await self.retire(key)

    async def close(self):
        for key in list(self.sessions):
            await self.retire(key)

    async def request(self, action, body, owner):
        if not isinstance(body, dict) or not isinstance(owner, str) or not 1 <= len(owner) <= 256:
            raise ValueError('Invalid local media request')
        await self.expire()
        if action == 'offer':
            sdp = body.get('sdp')
            if body.get('version') != 1 or not isinstance(sdp, str) or not 1 <= len(sdp) <= 65536:
                raise ValueError('Invalid local media offer')
            if len(self.sessions) >= 4:
                raise ValueError('Local media capacity reached')
            sections = [line for line in sdp.splitlines() if line.startswith('m=')]
            if len(sections) != 1 or not sections[0].startswith('m=application '):
                raise ValueError('Buffered media requires a data-only offer')
            peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
            traffic = PeerTraffic(peer, self.traffic)
            media = None
            key = secrets.token_hex(16)
            try:
                session = Session(peer, owner, secrets.token_hex(32), time.monotonic() + 60, media)
                self.sessions[key] = session

                @peer.on('datachannel')
                def channel_received(channel):
                    if session.bridge or channel.label != 'nc-av-v1' or not channel.ordered:
                        channel.close()
                        return
                    session.bridge = PeerBridge(channel, self.bridge_info, media=media, av_only=True,
                                                bridge_identity=self.identity, traffic=traffic)

                await peer.setRemoteDescription(RTCSessionDescription(type='offer', sdp=sdp))
                await asyncio.wait_for(peer.setLocalDescription(await peer.createAnswer()), 8)
                if key not in self.sessions or time.monotonic() > session.deadline:
                    raise ValueError('Local media negotiation expired')
                for old_key, old in list(self.sessions.items()):
                    if old_key != key and old.owner == owner:
                        await self.retire(old_key)
                return {'version': 1, 'session': key, 'credential': session.credential,
                        'sdp': peer.localDescription.sdp}
            except BaseException:
                self.sessions.pop(key, None)
                if media:
                    media.close()
                await peer.close()
                raise
        key = body.get('session')
        session = self.sessions.get(key) if isinstance(key, str) else None
        credential = body.get('credential')
        if (not session or session.owner != owner or not isinstance(credential, str)
                or not secrets.compare_digest(session.credential, credential)):
            raise PermissionError('Local media session unavailable')
        if action == 'close':
            await self.retire(key)
            return {'ok': True}
        if action == 'status':
            return {'state': session.peer.connectionState}
        if action == 'candidate':
            value = body.get('candidate')
            if not isinstance(value, dict) or session.candidates >= 64:
                raise ValueError('Local media candidate limit')
            text = value.get('candidate')
            mid, index = value.get('sdpMid'), value.get('sdpMLineIndex')
            if (not isinstance(text, str) or not text.startswith('candidate:') or len(text) > 2048
                    or not isinstance(mid, str) or len(mid) > 32 or type(index) is not int or not 0 <= index <= 2):
                raise ValueError('Invalid local media candidate')
            candidate = candidate_from_sdp(text[len('candidate:'):])
            # No relay or server-reflexive candidates on the local media path.
            if candidate.type != 'host':
                raise ValueError('Local host candidate required')
            candidate.sdpMid, candidate.sdpMLineIndex = mid, index
            session.candidates += 1
            await session.peer.addIceCandidate(candidate)
            return {'ok': True}
        raise ValueError('Unknown local media action')


async def main():
    worker = LocalAVWorker(Path(sys.argv[1]))
    diagnostics = install_media_diagnostics(Path(sys.argv[1]).parent)
    async def sweep():
        while True:
            await asyncio.sleep(2)
            try:
                await worker.expire()
            except PermissionError:
                # A new desktop requires a new worker, never a reused capability.
                pass
    timer = asyncio.create_task(sweep())
    try:
        while True:
            raw = await asyncio.to_thread(sys.stdin.buffer.readline, MAX_FRAME + 1)
            if not raw or len(raw) > MAX_FRAME:
                break
            try:
                message = json.loads(raw)
                result = await worker.request(message['action'], message['body'], message['owner'])
                response = {'status': 200, 'body': result}
            except PermissionError:
                response = {'status': 403, 'body': {'error': 'Local media session unavailable.'}}
            except (ValueError, KeyError, TypeError, TimeoutError):
                response = {'status': 409, 'body': {'error': 'Local media negotiation rejected. Check desktop media setup.'}}
            except Exception:
                response = {'status': 503, 'body': {'error': 'Local media worker unavailable.'}}
            print(json.dumps(response, separators=(',', ':')), flush=True)
    finally:
        timer.cancel()
        await worker.close()
        diagnostics.close()


if __name__ == '__main__':
    asyncio.run(main())
