from __future__ import annotations

import os
import threading
from pathlib import Path

from core.tts_runtime import PocketTTSSubprocessAdapter


class PocketTTSService:
    def __init__(self, context):
        self._context = context
        self._lock = threading.RLock()
        self._adapter = None
        self._python_exe = ""
        self.sr = 24000

    def _engine(self):
        import engine

        return engine

    def _resolve_python_exe(self) -> str:
        engine = self._engine()
        python_exe = str(engine.RUNTIME_CONFIG.get("pocket_tts_python", "") or "").strip()
        if not python_exe:
            fallback = str(getattr(engine, "DEFAULT_POCKET_TTS_PYTHON", "") or "").strip()
            if fallback and Path(fallback).exists():
                python_exe = fallback
                engine.update_runtime_config("pocket_tts_python", fallback)
        return python_exe

    def _ensure_adapter(self):
        with self._lock:
            engine = self._engine()
            python_exe = self._resolve_python_exe()
            if self._adapter is not None and python_exe == self._python_exe:
                return self._adapter
            if self._adapter is not None:
                try:
                    self._adapter.close()
                except Exception:
                    pass
            if not python_exe:
                raise RuntimeError("Set PocketTTS Python in the addon tab first.")
            self._adapter = PocketTTSSubprocessAdapter(
                python_exe,
                app_root=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                safe_delete_with_retry=getattr(engine, "safe_delete_with_retry", None),
                logger=print,
            )
            self._python_exe = python_exe
            self.sr = int(getattr(self._adapter, "sr", self.sr) or self.sr or 24000)
            return self._adapter

    def generate(self, text, audio_prompt_path=None, **kwargs):
        adapter = self._ensure_adapter()
        return adapter.generate(text, audio_prompt_path=audio_prompt_path, **kwargs)

    def close(self):
        with self._lock:
            adapter = self._adapter
            self._adapter = None
            self._python_exe = ""
        if adapter is not None:
            try:
                adapter.close()
            except Exception:
                pass
