"""Bounded NC data-channel requests; never a general-purpose proxy."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import time
import struct
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from ..traffic_usage import traffic_kind
from ..state_sync import StateSyncStore, request_cursor, encoded
from core.diagnostics.plan_trace import PlanTrace
from .peer_diagnostics import request_scope, mark, record_failure

_peer_diagnostics = PlanTrace()

MAX_REQUEST = 16 * 1024 * 1024
MAX_FILE = 64 * 1024 * 1024
CHUNK = 24 * 1024
_GET = {
    "/health",
    "/api/diagnostics/policy",
    "/api/state",
    "/api/presence",
    "/api/personas",
    "/api/llm/models",
    "/api/voices",
    "/api/tts/providers",
    "/api/audio",
    "/api/musetalk",
    "/api/visual",
    "/api/visual/image",
    "/api/mprc",
    "/api/mprc/state",
}
_POST = {
    "/api/story-plan",
    "/api/visual-auto",
    "/api/story-library",
    "/api/commands/start",
    "/api/continuous/status",
    "/api/continuous/command",
    "/api/continuous/claim",
    "/api/continuous/models",
    "/api/continuous/speech",
    "/api/commands/status",
    "/api/commands/cancel",
    "/api/send",
    "/api/control",
    "/api/engine/start",
    "/api/engine/stop",
    "/api/stt",
    "/api/image",
    "/api/debug",
    "/api/audio/clear",
    "/api/audio/progressive/mode",
    "/api/audio/progressive/read",
    "/api/visual",
    "/api/personas/select",
    "/api/personas/prompts",
    "/api/llm/models/select",
    "/api/voices/select",
    "/api/tts/providers/select",
    "/api/mprc/send",
    "/api/mprc/choice",
    "/api/mprc/play",
    "/api/mprc/pause",
    "/api/mprc/visual",
    "/api/mprc/cast",
}


def validate_path(method: str, path: str) -> str:
    if (
        len(path) > 4096
        or not path.startswith("/")
        or path.startswith("//")
        or "\\" in path
    ):
        raise ValueError("Invalid peer path")
    parsed = urllib.parse.urlsplit(path)
    decoded = urllib.parse.unquote(parsed.path)
    if (
        parsed.netloc
        or parsed.scheme
        or parsed.fragment
        or decoded != parsed.path
        or ".." in decoded
    ):
        raise ValueError("Invalid peer path")
    allowed = (method == "GET" and decoded in _GET) or (
        method == "POST" and decoded in _POST
    )
    if method == "GET" and re.fullmatch(
        r"/api/(?:audio/(?:file|spectrum)|avatar/file|chat/image|image/file|musetalk/frame)/[A-Za-z0-9_.-]{1,256}",
        decoded,
    ):
        allowed = True
    if re.fullmatch(
        r"/api/phone-reply/(?:session|action|status|presentation|conversation-action|conversation)",
        decoded,
    ):
        allowed = method in {"GET", "POST"}
    from .musetalk import is_live_route
    if is_live_route(method, decoded):
        allowed = True
    if decoded.startswith('/api/idle-cache/'):
        from ..idle_loop_http import parse_route
        parse_route(method, path)
        allowed = True
    if decoded.startswith('/api/soundscape/'):
        from ..soundscape.api import parse_route
        parse_route(method, path)
        allowed = True
    if decoded == '/api/chat-characters' or decoded.startswith('/api/chat-characters/'):
        from ..chat_characters_api import parse_route
        parse_route(method, decoded)
        allowed = True
    if not allowed:
        raise ValueError("Peer route not allowed")
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [
        (k, v)
        for k, v in query
        if k.lower() not in {"code", "token", "access_token", "ticket", "authorization"}
    ]
    return decoded + ("?" + urllib.parse.urlencode(query) if query else "")


class RequestAssembler:
    def __init__(self):
        self.pending = {}

    def expire(self):
        now = time.monotonic()
        for key, (_, _, stamp) in list(self.pending.items()):
            if now - stamp > 60:
                self.pending.pop(key, None)

    def start(self, key, size):
        self.expire()
        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or not 0 < size <= MAX_REQUEST
            or key in self.pending
            or len(self.pending) >= 8
        ):
            raise ValueError("Transfer limit")
        self.pending[key] = (size, bytearray(), time.monotonic())

    def chunk(self, key, data):
        self.expire()
        if key not in self.pending or not isinstance(data, str) or len(data) > 32768:
            raise ValueError("Invalid transfer")
        size, buffer, _ = self.pending[key]
        decoded = base64.b64decode(data, validate=True)
        if len(decoded) > CHUNK or len(buffer) + len(decoded) > size:
            self.pending.pop(key, None)
            raise ValueError("Transfer overflow")
        buffer.extend(decoded)
        self.pending[key] = (size, buffer, time.monotonic())

    def end(self, key):
        self.expire()
        size, buffer, _ = self.pending.pop(key)
        if len(buffer) != size:
            raise ValueError("Incomplete transfer")
        data = json.loads(buffer)
        if (
            not isinstance(data, dict)
            or data.get("id") != key
            or data.get("type") != "request"
        ):
            raise ValueError("Invalid transfer envelope")
        return data


class PeerBridge:
    def __init__(self, channel, bridge_info_path: Path, *, media=None, av_only=False, bridge_identity=None, traffic=None, session_id='', on_channel_close=None):
        self.channel = channel
        self.info = Path(bridge_info_path)
        from .diagnostics import PeerTrace, disk_sink
        self.trace = PeerTrace(disk_sink(self.info.parent / 'phone_debug' / 'peer_requests.jsonl')
                               if self.info.is_file() else lambda row: None, session_id=session_id)
        self.assembler = RequestAssembler()
        self.tasks = {}
        self.closed = False
        self._on_channel_close = on_channel_close
        self._state_sync = StateSyncStore(max_contexts=1)
        self._state_lock = asyncio.Lock()
        self.media = media
        self.buffered = None
        self.buffered_enabled = False
        self._live_arms = {}
        self.av_only = av_only
        self.bridge_identity = bridge_identity
        self.traffic = traffic
        self._traffic_pending, self._traffic_kinds = {}, {}
        if media is not None:
            media.bind(self.forward)
        channel.on("message", self.receive)
        channel.on("close", self.close)

    def close(self, reason='data_channel_closed'):
        if self.closed:
            return
        if reason == 'data_channel_closed' and self._on_channel_close is not None:
            try:
                self._on_channel_close(len(self.tasks))
            except Exception:
                pass
        self.trace.event('peer_close_origin', reason=reason, pending=len(self.tasks),
                         buffered_bytes=self.channel.bufferedAmount, failure=True)
        self.closed = True
        arms, self._live_arms = self._live_arms, {}
        if arms:
            # The phone can no longer send cleanup over this closed channel.
            # Cancel only identities registered by this peer, including arms
            # whose HTTP response has not arrived. The producer's existing
            # cancellation tombstone also fences a late arm request.
            asyncio.create_task(asyncio.to_thread(self._cancel_live_arms, arms))
        if self.buffered is not None:
            self.buffered.stop()
            # Encoding/filesystem cleanup never blocks the data-channel loop.
            asyncio.create_task(asyncio.to_thread(self.buffered.close))
        self._state_sync.clear()
        if self.media is not None:
            self.media.close()
        for task in list(self.tasks.values()):
            task.cancel()
        self.tasks.clear()
        self.assembler.pending.clear()
        if self.traffic:
            self.traffic.received('other', sum(self._traffic_pending.values()), observed=True)
        self._traffic_pending.clear()

    def _cancel_live_arms(self, arms):
        for identity in arms:
            try:
                status, _, _ = self.forward({'method':'POST',
                    'path':'/api/dev/musetalk-live/cancel',
                    'body':{'armRequestId':identity}})
                _peer_diagnostics.observe(identity, 'backend.peer.cleanup', 'arm_cancel_status', 200, status)
            except Exception:
                _peer_diagnostics.observe(identity, 'backend.peer.cleanup', 'arm_cancel_completed', True, False)

    def receive(self, raw):
        try:
            if not isinstance(raw, str) or len(raw.encode()) > 65536:
                raise ValueError("Frame limit")
            if self.traffic:
                self.traffic.data['received'] += len(raw.encode())
            msg = json.loads(raw)
            key = msg.get("id")
            kind = msg.get("type")
            if (
                msg.get("v") != 1
                or not isinstance(key, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", key)
            ):
                raise ValueError("Envelope")
            if kind == "cancel":
                if self.traffic:
                    self.traffic.received('other', len(raw.encode()) + self._traffic_pending.pop(key, 0), observed=True)
                task = self.tasks.pop(key, None)
                if task:
                    task.cancel()
                self.assembler.pending.pop(key, None)
                return
            if kind == "request-start":
                self.assembler.start(key, msg["bytes"])
                for stale in list(self._traffic_pending):
                    if stale not in self.assembler.pending:
                        count = self._traffic_pending.pop(stale)
                        if self.traffic:
                            self.traffic.received('other', count, observed=True)
                self._traffic_pending[key] = len(raw.encode())
                return
            if kind == "request-chunk":
                self.assembler.chunk(key, msg["data"])
                self._traffic_pending[key] = self._traffic_pending.get(key, 0) + len(raw.encode())
                return
            if kind == "request-end":
                msg = self.assembler.end(key)
            elif kind != "request":
                raise ValueError("Message type")
            if self.traffic:
                self.traffic.received(traffic_kind(msg.get('path')), len(raw.encode()) + self._traffic_pending.pop(key, 0), observed=True)
            if len(self.tasks) >= 8 or key in self.tasks:
                raise ValueError("Too many requests")
            task = asyncio.create_task(self.respond(key, msg))
            self.tasks[key] = task
            task.add_done_callback(
                lambda done, k=key: (
                    self.tasks.pop(k, None) if self.tasks.get(k) is done else None
                )
            )
        except Exception as exc:
            # No request/exception text goes to logs or across the boundary.
            self.trace.event('peer_frame_rejected', error_type=type(exc).__name__, failure=True)
            self.close('invalid_peer_frame')
            self.channel.close()

    async def send(self, frame):
        deadline = time.monotonic() + 30
        while self.channel.bufferedAmount > 512 * 1024:
            if self.closed or time.monotonic() > deadline:
                raise TimeoutError("Peer backpressure")
            await asyncio.sleep(0.02)
        if self.closed or self.channel.readyState != "open":
            raise ConnectionError("Peer closed")
        encoded = json.dumps(
            {"v": 1, **frame}, separators=(",", ":"), ensure_ascii=False
        )
        if len(encoded.encode("utf-8")) > 65536:
            raise ValueError("Peer frame limit")
        self.channel.send(encoded)
        if self.traffic:
            self.traffic.sent(self._traffic_kinds.get(frame.get('id'), 'other'), len(encoded.encode('utf-8')))

    def forward(self, msg):
        mark('bridge.path')
        method = msg.get("method")
        path = validate_path(method, msg.get("path", ""))
        self.trace.event('bridge_forward_started', request_id=msg.get('id'))
        mark('bridge_info.read')
        raw_info = self.info.read_text(encoding="utf-8")
        mark('bridge_info.parse')
        info = json.loads(raw_info)
        mark('bridge_info.identity')
        if self.bridge_identity is not None and (info.get('url'), info.get('token')) != self.bridge_identity:
            raise ValueError('Desktop instance changed')
        from addons.main_chat_remote.remote_backend import BridgeClient

        mark('bridge.client')
        bridge = BridgeClient(info["url"], info["token"], timeout_seconds=140)
        mark('bridge.body')
        body = msg.get("body")
        if body is not None and (method != "POST" or not isinstance(body, dict)):
            raise ValueError("Invalid body")
        try:
            from .auth import _NoRedirect

            mark('bridge_http.build')
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}), _NoRedirect()
            )
            request = bridge.build_request(method, path, body)
            mark('bridge_http.open')
            with opener.open(request, timeout=bridge.timeout_seconds) as response:
                mark('bridge_http.read')
                data = response.read(MAX_FILE + 1)
                mark('bridge_http.metadata')
                status = int(response.status)
                ctype = str(
                    response.headers.get("Content-Type", "application/octet-stream")
                )
        except urllib.error.HTTPError as exc:
            mark('bridge_http.error_read')
            data = exc.read(65536)
            status = int(exc.code)
            ctype = "application/json"
        mark('bridge.response_size')
        if len(data) > MAX_FILE:
            raise ValueError("Media limit")
        if path == "/health" and status == 200:
            mark('bridge.health')
            from addons.main_chat_remote.remote_backend import (
                public_bridge_health_snapshot,
            )

            data = json.dumps({**public_bridge_health_snapshot(json.loads(data)), 'state_sync_version': 1}).encode()
        self.trace.event('bridge_forward_finished', request_id=msg.get('id'), status=status)
        return status, data, ctype

    def _state_response(self, msg):
        path = validate_path(msg.get('method'), msg.get('path', ''))
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query, keep_blank_values=True)
        if query.get('sync') != ['1']:
            return 409, b'{"ok":false,"error":"Update NC Desktop and NC Remote together (state protocol 1 required)."}', 'application/json'
        try:
            cursor = request_cursor(query)
        except ValueError:
            return 400, b'{"ok":false,"error":"Invalid state cursor."}', 'application/json'
        status, data, ctype = self.forward({**msg, 'path': '/api/state'})
        if status == 200 and 'json' in ctype:
            payload = json.loads(data)
            if payload.get('ok') is True and isinstance(payload.get('state'), dict) and not self.closed:
                try:
                    data = encoded(self._state_sync.respond('peer', payload['state'], **cursor))
                except ValueError:
                    return 400, b'{"ok":false,"error":"Invalid state synchronization."}', 'application/json'
        return status, data, ctype

    async def respond(self, key, msg):
        with request_scope(), _peer_diagnostics.operation(key,'backend.peer.request'):
            return await self._respond(key,msg)

    async def _respond(self, key, msg):
        started = time.monotonic()
        status = 0
        outcome = 'completed'
        error_type = ''
        # Never record paths, request bodies, SDP, tokens or exception messages.
        route = str(msg.get('path', '')).split('?', 1)[0]
        route = route if route in _GET | _POST or route in {
            '/api/phone-reply/status', '/api/phone-reply/action', '/api/phone-reply/presentation'
        } else 'media_or_other'
        body = msg.get('body')
        action = body.get('action') if isinstance(body, dict) else None
        self.trace.event('request_received', request_id=key, route=route, method=msg.get('method'), pending=len(self.tasks),
                         reply_id=action.get('phone_request_id') if isinstance(action, dict) else body.get('phone_request_id') if isinstance(body, dict) else None,
                         operation=action.get('kind') if isinstance(action, dict) else None)
        self._traffic_kinds[key] = traffic_kind(msg.get('path'))
        try:
            idle_range = None
            if str(msg.get('path','')).startswith(('/api/idle-cache/file/', '/api/idle-cache/ordered/file/')):
                from ..idle_loop_http import parse_route
                idle_range = parse_route(msg.get('method'), msg['path'])
                if msg.get('accept') != 'NCI1':
                    raise ValueError('Binary idle transfer required')
            from .musetalk import is_live_route
            route = str(msg.get('path', ''))
            buffered_route = route in {'/api/buffered/negotiate', '/api/buffered/audio', '/api/buffered/replay', '/api/buffered/release'} or bool(
                re.fullmatch(r'/api/buffered/audio/[a-f0-9]{32}\.ogg', route))
            local_buffered_route = self.buffered_enabled and (is_live_route(msg.get('method'), route)
                or route.startswith('/api/idle-cache/'))
            if route == '/api/peer-health' and msg.get('method') == 'GET' and msg.get('body') is None:
                # Authenticated peer-local echo: no Qt/LLM/HTTP bridge work.
                status, data, ctype = 200, b'{"pong":1}', 'application/json'
                self.trace.event('peer_heartbeat_received', request_id=key, pending=len(self.tasks))
            elif self.av_only and not buffered_route and not local_buffered_route and msg.get('path') not in {
                '/api/av/negotiate', '/api/av/prepare', '/api/av/commit',
                '/api/av/visual', '/api/av/idle', '/api/av/stop', '/api/av/retire',
            }:
                status, data, ctype = 403, b'{"ok":false,"error":"AV controls only."}', 'application/json'
            elif buffered_route:
                mark('request.buffered')
                try:
                    method, body = msg.get('method'), msg.get('body')
                    if route == '/api/buffered/negotiate' and method == 'POST':
                        if (self.media is not None or body != {'version': 1, 'audio_formats': ['ogg-opus'], 'local_video': 1}):
                            raise ValueError('Buffered media update required')
                        self.buffered_enabled = True
                        from ..media_quality import load_quality, video_quality
                        quality = await asyncio.to_thread(load_quality, self.info.parent)
                        result = {'buffered_media': 1, 'audio_format': 'ogg-opus', 'video_format': 'h264-segments',
                                  'local_video': 1, 'video_quality': video_quality(quality), 'peer_heartbeat': 1}
                    else:
                        if not self.buffered_enabled:
                            raise ValueError('Buffered media negotiation required')
                        if self.buffered is None:
                            from .buffered_media import BufferedMediaService
                            from ..media_quality import load_quality
                            self.buffered = BufferedMediaService(self.forward, lambda: load_quality(self.info.parent)['opus_kbps']*1000)
                        if route == '/api/buffered/audio' and method == 'POST':
                            result = await asyncio.to_thread(self.buffered.prepare, body)
                        elif route == '/api/buffered/replay' and method == 'POST':
                            result = await asyncio.to_thread(self.buffered.prepare_replay, body)
                        elif route == '/api/buffered/release' and method == 'POST':
                            result = {'released': await asyncio.to_thread(self.buffered.release, body)}
                        elif method == 'GET' and body is None and route.endswith('.ogg'):
                            result = await asyncio.to_thread(self.buffered.read, route)
                        else:
                            raise ValueError('Buffered media route unavailable')
                    status = 200
                    data, ctype = (result, 'audio/ogg') if isinstance(result, bytes) else (json.dumps(result).encode(), 'application/json')
                except ValueError as exc:
                    error_type = type(exc).__name__
                    status, data, ctype = 409, b'{"ok":false,"error":"Buffered media negotiation or ownership unavailable."}', 'application/json'
            elif msg.get('method') == 'GET' and urllib.parse.urlsplit(msg.get('path', '')).path == '/api/state':
                mark('request.state')
                async with self._state_lock:
                    status, data, ctype = await asyncio.wait_for(asyncio.to_thread(self._state_response, msg), 150)
            elif str(msg.get('path', '')).startswith('/api/av/'):
                mark('request.av')
                # These controls terminate on this peer, never the local HTTP
                # bridge, signaling service or an arbitrary network destination.
                try:
                    if self.media is None:
                        if msg.get('method') != 'POST' or msg['path'] != '/api/av/negotiate':
                            raise ValueError('NC AV capability unavailable')
                        result = {'version': 0}
                    else:
                        result = await self.media.request(msg.get('method'), msg['path'], msg.get('body'))
                    status = 200
                except (ValueError, TimeoutError):
                    status, result = 409, {'ok': False, 'error': 'NC media admission unavailable.'}
                data, ctype = json.dumps(result).encode(), 'application/json'
            else:
                mark('request.arm')
                arm = None
                if msg.get('method') == 'POST' and route == '/api/dev/musetalk-live/arm':
                    body = msg.get('body')
                    if isinstance(body, dict) and body.get('muxedAudio') is True:
                        arm = body.get('armRequestId')
                        if (self.closed or not isinstance(arm, str)
                                or not re.fullmatch(r'[A-Za-z0-9_-]{16,96}', arm)
                                or (arm not in self._live_arms and len(self._live_arms) >= 64)):
                            raise ValueError('Peer arm identity unavailable')
                        self._live_arms.setdefault(arm, None)
                mark('request.forward')
                status, data, ctype = await asyncio.wait_for(
                    asyncio.to_thread(self.forward, msg), 150
                )
                if arm is not None and 400 <= status < 500 and self._live_arms.get(arm) is None:
                    self._live_arms.pop(arm, None)
                elif arm in self._live_arms and status == 200:
                    result = json.loads(data)
                    trial = result.get('trialId') if isinstance(result, dict) else None
                    if isinstance(trial, str) and re.fullmatch(r'[a-f0-9]{32}', trial):
                        self._live_arms[arm] = trial
                if msg.get('method') == 'POST' and route == '/api/dev/musetalk-live/cancel' and status == 200:
                    mark('request.cancel')
                    body = msg.get('body')
                    if isinstance(body, dict):
                        for identity, trial in list(self._live_arms.items()):
                            matches = (body.get('armRequestId') == identity
                                and (body.get('trialId') is None or body.get('trialId') == trial)
                                if body.get('armRequestId') is not None else
                                trial is not None and body.get('trialId') == trial)
                            if matches:
                                self._live_arms.pop(identity, None)
            mark('response.observe')
            _peer_diagnostics.observe(key,'backend.peer.response','response_status',None,status)
            _peer_diagnostics.observe(key,'backend.peer.response','response_bytes',None,len(data))
            self.trace.event('response_ready', request_id=key, status=status, response_bytes=len(data),
                             elapsed_ms=round((time.monotonic()-started)*1000))
            if idle_range and status == 200:
                mark('response.idle')
                if ctype != 'video/mp4' or len(data) != idle_range['length']:
                    raise ValueError('Invalid idle range response')
                deadline = time.monotonic()+30
                for offset in range(0,len(data),24576):
                    # A whole-file response, not a request/ACK per packet.
                    # Yield between bounded batches so cancellation/control
                    # still run even when the data channel drains immediately.
                    if offset%(16*24576)==0:
                        await asyncio.sleep(0)
                    while self.channel.bufferedAmount > 512*1024:
                        if self.closed or time.monotonic() > deadline:
                            raise ValueError('Idle transfer stopped')
                        await asyncio.sleep(.02)
                    if self.closed or self.channel.readyState != 'open' or time.monotonic()>deadline:
                        raise ValueError('Idle peer closed')
                    piece=data[offset:offset+24576]
                    header=json.dumps({'id':key,'offset':idle_range['offset']+offset,'length':len(piece)},separators=(',',':')).encode()
                    if len(header)>1024: raise ValueError('Idle header limit')
                    frame=b'NCI1'+struct.pack('!I',len(header))+header+piece
                    self.channel.send(frame)
                    if self.traffic: self.traffic.sent('video',len(frame))
                return
            if "json" in ctype and len(data) < 45000:
                mark('response.decode')
                response_body = json.loads(data)
                mark('response.send')
                await self.send(
                    {
                        "type": "response",
                        "id": key,
                        "status": status,
                        "contentType": ctype,
                        "body": response_body,
                    }
                )
                return
            mark('response.file_start')
            await self.send(
                {
                    "type": "file-start",
                    "id": key,
                    "status": status,
                    "contentType": ctype,
                    "bytes": len(data),
                }
            )
            for offset in range(0, len(data), CHUNK):
                mark('response.file_chunk')
                await self.send(
                    {
                        "type": "file-chunk",
                        "id": key,
                        "data": base64.b64encode(data[offset : offset + CHUNK]).decode(
                            "ascii"
                        ),
                    }
                )
                _peer_diagnostics.observe(key,'backend.peer.file','submitted_bytes',None,min(offset+CHUNK,len(data)))
            mark('response.file_end')
            await self.send({"type": "file-end", "id": key})
        except asyncio.CancelledError:
            _peer_diagnostics.observe(key,'backend.peer.request','cancelled',False,True)
            outcome = 'cancelled'
            raise
        except Exception as error:
            record_failure(_peer_diagnostics,key,msg,error)
            _peer_diagnostics.observe(key,'backend.peer.request','handler_failed',False,True)
            outcome = 'failed'
            status = 502
            error_type = type(error).__name__
            try:
                failure_body = {"ok": False, "error": "NC peer request failed."}
                if str(msg.get('path','')).startswith('/api/remote-output/'):
                    failure_body['diagnosticReason'] = 'ordered_peer_handler_failed'
                await self.send(
                    {
                        "type": "response",
                        "id": key,
                        "status": 502,
                        "contentType": "application/json",
                        "body": failure_body,
                    }
                )
            except Exception:
                pass
        finally:
            elapsed = round((time.monotonic()-started)*1000)
            self.trace.event('request_finished', request_id=key, status=status, elapsed_ms=elapsed,
                             outcome=outcome, error_type=error_type, pending=len(self.tasks), buffered_bytes=self.channel.bufferedAmount,
                             failure=outcome != 'completed' or status >= 400 or elapsed >= 5000)
            self._traffic_kinds.pop(key, None)
            if self.closed:
                self._state_sync.clear()
