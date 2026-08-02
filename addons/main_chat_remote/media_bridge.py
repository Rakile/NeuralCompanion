from __future__ import annotations

import mimetypes
import re
import shutil
import threading
import time
import wave
from pathlib import Path
from typing import Any

from addons.main_chat_remote.spectrum_analyzer import SPECTRUM_VERSION, SpectrumAnalyzer


DEFAULT_CAPTURE_SECONDS = 900.0
CAPTURE_CHUNK_IDLE_SECONDS = 45.0
MAX_PENDING_CAPTURE_POLICIES = 64
SUPPORTED_AUDIO_EXTENSIONS = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav", ".webm"}


class MainChatMediaBridge:
    """Copies runtime TTS chunks into an addon-local cache for phone playback."""

    def __init__(
        self,
        cache_dir: Path,
        logger=None,
        *,
        allow_auto_capture: bool = True,
        spectrum_analyzer=None,
    ):
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
        self._capture_id = ""
        self._capture_policies: dict[str, tuple[float, bool, bool]] = {}
        self._source_excerpt = ""
        self._next_index = 1
        self._allow_auto_capture = bool(allow_auto_capture)
        self._spectrum_analyzer = spectrum_analyzer or SpectrumAnalyzer(logger=logger)
        self._spectrum_shutdown = False

    def begin_tts_capture(
        self,
        source_text: str,
        *,
        capture_seconds: float = DEFAULT_CAPTURE_SECONDS,
        suppress_backend_playback: bool = False,
        capture_phone_audio: bool = True,
        capture_id: str = "",
    ) -> int:
        with self._lock:
            old_items = self._begin_capture_locked(
                source_text,
                capture_seconds=capture_seconds,
                now=time.time(),
                suppress_backend_playback=bool(suppress_backend_playback),
                capture_phone_audio=bool(capture_phone_audio),
                capture_id=str(capture_id or ""),
            )
            capture_generation = int(self._generation or 0)
        for item in old_items:
            self._unlink_cached_item(item)
        return capture_generation

    def stop_capture(self) -> None:
        with self._lock:
            self._capture_until = 0.0
            self._suppress_backend_playback_until = 0.0
            self._suppress_backend_playback_generation = 0
            self._phone_audio_capture_generation = 0
            self._capture_id = ""
            self._capture_policies.clear()
            if not self._items:
                self._status = "idle"

    def cancel_tts_capture(self, capture_id: str) -> None:
        wanted_capture_id = str(capture_id or "").strip()
        if not wanted_capture_id:
            return
        with self._lock:
            self._capture_policies.pop(wanted_capture_id, None)
            if wanted_capture_id != self._capture_id:
                return
            self._capture_until = 0.0
            self._suppress_backend_playback_until = 0.0
            self._suppress_backend_playback_generation = 0
            self._phone_audio_capture_generation = 0
            self._capture_id = ""
            if not self._items and not self._capture_policies:
                self._status = "idle"

    def cancel_current_tts_capture(self, capture_generation: int) -> bool:
        try:
            expected_generation = int(capture_generation)
        except (TypeError, ValueError):
            return False
        with self._lock:
            if expected_generation != int(self._generation or 0):
                return False
            current_capture_id = str(self._capture_id or "")
            if current_capture_id:
                self._capture_policies.pop(current_capture_id, None)
            self._capture_until = 0.0
            self._suppress_backend_playback_until = 0.0
            self._suppress_backend_playback_generation = 0
            self._phone_audio_capture_generation = 0
            self._capture_id = ""
            if not self._items and not self._capture_policies:
                self._status = "idle"
            return True

    def handle_tts_audio_chunk_ready(self, payload: dict[str, Any] | None = None):
        data = dict(payload or {})
        source_path = Path(str(data.get("audio_path") or ""))
        suffix = self._safe_audio_suffix(source_path)
        if not source_path.exists() or not source_path.is_file() or not suffix:
            return None
        now = time.time()
        meta = dict(data.get("source_meta") or {}) if isinstance(data.get("source_meta"), dict) else {}
        incoming_capture_id = str(meta.get("remote_capture_id") or "").strip()
        old_items: list[dict[str, Any]] = []
        with self._lock:
            self._prune_capture_policies_locked(now)
            capture_policy = self._capture_policies.get(incoming_capture_id)
            if now > float(self._capture_until or 0.0) and capture_policy is None:
                if not self._allow_auto_capture:
                    return {
                        "captured": False,
                        "skip_local_playback": False,
                    }
                old_items = self._begin_capture_locked(
                    self._auto_capture_excerpt(data),
                    capture_seconds=DEFAULT_CAPTURE_SECONDS,
                    now=now,
                    suppress_backend_playback=False,
                    capture_phone_audio=True,
                    capture_id="",
                )
            expected_capture_id = str(self._capture_id or "")
            if bool(meta.get("hidden_proactive", False)) or (
                incoming_capture_id
                and capture_policy is None
            ) or (
                expected_capture_id
                and not incoming_capture_id
            ):
                return {
                    "captured": False,
                    "skip_local_playback": False,
                }
            generation = int(self._generation or 0)
            if capture_policy is not None:
                _policy_until, skip_backend_playback, capture_phone_audio = capture_policy
            else:
                skip_backend_playback = bool(
                    self._suppress_backend_playback_generation == generation
                    and now <= float(self._suppress_backend_playback_until or 0.0)
                )
                capture_phone_audio = bool(self._phone_audio_capture_generation == generation)
            if capture_phone_audio:
                refreshed_until = now + CAPTURE_CHUNK_IDLE_SECONDS
                if capture_policy is not None:
                    self._capture_policies[incoming_capture_id] = (
                        refreshed_until,
                        bool(skip_backend_playback),
                        True,
                    )
                    if incoming_capture_id == expected_capture_id:
                        self._capture_until = refreshed_until
                        if self._suppress_backend_playback_generation == generation:
                            self._suppress_backend_playback_until = refreshed_until
                else:
                    self._capture_until = refreshed_until
                    if self._suppress_backend_playback_generation == generation:
                        self._suppress_backend_playback_until = float(self._capture_until)
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
            return {
                "captured": False,
                "skip_local_playback": skip_backend_playback,
            }
        item = {
            "id": target_id,
            "_file_path": str(target_path),
            "_spectrum_path": str(self._cache_dir / f"{target_id}.spectrum.json"),
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
            "spectrum_status": "pending",
            "spectrum_version": SPECTRUM_VERSION,
        }
        dropped_items: list[dict[str, Any]] = []
        with self._lock:
            current_generation = int(self._generation or 0)
            if generation != current_generation:
                capture_still_registered = bool(
                    incoming_capture_id
                    and incoming_capture_id in self._capture_policies
                )
                if not capture_still_registered:
                    try:
                        target_path.unlink()
                    except Exception:
                        pass
                    return {
                        "captured": False,
                        "skip_local_playback": skip_backend_playback,
                    }
                current_index = max(1, int(self._next_index or 1))
                self._next_index = current_index + 1
                item["index"] = current_index
            next_items = [dict(existing) for existing in self._items]
            next_items.append(item)
            if len(next_items) > 64:
                dropped_items = next_items[:-64]
                next_items = next_items[-64:]
            self._items = next_items
            self._status = "ready"
        for dropped in dropped_items:
            self._unlink_cached_item(dropped)
        self._schedule_spectrum_analysis(item)
        return {
            "captured": True,
            "skip_local_playback": skip_backend_playback,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            self._prune_capture_policies_locked(now)
            items = [
                {key: value for key, value in dict(item).items() if not str(key).startswith("_")}
                for item in list(self._items)
            ]
            status = str(self._status or "idle")
            capture_active = bool(
                now <= float(self._capture_until or 0.0)
                or self._capture_policies
            )
            generation = int(self._generation or 0)
            backend_playback_suppressed = bool(
                self._suppress_backend_playback_generation == generation
                and now <= float(self._suppress_backend_playback_until or 0.0)
            ) or any(
                suppress_backend_playback
                for _expires_at, suppress_backend_playback, _capture_phone_audio
                in self._capture_policies.values()
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

    def spectrum_file_path(self, audio_id: str) -> Path:
        raw_id = str(audio_id or "")
        wanted = re.sub(r"[^A-Za-z0-9_.-]+", "", raw_id)
        if not wanted or wanted != raw_id:
            raise FileNotFoundError("spectrum id is invalid")
        with self._lock:
            for item in list(self._items):
                if (
                    str(item.get("id") or "") == wanted
                    and str(item.get("spectrum_status") or "") == "ready"
                ):
                    path = Path(str(item.get("_spectrum_path") or ""))
                    if path.exists() and path.is_file():
                        return path
        raise FileNotFoundError("audio spectrum not found")

    def clear(self) -> None:
        self.stop_capture()
        with self._lock:
            items = list(self._items)
            self._items = []
        for item in items:
            self._unlink_cached_item(item)

    def cleanup(self) -> None:
        self.clear()
        if self._spectrum_shutdown:
            return
        self._spectrum_shutdown = True
        try:
            self._spectrum_analyzer.shutdown()
        except Exception:
            pass

    def _begin_capture_locked(
        self,
        source_text: str,
        *,
        capture_seconds: float = DEFAULT_CAPTURE_SECONDS,
        now: float | None = None,
        suppress_backend_playback: bool = False,
        capture_phone_audio: bool = True,
        capture_id: str = "",
    ) -> list[dict[str, Any]]:
        capture_started_at = float(now if now is not None else time.time())
        self._prune_capture_policies_locked(capture_started_at)
        retain_existing_items = bool(self._capture_policies)
        self._generation += 1
        old_items = [] if retain_existing_items else list(self._items)
        if not retain_existing_items:
            self._items = []
            self._next_index = 1
        self._status = "rendering"
        self._capture_until = capture_started_at + max(5.0, float(capture_seconds or DEFAULT_CAPTURE_SECONDS))
        if suppress_backend_playback:
            self._suppress_backend_playback_generation = int(self._generation or 0)
            self._suppress_backend_playback_until = float(self._capture_until or 0.0)
        else:
            self._suppress_backend_playback_generation = 0
            self._suppress_backend_playback_until = 0.0
        self._phone_audio_capture_generation = int(self._generation or 0) if capture_phone_audio else 0
        self._capture_id = str(capture_id or "").strip()
        if self._capture_id:
            self._capture_policies.pop(self._capture_id, None)
            self._capture_policies[self._capture_id] = (
                float(self._capture_until),
                bool(suppress_backend_playback),
                bool(capture_phone_audio),
            )
            while len(self._capture_policies) > MAX_PENDING_CAPTURE_POLICIES:
                oldest_capture_id = next(iter(self._capture_policies))
                self._capture_policies.pop(oldest_capture_id, None)
        self._source_excerpt = self._compact(source_text, 240)
        return old_items

    def _prune_capture_policies_locked(self, now: float) -> None:
        expired_capture_ids = [
            capture_id
            for capture_id, (expires_at, _suppress_backend_playback, _capture_phone_audio)
            in self._capture_policies.items()
            if float(expires_at) < float(now)
        ]
        for capture_id in expired_capture_ids:
            self._capture_policies.pop(capture_id, None)

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

    def _schedule_spectrum_analysis(self, item: dict[str, Any]) -> None:
        audio_id = str(item.get("id") or "")
        audio_path = Path(str(item.get("_file_path") or ""))
        spectrum_path = Path(str(item.get("_spectrum_path") or ""))
        try:
            accepted = bool(
                self._spectrum_analyzer.submit(
                    audio_id,
                    audio_path,
                    spectrum_path,
                    self._spectrum_analysis_finished,
                )
            )
        except Exception:
            accepted = False
        if accepted:
            return
        with self._lock:
            for existing in self._items:
                if str(existing.get("id") or "") == audio_id:
                    existing["spectrum_status"] = "unavailable"
                    existing.pop("spectrum_url_path", None)
                    break

    def _spectrum_analysis_finished(
        self,
        audio_id: str,
        payload: dict[str, Any] | None,
        error: str,
    ) -> None:
        with self._lock:
            for item in self._items:
                if str(item.get("id") or "") != str(audio_id or ""):
                    continue
                spectrum_path = Path(str(item.get("_spectrum_path") or ""))
                ready = (
                    not str(error or "")
                    and isinstance(payload, dict)
                    and int(payload.get("version") or 0) == SPECTRUM_VERSION
                    and spectrum_path.is_file()
                )
                item["spectrum_status"] = "ready" if ready else "unavailable"
                item["spectrum_version"] = SPECTRUM_VERSION
                if ready:
                    item["spectrum_url_path"] = f"/api/audio/spectrum/{audio_id}"
                else:
                    item.pop("spectrum_url_path", None)
                break

    def _unlink_cached_item(self, item: dict[str, Any]) -> None:
        data = dict(item or {})
        audio_id = str(data.get("id") or "")
        try:
            self._spectrum_analyzer.cancel(audio_id)
        except Exception:
            pass
        for key in ("_file_path", "_spectrum_path"):
            path = Path(str(data.get(key) or ""))
            if path.exists():
                try:
                    path.unlink()
                except Exception:
                    pass
        spectrum_path = Path(str(data.get("_spectrum_path") or ""))
        temporary_path = spectrum_path.with_suffix(spectrum_path.suffix + ".tmp")
        if temporary_path.exists():
            try:
                temporary_path.unlink()
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
