from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import threading
import time
import urllib.parse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from addons.main_chat_remote.internet_auth import (
    InternetCredentialStore,
    InternetDevice,
    SignedMediaGrant,
)


MAX_JSON_PAYLOAD_BYTES = 25 * 1024 * 1024
PROXY_CHUNK_BYTES = 64 * 1024
AUTH_FAILURE_LIMIT = 8
AUTH_FAILURE_WINDOW_SECONDS = 60.0
_SENSITIVE_QUERY_RE = re.compile(
    r"([?&](?:code|token|ticket|secret|signature|sig)=)([^&\s\"']+)",
    re.IGNORECASE,
)
_REQUEST_HEADER_ALLOWLIST = {
    "accept",
    "content-type",
    "if-modified-since",
    "if-none-match",
    "range",
    "user-agent",
}
_RESPONSE_HEADER_ALLOWLIST = {
    "accept-ranges",
    "content-length",
    "content-range",
    "content-type",
    "etag",
    "last-modified",
}


def redact_gateway_log(message: object) -> str:
    return _SENSITIVE_QUERY_RE.sub(r"\1<redacted>", str(message or ""))


class ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self) -> None:
        exclusive_option = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive_option is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive_option, 1)
        super().server_bind()


@dataclass(frozen=True)
class InternetGatewayConfig:
    host: str
    port: int
    cert_file: Path
    key_file: Path
    registry_file: Path
    signing_key_file: Path
    gateway_id: str
    allowed_public_hosts: tuple[str, ...]
    upstream_origin: str = "http://127.0.0.1:8777"
    upstream_pairing_code: str = ""
    tls_enabled: bool = True


class MainChatInternetGateway:
    def __init__(
        self,
        config: InternetGatewayConfig,
        *,
        logger: Callable[[str], None] | None = None,
    ):
        self.config = config
        self.credentials = InternetCredentialStore(
            config.registry_file,
            signing_key_path=config.signing_key_file,
        )
        self._logger = logger or print
        self._server: ExclusiveThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._auth_failures: dict[str, list[float]] = {}
        self._upstream_host, self._upstream_port = self._validated_upstream(config.upstream_origin)
        self._validate_config()

    @property
    def local_origin(self) -> str:
        server = self._server
        port = int(server.server_address[1]) if server is not None else int(self.config.port)
        scheme = "https" if self.config.tls_enabled else "http"
        host = self.config.host
        display_host = "127.0.0.1" if host in {"", "0.0.0.0", "::"} else host
        if ":" in display_host and not display_host.startswith("["):
            display_host = f"[{display_host}]"
        return f"{scheme}://{display_host}:{port}"

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            server = self._create_server()
            self._server = server
            thread = threading.Thread(
                target=server.serve_forever,
                name="nc-main-chat-internet-gateway",
                daemon=True,
            )
            self._thread = thread
            thread.start()

    def serve_forever(self) -> None:
        with self._lock:
            if self._server is not None:
                raise RuntimeError("Internet gateway is already running.")
            self._server = self._create_server()
            server = self._server
        try:
            server.serve_forever()
        finally:
            server.server_close()
            with self._lock:
                self._server = None

    def stop(self) -> None:
        with self._lock:
            server = self._server
            thread = self._thread
            self._server = None
            self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3.0)

    def _create_server(self) -> ExclusiveThreadingHTTPServer:
        server = ExclusiveThreadingHTTPServer(
            (str(self.config.host), int(self.config.port)),
            self._handler_class(),
        )
        if self.config.tls_enabled:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(str(self.config.cert_file), str(self.config.key_file))
            server.socket = context.wrap_socket(server.socket, server_side=True)
        return server

    def _validate_config(self) -> None:
        code = str(self.config.upstream_pairing_code or "").strip()
        if not (4 <= len(code) <= 9 and code.isdigit()):
            raise ValueError("A valid internal LAN pairing code is required.")
        if not self.config.gateway_id or self.config.gateway_id != self.credentials.gateway_id:
            raise ValueError("Internet gateway identity does not match the credential registry.")
        if not 0 <= int(self.config.port) <= 65_535:
            raise ValueError("Invalid Internet gateway port.")
        if self.config.tls_enabled:
            for label, path in (("certificate", self.config.cert_file), ("private key", self.config.key_file)):
                if not Path(path).is_file() or Path(path).stat().st_size <= 0:
                    raise ValueError(f"Internet gateway {label} is missing or empty.")

    @staticmethod
    def _validated_upstream(origin: str) -> tuple[str, int]:
        parsed = urllib.parse.urlsplit(str(origin or ""))
        if (
            parsed.scheme != "http"
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Internet gateway upstream must be a fixed loopback HTTP origin.")
        host = str(parsed.hostname or "").strip().lower()
        try:
            loopback = host == "localhost" or bool(ipaddress.ip_address(host).is_loopback)
        except ValueError:
            loopback = False
        if not loopback:
            raise ValueError("Internet gateway upstream must use loopback.")
        try:
            port = int(parsed.port or 80)
        except ValueError as exc:
            raise ValueError("Internet gateway upstream port is invalid.") from exc
        return host, port

    def _record_auth_failure(self, address: str) -> int:
        now = time.time()
        cutoff = now - AUTH_FAILURE_WINDOW_SECONDS
        with self._lock:
            failures = [stamp for stamp in self._auth_failures.get(address, ()) if stamp >= cutoff]
            failures.append(now)
            self._auth_failures[address] = failures
            return len(failures)

    def _clear_auth_failures(self, address: str) -> None:
        with self._lock:
            self._auth_failures.pop(address, None)

    def _log(self, message: object) -> None:
        self._logger(f"[MainChatInternet] {redact_gateway_log(message)}")

    def _handler_class(self):
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "NCMainChatInternet/0.1"

            def log_message(self, fmt: str, *args: object) -> None:
                client = self.client_address[0] if self.client_address else "?"
                gateway._log(f"{client} - {fmt % args}")

            def do_GET(self) -> None:
                self._handle("GET")

            def do_POST(self) -> None:
                self._handle("POST")

            def do_OPTIONS(self) -> None:
                self._send_json({"ok": False, "error": "Method not allowed"}, status=405)

            def _handle(self, method: str) -> None:
                try:
                    parsed = self._validated_target()
                    path = parsed.path.rstrip("/") or "/"
                    if path == "/health":
                        self._send_json(
                            {
                                "ok": True,
                                "service": "nc_main_chat_internet",
                                "gateway_id": gateway.config.gateway_id,
                                "status": "ready",
                            }
                        )
                        return
                    if path == "/internet/enroll/submit" and method == "POST":
                        self._submit_enrollment()
                        return
                    if path == "/internet/enroll/status" and method == "GET":
                        self._enrollment_status(parsed.query)
                        return
                    if path == "/internet/ws-ticket" and method == "POST":
                        device = self._authorize_or_send()
                        if device is not None:
                            self._read_json()
                            ticket = gateway.credentials.issue_ws_ticket(device.device_id)
                            self._send_json({"ok": True, "ticket": ticket, "expires_in": 30})
                        return
                    if path == "/internet/media-ticket" and method == "POST":
                        device = self._authorize_or_send()
                        if device is not None:
                            self._issue_media_ticket(device)
                        return
                    if path == "/media" and method == "GET":
                        self._serve_signed_media(parsed.query)
                        return
                    if path == "/ws" and method == "GET":
                        self._handle_websocket(parsed.query)
                        return
                    if not path.startswith("/api/"):
                        self._send_json({"ok": False, "error": "Not found"}, status=404)
                        return
                    if self._authorize_or_send() is None:
                        return
                    self._proxy(method, parsed)
                except ValueError as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=400)
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    return
                except (OSError, http.client.HTTPException) as exc:
                    self._send_json(
                        {"ok": False, "error": f"LAN backend unavailable: {exc}"},
                        status=502,
                    )
                except Exception as exc:
                    gateway._log(f"Request failed: {type(exc).__name__}")
                    self._send_json({"ok": False, "error": "Internet gateway error"}, status=500)

            def _submit_enrollment(self) -> None:
                payload = self._read_json()
                pending = gateway.credentials.submit_enrollment(
                    str(payload.get("enrollment_id") or ""),
                    str(payload.get("secret") or ""),
                    device_id=payload.get("device_id"),
                    device_name=payload.get("device_name"),
                )
                self._send_json(
                    {
                        "ok": True,
                        "status": pending.status,
                        "enrollment_id": pending.enrollment_id,
                        "device_id": pending.device_id,
                        "device_name": pending.device_name,
                        "expires_at": pending.expires_at,
                    }
                )

            def _enrollment_status(self, query: str) -> None:
                params = urllib.parse.parse_qs(query, keep_blank_values=True)
                enrollment_id = str(params.get("enrollment_id", [""])[0] or "")
                secret = str(params.get("secret", [""])[0] or "")
                pending = gateway.credentials.get_enrollment(enrollment_id, secret)
                if pending.status != "approved":
                    self._send_json(
                        {
                            "ok": True,
                            "status": pending.status,
                            "enrollment_id": pending.enrollment_id,
                            "expires_at": pending.expires_at,
                        }
                    )
                    return
                issued = gateway.credentials.complete_enrollment(enrollment_id, secret)
                self._send_json(
                    {
                        "ok": True,
                        "status": "complete",
                        "device_id": issued.device_id,
                        "device_token": issued.token,
                        "gateway_id": gateway.config.gateway_id,
                    }
                )

            def _issue_media_ticket(self, device: InternetDevice) -> None:
                self._validated_public_host()
                payload = self._read_json()
                target_path = str(payload.get("path") or "")
                raw_params = payload.get("params")
                if isinstance(raw_params, dict) and raw_params:
                    parsed_target = urllib.parse.urlsplit(target_path)
                    query = urllib.parse.parse_qsl(parsed_target.query, keep_blank_values=True)
                    query.extend(
                        (str(key), str(value))
                        for key, value in raw_params.items()
                        if value is not None and str(value) != ""
                    )
                    target_path = f"{parsed_target.path}?{urllib.parse.urlencode(query)}"
                grant = gateway.credentials.sign_media(
                    device.device_id,
                    target_path,
                    str(payload.get("method") or "GET"),
                )
                query = urllib.parse.urlencode(
                    {
                        "device_id": grant.device_id,
                        "path": grant.path,
                        "method": grant.method,
                        "expires": f"{grant.expires_at:.6f}",
                        "nonce": grant.nonce,
                        "signature": grant.signature,
                    }
                )
                self._send_json(
                    {
                        "ok": True,
                        "url": f"/media?{query}",
                        "expires_at": grant.expires_at,
                    }
                )

            def _serve_signed_media(self, query: str) -> None:
                params = urllib.parse.parse_qs(query, keep_blank_values=True)
                try:
                    grant = SignedMediaGrant(
                        device_id=str(params.get("device_id", [""])[0] or ""),
                        path=str(params.get("path", [""])[0] or ""),
                        method=str(params.get("method", [""])[0] or "").upper(),
                        expires_at=float(params.get("expires", ["0"])[0] or 0.0),
                        nonce=str(params.get("nonce", [""])[0] or ""),
                        signature=str(params.get("signature", [""])[0] or ""),
                    )
                except (TypeError, ValueError):
                    self._send_json({"ok": False, "error": "Unauthorized"}, status=401)
                    return
                device = gateway.credentials.verify_media(grant, "GET")
                if device is None:
                    self._send_json({"ok": False, "error": "Unauthorized"}, status=401)
                    return
                self._proxy("GET", urllib.parse.urlsplit(grant.path))

            def _validated_public_host(self) -> str:
                raw_host = str(self.headers.get("Host") or "").strip()
                try:
                    hostname = str(urllib.parse.urlsplit(f"//{raw_host}").hostname or "").lower()
                except ValueError as exc:
                    raise ValueError("Invalid Host header.") from exc
                allowed = {str(item).strip().strip("[]").lower() for item in gateway.config.allowed_public_hosts}
                if hostname not in allowed:
                    raise ValueError("Host is not configured for Internet Remote.")
                return hostname

            def _validated_target(self) -> urllib.parse.SplitResult:
                raw = str(self.path or "")
                parsed = urllib.parse.urlsplit(raw)
                if parsed.scheme or parsed.netloc or not parsed.path.startswith("/") or parsed.path.startswith("//"):
                    raise ValueError("Invalid request target.")
                return parsed

            def _authorize_or_send(self) -> InternetDevice | None:
                authorization = str(self.headers.get("Authorization") or "")
                scheme, separator, token = authorization.partition(" ")
                device = None
                if separator and scheme.lower() == "bearer" and token and " " not in token:
                    device = gateway.credentials.authenticate(token)
                client = self.client_address[0] if self.client_address else ""
                if device is not None:
                    gateway._clear_auth_failures(client)
                    return device
                failures = gateway._record_auth_failure(client)
                if failures > AUTH_FAILURE_LIMIT:
                    self._send_json(
                        {"ok": False, "error": "Too many invalid authentication attempts. Wait before retrying."},
                        status=429,
                    )
                else:
                    self._send_json({"ok": False, "error": "Unauthorized"}, status=401)
                return None

            def _handle_websocket(self, query: str) -> None:
                if str(self.headers.get("Upgrade") or "").strip().lower() != "websocket":
                    self._send_json({"ok": False, "error": "Invalid WebSocket upgrade request."}, status=400)
                    return
                connection_tokens = {
                    item.strip().lower()
                    for item in str(self.headers.get("Connection") or "").split(",")
                }
                key = str(self.headers.get("Sec-WebSocket-Key") or "").strip()
                version = str(self.headers.get("Sec-WebSocket-Version") or "").strip()
                try:
                    valid_key = len(base64.b64decode(key.encode("ascii"), validate=True)) == 16
                except Exception:
                    valid_key = False
                if "upgrade" not in connection_tokens or version != "13" or not valid_key:
                    self._send_json({"ok": False, "error": "Invalid WebSocket upgrade request."}, status=400)
                    return
                params = urllib.parse.parse_qs(query, keep_blank_values=True)
                ticket = str(params.get("ticket", [""])[0] or "")
                device = gateway.credentials.consume_ws_ticket(ticket)
                if device is None:
                    self._send_json({"ok": False, "error": "Unauthorized"}, status=401)
                    return
                upstream = socket.create_connection(
                    (gateway._upstream_host, gateway._upstream_port),
                    timeout=5.0,
                )
                try:
                    upstream.settimeout(5.0)
                    host_header = f"{gateway._upstream_host}:{gateway._upstream_port}"
                    request_lines = [
                        "GET /ws HTTP/1.1",
                        f"Host: {host_header}",
                        "Upgrade: websocket",
                        "Connection: Upgrade",
                        f"Sec-WebSocket-Key: {key}",
                        "Sec-WebSocket-Version: 13",
                        f"X-NC-Phone-Code: {gateway.config.upstream_pairing_code}",
                    ]
                    protocol = str(self.headers.get("Sec-WebSocket-Protocol") or "").strip()
                    if protocol:
                        request_lines.append(f"Sec-WebSocket-Protocol: {protocol}")
                    upstream.sendall(("\r\n".join(request_lines) + "\r\n\r\n").encode("ascii"))
                    response_header, remainder = self._read_socket_headers(upstream)
                    status_line, upstream_headers = self._parse_upstream_upgrade(response_header)
                    if not status_line.startswith("HTTP/") or " 101 " not in f"{status_line} ":
                        raise ConnectionError("LAN backend rejected the WebSocket upgrade.")
                    expected_accept = base64.b64encode(
                        hashlib.sha1(
                            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
                        ).digest()
                    ).decode("ascii")
                    if upstream_headers.get("sec-websocket-accept", "") != expected_accept:
                        raise ConnectionError("LAN backend returned an invalid WebSocket handshake.")
                    self.send_response(101, "Switching Protocols")
                    self.send_header("Upgrade", "websocket")
                    self.send_header("Connection", "Upgrade")
                    self.send_header("Sec-WebSocket-Accept", expected_accept)
                    selected_protocol = upstream_headers.get("sec-websocket-protocol", "")
                    if selected_protocol:
                        self.send_header("Sec-WebSocket-Protocol", selected_protocol)
                    self.end_headers()
                    self.wfile.flush()
                    self.close_connection = True
                    self._tunnel_websocket(upstream, remainder)
                finally:
                    try:
                        upstream.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    upstream.close()

            @staticmethod
            def _read_socket_headers(source: socket.socket) -> tuple[bytes, bytes]:
                received = b""
                while b"\r\n\r\n" not in received:
                    chunk = source.recv(4096)
                    if not chunk:
                        raise ConnectionError("LAN backend closed during WebSocket upgrade.")
                    received += chunk
                    if len(received) > 65_536:
                        raise ValueError("LAN backend WebSocket headers are too large.")
                header, _separator, remainder = received.partition(b"\r\n\r\n")
                return header, remainder

            @staticmethod
            def _parse_upstream_upgrade(header: bytes) -> tuple[str, dict[str, str]]:
                lines = header.decode("iso-8859-1").split("\r\n")
                status_line = lines[0] if lines else ""
                headers: dict[str, str] = {}
                for line in lines[1:]:
                    name, separator, value = line.partition(":")
                    if separator:
                        headers[name.strip().lower()] = value.strip()
                return status_line, headers

            def _tunnel_websocket(self, upstream: socket.socket, initial_upstream: bytes) -> None:
                stop_event = threading.Event()
                upstream.settimeout(0.5)
                self.connection.settimeout(0.5)
                if initial_upstream:
                    self.connection.sendall(initial_upstream)

                def copy(source: socket.socket, destination: socket.socket) -> None:
                    try:
                        while not stop_event.is_set():
                            try:
                                chunk = source.recv(PROXY_CHUNK_BYTES)
                            except socket.timeout:
                                continue
                            if not chunk:
                                break
                            destination.sendall(chunk)
                    except OSError:
                        pass
                    finally:
                        stop_event.set()

                threads = (
                    threading.Thread(
                        target=copy,
                        args=(self.connection, upstream),
                        name="nc-internet-ws-client-to-lan",
                        daemon=True,
                    ),
                    threading.Thread(
                        target=copy,
                        args=(upstream, self.connection),
                        name="nc-internet-ws-lan-to-client",
                        daemon=True,
                    ),
                )
                for thread in threads:
                    thread.start()
                stop_event.wait()
                for endpoint in (self.connection, upstream):
                    try:
                        endpoint.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                for thread in threads:
                    thread.join(timeout=1.0)

            def _proxy(self, method: str, parsed: urllib.parse.SplitResult) -> None:
                body = self._read_body() if method == "POST" else None
                query = [
                    (key, value)
                    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
                    if key.lower() not in {"code", "token", "ticket", "secret", "signature", "sig"}
                ]
                target = parsed.path
                if query:
                    target = f"{target}?{urllib.parse.urlencode(query)}"
                headers = {
                    key: value
                    for key, value in self.headers.items()
                    if key.lower() in _REQUEST_HEADER_ALLOWLIST
                }
                headers["X-NC-Phone-Code"] = gateway.config.upstream_pairing_code
                headers["Connection"] = "close"
                if body is not None:
                    headers["Content-Length"] = str(len(body))
                connection = http.client.HTTPConnection(
                    gateway._upstream_host,
                    gateway._upstream_port,
                    timeout=35.0,
                )
                try:
                    connection.request(method, target, body=body, headers=headers)
                    response = connection.getresponse()
                    self.send_response(int(response.status), str(response.reason or ""))
                    for key, value in response.getheaders():
                        if key.lower() in _RESPONSE_HEADER_ALLOWLIST:
                            self.send_header(key, value)
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.close_connection = True
                    while True:
                        chunk = response.read(PROXY_CHUNK_BYTES)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                    self.wfile.flush()
                finally:
                    connection.close()

            def _read_body(self) -> bytes:
                if str(self.headers.get("Transfer-Encoding") or "").strip():
                    raise ValueError("Chunked request bodies are not supported.")
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError as exc:
                    raise ValueError("Invalid Content-Length.") from exc
                if length < 0 or length > MAX_JSON_PAYLOAD_BYTES:
                    raise ValueError("Payload too large.")
                return self.rfile.read(length) if length else b""

            def _read_json(self) -> dict[str, object]:
                body = self._read_body()
                if not body:
                    return {}
                try:
                    payload = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError("Malformed JSON.") from exc
                if not isinstance(payload, dict):
                    raise ValueError("JSON object expected.")
                return payload

            def _send_json(self, payload: dict[str, object], *, status: int = 200) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                if status == 401:
                    self.send_header("WWW-Authenticate", "Bearer")
                self.end_headers()
                self.close_connection = True
                self.wfile.write(body)
                self.wfile.flush()

        return Handler


def _existing_nonempty_file(value: str, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError(f"{label} is missing or empty: {path}")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NeuralCompanion secure Internet phone gateway.")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--cert-file", required=True)
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--registry-file", default="")
    parser.add_argument("--signing-key-file", default="")
    parser.add_argument("--allowed-host", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        cert_file = _existing_nonempty_file(args.cert_file, "Certificate")
        key_file = _existing_nonempty_file(args.key_file, "Private key")
        registry_value = args.registry_file or os.environ.get("NC_MAIN_CHAT_INTERNET_REGISTRY_FILE", "")
        signing_key_value = args.signing_key_file or os.environ.get("NC_MAIN_CHAT_INTERNET_SIGNING_KEY_FILE", "")
        registry_file = _existing_nonempty_file(registry_value, "Credential registry")
        signing_key_file = _existing_nonempty_file(signing_key_value, "Signing key")
        pairing_code = str(os.environ.get("NC_MAIN_CHAT_INTERNET_UPSTREAM_CODE") or "").strip()
        credentials = InternetCredentialStore(
            registry_file,
            signing_key_path=signing_key_file,
        )
        config = InternetGatewayConfig(
            host=args.host,
            port=args.port,
            cert_file=cert_file,
            key_file=key_file,
            registry_file=registry_file,
            signing_key_file=signing_key_file,
            gateway_id=credentials.gateway_id,
            allowed_public_hosts=tuple(str(item).strip().lower() for item in args.allowed_host if str(item).strip()),
            upstream_pairing_code=pairing_code,
        )
        gateway = MainChatInternetGateway(config)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    gateway.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
