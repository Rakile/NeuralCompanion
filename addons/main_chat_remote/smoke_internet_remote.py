from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Iterator


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run_lan_characterization_tests() -> None:
    from addons.main_chat_remote.backend_process import (
        DEFAULT_BACKEND_PORT,
        normalize_pairing_code as normalize_supervisor_pairing_code,
    )
    from addons.main_chat_remote.remote_backend import (
        DEFAULT_REMOTE_PORT,
        local_network_client,
        normalize_bridge_url,
        normalize_pairing_code as normalize_backend_pairing_code,
        redact_sensitive_query_values,
    )

    assert DEFAULT_BACKEND_PORT == 8777
    assert DEFAULT_REMOTE_PORT == 8777
    assert local_network_client("127.0.0.1") is True
    assert local_network_client("169.254.8.4") is True
    assert local_network_client("192.168.1.20") is True
    assert local_network_client("172.20.1.20") is True
    assert local_network_client("10.10.1.20") is True
    assert local_network_client("8.8.8.8") is False
    assert normalize_backend_pairing_code("12-34-56") == "123456"
    assert normalize_supervisor_pairing_code("12-34-56") == "123456"
    assert normalize_backend_pairing_code("12") == ""
    assert normalize_supervisor_pairing_code("12") == ""
    assert normalize_bridge_url("http://127.0.0.1:8776") == "http://127.0.0.1:8776"
    assert normalize_bridge_url("https://127.0.0.1:8776") == "http://127.0.0.1:8776"
    redacted = redact_sensitive_query_values(
        'GET /api/state?code=123456&token=device-secret HTTP/1.1'
    )
    assert "123456" not in redacted
    assert "device-secret" not in redacted
    assert "code=<redacted>" in redacted
    assert "token=<redacted>" in redacted


class _MutableClock:
    def __init__(self, value: float):
        self.value = float(value)

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += float(seconds)


def run_settings_tests() -> None:
    from addons.main_chat_remote.internet_settings import (
        InternetRemoteSettings,
        InternetSettingsStore,
    )

    with tempfile.TemporaryDirectory(prefix="nc-internet-settings-") as temp_dir:
        root = Path(temp_dir)
        store = InternetSettingsStore(root / "settings.json")
        store.save(
            InternetRemoteSettings(
                enabled=True,
                ddns_hostname=" NC.Example.Test. ",
                public_ip="8.8.8.8",
                external_port=443,
                gateway_port=8788,
                acme_port=8780,
                account_email=" owner@example.test ",
                terms_accepted=True,
            )
        )
        loaded = store.load()
        assert loaded.enabled is True
        assert loaded.ddns_hostname == "nc.example.test"
        assert loaded.public_ip == "8.8.8.8"
        assert loaded.account_email == "owner@example.test"
        assert loaded.primary_origin == "https://nc.example.test"
        assert loaded.fallback_origin == "https://8.8.8.8"
        assert loaded.to_dict()["gateway_port"] == 8788
        assert not list(root.glob("*.tmp"))

        invalid = InternetRemoteSettings(
            ddns_hostname="https://user:pass@example.test/path",
            public_ip="192.168.1.20",
            external_port=99999,
        ).normalized()
        assert invalid.ddns_hostname == ""
        assert invalid.public_ip == ""
        assert invalid.external_port == 443


def run_auth_tests() -> None:
    from addons.main_chat_remote.internet_auth import InternetCredentialStore

    with tempfile.TemporaryDirectory(prefix="nc-internet-auth-") as temp_dir:
        root = Path(temp_dir)
        clock = _MutableClock(1_000.0)
        store = InternetCredentialStore(
            root / "credentials.json",
            signing_key_path=root / "signing.key",
            clock=clock,
        )
        gateway_id = store.gateway_id
        assert gateway_id
        assert InternetCredentialStore(
            root / "credentials.json",
            signing_key_path=root / "signing.key",
            clock=clock,
        ).gateway_id == gateway_id

        enrollment = store.create_enrollment(ttl_seconds=600.0)
        pending = store.submit_enrollment(
            enrollment.enrollment_id,
            enrollment.secret,
            device_id=" phone-1 ",
            device_name=" Lainol phone ",
        )
        assert pending.device_id == "phone-1"
        assert pending.device_name == "Lainol phone"
        assert pending.status == "pending"
        assert store.approve_enrollment(pending.enrollment_id) is True
        issued = store.complete_enrollment(pending.enrollment_id, enrollment.secret)
        assert issued.device_id == "phone-1"
        assert len(issued.token) >= 43
        device = store.authenticate(issued.token)
        assert device is not None
        assert device.device_id == "phone-1"
        assert issued.token not in (root / "credentials.json").read_text(encoding="utf-8")

        ticket = store.issue_ws_ticket("phone-1", ttl_seconds=30.0)
        assert store.consume_ws_ticket(ticket).device_id == "phone-1"
        assert store.consume_ws_ticket(ticket) is None

        grant = store.sign_media(
            "phone-1",
            "/api/audio/file/a1",
            "GET",
            ttl_seconds=120.0,
        )
        assert store.verify_media(grant, "GET").device_id == "phone-1"
        assert store.verify_media(grant, "POST") is None
        clock.advance(121.0)
        assert store.verify_media(grant, "GET") is None

        assert store.revoke_device("phone-1") is True
        assert store.authenticate(issued.token) is None

        expired = store.create_enrollment(ttl_seconds=10.0)
        clock.advance(11.0)
        try:
            store.submit_enrollment(
                expired.enrollment_id,
                expired.secret,
                device_id="phone-2",
                device_name="Expired phone",
            )
        except ValueError as exc:
            assert "expired" in str(exc).lower()
        else:
            raise AssertionError("Expired enrollment should be rejected.")


class _FakeLanUpstream:
    def __init__(self, expected_code: str):
        self.expected_code = expected_code
        self.requests: list[dict[str, Any]] = []
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    @property
    def origin(self) -> str:
        if self.server is None:
            return ""
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def last_header(self, name: str) -> str:
        if not self.requests:
            return ""
        return str(self.requests[-1]["headers"].get(name, ""))


@contextlib.contextmanager
def _running_fake_lan_upstream(expected_code: str) -> Iterator[_FakeLanUpstream]:
    upstream = _FakeLanUpstream(expected_code)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def do_GET(self) -> None:
            headers = {key: value for key, value in self.headers.items()}
            upstream.requests.append({"path": self.path, "headers": headers})
            authorized = headers.get("X-NC-Phone-Code", "") == expected_code
            if self.path.startswith("/ws") and authorized:
                websocket_key = headers.get("Sec-WebSocket-Key", "")
                accept = base64.b64encode(
                    hashlib.sha1(
                        (websocket_key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
                    ).digest()
                ).decode("ascii")
                self.send_response(101, "Switching Protocols")
                self.send_header("Upgrade", "websocket")
                self.send_header("Connection", "Upgrade")
                self.send_header("Sec-WebSocket-Accept", accept)
                self.end_headers()
                hello = b'{"type":"hello"}'
                self.connection.sendall(bytes((0x81, len(hello))) + hello)
                return
            body = json.dumps({"ok": authorized, "path": self.path}).encode("utf-8")
            self.send_response(200 if authorized else 401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    upstream.server = server
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    upstream.thread = thread
    thread.start()
    try:
        yield upstream
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def _json_request(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    expected_status: int = 200,
) -> tuple[dict[str, Any], Any]:
    request_headers = dict(headers or {})
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    try:
        response = urllib.request.urlopen(request, timeout=3.0)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        status = int(response.status)
        payload = json.loads(response.read().decode("utf-8"))
        response_headers = response.headers
    assert status == expected_status, (status, payload)
    return payload, response_headers


def _enrolled_device_token(root: Path) -> str:
    from addons.main_chat_remote.internet_auth import InternetCredentialStore

    store = InternetCredentialStore(
        root / "credentials.json",
        signing_key_path=root / "signing.key",
    )
    enrollment = store.create_enrollment()
    pending = store.submit_enrollment(
        enrollment.enrollment_id,
        enrollment.secret,
        device_id="phone-1",
        device_name="Test phone",
    )
    assert store.approve_enrollment(pending.enrollment_id)
    return store.complete_enrollment(pending.enrollment_id, enrollment.secret).token


def run_gateway_http_tests() -> None:
    from addons.main_chat_remote.internet_auth import InternetCredentialStore
    from addons.main_chat_remote.internet_gateway import (
        InternetGatewayConfig,
        MainChatInternetGateway,
    )

    with tempfile.TemporaryDirectory(prefix="nc-internet-gateway-") as temp_dir:
        root = Path(temp_dir)
        token = _enrolled_device_token(root)
        credentials = InternetCredentialStore(
            root / "credentials.json",
            signing_key_path=root / "signing.key",
        )
        log_lines: list[str] = []
        with _running_fake_lan_upstream("654321") as upstream:
            gateway = MainChatInternetGateway(
                InternetGatewayConfig(
                    host="127.0.0.1",
                    port=0,
                    cert_file=root / "unused-cert.pem",
                    key_file=root / "unused-key.pem",
                    registry_file=root / "credentials.json",
                    signing_key_file=root / "signing.key",
                    gateway_id=credentials.gateway_id,
                    allowed_public_hosts=("nc.example.test", "8.8.8.8"),
                    upstream_origin=upstream.origin,
                    upstream_pairing_code="654321",
                    tls_enabled=False,
                ),
                logger=log_lines.append,
            )
            gateway.start()
            try:
                health, _headers = _json_request(f"{gateway.local_origin}/health")
                assert health["service"] == "nc_main_chat_internet"
                unauthorized, _headers = _json_request(
                    f"{gateway.local_origin}/api/state", expected_status=401
                )
                assert unauthorized["error"] == "Unauthorized"
                state, headers = _json_request(
                    f"{gateway.local_origin}/api/state",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert state["ok"] is True
                assert upstream.last_header("X-NC-Phone-Code") == "654321"
                assert upstream.last_header("Authorization") == ""
                assert headers.get("Access-Control-Allow-Origin", "") != "*"

                stolen = "stolen-device-token"
                for attempt in range(9):
                    expected_status = 429 if attempt == 8 else 401
                    _json_request(
                        f"{gateway.local_origin}/api/state?token={stolen}",
                        headers={"Authorization": f"Bearer {stolen}"},
                        expected_status=expected_status,
                    )
                captured = "\n".join(log_lines)
                assert stolen not in captured
                assert "Authorization" not in captured
            finally:
                gateway.stop()


def run_enrollment_tests() -> None:
    from addons.main_chat_remote.internet_auth import InternetCredentialStore
    from addons.main_chat_remote.internet_gateway import (
        InternetGatewayConfig,
        MainChatInternetGateway,
    )

    with tempfile.TemporaryDirectory(prefix="nc-internet-enrollment-") as temp_dir:
        root = Path(temp_dir)
        credentials = InternetCredentialStore(
            root / "credentials.json",
            signing_key_path=root / "signing.key",
        )
        enrollment = credentials.create_enrollment(ttl_seconds=600.0)
        log_lines: list[str] = []
        with _running_fake_lan_upstream("654321") as upstream:
            gateway = MainChatInternetGateway(
                InternetGatewayConfig(
                    host="127.0.0.1",
                    port=0,
                    cert_file=root / "unused-cert.pem",
                    key_file=root / "unused-key.pem",
                    registry_file=root / "credentials.json",
                    signing_key_file=root / "signing.key",
                    gateway_id=credentials.gateway_id,
                    allowed_public_hosts=("127.0.0.1",),
                    upstream_origin=upstream.origin,
                    upstream_pairing_code="654321",
                    tls_enabled=False,
                ),
                logger=log_lines.append,
            )
            gateway.start()
            try:
                pending, _headers = _json_request(
                    f"{gateway.local_origin}/internet/enroll/submit",
                    method="POST",
                    payload={
                        "enrollment_id": enrollment.enrollment_id,
                        "secret": enrollment.secret,
                        "device_id": " phone-2 ",
                        "device_name": " Internet phone ",
                    },
                )
                assert pending["status"] == "pending"
                assert pending["device_id"] == "phone-2"
                assert credentials.approve_enrollment(pending["enrollment_id"])
                query = urllib.parse.urlencode(
                    {
                        "enrollment_id": pending["enrollment_id"],
                        "secret": enrollment.secret,
                    }
                )
                completed, _headers = _json_request(
                    f"{gateway.local_origin}/internet/enroll/status?{query}"
                )
                assert completed["status"] == "complete"
                assert len(completed["device_token"]) >= 43
                assert credentials.authenticate(completed["device_token"]) is not None
                _payload, _headers = _json_request(
                    f"{gateway.local_origin}/internet/enroll/status?{query}",
                    expected_status=400,
                )
                captured = "\n".join(log_lines)
                assert enrollment.secret not in captured
                assert completed["device_token"] not in captured
            finally:
                gateway.stop()


def _websocket_probe(origin: str, ticket: str) -> tuple[int, bytes]:
    parsed = urllib.parse.urlsplit(origin)
    key = base64.b64encode(b"0123456789abcdef").decode("ascii")
    request = (
        f"GET /ws?ticket={urllib.parse.quote(ticket)} HTTP/1.1\r\n"
        f"Host: {parsed.hostname}:{parsed.port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        f"Sec-WebSocket-Key: {key}\r\n\r\n"
    ).encode("ascii")
    with socket.create_connection((str(parsed.hostname), int(parsed.port or 80)), timeout=3.0) as client:
        client.settimeout(3.0)
        client.sendall(request)
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = client.recv(4096)
            if not chunk:
                break
            response += chunk
            if len(response) > 65_536:
                raise AssertionError("WebSocket response headers were too large.")
        header, _separator, remainder = response.partition(b"\r\n\r\n")
        status = int(header.split(b" ", 2)[1])
        if status == 101 and not remainder:
            try:
                remainder = client.recv(4096)
            except TimeoutError:
                remainder = b""
        return status, remainder


def run_websocket_tests() -> None:
    from addons.main_chat_remote.internet_auth import InternetCredentialStore
    from addons.main_chat_remote.internet_gateway import (
        InternetGatewayConfig,
        MainChatInternetGateway,
    )

    with tempfile.TemporaryDirectory(prefix="nc-internet-websocket-") as temp_dir:
        root = Path(temp_dir)
        token = _enrolled_device_token(root)
        credentials = InternetCredentialStore(
            root / "credentials.json",
            signing_key_path=root / "signing.key",
        )
        log_lines: list[str] = []
        with _running_fake_lan_upstream("654321") as upstream:
            gateway = MainChatInternetGateway(
                InternetGatewayConfig(
                    host="127.0.0.1",
                    port=0,
                    cert_file=root / "unused-cert.pem",
                    key_file=root / "unused-key.pem",
                    registry_file=root / "credentials.json",
                    signing_key_file=root / "signing.key",
                    gateway_id=credentials.gateway_id,
                    allowed_public_hosts=("127.0.0.1",),
                    upstream_origin=upstream.origin,
                    upstream_pairing_code="654321",
                    tls_enabled=False,
                ),
                logger=log_lines.append,
            )
            gateway.start()
            try:
                issued, _headers = _json_request(
                    f"{gateway.local_origin}/internet/ws-ticket",
                    method="POST",
                    payload={},
                    headers={"Authorization": f"Bearer {token}"},
                )
                ticket = str(issued["ticket"])
                status, frame = _websocket_probe(gateway.local_origin, ticket)
                assert status == 101
                assert b'"type":"hello"' in frame
                second_status, _frame = _websocket_probe(gateway.local_origin, ticket)
                assert second_status == 401
                assert upstream.last_header("X-NC-Phone-Code") == "654321"
                captured = "\n".join(log_lines)
                assert ticket not in captured
                assert token not in captured
            finally:
                gateway.stop()


def run_media_tests() -> None:
    from addons.main_chat_remote.internet_auth import InternetCredentialStore
    from addons.main_chat_remote.internet_gateway import (
        InternetGatewayConfig,
        MainChatInternetGateway,
    )

    with tempfile.TemporaryDirectory(prefix="nc-internet-media-") as temp_dir:
        root = Path(temp_dir)
        token = _enrolled_device_token(root)
        credentials = InternetCredentialStore(
            root / "credentials.json",
            signing_key_path=root / "signing.key",
        )
        log_lines: list[str] = []
        with _running_fake_lan_upstream("654321") as upstream:
            gateway = MainChatInternetGateway(
                InternetGatewayConfig(
                    host="127.0.0.1",
                    port=0,
                    cert_file=root / "unused-cert.pem",
                    key_file=root / "unused-key.pem",
                    registry_file=root / "credentials.json",
                    signing_key_file=root / "signing.key",
                    gateway_id=credentials.gateway_id,
                    allowed_public_hosts=("127.0.0.1",),
                    upstream_origin=upstream.origin,
                    upstream_pairing_code="654321",
                    tls_enabled=False,
                ),
                logger=log_lines.append,
            )
            gateway.start()
            try:
                issued, _headers = _json_request(
                    f"{gateway.local_origin}/internet/media-ticket",
                    method="POST",
                    payload={"path": "/api/audio/file/a1", "method": "GET"},
                    headers={"Authorization": f"Bearer {token}"},
                )
                signed_path = str(issued["url"])
                assert signed_path.startswith("/media?")
                media, _headers = _json_request(f"{gateway.local_origin}{signed_path}")
                assert media["ok"] is True
                assert media["path"] == "/api/audio/file/a1"
                assert upstream.last_header("X-NC-Phone-Code") == "654321"

                parsed = urllib.parse.urlsplit(signed_path)
                params = urllib.parse.parse_qs(parsed.query)
                params["path"] = ["/api/audio/file/a2"]
                tampered_path = f"{parsed.path}?{urllib.parse.urlencode(params, doseq=True)}"
                _payload, _headers = _json_request(
                    f"{gateway.local_origin}{tampered_path}", expected_status=401
                )
                params = urllib.parse.parse_qs(parsed.query)
                params["expires"] = ["0"]
                expired_path = f"{parsed.path}?{urllib.parse.urlencode(params, doseq=True)}"
                _payload, _headers = _json_request(
                    f"{gateway.local_origin}{expired_path}", expected_status=401
                )
                signature = str(urllib.parse.parse_qs(parsed.query)["signature"][0])
                captured = "\n".join(log_lines)
                assert signature not in captured
                assert token not in captured
            finally:
                gateway.stop()


def run_certificate_tests() -> None:
    from addons.main_chat_remote.certificate_manager import (
        CertificateManager,
        LEGO_RELEASE,
        LegoInstaller,
        LegoRelease,
    )
    from addons.main_chat_remote.internet_settings import InternetRemoteSettings

    with tempfile.TemporaryDirectory(prefix="nc-internet-certificate-") as temp_dir:
        root = Path(temp_dir)
        bad = LegoInstaller(runtime_dir=root / "bad", downloader=lambda _url: b"bad")
        result = bad.install()
        assert result.accepted is False
        assert "checksum" in result.message.lower()
        assert not (root / "bad" / "tools" / "lego" / LEGO_RELEASE.version / "lego.exe").exists()

        malicious_buffer = io.BytesIO()
        with zipfile.ZipFile(malicious_buffer, "w") as archive:
            archive.writestr("../lego.exe", b"malicious")
        malicious_bytes = malicious_buffer.getvalue()
        malicious_release = LegoRelease(
            version="5.2.1",
            asset_name="malicious.zip",
            url="https://example.test/malicious.zip",
            sha256=hashlib.sha256(malicious_bytes).hexdigest(),
        )
        malicious = LegoInstaller(
            runtime_dir=root / "malicious",
            downloader=lambda _url: malicious_bytes,
            runner=lambda _command: subprocess.CompletedProcess(_command, 0, "lego version 5.2.1", ""),
            release=malicious_release,
        )
        result = malicious.install()
        assert result.accepted is False
        assert "archive" in result.message.lower()

        settings = InternetRemoteSettings(
            enabled=True,
            ddns_hostname="nc.example.test",
            public_ip="8.8.8.8",
            external_port=443,
            gateway_port=8788,
            acme_port=8780,
            account_email="owner@example.test",
            terms_accepted=True,
        )

        disagreement = iter((b"8.8.8.8", b"1.1.1.1"))
        manager = CertificateManager(
            settings,
            runtime_dir=root / "manager-disagreement",
            ip_fetcher=lambda _url, _timeout, _limit: next(disagreement),
            resolver=lambda _host: ("8.8.8.8",),
        )
        assert manager.detect_public_ip().accepted is False

        agreement = iter((b"8.8.8.8", b"8.8.8.8\n"))
        manager = CertificateManager(
            settings,
            runtime_dir=root / "manager",
            ip_fetcher=lambda _url, _timeout, _limit: next(agreement),
            resolver=lambda _host: ("8.8.8.8",),
        )
        public_ip = manager.detect_public_ip()
        assert public_ip.accepted is True
        assert public_ip.public_ip == "8.8.8.8"
        ddns = manager.resolve_ddns()
        assert ddns.accepted is True
        assert ddns.addresses == ("8.8.8.8",)

        command = manager.issue_command(staging=True)
        assert "--server=letsencrypt-staging" in command
        assert "--profile=shortlived" in command
        assert command.count("--domains") == 2
        assert "nc.example.test" in command
        assert "8.8.8.8" in command
        assert "--http.port=:8780" in command
        assert command[-1] == "--http"


def run_process_tests() -> None:
    from addons.main_chat_remote.internet_process import InternetGatewaySupervisor
    from addons.main_chat_remote.internet_settings import InternetRemoteSettings

    with tempfile.TemporaryDirectory(prefix="nc-internet-process-") as temp_dir:
        runtime_dir = Path(temp_dir)
        settings = InternetRemoteSettings(
            enabled=True,
            ddns_hostname="nc.example.test",
            public_ip="8.8.8.8",
            external_port=443,
            gateway_host="0.0.0.0",
            gateway_port=8788,
            acme_port=8780,
            account_email="owner@example.test",
            terms_accepted=True,
        )
        supervisor = InternetGatewaySupervisor(app_root=ROOT, runtime_dir=runtime_dir)
        command, environment = supervisor.build_launch(settings, upstream_code="654321")
        command_text = subprocess.list2cmdline(command)
        assert "654321" not in command_text
        assert environment["NC_MAIN_CHAT_INTERNET_UPSTREAM_CODE"] == "654321"
        assert environment["NC_MAIN_CHAT_INTERNET_REGISTRY_FILE"]
        assert environment["NC_MAIN_CHAT_INTERNET_SIGNING_KEY_FILE"]
        public = json.dumps(supervisor.public_launch_snapshot(command, environment))
        assert "654321" not in public
        assert "NC_MAIN_CHAT_INTERNET_UPSTREAM_CODE" not in public
        assert "--allowed-host" in command
        assert "nc.example.test" in command
        assert "8.8.8.8" in command


def _wait_until(predicate: Callable[[], bool], timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return bool(predicate())


def run_controller_tests() -> None:
    from addons.main_chat_remote.controller import MainChatRemoteController

    class Context:
        def __init__(self, app_root: Path):
            self.app_root = app_root
            self.logger = None

        @staticmethod
        def get_service(_name: str):
            return None

    class FakeBridge:
        running = True

        def stop(self) -> None:
            self.running = False

        @staticmethod
        def status_snapshot() -> dict[str, Any]:
            return {
                "enabled": True,
                "running": True,
                "host": "127.0.0.1",
                "port": 8776,
                "url": "http://127.0.0.1:8776",
            }

    class FakeBackend:
        def __init__(self):
            self.running = True

        def status_snapshot(self) -> dict[str, Any]:
            return {"running": self.running, "pairing_code": "654321" if self.running else ""}

        def start(self, **_kwargs: object) -> dict[str, Any]:
            self.running = True
            return {"accepted": True, "running": True, "pairing_code": "654321"}

        def stop(self) -> dict[str, Any]:
            self.running = False
            return {"accepted": True, "running": False}

    class FakeCertificateManager:
        def status_snapshot(self) -> dict[str, Any]:
            return {
                "certificate_exists": True,
                "private_key_exists": True,
                "expires_at": time.time() + 86_400,
            }

    class FakeSupervisor:
        def __init__(self):
            self.start_count = 0
            self.stop_count = 0
            self.running = False

        def start(self, _settings, *, upstream_code: str) -> dict[str, Any]:
            assert upstream_code == "654321"
            self.start_count += 1
            self.running = True
            return {"accepted": True, "running": True}

        def stop(self) -> dict[str, Any]:
            self.stop_count += 1
            self.running = False
            return {"accepted": True, "running": False}

        def status_snapshot(self) -> dict[str, Any]:
            return {"running": self.running}

    with tempfile.TemporaryDirectory(prefix="nc-internet-controller-") as temp_dir:
        controller = MainChatRemoteController(Context(Path(temp_dir)))
        backend = FakeBackend()
        supervisor = FakeSupervisor()
        controller.backend_process = backend
        controller._bridge = FakeBridge()
        controller._certificate_manager = FakeCertificateManager()
        controller._internet_supervisor = supervisor
        try:
            controller.set_internet_enabled(True)
            assert _wait_until(lambda: supervisor.start_count == 1)
            assert _wait_until(lambda: not controller._current_internet_task())
            assert controller.status_snapshot()["internet"]["settings"]["enabled"] is True
            controller.set_internet_enabled(False)
            assert _wait_until(lambda: supervisor.stop_count == 1)
            assert _wait_until(lambda: not controller._current_internet_task())
            assert backend.status_snapshot()["running"] is True
        finally:
            controller.shutdown()


def run_ui_tests() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6 import QtWidgets
    except Exception as exc:
        print(f"SKIP: PySide6 unavailable; Internet Remote panel was not tested: {exc}")
        return
    from addons.main_chat_remote.internet_panel import InternetRemotePanel

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    del application
    panel = InternetRemotePanel()
    panel.apply_snapshot(
        {
            "settings": {
                "enabled": True,
                "ddns_hostname": "nc.example.test",
                "public_ip": "8.8.8.8",
                "external_port": 443,
            },
            "gateway": {"running": False},
            "certificate": {"status": "renewal_failed", "retry_at": 1234.0},
            "last_error": "Certificate renewal failed.",
        }
    )
    checkbox = panel.findChild(QtWidgets.QCheckBox, "main_chat_internet_enabled_checkbox")
    assert checkbox is not None and checkbox.isChecked()
    assert "renewal failed" in panel.status_text().lower()
    assert panel.findChild(QtWidgets.QLineEdit, "main_chat_internet_ddns_edit").text() == "nc.example.test"
    panel.deleteLater()


SECTIONS: dict[str, tuple[Callable[[], None], str]] = {
    "auth": (run_auth_tests, "Internet Remote credential tests passed."),
    "certificate": (run_certificate_tests, "Internet Remote certificate tests passed."),
    "controller": (run_controller_tests, "Internet Remote controller tests passed."),
    "enrollment": (run_enrollment_tests, "Internet Remote enrollment tests passed."),
    "gateway-http": (run_gateway_http_tests, "Internet Remote HTTP gateway tests passed."),
    "lan": (run_lan_characterization_tests, "Internet Remote LAN characterization passed."),
    "media": (run_media_tests, "Internet Remote signed media tests passed."),
    "process": (run_process_tests, "Internet Remote process tests passed."),
    "settings": (run_settings_tests, "Internet Remote settings tests passed."),
    "ui": (run_ui_tests, "Internet Remote panel tests passed (or explicitly skipped)."),
    "websocket": (run_websocket_tests, "Internet Remote WebSocket tests passed."),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Main Chat Internet Remote smoke checks.")
    parser.add_argument("--section", choices=sorted(SECTIONS), default="")
    args = parser.parse_args(argv)
    selected = [args.section] if args.section else list(SECTIONS)
    for section in selected:
        check, message = SECTIONS[section]
        check()
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
