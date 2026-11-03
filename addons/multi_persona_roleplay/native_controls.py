"""Typed native-QML state bindings for Multi Persona Roleplay.

The frozen control inventory lives in :mod:`native_contract`.  This module
maps that presentation contract onto the authoritative MPRC session, persona,
settings, story, audio, remote, and playback models without reading or writing
QWidget state.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from addons.multi_persona_roleplay.models import AR_MODE, SESSION_MODE_DESCRIPTIONS, normalize_persona_id, unique_persona_id
from addons.multi_persona_roleplay.native_contract import MPRC_CONTROL_SPECS


_SPECS = {str(spec[0]): spec for spec in MPRC_CONTROL_SPECS}
_READ_ONLY = {str(spec[0]) for spec in MPRC_CONTROL_SPECS if bool(spec[6])}
_ACTION_IDS = {str(spec[0]) for spec in MPRC_CONTROL_SPECS if str(spec[2]) == "action"}

_PERSONA_FIELDS = {
    "mprc_persona_id": "id",
    "mprc_persona_enabled": "enabled",
    "mprc_master_narrator": "master_narrator",
    "mprc_display_name": "display_name",
    "mprc_role": "role",
    "mprc_description": "description",
    "mprc_character_image_path": "character_image_path",
    "mprc_system_prompt": "system_prompt",
    "mprc_ar_profile_enabled": "ar_profile_enabled",
    "mprc_ar_description": "ar_description",
    "mprc_ar_system_prompt": "ar_system_prompt",
    "mprc_speaking_style": "speaking_style",
    "mprc_allowed_tone": "allowed_tone",
    "mprc_response_length": "response_length",
    "mprc_temperature_hint": "temperature_hint",
    "mprc_memory_scope": "memory_scope",
    "mprc_behavior_mode": "behavior_mode",
    "mprc_tags": "tags",
}

_VISUAL_FIELDS = {
    "mprc_visual_enabled": "enabled",
    "mprc_visual_mode": "mode",
    "mprc_visual_provider": "provider",
    "mprc_visual_model": "model",
    "mprc_visual_size": "size",
    "mprc_visual_style": "style_preset",
    "mprc_visual_character": "character_description",
    "mprc_visual_clothing": "clothing_props",
    "mprc_visual_environment": "environment_style",
    "mprc_visual_negative": "negative_prompt",
    "mprc_visual_continuity": "keep_continuity",
    "mprc_visual_appearance_freedom": "appearance_freedom",
    "mprc_visual_scene": "include_scene_summary",
    "mprc_visual_speaker": "include_active_speaker",
    "mprc_visual_interval": "auto_reply_interval",
    "mprc_visual_cooldown": "cooldown_seconds",
    "mprc_visual_max_auto": "max_auto_images_per_session",
    "mprc_visual_auto_show": "auto_show_dock",
}

_VOICE_FIELDS = {
    "mprc_voice_enabled": "enabled",
    "mprc_voice_backend": "backend",
    "mprc_voice_sample": "sample_path",
    "mprc_voice_sample_picker": "sample_path",
    "mprc_voice_preset": "preset_name",
    "mprc_voice_language": "language",
}

_SESSION_FIELDS = {
    "mprc_session_mode": "mode",
    "mprc_scene_title": "scene_title",
    "mprc_location": "location",
    "mprc_time_of_day": "time_of_day",
    "mprc_mood": "mood",
    "mprc_objective": "objective",
    "mprc_scene_summary": "scene_summary",
    "mprc_auto_select": "auto_select_speaker",
    "mprc_continuity": "keep_scene_continuity",
    "mprc_update_scene": "update_scene_after_reply",
}

_AR_FIELDS = {
    "mprc_ar_current_scene": "current_scene",
    "mprc_ar_location": "location",
    "mprc_ar_time_of_day": "time_of_day",
    "mprc_ar_mood": "mood",
    "mprc_ar_story_goal": "story_goal",
    "mprc_ar_player_intent": "player_intent",
    "mprc_ar_tension": "tension_level",
}

_SETTING_FIELDS = {
    "mprc_current_character_view_mode": "current_character_view_mode",
    "mprc_audio_story_sounds": "story_sounds_enabled",
    "mprc_audiofx_volume": "audiofx_volume",
    "mprc_audiofx_test_mode": "audiofx_test_mode",
    "mprc_audio_sound_description": "audio_prompt_description",
    "mprc_audio_type": "audio_prompt_type",
    "mprc_audio_prompt_output": "audio_prompt_output",
    "mprc_master_story_prompt": "master_story_prompt",
    "mprc_master_story_mode": "master_story_mode",
    "mprc_master_story_scene_title": "master_story_scene_title",
    "mprc_master_story_location": "master_story_location",
    "mprc_master_story_time_of_day": "master_story_time_of_day",
    "mprc_master_story_mood": "master_story_mood",
    "mprc_master_story_visual_direction": "master_story_visual_direction",
    "mprc_master_story_sfw_mode": "master_story_sfw_mode",
    "mprc_master_story_native_persona_count": "master_story_native_persona_count",
    "mprc_master_story_max_created_characters": "master_story_max_created_characters",
    "mprc_master_story_allow_exceed_max_created_characters": "master_story_allow_exceed_max_created_characters",
    "mprc_master_story_use_existing_personas": "master_story_use_existing_personas",
    "mprc_master_story_auto_create": "master_story_auto_create",
    "mprc_master_story_auto_assign_voices": "master_story_auto_assign_voices",
    "mprc_master_story_update_existing": "master_story_update_existing",
    "mprc_master_story_auto_avatars": "master_story_auto_avatars",
    "mprc_master_story_avatar_style_sheets": "master_story_avatar_style_sheets",
    "mprc_master_story_clear_memory": "master_story_clear_memory",
    "mprc_chat_visuals_checkbox": "chat_play_allow_story_visuals",
    "mprc_chat_director_tone_combo": "chat_director_tone",
    "mprc_chat_director_agency_combo": "chat_director_agency",
    "mprc_chat_director_choice_mode_combo": "chat_choice_mode",
    "mprc_chat_input_legacy": "native_chat_input_legacy",
    "mprc_chat_input": "native_chat_input",
    "mprc_chat_voice_volume_slider": "mprc_chat_voice_volume",
    "mprc_chat_intent_combo": "native_chat_intent",
    "mprc_chat_structured_output_checkbox": "chat_structured_output_enabled",
    "mprc_chat_structured_output_scope_combo": "chat_structured_output_scope",
    "mprc_chat_instructor_structured_outputs_checkbox": "mprc_instructor_structured_outputs_enabled",
    "mprc_chat_instructor_ar_turn_checkbox": "mprc_instructor_ar_turn_enabled",
    "mprc_chat_story_font_size_spin": "mprc_chat_story_font_size",
    "mprc_chat_remote_enabled_checkbox": "remote_enabled",
    "mprc_chat_remote_host_input": "remote_host",
    "mprc_chat_remote_port_spin": "remote_port",
    "mprc_chat_remote_code_spin": "remote_code",
    "mprc_chat_chromecast_device_combo": "chromecast_device_name",
    "mprc_chat_play_toolbar_advanced_toggle": "chat_play_toolbar_advanced",
}

_EXPORT_FIELDS = {
    "unnamed_qcheckbox_story_setup_session_state": "story_setup",
    "unnamed_qcheckbox_story_library_entry_story_metadata": "story_metadata",
    "unnamed_qcheckbox_personas_used_by_this_story_4": "personas",
    "unnamed_qcheckbox_persona_visual_settings": "persona_visual",
    "unnamed_qcheckbox_persona_avatar_image_files": "avatar_assets",
    "unnamed_qcheckbox_persona_voice_settings": "persona_voice",
    "unnamed_qcheckbox_voice_sample_audio_files": "voice_assets",
    "unnamed_qcheckbox_story_memory": "story_memory",
    "unnamed_qcheckbox_recent_story_events_story_log_4": "story_events",
    "unnamed_qcheckbox_sound_effects_audiofx_settings": "audiofx",
    "unnamed_qcheckbox_sound_effect_audio_files": "audiofx_assets",
    "unnamed_qcheckbox_visual_styles_used_by_story": "visual_styles",
    "unnamed_qcheckbox_master_story_draft_setup_data_if_available": "master_story",
    "unnamed_qcheckbox_story_prompt_template_data_if_available": "templates",
}

_EXPANSION_FIELDS = {
    control_id
    for control_id, spec in _SPECS.items()
    if str(spec[2]) == "boolean" and control_id.startswith("unnamed_qgroupbox_")
}


def _json(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def _lines(value: Any, *, limit: int = 20) -> list[str]:
    if isinstance(value, str):
        source = value.splitlines()
    elif isinstance(value, (list, tuple, set)):
        source = list(value)
    else:
        source = []
    return [str(item).strip() for item in source if str(item).strip()][:limit]


def _selected_persona(controller: Any) -> Any:
    selected = normalize_persona_id(
        controller.settings.get("native_selected_persona_id")
        or controller.session.active_persona_id
        or ""
    )
    persona = controller.persona_by_id(selected)
    if persona is None and controller.personas:
        persona = controller.personas[0]
        controller.settings["native_selected_persona_id"] = persona.id
    return persona


def _voice_persona(controller: Any) -> Any:
    if bool(controller.settings.get("voice_follow_active_persona", True)):
        return controller.active_persona() or _selected_persona(controller)
    selected = normalize_persona_id(
        controller.settings.get("voice_edit_persona_id") or ""
    )
    return controller.persona_by_id(selected) or _selected_persona(controller)


def _persona_options(controller: Any) -> tuple[tuple[str, str], ...]:
    return tuple((persona.id, persona.display_name or persona.id) for persona in controller.personas)


def _story_options(controller: Any) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []
    for story in controller.storage.load_story_index():
        if not isinstance(story, dict):
            continue
        story_id = controller.storage.story_id(story.get("id") or "")
        if story_id:
            result.append((story_id, str(story.get("title") or story_id)))
    return tuple(result or (("", "No saved stories"),))


def _voice_samples(controller: Any) -> tuple[tuple[str, str], ...]:
    paths: list[str] = []
    for candidate in list(controller.available_story_audio_files() or []):
        path = str(candidate or "").strip()
        if path and path not in paths:
            paths.append(path)
    for persona in controller.personas:
        path = str(getattr(persona.voice, "sample_path", "") or "").strip()
        if path and path not in paths:
            paths.append(path)
    return tuple((path, Path(path).name or path) for path in paths) or (("", "No voice sample"),)


def _memory_options(controller: Any) -> tuple[tuple[str, str], ...]:
    browser = dict(getattr(controller, "_native_memory_browser", {}) or {})
    entries = list(browser.get("entries") or browser.get("items") or [])
    result: list[tuple[str, str]] = []
    for index, item in enumerate(entries):
        if isinstance(item, dict):
            value = str(item.get("id") or item.get("key") or index)
            label = str(item.get("label") or item.get("title") or item.get("summary") or value)
        else:
            value = str(index)
            label = str(item)
        result.append((value, label))
    return tuple(result or (("", "No story memory snapshots"),))


def native_control_state(controller: Any) -> dict[str, Any]:
    """Return values and dynamic choices for every frozen MPRC control."""

    values = {control_id: copy.deepcopy(spec[4]) for control_id, spec in _SPECS.items()}
    options: dict[str, tuple[tuple[Any, str], ...]] = {}
    enabled: dict[str, bool] = {}
    persona = _selected_persona(controller)
    voice_persona = _voice_persona(controller)
    session = controller.session
    ar_state = session.ar_state
    presentation = {
        "debug": copy.deepcopy(getattr(controller, "_native_debug_state", {}) or {}),
        "play": copy.deepcopy(getattr(controller, "_native_play_controls", {}) or {}),
        "remote": copy.deepcopy(getattr(controller, "_native_remote_controls", {}) or {}),
        "cast": copy.deepcopy(getattr(controller, "_native_chromecast_controls", {}) or {}),
        "character": copy.deepcopy(getattr(controller, "_native_character_preview", {}) or {}),
    }

    values.update(
        {
            "mprc_enabled_checkbox": bool(session.enabled),
            "mprc_show_character_checkbox": bool(controller.settings.get("show_current_character_visual", False)),
            "mprc_ar_mode_checkbox": session.mode == AR_MODE,
            "mprc_active_persona_combo": str(session.active_persona_id or ""),
            "mprc_current_character_view_mode": str(controller.settings.get("current_character_view_mode") or "active_story"),
            "mprc_current_character_name": str((presentation["character"] or {}).get("display_name") or getattr(persona, "display_name", "No active persona")),
            "mprc_debug_prompt": _json(presentation["debug"].get("prompt") or presentation["debug"].get("persona_prompt") or ""),
            "mprc_debug_visual": _json(presentation["debug"].get("visual") or presentation["debug"].get("image_prompt") or ""),
            "mprc_debug_voice": _json(presentation["debug"].get("voice") or getattr(controller, "_native_voice_status", "")),
            "mprc_debug_state": _json(session.to_dict()),
            "mprc_debug_visual_calls": _json(getattr(controller, "_visual_debug_log", []) or "No Visual Reply calls have been recorded yet."),
            "mprc_master_story_list": str(controller.settings.get("native_selected_story_id") or ""),
            "mprc_master_story_status": str(getattr(controller, "_native_master_story_status", "") or "Ready."),
            "mprc_story_export_status": _json(getattr(controller, "_native_story_export_preview", {}) or "No export preview yet."),
            "mprc_master_story_draft": _json(getattr(controller, "_master_story_draft", {}) or controller.settings.get("master_story_draft") or ""),
            "mprc_ar_enabled": session.mode == AR_MODE,
            "mprc_ar_use_persona_profiles": bool(session.ar_use_persona_profiles),
            "mprc_ar_pacing": session.ar_pacing,
            "mprc_ar_interaction": session.ar_interaction_frequency,
            "mprc_ar_dialogue_density": session.ar_dialogue_density,
            "mprc_ar_active_characters": ", ".join(ar_state.active_characters),
            "mprc_ar_pending_choices": "\n".join(ar_state.pending_choices),
            "mprc_ar_recent_events": "\n".join(ar_state.recent_events),
            "mprc_session_mode_note": str(SESSION_MODE_DESCRIPTIONS.get(session.mode) or "Choose how personas, narration, and story direction are framed for the current scene."),
            "mprc_roster": "\n".join(f"{item.display_name} ({item.id}) - {item.behavior_mode}" for item in controller.personas if item.enabled),
            "mprc_next_speaker": str(session.current_speaker_id or session.active_persona_id or ""),
            "mprc_narrator_persona": str(controller.settings.get("narrator_persona_id") or ""),
            "mprc_voice_follow_active": bool(controller.settings.get("voice_follow_active_persona", True)),
            "mprc_voice_current_persona": str(getattr(voice_persona, "display_name", "No persona")),
            "mprc_voice_persona": str(getattr(voice_persona, "id", "")),
            "mprc_chat_voice_segments_summary": _json(presentation["debug"].get("voice_segments") or getattr(controller, "_native_voice_status", "")),
            "mprc_persona_list": str(getattr(persona, "id", "")),
            "mprc_story_status": str(controller._story_runtime_status_text()),
            "mprc_story_validation": _json((getattr(controller, "_native_action_result", {}) or {}).get("validation") or "Run Validate Story to refresh this report."),
            "mprc_story_voice_routes": _json(presentation["debug"].get("voice_routes") or presentation["debug"].get("voice") or {}),
            "mprc_story_next_inspector": str(getattr(controller, "_native_story_inspector", "") or "No inspector report yet."),
            "mprc_story_pinned_facts": _json((getattr(controller, "_native_memory_browser", {}) or {}).get("pinned_facts") or []),
            "mprc_story_template": str(controller.settings.get("native_story_template_id") or "fantasy_mystery"),
            "mprc_story_event_log": _json(getattr(controller, "_story_event_log", [])),
            "mprc_chat_spotify_music_summary": _json(getattr(controller, "_last_spotify_story_music_result", {}) or "No Spotify story-music request yet."),
            "mprc_chat_visual_beat_summary": _json(presentation["debug"].get("visual_beat") or {}),
            "mprc_chat_memory_databank_summary": _json(getattr(controller, "_native_memory_browser", {}) or {}),
            "mprc_chat_story_director_summary": _json(presentation["play"].get("director") or {}),
            "mprc_chat_director_pacing_combo": str(session.ar_pacing or "Balanced"),
            "mprc_chat_next_actions_list": str(controller.settings.get("native_next_action") or ""),
            "mprc_chat_recent_events_list": str(controller.settings.get("native_recent_event") or ""),
            "mprc_chat_present_characters_list": str(controller.settings.get("native_present_character") or ""),
            "mprc_chat_scene_state_label": str(session.scene_title or session.ar_state.current_scene or "No active scene"),
            "mprc_visual_prompt_debug_text": _json(presentation["debug"].get("visual_prompt") or ""),
            "mprc_chat_use_ar_checkbox": session.mode == AR_MODE,
            "mprc_chat_transcript": _json(getattr(controller, "_native_chat_transcript", [])),
            "mprc_buffer_race_summary": str(presentation["play"].get("buffer_summary") or "Buffer idle"),
            "mprc_buffer_race_render_bar": int(presentation["play"].get("render_progress", 0) or 0),
            "mprc_buffer_race_playback_bar": int(presentation["play"].get("playback_progress", 0) or 0),
            "mprc_chat_status_label": str(getattr(controller, "_native_chat_status", "") or "Ready."),
            "mprc_chat_speaker_combo": str(controller.settings.get("native_chat_speaker_id") or session.current_speaker_id or ""),
            "mprc_chat_chromecast_status_label": str(presentation["cast"].get("status") or "Chromecast idle."),
        }
    )

    if persona is not None:
        for control_id, attribute in _PERSONA_FIELDS.items():
            raw = getattr(persona, attribute)
            values[control_id] = ", ".join(raw) if attribute == "tags" else raw
        for control_id, attribute in _VISUAL_FIELDS.items():
            values[control_id] = getattr(persona.visual, attribute)
    if voice_persona is not None:
        for control_id, attribute in _VOICE_FIELDS.items():
            values[control_id] = getattr(voice_persona.voice, attribute)
    for control_id, attribute in _SESSION_FIELDS.items():
        values[control_id] = getattr(session, attribute)
    for control_id, attribute in _AR_FIELDS.items():
        values[control_id] = getattr(ar_state, attribute)
    for control_id, setting_key in _SETTING_FIELDS.items():
        values[control_id] = copy.deepcopy(controller.settings.get(setting_key, values.get(control_id)))

    selected_exports = set(controller._story_export_selected_sections())
    for control_id, export_key in _EXPORT_FIELDS.items():
        values[control_id] = export_key in selected_exports
    expanded = dict(controller.settings.get("native_mprc_expanded") or {})
    for control_id in _EXPANSION_FIELDS:
        values[control_id] = bool(expanded.get(control_id, values.get(control_id, False)))

    saved_prompts = list(getattr(controller, "_native_audio_saved_prompts", []) or [])
    audiofx = list(getattr(controller, "_native_audiofx_items", []) or [])
    values["mprc_audio_saved_prompts"] = int(controller.settings.get("native_selected_audio_prompt_index", -1) or -1)
    values["mprc_audiofx_list"] = int(controller.settings.get("native_selected_audiofx_index", -1) or -1)
    values["mprc_audiofx_status"] = _json(getattr(controller, "_native_audiofx_summary", {}) or {})
    values["mprc_story_memory_list"] = str(controller.settings.get("native_selected_memory_id") or "")

    persona_choices = _persona_options(controller)
    for control_id in (
        "mprc_active_persona_combo",
        "mprc_next_speaker",
        "mprc_narrator_persona",
        "mprc_voice_persona",
        "mprc_persona_list",
        "mprc_chat_speaker_combo",
    ):
        options[control_id] = persona_choices or (("", "No personas"),)
    options["mprc_master_story_list"] = _story_options(controller)
    options["mprc_voice_sample_picker"] = _voice_samples(controller)
    options["mprc_audio_saved_prompts"] = tuple(
        (index, str(item.get("label") or item.get("name") or item.get("prompt") or f"Prompt {index + 1}"))
        for index, item in enumerate(saved_prompts)
        if isinstance(item, dict)
    ) or ((-1, "No saved prompts"),)
    options["mprc_audiofx_list"] = tuple(
        (int(item.get("index", index)), str(item.get("label") or item.get("description") or f"Audio item {index + 1}"))
        for index, item in enumerate(audiofx)
        if isinstance(item, dict)
    ) or ((-1, "No AudioFX items"),)
    options["mprc_story_memory_list"] = _memory_options(controller)
    options["mprc_story_template"] = tuple(controller._story_template_choices()) or (("", "No story templates"),)
    options["mprc_chat_next_actions_list"] = tuple((item, item) for item in session.ar_state.pending_choices) or (("", "No pending actions"),)
    options["mprc_chat_recent_events_list"] = tuple((str(index), event) for index, event in enumerate(session.recent_events[-12:])) or (("", "No recent events"),)
    options["mprc_chat_present_characters_list"] = tuple(
        (item.id, item.display_name) for item in controller.personas if item.enabled
    ) or (("", "No present characters"),)
    cast_devices = list(presentation["cast"].get("devices") or [])
    options["mprc_chat_chromecast_device_combo"] = tuple(
        (
            controller._chromecast_device_name(item),
            controller._chromecast_device_name(item),
        )
        for item in cast_devices
        if isinstance(item, dict) and controller._chromecast_device_name(item)
    ) or (("", "No Chromecast devices"),)
    style_options = tuple(
        (
            str(item.get("id") or item.get("name") or ""),
            str(item.get("label") or item.get("name") or item.get("id") or "Style"),
        )
        for item in controller.visual_styles
        if isinstance(item, dict) and str(item.get("id") or item.get("name") or "").strip()
    )
    if style_options:
        options["mprc_visual_style"] = (("", "Default"), *style_options)

    enabled["mprc_voice_persona"] = not bool(controller.settings.get("voice_follow_active_persona", True))
    enabled["mprc_chat_structured_output_scope_combo"] = bool(controller.settings.get("chat_structured_output_enabled", False))
    enabled["mprc_chat_instructor_ar_turn_checkbox"] = bool(controller.settings.get("mprc_instructor_structured_outputs_enabled", False))
    enabled["mprc_chat_remote_enabled_checkbox"] = bool(controller._remote_server_installed())
    return {"values": values, "options": options, "enabled": enabled}


def _coerce(control_id: str, value: Any) -> Any:
    spec = _SPECS[control_id]
    kind = str(spec[2])
    if kind == "boolean":
        if isinstance(value, str):
            return value.strip().casefold() in {"1", "true", "yes", "on"}
        return bool(value)
    if kind in {"integer", "slider", "progress"}:
        return int(float(value or 0))
    return str(value or "") if kind in {"text", "multiline", "choice"} else value


def native_update_control(controller: Any, control_id: str, value: Any) -> dict[str, Any]:
    """Apply one frozen control through the authoritative MPRC models."""

    key = str(control_id or "").strip()
    if key not in _SPECS:
        raise KeyError(f"Unknown MPRC control {control_id!r}.")
    if key in _ACTION_IDS:
        raise ValueError(f"MPRC action {key!r} must be triggered, not edited.")
    if key in _READ_ONLY:
        raise ValueError(f"MPRC control {key!r} is read-only.")
    converted = _coerce(key, value)
    persona = _selected_persona(controller)
    voice_persona = _voice_persona(controller)
    session = controller.session
    persist_settings = False
    persist_state = False

    if key == "mprc_enabled_checkbox":
        session.enabled = bool(converted)
        persist_state = True
    elif key == "mprc_show_character_checkbox":
        controller.settings["show_current_character_visual"] = bool(converted)
        persist_settings = True
    elif key in {"mprc_ar_mode_checkbox", "mprc_ar_enabled", "mprc_chat_use_ar_checkbox"}:
        if bool(converted):
            if session.mode != AR_MODE:
                controller.settings["last_non_ar_mode"] = session.mode or "Narrator + characters"
            session.mode = AR_MODE
            session.enabled = True
            controller.ensure_ar_state()
        else:
            session.mode = str(controller.settings.get("last_non_ar_mode") or "Narrator + characters")
        persist_settings = persist_state = True
    elif key in {"mprc_active_persona_combo", "mprc_persona_list"}:
        selected = normalize_persona_id(converted)
        if controller.persona_by_id(selected) is None:
            raise ValueError(f"Unknown persona {converted!r}.")
        controller.settings["native_selected_persona_id"] = selected
        if key == "mprc_active_persona_combo":
            session.active_persona_id = selected
            if not session.current_speaker_id:
                session.current_speaker_id = selected
            persist_state = True
        persist_settings = True
    elif key == "mprc_current_character_view_mode":
        controller.settings["current_character_view_mode"] = converted if converted in {"active_story", "all"} else "active_story"
        persist_settings = True
    elif key in _EXPANSION_FIELDS:
        expanded = dict(controller.settings.get("native_mprc_expanded") or {})
        expanded[key] = bool(converted)
        controller.settings["native_mprc_expanded"] = expanded
        persist_settings = True
    elif key in _PERSONA_FIELDS:
        if persona is None:
            raise RuntimeError("No persona is available to edit.")
        attribute = _PERSONA_FIELDS[key]
        old_id = persona.id
        if attribute == "id":
            converted = unique_persona_id(converted, {item.id for item in controller.personas if item is not persona})
        elif attribute == "display_name":
            converted = str(converted).strip() or persona.id.replace("_", " ").title()
        elif attribute == "tags":
            converted = [item.strip().casefold() for item in str(converted).split(",") if item.strip()]
        setattr(persona, attribute, converted)
        if attribute == "id" and persona.id != old_id:
            if session.active_persona_id == old_id:
                session.active_persona_id = persona.id
            if session.current_speaker_id == old_id:
                session.current_speaker_id = persona.id
            controller.settings["native_selected_persona_id"] = persona.id
            if normalize_persona_id(controller.settings.get("voice_edit_persona_id") or "") == old_id:
                controller.settings["voice_edit_persona_id"] = persona.id
            if normalize_persona_id(controller.settings.get("narrator_persona_id") or "") == old_id:
                controller.settings["narrator_persona_id"] = persona.id
        persist_settings = persist_state = True
    elif key in _VISUAL_FIELDS:
        if persona is None:
            raise RuntimeError("No persona is available to edit.")
        if key == "mprc_visual_appearance_freedom":
            converted = "flexible" if str(converted).strip().lower() == "flexible" else "strict"
        setattr(persona.visual, _VISUAL_FIELDS[key], converted)
        persist_state = True
    elif key == "mprc_voice_follow_active":
        controller.settings["voice_follow_active_persona"] = bool(converted)
        if bool(converted) and controller.active_persona() is not None:
            controller.settings["voice_edit_persona_id"] = controller.active_persona().id
        persist_settings = True
    elif key == "mprc_voice_persona":
        selected = normalize_persona_id(converted)
        if controller.persona_by_id(selected) is None:
            raise ValueError(f"Unknown voice persona {converted!r}.")
        controller.settings["voice_edit_persona_id"] = selected
        controller.settings["voice_follow_active_persona"] = False
        persist_settings = True
    elif key == "mprc_narrator_persona":
        selected = normalize_persona_id(converted) if str(converted).strip() else ""
        if selected and controller.persona_by_id(selected) is None:
            raise ValueError(f"Unknown narrator persona {converted!r}.")
        controller.settings["narrator_persona_id"] = selected
        controller.settings["narrator_persona_mode"] = "explicit" if selected else "auto"
        persist_settings = True
    elif key in _VOICE_FIELDS:
        if voice_persona is None:
            raise RuntimeError("No persona is available for voice settings.")
        attribute = _VOICE_FIELDS[key]
        if attribute == "language":
            converted = str(converted).strip().casefold()
        setattr(voice_persona.voice, attribute, converted)
        persist_state = True
    elif key in _SESSION_FIELDS:
        old_mode = session.mode
        setattr(session, _SESSION_FIELDS[key], converted)
        if key == "mprc_session_mode":
            if session.mode == AR_MODE:
                if old_mode != AR_MODE:
                    controller.settings["last_non_ar_mode"] = old_mode
                session.enabled = True
                controller.ensure_ar_state()
            else:
                controller.settings["last_non_ar_mode"] = session.mode
            persist_settings = True
        persist_state = True
    elif key == "mprc_next_speaker":
        selected = normalize_persona_id(converted)
        if controller.persona_by_id(selected) is None:
            raise ValueError(f"Unknown speaker {converted!r}.")
        session.current_speaker_id = selected
        persist_state = True
    elif key == "mprc_ar_use_persona_profiles":
        session.ar_use_persona_profiles = bool(converted)
        persist_state = True
    elif key == "mprc_ar_pacing":
        session.ar_pacing = str(converted)
        persist_state = True
    elif key == "mprc_ar_interaction":
        session.ar_interaction_frequency = str(converted)
        persist_state = True
    elif key == "mprc_ar_dialogue_density":
        session.ar_dialogue_density = str(converted)
        persist_state = True
    elif key in _AR_FIELDS:
        setattr(session.ar_state, _AR_FIELDS[key], converted)
        persist_state = True
    elif key == "mprc_ar_active_characters":
        session.ar_state.active_characters = [normalize_persona_id(item) for item in str(converted).split(",") if item.strip()][:8]
        persist_state = True
    elif key == "mprc_ar_pending_choices":
        session.ar_state.pending_choices = _lines(converted, limit=6)
        persist_state = True
    elif key == "mprc_ar_recent_events":
        session.ar_state.recent_events = _lines(converted, limit=12)
        persist_state = True
    elif key in _EXPORT_FIELDS:
        selected = set(controller._story_export_selected_sections())
        export_key = _EXPORT_FIELDS[key]
        selected.add(export_key) if bool(converted) else selected.discard(export_key)
        controller.settings["story_library_export_sections"] = [item for item in controller._story_export_spec_by_key() if item in selected]
        persist_settings = True
    elif key == "mprc_master_story_list":
        story_id = controller.storage.story_id(converted) if str(converted).strip() else ""
        valid = {value for value, _label in _story_options(controller)}
        if story_id and story_id not in valid:
            raise ValueError(f"Unknown story {converted!r}.")
        controller.settings["native_selected_story_id"] = story_id
        controller._refresh_master_story_image_preview()
        persist_settings = True
    elif key == "mprc_master_story_draft":
        text = str(converted).strip()
        if text:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Master Story draft must be valid JSON: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError("Master Story draft must be a JSON object.")
            controller._master_story_draft = payload
        else:
            controller._master_story_draft = {}
        controller.settings["master_story_draft"] = text
        persist_settings = True
    elif key == "mprc_audio_saved_prompts":
        controller.settings["native_selected_audio_prompt_index"] = int(converted)
        persist_settings = True
    elif key == "mprc_audiofx_list":
        controller._select_audiofx_index(int(converted))
        persist_settings = True
    elif key == "mprc_story_memory_list":
        controller.settings["native_selected_memory_id"] = str(converted)
        persist_settings = True
    elif key == "mprc_story_template":
        valid = {item[0] for item in controller._story_template_choices()}
        selected = str(converted).strip()
        if selected not in valid:
            raise ValueError(f"Unknown story template {converted!r}.")
        controller.settings["native_story_template_id"] = selected
        persist_settings = True
    elif key == "mprc_story_pinned_facts":
        controller.settings["native_story_pinned_facts"] = "\n".join(_lines(converted, limit=80))
        persist_settings = True
    elif key == "mprc_chat_speaker_combo":
        selected = normalize_persona_id(converted)
        if selected and controller.persona_by_id(selected) is None:
            raise ValueError(f"Unknown chat speaker {converted!r}.")
        controller.settings["native_chat_speaker_id"] = selected
        session.current_speaker_id = selected or session.current_speaker_id
        persist_settings = persist_state = True
    elif key == "mprc_chat_director_pacing_combo":
        session.ar_pacing = str(converted)
        persist_state = True
    elif key == "mprc_chat_next_actions_list":
        controller.settings["native_next_action"] = str(converted)
        persist_settings = True
    elif key == "mprc_chat_recent_events_list":
        controller.settings["native_recent_event"] = str(converted)
        persist_settings = True
    elif key == "mprc_chat_present_characters_list":
        controller.settings["native_present_character"] = str(converted)
        persist_settings = True
    elif key == "mprc_chat_chromecast_device_combo":
        controller.settings["chromecast_device_name"] = str(converted)
        persist_settings = True
    elif key in _SETTING_FIELDS:
        controller.settings[_SETTING_FIELDS[key]] = converted
        persist_settings = True
    else:
        raise KeyError(f"MPRC control {key!r} has no native model binding.")

    if persist_settings:
        controller.storage.save_settings(controller.settings)
    if persist_state:
        controller._ensure_session_persona()
        controller.save_state()
    if key in {"mprc_audiofx_volume", "mprc_chat_voice_volume_slider"}:
        controller._apply_audiofx_volume()
    if key in {"mprc_chat_remote_enabled_checkbox", "mprc_chat_remote_host_input", "mprc_chat_remote_port_spin", "mprc_chat_remote_code_spin"}:
        controller._sync_remote_backend_from_settings()
    controller._request_ui_refresh()
    return native_control_state(controller)


def unsupported_editable_control_ids() -> tuple[str, ...]:
    """Static completeness check used by smoke tests and the release gate."""

    supported = (
        set(_PERSONA_FIELDS)
        | set(_VISUAL_FIELDS)
        | set(_VOICE_FIELDS)
        | set(_SESSION_FIELDS)
        | set(_AR_FIELDS)
        | set(_SETTING_FIELDS)
        | set(_EXPORT_FIELDS)
        | set(_EXPANSION_FIELDS)
        | {
            "mprc_enabled_checkbox", "mprc_show_character_checkbox", "mprc_ar_mode_checkbox",
            "mprc_active_persona_combo", "mprc_persona_list", "mprc_current_character_view_mode",
            "mprc_voice_follow_active", "mprc_voice_persona", "mprc_narrator_persona",
            "mprc_next_speaker", "mprc_ar_enabled", "mprc_ar_use_persona_profiles",
            "mprc_ar_pacing", "mprc_ar_interaction", "mprc_ar_dialogue_density",
            "mprc_ar_active_characters", "mprc_ar_pending_choices", "mprc_ar_recent_events",
            "mprc_master_story_list", "mprc_master_story_draft", "mprc_audio_saved_prompts",
            "mprc_audiofx_list", "mprc_story_memory_list", "mprc_story_template",
            "mprc_story_pinned_facts", "mprc_chat_speaker_combo",
            "mprc_chat_director_pacing_combo", "mprc_chat_next_actions_list",
            "mprc_chat_recent_events_list", "mprc_chat_present_characters_list",
            "mprc_chat_chromecast_device_combo", "mprc_chat_use_ar_checkbox",
        }
    )
    editable = set(_SPECS) - _READ_ONLY - _ACTION_IDS
    return tuple(sorted(editable - supported))


__all__ = [
    "native_control_state",
    "native_update_control",
    "unsupported_editable_control_ids",
]
