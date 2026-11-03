from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Any

from addons.ditto_avatar.config import DEFAULTS as _DITTO_DEFAULTS
from addons.ditto_avatar.session_schema import SESSION_KEY as DITTO_SESSION_KEY
from addons.audio_story_mode.session_schema import (
    LEGACY_FIELD_PATHS as AUDIO_STORY_LEGACY_FIELD_PATHS,
)
from addons.visual_reply.session_schema import (
    LEGACY_FIELD_PATHS as VISUAL_REPLY_LEGACY_FIELD_PATHS,
)
from core.ai_presence_session_schema import SESSION_KEY as AI_PRESENCE_SESSION_KEY
from core.chat_runtime_session_schema import (
    GENERATION_DEFAULT_KEYS,
    LEGACY_FIELD_PATHS as CHAT_RUNTIME_LEGACY_FIELD_PATHS,
    MODEL_STATE_KEYS,
    SESSION_KEY as CHAT_RUNTIME_SESSION_KEY,
)
from core.chunking_session_schema import (
    LEGACY_FIELD_PATHS as CHUNKING_LEGACY_FIELD_PATHS,
    SESSION_KEY as CHUNKING_SESSION_KEY,
)
from core.companion_orb_session_schema import SESSION_KEY as COMPANION_ORB_SESSION_KEY
from core.musetalk_session_schema import (
    LEGACY_FIELD_PATHS as MUSETALK_LEGACY_FIELD_PATHS,
    SESSION_KEY as MUSETALK_SESSION_KEY,
)
from core.persona_session_schema import (
    LEGACY_FIELD_PATHS as PERSONA_LEGACY_FIELD_PATHS,
    SESSION_KEY as PERSONA_SESSION_KEY,
)
from core.runtime_controls_session_schema import (
    LEGACY_FIELD_PATHS as RUNTIME_CONTROLS_LEGACY_FIELD_PATHS,
    SESSION_KEY as RUNTIME_CONTROLS_SESSION_KEY,
)
from core.sensory_session_schema import (
    LEGACY_FIELD_PATHS as SENSORY_LEGACY_FIELD_PATHS,
    SESSION_KEY as SENSORY_SESSION_KEY,
)
from core.stt_session_schema import (
    LEGACY_FIELD_PATHS as STT_LEGACY_FIELD_PATHS,
    OLD_TTS_STT_PATHS,
    SESSION_KEY as STT_SESSION_KEY,
)
from core.tts_session_schema import (
    LEGACY_FIELD_PATHS as TTS_LEGACY_FIELD_PATHS,
    SESSION_KEY as TTS_SESSION_KEY,
)
from core.ua_companion_orb_session_schema import SESSION_KEY as UA_COMPANION_ORB_SESSION_KEY
from core.ui_session_schema import LEGACY_FIELD_PATHS as UI_LEGACY_FIELD_PATHS


ROOT_METADATA_KEYS = frozenset()
ACTIVE_CHAT_PROVIDER = "{chat_provider}"
ACTIVE_VISUAL_REPLY_PROVIDER = "{visual_reply_provider}"
CREDENTIAL_FIELD_NAMES = frozenset(
    {
        "api_key",
        "access_token",
        "authorization",
        "auth_token",
        "bearer",
        "client_id",
        "client_secret",
        "oauth_token",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "session_token",
        "token",
    }
)
_CREDENTIAL_FIELD_SUFFIXES = (
    "_api_key",
    "_access_token",
    "_auth_token",
    "_client_id",
    "_client_secret",
    "_oauth_token",
    "_password",
    "_private_key",
    "_refresh_token",
    "_secret",
    "_session_token",
    "_token",
)

# These are the only credential leaves intentionally stored in qt_session.json.
# The paths are addon-owned and exact so the general credential redaction policy
# remains in force everywhere else.
_ADDON_PERSISTED_CREDENTIAL_PATHS = {
    "nc.visual_reply": (
        ("visual_reply_provider_settings", "{provider}", "api_key"),
        ("visual_reply", "providers", "settings", "{provider}", "api_key"),
    ),
    "nc.gemini_tts_preview": (
        ("gemini_tts_preview_settings", "api_key"),
        ("tts_runtime", "gemini_tts_preview", "settings", "api_key"),
    ),
    "nc.elevenlabs_tts": (
        ("elevenlabs_tts_settings", "api_key"),
        ("tts_runtime", "elevenlabs_tts", "settings", "api_key"),
    ),
}

_MUSETALK_PREPROCESS_KEYS = frozenset(
    {
        "musetalk_source_path",
        "musetalk_preprocess_target_pack_id",
        "musetalk_selected_avatar_id",
        "musetalk_avatar_id",
        "musetalk_recreate",
        "musetalk_create_frame_cache",
        "musetalk_emotion_tags",
        "musetalk_bbox_shift",
        "musetalk_parsing_mode",
        "musetalk_extra_margin",
        "musetalk_left_cheek_width",
        "musetalk_right_cheek_width",
        "musetalk_debug_show_mask_overlay",
        "musetalk_mask_range_start",
        "musetalk_mask_range_end",
        "musetalk_mask_range_passthrough",
        "musetalk_mask_range_selected_index",
        "musetalk_mask_ranges",
        "musetalk_mask_override_selected_index",
        "musetalk_mask_overrides",
        "musetalk_debug_frame_index",
        "musetalk_debug_brush_size",
        "musetalk_debug_brush_feather",
        "musetalk_debug_brush_transparency",
        "musetalk_debug_zoom",
        "musetalk_test_audio",
        "musetalk_enabled_pack_emotions",
    }
)

EXPECTED_ADDON_SESSION_NAMESPACES = {
    "nc.ai_presence_mode": frozenset({"ai_presence"}),
    "nc.audio_story_mode": frozenset({"audio_story_mode"}),
    "nc.buddy_chat": frozenset({"buddy_chat"}),
    "nc.chat_session_player": frozenset({"chat_session_player"}),
    "nc.chatterbox_multilingual_tts": frozenset({"tts_runtime"}),
    "nc.chatterbox_tts": frozenset({"tts_runtime"}),
    "nc.clipboard_source": frozenset({"sensory"}),
    "nc.companion_orb_overlay": frozenset({"companion_orb"}),
    "nc.ditto_avatar": frozenset({DITTO_SESSION_KEY}),
    "nc.gemini_tts_preview": frozenset({"tts_runtime"}),
    "nc.elevenlabs_tts": frozenset({"tts_runtime"}),
    "nc.identity_artifacts": frozenset({"identity_artifacts"}),
    "nc.main_chat_remote": frozenset({"main_chat_remote"}),
    "nc.mock_heart_rate": frozenset({"sensory"}),
    "nc.multi_persona_roleplay": frozenset({"multi_persona_roleplay"}),
    "nc.musetalk_avatar": frozenset({"chunking", "musetalk"}),
    "nc.musetalk_preprocess": frozenset({"musetalk"}),
    "nc.pockettts": frozenset({"tts_runtime"}),
    "nc.pockettts_multilingual_tts": frozenset({"tts_runtime"}),
    "nc.rag_context": frozenset({"rag_context"}),
    "nc.scenic_avatar": frozenset({"scenic_avatar"}),
    "nc.vseeface_avatar": frozenset({"vseeface"}),
    "nc.screen_source": frozenset({"sensory"}),
    "nc.spotify_sense": frozenset({"spotify_sense"}),
    "nc.ua_companion_orb_overlay": frozenset({"ua_companion_orb_overlay"}),
    "nc.visual_reply": frozenset({"visual_reply"}),
    "nc.visual_story_settings": frozenset({"visual_reply"}),
    "nc.web_intelligence": frozenset({"web_intelligence"}),
    "nc.webcam_source": frozenset({"sensory"}),
}

# Shared category roots need a second ownership boundary below the root.  A
# pattern claims the named path and every descendant of that path.  Exact leaf
# policies are still checked, so an exceptional leaf such as MuseTalk's active
# avatar selection cannot be claimed by the broader runtime prefix.
ADDON_SESSION_PATH_PATTERNS = {
    "core.addons.manager": (("tts_runtime", "diagnostics"),),
    "nc.chatterbox_tts": (("tts_runtime", "chatterbox"),),
    "nc.chatterbox_multilingual_tts": (("tts_runtime", "chatterbox_multilingual"),),
    "nc.gemini_tts_preview": (("tts_runtime", "gemini_tts_preview"),),
    "nc.elevenlabs_tts": (("tts_runtime", "elevenlabs_tts"),),
    "nc.pockettts": (("tts_runtime", "pockettts"),),
    "nc.pockettts_multilingual_tts": (("tts_runtime", "pockettts_multilingual"),),
    "nc.musetalk_avatar": (
        ("chunking", "musetalk"),
        ("musetalk", "runtime"),
    ),
    "nc.musetalk_preprocess": (
        ("musetalk", "preprocess"),
        ("musetalk", "runtime", "selected_avatar_id"),
    ),
    "nc.visual_reply": (
        ("visual_reply", "core"),
        ("visual_reply", "providers"),
        ("visual_reply", "ui"),
    ),
    "nc.visual_story_settings": (
        ("visual_reply", "prompt"),
        ("visual_reply", "story"),
    ),
}
_SHARED_ADDON_SESSION_ROOTS = frozenset({"chunking", "musetalk", "tts_runtime", "visual_reply"})

PRESET_ELIGIBLE_KEYS = frozenset(
    {
        "sensory_feedback_source",
        "sensory_feedback_interval_seconds",
        "sensory_pingpong_enabled",
        "sensory_allow_hidden_proactive_speech",
        "sensory_allow_hidden_visual_generation",
        "sensory_pingpong_history_depth",
        "sensory_pingpong_prompt",
        "sensory_pingpong_source_prompts",
        "sensory_provider_metadata_overrides",
        "sensory_context_templates",
        "allow_proactive_replies",
        "require_first_user_before_proactive",
        "listen_idle_window_seconds",
        "proactive_delay_seconds",
        "chat_context_window_messages",
        "stored_chat_history_limit",
        "chat_context_overflow_policy",
        "emotional_instructions",
        "system_prompt",
        "persona_prompt_type",
        "temperature",
        "top_p",
        "top_k",
        "repeat_penalty",
        "min_p",
        "limit_response_length",
        "max_response_tokens",
    }
)

_RECOGNIZED_LEGACY_ROOT_ALIASES = frozenset(
    {
        "active_quick_persona_name", "audio_story_analysis_mode",
        "chat_message_timestamps_enabled", "chat_replay_role_voices",
        "chunk_max_chars", "chunk_target_chars", "conversation_action_labels_enabled",
        "conversation_message_borders_enabled", "conversation_reset_button_visible",
        "conversation_response_action_layout",
        "conversation_response_placement_guides_enabled", "conversation_speech_highlight_mode",
        "conversation_speech_highlight_style", "conversation_user_action_layout",
        "conversation_user_min_height", "conversation_user_width_ratio",
        "conversation_visual_reply_auto_follow", "conversation_visual_reply_display_mode",
        "conversation_visual_replies_visible",
        "identity_relay_owner_override", "identity_relay_ref", "long_term_memory_db_id",
        "long_term_memory_db_path", "long_term_memory_embedding_min_score",
        "manual_action_hotkeys", "musetalk_chunk_max_chars", "musetalk_chunk_target_chars",
        "musetalk_debug_zoom", "musetalk_fps", "musetalk_mask_override_selected_index",
        "musetalk_mask_range_end", "musetalk_mask_range_passthrough",
        "musetalk_mask_range_selected_index", "musetalk_mask_range_start",
        "musetalk_quickstart_1_max_chars", "musetalk_quickstart_1_target_chars",
        "musetalk_quickstart_2_max_chars", "musetalk_quickstart_2_target_chars",
        "musetalk_selected_avatar_id", "musetalk_video_path", "offline_replay_only",
        "persona_mood_reference_enabled", "persona_portrait_prompt", "persona_self_image_mode",
        "persona_visual_identity_prompt", "persona_visual_reference_path",
        "persona_visual_reference_strength", "pocket_tts_language", "pocket_tts_max_tokens",
        "push_to_talk_hotkey", "quick_chat_context_active", "scenic_pack_id",
        "stream_chunk_max_chars", "stream_chunk_target_chars", "stream_first_chunk_min_chars",
        "stream_force_flush_later_seconds", "stream_force_flush_seconds",
        "tts_latency_diagnostics_enabled", "ui_action_hotkeys", "user_identity_enabled",
        "user_identity_name", "user_identity_visual_identity_prompt",
        "user_identity_visual_policy", "user_identity_visual_reference_path",
        "user_identity_visual_reference_strength", "voice_path", "webcam_source_device_id",
    }
)


class SettingLifetime(str, Enum):
    GLOBAL_APPLICATION = "global_application"
    GLOBAL_UI = "global_ui"
    RUNTIME_SESSION = "runtime_session"
    PERSONA = "persona"
    PRESET_ONLY = "preset_only"
    ADDON_GLOBAL = "addon_global"
    ADDON_PERSONA = "addon_persona"
    CREDENTIAL = "credential"
    TRANSIENT = "transient"
    DERIVED = "derived"
    ROOT_METADATA = "root_metadata"


class RestorePhase(IntEnum):
    PRE_ADDON = 10
    # Metadata for the existing validated addon import; never restore as raw config.
    ADDON_IMPORT = 15
    POST_ADDON = 20
    OWNER_PROJECTION = 30
    UI_SYNC = 40


@dataclass(frozen=True)
class LegacySource:
    path: tuple[str, ...]
    priority: int
    remove_after_save: bool = True


@dataclass(frozen=True)
class SettingPolicy:
    key: str
    owner: str
    lifetime: SettingLifetime
    canonical_path: tuple[str, ...] | None
    legacy_sources: tuple[LegacySource, ...] = ()
    restore_phase: RestorePhase | None = None
    preset_eligible: bool = False
    sensitive: bool = False
    reason: str = ""

    @property
    def session_persistent(self) -> bool:
        return self.canonical_path is not None


@dataclass(frozen=True)
class AddonPayloadMismatch:
    addon_id: str
    path: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class AddonPayloadNormalization:
    payload: dict[str, Any]
    mismatches: tuple[AddonPayloadMismatch, ...]


EXTRA_CANONICAL_PATHS = {
    "vseeface_bridge_enabled": ("vseeface", "bridge", "enabled"),
    "vseeface_bridge_install_path": ("vseeface", "bridge", "installation_path"),
    "vseeface_collapsed_cards": ("vseeface", "ui", "collapsed_cards"),
    "vseeface_controls_state": ("vseeface", "controls"),
    "chat_message_timestamps_enabled": ("chat_runtime", "ui", "message_timestamps_enabled"),
    "conversation_speech_highlight_mode": ("chat_runtime", "ui", "speech_highlight_mode"),
    "conversation_speech_highlight_style": ("chat_runtime", "ui", "speech_highlight_style"),
    "conversation_visual_reply_display_mode": ("chat_runtime", "ui", "visual_reply_display_mode"),
    "conversation_visual_reply_auto_follow": ("chat_runtime", "ui", "visual_reply_auto_follow"),
    "conversation_visual_replies_visible": ("chat_runtime", "ui", "visual_replies_visible"),
    "conversation_console_visible": ("chat_runtime", "ui", "console_visible"),
    "conversation_live_session_visible": ("chat_runtime", "ui", "live_session_visible"),
    "conversation_console_auto_scroll": ("chat_runtime", "ui", "console_auto_scroll"),
    "conversation_console_font_size": ("chat_runtime", "ui", "console_font_size"),
    "conversation_reset_button_visible": ("chat_runtime", "ui", "reset_button_visible"),
    "conversation_canvas_style": ("chat_runtime", "ui", "canvas_style"),
    "conversation_background_path": ("chat_runtime", "ui", "background_path"),
    "conversation_transparent_message_cards_enabled": (
        "chat_runtime",
        "ui",
        "transparent_message_cards",
    ),
    "conversation_message_text_color": (
        "chat_runtime",
        "ui",
        "message_text_color",
    ),
    "conversation_message_font_family": (
        "chat_runtime",
        "ui",
        "message_font_family",
    ),
    "conversation_bionic_reading_enabled": (
        "chat_runtime",
        "ui",
        "bionic_reading_enabled",
    ),
    "conversation_message_borders_enabled": ("chat_runtime", "ui", "message_borders_enabled"),
    "conversation_user_width_ratio": ("chat_runtime", "ui", "user_width_ratio"),
    "conversation_user_min_height": ("chat_runtime", "ui", "user_min_height"),
    "conversation_response_action_layout": ("chat_runtime", "ui", "response_action_layout"),
    "conversation_user_action_layout": ("chat_runtime", "ui", "user_action_layout"),
    "conversation_action_labels_enabled": ("chat_runtime", "ui", "action_labels_enabled"),
    "conversation_response_placement_guides_enabled": (
        "chat_runtime",
        "ui",
        "response_placement_guides_enabled",
    ),
    "long_term_memory_embedding_min_score": (
        "chat_runtime",
        "archive",
        "embedding_min_score",
    ),
    "voice_path": ("tts_runtime", "voice", "path"),
    "tts_latency_diagnostics_enabled": (
        "tts_runtime",
        "diagnostics",
        "latency_enabled",
    ),
    "audio_story_analysis_mode": ("audio_story_mode", "analysis", "analysis_mode"),
    "identity_relay_ref": ("identity_artifacts", "selected_ref"),
    "identity_relay_owner_override": ("identity_artifacts", "owner_override"),
    "scenic_pack_id": ("scenic_avatar", "selection", "pack_id"),
    "webcam_source_device_id": ("sensory", "sources", "webcam", "device_id"),
    "chat_replay_role_voices": ("chat_session_player", "role_voices"),
}

_LEGACY_CANONICAL_PATHS: dict[str, tuple[str, ...]] = {}
_LEGACY_SOURCES: dict[str, tuple[LegacySource, ...]] = {}


def _combine_legacy_sources(*source_groups: Iterable[LegacySource]) -> tuple[LegacySource, ...]:
    combined: list[LegacySource] = []
    seen: set[tuple[tuple[str, ...], int, bool]] = set()
    for group in source_groups:
        for source in group:
            marker = (source.path, source.priority, source.remove_after_save)
            if marker in seen:
                continue
            seen.add(marker)
            combined.append(source)
    combined.sort(key=lambda item: (item.priority, len(item.path), item.path))
    return tuple(combined)


def _register_legacy_paths(
    session_key: str,
    field_paths: Mapping[str, tuple[str, ...]],
    *,
    extra_legacy_sources: Mapping[str, tuple[LegacySource, ...]] | None = None,
) -> None:
    for key, path in field_paths.items():
        normalized_key = str(key)
        canonical_path = (session_key, *tuple(path))
        _LEGACY_CANONICAL_PATHS[normalized_key] = canonical_path
        grouped_source = (LegacySource(canonical_path, priority=10),)
        flat_source = (LegacySource((normalized_key,), priority=30),)
        extra_sources = extra_legacy_sources.get(normalized_key, ()) if extra_legacy_sources else ()
        _LEGACY_SOURCES[normalized_key] = _combine_legacy_sources(
            grouped_source,
            extra_sources,
            flat_source,
        )


def _register_explicit_legacy_sources(
    key: str,
    canonical_path: tuple[str, ...],
    *,
    flat_aliases: tuple[str, ...] | None = None,
    grouped_aliases: tuple[tuple[tuple[str, ...], int], ...] | None = None,
) -> None:
    aliases = flat_aliases or (key,)
    grouped = grouped_aliases or ((canonical_path, 10),)
    _LEGACY_SOURCES[key] = _combine_legacy_sources(
        tuple(LegacySource(path, priority=priority) for path, priority in grouped),
        tuple(LegacySource((alias,), priority=30) for alias in aliases),
    )


_register_legacy_paths(CHAT_RUNTIME_SESSION_KEY, CHAT_RUNTIME_LEGACY_FIELD_PATHS)
_register_legacy_paths(CHUNKING_SESSION_KEY, CHUNKING_LEGACY_FIELD_PATHS)
_register_legacy_paths(MUSETALK_SESSION_KEY, MUSETALK_LEGACY_FIELD_PATHS)
_register_legacy_paths(PERSONA_SESSION_KEY, PERSONA_LEGACY_FIELD_PATHS)
_register_legacy_paths(RUNTIME_CONTROLS_SESSION_KEY, RUNTIME_CONTROLS_LEGACY_FIELD_PATHS)
_register_legacy_paths(SENSORY_SESSION_KEY, SENSORY_LEGACY_FIELD_PATHS)
_register_legacy_paths(
    STT_SESSION_KEY,
    STT_LEGACY_FIELD_PATHS,
    extra_legacy_sources={
        key: (LegacySource(("tts_runtime", "stt", *path), priority=20),)
        for key, path in OLD_TTS_STT_PATHS.items()
    },
)
_register_legacy_paths(TTS_SESSION_KEY, TTS_LEGACY_FIELD_PATHS)
_register_explicit_legacy_sources(
    "voice_path",
    (TTS_SESSION_KEY, "voice", "path"),
    flat_aliases=("voice_path", "voice_file"),
)
_register_legacy_paths("ui", UI_LEGACY_FIELD_PATHS)
_register_legacy_paths("visual_reply", VISUAL_REPLY_LEGACY_FIELD_PATHS)
_register_legacy_paths("audio_story_mode", AUDIO_STORY_LEGACY_FIELD_PATHS)

_LEGACY_CANONICAL_PATHS.update(
    {
        "show_performance_guidance": ("ui", "docks", "performance_guidance_visible"),
        "model_name": (
            "chat_runtime",
            "provider_settings",
            ACTIVE_CHAT_PROVIDER,
            "model_name",
        ),
        "model_requires_vision": (
            "chat_runtime",
            "provider_settings",
            ACTIVE_CHAT_PROVIDER,
            "model_requires_vision",
        ),
        "model_supports_images": (
            "chat_runtime",
            "provider_settings",
            ACTIVE_CHAT_PROVIDER,
            "model_supports_images",
        ),
        "model_supports_reasoning": (
            "chat_runtime",
            "provider_settings",
            ACTIVE_CHAT_PROVIDER,
            "model_supports_reasoning",
        ),
        "model_supports_reasoning_toggle": (
            "chat_runtime",
            "provider_settings",
            ACTIVE_CHAT_PROVIDER,
            "model_supports_reasoning_toggle",
        ),
        "temperature": (
            "chat_runtime",
            "generation_settings",
            ACTIVE_CHAT_PROVIDER,
            "temperature",
        ),
        "top_p": ("chat_runtime", "generation_settings", ACTIVE_CHAT_PROVIDER, "top_p"),
        "top_k": ("chat_runtime", "generation_settings", ACTIVE_CHAT_PROVIDER, "top_k"),
        "repeat_penalty": (
            "chat_runtime",
            "generation_settings",
            ACTIVE_CHAT_PROVIDER,
            "repeat_penalty",
        ),
        "min_p": ("chat_runtime", "generation_settings", ACTIVE_CHAT_PROVIDER, "min_p"),
        "continuity_memory_update_on_save": (
            "chat_runtime",
            "memory",
            "update_on_save",
        ),
        "hotkeys": ("hotkeys",),
        "push_to_talk_hotkey": ("hotkeys", "push_to_talk"),
        "manual_action_hotkeys": ("hotkeys", "manual_actions"),
        "ui_action_hotkeys": ("hotkeys", "ui_actions"),
        "musetalk_video_path": ("musetalk", "runtime", "video_path"),
        "musetalk_fps": ("musetalk", "runtime", "fps"),
        "musetalk_selected_avatar_id": ("musetalk", "runtime", "selected_avatar_id"),
        "musetalk_debug_zoom": ("musetalk", "preprocess", "editor", "debug_zoom"),
        "musetalk_mask_range_start": (
            "musetalk",
            "preprocess",
            "editor",
            "mask_range_start",
        ),
        "musetalk_mask_range_end": (
            "musetalk",
            "preprocess",
            "editor",
            "mask_range_end",
        ),
        "musetalk_mask_range_passthrough": (
            "musetalk",
            "preprocess",
            "editor",
            "mask_range_passthrough",
        ),
        "musetalk_mask_range_selected_index": (
            "musetalk",
            "preprocess",
            "editor",
            "mask_range_selected_index",
        ),
        "musetalk_mask_override_selected_index": (
            "musetalk",
            "preprocess",
            "editor",
            "mask_override_selected_index",
        ),
        "visual_reply_model": (
            "visual_reply",
            "providers",
            "settings",
            ACTIVE_VISUAL_REPLY_PROVIDER,
            "model",
        ),
        "visual_reply_size": (
            "visual_reply",
            "providers",
            "settings",
            ACTIVE_VISUAL_REPLY_PROVIDER,
            "size",
        ),
    }
)
_LEGACY_CANONICAL_PATHS.update(EXTRA_CANONICAL_PATHS)

for key in _LEGACY_CANONICAL_PATHS:
    _register_explicit_legacy_sources(
        key,
        _LEGACY_CANONICAL_PATHS[key],
        flat_aliases=(key,),
    ) if key not in _LEGACY_SOURCES else None

_register_explicit_legacy_sources(
    "show_performance_guidance",
    _LEGACY_CANONICAL_PATHS["show_performance_guidance"],
    flat_aliases=("show_performance_guidance",),
    grouped_aliases=((("ui", "docks", "performance_guidance_visible"), 15),),
)

_GLOBAL_UI_KEYS = {
    "first_run",
    "welcome_hub_show_on_startup",
    "chat_font_size",
    "chat_visual_batch_size",
    "long_term_memory_image_review_enabled",
    "chat_message_timestamps_enabled",
    "conversation_speech_highlight_mode",
    "conversation_speech_highlight_style",
    "conversation_visual_reply_display_mode",
    "conversation_visual_reply_auto_follow",
    "conversation_visual_replies_visible",
    "conversation_console_visible",
    "conversation_live_session_visible",
    "conversation_console_auto_scroll",
    "conversation_console_font_size",
    "conversation_reset_button_visible",
    "conversation_save_button_visible",
    "conversation_save_as_button_visible",
    "conversation_load_button_visible",
    "conversation_memory_button_visible",
    "conversation_canvas_style",
    "conversation_background_path",
    "conversation_transparent_message_cards_enabled",
    "conversation_message_text_color",
    "conversation_message_font_family",
    "conversation_bionic_reading_enabled",
    "conversation_message_borders_enabled",
    "conversation_response_width_ratio",
    "conversation_response_min_height",
    "conversation_user_width_ratio",
    "conversation_user_min_height",
    "conversation_response_action_layout",
    "conversation_user_action_layout",
    "conversation_action_labels_enabled",
    "conversation_response_placement_guides_enabled",
    "show_performance_guidance",
    "performance_guidance_visible",
}

_GLOBAL_APPLICATION_KEYS = {
    "hotkeys",
    "push_to_talk_hotkey",
    "manual_action_hotkeys",
    "ui_action_hotkeys",
}

_TRANSIENT_KEYS = {
    "offline_replay_only": "Runtime replay flag; never restored from session storage.",
    "quick_chat_context_active": "Runtime-only chat context state.",
    "long_term_memory_db_path": "Active LTM binding is established at runtime.",
    "long_term_memory_db_id": "Active LTM binding is established at runtime.",
    "long_term_memory_embedding_session_model": "Embedding session scratch state.",
    "long_term_memory_embedding_session_context_length": "Embedding session scratch state.",
    "pocket_tts_language": "Derived from the active PocketTTS backend configuration.",
    "pocket_tts_max_tokens": "Derived from the active PocketTTS backend configuration.",
}

_PERSONA_PROJECTION_KEYS = {
    "active_quick_persona_id": "Owned by quick_personas.json and projected into runtime config; never a tool grant.",
    "persona_mood_tags": "Owned by quick_personas.json and projected into runtime config.",
    "active_quick_persona_name": "Owned by quick_personas.json and projected into runtime config.",
    "persona_visual_identity_prompt": "Owned by quick_personas.json and projected into runtime config.",
    "persona_portrait_prompt": "Owned by quick_personas.json and projected into runtime config.",
    "persona_visual_reference_path": "Owned by quick_personas.json and projected into runtime config.",
    "persona_self_image_mode": "Owned by quick_personas.json and projected into runtime config.",
    "persona_appearance_freedom": "Owned by quick_personas.json and projected into runtime config.",
    "persona_visual_reference_strength": "Owned by quick_personas.json and projected into runtime config.",
    "persona_mood_reference_enabled": "Owned by quick_personas.json and projected into runtime config.",
}

_USER_IDENTITY_PROJECTION_KEYS = {
    "user_identity_enabled",
    "user_identity_name",
    "user_identity_visual_identity_prompt",
    "user_identity_visual_reference_path",
    "user_identity_visual_policy",
    "user_identity_visual_reference_strength",
}

_ADDON_OWNER_OVERRIDES = {
    "ua_companion_orb_send_musetalk_face_mask": "nc.ua_companion_orb_overlay",
}

_register_explicit_legacy_sources(
    "ua_companion_orb_send_musetalk_face_mask",
    (
        UA_COMPANION_ORB_SESSION_KEY,
        "ua_companion_orb_send_musetalk_face_mask",
    ),
    grouped_aliases=(
        (
            (
                UA_COMPANION_ORB_SESSION_KEY,
                "ua_companion_orb_send_musetalk_face_mask",
            ),
            10,
        ),
        (
            (
                UA_COMPANION_ORB_SESSION_KEY,
                UA_COMPANION_ORB_SESSION_KEY,
                "ua_companion_orb_send_musetalk_face_mask",
            ),
            20,
        ),
    ),
)


def _policy(
    key: str,
    *,
    owner: str,
    lifetime: SettingLifetime,
    canonical_path: tuple[str, ...] | None,
    restore_phase: RestorePhase | None,
    reason: str = "",
    sensitive: bool = False,
) -> SettingPolicy:
    legacy_sources = _LEGACY_SOURCES.get(key, ())
    if canonical_path is not None and not legacy_sources:
        legacy_sources = (
            LegacySource(canonical_path, priority=10),
            LegacySource((key,), priority=30),
        )
    return SettingPolicy(
        key=key,
        owner=owner,
        lifetime=lifetime,
        canonical_path=canonical_path,
        legacy_sources=legacy_sources,
        restore_phase=restore_phase,
        preset_eligible=key in PRESET_ELIGIBLE_KEYS,
        sensitive=sensitive,
        reason=reason,
    )


def _family_canonical_path(key: str) -> tuple[str, ...] | None:
    if key.startswith("ai_presence_"):
        return (AI_PRESENCE_SESSION_KEY, key)
    if key.startswith("companion_orb_"):
        return (COMPANION_ORB_SESSION_KEY, key)
    if key != UA_COMPANION_ORB_SESSION_KEY and key.startswith("ua_companion_orb_"):
        return (UA_COMPANION_ORB_SESSION_KEY, key)
    return None


def _addon_owner_for_key(key: str) -> str | None:
    if key in {"vseeface_bridge_enabled", "vseeface_bridge_install_path",
               "vseeface_collapsed_cards", "vseeface_controls_state"}:
        return "nc.vseeface_avatar"
    if key in _ADDON_OWNER_OVERRIDES:
        return _ADDON_OWNER_OVERRIDES[key]
    if key == "audio_story_analysis_mode" or key.startswith("audio_story_mode_"):
        return "nc.audio_story_mode"
    if key.startswith("ai_presence_"):
        return "nc.ai_presence_mode"
    if key.startswith("clipboard_source_"):
        return "nc.clipboard_source"
    if key.startswith("companion_orb_"):
        return "nc.companion_orb_overlay"
    if key == "gemini_tts_preview_settings":
        return "nc.gemini_tts_preview"
    if key == "elevenlabs_tts_settings":
        return "nc.elevenlabs_tts"
    if key.startswith("mock_heart_rate_"):
        return "nc.mock_heart_rate"
    if key in _MUSETALK_PREPROCESS_KEYS:
        return "nc.musetalk_preprocess"
    if key.startswith("musetalk_"):
        return "nc.musetalk_avatar"
    if key.startswith("pocket_tts_multilingual_"):
        return "nc.pockettts_multilingual_tts"
    if key.startswith("pocket_tts_"):
        return "nc.pockettts"
    if key.startswith("tts_"):
        return "nc.chatterbox_tts"
    if key.startswith("chatterbox_multilingual_"):
        return "nc.chatterbox_multilingual_tts"
    if key.startswith("screen_source_"):
        return "nc.screen_source"
    if key.startswith("visual_reply_story_") or key in {
        "visual_reply_master_style_prompt",
        "visual_reply_master_prompt_safe",
        "visual_reply_master_prompt_no_speech_bubbles",
    }:
        return "nc.visual_story_settings"
    if key.startswith("visual_reply_") or key == "visual_replies_enabled":
        return "nc.visual_reply"
    if key == "scenic_pack_id":
        return "nc.scenic_avatar"
    if key == "webcam_source_device_id":
        return "nc.webcam_source"
    if key == "chat_replay_role_voices":
        return "nc.chat_session_player"
    if key.startswith("identity_relay_"):
        return "nc.identity_artifacts"
    return None


def policy_for_key(key: str) -> SettingPolicy | None:
    normalized = str(key or "").strip()
    if not normalized:
        return None

    if normalized in _TRANSIENT_KEYS:
        return _policy(
            normalized,
            owner="core.runtime",
            lifetime=SettingLifetime.TRANSIENT,
            canonical_path=None,
            restore_phase=None,
            reason=_TRANSIENT_KEYS[normalized],
        )

    if normalized in _PERSONA_PROJECTION_KEYS:
        return _policy(
            normalized,
            owner="quick_personas",
            lifetime=SettingLifetime.PERSONA,
            canonical_path=None,
            restore_phase=None,
            reason=_PERSONA_PROJECTION_KEYS[normalized],
        )

    if normalized in _DITTO_DEFAULTS:
        # Group saved settings while preserving validated addon import ownership.
        # Package/variant tuning and portable paths are resolved by Ditto;
        # generic config restoration must not bypass that validation.
        return _policy(
            normalized,
            owner="nc.ditto_avatar",
            lifetime=SettingLifetime.ADDON_GLOBAL,
            canonical_path=(DITTO_SESSION_KEY, normalized),
            restore_phase=RestorePhase.ADDON_IMPORT,
        )

    if normalized in _USER_IDENTITY_PROJECTION_KEYS:
        return _policy(
            normalized,
            owner="nc.user_identity",
            lifetime=SettingLifetime.ADDON_GLOBAL,
            canonical_path=None,
            restore_phase=None,
            reason="Owned by the User Identity profile store and only projected into runtime config.",
            sensitive=True,
        )

    if normalized == "addon_registry_state":
        return _policy(
            normalized,
            owner="core.addons.manager",
            lifetime=SettingLifetime.ADDON_GLOBAL,
            canonical_path=("addon_registry_state",),
            restore_phase=RestorePhase.POST_ADDON,
        )

    if normalized == "first_run":
        return _policy(
            normalized,
            owner="core.ui",
            lifetime=SettingLifetime.GLOBAL_UI,
            canonical_path=("ui", "onboarding", "first_run"),
            restore_phase=RestorePhase.UI_SYNC,
        )

    if normalized == "tts_latency_diagnostics_enabled":
        return _policy(
            normalized,
            owner="core.addons.manager",
            lifetime=SettingLifetime.GLOBAL_UI,
            canonical_path=EXTRA_CANONICAL_PATHS[normalized],
            restore_phase=RestorePhase.POST_ADDON,
        )

    if normalized in _GLOBAL_APPLICATION_KEYS:
        return _policy(
            normalized,
            owner="core.application",
            lifetime=SettingLifetime.GLOBAL_APPLICATION,
            canonical_path=_LEGACY_CANONICAL_PATHS.get(normalized),
            restore_phase=RestorePhase.PRE_ADDON,
        )

    if normalized == "tts_backend":
        return _policy(
            normalized,
            owner="core.runtime",
            lifetime=SettingLifetime.RUNTIME_SESSION,
            canonical_path=_LEGACY_CANONICAL_PATHS[normalized],
            restore_phase=RestorePhase.PRE_ADDON,
        )

    addon_owner = _addon_owner_for_key(normalized)
    if addon_owner is not None:
        phase = RestorePhase.POST_ADDON
        if normalized in {
            "screen_source_capture_screen_index",
            "screen_source_auto_attach_next_user_turn",
        }:
            phase = RestorePhase.PRE_ADDON
        if normalized in {"identity_relay_ref", "identity_relay_owner_override"}:
            phase = RestorePhase.OWNER_PROJECTION
        return _policy(
            normalized,
            owner=addon_owner,
            lifetime=SettingLifetime.ADDON_GLOBAL,
            canonical_path=_LEGACY_CANONICAL_PATHS.get(normalized)
            or _family_canonical_path(normalized),
            restore_phase=phase,
        )

    if normalized in _GLOBAL_UI_KEYS:
        return _policy(
            normalized,
            owner="core.ui",
            lifetime=SettingLifetime.GLOBAL_UI,
            canonical_path=_LEGACY_CANONICAL_PATHS.get(normalized),
            restore_phase=RestorePhase.UI_SYNC,
        )

    if normalized in {"system_prompt", "emotional_instructions", "persona_visual_reply_policy",
                      "persona_prompt_type", "persona_prompt_builder"}:
        return _policy(
            normalized,
            owner="core.persona",
            lifetime=SettingLifetime.RUNTIME_SESSION,
            canonical_path=_LEGACY_CANONICAL_PATHS.get(normalized),
            restore_phase=RestorePhase.OWNER_PROJECTION,
        )

    if normalized == "active_preset_name":
        return _policy(
            normalized,
            owner="core.persona",
            lifetime=SettingLifetime.RUNTIME_SESSION,
            canonical_path=_LEGACY_CANONICAL_PATHS.get(normalized),
            restore_phase=RestorePhase.PRE_ADDON,
        )

    if normalized in MODEL_STATE_KEYS or normalized in GENERATION_DEFAULT_KEYS:
        return _policy(
            normalized,
            owner="core.chat",
            lifetime=SettingLifetime.RUNTIME_SESSION,
            canonical_path=_LEGACY_CANONICAL_PATHS[normalized],
            restore_phase=RestorePhase.PRE_ADDON,
        )

    if normalized in {
        "chat_provider",
        "chat_provider_settings",
        "chat_provider_generation_settings",
        "allow_proactive_replies",
        "require_first_user_before_proactive",
        "listen_idle_window_seconds",
        "proactive_delay_seconds",
        "chat_context_window_messages",
        "chat_context_overflow_policy",
        "stored_chat_history_limit",
        "spellcheck_enabled",
        "spellcheck_language",
        "continuity_memory_id",
        "active_chat_context_path",
        "active_chat_context_name",
        "continuity_memory_enabled",
        "continuity_memory_auto_summarize",
        "continuity_memory_auto_turns",
        "continuity_memory_inject",
        "continuity_memory_max_chars",
        "continuity_memory_update_on_save",
        "long_term_memory_retrieval_enabled",
        "long_term_memory_retrieval_max_items",
        "long_term_memory_recall_text_budget",
        "long_term_memory_recall_image_limit",
        "long_term_memory_image_context_max_output_tokens",
        "long_term_memory_auto_archive_enabled",
        "long_term_memory_archive_batch_turns",
        "long_term_memory_embedding_enabled",
        "long_term_memory_embedding_provider",
        "long_term_memory_embedding_cloud_consent",
        "long_term_memory_embedding_model",
        "long_term_memory_embedding_context_length",
        "long_term_memory_embedding_base_url",
        "long_term_memory_embedding_min_score",
    }:
        return _policy(
            normalized,
            owner="core.chat",
            lifetime=SettingLifetime.RUNTIME_SESSION,
            canonical_path=_LEGACY_CANONICAL_PATHS.get(normalized),
            restore_phase=RestorePhase.PRE_ADDON,
        )

    if normalized in {
        "audio_input_device",
        "show_all_audio_input_devices",
        "audio_output_device",
        "audio_output_volume",
        "avatar_mode",
        "provider_prompt_defaults",
        "input_mode",
        "input_message_role",
        "stream_mode",
    }:
        return _policy(
            normalized,
            owner="core.runtime",
            lifetime=SettingLifetime.RUNTIME_SESSION,
            canonical_path=_LEGACY_CANONICAL_PATHS.get(normalized),
            restore_phase=RestorePhase.PRE_ADDON,
        )

    if normalized in {
        "stt_backend",
        "stt_model_size",
        "stt_language",
        "stt_backend_settings",
    }:
        return _policy(
            normalized,
            owner="core.stt",
            lifetime=SettingLifetime.RUNTIME_SESSION,
            canonical_path=_LEGACY_CANONICAL_PATHS.get(normalized),
            restore_phase=RestorePhase.PRE_ADDON,
        )

    if normalized in {
        "chunk_target_chars",
        "chunk_max_chars",
        "stream_chunk_target_chars",
        "stream_chunk_max_chars",
        "stream_first_chunk_min_chars",
        "stream_force_flush_seconds",
        "stream_force_flush_later_seconds",
        "musetalk_chunk_target_chars",
        "musetalk_chunk_max_chars",
        "musetalk_quickstart_1_target_chars",
        "musetalk_quickstart_1_max_chars",
        "musetalk_quickstart_2_target_chars",
        "musetalk_quickstart_2_max_chars",
    }:
        return _policy(
            normalized,
            owner="core.runtime",
            lifetime=SettingLifetime.RUNTIME_SESSION,
            canonical_path=_LEGACY_CANONICAL_PATHS.get(normalized),
            restore_phase=RestorePhase.PRE_ADDON,
        )

    if normalized in _LEGACY_CANONICAL_PATHS:
        return _policy(
            normalized,
            owner="core.runtime",
            lifetime=SettingLifetime.RUNTIME_SESSION,
            canonical_path=_LEGACY_CANONICAL_PATHS[normalized],
            restore_phase=RestorePhase.PRE_ADDON,
        )

    family_path = _family_canonical_path(normalized)
    if family_path is not None:
        return _policy(
            normalized,
            owner="core.runtime",
            lifetime=SettingLifetime.RUNTIME_SESSION,
            canonical_path=family_path,
            restore_phase=RestorePhase.PRE_ADDON,
        )
    return None


def policies_for_keys(keys: Mapping[str, Any] | Iterable[str]) -> dict[str, SettingPolicy]:
    requested = [str(key) for key in keys]
    policies: dict[str, SettingPolicy] = {}
    for key in requested:
        policy = policy_for_key(key)
        if policy is not None:
            policies[key] = policy
    return policies


def recognized_legacy_root_aliases() -> frozenset[str]:
    """Return the reviewed loose-root aliases recognized during migration."""

    return _RECOGNIZED_LEGACY_ROOT_ALIASES


def contract_inventory_keys() -> frozenset[str]:
    """Return static registry keys consumed by the generated contract ledger."""

    keys = set(_LEGACY_CANONICAL_PATHS)
    keys.update(EXTRA_CANONICAL_PATHS)
    keys.update(_TRANSIENT_KEYS)
    keys.update(_PERSONA_PROJECTION_KEYS)
    keys.update(_USER_IDENTITY_PROJECTION_KEYS)
    keys.update(_DITTO_DEFAULTS)
    keys.update(_GLOBAL_UI_KEYS)
    keys.update(_GLOBAL_APPLICATION_KEYS)
    keys.update({"addon_registry_state", "first_run"})
    return frozenset(keys)


def validate_contract(expected_keys: Mapping[str, Any] | Iterable[str], addon_declarations: Iterable[Any]) -> None:
    declarations = tuple(addon_declarations)
    declaration_keys = {str(declaration.config_key) for declaration in declarations}
    requested_keys = {str(key) for key in expected_keys}
    requested_keys.update(declaration_keys)
    policies = policies_for_keys(requested_keys)
    missing = sorted(requested_keys.difference(policies))
    if missing:
        raise ValueError(f"Unclassified settings: {', '.join(missing)}")

    path_owners: dict[tuple[str, ...], str] = {}
    for policy in policies.values():
        if policy.canonical_path is None:
            continue
        existing = path_owners.get(policy.canonical_path)
        if existing is not None and existing != policy.key:
            raise ValueError(
                "Duplicate canonical path "
                f"{policy.canonical_path!r} for {existing!r} and {policy.key!r}"
            )
        path_owners[policy.canonical_path] = policy.key

    grouped: dict[str, list[Any]] = defaultdict(list)
    for declaration in declarations:
        grouped[str(declaration.config_key)].append(declaration)

    for config_key, declarations in grouped.items():
        if len(declarations) < 2:
            continue
        values = [item.default_value for item in declarations]
        if any(value != values[0] for value in values[1:]):
            raise ValueError(
                f"Conflicting addon runtime defaults for {config_key!r}: "
                f"{sorted({item.addon_id for item in declarations})}"
            )
        expected_owner = _ADDON_OWNER_OVERRIDES.get(config_key)
        if expected_owner is None:
            continue
        if expected_owner not in {item.addon_id for item in declarations}:
            raise ValueError(
                f"Runtime default owner override for {config_key!r} points to a missing addon."
            )
        policy = policies.get(config_key) or policy_for_key(config_key)
        if policy is None or policy.owner != expected_owner:
            raise ValueError(
                f"Policy owner for {config_key!r} must be {expected_owner!r}."
            )

    assert policy_for_key("first_run").canonical_path == ("ui", "onboarding", "first_run")
    assert policy_for_key("addon_registry_state").canonical_path == ("addon_registry_state",)


def _path_matches(pattern: tuple[str, ...], path: tuple[str, ...]) -> bool:
    if len(pattern) != len(path):
        return False
    for expected, actual in zip(pattern, path):
        if expected.startswith("{") and expected.endswith("}"):
            continue
        if expected != actual:
            return False
    return True


def _candidate_policy_keys(path: tuple[str, ...]) -> tuple[str, ...]:
    candidates: set[str] = set()
    if not path:
        return ()
    candidates.add(path[0])
    for index in range(len(path)):
        candidates.add("_".join(path[index:]))
    if len(path) >= 2:
        candidates.add(f"{path[0]}_{path[-1]}")
    return tuple(sorted(candidate for candidate in candidates if candidate))


def _matching_policy(path: tuple[str, ...]) -> SettingPolicy | None:
    for key in _candidate_policy_keys(path):
        policy = policy_for_key(key)
        canonical_path = getattr(policy, "canonical_path", None)
        if policy is None or canonical_path is None:
            continue
        if _path_matches(canonical_path, path):
            return policy
    return None


def _is_sensitive_key(key: str) -> bool:
    lowered = str(key or "").strip().lower()
    return lowered in CREDENTIAL_FIELD_NAMES or any(
        lowered.endswith(suffix) for suffix in _CREDENTIAL_FIELD_SUFFIXES
    )


def _shared_path_owner(path: tuple[str, ...]) -> str | None:
    matches = [
        (len(pattern), owner)
        for owner, patterns in ADDON_SESSION_PATH_PATTERNS.items()
        for pattern in patterns
        if len(path) >= len(pattern) and path[: len(pattern)] == pattern
    ]
    if not matches:
        return None
    longest = max(length for length, _owner in matches)
    owners = {owner for length, owner in matches if length == longest}
    if len(owners) != 1:
        return None
    return next(iter(owners))


def _credential_path_allowed(
    path: tuple[str, ...],
    allowed_paths: tuple[tuple[str, ...], ...],
) -> bool:
    for pattern in allowed_paths:
        if len(pattern) != len(path):
            continue
        if all(
            expected == actual
            or (expected.startswith("{") and expected.endswith("}"))
            for expected, actual in zip(pattern, path)
        ):
            return True
    return False


def _sanitize_value(
    value: Any,
    *,
    path: tuple[str, ...] = (),
    allowed_credential_paths: tuple[tuple[str, ...], ...] = (),
) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for raw_key, raw_item in value.items():
            key = str(raw_key)
            child_path = (*path, key)
            if _is_sensitive_key(key) and not _credential_path_allowed(
                child_path, allowed_credential_paths
            ):
                continue
            sanitized[key] = _sanitize_value(
                raw_item,
                path=child_path,
                allowed_credential_paths=allowed_credential_paths,
            )
        return sanitized
    if isinstance(value, list):
        return [
            _sanitize_value(
                item,
                path=path,
                allowed_credential_paths=allowed_credential_paths,
            )
            for item in value
        ]
    if isinstance(value, tuple):
        return [
            _sanitize_value(
                item,
                path=path,
                allowed_credential_paths=allowed_credential_paths,
            )
            for item in value
        ]
    return value


def sanitize_session_value(
    value: Any,
    *,
    allowed_credential_paths: tuple[tuple[str, ...], ...] = (),
) -> Any:
    return _sanitize_value(
        value,
        allowed_credential_paths=allowed_credential_paths,
    )


def _deep_merge(target: dict[str, Any], incoming: Mapping[str, Any]) -> None:
    for raw_key, raw_value in incoming.items():
        key = str(raw_key)
        if isinstance(raw_value, Mapping) and isinstance(target.get(key), dict):
            _deep_merge(target[key], raw_value)
            continue
        if isinstance(raw_value, Mapping):
            target[key] = _sanitize_value(raw_value)
            continue
        target[key] = raw_value


def _normalized_root_namespaces(addon_id: str) -> frozenset[str]:
    if addon_id == "core.addons.manager":
        return frozenset({"addon_registry_state", "tts_runtime"})
    return EXPECTED_ADDON_SESSION_NAMESPACES.get(str(addon_id or "").strip(), frozenset())


def _append_mismatch(
    mismatches: list[AddonPayloadMismatch],
    addon_id: str,
    path: tuple[str, ...],
    reason: str,
) -> None:
    mismatch = AddonPayloadMismatch(addon_id=str(addon_id or "").strip(), path=path, reason=reason)
    if mismatch not in mismatches:
        mismatches.append(mismatch)


def _nested_set(
    payload: dict[str, Any],
    path: tuple[str, ...],
    value: Any,
    *,
    allowed_credential_paths: tuple[tuple[str, ...], ...] = (),
) -> None:
    current = payload
    for part in path[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[path[-1]] = _sanitize_value(
        value,
        path=path,
        allowed_credential_paths=allowed_credential_paths,
    )


def _validate_allowed_root(
    addon_id: str,
    root: str,
    value: Any,
    *,
    path_prefix: tuple[str, ...],
    mismatches: list[AddonPayloadMismatch],
    allowed_credential_paths: tuple[tuple[str, ...], ...] = (),
) -> Any:
    sanitized = _sanitize_value(
        value,
        path=path_prefix,
        allowed_credential_paths=allowed_credential_paths,
    )
    if not isinstance(sanitized, Mapping):
        policy = _matching_policy(path_prefix)
        if policy is not None and policy.owner != addon_id:
            _append_mismatch(
                mismatches,
                addon_id,
                path_prefix,
                f"recognized path belongs to {policy.owner}",
            )
            return {}
        return sanitized
    validated: dict[str, Any] = {}
    for raw_key, raw_item in sanitized.items():
        key = str(raw_key)
        child_path = (*path_prefix, key)
        if isinstance(raw_item, Mapping):
            child_value = _validate_allowed_root(
                addon_id,
                root,
                raw_item,
                path_prefix=child_path,
                mismatches=mismatches,
                allowed_credential_paths=allowed_credential_paths,
            )
            if child_value != {} or raw_item == {}:
                validated[key] = child_value
            continue
        policy = _matching_policy(child_path)
        shared_owner = _shared_path_owner(child_path)
        if root in _SHARED_ADDON_SESSION_ROOTS and shared_owner != addon_id:
            _append_mismatch(
                mismatches,
                addon_id,
                child_path,
                (
                    f"shared path belongs to {shared_owner}"
                    if shared_owner is not None
                    else "shared path has no unambiguous declared owner"
                ),
            )
            continue
        if policy is not None and policy.owner != addon_id:
            _append_mismatch(
                mismatches,
                addon_id,
                child_path,
                f"recognized path belongs to {policy.owner}",
            )
            continue
        validated[key] = raw_item
    return validated


def normalize_addon_session_payload(
    addon_id: str,
    payload: Mapping[str, Any] | None,
) -> AddonPayloadNormalization:
    normalized_addon_id = str(addon_id or "").strip()
    allowed_credential_paths = _ADDON_PERSISTED_CREDENTIAL_PATHS.get(
        normalized_addon_id, ()
    )
    source = _sanitize_value(
        dict(payload or {}),
        allowed_credential_paths=allowed_credential_paths,
    )
    allowed_roots = _normalized_root_namespaces(normalized_addon_id)
    if not allowed_roots:
        fallback: dict[str, Any] = {}
        for raw_key, raw_value in source.items():
            key = str(raw_key)
            policy = policy_for_key(key)
            if policy is not None and policy.canonical_path is not None:
                _nested_set(
                    fallback,
                    policy.canonical_path,
                    raw_value,
                    allowed_credential_paths=allowed_credential_paths,
                )
                continue
            fallback[key] = raw_value
        return AddonPayloadNormalization(payload=fallback, mismatches=())
    normalized: dict[str, Any] = {}
    mismatches: list[AddonPayloadMismatch] = []

    for raw_key, raw_value in source.items():
        key = str(raw_key)
        path = (key,)
        policy = policy_for_key(key)
        if (
            policy is not None
            and policy.canonical_path is not None
            and policy.owner == normalized_addon_id
            and policy.canonical_path[0] in allowed_roots
        ):
            _nested_set(
                normalized,
                policy.canonical_path,
                raw_value,
                allowed_credential_paths=allowed_credential_paths,
            )
            continue
        if key in allowed_roots:
            if isinstance(raw_value, Mapping):
                validated = _validate_allowed_root(
                    normalized_addon_id,
                    key,
                    raw_value,
                    path_prefix=path,
                    mismatches=mismatches,
                    allowed_credential_paths=allowed_credential_paths,
                )
                if validated != {} or raw_value == {}:
                    normalized[key] = validated
            else:
                matched = _matching_policy(path)
                if matched is not None and matched.owner != normalized_addon_id:
                    _append_mismatch(
                        mismatches,
                        normalized_addon_id,
                        path,
                        f"recognized path belongs to {matched.owner}",
                    )
                elif matched is not None and matched.owner == normalized_addon_id and matched.canonical_path == path:
                    normalized[key] = raw_value
                else:
                    _append_mismatch(
                        mismatches,
                        normalized_addon_id,
                        path,
                        "declared namespace root requires mapping",
                    )
            continue
        owner = getattr(policy, "owner", "")
        if policy is not None and policy.canonical_path is not None:
            reason = f"recognized key belongs to {owner or 'another owner'}"
        else:
            reason = f"unowned path outside declared namespaces {sorted(allowed_roots)}"
        _append_mismatch(mismatches, normalized_addon_id, path, reason)
    return AddonPayloadNormalization(
        payload=normalized,
        mismatches=tuple(sorted(mismatches, key=lambda item: (item.addon_id, item.path, item.reason))),
    )


__all__ = [
    "ADDON_SESSION_PATH_PATTERNS",
    "CREDENTIAL_FIELD_NAMES",
    "EXTRA_CANONICAL_PATHS",
    "AddonPayloadMismatch",
    "AddonPayloadNormalization",
    "EXPECTED_ADDON_SESSION_NAMESPACES",
    "LegacySource",
    "PRESET_ELIGIBLE_KEYS",
    "ROOT_METADATA_KEYS",
    "RestorePhase",
    "SettingLifetime",
    "SettingPolicy",
    "contract_inventory_keys",
    "sanitize_session_value",
    "normalize_addon_session_payload",
    "policies_for_keys",
    "policy_for_key",
    "recognized_legacy_root_aliases",
    "validate_contract",
]
