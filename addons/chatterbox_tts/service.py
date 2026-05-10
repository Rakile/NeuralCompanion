from __future__ import annotations

import os
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

    def _ensure_model(self):
        with self._lock:
            if self._model is not None:
                return self._model
            from chatterbox.tts_turbo import ChatterboxTurboTTS

            self._abort_event.clear()
            self._model = ChatterboxTurboTTS.from_pretrained(device=self._engine_attr("TTS_DEVICE", "cpu"))
            self._install_abort_hook(self._model)
            self.sr = int(getattr(self._model, "sr", self.sr) or self.sr or 24000)
            return self._model

    def generate(self, text, audio_prompt_path=None, **kwargs):
        self._abort_event.clear()
        model = self._ensure_model()
        request = dict(kwargs or {})
        for key in ("backend_id", "backend_label", "tts_backend", "text", "min_p"):
            request.pop(key, None)
        if audio_prompt_path is not None:
            request.setdefault("audio_prompt_path", audio_prompt_path)
        elif "audio_prompt_path" not in request:
            service = self._runtime_config_service()
            voice_path = str((service.get("voice_path", "") if service is not None else "") or "").strip()
            if voice_path and os.path.exists(voice_path):
                request["audio_prompt_path"] = voice_path
            elif voice_path:
                print(f"⚠️ Voice file not found: {voice_path}. Continuing without a reference voice.")
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
