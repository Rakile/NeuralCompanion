from __future__ import annotations

import base64
import json
import os
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtWidgets


DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"
DEFAULT_MODEL = "gemini-2.5-flash-preview-tts"
DEFAULT_VOICE = "Kore"
DEFAULT_LANGUAGE_CODE = ""
DEFAULT_STYLE_PROMPT = ""

FALLBACK_MODELS = [
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
        self._output_dir = Path(tempfile.gettempdir()) / "NeuralInterface" / "gemini_tts_preview"
        self._output_dir.mkdir(parents=True, exist_ok=True)

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
        return {
            "gemini_tts_preview_settings": self.snapshot(),
        }

    def import_session_state(self, session):
        payload = dict(session or {})
        state = payload.get("gemini_tts_preview_settings")
        if isinstance(state, dict):
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
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
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

    def list_models(self, quiet: bool = False) -> list[dict[str, Any]]:
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
                models.append(
                    {
                        "id": model_id,
                        "label": str(item.get("displayName") or model_id).strip() or model_id,
                        "source": "gemini_models",
                    }
                )
            return models or [{"id": model_id, "label": model_id, "source": "fallback"} for model_id in FALLBACK_MODELS]
        except Exception as exc:
            if not quiet:
                print(f"Error fetching Gemini TTS models: {exc}")
            return [{"id": model_id, "label": model_id, "source": "fallback"} for model_id in FALLBACK_MODELS]

    def check_connection(self) -> dict[str, Any]:
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
        speech_config: dict[str, Any] = {
            "voiceConfig": {
                "prebuiltVoiceConfig": {
                    "voiceName": self._voice_name(),
                }
            }
        }
        language_code = self._language_code()
        if language_code:
            speech_config["languageCode"] = language_code
        return {
            "model": self._model(),
            "contents": [{"parts": [{"text": spoken_text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": speech_config,
            },
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
        _ = audio_prompt_path
        _ = kwargs
        payload = self._build_payload(text)
        response = self._request_json("POST", self._generate_url(), payload, timeout=120.0)
        audio_bytes = self._extract_inline_audio(response)
        output_path = self._write_wave(audio_bytes)
        return str(output_path)


class GeminiTTSPreviewController(QtCore.QObject):
    def __init__(self, context, service: GeminiTTSPreviewService):
        super().__init__()
        self.context = context
        self.service = service
        self._widget = None

    def build_tab(self):
        if self._widget is not None:
            return self._widget

        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        intro = QtWidgets.QLabel(
            "Gemini preview TTS backend. Select this backend in Chat Runtime, then tune model, voice, and prompt style here."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #cbd5e1;")
        layout.addWidget(intro)

        card = QtWidgets.QFrame()
        card.setObjectName("gemini_tts_preview_card")
        card.setStyleSheet(
            "QFrame#gemini_tts_preview_card {"
            "  background: rgba(12, 18, 26, 0.35);"
            "  border: 1px solid #273342;"
            "  border-radius: 10px;"
            "}"
        )
        card_layout = QtWidgets.QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(10)

        self.status_label = QtWidgets.QLabel("Gemini TTS backend idle.")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        card_layout.addWidget(self.status_label)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignLeft)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)

        self.api_key_edit = QtWidgets.QLineEdit()
        self.api_key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("GEMINI_API_KEY or GOOGLE_API_KEY")
        self.api_key_edit.setText(self.service.snapshot().get("api_key", ""))
        self.api_key_edit.textChanged.connect(lambda text: self._update_setting("api_key", text))
        form.addRow("API Key", self.api_key_edit)

        self.base_url_edit = QtWidgets.QLineEdit()
        self.base_url_edit.setPlaceholderText(DEFAULT_BASE_URL)
        self.base_url_edit.setText(self.service.snapshot().get("base_url", DEFAULT_BASE_URL))
        self.base_url_edit.textChanged.connect(lambda text: self._update_setting("base_url", text))
        form.addRow("Base URL", self.base_url_edit)

        model_row = QtWidgets.QHBoxLayout()
        self.model_combo = QtWidgets.QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        model_row.addWidget(self.model_combo, 1)
        self.refresh_models_button = QtWidgets.QPushButton("Refresh")
        self.refresh_models_button.clicked.connect(self.refresh_models)
        model_row.addWidget(self.refresh_models_button)
        model_widget = QtWidgets.QWidget()
        model_widget.setLayout(model_row)
        form.addRow("Model", model_widget)

        self.voice_combo = QtWidgets.QComboBox()
        for voice_name, tone in VOICE_OPTIONS:
            self.voice_combo.addItem(f"{voice_name} - {tone}", voice_name)
        voice_index = self.voice_combo.findData(self.service.snapshot().get("voice_name", DEFAULT_VOICE))
        if voice_index >= 0:
            self.voice_combo.setCurrentIndex(voice_index)
        self.voice_combo.currentIndexChanged.connect(self._on_voice_changed)
        self.voice_combo.currentTextChanged.connect(lambda _text: self._on_voice_changed(self.voice_combo.currentIndex()))
        form.addRow("Voice", self.voice_combo)

        self.language_code_edit = QtWidgets.QLineEdit()
        self.language_code_edit.setPlaceholderText("Optional BCP-47 language code, e.g. en-US")
        self.language_code_edit.setText(self.service.snapshot().get("language_code", ""))
        self.language_code_edit.textChanged.connect(lambda text: self._update_setting("language_code", text))
        form.addRow("Language", self.language_code_edit)

        self.style_prompt_edit = QtWidgets.QPlainTextEdit()
        self.style_prompt_edit.setPlaceholderText("Optional style prompt such as 'Speak like a calm friendly narrator.'")
        self.style_prompt_edit.setPlainText(self.service.snapshot().get("style_prompt", DEFAULT_STYLE_PROMPT))
        self.style_prompt_edit.textChanged.connect(self._on_style_prompt_changed)
        self.style_prompt_edit.setMinimumHeight(100)
        form.addRow("Style Prompt", self.style_prompt_edit)

        card_layout.addLayout(form)

        button_row = QtWidgets.QHBoxLayout()
        self.check_button = QtWidgets.QPushButton("Check Connection")
        self.check_button.clicked.connect(self.check_connection)
        button_row.addWidget(self.check_button)
        self.refresh_button = QtWidgets.QPushButton("Refresh Models")
        self.refresh_button.clicked.connect(self.refresh_models)
        button_row.addWidget(self.refresh_button)
        button_row.addStretch(1)
        card_layout.addLayout(button_row)

        layout.addWidget(card)
        layout.addStretch(1)

        self._widget = widget
        self.refresh_models()
        self.check_connection()
        return widget

    def _update_setting(self, key: str, value: str):
        self.service.update_settings(**{key: value})

    def _on_model_changed(self, value: str):
        current_data = str(self.model_combo.currentData() or "").strip()
        candidate = current_data or str(value or self.model_combo.currentText() or "").strip()
        if candidate:
            self.service.update_settings(model=candidate)

    def _on_voice_changed(self, _index: int):
        value = str(self.voice_combo.currentData() or self.voice_combo.currentText() or "").strip()
        if value:
            self.service.update_settings(voice_name=value)

    def _on_style_prompt_changed(self):
        self.service.update_settings(style_prompt=self.style_prompt_edit.toPlainText())

    def refresh_models(self):
        current_value = str(self.model_combo.currentText() or self.service.snapshot().get("model", DEFAULT_MODEL) or DEFAULT_MODEL).strip()
        self.model_combo.blockSignals(True)
        try:
            self.model_combo.clear()
            models = self.service.list_models(quiet=False)
            seen = set()
            for item in models:
                model_id = str(item.get("id") or "").strip()
                if not model_id or model_id in seen:
                    continue
                label = str(item.get("label") or model_id).strip() or model_id
                self.model_combo.addItem(label, model_id)
                seen.add(model_id)
            if self.model_combo.count() == 0:
                self.model_combo.addItem(DEFAULT_MODEL, DEFAULT_MODEL)
            index = self.model_combo.findData(current_value)
            if index < 0:
                index = self.model_combo.findData(DEFAULT_MODEL)
            if index < 0:
                index = 0
            self.model_combo.setCurrentIndex(index)
        finally:
            self.model_combo.blockSignals(False)
        self.service.update_settings(model=str(self.model_combo.currentData() or self.model_combo.currentText() or DEFAULT_MODEL))
        self._set_status("Gemini model list refreshed.")

    def check_connection(self):
        result = self.service.check_connection()
        if isinstance(result, dict) and result.get("ok"):
            self._set_status(str(result.get("detail") or "Connected."))
        else:
            self._set_status(str(result.get("detail") if isinstance(result, dict) else result))
        return result

    def _set_status(self, text: str):
        if hasattr(self, "status_label") and self.status_label is not None:
            self.status_label.setText(str(text or "").strip())

    def export_session_state(self):
        return self.service.export_session_state()

    def import_session_state(self, session):
        self.service.import_session_state(session)
        state = self.service.snapshot()
        if hasattr(self, "api_key_edit"):
            self.api_key_edit.blockSignals(True)
            self.api_key_edit.setText(state.get("api_key", ""))
            self.api_key_edit.blockSignals(False)
        if hasattr(self, "base_url_edit"):
            self.base_url_edit.blockSignals(True)
            self.base_url_edit.setText(state.get("base_url", DEFAULT_BASE_URL))
            self.base_url_edit.blockSignals(False)
        if hasattr(self, "language_code_edit"):
            self.language_code_edit.blockSignals(True)
            self.language_code_edit.setText(state.get("language_code", ""))
            self.language_code_edit.blockSignals(False)
        if hasattr(self, "style_prompt_edit"):
            self.style_prompt_edit.blockSignals(True)
            self.style_prompt_edit.setPlainText(state.get("style_prompt", DEFAULT_STYLE_PROMPT))
            self.style_prompt_edit.blockSignals(False)
        if hasattr(self, "voice_combo"):
            voice_index = self.voice_combo.findData(state.get("voice_name", DEFAULT_VOICE))
            if voice_index >= 0:
                self.voice_combo.setCurrentIndex(voice_index)
        if hasattr(self, "model_combo"):
            model_index = self.model_combo.findData(state.get("model", DEFAULT_MODEL))
            if model_index >= 0:
                self.model_combo.setCurrentIndex(model_index)
        return None

    def import_preset_state(self, preset):
        self.service.import_preset_state(preset)
        state = self.service.snapshot()
        if hasattr(self, "base_url_edit"):
            self.base_url_edit.blockSignals(True)
            self.base_url_edit.setText(state.get("base_url", DEFAULT_BASE_URL))
            self.base_url_edit.blockSignals(False)
        if hasattr(self, "language_code_edit"):
            self.language_code_edit.blockSignals(True)
            self.language_code_edit.setText(state.get("language_code", ""))
            self.language_code_edit.blockSignals(False)
        if hasattr(self, "style_prompt_edit"):
            self.style_prompt_edit.blockSignals(True)
            self.style_prompt_edit.setPlainText(state.get("style_prompt", DEFAULT_STYLE_PROMPT))
            self.style_prompt_edit.blockSignals(False)
        if hasattr(self, "voice_combo"):
            voice_index = self.voice_combo.findData(state.get("voice_name", DEFAULT_VOICE))
            if voice_index >= 0:
                self.voice_combo.setCurrentIndex(voice_index)
        if hasattr(self, "model_combo"):
            model_index = self.model_combo.findData(state.get("model", DEFAULT_MODEL))
            if model_index >= 0:
                self.model_combo.setCurrentIndex(model_index)
        return None

    def shutdown(self):
        self._widget = None
        return None
