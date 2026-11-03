"""Native QML settings for the Gemini TTS Preview addon."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from ui.qml_bridge.native_contracts import (
    NativeChoice,
    NativeControl,
    NativeControlKind,
    NativeSurface,
)
from ui.qml_bridge.native_registry import NativeSurfaceAdapter


_FALLBACK_MODELS = (
    "gemini-3.1-flash-tts-preview",
    "gemini-2.5-flash-preview-tts",
    "gemini-2.5-pro-preview-tts",
)

_VOICE_OPTIONS = (
    ("Zephyr", "Bright"), ("Puck", "Upbeat"), ("Charon", "Informative"),
    ("Kore", "Firm"), ("Fenrir", "Excitable"), ("Leda", "Youthful"),
    ("Orus", "Firm"), ("Aoede", "Breezy"), ("Callirrhoe", "Easy-going"),
    ("Autonoe", "Bright"), ("Enceladus", "Breathy"), ("Iapetus", "Clear"),
    ("Umbriel", "Easy-going"), ("Algieba", "Smooth"), ("Despina", "Smooth"),
    ("Erinome", "Clear"), ("Algenib", "Gravelly"),
    ("Rasalgethi", "Informative"), ("Laomedeia", "Upbeat"),
    ("Achernar", "Soft"), ("Alnilam", "Firm"), ("Schedar", "Even"),
    ("Gacrux", "Mature"), ("Pulcherrima", "Forward"),
    ("Achird", "Friendly"), ("Zubenelgenubi", "Casual"),
    ("Vindemiatrix", "Gentle"), ("Sadachbia", "Lively"),
    ("Sadaltager", "Knowledgeable"), ("Sulafat", "Warm"),
)


class GeminiTtsNativeAdapter(NativeSurfaceAdapter):
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
        self._status = "Configure a Gemini API key, then check the connection."
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
                str(getattr(failure, "message", "Gemini TTS is unavailable."))
            )
        return result.value

    def snapshot(self) -> NativeSurface:
        settings_value = self._invoke("runtime.gemini_tts.snapshot")
        settings = dict(settings_value or {})
        current_model = str(settings.get("model") or _FALLBACK_MODELS[0])
        models = list(dict.fromkeys([current_model, *self._models]))
        controls = []
        for control in self._surface.controls:
            if control.id == "gemini_tts_intro":
                control = replace(
                    control,
                    value="Cloud TTS preview using Gemini speech models and preset voices.",
                )
            elif control.id == "gemini_tts_status":
                control = replace(control, value=self._status)
            elif control.id == "model":
                control = replace(
                    control,
                    value=current_model,
                    choices=tuple(NativeChoice(value=item, label=item) for item in models),
                )
            elif control.kind not in {NativeControlKind.ACTION, NativeControlKind.DISPLAY}:
                control = replace(
                    control,
                    value=settings.get(control.id, control.default_value),
                )
            controls.append(control)
        return replace(
            self._surface,
            controls=tuple(controls),
            revision=self._revision,
        )

    def set_value(self, control_id: str, value: Any) -> None:
        key = str(control_id or "").strip()
        control = self._controls.get(key)
        if control is None or control.kind in {
            NativeControlKind.ACTION,
            NativeControlKind.DISPLAY,
        }:
            raise KeyError(f"Unknown Gemini TTS setting '{control_id}'.")
        if key == "voice_name":
            allowed = {name for name, _tone in _VOICE_OPTIONS}
            if str(value) not in allowed:
                raise ValueError("Unknown Gemini TTS voice.")
        self._invoke("runtime.gemini_tts.update", {"changes": {key: str(value or "")}})
        self._revision += 1
        if callable(self._persist):
            self._persist()
        self.changed.emit()

    def trigger(self, control_id: str) -> None:
        action = str(control_id or "").strip()
        if action in {"gemini_tts_model_refresh", "gemini_tts_refresh_models"}:
            result = self._invoke("runtime.gemini_tts.models")
            models = []
            for item in list(result or []):
                model_id = str(dict(item or {}).get("id") or "").strip()
                if model_id and model_id not in models:
                    models.append(model_id)
            if models:
                self._models = models
            self._status = f"Gemini model list refreshed ({len(self._models)} model(s))."
        elif action == "gemini_tts_check_connection":
            result = self._invoke("runtime.gemini_tts.check_connection")
            payload = dict(result or {})
            self._status = str(payload.get("detail") or "Connection check finished.")
        else:
            raise KeyError(f"Unknown Gemini TTS action '{control_id}'.")
        self._revision += 1
        self.changed.emit()


def build_gemini_tts_adapter(
    application_facade: Any,
    *,
    persist: Callable[[], object] | None = None,
) -> GeminiTtsNativeAdapter:
    voice_choices = tuple(
        NativeChoice(value=name, label=f"{name} - {tone}")
        for name, tone in _VOICE_OPTIONS
    )
    surface = NativeSurface(
        id="gemini_tts_preview_tab",
        title="Gemini TTS",
        addon_id="nc.gemini_tts_preview",
        sections=("Overview", "Connection", "Voice"),
        description="Configure Google's Gemini preview text-to-speech backend.",
        controls=(
            NativeControl("gemini_tts_intro", "Gemini TTS Preview", NativeControlKind.DISPLAY, "Overview"),
            NativeControl("gemini_tts_status", "Status", NativeControlKind.DISPLAY, "Overview"),
            NativeControl("api_key", "API key", NativeControlKind.TEXT, "Connection", secret=True),
            NativeControl("base_url", "Base URL", NativeControlKind.TEXT, "Connection", default_value="https://generativelanguage.googleapis.com"),
            NativeControl("model", "Model", NativeControlKind.CHOICE, "Connection", default_value=_FALLBACK_MODELS[0], choices=tuple(NativeChoice(value=item, label=item) for item in _FALLBACK_MODELS)),
            NativeControl("gemini_tts_model_refresh", "Refresh model list", NativeControlKind.ACTION, "Connection"),
            NativeControl("voice_name", "Voice", NativeControlKind.CHOICE, "Voice", default_value="Kore", choices=voice_choices),
            NativeControl("language_code", "Language code", NativeControlKind.TEXT, "Voice", description="Optional BCP-47 language code, for example en-US."),
            NativeControl("style_prompt", "Style prompt", NativeControlKind.MULTILINE, "Voice"),
            NativeControl("gemini_tts_check_connection", "Check connection", NativeControlKind.ACTION, "Connection"),
            NativeControl("gemini_tts_refresh_models", "Refresh models", NativeControlKind.ACTION, "Connection"),
        ),
    )
    return GeminiTtsNativeAdapter(
        application_facade,
        surface,
        persist=persist,
    )


__all__ = ["GeminiTtsNativeAdapter", "build_gemini_tts_adapter"]
