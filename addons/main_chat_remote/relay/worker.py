"""Standalone addon worker: account state, signaling, and aiortc peers."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import random
import secrets
import sys
import time
import uuid
from pathlib import Path

from .auth import SIGNAL, RelayAuth, RelayError, http_request
from .credentials import CredentialStore
from .ice import desktop_ice_servers
from .peer import PeerBridge
from .protocol import protocol_constants, validate_signal
from ..media_quality import load_quality
from ..traffic_usage import TrafficTotals
from .traffic import PeerTraffic
from .media_diagnostics import install_media_diagnostics
from .contract_diagnostics import emit_relay_transition

PEER_CONNECT_TIMEOUT = 50


class RelayWorker:
    def __init__(
        self,
        runtime_dir: Path,
        bridge_info_path: Path,
        emit=lambda value: None,
        store=None,
        av_tracks=True,
    ):
        self.runtime = runtime_dir
        self.bridge_info = bridge_info_path
        from .diagnostics import PeerTrace, disk_sink
        self.trace = PeerTrace(disk_sink(bridge_info_path.parent / 'phone_debug' / 'relay_handshake.jsonl')
                               if bridge_info_path.is_file() else lambda row: None)
        self.traffic = TrafficTotals(bridge_info_path.parent, 'internet')
        self.emit = emit
        # Rollout gate stays off until native/app integration is complete. Older
        # clients never offer the required receive-only media sections anyway.
        self.av_tracks = av_tracks is True
        identity_path = runtime_dir / "identity.json"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        if identity_path.exists():
            self.identity = json.loads(identity_path.read_text(encoding="utf-8"))
        else:
            self.identity = {
                "desktopId": str(uuid.uuid4()),
                "publicIdentityKey": base64.b64encode(secrets.token_bytes(32)).decode(),
                "deviceLabel": "NeuralCompanion",
            }
            with identity_path.open("x", encoding="utf-8") as f:
                json.dump(self.identity, f)
        key = hashlib.sha256(str(runtime_dir.resolve()).encode()).hexdigest()[:24]
        self.auth = RelayAuth(
            store or CredentialStore("NeuralCompanion/NCRelay/Desktop/" + key)
        )
        self.state = {
            "enabled": False,
            "busy": False,
            "status": "signed_out",
            "error_code": "",
            "message": "Sign in to NC Relay.",
            "authenticated": False,
            "email_verified": False,
            "account": {},
            "desktop_id": self.identity["desktopId"],
            "registered": False,
            "online": False,
            "peer_count": 0,
            "dependencies_ready": True,
        }
        self.connection = None
        self.socket = None
        self.peers = {}
        self.prefer_turn_tcp = False
        from .router_mapping import MappingSettings
        self.mapping_settings = MappingSettings.load(runtime_dir / "router_mapping.json")
        self.mapping_suppressed_until = 0.0
        self.state.update(router_mapping_enabled=self.mapping_settings.enabled,
                          router_mapping_status="ready" if self.mapping_settings.enabled else "disabled")
        if self.mapping_settings.enabled:
            self.trace.event("router_mapping_opt_in", operation="warning_temporary_inbound_udp_enabled")
        self.commands = asyncio.Lock()
        self.stopping = False
        self._mfa_expiry_task = None
        self._mfa_qr = ""
        self.version = protocol_constants()["version"]

    def _relay_transition(self, sid, peer, trigger, initiator, event_role,
                          *, channel=None, pending=0, failure=False):
        """Snapshot the cause before a later cleanup mutates the peer."""
        remaining = self.auth.expires - time.monotonic()
        socket_state = getattr(getattr(self.socket, "state", None), "name", "")
        signaling = str(socket_state).lower()
        if signaling not in {"connecting", "open", "closing", "closed"}:
            signaling = "open" if self.socket is not None else "none"
        emit_relay_transition(
            session_id=sid, trigger=trigger, initiator=initiator,
            event_role=event_role, failure=failure,
            state={
                "peer_state": getattr(peer, "connectionState", "none"),
                "ice_state": getattr(peer, "iceConnectionState", "unknown"),
                "channel_state": getattr(channel, "readyState", "unknown"),
                "signaling_state": signaling,
                "authorization_valid": bool(self.auth.token and remaining > 0),
                "authorization_remaining_ms": max(0, int(remaining)) if self.auth.token else None,
                "pending_commands": pending,
                "selected_candidate_type": "unknown", "candidate_protocol": "unknown",
            },
        )

    def _record_channel_close(self, sid, peer, channel, *, pending=0):
        # close_peers removes its owner before closing the native peer. A later
        # channel callback from that teardown is cleanup, not a new outage.
        if self.peers.get(sid) is not peer:
            return
        self._relay_transition(sid, peer, "data_channel_closed", "data_channel",
                               "initiating", channel=channel, pending=pending,
                               failure=True)

    def publish(self, **values):
        self.state.update(values)
        self.state.update(
            authenticated=bool(self.auth.token),
            email_verified=bool(self.auth.account.get("emailVerified")),
            account={
                k: self.auth.account[k]
                for k in ("username", "email")
                if k in self.auth.account
            },
            peer_count=len(self.peers),
            mfa_pending=self.auth.mfa_pending,
            mfa_status=self.auth.mfa_status,
            mfa_secret=self.auth.enrollment_secret,
            mfa_uri=self.auth.enrollment_uri,
            mfa_qr=self._mfa_qr if self.auth.enrollment_uri else "",
            mfa_recovery_codes=list(self.auth.recovery_codes),
        )
        self.emit(dict(self.state))

    async def _expire_mfa(self):
        while True:
            await asyncio.sleep(1)
            # A valid confirmation can arrive while the old local deadline passes.
            # Inspect/expire only after the command finishes, so a new recovery
            # phase never inherits an already-finishing enrollment watchdog.
            async with self.commands:
                if self.auth.mfa_pending:
                    continue
                if not self.auth.token:
                    self._mfa_qr = ""
                    self.publish(status="signed_out", message="Sign-in expired or cancelled. Sign in again.")
                return

    async def _continue_login(self):
        if self.auth.mfa_pending:
            self.publish(status=self.auth.mfa_status, message=(
                "Save your recovery codes, then confirm to continue." if self.auth.mfa_status == "recovery_codes"
                else "Set up Google Authenticator, then enter its code." if self.auth.mfa_status == "mfa_enrollment_required"
                else "Enter your authenticator code or a recovery code."))
            if self._mfa_expiry_task is None or self._mfa_expiry_task.done():
                self._mfa_expiry_task = asyncio.create_task(self._expire_mfa())
            return
        self._mfa_qr = ""
        await self.register()
        self.connect()

    @staticmethod
    def _enrollment_qr(uri: str) -> str:
        # Local generation only: never send an enrollment secret to a QR service.
        try:
            import io
            import qrcode
            output = io.BytesIO()
            qrcode.make(uri).save(output, format="PNG")
            return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")
        except (ImportError, OSError, ValueError):
            return ""

    async def register(self, replace_password=None):
        body = dict(self.identity)
        if replace_password is not None:
            body["password"] = replace_password
        result = await self.auth.register_desktop(body, replace_password is not None)
        self.publish(registered=True, error_code="", message="Desktop registered.")
        return result

    async def disconnect(self):
        self.state["enabled"] = False
        for sid, peer in list(self.peers.items()):
            self._relay_transition(sid, peer, "explicit_cleanup", "application", "initiating")
        if self.socket:
            try:
                await self.send(
                    {
                        "type": "desktop-presence",
                        "online": False,
                        "desktopId": self.identity["desktopId"],
                    }
                )
            except Exception:
                pass
        task = self.connection
        self.connection = None
        if task and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        for sid, peer in list(self.peers.items()):
            self.trace.event('peer_close_origin', request_id=sid, operation='desktop_disconnect')
            if self.peers.get(sid) is peer:
                self.peers.pop(sid, None)
            await peer.close()
        self.peers.clear()
        self.socket = None
        self.publish(
            online=False, status="disconnected", message="Internet disconnected."
        )

    async def action(self, name, payload=None):
        data = dict(payload or {})
        async with self.commands:
            self.publish(busy=True, error_code="")
            try:
                if name == "set_router_mapping":
                    from .router_mapping import MappingSettings
                    if self.peers:
                        raise ValueError("Disconnect the phone before changing router mapping")
                    if type(data.get("enabled")) is not bool:
                        raise ValueError("Router mapping requires an explicit boolean")
                    settings = MappingSettings(data["enabled"])
                    await asyncio.to_thread(settings.save, self.runtime / "router_mapping.json")
                    self.mapping_settings = settings
                    self.trace.event("router_mapping_opt_in", operation=(
                        "warning_temporary_inbound_udp_enabled" if settings.enabled else "disabled"))
                    self.publish(router_mapping_enabled=settings.enabled,
                                 router_mapping_status="ready" if settings.enabled else "disabled")
                elif name == "register_account":
                    await http_request(
                        "/v1/auth/register",
                        {k: data.get(k, "") for k in ("username", "email", "password", "inviteCode")},
                    )
                    self.publish(
                        message="Account created. Open the verification email, then sign in.",
                        status="verify_email",
                    )
                elif name == "verify_email":
                    await http_request(
                        "/v1/auth/verify-email", {"token": data.get("token", "")}
                    )
                    if self.auth.token:
                        self.auth.account = (await self.auth.authorized("/v1/account"))[
                            "account"
                        ]
                    self.publish(
                        message="Email verified. Connect to register this desktop."
                    )
                elif name == "login":
                    await self.disconnect()
                    await self.auth.login(
                        data.get("identifier", ""), data.get("password", "")
                    )
                    await self._continue_login()
                elif name == "mfa_enroll":
                    await self.auth.begin_enrollment()
                    self._mfa_qr = await asyncio.to_thread(self._enrollment_qr, self.auth.enrollment_uri)
                    await self._continue_login()
                elif name == "mfa_confirm":
                    await self.auth.confirm_enrollment(str(data.get("code", "")))
                    await self._continue_login()
                elif name == "mfa_verify":
                    await self.auth.verify_mfa(code=str(data.get("code", "")), recovery_code=str(data.get("recoveryCode", "")))
                    await self._continue_login()
                elif name == "mfa_acknowledge":
                    self.auth.acknowledge_recovery()
                    await self._continue_login()
                elif name == "mfa_cancel":
                    self.auth.clear()
                    self._mfa_qr = ""
                    self.publish(status="signed_out", message="Sign-in cancelled.")
                elif name in {"connect", "resume"}:
                    await self.auth.access()
                    self.auth.account = (await self.auth.authorized("/v1/account"))[
                        "account"
                    ]
                    await self.register()
                    self.connect()
                elif name == "replace_desktop":
                    await self.disconnect()
                    await self.register(data.get("password", ""))
                    self.connect()
                elif name == "disconnect":
                    await self.disconnect()
                elif name == "logout":
                    await self.disconnect()
                    await self.auth.logout()
                    self.publish(
                        registered=False, status="signed_out", message="Signed out."
                    )
                elif name == "resend_verification":
                    await self.auth.authorized("/v1/auth/resend-verification", {})
                    self.publish(message="Verification email requested.")
                elif name == "forgot_password":
                    await http_request(
                        "/v1/auth/forgot-password", {"email": data.get("email", "")}
                    )
                    self.publish(message="Password reset email requested.")
                elif name == "reset_password":
                    await http_request(
                        "/v1/auth/reset-password",
                        {k: data.get(k, "") for k in ("token", "password")},
                    )
                    await self.disconnect()
                    self.auth.clear()
                    self.publish(message="Password reset. Sign in again.")
                else:
                    raise RelayError("UNKNOWN_ACTION")
            except Exception as exc:
                code = exc.code if isinstance(exc, RelayError) else "CLIENT_ERROR"
                messages = {
                    "MFA_INVALID": "The code or sign-in request is invalid or expired. Try again or sign in again.",
                    "MFA_REQUIRED": "Complete authenticator sign-in first.",
                    "INVITE_INVALID": "This invitation is invalid, expired, revoked or already used.",
                    "EMAIL_NOT_VERIFIED": "Verify your email before registering this desktop.",
                    "DESKTOP_REPLACEMENT_REQUIRED": "Another desktop is registered. Confirm replacement with your password.",
                    "TOKEN_REUSED": "Session revoked. Sign in again.",
                    "LOGIN_REQUIRED": "Sign in to reconnect.",
                    "INVALID_CREDENTIALS": "Username/email or password is incorrect.",
                    "RATE_LIMITED": "Too many requests. Wait before trying again.",
                }
                self.publish(
                    status="error",
                    error_code=code,
                    message=messages.get(
                        code, "NC Relay operation failed (" + code + ")."
                    ),
                )
            finally:
                self.publish(busy=False)

    def connect(self):
        if self.connection and not self.connection.done():
            return
        self.state["enabled"] = True
        self.connection = asyncio.create_task(self.run_connection())

    async def send(self, message):
        frame = validate_signal({"v": self.version, **message})
        await self.socket.send(json.dumps(frame))

    async def heartbeat(self, socket_token: str):
        while True:
            await self.send(
                {
                    "type": "desktop-presence",
                    "online": True,
                    "desktopId": self.identity["desktopId"],
                }
            )
            if await self.auth.access() != socket_token:
                # A WebSocket keeps its opening JWT. Reopen with renewed
                # authority before that JWT expires, retaining healthy peers.
                await self.socket.close()
                return
            self.publish(
                online=True, status="online", message="Online. Waiting for your phone."
            )
            await asyncio.sleep(20)

    async def close_peers(self, *, preserve_connected=False, reason='signaling_cleanup'):
        for sid, peer in list(self.peers.items()):
            if preserve_connected and peer.connectionState == "connected":
                continue
            self._relay_transition(sid, peer,
                                   "authorization_expired" if reason == "authorization_expired" else "explicit_cleanup",
                                   "authorization" if reason == "authorization_expired" else "application",
                                   "cleanup", failure=reason == "authorization_expired")
            if self.peers.get(sid) is peer:
                self.peers.pop(sid, None)
            self.trace.event('peer_close_origin', request_id=sid, operation=reason, outcome=peer.connectionState)
            # Signaling shutdown may cancel the expiry watchdog while it is
            # closing this peer. Finish native teardown before propagating it.
            closing = asyncio.create_task(peer.close())
            cancelled = False
            while not closing.done():
                try:
                    await asyncio.shield(closing)
                except asyncio.CancelledError:
                    cancelled = True
            closing.result()
            if cancelled:
                raise asyncio.CancelledError

    async def watch_authorization(self):
        # Independent of socket/backoff waits: signaling recovery must never
        # extend an authenticated peer beyond the last issued access expiry.
        while self.state["enabled"]:
            remaining = self.auth.expires - time.monotonic()
            if not self.auth.token or remaining <= 0:
                self.state["enabled"] = False
                for sid, peer in list(self.peers.items()):
                    self._relay_transition(sid, peer, "authorization_expired", "authorization",
                                           "initiating", failure=True)
                await self.close_peers(reason='authorization_expired')
                if self.socket:
                    await self.socket.close()
                self.publish(online=False, status="error", error_code="LOGIN_REQUIRED",
                             message="Relay authorization expired. Sign in again.")
                return
            await asyncio.sleep(min(1, remaining))

    async def run_connection(self):
        authorization = asyncio.create_task(self.watch_authorization())
        try:
            await self.run_signaling()
        finally:
            authorization.cancel()
            try:
                await asyncio.gather(authorization, return_exceptions=True)
            finally:
                await self.close_peers()

    async def run_signaling(self):
        try:
            import websockets
        except (ImportError, OSError):
            # Report startup failures from this background task to the UI.
            self.publish(
                enabled=False,
                online=False,
                dependencies_ready=False,
                status="setup_required",
                error_code="DEPENDENCIES_MISSING",
                message="Internet runtime is incomplete. Its dependencies need repair.",
            )
            return

        attempts = 0
        registration_changed = False
        while self.state["enabled"]:
            heart = None
            preserve_connected = True
            try:
                if registration_changed:
                    current = await self.auth.authorized("/v1/desktops/current")
                    if current["desktop"]["desktopId"] != self.identity["desktopId"]:
                        raise RelayError("DESKTOP_REPLACEMENT_REQUIRED", 409)
                    await self.register()
                    registration_changed = False
                token = await self.auth.access()
                self.publish(status="connecting", message="Connecting to NC Relay.")
                async with websockets.connect(
                    SIGNAL,
                    additional_headers={"Authorization": "Bearer " + token},
                    max_size=65536,
                    open_timeout=15,
                    close_timeout=3,
                ) as socket:
                    self.socket = socket
                    hello = validate_signal(await asyncio.wait_for(socket.recv(), 15))
                    if hello["type"] != "hello" or hello["role"] != "desktop":
                        raise RelayError("INVALID_MESSAGE")
                    self.trace.event('signaling_connected')
                    heart = asyncio.create_task(self.heartbeat(token))
                    receive = asyncio.create_task(self.read_messages(socket))
                    try:
                        done, _ = await asyncio.wait(
                            [heart, receive], return_when=asyncio.FIRST_COMPLETED
                        )
                        for finished in done:
                            finished.result()
                    finally:
                        receive.cancel()
                        heart.cancel()
                        await asyncio.gather(receive, heart, return_exceptions=True)
            except asyncio.CancelledError:
                preserve_connected = False
                raise
            except RelayError as exc:
                self.trace.event('signaling_failed', failure=True, outcome=exc.code,
                                 error_type=type(exc).__name__)
                self.publish(
                    error_code=exc.code,
                    status="error",
                    online=False,
                    message="NC Relay: " + exc.code,
                )
                if exc.code in {
                    "NOT_AUTHENTICATED",
                    "LOGIN_REQUIRED",
                    "TOKEN_REUSED",
                    "INVALID_TOKEN",
                    "DESKTOP_REPLACEMENT_REQUIRED",
                    "DESKTOP_MISMATCH",
                    "UNAUTHORIZED",
                    "FORBIDDEN",
                }:
                    preserve_connected = False
                    break
                await asyncio.sleep(max(1, exc.retry_after))
            except Exception as exc:
                self.trace.event('signaling_interrupted', failure=True, error_type=type(exc).__name__)
                code = getattr(getattr(exc, "rcvd", None), "code", None) or getattr(
                    exc, "code", None
                )
                registration_changed = code in {4001, 4002}
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if registration_changed or code in {1008, 1009} or status in {401, 403}:
                    preserve_connected = False
                self.publish(
                    online=False,
                    status="reconnecting",
                    error_code=str(code or "CONNECTION_CLOSED"),
                    message="Internet connection interrupted. Reconnecting.",
                )
                if code in {1008, 1009} or status in {401, 403}:
                    break
            finally:
                if heart:
                    heart.cancel()
                for sid, peer in list(self.peers.items()):
                    self._relay_transition(sid, peer,
                                           "socket_closed" if self.state["enabled"] else "explicit_cleanup",
                                           "signaling" if self.state["enabled"] else "application",
                                           "initiating" if self.state["enabled"] else "cleanup",
                                           failure=self.state["enabled"])
                self.socket = None
                await self.close_peers(preserve_connected=bool(preserve_connected
                    and self.state["enabled"] and self.auth.token and self.auth.expires > time.monotonic()))
                self.publish(online=False)
            attempts += 1
            await asyncio.sleep(min(60, 2 ** min(attempts, 6)) + random.random())
        self.state["enabled"] = False
        self.publish(online=False)

    async def read_messages(self, socket):
        async for raw in socket:
            msg = validate_signal(raw)
            kind = msg["type"]
            if kind == "offer":
                await self.offer(msg)
            elif kind == "ice-candidate" and msg["sessionId"] in self.peers:
                from aiortc.sdp import candidate_from_sdp

                candidate = msg["candidate"]
                text = candidate.get("candidate", "")
                if text:
                    ice = candidate_from_sdp(text.removeprefix("candidate:"))
                    ice.sdpMid = candidate.get("sdpMid")
                    ice.sdpMLineIndex = candidate.get("sdpMLineIndex")
                    await self.peers[msg["sessionId"]].addIceCandidate(ice)
            elif kind == "hangup":
                peer = self.peers.pop(msg["sessionId"], None)
                if peer:
                    self.trace.event('peer_close_origin', request_id=msg['sessionId'], operation='remote_hangup')
                    await peer.close()
                self.publish()
            elif kind == "error":
                if msg["code"] in {"NOT_AUTHENTICATED", "TOKEN_REUSED", "LOGIN_REQUIRED", "INVALID_TOKEN",
                                   "UNAUTHORIZED", "FORBIDDEN", "DESKTOP_MISMATCH",
                                   "DESKTOP_REPLACEMENT_REQUIRED"}:
                    raise RelayError(msg["code"])
                peer = self.peers.pop(msg.get("sessionId", ""), None)
                if peer:
                    self.trace.event('peer_close_origin', request_id=msg.get('sessionId'), operation='signaling_error', outcome=msg['code'])
                    await peer.close()
                self.publish(
                    error_code=msg["code"], message="Relay signaling: " + msg["code"]
                )

    async def expire_peer(self, sid, peer, finished):
        # Trickle ICE can remain "checking" indefinitely when the remote peer
        # disappears without an end-of-candidates message. Bound that lifetime
        # before the phone's 60-second negotiation timeout starts another offer.
        try:
            await asyncio.wait_for(finished.wait(), PEER_CONNECT_TIMEOUT)
            return
        except TimeoutError:
            pass
        if self.peers.get(sid) is not peer or peer.connectionState == "connected":
            return
        self.trace.event('peer_connect_timeout', failure=True, request_id=sid,
                         outcome=peer.connectionState)
        self.peers.pop(sid, None)
        self.prefer_turn_tcp = not self.prefer_turn_tcp
        await peer.close()
        self.publish()
        try:
            await self.send(
                {
                    "type": "hangup",
                    "sessionId": sid,
                    "targetRole": "mobile",
                    "reason": "Peer connection timed out. Retry with alternate TURN transport.",
                }
            )
        except Exception:
            # The signaling socket may already have closed; cleanup still wins.
            pass

    async def offer(self, msg):
        self.trace.event('offer_received', request_id=msg.get('sessionId'),
                         operation='turn_tcp' if self.prefer_turn_tcp else 'turn_udp')
        from aiortc import (
            RTCConfiguration,
            RTCIceServer,
            RTCPeerConnection,
            RTCSessionDescription,
        )

        sid = msg["sessionId"]
        if sid in self.peers:
            self.trace.event('peer_close_origin', request_id=sid, operation='replaced_by_offer')
            await self.peers.pop(sid).close()
        if len(self.peers) >= 4:
            await self.send(
                {
                    "type": "hangup",
                    "sessionId": sid,
                    "targetRole": "mobile",
                    "reason": "Desktop session limit",
                }
            )
            return
        config = await self.auth.authorized("/v1/ice-servers")
        self.trace.event('ice_configuration_received', request_id=sid)
        peer = RTCPeerConnection(
            RTCConfiguration(
                iceServers=[
                    RTCIceServer(**entry)
                    for entry in desktop_ice_servers(
                        config["iceServers"], prefer_tcp=self.prefer_turn_tcp
                    )
                ]
            )
        )
        self.peers[sid] = peer
        traffic = PeerTraffic(peer, self.traffic)
        finished = asyncio.Event()
        asyncio.create_task(self.expire_peer(sid, peer, finished))
        media = None
        channel_bound = False

        @peer.on("datachannel")
        def on_channel(channel):
            nonlocal channel_bound
            if channel.label != "nc-rpc-v1" or channel_bound:
                channel.close()
                return
            channel_bound = True
            self.trace.event('datachannel_received', request_id=sid)
            PeerBridge(channel, self.bridge_info, media=media, traffic=traffic, session_id=sid,
                       on_channel_close=lambda pending: self._record_channel_close(
                           sid, peer, channel, pending=pending))

        @peer.on("iceconnectionstatechange")
        def ice_state_changed():
            self.trace.event('ice_state_changed', request_id=sid, outcome=peer.iceConnectionState,
                             failure=peer.iceConnectionState == 'failed')
            if peer.iceConnectionState in {"failed", "disconnected"}:
                self._relay_transition(sid, peer, "ice_state_changed", "ice", "initiating",
                                       failure=True)

        @peer.on("connectionstatechange")
        async def state_changed():
            self.trace.event('peer_state_changed', request_id=sid, outcome=peer.connectionState,
                             failure=peer.connectionState == 'failed')
            if peer.connectionState == "connected":
                try:
                    from .mapped_transport import selected_route
                    self.trace.event("ice_path", request_id=sid, route=selected_route(peer))
                except Exception:
                    pass  # Route diagnostics must not change a call outcome.
            if peer.connectionState in {"failed", "closed"}:
                self._relay_transition(sid, peer, "peer_failed", "peer", "initiating",
                                       failure=True)
            if peer.connectionState in {"connected", "failed", "closed"}:
                finished.set()
            if peer.connectionState in {"failed", "closed"}:
                if self.peers.get(sid) is peer:
                    self.peers.pop(sid, None)
                if peer.connectionState == "failed":
                    self.prefer_turn_tcp = not self.prefer_turn_tcp
                    if self.mapping_settings.enabled:
                        self.mapping_suppressed_until = time.monotonic() + 120
                    await peer.close()
            self.publish()

        stage = 'attach_media'
        try:
            if self.av_tracks:
                from .av_peer import attach_peer_media
                media = attach_peer_media(peer, msg["sdp"], enabled=True, quality=load_quality(self.bridge_info.parent), frame_handoff=True)
            stage = 'remote_description'
            await peer.setRemoteDescription(
                RTCSessionDescription(sdp=msg["sdp"], type="offer")
            )
            self.trace.event('remote_description_set', request_id=sid)
            if self.mapping_settings.enabled and time.monotonic() >= self.mapping_suppressed_until:
                from .mapped_transport import install_mapping
                from .router_mapping import RouterMapper, default_gateway

                def mapping_event(status):
                    self.trace.event("router_mapping", request_id=sid, operation=status)
                    self.publish(router_mapping_status=status)

                async def mapping_failed():
                    self.mapping_suppressed_until = time.monotonic() + 120
                    mapping_event("retry_without_mapping")
                    if self.peers.get(sid) is peer:
                        self.peers.pop(sid, None)
                        await peer.close()
                        try:
                            await self.send({"type": "hangup", "sessionId": sid,
                                             "targetRole": "mobile", "reason": "Reconnecting with normal ICE"})
                        except Exception:
                            pass

                async def mapping_factory():
                    return RouterMapper(await default_gateway(), event=mapping_event,
                                        on_failure=lambda: asyncio.create_task(mapping_failed()))

                try:
                    install_mapping(peer, enabled=True, mapper_factory=mapping_factory,
                                    event=mapping_event)
                except Exception:
                    mapping_event("unsupported_fallback")
            stage = 'gather_local_candidates'
            await asyncio.wait_for(
                peer.setLocalDescription(await peer.createAnswer()), 45
            )
            self.trace.event('local_description_set', request_id=sid)
            stage = 'send_answer'
            await self.send(
                {
                    "type": "answer",
                    "sessionId": sid,
                    "targetRole": "mobile",
                    "sdp": peer.localDescription.sdp,
                }
            )
            self.trace.event('answer_sent', request_id=sid)
        except Exception as exc:
            self.trace.event('peer_setup_failed', failure=True, request_id=sid,
                             operation=stage, error_type=type(exc).__name__)
            self.peers.pop(sid, None)
            await peer.close()
            await self.send(
                {
                    "type": "hangup",
                    "sessionId": sid,
                    "targetRole": "mobile",
                    "reason": "Peer setup failed",
                }
            )
        self.publish()


async def main():
    runtime, info = map(Path, sys.argv[1:3])
    diagnostics = install_media_diagnostics(info.parent, internet=True)
    try:
        await run_worker(runtime, info)
    finally:
        diagnostics.close()


async def run_worker(runtime, info):

    def emit(state):
        print(json.dumps(state), flush=True)

    worker = RelayWorker(runtime, info, emit, av_tracks=os.environ.get('NC_REMOTE_AV_TRACKS') != '0')
    worker.publish()
    # Authentication and connection start only with an explicit Internet action.
    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            break
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if message.get("action") == "stop":
            break
        if message.get("action") == "chess_mcp":
            from .chess_rpc import dispatch_chess_rpc
            await dispatch_chess_rpc(worker, message)
            continue
        await worker.action(message.get("action"), message.get("payload"))
    await worker.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        print(
            json.dumps(
                {
                    "status": "error",
                    "message": "NC Relay worker stopped. Check runtime dependencies.",
                    "error_code": "WORKER_ERROR",
                    "online": False,
                }
            ),
            flush=True,
        )
