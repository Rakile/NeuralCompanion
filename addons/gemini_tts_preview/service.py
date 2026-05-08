from __future__ import annotations

import base64
import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
from pathlib import Path
from typing import Any

from core import runtime_paths


DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"
DEFAULT_MODEL = "gemini-3.1-flash-tts-preview"
DEFAULT_VOICE = "Kore"
DEFAULT_LANGUAGE_CODE = ""
DEFAULT_STYLE_PROMPT = ""

FALLBACK_MODELS = [
    "gemini-3.1-flash-tts-preview",
    "gemini-2.5-flash-preview-tts",
    "gemini-2.5-pro-preview-tts",
]

VOICE_OPTIONS = [
    ("Zephyr", "Bright"),
    ("Puck", "Upbeat"),
    ("Charon", "Informative"),
    ("Kore", "Firm"),
    ("Fenrir", "Excitable"),
    ("Leda", "Youthful"),
    ("Orus", "Firm"),
    ("Aoede", "Breezy"),
    ("Callirrhoe", "Easy-going"),
    ("Autonoe", "Bright"),
    ("Enceladus", "Breathy"),
    ("Iapetus", "Clear"),
    ("Umbriel", "Easy-going"),
    ("Algieba", "Smooth"),
    ("Despina", "Smooth"),
    ("Erinome", "Clear"),
    ("Algenib", "Gravelly"),
    ("Rasalgethi", "Informative"),
    ("Laomedeia", "Upbeat"),
    ("Achernar", "Soft"),
    ("Alnilam", "Firm"),
    ("Schedar", "Even"),
    ("Gacrux", "Mature"),
    ("Pulcherrima", "Forward"),
    ("Achird", "Friendly"),
    ("Zubenelgenubi", "Casual"),
    ("Vindemiatrix", "Gentle"),
    ("Sadachbia", "Lively"),
    ("Sadaltager", "Knowledgeable"),
    ("Sulafat", "Warm"),
]


class GeminiTTSPreviewService:
    def __init__(self, context):
        self._context = context
        self._shell_preview = bool(
            context.get_service("qt.shell_preview") or context.get_service("qt.gemini_tts_preview_shell_preview")
        ) if context is not None else False
        self._lock = threading.RLock()
        self._settings = {
            "api_key": self._env_value("NC_TTS_GEMINI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"),
            "base_url": self._normalize_base_url(
                self._env_value("NC_TTS_GEMINI_BASE_URL", fallback=DEFAULT_BASE_URL)
            ),
            "model": self._env_value("NC_TTS_GEMINI_MODEL", fallback=DEFAULT_MODEL),
            "voice_name": self._env_value("NC_TTS_GEMINI_VOICE", fallback=DEFAULT_VOICE),
            "language_code": self._env_value("NC_TTS_GEMINI_LANGUAGE_CODE", fallback=DEFAULT_LANGUAGE_CODE),
            "style_prompt": self._env_value("NC_TTS_GEMINI_STYLE_PROMPT", fallback=DEFAULT_STYLE_PROMPT),
        }
        self._output_dir = runtime_paths.runtime_temp_dir("gemini_tts_preview", create=not self._shell_preview)
        if not self._shell_preview:
            self._output_dir.mkdir(parents=True, exist_ok=True)

    def is_shell_preview(self) -> bool:
        return bool(self._shell_preview)

    def _env_value(self, *names: str, fallback: str = "") -> str:
        for name in names:
            value = str(os.environ.get(name, "") or "").strip()
            if value:
                return value
        return str(fallback or "").strip()

    def _normalize_base_url(self, base_url: str) -> str:
        value = str(base_url or "").strip().rstrip("/")
        for suffix in ("/v1beta", "/v1"):
            if value.endswith(suffix):
                value = value[: -len(suffix)]
        return value or DEFAULT_BASE_URL

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._settings)

    def update_settings(self, **changes) -> dict[str, Any]:
        allowed = {"api_key", "base_url", "model", "voice_name", "language_code", "style_prompt"}
        with self._lock:
            for key, value in dict(changes or {}).items():
                if key not in allowed:
                    continue
                text = str(value or "").strip()
                if key == "base_url":
                    text = self._normalize_base_url(text)
                self._settings[key] = text
            return dict(self._settings)

    def export_session_state(self):
        return {"gemini_tts_preview_settings": self.snapshot()}

    def export_preset_state(self):
        state = self.snapshot()
        state.pop("api_key", None)
        return {"gemini_tts_preview_settings": state}

    def import_session_state(self, session):
        payload = dict(session or {})
        state = payload.get("gemini_tts_preview_settings")
        if isinstance(state, dict):
            self.update_settings(**state)
        return None

    def import_preset_state(self, preset):
        payload = dict(preset or {})
        state = payload.get("gemini_tts_preview_settings")
        if isinstance(state, dict):
            state = dict(state)
            state.pop("api_key", None)
            self.update_settings(**state)
        return None

    def close(self):
        return None

    def _api_key(self) -> str:
        with self._lock:
            return str(self._settings.get("api_key") or "").strip()

    def _base_url(self) -> str:
        with self._lock:
            return self._normalize_base_url(self._settings.get("base_url") or DEFAULT_BASE_URL)

    def _model(self) -> str:
        with self._lock:
            return str(self._settings.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL

    def _voice_name(self) -> str:
        with self._lock:
            value = str(self._settings.get("voice_name") or DEFAULT_VOICE).strip()
            return value or DEFAULT_VOICE

    def _language_code(self) -> str:
        with self._lock:
            return str(self._settings.get("language_code") or "").strip()

    def _style_prompt(self) -> str:
        with self._lock:
            return str(self._settings.get("style_prompt") or "").strip()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        api_key = self._api_key()
        if api_key:
            headers["x-goog-api-key"] = api_key
        return headers

    def _request_json(self, method: str, url: str, payload: dict[str, Any] | None = None, *, timeout: float = 60.0):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers=self._headers(),
            method=str(method or "GET").upper(),
        )
        try:
            with urllib.request.urlopen(request, timeout=float(timeout)) as response:
                raw = response.read()
                encoding = response.headers.get_content_charset() or "utf-8"
                return json.loads(raw.decode(encoding, errors="replace"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(self._format_http_error(exc)) from exc

    def _format_http_error(self, exc: urllib.error.HTTPError) -> str:
        try:
            raw = exc.read()
            payload = json.loads(raw.decode("utf-8", errors="replace"))
            if isinstance(payload, dict):
                error_payload = payload.get("error")
                if isinstance(error_payload, dict):
                    message = error_payload.get("message") or error_payload.get("status") or error_payload.get("type")
                    if message:
                        return f"Gemini TTS API HTTP {exc.code}: {message}"
                message = payload.get("message")
                if message:
                    return f"Gemini TTS API HTTP {exc.code}: {message}"
        except Exception:
            pass
        return f"Gemini TTS API HTTP {exc.code}: {getattr(exc, 'reason', '')}"

    def _models_url(self) -> str:
        return f"{self._base_url()}/v1beta/models"

    def _generate_url(self, model: str | None = None) -> str:
        model_id = str(model or self._model() or DEFAULT_MODEL).strip() or DEFAULT_MODEL
        return f"{self._base_url()}/v1beta/models/{urllib.parse.quote(model_id, safe='-_.~')}:generateContent"

    def _model_candidates(self) -> list[str]:
        primary = self._model()
        candidates = [primary]
        if primary.endswith("-tts-preview"):
            alt = primary[: -len("-tts-preview")] + "-preview-tts"
            if alt not in candidates:
                candidates.append(alt)
        elif primary.endswith("-preview-tts"):
            alt = primary[: -len("-preview-tts")] + "-tts-preview"
            if alt not in candidates:
                candidates.append(alt)
        return [candidate for candidate in candidates if candidate]

    def list_models(self, quiet: bool = False) -> list[dict[str, Any]]:
        if self._shell_preview:
            return [{"id": model_id, "label": model_id, "source": "shell_preview"} for model_id in FALLBACK_MODELS]
        if not self._api_key():
            return [{"id": model_id, "label": model_id, "source": "fallback"} for model_id in FALLBACK_MODELS]
        try:
            payload = self._request_json("GET", self._models_url(), timeout=15.0)
            entries = list(payload.get("models") or payload.get("data") or []) if isinstance(payload, dict) else []
            models = []
            for item in entries:
                if not isinstance(item, dict):
                    continue
                model_name = str(item.get("name") or item.get("id") or "").strip()
                if not model_name:
                    continue
                model_id = model_name.rsplit("/", 1)[-1]
                if "tts" not in model_id.lower():
                    continue
                models.append({"id": model_id, "label": str(item.get("displayName") or model_id).strip() or model_id, "source": "gemini_models"})
            return models or [{"id": model_id, "label": model_id, "source": "fallback"} for model_id in FALLBACK_MODELS]
        except Exception as exc:
            if not quiet:
                print(f"Error fetching Gemini TTS models: {exc}")
            return [{"id": model_id, "label": model_id, "source": "fallback"} for model_id in FALLBACK_MODELS]

    def check_connection(self) -> dict[str, Any]:
        if self._shell_preview:
            return {"ok": False, "detail": "Shell preview: Gemini TTS network checks are disabled."}
        if not self._api_key():
            return {"ok": False, "detail": "Gemini API key is required."}
        try:
            payload = self._request_json("GET", self._models_url(), timeout=15.0)
            entries = list(payload.get("models") or payload.get("data") or []) if isinstance(payload, dict) else []
            count = len(entries)
            return {"ok": True, "detail": f"Connected to Gemini TTS ({count} model(s) available)", "model_count": count}
        except Exception as exc:
            return {"ok": False, "detail": str(exc)}

    def _build_payload(self, text: str) -> dict[str, Any]:
        spoken_text = str(text or "").strip()
        if not spoken_text:
            raise RuntimeError("Gemini TTS requires non-empty text.")
        style_prompt = self._style_prompt()
        if style_prompt:
            spoken_text = f"{style_prompt}\n\n{spoken_text}"
        speech_config: dict[str, Any] = {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self._voice_name()}}}
        language_code = self._language_code()
        if language_code:
            speech_config["languageCode"] = language_code
        return {
            "model": f"models/{self._model()}",
            "contents": [{"parts": [{"text": spoken_text}]}],
            "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": speech_config},
        }

    def _extract_inline_audio(self, response: Any) -> bytes:
        if not isinstance(response, dict):
            raise RuntimeError("Gemini TTS returned an unsupported response payload.")
        candidates = list(response.get("candidates") or [])
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content") or {}
            if not isinstance(content, dict):
                continue
            for part in list(content.get("parts") or []):
                if not isinstance(part, dict):
                    continue
                inline = part.get("inlineData") or part.get("inline_data") or {}
                if not isinstance(inline, dict):
                    continue
                audio_b64 = inline.get("data")
                if not audio_b64:
                    continue
                if isinstance(audio_b64, bytes):
                    return bytes(audio_b64)
                try:
                    return base64.b64decode(str(audio_b64))
                except Exception as exc:
                    raise RuntimeError(f"Failed to decode Gemini TTS audio payload: {exc}") from exc
        raise RuntimeError("Gemini TTS response did not contain audio data.")

    def _write_wave(self, raw_audio: bytes) -> Path:
        if self._shell_preview:
            raise RuntimeError("Shell preview: Gemini TTS audio file writes are disabled.")
        target = self._output_dir / f"gemini_tts_{uuid.uuid4().hex}.wav"
        if raw_audio.startswith(b"RIFF") and raw_audio[8:12] == b"WAVE":
            target.write_bytes(raw_audio)
            return target
        with wave.open(str(target), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(raw_audio)
        return target

    def generate(self, text, audio_prompt_path=None, **kwargs):
        if self._shell_preview:
            raise RuntimeError("Shell preview: Gemini TTS generation is disabled.")
        _ = audio_prompt_path
        _ = kwargs
        payload = self._build_payload(text)
        last_error: Exception | None = None
        for model_id in self._model_candidates():
            try:
                response = self._request_json("POST", self._generate_url(model_id), payload, timeout=120.0)
                break
            except RuntimeError as exc:
                last_error = exc
                message = str(exc).lower()
                if "unexpected model name format" in message and model_id != self._model_candidates()[-1]:
                    continue
                raise
        else:
            if last_error is not None:
                raise last_error
        audio_bytes = self._extract_inline_audio(response)
        output_path = self._write_wave(audio_bytes)
        return str(output_path)
