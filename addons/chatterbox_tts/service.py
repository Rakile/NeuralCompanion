from __future__ import annotations

import os
import inspect
import importlib
import logging
import threading
from typing import Any


class _SilentTqdm:
    def __init__(self, iterable=None, *args, **kwargs):
        self.iterable = iterable

    def __iter__(self):
        if self.iterable is None:
            return iter(())
        return iter(self.iterable)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def update(self, *args, **kwargs):
        return None

    def close(self):
        return None

    def set_description(self, *args, **kwargs):
        return None

    def set_postfix(self, *args, **kwargs):
        return None


def _silent_tqdm(iterable=None, *args, **kwargs):
    return _SilentTqdm(iterable, *args, **kwargs)


class _SuppressReferenceMelFilter(logging.Filter):
    def filter(self, record):
        try:
            return "Reference mel length is not equal to 2 * reference token length." not in record.getMessage()
        except Exception:
            return True


def _suppress_chatterbox_console_noise():
    try:
        root_logger = logging.getLogger()
        if not any(isinstance(item, _SuppressReferenceMelFilter) for item in root_logger.filters):
            root_logger.addFilter(_SuppressReferenceMelFilter())
    except Exception:
        pass
    for module_name in (
        "chatterbox.models.t3.t3",
        "chatterbox.models.s3gen.flow_matching",
    ):
        try:
            module = importlib.import_module(module_name)
            setattr(module, "tqdm", _silent_tqdm)
        except Exception:
            continue


class _NoOpWatermarker:
    def apply_watermark(self, wav, sample_rate=None):
        return wav


class ChatterboxTTSService:
    def __init__(self, context):
        _suppress_chatterbox_console_noise()
        self._context = context
        self._lock = threading.RLock()
        self._abort_event = threading.Event()
        self._model = None
        self.sr = 24000

    def _runtime_config_service(self):
        return self._context.get_service("qt.runtime_config") if self._context is not None else None

    def _engine_attr(self, name: str, default=None):
        service = self._runtime_config_service()
        if service is not None and hasattr(service, "engine_attr"):
            return service.engine_attr(name, default)
        return default

    def _runtime_bool(self, key: str, default: bool) -> bool:
        service = self._runtime_config_service()
        if service is None:
            return bool(default)
        value = service.get(key, default)
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)

    def _install_abort_hook(self, model):
        if bool(getattr(model, "_nc_abort_hook_installed", False)):
            return
        t3 = getattr(model, "t3", None)
        transformer = getattr(t3, "tfmr", None)
        original_forward = getattr(transformer, "forward", None)
        if not callable(original_forward):
            return

        abort_event = self._abort_event

        def guarded_forward(*args, **kwargs):
            if abort_event.is_set():
                raise RuntimeError("Chatterbox TTS generation cancelled during shutdown")
            return original_forward(*args, **kwargs)

        transformer.forward = guarded_forward
        setattr(model, "_nc_abort_hook_installed", True)

    def _generate_accepts(self, model, parameter_name: str) -> bool:
        try:
            signature = inspect.signature(model.generate)
        except Exception:
            return False
        return str(parameter_name or "") in signature.parameters

    def _set_watermark_enabled(self, model, enabled: bool):
        if model is None or self._generate_accepts(model, "apply_watermark"):
            return
        if not hasattr(model, "watermarker"):
            return
        original = getattr(model, "_nc_original_watermarker", None)
        if original is None:
            original = getattr(model, "watermarker", None)
            setattr(model, "_nc_original_watermarker", original)
        if enabled and isinstance(original, _NoOpWatermarker):
            try:
                import perth

                original = perth.PerthImplicitWatermarker()
                setattr(model, "_nc_original_watermarker", original)
            except Exception:
                original = getattr(model, "watermarker", original)
        model.watermarker = original if enabled else _NoOpWatermarker()

    def _ensure_model(self):
        with self._lock:
            if self._model is not None:
                self._set_watermark_enabled(self._model, self._runtime_bool("tts_apply_watermark", True))
                return self._model
            from chatterbox import tts_turbo

            self._abort_event.clear()
            apply_watermark = self._runtime_bool("tts_apply_watermark", True)
            original_watermarker_cls = None
            if not apply_watermark:
                try:
                    original_watermarker_cls = tts_turbo.perth.PerthImplicitWatermarker
                    tts_turbo.perth.PerthImplicitWatermarker = _NoOpWatermarker
                except Exception:
                    original_watermarker_cls = None
            try:
                self._model = tts_turbo.ChatterboxTurboTTS.from_pretrained(device=self._engine_attr("TTS_DEVICE", "cpu"))
            finally:
                if original_watermarker_cls is not None:
                    try:
                        tts_turbo.perth.PerthImplicitWatermarker = original_watermarker_cls
                    except Exception:
                        pass
            self._install_abort_hook(self._model)
            self._set_watermark_enabled(self._model, apply_watermark)
            self.sr = int(getattr(self._model, "sr", self.sr) or self.sr or 24000)
            return self._model

    def _voice_prompt_path(self):
        service = self._runtime_config_service()
        voice_path = str((service.get("voice_path", "") if service is not None else "") or "").strip()
        if voice_path and os.path.exists(voice_path):
            return voice_path
        if voice_path:
            print(f"⚠️ Voice file not found: {voice_path}. Continuing without a reference voice.")
        return ""

    def _generation_request(self, kwargs):
        request = dict(kwargs or {})
        for key in ("backend_id", "backend_label", "tts_backend", "text"):
            request.pop(key, None)
        apply_watermark = self._runtime_bool("tts_apply_watermark", True)
        model = self._ensure_model()
        self._set_watermark_enabled(model, apply_watermark)
        if self._generate_accepts(model, "apply_watermark"):
            request["apply_watermark"] = apply_watermark
        return model, request

    def warm_up(self):
        if not self._runtime_bool("tts_prewarm_on_start", True):
            return False
        with self._lock:
            try:
                self._abort_event.clear()
                model, request = self._generation_request(
                    {
                        "audio_prompt_path": self._voice_prompt_path(),
                        "temperature": 0.6,
                        "top_p": 0.9,
                        "top_k": 40,
                        "repetition_penalty": 1.2,
                        "min_p": 0.0,
                        "norm_loudness": False,
                    }
                )
                if not request.get("audio_prompt_path"):
                    request.pop("audio_prompt_path", None)
                model.generate("Ready.", **request)
                print("✓ Chatterbox warmup complete")
                return True
            except Exception as exc:
                print(f"⚠️ Chatterbox warmup failed: {exc}")
                return False

    def generate(self, text, audio_prompt_path=None, **kwargs):
        self._abort_event.clear()
        model, request = self._generation_request(kwargs)
        for key in ("min_p",):
            request.pop(key, None)
        if audio_prompt_path is not None:
            request.setdefault("audio_prompt_path", audio_prompt_path)
        elif "audio_prompt_path" not in request:
            voice_path = self._voice_prompt_path()
            if voice_path:
                request["audio_prompt_path"] = voice_path
        return model.generate(str(text or ""), **request)

    def close(self):
        self._abort_event.set()
        with self._lock:
            model = self._model
            self._model = None
        if model is not None:
            closer = getattr(model, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:
                    pass
