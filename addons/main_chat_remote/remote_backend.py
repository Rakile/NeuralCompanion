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
_request_diagnostics = None
_request_diagnostics_unavailable = False


def _trace_remote_request(body, site, work):
    global _request_diagnostics, _request_diagnostics_unavailable
    if _request_diagnostics is None and not _request_diagnostics_unavailable:
        try:
            from core.diagnostics.plan_trace import PlanTrace
            _request_diagnostics = PlanTrace()
        except Exception:
            _request_diagnostics_unavailable = True
            try:sys.stderr.write('[NC diagnostics] remote request recorder unavailable\n')
            except Exception:pass
    if _request_diagnostics is None:
        return work({key:value for key,value in body.items() if key!='diagnosticLink'})
    return _request_diagnostics.remote_call(body,site,work)


def _bridge_info_rejected(reason, expected=True, actual=False, *, error=None):
    """Failure-only evidence from the rejecting read; never retry or alter admission."""
    global _request_diagnostics
    try:
        import math
        from core.diagnostics.plan_trace import PlanTrace, current_operation
        if _request_diagnostics is None:
            _request_diagnostics = PlanTrace()
        active = current_operation()
        trace_id = active['trace_id'] if active else secrets.token_hex(16)
        caller = sys._getframe(2).f_code.co_name
        if caller not in {'_current', 'serve_forever', '_serve_ordered_output',
                          '_serve_dev_musetalk_live', '_serve_websocket'}:
            caller = 'other'
        site = 'backend.bridge_info.reject.' + caller
        # Nonfinite/huge timestamps must not suppress the rejection evidence.
        if type(actual) is float and (not math.isfinite(actual) or abs(actual) > 9007199254740991):
            actual = 'out_of_diagnostic_range'
        _request_diagnostics.observe(trace_id, site, reason, expected, actual)
        if error is not None:
            for name in ('errno', 'winerror'):
                value = getattr(error, name, None)
                if type(value) is int and abs(value) <= 9007199254740991:
                    _request_diagnostics.observe(trace_id, site, 'os_' + name, 0, value)
    except Exception:
        try: sys.stderr.write('[NC diagnostics] bridge rejection recorder unavailable\n')
        except Exception: pass
    return False

try:
    from .state_sync import StateSyncStore, request_cursor
except ImportError:
    from state_sync import StateSyncStore, request_cursor


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
WEBSOCKET_PRESENCE_INTERVAL_SECONDS = 0.15
WEBSOCKET_PRESENCE_BRIDGE_TIMEOUT_SECONDS = 0.35
BRIDGE_INFO_WATCH_INTERVAL_SECONDS = 1.0
WEBSOCKET_AUDIO_INTERVAL_SECONDS = 0.25
WEBSOCKET_AUDIO_BRIDGE_TIMEOUT_SECONDS = 1.0
WEBSOCKET_BRIDGE_RESULT_POLL_SECONDS = 0.05
WEBSOCKET_FRAME_TIMEOUT_SECONDS = 5.0
AUTH_FAILURE_LIMIT = 8
AUTH_FAILURE_WINDOW_SECONDS = 60.0
BRIDGE_QUERY_DROP_KEYS = {"code", "token"}
SENSITIVE_QUERY_VALUE_RE = re.compile(r"([?&](?:code|token|context|epoch)=)([^&\s\"']+)", re.IGNORECASE)
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


def audio_snapshot_signature(
    payload: dict[str, Any],
) -> tuple[int, int, str, str, int, tuple[tuple[str, str, int], ...]]:
    audio = dict(payload or {})
    items = list(audio.get("items") or [])
    latest = dict(items[-1]) if items else {}
    spectrum_states = tuple(
        (
            str(dict(item).get("id") or ""),
            str(dict(item).get("spectrum_status") or ""),
            int(dict(item).get("spectrum_version") or 0),
        )
        for item in items
    )
    return (
        int(audio.get("generation") or 0),
        len(items),
        str(latest.get("id") or ""),
        str(latest.get("spectrum_status") or ""),
        int(latest.get("spectrum_version") or 0),
        spectrum_states,
    )


def presence_snapshot_signature(payload: dict[str, Any]) -> tuple[str, int]:
    """Identify semantic Presence updates while ignoring transport timestamps."""

    presence = dict(payload or {})
    return (
        str(presence.get("stream_id") or ""),
        int(presence.get("revision") or 0),
    )


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
        self.state_sync = StateSyncStore()
        from core.diagnostics.policy_config import ensure_policy_loader
        ensure_policy_loader()
        self._state_sync_lock = threading.RLock()
        try:
            from .traffic_usage import TrafficTotals, traffic_kind
        except ImportError:
            from traffic_usage import TrafficTotals, traffic_kind
        self.traffic = TrafficTotals(self.bridge_info_path.parent, 'lan-http') if self.bridge_info_path else None
        self.traffic_kind = traffic_kind
        try:
            from .local_av_service import LocalAVService
        except ImportError:
            from local_av_service import LocalAVService
        self.local_av = LocalAVService(self.bridge_info_path)
        self.idle_cache = None
        self.ordered_idle_cache = None
        self.dev_musetalk_probe = None
        self.dev_musetalk_live = None
        self.ordered_output = None
        self.musetalk_delivery_status = {"status": "disabled"}
        managed_runtime = str(os.environ.get('NC_MAIN_CHAT_REMOTE_MUSETALK_RUNTIME') or '').strip()
        live_runtime = str(os.environ.get('NC_DEV_MUSETALK_LIVE_RUNTIME') or '').strip()
        live_output = str(os.environ.get('NC_DEV_MUSETALK_LIVE_OUTPUT') or '').strip()
        if managed_runtime or (live_runtime and live_output):
            failure_reason = 'initialization failed; check phone backend log'
            try:
                if managed_runtime:
                    live_root = Path(managed_runtime).resolve(strict=True)
                    expected_info = live_root / 'runtime/main_chat_remote/bridge_info.json'
                    if self.bridge_info_path is None or self.bridge_info_path.resolve() != expected_info.resolve():
                        raise ValueError('Managed delivery must use the active installation bridge')
                    # NC may start the phone service before initializing its avatar.
                    # These are source directories only; no model/renderer is started here.
                    if not (live_root / 'MuseTalk').is_dir():
                        raise FileNotFoundError('MuseTalk installation is missing')
                    for name in ('staged_audio', 'rendered_chunks'):
                        (live_root / 'MuseTalk/runtime' / name).mkdir(parents=True, exist_ok=True)
                    output_root = expected_info.parent / 'musetalk_delivery'
                    output_root.mkdir(exist_ok=True)
                    live_runtime, live_output = str(live_root), str(output_root)
                    # This process already owns media encoding; Qt only projects
                    # narrow selection data over its authenticated local bridge.
                    from addons.main_chat_remote.idle_loop_service import IdleLoopWorker
                    self.idle_cache = IdleLoopWorker(live_root, expected_info.parent/'idle-cache-v1',
                        selection=lambda: self.bridge.json_request('GET', '/api/internal/idle-selection'),
                        authorize=self.bridge_info_is_current)
                    self.ordered_idle_cache = IdleLoopWorker(live_root, expected_info.parent/'ordered-idle-cache-v1',
                        selection=lambda: self.bridge.json_request('GET', '/api/internal/idle-selection'),
                        authorize=self.bridge_info_is_current, fixed_fps=24)
                # The supervisor executes this file as a script. Keep the
                # producer in its package so its relative imports still work.
                from addons.main_chat_remote.dev_musetalk_live import DevMuseTalkLive
                # Report missing tools separately, without exposing paths or credentials.
                from core.phone_media_tools import tools
                failure_reason = 'ffmpeg/ffprobe unavailable'
                tools()
                failure_reason = 'initialization failed; check phone backend log'
                candidate = DevMuseTalkLive(live_runtime, live_output)
                if (candidate.reader.info['url'].rstrip('/') != self.bridge.bridge_url.rstrip('/')
                        or candidate.reader.info['token'] != self.bridge.bridge_token):
                    candidate.close()
                    raise ValueError('Live source must match the configured bridge')
                self.dev_musetalk_live = candidate
                from addons.main_chat_remote.ordered_output_service import OrderedOutputService
                from addons.main_chat_remote.media_quality import load_quality
                from addons.main_chat_remote.idle_cache_settings import load_settings as load_idle_cache_settings
                # Construction is inactive. Only an authenticated open accepted
                # by Desktop's complete-path capability can start the producer.
                self.ordered_output = OrderedOutputService(Path(live_output)/'ordered-v1',
                    request=self.bridge.json_request, ffmpeg=tools()[0],
                    source_roots=(Path(live_runtime),), authorize=self.bridge_info_is_current,
                    quality=lambda: load_quality(Path(live_runtime)/'runtime/main_chat_remote'),
                    idle_settings=lambda: load_idle_cache_settings(Path(live_runtime)/'runtime/main_chat_remote'),
                    idle_inventory=self._ordered_idle_inventory)
                self.musetalk_delivery_status = {'status': 'ready'}
                print('[MainChatRemote] MuseTalk video delivery ready.', flush=True)
            except Exception as exc:
                self.dev_musetalk_live = None
                self.musetalk_delivery_status = {'status': 'unavailable', 'reason': failure_reason}
                print(f'[MainChatRemote] MuseTalk video delivery unavailable: {failure_reason} ({type(exc).__name__}).', flush=True)
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
            # Windows can briefly deny opening the atomically replaced heartbeat
            # file. Retry only that read, never reuse a previous identity or turn
            # a failed check into admission. All fields below validate fresh data.
            for attempt, delay in enumerate((0.02, 0.04, 0.08, None)):
                try:
                    content = self.bridge_info_path.read_text(encoding="utf-8")
                    break
                except PermissionError:
                    if delay is None:
                        raise
                    time.sleep(delay)
            if attempt and _request_diagnostics is not None:
                try:
                    _request_diagnostics.observe('bridge-info-read', 'backend.bridge_info.retry',
                                                 'read_recovered_after_retries', 0, attempt)
                except Exception:
                    pass  # Observation is not an identity check.
            payload = json.loads(content)
        except OSError as error:
            reason = ('file_missing' if isinstance(error, FileNotFoundError) else
                      'file_permission_denied' if isinstance(error, PermissionError) else 'file_read_failed')
            return _bridge_info_rejected(reason, error=error)
        except UnicodeError:
            return _bridge_info_rejected('text_decode_failed')
        except json.JSONDecodeError:
            return _bridge_info_rejected('json_invalid')
        except (ValueError, TypeError):
            return _bridge_info_rejected('metadata_read_invalid')
        if not isinstance(payload, dict):
            return _bridge_info_rejected('payload_not_object')
        if str(payload.get("service") or "").strip() != "nc_main_chat_bridge":
            return _bridge_info_rejected('service_mismatch')
        if payload.get("enabled") is not True:
            return _bridge_info_rejected('bridge_disabled')
        token = str(payload.get("token") or "").strip()
        if not token:
            return _bridge_info_rejected('token_missing')
        if not secrets.compare_digest(token, self.bridge.bridge_token):
            return _bridge_info_rejected('token_mismatch')
        try:
            updated_at = float(payload.get("updated_at"))
        except (TypeError, ValueError):
            return _bridge_info_rejected('updated_at_invalid')
        age_seconds = time.time() - updated_at
        if age_seconds < -BRIDGE_INFO_MAX_FUTURE_SKEW_SECONDS:
            return _bridge_info_rejected('heartbeat_future', -BRIDGE_INFO_MAX_FUTURE_SKEW_SECONDS, age_seconds)
        if age_seconds > BRIDGE_INFO_MAX_AGE_SECONDS:
            return _bridge_info_rejected('heartbeat_expired', BRIDGE_INFO_MAX_AGE_SECONDS, age_seconds)
        bridge_url = normalize_bridge_url(str(payload.get("url") or DEFAULT_BRIDGE_URL))
        if bridge_url != self.bridge.bridge_url:
            return _bridge_info_rejected('url_mismatch')
        return True

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
            "musetalk_delivery": dict(self.musetalk_delivery_status),
        }

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            from core.diagnostics.policy_config import ensure_policy_loader

            ensure_policy_loader()
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
        if self.ordered_output is not None:
            self.ordered_output.shutdown()
        if self.idle_cache is not None:
            self.idle_cache.close()
        if self.ordered_idle_cache is not None:
            self.ordered_idle_cache.close()
        self.local_av.close()
        if self.dev_musetalk_live is not None:
            self.dev_musetalk_live.close()
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

    def _ordered_idle_inventory(self):
        if self.ordered_idle_cache is None: raise ValueError('ordered_cached_inventory_pending')
        status, body, _ = self.ordered_idle_cache.request('/api/idle-cache/manifest?frame_handoff=1')
        if status != 200: raise ValueError('ordered_cached_inventory_pending')
        return json.loads(body)

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

            def _count_traffic(self, direction, count):
                # Loopback is internal forwarding, already counted at the peer.
                if backend.traffic and self.client_address[0] not in ('127.0.0.1', '::1'):
                    backend.traffic.add(backend.traffic_kind(self.path), direction, count)

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

            def do_HEAD(self) -> None:
                self._handle("HEAD")

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
                    if (method == "HEAD" and not path.startswith("/api/audio/file/")
                            and not re.fullmatch(r'/api/remote-output/media/[a-f0-9]{32}/[0-9]{1,16}/[0-9]{1,16}\.mp4', path)
                            and path != "/api/dev/musetalk-probe/visual-only.mp4"
                            and not re.fullmatch(r"/api/dev/musetalk-live/(?:segment|anticipation)/[a-f0-9]{32}/[0-9]{8}\.mp4|/api/dev/musetalk-live/idle/[a-f0-9]{32}\.mp4", path)
                            and not re.fullmatch(r"/api/dev/musetalk-probe/segment/(12|24)/([0-9]{8})\.mp4", path)):
                        self._send_json({"ok": False, "error": "Method not allowed"}, status=405)
                        return
                    if path == "/health":
                        bridge_health = backend.bridge.with_timeout(HEALTH_BRIDGE_TIMEOUT_SECONDS).json_request("GET", "/health")
                        ready = bool(bridge_health.get("ok") is True)
                        public_bridge_health = public_bridge_health_snapshot(bridge_health)
                        self._send_json(
                            {
                                "ok": ready,
                                "state_sync_version": 1,
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
                    if path == '/api/diagnostics/policy':
                        if method != 'GET':
                            self._send_json({'ok':False,'error':'GET required'},status=405)
                            return
                        from core.diagnostics.policy import policy
                        self._send_json({'ok':True,'policy':policy.snapshot()})
                        return
                    if path.startswith('/api/internal/'):
                        self._send_json({'error':'Not found'}, status=404)
                        return
                    if path.startswith('/api/remote-output/'):
                        self._serve_ordered_output(method, path, parsed.query)
                        return
                    if path.startswith('/api/soundscape/'):
                        from addons.main_chat_remote.soundscape.api import parse_route, MAX_BODY
                        parse_route(method, self._bridge_path(path, parsed.query))
                        if method == 'POST' and int(self.headers.get('Content-Length') or 0) > MAX_BODY:
                            self.close_connection = True
                            self._send_json({'error': 'Sound request is too large.'}, status=413)
                            return
                    if path.startswith('/api/idle-cache/'):
                        if method != 'GET':
                            self._send_json({'error':'GET required'}, status=405)
                            return
                        ordered_idle = path.startswith('/api/idle-cache/ordered/')
                        worker = backend.ordered_idle_cache if ordered_idle else backend.idle_cache
                        if worker is None:
                            self._send_json({'error':'Idle cache unavailable'}, status=503)
                            return
                        if not backend.bridge_info_is_current():
                            self._send_json({'error':'Desktop instance changed'}, status=403)
                            return
                        # Authentication query parameters belong to the HTTP
                        # gate; they are never part of a file capability.
                        query = urllib.parse.urlencode([(k,v) for k,v in urllib.parse.parse_qsl(parsed.query)
                                                       if k.lower() not in BRIDGE_QUERY_DROP_KEYS])
                        try:
                            catalog_path = '/api/idle-cache/'+path[len('/api/idle-cache/ordered/'):] if ordered_idle else path
                            status, data, content_type = worker.request(catalog_path+('?' + query if query else ''))
                        except PermissionError:
                            self._send_json({'error':'Idle authorization ended'}, status=403)
                            return
                        if not self._authorize_or_send(parsed.query):
                            return
                        if not backend.bridge_info_is_current():
                            self._send_json({'error':'Desktop instance changed'}, status=403)
                            return
                        self.send_response(status)
                        self.send_header('Content-Type', content_type)
                        self.send_header('Content-Length', str(len(data)))
                        self.send_header('Cache-Control', 'no-store')
                        self.end_headers()
                        self.wfile.write(data)
                        if backend.traffic and not loopback_host(client_ip):
                            backend.traffic.add('video' if content_type == 'video/mp4' else 'other', 'sent', len(data))
                        return
                    if path == '/api/state' and method == 'GET':
                        if parse_qs(parsed.query).get('sync') != ['1']:
                            self._send_json({'ok': False, 'error': 'Update NC Desktop and NC Remote together (state protocol 1 required).'}, status=409)
                            return
                        cursor = request_cursor(parse_qs(parsed.query, keep_blank_values=True))
                        with backend._state_sync_lock:
                            if not backend.bridge_info_is_current():
                                backend.state_sync.clear()
                                self._send_json({'ok': False, 'error': 'Desktop instance changed. Reconnect.'}, status=409)
                                return
                            state = backend.bridge.json_request('GET', '/api/state')
                            if state.get('ok') is not True or not isinstance(state.get('state'), dict):
                                self._send_json(state, status=int(state.get('status', 502)))
                                return
                            owner = hashlib.sha256(repr((backend.pairing_code, client_ip, backend.bridge.bridge_url, backend.bridge.bridge_token)).encode()).hexdigest()
                            payload = backend.state_sync.respond(owner, state['state'], **cursor)
                        self._send_json(payload)
                        return
                    if path.startswith('/api/local-av/'):
                        if method != 'POST':
                            self._send_json({'error': 'POST required.'}, status=405)
                            return
                        if not backend.bridge_info_is_current():
                            backend.local_av.close()
                            self._send_json({'error': 'Desktop instance changed. Reconnect.'}, status=409)
                            return
                        if not 0 < int(self.headers.get('Content-Length') or 0) <= 90000:
                            self._send_json({'error': 'Invalid local media payload size.'}, status=413)
                            self.close_connection = True
                            return
                        status, payload = backend.local_av.request(path.removeprefix('/api/local-av/'),
                            self._read_json(), pairing_code=backend.pairing_code, address=client_ip)
                        self._send_json(payload, status=status)
                        return
                    if path.startswith('/api/dev/musetalk-live/'):
                        self._serve_dev_musetalk_live(method, path)
                        return
                    if method in {"GET", "HEAD"}:
                        if path.startswith("/api/dev/musetalk-probe/"):
                            self._serve_dev_musetalk_probe(path)
                            return
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

            def _serve_ordered_output(self, method, path, query):
                from addons.main_chat_remote.ordered_output_service import public_failure
                service = backend.ordered_output
                if service is None:
                    self._send_json({'ok':False,'diagnosticReason':'ordered_service_unavailable'},status=503)
                    return
                try:
                    if not backend.bridge_info_is_current():
                        raise ValueError('ordered_service_desktop_changed')
                    match = re.fullmatch(r'/api/remote-output/media/([a-f0-9]{32})/([0-9]{1,16})/([0-9]{1,16})\.mp4',path)
                    if method in {'GET','HEAD'} and match:
                        data = service.media(match[1],int(match[2]),int(match[3]))
                        if not self._authorize_or_send(query): return
                        self._send_audio_bytes(data,content_type='video/mp4')
                        return
                    route = path.removeprefix('/api/remote-output/')
                    if method == 'POST' and route in {'open','recover','wait','ack','close','halt','restart','started','cached','progress','capabilities','reattach'}:
                        if not 0 < int(self.headers.get('Content-Length') or 0) <= 4096:
                            self.close_connection=True
                            raise ValueError('ordered_service_body_size')
                        result = service.request(route,self._read_json())
                        if not self._authorize_or_send(query): return
                        if not backend.bridge_info_is_current(): raise ValueError('ordered_service_desktop_changed')
                        self._send_json(result)
                        return
                    self._send_json({'ok':False,'diagnosticReason':'ordered_service_route'},status=404)
                except Exception as error:
                    if isinstance(error,(BrokenPipeError,ConnectionAbortedError,ConnectionResetError)): return
                    details=public_failure(error)
                    self._send_json({'ok':False,'diagnosticReason':details['reason'],'failure':details},
                        status=400 if isinstance(error,ValueError) else 503)

            def _serve_dev_musetalk_live(self, method: str, path: str) -> None:
                live = backend.dev_musetalk_live
                if live is None:
                    self._send_json({'ok': False, 'error': 'Not found'}, status=404)
                    return
                prefix = '/api/dev/musetalk-live/'
                route = path[len(prefix):]
                try:
                    if method == 'POST' and route in {'arm', 'recover', 'prepare', 'prefetch', 'cancel', 'anticipation-cursor', 'idle-chunks', 'idle-chunk-cursor', 'wait-ready'}:
                        if int(self.headers.get('Content-Length') or 0) > 4096:
                            raise ValueError('Payload too large')
                        data = self._read_json()
                        if route in {'arm', 'cancel'} and 'armRequestId' in data and data['armRequestId'] is None:
                            raise ValueError('Invalid arm request identity')
                        if route == 'arm':
                            result = live.arm(**({'arm_request_id': data['armRequestId']} if 'armRequestId' in data else {}),
                                              idle_chunks=data.get('idleChunks', False),
                                              **({'muxed_audio': data['muxedAudio']} if 'muxedAudio' in data else {}))
                        elif route == 'recover':
                            result = live.recover(data.get('audio'))
                        elif route == 'prepare':
                            result = _trace_remote_request(data, 'backend.plan.prepare',
                                lambda clean: live.prepare(clean.get('trialId'), clean.get('audio'), clean.get('currentIndex')))
                        elif route == 'prefetch':
                            result = live.prefetch(data.get('trialId'), data.get('audio'))
                        elif route == 'wait-ready':
                            result = _trace_remote_request(data, 'backend.plan.wait_ready', live.wait_ready)
                        elif route == 'anticipation-cursor':
                            result = live.anticipation_cursor(data.get('trialId'), data.get('audio'), data.get('mediaId'), data.get('cursor'))
                        elif route == 'idle-chunks':
                            result = live.idle_chunks(data)
                        elif route == 'idle-chunk-cursor':
                            result = live.idle_chunk_cursor(data)
                        else:
                            arm_options = {'arm_request_id': data['armRequestId']} if 'armRequestId' in data else {}
                            if 'idleMediaId' in data:
                                live.cancel(data.get('trialId'), data.get('idleMediaId'), **arm_options)
                            else:
                                live.cancel(data.get('trialId'), **arm_options)
                            result = {'ok': True}
                        self._send_json(result)
                        return
                    status = re.fullmatch(r'status/([a-f0-9]{32})', route)
                    if method == 'GET' and status:
                        self._send_json(live.status(status.group(1)))
                        return
                    segment = re.fullmatch(r'segment/([a-f0-9]{32})/([0-9]{8})\.mp4', route)
                    if method in {'GET', 'HEAD'} and segment:
                        self._send_audio_bytes(live.segment_bytes(segment.group(1), int(segment.group(2))), content_type='video/mp4')
                        return
                    anticipation = re.fullmatch(r'anticipation/([a-f0-9]{32})/([0-9]{8})\.mp4', route)
                    if method in {'GET', 'HEAD'} and anticipation:
                        self._send_audio_bytes(live.anticipation_bytes(anticipation.group(1), int(anticipation.group(2))), content_type='video/mp4')
                        return
                    idle_chunk = re.fullmatch(r'idle-chunk/([a-f0-9]{32})/([0-9]{8})\.mp4', route)
                    if method in {'GET', 'HEAD'} and idle_chunk:
                        self._send_audio_bytes(live.idle_chunk_bytes(idle_chunk.group(1), int(idle_chunk.group(2))), content_type='video/mp4')
                        return
                    idle = re.fullmatch(r'idle/([a-f0-9]{32})\.mp4', route)
                    if method in {'GET', 'HEAD'} and idle:
                        self._send_audio_bytes(live.idle_bytes(idle.group(1)), content_type='video/mp4')
                        return
                except ValueError as exc:
                    from addons.main_chat_remote.dev_musetalk_live import MuxedTrialBusyError
                    from addons.main_chat_remote.live_control_diagnostics import rejection_reason, record_rejection
                    reason = rejection_reason(exc)
                    record_rejection(reason)
                    self._send_json({'ok': False, 'error': 'Live trial request rejected', 'diagnosticReason': reason},
                                    status=409 if isinstance(exc, MuxedTrialBusyError) else 400)
                    return
                except (LookupError, OSError):
                    pass
                except Exception:
                    self._send_json({'ok': False, 'error': 'Live trial unavailable'}, status=503)
                    return
                self._send_json({'ok': False, 'error': 'Not found'}, status=404)

            def _serve_dev_musetalk_probe(self, path: str) -> None:
                probe = backend.dev_musetalk_probe
                if probe is None:
                    self._send_json({"ok": False, "error": "Not found"}, status=404)
                    return
                try:
                    segment = re.fullmatch(r"/api/dev/musetalk-probe/segment/(12|24)/([0-9]{8})\.mp4", path)
                    if segment:
                        self._send_audio_bytes(probe.segment_bytes(int(segment.group(1)), int(segment.group(2))), content_type="video/mp4")
                        return
                    if path == "/api/dev/musetalk-probe/visual-only.mp4":
                        # Reuse the existing AVPlayer byte-range responder.
                        self._send_audio_bytes(probe.video_bytes(), content_type="video/mp4")
                        return
                    if path == "/api/dev/musetalk-probe/manifest":
                        self._send_bytes(probe.manifest_bytes(), content_type="application/json; charset=utf-8")
                        return
                    match = re.fullmatch(r"/api/dev/musetalk-probe/frame/([0-9]{8})\.png", path)
                    if match:
                        self._send_bytes(probe.frame_bytes(int(match.group(1))), content_type="image/png")
                        return
                except (LookupError, OSError, ValueError):
                    pass
                self._send_json({"ok": False, "error": "Not found"}, status=404)

            def _proxy_get(self, path: str) -> None:
                status, body, content_type = backend.bridge.request("GET", path)
                if status == 200 and urlparse(path).path.startswith("/api/audio/file/"):
                    self._send_audio_bytes(body, content_type=content_type or "application/octet-stream")
                    return
                self._send_bytes(body, status=status, content_type=content_type or "application/octet-stream")

            def _send_audio_bytes(self, body: bytes, *, content_type: str) -> None:
                # AVPlayer probes byte ranges. Slice the already-buffered bridge
                # response here; no changes to NC's capture or playback ownership.
                total = len(body)
                headers = {"Accept-Ranges": "bytes"}
                status = 200
                raw_range = self.headers.get("Range", "").strip()
                # No validators are published: If-Range cannot match. Unsupported
                # multi-ranges/malformed input fall back to the existing full GET.
                match = None
                if self.command == "GET" and not self.headers.get("If-Range") and len(raw_range) <= 128:
                    match = re.fullmatch(r"bytes=([0-9]*)-([0-9]*)", raw_range, re.IGNORECASE)
                if match and any(match.groups()):
                    first, last = match.groups()
                    start = int(first) if first else max(0, total - int(last))
                    end = min(int(last), total - 1) if first and last else total - 1
                    malformed = bool(first and last and int(last) < start)
                    if not malformed:
                        if total == 0 or start >= total or (not first and int(last) == 0):
                            status = 416
                            headers["Content-Range"] = f"bytes */{total}"
                            body = b""
                        else:
                            status = 206
                            headers["Content-Range"] = f"bytes {start}-{end}/{total}"
                            body = body[start:end + 1]
                self._send_bytes(body, status=status, content_type=content_type, extra_headers=headers)

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
                        self._count_traffic('sent', len(chunk))
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
                # Shape selects a transport budget only; bridge auth remains mandatory.
                scoped = path.rstrip("/") == "/api/phone-reply/action" or (
                    path.rstrip("/") == "/api/stt" and isinstance(payload.get("phone_reply_auth"), dict)
                )
                client = backend.bridge.with_timeout(130.0) if scoped else backend.bridge
                status, body, content_type = client.request("POST", path, payload)
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
                self._count_traffic('received', len(data))
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
                if status in {401, 429}:
                    self._finish_rejected_auth_body()

            def _finish_rejected_auth_body(self) -> None:
                # Authentication precedes body parsing. Finish the error before
                # closing unread input; a TCP reset otherwise hides the rejection.
                try:
                    remaining = min(max(0, int(self.headers.get('Content-Length') or 0)), 512 * 1024)
                except ValueError:
                    remaining = 512 * 1024
                if remaining <= 0:
                    return
                self.close_connection = True
                try:
                    self.wfile.flush()
                    self.connection.shutdown(socket.SHUT_WR)
                    deadline = time.monotonic() + .25
                    while remaining:
                        wait = deadline - time.monotonic()
                        if wait <= 0:
                            break
                        self.connection.settimeout(wait)
                        chunk = self.rfile.read1(min(64 * 1024, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                except (OSError, ValueError):
                    pass

            def _send_bytes(self, body: bytes, *, status: int = 200, content_type: str = "application/octet-stream", extra_headers: dict[str, str] | None = None) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-NC-Phone-Code")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                for name, value in (extra_headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)
                    self._count_traffic('sent', len(body))
                    self.wfile.flush()

            def _handle_websocket(self) -> None:
                if parse_qs(urlparse(self.path).query).get('state_sync') != ['1']:
                    self._send_json({'ok': False, 'error': 'Update NC Desktop and NC Remote together (state protocol 1 required).'}, status=409)
                    return
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
                    self._send_ws_json({"type": "hello", "state_sync_version": 1, "remote": backend.public_status_snapshot()})
                except OSError:
                    return
                state_bridge = backend.bridge.with_timeout(WEBSOCKET_STATE_BRIDGE_TIMEOUT_SECONDS)
                audio_bridge = backend.bridge.with_timeout(WEBSOCKET_AUDIO_BRIDGE_TIMEOUT_SECONDS)
                presence_bridge = backend.bridge.with_timeout(WEBSOCKET_PRESENCE_BRIDGE_TIMEOUT_SECONDS)
                next_state_at = 0.0
                next_audio_at = 0.0
                next_presence_at = 0.0
                last_audio_signature: tuple[int, int, str, str, int] | None = None
                last_presence_signature: tuple[str, int] | None = None
                bridge_executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=3,
                    thread_name_prefix="nc-main-chat-remote-ws-bridge",
                )
                state_future: concurrent.futures.Future[dict[str, Any]] | None = None
                self._state_store = StateSyncStore(max_contexts=1)
                self._state_cursor = {}
                ws_pairing = backend.pairing_code
                audio_future: concurrent.futures.Future[dict[str, Any]] | None = None
                presence_future: concurrent.futures.Future[dict[str, Any]] | None = None
                try:
                    while True:
                        if ws_pairing != backend.pairing_code or not backend.bridge_info_is_current():
                            self._state_store.clear()
                            self._send_ws_close()
                            return
                        now = time.time()
                        if state_future is not None and state_future.done():
                            state = state_future.result()
                            state_future = None
                            try:
                                self._send_synced_state(state)
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
                        if presence_future is not None and presence_future.done():
                            try:
                                presence_response = presence_future.result()
                                presence_payload = presence_response.get("presence")
                                if (
                                    presence_response.get("status") == 200
                                    and presence_response.get("ok") is True
                                    and isinstance(presence_payload, dict)
                                ):
                                    signature = presence_snapshot_signature(presence_payload)
                                    if signature != last_presence_signature:
                                        try:
                                            self._send_ws_json({"type": "presence", "payload": presence_payload})
                                        except OSError:
                                            return
                                        last_presence_signature = signature
                            except Exception:
                                pass
                            finally:
                                presence_future = None
                        if state_future is None and now >= next_state_at:
                            state_future = bridge_executor.submit(state_bridge.json_request, "GET", "/api/state")
                            next_state_at = now + 1.0
                        if audio_future is None and now >= next_audio_at:
                            audio_future = bridge_executor.submit(audio_bridge.json_request, "GET", "/api/audio")
                            next_audio_at = now + WEBSOCKET_AUDIO_INTERVAL_SECONDS
                        if presence_future is None and now >= next_presence_at:
                            presence_future = bridge_executor.submit(presence_bridge.json_request, "GET", "/api/presence")
                            next_presence_at = now + WEBSOCKET_PRESENCE_INTERVAL_SECONDS
                        if state_future is not None or audio_future is not None or presence_future is not None:
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
                    if presence_future is not None:
                        presence_future.cancel()
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
                    for key in ("play_on_backend", "capture_phone_audio", "visual_after_send", "audio_mode"):
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
                if msg_type == "state_sync_reset":
                    self._state_store.clear()
                    self._state_cursor = {}
                    return
                response = {"type": "error", "error": f"Unsupported message type: {msg_type}"}
                if request_id:
                    response["request_id"] = request_id
                self._send_ws_json(response)

            def _send_synced_state(self, payload) -> None:
                if payload.get('ok') is True and isinstance(payload.get('state'), dict):
                    payload = self._state_store.respond('socket', payload['state'], **self._state_cursor)
                    envelope = payload['state_sync']
                    self._state_cursor = {k: envelope[k] for k in ('context', 'epoch', 'revision')}
                self._send_ws_json({'type': 'state_sync', 'payload': payload})

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
                self._count_traffic('received', len(payload) + 6 + (2 if second & 0x7F == 126 else 8 if second & 0x7F == 127 else 0))
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
                self._count_traffic('sent', len(header) + len(body))

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
