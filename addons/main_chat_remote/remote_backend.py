from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import ipaddress
import json
import os
import re
import secrets
import socket
import struct
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


DEFAULT_REMOTE_HOST = "0.0.0.0"
DEFAULT_REMOTE_PORT = 8777
DEFAULT_BRIDGE_URL = "http://127.0.0.1:8776"
PAIRING_CODE_DIGITS = 6
PAIRING_CODE_MIN_DIGITS = 4
PAIRING_CODE_MAX_DIGITS = 9
MAX_JSON_PAYLOAD_BYTES = 25 * 1024 * 1024
MAX_WS_PAYLOAD_BYTES = 1024 * 1024
DEFAULT_BRIDGE_TIMEOUT_SECONDS = 10.0
HEALTH_BRIDGE_TIMEOUT_SECONDS = 0.75
WEBSOCKET_STATE_BRIDGE_TIMEOUT_SECONDS = 2.0
BRIDGE_INFO_WATCH_INTERVAL_SECONDS = 1.0
WEBSOCKET_AUDIO_INTERVAL_SECONDS = 0.25
WEBSOCKET_AUDIO_BRIDGE_TIMEOUT_SECONDS = 1.0
WEBSOCKET_BRIDGE_RESULT_POLL_SECONDS = 0.05
WEBSOCKET_FRAME_TIMEOUT_SECONDS = 5.0
AUTH_FAILURE_LIMIT = 8
AUTH_FAILURE_WINDOW_SECONDS = 60.0
BRIDGE_QUERY_DROP_KEYS = {"code", "token"}
SENSITIVE_QUERY_VALUE_RE = re.compile(r"([?&](?:code|token)=)([^&\s\"']+)", re.IGNORECASE)
BRIDGE_INFO_MAX_AGE_SECONDS = 10 * 60.0
BRIDGE_INFO_MAX_FUTURE_SKEW_SECONDS = 60.0
LAN_IPV4_NETWORKS = tuple(
    ipaddress.ip_network(item)
    for item in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
LAN_IPV6_NETWORKS = (ipaddress.ip_network("fc00::/7"),)
LOW_PRIORITY_DISPLAY_IPV4_NETWORKS = tuple(
    ipaddress.ip_network(item)
    for item in (
        "192.168.56.0/24",  # Common VirtualBox host-only adapter range.
    )
)


class ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self) -> None:
        exclusive_option = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive_option is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive_option, 1)
        super().server_bind()


def generate_pairing_code(digits: int = PAIRING_CODE_DIGITS) -> str:
    digits = max(PAIRING_CODE_MIN_DIGITS, min(PAIRING_CODE_MAX_DIGITS, int(digits or PAIRING_CODE_DIGITS)))
    floor = 10 ** (digits - 1)
    return str(floor + secrets.randbelow(9 * floor))


def normalize_pairing_code(value: str, *, max_digits: int = PAIRING_CODE_MAX_DIGITS) -> str:
    digits = "".join(ch for ch in str(value or "") if "0" <= ch <= "9")[: max(1, int(max_digits or PAIRING_CODE_MAX_DIGITS))]
    if len(digits) < PAIRING_CODE_MIN_DIGITS:
        return ""
    return digits


def redact_sensitive_query_values(message: str) -> str:
    return SENSITIVE_QUERY_VALUE_RE.sub(r"\1<redacted>", str(message or ""))


def public_bridge_health_snapshot(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(payload or {})
    public: dict[str, Any] = {}
    for key in ("ok", "status", "error", "service"):
        if key in data:
            public[key] = data.get(key)
    bridge = data.get("bridge")
    if isinstance(bridge, dict):
        nested = {}
        for key in ("enabled", "running", "started_at"):
            if key in bridge:
                nested[key] = bridge.get(key)
        if nested:
            public["bridge"] = nested
    return public


def audio_snapshot_signature(payload: dict[str, Any]) -> tuple[int, int, str]:
    audio = dict(payload or {})
    items = list(audio.get("items") or [])
    latest_id = str(dict(items[-1]).get("id") or "") if items else ""
    return int(audio.get("generation") or 0), len(items), latest_id


def lan_ip_address() -> str:
    candidates: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM):
            address = str(info[4][0])
            if address and address not in candidates:
                candidates.append(address)
    except Exception:
        pass
    ranked = [
        (lan_ip_display_sort_key(address), address)
        for address in candidates
        if lan_ip_display_sort_key(address)[0] < 99
    ]
    if ranked:
        return sorted(ranked, key=lambda item: item[0])[0][1]
    return "127.0.0.1"


def lan_ip_display_sort_key(address: str) -> tuple[int, int]:
    try:
        ip = ipaddress.ip_address(str(address or "").split("%", 1)[0])
    except Exception:
        return (99, 0)
    if ip.version != 4 or ip.is_loopback or ip.is_link_local or not local_network_client(address):
        return (99, int(ip) if ip.version == 4 else 0)
    if any(ip in network for network in LOW_PRIORITY_DISPLAY_IPV4_NETWORKS):
        return (2, int(ip))
    octets = str(ip).split(".")
    first = int(octets[0])
    second = int(octets[1])
    if first == 192 and second == 168:
        return (0, int(ip))
    if first == 172 and 16 <= second <= 31:
        return (3, int(ip))
    if first == 10:
        return (4, int(ip))
    return (5, int(ip))


def local_network_client(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(str(address or "").split("%", 1)[0])
    except Exception:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    if ip.is_loopback or ip.is_link_local:
        return True
    if ip.version == 4:
        return any(ip in network for network in LAN_IPV4_NETWORKS)
    if ip.version == 6:
        return any(ip in network for network in LAN_IPV6_NETWORKS)
    return False


def loopback_host(host: str) -> bool:
    text = str(host or "").strip().strip("[]").split("%", 1)[0].lower()
    if text == "localhost":
        return True
    try:
        return bool(ipaddress.ip_address(text).is_loopback)
    except Exception:
        return False


def normalize_bridge_url(value: str) -> str:
    text = str(value or DEFAULT_BRIDGE_URL).strip() or DEFAULT_BRIDGE_URL
    if "://" not in text:
        text = f"http://{text}"
    try:
        parsed = urllib.parse.urlparse(text)
        if parsed.scheme.lower() != "http" or parsed.username or parsed.password:
            return DEFAULT_BRIDGE_URL
        host = str(parsed.hostname or "").strip()
        if not loopback_host(host):
            return DEFAULT_BRIDGE_URL
        port = parsed.port
        host_part = f"[{host}]" if ":" in host and not host.startswith("[") else host
        return f"http://{host_part}{f':{port}' if port else ''}".rstrip("/")
    except Exception:
        return DEFAULT_BRIDGE_URL


class BridgeClient:
    def __init__(self, bridge_url: str, bridge_token: str, *, timeout_seconds: float = DEFAULT_BRIDGE_TIMEOUT_SECONDS):
        self.bridge_url = normalize_bridge_url(bridge_url)
        self.bridge_token = str(bridge_token or "").strip()
        self.timeout_seconds = max(0.1, float(timeout_seconds or DEFAULT_BRIDGE_TIMEOUT_SECONDS))

    def with_timeout(self, timeout_seconds: float) -> "BridgeClient":
        return BridgeClient(self.bridge_url, self.bridge_token, timeout_seconds=timeout_seconds)

    def build_request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> urllib.request.Request:
        target_path = str(path or "/")
        body = None
        headers = {"X-NC-Bridge-Token": self.bridge_token}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        return urllib.request.Request(f"{self.bridge_url}{target_path}", data=body, method=str(method or "GET").upper(), headers=headers)

    def open(self, method: str, path: str, payload: dict[str, Any] | None = None):
        return urllib.request.urlopen(self.build_request(method, path, payload), timeout=self.timeout_seconds)

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, bytes, str]:
        try:
            with self.open(method, path, payload) as response:
                return int(response.status), response.read(), str(response.headers.get("Content-Type") or "")
        except urllib.error.HTTPError as exc:
            return int(exc.code), exc.read(), str(exc.headers.get("Content-Type") or "")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            body = json.dumps(
                {"ok": False, "status": 502, "error": f"Bridge unavailable: {exc}"},
                ensure_ascii=False,
            ).encode("utf-8")
            return 502, body, "application/json; charset=utf-8"

    def json_request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        status, body, _content_type = self.request(method, path, payload)
        try:
            data = json.loads(body.decode("utf-8"))
        except Exception:
            data = {"ok": False, "error": body.decode("utf-8", errors="replace")}
        if isinstance(data, dict):
            data.setdefault("status", status)
            return data
        return {"ok": False, "status": status, "error": "Bridge returned non-object JSON."}


class MainChatRemoteBackend:
    def __init__(
        self,
        *,
        host: str = DEFAULT_REMOTE_HOST,
        port: int = DEFAULT_REMOTE_PORT,
        pairing_code: str = "",
        bridge_url: str = DEFAULT_BRIDGE_URL,
        bridge_token: str = "",
        bridge_info_path: str | Path | None = None,
        hide_pairing_code_output: bool = False,
    ):
        self.host = str(host or DEFAULT_REMOTE_HOST).strip() or DEFAULT_REMOTE_HOST
        self.port = max(1, min(65535, int(port or DEFAULT_REMOTE_PORT)))
        self.pairing_code = normalize_pairing_code(pairing_code) or generate_pairing_code()
        self.hide_pairing_code_output = bool(hide_pairing_code_output)
        self.bridge = BridgeClient(bridge_url, bridge_token)
        self.bridge_info_path = Path(bridge_info_path) if bridge_info_path else None
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._clients: dict[str, float] = {}
        self._auth_failures: dict[str, list[float]] = {}
        self._started_at = 0.0

    @property
    def running(self) -> bool:
        with self._lock:
            return self._server is not None and self._thread is not None and self._thread.is_alive()

    @property
    def display_host(self) -> str:
        if self.host in {"", "0.0.0.0", "::"}:
            return lan_ip_address()
        return self.host

    @property
    def display_url(self) -> str:
        return f"http://{self.display_host}:{self.port}"

    def pairing_code_display_text(self) -> str:
        if self.hide_pairing_code_output:
            return "configured by launcher"
        return self.pairing_code

    def bridge_info_is_current(self) -> bool:
        if self.bridge_info_path is None:
            return True
        try:
            payload = json.loads(self.bridge_info_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return False
        if not isinstance(payload, dict):
            return False
        if str(payload.get("service") or "").strip() != "nc_main_chat_bridge":
            return False
        if payload.get("enabled") is not True:
            return False
        token = str(payload.get("token") or "").strip()
        if not token or not secrets.compare_digest(token, self.bridge.bridge_token):
            return False
        try:
            updated_at = float(payload.get("updated_at"))
        except (TypeError, ValueError):
            return False
        age_seconds = time.time() - updated_at
        if age_seconds < -BRIDGE_INFO_MAX_FUTURE_SKEW_SECONDS or age_seconds > BRIDGE_INFO_MAX_AGE_SECONDS:
            return False
        bridge_url = normalize_bridge_url(str(payload.get("url") or DEFAULT_BRIDGE_URL))
        return bridge_url == self.bridge.bridge_url

    def clients_snapshot(self) -> list[dict[str, Any]]:
        cutoff = time.time() - 180.0
        with self._lock:
            self._clients = {host: stamp for host, stamp in self._clients.items() if stamp >= cutoff}
            return [
                {"address": host, "last_seen": stamp}
                for host, stamp in sorted(self._clients.items(), key=lambda item: item[1], reverse=True)
            ]

    def status_snapshot(self) -> dict[str, Any]:
        clients = self.clients_snapshot()
        return {
            "running": self.running,
            "host": self.host,
            "port": self.port,
            "url": self.display_url,
            "pairing_code_digits": len(self.pairing_code),
            "bridge_url": self.bridge.bridge_url,
            "connected_clients": len(clients),
            "clients": clients,
            "started_at": self._started_at,
        }

    def public_status_snapshot(self) -> dict[str, Any]:
        clients = self.clients_snapshot()
        return {
            "running": self.running,
            "host": self.host,
            "port": self.port,
            "url": self.display_url,
            "pairing_code_digits": len(self.pairing_code),
            "connected_clients": len(clients),
            "started_at": self._started_at,
        }

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            handler_cls = self._handler_class()
            server = ExclusiveThreadingHTTPServer((self.host, self.port), handler_cls)
            server.daemon_threads = True
            server.backend = self  # type: ignore[attr-defined]
            thread = threading.Thread(target=server.serve_forever, name="nc-main-chat-remote-http", daemon=True)
            self._server = server
            self._thread = thread
            self._started_at = time.time()
            thread.start()

    def stop(self) -> None:
        with self._lock:
            server = self._server
            self._server = None
            self._thread = None
        if server is None:
            return
        try:
            server.shutdown()
        finally:
            server.server_close()

    def serve_forever(self) -> None:
        self.start()
        print(f"Main Chat Remote LAN backend: {self.display_url}")
        print(f"Pairing code: {self.pairing_code_display_text()}")
        print(f"Bridge: {self.bridge.bridge_url}")
        try:
            while True:
                time.sleep(BRIDGE_INFO_WATCH_INTERVAL_SECONDS)
                if not self.bridge_info_is_current():
                    print("Main Chat Remote bridge stopped or changed; stopping LAN backend.")
                    break
        except KeyboardInterrupt:
            print("\nStopping Main Chat Remote LAN backend.")
        finally:
            self.stop()

    def record_client(self, address: str) -> None:
        if not address:
            return
        with self._lock:
            self._clients[str(address)] = time.time()

    def auth_failure_count(self, address: str) -> int:
        if not address:
            return 0
        with self._lock:
            return len(self._recent_auth_failures_locked(str(address), time.time()))

    def record_auth_failure(self, address: str) -> int:
        if not address:
            return 0
        with self._lock:
            host = str(address)
            now = time.time()
            failures = self._recent_auth_failures_locked(host, now)
            failures.append(now)
            self._auth_failures[host] = failures
            return len(failures)

    def clear_auth_failures(self, address: str) -> None:
        if not address:
            return
        with self._lock:
            self._auth_failures.pop(str(address), None)

    def _recent_auth_failures_locked(self, address: str, now: float) -> list[float]:
        cutoff = float(now) - AUTH_FAILURE_WINDOW_SECONDS
        failures = [stamp for stamp in self._auth_failures.get(address, []) if stamp >= cutoff]
        if failures:
            self._auth_failures[address] = failures
        else:
            self._auth_failures.pop(address, None)
        return failures

    def _handler_class(self):
        backend = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "NCMainChatRemote/0.1"

            def log_message(self, fmt: str, *args) -> None:
                line = redact_sensitive_query_values(fmt % args)
                print(f"[MainChatRemote] {self.client_address[0] if self.client_address else '?'} - {line}")

            def do_OPTIONS(self) -> None:
                client_ip = self.client_address[0] if self.client_address else ""
                if not local_network_client(client_ip):
                    self._send_json({"ok": False, "error": "LAN clients only"}, status=403)
                    return
                backend.record_client(client_ip)
                self._send_json({"ok": True})

            def do_GET(self) -> None:
                self._handle("GET")

            def do_POST(self) -> None:
                self._handle("POST")

            def _handle(self, method: str) -> None:
                client_ip = self.client_address[0] if self.client_address else ""
                if not local_network_client(client_ip):
                    self._send_json({"ok": False, "error": "LAN clients only"}, status=403)
                    return
                backend.record_client(client_ip)
                parsed = urlparse(self.path)
                path = parsed.path.rstrip("/") or "/"
                try:
                    if path == "/health":
                        bridge_health = backend.bridge.with_timeout(HEALTH_BRIDGE_TIMEOUT_SECONDS).json_request("GET", "/health")
                        ready = bool(bridge_health.get("ok") is True)
                        public_bridge_health = public_bridge_health_snapshot(bridge_health)
                        self._send_json(
                            {
                                "ok": ready,
                                "service": "nc_main_chat_remote",
                                "status": "ready" if ready else "bridge_unavailable",
                                "remote": backend.public_status_snapshot(),
                                "bridge": public_bridge_health,
                            }
                        )
                        return
                    if path == "/ws":
                        if not self._authorize_or_send(parsed.query):
                            return
                        self._handle_websocket()
                        return
                    if not path.startswith("/api/"):
                        self._send_json({"ok": False, "error": "Not found"}, status=404)
                        return
                    if not self._authorize_or_send(parsed.query):
                        return
                    if method == "GET":
                        bridge_path = self._bridge_path(path, parsed.query)
                        if path == "/api/musetalk/stream":
                            self._proxy_stream_get(bridge_path)
                        else:
                            self._proxy_get(bridge_path)
                        return
                    if method == "POST":
                        self._proxy_post(path)
                        return
                    self._send_json({"ok": False, "error": "Method not allowed"}, status=405)
                except ValueError as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=400)
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    return
                except Exception as exc:
                    self._send_json({"ok": False, "error": str(exc) or "Remote backend error"}, status=500)

            def _proxy_get(self, path: str) -> None:
                status, body, content_type = backend.bridge.request("GET", path)
                self._send_bytes(body, status=status, content_type=content_type or "application/octet-stream")

            def _proxy_stream_get(self, path: str) -> None:
                response = None
                headers_sent = False
                try:
                    response = backend.bridge.with_timeout(self._stream_bridge_timeout(path)).open("GET", path)
                    self.send_response(int(response.status))
                    self.send_header("Content-Type", str(response.headers.get("Content-Type") or "application/octet-stream"))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    headers_sent = True
                    while True:
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except urllib.error.HTTPError as exc:
                    if headers_sent:
                        return
                    self._send_bytes(exc.read(), status=int(exc.code), content_type=str(exc.headers.get("Content-Type") or "application/json; charset=utf-8"))
                except (BrokenPipeError, ConnectionError):
                    return
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    if not headers_sent:
                        body = json.dumps(
                            {"ok": False, "status": 502, "error": f"Bridge unavailable: {exc}"},
                            ensure_ascii=False,
                        ).encode("utf-8")
                        self._send_bytes(body, status=502, content_type="application/json; charset=utf-8")
                finally:
                    if response is not None:
                        try:
                            response.close()
                        except Exception:
                            pass

            def _proxy_post(self, path: str) -> None:
                payload = self._read_json()
                status, body, content_type = backend.bridge.request("POST", path, payload)
                self._send_bytes(body, status=status, content_type=content_type or "application/json; charset=utf-8")

            @staticmethod
            def _bridge_path(path: str, query: str) -> str:
                params = [
                    (key, value)
                    for key, value in urllib.parse.parse_qsl(str(query or ""), keep_blank_values=True)
                    if key.lower() not in BRIDGE_QUERY_DROP_KEYS
                ]
                if not params:
                    return path
                return f"{path}?{urllib.parse.urlencode(params)}"

            @staticmethod
            def _stream_bridge_timeout(path: str) -> float:
                try:
                    params = parse_qs(urlparse(str(path or "")).query)
                    wait_seconds = float(params.get("wait", ["2"])[0] or 2.0)
                except Exception:
                    wait_seconds = 2.0
                wait_seconds = max(0.0, min(30.0, wait_seconds))
                return max(1.0, min(DEFAULT_BRIDGE_TIMEOUT_SECONDS, wait_seconds + 1.0))

            def _authorized(self, query: str) -> bool:
                expected = backend.pairing_code
                provided = normalize_pairing_code(str(self.headers.get("X-NC-Phone-Code") or ""))
                if not provided:
                    provided = normalize_pairing_code(str(parse_qs(query).get("code", [""])[0] or ""))
                return bool(expected) and secrets.compare_digest(provided, expected)

            def _authorize_or_send(self, query: str) -> bool:
                client_ip = self.client_address[0] if self.client_address else ""
                if self._authorized(query):
                    backend.clear_auth_failures(client_ip)
                    return True
                failures = backend.record_auth_failure(client_ip)
                if failures > AUTH_FAILURE_LIMIT:
                    self._send_json(
                        {"ok": False, "error": "Too many invalid pairing attempts. Wait before retrying."},
                        status=429,
                    )
                    return False
                self._send_json({"ok": False, "error": "Unauthorized"}, status=401)
                return False

            def _read_json(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0:
                    return {}
                if length > MAX_JSON_PAYLOAD_BYTES:
                    raise ValueError("payload too large")
                data = self.rfile.read(length)
                try:
                    payload = json.loads(data.decode("utf-8"))
                except Exception as exc:
                    raise ValueError("malformed JSON") from exc
                if not isinstance(payload, dict):
                    raise ValueError("JSON object expected")
                return payload

            def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self._send_bytes(body, status=status, content_type="application/json; charset=utf-8")

            def _send_bytes(self, body: bytes, *, status: int = 200, content_type: str = "application/octet-stream") -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-NC-Phone-Code")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.end_headers()
                self.wfile.write(body)
                self.wfile.flush()

            def _handle_websocket(self) -> None:
                if not self._websocket_upgrade_requested():
                    self._send_json({"ok": False, "error": "Invalid WebSocket upgrade request."}, status=400)
                    return
                if str(self.headers.get("Sec-WebSocket-Version") or "").strip() != "13":
                    self._send_json({"ok": False, "error": "Unsupported WebSocket version."}, status=400)
                    return
                key = str(self.headers.get("Sec-WebSocket-Key") or "").strip()
                if not key:
                    self._send_json({"ok": False, "error": "Missing Sec-WebSocket-Key"}, status=400)
                    return
                try:
                    if len(base64.b64decode(key.encode("ascii"), validate=True)) != 16:
                        raise ValueError("wrong key length")
                except Exception:
                    self._send_json({"ok": False, "error": "Invalid Sec-WebSocket-Key"}, status=400)
                    return
                accept = base64.b64encode(
                    hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
                ).decode("ascii")
                self.send_response(101, "Switching Protocols")
                self.send_header("Upgrade", "websocket")
                self.send_header("Connection", "Upgrade")
                self.send_header("Sec-WebSocket-Accept", accept)
                self.end_headers()
                self.close_connection = True
                self.connection.settimeout(0.25)
                try:
                    self._send_ws_json({"type": "hello", "remote": backend.public_status_snapshot()})
                except OSError:
                    return
                state_bridge = backend.bridge.with_timeout(WEBSOCKET_STATE_BRIDGE_TIMEOUT_SECONDS)
                audio_bridge = backend.bridge.with_timeout(WEBSOCKET_AUDIO_BRIDGE_TIMEOUT_SECONDS)
                next_state_at = 0.0
                next_audio_at = 0.0
                last_audio_signature: tuple[int, int, str] | None = None
                bridge_executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=2,
                    thread_name_prefix="nc-main-chat-remote-ws-bridge",
                )
                state_future: concurrent.futures.Future[dict[str, Any]] | None = None
                audio_future: concurrent.futures.Future[dict[str, Any]] | None = None
                try:
                    while True:
                        now = time.time()
                        if state_future is not None and state_future.done():
                            state = state_future.result()
                            state_future = None
                            try:
                                self._send_ws_json({"type": "state", "payload": state})
                            except OSError:
                                return
                        if audio_future is not None and audio_future.done():
                            audio_response = audio_future.result()
                            audio_future = None
                            audio_payload = audio_response.get("audio")
                            if (
                                audio_response.get("status") == 200
                                and audio_response.get("ok") is True
                                and isinstance(audio_payload, dict)
                            ):
                                signature = audio_snapshot_signature(audio_payload)
                                if signature != last_audio_signature:
                                    try:
                                        self._send_ws_json({"type": "audio", "payload": audio_payload})
                                    except OSError:
                                        return
                                    last_audio_signature = signature
                        if state_future is None and now >= next_state_at:
                            state_future = bridge_executor.submit(state_bridge.json_request, "GET", "/api/state")
                            next_state_at = now + 1.0
                        if audio_future is None and now >= next_audio_at:
                            audio_future = bridge_executor.submit(audio_bridge.json_request, "GET", "/api/audio")
                            next_audio_at = now + WEBSOCKET_AUDIO_INTERVAL_SECONDS
                        if state_future is not None or audio_future is not None:
                            self.connection.settimeout(WEBSOCKET_BRIDGE_RESULT_POLL_SECONDS)
                        else:
                            self.connection.settimeout(WEBSOCKET_AUDIO_INTERVAL_SECONDS)
                        try:
                            frame = self._read_ws_frame()
                        except TimeoutError:
                            continue
                        except ValueError as exc:
                            try:
                                self._send_ws_json({"type": "error", "error": str(exc) or "Invalid WebSocket frame"})
                            except OSError:
                                pass
                            self._send_ws_close()
                            return
                        except (ConnectionError, OSError):
                            return
                        if frame is None:
                            return
                        opcode, payload = frame
                        if opcode == 0x8:
                            self._send_ws_close()
                            return
                        if opcode == 0x9:
                            try:
                                self._send_ws_frame(0xA, payload)
                            except OSError:
                                return
                            continue
                        if opcode == 0xA:
                            continue
                        if opcode != 0x1:
                            continue
                        self._handle_ws_text(payload.decode("utf-8", errors="replace"))
                finally:
                    if state_future is not None:
                        state_future.cancel()
                    if audio_future is not None:
                        audio_future.cancel()
                    bridge_executor.shutdown(wait=False, cancel_futures=True)

            def _websocket_upgrade_requested(self) -> bool:
                upgrade = str(self.headers.get("Upgrade") or "").strip().lower()
                if upgrade != "websocket":
                    return False
                connection_values = self.headers.get_all("Connection") or []
                if not connection_values:
                    connection_values = [str(self.headers.get("Connection") or "")]
                tokens = {
                    token.strip().lower()
                    for value in connection_values
                    for token in str(value or "").split(",")
                    if token.strip()
                }
                return "upgrade" in tokens

            def _handle_ws_text(self, text: str) -> None:
                try:
                    message = json.loads(text)
                except Exception:
                    self._send_ws_json({"type": "error", "error": "malformed JSON"})
                    return
                if not isinstance(message, dict):
                    self._send_ws_json({"type": "error", "error": "JSON object expected"})
                    return
                msg_type = str(message.get("type") or "").strip()
                request_id = str(message.get("request_id") or "").strip()

                def send_response(response_type: str, payload: dict[str, Any]) -> None:
                    response = {"type": response_type, "payload": payload}
                    if request_id:
                        response["request_id"] = request_id
                    self._send_ws_json(response)

                if msg_type in {"send", "send_text"}:
                    payload = dict(message.get("payload") or {}) if isinstance(message.get("payload"), dict) else {}
                    payload["text"] = str(message.get("text") or payload.get("text") or "")
                    for key in ("play_on_backend", "capture_phone_audio", "visual_after_send"):
                        if key in message:
                            payload[key] = message.get(key)
                    result = backend.bridge.json_request("POST", "/api/send", payload)
                    send_response("send_result", result)
                    return
                if msg_type == "control":
                    payload = dict(message.get("payload") or {}) if isinstance(message.get("payload"), dict) else {}
                    payload["action"] = str(message.get("action") or payload.get("action") or "")
                    for key in ("play_on_backend", "capture_phone_audio"):
                        if key in message:
                            payload[key] = message.get(key)
                    result = backend.bridge.json_request("POST", "/api/control", payload)
                    send_response("control_result", result)
                    return
                if msg_type in {"engine_start", "engine_stop"}:
                    target = "/api/engine/start" if msg_type == "engine_start" else "/api/engine/stop"
                    result = backend.bridge.json_request("POST", target, {})
                    send_response(f"{msg_type}_result", result)
                    return
                if msg_type == "visual":
                    payload = message.get("payload") or {}
                    if not isinstance(payload, dict):
                        response = {"type": "error", "error": "visual payload must be an object"}
                        if request_id:
                            response["request_id"] = request_id
                        self._send_ws_json(response)
                        return
                    result = backend.bridge.json_request("POST", "/api/visual", dict(payload))
                    send_response("visual_result", result)
                    return
                if msg_type == "state":
                    result = backend.bridge.with_timeout(WEBSOCKET_STATE_BRIDGE_TIMEOUT_SECONDS).json_request("GET", "/api/state")
                    self._send_ws_json({"type": "state", "payload": result})
                    return
                response = {"type": "error", "error": f"Unsupported message type: {msg_type}"}
                if request_id:
                    response["request_id"] = request_id
                self._send_ws_json(response)

            def _read_ws_frame(self) -> tuple[int, bytes] | None:
                try:
                    header = self._recv_exact(2, idle_timeout_ok=True)
                except EOFError:
                    return None
                except socket.timeout as exc:
                    raise TimeoutError() from exc
                first, second = header[0], header[1]
                opcode = first & 0x0F
                masked = bool(second & 0x80)
                length = second & 0x7F
                if not masked:
                    raise ValueError("WebSocket client frames must be masked")
                if length == 126:
                    length = struct.unpack("!H", self._recv_exact(2))[0]
                elif length == 127:
                    length = struct.unpack("!Q", self._recv_exact(8))[0]
                if length > MAX_WS_PAYLOAD_BYTES:
                    raise ValueError("WebSocket message too large")
                mask = self._recv_exact(4) if masked else b""
                payload = self._recv_exact(length) if length else b""
                if masked and mask:
                    payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
                return opcode, payload

            def _recv_exact(self, length: int, *, idle_timeout_ok: bool = False) -> bytes:
                chunks = []
                remaining = int(length)
                deadline = time.time() + WEBSOCKET_FRAME_TIMEOUT_SECONDS
                while remaining > 0:
                    try:
                        chunk = self.connection.recv(remaining)
                    except socket.timeout as exc:
                        if not chunks and idle_timeout_ok:
                            raise
                        if time.time() >= deadline:
                            raise ValueError("Timed out reading WebSocket frame") from exc
                        continue
                    if not chunk:
                        if not chunks and idle_timeout_ok:
                            raise EOFError()
                        raise ConnectionError("WebSocket closed")
                    chunks.append(chunk)
                    remaining -= len(chunk)
                return b"".join(chunks)

            def _send_ws_json(self, payload: dict[str, Any]) -> None:
                self._send_ws_text(json.dumps(payload, ensure_ascii=False))

            def _send_ws_text(self, text: str) -> None:
                self._send_ws_frame(0x1, text.encode("utf-8"))

            def _send_ws_frame(self, opcode: int, body: bytes) -> None:
                header = bytearray([0x80 | (int(opcode) & 0x0F)])
                length = len(body)
                if length < 126:
                    header.append(length)
                elif length <= 0xFFFF:
                    header.append(126)
                    header.extend(struct.pack("!H", length))
                else:
                    header.append(127)
                    header.extend(struct.pack("!Q", length))
                self.connection.sendall(bytes(header) + body)

            def _send_ws_close(self) -> None:
                try:
                    self._send_ws_frame(0x8, b"")
                except Exception:
                    pass

        return Handler


def load_bridge_info(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    info_path = Path(path)
    if not info_path.exists():
        raise FileNotFoundError(f"bridge info file not found: {info_path}")
    payload = json.loads(info_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("bridge info JSON object expected")
    if str(payload.get("service") or "").strip() != "nc_main_chat_bridge":
        raise ValueError("bridge info is not for the Main Chat Remote bridge")
    if payload.get("enabled") is not True:
        raise ValueError("bridge info is not enabled")
    token = str(payload.get("token") or "").strip()
    if not token:
        raise ValueError("bridge info is missing the bridge token")
    try:
        updated_at = float(payload.get("updated_at"))
    except (TypeError, ValueError):
        raise ValueError("bridge info is missing a freshness timestamp")
    age_seconds = time.time() - updated_at
    if age_seconds < -BRIDGE_INFO_MAX_FUTURE_SKEW_SECONDS:
        raise ValueError("bridge info timestamp is from the future; restart the local bridge")
    if age_seconds > BRIDGE_INFO_MAX_AGE_SECONDS:
        raise ValueError("bridge info is stale; restart the local bridge")
    payload["token"] = token
    payload["updated_at"] = updated_at
    payload["url"] = normalize_bridge_url(str(payload.get("url") or DEFAULT_BRIDGE_URL))
    return payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NeuralCompanion Main Chat Remote LAN backend.")
    parser.add_argument("--host", default=os.environ.get("NC_MAIN_CHAT_REMOTE_HOST", DEFAULT_REMOTE_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("NC_MAIN_CHAT_REMOTE_PORT", DEFAULT_REMOTE_PORT)))
    parser.add_argument("--pairing-code", default=os.environ.get("NC_MAIN_CHAT_REMOTE_CODE", ""))
    parser.add_argument("--bridge-url", default=os.environ.get("NC_MAIN_CHAT_BRIDGE_URL", DEFAULT_BRIDGE_URL))
    parser.add_argument("--bridge-token", default=os.environ.get("NC_MAIN_CHAT_BRIDGE_TOKEN", ""))
    parser.add_argument("--bridge-info", default=os.environ.get("NC_MAIN_CHAT_BRIDGE_INFO", ""))
    parser.add_argument(
        "--hide-pairing-code-output",
        action="store_true",
        default=str(os.environ.get("NC_MAIN_CHAT_REMOTE_HIDE_CODE_OUTPUT", "")).strip().lower() in {"1", "true", "yes", "on"},
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        info = load_bridge_info(args.bridge_info) if args.bridge_info else {}
    except Exception as exc:
        print(f"Bridge info is not usable. Start the local bridge first: {exc}", file=sys.stderr)
        return 3
    bridge_url = str(info.get("url") or args.bridge_url or DEFAULT_BRIDGE_URL)
    bridge_token = str(info.get("token") or args.bridge_token or "")
    backend = MainChatRemoteBackend(
        host=args.host,
        port=args.port,
        pairing_code=args.pairing_code,
        bridge_url=bridge_url,
        bridge_token=bridge_token,
        bridge_info_path=args.bridge_info or None,
        hide_pairing_code_output=bool(args.hide_pairing_code_output),
    )
    backend.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
