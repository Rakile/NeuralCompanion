"""Native QML settings for the Chatterbox Multilingual TTS provider."""

from __future__ import annotations

from ui.qml_bridge.adapters.config import RuntimeConfigNativeAdapter
from ui.qml_bridge.native_contracts import (
    NativeControl,
    NativeControlKind,
    NativeSurface,
    choices,
)


_LANGUAGES = (
    ("en", "English"),
    ("ar", "Arabic"),
    ("zh", "Chinese"),
    ("da", "Danish"),
    ("nl", "Dutch"),
    ("fi", "Finnish"),
    ("de", "German"),
    ("el", "Greek"),
    ("fr", "French"),
    ("he", "Hebrew"),
    ("hi", "Hindi"),
    ("it", "Italian"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("ms", "Malay"),
    ("no", "Norwegian"),
    ("pl", "Polish"),
    ("pt", "Portuguese"),
    ("ru", "Russian"),
    ("es", "Spanish"),
    ("sv", "Swedish"),
    ("sw", "Swahili"),
    ("tr", "Turkish"),
)


def build_chatterbox_multilingual_adapter(application_facade, *, persist=None):
    controls = (
        NativeControl(
            "chatterbox_multilingual_language",
            "Language",
            NativeControlKind.CHOICE,
            section="Language",
            default_value="en",
            choices=choices(_LANGUAGES),
        ),
        NativeControl(
            "chatterbox_multilingual_seed",
            "Seed",
            NativeControlKind.INTEGER,
            section="Generation",
            description="Seed setting for multilingual speech; identical audio is not guaranteed.",
            default_value=0,
            minimum=0,
            maximum=2_147_483_647,
        ),
        NativeControl(
            "chatterbox_multilingual_temperature",
            "Temperature",
            NativeControlKind.NUMBER,
            section="Generation",
            default_value=0.8,
            minimum=0.05,
            maximum=5.0,
            step=0.05,
        ),
        NativeControl(
            "chatterbox_multilingual_top_p",
            "Top P",
            NativeControlKind.NUMBER,
            section="Generation",
            default_value=1.0,
            minimum=0.0,
            maximum=1.0,
            step=0.01,
        ),
        NativeControl(
            "chatterbox_multilingual_exaggeration",
            "Exaggeration",
            NativeControlKind.NUMBER,
            section="Generation",
            default_value=0.5,
            minimum=0.0,
            maximum=2.0,
            step=0.05,
        ),
        NativeControl(
            "chatterbox_multilingual_cfg_weight",
            "CFG weight",
            NativeControlKind.NUMBER,
            section="Generation",
            default_value=0.5,
            minimum=0.0,
            maximum=1.0,
            step=0.05,
        ),
        NativeControl(
            "chatterbox_multilingual_min_p",
            "Min P",
            NativeControlKind.NUMBER,
            section="Generation",
            default_value=0.05,
            minimum=0.0,
            maximum=1.0,
            step=0.01,
        ),
        NativeControl(
            "chatterbox_multilingual_repeat_penalty",
            "Repetition penalty",
            NativeControlKind.NUMBER,
            section="Generation",
            default_value=2.0,
            minimum=1.0,
            maximum=4.0,
            step=0.01,
        ),
        NativeControl(
            "chatterbox_multilingual_use_cloned_voice",
            "Use cloned voice",
            NativeControlKind.BOOLEAN,
            section="Voice",
            default_value=True,
        ),
        NativeControl(
            "chatterbox_multilingual_apply_watermark",
            "Apply audio watermark",
            NativeControlKind.BOOLEAN,
            section="Voice",
            default_value=False,
        ),
        NativeControl(
            "chatterbox_multilingual_prewarm_on_start",
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
            id="chatterbox_multilingual_tts_tab",
            addon_id="nc.chatterbox_multilingual_tts",
            title="Chatterbox Multilingual",
            description="Multilingual Chatterbox language and generation settings.",
            sections=("Language", "Generation", "Voice", "Startup"),
            controls=controls,
        ),
        persist=persist,
    )


__all__ = ["build_chatterbox_multilingual_adapter"]
