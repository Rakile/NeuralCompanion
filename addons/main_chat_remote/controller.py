from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import re
import secrets
import socket
import subprocess
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from addons.main_chat_remote.backend_process import BackendProcessSupervisor
from addons.main_chat_remote.media_bridge import MainChatMediaBridge

try:  # PySide6 is present in the full app, but smoke tests can run without it.
    from PySide6 import QtCore, QtWidgets
except Exception:  # pragma: no cover - exercised in non-Qt smoke contexts.
    QtCore = None
    QtWidgets = None


DEFAULT_BRIDGE_HOST = "127.0.0.1"
DEFAULT_BRIDGE_PORT = 8776
BRIDGE_INFO_FILE = "bridge_info.json"
MAX_JSON_PAYLOAD_BYTES = 25 * 1024 * 1024
STT_UPLOAD_RETENTION_SECONDS = 24 * 60 * 60
STT_UPLOAD_MAX_FILES = 128
VISUAL_REQUEST_MAX_ITEMS = 20
BRIDGE_INFO_REFRESH_SECONDS = 30.0
MPRC_REMOTE_CAPABILITIES = {
    "send": "mprc.remote_send",
    "choice": "mprc.remote_choice",
    "play": "mprc.remote_play",
    "pause": "mprc.remote_pause",
    "visual": "mprc.remote_visual",
    "cast": "mprc.remote_cast",
}
SENSITIVE_QUERY_VALUE_RE = re.compile(r"([?&](?:code|token)=)([^&\s\"']+)", re.IGNORECASE)
PHONE_HIDDEN_LOCAL_PATH_KEYS = {
    "audio_path",
    "backend_script",
    "bridge_info_path",
    "command",
    "create_command",
    "frame_path",
    "frame_paths",
    "image_path",
    "log_path",
    "python",
    "setup_script",
    "start_command",
    "venv_dir",
    "venv_python",
}
PHONE_HIDDEN_LOCAL_PATH_SUFFIXES = (
    "_dir",
    "_directory",
    "_folder",
    "_path",
    "_root",
)
PHONE_SAFE_URL_PATH_KEYS = {
    "frame_url_path",
    "image_url_path",
    "stream_url_path",
    "url_path",
}
REMOTE_CONTROL_FALLBACK_ACTIONS = {
    "pause_speech",
    "regenerate_response",
    "replay_chat_session",
    "replay_last_assistant",
    "retry_user_input",
    "skip_speech",
    "skip_user_reply",
}
REMOTE_TTS_PRODUCING_ACTIONS = {
    "regenerate_response",
    "replay_chat_session",
    "replay_last_assistant",
    "retry_user_input",
}
PHONE_HIDDEN_SECRET_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "auth_token",
    "authorization",
    "password",
    "refresh_token",
    "secret",
    "token",
}
PHONE_SECRET_KEY_PARTS = {
    "access_token",
    "api_key",
    "apikey",
    "auth_token",
    "authorization",
    "bearer_token",
    "client_secret",
    "password",
    "refresh_token",
    "secret",
    "token",
}
PHONE_SAFE_SECRET_LIKE_KEYS = {
    "image_cache_key",
    "pairing_code_configured",
    "token_configured",
}


def generate_bridge_token() -> str:
    return secrets.token_urlsafe(24)


def redact_sensitive_query_values(message: str) -> str:
    return SENSITIVE_QUERY_VALUE_RE.sub(r"\1<redacted>", str(message or ""))


@dataclass
class BridgeSettings:
    enabled: bool = False
    host: str = DEFAULT_BRIDGE_HOST
    port: int = DEFAULT_BRIDGE_PORT
    token: str = ""

    def normalized(self) -> "BridgeSettings":
        host = str(self.host or DEFAULT_BRIDGE_HOST).strip() or DEFAULT_BRIDGE_HOST
        if host not in {"127.0.0.1", "localhost", "::1"}:
            host = DEFAULT_BRIDGE_HOST
        try:
            port_value = int(self.port or DEFAULT_BRIDGE_PORT)
        except (TypeError, ValueError):
            port_value = DEFAULT_BRIDGE_PORT
        port = max(1, min(65535, port_value))
        token = str(self.token or "").strip() or generate_bridge_token()
        return BridgeSettings(enabled=bool(self.enabled), host=host, port=port, token=token)

    def to_dict(self) -> dict[str, Any]:
        item = self.normalized()
        return {"enabled": item.enabled, "host": item.host, "port": item.port, "token": item.token}

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "BridgeSettings":
        data = dict(payload or {})
        return cls(
            enabled=bool(data.get("enabled", False)),
            host=str(data.get("host") or DEFAULT_BRIDGE_HOST),
            port=data.get("port") or DEFAULT_BRIDGE_PORT,
            token=str(data.get("token") or ""),
        ).normalized()


class _MainThreadInvoker(QtCore.QObject if QtCore is not None else object):
    if QtCore is not None:
        call_requested = QtCore.Signal(object)

    def __init__(self):
        if QtCore is not None:
            super().__init__()
            self.call_requested.connect(self._handle_call, QtCore.Qt.QueuedConnection)
        self._qt_available = QtCore is not None

    def invoke(self, func: Callable[[], Any], *, timeout_seconds: float = 10.0) -> Any:
        if not self._qt_available:
            return func()
        try:
            if QtCore.QCoreApplication.instance() is None:
                return func()
        except Exception:
            return func()
        try:
            if QtCore.QThread.currentThread() is self.thread():
                return func()
        except Exception:
            return func()
        request = {"func": func, "event": threading.Event(), "result": None, "error": None}
        self.call_requested.emit(request)
        if not request["event"].wait(max(0.1, float(timeout_seconds or 10.0))):
            raise TimeoutError("Timed out waiting for NeuralCompanion UI thread.")
        if request.get("error") is not None:
            raise RuntimeError(str(request["error"]))
        return request.get("result")

    def _handle_call(self, payload) -> None:
        request = payload if isinstance(payload, dict) else {}
        event = request.get("event")
        try:
            func = request.get("func")
            if not callable(func):
                raise RuntimeError("main-thread request is missing callable")
            request["result"] = func()
        except Exception as exc:
            request["error"] = str(exc) or repr(exc)
        finally:
            if event is not None and hasattr(event, "set"):
                event.set()


class MainChatBridgeServer:
    def __init__(self, controller: "MainChatRemoteController", settings: BridgeSettings):
        self.controller = controller
        self.settings = settings.normalized()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._started_at = 0.0

    @property
    def running(self) -> bool:
        with self._lock:
            return self._server is not None and self._thread is not None and self._thread.is_alive()

    @property
    def url(self) -> str:
        return f"http://{self.settings.host}:{self.settings.port}"

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            handler_cls = self._handler_class()
            server = ThreadingHTTPServer((self.settings.host, self.settings.port), handler_cls)
            server.daemon_threads = True
            server.bridge = self  # type: ignore[attr-defined]
            thread = threading.Thread(target=server.serve_forever, name="nc-main-chat-bridge", daemon=True)
            self._server = server
            self._thread = thread
            self._started_at = time.time()
            thread.start()
        self.controller.log("info", "Local bridge started at %s", self.url)

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
            self.controller.log("info", "Local bridge stopped.")

        threading.Thread(target=worker, name="nc-main-chat-bridge-stop", daemon=True).start()

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.settings.enabled),
            "running": self.running,
            "host": self.settings.host,
            "port": self.settings.port,
            "url": self.url,
            "token_configured": bool(self.settings.token),
            "started_at": self._started_at,
        }

    def _handler_class(self):
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "NCMainChatBridge/0.1"

            def log_message(self, fmt: str, *args) -> None:
                line = redact_sensitive_query_values(fmt % args)
                bridge.controller.log("debug", "%s - %s", self.client_address[0] if self.client_address else "?", line)

            def do_OPTIONS(self) -> None:
                if not self._loopback_client():
                    self._send_json({"ok": False, "error": "Bridge accepts loopback clients only."}, status=403)
                    return
                self._send_json({"ok": True})

            def do_GET(self) -> None:
                self._handle("GET")

            def do_POST(self) -> None:
                self._handle("POST")

            def _handle(self, method: str) -> None:
                if not self._loopback_client():
                    self._send_json({"ok": False, "error": "Bridge accepts loopback clients only."}, status=403)
                    return
                parsed = urlparse(self.path)
                path = parsed.path.rstrip("/") or "/"
                try:
                    if path == "/health":
                        self._send_json({"ok": True, "service": "nc_main_chat_bridge", "bridge": bridge.status_snapshot()})
                        return
                    if path.startswith("/api/") and not self._authorized(parsed.query):
                        self._send_json({"ok": False, "error": "Unauthorized"}, status=401)
                        return
                    if method == "GET":
                        self._handle_get(path, parsed.query)
                        return
                    if method == "POST":
                        self._handle_post(path)
                        return
                    self._send_json({"ok": False, "error": "Method not allowed"}, status=405)
                except FileNotFoundError as exc:
                    self._send_json({"ok": False, "error": str(exc) or "not found"}, status=404)
                except ValueError as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=400)
                except Exception as exc:
                    bridge.controller.log("warning", "Bridge request failed: %s", exc)
                    self._send_json({"ok": False, "error": str(exc) or "Bridge request failed"}, status=500)

            def _handle_get(self, path: str, query: str = "") -> None:
                controller = bridge.controller
                if path == "/api/state":
                    self._send_json({"ok": True, "state": controller.remote_state_snapshot()})
                    return
                if path == "/api/audio":
                    self._send_json({"ok": True, "audio": controller.media_snapshot()})
                    return
                if path.startswith("/api/audio/file/"):
                    audio_id = path.rsplit("/", 1)[-1]
                    audio_path = controller.audio_file_path(audio_id)
                    self._send_file(audio_path, content_type=controller.file_content_type(audio_path))
                    return
                if path == "/api/visual":
                    self._send_json({"ok": True, "visual": controller.visual_snapshot(phone_safe=True)})
                    return
                if path == "/api/visual/image":
                    self._send_file(controller.visual_image_path(), content_type=controller.visual_image_content_type())
                    return
                if path == "/api/musetalk":
                    params = parse_qs(query)
                    after_seq = int(str(params.get("after_seq", ["0"])[0] or "0"))
                    self._send_json({"ok": True, "musetalk": controller.musetalk_snapshot(after_seq=after_seq, phone_safe=True)})
                    return
                if path in {"/api/mprc", "/api/mprc/state"}:
                    self._send_json({"ok": True, "mprc": controller.mprc_snapshot(phone_safe=True)})
                    return
                if path == "/api/musetalk/stream":
                    self._send_musetalk_stream(query)
                    return
                if path.startswith("/api/musetalk/frame/"):
                    frame_id = path.rsplit("/", 1)[-1]
                    frame_path = controller.musetalk_frame_file_path(frame_id)
                    self._send_file(frame_path, content_type=controller.file_content_type(frame_path))
                    return
                self._send_json({"ok": False, "error": "Not found"}, status=404)

            def _handle_post(self, path: str) -> None:
                controller = bridge.controller
                payload = self._read_json()
                if path == "/api/send":
                    text = str(payload.get("text") or payload.get("message") or "").strip()
                    if not text:
                        raise ValueError("text is required")
                    self._send_json({"ok": True, "result": controller.remote_send_text(text, payload)})
                    return
                if path == "/api/control":
                    action = str(payload.get("action") or "").strip()
                    if not action:
                        raise ValueError("action is required")
                    self._send_json({"ok": True, "result": controller.remote_control(action, payload)})
                    return
                if path == "/api/engine/start":
                    self._send_json({"ok": True, "result": controller.remote_engine_start()})
                    return
                if path == "/api/engine/stop":
                    self._send_json({"ok": True, "result": controller.remote_engine_stop()})
                    return
                if path == "/api/stt":
                    self._send_json({"ok": True, "result": controller.remote_stt_upload(payload)})
                    return
                if path == "/api/audio/clear":
                    self._send_json({"ok": True, "result": controller.remote_audio_clear()})
                    return
                if path == "/api/visual":
                    self._send_json({"ok": True, "result": controller.remote_visual_request(payload)})
                    return
                if path.startswith("/api/mprc/"):
                    action = path.rsplit("/", 1)[-1]
                    self._send_json({"ok": True, "result": controller.remote_mprc_action(action, payload)})
                    return
                self._send_json({"ok": False, "error": "Not found"}, status=404)

            def _loopback_client(self) -> bool:
                host = self.client_address[0] if self.client_address else ""
                return host in {"127.0.0.1", "::1", "localhost"}

            def _authorized(self, query: str) -> bool:
                expected = bridge.settings.token
                if not expected:
                    return False
                if self._query_has_credentials(query):
                    return False
                provided = str(self.headers.get("X-NC-Bridge-Token") or "").strip()
                return secrets.compare_digest(provided, expected)

            @staticmethod
            def _query_has_credentials(query: str) -> bool:
                try:
                    params = parse_qs(str(query or ""), keep_blank_values=True)
                except Exception:
                    return False
                return any(str(key or "").strip().lower() in {"code", "token"} for key in params)

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
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-NC-Bridge-Token")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.end_headers()
                self.wfile.write(body)

            def _send_file(self, path: Path, *, content_type: str = "application/octet-stream") -> None:
                body = path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)

            def _send_musetalk_stream(self, query: str) -> None:
                params = parse_qs(query)
                fps = self._bounded_float(params.get("fps", ["8"])[0], default=8.0, minimum=1.0, maximum=24.0)
                max_frames = int(self._bounded_float(params.get("frames", ["0"])[0], default=0.0, minimum=0.0, maximum=10000.0))
                wait_seconds = self._bounded_float(params.get("wait", ["2"])[0], default=2.0, minimum=0.0, maximum=30.0)
                boundary = "nc_musetalk_frame"
                first_frame_deadline = time.time() + wait_seconds
                while True:
                    try:
                        frame_path = bridge.controller.musetalk_current_frame_file_path()
                        break
                    except FileNotFoundError:
                        if time.time() >= first_frame_deadline:
                            raise
                        time.sleep(0.1)
                self.send_response(200)
                self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={boundary}")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Connection", "close")
                self.end_headers()
                sent = 0
                last_signature = ""
                last_sent_at = 0.0
                interval = 1.0 / fps
                while max_frames <= 0 or sent < max_frames:
                    try:
                        frame_path = bridge.controller.musetalk_current_frame_file_path()
                        stat = frame_path.stat()
                        signature = f"{frame_path}:{stat.st_mtime_ns}:{stat.st_size}"
                        if signature == last_signature and max_frames <= 0 and time.time() - last_sent_at < 2.0:
                            time.sleep(interval)
                            continue
                        body = frame_path.read_bytes()
                        if not body:
                            time.sleep(interval)
                            continue
                        content_type = bridge.controller.file_content_type(frame_path)
                        frame_id = bridge.controller.frame_id_for_path(frame_path)
                        header = (
                            f"--{boundary}\r\n"
                            f"Content-Type: {content_type}\r\n"
                            f"Content-Length: {len(body)}\r\n"
                            f"X-NC-Frame-Id: {frame_id}\r\n"
                            "\r\n"
                        ).encode("ascii")
                        self.wfile.write(header)
                        self.wfile.write(body)
                        self.wfile.write(b"\r\n")
                        self.wfile.flush()
                        last_signature = signature
                        last_sent_at = time.time()
                        sent += 1
                    except (BrokenPipeError, ConnectionError, OSError):
                        return
                    time.sleep(interval)
                try:
                    self.wfile.write(f"--{boundary}--\r\n".encode("ascii"))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionError, OSError):
                    return

            @staticmethod
            def _bounded_float(value, *, default: float, minimum: float, maximum: float) -> float:
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    number = default
                return max(minimum, min(maximum, number))

        return Handler


class MainChatRemoteController:
    def __init__(self, context=None):
        self.context = context
        self.shell = context.get_service("qt.shell") if context is not None else None
        self.runtime_status = context.get_service("qt.runtime_status") if context is not None else None
        self.runtime_controls = context.get_service("qt.runtime_controls") if context is not None else None
        self.engine_lifecycle = context.get_service("qt.engine_lifecycle") if context is not None else None
        self.chat_replay = context.get_service("qt.chat_replay") if context is not None else None
        self.runtime_config = context.get_service("qt.runtime_config") if context is not None else None
        self.visual_reply = context.get_service("qt.visual_reply") if context is not None else None
        self.addon_capabilities = context.get_service("addons.capabilities") if context is not None else None
        app_root = Path(getattr(context, "app_root", Path.cwd()) or Path.cwd())
        self.runtime_dir = app_root / "runtime" / "main_chat_remote"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.stt_upload_dir = self.runtime_dir / "stt_uploads"
        self.bridge_info_path = self.runtime_dir / BRIDGE_INFO_FILE
        self.media_bridge = MainChatMediaBridge(self.runtime_dir / "audio", logger=getattr(context, "logger", None))
        self.backend_process = BackendProcessSupervisor(
            app_root=app_root,
            runtime_dir=self.runtime_dir,
            bridge_info_path=self.bridge_info_path,
            logger=getattr(context, "logger", None),
        )
        self._invoker = _MainThreadInvoker()
        self._settings = BridgeSettings().normalized()
        self._bridge: MainChatBridgeServer | None = None
        self._tab = None
        self._refresh_timer = None
        self._backend_task_lock = threading.RLock()
        self._backend_task = ""
        self._stt_lock = threading.Lock()
        self._visual_request_lock = threading.RLock()
        self._visual_requests: list[dict[str, Any]] = []
        self._last_bridge_info_write = 0.0

    def build_tab(self):
        if QtWidgets is None:
            raise RuntimeError("PySide6 is required to build the Main Chat Remote tab.")
        widget = QtWidgets.QWidget()
        widget.setObjectName("main_chat_remote_tab")
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        intro = QtWidgets.QLabel(
            "Pair a phone on your local network with the real NeuralCompanion main chat runtime. "
            "Use the steps in order, then enter the shown URL and numeric pairing code in the Expo phone app."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        def step_group(title: str, description: str = ""):
            group = QtWidgets.QGroupBox(title)
            group.setObjectName("main_chat_remote_step_group")
            group_layout = QtWidgets.QVBoxLayout(group)
            group_layout.setContentsMargins(12, 16, 12, 12)
            group_layout.setSpacing(8)
            if description:
                label = QtWidgets.QLabel(description)
                label.setWordWrap(True)
                label.setStyleSheet("color: #9fb3c8;")
                group_layout.addWidget(label)
            return group, group_layout

        bridge_group, bridge_layout = step_group(
            "1. Enable desktop bridge",
            "This starts the safe local bridge inside NC. The phone backend can only reach NC through this local bridge.",
        )
        self._enabled_checkbox = QtWidgets.QCheckBox("Enable desktop bridge")
        self._enabled_checkbox.setObjectName("main_chat_remote_enabled_checkbox")
        self._enabled_checkbox.setChecked(bool(self._settings.enabled))
        self._enabled_checkbox.toggled.connect(self._set_bridge_enabled)
        bridge_layout.addWidget(self._enabled_checkbox)

        self._status_label = QtWidgets.QLabel("")
        self._status_label.setObjectName("main_chat_remote_status_label")
        self._status_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self._status_label.setWordWrap(True)
        bridge_layout.addWidget(self._status_label)

        button_row = QtWidgets.QHBoxLayout()
        self._start_button = QtWidgets.QPushButton("Start desktop bridge")
        self._start_button.setObjectName("main_chat_remote_start_bridge_button")
        self._start_button.clicked.connect(self.start_bridge)
        button_row.addWidget(self._start_button)
        self._stop_button = QtWidgets.QPushButton("Stop bridge")
        self._stop_button.setObjectName("main_chat_remote_stop_bridge_button")
        self._stop_button.clicked.connect(self.stop_bridge)
        button_row.addWidget(self._stop_button)
        self._refresh_button = QtWidgets.QPushButton("Refresh status")
        self._refresh_button.setObjectName("main_chat_remote_refresh_button")
        self._refresh_button.clicked.connect(self.refresh_tab)
        button_row.addWidget(self._refresh_button)
        button_row.addStretch(1)
        bridge_layout.addLayout(button_row)
        layout.addWidget(bridge_group)

        backend_group, backend_layout = step_group(
            "2. Start phone backend",
            "The phone backend listens on your LAN, shows the pairing code, and serves phone-safe chat, audio, STT, Visual Reply, and MuseTalk data.",
        )

        self._backend_status_label = QtWidgets.QLabel("")
        self._backend_status_label.setObjectName("main_chat_remote_backend_status_label")
        self._backend_status_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self._backend_status_label.setWordWrap(True)
        backend_layout.addWidget(self._backend_status_label)

        backend_row = QtWidgets.QHBoxLayout()
        self._create_backend_venv_button = QtWidgets.QPushButton("Prepare phone backend")
        self._create_backend_venv_button.setObjectName("main_chat_remote_create_backend_venv_button")
        self._create_backend_venv_button.clicked.connect(self.create_backend_venv)
        backend_row.addWidget(self._create_backend_venv_button)
        self._start_backend_button = QtWidgets.QPushButton("Start phone backend")
        self._start_backend_button.setObjectName("main_chat_remote_start_backend_button")
        self._start_backend_button.clicked.connect(self.start_remote_backend)
        backend_row.addWidget(self._start_backend_button)
        self._stop_backend_button = QtWidgets.QPushButton("Stop phone backend")
        self._stop_backend_button.setObjectName("main_chat_remote_stop_backend_button")
        self._stop_backend_button.clicked.connect(self.stop_remote_backend)
        backend_row.addWidget(self._stop_backend_button)
        backend_row.addStretch(1)
        backend_layout.addLayout(backend_row)
        layout.addWidget(backend_group)

        pair_group, pair_layout = step_group(
            "3. Pair phone",
            "Use the LAN URL and pairing code shown above in the phone app. Keep both devices on the same network.",
        )
        pair_layout.addWidget(QtWidgets.QLabel("Pairing details update automatically while the phone backend is running."))
        layout.addWidget(pair_group)

        test_group, test_layout = step_group(
            "4. Test chat, audio, and visuals",
            "After pairing, send a short text message from the phone, play a generated TTS chunk, open Visual Reply, and check the MuseTalk view if it is enabled.",
        )
        layout.addWidget(test_group)

        self._remote_command = QtWidgets.QPlainTextEdit()
        self._remote_command.setObjectName("main_chat_remote_command_text")
        self._remote_command.setReadOnly(True)
        self._remote_command.setMaximumHeight(132)
        command_group, command_layout = step_group("Advanced backend command")
        command_group.setCheckable(True)
        command_group.setChecked(False)
        self._remote_command.setVisible(False)
        command_group.toggled.connect(lambda checked: self._remote_command.setVisible(bool(checked)))
        command_layout.addWidget(self._remote_command)
        layout.addWidget(command_group)
        layout.addStretch(1)
        self._tab = widget
        self._refresh_timer = QtCore.QTimer(widget)
        self._refresh_timer.setInterval(1500)
        self._refresh_timer.timeout.connect(self.refresh_tab)
        self._refresh_timer.start()
        self.refresh_tab()
        return widget

    def export_session_state(self) -> dict[str, Any]:
        return {"main_chat_remote": {"bridge": self._settings.to_dict()}}

    def import_session_state(self, session) -> None:
        payload = dict(session or {}).get("main_chat_remote", {})
        if isinstance(payload, dict):
            self._settings = BridgeSettings.from_payload(payload.get("bridge") if isinstance(payload.get("bridge"), dict) else payload)
        if self._settings.enabled:
            try:
                self.start_bridge()
            except Exception as exc:
                self.log("warning", "Could not auto-start local bridge: %s", exc)
        else:
            self._remove_bridge_info()
        self.refresh_tab()

    def shutdown(self) -> None:
        self._stop_refresh_timer()
        self._tab = None
        self.backend_process.stop()
        self.stop_bridge()
        self.media_bridge.cleanup()

    def invoke_capability(self, capability, payload=None):
        name = str(capability or "").strip().lower()
        if name == "tts.audio_chunk_ready":
            return self.media_bridge.handle_tts_audio_chunk_ready(dict(payload or {}))
        if name == "main_chat_remote.status":
            return self.status_snapshot()
        if name == "main_chat_remote.start_bridge":
            self.start_bridge()
            return self.status_snapshot()
        if name == "main_chat_remote.stop_bridge":
            self.stop_bridge()
            return self.status_snapshot()
        return None

    def start_bridge(self) -> None:
        self._settings = BridgeSettings(
            enabled=True,
            host=self._settings.host,
            port=self._settings.port,
            token=self._settings.token,
        ).normalized()
        if self._bridge is None or self._bridge.settings.port != self._settings.port:
            if self._bridge is not None:
                self._bridge.stop()
            self._bridge = MainChatBridgeServer(self, self._settings)
        self._bridge.start()
        self._write_bridge_info()
        self.refresh_tab()

    def stop_bridge(self) -> None:
        self._settings = BridgeSettings(
            enabled=False,
            host=self._settings.host,
            port=self._settings.port,
            token=self._settings.token,
        ).normalized()
        bridge = self._bridge
        self._bridge = None
        if bridge is not None:
            bridge.stop()
        self._remove_bridge_info()
        self.refresh_tab()

    def status_snapshot(self) -> dict[str, Any]:
        self._refresh_bridge_info_if_running()
        bridge = self._bridge.status_snapshot() if self._bridge is not None else {
            "enabled": bool(self._settings.enabled),
            "running": False,
            "host": self._settings.host,
            "port": self._settings.port,
            "url": f"http://{self._settings.host}:{self._settings.port}",
            "token_configured": bool(self._settings.token),
            "started_at": 0.0,
        }
        return {
            "bridge": bridge,
            "backend": self.backend_process.status_snapshot(),
            "backend_task": self._current_backend_task(),
            "bridge_info_path": str(self.bridge_info_path),
            "media": self.media_bridge.snapshot(),
        }

    def create_backend_venv(self) -> None:
        self._run_backend_task("creating backend venv", self.backend_process.create_venv)

    def start_remote_backend(self) -> None:
        if self._bridge is None or not self._bridge.running:
            try:
                self.start_bridge()
            except Exception as exc:
                self.log("warning", "Could not start local bridge before LAN backend: %s", exc)
        self._run_backend_task("starting LAN backend", self.backend_process.start)

    def stop_remote_backend(self) -> None:
        self._run_backend_task("stopping LAN backend", self.backend_process.stop)

    def remote_state_snapshot(self) -> dict[str, Any]:
        def build() -> dict[str, Any]:
            runtime_status = self._safe_service_call(self.runtime_status, "snapshot", {})
            runtime_config = self._safe_service_call(self.runtime_config, "snapshot", {})
            status_line = self._safe_service_call(self.runtime_status, "status_line", "runtime: unavailable")
            lifecycle = self._safe_service_call(self.engine_lifecycle, "snapshot", {})
            controls = self._safe_service_call(self.runtime_controls, "snapshot", {})
            chat_session = self._safe_service_call(self.chat_replay, "snapshot_chat_session", {})
            replayable = self._safe_service_call(self.chat_replay, "replayable_chat_entries", [])
            mprc = self.mprc_snapshot(phone_safe=True)
            buddy_chat = self.buddy_chat_snapshot(phone_safe=True)
            return {
                "runtime_status": runtime_status,
                "runtime_settings": self._runtime_settings_summary(runtime_config),
                "status_line": status_line,
                "engine": lifecycle,
                "controls": controls,
                "chat": self._chat_feed(chat_session),
                "replayable": list(replayable or [])[-100:],
                "llm": self._addon_snapshot("llm"),
                "tts": self._addon_snapshot("tts"),
                "avatar": self._addon_snapshot("avatar"),
                "media": self.media_bridge.snapshot(),
                "visual": self.visual_snapshot(phone_safe=True),
                "musetalk": self.musetalk_snapshot(phone_safe=True),
                "mprc": mprc,
                "buddy_chat": buddy_chat,
                "remote": self._phone_status_snapshot(),
                "features": {
                    "text_send": True,
                    "runtime_status": True,
                    "tts_audio_chunks": True,
                    "phone_stt": self._stt_transcriber_available(),
                    "visual_reply_controls": self.visual_reply is not None,
                    "visual_reply_display": True,
                    "musetalk_frame_feed": True,
                    "musetalk_frame_stream": True,
                    "mprc_story_mode": bool(dict(mprc or {}).get("available", False)),
                    "buddy_chat": bool(dict(buddy_chat or {}).get("available", False)),
                },
            }

        return self._phone_safe_payload(self._invoke_main(build))

    @staticmethod
    def _runtime_settings_summary(runtime_config: dict[str, Any] | None) -> dict[str, Any]:
        config = dict(runtime_config or {})
        return {
            "chat_provider": str(config.get("chat_provider", "") or ""),
            "model_name": str(config.get("model_name", "") or ""),
            "stt_backend": str(config.get("stt_backend", "") or ""),
            "stt_model_size": str(config.get("stt_model_size", "") or ""),
            "tts_backend": str(config.get("tts_backend", "") or ""),
            "visual_reply_provider": str(config.get("visual_reply_provider", "") or ""),
        }

    def media_snapshot(self) -> dict[str, Any]:
        return self.media_bridge.snapshot()

    def _phone_status_snapshot(self) -> dict[str, Any]:
        snapshot = dict(self.status_snapshot() or {})
        backend = dict(snapshot.get("backend") or {})
        pairing_code = str(backend.get("pairing_code") or "")
        backend["pairing_code"] = ""
        backend["pairing_code_configured"] = bool(pairing_code)
        last_result = dict(backend.get("last_result") or {})
        if "pairing_code" in last_result:
            last_result["pairing_code"] = ""
            last_result["pairing_code_configured"] = True
        backend["last_result"] = last_result
        snapshot["backend"] = backend
        return self._phone_safe_payload(snapshot)

    def mprc_snapshot(self, *, phone_safe: bool = False) -> dict[str, Any]:
        result = self._invoke_mprc_capability("mprc.remote_state", {})
        if not isinstance(result, dict):
            snapshot = {
                "available": False,
                "message": "Multi Persona Story Mode remote state is unavailable.",
            }
        else:
            snapshot = dict(result)
            snapshot.setdefault("available", True)
        return self._phone_safe_payload(snapshot) if phone_safe else snapshot

    def buddy_chat_snapshot(self, *, phone_safe: bool = False) -> dict[str, Any]:
        invoker = getattr(self.addon_capabilities, "invoke", None)
        if not callable(invoker):
            snapshot = {
                "available": False,
                "message": "Buddy Chat addon is unavailable.",
            }
        else:
            result = invoker("buddy_chat.status", {})
            if not isinstance(result, dict):
                snapshot = {
                    "available": False,
                    "message": "Buddy Chat addon is unavailable.",
                }
            else:
                snapshot = self._buddy_chat_phone_safe_status(result) if phone_safe else dict(result)
                snapshot.setdefault("available", True)
        return self._phone_safe_payload(snapshot) if phone_safe else snapshot

    @staticmethod
    def _buddy_chat_phone_safe_status(payload: dict[str, Any]) -> dict[str, Any]:
        source = dict(payload or {})
        shared_provider = dict(source.get("shared_provider") or {})
        safe_personas = []
        for item in list(source.get("personas") or []):
            if not isinstance(item, dict):
                continue
            safe_personas.append(
                {
                    "id": str(item.get("id") or ""),
                    "display_name": str(item.get("display_name") or ""),
                    "enabled": bool(item.get("enabled", False)),
                    "source": str(item.get("source") or ""),
                    "provider_id": str(item.get("provider_id") or "inherit"),
                    "model": str(item.get("model") or ""),
                    "voice_enabled": bool(item.get("voice_enabled", False)),
                }
            )
        return {
            "available": bool(source.get("available", True)),
            "enabled": bool(source.get("enabled", False)),
            "reply_mode": str(source.get("reply_mode") or ""),
            "llm_mode": str(source.get("llm_mode") or ""),
            "persona_count": int(source.get("persona_count", len(safe_personas)) or 0),
            "active_persona_count": int(source.get("active_persona_count", 0) or 0),
            "max_speakers": int(source.get("max_speakers", 1) or 1),
            "per_persona_provider_count": int(source.get("per_persona_provider_count", 0) or 0),
            "shared_provider": {
                "provider_id": str(shared_provider.get("provider_id") or "inherit"),
                "model": str(shared_provider.get("model") or ""),
            },
            "personas": safe_personas,
            "message": str(source.get("message") or ""),
        }

    def remote_mprc_action(self, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        action_key = str(action or "").strip().lower()
        capability = MPRC_REMOTE_CAPABILITIES.get(action_key)
        if not capability:
            return {
                "accepted": False,
                "message": f"Unsupported Multi Persona Story action: {action_key or 'missing'}",
                "mprc": self.mprc_snapshot(phone_safe=True),
            }
        data = dict(payload or {})
        if action_key == "send":
            text = str(data.get("text") or data.get("message") or "").strip()
            if not text:
                return {"accepted": False, "message": "text is required", "mprc": self.mprc_snapshot(phone_safe=True)}
            data["text"] = text
            data["intent"] = str(data.get("intent") or "").strip()
            data["speaker_id"] = str(data.get("speaker_id") or "").strip()
        elif action_key == "choice":
            choice = str(data.get("choice") or data.get("choice_id") or data.get("text") or "").strip()
            if not choice:
                return {"accepted": False, "message": "choice is required", "mprc": self.mprc_snapshot(phone_safe=True)}
            data["choice"] = choice
        result = self._invoke_mprc_capability(capability, data)
        if not isinstance(result, dict):
            result = {
                "accepted": False,
                "message": "Multi Persona Story Mode did not accept the action.",
            }
        response = dict(result)
        response.setdefault("accepted", bool(response.get("accepted", False)))
        response.setdefault(
            "message",
            "Multi Persona Story Mode action queued." if bool(response.get("accepted")) else "Multi Persona Story Mode action was not accepted.",
        )
        response["mprc"] = self.mprc_snapshot(phone_safe=True)
        return self._phone_safe_payload(response)

    def _phone_safe_payload(self, value: Any):
        if isinstance(value, dict):
            return {
                str(key): self._phone_safe_payload(item)
                for key, item in value.items()
                if not self._phone_hidden_local_path_key(str(key))
                and not self._phone_hidden_secret_key(str(key))
            }
        if isinstance(value, list):
            return [self._phone_safe_payload(item) for item in value]
        return value

    @staticmethod
    def _phone_hidden_secret_key(key: str) -> bool:
        normalized = re.sub(r"[^a-z0-9]+", "_", str(key or "").strip().lower()).strip("_")
        if not normalized or normalized in PHONE_SAFE_SECRET_LIKE_KEYS:
            return False
        if normalized in PHONE_HIDDEN_SECRET_KEYS:
            return True
        compact = normalized.replace("_", "")
        return any(
            part in normalized or part.replace("_", "") in compact
            for part in PHONE_SECRET_KEY_PARTS
        )

    @staticmethod
    def _phone_hidden_local_path_key(key: str) -> bool:
        normalized = re.sub(r"[^a-z0-9]+", "_", str(key or "").strip().lower()).strip("_")
        if not normalized or normalized in PHONE_SAFE_URL_PATH_KEYS:
            return False
        if normalized in PHONE_HIDDEN_LOCAL_PATH_KEYS:
            return True
        compact = normalized.replace("_", "")
        return any(
            normalized.endswith(suffix) or compact.endswith(suffix.replace("_", ""))
            for suffix in PHONE_HIDDEN_LOCAL_PATH_SUFFIXES
        )

    def audio_file_path(self, audio_id: str) -> Path:
        return self.media_bridge.audio_file_path(audio_id)

    def remote_send_text(self, text: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        message = str(text or "").strip()
        if not message:
            return {"accepted": False, "message": "text is required", "state": self.remote_state_snapshot()}
        data = dict(options or {})
        play_on_backend = bool(data.get("play_on_backend", False))
        capture_phone_audio = bool(data.get("capture_phone_audio", True))
        self.media_bridge.begin_tts_capture(
            message,
            suppress_backend_playback=not play_on_backend,
            capture_phone_audio=capture_phone_audio,
        )

        def send() -> bool:
            sender = getattr(self.shell, "send_typed_chat_message", None)
            if not callable(sender):
                return False
            return bool(sender(message))

        accepted = bool(self._invoke_main(send))
        if not accepted:
            self.media_bridge.stop_capture()
        elif bool(data.get("visual_after_send", False)):
            try:
                self.remote_visual_request({"action": "generate", "prompt": message, "source_text": message})
            except Exception:
                pass
        return {
            "accepted": accepted,
            "message": "Queued main chat message." if accepted else "Main chat runtime did not accept the message.",
            "state": self.remote_state_snapshot(),
        }

    def remote_audio_clear(self) -> dict[str, Any]:
        self.media_bridge.cleanup()
        return {
            "accepted": True,
            "message": "Phone audio queue cleared.",
            "audio": self.media_snapshot(),
        }

    def remote_control(self, action: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        action_key = str(action or "").strip()
        if not action_key:
            return {"accepted": False, "message": "action is required", "state": self.remote_state_snapshot()}
        data = dict(options or {})
        if action_key in REMOTE_TTS_PRODUCING_ACTIONS:
            self.media_bridge.begin_tts_capture(
                f"Remote control: {action_key}",
                suppress_backend_playback=not bool(data.get("play_on_backend", False)),
                capture_phone_audio=bool(data.get("capture_phone_audio", True)),
            )

        def trigger() -> dict[str, Any]:
            controls = self._safe_service_call(self.runtime_controls, "snapshot", {})
            allowed = set(controls.get("actions") or [])
            allowed_actions = allowed or REMOTE_CONTROL_FALLBACK_ACTIONS
            if action_key not in allowed_actions:
                return {"accepted": False, "message": f"Unsupported action: {action_key}"}
            trigger = getattr(self.runtime_controls, "trigger", None)
            if not callable(trigger):
                return {"accepted": False, "message": "Runtime control service is unavailable."}
            return dict(trigger(action_key) or {})

        result = dict(self._invoke_main(trigger) or {})
        accepted = bool(result.get("accepted", False))
        if not accepted and action_key in REMOTE_TTS_PRODUCING_ACTIONS:
            self.media_bridge.stop_capture()
        return {
            "accepted": accepted,
            "message": result.get("message") or ("Control action queued." if accepted else "Control action was not accepted."),
            "control": result,
            "state": self.remote_state_snapshot(),
        }

    def remote_engine_start(self) -> dict[str, Any]:
        def start() -> dict[str, Any]:
            starter = getattr(self.engine_lifecycle, "start_engine", None)
            if callable(starter):
                result = dict(starter() or {})
                accepted = bool(result.get("accepted", True))
                return {
                    "accepted": accepted,
                    "message": result.get("message") or ("Engine start requested." if accepted else "Engine start was not accepted."),
                    "engine": result,
                }
            return {
                "accepted": False,
                "message": "Engine lifecycle service is unavailable.",
                "engine": {"running": False},
            }

        result = dict(self._invoke_main(start) or {})
        return {
            "accepted": bool(result.get("accepted", False)),
            "message": result.get("message") or "Engine start command finished.",
            "engine": dict(result.get("engine") or {}),
            "state": self.remote_state_snapshot(),
        }

    def remote_engine_stop(self) -> dict[str, Any]:
        def stop() -> dict[str, Any]:
            stopper = getattr(self.engine_lifecycle, "stop_engine", None)
            if callable(stopper):
                result = dict(stopper() or {})
                accepted = bool(result.get("accepted", True))
                return {
                    "accepted": accepted,
                    "message": result.get("message") or ("Engine stop requested." if accepted else "Engine stop was not accepted."),
                    "engine": result,
                }
            return {
                "accepted": False,
                "message": "Engine lifecycle service is unavailable.",
                "engine": {"running": False},
            }

        self.media_bridge.stop_capture()
        result = dict(self._invoke_main(stop) or {})
        return {
            "accepted": bool(result.get("accepted", False)),
            "message": result.get("message") or "Engine stop command finished.",
            "engine": dict(result.get("engine") or {}),
            "state": self.remote_state_snapshot(),
        }

    def remote_stt_upload(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = dict(payload or {})
        encoded = str(data.get("audio_base64") or data.get("audio") or "").strip()
        if not encoded:
            return {"accepted": False, "error": "audio_base64 is required"}
        if "," in encoded and encoded.lower().startswith("data:"):
            encoded = encoded.split(",", 1)[1]
        try:
            audio_bytes = base64.b64decode(encoded, validate=True)
        except Exception:
            return {"accepted": False, "error": "audio_base64 is not valid base64"}
        if not audio_bytes:
            return {"accepted": False, "error": "audio payload is empty"}
        if len(audio_bytes) > MAX_JSON_PAYLOAD_BYTES:
            return {"accepted": False, "error": "audio payload is too large"}
        transcriber = self._engine_attr("transcribe_file_with_stt", None)
        if not callable(transcriber):
            self._cleanup_stt_uploads()
            return {
                "accepted": False,
                "error": "Selected NC STT backend does not expose file transcription.",
                "audio_cached": False,
            }
        extension = self._safe_audio_extension(data.get("format") or data.get("extension") or "wav")
        self.stt_upload_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup_stt_uploads()
        audio_path = self.stt_upload_dir / f"phone_{int(time.time() * 1000)}_{secrets.token_hex(4)}{extension}"
        audio_path.write_bytes(audio_bytes)
        self._cleanup_stt_uploads()
        with self._stt_lock:
            try:
                stt_result = transcriber(str(audio_path), language=data.get("language"))
            except TypeError:
                stt_result = transcriber(str(audio_path))
            except Exception as exc:
                return {"accepted": False, "error": str(exc) or "STT transcription failed.", "audio_cached": True}
        text = self._stt_text_from_result(stt_result)
        result = {
            "accepted": bool(text),
            "text": text,
            "audio_cached": True,
            "send_to_chat": bool(data.get("send_to_chat", True)),
        }
        if text and bool(data.get("send_to_chat", True)):
            result["send_result"] = self.remote_send_text(
                text,
                {
                    "play_on_backend": bool(data.get("play_on_backend", False)),
                    "capture_phone_audio": bool(data.get("capture_phone_audio", True)),
                    "visual_after_send": bool(data.get("visual_after_send", False)),
                },
            )
        self._cleanup_stt_uploads()
        return result

    def remote_visual_request(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = dict(payload or {})
        action = str(data.get("action") or "generate").strip().lower()
        service = self.visual_reply
        if service is None:
            return {"accepted": False, "error": "Visual Reply service is unavailable.", "visual": self.visual_snapshot(phone_safe=True)}
        if action == "snapshot":
            return {"accepted": True, "visual": self.visual_snapshot(phone_safe=True)}
        if action == "show":
            return {"accepted": self._visual_service_action(service, "show"), "visual": self.visual_snapshot(phone_safe=True)}
        if action == "hide":
            return {"accepted": self._visual_service_action(service, "hide"), "visual": self.visual_snapshot(phone_safe=True)}
        if action == "clear":
            accepted = self._visual_service_action(service, "clear", auto_show=False)
            return {"accepted": accepted, "visual": self.visual_snapshot(phone_safe=True)}
        prompt = str(data.get("prompt") or data.get("source_text") or "").strip()
        if action in {"generate_last", "last_assistant"}:
            prompt = self._latest_chat_text(role="assistant")
        if not prompt:
            prompt = self._latest_chat_text(role="assistant")
        if not prompt:
            return {"accepted": False, "error": "prompt or assistant chat text is required.", "visual": self.visual_snapshot(phone_safe=True)}
        request_id = f"phone_{int(time.time())}_{secrets.token_hex(3)}"
        self._record_visual_request(
            request_id,
            "queued",
            accepted=None,
            prompt_preview=prompt[:240],
            source="phone",
        )

        def worker() -> None:
            generator = getattr(service, "request_generation", None)
            if not callable(generator):
                self._record_visual_request(
                    request_id,
                    "error",
                    accepted=False,
                    message="Visual Reply generation service is unavailable.",
                )
                return
            self._record_visual_request(request_id, "running", accepted=None)
            try:
                def generate() -> Any:
                    return generator(
                        prompt=prompt,
                        caption=str(data.get("caption") or data.get("source_text") or prompt),
                        provider=str(data.get("provider") or "inherit"),
                        model=str(data.get("model") or ""),
                        size=str(data.get("size") or "inherit"),
                        source="main_chat_remote",
                        metadata={"request_id": request_id, "remote": "phone"},
                        auto_show=bool(data.get("auto_show", True)),
                    )

                result = self._invoke_main(generate)
                if isinstance(result, dict):
                    accepted = bool(result.get("accepted", False))
                    service_request_id = str(result.get("request_id") or "")
                    image_available = bool(result.get("image_path"))
                else:
                    accepted = bool(result)
                    service_request_id = ""
                    image_available = False
                self._record_visual_request(
                    request_id,
                    "done" if accepted else "rejected",
                    accepted=accepted,
                    service_request_id=service_request_id,
                    image_available=image_available,
                )
            except Exception as exc:
                self._record_visual_request(
                    request_id,
                    "error",
                    accepted=False,
                    message=str(exc) or "Visual Reply remote request failed.",
                )
                self.log("warning", "Visual Reply remote request failed: %s", exc)

        thread = threading.Thread(target=worker, name="nc-main-chat-remote-visual", daemon=True)
        thread.start()
        return {"accepted": True, "request_id": request_id, "queued": True, "visual": self.visual_snapshot(phone_safe=True)}

    def visual_snapshot(self, *, phone_safe: bool = False) -> dict[str, Any]:
        try:
            from addons.visual_reply import state as visual_state

            current = dict(getattr(visual_state, "current_visual_reply_data", {}) or {})
        except Exception:
            current = {}
        image_path = Path(str(current.get("image_path") or ""))
        if image_path.exists() and image_path.is_file():
            current["image_url_path"] = "/api/visual/image"
            current["image_content_type"] = self.file_content_type(image_path)
            try:
                stat = image_path.stat()
                current["image_cache_key"] = f"{stat.st_mtime_ns}:{stat.st_size}"
            except Exception:
                pass
        settings = {}
        service = self.visual_reply
        settings_snapshot = getattr(service, "settings_snapshot", None)
        if callable(settings_snapshot):
            try:
                settings = dict(settings_snapshot() or {})
            except Exception:
                settings = {}
        payload = {
            "available": bool(current),
            "service_available": service is not None,
            "state": current,
            "settings": settings,
            "requests": self._visual_requests_snapshot(),
        }
        requests = payload["requests"]
        payload["latest_request"] = requests[-1] if requests else {}
        return self._phone_safe_payload(payload) if phone_safe else payload

    def visual_image_path(self) -> Path:
        state = self.visual_snapshot().get("state", {})
        path = Path(str(dict(state or {}).get("image_path") or ""))
        if path.exists() and path.is_file():
            return path
        raise FileNotFoundError("visual reply image not found")

    def visual_image_content_type(self) -> str:
        return self.file_content_type(self.visual_image_path())

    def musetalk_snapshot(self, *, after_seq: int = 0, phone_safe: bool = False) -> dict[str, Any]:
        try:
            from addons.musetalk_avatar import state as musetalk_state

            frame_state = dict(getattr(musetalk_state, "current_musetalk_frame_data", {}) or {})
            pipeline = dict(musetalk_state.get_musetalk_pipeline_snapshot() or {})
            feed = list(musetalk_state.consume_musetalk_preview_feed(after_seq=after_seq) or [])
        except Exception as exc:
            return {"available": False, "error": str(exc) or "MuseTalk state unavailable."}
        frame_paths = [str(path or "") for path in list(frame_state.get("frame_paths") or []) if str(path or "").strip()]
        frame_entries = []
        for index, raw_path in enumerate(frame_paths[:64]):
            path = Path(raw_path)
            if not path.exists() or not path.is_file():
                continue
            frame_id = self._frame_id(path)
            frame_entries.append(
                {
                    "id": frame_id,
                    "index": index,
                    "url_path": f"/api/musetalk/frame/{frame_id}",
                    "content_type": self.file_content_type(path),
                }
            )
        current_frame = str(frame_state.get("frame_path") or "")
        if current_frame:
            path = Path(current_frame)
            if path.exists() and path.is_file():
                frame_id = self._frame_id(path)
                frame_state["frame_url_path"] = f"/api/musetalk/frame/{frame_id}"
                frame_state["frame_id"] = frame_id
        if frame_entries and "frame_url_path" not in frame_state:
            frame_state["frame_url_path"] = frame_entries[0]["url_path"]
            frame_state["frame_id"] = frame_entries[0]["id"]
        frame_state["stream_url_path"] = "/api/musetalk/stream"
        payload = {
            "available": bool(frame_entries or current_frame or pipeline),
            "state": frame_state,
            "frames": frame_entries,
            "feed": [self._decorate_musetalk_feed_item(item) for item in feed[-100:]],
            "pipeline": pipeline,
            "stream_url_path": "/api/musetalk/stream",
        }
        return self._phone_safe_payload(payload) if phone_safe else payload

    def musetalk_frame_file_path(self, frame_id: str) -> Path:
        target = str(frame_id or "").strip()
        if not target:
            raise FileNotFoundError("frame id is required")
        for path in self._candidate_musetalk_frame_paths():
            if self._frame_id(path) == target and path.exists() and path.is_file():
                return path
        raise FileNotFoundError("MuseTalk frame not found")

    def musetalk_current_frame_file_path(self) -> Path:
        for path in self._candidate_musetalk_frame_paths(prefer_current=True):
            if path.exists() and path.is_file():
                return path
        raise FileNotFoundError("MuseTalk frame not found")

    def refresh_tab(self) -> None:
        if self._tab is None or QtWidgets is None:
            return
        snapshot = self.status_snapshot()
        bridge = dict(snapshot.get("bridge") or {})
        running = bool(bridge.get("running", False))
        if hasattr(self, "_enabled_checkbox"):
            self._enabled_checkbox.blockSignals(True)
            self._enabled_checkbox.setChecked(bool(self._settings.enabled))
            self._enabled_checkbox.blockSignals(False)
        if hasattr(self, "_status_label"):
            self._status_label.setText(
                f"Desktop bridge: {'running' if running else 'stopped'}\n"
                f"Local NC URL: {bridge.get('url', '')}"
            )
        backend = dict(snapshot.get("backend") or {})
        backend_running = bool(backend.get("running", False))
        backend_task = str(snapshot.get("backend_task") or "")
        if hasattr(self, "_backend_status_label"):
            message = str(backend.get("last_message") or "")
            pairing_code = str(backend.get("pairing_code") or "")
            health = dict(backend.get("health") or {})
            health_status = str(health.get("status") or "unknown")
            self._backend_status_label.setText(
                f"Phone backend: {'running' if backend_running else 'stopped'}"
                f"{' (' + backend_task + ')' if backend_task else ''}\n"
                f"{'Pairing code: ' + pairing_code + chr(10) if pairing_code else ''}"
                f"Phone app URL: {backend.get('display_url', '')}\n"
                f"Connection health: {health_status}"
                f"{chr(10) + 'Last: ' + message if message else ''}"
            )
        if hasattr(self, "_remote_command"):
            self._remote_command.setPlainText(
                f"Bridge info: {self.bridge_info_path}\n"
                f"Backend Python: {backend.get('venv_python', '')}\n"
                f"Backend log: {backend.get('log_path', '')}\n\n"
                f"{self._format_command(self.backend_process.create_venv_command())}\n"
                f"{self._format_command(self.backend_process.start_helper_command())}"
            )
        if hasattr(self, "_start_button"):
            self._start_button.setEnabled(not running)
        if hasattr(self, "_stop_button"):
            self._stop_button.setEnabled(running)
        busy = bool(backend_task)
        venv_exists = bool(backend.get("venv_python_exists", False))
        if hasattr(self, "_create_backend_venv_button"):
            self._create_backend_venv_button.setEnabled(not busy and not venv_exists)
        if hasattr(self, "_start_backend_button"):
            self._start_backend_button.setEnabled(not busy and venv_exists and not backend_running)
        if hasattr(self, "_stop_backend_button"):
            self._stop_backend_button.setEnabled(not busy and backend_running)

    def log(self, level: str, message: str, *args) -> None:
        logger = getattr(self.context, "logger", None)
        log_fn = getattr(logger, str(level or "info"), None) if logger is not None else None
        if callable(log_fn):
            try:
                log_fn("[MainChatRemote] " + message, *args)
            except Exception:
                pass

    def _set_bridge_enabled(self, enabled: bool) -> None:
        if bool(enabled):
            self.start_bridge()
        else:
            self.stop_bridge()

    def _stop_refresh_timer(self) -> None:
        timer = self._refresh_timer
        self._refresh_timer = None
        if timer is None:
            return
        try:
            timer.stop()
        except Exception:
            pass
        try:
            timeout = getattr(timer, "timeout", None)
            disconnect = getattr(timeout, "disconnect", None)
            if callable(disconnect):
                disconnect(self.refresh_tab)
        except Exception:
            pass

    @staticmethod
    def _format_command(command: list[str]) -> str:
        return subprocess.list2cmdline([str(part) for part in list(command or [])])

    def _invoke_main(self, func: Callable[[], Any]) -> Any:
        return self._invoker.invoke(func)

    def _current_backend_task(self) -> str:
        with self._backend_task_lock:
            return str(self._backend_task or "")

    def _run_backend_task(self, label: str, func: Callable[[], dict[str, Any]]) -> None:
        task = str(label or "backend task").strip()
        with self._backend_task_lock:
            if self._backend_task:
                return
            self._backend_task = task

        def worker() -> None:
            try:
                result = dict(func() or {})
                if not bool(result.get("accepted", False)):
                    self.log("warning", "%s", result.get("message") or f"{task} failed.")
            except Exception as exc:
                self.log("warning", "%s failed: %s", task, exc)
            finally:
                with self._backend_task_lock:
                    self._backend_task = ""
                try:
                    self._invoke_main(self.refresh_tab)
                except Exception:
                    pass

        threading.Thread(target=worker, name="nc-main-chat-remote-backend-task", daemon=True).start()
        self.refresh_tab()

    def _write_bridge_info(self) -> None:
        payload = {
            "service": "nc_main_chat_bridge",
            "url": f"http://{self._settings.host}:{self._settings.port}",
            "host": self._settings.host,
            "port": self._settings.port,
            "token": self._settings.token,
            "enabled": bool(self._settings.enabled),
            "updated_at": time.time(),
        }
        tmp_path: Path | None = None
        try:
            self.runtime_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = self.bridge_info_path.with_name(f".{self.bridge_info_path.name}.{secrets.token_hex(4)}.tmp")
            tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp_path.replace(self.bridge_info_path)
            self._last_bridge_info_write = time.time()
        except Exception as exc:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
            self.log("warning", "Could not write bridge info: %s", exc)

    def _remove_bridge_info(self) -> None:
        try:
            self.bridge_info_path.unlink(missing_ok=True)
            self._last_bridge_info_write = 0.0
        except Exception as exc:
            self.log("warning", "Could not remove bridge info: %s", exc)

    def _refresh_bridge_info_if_running(self) -> None:
        if not self._settings.enabled or self._bridge is None or not self._bridge.running:
            return
        now = time.time()
        if now - float(self._last_bridge_info_write or 0.0) < BRIDGE_INFO_REFRESH_SECONDS:
            return
        self._write_bridge_info()

    @staticmethod
    def _safe_service_call(service, method_name: str, default):
        method = getattr(service, str(method_name), None)
        if not callable(method):
            return default
        try:
            return method()
        except Exception:
            return default

    def _invoke_mprc_capability(self, capability: str, payload: dict[str, Any] | None = None) -> Any:
        invoker = getattr(self.addon_capabilities, "invoke", None)
        if not callable(invoker):
            return None
        try:
            return invoker(str(capability or ""), dict(payload or {}))
        except Exception as exc:
            self.log("warning", "MPRC remote capability '%s' failed: %s", capability, exc)
            return None

    def _visual_service_action(self, service, method_name: str, **kwargs) -> bool:
        method = getattr(service, str(method_name), None)
        if not callable(method):
            return False

        def call() -> bool:
            result = method(**kwargs)
            return True if result is None else bool(result)

        try:
            return bool(self._invoke_main(call))
        except Exception as exc:
            self.log("warning", "Visual Reply %s action failed: %s", method_name, exc)
            return False

    def _record_visual_request(self, request_id: str, status: str, **fields: Any) -> None:
        normalized_id = str(request_id or "").strip()
        if not normalized_id:
            return
        now = time.time()
        with self._visual_request_lock:
            existing = None
            for item in self._visual_requests:
                if str(item.get("request_id") or "") == normalized_id:
                    existing = item
                    break
            if existing is None:
                existing = {
                    "request_id": normalized_id,
                    "created_at": now,
                }
                self._visual_requests.append(existing)
            existing["status"] = str(status or "").strip() or "unknown"
            existing["updated_at"] = now
            for key, value in fields.items():
                if value is None:
                    continue
                existing[str(key)] = value
            if len(self._visual_requests) > VISUAL_REQUEST_MAX_ITEMS:
                self._visual_requests = self._visual_requests[-VISUAL_REQUEST_MAX_ITEMS:]

    def _visual_requests_snapshot(self) -> list[dict[str, Any]]:
        with self._visual_request_lock:
            return [dict(item) for item in self._visual_requests[-VISUAL_REQUEST_MAX_ITEMS:]]

    def _addon_snapshot(self, name: str) -> dict[str, Any]:
        source = getattr(self.context, str(name), None) if self.context is not None else None
        snapshot = getattr(source, "snapshot", None)
        if not callable(snapshot):
            return {}
        try:
            return dict(snapshot() or {})
        except Exception:
            return {}

    def _engine_attr(self, name: str, default=None):
        service = self.runtime_config
        getter = getattr(service, "engine_attr", None)
        if not callable(getter):
            return default
        try:
            return getter(str(name), default)
        except Exception:
            return default

    def _stt_transcriber_available(self) -> bool:
        return callable(self._engine_attr("transcribe_file_with_stt", None))

    def _latest_chat_text(self, *, role: str = "") -> str:
        chat_session = self._safe_service_call(self.chat_replay, "snapshot_chat_session", {})
        wanted_role = str(role or "").strip().lower()
        for item in reversed(list(dict(chat_session or {}).get("conversation_history") or [])):
            turn = dict(item or {})
            if wanted_role and str(turn.get("role") or "").strip().lower() != wanted_role:
                continue
            text = str(turn.get("content") or "").strip()
            if text:
                return text
        return ""

    def _candidate_musetalk_frame_paths(self, *, prefer_current: bool = False) -> list[Path]:
        try:
            from addons.musetalk_avatar import state as musetalk_state

            frame_state = dict(getattr(musetalk_state, "current_musetalk_frame_data", {}) or {})
            feed = list(musetalk_state.consume_musetalk_preview_feed(after_seq=0) or [])
        except Exception:
            frame_state = {}
            feed = []
        candidates = []
        if prefer_current and frame_state.get("frame_path"):
            candidates.append(Path(str(frame_state.get("frame_path") or "")))
        if prefer_current:
            for item in reversed(feed):
                raw = dict(item or {}).get("frame_path")
                if raw:
                    candidates.append(Path(str(raw or "")))
        for raw in list(frame_state.get("frame_paths") or []):
            candidates.append(Path(str(raw or "")))
        if not prefer_current and frame_state.get("frame_path"):
            candidates.append(Path(str(frame_state.get("frame_path") or "")))
        if not prefer_current:
            for item in feed:
                raw = dict(item or {}).get("frame_path")
                if raw:
                    candidates.append(Path(str(raw or "")))
        seen = set()
        result = []
        for path in candidates:
            key = str(path)
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(path)
        return result

    def _decorate_musetalk_feed_item(self, item: dict[str, Any]) -> dict[str, Any]:
        payload = dict(item or {})
        raw_path = str(payload.get("frame_path") or "")
        path = Path(raw_path) if raw_path else None
        if path is not None and path.exists() and path.is_file():
            frame_id = self._frame_id(path)
            payload["frame_id"] = frame_id
            payload["frame_url_path"] = f"/api/musetalk/frame/{frame_id}"
            payload["frame_content_type"] = self.file_content_type(path)
        return payload

    @staticmethod
    def _safe_audio_extension(value: Any) -> str:
        text = str(value or "wav").strip().lower().lstrip(".")
        allowed = {"wav", "mp3", "m4a", "aac", "ogg", "flac", "webm"}
        if text not in allowed:
            text = "wav"
        return f".{text}"

    @classmethod
    def _stt_text_from_result(cls, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            for key in ("text", "transcript", "transcription"):
                text = str(value.get(key) or "").strip()
                if text:
                    return text
            return cls._stt_text_from_segments(value.get("segments"))
        text_attr = getattr(value, "text", None)
        if text_attr is not None:
            return str(text_attr or "").strip()
        if isinstance(value, tuple) and len(value) == 2:
            segments, info = value
            info_text = cls._stt_text_from_result(info)
            return info_text or cls._stt_text_from_segments(segments)
        if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
            return cls._stt_text_from_segments(value)
        return ""

    @classmethod
    def _stt_text_from_segments(cls, segments: Any) -> str:
        if segments is None:
            return ""
        if isinstance(segments, (str, dict)):
            return cls._stt_text_from_result(segments)
        pieces = []
        try:
            iterator = iter(segments)
        except TypeError:
            text_attr = getattr(segments, "text", None)
            return str(text_attr or "").strip() if text_attr is not None else ""
        for item in iterator:
            text = cls._stt_text_from_result(item)
            if text:
                pieces.append(text)
        return " ".join(pieces).strip()

    def _cleanup_stt_uploads(
        self,
        *,
        now: float | None = None,
        max_age_seconds: float = STT_UPLOAD_RETENTION_SECONDS,
        max_files: int = STT_UPLOAD_MAX_FILES,
    ) -> None:
        upload_dir = self.stt_upload_dir
        if not upload_dir.exists():
            return
        current_time = time.time() if now is None else float(now)
        max_age = max(0.0, float(max_age_seconds))
        max_count = max(1, int(max_files))
        entries: list[tuple[float, Path]] = []
        for path in upload_dir.glob("phone_*"):
            try:
                if not path.is_file():
                    continue
                modified_at = float(path.stat().st_mtime)
            except Exception:
                continue
            if max_age and current_time - modified_at > max_age:
                self._unlink_quietly(path)
                continue
            entries.append((modified_at, path))
        entries.sort(key=lambda item: item[0], reverse=True)
        for _modified_at, path in entries[max_count:]:
            self._unlink_quietly(path)

    @staticmethod
    def _unlink_quietly(path: Path) -> None:
        try:
            path.unlink()
        except Exception:
            pass

    @staticmethod
    def _frame_id(path: Path) -> str:
        return hashlib.sha1(str(path.resolve()).encode("utf-8", errors="ignore")).hexdigest()[:20]

    @staticmethod
    def frame_id_for_path(path: Path) -> str:
        return MainChatRemoteController._frame_id(path)

    @staticmethod
    def file_content_type(path: Path) -> str:
        guessed, _encoding = mimetypes.guess_type(str(path))
        return str(guessed or "application/octet-stream")

    @staticmethod
    def _chat_feed(chat_session: dict[str, Any]) -> dict[str, Any]:
        history = list(dict(chat_session or {}).get("conversation_history") or [])
        messages = []
        for index, item in enumerate(history[-200:]):
            turn = dict(item or {})
            content = str(turn.get("content") or "").strip()
            if not content:
                continue
            messages.append(
                {
                    "id": str(turn.get("id") or turn.get("turn_id") or index),
                    "index": index,
                    "role": str(turn.get("role") or "").strip(),
                    "origin": str(turn.get("origin") or "").strip(),
                    "content": content,
                    "created_at": turn.get("created_at") or turn.get("timestamp"),
                }
            )
        return {
            "version": dict(chat_session or {}).get("version", 1),
            "saved_at": dict(chat_session or {}).get("saved_at", 0.0),
            "message_count": len(history),
            "messages": messages,
        }


def free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
