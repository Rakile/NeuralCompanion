"""Speech-to-text runtime helpers and addon-backed STT services."""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
import re
import threading
import time
import uuid

from core import runtime_paths

WHISPER_LANGUAGE_OPTIONS = (
    ("Auto Detect", ""),
    ("English", "en"),
    ("Swedish", "sv"),
    ("German", "de"),
    ("French", "fr"),
    ("Spanish", "es"),
    ("Italian", "it"),
    ("Portuguese", "pt"),
    ("Japanese", "ja"),
    ("Korean", "ko"),
    ("Chinese", "zh"),
    ("Russian", "ru"),
    ("Arabic", "ar"),
    ("Hindi", "hi"),
    ("Turkish", "tr"),
)

WHISPER_MODEL_SIZE_OPTIONS = ("tiny.en", "tiny", "base", "small", "medium", "large-v3")


def normalize_whisper_language(value):
    text = str(value or "").strip().lower()
    if text in {"", "auto", "detect", "auto detect", "automatic"}:
        return None
    for label, code in WHISPER_LANGUAGE_OPTIONS:
        if text in {str(label).strip().lower(), str(code).strip().lower()}:
            return str(code or "").strip() or None
    return text or None


def effective_whisper_model_size(model_size, *, language=None, backend=None):
    model = str(model_size or "tiny.en").strip() or "tiny.en"
    backend_id = str(backend or "").strip().lower()
    if backend_id == "whisper_multilingual" and model.endswith(".en"):
        return model[:-3] or "tiny"
    lang = normalize_whisper_language(language)
    if lang and lang != "en" and model.endswith(".en"):
        return model[:-3] or "tiny"
    return model


def effective_whisper_language(language, *, backend=None):
    backend_id = str(backend or "").strip().lower()
    if backend_id == "whisper_english":
        return "en"
    return normalize_whisper_language(language)


@dataclass
class STTRuntimeState:
    ok: bool
    model: object | None
    backend_name: str | None


def list_available_stt_backends(manager_getter, *, logger=print):
    backends = []
    seen = set()
    manager = manager_getter()
    if manager is not None:
        try:
            entries = list(manager.list_registered_services() or [])
        except Exception as exc:
            logger(f"⚠️ [Addons] Failed to enumerate STT backends: {exc}")
            entries = []
        for entry in entries:
            metadata = dict(entry.get("metadata") or {})
            kind = str(metadata.get("kind", "") or "").strip().lower()
            if kind not in {"stt", "stt_backend", "speech_to_text"}:
                continue
            backend_id = str(metadata.get("backend_id") or entry.get("name") or "").strip().lower()
            if not backend_id or backend_id in seen:
                continue
            label = str(metadata.get("label") or entry.get("name") or backend_id).strip()
            backends.append(
                {
                    "id": backend_id,
                    "label": label,
                    "kind": "addon",
                    "service_name": str(entry.get("name") or backend_id).strip(),
                    "metadata": metadata,
                }
            )
            seen.add(backend_id)
    return backends


def resolve_addon_stt_backend(backend_id: str, manager_getter):
    target = str(backend_id or "").strip().lower()
    if not target:
        return None
    manager = manager_getter()
    if manager is None:
        return None
    try:
        entries = list(manager.list_registered_services() or [])
    except Exception:
        return None
    for entry in entries:
        metadata = dict(entry.get("metadata") or {})
        kind = str(metadata.get("kind", "") or "").strip().lower()
        if kind not in {"stt", "stt_backend", "speech_to_text"}:
            continue
        service_name = str(entry.get("name") or "").strip()
        candidate_id = str(metadata.get("backend_id") or service_name).strip().lower()
        candidate_label = str(metadata.get("label") or service_name or candidate_id).strip().lower()
        if target not in {candidate_id, candidate_label, service_name.lower()}:
            continue
        service = manager.get_registered_service(service_name)
        if service is None:
            continue
        return {
            "id": candidate_id or target,
            "label": str(metadata.get("label") or service_name or candidate_id or target).strip(),
            "service_name": service_name,
            "service": service,
            "metadata": metadata,
        }
    return None


def initialize_stt_backend(
    *,
    runtime_config,
    current_model,
    current_backend_name,
    addon_resolver,
    addon_adapter_cls,
    logger=print,
):
    desired_backend = str(runtime_config.get("stt_backend", "none") or "none").lower().strip()

    if current_model is not None and current_backend_name == desired_backend:
        logger(f"✓ {desired_backend} STT backend already loaded (Skipping reload)")
        return STTRuntimeState(True, current_model, current_backend_name)

    if current_model is not None and hasattr(current_model, "close"):
        try:
            current_model.close()
        except Exception:
            pass

    resolved = addon_resolver(desired_backend) if desired_backend else None
    if resolved is None:
        logger(f"⚠️ STT backend '{desired_backend}' is unavailable; microphone transcription is disabled.")
        return STTRuntimeState(False, None, None)

    logger(f"Loading addon STT backend '{resolved['label']}' ({resolved['service_name']})...")
    try:
        model = addon_adapter_cls(
            backend_id=resolved["id"],
            label=resolved["label"],
            service=resolved["service"],
        )
        warmer = getattr(model, "warm_up", None)
        if callable(warmer):
            warmer()
        logger(f"✓ Addon STT backend loaded successfully: {resolved['label']}")
        return STTRuntimeState(True, model, resolved["id"])
    except Exception as exc:
        logger(f"✗ Failed to load addon STT backend '{resolved['label']}': {exc}")
        return STTRuntimeState(False, None, None)


def whisper_runtime_config(runtime_config, *, cuda_available: bool, vram_mode: str = "quality"):
    vram_mode = str(vram_mode or "quality").strip().lower()
    if not cuda_available:
        return "cpu", "int8"
    # Keep the current runtime behavior: main Whisper prefers CUDA whenever available.
    return "cuda", "float16"


def whisper_runtime_reason(runtime_config, *, cuda_available: bool, vram_mode: str = "quality"):
    vram_mode = str(vram_mode or "quality").strip().lower()
    if not cuda_available:
        return "CUDA unavailable"
    return "main STT Whisper uses CUDA when available"


def _segments_to_text(result):
    if result is None:
        return None
    if isinstance(result, str):
        text = result.strip()
        return text or None
    if isinstance(result, dict):
        for key in ("text", "transcript", "content"):
            text = str(result.get(key) or "").strip()
            if text:
                return text
        return None
    if isinstance(result, tuple) and result:
        return _segments_to_text(result[0])
    try:
        text = " ".join((segment.text or "").strip() for segment in result).strip()
        return text or None
    except Exception:
        return None


class AddonSTTBackendAdapter:
    def __init__(self, backend_id: str, label: str, service):
        self.backend_id = str(backend_id or "").strip().lower()
        self.label = str(label or backend_id or "AddonSTT").strip()
        self.service = service

    def _callable(self, names):
        for name in names:
            candidate = getattr(self.service, name, None)
            if callable(candidate):
                return candidate
        return None

    def transcribe(self, audio, **kwargs):
        fn = self._callable(("transcribe", "recognize", "stt"))
        if fn is None:
            raise RuntimeError(f"Addon STT backend '{self.backend_id}' does not expose transcribe(audio)")
        try:
            return _segments_to_text(fn(audio, **dict(kwargs or {})))
        except TypeError:
            return _segments_to_text(fn(audio))

    def transcribe_file(self, path, **kwargs):
        fn = self._callable(("transcribe_file", "transcribe_path", "recognize_file"))
        if fn is not None:
            try:
                return _segments_to_text(fn(str(path), **dict(kwargs or {})))
            except TypeError:
                return _segments_to_text(fn(str(path)))
        fn = self._callable(("transcribe", "recognize", "stt"))
        if fn is None:
            raise RuntimeError(f"Addon STT backend '{self.backend_id}' does not expose file transcription")
        try:
            return _segments_to_text(fn(str(path), **dict(kwargs or {})))
        except TypeError:
            return _segments_to_text(fn(str(path)))

    def transcribe_file_raw(self, path, **kwargs):
        fn = self._callable(("transcribe_file_raw", "transcribe_file_segments", "transcribe_segments"))
        if fn is not None:
            try:
                return fn(str(path), **dict(kwargs or {}))
            except TypeError:
                return fn(str(path))
        text = self.transcribe_file(path, **kwargs)
        return (), {"text": text or ""}

    def warm_up(self):
        warmer = getattr(self.service, "warm_up", None)
        if callable(warmer):
            return warmer()
        return False

    def close(self):
        closer = getattr(self.service, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                pass


class NoSTTService:
    def transcribe(self, _audio, **_kwargs):
        return None

    def transcribe_file(self, _path, **_kwargs):
        return None

    def transcribe_file_raw(self, _path, **_kwargs):
        return (), None

    def warm_up(self):
        return True

    def close(self):
        return None


class LocalWhisperSTTService:
    def __init__(
        self,
        context,
        *,
        backend_id: str,
        default_model_size: str,
        default_language=None,
        force_language=None,
    ):
        self._context = context
        self.backend_id = str(backend_id or "").strip().lower()
        self.default_model_size = str(default_model_size or "tiny.en").strip() or "tiny.en"
        self.default_language = default_language
        self.force_language = force_language
        self._lock = threading.RLock()
        self._model = None
        self._model_signature = None

    def _runtime_config_service(self):
        return self._context.get_service("qt.runtime_config") if self._context is not None else None

    def _runtime_config(self):
        service = self._runtime_config_service()
        if service is not None and hasattr(service, "snapshot"):
            return service.snapshot()
        return {}

    def _engine_attr(self, name: str, default=None):
        service = self._runtime_config_service()
        if service is not None and hasattr(service, "engine_attr"):
            return service.engine_attr(name, default)
        return default

    def _safe_delete(self, path):
        deleter = self._engine_attr("safe_delete_with_retry", None)
        if callable(deleter):
            return deleter(path)
        try:
            os.unlink(path)
        except Exception:
            pass
        return None

    def _runtime_language(self, language=None):
        if self.force_language:
            return str(self.force_language)
        value = language
        if value is None:
            value = self._runtime_config().get("stt_language", self.default_language)
        return effective_whisper_language(value, backend=self.backend_id)

    def _runtime_model_size(self, language=None):
        configured = self._runtime_config().get("stt_model_size", self.default_model_size)
        return effective_whisper_model_size(configured, language=self._runtime_language(language), backend=self.backend_id)

    def _cuda_available(self):
        try:
            import torch

            return bool(torch.cuda.is_available())
        except Exception:
            return False

    def _ensure_model(self, language=None):
        with self._lock:
            runtime_config = self._runtime_config()
            cuda_available = self._cuda_available()
            device, compute_type = whisper_runtime_config(runtime_config, cuda_available=cuda_available)
            model_size = self._runtime_model_size(language)
            signature = (model_size, device, compute_type)
            if self._model is not None and self._model_signature == signature:
                return self._model
            if self._model is not None:
                self.close()
            from faster_whisper import WhisperModel

            reason = whisper_runtime_reason(runtime_config, cuda_available=cuda_available)
            language = self._runtime_language(language)
            language_label = language or "auto"
            print(
                f"Loading STT backend {self.backend_id}: Whisper ({model_size}) on {device} "
                f"[language={language_label}, compute_type={compute_type}, reason={reason}]..."
            )
            self._model = WhisperModel(model_size, device=device, compute_type=compute_type)
            self._model_signature = signature
            print(f"✓ STT backend {self.backend_id} loaded Whisper {model_size} on {device} ({compute_type}, language={language_label})")
            return self._model

    def _transcribe_path(self, path, language=None):
        model = self._ensure_model(language)
        segments, _info = model.transcribe(str(path), language=self._runtime_language(language))
        return _segments_to_text(segments)

    def transcribe_file_raw(self, path, language=None, **_kwargs):
        model = self._ensure_model(language)
        return model.transcribe(str(path), language=self._runtime_language(language))

    def transcribe(self, audio, language=None, **_kwargs):
        if isinstance(audio, str):
            return self.transcribe_file(audio, language=language)
        temp_path = None
        try:
            temp_path = str(runtime_paths.runtime_temp_file(f"whisper_{uuid.uuid4().hex}.wav", "stt"))
            with open(temp_path, "wb") as tmp:
                tmp.write(audio.get_wav_data())
            return self._transcribe_path(temp_path, language=language)
        finally:
            if temp_path:
                self._safe_delete(temp_path)

    def transcribe_file(self, path, language=None, **_kwargs):
        return self._transcribe_path(path, language=language)

    def warm_up(self):
        self._ensure_model()
        return True

    def close(self):
        with self._lock:
            model = self._model
            self._model = None
            self._model_signature = None
        if model is not None:
            closer = getattr(model, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:
                    pass


def listen_for_speech(
    source,
    *,
    recognizer,
    microphone_active,
    transcribe_func,
    sr_module,
    settings,
    np_module=None,
    timeout=None,
    logger=print,
):
    recognizer.energy_threshold = settings["energy_threshold"]
    recognizer.dynamic_energy_threshold = settings["dynamic_energy_threshold"]
    recognizer.pause_threshold = settings["pause_threshold"]
    recognizer.non_speaking_duration = settings["non_speaking_duration"]
    recognizer.phrase_threshold = settings["phrase_threshold"]
    try:
        microphone_active.set()
        audio = recognizer.listen(source, timeout=timeout)
        if np_module is not None:
            _audio_data = np_module.frombuffer(audio.get_raw_data(), dtype=np_module.int16).astype(np_module.float32) / 32768.0
        text = transcribe_func(audio)
        if text and re.search(r"[a-zA-Z0-9]", text):
            return text
        return None
    except sr_module.WaitTimeoutError:
        return None
    except sr_module.UnknownValueError:
        return None
    except Exception as exc:
        logger(f"✗ Mic error: {exc}")
        return None
    finally:
        microphone_active.clear()


def listen_for_speech_push_to_talk(
    source,
    *,
    recognizer,
    microphone_active,
    transcribe_func,
    sr_module,
    is_push_to_talk_held,
    audio_data_factory,
    chunk_size=1024,
    max_seconds=300.0,
    tail_seconds=0.55,
    min_tail_chunks=8,
    trailing_chunks=None,
    logger=print,
):
    sample_rate = getattr(source, "SAMPLE_RATE", 16000)
    sample_width = getattr(source, "SAMPLE_WIDTH", 2)
    if trailing_chunks is None:
        chunk_seconds = float(chunk_size) / max(float(sample_rate), 1.0)
        trailing_chunks = max(min_tail_chunks, int(math.ceil(tail_seconds / max(chunk_seconds, 0.001))))
    frames = []
    deadline = (time.time() + float(max_seconds)) if max_seconds else None
    trailing = 0
    try:
        microphone_active.set()
        while deadline is None or time.time() < deadline:
            if source.stream is None:
                break
            try:
                data = source.stream.read(chunk_size)
            except Exception:
                break
            if data:
                frames.append(data)

            if is_push_to_talk_held():
                trailing = trailing_chunks
                continue

            if trailing > 0:
                trailing -= 1
                continue
            break

        if deadline is not None and time.time() >= deadline and is_push_to_talk_held():
            logger("⚠️ Push-to-talk reached the recording safety limit and stopped automatically.")

        if not frames:
            return None

        audio = audio_data_factory(b"".join(frames), sample_rate, sample_width)
        text = transcribe_func(audio)
        if text and re.search(r"[a-zA-Z0-9]", text):
            return text
        return None
    except sr_module.UnknownValueError:
        return None
    except Exception as exc:
        logger(f"✗ Push-to-talk mic error: {exc}")
        return None
    finally:
        microphone_active.clear()
