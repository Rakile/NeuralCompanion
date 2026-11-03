"""Native QML settings surface for the built-in Chatterbox TTS provider."""

from __future__ import annotations

from ui.qml_bridge.adapters.config import RuntimeConfigNativeAdapter
from ui.qml_bridge.native_contracts import NativeControl, NativeControlKind, NativeSurface


def build_chatterbox_adapter(application_facade, *, persist=None):
    controls = (
        NativeControl(
            "tts_seed",
            "Seed",
            NativeControlKind.INTEGER,
            section="Generation",
            description="Use 0 for the default randomized generation seed.",
            default_value=0,
            minimum=0,
            maximum=2_147_483_647,
        ),
        NativeControl(
            "tts_temperature",
            "Temperature",
            NativeControlKind.NUMBER,
            section="Generation",
            description="Controls variation in voice generation.",
            default_value=0.8,
            minimum=0.05,
            maximum=2.0,
            step=0.05,
        ),
        NativeControl(
            "tts_top_p",
            "Top P",
            NativeControlKind.NUMBER,
            section="Generation",
            default_value=0.9,
            minimum=0.0,
            maximum=1.0,
            step=0.01,
        ),
        NativeControl(
            "tts_top_k",
            "Top K",
            NativeControlKind.INTEGER,
            section="Generation",
            default_value=40,
            minimum=0,
            maximum=1000,
        ),
        NativeControl(
            "tts_repeat_penalty",
            "Repetition penalty",
            NativeControlKind.NUMBER,
            section="Generation",
            default_value=1.2,
            minimum=0.01,
            maximum=4.0,
            step=0.01,
        ),
        NativeControl(
            "tts_use_cloned_voice",
            "Use cloned voice",
            NativeControlKind.BOOLEAN,
            section="Voice",
            description="Use the active voice reference when one is selected.",
            default_value=True,
        ),
        NativeControl(
            "tts_normalize_loudness",
            "Normalize loudness",
            NativeControlKind.BOOLEAN,
            section="Voice",
            default_value=False,
        ),
        NativeControl(
            "tts_apply_watermark",
            "Apply audio watermark",
            NativeControlKind.BOOLEAN,
            section="Voice",
            default_value=False,
        ),
        NativeControl(
            "tts_prewarm_on_start",
            "Prewarm on runtime start",
            NativeControlKind.BOOLEAN,
            section="Startup",
            description="Reduces the delay before the first spoken sentence.",
            default_value=True,
        ),
    )
    return RuntimeConfigNativeAdapter(
        application_facade,
        NativeSurface(
            id="chatterbox_tts_tab",
            addon_id="nc.chatterbox_tts",
            title="Chatterbox",
            description="English Chatterbox Turbo speech. Min P, CFG weight and exaggeration are not supported by Turbo.",
            sections=("Generation", "Voice", "Startup"),
            controls=controls,
        ),
        persist=persist,
    )


__all__ = ["build_chatterbox_adapter"]
