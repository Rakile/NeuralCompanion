"""Presentation-only, surface-scoped setting help; never reads runtime values."""
from __future__ import annotations
from collections.abc import Mapping
import math


_VISUAL_SURFACES = frozenset({
    "ai_presence_mode_tab", "companion_orb_overlay_tab", "corsair_visual_instrument_tab",
    "visual_story_settings_tab", "visuals_host", "vseeface_avatar_tab",
})
_CONVERSATION_SURFACES = frozenset({
    "buddy_chat_tab", "discord_voice_bridge_tab", "multi_persona_roleplay_tab",
    "chat_session_player_tab", "identity_artifacts_tab", "user_identity_tab", "main_chat_remote_tab",
})
_PROVIDER_SURFACES = frozenset({
    "audio_story_mode_runtime", "chatterbox_multilingual_tts_tab", "chatterbox_tts_tab",
    "clipboard_source_tab", "clipboard_supervisor_tab", "ditto_avatar_tab", "ditto_preprocess_tab",
    "elevenlabs_tts_tab", "gemini_tts_preview_tab", "heart_rate_behavior_tab", "heart_rate_source_tab",
    "hotkeys_tab", "musetalk_avatar_tab", "musetalk_preprocess_tab", "pockettts_multilingual_tts_tab",
    "pockettts_tab", "rag_context_tab", "scenic_avatar_tab", "screen_source_capture_tab",
    "screen_supervisor_tab", "spotify_sense_tab", "voice_studio_tab", "web_intelligence_tab",
    "webcam_source_tab", "webcam_supervisor_tab",
})
_CHAT_SURFACES = frozenset("chat_provider:" + name for name in
                         ("lmstudio", "lmstudio_sdk", "ollama", "openai", "deepseek", "claude", "xai"))


def help_for(control_id: str, surface_id: str = "") -> str:
    """Look up only this built-in surface; third-party IDs are never inferred."""
    from . import visual, conversation, providers, core
    if surface_id in _VISUAL_SURFACES:
        return visual.help_for(control_id, surface_id)
    if surface_id in _CONVERSATION_SURFACES:
        return conversation.help_for(control_id, surface_id)
    if surface_id in _PROVIDER_SURFACES:
        return providers.help_for(control_id, surface_id)
    if surface_id in _CHAT_SURFACES or surface_id == "stt":
        return core.HELP.get(f"{surface_id}.{control_id}", "")
    if surface_id:
        return ""
    # Explicit internal lookups without a surface may resolve stable native IDs.
    # Serialization below does not infer built-in ownership for a bare descriptor.
    for catalog in (visual, conversation, providers, core):
        text = catalog.help_for(control_id)
        if text:
            return text
    return ""


def field_help(field: Mapping[str, object], surface_id: str = "") -> str:
    """Return authored help plus verified displayed bounds, without values/secrets."""
    key = str(field.get("id") or field.get("key") or "")
    text = help_for(key, surface_id) if surface_id else ""
    if not text:
        text = str(field.get("toolTip") or field.get("tooltip") or field.get("description") or "").strip()
    if not text:
        return ""
    kind = str(field.get("type") or field.get("kind") or "")
    if kind in {"integer", "number", "slider", "int", "float"}:
        low, high = field.get("minimum", field.get("min")), field.get("maximum", field.get("max"))
        scale = max(1, float(field.get("displayScale") or 1))
        if isinstance(low, (int,float)) and isinstance(high, (int,float)) and math.isfinite(low) and math.isfinite(high):
            text += f" Range: {low / scale:g} to {high / scale:g}."
    return text
