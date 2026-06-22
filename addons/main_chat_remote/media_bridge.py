from __future__ import annotations

import mimetypes
import re
import shutil
import threading
import time
import wave
from pathlib import Path
from typing import Any


DEFAULT_CAPTURE_SECONDS = 900.0
SUPPORTED_AUDIO_EXTENSIONS = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav", ".webm"}


class MainChatMediaBridge:
    """Copies runtime TTS chunks into an addon-local cache for phone playback."""

    def __init__(self, cache_dir: Path, logger=None):
        self._cache_dir = Path(cache_dir)
        self._logger = logger
        self._lock = threading.RLock()
        self._generation = 0
        self._items: list[dict[str, Any]] = []
        self._status = "idle"
        self._capture_until = 0.0
        self._suppress_backend_playback_until = 0.0
        self._suppress_backend_playback_generation = 0
        self._phone_audio_capture_generation = 0
        self._source_excerpt = ""
        self._next_index = 1

    def begin_tts_capture(
        self,
        source_text: str,
        *,
        capture_seconds: float = DEFAULT_CAPTURE_SECONDS,
        suppress_backend_playback: bool = False,
        capture_phone_audio: bool = True,
    ) -> None:
        with self._lock:
            old_items = self._begin_capture_locked(
                source_text,
                capture_seconds=capture_seconds,
                now=time.time(),
                suppress_backend_playback=bool(suppress_backend_playback),
                capture_phone_audio=bool(capture_phone_audio),
            )
        for item in old_items:
            self._unlink_cached_item(item)

    def stop_capture(self) -> None:
        with self._lock:
            self._capture_until = 0.0
            self._suppress_backend_playback_until = 0.0
            self._suppress_backend_playback_generation = 0
            self._phone_audio_capture_generation = 0
            if not self._items:
                self._status = "idle"

    def handle_tts_audio_chunk_ready(self, payload: dict[str, Any] | None = None):
        data = dict(payload or {})
        source_path = Path(str(data.get("audio_path") or ""))
        suffix = self._safe_audio_suffix(source_path)
        if not source_path.exists() or not source_path.is_file() or not suffix:
            return None
        now = time.time()
        old_items: list[dict[str, Any]] = []
        with self._lock:
            if now > float(self._capture_until or 0.0):
                old_items = self._begin_capture_locked(
                    self._auto_capture_excerpt(data),
                    capture_seconds=DEFAULT_CAPTURE_SECONDS,
                    now=now,
                    suppress_backend_playback=False,
                    capture_phone_audio=True,
                )
            generation = int(self._generation or 0)
            skip_backend_playback = bool(
                self._suppress_backend_playback_generation == generation
                and now <= float(self._suppress_backend_playback_until or 0.0)
            )
            capture_phone_audio = bool(self._phone_audio_capture_generation == generation)
            index = max(1, int(self._next_index or 1))
            self._next_index = index + 1
        for item in old_items:
            self._unlink_cached_item(item)
        if not capture_phone_audio:
            return {
                "captured": False,
                "skip_local_playback": skip_backend_playback,
            }
        target_id = f"g{generation:04d}_{index:03d}_{int(now * 1000)}"
        target_path = self._cache_dir / f"{target_id}{suffix}"
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
        except Exception as exc:
            self._log("warning", "Could not copy TTS chunk for phone audio: %s", exc)
            return None
        meta = dict(data.get("source_meta") or {}) if isinstance(data.get("source_meta"), dict) else {}
        item = {
            "id": target_id,
            "_file_path": str(target_path),
            "url_path": f"/api/audio/file/{target_id}",
            "index": index,
            "sequence_index": self._int_value(data.get("sequence_index"), default=max(0, index - 1)),
            "text": str(data.get("text") or "").strip(),
            "emotion": str(data.get("emotion") or "").strip(),
            "speaker": str(meta.get("display_name") or meta.get("persona_id") or "Assistant").strip() or "Assistant",
            "duration_seconds": self._duration_seconds(data, target_path),
            "content_type": self._audio_content_type(target_path),
            "sample_rate": int(data.get("sample_rate") or 0),
            "tts_backend": str(data.get("tts_backend") or "").strip(),
            "created_at": float(data.get("created_at") or now),
        }
        dropped_items: list[dict[str, Any]] = []
        with self._lock:
            if generation != int(self._generation or 0):
                try:
                    target_path.unlink()
                except Exception:
                    pass
                return None
            next_items = [dict(existing) for existing in self._items]
            next_items.append(item)
            if len(next_items) > 64:
                dropped_items = next_items[:-64]
                next_items = next_items[-64:]
            self._items = next_items
            self._status = "ready"
        for dropped in dropped_items:
            self._unlink_cached_item(dropped)
        return {
            "captured": True,
            "skip_local_playback": skip_backend_playback,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            items = [
                {key: value for key, value in dict(item).items() if not str(key).startswith("_")}
                for item in list(self._items)
            ]
            status = str(self._status or "idle")
            capture_active = time.time() <= float(self._capture_until or 0.0)
            generation = int(self._generation or 0)
            backend_playback_suppressed = bool(
                self._suppress_backend_playback_generation == generation
                and time.time() <= float(self._suppress_backend_playback_until or 0.0)
            )
            source_excerpt = str(self._source_excerpt or "")
        if not items and not capture_active:
            status = "idle"
        return {
            "available": bool(items),
            "status": status,
            "generation": generation,
            "capture_active": bool(capture_active),
            "backend_playback_suppressed": bool(backend_playback_suppressed),
            "source_excerpt": source_excerpt,
            "items": items,
        }

    def audio_file_path(self, audio_id: str) -> Path:
        wanted = re.sub(r"[^A-Za-z0-9_.-]+", "", str(audio_id or ""))
        if not wanted:
            raise FileNotFoundError("audio id is required")
        with self._lock:
            for item in list(self._items):
                if str(item.get("id") or "") == wanted:
                    path = Path(str(item.get("_file_path") or ""))
                    if path.exists() and path.is_file():
                        return path
        raise FileNotFoundError("audio chunk not found")

    def cleanup(self) -> None:
        self.stop_capture()
        with self._lock:
            items = list(self._items)
            self._items = []
        for item in items:
            self._unlink_cached_item(item)

    def _begin_capture_locked(
        self,
        source_text: str,
        *,
        capture_seconds: float = DEFAULT_CAPTURE_SECONDS,
        now: float | None = None,
        suppress_backend_playback: bool = False,
        capture_phone_audio: bool = True,
    ) -> list[dict[str, Any]]:
        self._generation += 1
        old_items = list(self._items)
        self._items = []
        self._next_index = 1
        self._status = "rendering"
        self._capture_until = float(now if now is not None else time.time()) + max(5.0, float(capture_seconds or DEFAULT_CAPTURE_SECONDS))
        if suppress_backend_playback:
            self._suppress_backend_playback_generation = int(self._generation or 0)
            self._suppress_backend_playback_until = float(self._capture_until or 0.0)
        else:
            self._suppress_backend_playback_generation = 0
            self._suppress_backend_playback_until = 0.0
        self._phone_audio_capture_generation = int(self._generation or 0) if capture_phone_audio else 0
        self._source_excerpt = self._compact(source_text, 240)
        return old_items

    @classmethod
    def _auto_capture_excerpt(cls, payload: dict[str, Any]) -> str:
        text = str(payload.get("text") or "").strip()
        if text:
            return text
        meta = payload.get("source_meta")
        if isinstance(meta, dict):
            for key in ("display_name", "persona_id", "voice_id"):
                value = str(meta.get(key) or "").strip()
                if value:
                    return f"Runtime TTS from {value}"
        return "Runtime TTS"

    @staticmethod
    def _safe_audio_suffix(path: Path) -> str:
        suffix = str(path.suffix or "").strip().lower()
        return suffix if suffix in SUPPORTED_AUDIO_EXTENSIONS else ""

    @staticmethod
    def _audio_content_type(path: Path) -> str:
        guessed, _encoding = mimetypes.guess_type(str(path))
        return str(guessed or "application/octet-stream")

    @staticmethod
    def _wav_duration_seconds(path: Path) -> float:
        try:
            with wave.open(str(path), "rb") as handle:
                frames = int(handle.getnframes() or 0)
                rate = int(handle.getframerate() or 0)
            return round(frames / rate, 3) if rate > 0 else 0.0
        except Exception:
            return 0.0

    @classmethod
    def _duration_seconds(cls, payload: dict[str, Any], path: Path) -> float:
        try:
            value = float(payload.get("duration_seconds") or 0.0)
        except Exception:
            value = 0.0
        if value > 0.0:
            return round(value, 3)
        return cls._wav_duration_seconds(path)

    @staticmethod
    def _int_value(value: Any, *, default: int = 0) -> int:
        if value is None:
            return int(default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    @staticmethod
    def _unlink_cached_item(item: dict[str, Any]) -> None:
        path = Path(str(dict(item or {}).get("_file_path") or ""))
        if path.exists():
            try:
                path.unlink()
            except Exception:
                pass

    @staticmethod
    def _compact(text: str, limit: int) -> str:
        compact = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(compact) <= limit:
            return compact
        return compact[: max(0, limit - 3)].rstrip() + "..."

    def _log(self, level: str, message: str, *args) -> None:
        logger = self._logger
        if logger is None:
            return
        log_fn = getattr(logger, str(level or "info"), None)
        if callable(log_fn):
            try:
                log_fn("[MainChatRemote] " + message, *args)
            except Exception:
                pass
