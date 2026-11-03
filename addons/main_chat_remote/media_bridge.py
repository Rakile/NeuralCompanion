from __future__ import annotations

import mimetypes
import hashlib
from dataclasses import dataclass, field
import re
import shutil
import threading
import time
import wave
import uuid
from pathlib import Path
from typing import Any

from addons.main_chat_remote.spectrum_analyzer import SPECTRUM_VERSION, SpectrumAnalyzer
from addons.main_chat_remote.phone_reply_receipts import PhoneReplyRejected
from addons.main_chat_remote.phone_reply_continuation import ReplyMediaRetention
from addons.main_chat_remote.progressive_audio import ProgressivePhoneAudioStore


DEFAULT_CAPTURE_SECONDS = 900.0
CAPTURE_CHUNK_IDLE_SECONDS = 45.0
MAX_PENDING_CAPTURE_POLICIES = 64
SUPPORTED_AUDIO_EXTENSIONS = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav", ".webm"}


@dataclass(repr=False)
class _PhonePublication:
    registry: Any
    inflight: int = 0
    next_sequence: int = 0
    producer_finished: bool = False
    suppressed: bool = False
    cancelled: bool = False
    settled_at: float | None = None
    seen: dict = field(default_factory=dict)
    staged: dict = field(default_factory=dict)
    text_bytes: int = 0
    progressive: bool = False


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
        self._error = ""
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
        self._phone_replies: dict[str, _PhonePublication] = {}
        self._phone_text_bytes = 0
        self._reply_retention = ReplyMediaRetention(time.monotonic)
        self._progressive_audio = ProgressivePhoneAudioStore()

    def register_phone_reply(self, request_id: str, registry, *, continuation: bool = False,
                             progressive: bool = False) -> None:
        with self._lock:
            now = time.monotonic()
            for key, state in tuple(self._phone_replies.items()):
                if state.settled_at is not None and now - state.settled_at >= 900 and not self._reply_retention.owns(key):
                    self._phone_text_bytes -= state.text_bytes
                    del self._phone_replies[key]
            if request_id in self._phone_replies:
                return
            if len(self._phone_replies) >= 256:
                raise PhoneReplyRejected("capacity")
            self._phone_replies[request_id] = _PhonePublication(registry, progressive=progressive)
            if continuation:
                self._reply_retention.reserve(request_id)

    def _drain_retention_locked(self) -> None:
        visible_ids = {item["id"] for item in self._items}
        for item in self._reply_retention.drain_released():
            if item["id"] not in visible_ids:
                self._unlink_cached_item(item)

    def release_reply_continuation(self, request_id: str) -> None:
        with self._lock:
            self._progressive_audio.release_reply(request_id)
            self._reply_retention.release(request_id)
            self._drain_retention_locked()

    def maintain_reply_continuations(self) -> tuple[str, ...]:
        with self._lock:
            expired = self._reply_retention.maintain()
            for request_id in expired:
                self._progressive_audio.release_reply(request_id)
            self._drain_retention_locked()
            return expired

    @property
    def continuation_maintenance_needed(self) -> bool:
        return self._reply_retention.maintenance_needed

    def reply_continuation(self, request_id: str, cursor: int, completed_sequence: int) -> dict:
        # Only called after original capability/owner validation by the protocol.
        with self._lock:
            self._reply_retention.progress(request_id, completed_sequence)
            if completed_sequence >= 0:
                self._progressive_audio.release_reply(request_id, completed_sequence)
            page = self._reply_retention.page(request_id, cursor)
            self._drain_retention_locked()
            return page

    def suppress_phone_reply(self, request_id: str) -> None:
        with self._lock:
            state = self._phone_replies.get(request_id)
            if state is not None:
                state.suppressed = True
                self._settle_phone_locked(request_id, state)

    def finish_phone_reply(self, request_id: str, *, cancelled: bool = False) -> None:
        with self._lock:
            state = self._phone_replies.get(request_id)
            if state is not None:
                state.producer_finished = True
                if cancelled:
                    state.cancelled = state.suppressed = True
                    # Replacement must also invalidate an already completed tail.
                    state.registry.cancel(request_id)
                self._settle_phone_locked(request_id, state)

    def _settle_phone_locked(self, request_id: str, state: _PhonePublication) -> None:
        if state.suppressed:
            self.release_reply_continuation(request_id)
            for item in state.staged.values():
                self._unlink_cached_item(item)
            state.staged.clear()
        if not state.producer_finished or state.inflight or state.settled_at is not None:
            return
        if state.staged:  # Producer closed with a missing authoritative index.
            state.cancelled = state.suppressed = True
            for item in state.staged.values():
                self._unlink_cached_item(item)
            state.staged.clear()
        if state.cancelled:
            state.registry.cancel(request_id)
        else:
            state.registry.complete(request_id, state.next_sequence - 1 if state.next_sequence else None)
        state.settled_at = time.monotonic()

    def _handle_phone_chunk(self, request_id: str, data: dict, source: Path, meta: dict):
        rejected = {"captured": False, "skip_local_playback": True}
        sequence = data.get("sequence_index")
        text = data.get("text") or ""
        suffix = self._safe_audio_suffix(source)
        with self._lock:
            state = self._phone_replies.get(request_id)
            if state is None or state.suppressed or state.producer_finished:
                return rejected
            if type(sequence) is not int or sequence < 0 or sequence >= 2048 or type(text) is not str:
                state.cancelled = state.suppressed = state.producer_finished = True
                self._settle_phone_locked(request_id, state)
                return rejected
            fingerprint = (str(source), hashlib.sha256(text.encode("utf-8")).digest())
            previous = state.seen.get(sequence)
            if previous is not None:
                if previous != fingerprint:
                    state.cancelled = state.suppressed = state.producer_finished = True
                    self._settle_phone_locked(request_id, state)
                return rejected
            size = len(text.encode("utf-8"))
            if state.text_bytes + size > 1024 * 1024 or self._phone_text_bytes + size > 8 * 1024 * 1024:
                state.cancelled = state.suppressed = state.producer_finished = True
                self._settle_phone_locked(request_id, state)
                return rejected
            state.seen[sequence] = fingerprint
            state.text_bytes += size
            self._phone_text_bytes += size
            state.inflight += 1
        target_id = "p" + hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:32] + f"_{sequence:04d}"
        target_path = self._cache_dir / f"{target_id}{suffix}"
        item = None
        published = []
        dropped = []
        try:
            if not suffix or not source.is_file():
                raise OSError("audio unavailable")
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target_path)
            item = {
                "id": target_id, "_file_path": str(target_path),
                # Same prepared audio basename passed by the core AvatarService
                # to MuseTalk. Private linkage, never an untrusted phone path.
                "_render_chunk_id": source.stem,
                "_spectrum_path": str(self._cache_dir / f"{target_id}.spectrum.json"),
                "url_path": f"/api/audio/file/{target_id}", "phone_request_id": request_id,
                "sequence_index": sequence, "text": text.strip(),
                "emotion": str(data.get("emotion") or ""),
                "speaker": str(meta.get("display_name") or meta.get("persona_id") or "Assistant"),
                "duration_seconds": self._duration_seconds(data, target_path),
                "content_type": self._audio_content_type(target_path),
                "sample_rate": int(data.get("sample_rate") or 0),
                "tts_backend": str(data.get("tts_backend") or ""),
                "created_at": float(data.get("created_at") or time.time()),
                "spectrum_status": "pending", "spectrum_version": SPECTRUM_VERSION,
            }
            if data.get("progressive_audio_source") is not None:
                item["progressive_audio"] = dict(version=1, sample_rate=24000, channels=1)
                # A prefix duration is not the duration of its logical utterance.
                item["duration_seconds"] = max(1.0, len(text) / 14.0)
                item["spectrum_status"] = "pending"
            with self._lock:
                if state.suppressed:
                    self._unlink_cached_item(item)
                else:
                    state.staged[sequence] = item
                    while state.next_sequence in state.staged:
                        ready = state.staged[state.next_sequence]
                        state.registry.add_chunk(request_id, ready["id"], state.next_sequence, ready["text"])
                        del state.staged[state.next_sequence]
                        state.next_sequence += 1
                        ready["index"] = self._next_index
                        self._next_index += 1
                        self._items.append(ready)
                        self._reply_retention.publish(request_id, ready, Path(ready["_file_path"]).stat().st_size)
                        published.append(ready)
                    if len(self._items) > 64:
                        dropped = self._items[:-64]
                        self._items = self._items[-64:]
                    self._status = "ready" if self._items else "rendering"
                    self._drain_retention_locked()
        except Exception:
            with self._lock:
                state.cancelled = state.suppressed = state.producer_finished = True
                self._status = "error"
                self._error = "Phone audio could not be prepared. Try the reply again."
            if item is not None:
                self._unlink_cached_item(item)
            else:
                try:
                    target_path.unlink(missing_ok=True)
                except OSError:
                    pass
        finally:
            with self._lock:
                state.inflight -= 1
                self._settle_phone_locked(request_id, state)
        for old in dropped:
            self._unlink_cached_item(old)
        for ready in published:
            if "progressive_audio" not in ready:
                self._schedule_spectrum_analysis(ready)
        return {"captured": bool(published), "skip_local_playback": True}

    def progressive_requested(self, request_id: str) -> bool:
        with self._lock:
            state = self._phone_replies.get(request_id)
            return bool(state and state.progressive and not state.suppressed and not state.producer_finished)

    def progressive_audio_read(self, request_id, audio_id, sequence, cursor):
        # Called only after the original phone reply's owner/status validation.
        with self._lock:
            state = self._phone_replies.get(request_id)
            if not state or state.suppressed or not state.progressive:
                raise ValueError('Progressive audio unavailable')
            return self._progressive_audio.read(request_id, audio_id, sequence, cursor)

    def _handle_progressive_audio(self, data):
        rejected = dict(captured=False, skip_local_playback=True, progressive_audio_admitted=False)
        meta = data.get('source_meta')
        if not isinstance(meta, dict) or meta.get('phone_reply_control') is not True:
            return rejected
        request_id = meta.get('remote_capture_id')
        sequence = data.get('sequence_index')
        if (type(request_id) is not str or type(sequence) is not int or not 0 <= sequence < 2048
                or data.get('tts_backend') != 'liquidai'):
            return rejected
        audio_id = 'p'+hashlib.sha256(request_id.encode('utf-8')).hexdigest()[:32]+f'_{sequence:04d}'
        source = data.get('progressive_audio_source')
        if source is not None:
            with self._lock:
                if not self.progressive_requested(request_id):
                    return rejected
                if not self._progressive_audio.admit(request_id, audio_id, sequence, source):
                    return rejected
            result = self._handle_phone_chunk(request_id, data, Path(str(data.get('audio_path') or '')), meta)
            with self._lock:
                state = self._phone_replies.get(request_id)
                admitted = bool(state and not state.suppressed and sequence in state.seen)
                if not admitted:
                    self._progressive_audio.release_reply(request_id)
            return {**result, 'progressive_audio_admitted': admitted}

        source = data.get('progressive_finalize_source')
        if not self._progressive_audio.matches(request_id, audio_id, sequence, source):
            return rejected
        complete = Path(str(data.get('audio_path') or ''))
        # Only the exact PCM successfully generated for this published chunk may
        # replace its prefix. No public endpoint accepts source files or paths.
        try:
            with wave.open(str(complete), 'rb') as wav:
                if (wav.getframerate() != 24000 or wav.getnchannels() != 1 or wav.getsampwidth() != 2
                        or wav.getnframes() != source.frame_count or not source.succeeded):
                    return rejected
            target = self._cache_dir / (audio_id+'.wav')
            temporary = target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
            try:
                shutil.copyfile(complete, temporary)
                with self._lock:
                    state = self._phone_replies.get(request_id)
                    if not state or state.suppressed or source.cancelled:
                        return rejected
                    candidates = [*self._items, *state.staged.values()]
                    pinned = self._reply_retention.find_item(audio_id)
                    item = next((item for item in candidates if item['id'] == audio_id), pinned)
                    if item is None or 'progressive_audio' not in item:
                        return rejected
                    promoted = dict(item)
                    promoted.pop('progressive_audio')
                    promoted['duration_seconds'] = source.frame_count/24000
                    # Readers hold this same bridge lock. Publish the actual file
                    # before removing the prefix marker from retained metadata.
                    temporary.replace(target)
                    if pinned is not None and not self._reply_retention.replace_item(
                            request_id, promoted, target.stat().st_size):
                        return rejected
                    item.update(promoted)
                    item.pop('progressive_audio', None)
                    self._progressive_audio.finalize(request_id, audio_id, sequence, source)
                self._schedule_spectrum_analysis(promoted)
                return dict(captured=True, skip_local_playback=True, progressive_audio_admitted=True)
            finally:
                temporary.unlink(missing_ok=True)
        except (OSError, ValueError, wave.Error):
            source.fail(ValueError('Progressive recording could not be finalized'))
            return rejected

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
            self._reply_retention.release_all()
            self._drain_retention_locked()
            for request_id in tuple(self._phone_replies):
                self.finish_phone_reply(request_id, cancelled=True)
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
        if data.get("progressive_audio_source") is not None or data.get("progressive_finalize_source") is not None:
            return self._handle_progressive_audio(data)
        source_path = Path(str(data.get("audio_path") or ""))
        meta = data.get("source_meta") if isinstance(data.get("source_meta"), dict) else {}
        incoming_capture_id = str(meta.get("remote_capture_id") or "").strip()
        if incoming_capture_id and (meta.get("phone_reply_control") is True or incoming_capture_id in self._phone_replies):
            return self._handle_phone_chunk(incoming_capture_id, data, source_path, meta)
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
            self._log("warning", "Could not copy TTS chunk for phone audio (%s)", type(exc).__name__)
            with self._lock:
                capture_still_owned = (
                    incoming_capture_id in self._capture_policies
                    if incoming_capture_id
                    else generation == self._generation and self._capture_until > 0.0
                )
                if capture_still_owned:
                    self._status = "error"
                    self._error = "Phone audio could not be prepared. Try the reply again."
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
        if incoming_capture_id:
            item["phone_request_id"] = incoming_capture_id
        dropped_items: list[dict[str, Any]] = []
        with self._lock:
            current_generation = int(self._generation or 0)
            capture_still_registered = bool(
                incoming_capture_id
                and incoming_capture_id in self._capture_policies
            )
            if (incoming_capture_id or generation != current_generation) and not capture_still_registered:
                try:
                    target_path.unlink()
                except Exception:
                    pass
                return {
                    "captured": False,
                    "skip_local_playback": skip_backend_playback,
                }
            if generation != current_generation:
                current_index = max(1, int(self._next_index or 1))
                self._next_index = current_index + 1
                item["index"] = current_index
            next_items = [dict(existing) for existing in self._items]
            next_items.append(item)
            if len(next_items) > 64:
                dropped_items = next_items[:-64]
                next_items = next_items[-64:]
            self._items = next_items
            self._status = "error" if self._error else "ready"
        for dropped in dropped_items:
            self._unlink_cached_item(dropped)
        self._schedule_spectrum_analysis(item)
        return {
            "captured": True,
            "skip_local_playback": skip_backend_playback,
        }

    def ordered_speech_source(self, request_id: str, sequence: int) -> dict | None:
        """Private lookup after the ordering port authenticates the reply owner.

        Retain the existing copied audio. Never search short-lived staged WAVs,
        infer identity from text, or expose the private path in public snapshots.
        """
        if (type(request_id) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', request_id)
                or type(sequence) is not int or not 0 <= sequence <= 63):
            raise ValueError('ordered_speech_identity')
        audio_id = 'p' + hashlib.sha256(request_id.encode()).hexdigest()[:32] + f'_{sequence:04d}'
        with self._lock:
            state = self._phone_replies.get(request_id)
            if state is None or state.suppressed or state.cancelled:
                raise ValueError('ordered_speech_reply_unavailable')
            item = self._reply_retention.find_item(audio_id)
            if item is None:
                item = next((row for row in self._items if row['id'] == audio_id), None)
            if item is None:
                if sequence < state.next_sequence:
                    raise ValueError('ordered_speech_audio_retired')
                return None
            chunk = item.get('_render_chunk_id')
            if (item.get('phone_request_id') != request_id or item.get('sequence_index') != sequence
                    or type(chunk) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', chunk)):
                raise ValueError('ordered_speech_identity')
            return dict(chunkId=chunk, wav=item['_file_path'], audioId=audio_id)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            self._prune_capture_policies_locked(now)
            items = [
                {key: value for key, value in dict(item).items() if not str(key).startswith("_")}
                for item in list(self._items)
            ]
            status = "error" if self._error else str(self._status or "idle")
            error = self._error
            capture_active = bool(
                now <= float(self._capture_until or 0.0)
                or self._capture_policies
                or any(state.settled_at is None for state in self._phone_replies.values())
            )
            generation = int(self._generation or 0)
            backend_playback_suppressed = bool(
                self._suppress_backend_playback_generation == generation
                and now <= float(self._suppress_backend_playback_until or 0.0)
            ) or any(
                suppress_backend_playback
                for _expires_at, suppress_backend_playback, _capture_phone_audio
                in self._capture_policies.values()
            ) or any(state.settled_at is None for state in self._phone_replies.values())
            source_excerpt = str(self._source_excerpt or "")
        if not items and not capture_active and not error:
            status = "idle"
        return {
            "available": bool(items),
            "status": status,
            "error": error,
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
            pinned = self._reply_retention.find_item(wanted)
            for item in list(self._items) + ([pinned] if pinned else []):
                if str(item.get("id") or "") == wanted:
                    if "progressive_audio" in item:
                        raise FileNotFoundError("Audio is still generating; Replay is available when it finishes")
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
            self._progressive_audio.close()
            items = list(self._items)
            self._items = []
            self._error = ""
            self._status = "idle"
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
        self._error = ""
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
        if self._reply_retention.find_item(audio_id) is not None:
            return
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
