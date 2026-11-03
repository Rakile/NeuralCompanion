from __future__ import annotations

import base64
import copy
import hashlib
import io
import inspect
import json
import mimetypes
import queue
import re
import secrets
import socket
import subprocess
import threading
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlparse

from addons.main_chat_remote.backend_process import (
    BackendProcessSupervisor,
    generate_pairing_code,
    normalize_pairing_code,
)
from addons.main_chat_remote.certificate_manager import CertificateManager
from addons.main_chat_remote.internet_auth import InternetCredentialStore
from addons.main_chat_remote.internet_process import InternetGatewaySupervisor
from addons.main_chat_remote.internet_settings import (
    InternetRemoteSettings,
    InternetSettingsStore,
)
from addons.main_chat_remote.media_bridge import MainChatMediaBridge
from addons.main_chat_remote.presence_projection import PhonePresenceProjector
from addons.main_chat_remote.story_progress_context import recent_story_replies
from addons.main_chat_remote.phone_native_audio import NativeDispatchGuard, NativeRequestRegistry
from addons.main_chat_remote.phone_narration import split_phone_speech_clauses
from addons.main_chat_remote.phone_presentation import PhonePresentationLedger
from addons.main_chat_remote.phone_reply_receipts import PhoneReplyRejected
from addons.main_chat_remote.phone_reply_protocol import PhoneReplyProtocol, MAX_CONTROL_BODY_BYTES, wire_result
from core.addons.supervised_http import TaskSupervisedThreadingHTTPServer
from core.runtime.continuous_next_reply import voice_settings_fingerprint
from core.diagnostics.plan_trace import PlanTrace

_bridge_diagnostics = PlanTrace(component='desktop')
# Complete Desktop-owned noncached stream; physical acceptance remains separate.
ORDERED_OUTPUT_VERSION = 1

try:  # PySide6 is present in the full app, but smoke tests can run without it.
    from PySide6 import QtCore, QtGui
except Exception:  # pragma: no cover - exercised in non-Qt smoke contexts.
    QtCore = None
    QtGui = None
try:
    import qrcode
except Exception:  # Optional so an older runtime can still open the addon.
    qrcode = None


DEFAULT_BRIDGE_HOST = "127.0.0.1"
DEFAULT_BRIDGE_PORT = 8776
BRIDGE_INFO_FILE = "bridge_info.json"
MAX_JSON_PAYLOAD_BYTES = 25 * 1024 * 1024
STT_UPLOAD_RETENTION_SECONDS = 24 * 60 * 60
STT_UPLOAD_MAX_FILES = 128
IMAGE_UPLOAD_RETENTION_SECONDS = 7 * 24 * 60 * 60
IMAGE_UPLOAD_MAX_FILES = 128
VISUAL_REQUEST_MAX_ITEMS = 20
CHAT_IMAGE_REGISTRY_MAX_ITEMS = 512
CHAT_IMAGE_FIELDS = (
    "attachment_image_path",
    "visual_reply_image_path",
    "assistant_visual_reply_image_path",
    "generated_image_path",
    "visual_reply_image_paths",
    "assistant_visual_reply_image_paths",
    "generated_image_paths",
)
VISUAL_REPLY_IMAGE_FIELDS = tuple(
    field_name for field_name in CHAT_IMAGE_FIELDS if field_name != "attachment_image_path"
)
BRIDGE_INFO_REFRESH_SECONDS = 30.0
SENSITIVE_QUERY_VALUE_RE = re.compile(r"([?&](?:code|token)=)([^&\s\"']+)", re.IGNORECASE)
PHONE_DEBUG_SENSITIVE_QUERY_RE = re.compile(
    r"([?&](?:api_?key|authorization|code|password|secret|signature|ticket|token)=)"
    r"([^&\s\"'#]+)",
    re.IGNORECASE,
)
PHONE_DEBUG_BEARER_RE = re.compile(
    r"\bBearer\s+[A-Za-z0-9._~+/=-]+",
    re.IGNORECASE,
)
PHONE_DEBUG_PAIRING_CODE_RE = re.compile(
    r"\b(pairing(?:[_ -]?code)?\s*[:=]\s*)\d{4,9}\b",
    re.IGNORECASE,
)
PHONE_DEBUG_CONTENT_KEYS = {
    "audio_base64",
    "content",
    "image_base64",
    "message",
    "prompt",
    "response_text",
    "source_text",
    "stack",
    "text",
    "transcript",
}
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
    "avatar_url_path",
    "frame_url_path",
    "image_url_path",
    "mood_url_path",
    "neutral_avatar_url_path",
    "neutral_url_path",
    "stream_url_path",
    "url_path",
}
AVATAR_IMAGE_REGISTRY_MAX_ITEMS = 128
REMOTE_CONTROL_FALLBACK_ACTIONS = {
    "interrupt_response",
    "pause_speech",
    "regenerate_response",
    "replay_chat_session",
    "replay_last_assistant",
    "retry_user_input",
    "skip_speech",
    "skip_user_reply",
}
PHONE_REPLY_PLAY_ON_BACKEND = False
PHONE_REPLY_CAPTURE_AUDIO = True
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
PHONE_HIDDEN_INTERNAL_CORRELATION_KEYS = {
    "normal_chat_transaction_id",
    "remote_capture_id",
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

    def invoke(
        self,
        func: Callable[[], Any],
        *,
        timeout_seconds: float = 10.0,
        commit_call: Callable[[Callable[[], Any]], Any] | None = None,
    ) -> Any:
        def call_if_current() -> Any:
            if commit_call is not None:
                return commit_call(func)
            return func()

        if not self._qt_available:
            return call_if_current()
        try:
            if QtCore.QCoreApplication.instance() is None:
                return call_if_current()
        except Exception:
            return call_if_current()
        try:
            if QtCore.QThread.currentThread() is self.thread():
                return call_if_current()
        except Exception:
            return call_if_current()
        request = {
            "func": func,
            "commit_call": commit_call,
            "event": threading.Event(),
            "result": None,
            "error": None,
        }
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
            commit_call = request.get("commit_call")
            request["result"] = commit_call(func) if callable(commit_call) else func()
        except Exception as exc:
            request["error"] = str(exc) or repr(exc)
        finally:
            if event is not None and hasattr(event, "set"):
                event.set()


class MainChatBridgeServer:
    def __init__(self, controller: "MainChatRemoteController", settings: BridgeSettings):
        self.controller = controller
        self.settings = settings.normalized()
        self.tasks = controller.tasks
        self._server: TaskSupervisedThreadingHTTPServer | None = None
        self._worker = None
        self._lock = threading.RLock()
        self._started_at = 0.0
        self._voice_preview_cache = None

    def voice_preview_media(self, source: Path) -> Path:
        from .voice_preview_opus import VoicePreviewOpusCache
        with self._lock:
            if self._voice_preview_cache is None:
                self._voice_preview_cache = VoicePreviewOpusCache()
            cache = self._voice_preview_cache
        return cache.path_for(source)

    @property
    def running(self) -> bool:
        with self._lock:
            return (
                self._server is not None
                and self._worker is not None
                and self._worker.is_alive()
            )

    @property
    def url(self) -> str:
        return f"http://{self.settings.host}:{self.settings.port}"

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
        from core.diagnostics.policy_config import ensure_policy_loader

        ensure_policy_loader()
        handler_cls = self._handler_class()
        server = TaskSupervisedThreadingHTTPServer(
            (self.settings.host, self.settings.port),
            handler_cls,
            tasks=self.tasks,
            request_task_name="local-bridge-request",
        )
        server.bridge = self  # type: ignore[attr-defined]
        superseded = False
        with self._lock:
            if self._server is not None:
                superseded = True
            else:
                self._server = server
                self._started_at = time.time()
        if superseded:
            server.server_close()
            return

        serve_admission_lock = threading.Lock()
        serve_committed = False

        def stop_server(_reason="") -> None:
            with serve_admission_lock:
                committed = serve_committed
            if committed:
                server.shutdown()

        def serve(cancellation) -> None:
            nonlocal serve_committed
            with serve_admission_lock:
                if cancellation.cancelled:
                    return
                serve_committed = True
            try:
                server.serve_forever()
            finally:
                server.cancel_requests("local_bridge_server_retired")
                try:
                    server.server_close()
                except Exception:
                    pass
                with self._lock:
                    if self._server is server:
                        self._server = None
                        self._worker = None

        try:
            worker = self.tasks.spawn(
                "local-bridge-server",
                serve,
                on_cancel=stop_server,
            )
        except Exception:
            try:
                server.server_close()
            except Exception:
                pass
            with self._lock:
                if self._server is server:
                    self._server = None
            raise
        with self._lock:
            if self._server is server:
                self._worker = worker
            else:
                self.tasks.cancel_worker(worker, "bridge_start_superseded")
        self.controller.log("info", "Local bridge started at %s", self.url)

    def stop(self) -> None:
        with self._lock:
            server = self._server
            worker = self._worker
            self._server = None
            self._worker = None
        if server is None:
            return
        if worker is not None:
            try:
                self.tasks.cancel_worker(worker, "bridge_stopped")
                self.tasks.join_worker(worker)
            except Exception:
                pass
        else:
            try:
                server.server_close()
            except Exception:
                pass
        with self._lock:
            cache = self._voice_preview_cache
            self._voice_preview_cache = None
        if cache is not None:
            cache.close()
        self.controller.log("info", "Local bridge stopped.")

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
                trace_id=self.headers.get('X-NC-Diagnostic-Trace')
                if isinstance(trace_id,str) and re.fullmatch(r'[a-f0-9]{32}',trace_id):
                    parent=self.headers.get('X-NC-Diagnostic-Operation')
                    event=self.headers.get('X-NC-Diagnostic-Event')
                    parent=parent if isinstance(parent,str) and re.fullmatch(r'[a-f0-9]{32}',parent) else None
                    event=event if parent and isinstance(event,str) and len(event)<=64 and re.fullmatch(r'[a-f0-9]{32}:[0-9]+',event) else None
                    with _bridge_diagnostics.operation(trace_id,'desktop.bridge.handle',parent_operation_id=parent,parent_event_id=event):
                        return self._handle_request(method)
                return self._handle_request(method)

            def _handle_request(self, method: str) -> None:
                if not self._loopback_client():
                    self._send_json({"ok": False, "error": "Bridge accepts loopback clients only."}, status=403)
                    return
                if not bridge.controller._is_open():
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
                    if path.startswith('/api/soundscape/'):
                        from .soundscape.api import parse_route, MAX_BODY
                        import hashlib
                        route = parse_route(method, self.path)
                        api = getattr(bridge.controller, '_soundscape', None)
                        if api is None:
                            self._send_json({'error': 'Soundscape is unavailable.'}, status=503)
                            return
                        if method == 'POST' and int(self.headers.get('Content-Length') or 0) > MAX_BODY:
                            raise ValueError('Sound request is too large.')
                        body = self._read_json() if method == 'POST' else None
                        # The gateway has authenticated the paired installation. Never
                        # accept an owner from the body or an unverified client header.
                        owner = hashlib.sha256(('soundscape:' + bridge.settings.token).encode()).hexdigest()
                        status, result = api.dispatch(route, body, owner=owner)
                        if isinstance(result, bytes):
                            self.send_response(status)
                            self.send_header('Content-Type', 'audio/ogg')
                            self.send_header('Content-Length', str(len(result)))
                            self.send_header('Cache-Control', 'no-store')
                            self.end_headers()
                            self.wfile.write(result)
                        else:
                            self._send_json(result, status=status)
                        return
                    if path == '/api/chat-characters' or path.startswith('/api/chat-characters/'):
                        from .chat_characters_api import dispatch, parse_route, MAX_BODY
                        route = parse_route(method, path)
                        if route['action'] == 'media':
                            media = bridge.controller.remote_commands.chat_character_media(route['asset_id'])
                            if Path(media).suffix.lower() == '.wav':
                                media = bridge.voice_preview_media(Path(media))
                            self._send_file(media, content_type=bridge.controller.file_content_type(media))
                            return
                        if method == 'POST' and int(self.headers.get('Content-Length') or 0) > MAX_BODY:
                            raise ValueError('Character request is too large.')
                        body = self._read_json() if method == 'POST' else None
                        status, result = dispatch(bridge.controller.remote_commands, method, self.path, body)
                        self._send_json(result, status=status)
                        return
                    if path.startswith('/api/idle-cache/'):
                        from addons.main_chat_remote.idle_loop_http import forward_idle
                        status, body, content_type = forward_idle(
                            bridge.controller.backend_process.status_snapshot(), method, self.path)
                        if not bridge.controller._is_open() or not self._authorized(parsed.query):
                            return
                        self.send_response(status)
                        self.send_header('Content-Type', content_type)
                        self.send_header('Content-Length', str(len(body)))
                        self.send_header('Cache-Control', 'no-store')
                        self.end_headers()
                        self.wfile.write(body)
                        return
                    if path.startswith(('/api/dev/musetalk-live/', '/api/remote-output/')):
                        from addons.main_chat_remote.relay.musetalk import forward_live, is_live_route, MAX_BODY
                        if not is_live_route(method, self.path):
                            raise ValueError('Live visual route not allowed')
                        if method == 'POST' and int(self.headers.get('Content-Length') or 0) > MAX_BODY:
                            raise ValueError('Live visual payload too large')
                        payload = self._read_json() if method == 'POST' else None
                        status, body, content_type = forward_live(
                            bridge.controller.backend_process.status_snapshot(), method, path, payload)
                        self.send_response(status)
                        self.send_header('Content-Type', content_type)
                        self.send_header('Content-Length', str(len(body)))
                        self.send_header('Cache-Control', 'no-store')
                        self.end_headers()
                        self.wfile.write(body)
                        return
                    if method == "GET":
                        self._handle_get(path, parsed.query)
                        return
                    if method == "POST":
                        self._handle_post(path)
                        return
                    self._send_json({"ok": False, "error": "Method not allowed"}, status=405)
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    return
                except PhoneReplyRejected as exc:
                    status = {"authentication": 401, "ownership": 403, "capacity": 429, "unavailable": 503}.get(exc.reason, 409)
                    self._send_json({"ok": False, "error": "phone_reply_" + exc.reason}, status=status)
                except FileNotFoundError as exc:
                    self._send_json({"ok": False, "error": str(exc) or "not found"}, status=404)
                except ValueError as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=400)
                    self._finish_rejected_body()
                except Exception as exc:
                    bridge.controller.log("warning", "Bridge request failed: %s", exc)
                    self._send_json({"ok": False, "error": str(exc) or "Bridge request failed"}, status=500)

            def _handle_get(self, path: str, query: str = "") -> None:
                controller = bridge.controller
                if path == '/api/diagnostics/policy':
                    from core.diagnostics.policy import policy
                    self._send_json({'ok':True,'policy':policy.snapshot()})
                    return
                if path == '/api/internal/idle-selection':
                    self._send_json(controller.idle_selection_snapshot())
                    return
                if path == "/api/state":
                    self._send_json({"ok": True, "state": controller.remote_state_snapshot()})
                    return
                if path == "/api/audio":
                    self._send_json({"ok": True, "audio": controller.media_snapshot()})
                    return
                if path == "/api/presence":
                    self._send_json({"ok": True, "presence": controller.presence_snapshot(phone_safe=True)})
                    return
                if path == "/api/personas":
                    self._send_json({"ok": True, "personas": controller.quick_persona_snapshot()})
                    return
                if path == "/api/llm/models":
                    self._send_json({"ok": True, "models": controller.llm_model_snapshot()})
                    return
                if path == "/api/voices":
                    self._send_json({"ok": True, "voices": controller.voice_snapshot()})
                    return
                if path == "/api/tts/providers":
                    self._send_json({"ok": True, "tts": controller.tts_provider_snapshot()})
                    return
                if path.startswith("/api/avatar/file/"):
                    image_id = path.rsplit("/", 1)[-1]
                    image_path = controller.avatar_file_path(image_id)
                    self._send_file(image_path, content_type=controller.file_content_type(image_path))
                    return
                if path.startswith("/api/audio/spectrum/"):
                    audio_id = path.rsplit("/", 1)[-1]
                    spectrum_path = controller.spectrum_file_path(audio_id)
                    self._send_file(spectrum_path, content_type="application/json; charset=utf-8")
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
                if path.startswith("/api/image/file/"):
                    image_id = path.rsplit("/", 1)[-1]
                    image_path = controller.image_upload_path(image_id)
                    self._send_file(image_path, content_type=controller.file_content_type(image_path))
                    return
                if path.startswith("/api/chat/image/"):
                    image_id = path.rsplit("/", 1)[-1]
                    image_path = controller.chat_image_path(image_id)
                    self._send_file(image_path, content_type=controller.file_content_type(image_path))
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
                if path in {'/api/audio/progressive/mode', '/api/audio/progressive/read'}:
                    self._send_json({'ok': True, 'result': controller.remote_progressive_audio(
                        path.rsplit('/', 1)[-1], payload)})
                    return
                if path.startswith('/api/internal/ordered-output/'):
                    from addons.main_chat_remote.output_sequence import OutputRejected
                    from addons.main_chat_remote.phone_reply_receipts import PhoneReplyRejected
                    try:
                        result = controller.remote_ordered_output(path.rsplit('/', 1)[-1], payload)
                        self._send_json({'ok': True, 'result': result})
                    except OutputRejected as error:
                        self._send_json({'ok': False, 'error': str(error), 'outputRejection': {
                            'reason': error.reason, 'expectedOrdinal': error.expected_ordinal,
                            'actualOrdinal': error.actual_ordinal}}, status=409)
                    except PhoneReplyRejected as error:
                        reason = error.reason if error.reason in ('authentication','ownership','unavailable','capacity','pending') else 'rejected'
                        self._send_json({'ok': False, 'error': 'phone_reply_'+reason},
                                        status={'authentication':401,'unavailable':503}.get(reason,409))
                    return
                if path in {"/api/continuous/status", "/api/continuous/command", "/api/continuous/claim", "/api/continuous/models", "/api/continuous/speech"}:
                    self._send_json({"ok": True, "result": controller._continuous.handle(path.rsplit("/", 1)[-1], payload)})
                    return
                if path.startswith("/api/phone-reply/"):
                    self._send_phone_result(controller.remote_phone_reply(path.rsplit("/", 1)[-1], payload))
                    return
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
                    result = controller.remote_stt_upload(payload)
                    if "phone_reply_auth" in payload or "phone_interruption" in payload:
                        self._send_phone_result(result)
                    else:
                        self._send_json({"ok": True, "result": result})
                    return
                if path == "/api/image":
                    self._send_json({"ok": True, "result": controller.remote_image_upload(payload)})
                    return
                if path == "/api/debug":
                    self._send_json({"ok": True, "result": controller.remote_debug_upload(payload)})
                    return
                if path in {"/api/commands/start", "/api/commands/status", "/api/commands/cancel"}:
                    self._send_json({"ok": True, "result": controller._command_drafts.handle(path.rsplit("/", 1)[-1], payload)})
                    return
                if path == "/api/story-plan":
                    self._send_json({"ok": True, "result": controller._story_plans.handle(payload)})
                    return
                if path == "/api/visual-auto":
                    self._send_json({"ok": True, "result": controller.remote_visual_auto(payload)})
                    return
                if path == "/api/story-library":
                    library = getattr(controller, '_story_library', None)
                    if library is None:
                        raise ValueError('Story Library is unavailable. Restart NC desktop.')
                    self._send_json({"ok": True, "result": library.handle(payload)})
                    return
                if path == "/api/personas/select":
                    slot = payload.get("slot")
                    if isinstance(slot, bool) or not isinstance(slot, int) or slot < 0:
                        raise ValueError("a non-negative integer persona slot is required")
                    self._send_json({"ok": True, "result": controller.remote_quick_persona_select(slot)})
                    return
                if path == "/api/personas/prompts":
                    self._send_json({"ok": True, "result": controller.remote_quick_persona_prompts(payload)})
                    return
                if path == "/api/llm/models/select":
                    self._send_json({"ok": True, "result": controller.remote_llm_model_select(payload.get("provider_id"), payload.get("model_id"))})
                    return
                if path == "/api/voices/select":
                    self._send_json({"ok": True, "result": controller.remote_voice_select(payload.get("voice_id"))})
                    return
                if path == "/api/tts/providers/select":
                    self._send_json({"ok": True, "result": controller.remote_tts_provider_select(payload.get("provider_id"))})
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
                control_path = urlparse(self.path).path.startswith("/api/phone-reply/")
                # Invalid framing has no trustworthy body length. Keep even
                # its best-effort rejection cleanup strictly byte/time bounded.
                self._rejected_body_remaining = 512 * 1024
                if self.headers.get("Transfer-Encoding"):
                    raise ValueError("Unsupported transfer encoding")
                length = int(self.headers.get("Content-Length") or 0)
                if length < 0:
                    raise ValueError("Invalid content length")
                self._rejected_body_remaining = min(length, 512 * 1024)
                if length <= 0:
                    return {}
                if length > (MAX_CONTROL_BODY_BYTES if control_path else MAX_JSON_PAYLOAD_BYTES):
                    raise ValueError("payload too large")
                data = self.rfile.read(length)
                self._rejected_body_remaining = 0
                try:
                    payload = json.loads(data.decode("utf-8"))
                except Exception as exc:
                    raise ValueError("malformed JSON") from exc
                if not isinstance(payload, dict):
                    raise ValueError("JSON object expected")
                return payload

            def _finish_rejected_body(self) -> None:
                remaining = getattr(self, '_rejected_body_remaining', 0)
                if remaining <= 0:
                    return
                self.close_connection = True
                try:
                    # An immediate close with unread input can reset TCP and
                    # discard our HTTP error on Windows. Send FIN on the output
                    # half first, then drain a bounded amount of rejected input.
                    # This never parses, accepts or buffers an oversized body.
                    self.wfile.flush()
                    self.connection.shutdown(socket.SHUT_WR)
                    deadline = time.monotonic() + 0.25
                    while remaining > 0:
                        wait = deadline - time.monotonic()
                        if wait <= 0:
                            break
                        self.connection.settimeout(wait)
                        chunk = self.rfile.read1(min(64 * 1024, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                except (OSError, ValueError):
                    pass  # The response was sent; this connection will close.

            def _send_phone_result(self, result):
                outcome = result.get("status")
                status = {"stale": 409, "busy": 409, "unavailable": 503}.get(outcome, 200)
                payload = {"ok": status == 200, "result": result}
                if status != 200:
                    payload["error"] = "phone_reply_" + outcome
                self._send_json(payload, status=status)

            def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
                if not bridge.controller._is_open():
                    return
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
                if not bridge.controller._is_open():
                    return
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
                    if not bridge.controller._is_open():
                        return
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
                    if not bridge.controller._is_open():
                        return
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
    @staticmethod
    def _runtime_control_service(context) -> Any:
        get_service = getattr(context, "get_service", None)
        explicit_runtime_controls = (
            get_service("qt.runtime_controls") if callable(get_service) else None
        )
        if callable(getattr(explicit_runtime_controls, "trigger", None)):
            return explicit_runtime_controls
        return None

    def __init__(self, context=None):
        self.context = context
        self.tasks = context.tasks
        self.shell = context.capabilities.shell if context is not None else None
        self.user_image_turns = context.capabilities.user_image_turns if context is not None else None
        self.runtime_status = context.capabilities.runtime_status if context is not None else None
        self.runtime_controls = self._runtime_control_service(context)
        get_service = getattr(context, "get_service", None)
        self.chat_context = get_service("qt.chat_context") if callable(get_service) else None
        self.engine_lifecycle = context.capabilities.engine_lifecycle if context is not None else None
        self.chat_replay = context.capabilities.replay if context is not None else None
        self.runtime_config = context.capabilities.runtime_config if context is not None else None
        self.file_transcription = (
            context.capabilities.file_transcription if context is not None else None
        )
        self.visual_reply = context.capabilities.visual_reply if context is not None else None
        self.remote_commands = context.capabilities.remote_commands if context is not None else None
        self.llm_status = (
            getattr(context.capabilities, "llm_status", None) or getattr(context, "llm", None)
            if context is not None
            else None
        )
        self.tts_status = (
            getattr(context.capabilities, "tts_status", None) or getattr(context, "tts", None)
            if context is not None
            else None
        )
        self.avatar_status = (
            getattr(context.capabilities, "avatar_status", None) or getattr(context, "avatar", None)
            if context is not None
            else None
        )
        self.host = (
            getattr(context.capabilities, "host", None)
            or getattr(context.capabilities, "main_chat_remote_host", None)
            if context is not None
            else None
        )
        app_root = Path(getattr(context, "app_root", Path.cwd()) or Path.cwd()).resolve()
        self.app_root = app_root
        self.runtime_dir = app_root / "runtime" / "main_chat_remote"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        from core.diagnostics.policy_config import ensure_policy_loader
        ensure_policy_loader()
        self.stt_upload_dir = self.runtime_dir / "stt_uploads"
        self.image_upload_dir = self.runtime_dir / "image_uploads"
        self.phone_debug_dir = self.runtime_dir / "phone_debug"
        self.bridge_info_path = self.runtime_dir / BRIDGE_INFO_FILE
        from addons.main_chat_remote.relay.service import RelayService
        self.relay_service = RelayService(runtime_dir=self.runtime_dir, app_root=self.app_root, bridge_info_path=self.bridge_info_path)
        self.media_bridge = MainChatMediaBridge(
            self.runtime_dir / "audio",
            logger=getattr(context, "logger", None),
            allow_auto_capture=False,
        )
        self.backend_process = BackendProcessSupervisor(
            app_root=app_root,
            runtime_dir=self.runtime_dir,
            bridge_info_path=self.bridge_info_path,
            tasks=self.tasks,
            logger=getattr(context, "logger", None),
        )
        self.internet_dir = self.runtime_dir / "internet"
        self.internet_dir.mkdir(parents=True, exist_ok=True)
        self._internet_settings_store = InternetSettingsStore(self.internet_dir / "settings.json")
        self._internet_settings = self._internet_settings_store.load()
        self._internet_credentials = InternetCredentialStore(
            self.internet_dir / "credentials.json",
            signing_key_path=self.internet_dir / "signing.key",
        )
        self._certificate_manager = CertificateManager(
            self._internet_settings,
            runtime_dir=self.internet_dir,
        )
        self._internet_supervisor = InternetGatewaySupervisor(
            app_root=app_root,
            runtime_dir=self.internet_dir,
            tasks=self.tasks,
            logger=getattr(context, "logger", None),
        )
        self._invoker = _MainThreadInvoker()
        self._settings = BridgeSettings().normalized()
        self._pending_pairing_code = generate_pairing_code()
        self._bridge: MainChatBridgeServer | None = None
        self._tab = None
        self._refresh_timer = None
        self._backend_task_lock = threading.RLock()
        self._backend_task = ""
        self._connection_result: dict[str, Any] = {}
        self._internet_task_lock = threading.RLock()
        self._internet_task = ""
        self._internet_status_lock = threading.RLock()
        self._internet_last_error = ""
        self._internet_last_result: dict[str, Any] = {}
        self._internet_enrollment_setup_uri = ""
        self._internet_renewal_worker = None
        self._internet_snapshot: dict[str, Any] = {}
        self._stt_lock = threading.Lock()
        self._phone_upload_paths: set[Path] = set()
        self._stt_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stt_worker_active = False
        self._stt_active_job: dict[str, Any] | None = None
        self._phone_debug_lock = threading.RLock()
        self._native_requests = NativeRequestRegistry()
        self._visual_request_lock = threading.RLock()
        self._visual_requests: list[dict[str, Any]] = []
        self._chat_image_lock = threading.RLock()
        self._chat_image_paths: dict[str, Path] = {}
        self._presence_lock = threading.RLock()
        self._presence_projector = PhonePresenceProjector(self.app_root)
        self._avatar_image_paths: dict[str, Path] = {}
        self._last_bridge_info_write = 0.0
        self._bridge_info_lock = threading.RLock()
        self._bridge_info_worker = None
        self._current_pairing_setup_uri = ""
        self._host_snapshot_lock = threading.RLock()
        self._shutdown_requested = threading.Event()
        self._host_closed = False
        self._host_status_snapshot = None
        self._host_history_snapshot = None
        self._story_checkpoint_revision = None
        self._host_subscriptions = []
        controls_getter = getattr(self.host, "phone_reply_controls", None)
        controls = controls_getter() if callable(controls_getter) else None
        try:
            supports_marker = "phone_reply_control" in inspect.signature(self.user_image_turns.queue_image_turn).parameters
        except (AttributeError, TypeError, ValueError):
            supports_marker = False
        self._shared_manual_queue_supported = bool(supports_marker and
            "phone_shared_queue" in inspect.signature(self.user_image_turns.queue_image_turn).parameters
            and callable(getattr(controls, "playback_finished", None)))
        self._ordered_output_lock = threading.RLock()
        # Recovery capabilities belong to this controller's in-memory registry.
        # Public lifetime marker: never persist or reuse it after desktop restart.
        self._ordered_output_instance = secrets.token_hex(16)
        self._ordered_output = None
        self._retired_ordered_outputs = {}
        from .ordered_output_recovery import OrderedRecoveryRegistry
        self._ordered_recovery = OrderedRecoveryRegistry()
        self._phone_reply = PhoneReplyProtocol(controls if supports_marker else None, self.media_bridge,
                                              on_registered=self._ordered_reply_registered)
        self._phone_presentation = PhonePresentationLedger(
            self._phone_reply,
            logger=lambda active: self.log(
                "info", "Phone presentation ownership %s", "active" if active else "released"
            ),
        )
        self._refresh_internet_cache()
        self._bind_host_subscriptions()
        from addons.main_chat_remote.command_drafts import PhoneCommandDrafts
        self._command_drafts = PhoneCommandDrafts(
            getattr(context.capabilities, "providers", None), self._command_draft_scope,
            model_resolver=self._continuous_model, extension_context=self._story_extension_context)
        from addons.main_chat_remote.story_plan import StoryPlanStore
        from addons.main_chat_remote.story_plan_gateway import PhoneStoryPlans
        self._story_plans = PhoneStoryPlans(
            StoryPlanStore(self.runtime_dir / "story_plans.json"),
            getattr(context.capabilities, "providers", None), self._story_plan_scope)
        from .visual_auto import VisualAutoPolicy
        self._visual_auto = VisualAutoPolicy(self.runtime_dir / "visual_auto.json")
        self._visual_auto_pending: set[tuple[str, str]] = set()
        try:
            _scope = self._story_plan_scope()
            _status, _history = self._current_host_snapshots()
            _turns = list((_history or {}).get("conversation_history") or [])
            _canonical = self._phone_reply.conversation_actions_snapshot(include_history=True).get("_history") or ()
            self._visual_auto.seed_latest(_scope, _canonical if len(_canonical) >= len(_turns) else _turns)
        except (KeyError, TypeError, ValueError, OSError):
            pass
        from addons.main_chat_remote.continuous_gateway import ContinuousGateway
        self._continuous = ContinuousGateway(self, getattr(context.capabilities, "providers", None))
        self._soundscape = None
        try:
            from .soundscape.runtime import create_soundscape
            self._soundscape = create_soundscape(self.runtime_dir / 'soundscape', context,
                                                 self._story_plan_scope, model=self._soundscape_model)
            from .soundscape.desktop_import import DesktopSoundImports
            self._soundscape_imports = DesktopSoundImports(self._soundscape.library)
        except (OSError, ValueError, KeyError):
            self.log('warning', 'Soundscape storage could not open; existing chat remains available.')
        self._story_library = None
        if (self.chat_context is not None and self.remote_commands is not None
                and bool(getattr(self.chat_context, 'phone_story_available', False))):
            try:
                from .story_library_store import StoryLibraryStore
                from .story_library_session import StoryLibrarySession
                from .soundscape.story_assets import SoundscapeStoryAssets
                self._story_library = StoryLibrarySession(
                    StoryLibraryStore(self.runtime_dir / 'story_library'),
                    self.chat_context, self._story_plans, self.remote_commands.chat_characters,
                    self._story_library_scope, self._stop_story_library_playback,
                    self._refresh_story_library_chat,
                    soundscape=SoundscapeStoryAssets(self._soundscape.state, self._soundscape.library) if self._soundscape else None,
                    visual_auto=self._visual_auto)
            except (OSError, ValueError) as error:
                self.log('warning', 'Story Library could not open: %s', error)
        start_story = getattr(self.chat_context, "start_story_persistence", None)
        if callable(start_story):
            start_story()

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
        # Probe relay dependencies only. Internet connects explicitly from its
        # tab; restoring a saved login/session must not launch a relay worker.
        self.relay_service.start()
        self.refresh_tab()

    def begin_shutdown(self) -> None:
        flush_story = getattr(getattr(self, "chat_context", None), "flush_story_checkpoint", None)
        if callable(flush_story):
            flush_story()
        self._shutdown_requested.set()
        with self._ordered_output_lock:
            if self._ordered_output is not None:
                self._ordered_output.retire('disconnect')
        continuous = getattr(self, "_continuous", None)
        if continuous is not None:
            continuous.close()
        drafts = getattr(self, "_command_drafts", None)
        if drafts is not None:
            drafts.close()
        plans = getattr(self, "_story_plans", None)
        if plans is not None:
            plans.close()
        soundscape = getattr(self, '_soundscape', None)
        if soundscape is not None:
            soundscape.close()
        sound_imports = getattr(self, '_soundscape_imports', None)
        if sound_imports is not None:
            sound_imports.close()
        relay = getattr(self, "relay_service", None)
        if relay is not None:
            relay.stop()
        protocol = getattr(self, "_phone_reply", None)
        if protocol is not None:
            protocol.close()
        presentation = getattr(self, "_phone_presentation", None)
        if presentation is not None:
            presentation.close()

    def shutdown(self) -> None:
        self.begin_shutdown()
        with self._host_snapshot_lock:
            if self._host_closed:
                return
            self._host_closed = True
            subscriptions = tuple(self._host_subscriptions)
            self._host_subscriptions.clear()
        self._stop_bridge_info_heartbeat()
        self.tasks.cancel_and_join("main_chat_remote_shutdown")
        for subscription in subscriptions:
            subscription.close()
        if self.host is not None:
            self.host.close()
        self._stop_refresh_timer()
        self._tab = None
        self._cancel_internet_renewal_timer()
        self.stop_bridge()
        self.relay_service.wait_for_offline(8.0)
        self.media_bridge.cleanup()

    def _bind_host_subscriptions(self) -> None:
        if self.host is None:
            return
        self._receive_host_status(self.host.status_snapshot())
        self._receive_host_history(self.host.history_snapshot())
        self._host_subscriptions.extend(
            (
                self.host.subscribe_status(self._receive_host_status),
                self.host.subscribe_history(self._receive_host_history),
            )
        )

    def _is_open(self) -> bool:
        with self._host_snapshot_lock:
            return not self._shutdown_requested.is_set() and not self._host_closed

    def _commit_if_open(self, effect: Callable[[], Any], cancellation=None) -> Any:
        admission_scope = getattr(cancellation, "admission_scope", None)
        if callable(admission_scope):
            with admission_scope() as admitted:
                if not admitted:
                    return None
                with self._host_snapshot_lock:
                    if self._shutdown_requested.is_set() or self._host_closed:
                        return None
                    result = effect()
                    if self._shutdown_requested.is_set() or self._host_closed:
                        return None
                    return result
        with self._host_snapshot_lock:
            if self._shutdown_requested.is_set() or self._host_closed:
                return None
            result = effect()
            if self._shutdown_requested.is_set() or self._host_closed:
                return None
            return result

    def _receive_host_status(self, snapshot) -> None:
        with self._host_snapshot_lock:
            if self._host_closed:
                return
            self._host_status_snapshot = snapshot

    def _receive_host_history(self, snapshot) -> None:
        with self._host_snapshot_lock:
            if self._host_closed:
                return
            self._host_history_snapshot = snapshot
        changed = getattr(getattr(self, "chat_context", None), "story_history_changed", None)
        if callable(changed):
            changed()
        plans = getattr(self, "_story_plans", None)
        soundscape = getattr(self, "_soundscape", None)
        turns = list((snapshot or {}).get("conversation_history") or []) if isinstance(snapshot, Mapping) else []
        visual_auto = getattr(self, "_visual_auto", None)
        if not turns or (plans is None and soundscape is None and visual_auto is None):
            return
        latest = turns[-1]
        try:
            scope = self._story_plan_scope()
            conversation_id = str(scope["conversation_id"])
            if latest.get("role") != "assistant":
                if soundscape is not None:
                    soundscape.director.invalidate(conversation_id, "new_input")
                return
            assistant_id = str(latest.get("turn_id") or latest.get("id") or "")
            content = str(latest.get("content") or "")
            if visual_auto is not None:
                self._observe_auto_visual(scope, turns)
            if plans is not None:
                plans.observe(conversation_id, assistant_id, content,
                              recent_assistant_turns=recent_story_replies(turns, assistant_id))
            if soundscape is not None:
                self._observe_soundscape(scope, turns)
        except (KeyError, ValueError, TypeError):
            pass

    def _observe_soundscape(self, scope: Mapping[str, object], turns: Sequence[Mapping[str, object]]) -> None:
        """Use canonical phone history as well as Desktop history publications."""
        soundscape = getattr(self, '_soundscape', None)
        if soundscape is None or not turns:
            return
        try:
            conversation_id = str(scope.get('conversation_id') or '')
            generation = scope.get('session_generation')
            if not conversation_id or type(generation) is not int:
                return
            latest = turns[-1]
            if latest.get('role') != 'assistant' or latest.get('interrupted') or latest.get('hidden_proactive'):
                soundscape.director.invalidate(conversation_id, 'new_input_or_retired_reply')
                return
            transaction_id = str(latest.get('normal_chat_transaction_id') or '')
            reply_id = (self._phone_reply.registry.request_for_transaction(transaction_id, generation)
                        if transaction_id else None)
            if not reply_id and transaction_id:
                reply_id = self._native_requests.correlate(turns).get(transaction_id)
            if reply_id:
                plans = getattr(self, '_story_plans', None)
                plan = plans.store.snapshot(conversation_id) if plans is not None else None
                soundscape.director.observe(conversation_id, generation,
                    str(latest.get('turn_id') or latest.get('id') or ''), reply_id,
                    str(latest.get('content') or ''), plan)
        except (KeyError, ValueError, TypeError):
            return

    def _observe_auto_visual(self, scope: Mapping[str, object], turns: Sequence[Mapping[str, object]]) -> None:
        """Watch the canonical phone history as well as host history notifications."""
        policy = getattr(self, "_visual_auto", None)
        if policy is None or not turns or turns[-1].get("role") != "assistant":
            return
        conversation_id = str(scope.get("conversation_id") or "")
        turn_id = str(turns[-1].get("turn_id") or turns[-1].get("id") or "")
        if not conversation_id or not turn_id or policy.has_seen(conversation_id, turn_id):
            return
        pending_key = (conversation_id, turn_id)
        with self._visual_request_lock:
            pending = getattr(self, "_visual_auto_pending", None)
            if pending is None:
                pending = self._visual_auto_pending = set()
            if pending_key in pending:
                return
            pending.add(pending_key)
        try:
            plans = getattr(self, "_story_plans", None)
            plan = plans.store.snapshot(conversation_id) if plans is not None else None
            self.tasks.spawn("visual-auto-observe", lambda cancellation: self._observe_auto_visual_worker(
                cancellation, scope, turns, plan, pending_key))
        except (RuntimeError, OSError, ValueError) as error:
            with self._visual_request_lock:
                self._visual_auto_pending.discard(pending_key)
            self.log("warning", "Automatic Visual Reply observation could not start: %s", error)

    def _observe_auto_visual_worker(self, cancellation: Any, scope: Mapping[str, object],
                                    turns: Sequence[Mapping[str, object]],
                                    plan: Mapping[str, object] | None,
                                    pending_key: tuple[str, str]) -> None:
        try:
            if cancellation.cancelled or not self._is_open():
                return
            policy = getattr(self, "_visual_auto", None)
            if policy is None:
                return
            requests = self._visual_requests_snapshot()
            policy.refresh(scope, requests)
            busy = any(str(item.get("status") or "") in {"queued", "running", "generating"}
                       for item in requests)
            job = policy.observe(scope, turns, plan, external_busy=busy)
            if job is not None:
                self._dispatch_auto_visual(cancellation, scope, job)
        except (OSError, ValueError, TypeError) as error:
            self.log("warning", "Automatic Visual Reply observation failed: %s", error)
        finally:
            with self._visual_request_lock:
                self._visual_auto_pending.discard(pending_key)

    def _observe_story_revision(self, revision: object) -> None:
        """Checkpoint phone turns even when the desktop conversation view is hidden."""
        if type(revision) is not int or revision < 0:
            return
        if self._story_checkpoint_revision == revision:
            return
        self._story_checkpoint_revision = revision
        changed = getattr(getattr(self, "chat_context", None), "story_history_changed", None)
        if callable(changed):
            changed()

    @staticmethod
    def _mutable_host_snapshot(value):
        if isinstance(value, dict) or hasattr(value, "items"):
            return {
                key: MainChatRemoteController._mutable_host_snapshot(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [
                MainChatRemoteController._mutable_host_snapshot(item)
                for item in value
            ]
        if isinstance(value, (set, frozenset)):
            return [
                MainChatRemoteController._mutable_host_snapshot(item)
                for item in value
            ]
        return value

    def _subscribed_host_snapshots(self):
        with self._host_snapshot_lock:
            status = self._host_status_snapshot
            history = self._host_history_snapshot
        return (
            self._mutable_host_snapshot(status) if status is not None else None,
            self._mutable_host_snapshot(history) if history is not None else None,
        )

    def _current_host_snapshots(self):
        status, history = self._subscribed_host_snapshots()
        host = self.host
        if host is None:
            return status, history
        current_status = self._safe_service_call(
            getattr(host, "status_snapshot", None), status
        )
        current_history = self._safe_service_call(
            getattr(host, "history_snapshot", None), history
        )
        return (
            self._mutable_host_snapshot(current_status)
            if current_status is not None
            else None,
            self._mutable_host_snapshot(current_history)
            if current_history is not None
            else None,
        )

    def _mprc_session_active(self) -> bool:
        try:
            mprc = (
                self.remote_commands.mprc_state()
                if self.remote_commands is not None
                else None
            )
        except Exception:
            mprc = None
        session = mprc.get("session") if isinstance(mprc, Mapping) else None
        if not isinstance(session, Mapping):
            return False
        return bool(session.get("enabled", session.get("active", False)))

    def handle_tts_audio_chunk(self, payload):
        data = dict(payload or {})
        source_meta = (
            dict(data.get("source_meta") or {})
            if isinstance(data.get("source_meta"), Mapping)
            else {}
        )
        result = self.media_bridge.handle_tts_audio_chunk_ready(data)
        result_data = dict(result or {}) if isinstance(result, Mapping) else {}
        timing = data.get("preparation_timing")
        timing = timing if isinstance(timing, Mapping) else {}
        self._write_phone_debug_event(
            "info",
            "tts_audio_chunk_routed",
            {
                "remote_capture_id_present": bool(
                    str(source_meta.get("remote_capture_id") or "").strip()
                ),
                "captured_for_phone": bool(result_data.get("captured", False)),
                "desktop_playback_suppressed": bool(
                    result_data.get("skip_local_playback", False)
                ),
                "tts_backend": str(data.get("tts_backend") or "")[:80],
                "chat_character_id": str(source_meta.get("chat_character_id") or "")[:120],
                "request_id": str(source_meta.get("remote_capture_id") or "")[:120],
                "sequence_index": data.get("sequence_index"),
                "preparation_timing": {
                    key: timing[key] for key in (
                        "speech_id", "gate_wait_ms", "generation_ms", "cache_hit"
                    ) if key in timing
                },
            },
        )
        return result

    def phone_tts_voice_segments(self, payload: dict[str, Any] | None = None):
        """Publish TTS chunk events only while a phone-owned capture is active."""

        source = dict(payload or {}).get("source_meta")
        request_id = str(source.get("remote_capture_id") or "") if isinstance(source, Mapping) else ""
        policy = self.phone_native_speech_policy(request_id)
        if policy is not None:
            return policy
        if self._mprc_session_active():
            return None
        text = str(dict(payload or {}).get("text") or "").strip()
        if not text:
            return None
        segment = {
            "text": text,
            "publish_tts_addon_events": True,
        }
        media = dict(self.media_bridge.snapshot() or {})
        if not bool(media.get("capture_active", False)):
            return None
        # This capability handles phone capture before MPR is visited by the
        # first-result addon dispatcher. Delegate voice selection explicitly,
        # then decorate every segment with the existing phone delivery flag.
        peer_services = getattr(getattr(self, "context", None), "services", None)
        get_service = getattr(peer_services, "get", None)
        router = get_service("nc.multi_persona_roleplay.voice_router") if callable(get_service) else None
        split = getattr(router, "split_text_by_persona", None)
        segments = [segment]
        if callable(split):
            routed = split(dict(payload or {}))
            if isinstance(routed, Mapping) and routed.get("segments"):
                segments = [{**part, "publish_tts_addon_events": True} for part in routed["segments"]]
        if request_id:
            # Only phone-owned speech changes cadence. Keep character routing,
            # emotion tags and original text for receipts/read-along intact.
            backend = str(dict(payload or {}).get('tts_backend') or '')
            segments = [{**part, "text": phrase, **({"story_audio_cues": []} if index else {})}
                        for part in segments for index, phrase in enumerate(
                             split_phone_speech_clauses(str(part.get("text") or ""), tts_backend=backend))]
            if self.media_bridge.progressive_requested(request_id):
                segments = [{**part, 'phone_progressive_audio': True} for part in segments]
        return {"segments": segments}

    def phone_native_speech_policy(self, request_id: str) -> dict[str, Any] | None:
        if request_id and self._native_requests.owns(request_id):
            return {"segments": [], "suppress_original": True}
        return None

    def _phone_native_audio_reason(self) -> str:
        if not callable(getattr(self.user_image_turns, "queue_image_turn", None)):
            return "Phone Native requires the normal chat request queue."
        try:
            buddy = self.buddy_chat_snapshot()
            if buddy.get("available") and not buddy.get("phone_native_audio_handoff"):
                return "Update Buddy Chat to support Phone Native audio."
            if self._mprc_session_active():
                return "Phone Native is unavailable while Story Mode is enabled."
        except Exception:
            return "Phone Native audio routing is temporarily unavailable."
        return ""

    def _phone_audio_mode(self, data: dict[str, Any]) -> tuple[str, str]:
        raw = data.get("audio_mode")
        mode = "backend_hq" if raw is None or raw == "" else raw
        if mode not in ("backend_hq", "phone_native"):
            return "", "audio_mode must be backend_hq or phone_native."
        reason = self._invoke_main(self._phone_native_audio_reason) if mode == "phone_native" else ""
        return mode, reason

    def start_bridge(self) -> None:
        self._stop_bridge_info_heartbeat()
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
        self._start_bridge_info_heartbeat()
        self.refresh_tab()

    def stop_bridge(self) -> None:
        self.relay_service.disconnect()
        self._stop_bridge_info_heartbeat()
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
            "connection_result": self._connection_result_copy(),
            "bridge_info_path": str(self.bridge_info_path),
            "media": self.media_bridge.snapshot(),
            "internet": self._internet_snapshot_copy(),
        }

    def create_backend_venv(self) -> None:
        self._run_backend_task("creating backend venv", self.backend_process.create_venv)

    def _connection_result_copy(self) -> dict[str, Any]:
        with self._backend_task_lock:
            return dict(self._connection_result)

    def connect_phone(self, pairing_code=None) -> bool:
        """Prepare the existing LAN path without blocking the desktop UI."""
        code = self._pairing_code_for_start(str(pairing_code or self._pending_pairing_code or ""))

        def stage(label: str) -> None:
            with self._backend_task_lock:
                self._backend_task = label

        def connect() -> dict[str, Any]:
            with self._backend_task_lock:
                self._connection_result = {}
            result = dict(self.backend_process.create_venv() or {})
            if not result.get("accepted"):
                return result
            if not self._is_open():
                return {"accepted": False, "message": "Desktop is closing."}
            stage("Starting desktop bridge")
            # The queued callback must recheck shutdown before starting a service.
            def ensure_bridge() -> None:
                if self._bridge is None or not self._bridge.running:
                    self.start_bridge()
            self._invoke_main(lambda: self._commit_if_open(ensure_bridge))
            if not self._is_open():
                return {"accepted": False, "message": "Desktop is closing."}
            stage("Starting phone backend")
            result = dict(self.backend_process.start(pairing_code=code) or {})
            if not result.get("accepted"):
                return result
            stage("Checking phone backend")
            deadline = time.monotonic() + 10.0
            while self._is_open() and time.monotonic() < deadline:
                backend = self.backend_process.status_snapshot()
                if not backend.get("running"):
                    return {"accepted": False, "message": str(backend.get("last_message") or "Phone backend stopped. Open Troubleshooting for details.")}
                if dict(backend.get("health") or {}).get("ok"):
                    return {"accepted": True, "message": "Ready to pair. Scan the QR code with your phone app."}
                if self._shutdown_requested.wait(0.2):
                    break
            return {"accepted": False, "message": "Backend has not responded yet. Refresh status or open Troubleshooting before retrying."}

        def completed(result: dict[str, Any]) -> None:
            with self._backend_task_lock:
                self._connection_result = dict(result)

        return self._run_task(
            label="Preparing phone backend", lock=self._backend_task_lock,
            slot_name="_backend_task", func=connect,
            thread_name="nc-main-chat-connect-phone", on_complete=completed,
        )

    def start_remote_backend(self, pairing_code=None) -> None:
        requested_code = str(pairing_code or self._pending_pairing_code or "")
        try:
            pairing_code = self._pairing_code_for_start(requested_code)
        except ValueError as exc:
            self.log("warning", "Invalid pairing code: %s", exc)
            return
        self._pending_pairing_code = pairing_code
        if self._bridge is None or not self._bridge.running:
            try:
                self.start_bridge()
            except Exception as exc:
                self.log("warning", "Could not start local bridge before LAN backend: %s", exc)
        self._run_backend_task(
            "starting LAN backend",
            lambda code=pairing_code: self.backend_process.start(pairing_code=code),
        )

    def stop_remote_backend(self) -> None:
        def stop():
            self.relay_service.disconnect()
            pending_replies = ()
            # Serialize admission with the supervisor's positive process-stop
            # result. A failed/uncertain stop is not permission to replace output.
            with self._ordered_output_lock:
                result = self.backend_process.stop()
                ordered = self._ordered_output
                stopped = result.get('accepted') is True and result.get('running') is False
                if ordered is not None:
                    _bridge_diagnostics.observe(ordered.stream_id, 'desktop.ordered.recovery',
                                                'producer_stopped', True, stopped)
                    if stopped:
                        pending_replies = ordered.recovery_replies()
                        ordered.retire('disconnect')
                        _bridge_diagnostics.observe(ordered.stream_id, 'desktop.ordered.recovery',
                                                    'reader_custody_retained', None, not ordered.reclaimable)
                        result = {**result, 'message': 'LAN backend stopped; remote stream retired. Start the backend and reconnect.'}
            # Retiring the producer is not completion of its spoken replies.
            # Use exact-scope Skip outside the admission lock: runtime callbacks
            # may need that lock while settling the interrupted generation.
            if pending_replies:
                operation = hashlib.sha256(('backend-stop:' + ordered.stream_id).encode()).hexdigest()[:32]
                for reply_id in pending_replies:
                    self._phone_reply.stop_for_recovery(ordered.owner_epoch, reply_id, operation)
            return result
        self._run_backend_task("stopping LAN backend", stop)

    def stop_remote_services(self) -> bool:
        """Disconnect remote access without closing the addon or signing out."""
        if self.relay_service.snapshot().get("busy"):
            raise ValueError("Wait for the current Internet operation before stopping Remote.")

        def stop() -> dict[str, Any]:
            errors: list[str] = []
            relay = self.relay_service.snapshot()
            if relay.get("enabled") or relay.get("online") or relay.get("worker_running"):
                if not self.relay_service.submit("disconnect"):
                    errors.append("Internet disconnect was not accepted.")
                else:
                    if not self.relay_service.wait_for_offline(15.0):
                        errors.append("Internet has not disconnected; check the Internet tab.")
            if not self._is_open():
                return {"accepted": False, "message": "Desktop is closing."}
            try:
                result = self.backend_process.stop()
                if not result.get("accepted"):
                    errors.append(str(result.get("message") or "Phone backend did not stop."))
            except Exception as exc:
                errors.append(str(exc))
            try:
                self.stop_bridge()
            except Exception as exc:
                errors.append(str(exc))
            return {"accepted": not errors, "message": " ".join(errors) or "Main Chat Remote stopped."}

        def completed(result: dict[str, Any]) -> None:
            with self._backend_task_lock:
                self._connection_result = dict(result)

        return self._run_task(
            label="Stopping Main Chat Remote", lock=self._backend_task_lock,
            slot_name="_backend_task", func=stop,
            thread_name="nc-main-chat-stop-remote", on_complete=completed,
        )

    def apply_internet_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        merged = self._internet_settings.to_dict()
        merged.update(dict(payload or {}))
        self._internet_settings = self._internet_settings_store.save(
            InternetRemoteSettings.from_payload(merged)
        )
        if hasattr(self._certificate_manager, "settings"):
            self._certificate_manager.settings = self._internet_settings
        self._refresh_internet_cache()
        if self._internet_settings.enabled:
            self._run_internet_task("applying Internet settings", self._start_internet_services)
        return self._internet_snapshot_copy()

    def set_internet_enabled(self, enabled: bool) -> None:
        merged = self._internet_settings.to_dict()
        merged["enabled"] = bool(enabled)
        self._internet_settings = self._internet_settings_store.save(
            InternetRemoteSettings.from_payload(merged)
        )
        if hasattr(self._certificate_manager, "settings"):
            self._certificate_manager.settings = self._internet_settings
        if not enabled:
            self._cancel_internet_renewal_timer()
        self._refresh_internet_cache()
        operation = self._start_internet_services if enabled else self._stop_internet_services
        label = "starting Internet Remote" if enabled else "stopping Internet Remote"
        self._run_internet_task(label, operation)

    def install_certificate_helper(self) -> None:
        def install() -> dict[str, Any]:
            result = self._certificate_manager.installer.install()
            return {
                "accepted": result.accepted,
                "message": result.message,
                "executable": result.executable,
            }

        self._run_internet_task("installing certificate helper", install)

    def test_certificate_setup(self) -> None:
        self._run_internet_task(
            "testing certificate setup",
            lambda: self._certificate_result_dict(self._certificate_manager.issue(staging=True)),
        )

    def issue_internet_certificate(self) -> None:
        def issue() -> dict[str, Any]:
            result = self._certificate_manager.issue(staging=False)
            if result.accepted and self._internet_settings.enabled:
                started = self._start_internet_services()
                if not started.get("accepted"):
                    return started
            return self._certificate_result_dict(result)

        self._run_internet_task("issuing Internet certificate", issue)

    def refresh_public_ip(self) -> None:
        def refresh() -> dict[str, Any]:
            result = self._certificate_manager.detect_public_ip(explicit=True)
            if result.accepted and result.public_ip:
                merged = self._internet_settings.to_dict()
                merged["public_ip"] = result.public_ip
                self._internet_settings = self._internet_settings_store.save(
                    InternetRemoteSettings.from_payload(merged)
                )
                if hasattr(self._certificate_manager, "settings"):
                    self._certificate_manager.settings = self._internet_settings
            return {
                "accepted": result.accepted,
                "message": result.message,
                "public_ip": result.public_ip,
            }

        self._run_internet_task("detecting public IP", refresh)

    def create_internet_enrollment(self) -> dict[str, Any]:
        enrollment = self._internet_credentials.create_enrollment()
        settings = self._internet_settings
        query = urlencode(
            {
                "version": "2",
                "mode": "internet",
                "gateway_id": self._internet_credentials.gateway_id,
                "hostname_url": settings.primary_origin,
                "ip_url": settings.fallback_origin,
                "enrollment_id": enrollment.enrollment_id,
                "secret": enrollment.secret,
            }
        )
        self._internet_enrollment_setup_uri = f"ncchatremote://pair?{query}"
        self._refresh_internet_cache()
        return {
            "accepted": True,
            "enrollment_id": enrollment.enrollment_id,
            "expires_at": enrollment.expires_at,
            "setup_uri": self._internet_enrollment_setup_uri,
        }

    def approve_internet_enrollment(self, enrollment_id: str) -> bool:
        accepted = self._internet_credentials.approve_enrollment(enrollment_id)
        self._refresh_internet_cache()
        return accepted

    def reject_internet_enrollment(self, enrollment_id: str) -> bool:
        accepted = self._internet_credentials.reject_enrollment(enrollment_id)
        self._refresh_internet_cache()
        return accepted

    def revoke_internet_device(self, device_id: str) -> bool:
        accepted = self._internet_credentials.revoke_device(device_id)
        self._refresh_internet_cache()
        return accepted

    def _start_internet_services(self) -> dict[str, Any]:
        try:
            self._ensure_bridge_for_internet()
        except Exception as exc:
            return {"accepted": False, "message": f"Desktop bridge could not start: {exc}"}
        backend = dict(self.backend_process.status_snapshot() or {})
        if not backend.get("running"):
            pairing_code = generate_pairing_code()
            result = dict(self.backend_process.start(pairing_code=pairing_code) or {})
            if not result.get("accepted"):
                return {
                    "accepted": False,
                    "message": result.get("message") or "LAN phone backend could not start.",
                }
            backend = dict(self.backend_process.status_snapshot() or result)
        pairing_code = normalize_pairing_code(str(backend.get("pairing_code") or ""))
        if not pairing_code:
            return {"accepted": False, "message": "LAN backend has no active pairing code."}
        certificate = dict(self._certificate_manager.status_snapshot() or {})
        if not certificate.get("certificate_exists") or not certificate.get("private_key_exists"):
            return {
                "accepted": False,
                "message": "A valid production certificate is required before opening Internet Remote.",
            }
        result = dict(
            self._internet_supervisor.start(
                self._internet_settings,
                upstream_code=pairing_code,
            )
            or {}
        )
        if result.get("accepted"):
            self._schedule_internet_renewal()
        return result

    def _stop_internet_services(self) -> dict[str, Any]:
        self._cancel_internet_renewal_timer()
        return dict(self._internet_supervisor.stop() or {})

    def _ensure_bridge_for_internet(self) -> None:
        if self._bridge is not None and self._bridge.running:
            return
        self._stop_bridge_info_heartbeat()
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
        self._start_bridge_info_heartbeat()

    def _schedule_internet_renewal(self) -> None:
        self._cancel_internet_renewal_timer()
        if not self._internet_settings.enabled or not self._is_open():
            return
        status = dict(self._certificate_manager.status_snapshot() or {})
        next_check = float(status.get("next_check_at", 0.0) or 0.0)
        delay = max(60.0, next_check - time.time()) if next_check else 12 * 60 * 60.0
        holder = []

        def wait_for_renewal(cancellation) -> None:
            if cancellation.wait(delay) or not self._is_open():
                return
            self._internet_renewal_due(holder[0] if holder else None)

        worker = self.tasks.spawn("internet-certificate-renewal", wait_for_renewal)
        holder.append(worker)
        self._internet_renewal_worker = worker

    def _internet_renewal_due(self, worker=None) -> None:
        if worker is not None and self._internet_renewal_worker is not worker:
            return
        self._internet_renewal_worker = None
        if not self._is_open():
            return

        def renew() -> dict[str, Any]:
            result = self._certificate_manager.renew_if_due()
            payload = self._certificate_result_dict(result)
            if result.accepted and result.changed:
                backend = dict(self.backend_process.status_snapshot() or {})
                code = normalize_pairing_code(str(backend.get("pairing_code") or ""))
                if code:
                    payload = dict(
                        self._internet_supervisor.reload(
                            self._internet_settings,
                            upstream_code=code,
                        )
                        or payload
                    )
            self._schedule_internet_renewal()
            return payload

        self._run_internet_task("renewing Internet certificate", renew)

    def _cancel_internet_renewal_timer(self) -> None:
        worker = self._internet_renewal_worker
        self._internet_renewal_worker = None
        if worker is not None:
            self.tasks.cancel_worker(worker, "internet_renewal_cancelled")
            self.tasks.join_worker(worker)

    @staticmethod
    def _certificate_result_dict(result) -> dict[str, Any]:
        return {
            "accepted": bool(result.accepted),
            "message": str(result.message),
            "changed": bool(result.changed),
            "expires_at": float(result.expires_at),
            "next_check_at": float(result.next_check_at),
        }

    def _refresh_internet_cache(self) -> None:
        try:
            pending = [item.__dict__.copy() for item in self._internet_credentials.pending_enrollments()]
            devices = [item.__dict__.copy() for item in self._internet_credentials.devices()]
        except Exception:
            pending = []
            devices = []
        try:
            gateway = dict(self._internet_supervisor.status_snapshot() or {})
        except Exception:
            gateway = {"running": False}
        try:
            certificate = dict(self._certificate_manager.status_snapshot() or {})
        except Exception:
            certificate = {}
        with self._internet_status_lock:
            self._internet_snapshot = {
                "settings": self._internet_settings.to_dict(),
                "gateway": gateway,
                "certificate": certificate,
                "task": self._current_internet_task(),
                "last_error": self._internet_last_error,
                "last_result": dict(self._internet_last_result),
                "pending_enrollments": pending,
                "devices": devices,
                "enrollment_setup_uri": self._internet_enrollment_setup_uri,
            }

    def _internet_snapshot_copy(self) -> dict[str, Any]:
        with self._internet_status_lock:
            return copy.deepcopy(self._internet_snapshot)

    def _continuous_runtime(self) -> dict:
        def read():
            config = self._safe_service_call(self.runtime_config.snapshot if self.runtime_config else None, {})
            status = self._safe_service_call(self.runtime_status.snapshot if self.runtime_status else None, {})
            persona = {key: config.get(key) for key in ("active_quick_persona_name", "system_prompt", "persona_prompt_type", "emotional_instructions", "chat_character_conversation_id")}
            identity_getter = getattr(self.remote_commands, "quick_persona_identity", None)
            identity = str(identity_getter() or "") if callable(identity_getter) else ""
            stable_identity = hashlib.sha256(json.dumps([identity,
                config.get("chat_character_conversation_id")], sort_keys=True).encode()).hexdigest() if identity else ""
            return {"running": bool(status.get("running")), "persona": hashlib.sha256(json.dumps(persona, sort_keys=True).encode()).hexdigest(),
                    "persona_identity": stable_identity,
                    "persona_name": str(config.get("active_quick_persona_name") or ""),
                    "provider_id": config.get("chat_provider"), "model_id": config.get("model_name"),
                    "voice_fingerprint": voice_settings_fingerprint(config)}
        return self._invoke_main(read)

    def _soundscape_model(self) -> tuple[str, str]:
        """Only independent cloud calls may refine a nonblocking scene hint."""
        runtime = self._continuous_runtime()
        provider_id = str(runtime.get("provider_id") or "").casefold()
        model_id = str(runtime.get("model_id") or "")
        if provider_id in {"openai", "deepseek", "xai", "claude"} and model_id:
            return provider_id, model_id
        return "", ""

    def _continuous_model(self, provider_id: str, model_id: str) -> tuple[str, str]:
        def read():
            callback = getattr(self.remote_commands, "llm_model_state", None)
            state = callback() if callable(callback) else {}
            for provider in state.get("providers", []):
                if provider.get("id") != provider_id or not provider.get("available"): continue
                for model in provider.get("models", []):
                    raw = str(model.get("id") or model.get("model") or model.get("name") or "").strip()
                    if raw and secrets.compare_digest(self._llm_model_token(provider_id, raw), model_id): return provider_id, raw
            raise ValueError("Auto-Reply model is unavailable. Refresh its model list.")
        return self._invoke_main(read)

    def _command_draft_scope(self) -> object | None:
        def read() -> object | None:
            if self._shutdown_requested.is_set():
                return None
            status = self._safe_service_call(self.runtime_status.snapshot if self.runtime_status else None, {})
            if not status.get("running"):
                return None
            return self._phone_reply.conversation_actions_snapshot().get("session_generation")
        return self._invoke_main(read)

    def _story_plan_scope(self) -> dict[str, object]:
        def read() -> dict[str, object]:
            config = self._safe_service_call(self.runtime_config.snapshot if self.runtime_config else None, {})
            conversation_id = str(config.get("chat_character_conversation_id") or "")
            generation = self._phone_reply.conversation_actions_snapshot().get("session_generation")
            _status, history = self._current_host_snapshots()
            latest_id = ""
            if isinstance(history, Mapping):
                for turn in reversed(tuple(history.get("conversation_history") or ())):
                    if turn.get("role") == "assistant":
                        latest_id = str(turn.get("turn_id") or turn.get("id") or "")
                        break
            return {"conversation_id": conversation_id, "session_generation": generation,
                    "latest_assistant_id": latest_id,
                    "story_revision": (self._story_plans.store.snapshot(conversation_id) or {}).get("revision")
                    if getattr(self, "_story_plans", None) is not None and conversation_id else None}
        return self._invoke_main(read)

    def _story_library_scope(self) -> dict[str, object]:
        scope = self._story_plan_scope()
        actions = self._phone_reply.conversation_actions_snapshot(include_history=True)
        history = actions.get('_history') or ()
        return {**scope, 'revision': actions.get('revision'),
                'disabled_reason': actions.get('disabled_reason') or '',
                'last_role': history[-1].get('role') if history else ''}

    def _story_extension_context(self, options: dict[str, Any]) -> str:
        from .story_extension import extension_context
        scope = self._story_plan_scope()
        plan = self._story_plans.store.snapshot(str(scope['conversation_id']))
        if (not plan or plan['plan_id'] != options['plan_id']
                or plan['revision'] != options['revision'] or plan['status'] == 'saved'):
            raise ValueError('The story changed. Refresh before refining extra beats.')
        history = self._phone_reply.conversation_actions_snapshot(include_history=True).get('_history') or []
        continuous = getattr(self, '_continuous', None)
        played: set[str] = set()
        if continuous is not None:
            with continuous._lock:
                played = {ack[1] for ack in continuous._acks.values()
                          if ack[2] == scope['session_generation']}
        def cast_context() -> list[dict[str, str]]:
            try:
                snapshot = self.remote_commands.chat_characters({'action': 'snapshot'})
                if snapshot.get('conversation_id') != scope['conversation_id']:
                    return []
                return [{'name': str(card.get('name') or '')[:120],
                         'description': str(card.get('description') or '')[:500]}
                        for card in (snapshot.get('characters') or [])[:20]]
            except (RuntimeError, LookupError):
                return []  # Optional character addon need not be installed.
        cast = self._invoke_main(cast_context)
        return extension_context(plan, history, played) + '\nEstablished cast: ' + json.dumps(cast, ensure_ascii=False)

    def _stop_story_library_playback(self) -> None:
        continuous = getattr(self, '_continuous', None)
        if continuous is not None:
            continuous._cancel_staging('story_library_open')
            with continuous.controller._lock:
                continuous.controller._pause('Story Library opened another conversation')
        self.remote_control('interrupt_response')

    def _refresh_story_library_chat(self) -> None:
        if self.host is not None:
            self._receive_host_history(self._invoke_main(self.host.history_snapshot))

    def remote_state_snapshot(self) -> dict[str, Any]:
        def build() -> dict[str, Any]:
            subscribed_status, subscribed_history = self._current_host_snapshots()
            runtime_status = subscribed_status
            if runtime_status is None:
                runtime_status = self._safe_service_call(
                    self.runtime_status.snapshot if self.runtime_status is not None else None, {}
                )
            runtime_config = self._safe_service_call(
                self.runtime_config.snapshot if self.runtime_config is not None else None, {}
            )
            status_line = self._safe_service_call(
                self.runtime_status.status_line if self.runtime_status is not None else None,
                "runtime: unavailable",
            )
            lifecycle = self._safe_service_call(
                self.engine_lifecycle.snapshot if self.engine_lifecycle is not None else None, {}
            )
            controls = self._safe_service_call(
                self.runtime_controls.snapshot if self.runtime_controls is not None else None, {}
            )
            chat_session = subscribed_history
            if chat_session is None:
                chat_session = self._safe_service_call(
                    self.chat_replay.snapshot_chat_session if self.chat_replay is not None else None, {}
                )
            replayable = self._safe_service_call(
                self.chat_replay.replayable_chat_entries if self.chat_replay is not None else None, []
            )
            mprc = self.mprc_snapshot(phone_safe=True)
            buddy_chat = self.buddy_chat_snapshot(phone_safe=True)
            native_audio_reason = self._phone_native_audio_reason()
            conversation_actions = self._phone_reply.conversation_actions_snapshot(
                include_history=True, include_preview=True,
            )
            self._observe_story_revision(conversation_actions.get("revision"))
            canonical_history = conversation_actions.pop('_history', None)
            stream_preview = conversation_actions.pop('_stream_preview', None)
            conversation_actions.pop('_retired_revision', None)
            if canonical_history is not None:
                chat_session = dict(chat_session or {}, conversation_history=canonical_history)
                if getattr(self, '_soundscape', None) is not None:
                    self._observe_soundscape(self._story_plan_scope(), canonical_history)
                if getattr(self, "_visual_auto", None) is not None:
                    self._observe_auto_visual(self._story_plan_scope(), canonical_history)
            if stream_preview is not None:
                chat_session = dict(chat_session or {}, streaming_preview=stream_preview)
            return {
                "ordered_output_instance": self._ordered_output_instance,
                "runtime_status": runtime_status,
                "runtime_settings": self._runtime_settings_summary(runtime_config),
                "status_line": status_line,
                "engine": lifecycle,
                "controls": controls,
                "chat": self._chat_feed(chat_session),
                "conversation_actions": conversation_actions,
                "replayable": list(replayable or [])[-100:],
                "llm": self._addon_snapshot("llm"),
                "tts": self._addon_snapshot("tts"),
                "avatar": self._addon_snapshot("avatar"),
                "media": self.media_bridge.snapshot(),
                "presence": self.presence_snapshot(phone_safe=True),
                "visual": self.visual_snapshot(phone_safe=True),
                "musetalk": self.musetalk_snapshot(phone_safe=True),
                "mprc": mprc,
                "buddy_chat": buddy_chat,
                "remote": self._phone_status_snapshot(),
                "command_drafts": getattr(self, "_command_drafts", None).choices() if getattr(self, "_command_drafts", None) else [],
                "features": {
                    **({"soundscape_version": 1, "soundscape_context_version": 1} if getattr(self, '_soundscape', None) is not None else {}),
                    **({"story_plan_version": 1, "story_refine_options_version": 1, "story_extension_version": 1} if getattr(self, "_story_plans", None) is not None else {}),
                    **({"visual_auto_version": 1} if getattr(self, "_visual_auto", None) is not None else {}),
                    **({"story_library_version": 1} if getattr(self, "_story_library", None) is not None else {}),
                    **({"story_checkpoint_version": 1} if bool(getattr(getattr(self, "chat_context", None), "phone_story_available", False)) else {}),
                    **({"continuous_version": 1} if getattr(self, "_continuous", None) is not None and self._continuous.available else {}),
                    "chat_characters_version": 1,
                    "chat_reset": callable(getattr(self.engine_lifecycle, "reset_chat_memory", None)),
                    **({"conversation_actions_version": 1} if self._phone_reply.conversation_actions_available else {}),
                    **({"phone_reply_controls_version": 1, "progressive_audio_version": 1} if getattr(self, "_phone_reply", None) is not None and self._phone_reply.available else {}),
                    **({"shared_manual_queue_version": 1} if getattr(self, "_shared_manual_queue_supported", False) and self._phone_reply.available else {}),
                    **({"reply_continuation_version": 1} if getattr(self, "_shared_manual_queue_supported", False) and self._phone_reply.available else {}),
                    **({"phone_presentation_version": 1} if getattr(self, "_phone_reply", None) is not None and self._phone_reply.available else {}),
                    "text_send": True,
                    "runtime_status": True,
                    "presence_state": True,
                    "tts_audio_chunks": True,
                    "phone_stt": self._stt_transcriber_available(),
                    "phone_image_upload": True,
                    "phone_native_audio": not bool(native_audio_reason),
                    "phone_native_audio_reason": native_audio_reason,
                    "phone_debug_upload": True,
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

    def presence_snapshot(self, *, phone_safe: bool = True) -> dict[str, Any]:
        """Return addon-owned, phone-safe companion Presence state."""

        subscribed_status, _subscribed_history = self._invoke_main(
            self._current_host_snapshots
        )
        runtime_status = subscribed_status
        if runtime_status is None:
            runtime_status = self._invoke_main(
                lambda: self._safe_service_call(
                    self.runtime_status.snapshot if self.runtime_status is not None else None,
                    {},
                )
            )
        raw_playback = self._invoke_main(lambda: self._safe_service_call(
            getattr(self.host, "portrait_playback_snapshot", None), {}
        ))
        portrait_playback = None
        if isinstance(raw_playback, Mapping):
            message_id = str(raw_playback.get("message_id") or "")
            transaction_id = str(raw_playback.get("transaction_id") or "")
            mood = str(raw_playback.get("mood") or "").strip().casefold()
            if (message_id and len(message_id) <= 120 and
                    re.fullmatch(r"[A-Za-z0-9_.:-]+", message_id) and
                    re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", mood)):
                portrait_playback = {
                    "message_id": message_id,
                    "portrait_key": hashlib.sha256(transaction_id.encode("ascii")).hexdigest()[:24]
                    if re.fullmatch(r"[0-9a-f]{32}", transaction_id) else "",
                    "mood": mood,
                }
        with self._presence_lock:
            projection = self._presence_projector.project(
                runtime_status=runtime_status,
                visual_presence=self._visual_presence_snapshot(),
                media=self.media_bridge.snapshot(),
                musetalk=self._presence_musetalk_snapshot(),
                portrait_playback=portrait_playback,
            )
            neutral_identity = self._presence_projector.message_persona({"content": ""})
            payload = copy.deepcopy(projection.payload)
            registered = self._register_avatar_image(projection.avatar_path)
            registered_neutral = self._register_avatar_image(neutral_identity.avatar_path)
        if registered is not None:
            image_id, image_path = registered
            avatar = dict(payload.get("avatar") or {})
            avatar["url_path"] = f"/api/avatar/file/{image_id}"
            avatar["content_type"] = self.file_content_type(image_path)
            if projection.avatar_path != neutral_identity.avatar_path:
                avatar["mood_url_path"] = avatar["url_path"]
            payload["avatar"] = avatar
        if registered_neutral is not None:
            neutral_id, _neutral_path = registered_neutral
            avatar = dict(payload.get("avatar") or {})
            avatar["neutral_url_path"] = f"/api/avatar/file/{neutral_id}"
            payload["avatar"] = avatar
        return self._phone_safe_payload(payload) if phone_safe else payload

    def quick_persona_snapshot(self) -> dict[str, Any]:
        """Return saved Quick Personas without exposing their runtime records."""

        try:
            raw_items = self._invoke_main(
                lambda: (
                    self.remote_commands.quick_persona_state()
                    if self.remote_commands is not None
                    else []
                )
            )
        except Exception as exc:
            self.log("warning", "Quick Persona remote state failed: %s", exc)
            raw_items = []
        items: list[dict[str, Any]] = []
        active_slot = -1
        for raw in list(raw_items or []):
            if not isinstance(raw, Mapping):
                continue
            try:
                slot = int(raw.get("slot", -1))
            except (TypeError, ValueError):
                continue
            if slot < 0:
                continue
            name = str(raw.get("name") or f"Persona {slot + 1}").strip()
            persona_id = str(raw.get("id") or f"persona-{slot + 1}").strip()
            initials = "".join(
                word[0].upper() for word in name.split()[:2] if word
            ) or "NC"
            item: dict[str, Any] = {
                "slot": slot,
                "id": persona_id,
                "name": name,
                "initials": initials[:2],
                "active": bool(raw.get("active", False)),
            }
            avatar_value = str(raw.get("avatar_path") or "").strip()
            if avatar_value:
                avatar_path = Path(avatar_value)
                if not avatar_path.is_absolute():
                    avatar_path = self.app_root / avatar_path
                registered = self._register_avatar_image(avatar_path)
                if registered is not None:
                    image_id, image_path = registered
                    item["avatar_url_path"] = f"/api/avatar/file/{image_id}"
                    item["avatar_content_type"] = self.file_content_type(image_path)
            if item["active"]:
                active_slot = slot
            items.append(item)
        return self._phone_safe_payload(
            {
                "schema_version": 1,
                "active_slot": active_slot,
                "items": items,
            }
        )

    def remote_quick_persona_select(self, slot: int) -> dict[str, Any]:
        normalized_slot = int(slot)
        if normalized_slot < 0:
            raise ValueError("a non-negative integer persona slot is required")
        try:
            result = self._invoke_main(
                lambda: (
                    self.remote_commands.quick_persona_apply(normalized_slot)
                    if self.remote_commands is not None
                    else None
                )
            )
        except Exception as exc:
            self.log("warning", "Quick Persona remote activation failed: %s", exc)
            result = None
        if not isinstance(result, Mapping):
            return {
                "accepted": False,
                "message": "Quick Persona controls are unavailable.",
            }
        response = dict(result)
        response["accepted"] = bool(response.get("accepted", False))
        response.setdefault(
            "message",
            "Quick Persona activated."
            if response["accepted"]
            else "Quick Persona was not activated.",
        )
        return self._phone_safe_payload(response)

    def remote_quick_persona_prompts(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        handler = getattr(self.remote_commands, 'quick_persona_prompts', None)
        if not callable(handler):
            raise ValueError('Update the desktop to edit persona prompts.')
        # HTTP worker owns disk access; only the small runtime update uses Qt.
        result = handler(dict(payload))
        catalog = getattr(self.remote_commands, 'persona_rule_catalog', None)
        if callable(catalog):
            result['rule_catalog'] = self._invoke_main(lambda: catalog(result))
        if payload.get('action', 'read') != 'read':
            apply = getattr(self.remote_commands, 'apply_persona_prompts', None)
            if callable(apply):
                self._invoke_main(lambda: apply(result))
        return result

    @staticmethod
    def _llm_model_token(provider_id: str, model_id: str) -> str:
        return hashlib.sha256(f"{provider_id}\0{model_id}".encode("utf-8")).hexdigest()

    @staticmethod
    def _voice_token(voice_path: str) -> str:
        return hashlib.sha256(f"voice\0{voice_path}".encode("utf-8")).hexdigest()

    def voice_snapshot(self) -> dict[str, Any]:
        try:
            callback = getattr(self.remote_commands, "voice_state", None)
            state = self._invoke_main(callback) if callable(callback) else {}
        except Exception:
            state = {}
        if not isinstance(state, Mapping):
            state = {}
        items = []
        for item in state.get("items") or []:
            if not isinstance(item, Mapping) or not isinstance(item.get("value"), str):
                continue
            value = item["value"]
            label = str(item.get("label") or "Voice").replace("\\", "/").rsplit("/", 1)[-1] if value else "Built-in / default voice"
            items.append({"id": self._voice_token(value), "label": label[:240], "selected": value == state.get("selected")})
        available = bool(state.get("available"))
        return {"schema_version": 1, "available": available, "loading": bool(state.get("loading")),
                "message": "" if available else "Voice controls are unavailable. Update or check the desktop.", "items": items}

    def tts_provider_snapshot(self) -> dict[str, Any]:
        from addons.main_chat_remote.tts_provider_gateway import TtsProviderGateway
        return TtsProviderGateway(self).snapshot()

    def remote_tts_provider_select(self, provider_id: Any) -> dict[str, Any]:
        from addons.main_chat_remote.tts_provider_gateway import TtsProviderGateway
        return TtsProviderGateway(self).select(provider_id)

    def remote_voice_select(self, voice_id: Any) -> dict[str, Any]:
        if not isinstance(voice_id, str) or not re.fullmatch(r"[a-f0-9]{64}", voice_id):
            raise ValueError("a valid voice_id from the voice list is required")

        def apply() -> bool:
            state_callback = getattr(self.remote_commands, "voice_state", None)
            apply_callback = getattr(self.remote_commands, "voice_apply", None)
            if not callable(state_callback) or not callable(apply_callback):
                return False
            state = state_callback()
            if not state.get("available"):
                return False
            for item in state.get("items") or []:
                value = item.get("value")
                if isinstance(value, str) and secrets.compare_digest(self._voice_token(value), voice_id):
                    result = apply_callback(value)
                    return isinstance(result, Mapping) and bool(result.get("accepted"))
            return False

        try:
            accepted = bool(self._invoke_main(apply))
        except Exception:
            accepted = False
        return {"accepted": accepted, "message": "Conversation voice changed." if accepted else "Voice was not changed. Refresh the list or check the desktop."}

    def llm_model_snapshot(self) -> dict[str, Any]:
        """Expose only display metadata; model paths stay behind opaque ids."""
        try:
            callback = getattr(self.remote_commands, "llm_model_state", None)
            state = self._invoke_main(callback) if callable(callback) else {}
        except Exception:
            state = {}
        if not isinstance(state, Mapping):
            state = {}
        selected_provider = str(state.get("selected_provider_id") or "")
        selected_model = str(state.get("selected_model_id") or "")
        providers: list[dict[str, Any]] = []
        for raw in list(state.get("providers") or []):
            if not isinstance(raw, Mapping):
                continue
            provider_id = str(raw.get("id") or "")
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", provider_id):
                continue
            models: list[dict[str, Any]] = []
            seen: set[str] = set()
            for model in list(raw.get("models") or []):
                if not isinstance(model, Mapping):
                    continue
                model_id = str(model.get("id") or model.get("model") or model.get("name") or "").strip()
                if not model_id or model_id in seen:
                    continue
                seen.add(model_id)
                label = model_id
                if label.startswith(("/", "~", "./", "../")) or "\\" in label or label.lower().endswith((".gguf", ".safetensors", ".bin")) or re.match(r"^[A-Za-z]:[\\/]", label):
                    label = label.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
                if "://" in label or any(char in label for char in "?\r\n\t"):
                    label = "Configured model"
                models.append({
                    "id": self._llm_model_token(provider_id, model_id),
                    "label": label[:240],
                    "selected": provider_id == selected_provider and model_id == selected_model,
                })
            available = bool(raw.get("available", False))
            providers.append({
                "id": provider_id, "label": str(raw.get("label") or provider_id)[:120],
                "selected": provider_id == selected_provider, "available": available,
                "loading": bool(raw.get("loading", False)),
                "message": ("Could not load models. Check the provider on the desktop." if available else "Provider is unavailable on the desktop.") if raw.get("message") or not available else "",
                "models": models,
            })
        available = bool(state.get("available", False))
        if not any(item["id"] == selected_provider for item in providers):
            selected_provider, selected_model = "", ""
        return {
            "schema_version": 1, "available": available,
            "loading": bool(state.get("loading", False)),
            "message": "" if available else "Model controls are unavailable on this desktop.",
            "selected_provider_id": selected_provider,
            "selected_model_id": self._llm_model_token(selected_provider, selected_model) if selected_model else "",
            "providers": providers,
        }

    def remote_llm_model_select(self, provider_id: Any, model_id: Any) -> dict[str, Any]:
        if not isinstance(provider_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", provider_id):
            raise ValueError("a valid provider_id is required")
        if not isinstance(model_id, str) or not re.fullmatch(r"[a-f0-9]{64}", model_id):
            raise ValueError("a valid model_id from the model list is required")

        def apply() -> bool:
            state_callback = getattr(self.remote_commands, "llm_model_state", None)
            apply_callback = getattr(self.remote_commands, "llm_model_apply", None)
            if not callable(state_callback) or not callable(apply_callback):
                return False
            state = state_callback()
            for provider in list(state.get("providers") or []):
                if provider.get("id") != provider_id or not provider.get("available"):
                    continue
                for model in list(provider.get("models") or []):
                    raw_id = str(model.get("id") or model.get("model") or model.get("name") or "").strip()
                    if raw_id and secrets.compare_digest(self._llm_model_token(provider_id, raw_id), model_id):
                        result = apply_callback(provider_id, raw_id)
                        return isinstance(result, Mapping) and bool(result.get("accepted", False))
            return False

        try:
            accepted = bool(self._invoke_main(apply))
        except Exception:
            accepted = False
        return {
            "accepted": accepted,
            "message": "Language model selected." if accepted else "Model selection failed. Refresh the list or check the desktop.",
        }

    @staticmethod
    def _presence_musetalk_snapshot() -> dict[str, Any]:
        """Read a lightweight MuseTalk summary without scanning frame files."""

        try:
            from addons.musetalk_avatar import state as musetalk_state

            frame_state = dict(getattr(musetalk_state, "current_musetalk_frame_data", {}) or {})
            pipeline = dict(musetalk_state.get_musetalk_pipeline_snapshot() or {})
            frame_paths = list(frame_state.get("frame_paths") or [])
            renderable = bool(frame_state.get("frame_path") or frame_paths)
            status = str(frame_state.get("status") or "idle")
            sync_time = frame_state.get("updated_at") or frame_state.get("sync_time") or 0.0
            return {
                "available": bool(renderable or pipeline.get("active")),
                "renderable": renderable,
                "state": {
                    "status": status,
                    "sync_time": sync_time,
                },
                "pipeline": {
                    "active": bool(pipeline.get("active")),
                    "updated_at": pipeline.get("updated_at") or 0.0,
                },
            }
        except Exception:
            return {"available": False, "renderable": False}

    @staticmethod
    def _visual_presence_snapshot() -> dict[str, Any]:
        try:
            from visual_presence import runtime as visual_presence_runtime

            return dict(visual_presence_runtime.snapshot_state() or {})
        except Exception:
            return {}

    def avatar_file_path(self, image_id: str) -> Path:
        wanted = re.sub(r"[^A-Za-z0-9_.-]+", "", str(image_id or ""))
        if not wanted:
            raise FileNotFoundError("avatar image id is required")
        with self._presence_lock:
            path = self._avatar_image_paths.get(wanted)
        if path is None or not path.is_file() or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise FileNotFoundError("avatar image not found")
        return path

    def _register_avatar_image(self, path: Path | None) -> tuple[str, Path] | None:
        if path is None:
            return None
        try:
            resolved = path.resolve()
            resolved.relative_to((self.app_root / "runtime" / "quick_personas").resolve())
        except (OSError, ValueError):
            return None
        if not resolved.is_file() or resolved.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            return None
        try:
            version = resolved.stat()
        except OSError:
            return None
        # Stable across reconnects, but a replaced portrait gets a new cache key.
        identity = f"{resolved}\0{version.st_mtime_ns}\0{version.st_size}"
        image_id = hashlib.sha1(identity.encode("utf-8", errors="ignore")).hexdigest()[:20]
        with self._presence_lock:
            self._avatar_image_paths[image_id] = resolved
            while len(self._avatar_image_paths) > AVATAR_IMAGE_REGISTRY_MAX_ITEMS:
                self._avatar_image_paths.pop(next(iter(self._avatar_image_paths)))
        return image_id, resolved

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
        try:
            result = (
                self.remote_commands.mprc_state()
                if self.remote_commands is not None
                else None
            )
        except Exception as exc:
            self.log("warning", "MPRC remote state failed: %s", exc)
            result = None
        if not isinstance(result, Mapping):
            snapshot = {
                "available": False,
                "message": "Multi Persona Story Mode remote state is unavailable.",
            }
        else:
            snapshot = self._mutable_host_snapshot(result)
            snapshot.setdefault("available", True)
        return self._phone_safe_payload(snapshot) if phone_safe else snapshot

    def buddy_chat_snapshot(self, *, phone_safe: bool = False) -> dict[str, Any]:
        if self.remote_commands is None:
            snapshot = {
                "available": False,
                "message": "Buddy Chat addon is unavailable.",
            }
        else:
            result = self.remote_commands.buddy_status()
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
            "last_provider_error": str(source.get("last_provider_error") or "")[:1200],
            "last_provider_error_at": float(source.get("last_provider_error_at", 0.0) or 0.0),
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
        if not self._is_open():
            return {
                "accepted": False,
                "message": "Main Chat Remote is shutting down.",
            }
        action_key = str(action or "").strip().lower()
        if action_key not in {"send", "choice", "play", "pause", "visual", "cast"}:
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
        try:
            if self.remote_commands is None:
                result = None
            elif action_key == "send":
                result = self.remote_commands.mprc_send(data)
            elif action_key == "choice":
                result = self.remote_commands.mprc_choice(data)
            elif action_key == "play":
                result = self.remote_commands.mprc_play(data)
            elif action_key == "pause":
                result = self.remote_commands.mprc_pause(data)
            elif action_key == "visual":
                result = self.remote_commands.mprc_visual(data)
            else:
                result = self.remote_commands.mprc_cast(data)
        except Exception as exc:
            self.log("warning", "MPRC remote action '%s' failed: %s", action_key, exc)
            result = None
        if not isinstance(result, Mapping):
            result = {
                "accepted": False,
                "message": "Multi Persona Story Mode did not accept the action.",
            }
        response = self._mutable_host_snapshot(result)
        # Native Story commands return the updated snapshot on success.
        is_story_snapshot = (
            response.get("schema_version") == 1
            and isinstance(response.get("session"), Mapping)
            and isinstance(response.get("personas"), list)
        )
        response["accepted"] = (
            bool(response.get("accepted", is_story_snapshot))
            and response.get("ok") is not False
            and response.get("available") is not False
            and not bool(response.get("error"))
        )
        response.setdefault(
            "message",
            "Multi Persona Story Mode action queued." if bool(response.get("accepted")) else "Multi Persona Story Mode action was not accepted.",
        )
        response["mprc"] = self.mprc_snapshot(phone_safe=True)
        return self._phone_safe_payload(response)

    def _phone_safe_payload(self, value: Any):
        if isinstance(value, Mapping):
            return {
                str(key): self._phone_safe_payload(item)
                for key, item in value.items()
                if not self._phone_hidden_local_path_key(str(key))
                and not self._phone_hidden_secret_key(str(key))
                and not self._phone_hidden_internal_correlation_key(str(key))
            }
        if isinstance(value, (list, tuple, set, frozenset)):
            return [self._phone_safe_payload(item) for item in value]
        return value

    @staticmethod
    def _phone_hidden_internal_correlation_key(key: str) -> bool:
        normalized = re.sub(
            r"[^a-z0-9]+", "_", str(key or "").strip().lower()
        ).strip("_")
        return normalized in PHONE_HIDDEN_INTERNAL_CORRELATION_KEYS

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
        try:
            return self.media_bridge.audio_file_path(audio_id)
        except FileNotFoundError:
            continuous = getattr(self, "_continuous", None)
            if continuous is None:
                raise
            return continuous.speech.media.audio_file_path(audio_id)

    def spectrum_file_path(self, audio_id: str) -> Path:
        return self.media_bridge.spectrum_file_path(audio_id)

    def remote_send_text(self, text: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._is_open():
            return {"accepted": False, "message": "Main Chat Remote is shutting down."}
        message = str(text or "").strip()
        if not message:
            return {"accepted": False, "message": "text is required", "state": self.remote_state_snapshot()}
        data = dict(options or {})
        phone_control = "phone_reply_auth" in data
        if phone_control:
            self._phone_reply.authenticate(data["phone_reply_auth"])
            if data.get("audio_mode") not in (None, "", "backend_hq"):
                raise PhoneReplyRejected("unavailable")
        audio_mode, audio_error = self._phone_audio_mode(data)
        if audio_error:
            return {"accepted": False, "error": audio_error, "state": self.remote_state_snapshot()}
        play_on_backend = PHONE_REPLY_PLAY_ON_BACKEND
        capture_phone_audio = audio_mode == "backend_hq" and PHONE_REPLY_CAPTURE_AUDIO
        debug_trace_id = (
            str(data.get("debug_trace_id") or "").strip()[:80]
            or f"text-{secrets.token_hex(6)}"
        )
        capture_id = self._phone_reply.register(data["phone_reply_auth"]) if phone_control else secrets.token_urlsafe(18)
        if audio_mode == "phone_native":
            if not self._native_requests.register(capture_id):
                return {"accepted": False, "error": "Phone Native request capacity reached. Wait for pending replies."}
        elif not phone_control:
            self.media_bridge.begin_tts_capture(
                message,
                suppress_backend_playback=not play_on_backend,
                capture_phone_audio=capture_phone_audio,
                capture_id=capture_id,
            )
        self._write_phone_debug_event(
            "info",
            "phone_text_received",
            {
                "debug_trace_id": debug_trace_id,
                "character_count": len(message),
                "capture_phone_audio": capture_phone_audio,
                "play_on_backend": play_on_backend,
            },
        )

        dispatch_path = "unavailable"
        native_dispatch = NativeDispatchGuard() if audio_mode == "phone_native" or phone_control else None

        def send() -> tuple[bool, str]:
            if not self._is_open():
                return False, "controller_closed"
            if audio_mode == "phone_native" and self._phone_native_audio_reason():
                return False, "native_routing_unavailable"
            result = self._queue_phone_text_turn(message, capture_id, phone_reply_control=phone_control,
                                                phone_shared_queue=phone_control and self._phone_reply.registry.shared_queue_enabled(data["phone_reply_auth"]))
            if result[0] and phone_control:
                continuous = getattr(self, "_continuous", None)
                if continuous:
                    continuous.observe_manual_input(data["phone_reply_auth"], capture_id)
            return result

        try:
            send_result = (
                self._invoke_main(send, commit_call=native_dispatch.commit)
                if native_dispatch is not None else self._invoke_main(send)
            )
            if isinstance(send_result, tuple) and len(send_result) == 2:
                accepted = bool(send_result[0])
                dispatch_path = str(send_result[1] or "unknown")[:80]
            else:
                accepted = bool(send_result)
                dispatch_path = "legacy_result"
        except Exception as exc:
            if phone_control:
                self._phone_reply.cancel(capture_id)
            self.media_bridge.cancel_tts_capture(capture_id)
            if native_dispatch is None or native_dispatch.cancel_before_start():
                self._native_requests.discard(capture_id)
            self._write_phone_debug_event(
                "error",
                "phone_text_dispatch_failed",
                {
                    "debug_trace_id": debug_trace_id,
                    "error_type": type(exc).__name__,
                },
            )
            return {
                "accepted": False,
                "error": "Main chat runtime did not accept the message.",
                "debug_trace_id": debug_trace_id,
                "state": self.remote_state_snapshot(),
            }
        if not accepted:
            if phone_control:
                self._phone_reply.cancel(capture_id)
            self.media_bridge.cancel_tts_capture(capture_id)
            self._native_requests.discard(capture_id)
        elif bool(data.get("visual_after_send", False)):
            try:
                self.remote_visual_request({"action": "generate", "prompt": message, "source_text": message})
            except Exception:
                pass
        self._write_phone_debug_event(
            "info" if accepted else "warning",
            "phone_text_dispatch_result",
            {
                "debug_trace_id": debug_trace_id,
                "accepted": accepted,
                "dispatch_path": dispatch_path,
            },
        )
        return {
            "accepted": accepted,
            "message": "Queued main chat message." if accepted else "Main chat runtime did not accept the message.",
            "audio_mode": audio_mode,
            "phone_request_id": capture_id if accepted else "",
            "debug_trace_id": debug_trace_id,
            "state": self.remote_state_snapshot(),
        }

    def remote_progressive_audio(self, method: str, payload: dict[str, Any]) -> dict:
        """Negotiated PCM transport; original phone reply ownership still applies."""
        from addons.main_chat_remote.phone_reply_receipts import PhoneReplyRejected
        if not self._is_open() or type(payload) is not dict:
            raise PhoneReplyRejected('unavailable')
        protocol = self._phone_reply
        if method == 'mode':
            if (set(payload) != {'auth', 'version', 'enabled'} or type(payload['version']) is not int
                    or payload['version'] != 1):
                raise PhoneReplyRejected('invalid_request')
            return protocol.set_progressive_audio_mode(payload['auth'], payload['enabled'])
        if method != 'read' or set(payload) != {'auth', 'phone_request_id', 'chunk_id', 'sequence_index', 'cursor'}:
            raise PhoneReplyRejected('invalid_request')
        protocol.authenticate(payload['auth'])
        status = protocol.registry.status(payload['auth'], payload['phone_request_id'])
        if status['phase'] not in {'pending', 'generating', 'complete'} or status.get('playback_stop_requested'):
            raise PhoneReplyRejected('unavailable')
        sequence, cursor, audio_id = payload['sequence_index'], payload['cursor'], payload['chunk_id']
        if (type(sequence) is not int or not 0 <= sequence < 2048 or type(cursor) is not int
                or type(audio_id) is not str or not re.fullmatch(r'p[a-f0-9]{32}_[0-9]{4}', audio_id)):
            raise PhoneReplyRejected('invalid_request')
        return self.media_bridge.progressive_audio_read(payload['phone_request_id'], audio_id, sequence, cursor)

    def remote_phone_reply(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        if method in {"action", "conversation-action"}:
            from core.runtime.stop_diagnostics import record_runtime_event
            action = payload.get("action") if method == "action" else payload
            kind = action.get("kind") if isinstance(action, dict) else None
            if kind in {"skip", "abandon", "onset", "resume", "retry", "continue", "cancel"}:
                record_runtime_event("phone_reply_control", reason=kind)
        protocol = self._phone_reply
        if method == "session":
            if (set(payload) - {"shared_queue_version", "reply_continuation_version"}
                    or any(type(value) is not int or value != 1 for value in payload.values())
                    or ("reply_continuation_version" in payload and "shared_queue_version" not in payload)):
                raise PhoneReplyRejected("invalid_request")
            if payload.get("shared_queue_version") == 1 and not self._shared_manual_queue_supported:
                raise PhoneReplyRejected("unavailable")
            return protocol.new_client(shared_queue=payload.get("shared_queue_version") == 1,
                                       continuation=payload.get("reply_continuation_version") == 1)
        if method == "presentation":
            position = ({"position": payload["position"]} if "position" in payload else {})
            if 'handoff' in payload: position['handoff'] = payload['handoff']
            return self._phone_presentation.update(
                payload.get("auth"),
                active=payload.get("active"),
                sequence=payload.get("sequence"),
                **position,
            )
        auth = payload.get("auth")
        protocol.registry.authenticate(auth)
        protocol.maintain()
        if method == "status":
            if "continuation" in payload:
                return protocol.continuation_status(auth, payload.get("phone_request_id"), payload["continuation"])
            return protocol.registry.status(auth, payload.get("phone_request_id"))
        if method == "action":
            action = payload.get('action') or {}
            started = time.monotonic()
            outcome = 'failed'
            try:
                result = wire_result(protocol.action(auth, action))
                outcome = result['status']
                if (action.get("kind") == "playback_finished" and outcome in {"accepted", "duplicate"}
                        and getattr(self, "_continuous", None) is not None):
                    self._continuous.observe_ack(auth, action.get("phone_request_id"))
                if (action.get("kind") == "skip" and outcome in {"accepted", "duplicate"}
                        and getattr(self, "_continuous", None) is not None):
                    self._continuous.observe_skip(auth, action.get("phone_request_id"))
                return result
            finally:
                try:
                    # Request worker only. No auth, request content or exception text.
                    from .relay.diagnostics import safe_fields
                    self._write_phone_debug_event('info', 'phone_control_result', {
                        **safe_fields({'reply_id': action.get('phone_request_id') if isinstance(action, dict) else None,
                                       'operation': action.get('kind') if isinstance(action, dict) else None,
                                       'outcome': outcome, 'elapsed_ms': round((time.monotonic()-started)*1000)}),
                        'ownership': protocol.diagnostic_snapshot(),
                    })
                except Exception:
                    pass
        if method == "conversation-action":
            if set(payload) != {'auth', 'kind', 'operation_id', 'target'}:
                raise PhoneReplyRejected('invalid_request')
            return protocol.conversation_action(auth, {key: value for key, value in payload.items() if key != 'auth'})
        raise PhoneReplyRejected("invalid_request")

    def _ordered_reply_registered(self, auth, request_id):
        with self._ordered_output_lock:
            ordered = self._ordered_output
            if ordered is not None and ordered.active and self._phone_reply.registry.authenticate(auth) == ordered.owner_epoch:
                ordered.registered(auth, request_id)

    def remote_ordered_output(self, method, payload):
        """Loopback-only backend port, excluded from LAN/relay forwarding."""
        from addons.main_chat_remote.ordered_output_bridge import DesktopOutputBinding
        if type(payload) is not dict:
            raise ValueError('ordered_bridge_shape')
        auth = payload.get('auth')
        epoch = self._phone_reply.registry.authenticate(auth)
        if method in ('recover-prepare','recover-commit'):
            return self._ordered_recovery.dispatch(self,method,payload)
        with self._ordered_output_lock:
            if method == 'open':
                self._ordered_recovery.check_open(payload.get('streamId'))
                if ORDERED_OUTPUT_VERSION != 1:
                    raise PhoneReplyRejected('unavailable')
                if set(payload) not in ({'auth', 'streamId'}, {'auth','streamId','recovery'}):
                    raise ValueError('ordered_bridge_shape')
                from .ordered_output_recovery import open_capability
                recovery_digest = open_capability(payload.get('recovery'))
                if payload['streamId'] in self._retired_ordered_outputs:
                    raise ValueError('ordered_binding_retired')
                previous = self._ordered_output
                if previous is not None and not previous.reclaimable:
                    if previous.active or previous.stream_id == payload['streamId']:
                        if previous.owner_epoch != epoch or previous.stream_id != payload['streamId']:
                            raise PhoneReplyRejected('ownership')
                        if recovery_digest is not None or previous._recovery_digest is not None:
                            previous.verify_recovery(recovery_digest)
                        return previous.planning_snapshot()
                    # Retired admission cannot produce new frames, but old media
                    # custody survives until its exact authenticated reader ACKs.
                    # Never delete files or turn a process exit into those ACKs.
                    # Expired credentials can never authenticate late cleanup.
                    # Discard only unreachable control records, not media, reader
                    # evidence or files (the stopped backend retains those).
                    cleanup_owner_exists = self._phone_reply.registry.cleanup_owner_exists
                    self._retired_ordered_outputs = {key:value for key,value in self._retired_ordered_outputs.items()
                                                    if not value.reclaimable and cleanup_owner_exists(value.owner_epoch)}
                    if len(self._retired_ordered_outputs) >= 64:
                        raise ValueError('ordered_recovery_retention_capacity')
                    if cleanup_owner_exists(previous.owner_epoch):
                        self._retired_ordered_outputs[previous.stream_id] = previous
                from addons.main_chat_remote.ordered_idle_source import OrderedIdleSource
                from addons.main_chat_remote.ordered_speech_source import OrderedSpeechSource
                self._ordered_output = DesktopOutputBinding(self._phone_reply, auth, payload['streamId'],
                    recovery_digest=recovery_digest,
                    idle_source=OrderedIdleSource(self.app_root, self.idle_selection_snapshot),
                    speech_source=OrderedSpeechSource(self.app_root, self.media_bridge),
                    transition_ms=lambda: max(0,min(5000,int(self.idle_selection_snapshot()['config'].get('musetalk_loop_fade_ms',180) or 0))))
                return self._ordered_output.planning_snapshot()
            ordered = self._retired_ordered_outputs.get(payload.get('streamId'), self._ordered_output)
            if ordered is None:
                # An authenticated open may never have reached Desktop. Prove
                # absence here so its backend can settle an uncertain open;
                # this neither creates output nor joins any existing readers.
                if (method == 'close' and set(payload) == {'auth','streamId'}
                        and isinstance(payload['streamId'],str)
                        and re.fullmatch('[a-f0-9]{32}',payload['streamId'])):
                    return True
                raise PhoneReplyRejected('unavailable')
            return ordered.dispatch(method, payload)

    def phone_presentation_snapshot(self, request=None) -> dict[str, object]:
        ordered = getattr(self, '_ordered_output', None)
        if ordered is not None:
            snapshot = ordered.presentation_snapshot(request)
            if snapshot is not None:
                return snapshot
        if request:
            if not isinstance(request, dict) or set(request) != {'handoff'}:
                raise ValueError('Invalid presentation request')
            return self._phone_presentation.request_handoff(request['handoff'])
        return self._phone_presentation.snapshot()

    def _queue_phone_text_turn(self, message: str, capture_id: str, *, phone_reply_control: bool = False, phone_shared_queue: bool = False) -> tuple[bool, str]:
        """Queue a phone turn through the same pending-input path as desktop chat."""

        queue_turn = getattr(self.user_image_turns, "queue_image_turn", None)
        if callable(queue_turn):
            queued = queue_turn(
                "",
                content=message,
                source="phone_text",
                remote_capture_id=capture_id,
                **({"phone_reply_control": True} if phone_reply_control else {}),
                **({"phone_shared_queue": True} if phone_shared_queue else {}),
            )
            return queued is not False, "runtime_pending_turn_queue"
        return False, "unavailable"

    def remote_audio_clear(self) -> dict[str, Any]:
        if not self._is_open():
            return {"accepted": False, "message": "Main Chat Remote is shutting down."}
        self.media_bridge.clear()
        if self._phone_reply is not None:
            self._phone_reply.maintain()
        return {
            "accepted": True,
            "message": "Phone audio queue cleared.",
            "audio": self.media_snapshot(),
        }

    def remote_control(self, action: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        from core.runtime.stop_diagnostics import record_runtime_event
        if action in {"reset_chat", "interrupt_response", "skip_speech", "skip_user_reply", "retry_user_input", "regenerate_response"}:
            record_runtime_event("phone_control_requested", reason=action)
        if not self._is_open():
            return {"accepted": False, "message": "Main Chat Remote is shutting down."}
        action_key = str(action or "").strip()
        if not action_key:
            return {"accepted": False, "message": "action is required", "state": self.remote_state_snapshot()}
        del options

        if action_key in {"quick_save_chat_context", "quick_load_chat_context"}:
            method = getattr(getattr(self, "chat_context", None), "phone_quick_save" if action_key == "quick_save_chat_context" else "phone_quick_load", None)
            if not callable(method):
                return {"accepted": False, "message": "Phone chat saves are unavailable.", "state": self.remote_state_snapshot()}
            try:
                detail = str(method())
            except Exception as exc:
                return {"accepted": False, "message": str(exc) or "Chat save could not complete.", "state": self.remote_state_snapshot()}
            if action_key == "quick_load_chat_context" and self.host is not None:
                try:
                    self._receive_host_history(self._invoke_main(self.host.history_snapshot))
                except Exception as exc:
                    self.log("warning", "Could not refresh phone history after Quick Load: %s", exc)
            return {"accepted": True, "message": detail, "state": self.remote_state_snapshot()}

        def trigger() -> dict[str, Any]:
            if not self._is_open():
                return {
                    "accepted": False,
                    "message": "Main Chat Remote is shutting down.",
                }
            if action_key in {"web_search_on", "web_search_off"}:
                setter = getattr(self.runtime_controls, "set_web_search_enabled", None)
                if not callable(setter):
                    return {"accepted": False, "message": "Update and restart NC desktop to control Web Search."}
                return dict(setter(action_key == "web_search_on") or {})
            if action_key == "reset_chat":
                reset = getattr(getattr(self, "engine_lifecycle", None), "reset_chat_memory", None)
                if not callable(reset):
                    return {"accepted": False, "message": "Chat reset is unavailable."}
                try:
                    accepted = reset() is not False
                except Exception:
                    return {"accepted": False, "message": "Chat reset could not be completed. Check NC before trying again."}
                return {"accepted": accepted, "message": "Chat reset." if accepted else "Chat reset was not accepted."}
            controls = self._safe_service_call(
                self.runtime_controls.snapshot if self.runtime_controls is not None else None, {}
            )
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
        if accepted and action_key in {"interrupt_response", "reset_chat"}:
            self.media_bridge.clear()
            if self._phone_reply is not None:
                self._phone_reply.maintain()
        if accepted and action_key == "reset_chat":
            flush_story = getattr(getattr(self, "chat_context", None), "flush_story_checkpoint", None)
            if callable(flush_story):
                flush_story()
        return {
            "accepted": accepted,
            "message": result.get("message") or ("Control action queued." if accepted else "Control action was not accepted."),
            "control": result,
            "state": self.remote_state_snapshot(),
        }

    def remote_engine_start(self) -> dict[str, Any]:
        from core.runtime.stop_diagnostics import record_runtime_event
        record_runtime_event("phone_engine_start_requested")
        if not self._is_open():
            return {"accepted": False, "message": "Main Chat Remote is shutting down."}

        def start() -> dict[str, Any]:
            if not self._is_open():
                return {
                    "accepted": False,
                    "message": "Main Chat Remote is shutting down.",
                    "engine": {},
                }
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
        from core.runtime.stop_diagnostics import record_runtime_event
        record_runtime_event("phone_engine_stop_requested")
        if not self._is_open():
            return {"accepted": False, "message": "Main Chat Remote is shutting down."}

        def stop() -> dict[str, Any]:
            if not self._is_open():
                return {
                    "accepted": False,
                    "message": "Main Chat Remote is shutting down.",
                    "engine": {},
                }
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
        if "phone_reply_auth" in data or "phone_interruption" in data:
            return self._remote_phone_stt(data)
        if data.get("audio_mode") not in (None, "", "backend_hq"):
            return {
                "accepted": False,
                "error": "Backend STT requires backend_hq audio mode. Send Phone Native transcripts through /api/send.",
                "audio_cached": False,
            }
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
        transcriber = getattr(self.file_transcription, "transcribe", None)
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
        stt_result, stt_error = self._transcribe_file_owned(
            transcriber,
            audio_path,
            language=data.get("language"),
        )
        if stt_error:
            return {
                "accepted": False,
                "error": stt_error,
                "audio_cached": True,
            }
        text = self._stt_text_from_result(stt_result)
        result = {
            "accepted": bool(text),
            "text": text,
            "audio_cached": True,
            "send_to_chat": bool(data.get("send_to_chat", True)),
        }
        if text and bool(data.get("send_to_chat", True)) and self._is_open():
            result["send_result"] = self.remote_send_text(
                text,
                {
                    "play_on_backend": PHONE_REPLY_PLAY_ON_BACKEND,
                    "capture_phone_audio": PHONE_REPLY_CAPTURE_AUDIO,
                    "visual_after_send": bool(data.get("visual_after_send", False)),
                },
            )
        self._cleanup_stt_uploads()
        return result

    def _remote_phone_stt(self, data):
        protocol = self._phone_reply
        auth = data.get("phone_reply_auth")
        protocol.authenticate(auth)
        if data.get("audio_mode") not in (None, "", "backend_hq"):
            raise PhoneReplyRejected("unavailable")
        if "phone_interruption" not in data:
            return self._remote_phone_initial_stt(data)
        op, first = protocol.begin_stt(auth, data["phone_interruption"])
        if not first:
            return wire_result(protocol.wait(op, retry=True))
        deadline = op.deadline
        if not protocol._uploads.acquire(blocking=False):
            protocol.timeout(op)
            raise PhoneReplyRejected("capacity")
        path = None
        transferred = False
        def cleanup():
            if path is not None:
                self._unlink_quietly(path)
                with self._stt_lock:
                    self._phone_upload_paths.discard(path)
            protocol._uploads.release()
        try:
            transcriber = getattr(self.file_transcription, "transcribe", None)
            if not callable(transcriber):
                raise PhoneReplyRejected("unavailable")
            encoded = data.get("audio_base64") or data.get("audio") or ""
            if type(encoded) is not str or len(encoded) > MAX_JSON_PAYLOAD_BYTES:
                raise PhoneReplyRejected("invalid_request")
            if encoded.startswith("data:") and "," in encoded:
                encoded = encoded.split(",", 1)[1]
            try:
                audio = base64.b64decode(encoded, validate=True)
            except Exception:
                raise PhoneReplyRejected("invalid_request") from None
            if not audio or len(audio) > MAX_JSON_PAYLOAD_BYTES:
                raise PhoneReplyRejected("invalid_request")
            self.stt_upload_dir.mkdir(parents=True, exist_ok=True)
            path = self.stt_upload_dir / ("phone_control_" + secrets.token_hex(12) + self._safe_audio_extension(data.get("format") or data.get("extension") or "wav"))
            with self._stt_lock:
                self._phone_upload_paths.add(path)
            path.write_bytes(audio)
            def completion(result, error):
                text = "" if error else self._stt_text_from_result(result)
                protocol.complete_stt(op, auth, text, send_to_chat=bool(data.get("send_to_chat", True)) and self._is_open())
            transferred = True
            result, error = self._transcribe_file_owned(transcriber, path, language=data.get("language"),
                              deadline=deadline, phone_completion=completion, phone_cleanup=cleanup)
            if error:
                protocol.timeout(op)
            answer = wire_result(protocol.wait(op))
            if answer["next_phone_request_id"] and bool(data.get("visual_after_send", False)):
                try:
                    self.remote_visual_request({"action": "generate", "prompt": self._stt_text_from_result(result), "source_text": self._stt_text_from_result(result)})
                except Exception:
                    pass
            return answer
        except Exception:
            protocol.timeout(op)
            raise
        finally:
            if not transferred:
                cleanup()

    def _remote_phone_initial_stt(self, data):
        """One authenticated upload ID owns transcription and the queued UI claim."""
        protocol = self._phone_reply
        deadline = protocol.clock() + 120
        auth = data["phone_reply_auth"]
        path = None
        owns_slot = False
        transferred = False
        op = None
        first = False
        def cleanup():
            nonlocal owns_slot
            if path is not None:
                self._unlink_quietly(path)
                with self._stt_lock:
                    self._phone_upload_paths.discard(path)
            if owns_slot:
                owns_slot = False
                protocol._uploads.release()
        try:
            encoded = data.get("audio_base64") or data.get("audio") or ""
            if type(encoded) is not str or len(encoded) > MAX_JSON_PAYLOAD_BYTES:
                raise PhoneReplyRejected("invalid_request")
            if encoded.startswith("data:") and "," in encoded:
                encoded = encoded.split(",", 1)[1]
            try:
                audio = base64.b64decode(encoded, validate=True)
            except Exception:
                raise PhoneReplyRejected("invalid_request") from None
            if not audio or len(audio) > MAX_JSON_PAYLOAD_BYTES:
                raise PhoneReplyRejected("invalid_request")
            extension = self._safe_audio_extension(data.get("format") or data.get("extension") or "wav")
            language = data.get("language")
            if language is not None and (type(language) is not str or len(language) > 128):
                raise PhoneReplyRejected("invalid_request")
            send_to_chat = bool(data.get("send_to_chat", True))
            visual = bool(data.get("visual_after_send", False))
            effective = json.dumps([hashlib.sha256(audio).hexdigest(), extension, language, send_to_chat, visual], separators=(",", ":")).encode()
            op, first = protocol.begin_submission(auth, data.get("phone_submission_id"), hashlib.sha256(effective).digest(),
                                                   deadline=deadline, acquire_upload=True)
            owns_slot = first
            if not first:
                return protocol.wait_submission(op, retry=True)
            transcriber = getattr(self.file_transcription, "transcribe", None)
            if not callable(transcriber):
                raise PhoneReplyRejected("unavailable")
            self.stt_upload_dir.mkdir(parents=True, exist_ok=True)
            path = self.stt_upload_dir / ("phone_control_" + secrets.token_hex(12) + extension)
            with self._stt_lock:
                self._phone_upload_paths.add(path)
            path.write_bytes(audio)
            def completion(result, error):
                if op.future.done():
                    return
                text = "" if error else self._stt_text_from_result(result)
                answer = {"accepted": bool(text), "text": text, "audio_cached": False, "send_to_chat": send_to_chat}
                try:
                    protocol.reserve_submission_text(op, text)
                    if error or not self._is_open():
                        protocol.timeout_submission(op)
                    elif not text or not send_to_chat:
                        if protocol.claim_submission(op):
                            protocol.finish_submission(op, answer)
                        else:
                            protocol.timeout_submission(op)
                    else:
                        request_id = protocol.register(auth)
                        op.request_id = request_id
                        if op.future.done():
                            protocol.cancel(request_id)
                            return
                        def send():
                            try:
                                accepted, _path = self._queue_phone_text_turn(text, request_id, phone_reply_control=True,
                                    phone_shared_queue=protocol.registry.shared_queue_enabled(auth))
                                answer["send_result"] = {"accepted": accepted, "phone_request_id": request_id if accepted else "", "audio_mode": "backend_hq"}
                                if not accepted:
                                    protocol.cancel(request_id)
                                protocol.finish_submission(op, answer)
                                if accepted and visual:
                                    try:
                                        self.remote_visual_request({"action": "generate", "prompt": text, "source_text": text})
                                    except Exception:
                                        pass
                                return accepted
                            except Exception:
                                protocol.cancel(request_id)
                                protocol.finish_submission(op, {"status": "unavailable", "phone_request_id": request_id, "next_phone_request_id": None})
                                return False
                        def commit(effect):
                            if self._is_open() and protocol.claim_submission(op):
                                return effect()
                            protocol.timeout_submission(op)
                            return False
                        try:
                            self._invoke_main(send, commit_call=commit)
                        except Exception:
                            protocol.timeout_submission(op)
                except Exception:
                    protocol.timeout_submission(op)
            transferred = True
            _result, error = self._transcribe_file_owned(transcriber, path, language=language, deadline=op.deadline,
                                phone_completion=completion, phone_cleanup=cleanup)
            if error:
                protocol.timeout_submission(op)
            return protocol.wait_submission(op)
        except Exception as exc:
            if op is not None and first:
                protocol.fail_submission(op, exc.reason if isinstance(exc, PhoneReplyRejected) else "unavailable")
                return protocol.wait_submission(op)
            raise
        finally:
            if not transferred:
                cleanup()

    def _transcribe_file_owned(self, transcriber, audio_path: Path, *, language=None, deadline=None, phone_completion=None, phone_cleanup=None):
        if not self._is_open():
            if phone_cleanup is not None:
                phone_cleanup()
            return None, "Main Chat Remote is shutting down."
        job = {
            "transcriber": transcriber,
            "path": str(audio_path),
            "language": language,
            "done": threading.Event(),
            "result": None,
            "error": "",
            "deadline": deadline,
            "phone_completion": phone_completion,
            "phone_cleanup": phone_cleanup,
        }
        start_worker = False
        closed = False
        with self._stt_lock:
            if not self._is_open():
                closed = True
            else:
                self._stt_queue.put_nowait(job)
                if not self._stt_worker_active:
                    self._stt_worker_active = True
                    start_worker = True
        if closed:
            if phone_cleanup is not None:
                phone_cleanup()
            return None, "Main Chat Remote is shutting down."
        if start_worker:
            try:
                self.tasks.spawn(
                    "file-transcription",
                    self._transcription_worker,
                    on_cancel=lambda _reason: self._cancel_transcription_jobs(),
                )
            except Exception as exc:
                self._cancel_transcription_jobs(
                    str(exc) or "Could not start file transcription."
                )
        if not job["done"].wait(None if deadline is None else max(0.0, deadline - time.monotonic())):
            error = "Phone transcription deadline elapsed."
            retired = False
            with self._stt_lock:
                # Dequeue and cancellation share this lock: only one may own
                # cleanup. An active reader keeps its file until it returns.
                if self._stt_active_job is not job and not job["done"].is_set():
                    retained = []
                    while True:
                        try:
                            candidate = self._stt_queue.get_nowait()
                        except queue.Empty:
                            break
                        if candidate is job:
                            retired = True
                        else:
                            retained.append(candidate)
                        self._stt_queue.task_done()
                    for candidate in retained:
                        self._stt_queue.put_nowait(candidate)
                    if retired:
                        job["cancelled"] = True
                        job["error"] = error
                        job["done"].set()
            if retired:
                try:
                    if phone_completion is not None:
                        phone_completion(None, error)
                finally:
                    if phone_cleanup is not None:
                        phone_cleanup()
            return None, error
        return job.get("result"), str(job.get("error") or "")

    def _transcription_worker(self, cancellation) -> None:
        try:
            while not cancellation.cancelled:
                with self._stt_lock:
                    try:
                        job = self._stt_queue.get_nowait()
                    except queue.Empty:
                        self._stt_worker_active = False
                        self._stt_active_job = None
                        return
                    self._stt_active_job = job
                error = ""
                result = None
                try:
                    if job.get("deadline") is not None and time.monotonic() >= job["deadline"]:
                        raise TimeoutError("Phone transcription deadline elapsed.")
                    transcriber = job["transcriber"]
                    try:
                        result = transcriber(
                            job["path"],
                            language=job.get("language"),
                        )
                    except TypeError:
                        result = transcriber(job["path"])
                except Exception as exc:
                    error = str(exc) or "STT transcription failed."
                if cancellation.cancelled or not self._is_open() or job.get("cancelled"):
                    error = "Main Chat Remote transcription was cancelled."
                    result = None
                completion = job.get("phone_completion")
                if completion is not None:
                    try:
                        completion(result, error)
                    except Exception:
                        error = "Phone transcription resolution unavailable."
                cleanup = job.get("phone_cleanup")
                if cleanup is not None:
                    cleanup()
                with self._stt_lock:
                    if self._stt_active_job is job:
                        self._stt_active_job = None
                    if not job["done"].is_set():
                        job["result"] = result
                        job["error"] = error
                        job["done"].set()
                    self._stt_queue.task_done()
        finally:
            self._cancel_transcription_jobs()

    def _cancel_transcription_jobs(
        self,
        error: str = "Main Chat Remote transcription was cancelled.",
    ) -> None:
        queued_phone_jobs = []
        with self._stt_lock:
            jobs = []
            active_phone_reader = False
            if self._stt_active_job is not None:
                jobs.append(self._stt_active_job)
                active_phone_reader = self._stt_active_job.get("phone_cleanup") is not None
                if not active_phone_reader:
                    self._stt_active_job = None
            while True:
                try:
                    job = self._stt_queue.get_nowait()
                    jobs.append(job)
                    if job.get("phone_cleanup") is not None:
                        queued_phone_jobs.append(job)
                except queue.Empty:
                    break
                else:
                    self._stt_queue.task_done()
            if not active_phone_reader:
                self._stt_worker_active = False
            for job in jobs:
                job["cancelled"] = True
                if not job["done"].is_set():
                    job["error"] = str(error)
                    job["done"].set()
        # The worker retains an active reader's file until transcribe returns.
        for job in queued_phone_jobs:
            try:
                if job.get("phone_completion") is not None:
                    job["phone_completion"](None, "Phone transcription cancelled.")
            finally:
                job["phone_cleanup"]()

    def remote_image_upload(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._is_open():
            return {"accepted": False, "error": "Main Chat Remote is shutting down."}
        data = dict(payload or {})
        phone_control = "phone_reply_auth" in data
        if phone_control:
            self._phone_reply.authenticate(data["phone_reply_auth"])
            if data.get("audio_mode") not in (None, "", "backend_hq"):
                raise PhoneReplyRejected("unavailable")
        audio_mode, audio_error = self._phone_audio_mode(data)
        if audio_error:
            return {"accepted": False, "error": audio_error, "state": self.remote_state_snapshot()}
        encoded = str(data.get("image_base64") or data.get("image") or "").strip()
        if not encoded:
            return {"accepted": False, "error": "image_base64 is required"}
        try:
            image_bytes, extension = self._decode_phone_image(encoded)
        except ValueError as exc:
            return {"accepted": False, "error": str(exc)}
        prompt = str(data.get("prompt") or data.get("text") or "").strip()
        if not prompt:
            prompt = "Please respond to the photo I just sent you."
        if data.get("visual_after_send") is True:
            # Keep generation on the accepted reply's existing visual pipeline;
            # a second immediate /visual job would lose the photo/turn binding.
            prompt = "Edit the attached photo. " + prompt
        debug_trace_id = (
            str(data.get("debug_trace_id") or "").strip()[:80]
            or f"photo-{secrets.token_hex(6)}"
        )
        image_source = str(data.get("source") or "phone_camera").strip().lower()
        if image_source not in {"phone_camera", "phone_gallery"}:
            image_source = "phone_camera"
        self.image_upload_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup_image_uploads()
        image_id = f"phone_{int(time.time() * 1000)}_{secrets.token_hex(4)}"
        image_path = self.image_upload_dir / f"{image_id}{extension}"
        image_path.write_bytes(image_bytes)
        self._cleanup_image_uploads()
        capture_id = self._phone_reply.register(data["phone_reply_auth"]) if phone_control else secrets.token_urlsafe(18)
        if audio_mode == "phone_native":
            if not self._native_requests.register(capture_id):
                self._unlink_quietly(image_path)
                return {"accepted": False, "error": "Phone Native request capacity reached. Wait for pending replies."}
        elif not phone_control:
            self.media_bridge.begin_tts_capture(
                prompt,
                suppress_backend_playback=not PHONE_REPLY_PLAY_ON_BACKEND,
                capture_phone_audio=PHONE_REPLY_CAPTURE_AUDIO,
                capture_id=capture_id,
            )
        self._write_phone_debug_event(
            "info",
            "phone_photo_received",
            {
                "debug_trace_id": debug_trace_id,
                "byte_count": len(image_bytes),
                "format": extension.lstrip("."),
                "source": image_source,
                "prompt_character_count": len(prompt),
                "capture_phone_audio": audio_mode == "backend_hq" and PHONE_REPLY_CAPTURE_AUDIO,
                "play_on_backend": PHONE_REPLY_PLAY_ON_BACKEND,
            },
        )

        native_dispatch = NativeDispatchGuard() if audio_mode == "phone_native" or phone_control else None

        def send() -> bool:
            if not self._is_open():
                return False
            if audio_mode == "phone_native" and self._phone_native_audio_reason():
                return False
            sender = getattr(self.user_image_turns, "queue_image_turn", None)
            if not callable(sender):
                return False
            queued = sender(
                str(image_path),
                content=prompt,
                source=image_source,
                remote_capture_id=capture_id,
                **({"phone_reply_control": True} if phone_control else {}),
                **({"phone_shared_queue": True} if phone_control and self._phone_reply.registry.shared_queue_enabled(data["phone_reply_auth"]) else {}),
            )
            if queued is not False and phone_control:
                continuous = getattr(self, "_continuous", None)
                if continuous is not None:
                    continuous.observe_manual_input(data["phone_reply_auth"], capture_id)
            return queued is not False

        try:
            accepted = bool(
                self._invoke_main(send, commit_call=native_dispatch.commit)
                if native_dispatch is not None else self._invoke_main(send)
            )
        except Exception as exc:
            if phone_control:
                self._phone_reply.cancel(capture_id)
            self.media_bridge.cancel_tts_capture(capture_id)
            if native_dispatch is None or native_dispatch.cancel_before_start():
                self._native_requests.discard(capture_id)
                self._unlink_quietly(image_path)
            self._write_phone_debug_event(
                "error",
                "phone_photo_dispatch_failed",
                {
                    "debug_trace_id": debug_trace_id,
                    "error_type": type(exc).__name__,
                },
            )
            return {
                "accepted": False,
                "error": "Main chat runtime did not accept the phone photo.",
                "debug_trace_id": debug_trace_id,
                "image_url_path": "",
                "state": self.remote_state_snapshot(),
            }
        if not accepted:
            if phone_control:
                self._phone_reply.cancel(capture_id)
            self.media_bridge.cancel_tts_capture(capture_id)
            self._native_requests.discard(capture_id)
            self._unlink_quietly(image_path)
        self._write_phone_debug_event(
            "info" if accepted else "warning",
            "phone_photo_dispatch_result",
            {"debug_trace_id": debug_trace_id, "accepted": accepted},
        )
        return {
            "accepted": accepted,
            "message": "Queued phone photo for main chat." if accepted else "Main chat runtime did not accept the phone photo.",
            "audio_mode": audio_mode,
            "phone_request_id": capture_id if accepted else "",
            "debug_trace_id": debug_trace_id,
            "image_url_path": f"/api/image/file/{image_id}" if accepted else "",
            "state": self.remote_state_snapshot(),
        }

    def remote_debug_upload(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        from core.diagnostics.sink import prepare_contract_record
        if not self._is_open():
            return {"accepted": False, "events_written": 0, "error": "Main Chat Remote is shutting down."}
        data = dict(payload or {})
        events = list(data.get("events") or [])[:200]
        if not events:
            return {"accepted": False, "events_written": 0, "error": "events are required"}
        app_data = self._sanitize_phone_debug_value(data.get("app") or {})
        reason = str(data.get("reason") or "automatic")[:80]
        written = 0
        self.phone_debug_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.phone_debug_dir / "phone_remote.log"
        from .relay.diagnostics import disk_sink
        incident_sink = disk_sink(self.phone_debug_dir / 'connection_incidents.jsonl')
        playback_sink = disk_sink(self.phone_debug_dir / 'playback_incidents.jsonl')
        lock = getattr(self, "_phone_debug_lock", None) or threading.RLock()
        with lock:
            self._rotate_phone_debug_log(log_path)
            with log_path.open("a", encoding="utf-8", newline="\n") as stream:
                for item in events:
                    if not self._is_open():
                        break
                    if not isinstance(item, dict):
                        continue
                    event_name = str(item.get("event") or "phone_event")[:100]
                    details = item.get("details") or {}
                    if event_name == "diagnostic_event":
                        from core.diagnostics.sink import prepare_contract_record

                        event_name, details = prepare_contract_record(details)
                    else:
                        details = self._sanitize_phone_debug_value(details)
                    record = {
                        "received_at": time.time(),
                        "reason": reason,
                        "app": app_data,
                        "timestamp": str(item.get("timestamp") or "")[:80],
                        "level": str(item.get("level") or "info")[:20],
                        "event": event_name,
                        "details": details,
                    }
                    if item.get("event") == "diagnostic_event":
                        record["event"], record["details"] = prepare_contract_record(item.get("details"))
                    stream.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")
                    if event_name.startswith(('audio_', 'manual_reply_', 'reply_recovery_')) or (
                        event_name == 'diagnostic_event'
                        and str(details.get('contract', {}).get('data', {}).get('site', '')).startswith('native.playback.')
                    ):
                        playback_sink(record)
                    if record['event'].startswith(('connection_', 'relay_', 'rtc_', 'peer_close',
                                                   'peer_heartbeat', 'phone_network', 'phone_lifecycle',
                                                   'phone_power', 'js_timer', 'diagnostics_started')):
                        incident_sink(record)
                    if record['event'].startswith('continuous_'):
                        self._write_continuous_incident(record)
                    written += 1
                snapshot_record = {
                    "received_at": time.time(),
                    "reason": reason,
                    "app": app_data,
                    "timestamp": "",
                    "level": "info",
                    "event": "backend_diagnostic_snapshot",
                    "details": self._backend_diagnostic_snapshot(),
                }
                stream.write(
                    json.dumps(snapshot_record, ensure_ascii=True, separators=(",", ":"))
                    + "\n"
                )
        return {
            "accepted": bool(written),
            "events_written": written,
            "desktop_log_path": "runtime/main_chat_remote/phone_debug/phone_remote.log",
        }

    def _write_phone_debug_event(
        self,
        level: str,
        event: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        from core.diagnostics.sink import prepare_contract_record
        debug_dir = getattr(self, "phone_debug_dir", None)
        if not isinstance(debug_dir, Path):
            return
        try:
            debug_dir.mkdir(parents=True, exist_ok=True)
            log_path = debug_dir / "phone_remote.log"
            lock = getattr(self, "_phone_debug_lock", None) or threading.RLock()
            event_name = str(event or "backend_event")[:100]
            record_details = dict(details or {})
            if event_name == "diagnostic_event":
                from core.diagnostics.sink import prepare_contract_record

                event_name, record_details = prepare_contract_record(record_details)
            else:
                record_details = self._sanitize_phone_debug_value(record_details)
            record = {
                "received_at": time.time(),
                "reason": "backend",
                "app": {},
                "timestamp": "",
                "level": str(level or "info")[:20],
                "event": event_name,
                "details": record_details,
            }
            if event == "diagnostic_event":
                record["event"], record["details"] = prepare_contract_record(details)
            with lock:
                self._rotate_phone_debug_log(log_path)
                with log_path.open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write(
                        json.dumps(record, ensure_ascii=True, separators=(",", ":"))
                        + "\n"
                    )
                if record["event"].startswith("continuous_"):
                    self._write_continuous_incident(record)
        except OSError:
            return

    def _write_continuous_incident(self, record: Mapping[str, Any]) -> None:
        """Keep sparse handoff evidence apart from high-volume peer requests."""
        incident_path = self.phone_debug_dir / "continuous_incidents.jsonl"
        self._rotate_phone_debug_log(incident_path)
        with incident_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")

    def _backend_diagnostic_snapshot(self) -> dict[str, Any]:
        from core.runtime.stop_diagnostics import runtime_diagnostic_snapshot
        try:
            state = dict(self.remote_state_snapshot() or {})
        except Exception as exc:
            return {"snapshot_error": type(exc).__name__}
        runtime_status = dict(state.get("runtime_status") or {})
        engine = dict(state.get("engine") or {})
        runtime_settings = dict(state.get("runtime_settings") or {})
        llm = dict(state.get("llm") or {})
        media = dict(state.get("media") or {})
        chat = dict(state.get("chat") or {})
        messages = [
            dict(item)
            for item in list(chat.get("messages") or [])
            if isinstance(item, Mapping)
        ]
        return {
            "runtime": {
                "running": bool(runtime_status.get("running", False)),
                "lifecycle_diagnostics": runtime_diagnostic_snapshot(),
                "lifecycle_state": str(
                    runtime_status.get("lifecycle_state")
                    or engine.get("state")
                    or ""
                )[:80],
            },
            "llm": {
                "provider": str(
                    llm.get("chat_provider")
                    or llm.get("provider")
                    or runtime_settings.get("chat_provider")
                    or ""
                )[:120],
                "model": str(
                    llm.get("selected_model")
                    or llm.get("model_name")
                    or runtime_settings.get("model_name")
                    or ""
                )[:160],
            },
            "chat": {
                "total_messages": len(messages),
                "user_messages": sum(
                    1 for item in messages if str(item.get("role") or "") == "user"
                ),
                "assistant_messages": sum(
                    1
                    for item in messages
                    if str(item.get("role") or "") == "assistant"
                ),
                "last_role": str(messages[-1].get("role") or "")[:40]
                if messages
                else "",
            },
            "media": {
                "generation": int(media.get("generation") or 0),
                "capture_active": bool(media.get("capture_active", False)),
                "backend_playback_suppressed": bool(
                    media.get("backend_playback_suppressed", False)
                ),
                "captured_items": len(list(media.get("items") or [])),
            },
            "phone_ownership": self._phone_reply.diagnostic_snapshot(),
        }

    @staticmethod
    def _sanitize_phone_debug_value(value: Any, *, depth: int = 0) -> Any:
        if depth >= 5:
            return "[truncated]"
        if isinstance(value, Mapping):
            result: dict[str, Any] = {}
            for raw_key, child in list(value.items())[:50]:
                key = str(raw_key)[:80]
                lowered = re.sub(r"[ -]+", "_", key.strip().lower())
                if (lowered in {'framesdecoded', 'keyframesdecoded', 'totaldecodetime', 'native_error_code'}
                        and type(child) in (int, float) and 0 <= child <= 2**53-1):
                    result[key] = child
                    continue
                if (
                    lowered in PHONE_DEBUG_CONTENT_KEYS
                    or any(
                        marker in lowered
                        for marker in (
                            "code",
                            "token",
                            "secret",
                            "password",
                            "api_key",
                            "apikey",
                            "authorization",
                            "signature",
                            "ticket",
                        )
                    )
                ):
                    result[key] = "[redacted]"
                else:
                    result[key] = MainChatRemoteController._sanitize_phone_debug_value(child, depth=depth + 1)
            return result
        if isinstance(value, (list, tuple)):
            return [MainChatRemoteController._sanitize_phone_debug_value(item, depth=depth + 1) for item in list(value)[:50]]
        if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
            return value
        text = PHONE_DEBUG_SENSITIVE_QUERY_RE.sub(r"\1[redacted]", str(value))
        text = PHONE_DEBUG_BEARER_RE.sub("Bearer [redacted]", text)
        text = PHONE_DEBUG_PAIRING_CODE_RE.sub(r"\1[redacted]", text)
        return text[:2000]

    @staticmethod
    def _rotate_phone_debug_log(log_path: Path, *, max_bytes: int = 2 * 1024 * 1024) -> None:
        try:
            if not log_path.exists() or log_path.stat().st_size < max_bytes:
                return
            rotated = log_path.with_suffix(log_path.suffix + ".1")
            if rotated.exists():
                rotated.unlink()
            log_path.replace(rotated)
        except OSError:
            return

    def remote_visual_auto(self, payload: dict[str, Any]) -> dict[str, Any]:
        policy = getattr(self, "_visual_auto", None)
        if policy is None:
            raise ValueError("Automatic Visual Reply is unavailable. Restart NC desktop.")
        scope = self._story_plan_scope()
        if payload.get("session_generation") != scope.get("session_generation"):
            raise ValueError("The conversation changed. Refresh and try again.")
        conversation_id = str(scope["conversation_id"])
        with self._host_snapshot_lock:
            history = self._host_history_snapshot
        turns = list((history or {}).get("conversation_history") or []) if isinstance(history, Mapping) else []
        canonical = self._phone_reply.conversation_actions_snapshot(include_history=True).get("_history") or ()
        if len(canonical) >= len(turns):
            turns = list(canonical)
        policy.seed_latest(scope, turns)
        if payload.get("action") == "update":
            policy.update(scope, payload)
        elif payload.get("action") != "status":
            raise ValueError("Unknown Visual Reply settings action.")
        plan = self._story_plans.store.snapshot(conversation_id)
        policy.refresh(scope, self._visual_requests_snapshot())
        return policy.phone_status(scope, plan)

    def _dispatch_auto_visual(self, cancellation: Any, scope: Mapping[str, object],
                              job: Mapping[str, str]) -> None:
        policy = getattr(self, "_visual_auto", None)
        if policy is None:
            return
        key = str(job["key"])
        try:
            current = self._story_plan_scope()
            if (cancellation.cancelled or not self._is_open()
                    or current.get("conversation_id") != scope.get("conversation_id")
                    or current.get("session_generation") != scope.get("session_generation")
                    or not policy.can_dispatch(scope, key)):
                policy.abandon(scope, key)
                return
            result = self.remote_visual_request({"action": "generate", "prompt": job["content"],
                                                 "turn_id": job["turn_id"], "refine_prompt": True,
                                                 "auto_source": True,
                                                 "expected_conversation_id": scope["conversation_id"],
                                                 "expected_session_generation": scope["session_generation"]})
            policy.finish(scope, key, accepted=bool(result.get("accepted")),
                          request_id=str(result.get("request_id") or ""),
                          busy="busy" in str(result.get("error") or "").casefold())
        except Exception as exc:
            policy.finish(scope, key, accepted=False)
            self.log("warning", "Automatic Visual Reply request failed: %s", exc)

    def remote_visual_request(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._is_open():
            return {"accepted": False, "error": "Main Chat Remote is shutting down."}
        data = dict(payload or {})
        action = str(data.get("action") or "generate").strip().lower()
        service = self.visual_reply
        if service is None:
            return {"accepted": False, "error": "Visual Reply service is unavailable.", "visual": self.visual_snapshot(phone_safe=True)}
        if action == "snapshot":
            return {"accepted": True, "visual": self.visual_snapshot(phone_safe=True)}
        if action in {"show", "hide", "clear"}:
            callback = getattr(service, action, None)
            if not callable(callback):
                return {
                    "accepted": False,
                    "error": f"Visual Reply {action} is not supported by this desktop host.",
                    "visual": self.visual_snapshot(phone_safe=True),
                }
            kwargs = {"auto_show": False} if action == "clear" else {}
            accepted = self._visual_service_action(callback, **kwargs)
            return {"accepted": accepted, "visual": self.visual_snapshot(phone_safe=True)}
        prompt = str(data.get("prompt") or data.get("source_text") or "").strip()
        if action in {"generate_last", "last_assistant"}:
            prompt = self._latest_chat_text(role="assistant", prefer_visual_prompt=True)
        if not prompt:
            prompt = self._latest_chat_text(role="assistant", prefer_visual_prompt=True)
        if not prompt:
            return {"accepted": False, "error": "prompt or assistant chat text is required.", "visual": self.visual_snapshot(phone_safe=True)}
        try:
            target = self._invoke_main(lambda: self._visual_request_target(
                data, latest=action in {"generate_last", "last_assistant"}
            ))
        except ValueError as exc:
            return {"accepted": False, "error": str(exc), "visual": self.visual_snapshot(phone_safe=True)}
        target = dict(target or {})
        target_turn_id = str(target.get("turn_id") or target.get("id") or "")[:120]
        target_transaction = str(target.get("normal_chat_transaction_id") or "")[:120]
        request_id = f"phone_{int(time.time())}_{secrets.token_hex(3)}"
        self._record_visual_request(
            request_id,
            "queued",
            accepted=None,
            prompt_preview=prompt[:240],
            source="phone_auto" if data.get("auto_source") is True else "phone",
            normal_chat_transaction_id=target_transaction,
            turn_id=target_turn_id,
        )

        def worker(cancellation) -> None:
            generator = getattr(service, "request_generation", None)
            if not callable(generator):
                if not cancellation.cancelled and self._is_open():
                    self._record_visual_request(
                        request_id,
                        "error",
                        accepted=False,
                        message="Visual Reply generation service is unavailable.",
                    )
                return
            if cancellation.cancelled or not self._is_open():
                return
            self._record_visual_request(request_id, "running", accepted=None)
            try:
                def auto_scope_current() -> bool:
                    if data.get("auto_source") is not True:
                        return True
                    current = self._story_plan_scope()
                    return (current.get("conversation_id") == data.get("expected_conversation_id")
                            and current.get("session_generation") == data.get("expected_session_generation"))

                if not auto_scope_current():
                    raise ValueError("The conversation changed before the automatic image request.")
                image_prompt = prompt
                if data.get('refine_prompt') is True:
                    refiner = getattr(self.remote_commands, 'refine_visual_prompt', None)
                    if not callable(refiner):
                        raise RuntimeError('The desktop image-prompt refiner is unavailable.')
                    image_prompt = str(refiner(prompt)).strip()
                    if not image_prompt:
                        raise ValueError('The current language model returned no image prompt.')
                prepared_options: dict[str, Any] = {}
                prepare = getattr(service, "prepare_phone_generation", None)
                if callable(prepare):
                    runtime = self._invoke_main(
                        service.settings_snapshot,
                        commit_call=lambda effect: self._commit_if_open(effect, cancellation),
                    )
                    if cancellation.cancelled or not self._is_open():
                        return
                    source_photo = target.get("_source_photo_turn")
                    if isinstance(source_photo, dict):
                        from core.runtime.visual import VISUAL_REPLY_REQUEST_TEXT_CONFIG_KEY, VISUAL_REPLY_SOURCE_IMAGE_CONFIG_KEY
                        runtime = dict(runtime)
                        runtime[VISUAL_REPLY_REQUEST_TEXT_CONFIG_KEY] = source_photo["content"]
                        runtime[VISUAL_REPLY_SOURCE_IMAGE_CONFIG_KEY] = source_photo["attachment_image_path"]
                    # Identity planning may inspect disk/network reference paths.
                    # Keep that work here; only snapshot/final dispatch use Qt.
                    prepared_options["prepared_phone_request"] = prepare(
                        prompt=image_prompt, runtime_config=runtime
                    )

                def generate() -> Any:
                    if not auto_scope_current():
                        raise ValueError("The conversation changed before the automatic image request.")
                    if target_turn_id or target_transaction:
                        self._visual_request_target({
                            "turn_id": target_turn_id,
                            "normal_chat_transaction_id": target_transaction,
                        })
                    return generator(
                        prompt=image_prompt,
                        caption=str(target.get("content") or data.get("caption") or data.get("source_text") or prompt),
                        provider=str(data.get("provider") or "inherit"),
                        model=str(data.get("model") or ""),
                        size=str(data.get("size") or "inherit"),
                        source="main_chat_remote",
                        metadata={
                            "request_id": request_id,
                            "remote": "phone",
                            "turn_id": target_turn_id,
                            "target_turn_id": target_turn_id,
                            "normal_chat_transaction_id": target_transaction,
                            "append_visual_variation": bool(target_turn_id or target_transaction),
                            "variation_of_request_id": str(target.get("visual_reply_request_id") or "")[:120],
                        },
                        auto_show=bool(data.get("auto_show", True)),
                        **prepared_options,
                    )

                result = self._invoke_main(
                    generate,
                    commit_call=lambda effect: self._commit_if_open(effect, cancellation),
                )
                if cancellation.cancelled or not self._is_open():
                    return
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
                    ("ready" if image_available else "generating") if accepted else "failed",
                    accepted=accepted,
                    service_request_id=service_request_id,
                    image_available=image_available,
                )
            except Exception as exc:
                if not cancellation.cancelled and self._is_open():
                    self._record_visual_request(
                        request_id,
                        "error",
                        accepted=False,
                        message=str(exc) or "Visual Reply remote request failed.",
                    )
                    self.log("warning", "Visual Reply remote request failed: %s", exc)

        self.tasks.spawn("visual-request", worker)
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
        supported_actions = ["snapshot"] if service is not None else []
        if callable(getattr(service, "request_generation", None)):
            supported_actions.extend(["generate", "generate_last", "last_assistant"])
        supported_actions.extend(
            action for action in ("show", "hide", "clear")
            if callable(getattr(service, action, None))
        )
        settings_snapshot = getattr(service, "settings_snapshot", None)
        if callable(settings_snapshot):
            try:
                settings = dict(settings_snapshot() or {})
            except Exception:
                settings = {}
        payload = {
            "available": bool(current),
            "service_available": service is not None,
            "supported_actions": supported_actions,
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

    def idle_selection_snapshot(self) -> dict[str, Any]:
        """Trusted loopback-only projection; never export the runtime config."""
        import sys
        config = self._safe_service_call(self.runtime_config.snapshot if self.runtime_config is not None else None, {})
        keys = ('musetalk_avatar_pack_id', 'musetalk_avatar_id', 'musetalk_enabled_pack_emotions', 'musetalk_loop_fade_ms')
        def plain(value):
            # Runtime snapshots recursively freeze maps/lists. deepcopy cannot
            # copy mappingproxy; only thaw the allowlisted projection, not config.
            if isinstance(value, Mapping):
                return {str(key): plain(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [plain(item) for item in value]
            if value is None or type(value) in (str, int, float, bool):
                return value
            raise ValueError('Invalid idle selection value')
        state = sys.modules.get('addons.musetalk_avatar.state')
        adapter = sys.modules.get('addons.musetalk_avatar.adapter')
        frame = dict(getattr(state, 'current_musetalk_frame_data', {}) or {})
        projected = {key:plain(config[key]) for key in keys if key in config}
        active = getattr(state, 'current_musetalk_avatar_selection', {})
        if isinstance(active, Mapping):
            pack_id, default_id = active.get('pack_id'), active.get('default_avatar_id')
            if all(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value)
                   for value in (pack_id, default_id)):
                # The adapter may resolve an unset/stale preference to a real
                # prepared pack. Export that inventory without rewriting settings.
                projected.update(musetalk_avatar_pack_id=pack_id, musetalk_avatar_id=default_id)
        return {'config':projected,
                'current_avatar':str(frame.get('avatar_id') or projected.get('musetalk_avatar_id') or ''),
                'legacy_map':dict(getattr(adapter, 'MUSE_EMOTION_AVATAR_MAP', {}) or {})}

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
        runtime_config = self._safe_service_call(
            self.runtime_config.snapshot if self.runtime_config is not None else None, {})
        payload = {
            "available": bool(frame_entries or current_frame or pipeline),
            "state": frame_state,
            "loopFadeMs": max(0, min(5000, int(runtime_config.get("musetalk_loop_fade_ms", 180) or 0))),
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
        protocol = getattr(self, "_phone_reply", None)
        if protocol is not None:
            protocol.maintain()
        self._refresh_internet_cache()
        self._refresh_bridge_info_if_running()

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

    def _generate_pending_pairing_code(self) -> None:
        self._pending_pairing_code = generate_pairing_code()
        if hasattr(self, "_pairing_code_edit"):
            self._pairing_code_edit.setText(self._pending_pairing_code)

    def native_snapshot(self) -> dict[str, Any]:
        snapshot = dict(self.status_snapshot() or {})
        imports = getattr(self, '_soundscape_imports', None)
        snapshot['soundscape_import'] = imports.snapshot() if imports else {'busy': False, 'message': 'Soundscape unavailable.'}
        snapshot['soundscape_import']['speech_active'] = bool(self.media_bridge.snapshot().get('capture_active'))
        relay = getattr(self, "relay_service", None)
        snapshot["relay"] = relay.snapshot() if relay is not None else {}
        backend = dict(snapshot.get("backend") or {})
        active_code = str(backend.get("pairing_code") or "")
        display_url = str(backend.get("display_url") or "")
        setup_uri = self._pairing_setup_uri(display_url, active_code)
        self._current_pairing_setup_uri = setup_uri
        qr_png = self._pairing_qr_png(setup_uri)
        snapshot["pending_pairing_code"] = str(
            active_code or self._pending_pairing_code or ""
        )
        snapshot["pairing_setup_uri"] = setup_uri
        snapshot["pairing_qr_data_uri"] = (
            "data:image/png;base64," + base64.b64encode(qr_png).decode("ascii")
            if qr_png
            else ""
        )
        snapshot["backend_command"] = self._format_command(
            list(backend.get("start_command") or backend.get("command") or [])
        )
        return snapshot

    def native_set_bridge_enabled(self, enabled: bool) -> dict[str, Any]:
        self._set_bridge_enabled(bool(enabled))
        return self.native_snapshot()

    def native_set_pairing_code(self, value: object) -> dict[str, Any]:
        self._pending_pairing_code = self._pairing_code_for_start(str(value or ""))
        return self.native_snapshot()

    def native_apply_internet_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.apply_internet_settings(dict(payload or {}))
        return self.native_snapshot()

    def native_action(self, action: object, payload=None) -> dict[str, Any]:
        name = str(action or "").strip().lower()
        request = dict(payload or {})
        if name == 'soundscape_import':
            imports = getattr(self, '_soundscape_imports', None)
            if imports is None: raise ValueError('Soundscape is unavailable.')
            imports.start(request)
        elif name.startswith("relay_"):
            if name in {"relay_login", "relay_connect", "relay_replace_desktop"} and (self._bridge is None or not self._bridge.running):
                self.start_bridge()
            accepted = self.relay_service.submit(name.removeprefix("relay_"), request)
            if not accepted:
                raise ValueError("An Internet operation is already running.")
        elif name == "connect_phone":
            self.connect_phone(request.get("pairing_code"))
        elif name == "stop_remote":
            self.stop_remote_services()
        elif name == "start_bridge":
            self.start_bridge()
        elif name == "stop_bridge":
            self.stop_bridge()
        elif name == "refresh":
            self._refresh_internet_cache()
        elif name == "generate_pairing_code":
            self._generate_pending_pairing_code()
        elif name == "prepare_backend":
            self.create_backend_venv()
        elif name == "start_backend":
            self.start_remote_backend(request.get("pairing_code"))
        elif name == "stop_backend":
            self.stop_remote_backend()
        elif name == "detect_public_ip":
            self.refresh_public_ip()
        elif name == "install_helper":
            self.install_certificate_helper()
        elif name == "staging_test":
            self.test_certificate_setup()
        elif name == "issue_certificate":
            self.issue_internet_certificate()
        elif name == "create_enrollment":
            self.create_internet_enrollment()
        elif name == "approve_enrollment":
            self.approve_internet_enrollment(str(request.get("id") or ""))
        elif name == "reject_enrollment":
            self.reject_internet_enrollment(str(request.get("id") or ""))
        elif name == "revoke_device":
            self.revoke_internet_device(str(request.get("id") or ""))
        else:
            raise KeyError(f"Unknown Main Chat Remote action: {name}")
        return self.native_snapshot()

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

    @staticmethod
    def _pairing_code_for_start(value: str) -> str:
        requested = str(value or "").strip()
        if not requested:
            return generate_pairing_code()
        normalized = normalize_pairing_code(requested)
        if not normalized:
            raise ValueError("Pairing code must contain 4 to 9 digits.")
        return normalized

    @staticmethod
    def _pairing_setup_uri(base_url: str, pairing_code: str) -> str:
        normalized_url = str(base_url or "").strip().rstrip("/")
        normalized_code = "".join(ch for ch in str(pairing_code or "") if ch.isdigit())
        if not normalized_url or not normalized_code:
            return ""
        return f"ncchatremote://pair?{urlencode({'url': normalized_url, 'code': normalized_code})}"

    @staticmethod
    def _pairing_qr_png(setup_uri: str) -> bytes:
        value = str(setup_uri or "").strip()
        if not value:
            return b""
        if qrcode is not None:
            try:
                qr = qrcode.QRCode(
                    version=None,
                    error_correction=qrcode.constants.ERROR_CORRECT_M,
                    box_size=8,
                    border=4,
                )
                qr.add_data(value)
                qr.make(fit=True)
                image = qr.make_image(fill_color="black", back_color="white")
                output = io.BytesIO()
                image.save(output, format="PNG")
                return output.getvalue()
            except Exception:
                pass
        try:
            import cv2

            matrix = cv2.QRCodeEncoder_create().encode(value)
            target_size = 212
            module_scale = max(1, target_size // max(matrix.shape[:2]))
            display_matrix = cv2.resize(
                matrix,
                None,
                fx=module_scale,
                fy=module_scale,
                interpolation=cv2.INTER_NEAREST,
            )
            height, width = display_matrix.shape[:2]
            if height <= target_size and width <= target_size:
                vertical_padding = target_size - height
                horizontal_padding = target_size - width
                display_matrix = cv2.copyMakeBorder(
                    display_matrix,
                    vertical_padding // 2,
                    vertical_padding - (vertical_padding // 2),
                    horizontal_padding // 2,
                    horizontal_padding - (horizontal_padding // 2),
                    cv2.BORDER_CONSTANT,
                    value=255,
                )
            encoded, png = cv2.imencode(".png", display_matrix)
            return png.tobytes() if encoded else b""
        except Exception:
            return b""

    def _invoke_main(
        self,
        func: Callable[[], Any],
        *,
        commit_call: Callable[[Callable[[], Any]], Any] | None = None,
    ) -> Any:
        return self._invoker.invoke(func, commit_call=commit_call)

    def _current_backend_task(self) -> str:
        with self._backend_task_lock:
            return str(self._backend_task or "")

    def _current_internet_task(self) -> str:
        with self._internet_task_lock:
            return str(self._internet_task or "")

    def _run_backend_task(self, label: str, func: Callable[[], dict[str, Any]]) -> None:
        self._run_task(
            label=label,
            lock=self._backend_task_lock,
            slot_name="_backend_task",
            func=func,
            thread_name="nc-main-chat-remote-backend-task",
        )

    def _run_internet_task(self, label: str, func: Callable[[], dict[str, Any]]) -> None:
        def completed(result: dict[str, Any]) -> None:
            with self._internet_status_lock:
                self._internet_last_result = dict(result)
                self._internet_last_error = (
                    "" if result.get("accepted") else str(result.get("message") or "Internet operation failed.")
                )
            self._refresh_internet_cache()

        started = self._run_task(
            label=label,
            lock=self._internet_task_lock,
            slot_name="_internet_task",
            func=func,
            thread_name="nc-main-chat-internet-task",
            on_complete=completed,
        )
        if started:
            self._refresh_internet_cache()

    def _run_task(
        self,
        *,
        label: str,
        lock: threading.RLock,
        slot_name: str,
        func: Callable[[], dict[str, Any]],
        thread_name: str,
        on_complete: Callable[[dict[str, Any]], None] | None = None,
    ) -> bool:
        task = str(label or "background task").strip()
        if not self._is_open():
            return False
        with lock:
            if getattr(self, slot_name, ""):
                return False
            setattr(self, slot_name, task)

        def worker(cancellation) -> None:
            try:
                result = dict(func() or {})
            except Exception as exc:
                result = {"accepted": False, "message": str(exc) or f"{task} failed."}
            if cancellation.cancelled or not self._is_open():
                return
            if not bool(result.get("accepted", False)):
                self.log("warning", "%s", result.get("message") or f"{task} failed.")
            if on_complete is not None:
                try:
                    on_complete(result)
                except Exception as exc:
                    self.log("warning", "%s completion failed: %s", task, exc)
            with lock:
                setattr(self, slot_name, "")
            try:
                self._invoke_main(self.refresh_tab)
            except Exception:
                pass

        try:
            self.tasks.spawn(thread_name, worker)
        except Exception:
            with lock:
                setattr(self, slot_name, "")
            return False
        self.refresh_tab()
        return True

    def _start_bridge_info_heartbeat(self) -> None:
        if self._bridge_info_worker is not None:
            return

        def refresh(cancellation) -> None:
            while not cancellation.wait(BRIDGE_INFO_REFRESH_SECONDS):
                if not self._is_open():
                    return
                protocol = getattr(self, "_phone_reply", None)
                if protocol is not None and protocol.continuation_maintenance_needed:
                    protocol.maintain()
                self._refresh_bridge_info_if_running()

        self._bridge_info_worker = self.tasks.spawn("bridge-info-heartbeat", refresh)

    def _stop_bridge_info_heartbeat(self) -> None:
        worker = self._bridge_info_worker
        self._bridge_info_worker = None
        if worker is not None:
            self.tasks.cancel_worker(worker, "bridge_info_stopped")
            self.tasks.join_worker(worker)

    def _write_bridge_info(self) -> None:
        with self._bridge_info_lock:
            self._write_bridge_info_locked()

    def _write_bridge_info_locked(self) -> None:
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
        with self._bridge_info_lock:
            try:
                self.bridge_info_path.unlink(missing_ok=True)
                self._last_bridge_info_write = 0.0
            except Exception as exc:
                self.log("warning", "Could not remove bridge info: %s", exc)

    def _refresh_bridge_info_if_running(self) -> None:
        with self._bridge_info_lock:
            if not self._settings.enabled or self._bridge is None or not self._bridge.running:
                return
            now = time.time()
            if now - float(self._last_bridge_info_write or 0.0) < BRIDGE_INFO_REFRESH_SECONDS:
                return
            self._write_bridge_info_locked()

    @staticmethod
    def _safe_service_call(method, default):
        if not callable(method):
            return default
        try:
            return method()
        except Exception:
            return default

    def _visual_service_action(self, method, **kwargs) -> bool:
        if not callable(method):
            return False

        def call() -> bool:
            result = method(**kwargs)
            return True if result is None else bool(result)

        try:
            return bool(self._invoke_main(call, commit_call=self._commit_if_open))
        except Exception as exc:
            self.log("warning", "Visual Reply action failed: %s", exc)
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
        try:
            from addons.visual_reply import state as visual_state

            runtime_requests = visual_state.request_states_snapshot()
        except Exception:
            runtime_requests = {}
        with self._visual_request_lock:
            for item in self._visual_requests:
                if str(item.get("status") or "") in {"ready", "failed", "error", "rejected"}:
                    continue
                request_id = str(item.get("service_request_id") or item.get("request_id") or "")
                runtime = runtime_requests.get(request_id, {})
                status = str(runtime.get("status") or "").casefold()
                if status in {"error", "failed", "rejected", "cancelled", "retired"}:
                    item.update(status="failed", image_available=False,
                                message="Visual Reply generation failed.")
                elif status == "ready" and runtime.get("image_path"):
                    item.update(status="ready", image_available=True)
                elif status in {"loading", "queued", "running", "generating"}:
                    item.update(status="generating", image_available=False)
                else:
                    continue
                item["updated_at"] = runtime.get("updated_at") or item.get("updated_at")
            return [dict(item) for item in self._visual_requests[-VISUAL_REQUEST_MAX_ITEMS:]]

    def _visual_request_target(self, data: dict[str, Any], *, latest: bool = False) -> dict[str, Any]:
        """Resolve a phone selection against current assistant history, never text."""
        target_id = data.get("turn_id", "")
        transaction_id = data.get("normal_chat_transaction_id", "")
        if any(not isinstance(value, str) or len(value) > 120 for value in (target_id, transaction_id)):
            raise ValueError("The selected response is invalid. Refresh the conversation.")
        target_id, transaction_id = target_id.strip(), transaction_id.strip()
        if not (target_id or transaction_id or latest):
            return {}
        callback = getattr(getattr(self, "host", None), "history_snapshot", None)
        if not callable(callback):
            callback = getattr(self.chat_replay, "snapshot_chat_session", None)
        snapshot = self._safe_service_call(callback, {})
        matches = []
        for item in dict(snapshot or {}).get("conversation_history") or ():
            if not isinstance(item, Mapping):
                continue
            turn = dict(item)
            if str(turn.get("role") or "").strip().casefold() != "assistant" or turn.get("hidden_proactive"):
                continue
            transaction = str(turn.get("normal_chat_transaction_id") or "")
            identifiers = {str(turn.get(key) or "") for key in ("turn_id", "id")}
            if transaction:
                identifiers.add("phone-native-" + hashlib.sha256(transaction.encode("utf-8")).hexdigest()[:24])
            if target_id and target_id not in identifiers:
                continue
            if transaction_id and transaction_id != transaction:
                continue
            if latest and not (turn.get("content") or turn.get("visual_reply_prompt")):
                continue
            matches.append(turn)
        if (target_id or transaction_id) and len(matches) != 1:
            raise ValueError("The selected response is no longer available. Refresh the conversation.")
        selected = matches[-1] if matches else {}
        selected_transaction = selected.get("normal_chat_transaction_id")
        if selected_transaction:
            sources = [item for item in dict(snapshot or {}).get("conversation_history") or ()
                       if isinstance(item, Mapping) and item.get("role") == "user"
                       and item.get("normal_chat_transaction_id") == selected_transaction]
            if len(sources) == 1 and sources[0].get("attachment_image_path"):
                selected["_source_photo_turn"] = {
                    "content": str(sources[0].get("content") or ""),
                    "attachment_image_path": str(sources[0]["attachment_image_path"]),
                }
        return selected

    def _addon_snapshot(self, name: str) -> dict[str, Any]:
        source = {
            "llm": self.llm_status,
            "tts": self.tts_status,
            "avatar": self.avatar_status,
        }.get(str(name))
        if source is None:
            return {}
        try:
            return dict(source.snapshot() or {})
        except Exception:
            return {}

    def _stt_transcriber_available(self) -> bool:
        return callable(getattr(self.file_transcription, "transcribe", None))

    def _latest_chat_text(self, *, role: str = "", prefer_visual_prompt: bool = False) -> str:
        chat_session = self._safe_service_call(
            self.chat_replay.snapshot_chat_session if self.chat_replay is not None else None, {}
        )
        wanted_role = str(role or "").strip().lower()
        for item in reversed(list(dict(chat_session or {}).get("conversation_history") or [])):
            turn = dict(item or {})
            if wanted_role and str(turn.get("role") or "").strip().lower() != wanted_role:
                continue
            if prefer_visual_prompt:
                visual_prompt = str(turn.get("visual_reply_prompt") or "").strip()
                if visual_prompt:
                    return visual_prompt
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
            if path in getattr(self, "_phone_upload_paths", ()):
                continue
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

    def _cleanup_image_uploads(
        self,
        *,
        now: float | None = None,
        max_age_seconds: float = IMAGE_UPLOAD_RETENTION_SECONDS,
        max_files: int = IMAGE_UPLOAD_MAX_FILES,
    ) -> None:
        upload_dir = self.image_upload_dir
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
    def _decode_phone_image(encoded: str) -> tuple[bytes, str]:
        value = str(encoded or "").strip()
        if "," in value and value.lower().startswith("data:"):
            value = value.split(",", 1)[1]
        try:
            image_bytes = base64.b64decode(value, validate=True)
        except Exception as exc:
            raise ValueError("image_base64 is not valid base64") from exc
        if not image_bytes:
            raise ValueError("image payload is empty")
        if len(image_bytes) > MAX_JSON_PAYLOAD_BYTES:
            raise ValueError("image payload is too large")
        if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return image_bytes, ".png"
        if image_bytes.startswith(b"\xff\xd8\xff"):
            return image_bytes, ".jpg"
        if len(image_bytes) >= 12 and image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
            return image_bytes, ".webp"
        raise ValueError("image payload must be PNG, JPEG, or WebP")

    def image_upload_path(self, image_id: str) -> Path:
        wanted = re.sub(r"[^A-Za-z0-9_.-]+", "", str(image_id or ""))
        if not wanted:
            raise FileNotFoundError("image id is required")
        for path in self.image_upload_dir.glob(f"{wanted}.*"):
            if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                return path
        raise FileNotFoundError("phone image not found")

    def chat_image_path(self, image_id: str) -> Path:
        wanted = re.sub(r"[^A-Za-z0-9_.-]+", "", str(image_id or ""))
        if not wanted:
            raise FileNotFoundError("chat image id is required")
        with self._chat_image_lock:
            path = self._chat_image_paths.get(wanted)
        if path is None or not path.is_file() or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise FileNotFoundError("chat image not found")
        return path

    def _register_chat_image(self, path_value: object) -> tuple[str, Path] | None:
        path_text = str(path_value or "").strip()
        if not path_text:
            return None
        try:
            path = Path(path_text).expanduser().resolve()
        except Exception:
            return None
        if not path.is_file() or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            return None
        image_id = hashlib.sha1(str(path).encode("utf-8", errors="ignore")).hexdigest()[:20]
        with self._chat_image_lock:
            self._chat_image_paths[image_id] = path
            while len(self._chat_image_paths) > CHAT_IMAGE_REGISTRY_MAX_ITEMS:
                self._chat_image_paths.pop(next(iter(self._chat_image_paths)))
        return image_id, path

    def _chat_turn_images(
        self,
        turn: dict[str, Any],
        *,
        field_names: tuple[str, ...] = CHAT_IMAGE_FIELDS,
    ) -> list[tuple[str, Path]]:
        images: list[tuple[str, Path]] = []
        seen_paths: set[Path] = set()
        for field_name in field_names:
            value = turn.get(field_name)
            candidates = value if isinstance(value, (list, tuple)) else (value,)
            for candidate in candidates:
                registered = self._register_chat_image(candidate)
                if registered is not None:
                    image_id, image_path = registered
                    resolved = image_path.resolve()
                    if resolved in seen_paths:
                        continue
                    seen_paths.add(resolved)
                    images.append((image_id, image_path))
        return images

    def _chat_turn_image(self, turn: dict[str, Any]) -> tuple[str, Path] | None:
        images = self._chat_turn_images(turn)
        return images[0] if images else None

    def _chat_visual_replies(self, turn: dict[str, Any]) -> list[dict[str, Any]]:
        turn_id = str(turn.get("turn_id") or turn.get("id") or "").strip()[:120]
        transaction_id = str(
            turn.get("normal_chat_transaction_id") or turn.get("transaction_id") or ""
        ).strip()[:120]
        caption = str(
            turn.get("visual_reply_caption")
            or turn.get("image_caption")
            or turn.get("caption")
            or ""
        ).strip()[:500]
        prompt_preview = str(
            turn.get("visual_reply_prompt")
            or turn.get("generated_image_prompt")
            or ""
        ).strip()[:240]
        created_at = turn.get("visual_reply_created_at") or turn.get("created_at") or turn.get("timestamp")
        updated_at = turn.get("visual_reply_updated_at") or created_at
        replies: list[dict[str, Any]] = []
        for image_id, image_path in self._chat_turn_images(
            turn,
            field_names=VISUAL_REPLY_IMAGE_FIELDS,
        ):
            replies.append(
                {
                    "id": image_id,
                    "status": "ready",
                    "url_path": f"/api/chat/image/{image_id}",
                    "content_type": self.file_content_type(image_path),
                    "caption": caption,
                    "prompt_preview": prompt_preview,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "turn_id": turn_id,
                    "normal_chat_transaction_id": transaction_id,
                }
            )
        turn_identifiers = {
            str(turn.get(key) or "").strip()
            for key in (
                "id",
                "turn_id",
                "transaction_id",
                "normal_chat_transaction_id",
                "visual_reply_request_id",
            )
            if str(turn.get(key) or "").strip()
        }
        if not turn_identifiers:
            return replies
        for request in self._visual_requests_snapshot():
            request_identifiers = {
                str(request.get(key) or "").strip()
                for key in (
                    "request_id",
                    "service_request_id",
                    "turn_id",
                    "transaction_id",
                    "normal_chat_transaction_id",
                )
                if str(request.get(key) or "").strip()
            }
            if not turn_identifiers.intersection(request_identifiers):
                continue
            raw_status = str(request.get("status") or "").strip().casefold()
            if raw_status in {"queued", "running", "pending", "accepted", "generating"}:
                status = "generating"
            elif raw_status in {"error", "failed", "rejected"}:
                status = "failed"
            else:
                continue
            reply: dict[str, Any] = {
                "id": str(request.get("request_id") or request.get("service_request_id") or "visual-reply"),
                "status": status,
                "caption": caption,
                "prompt_preview": str(request.get("prompt_preview") or prompt_preview).strip()[:240],
                "created_at": request.get("created_at") or created_at,
                "updated_at": request.get("updated_at") or updated_at,
                "turn_id": str(request.get("turn_id") or turn_id).strip()[:120],
                "normal_chat_transaction_id": str(
                    request.get("normal_chat_transaction_id") or transaction_id
                ).strip()[:120],
            }
            if status == "failed":
                reply["error"] = "Visual Reply failed."
            replies.append(reply)
        return replies

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

    def _chat_feed(self, chat_session: dict[str, Any]) -> dict[str, Any]:
        history = list(dict(chat_session or {}).get("conversation_history") or [])
        native_transactions = self._native_requests.correlate(history)
        messages = []
        for index, item in enumerate(history[-200:]):
            turn = dict(item or {})
            if bool(turn.get("hidden_proactive", False)):
                continue
            content = str(turn.get("content") or "").strip()
            if not content and not (turn.get('image_path') or turn.get('attachment_image_path')):
                continue
            message = {
                    "id": str(turn.get("id") or turn.get("turn_id") or index),
                    "turn_id": str(turn.get("turn_id") or turn.get("id") or "").strip()[:120],
                    "index": index,
                    "role": str(turn.get("role") or "").strip(),
                    "origin": str(turn.get("origin") or "").strip(),
                    "content": content,
                    "created_at": turn.get("created_at") or turn.get("timestamp"),
                }
            role = str(message.get("role") or "").casefold()
            if role == "assistant":
                transaction_id = str(turn.get("normal_chat_transaction_id") or "")
                if re.fullmatch(r"[0-9a-f]{32}", transaction_id):
                    message["stream_key"] = "stream-" + hashlib.sha256(transaction_id.encode("ascii")).hexdigest()[:24]
                native_request_id = native_transactions.get(transaction_id)
                if native_request_id and not turn.get("interrupted"):
                    message["phone_request_id"] = native_request_id
                    message["phone_audio_mode"] = "phone_native"
                    message["id"] = "phone-native-" + hashlib.sha256(transaction_id.encode("utf-8")).hexdigest()[:24]
                with self._presence_lock:
                    identity = self._presence_projector.message_persona(turn)
                    registered_avatar = self._register_avatar_image(identity.avatar_path)
                message["display_name"] = identity.display_name
                message["avatar_initials"] = identity.initials
                message["mood"] = identity.mood
                if re.fullmatch(r"[0-9a-f]{32}", transaction_id):
                    message["portrait_key"] = hashlib.sha256(transaction_id.encode("ascii")).hexdigest()[:24]
                if registered_avatar is not None:
                    avatar_id, _avatar_path = registered_avatar
                    message["avatar_url_path"] = f"/api/avatar/file/{avatar_id}"
                with self._presence_lock:
                    neutral = self._register_avatar_image(identity.neutral_avatar_path)
                    mood_avatars = {
                        mood: registered
                        for mood, path in identity.mood_avatar_paths.items()
                        if (registered := self._register_avatar_image(path)) is not None
                    }
                if neutral is not None:
                    message["neutral_avatar_url_path"] = f"/api/avatar/file/{neutral[0]}"
                if mood_avatars:
                    message["mood_avatar_url_paths"] = {
                        mood: f"/api/avatar/file/{registered[0]}"
                        for mood, registered in mood_avatars.items()
                    }
            else:
                message["display_name"] = "You"
                message["avatar_initials"] = "Y"
                message["mood"] = "neutral"
            visual_replies = self._chat_visual_replies(turn)
            if visual_replies:
                message["visual_replies"] = visual_replies
            attachment_path = Path(str(turn.get("attachment_image_path") or ""))
            try:
                image_root = self.image_upload_dir.resolve()
                resolved_attachment = attachment_path.resolve()
                if (
                    attachment_path.is_file()
                    and resolved_attachment.parent == image_root
                    and resolved_attachment.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
                ):
                    message["image_url_path"] = f"/api/image/file/{resolved_attachment.stem}"
                    message["image_content_type"] = self.file_content_type(resolved_attachment)
            except Exception:
                pass
            if "image_url_path" not in message:
                chat_image = self._chat_turn_image(turn)
                if chat_image is not None:
                    image_id, image_path = chat_image
                    message["image_url_path"] = f"/api/chat/image/{image_id}"
                    message["image_content_type"] = self.file_content_type(image_path)
            if "image_url_path" not in message and visual_replies:
                first_ready = next(
                    (
                        item
                        for item in visual_replies
                        if item.get("status") == "ready" and item.get("url_path")
                    ),
                    None,
                )
                if first_ready is not None:
                    message["image_url_path"] = first_ready["url_path"]
                    message["image_content_type"] = first_ready.get(
                        "content_type",
                        "application/octet-stream",
                    )
            messages.append(message)
        preview_message = None
        raw_preview = dict(chat_session or {}).get("streaming_preview")
        if isinstance(raw_preview, Mapping):
            transaction_id = str(raw_preview.get("normal_chat_transaction_id") or "")
            content = str(raw_preview.get("content") or "")[:80000]
            if (re.fullmatch(r"[0-9a-f]{32}", transaction_id) and content.strip()
                    and not any(str(turn.get("normal_chat_transaction_id") or "") == transaction_id
                                and str(turn.get("role") or "").lower() == "assistant" for turn in history)):
                stream_key = "stream-" + hashlib.sha256(transaction_id.encode("ascii")).hexdigest()[:24]
                generation = raw_preview.get("session_generation")
                request_id = (self._phone_reply.registry.request_for_transaction(transaction_id, generation)
                              if type(generation) is int else None)
                with self._presence_lock:
                    identity = self._presence_projector.message_persona({"content": content})
                preview_message = {
                    "id": ("phone-native-" + stream_key[7:]) if request_id else stream_key,
                    "stream_key": stream_key,
                    "normal_chat_transaction_id": transaction_id,
                    "content": content,
                    "generation_complete": raw_preview.get("generation_complete") is True,
                    "display_name": identity.display_name,
                    "avatar_initials": identity.initials,
                    **({"phone_request_id": request_id, "phone_audio_mode": "phone_native"} if request_id else {}),
                }
        return {
            "version": dict(chat_session or {}).get("version", 1),
            "saved_at": dict(chat_session or {}).get("saved_at", 0.0),
            "message_count": len(history),
            "messages": messages,
            **({"streaming_preview": preview_message} if preview_message is not None else {}),
        }


def free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
