"""Native QML settings for the ElevenLabs TTS addon."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from ui.qml_bridge.native_contracts import (
    NativeChoice,
    NativeControl,
    NativeControlKind,
    NativeSurface,
)
from ui.qml_bridge.native_registry import NativeSurfaceAdapter

_MODEL_LABELS = {
    "eleven_flash_v2_5": "Eleven Flash v2.5 - Fastest",
    "eleven_v3_conversational": "Eleven v3 Conversational - Expressive realtime",
    "eleven_multilingual_v2": "Eleven Multilingual v2 - Higher latency, stable long-form",
    "eleven_v3": "Eleven v3 - Slowest, highest quality",
}
_FALLBACK_MODELS = tuple(
    (model_id, _MODEL_LABELS[model_id])
    for model_id in (
        "eleven_flash_v2_5",
        "eleven_multilingual_v2",
        "eleven_v3",
    )
)

_DELIVERY_SLIDER_SCALE = 100
_DELIVERY_SLIDERS = frozenset({"stability", "similarity_boost", "style", "speed"})


def _model_label(model_id: str, provider_label: str) -> str:
    return _MODEL_LABELS.get(model_id) or provider_label or model_id


def _status_for_model(status: str, model_id: str) -> str:
    if model_id != "eleven_v3":
        return status
    return (
        f"{status} Eleven v3 prioritizes maximum quality and can start more slowly. "
        "Choose Eleven Flash v2.5 for faster conversational playback."
    )


class ElevenLabsTtsNativeAdapter(NativeSurfaceAdapter):
    def __init__(
        self,
        application_facade: Any,
        surface: NativeSurface,
        *,
        persist: Callable[[], object] | None = None,
        parent=None,
    ) -> None:
        super().__init__(surface.id, surface.addon_id, parent)
        self._application = application_facade
        self._surface = surface
        self._controls = {control.id: control for control in surface.controls}
        self._persist = persist
        self._models = list(_FALLBACK_MODELS)
        self._voices: list[tuple[str, str]] = []
        self._status = "Enter an ElevenLabs API key, then refresh voices."
        self._revision = 0

    def _invoke(self, capability: str, payload=None) -> object:
        result = self._application.addons.invoke_addon_capability(
            self.addon_id,
            capability,
            dict(payload or {}),
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            raise RuntimeError(
                str(getattr(failure, "message", "ElevenLabs TTS is unavailable."))
            )
        return result.value

    def snapshot(self) -> NativeSurface:
        settings = dict(self._invoke("runtime.elevenlabs_tts.snapshot") or {})
        current_model = str(settings.get("model") or _FALLBACK_MODELS[0][0])
        current_voice = str(settings.get("voice_id") or "")
        model_choices = list(self._models)
        if current_model and current_model not in {
            value for value, _label in model_choices
        }:
            model_choices.insert(0, (current_model, current_model))
        voice_choices = list(self._voices)
        if current_voice and current_voice not in {
            value for value, _label in voice_choices
        }:
            voice_choices.insert(0, (current_voice, current_voice))
        if not voice_choices:
            voice_choices = [("", "Refresh voices to choose")]

        controls = []
        for control in self._surface.controls:
            if control.id == "elevenlabs_tts_intro":
                control = replace(
                    control,
                    value="Cloud text-to-speech using voices from your ElevenLabs account.",
                )
            elif control.id == "elevenlabs_tts_status":
                control = replace(
                    control,
                    value=_status_for_model(self._status, current_model),
                )
            elif control.id == "model":
                control = replace(
                    control,
                    value=current_model,
                    choices=tuple(
                        NativeChoice(value=value, label=label)
                        for value, label in model_choices
                    ),
                )
            elif control.id == "voice_id":
                control = replace(
                    control,
                    value=current_voice,
                    choices=tuple(
                        NativeChoice(value=value, label=label)
                        for value, label in voice_choices
                    ),
                )
            elif control.id in _DELIVERY_SLIDERS:
                fallback = float(control.default_value) / _DELIVERY_SLIDER_SCALE
                control = replace(
                    control,
                    value=round(
                        float(settings.get(control.id, fallback))
                        * _DELIVERY_SLIDER_SCALE
                    ),
                )
            elif control.kind not in {
                NativeControlKind.ACTION,
                NativeControlKind.DISPLAY,
            }:
                control = replace(
                    control,
                    value=settings.get(control.id, control.default_value),
                )
            controls.append(control)
        return replace(self._surface, controls=tuple(controls), revision=self._revision)

    def set_value(self, control_id: str, value: Any) -> None:
        key = str(control_id or "").strip()
        control = self._controls.get(key)
        if control is None or control.kind in {
            NativeControlKind.ACTION,
            NativeControlKind.DISPLAY,
        }:
            raise KeyError(f"Unknown ElevenLabs TTS setting '{control_id}'.")
        if key in _DELIVERY_SLIDERS:
            normalized: object = float(value) / _DELIVERY_SLIDER_SCALE
        elif control.kind in {NativeControlKind.NUMBER, NativeControlKind.SLIDER}:
            normalized = float(value)
        elif control.kind is NativeControlKind.BOOLEAN:
            normalized = bool(value)
        else:
            normalized = str(value or "")
        self._invoke(
            "runtime.elevenlabs_tts.update",
            {"changes": {key: normalized}},
        )
        self._revision += 1
        if callable(self._persist):
            self._persist()
        self.changed.emit()

    def trigger(self, control_id: str) -> None:
        action = str(control_id or "").strip()
        if action == "elevenlabs_tts_refresh_voices":
            result = self._invoke("runtime.elevenlabs_tts.voices")
            self._voices = [
                (
                    str(item.get("id") or ""),
                    str(item.get("label") or item.get("id") or ""),
                )
                for item in (dict(value or {}) for value in list(result or []))
                if str(item.get("id") or "").strip()
            ]
            self._status = (
                f"ElevenLabs voice list refreshed ({len(self._voices)} voice(s))."
            )
        elif action == "elevenlabs_tts_refresh_models":
            result = self._invoke("runtime.elevenlabs_tts.models")
            models = [
                (
                    str(item.get("id") or ""),
                    _model_label(
                        str(item.get("id") or ""),
                        str(item.get("label") or item.get("id") or ""),
                    ),
                )
                for item in (dict(value or {}) for value in list(result or []))
                if str(item.get("id") or "").strip()
            ]
            if models:
                self._models = models
            self._status = f"ElevenLabs model list refreshed ({len(models)} model(s))."
        elif action == "elevenlabs_tts_check_connection":
            result = dict(self._invoke("runtime.elevenlabs_tts.check_connection") or {})
            self._status = str(result.get("detail") or "Connection check finished.")
        else:
            raise KeyError(f"Unknown ElevenLabs TTS action '{control_id}'.")
        self._revision += 1
        self.changed.emit()


def build_elevenlabs_tts_adapter(
    application_facade: Any,
    *,
    persist: Callable[[], object] | None = None,
) -> ElevenLabsTtsNativeAdapter:
    surface = NativeSurface(
        id="elevenlabs_tts_tab",
        title="ElevenLabs TTS",
        addon_id="nc.elevenlabs_tts",
        sections=("Connection", "Voice", "Delivery"),
        description="Configure the ElevenLabs cloud text-to-speech backend.",
        controls=(
            NativeControl(
                "elevenlabs_tts_intro",
                "ElevenLabs TTS",
                NativeControlKind.DISPLAY,
                "Connection",
            ),
            NativeControl(
                "elevenlabs_tts_status",
                "Status",
                NativeControlKind.DISPLAY,
                "Connection",
            ),
            NativeControl(
                "api_key", "API key", NativeControlKind.TEXT, "Connection", secret=True
            ),
            NativeControl(
                "base_url",
                "Base URL",
                NativeControlKind.TEXT,
                "Connection",
                default_value="https://api.elevenlabs.io",
            ),
            NativeControl(
                "elevenlabs_tts_check_connection",
                "Check connection",
                NativeControlKind.ACTION,
                "Connection",
                metadata={"actionStrip": True, "compactActionWidth": 180},
            ),
            NativeControl(
                "model",
                "Model",
                NativeControlKind.CHOICE,
                "Voice",
                description="Flash v2.5 starts fastest; Eleven v3 prioritizes expression and quality.",
                default_value=_FALLBACK_MODELS[0][0],
                choices=tuple(
                    NativeChoice(value=value, label=label)
                    for value, label in _FALLBACK_MODELS
                ),
            ),
            NativeControl(
                "elevenlabs_tts_refresh_models",
                "Refresh models",
                NativeControlKind.ACTION,
                "Voice",
                metadata={"actionStrip": True, "compactActionWidth": 180},
            ),
            NativeControl(
                "voice_id",
                "Voice",
                NativeControlKind.CHOICE,
                "Voice",
                default_value="",
                choices=(NativeChoice(value="", label="Refresh voices to choose"),),
            ),
            NativeControl(
                "elevenlabs_tts_refresh_voices",
                "Refresh voices",
                NativeControlKind.ACTION,
                "Voice",
                metadata={"actionStrip": True, "compactActionWidth": 180},
            ),
            NativeControl(
                "language_code",
                "Language code",
                NativeControlKind.TEXT,
                "Voice",
                description="Optional ISO 639-1 language code.",
            ),
            NativeControl(
                "stability",
                "Stability",
                NativeControlKind.SLIDER,
                "Delivery",
                default_value=50,
                minimum=0,
                maximum=100,
                step=1,
                metadata={
                    "displayScale": 100,
                    "preciseEditor": True,
                    "deferredCommit": True,
                },
            ),
            NativeControl(
                "similarity_boost",
                "Similarity",
                NativeControlKind.SLIDER,
                "Delivery",
                default_value=75,
                minimum=0,
                maximum=100,
                step=1,
                metadata={
                    "displayScale": 100,
                    "preciseEditor": True,
                    "deferredCommit": True,
                },
            ),
            NativeControl(
                "style",
                "Style exaggeration",
                NativeControlKind.SLIDER,
                "Delivery",
                default_value=0,
                minimum=0,
                maximum=100,
                step=1,
                metadata={
                    "displayScale": 100,
                    "preciseEditor": True,
                    "deferredCommit": True,
                },
            ),
            NativeControl(
                "speed",
                "Speed",
                NativeControlKind.SLIDER,
                "Delivery",
                default_value=100,
                minimum=70,
                maximum=120,
                step=1,
                metadata={
                    "displayScale": 100,
                    "preciseEditor": True,
                    "deferredCommit": True,
                },
            ),
            NativeControl(
                "use_speaker_boost",
                "Speaker boost",
                NativeControlKind.BOOLEAN,
                "Delivery",
                default_value=True,
            ),
        ),
    )
    return ElevenLabsTtsNativeAdapter(
        application_facade,
        surface,
        persist=persist,
    )


__all__ = ["ElevenLabsTtsNativeAdapter", "build_elevenlabs_tts_adapter"]
