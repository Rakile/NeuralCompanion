"""Opt-in live relay test, with no phone and no model generation.

Run as a module. Password comes only from Windows Credential Manager. The
default local fixture checks the production peer adapter without launching NC.
Supply --bridge-info to read health/state from an already running NC instead.
No tokens, SDP, ICE addresses or NC payloads are printed.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import ipaddress
import json
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import websockets
from aioice.ice import TransportPolicy
from aiortc import (
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
)

from .relay.auth import SIGNAL, RelayAuth, RelayError, http_request
from .relay.credentials import CredentialStore
from .relay.protocol import validate_signal
from .relay.worker import RelayWorker


async def until(predicate, timeout=40):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise TimeoutError("Live check deadline")
        await asyncio.sleep(0.1)


def fixture(runtime):
    token = secrets.token_urlsafe(32)
    media = b"RIFF" + bytes(range(256)) * 400

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.headers.get("X-NC-Bridge-Token") != token:
                self.send_error(401)
                return
            if self.path == "/api/audio/file/live-check":
                body, content_type = media, "audio/wav"
            else:
                body, content_type = (
                    json.dumps(
                        {
                            "ok": True,
                            "state": {"fixture": True},
                            "bridge": {"running": True, "token": "must-be-scrubbed"},
                        }
                    ).encode(),
                    "application/json",
                )
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.headers.get("X-NC-Bridge-Token") != token:
                self.send_error(401)
                return
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            value = json.loads(body)
            result = json.dumps(
                {"ok": True, "received": len(value["audio_base64"])}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(result)))
            self.end_headers()
            self.wfile.write(result)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    info = runtime / "fixture-bridge.json"
    info.write_text(
        json.dumps({"url": f"http://127.0.0.1:{server.server_port}", "token": token})
    )
    return server, info, media


async def session(worker, mobile, *, force_turn, expected_media=None):
    config = await mobile.authorized("/v1/ice-servers")
    pc = RTCPeerConnection(
        RTCConfiguration(iceServers=[RTCIceServer(**x) for x in config["iceServers"]])
    )
    channel = pc.createDataChannel("nc-rpc-v1", ordered=True)
    ice_connection = pc.sctp.transport.transport.iceGatherer._connection
    if force_turn:
        # Test-only aioice policy: no host/srflx candidates may be nominated.
        ice_connection._transport_policy = TransportPolicy.RELAY
    opened = asyncio.Event()
    inbox = asyncio.Queue()
    channel.on("open", opened.set)
    channel.on("message", lambda raw: inbox.put_nowait(json.loads(raw)))
    sid = str(uuid.uuid4())
    host_protocols = []
    try:
        async with websockets.connect(
            SIGNAL,
            additional_headers={"Authorization": "Bearer " + await mobile.access()},
            max_size=65536,
        ) as ws:

            async def next_kind(kind):
                while True:
                    msg = validate_signal(await asyncio.wait_for(ws.recv(), 60))
                    if msg["type"] == "error":
                        raise RelayError(msg["code"])
                    if msg["type"] == kind:
                        return msg

            assert (await next_kind("hello"))["role"] == "mobile"
            presence = await next_kind("desktop-presence")
            assert (
                presence["online"]
                and presence["desktopId"] == worker.identity["desktopId"]
            )
            if force_turn:
                await pc.sctp.transport.transport.iceGatherer.gather()
                # aioice keeps host sockets even under RELAY policy. Remove them
                # in this harness so peer-reflexive checks cannot bypass TURN.
                host_protocols = [
                    p
                    for p in ice_connection._protocols
                    if p.local_candidate.type != "relay"
                ]
                ice_connection._protocols = [
                    p
                    for p in ice_connection._protocols
                    if p.local_candidate.type == "relay"
                ]
                ice_connection._local_candidates = [
                    c for c in ice_connection.local_candidates if c.type == "relay"
                ]
                assert ice_connection.local_candidates, (
                    "TURN allocation returned no relay candidate"
                )
            await pc.setLocalDescription(await pc.createOffer())
            await ws.send(
                json.dumps(
                    validate_signal(
                        {
                            "v": 1,
                            "type": "offer",
                            "sessionId": sid,
                            "targetRole": "desktop",
                            "sdp": pc.localDescription.sdp,
                        }
                    )
                )
            )
            answer = await next_kind("answer")
            if force_turn:
                # TURN correctly rejects private peer addresses. This harness
                # is on the desktop's LAN, so retain only public peer candidates.
                answer["sdp"] = (
                    "\r\n".join(
                        line
                        for line in answer["sdp"].splitlines()
                        if not line.startswith("a=candidate:")
                        or ipaddress.ip_address(line.split()[4]).is_global
                    )
                    + "\r\n"
                )
            await pc.setRemoteDescription(
                RTCSessionDescription(sdp=answer["sdp"], type="answer")
            )
            await asyncio.wait_for(opened.wait(), 60)
            pairs = list(ice_connection._nominated.values())
            if force_turn:
                assert pairs and all(
                    pair.local_candidate.type == "relay" for pair in pairs
                ), "TURN was not the nominated transport"

            async def request(path, body=None):
                rid = uuid.uuid4().hex
                frame = {
                    "v": 1,
                    "type": "request",
                    "id": rid,
                    "method": "POST" if body else "GET",
                    "path": path,
                }
                if body:
                    frame["body"] = body
                raw = json.dumps(frame).encode()
                if len(raw) < 45000:
                    channel.send(raw.decode())
                else:
                    channel.send(
                        json.dumps(
                            {
                                "v": 1,
                                "type": "request-start",
                                "id": rid,
                                "bytes": len(raw),
                            }
                        )
                    )
                    for offset in range(0, len(raw), 24576):
                        channel.send(
                            json.dumps(
                                {
                                    "v": 1,
                                    "type": "request-chunk",
                                    "id": rid,
                                    "data": base64.b64encode(
                                        raw[offset : offset + 24576]
                                    ).decode(),
                                }
                            )
                        )
                    channel.send(json.dumps({"v": 1, "type": "request-end", "id": rid}))
                chunks = bytearray()
                size = None
                while True:
                    result = await asyncio.wait_for(inbox.get(), 30)
                    assert result["id"] == rid
                    if result["type"] == "response":
                        assert result["status"] == 200
                        return result["body"]
                    if result["type"] == "file-start":
                        assert result["status"] == 200
                        size = result["bytes"]
                    elif result["type"] == "file-chunk":
                        chunks.extend(base64.b64decode(result["data"]))
                    elif result["type"] == "file-end":
                        assert len(chunks) == size
                        return bytes(chunks)

            health = await request("/health")
            assert health["ok"] and "token" not in health.get("bridge", {})
            state = await request("/api/state")
            assert state["ok"]
            if expected_media:
                assert await request("/api/audio/file/live-check") == expected_media
                assert (await request("/api/stt", {"audio_base64": "a" * 100000}))[
                    "received"
                ] == 100000
            await ws.send(
                json.dumps(
                    {
                        "v": 1,
                        "type": "hangup",
                        "targetRole": "desktop",
                        "sessionId": sid,
                        "reason": "Live check finished",
                    }
                )
            )
            await until(lambda: not worker.peers, 10)
            print(
                "PASS live signaling, presence, offer/answer/ICE, peer RPC"
                + (
                    ", TURN-only allocation and data"
                    if force_turn
                    else ", automatic ICE"
                )
                + (
                    ", chunk upload/download (local NC fixture)"
                    if expected_media
                    else ", running NC health/state"
                ),
                flush=True,
            )
    finally:
        await pc.close()
        for protocol in host_protocols:
            await protocol.close()


async def main(args):
    credentials = json.loads(CredentialStore(args.credential_target).get() or "{}")
    assert credentials.get("username") and credentials.get("password"), (
        "Dedicated test credential missing"
    )
    runtime = Path(args.runtime).resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    server = None
    media = None
    if args.bridge_info:
        info = Path(args.bridge_info)
    else:
        server, info, media = fixture(runtime)
    suffix = hashlib.sha256(str(runtime).encode()).hexdigest()[:20]
    mobile = RelayAuth(
        CredentialStore("NeuralCompanion/NCRelay/LiveCheck/mobile/" + suffix),
        role="mobile",
    )
    worker = RelayWorker(runtime, info)
    try:
        assert (await http_request("/health/live"))["status"] == "ok"
        assert (await http_request("/health/ready"))["status"] == "ok"
        await worker.action(
            "login",
            {
                "identifier": credentials["username"],
                "password": credentials["password"],
            },
        )
        if worker.state["error_code"]:
            raise RelayError(worker.state["error_code"])
        await until(lambda: worker.state["online"])
        print(
            "PASS live verified account and desktop register/resume, secure token storage",
            flush=True,
        )
        await mobile.login(
            credentials["username"], credentials["password"], "NC Relay headless check"
        )
        old = mobile.store.get()
        mobile.expires = 0
        await asyncio.gather(mobile.access(), mobile.access())
        assert mobile.store.get() != old
        print(
            "PASS live single-use refresh rotation with concurrent callers", flush=True
        )
        await session(worker, mobile, force_turn=False, expected_media=media)
        if not args.skip_turn:
            await session(worker, mobile, force_turn=True, expected_media=media)
        prior = worker.socket
        await prior.close(code=1012, reason="Client-injected restart recovery check")
        await until(
            lambda: (
                worker.socket is not None
                and worker.socket is not prior
                and worker.state["online"]
            )
        )
        print(
            "PASS live reconnect after client-injected 1012 close (no server change)",
            flush=True,
        )
        # A second real desktop socket supersedes the first with 4001.
        prior = worker.socket
        async with websockets.connect(
            SIGNAL,
            additional_headers={
                "Authorization": "Bearer " + await worker.auth.access()
            },
        ) as duplicate:
            await duplicate.recv()
            await until(
                lambda: (
                    worker.socket is not None
                    and worker.socket is not prior
                    and worker.state["online"]
                )
            )
        print("PASS live 4001 supersession, re-registration and reconnect", flush=True)
        replacement = RelayAuth(
            CredentialStore("NeuralCompanion/NCRelay/LiveCheck/replacement/" + suffix)
        )
        try:
            await replacement.login(
                credentials["username"],
                credentials["password"],
                "Replacement recovery check",
            )
            new_identity = {**worker.identity, "desktopId": str(uuid.uuid4())}
            try:
                await replacement.register_desktop(new_identity)
                raise AssertionError(
                    "Replacement must require explicit password confirmation"
                )
            except RelayError as exc:
                assert exc.code == "DESKTOP_REPLACEMENT_REQUIRED" and exc.status == 409
            await replacement.register_desktop(
                {**new_identity, "password": credentials["password"]}, replace=True
            )
            await until(
                lambda: not worker.state["enabled"] and not worker.state["online"]
            )
            assert worker.state["error_code"] in {
                "INVALID_TOKEN",
                "TOKEN_REUSED",
                "LOGIN_REQUIRED",
                "DESKTOP_REPLACEMENT_REQUIRED",
            }
            # Restore only this dedicated test account's original registration.
            await replacement.register_desktop(
                {**worker.identity, "password": credentials["password"]}, replace=True
            )
            await worker.action(
                "login",
                {
                    "identifier": credentials["username"],
                    "password": credentials["password"],
                },
            )
            await until(lambda: worker.state["online"])
            print(
                "PASS live replacement 409, 4002 revocation, explicit re-login and re-registration",
                flush=True,
            )
        finally:
            await replacement.logout()
        async with websockets.connect(
            SIGNAL,
            additional_headers={"Authorization": "Bearer " + await mobile.access()},
        ) as observer:
            await observer.recv()
            await observer.recv()
            await worker.disconnect()
            while True:
                state = validate_signal(await asyncio.wait_for(observer.recv(), 10))
                if state["type"] == "desktop-presence" and not state["online"]:
                    break
            await worker.action("connect")
            await until(lambda: worker.state["online"])
            print(
                "PASS live phone-role offline presence and desktop resume", flush=True
            )
        # Deliberately replay only this disposable mobile family; then assert
        # the production client clears the rejected successor from secure storage.
        try:
            await http_request("/v1/auth/refresh", {"refreshToken": old})
            raise AssertionError("Expected refresh replay rejection")
        except RelayError as exc:
            assert exc.code == "TOKEN_REUSED" and exc.status == 401
        mobile.expires = 0
        try:
            await mobile.access()
            raise AssertionError("Expected revoked family rejection")
        except RelayError as exc:
            assert exc.status == 401 and mobile.store.get() is None and not mobile.token
        print(
            "PASS live TOKEN_REUSED 401, family revocation, secure credential wipe",
            flush=True,
        )
    finally:
        await worker.disconnect()
        for auth in (mobile, worker.auth):
            try:
                await auth.logout()
            except Exception:
                auth.clear()
        if server:
            await asyncio.to_thread(server.shutdown)
            server.server_close()
            info.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credential-target", required=True)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--bridge-info")
    parser.add_argument(
        "--skip-turn",
        action="store_true",
        help="Run the remaining live checks while diagnosing TURN separately",
    )
    try:
        asyncio.run(main(parser.parse_args()))
    except Exception as exc:
        print(
            "FAIL live check:",
            exc.code if isinstance(exc, RelayError) else type(exc).__name__,
            flush=True,
        )
        raise SystemExit(1) from None
