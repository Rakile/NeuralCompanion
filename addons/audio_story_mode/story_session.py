from __future__ import annotations

from copy import deepcopy


def _copy_mapping(value) -> dict:
    return deepcopy(value) if isinstance(value, dict) else {}


def _copy_list(value) -> list:
    if isinstance(value, (list, tuple)):
        return [deepcopy(item) for item in value]
    return []


def build_story_state_flat_payload(
    *,
    story_bible=None,
    scene_plan=None,
    scene_overrides=None,
    continuity_memory=None,
    character_anchors=None,
    location_anchors=None,
    transcript_chunks=None,
    full_transcript_text: str = "",
    raw_transcript_segments=None,
    audio_duration_seconds: float = 0.0,
) -> dict:
    """Return session-schema legacy keys for restorable Audio Story state."""

    try:
        duration = max(0.0, float(audio_duration_seconds or 0.0))
    except Exception:
        duration = 0.0
    return {
        "audio_story_mode_story_bible": _copy_mapping(story_bible),
        "audio_story_mode_scene_plan": _copy_list(scene_plan),
        "audio_story_mode_scene_overrides": _copy_mapping(scene_overrides),
        "audio_story_mode_continuity_memory": _copy_mapping(continuity_memory),
        "audio_story_mode_character_anchors": _copy_mapping(character_anchors),
        "audio_story_mode_location_anchors": _copy_mapping(location_anchors),
        "audio_story_mode_transcript_chunks": _copy_list(transcript_chunks),
        "audio_story_mode_full_transcript_text": str(full_transcript_text or "").strip(),
        "audio_story_mode_raw_transcript_segments": _copy_list(raw_transcript_segments),
        "audio_story_mode_audio_duration_seconds": duration,
    }


def restore_story_overrides(value) -> dict:
    source = _copy_mapping(value)
    return {
        "pinned_character_ids": list(source.get("pinned_character_ids", []) or []),
        "pinned_location_ids": list(source.get("pinned_location_ids", []) or []),
        "forced_scene_modes": dict(source.get("forced_scene_modes", {}) or {}),
        "scene_anchor_overrides": dict(source.get("scene_anchor_overrides", {}) or {}),
        "global_scene_anchor": str(source.get("global_scene_anchor", "") or "").strip(),
        "global_scene_anchor_enabled": bool(source.get("global_scene_anchor_enabled", False)),
        "scene_negative_prompt_overrides": dict(source.get("scene_negative_prompt_overrides", {}) or {}),
        "global_negative_prompt": str(source.get("global_negative_prompt", "") or "").strip(),
        "global_negative_prompt_enabled": bool(source.get("global_negative_prompt_enabled", False)),
    }
