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

    def _runtime_config_service(self):
        return self._context.get_service("qt.runtime_config") if self._context is not None else None

    def _engine_attr(self, name: str, default=None):
        service = self._runtime_config_service()
        if service is not None and hasattr(service, "engine_attr"):
            return service.engine_attr(name, default)
        return default

    def _resolve_python_exe(self) -> str:
        service = self._runtime_config_service()
        python_exe = str((service.get("pocket_tts_python", "") if service is not None else "") or "").strip()
        if not python_exe:
            fallback = str(self._engine_attr("DEFAULT_POCKET_TTS_PYTHON", "") or "").strip()
            if fallback and Path(fallback).exists():
                python_exe = fallback
                if service is not None:
                    service.update("pocket_tts_python", fallback)
        return python_exe

    def _ensure_adapter(self):
        with self._lock:
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
                safe_delete_with_retry=self._engine_attr("safe_delete_with_retry", None),
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
