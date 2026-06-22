from __future__ import annotations

import ipaddress
import json
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse


DEFAULT_REMOTE_PORT = 8765
REMOTE_CODE_DIGITS = 6


def generate_remote_code(digits: int = REMOTE_CODE_DIGITS) -> str:
    digits = max(4, min(9, int(digits or REMOTE_CODE_DIGITS)))
    floor = 10 ** (digits - 1)
    return str(floor + secrets.randbelow(9 * floor))


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
    for address in candidates:
        try:
            ip = ipaddress.ip_address(address)
        except Exception:
            continue
        if ip.version == 4 and (ip.is_private or ip.is_link_local) and not ip.is_loopback:
            return address
    for address in candidates:
        if not address.startswith("127."):
            return address
    return "127.0.0.1"


def local_network_client(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(str(address or "").split("%", 1)[0])
    except Exception:
        return False
    return bool(ip.is_loopback or ip.is_private or ip.is_link_local)


class MPRCRemoteBackend:
    def __init__(self, controller, *, host: str = "0.0.0.0", port: int = DEFAULT_REMOTE_PORT, code: str = ""):
        self.controller = controller
        self.host = str(host or "0.0.0.0").strip() or "0.0.0.0"
        self.port = max(1, min(65535, int(port or DEFAULT_REMOTE_PORT)))
        self.code = str(code or "").strip()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._clients: dict[str, float] = {}
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
            "enabled": bool(getattr(self.controller, "settings", {}).get("remote_enabled", False)),
            "running": self.running,
            "host": self.host,
            "port": self.port,
            "url": self.display_url,
            "code_configured": bool(self.code),
            "connected_clients": len(clients),
            "clients": clients,
            "started_at": self._started_at,
        }

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            handler_cls = self._handler_class()
            server = ThreadingHTTPServer((self.host, self.port), handler_cls)
            server.daemon_threads = True
            server.backend = self  # type: ignore[attr-defined]
            thread = threading.Thread(target=server.serve_forever, name="mprc-remote-http", daemon=True)
            self._server = server
            self._thread = thread
            self._started_at = time.time()
            thread.start()
        self._log("started at %s", self.display_url)

    def stop(self) -> None:
        with self._lock:
            server = self._server
            self._server = None
            self._thread = None
        if server is None:
            return

        def worker() -> None:
            try:
                server.shutdown()
            except Exception:
                pass
            try:
                server.server_close()
            except Exception:
                pass
            self._log("stopped")

        threading.Thread(target=worker, name="mprc-remote-stop", daemon=True).start()

    def record_client(self, address: str) -> None:
        if not address:
            return
        with self._lock:
            self._clients[str(address)] = time.time()

    def _log(self, message: str, *args) -> None:
        logger = getattr(getattr(self.controller, "context", None), "logger", None)
        if logger is not None:
            try:
                logger.info("[MPRC Remote] " + message, *args)
            except Exception:
                pass

    def _handler_class(self):
        backend = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "MPRCRemote/1.0"

            def log_message(self, fmt: str, *args) -> None:
                backend._log("%s - " + fmt, self.client_address[0] if self.client_address else "?", *args)

            def do_OPTIONS(self) -> None:
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
                        self._send_json({"ok": True, "service": "mprc_remote", "status": backend.status_snapshot()})
                        return
                    if path.startswith("/api/") and not self._authorized(parsed.query):
                        self._send_json({"ok": False, "error": "Unauthorized"}, status=401)
                        return
                    if method == "GET":
                        self._handle_get(path)
                        return
                    if method == "POST":
                        self._handle_post(path)
                        return
                    self._send_json({"ok": False, "error": "Method not allowed"}, status=405)
                except ValueError as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=400)
                except Exception as exc:
                    backend._log("request failed: %s", exc)
                    self._send_json({"ok": False, "error": str(exc) or "Remote backend error"}, status=500)

            def _handle_get(self, path: str) -> None:
                controller = backend.controller
                if path == "/api/state":
                    self._send_json({"ok": True, "state": controller.remote_snapshot()})
                    return
                if path == "/api/personas":
                    self._send_json({"ok": True, "personas": controller.remote_personas_snapshot()})
                    return
                if path == "/api/session":
                    self._send_json({"ok": True, "session": controller.remote_session_snapshot()})
                    return
                if path == "/api/audio-settings":
                    self._send_json({"ok": True, "audio_settings": controller.audio_settings_snapshot()})
                    return
                if path == "/api/speech-audio":
                    self._send_json({"ok": True, "speech_audio": controller.remote_speech_audio_snapshot()})
                    return
                if path.startswith("/api/speech-audio/file/"):
                    audio_id = path.rsplit("/", 1)[-1]
                    try:
                        audio_path = controller.remote_speech_audio_file_path(audio_id)
                    except FileNotFoundError as exc:
                        self._send_json({"ok": False, "error": str(exc) or "speech audio chunk not found"}, status=404)
                        return
                    self._send_file(audio_path, content_type="audio/wav")
                    return
                self._send_json({"ok": False, "error": "Not found"}, status=404)

            def _handle_post(self, path: str) -> None:
                controller = backend.controller
                payload = self._read_json()
                if path == "/api/session":
                    self._send_json({"ok": True, "state": controller.remote_update_session(payload)})
                    return
                if path == "/api/send":
                    text = str(payload.get("text") or payload.get("message") or payload.get("action") or "").strip()
                    if not text:
                        raise ValueError("text is required")
                    self._send_json(
                        {
                            "ok": True,
                            "state": controller.remote_send_user_text(
                                text,
                                intent=str(payload.get("intent") or "Auto"),
                                speaker_id=str(payload.get("speaker_id") or ""),
                            ),
                        }
                    )
                    return
                if path == "/api/choice":
                    text = str(payload.get("choice") or payload.get("text") or payload.get("choice_id") or "").strip()
                    if not text:
                        raise ValueError("choice or text is required")
                    self._send_json({"ok": True, "state": controller.remote_select_choice(text)})
                    return
                if path == "/api/play":
                    self._send_json({"ok": True, "state": controller.remote_play()})
                    return
                if path == "/api/pause":
                    self._send_json({"ok": True, "state": controller.remote_pause()})
                    return
                if path == "/api/visual":
                    self._send_json({"ok": True, "state": controller.remote_request_visual()})
                    return
                if path == "/api/cast":
                    self._send_json({"ok": True, "result": controller.remote_chromecast_action(payload)})
                    return
                self._send_json({"ok": False, "error": "Not found"}, status=404)

            def _authorized(self, query: str) -> bool:
                expected = backend.code
                if not expected:
                    return False
                header = str(self.headers.get("X-MPRC-Code") or "").strip()
                if not header:
                    header = str(parse_qs(query).get("code", [""])[0] or "").strip()
                return secrets.compare_digest(header, expected)

            def _read_json(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0:
                    return {}
                if length > 1024 * 1024:
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
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-MPRC-Code")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.end_headers()
                self.wfile.write(body)

            def _send_file(self, path, *, content_type: str = "application/octet-stream") -> None:
                try:
                    body = path.read_bytes()
                except FileNotFoundError:
                    self._send_json({"ok": False, "error": "file not found"}, status=404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-MPRC-Code")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.end_headers()
                self.wfile.write(body)

        return Handler
