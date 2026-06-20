from __future__ import annotations

import json
import mimetypes
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from addons.audio_story_mode.visual_stream import (
    chromecast_dependency_error,
    discover_chromecast_devices,
    install_chromecast_dependencies,
    stop_chromecast,
)
from addons.visual_reply import state as visual_reply_state


DEFAULT_MPRC_CAST_STREAM_PORT = 8766


class _ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def _local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return str(sock.getsockname()[0])
    except Exception:
        return "127.0.0.1"


def _current_visual_payload() -> dict[str, Any]:
    return dict(getattr(visual_reply_state, "current_visual_reply_data", {}) or {})


def _current_image_path() -> str:
    image_path = str(_current_visual_payload().get("image_path", "") or "").strip()
    if not image_path:
        return ""
    try:
        path = Path(image_path)
        if path.exists() and path.is_file():
            return str(path)
    except Exception:
        return ""
    return ""


def _mime_type_for_path(path: str) -> str:
    guessed, _encoding = mimetypes.guess_type(str(path or ""))
    if guessed:
        return str(guessed)
    suffix = Path(str(path or "")).suffix.lower()
    if suffix == ".wav":
        return "audio/wav"
    if suffix == ".mp3":
        return "audio/mpeg"
    if suffix == ".m4a":
        return "audio/mp4"
    if suffix == ".ogg":
        return "audio/ogg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    return "application/octet-stream"


def _query_int(query: dict[str, list[str]], key: str, default: int) -> int:
    try:
        value = int((query.get(key) or [default])[0] or default)
    except Exception:
        value = int(default)
    return max(1, min(7680, value))


def _image_bytes_fit(image_path: str, *, width: int, height: int) -> bytes:
    import io

    from PIL import Image

    with Image.open(str(image_path)) as image:
        image = image.convert("RGB")
        image.thumbnail((int(width), int(height)), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (int(width), int(height)), (0, 0, 0))
        left = max(0, (int(width) - image.width) // 2)
        top = max(0, (int(height) - image.height) // 2)
        canvas.paste(image, (left, top))
        output = io.BytesIO()
        canvas.save(output, format="JPEG", quality=92, optimize=True)
        return output.getvalue()


_chromecast_browsers: list[Any] = []


def _remember_chromecast_browser(browser: Any) -> None:
    if browser is None:
        return
    _chromecast_browsers.append(browser)
    if len(_chromecast_browsers) > 8:
        del _chromecast_browsers[:-8]


def cast_stream_page_to_chromecast(
    device_name: str,
    page_url: str,
    *,
    fallback_image_url: str = "",
    timeout: float = 12.0,
) -> tuple[bool, str]:
    dependency_error = chromecast_dependency_error()
    if dependency_error:
        return False, dependency_error
    name = str(device_name or "").strip()
    if not name:
        return False, "Choose a Chromecast device first."
    page = str(page_url or "").strip()
    if not page:
        return False, "No MPRC cast stream URL is available."

    import pychromecast

    browser = None
    try:
        chromecasts, browser = pychromecast.get_listed_chromecasts(
            friendly_names=[name],
            discovery_timeout=float(timeout),
        )
        if not chromecasts:
            return False, f"Chromecast not found: {name}"
        cast = chromecasts[0]
        cast.wait(timeout=float(timeout))
        try:
            from pychromecast.controllers.dashcast import DashCastController

            dashcast = DashCastController()
            cast.register_handler(dashcast)
            dashcast.load_url(page, force=True)
            return True, f"Casting MPRC story visuals and speech to {name}."
        except Exception as exc:
            image_url = str(fallback_image_url or "").strip()
            if image_url:
                controller = cast.media_controller
                controller.play_media(image_url, "image/jpeg", title="MPRC Story Mode")
                controller.block_until_active(timeout=float(timeout))
                return True, f"DashCast web stream failed ({exc}); casting latest MPRC visual only to {name}."
            return False, f"DashCast web stream failed: {exc}"
    except Exception as exc:
        return False, str(exc)
    finally:
        _remember_chromecast_browser(browser)


class MprcCastStreamServer:
    def __init__(self, controller: Any, *, port: int = DEFAULT_MPRC_CAST_STREAM_PORT, port_scan_limit: int = 80):
        self.controller = controller
        self.port = max(1024, min(65535, int(port or DEFAULT_MPRC_CAST_STREAM_PORT)))
        self.port_scan_limit = max(1, min(512, int(port_scan_limit or 80)))
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def url(self) -> str:
        return f"http://{_local_ip()}:{int(self.port)}/"

    def start(self) -> str:
        if self._server is not None:
            return self.url
        server = self._bind_server()
        server.daemon_threads = True
        server.mprc_cast_stream = self  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, name="mprc-cast-stream", daemon=True)
        thread.start()
        self._server = server
        self._thread = thread
        return self.url

    def stop(self) -> None:
        server = self._server
        self._server = None
        self._thread = None
        if server is None:
            return
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass

    def snapshot(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "url": self.url if self.running else "",
            "port": int(self.port),
        }

    def _bind_server(self) -> ThreadingHTTPServer:
        first_port = int(self.port)
        last_error: Exception | None = None
        candidates = list(range(first_port, min(65535, first_port + int(self.port_scan_limit) - 1) + 1))
        candidates.extend(
            port
            for port in range(49152, min(65535, 49152 + int(self.port_scan_limit) - 1) + 1)
            if port not in candidates
        )
        for candidate in candidates:
            try:
                server = _ReusableThreadingHTTPServer(("0.0.0.0", int(candidate)), _MprcCastStreamHandler)
                self.port = int(candidate)
                return server
            except OSError as exc:
                last_error = exc
                if getattr(exc, "winerror", None) not in {10013, 10048, None}:
                    break
                continue
        if last_error is not None:
            raise RuntimeError(f"Could not bind MPRC Cast stream near port {first_port}: {last_error}") from last_error
        raise RuntimeError(f"Could not bind MPRC Cast stream near port {first_port}.")

    def state_payload(self) -> dict[str, Any]:
        image_path = _current_image_path()
        visual_payload = _current_visual_payload()
        try:
            speech_audio = dict(self.controller.remote_speech_audio_snapshot() or {})
        except Exception:
            speech_audio = {}
        items: list[dict[str, Any]] = []
        for item in list(speech_audio.get("items") or []):
            data = dict(item or {})
            audio_id = str(data.get("id") or "").strip()
            if not audio_id:
                continue
            data["url_path"] = f"/audio/file/{audio_id}"
            items.append(data)
        caption = str(visual_payload.get("caption") or visual_payload.get("source") or "MPRC Story Mode").strip()
        return {
            "ready": bool(image_path),
            "path": image_path,
            "caption": caption,
            "audio_ready": bool(items),
            "audio_generation": int(speech_audio.get("generation") or 0),
            "audio_items": items,
            "speech_status": str(speech_audio.get("status") or "idle"),
            "updated_at": time.time(),
        }

    def audio_file_path(self, audio_id: str) -> Path:
        return self.controller.remote_speech_audio_file_path(str(audio_id or ""))


class _MprcCastStreamHandler(BaseHTTPRequestHandler):
    server_version = "MprcCastStream/0.1"

    def log_message(self, _format, *_args):
        return

    @property
    def stream(self) -> MprcCastStreamServer:
        return self.server.mprc_cast_stream  # type: ignore[attr-defined]

    def do_GET(self):  # noqa: N802
        parsed = urlparse(str(self.path or "/"))
        path = parsed.path
        if path in {"", "/"}:
            return self._send_html()
        if path == "/state.json":
            return self._send_json(self.stream.state_payload())
        if path == "/current.jpg":
            query = parse_qs(parsed.query or "")
            fit = str((query.get("fit") or [""])[0] or "").strip().lower()
            width = _query_int(query, "w", 1920)
            height = _query_int(query, "h", 1080)
            return self._send_current_image(width=width, height=height) if fit else self._send_current_image()
        if path.startswith("/audio/file/"):
            audio_id = path.rsplit("/", 1)[-1]
            return self._send_audio(audio_id)
        self.send_error(404)

    def _send_html(self) -> None:
        payload = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MPRC Story Cast</title>
<style>
html, body { margin: 0; width: 100%; height: 100%; background: #05070a; color: #f8fafc; font-family: system-ui, sans-serif; overflow: hidden; }
#stage { width: 100vw; height: 100vh; display: grid; place-items: center; background: #05070a; }
#image { width: 100vw; height: 100vh; object-fit: contain; }
#empty { color: #94a3b8; font-size: 18px; padding: 24px; text-align: center; }
#caption { position: fixed; left: 24px; right: 24px; bottom: 28px; max-height: 30vh; overflow: hidden; padding: 16px 18px; background: rgba(3,7,18,.72); border: 1px solid rgba(148,163,184,.28); border-radius: 8px; color: #f8fafc; font-size: 18px; line-height: 1.35; text-shadow: 0 1px 3px #000; white-space: pre-wrap; }
</style>
</head>
<body>
<div id="stage"><div id="empty">Waiting for MPRC story visual...</div><img id="image" hidden></div>
<div id="caption" hidden></div>
<audio id="audio" preload="auto" autoplay></audio>
<script>
let lastPath = "";
let generation = -1;
let queue = [];
let played = new Set();
let currentId = "";
const audio = document.getElementById("audio");

function playNext() {
  if (currentId || !queue.length) return;
  const item = queue.shift();
  if (!item || !item.id || played.has(item.id)) {
    setTimeout(playNext, 0);
    return;
  }
  currentId = item.id;
  played.add(item.id);
  audio.src = item.url_path + "?ts=" + Date.now();
  audio.play().catch(() => {
    currentId = "";
    setTimeout(playNext, 250);
  });
}

audio.addEventListener("ended", () => {
  currentId = "";
  playNext();
});
audio.addEventListener("error", () => {
  currentId = "";
  setTimeout(playNext, 500);
});

async function refresh() {
  try {
    const response = await fetch("/state.json?ts=" + Date.now(), { cache: "no-store" });
    const state = await response.json();
    const img = document.getElementById("image");
    const empty = document.getElementById("empty");
    const caption = document.getElementById("caption");
    if (state.ready) {
      if (state.path !== lastPath) {
        lastPath = state.path;
        img.src = "/current.jpg?fit=screen&w=1920&h=1080&ts=" + Date.now();
      }
      img.hidden = false;
      empty.hidden = true;
      caption.textContent = state.caption || "";
      caption.hidden = !caption.textContent;
    } else {
      img.hidden = true;
      empty.hidden = false;
      caption.textContent = "";
      caption.hidden = true;
    }
    const nextGeneration = Number(state.audio_generation || 0);
    if (nextGeneration !== generation) {
      generation = nextGeneration;
      queue = [];
      played = new Set();
      currentId = "";
    }
    for (const item of state.audio_items || []) {
      if (!item.id || played.has(item.id) || queue.some((queued) => queued.id === item.id) || currentId === item.id) continue;
      queue.push(item);
    }
    playNext();
  } catch (error) {}
}
setInterval(refresh, 500);
refresh();
</script>
</body>
</html>""".encode("utf-8")
        self._send_bytes(payload, "text/html; charset=utf-8")

    def _send_json(self, payload: dict[str, Any]) -> None:
        self._send_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _send_current_image(self, *, width: int | None = None, height: int | None = None) -> None:
        image_path = _current_image_path()
        if not image_path:
            self.send_error(404)
            return
        try:
            if width and height:
                data = _image_bytes_fit(image_path, width=int(width), height=int(height))
                content_type = "image/jpeg"
            else:
                data = Path(image_path).read_bytes()
                content_type = _mime_type_for_path(image_path)
        except Exception:
            self.send_error(404)
            return
        self._send_bytes(data, content_type)

    def _send_audio(self, audio_id: str) -> None:
        try:
            path = self.stream.audio_file_path(audio_id)
        except Exception:
            self.send_error(404)
            return
        self._send_file(path, _mime_type_for_path(str(path)))

    def _send_bytes(self, payload: bytes, content_type: str, *, status: int = 200) -> None:
        self.send_response(int(status))
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def _send_file(self, path: Path, content_type: str) -> None:
        try:
            file_size = path.stat().st_size
        except Exception:
            self.send_error(404)
            return
        range_header = str(self.headers.get("Range", "") or "").strip()
        start = 0
        end = max(0, int(file_size) - 1)
        status = 200
        if range_header.lower().startswith("bytes="):
            raw_range = range_header.split("=", 1)[1].split(",", 1)[0].strip()
            raw_start, _sep, raw_end = raw_range.partition("-")
            try:
                if raw_start:
                    start = max(0, min(end, int(raw_start)))
                if raw_end:
                    end = max(start, min(end, int(raw_end)))
                status = 206
            except Exception:
                start = 0
                end = max(0, int(file_size) - 1)
                status = 200
        length = max(0, int(end) - int(start) + 1)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            with path.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = handle.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except Exception:
            return


class MprcChromecastBridge:
    def __init__(
        self,
        controller: Any,
        *,
        discover_func: Callable[[float], tuple[list[dict], str]] = discover_chromecast_devices,
        cast_func: Callable[..., tuple[bool, str]] = cast_stream_page_to_chromecast,
        stop_func: Callable[..., tuple[bool, str]] = stop_chromecast,
        install_func: Callable[[], tuple[bool, str]] = install_chromecast_dependencies,
        dependency_error_func: Callable[[], str] = chromecast_dependency_error,
    ):
        self.controller = controller
        self._discover_func = discover_func
        self._cast_func = cast_func
        self._stop_func = stop_func
        self._install_func = install_func
        self._dependency_error_func = dependency_error_func
        self._lock = threading.RLock()
        self._devices: list[dict[str, Any]] = []
        self._active_device_name = ""
        self._status = "Chromecast discovery not run."
        self._busy = False
        self._stream_server: MprcCastStreamServer | None = None

    def snapshot(self) -> dict[str, Any]:
        dependency_error = self._dependency_error_func()
        with self._lock:
            stream = self._stream_server.snapshot() if self._stream_server is not None else {"running": False, "url": "", "port": self.stream_port()}
            return {
                "available": not bool(dependency_error),
                "dependency_error": dependency_error,
                "devices": [dict(item) for item in self._devices],
                "selected_device": self.selected_device_name(),
                "active_device": str(self._active_device_name or ""),
                "casting": bool(self._active_device_name),
                "busy": bool(self._busy),
                "status": dependency_error or str(self._status or "Chromecast idle."),
                "stream": stream,
            }

    def selected_device_name(self) -> str:
        settings = getattr(self.controller, "settings", {}) or {}
        return str(settings.get("chromecast_device_name") or "").strip()

    def stream_port(self) -> int:
        settings = getattr(self.controller, "settings", {}) or {}
        try:
            value = int(settings.get("chromecast_stream_port", DEFAULT_MPRC_CAST_STREAM_PORT) or DEFAULT_MPRC_CAST_STREAM_PORT)
        except Exception:
            value = DEFAULT_MPRC_CAST_STREAM_PORT
        return max(1024, min(65535, value))

    def action(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = dict(payload or {})
        action = str(data.get("action") or "status").strip().lower()
        if action in {"status", "state"}:
            return {"accepted": True, "message": self.snapshot().get("status", ""), "cast": self.snapshot()}
        if action in {"refresh", "discover", "devices"}:
            return self.discover()
        if action == "install":
            return self.install()
        if action in {"start", "cast"}:
            return self.cast(str(data.get("device_name") or data.get("device") or ""))
        if action in {"stop", "disconnect"}:
            return self.stop()
        return {"accepted": False, "message": f"Unsupported Chromecast action: {action or 'missing'}", "cast": self.snapshot()}

    def discover(self) -> dict[str, Any]:
        if not self._begin_busy():
            return {"accepted": False, "message": "Chromecast operation already running.", "cast": self.snapshot()}
        try:
            devices, error = self._discover_func(7.0)
            with self._lock:
                self._devices = [dict(item) for item in list(devices or [])]
                if error:
                    self._status = f"Chromecast discovery failed: {error}"
                    accepted = False
                elif self._devices:
                    self._status = f"Found {len(self._devices)} Chromecast device(s)."
                    accepted = True
                else:
                    self._status = "No Chromecast devices found on this network."
                    accepted = True
            return {"accepted": accepted, "message": self._status, "cast": self.snapshot()}
        finally:
            self._end_busy()

    def install(self) -> dict[str, Any]:
        if not self._begin_busy():
            return {"accepted": False, "message": "Chromecast operation already running.", "cast": self.snapshot()}
        try:
            ok, message = self._install_func()
            with self._lock:
                self._status = str(message or ("PyChromecast installed." if ok else "PyChromecast install failed."))
            return {"accepted": bool(ok), "message": self._status, "cast": self.snapshot()}
        finally:
            self._end_busy()

    def cast(self, device_name: str = "") -> dict[str, Any]:
        name = str(device_name or self.selected_device_name() or "").strip()
        if not name:
            return {"accepted": False, "message": "Choose a Chromecast device first.", "cast": self.snapshot()}
        if not self._begin_busy():
            return {"accepted": False, "message": "Chromecast operation already running.", "cast": self.snapshot()}
        try:
            self._set_selected_device(name)
            page_url = self._stream_page_url()
            image_url = self._cast_image_url()
            if not page_url:
                with self._lock:
                    self._status = "Could not start MPRC Cast stream. Try another port or allow Python through Windows Firewall."
                return {"accepted": False, "message": self._status, "cast": self.snapshot()}
            ok, message = self._cast_func(name, page_url, fallback_image_url=image_url, timeout=12.0)
            with self._lock:
                if ok:
                    self._active_device_name = name
                self._status = str(message or ("Chromecast cast started." if ok else "Chromecast cast failed."))
            return {"accepted": bool(ok), "message": self._status, "cast": self.snapshot()}
        finally:
            self._end_busy()

    def stop(self) -> dict[str, Any]:
        target_names: list[str] = []
        with self._lock:
            for name in (self._active_device_name, self.selected_device_name()):
                if name and name not in target_names:
                    target_names.append(str(name))
        if not target_names:
            self.stop_stream()
            return {"accepted": False, "message": "Choose a Chromecast device first.", "cast": self.snapshot()}
        if not self._begin_busy():
            return {"accepted": False, "message": "Chromecast operation already running.", "cast": self.snapshot()}
        try:
            messages: list[str] = []
            ok_any = False
            for target in target_names:
                ok, message = self._stop_func(target, timeout=8.0)
                ok_any = bool(ok_any or ok)
                if message:
                    messages.append(str(message))
            self.stop_stream()
            with self._lock:
                self._active_device_name = ""
                self._status = " ".join(messages).strip() or "Stopped Chromecast."
            accepted = bool(ok_any or messages or target_names)
            return {"accepted": accepted, "message": self._status, "cast": self.snapshot()}
        finally:
            self._end_busy()

    def stop_stream(self) -> None:
        server = self._stream_server
        self._stream_server = None
        if server is not None:
            try:
                server.stop()
            except Exception:
                pass

    def _stream_page_url(self) -> str:
        server = self._ensure_stream_server()
        if server is None or not server.running:
            return ""
        return f"{server.url.rstrip('/')}/?cast=1&ts={int(time.time())}"

    def _cast_image_url(self) -> str:
        server = self._ensure_stream_server()
        if server is None or not server.running:
            return ""
        return f"{server.url.rstrip('/')}/current.jpg?fit=cast&w=1920&h=1080&ts={int(time.time())}"

    def _ensure_stream_server(self) -> MprcCastStreamServer | None:
        server = self._stream_server
        if server is not None and server.running:
            return server
        try:
            server = MprcCastStreamServer(self.controller, port=self.stream_port())
            server.start()
            self._stream_server = server
            settings = getattr(self.controller, "settings", None)
            if isinstance(settings, dict):
                settings["chromecast_stream_port"] = int(server.port)
                storage = getattr(self.controller, "storage", None)
                save_settings = getattr(storage, "save_settings", None)
                if callable(save_settings):
                    save_settings(settings)
            return server
        except Exception as exc:
            with self._lock:
                self._status = f"Could not start MPRC Cast stream: {exc}"
            return None

    def _set_selected_device(self, name: str) -> None:
        settings = getattr(self.controller, "settings", None)
        if isinstance(settings, dict):
            settings["chromecast_device_name"] = str(name or "").strip()
            storage = getattr(self.controller, "storage", None)
            save_settings = getattr(storage, "save_settings", None)
            if callable(save_settings):
                save_settings(settings)

    def _begin_busy(self) -> bool:
        with self._lock:
            if self._busy:
                return False
            self._busy = True
            return True

    def _end_busy(self) -> None:
        with self._lock:
            self._busy = False
