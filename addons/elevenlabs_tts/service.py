from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import numpy as np

from core.tts_session_schema import with_flat_tts_runtime_settings

DEFAULT_BASE_URL = "https://api.elevenlabs.io"
DEFAULT_MODEL = "eleven_flash_v2_5"
DEFAULT_OUTPUT_FORMAT = "pcm_24000"
DEFAULT_SAMPLE_RATE = 24000


class ElevenLabsTTSService:
    sr = DEFAULT_SAMPLE_RATE

    def __init__(self, context) -> None:
        self._context = context
        shell_session = getattr(getattr(context, "capabilities", None), "shell_session", None)
        self._shell_preview = bool(getattr(shell_session, "preview", False))
        self._lock = threading.RLock()
        self._settings: dict[str, Any] = {
            "api_key": "",
            "base_url": DEFAULT_BASE_URL,
            "model": DEFAULT_MODEL,
            "voice_id": "",
            "language_code": "",
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.0,
            "speed": 1.0,
            "use_speaker_boost": True,
        }

    @staticmethod
    def _normalize_base_url(value: object) -> str:
        base_url = str(value or "").strip().rstrip("/")
        base_url = base_url.removesuffix("/v1")
        return base_url or DEFAULT_BASE_URL

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._settings)

    @staticmethod
    def _bounded_float(value: object, fallback: float, minimum: float, maximum: float) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = fallback
        return max(minimum, min(maximum, numeric))

    @staticmethod
    def _boolean(value: object) -> bool:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"false", "0", "no", "off"}:
                return False
            if normalized in {"true", "1", "yes", "on"}:
                return True
        return bool(value)

    def update_settings(self, **changes) -> dict[str, Any]:
        float_fields = {"stability", "similarity_boost", "style", "speed"}
        text_fields = {"api_key", "base_url", "model", "voice_id", "language_code"}
        with self._lock:
            for key, value in dict(changes or {}).items():
                if key in float_fields:
                    minimum, maximum = (0.7, 1.2) if key == "speed" else (0.0, 1.0)
                    self._settings[key] = self._bounded_float(
                        value,
                        float(self._settings[key]),
                        minimum,
                        maximum,
                    )
                elif key == "use_speaker_boost":
                    self._settings[key] = self._boolean(value)
                elif key in text_fields:
                    text = str(value or "").strip()
                    self._settings[key] = (
                        self._normalize_base_url(text) if key == "base_url" else text
                    )
            return dict(self._settings)

    def export_session_state(self) -> dict[str, Any]:
        return {"elevenlabs_tts_settings": self.snapshot()}

    def export_preset_state(self) -> dict[str, Any]:
        state = self.snapshot()
        state.pop("api_key", None)
        return {"elevenlabs_tts_settings": state}

    def import_session_state(self, session) -> None:
        payload = with_flat_tts_runtime_settings(session or {})
        settings = payload.get("elevenlabs_tts_settings")
        if isinstance(settings, dict):
            self.update_settings(**settings)

    def import_preset_state(self, preset) -> None:
        payload = with_flat_tts_runtime_settings(preset or {})
        settings = payload.get("elevenlabs_tts_settings")
        if isinstance(settings, dict):
            safe_settings = dict(settings)
            safe_settings.pop("api_key", None)
            self.update_settings(**safe_settings)

    def close(self) -> None:
        return None

    def _headers(self) -> dict[str, str]:
        api_key = str(self.snapshot().get("api_key") or "").strip()
        if not api_key:
            raise RuntimeError("ElevenLabs API key is required.")
        return {
            "Content-Type": "application/json",
            "Accept": "audio/pcm",
            "xi-api-key": api_key,
        }

    def _synthesis_url(self, voice_id: str) -> str:
        base_url = self._normalize_base_url(self.snapshot().get("base_url"))
        encoded_voice = urllib.parse.quote(str(voice_id), safe="-_.~")
        return f"{base_url}/v1/text-to-speech/{encoded_voice}?output_format={DEFAULT_OUTPUT_FORMAT}"

    def _request_json(self, url: str, *, timeout: float = 15.0) -> Any:
        request = urllib.request.Request(
            url,
            headers={**self._headers(), "Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                encoding = response.headers.get_content_charset() or "utf-8"
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"ElevenLabs API HTTP {exc.code}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach ElevenLabs: {exc.reason}") from exc
        try:
            return json.loads(raw.decode(encoding, errors="replace"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("ElevenLabs API returned invalid JSON.") from exc

    def list_voices(self, quiet: bool = False) -> list[dict[str, Any]]:
        if self._shell_preview or not str(self.snapshot().get("api_key") or "").strip():
            return []
        try:
            base_url = self._normalize_base_url(self.snapshot().get("base_url"))
            voices = []
            next_page_token = ""
            for _page in range(100):
                url = f"{base_url}/v2/voices?page_size=100"
                if next_page_token:
                    url += "&next_page_token=" + urllib.parse.quote(
                        next_page_token, safe="-_.~"
                    )
                payload = self._request_json(url)
                items = (
                    list(payload.get("voices") or [])
                    if isinstance(payload, dict)
                    else []
                )
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    voice_id = str(item.get("voice_id") or "").strip()
                    if not voice_id:
                        continue
                    name = str(item.get("name") or voice_id).strip() or voice_id
                    labels = item.get("labels") if isinstance(item.get("labels"), dict) else {}
                    accent = str(labels.get("accent") or "").strip()
                    voices.append(
                        {
                            "id": voice_id,
                            "label": f"{name} - {accent}" if accent else name,
                            "category": str(item.get("category") or "").strip(),
                        }
                    )
                next_page_token = (
                    str(payload.get("next_page_token") or "").strip()
                    if isinstance(payload, dict) and bool(payload.get("has_more"))
                    else ""
                )
                if not next_page_token:
                    break
            return voices
        except RuntimeError as exc:
            if not quiet:
                print(f"Error fetching ElevenLabs voices: {exc}")
            return []

    def list_models(self, quiet: bool = False) -> list[dict[str, str]]:
        if self._shell_preview or not str(self.snapshot().get("api_key") or "").strip():
            return []
        try:
            base_url = self._normalize_base_url(self.snapshot().get("base_url"))
            payload = self._request_json(f"{base_url}/v1/models")
            models = []
            for item in list(payload or []) if isinstance(payload, list) else []:
                if not isinstance(item, dict) or not bool(item.get("can_do_text_to_speech")):
                    continue
                model_id = str(item.get("model_id") or "").strip()
                if not model_id:
                    continue
                models.append(
                    {
                        "id": model_id,
                        "label": str(item.get("name") or model_id).strip() or model_id,
                    }
                )
            return models
        except RuntimeError as exc:
            if not quiet:
                print(f"Error fetching ElevenLabs models: {exc}")
            return []

    def check_connection(self) -> dict[str, Any]:
        if self._shell_preview:
            return {
                "ok": False,
                "detail": "Shell preview: ElevenLabs TTS network checks are disabled.",
            }
        if not str(self.snapshot().get("api_key") or "").strip():
            return {"ok": False, "detail": "ElevenLabs API key is required."}
        try:
            base_url = self._normalize_base_url(self.snapshot().get("base_url"))
            payload = self._request_json(f"{base_url}/v2/voices?page_size=1")
            voices = list(payload.get("voices") or []) if isinstance(payload, dict) else []
            voice_count = (
                int(payload.get("total_count"))
                if isinstance(payload, dict) and payload.get("total_count") is not None
                else len(voices)
            )
            return {
                "ok": True,
                "detail": f"Connected to ElevenLabs ({voice_count} voice(s) available)",
                "voice_count": voice_count,
            }
        except RuntimeError as exc:
            return {"ok": False, "detail": str(exc)}

    def _payload(self, text: str) -> dict[str, Any]:
        settings = self.snapshot()
        payload: dict[str, Any] = {
            "text": str(text or "").strip(),
            "model_id": str(settings.get("model") or DEFAULT_MODEL),
            "voice_settings": {
                "stability": float(settings.get("stability", 0.5)),
                "similarity_boost": float(settings.get("similarity_boost", 0.75)),
                "style": float(settings.get("style", 0.0)),
                "speed": float(settings.get("speed", 1.0)),
                "use_speaker_boost": bool(settings.get("use_speaker_boost", True)),
            },
        }
        language_code = str(settings.get("language_code") or "").strip()
        if language_code:
            payload["language_code"] = language_code
        return payload

    @staticmethod
    def _decode_pcm(audio: bytes, content_type: str) -> np.ndarray:
        media_type = str(content_type or "").strip().lower()
        if media_type and not (
            media_type.startswith("audio/")
            or media_type in {"application/octet-stream", "binary/octet-stream"}
        ):
            raise RuntimeError(
                f"ElevenLabs TTS returned a non-audio response ({media_type})."
            )
        if not audio:
            raise RuntimeError("ElevenLabs TTS returned empty audio.")
        if not media_type or media_type in {
            "application/octet-stream",
            "binary/octet-stream",
        }:
            probe = audio[:4096].lstrip()
            structured = False
            if probe.startswith((b"{", b"[")):
                try:
                    json.loads(probe.decode("utf-8"))
                    structured = True
                except (UnicodeDecodeError, json.JSONDecodeError):
                    pass
            elif probe.lower().startswith((b"<!doctype", b"<html", b"<?xml")):
                structured = True
            if structured:
                raise RuntimeError("ElevenLabs TTS returned a non-audio response body.")
        if len(audio) % 2:
            raise RuntimeError("ElevenLabs TTS returned malformed 16-bit PCM audio.")
        return np.frombuffer(audio, dtype="<i2").astype(np.float32) / 32768.0

    def generate(self, text, audio_prompt_path=None, **kwargs) -> dict[str, Any]:
        del audio_prompt_path, kwargs
        if self._shell_preview:
            raise RuntimeError("Shell preview: ElevenLabs TTS generation is disabled.")
        spoken_text = str(text or "").strip()
        if not spoken_text:
            raise RuntimeError("ElevenLabs TTS requires non-empty text.")
        settings = self.snapshot()
        voice_id = str(settings.get("voice_id") or "").strip()
        if not voice_id:
            raise RuntimeError("ElevenLabs voice selection is required.")
        request = urllib.request.Request(
            self._synthesis_url(voice_id),
            data=json.dumps(self._payload(spoken_text)).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120.0) as response:
                audio = response.read()
                content_type = response.headers.get_content_type()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"ElevenLabs API HTTP {exc.code}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach ElevenLabs: {exc.reason}") from exc
        return {
            "wav": self._decode_pcm(audio, content_type),
            "sample_rate": DEFAULT_SAMPLE_RATE,
        }
