"""Native QML settings for the PocketTTS provider."""

from __future__ import annotations

from core.pocket_tts_voices import POCKET_TTS_BUILTIN_VOICE_CHOICES
from ui.qml_bridge.adapters.config import RuntimeConfigNativeAdapter
from ui.qml_bridge.native_contracts import (
    NativeControl,
    NativeControlKind,
    NativeSurface,
    choices,
)


def _voice_choices():
    return choices((value, label) for label, value in POCKET_TTS_BUILTIN_VOICE_CHOICES)


def build_pockettts_adapter(application_facade, *, persist=None):
    controls = (
        NativeControl(
            "pocket_tts_builtin_voice",
            "Built-in voice",
            NativeControlKind.CHOICE,
            section="Voice",
            default_value="auto",
            choices=_voice_choices(),
        ),
        NativeControl(
            "pocket_tts_use_cloned_voice",
            "Use cloned voice",
            NativeControlKind.BOOLEAN,
            section="Voice",
            default_value=True,
        ),
        NativeControl(
            "pocket_tts_prewarm_on_start",
            "Prewarm on runtime start",
            NativeControlKind.BOOLEAN,
            section="Startup",
            default_value=True,
        ),
        NativeControl(
            "pocket_tts_temperature",
            "Temperature",
            NativeControlKind.NUMBER,
            section="Advanced generation",
            default_value=0.7,
            minimum=0.05,
            maximum=2.0,
            step=0.05,
        ),
        NativeControl(
            "pocket_tts_lsd_decode_steps",
            "LSD decode steps",
            NativeControlKind.INTEGER,
            section="Advanced generation",
            default_value=1,
            minimum=1,
            maximum=64,
        ),
        NativeControl(
            "pocket_tts_eos_threshold",
            "End-of-speech threshold",
            NativeControlKind.NUMBER,
            section="Advanced generation",
            default_value=-4.0,
            minimum=-20.0,
            maximum=10.0,
            step=0.1,
        ),
        NativeControl(
            "pocket_tts_frames_after_eos",
            "Frames after end-of-speech",
            NativeControlKind.INTEGER,
            section="Advanced generation",
            default_value=0,
            minimum=0,
            maximum=100,
        ),
        NativeControl(
            "pocket_tts_python",
            "PocketTTS Python override",
            NativeControlKind.TEXT,
            section="Advanced runtime",
            description=(
                "Optional python.exe override. Leave empty to use the bundled "
                "PocketTTS interpreter."
            ),
            default_value="",
        ),
    )
    return RuntimeConfigNativeAdapter(
        application_facade,
        NativeSurface(
            id="pockettts_tab",
            addon_id="nc.pockettts",
            title="PocketTTS",
            description="PocketTTS voice, generation, and interpreter settings.",
            sections=("Voice", "Startup", "Advanced generation", "Advanced runtime"),
            controls=controls,
        ),
        persist=persist,
    )


__all__ = ["build_pockettts_adapter"]
