"""TTS backend adapters and backend discovery helpers."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid

import numpy as np
import soundfile as sf
import torch

from core import runtime_paths
from core.pocket_tts_voices import default_pocket_tts_voice_for_language


def _auto_pocket_tts_max_tokens(text: str, configured_max_tokens: int, language: str) -> int:
    """Choose a synthesis token budget from the actual text chunk length."""
    clean = " ".join(str(text or "").split())
    configured = max(1, int(configured_max_tokens or 1))
    if not clean:
        return configured
    lang = str(language or "").strip().lower()
    multilingual = lang not in {"", "en", "english"}
    base = 56 if multilingual else 40
    ratio = 2.1 if multilingual else 1.6
    ceiling = 520 if multilingual else 420
    estimated = base + int(round(len(clean) * ratio))
    return min(ceiling, max(configured, estimated))


def load_audio_file(path):
    audio, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
    wav = torch.from_numpy(audio).transpose(0, 1).contiguous()
    return wav, int(sample_rate or 0)


@dataclass
class TTSRuntimeState:
    ok: bool
    model: object | None
    backend_name: str | None


class TTSController:
    def __init__(self):
        self.done = threading.Event()
        self.interrupted = threading.Event()
        self.cancel_requested = threading.Event()
        self.skip_current_message = threading.Event()
        self.spoken_chunks = []
        self._current_message_id = ""
        self._current_replay_index = 0
        self._generating_message_id = ""
        self._skip_message_id = ""
        self._skipped_message_ids = set()
        self._ready_message_ids = set()
        self._lock = threading.Lock()

    def add_spoken(self, chunk_text: str):
        with self._lock:
            self.spoken_chunks.append(chunk_text)

    def get_spoken_text(self) -> str:
        with self._lock:
            return " ".join(self.spoken_chunks).strip()

    def set_current_message_id(self, message_id: str):
        with self._lock:
            self._current_message_id = str(message_id or "")
            raw = self._current_message_id
            if raw.startswith("replay:"):
                try:
                    self._current_replay_index = int(raw.split(":", 1)[1])
                except Exception:
                    pass
            if self.skip_current_message.is_set() and self._skip_message_id == "__pending__":
                self._skip_message_id = self._current_message_id

    def current_replay_index(self) -> int:
        with self._lock:
            return int(self._current_replay_index or 0)

    def can_prepare_replay_index(self, index: int, lookahead: int = 1) -> bool:
        try:
            target = int(index)
            ahead = max(0, int(lookahead))
        except Exception:
            return True
        with self._lock:
            current = int(self._current_replay_index or 0)
        if current <= 0:
            return target <= 1
        return target <= current + ahead

    def request_skip_current_message(self):
        with self._lock:
            skip_message_id = str(self._current_message_id or "__pending__")
            already_requested = self.skip_current_message.is_set() and self._skip_message_id == skip_message_id
            self._skip_message_id = skip_message_id
            if skip_message_id and skip_message_id != "__pending__":
                self._skipped_message_ids.add(skip_message_id)
            self.skip_current_message.set()
            return not already_requested

    def cancel(self):
        with self._lock:
            skip_message_id = str(self._current_message_id or "__pending__")
            self._skip_message_id = skip_message_id
            if skip_message_id and skip_message_id != "__pending__":
                self._skipped_message_ids.add(skip_message_id)
            self.cancel_requested.set()
            self.skip_current_message.set()

    def set_generating_message_id(self, message_id: str):
        with self._lock:
            self._generating_message_id = str(message_id or "")

    def clear_generating_message_id(self, message_id: str):
        with self._lock:
            current = str(message_id or "")
            if not current or self._generating_message_id == current:
                self._generating_message_id = ""

    def should_cancel_active_generation_for_skip(self) -> bool:
        with self._lock:
            if not self.skip_current_message.is_set() or not self._skip_message_id:
                return False
            if not self._generating_message_id:
                return False
            if self._skip_message_id == "__pending__":
                self._skip_message_id = self._generating_message_id
                self._current_message_id = self._generating_message_id
                if self._generating_message_id:
                    self._skipped_message_ids.add(self._generating_message_id)
                return True
            return self._skip_message_id == self._generating_message_id

    def clear_skip_current_message_if_new(self, message_id: str):
        with self._lock:
            current = str(message_id or "")
            if self.skip_current_message.is_set() and self._skip_message_id and self._skip_message_id != current:
                self._skip_message_id = ""
                self.skip_current_message.clear()

    def should_skip_message(self, message_id: str) -> bool:
        with self._lock:
            current = str(message_id or "")
            if current and current in self._skipped_message_ids:
                return True
            if self.skip_current_message.is_set() and self._skip_message_id == "__pending__" and current:
                self._skip_message_id = current
                self._current_message_id = current
                self._skipped_message_ids.add(current)
                return True
            return bool(self.skip_current_message.is_set() and self._skip_message_id and self._skip_message_id == current)

    def mark_message_ready(self, message_id: str):
        value = str(message_id or "")
        if not value:
            return
        with self._lock:
            self._ready_message_ids.add(value)

    def has_ready_replay_message_after(self, index: int) -> bool:
        try:
            current_index = int(index)
        except Exception:
            return False
        with self._lock:
            for message_id in self._ready_message_ids:
                raw = str(message_id or "")
                if not raw.startswith("replay:"):
                    continue
                try:
                    if int(raw.split(":", 1)[1]) > current_index:
                        return True
                except Exception:
                    continue
            return False


def list_available_tts_backends(manager_getter, *, logger=print):
    backends = []
    seen = set()
    manager = manager_getter()
    if manager is not None:
        try:
            entries = list(manager.list_registered_services() or [])
        except Exception as exc:
            logger(f"⚠️ [Addons] Failed to enumerate TTS backends: {exc}")
            entries = []
        for entry in entries:
            metadata = dict(entry.get("metadata") or {})
            kind = str(metadata.get("kind", "") or "").strip().lower()
            if kind not in {"tts", "tts_backend", "text_to_speech"}:
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
    builtin_backends = [
        {"id": "none", "label": "None", "kind": "builtin"},
    ]
    if manager is None:
        # Legacy mode: before the addon manager exists, expose the old direct
        # backends so non-addon startup paths still behave as before.
        builtin_backends.extend(
            [
                {"id": "chatterbox", "label": "Chatterbox", "kind": "builtin"},
                {"id": "pockettts", "label": "PocketTTS", "kind": "builtin"},
            ]
        )
    for item in builtin_backends:
        backend_id = str(item.get("id") or "").strip().lower()
        if backend_id and backend_id not in seen:
            backends.append(item)
            seen.add(backend_id)
    return backends


def resolve_addon_tts_backend(backend_id: str, manager_getter):
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
        if kind not in {"tts", "tts_backend", "text_to_speech"}:
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


def initialize_tts_backend(
    *,
    runtime_config,
    current_model,
    current_backend_name,
    addon_resolver,
    addon_adapter_cls,
    logger=print,
):
    desired_backend = str(runtime_config.get("tts_backend", "none") or "none").lower().strip()

    if desired_backend in {"none", "off", "disabled", "no_tts", "no-tts"}:
        if current_model is not None and hasattr(current_model, "close"):
            try:
                current_model.close()
            except Exception:
                pass
        logger("TTS disabled; continuing without speech output.")
        return TTSRuntimeState(True, None, "none")

    if current_model is not None and current_backend_name == desired_backend:
        logger(f"✓ {desired_backend} TTS model already loaded (Skipping reload)")
        return TTSRuntimeState(True, current_model, current_backend_name)

    if current_model is not None and hasattr(current_model, "close"):
        try:
            current_model.close()
        except Exception:
            pass
    model = None
    backend_name = None

    if desired_backend:
        resolved = addon_resolver(desired_backend)
        if resolved is not None:
            logger(f"Loading addon TTS backend '{resolved['label']}' ({resolved['service_name']})...")
            try:
                model = addon_adapter_cls(
                    backend_id=resolved["id"],
                    label=resolved["label"],
                    service=resolved["service"],
                )
                backend_name = resolved["id"]
                logger(f"✓ Addon TTS backend loaded successfully: {resolved['label']}")
                return TTSRuntimeState(True, model, backend_name)
            except Exception as exc:
                logger(f"✗ Failed to load addon TTS backend '{resolved['label']}': {exc}")
                logger("↩️ Continuing without TTS because the selected addon backend failed.")
                return TTSRuntimeState(True, None, "none")

    logger(f"⚠️ TTS backend '{desired_backend}' is unavailable or disabled; continuing without TTS.")
    return TTSRuntimeState(True, None, "none")


def build_generation_kwargs(runtime_config, *, set_seed=None, path_exists=os.path.exists, logger=print):
    configured_seed = int(runtime_config.get("tts_seed", 0) or 0)
    if configured_seed > 0 and callable(set_seed):
        set_seed(configured_seed)
    kwargs = dict(
        temperature=float(runtime_config.get("tts_temperature", 0.8) or 0.8),
        top_p=float(runtime_config.get("tts_top_p", 0.9) or 0.9),
        top_k=int(runtime_config.get("tts_top_k", 40) or 40),
        repetition_penalty=float(runtime_config.get("tts_repeat_penalty", 1.2) or 1.2),
        min_p=float(runtime_config.get("tts_min_p", 0.0) or 0.0),
        norm_loudness=bool(runtime_config.get("tts_normalize_loudness", False)),
    )
    voice_path = str(runtime_config.get("voice_path", "") or "").strip()
    if voice_path and path_exists(voice_path):
        kwargs["audio_prompt_path"] = voice_path
    elif voice_path:
        logger(f"⚠️ Voice file not found: {voice_path}. Continuing without a reference voice.")
    return kwargs


class PocketTTSSubprocessAdapter:
    def __init__(
        self,
        python_exe,
        *,
        app_root=None,
        safe_delete_with_retry=None,
        logger=print,
        temperature=0.7,
        language="en",
        lsd_decode_steps=1,
        eos_threshold=-4.0,
        max_tokens=50,
        frames_after_eos=0,
    ):
        self.python_exe = python_exe
        self.app_root = app_root or os.getcwd()
        self.safe_delete_with_retry = safe_delete_with_retry or (lambda path: None)
        self.logger = logger
        self.temperature = float(temperature or 0.7)
        self.language = str(language or "en").strip().lower() or "en"
        self.lsd_decode_steps = max(1, int(lsd_decode_steps or 1))
        self.eos_threshold = float(eos_threshold if eos_threshold is not None else -4.0)
        self.max_tokens = max(1, int(max_tokens or 50))
        self.frames_after_eos = max(0, int(frames_after_eos or 0))
        self.process = None
        self.lock = threading.Lock()
        self.sr = 24000
        self._stderr_thread = None
        self._start_worker()

    def _start_worker(self):
        worker_script = os.path.abspath(os.path.join(self.app_root, "pocket_tts_worker.py"))
        if not os.path.exists(self.python_exe):
            raise FileNotFoundError(f"PocketTTS interpreter not found: {self.python_exe}")
        if not os.path.exists(worker_script):
            raise FileNotFoundError(f"PocketTTS worker not found: {worker_script}")
        command = [
            self.python_exe,
            worker_script,
            "--temperature",
            str(self.temperature),
            "--language",
            str(self.language),
            "--lsd-decode-steps",
            str(self.lsd_decode_steps),
            "--eos-threshold",
            str(self.eos_threshold),
        ]
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()
        ready = self._read_message(timeout=120.0)
        if not ready or ready.get("status") != "ready":
            error = str((ready or {}).get("error") or ready or "unknown startup error")
            raise RuntimeError(f"PocketTTS worker failed to start: {error}")
        self.sr = int(ready.get("sample_rate", 24000) or 24000)
        worker_pid = ready.get("pid")
        if worker_pid:
            language = str(ready.get("language", self.language) or self.language)
            model_language = str(ready.get("model_language", language) or language)
            applied = "yes" if bool(ready.get("language_applied", False)) else "no"
            self.logger(
                f"[PocketTTS] Worker ready: pid={worker_pid}, sample_rate={self.sr}, "
                f"language={language}, model_language={model_language}, load_model_language={applied}"
            )

    def _drain_stderr(self):
        if self.process is None or self.process.stderr is None:
            return
        for line in self.process.stderr:
            line = (line or "").rstrip()
            if line:
                self.logger(f"[PocketTTS] {line}")

    def _read_message(self, timeout=60.0):
        if self.process is None or self.process.stdout is None:
            raise RuntimeError("PocketTTS worker is not running")
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.process.poll() is not None:
                line = self.process.stdout.readline()
                if line:
                    return json.loads(line)
                raise RuntimeError(f"PocketTTS worker stopped before responding (exit_code={self.process.returncode})")
            line = self.process.stdout.readline()
            if line:
                return json.loads(line)
            time.sleep(0.01)
        raise TimeoutError("Timed out waiting for PocketTTS worker response")

    def generate(self, text, audio_prompt_path=None, **kwargs):
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError("PocketTTS worker is not available")
        request_id = uuid.uuid4().hex[:8]
        output_path = str(runtime_paths.runtime_temp_file(f"pocket_tts_{request_id}.wav", "tts", "pocket_tts"))
        request_language = str(kwargs.get("pocket_tts_language", self.language) or self.language)
        configured_max_tokens = max(1, int(kwargs.get("pocket_tts_max_tokens", self.max_tokens) or self.max_tokens))
        max_tokens = _auto_pocket_tts_max_tokens(text, configured_max_tokens, request_language)
        frames_after_eos = max(0, int(kwargs.get("pocket_tts_frames_after_eos", self.frames_after_eos) or 0))
        default_voice = default_pocket_tts_voice_for_language(self.language)
        payload = {
            "cmd": "synthesize",
            "request_id": request_id,
            "text": text,
            "voice_prompt": audio_prompt_path or default_voice,
            "output_path": output_path,
            "max_tokens": max_tokens,
            "frames_after_eos": frames_after_eos,
            "language": request_language,
        }
        with self.lock:
            self.process.stdin.write(json.dumps(payload) + "\n")
            self.process.stdin.flush()
            response = self._read_message(timeout=180.0)
        if response.get("status") != "ok":
            raise RuntimeError(response.get("error", "PocketTTS worker synthesis failed"))
        wav, sample_rate = load_audio_file(output_path)
        self.sr = int(sample_rate or self.sr or 24000)
        self.safe_delete_with_retry(output_path)
        return wav

    def close(self):
        process = self.process
        self.process = None
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.write(json.dumps({"cmd": "close"}) + "\n")
                process.stdin.flush()
        except Exception:
            pass
        try:
            process.wait(timeout=3.0)
        except Exception:
            try:
                process.terminate()
                process.wait(timeout=2.0)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass


class AddonTTSBackendAdapter:
    def __init__(self, backend_id: str, label: str, service):
        self.backend_id = str(backend_id or "").strip().lower()
        self.label = str(label or backend_id or "AddonTTS").strip()
        self.service = service
        self.sr = int(getattr(service, "sr", getattr(service, "sample_rate", 24000)) or 24000)

    def _callable(self):
        for name in ("generate", "synthesize", "tts", "speak"):
            candidate = getattr(self.service, name, None)
            if callable(candidate):
                return candidate
        return None

    def _normalize_result(self, result):
        if result is None:
            raise RuntimeError(f"Addon TTS backend '{self.backend_id}' returned no audio")
        if isinstance(result, (str, Path)):
            wav, sample_rate = load_audio_file(result)
            self.sr = int(sample_rate or self.sr or 24000)
            return wav
        if isinstance(result, dict):
            audio_path = str(result.get("audio_path") or result.get("path") or "").strip()
            if audio_path:
                wav, sample_rate = load_audio_file(audio_path)
                self.sr = int(result.get("sample_rate") or result.get("sr") or sample_rate or self.sr or 24000)
                return wav
            wav = result.get("wav")
            if wav is not None:
                sample_rate = int(result.get("sample_rate") or result.get("sr") or self.sr or 24000)
                self.sr = sample_rate
                if hasattr(wav, "cpu"):
                    return wav
                return torch.as_tensor(wav)
        if isinstance(result, tuple) and len(result) == 2:
            wav, sample_rate = result
            if isinstance(wav, (str, Path)):
                wav, loaded_sample_rate = load_audio_file(wav)
                self.sr = int(sample_rate or loaded_sample_rate or self.sr or 24000)
                return wav
            self.sr = int(sample_rate or self.sr or 24000)
            if hasattr(wav, "cpu"):
                return wav
            return torch.as_tensor(wav)
        if hasattr(result, "cpu"):
            return result
        if isinstance(result, np.ndarray):
            return torch.from_numpy(result)
        raise RuntimeError(f"Addon TTS backend '{self.backend_id}' returned an unsupported audio payload")

    def generate(self, text, audio_prompt_path=None, **kwargs):
        fn = self._callable()
        if fn is None:
            raise RuntimeError(f"Addon TTS backend '{self.backend_id}' does not expose a generate-compatible method")
        request = dict(kwargs or {})
        if audio_prompt_path is not None:
            request.setdefault("audio_prompt_path", audio_prompt_path)
        request.setdefault("backend_id", self.backend_id)
        request.setdefault("backend_label", self.label)
        request.setdefault("tts_backend", self.backend_id)
        try:
            result = fn(text, **request)
        except TypeError:
            result = fn(text)
        return self._normalize_result(result)

    def warm_up(self):
        warmer = getattr(self.service, "warm_up", None)
        if callable(warmer):
            return warmer()
        return False

    def prepare_voice(self, audio_prompt_path, **kwargs):
        preparer = getattr(self.service, "prepare_voice", None)
        if not callable(preparer):
            return False
        return bool(preparer(audio_prompt_path, **dict(kwargs or {})))

    def close(self):
        closer = getattr(self.service, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                pass
