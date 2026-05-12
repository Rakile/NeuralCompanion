from __future__ import annotations

import json
import mimetypes
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from addons.visual_reply import state as visual_reply_state


class _ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def _local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return str(sock.getsockname()[0])
    except Exception:
        return "127.0.0.1"


def _current_image_path() -> str:
    payload = dict(getattr(visual_reply_state, "current_visual_reply_data", {}) or {})
    image_path = str(payload.get("image_path", "") or "").strip()
    if not image_path:
        return ""
    try:
        path = Path(image_path)
        if path.exists() and path.is_file():
            return str(path)
    except Exception:
        return ""
    return ""


_current_audio_path_lock = threading.Lock()
_current_audio_path = ""
_stream_state_lock = threading.Lock()
_stream_state = {
    "playback_state": "stopped",
    "position_seconds": 0.0,
    "show_prompt": False,
}
_chromecast_browsers = []


def set_current_audio_path(path: str) -> None:
    global _current_audio_path
    value = str(path or "").strip()
    with _current_audio_path_lock:
        _current_audio_path = value


def _active_audio_path() -> str:
    with _current_audio_path_lock:
        audio_path = str(_current_audio_path or "").strip()
    if not audio_path:
        return ""
    try:
        path = Path(audio_path)
        if path.exists() and path.is_file():
            return str(path)
    except Exception:
        return ""
    return ""


def set_stream_playback_state(*, playback_state: str = "", position_seconds: float | None = None, show_prompt: bool | None = None) -> None:
    with _stream_state_lock:
        if playback_state:
            _stream_state["playback_state"] = str(playback_state or "stopped").strip().lower() or "stopped"
        if position_seconds is not None:
            try:
                _stream_state["position_seconds"] = max(0.0, float(position_seconds or 0.0))
            except Exception:
                _stream_state["position_seconds"] = 0.0
        if show_prompt is not None:
            _stream_state["show_prompt"] = bool(show_prompt)


def _current_stream_state() -> dict:
    with _stream_state_lock:
        return dict(_stream_state or {})


class AudioStoryVisualStreamServer:
    def __init__(self, *, port: int = 8765, port_scan_limit: int = 80):
        self.port = max(1024, min(65535, int(port or 8765)))
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
        thread = threading.Thread(target=server.serve_forever, name="audio-story-visual-stream", daemon=True)
        thread.start()
        self._server = server
        self._thread = thread
        return self.url

    def _bind_server(self) -> ThreadingHTTPServer:
        first_port = int(self.port)
        last_error: Exception | None = None
        candidates = list(range(first_port, min(65535, first_port + int(self.port_scan_limit) - 1) + 1))
        candidates.extend(port for port in range(49152, min(65535, 49152 + int(self.port_scan_limit) - 1) + 1) if port not in candidates)
        for candidate in candidates:
            if candidate > 65535:
                break
            try:
                server = _ReusableThreadingHTTPServer(("0.0.0.0", int(candidate)), _VisualStreamHandler)
                self.port = int(candidate)
                return server
            except OSError as exc:
                last_error = exc
                if getattr(exc, "winerror", None) not in {10013, 10048, None}:
                    break
                continue
        if last_error is not None:
            raise RuntimeError(
                f"Could not bind visual stream on port {first_port}, nearby ports,"
                f" or fallback high ports: {last_error}"
            ) from last_error
        raise RuntimeError(f"Could not bind visual stream on port {first_port}.")

    def stop(self) -> None:
        server = self._server
        self._server = None
        self._thread = None
        if server is not None:
            try:
                server.shutdown()
            except Exception:
                pass
            try:
                server.server_close()
            except Exception:
                pass


def chromecast_dependency_error() -> str:
    try:
        import pychromecast  # noqa: F401

        return ""
    except Exception:
        return "PyChromecast is not installed. Run: pip install PyChromecast zeroconf"


def discover_chromecast_devices(timeout: float = 6.0) -> tuple[list[dict], str]:
    dependency_error = chromecast_dependency_error()
    if dependency_error:
        return [], dependency_error
    import pychromecast

    browser = None
    try:
        chromecasts, browser = pychromecast.get_chromecasts(timeout=float(timeout))
        devices = []
        for cast in list(chromecasts or []):
            info = getattr(cast, "cast_info", None)
            friendly_name = str(getattr(info, "friendly_name", "") or getattr(cast, "name", "") or "").strip()
            uuid_value = str(getattr(info, "uuid", "") or getattr(cast, "uuid", "") or "").strip()
            cast_type = str(getattr(info, "cast_type", "") or getattr(cast, "cast_type", "") or "").strip()
            model_name = str(getattr(info, "model_name", "") or getattr(cast, "model_name", "") or "").strip()
            host = str(getattr(info, "host", "") or "").strip()
            if not friendly_name:
                continue
            if cast_type.lower() in {"audio", "group"}:
                continue
            devices.append(
                {
                    "name": friendly_name,
                    "uuid": uuid_value,
                    "cast_type": cast_type,
                    "model_name": model_name,
                    "host": host,
                    "label": f"{friendly_name} ({model_name or cast_type or 'Cast'})",
                }
            )
        devices.sort(key=lambda item: str(item.get("name", "")).lower())
        return devices, ""
    except Exception as exc:
        return [], str(exc)
    finally:
        # Keep the discovery browser alive here. PyChromecast cast sockets can
        # retain the discovered service object and crash if its Zeroconf loop is
        # stopped immediately after media launch.
        _remember_chromecast_browser(browser)


def _remember_chromecast_browser(browser) -> None:
    if browser is None:
        return
    _chromecast_browsers.append(browser)
    if len(_chromecast_browsers) > 8:
        del _chromecast_browsers[:-8]


def cast_image_to_chromecast(device_name: str, image_url: str, *, page_url: str = "", audio_url: str = "", timeout: float = 12.0) -> tuple[bool, str]:
    dependency_error = chromecast_dependency_error()
    if dependency_error:
        return False, dependency_error
    name = str(device_name or "").strip()
    if not name:
        return False, "Choose a Chromecast device first."
    url = str(image_url or "").strip()
    if not url:
        return False, "No image URL is available to cast."
    import pychromecast

    browser = None
    try:
        chromecasts, browser = pychromecast.get_listed_chromecasts(friendly_names=[name], discovery_timeout=float(timeout))
        if not chromecasts:
            return False, f"Chromecast not found: {name}"
        cast = chromecasts[0]
        cast.wait(timeout=float(timeout))
        if page_url:
            try:
                from pychromecast.controllers.dashcast import DashCastController

                dashcast = DashCastController()
                cast.register_handler(dashcast)
                dashcast.load_url(str(page_url), force=True)
                return True, f"Casting Audio Story visuals and audio to {name}."
            except Exception as exc:
                if audio_url:
                    controller = cast.media_controller
                    controller.play_media(str(audio_url), _mime_type_for_path(_active_audio_path() or str(audio_url)), title="Audio Story Mode")
                    controller.block_until_active(timeout=float(timeout))
                    return True, f"DashCast web stream failed ({exc}); casting Audio Story audio only to {name}."
        controller = cast.media_controller
        controller.play_media(url, "image/jpeg", title="Audio Story Mode")
        controller.block_until_active(timeout=float(timeout))
        return True, f"Casting Audio Story visuals to {name}."
    except Exception as exc:
        return False, str(exc)
    finally:
        _remember_chromecast_browser(browser)


def stop_chromecast(device_name: str, *, timeout: float = 8.0) -> tuple[bool, str]:
    dependency_error = chromecast_dependency_error()
    if dependency_error:
        return False, dependency_error
    name = str(device_name or "").strip()
    if not name:
        return False, "Choose a Chromecast device first."
    import pychromecast

    browser = None
    try:
        chromecasts, browser = pychromecast.get_listed_chromecasts(friendly_names=[name], discovery_timeout=float(timeout))
        if not chromecasts:
            return False, f"Chromecast not found: {name}"
        cast = chromecasts[0]
        cast.wait(timeout=float(timeout))
        try:
            cast.media_controller.stop()
        except Exception:
            pass
        try:
            cast.quit_app()
        except Exception:
            pass
        try:
            cast.disconnect(timeout=float(timeout))
        except Exception:
            pass
        return True, f"Stopped Chromecast: {name}."
    except Exception as exc:
        return False, str(exc)
    finally:
        _remember_chromecast_browser(browser)


class _VisualStreamHandler(BaseHTTPRequestHandler):
    server_version = "AudioStoryVisualStream/0.1"

    def log_message(self, _format, *_args):
        return

    def do_GET(self):  # noqa: N802
        parsed_url = urlparse(str(self.path or "/"))
        path = parsed_url.path
        if path in {"", "/"}:
            return self._send_html()
        if path == "/state.json":
            return self._send_state()
        if path == "/audio":
            return self._send_audio()
        if path == "/current.jpg":
            query = parse_qs(parsed_url.query or "")
            fit = str((query.get("fit") or [""])[0] or "").strip().lower()
            width = _query_int(query, "w", 1920)
            height = _query_int(query, "h", 1080)
            if fit:
                return self._send_current_image(width=width, height=height)
            return self._send_current_image()
        self.send_error(404)

    def _send_bytes(self, payload: bytes, content_type: str, *, status: int = 200) -> None:
        self.send_response(int(status))
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def _send_html(self) -> None:
        payload = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Audio Story Visual Stream</title>
<style>
html, body { margin: 0; width: 100%; height: 100%; background: #05070a; color: #f8fafc; font-family: system-ui, sans-serif; overflow: hidden; }
#stage { width: 100vw; height: 100vh; display: grid; place-items: center; background: #05070a; }
#image { width: 100vw; height: 100vh; object-fit: contain; }
#empty { color: #94a3b8; font-size: 18px; padding: 24px; text-align: center; }
#prompt { position: fixed; left: 24px; right: 24px; bottom: 28px; max-height: 34vh; overflow: hidden; padding: 16px 18px; background: rgba(3,7,18,.72); border: 1px solid rgba(148,163,184,.28); border-radius: 8px; color: #f8fafc; font-size: 18px; line-height: 1.35; text-shadow: 0 1px 3px #000; white-space: pre-wrap; }
</style>
</head>
<body>
<div id="stage"><div id="empty">Waiting for Audio Story image...</div><img id="image" hidden></div>
<div id="prompt" hidden></div>
<audio id="audio" preload="auto" autoplay></audio>
<script>
let lastPath = "";
let lastAudioPath = "";
let lastSeek = 0;
let lastPlaybackState = "";
async function refresh() {
  try {
    const response = await fetch("/state.json?ts=" + Date.now(), { cache: "no-store" });
    const state = await response.json();
    const img = document.getElementById("image");
    const empty = document.getElementById("empty");
    const prompt = document.getElementById("prompt");
    const audio = document.getElementById("audio");
    if (state.ready) {
      if (state.path !== lastPath) {
        lastPath = state.path;
        img.src = "/current.jpg?fit=screen&w=1920&h=1080&ts=" + Date.now();
      }
      img.hidden = false;
      empty.hidden = true;
      if (state.show_prompt) {
        prompt.textContent = state.caption || "";
        prompt.hidden = false;
      } else {
        prompt.textContent = "";
        prompt.hidden = true;
      }
    } else {
      img.hidden = true;
      empty.hidden = false;
      prompt.textContent = "";
      prompt.hidden = true;
    }
    if (state.audio_ready && state.audio_path !== lastAudioPath) {
      lastAudioPath = state.audio_path;
      audio.src = "/audio?ts=" + Date.now();
      lastSeek = 0;
    }
    if (state.audio_ready) {
      const target = Number(state.position_seconds || 0);
      if (Math.abs((audio.currentTime || 0) - target) > 1.25 && Date.now() - lastSeek > 900) {
        audio.currentTime = target;
        lastSeek = Date.now();
      }
      if (state.playback_state === "playing") {
        audio.play().catch(() => {});
      } else if (state.playback_state === "paused" || state.playback_state === "stopped") {
        audio.pause();
        if (state.playback_state === "stopped" && Math.abs((audio.currentTime || 0) - target) > 0.25) {
          audio.currentTime = target;
        }
      }
      lastPlaybackState = state.playback_state || "";
    } else {
      if (lastAudioPath) {
        audio.pause();
        audio.removeAttribute("src");
        audio.load();
      }
      lastAudioPath = "";
      lastPlaybackState = "";
    }
  } catch (error) {}
}
setInterval(refresh, 500);
refresh();
</script>
</body>
</html>""".encode("utf-8")
        self._send_bytes(payload, "text/html; charset=utf-8")

    def _send_state(self) -> None:
        image_path = _current_image_path()
        audio_path = _active_audio_path()
        payload = dict(getattr(visual_reply_state, "current_visual_reply_data", {}) or {})
        stream_state = _current_stream_state()
        show_prompt = bool(stream_state.get("show_prompt", False))
        caption = str(payload.get("caption") or payload.get("source") or "Audio Story Mode").strip() if show_prompt else ""
        state = {
            "ready": bool(image_path),
            "path": image_path,
            "audio_ready": bool(audio_path),
            "audio_path": audio_path,
            "caption": caption,
            "playback_state": str(stream_state.get("playback_state", "stopped") or "stopped"),
            "position_seconds": max(0.0, float(stream_state.get("position_seconds", 0.0) or 0.0)),
            "show_prompt": show_prompt,
            "updated_at": time.time(),
        }
        self._send_bytes(json.dumps(state, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _send_audio(self) -> None:
        audio_path = _active_audio_path()
        if not audio_path:
            self.send_error(404)
            return
        self._send_file(audio_path, _mime_type_for_path(audio_path))

    def _send_current_image(self, *, width: int | None = None, height: int | None = None) -> None:
        image_path = _current_image_path()
        if not image_path:
            self.send_error(404)
            return
        try:
            if width and height:
                data = _image_bytes_fit(image_path, width=width, height=height)
                content_type = "image/jpeg"
            else:
                data = Path(image_path).read_bytes()
                suffix = Path(image_path).suffix.lower()
                content_type = "image/png" if suffix == ".png" else "image/webp" if suffix == ".webp" else "image/jpeg"
        except Exception:
            self.send_error(404)
            return
        self._send_bytes(data, content_type)

    def _send_file(self, path: str, content_type: str) -> None:
        file_path = Path(path)
        try:
            file_size = file_path.stat().st_size
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
            with file_path.open("rb") as handle:
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


def _query_int(query: dict, key: str, default: int) -> int:
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
    return "application/octet-stream"
