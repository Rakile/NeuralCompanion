from __future__ import annotations

import copy
from collections import OrderedDict
from collections.abc import Mapping


SESSION_KEY = "audio_story_mode"

LEGACY_FIELD_PATHS = OrderedDict(
    (
        ("audio_story_mode_audio_path", ("audio", "audio_path")),
        ("audio_story_mode_playback_mode", ("audio", "playback_mode")),
        ("audio_story_mode_transcribe_seconds", ("audio", "transcribe_seconds")),
        ("audio_story_mode_transcription_start_seconds", ("audio", "transcription_start_seconds")),
        ("audio_story_mode_transcription_end_seconds", ("audio", "transcription_end_seconds")),
        ("audio_story_mode_image_frequency_seconds", ("timing", "image_frequency_seconds")),
        ("audio_story_mode_image_timing_mode", ("timing", "image_timing_mode")),
        ("audio_story_mode_generate_ahead_frames", ("timing", "generate_ahead_frames")),
        ("audio_story_mode_analysis_mode", ("analysis", "analysis_mode")),
        ("audio_story_mode_use_llm_story_analysis", ("analysis", "use_llm_story_analysis")),
        ("audio_story_mode_story_analysis_provider_mode", ("analysis", "story_analysis_provider_mode")),
        ("audio_story_mode_story_analysis_model", ("analysis", "story_analysis_model")),
        ("audio_story_mode_continuity_strength", ("visuals", "continuity_strength")),
        ("audio_story_mode_cost_profile", ("visuals", "cost_profile")),
        ("audio_story_mode_style_prompts", ("visuals", "style_prompts")),
        ("audio_story_mode_style_labels", ("visuals", "style_labels")),
        ("audio_story_mode_style_enabled", ("visuals", "style_enabled")),
        ("audio_story_mode_style_change_live", ("visuals", "style_change_live")),
        ("audio_story_mode_xai_image_settings", ("visuals", "xai_image_settings")),
        ("audio_story_mode_prompt_block_limits", ("visuals", "prompt_block_limits")),
        ("audio_story_mode_prompt_safety_cap", ("visuals", "prompt_safety_cap")),
        ("audio_story_mode_visual_stream_enabled", ("visuals", "visual_stream_enabled")),
        ("audio_story_mode_visual_stream_port", ("visuals", "visual_stream_port")),
        ("audio_story_mode_story_master_prompt_enabled", ("story", "story_master_prompt_enabled")),
        ("audio_story_mode_story_master_prompt_mode", ("story", "story_master_prompt_mode")),
        ("audio_story_mode_story_bible", ("story", "story_bible")),
        ("audio_story_mode_scene_plan", ("story", "scene_plan")),
        ("audio_story_mode_scene_overrides", ("story", "scene_overrides")),
        ("audio_story_mode_continuity_memory", ("story", "continuity_memory")),
        ("audio_story_mode_character_anchors", ("story", "character_anchors")),
        ("audio_story_mode_location_anchors", ("story", "location_anchors")),
        ("audio_story_mode_transcript_chunks", ("story", "transcript_chunks")),
        ("audio_story_mode_full_transcript_text", ("story", "full_transcript_text")),
        ("audio_story_mode_raw_transcript_segments", ("story", "raw_transcript_segments")),
        ("audio_story_mode_audio_duration_seconds", ("audio", "audio_duration_seconds")),
        ("audio_story_mode_chromecast_device_name", ("chromecast", "device_name")),
        ("audio_story_mode_chromecast_cast_active", ("chromecast", "cast_active")),
        ("audio_story_mode_chromecast_show_prompt", ("chromecast", "show_prompt")),
    )
)

_MISSING = object()


def _mapping(value) -> dict:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _nested_get(payload: Mapping, path: tuple[str, str]):
    current = payload
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return _MISSING
        current = current.get(part)
    return current


def _nested_set(payload: dict, path: tuple[str, str], value) -> None:
    current = payload
    for part in path[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[path[-1]] = copy.deepcopy(value)


def normalize_audio_story_mode_settings(session_or_settings) -> dict:
    source = _mapping(session_or_settings)
    grouped = _mapping(source.get(SESSION_KEY))
    if not grouped and any(key in source for key in LEGACY_FIELD_PATHS):
        grouped = {}
    else:
        grouped = copy.deepcopy(grouped)

    for legacy_key, path in LEGACY_FIELD_PATHS.items():
        if legacy_key in source and _nested_get(grouped, path) is _MISSING:
            _nested_set(grouped, path, source.get(legacy_key))

    return grouped


def flatten_audio_story_mode_settings(session_or_settings) -> dict:
    grouped = normalize_audio_story_mode_settings(session_or_settings)
    flattened = {}
    for legacy_key, path in LEGACY_FIELD_PATHS.items():
        value = _nested_get(grouped, path)
        if value is not _MISSING:
            flattened[legacy_key] = copy.deepcopy(value)
    return flattened


def audio_story_mode_session_payload(flat_settings: Mapping) -> dict:
    return {SESSION_KEY: normalize_audio_story_mode_settings(dict(flat_settings or {}))}


def audio_story_mode_session_value(session_or_settings, legacy_key: str, default=None):
    path = LEGACY_FIELD_PATHS.get(str(legacy_key or ""))
    if path is None:
        return default
    grouped = normalize_audio_story_mode_settings(session_or_settings)
    value = _nested_get(grouped, path)
    if value is _MISSING:
        return default
    return value
