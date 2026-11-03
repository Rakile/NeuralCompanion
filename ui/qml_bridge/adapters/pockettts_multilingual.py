"""Native QML settings for the PocketTTS Multilingual provider."""

from __future__ import annotations

from core.pocket_tts_voices import POCKET_TTS_BUILTIN_VOICE_CHOICES
from ui.qml_bridge.adapters.config import RuntimeConfigNativeAdapter
from ui.qml_bridge.native_contracts import (
    NativeControl,
    NativeControlKind,
    NativeSurface,
    choices,
)


_LANGUAGES = (
    ("en", "English"),
    ("fr", "French"),
    ("de", "German"),
    ("es", "Spanish"),
    ("pt", "Portuguese"),
    ("it", "Italian"),
)


def _voice_choices():
    return choices((value, label) for label, value in POCKET_TTS_BUILTIN_VOICE_CHOICES)


def build_pockettts_multilingual_adapter(application_facade, *, persist=None):
    controls = (
        NativeControl(
            "pocket_tts_multilingual_language",
            "Language",
            NativeControlKind.CHOICE,
            section="Language and voice",
            default_value="en",
            choices=choices(_LANGUAGES),
        ),
        NativeControl(
            "pocket_tts_multilingual_builtin_voice",
            "Built-in voice",
            NativeControlKind.CHOICE,
            section="Language and voice",
            default_value="auto",
            choices=_voice_choices(),
        ),
        NativeControl(
            "pocket_tts_multilingual_use_cloned_voice",
            "Use cloned voice",
            NativeControlKind.BOOLEAN,
            section="Language and voice",
            default_value=True,
        ),
        NativeControl(
            "pocket_tts_multilingual_prewarm_on_start",
            "Prewarm on runtime start",
            NativeControlKind.BOOLEAN,
            section="Startup",
            default_value=True,
        ),
        NativeControl(
            "pocket_tts_multilingual_temperature",
            "Temperature",
            NativeControlKind.NUMBER,
            section="Generation",
            default_value=0.7,
            minimum=0.05,
            maximum=2.0,
            step=0.05,
        ),
        NativeControl(
            "pocket_tts_multilingual_lsd_decode_steps",
            "LSD decode steps",
            NativeControlKind.INTEGER,
            section="Generation",
            default_value=1,
            minimum=1,
            maximum=64,
        ),
        NativeControl(
            "pocket_tts_multilingual_eos_threshold",
            "End-of-speech threshold",
            NativeControlKind.NUMBER,
            section="Generation",
            default_value=-4.0,
            minimum=-20.0,
            maximum=10.0,
            step=0.1,
        ),
        NativeControl(
            "pocket_tts_multilingual_frames_after_eos",
            "Frames after end-of-speech",
            NativeControlKind.INTEGER,
            section="Generation",
            default_value=0,
            minimum=0,
            maximum=100,
        ),
    )
    return RuntimeConfigNativeAdapter(
        application_facade,
        NativeSurface(
            id="pockettts_multilingual_tts_tab",
            addon_id="nc.pockettts_multilingual_tts",
            title="PocketTTS Multilingual",
            description="PocketTTS multilingual voice and generation settings.",
            sections=("Language and voice", "Startup", "Generation"),
            controls=controls,
        ),
        persist=persist,
    )


__all__ = ["build_pockettts_multilingual_adapter"]
