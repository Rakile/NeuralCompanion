from __future__ import annotations

import threading
from typing import Any


class ChatterboxTTSService:
    def __init__(self, context):
        self._context = context
        self._lock = threading.RLock()
        self._abort_event = threading.Event()
        self._model = None
        self.sr = 24000

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
            import engine

            self._abort_event.clear()
            self._model = ChatterboxTurboTTS.from_pretrained(device=getattr(engine, "TTS_DEVICE", "cpu"))
            self._install_abort_hook(self._model)
            self.sr = int(getattr(self._model, "sr", self.sr) or self.sr or 24000)
            return self._model

    def generate(self, text, audio_prompt_path=None, **kwargs):
        self._abort_event.clear()
        model = self._ensure_model()
        request = dict(kwargs or {})
        for key in ("backend_id", "backend_label", "tts_backend", "text"):
            request.pop(key, None)
        if audio_prompt_path is not None:
            request.setdefault("audio_prompt_path", audio_prompt_path)
        elif "audio_prompt_path" not in request:
            import engine

            request["audio_prompt_path"] = str(engine.RUNTIME_CONFIG.get("voice_path", "voices/Hot_16.wav") or "voices/Hot_16.wav")
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
