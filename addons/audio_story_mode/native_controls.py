"""Typed native-QML control bindings for Audio Story Mode."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from addons.audio_story_mode.native_contract import NATIVE_CONTROL_SPECS
from addons.audio_story_mode.session_schema import audio_story_mode_session_payload, flatten_audio_story_mode_settings


_SPECS = {str(spec["id"]): dict(spec) for spec in NATIVE_CONTROL_SPECS}
_ACTIONS = {key for key, spec in _SPECS.items() if spec["kind"] == "action"}
_READ_ONLY = {key for key, spec in _SPECS.items() if bool(spec.get("read_only"))}
_PERCENTAGE_CONTROLS = frozenset({"audio_story_continuity_slider"})

_FLAT_FIELDS = {
    "audio_story_path_edit": "audio_story_mode_audio_path",
    "audio_story_playback_mode_combo": "audio_story_mode_playback_mode",
    "audio_story_cost_profile_combo": "audio_story_mode_cost_profile",
    "audio_story_transcribe_seconds_slider": "audio_story_mode_transcribe_seconds",
    "audio_story_selected_range_checkbox": "audio_story_mode_selected_range_enabled",
    "audio_story_transcription_start_spin": "audio_story_mode_transcription_start_seconds",
    "audio_story_transcription_end_spin": "audio_story_mode_transcription_end_seconds",
    "audio_story_tts_startup_buffer_spin": "audio_story_mode_tts_startup_buffer_seconds",
    "audio_story_tts_render_ahead_spin": "audio_story_mode_tts_render_ahead_seconds",
    "audio_story_image_frequency_slider": "audio_story_mode_image_frequency_seconds",
    "audio_story_image_timing_combo": "audio_story_mode_image_timing_mode",
    "audio_story_continuity_slider": "audio_story_mode_continuity_strength",
    "audio_story_generate_ahead_slider": "audio_story_mode_generate_ahead_frames",
    "audio_story_llm_analysis_checkbox": "audio_story_mode_use_llm_story_analysis",
    "audio_story_analysis_mode_combo": "audio_story_mode_analysis_mode",
    "audio_story_analysis_provider_combo": "audio_story_mode_story_analysis_provider_mode",
    "audio_story_analysis_model_combo": "audio_story_mode_story_analysis_model",
    "audio_story_instructor_beats_checkbox": "audio_story_mode_instructor_beats_enabled",
    "audio_story_prompt_safety_cap_spin": "audio_story_mode_prompt_safety_cap",
    "audio_story_style_live_checkbox": "audio_story_mode_style_change_live",
    "audio_story_master_prompt_button": "audio_story_mode_story_master_prompt_enabled",
    "audio_story_master_prompt_mode_combo": "audio_story_mode_story_master_prompt_mode",
    "audio_story_stream_enabled_checkbox": "audio_story_mode_visual_stream_enabled",
    "audio_story_stream_port_spin": "audio_story_mode_visual_stream_port",
    "audio_story_cast_prompt_checkbox": "audio_story_mode_chromecast_show_prompt",
    "audio_story_cast_device_combo": "audio_story_mode_chromecast_device_name",
}

_STYLE_CONTROLS = {
    "realistic": ("unnamed_qpushbutton_realistic", "unnamed_qlineedit_qlineedit"),
    "cartoon": ("unnamed_qpushbutton_cartoon", "unnamed_qlineedit_qlineedit#2"),
    "retro": ("unnamed_qpushbutton_retro", "unnamed_qlineedit_qlineedit#3"),
    "cyberpunk": ("unnamed_qpushbutton_cyberpunk", "unnamed_qlineedit_qlineedit#4"),
}

_XAI_FIELDS = {
    "audio_story_xai_aspect_ratio_combo": "xai_image_aspect_ratio",
    "audio_story_xai_resolution_combo": "xai_image_resolution",
    "audio_story_xai_response_format_combo": "xai_image_response_format",
    "audio_story_xai_n_spin": "xai_image_n",
}

_NOVEL_FIELDS = {
    "unnamed_qlineedit_qlineedit#5": "native_project_name",
    "unnamed_qlineedit_message_collection": "message_collection",
    "unnamed_qlineedit_speaker_field": "speaker_field",
    "unnamed_qlineedit_text_field": "text_field",
    "unnamed_qlineedit_role_field": "role_field",
    "unnamed_qlineedit_timestamp_field": "timestamp_field",
    "unnamed_qlineedit_thread_field": "thread_field",
}


def _json(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def _coerce(control_id: str, value: Any) -> Any:
    kind = str(_SPECS[control_id]["kind"])
    if kind == "boolean":
        if isinstance(value, str):
            return value.strip().casefold() in {"1", "true", "yes", "on"}
        return bool(value)
    if kind in {"integer", "slider", "progress"}:
        converted = int(float(value or 0))
        if control_id in _PERCENTAGE_CONTROLS:
            return float(converted) / 100.0
        return converted
    return str(value or "") if kind in {"text", "multiline", "choice"} else value


def _control_value(control_id: str, value: Any) -> Any:
    if control_id in _PERCENTAGE_CONTROLS:
        return int(round(float(value) * 100.0))
    return copy.deepcopy(value)


def _current_scene_state(controller: Any) -> dict[str, Any]:
    scene_id = str(controller._current_scene_id() or "")
    scene = dict(controller._current_scene_entry() or {})
    overrides = dict(controller.scene_overrides or {})
    anchor = (
        str(overrides.get("global_scene_anchor") or "")
        if bool(overrides.get("global_scene_anchor_enabled"))
        else str(dict(overrides.get("scene_anchor_overrides") or {}).get(scene_id) or "")
    )
    negative = (
        str(overrides.get("global_negative_prompt") or "")
        if bool(overrides.get("global_negative_prompt_enabled"))
        else str(dict(overrides.get("scene_negative_prompt_overrides") or {}).get(scene_id) or "")
    )
    location_id = str(scene.get("location_id") or "")
    forced = str(dict(overrides.get("forced_scene_modes") or {}).get(scene_id) or "")
    return {
        "scene_id": scene_id,
        "scene": scene,
        "anchor": anchor,
        "negative": negative,
        "pin_location": bool(location_id and location_id in set(overrides.get("pinned_location_ids") or [])),
        "force_fresh": forced == "fresh",
        "force_continuation": forced == "continuation",
        "anchor_pinned": bool(overrides.get("global_scene_anchor_enabled")),
        "negative_pinned": bool(overrides.get("global_negative_prompt_enabled")),
    }


def _selected_project_id(controller: Any) -> str:
    """Return the native selection, falling back for older controller state."""

    return str(
        getattr(controller, "_native_selected_project_id", "")
        or controller.current_story_project_id
        or ""
    ).strip()


def native_control_state(controller: Any) -> dict[str, Any]:
    flat = flatten_audio_story_mode_settings(controller.export_session_state())
    values = {key: copy.deepcopy(spec.get("default")) for key, spec in _SPECS.items()}
    options: dict[str, tuple[tuple[Any, str], ...]] = {}
    enabled: dict[str, bool] = {}
    novel = controller.audio_story_novel_panel.snapshot()
    novel_settings = dict(novel.get("settings") or {})
    field_map = dict(novel.get("field_map") or {})
    scene_state = _current_scene_state(controller)
    scene = scene_state["scene"]

    for control_id, flat_key in _FLAT_FIELDS.items():
        if flat_key in flat:
            values[control_id] = _control_value(control_id, flat[flat_key])
    styles = dict(flat.get("audio_story_mode_style_prompts") or {})
    labels = dict(flat.get("audio_story_mode_style_labels") or {})
    active_styles = set(flat.get("audio_story_mode_style_enabled") or [])
    for style_id, (toggle_id, prompt_id) in _STYLE_CONTROLS.items():
        values[toggle_id] = style_id in active_styles
        values[prompt_id] = str(styles.get(style_id) or "")
    xai = dict(flat.get("audio_story_mode_xai_image_settings") or {})
    for control_id, setting_key in _XAI_FIELDS.items():
        values[control_id] = copy.deepcopy(xai.get(setting_key, values[control_id]))

    projects = [dict(item) for item in list(controller._story_projects or []) if isinstance(item, Mapping)]
    current_project = dict(controller._current_story_project or {})
    chapters = dict(current_project.get("chapters") or {})
    chapter_order = [str(item) for item in list(current_project.get("chapter_order") or [])]
    sources = [dict(item) for item in list(controller._native_audio_source_queue or []) if isinstance(item, Mapping)]
    values.update(
        {
            "audio_story_project_autosave_label": str(dict(controller._native_project_status or {}).get("autosave") or "Select or create a project to begin."),
            "audio_story_project_recovery_label": str(dict(controller._native_project_status or {}).get("recovery") or "No recovery action is needed."),
            "audio_story_project_list": _selected_project_id(controller),
            "audio_story_project_chapter_list": str(controller._current_story_chapter_id or ""),
            "audio_story_project_chapter_status_label": str(dict(controller._native_project_status or {}).get("chapter") or "No chapter selected."),
            "audio_story_source_list": int(getattr(controller, "_native_selected_source_index", 0) or 0),
            "audio_story_settings_preset_combo": str(getattr(controller, "_native_selected_settings_preset", "") or ""),
            "audio_story_transcription_progress_bar": int(getattr(controller, "_transcription_progress", 0) or 0),
            "audio_story_transcription_console": str(getattr(controller, "_transcription_console_text", "") or ""),
            "audio_story_tts_state_label": str(getattr(controller, "_tts_render_status_text", "") or "Idle"),
            "audio_story_position_slider": int(round(controller._player_position_seconds())),
            "audio_story_status_label": str(getattr(controller, "_stored_status_text", "") or "Ready"),
            "audio_story_cast_status_label": str(getattr(controller, "_chromecast_status_text", "") or "Chromecast idle."),
            "audio_story_scene_status_label": str(controller._current_scene_label() or "No scene selected."),
            "audio_story_pin_location_button": scene_state["pin_location"],
            "audio_story_force_fresh_button": scene_state["force_fresh"],
            "audio_story_force_continuation_button": scene_state["force_continuation"],
            "audio_story_scene_anchor_edit": scene_state["anchor"],
            "audio_story_scene_negative_prompt_edit": scene_state["negative"],
            "audio_story_scene_anchor_pin_button": scene_state["anchor_pinned"],
            "audio_story_negative_prompt_anchor_button": scene_state["negative_pinned"],
            "audio_story_scene_hint": str(scene.get("summary") or scene.get("text") or "No scene is selected."),
            "audio_story_summary_label": f"Image windows: {len(controller.transcript_chunks)}\nScenes: {len(controller.scene_plan)}",
            "audio_story_transcript_edit": str(controller.full_transcript_text or ""),
            "audio_story_style_apply_status_label": str(getattr(controller, "_style_apply_state", "Saved") or "Saved"),
            "audio_story_planner_apply_status_label": str(getattr(controller, "_planner_apply_state", "Saved") or "Saved"),
            "audio_story_instructor_status_label": str(getattr(controller, "_instructor_status_text", "") or "Instructor status unavailable."),
            "audio_story_novel_status_label": str(novel.get("status") or ""),
            "unnamed_qprogressbar_qprogressbar": int(novel.get("progress") or 0),
            "unnamed_qcombobox_adaptation_style": str(novel_settings.get("adaptation_style") or "faithful"),
            "unnamed_qplaintextedit_novel_instructions": str(novel_settings.get("novel_instructions") or ""),
            "unnamed_qgroupbox_advanced_prompt_additions": bool(novel_settings.get("advanced_prompt_additions_visible", False)),
            "unnamed_qplaintextedit_story_map": _json(novel.get("story_map") or {}),
            "unnamed_qplaintextedit_outline": _json(novel.get("outline") or {}),
            "unnamed_qplaintextedit_scene_plans": _json(novel.get("scene_plans") or {}),
            "unnamed_qplaintextedit_prose": _json(novel.get("prose") or {}),
            "audio_story_novel_outline_tree": str(novel.get("selected_scene_id") or novel.get("selected_chapter_id") or ""),
        }
    )
    for control_id, field_key in _NOVEL_FIELDS.items():
        if field_key == "native_project_name":
            values[control_id] = str(getattr(controller, "_native_novel_project_name", "") or "")
        else:
            values[control_id] = str(field_map.get(field_key) or values[control_id])

    options["audio_story_source_list"] = tuple(
        (index, str(item.get("label") or item.get("path") or item.get("audio_path") or f"Source {index + 1}"))
        for index, item in enumerate(sources)
    ) or ((-1, "No audio sources"),)
    options["audio_story_project_list"] = tuple(
        (str(item.get("project_id") or ""), str(item.get("name") or item.get("project_id") or "Untitled"))
        for item in projects if str(item.get("project_id") or "")
    ) or (("", "No saved projects"),)
    options["audio_story_project_chapter_list"] = tuple(
        (chapter_id, str(dict(chapters.get(chapter_id) or {}).get("name") or chapter_id))
        for chapter_id in chapter_order if chapter_id in chapters
    ) or (("", "No chapters"),)
    preset_names = list(controller._audio_story_settings_preset_names())
    options["audio_story_settings_preset_combo"] = tuple((name, name) for name in preset_names) or (("", "No saved presets"),)
    cast_devices = [dict(item) for item in list(getattr(controller, "_chromecast_devices", []) or []) if isinstance(item, Mapping)]
    options["audio_story_cast_device_combo"] = tuple(
        (str(item.get("name") or item.get("friendly_name") or ""), str(item.get("name") or item.get("friendly_name") or "Chromecast"))
        for item in cast_devices if str(item.get("name") or item.get("friendly_name") or "")
    ) or (("", "No cast devices"),)
    outline = dict(novel.get("outline") or {})
    outline_options: list[tuple[str, str]] = []
    for chapter in list(outline.get("chapters") or []):
        if not isinstance(chapter, Mapping):
            continue
        chapter_id = str(chapter.get("chapter_id") or chapter.get("id") or "")
        if chapter_id:
            outline_options.append((chapter_id, str(chapter.get("title") or chapter_id)))
        for scene_item in list(chapter.get("scenes") or []):
            if isinstance(scene_item, Mapping):
                scene_id = str(scene_item.get("scene_id") or scene_item.get("id") or "")
                if scene_id:
                    outline_options.append((scene_id, f"  {str(scene_item.get('title') or scene_id)}"))
    options["audio_story_novel_outline_tree"] = tuple(outline_options) or (("", "No outline items"),)
    return {"values": values, "options": options, "enabled": enabled}


def _apply_flat_update(controller: Any, flat_key: str, value: Any) -> None:
    flat = flatten_audio_story_mode_settings(controller.export_session_state())
    flat[flat_key] = copy.deepcopy(value)
    controller.import_session_state(audio_story_mode_session_payload(flat))


def native_update_control(controller: Any, control_id: str, value: Any) -> dict[str, Any]:
    key = str(control_id or "").strip()
    if key not in _SPECS:
        raise KeyError(f"Unknown Audio Story control {control_id!r}.")
    if key in _ACTIONS:
        raise ValueError(f"Audio Story action {key!r} must be triggered.")
    if key in _READ_ONLY:
        raise ValueError(f"Audio Story control {key!r} is read-only.")
    converted = _coerce(key, value)
    if key == "audio_story_cost_profile_combo":
        profile_id = str(converted or "").strip().lower()
        if profile_id != "custom" and not controller._apply_audio_story_cost_profile(
            profile_id,
            rebuild_story=True,
        ):
            raise ValueError(f"Unknown Audio Story quality profile {converted!r}.")
    elif key in _FLAT_FIELDS:
        _apply_flat_update(controller, _FLAT_FIELDS[key], converted)
    elif key in {item for pair in _STYLE_CONTROLS.values() for item in pair}:
        flat = flatten_audio_story_mode_settings(controller.export_session_state())
        prompts = dict(flat.get("audio_story_mode_style_prompts") or {})
        enabled = set(flat.get("audio_story_mode_style_enabled") or [])
        for style_id, (toggle_id, prompt_id) in _STYLE_CONTROLS.items():
            if key == toggle_id:
                enabled.add(style_id) if bool(converted) else enabled.discard(style_id)
            elif key == prompt_id:
                prompts[style_id] = str(converted)
        flat["audio_story_mode_style_prompts"] = prompts
        flat["audio_story_mode_style_enabled"] = sorted(enabled)
        controller.import_session_state(audio_story_mode_session_payload(flat))
    elif key in _XAI_FIELDS:
        flat = flatten_audio_story_mode_settings(controller.export_session_state())
        settings = dict(flat.get("audio_story_mode_xai_image_settings") or {})
        settings[_XAI_FIELDS[key]] = converted
        flat["audio_story_mode_xai_image_settings"] = settings
        controller.import_session_state(audio_story_mode_session_payload(flat))
    elif key == "audio_story_source_list":
        controller._native_selected_source_index = int(converted)
    elif key == "audio_story_project_list":
        controller._native_selected_project_id = str(converted)
    elif key == "audio_story_project_chapter_list":
        controller._current_story_chapter_id = str(converted)
    elif key == "audio_story_settings_preset_combo":
        controller._native_selected_settings_preset = str(converted)
    elif key == "audio_story_position_slider":
        controller._set_player_global_position(float(converted))
        controller._sync_visual_to_position(float(converted), force=True)
    elif key in {"audio_story_pin_location_button", "audio_story_force_fresh_button", "audio_story_force_continuation_button"}:
        if key == "audio_story_pin_location_button":
            controller._on_pin_location_toggled(bool(converted))
        else:
            controller._on_force_scene_mode_changed("fresh" if key.endswith("fresh_button") else "continuation", bool(converted))
    elif key in {"audio_story_scene_anchor_edit", "audio_story_scene_negative_prompt_edit", "audio_story_scene_anchor_pin_button", "audio_story_negative_prompt_anchor_button"}:
        scene_id = str(controller._current_scene_id() or "")
        overrides = dict(controller.scene_overrides or {})
        if key == "audio_story_scene_anchor_edit":
            target = dict(overrides.get("scene_anchor_overrides") or {})
            target[scene_id] = str(converted)
            controller._replace_scene_overrides(scene_anchor_overrides=target)
        elif key == "audio_story_scene_negative_prompt_edit":
            target = dict(overrides.get("scene_negative_prompt_overrides") or {})
            target[scene_id] = str(converted)
            controller._replace_scene_overrides(scene_negative_prompt_overrides=target)
        elif key == "audio_story_scene_anchor_pin_button":
            changes = {"global_scene_anchor_enabled": bool(converted)}
            if converted:
                changes["global_scene_anchor"] = _current_scene_state(controller)["anchor"]
            controller._replace_scene_overrides(**changes)
        else:
            changes = {"global_negative_prompt_enabled": bool(converted)}
            if converted:
                changes["global_negative_prompt"] = _current_scene_state(controller)["negative"]
            controller._replace_scene_overrides(**changes)
        controller._scene_override_refresh_after_change(refresh_visuals=bool(controller.transcript_chunks))
    elif key in _NOVEL_FIELDS:
        field_key = _NOVEL_FIELDS[key]
        if field_key == "native_project_name":
            controller._native_novel_project_name = str(converted)
        else:
            snapshot = controller.audio_story_novel_panel.snapshot()
            field_map = dict(snapshot.get("field_map") or {})
            field_map[field_key] = str(converted)
            controller.native_update("audio_story_novel_field_map", field_map)
    elif key == "unnamed_qcombobox_adaptation_style":
        controller.native_update("audio_story_novel_adaptation_style", converted)
    elif key == "unnamed_qplaintextedit_novel_instructions":
        controller.native_update("audio_story_novel_instructions", converted)
    elif key == "unnamed_qgroupbox_advanced_prompt_additions":
        settings = dict(controller.audio_story_novel_panel.snapshot().get("settings") or {})
        settings["advanced_prompt_additions_visible"] = bool(converted)
        controller.audio_story_novel_panel.update_settings(settings)
    elif key in {"unnamed_qplaintextedit_story_map", "unnamed_qplaintextedit_outline"}:
        try:
            payload = json.loads(str(converted or "{}"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{_SPECS[key]['label']} must be valid JSON: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise ValueError(f"{_SPECS[key]['label']} must be a JSON object.")
        if key.endswith("story_map"):
            controller.audio_story_novel_panel.set_story_map(payload)
        else:
            controller.audio_story_novel_panel.set_outline(payload)
    elif key == "audio_story_novel_outline_tree":
        selected = str(converted)
        outline = dict(controller.audio_story_novel_panel.snapshot().get("outline") or {})
        chapter_ids = {str(item.get("chapter_id") or item.get("id") or "") for item in list(outline.get("chapters") or []) if isinstance(item, Mapping)}
        if selected in chapter_ids:
            controller.audio_story_novel_panel.select(chapter_id=selected, scene_id="")
        else:
            controller.audio_story_novel_panel.select(chapter_id="", scene_id=selected)
    elif key in {"unnamed_qplaintextedit_scene_plans", "unnamed_qplaintextedit_prose"}:
        raise ValueError(f"{_SPECS[key]['label']} is generated by the Novel Workshop pipeline.")
    else:
        raise KeyError(f"Audio Story control {key!r} has no native binding.")
    controller._refresh_scene_override_controls()
    return native_control_state(controller)


def unsupported_editable_control_ids() -> tuple[str, ...]:
    supported = set(_FLAT_FIELDS) | set(_XAI_FIELDS) | set(_NOVEL_FIELDS)
    supported |= {item for pair in _STYLE_CONTROLS.values() for item in pair}
    supported |= {
        "audio_story_source_list", "audio_story_project_list", "audio_story_project_chapter_list",
        "audio_story_settings_preset_combo", "audio_story_position_slider", "audio_story_pin_location_button",
        "audio_story_force_fresh_button", "audio_story_force_continuation_button", "audio_story_scene_anchor_edit",
        "audio_story_scene_negative_prompt_edit", "audio_story_scene_anchor_pin_button",
        "audio_story_negative_prompt_anchor_button", "unnamed_qcombobox_adaptation_style",
        "unnamed_qplaintextedit_novel_instructions", "unnamed_qgroupbox_advanced_prompt_additions",
        "unnamed_qplaintextedit_story_map", "unnamed_qplaintextedit_outline",
        "unnamed_qplaintextedit_scene_plans", "unnamed_qplaintextedit_prose", "audio_story_novel_outline_tree",
    }
    editable = set(_SPECS) - _ACTIONS - _READ_ONLY
    return tuple(sorted(editable - supported))


__all__ = ["native_control_state", "native_update_control", "unsupported_editable_control_ids"]
