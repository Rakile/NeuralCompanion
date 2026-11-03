from __future__ import annotations

import os
import threading
from pathlib import Path

from core.pocket_tts_voices import resolve_pocket_tts_builtin_voice
from core.tts_runtime import PocketTTSSubprocessAdapter
from addons.pockettts.runtime_config import default_pocket_tts_python, safe_delete_with_retry


class PocketTTSService:
    def __init__(self, context):
        self._context = context
        self._lock = threading.RLock()
        self._adapter = None
        self._python_exe = ""
        self._settings_signature = ()
        self.sr = 24000

    def _runtime_config_service(self):
        return self._context.capabilities.runtime_config if self._context is not None else None

    def _resolve_python_exe(self) -> str:
        service = self._runtime_config_service()
        python_exe = str((service.get("pocket_tts_python", "") if service is not None else "") or "").strip()
        if not python_exe:
            fallback = default_pocket_tts_python(self._context.paths.app_root) if self._context is not None else ""
            if fallback and Path(fallback).exists():
                python_exe = fallback
                if service is not None:
                    service.update("pocket_tts_python", fallback)
        return python_exe

    def _runtime_settings(self):
        service = self._runtime_config_service()
        getter = service.get if service is not None else (lambda _key, default=None: default)
        return {
            "language": "en",
            "temperature": max(0.05, float(getter("pocket_tts_temperature", 0.7) or 0.7)),
            "lsd_decode_steps": max(1, int(getter("pocket_tts_lsd_decode_steps", 1) or 1)),
            "eos_threshold": float(getter("pocket_tts_eos_threshold", -4.0) or -4.0),
            "frames_after_eos": max(0, int(getter("pocket_tts_frames_after_eos", 0) or 0)),
        }

    def _runtime_bool(self, key: str, default: bool) -> bool:
        service = self._runtime_config_service()
        if service is None:
            return bool(default)
        value = service.get(key, default)
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)

    def _use_cloned_voice(self):
        return self._runtime_bool("pocket_tts_use_cloned_voice", True)

    def _builtin_voice(self, language="en"):
        service = self._runtime_config_service()
        value = service.get("pocket_tts_builtin_voice", "auto") if service is not None else "auto"
        return resolve_pocket_tts_builtin_voice(value, language)

    def _voice_prompt_path(self):
        if not self._use_cloned_voice():
            return ""
        service = self._runtime_config_service()
        voice_path = str((service.get("voice_path", "") if service is not None else "") or "").strip()
        if voice_path and os.path.exists(voice_path):
            return voice_path
        if voice_path:
            print(f"⚠️ Voice file not found: {voice_path}. Continuing without the PocketTTS voice reference.")
        return ""

    def _ensure_adapter(self):
        with self._lock:
            python_exe = self._resolve_python_exe()
            settings = self._runtime_settings()
            signature = tuple((key, settings[key]) for key in sorted(settings))
            if self._adapter is not None and python_exe == self._python_exe and signature == self._settings_signature:
                return self._adapter
            if self._adapter is not None:
                self._close_adapter_strict(self._adapter)
            if not python_exe:
                raise RuntimeError("Set PocketTTS Python in the addon tab first.")
            self._adapter = PocketTTSSubprocessAdapter(
                python_exe,
                app_root=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                safe_delete_with_retry=safe_delete_with_retry,
                logger=print,
                **settings,
            )
            self._python_exe = python_exe
            self._settings_signature = signature
            self.sr = int(getattr(self._adapter, "sr", self.sr) or self.sr or 24000)
            return self._adapter

    def generate(self, text, audio_prompt_path=None, **kwargs):
        # Keep direct narration calls serialized with model cleanup.
        with self._lock:
            process = getattr(self._adapter, "process", None)
            try:
                worker_exited = process is not None and process.poll() is not None
            except Exception:
                worker_exited = False  # Unknown state does not authorize replacement.
            if worker_exited:
                # Recover only for this new request, after strict cleanup succeeds.
                self._close_adapter_strict(self._adapter)
            adapter = self._ensure_adapter()
            language = self._runtime_settings()["language"]
            if not self._use_cloned_voice():
                audio_prompt_path = self._builtin_voice(language)
            elif audio_prompt_path is None:
                audio_prompt_path = self._voice_prompt_path() or None
            return adapter.generate(text, audio_prompt_path=audio_prompt_path, **kwargs)

    def warm_up(self):
        if not self._runtime_bool("pocket_tts_prewarm_on_start", True):
            return False
        with self._lock:
            try:
                adapter = self._ensure_adapter()
                language = self._runtime_settings()["language"]
                audio_prompt_path = self._voice_prompt_path() or None
                if not self._use_cloned_voice():
                    audio_prompt_path = self._builtin_voice(language)
                adapter.generate(
                    "Ready.",
                    audio_prompt_path=audio_prompt_path,
                    pocket_tts_max_tokens=12,
                    pocket_tts_frames_after_eos=0,
                )
                self.sr = int(getattr(adapter, "sr", self.sr) or self.sr or 24000)
                print("✓ PocketTTS warmup complete")
                return True
            except Exception as exc:
                print(f"⚠️ PocketTTS warmup failed: {exc}")
                return False

    def resources_snapshot(self):
        with self._lock:
            process = getattr(self._adapter, "process", None)
            if process is None or process.poll() is not None:
                return []
            return [{"id": str(process.pid), "name": "Pocket TTS", "model": "Pocket TTS",
                     "device": "CPU", "owner": "NC · voice worker", "canUnload": True,
                     "processId": process.pid, "processLabel": "Pocket TTS worker"}]

    def unload_resource(self, instance_id):
        adapter = self._adapter
        process = getattr(adapter, "process", None)
        if process is None or str(process.pid) != str(instance_id):
            return False
        self._close_adapter_strict(adapter)
        return True

    def close_strict(self):
        while not self._close_adapter_strict(self._adapter):
            pass  # Startup or a settings change published a different adapter.

    def _close_adapter_strict(self, adapter):
        # Interrupt the worker before waiting for a narration call's service lock.
        if adapter is not None:
            closer = getattr(adapter, "close_strict", None) or adapter.close
            result = closer()
            if result is False or getattr(result, "accepted", True) is False:
                raise RuntimeError("PocketTTS adapter rejected cleanup.")
        while not self._lock.acquire(timeout=0.1):
            if self._adapter is not adapter:
                return False
        try:
            if self._adapter is not adapter:
                return False
            self._adapter = None
            self._python_exe = ""
            self._settings_signature = ()
            return True
        finally:
            self._lock.release()

    def close(self):
        try:
            self.close_strict()
        except Exception:
            pass
