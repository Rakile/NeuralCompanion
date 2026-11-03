"""Speech-to-text runtime helpers and addon-backed STT services."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
import threading
import uuid

from core import runtime_files, runtime_paths

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


def stt_backend_runtime_config(runtime_config, *, backend_id=None):
    """Resolve provider-local settings while retaining legacy flat-only configs."""
    values = dict(runtime_config or {})
    selected = str(values.get("stt_backend") or "none").strip().lower()
    backend = str(backend_id or selected).strip().lower()
    settings_map = values.get("stt_backend_settings")
    settings_map = settings_map if isinstance(settings_map, Mapping) else {}
    scoped = settings_map.get(backend)
    scoped = scoped if isinstance(scoped, Mapping) else {}
    defaults = {
        "whisper_english": ("tiny.en", "en"),
        "whisper_multilingual": ("tiny", ""),
    }
    if backend in defaults and (backend in settings_map or backend != selected):
        values["stt_model_size"], values["stt_language"] = defaults[backend]
    for field in ("model_size", "language"):
        if field in scoped:
            values[f"stt_{field}"] = scoped[field]
    return values


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
    runtime_config = stt_backend_runtime_config(runtime_config)
    desired_backend = str(runtime_config.get("stt_backend", "none") or "none").lower().strip()

    if desired_backend == "none":
        if current_model is not None:
            closer = getattr(current_model, "close", None)
            if callable(closer):
                closer()
            logger("STT disabled; previous backend released.")
        return STTRuntimeState(True, None, None)

    if current_model is not None and current_backend_name == desired_backend:
        configure = getattr(current_model, "configure", None)
        reload_requested = False
        if callable(configure):
            reload_requested = bool(configure(runtime_config))
        if reload_requested:
            warmer = getattr(current_model, "warm_up", None)
            if callable(warmer):
                warmer()
            logger(f"✓ {desired_backend} STT backend configuration reloaded")
        else:
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
        configure = getattr(model, "configure", None)
        if callable(configure):
            configure(runtime_config)
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

    def configure(self, runtime_settings):
        configure = self._callable(("configure", "configure_runtime"))
        if configure is not None:
            return configure(dict(runtime_settings or {}))
        return None

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


    def close_strict(self):
        closer = getattr(self.service, "close_strict", None) or getattr(self.service, "close", None)
        if callable(closer):
            result = closer()
            if result is False or getattr(result, "accepted", True) is False:
                raise RuntimeError(f"STT backend '{self.backend_id}' rejected cleanup: {getattr(result, 'failure', result)}")


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
        _legacy_context=None,
        *,
        backend_id: str,
        default_model_size: str,
        default_language=None,
        force_language=None,
        runtime_settings=None,
        logger=print,
        safe_delete=None,
    ):
        self.backend_id = str(backend_id or "").strip().lower()
        self.default_model_size = str(default_model_size or "tiny.en").strip() or "tiny.en"
        self.default_language = default_language
        self.force_language = force_language
        self._runtime_settings = runtime_settings or {}
        self._logger = logger
        self._safe_delete_file = safe_delete or (
            lambda path: runtime_files.safe_delete_with_retry(
                path,
                logger=self._logger,
            )
        )
        self._lock = threading.RLock()
        self._model = None
        self._model_signature = None

    def _runtime_config(self):
        settings = self._runtime_settings
        if callable(settings):
            try:
                settings = settings()
            except Exception:
                settings = {}
        return dict(settings or {})

    def configure(self, runtime_settings):
        with self._lock:
            previous_model_size = self._runtime_model_size()
            self._runtime_settings = dict(runtime_settings or {})
            next_model_size = self._runtime_model_size()
        return previous_model_size != next_model_size

    def _safe_delete(self, path):
        try:
            return self._safe_delete_file(path)
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
            self._logger(
                f"Loading STT backend {self.backend_id}: Whisper ({model_size}) on {device} "
                f"[language={language_label}, compute_type={compute_type}, reason={reason}]..."
            )
            self._model = WhisperModel(model_size, device=device, compute_type=compute_type)
            self._model_signature = signature
            self._logger(
                f"STT backend {self.backend_id} loaded Whisper {model_size} on {device} "
                f"({compute_type}, language={language_label})"
            )
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

    def resources_snapshot(self):
        with self._lock:
            if self._model is None:
                return []
            signature = self._model_signature or ()
            return [{"id": str(id(self._model)), "name": "Whisper",
                     "model": str(signature[0]) if signature else "Whisper",
                     "device": str(signature[1]) if len(signature) > 1 else "Unavailable",
                     "owner": "NC · speech-to-text", "canUnload": True,
                     "processId": os.getpid(), "processLabel": "NeuralCompanion"}]

    def unload_resource(self, instance_id):
        with self._lock:
            if self._model is None or str(id(self._model)) != str(instance_id):
                return False
            self.close_strict()
            return True

    def close_strict(self):
        with self._lock:
            model = self._model
            closer = getattr(model, "close", None)
            if callable(closer):
                result = closer()
                if result is False or getattr(result, "accepted", True) is False:
                    raise RuntimeError("Whisper model rejected cleanup.")
            self._model = None
            self._model_signature = None

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
