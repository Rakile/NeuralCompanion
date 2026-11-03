"""Exact action dispatch for the complete Companion Orb native-QML surface."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import unquote, urlparse

from addons.companion_orb_overlay.native_contract import NATIVE_CONTROL_SPECS
from addons.companion_orb_overlay.native_controls import (
    native_control_state,
    native_update_control,
    selected_behavior_index,
)
from core import companion_orb_reply_styles


_ACTION_IDS = {
    str(spec["id"])
    for spec in NATIVE_CONTROL_SPECS
    if str(spec.get("kind")) == "action"
}

_COLOR_ACTIONS = {
    "companion_orb_eye_tracking_gaze_timer_color_pick_button": (
        "companion_orb_eye_tracking_gaze_timer_color_edit"
    ),
    "companion_orb_eye_tracking_bounding_box_normal_color_pick_button": (
        "companion_orb_eye_tracking_bounding_box_normal_color_edit"
    ),
    "companion_orb_eye_tracking_bounding_box_hover_color_pick_button": (
        "companion_orb_eye_tracking_bounding_box_hover_color_edit"
    ),
    "companion_orb_eye_tracking_bounding_box_selected_color_pick_button": (
        "companion_orb_eye_tracking_bounding_box_selected_color_edit"
    ),
    "companion_orb_primary_color_pick_button": "companion_orb_primary_color_edit",
    "companion_orb_secondary_color_pick_button": "companion_orb_secondary_color_edit",
    "companion_orb_accent_color_pick_button": "companion_orb_accent_color_edit",
    "companion_orb_glow_color_pick_button": "companion_orb_glow_color_edit",
    "companion_orb_idle_color_pick_button": "companion_orb_idle_color_edit",
    "companion_orb_thinking_color_pick_button": "companion_orb_thinking_color_edit",
    "companion_orb_speaking_color_pick_button": "companion_orb_speaking_color_edit",
}

_DIRECT_ACTIONS = {
    "companion_orb_spatial_test_grounding_button": "_start_companion_orb_spatial_diagnostics",
    "companion_orb_vision_test_connection_button": "_start_companion_orb_vision_probe",
    "companion_orb_capture_show_button": "_show_companion_orb",
    "companion_orb_capture_clear_target_button": "_clear_companion_orb_target",
    "companion_orb_capture_reset_position_button": "_reset_companion_orb_position",
    "companion_orb_eye_tracking_calibration_start_button": "_start_eye_tracking_calibration",
    "companion_orb_eye_tracking_calibration_cancel_button": "_cancel_eye_tracking_calibration",
    "companion_orb_eye_tracking_calibration_reset_button": "_reset_eye_tracking_calibration",
    "companion_orb_eye_tracking_stable_preset_button": "_apply_stable_eye_tracking_movement_preset",
    "companion_orb_show_button": "_show_companion_orb",
    "companion_orb_edit_mode_button": "_toggle_companion_orb_edit_mode",
    "companion_orb_placement_mode_button": "_toggle_companion_orb_placement_mode",
    "companion_orb_clear_target_button": "_clear_companion_orb_target",
    "companion_orb_reset_position_button": "_reset_companion_orb_position",
}

_CUSTOM_COLOR_KEYS = (
    "companion_orb_primary_color",
    "companion_orb_secondary_color",
    "companion_orb_accent_color",
    "companion_orb_glow_color",
)


def _payload_value(payload: Any) -> Any:
    if isinstance(payload, Mapping) and "payload" in payload:
        return payload.get("payload")
    return payload


def _input_text(payload: Any) -> str:
    return str(_payload_value(payload) or "").strip()


def _confirmed(payload: Any) -> bool:
    return bool(payload.get("confirmed")) if isinstance(payload, Mapping) else False


def _native_path(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme.casefold() != "file":
        return raw
    path = unquote(parsed.path or "")
    if parsed.netloc:
        path = f"//{parsed.netloc}{path}"
    if len(path) >= 3 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return path.replace("/", os.sep)


def _paths(payload: Any) -> tuple[str, ...]:
    value = _payload_value(payload)
    candidates = value if isinstance(value, (list, tuple)) else (value,)
    return tuple(path for path in (_native_path(item) for item in candidates) if path)


def _debug_log_path(controller: Any) -> Path:
    root = Path(getattr(controller.context, "app_root", Path.cwd()) or Path.cwd())
    return root / "runtime" / "companion_orb" / "debug" / "companion_orb_debug.log"


def _set_status(controller: Any, message: str) -> None:
    controller._set_status(str(message or ""))


def _save_supervisor(controller: Any, personas: list[dict[str, Any]]) -> None:
    controller._set_companion_orb_supervisor_personas(personas)
    controller._save_session()


def _add_supervisor_persona(controller: Any, payload: Any) -> None:
    name = _input_text(payload)
    if not name:
        raise ValueError("Enter a name for the Companion Orb supervisor persona.")
    personas = controller._companion_orb_supervisor_personas()
    persona = {
        "id": f"orb_persona_{os.urandom(6).hex()}",
        "name": name,
        "style": "playful, observant desktop companion",
        "behaviors": [],
    }
    personas.append(persona)
    controller._update_runtime_config(
        "companion_orb_supervisor_selected_persona_id", persona["id"]
    )
    _save_supervisor(controller, personas)
    _set_status(controller, f"Added Companion Orb supervisor persona: {name}.")


def _rename_supervisor_persona(controller: Any, payload: Any) -> None:
    name = _input_text(payload)
    if not name:
        raise ValueError("Enter a new Companion Orb supervisor persona name.")
    active = controller._selected_companion_orb_supervisor_persona()
    selected_id = str(active.get("id") or "")
    personas = controller._companion_orb_supervisor_personas()
    for persona in personas:
        if str(persona.get("id") or "") == selected_id:
            persona["name"] = name
            break
    _save_supervisor(controller, personas)
    _set_status(controller, f"Renamed Companion Orb supervisor persona to {name}.")


def _delete_supervisor_persona(controller: Any, payload: Any) -> None:
    if not _confirmed(payload):
        raise ValueError("Deleting a Companion Orb supervisor persona requires confirmation.")
    personas = controller._companion_orb_supervisor_personas()
    if len(personas) <= 1:
        raise ValueError("The final Companion Orb supervisor persona cannot be deleted.")
    selected_id = str(
        controller._selected_companion_orb_supervisor_persona().get("id") or ""
    )
    personas = [item for item in personas if str(item.get("id") or "") != selected_id]
    controller._update_runtime_config(
        "companion_orb_supervisor_selected_persona_id", personas[0]["id"]
    )
    _save_supervisor(controller, personas)
    _set_status(controller, "Deleted the Companion Orb supervisor persona.")


def _add_supervisor_behavior(controller: Any) -> None:
    selected_id = str(
        controller._selected_companion_orb_supervisor_persona().get("id") or ""
    )
    personas = controller._companion_orb_supervisor_personas()
    for persona in personas:
        if str(persona.get("id") or "") != selected_id:
            continue
        behavior = {
            "id": f"orb_behavior_{os.urandom(6).hex()}",
            "enabled": False,
            "trigger": "",
            "action": "",
            "strictness": controller._normalize_supervisor_strictness(None),
            "emotion": controller._normalize_supervisor_emotion(None),
            "repeat_mode": controller._normalize_supervisor_repeat_mode(None),
            "repeat_interval": controller._normalize_supervisor_repeat_interval(None),
        }
        persona.setdefault("behaviors", []).append(behavior)
        controller._native_selected_behavior_id = behavior['id']
        controller._companion_orb_supervisor_expanded_behavior_ids.add(behavior["id"])
        _save_supervisor(controller, personas)
        _set_status(controller, "Added a Companion Orb supervisor behavior rule.")
        return
    raise ValueError("Choose a Companion Orb supervisor persona first.")


def _remove_supervisor_behavior(controller: Any, index: int, payload: Any) -> None:
    if not _confirmed(payload):
        raise ValueError("Removing a Companion Orb behavior rule requires confirmation.")
    selected_id = str(
        controller._selected_companion_orb_supervisor_persona().get("id") or ""
    )
    personas = controller._companion_orb_supervisor_personas()
    for persona in personas:
        if str(persona.get("id") or "") != selected_id:
            continue
        behaviors = list(persona.get("behaviors") or [])
        if not 0 <= index < len(behaviors):
            raise ValueError("That Companion Orb behavior rule is no longer available.")
        removed = dict(behaviors.pop(index) or {})
        persona["behaviors"] = behaviors
        controller._companion_orb_supervisor_expanded_behavior_ids.discard(
            str(removed.get("id") or "")
        )
        _save_supervisor(controller, personas)
        _set_status(controller, "Removed the Companion Orb supervisor behavior rule.")
        return
    raise ValueError("Choose a Companion Orb supervisor persona first.")


def _reply_style_action(controller: Any, action_id: str, payload: Any) -> None:
    style = companion_orb_reply_styles.normalize_reply_style(
        getattr(controller, "_native_reply_style_id", "friendly")
    )
    overrides = controller._reply_style_prompt_overrides()
    if action_id == "btn_companion_orb_reply_style_save":
        text = str(getattr(controller, "_native_reply_style_prompt", "") or "").strip()
        overrides[style] = text or companion_orb_reply_styles.default_reply_style_prompt(style)
        message = f"Saved Companion Orb reply style: {companion_orb_reply_styles.reply_style_label(style)}."
    elif action_id == "btn_companion_orb_reply_style_load":
        controller._native_reply_style_prompt = ""
        _set_status(controller, "Reloaded the selected Companion Orb reply style.")
        return
    elif action_id == "btn_companion_orb_reply_style_default":
        overrides.pop(style, None)
        message = f"Restored recommended Companion Orb reply style: {companion_orb_reply_styles.reply_style_label(style)}."
    else:
        if not _confirmed(payload):
            raise ValueError("Resetting all Companion Orb reply styles requires confirmation.")
        overrides = {}
        message = "Restored all recommended Companion Orb reply style prompts."
    controller._update_runtime_config("companion_orb_response_style_prompts", overrides)
    controller._native_reply_style_prompt = ""
    controller._save_session()
    _set_status(controller, message)


def _apply_custom_colors(controller: Any, *, saved: bool) -> None:
    config = controller._runtime_config()
    controller._update_runtime_config("companion_orb_custom_colors_enabled", True)
    defaults = {
        "companion_orb_primary_color": "#22d3ee",
        "companion_orb_secondary_color": "#38bdf8",
        "companion_orb_accent_color": "#a78bfa",
        "companion_orb_glow_color": "#67e8f9",
    }
    for key in _CUSTOM_COLOR_KEYS:
        controller._update_runtime_config(
            key,
            controller._normalized_hex_color(config.get(key), defaults[key]),
        )
    controller._apply_runtime_config()
    controller._save_session()
    _set_status(
        controller,
        "Companion Orb custom colors saved."
        if saved
        else "Companion Orb custom colors applied.",
    )


def _selected_preset(controller: Any):
    preset_id = str(getattr(controller, "_native_selected_preset_id", "") or "").strip()
    if not preset_id:
        raise ValueError("Choose a Companion Orb preset first.")
    return controller._companion_orb_preset_store.load(preset_id)


def _preset_action(controller: Any, action_id: str, payload: Any) -> None:
    if action_id == "companion_orb_preset_load_button":
        record = _selected_preset(controller)
        controller._apply_companion_orb_preset_record(record)
        controller._native_preset_comment = record.comment
        return
    if action_id == "companion_orb_preset_delete_button":
        if not _confirmed(payload):
            raise ValueError("Deleting a Companion Orb preset requires confirmation.")
        record = _selected_preset(controller)
        controller._companion_orb_preset_store.delete(record.preset_id)
        controller._native_selected_preset_id = ""
        controller._native_preset_comment = ""
        _set_status(controller, f"Deleted Companion Orb preset: {record.name}.")
        return
    if action_id == "companion_orb_preset_save_button":
        existing = _selected_preset(controller)
        name = existing.name
        overwrite = True
    else:
        name = _input_text(payload)
        overwrite = False
        if not name:
            raise ValueError("Enter a name for the new Companion Orb preset.")
    comment = str(getattr(controller, "_native_preset_comment", "") or "")
    record = controller._companion_orb_preset_store.save(
        name,
        comment,
        controller._companion_orb_preset_settings_snapshot(),
        overwrite=overwrite,
    )
    controller._native_selected_preset_id = record.preset_id
    controller._native_preset_comment = record.comment
    _set_status(controller, f"Saved Companion Orb preset: {record.name}.")


def _service_action(controller: Any, method_name: str, **kwargs: Any) -> Any:
    service = controller._companion_orb_service()
    callback = getattr(service, method_name, None)
    if not callable(callback):
        raise RuntimeError("The running Companion Orb service is unavailable.")
    return callback(**kwargs)


def native_control_action(
    controller: Any,
    control_id: str,
    payload: Any = None,
) -> dict[str, Any]:
    """Dispatch one exact legacy action ID without constructing a widget."""

    key = str(control_id or "").strip()
    if key not in _ACTION_IDS:
        raise KeyError(f"Unknown Companion Orb action {control_id!r}.")
    request = dict(payload or {}) if isinstance(payload, Mapping) else {"payload": payload}
    presentation: dict[str, Any] = {}

    if key == 'companion_orb_watch_setup_apply':
        from .watch_setup import required_watch_settings
        expected = dict(request.get('payload') or {})
        changes = required_watch_settings(controller._runtime_config())
        if changes != expected.get('changes'):
            raise ValueError('Watch settings changed. Review setup again.')
        # Known settings only; no model selection, supervisor or other sources are enabled.
        for setting, value in changes.items():
            controller._on_setting_changed(setting, value)
        controller._save_session()
    elif key in _DIRECT_ACTIONS:
        callback = getattr(controller, _DIRECT_ACTIONS[key])
        callback()
    elif key == "btn_companion_orb_open_debug_log_folder":
        path = _debug_log_path(controller)
        path.parent.mkdir(parents=True, exist_ok=True)
        presentation["open_folder"] = str(path.parent)
        _set_status(controller, f"Opened debug log folder: {path.parent}")
    elif key == "btn_companion_orb_clear_debug_log":
        path = _debug_log_path(controller)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        _set_status(controller, "Cleared Companion Orb debug log.")
    elif key == "btn_companion_orb_copy_debug_log_path":
        presentation["clipboard_suggestion"] = str(_debug_log_path(controller))
        _set_status(controller, "Copied Companion Orb debug log path.")
    elif key == "btn_companion_orb_copy_latest_vision_trace_path":
        pointer = _debug_log_path(controller).parent / "vision_pipeline" / "latest_trace.txt"
        trace_path = pointer.read_text(encoding="utf-8").strip()
        if not trace_path or not Path(trace_path).is_file():
            raise RuntimeError(
                "No trace exists yet. Enable the recorder and run one Orb image action."
            )
        presentation["clipboard_suggestion"] = trace_path
        _set_status(controller, "Copied latest Companion Orb vision trace path.")
    elif key == 'companion_orb_watch_stop':
        target=request.get('payload',request)
        identity={k:target[k] for k in ('watch_id','expected_revision','session_key') if isinstance(target,Mapping) and k in target}
        _service_action(controller, 'stop_conversational_watch', **identity)
        _set_status(controller, 'Removed the selected watch. Other watches and sources are unchanged.')
    elif key == 'companion_orb_watch_open_capture':
        target=request.get('payload',request)
        identity={k:target[k] for k in ('watch_id','expected_revision','session_key') if isinstance(target,Mapping) and k in target}
        capture = _service_action(controller, 'watch_capture_snapshot', **identity)
        presentation['open_file'] = str(capture['image_path'])
    elif key == "companion_orb_vision_pipeline_details_button":
        snapshot = controller._service_snapshot("vision_runtime_snapshot")
        presentation["viewer_text"] = controller._vision_pipeline_details_json(snapshot)
    elif key == "btn_companion_orb_supervisor_add_persona":
        _add_supervisor_persona(controller, request)
    elif key == "btn_companion_orb_supervisor_rename_persona":
        _rename_supervisor_persona(controller, request)
    elif key == "btn_companion_orb_supervisor_delete_persona":
        _delete_supervisor_persona(controller, request)
    elif key == "btn_companion_orb_supervisor_add_behavior":
        _add_supervisor_behavior(controller)
    elif key == 'companion_orb_behavior_remove':
        index = selected_behavior_index(controller)
        if index is None:
            raise ValueError('Choose an existing behavior rule.')
        _remove_supervisor_behavior(controller, index, request)
    elif key == "btn_companion_orb_supervisor_reset_template":
        controller._update_runtime_config("companion_orb_supervisor_prompt_template", "")
        controller._publish_companion_orb_supervisor()
        controller._save_session()
        _set_status(controller, "Restored the recommended Companion Orb supervisor template.")
    elif key.startswith("unnamed_qpushbutton_remove"):
        index = 0 if "#" not in key else int(key.rsplit("#", 1)[1]) - 1
        _remove_supervisor_behavior(controller, index, request)
    elif key.startswith("btn_companion_orb_reply_style_"):
        _reply_style_action(controller, key, request)
    elif key == "btn_companion_orb_reader_commentary_reload":
        _set_status(controller, "Reloaded the saved selected-text commentary prompt.")
    elif key == "btn_companion_orb_reader_commentary_default":
        controller.native_update_setting(
            "companion_orb_reader_commentary_prompt",
            controller._reader_commentary_prompt_default(),
        )
        _set_status(controller, "Restored the recommended selected-text prompt.")
    elif key in _COLOR_ACTIONS:
        value = _input_text(request)
        if not value:
            raise ValueError("Enter a six-digit hex color such as #38bdf8.")
        native_update_control(controller, _COLOR_ACTIONS[key], value)
    elif key == "companion_orb_eye_tracking_browse_button":
        paths = _paths(request)
        if not paths:
            raise ValueError("Choose the official Tobii Stream Engine DLL.")
        native_update_control(controller, "companion_orb_eye_tracking_dll_path_edit", paths[0])
    elif key == "companion_orb_eye_tracking_reconnect_button":
        result = _service_action(controller, "reconnect_eye_tracking")
        if isinstance(result, Mapping) and not bool(result.get("ok", True)):
            raise RuntimeError(str(result.get("error") or "Eye tracking could not reconnect."))
    elif key == "companion_orb_eye_tracking_react_button":
        result = _service_action(controller, "react_at_gaze", force=True)
        if isinstance(result, Mapping) and not bool(result.get("ok", True)):
            raise RuntimeError(str(result.get("error") or "No valid gaze point is available."))
    elif key in {"btn_companion_orb_apply_custom_colors", "btn_companion_orb_save_custom_colors"}:
        _apply_custom_colors(
            controller,
            saved=key == "btn_companion_orb_save_custom_colors",
        )
    elif key == "companion_orb_lfm_interactive_guide_button":
        tutorials = getattr(controller.context.capabilities, "tutorials", None)
        starter = getattr(tutorials, "start_tutorial", None)
        if not callable(starter):
            raise RuntimeError("Interactive tutorials are unavailable.")
        starter("companion_orb_lfm_interactive")
        _set_status(controller, "Started the Companion Orb auxiliary vision guide.")
    elif key in {
        "companion_orb_preset_load_button",
        "companion_orb_preset_save_button",
        "companion_orb_preset_save_as_button",
        "companion_orb_preset_delete_button",
    }:
        _preset_action(controller, key, request)
    else:
        raise KeyError(f"Companion Orb action {key!r} has no native binding.")

    result = controller.native_snapshot()
    if presentation:
        result["presentation"] = presentation
    return result


def unsupported_action_ids() -> tuple[str, ...]:
    """Return action IDs that do not have an explicit native dispatcher branch."""

    supported = set(_DIRECT_ACTIONS) | set(_COLOR_ACTIONS)
    supported.update(
        {
            "btn_companion_orb_open_debug_log_folder",
            "btn_companion_orb_clear_debug_log",
            "btn_companion_orb_copy_debug_log_path",
            "btn_companion_orb_copy_latest_vision_trace_path",
            "companion_orb_vision_pipeline_details_button",
            'companion_orb_watch_stop',
            'companion_orb_watch_open_capture',
            'companion_orb_watch_setup_apply',
            "btn_companion_orb_supervisor_add_persona",
            "btn_companion_orb_supervisor_rename_persona",
            "btn_companion_orb_supervisor_delete_persona",
            "btn_companion_orb_supervisor_add_behavior",
            "companion_orb_behavior_remove",
            "btn_companion_orb_supervisor_reset_template",
            "btn_companion_orb_reply_style_save",
            "btn_companion_orb_reply_style_load",
            "btn_companion_orb_reply_style_default",
            "btn_companion_orb_reply_style_reset_all",
            "btn_companion_orb_reader_commentary_reload",
            "btn_companion_orb_reader_commentary_default",
            "companion_orb_eye_tracking_browse_button",
            "companion_orb_eye_tracking_reconnect_button",
            "companion_orb_eye_tracking_react_button",
            "btn_companion_orb_apply_custom_colors",
            "btn_companion_orb_save_custom_colors",
            "companion_orb_lfm_interactive_guide_button",
            "companion_orb_preset_load_button",
            "companion_orb_preset_save_button",
            "companion_orb_preset_save_as_button",
            "companion_orb_preset_delete_button",
        }
    )
    supported.update(
        key for key in _ACTION_IDS if key.startswith("unnamed_qpushbutton_remove")
    )
    return tuple(sorted(_ACTION_IDS - supported))


__all__ = ["native_control_action", "unsupported_action_ids"]
