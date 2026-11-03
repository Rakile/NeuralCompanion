"""Exact reviewed action dispatch for the native Audio Story QML surface."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import unquote, urlparse

from addons.audio_story_mode.native_contract import NATIVE_CONTROL_SPECS
from addons.audio_story_mode.native_controls import (
    _selected_project_id,
    native_control_state,
    native_update_control,
)


_ACTION_IDS = {
    str(spec["id"])
    for spec in NATIVE_CONTROL_SPECS
    if str(spec.get("kind")) == "action"
}

_DIRECT_ACTIONS = {
    "audio_story_tts_retry_button": "retry_tts",
    "audio_story_tts_clear_cache_button": "clear_tts_cache",
    "audio_story_play_button": "play",
    "audio_story_pause_button": "pause",
    "audio_story_stop_button": "stop",
    "audio_story_cast_refresh_button": "refresh_cast_devices",
    "audio_story_cast_button": "cast_current",
    "audio_story_cast_stop_button": "stop_cast",
    "audio_story_cast_install_button": "install_cast_support",
    "audio_story_style_apply_button": "apply_style",
    "audio_story_style_cancel_button": "cancel_settings_apply",
    "audio_story_recommended_continuity_button": "recommended_continuity",
    "audio_story_planner_apply_button": "apply_planner",
    "audio_story_planner_cancel_button": "cancel_settings_apply",
    "unnamed_qpushbutton_cancel": "cancel_novel_job",
    "unnamed_qpushbutton_import_confirmed_source": "import_novel_source",
    "unnamed_qpushbutton_reset_to_defaults": "reset_novel_prompts",
    "unnamed_qpushbutton_build_story_map": "build_novel_story_map",
    "unnamed_qpushbutton_build_outline": "build_novel_outline",
    "unnamed_qpushbutton_save_outline": "save_novel_outline",
    "unnamed_qpushbutton_approve_and_generate": "approve_novel",
    "unnamed_qpushbutton_assemble_novel": "assemble_novel",
    "unnamed_qpushbutton_assemble_partial_preview": "assemble_novel",
    "unnamed_qpushbutton_retry_selected_scene": "retry_novel_scene",
    "unnamed_qpushbutton_narrate_selected_chapter": "narrate_novel_chapter",
    "unnamed_qpushbutton_use_in_story_images": "handoff_novel_chapter",
    "audio_story_source_clear_button": "clear_sources",
    "audio_story_transcribe_button": "transcribe",
    "audio_story_transcription_console_clear_button": "clear_transcription_console",
    "audio_story_project_close_button": "close_project",
    "audio_story_project_resume_all_button": "resume_project",
}

_REFINE_CONTROLS = {
    "audio_story_scene_anchor_refine_button": (
        "audio_story_scene_anchor_edit",
        "Scene Anchor",
        "Refine this into a concise visual anchor with subject, action, setting, mood, camera framing, and continuity details. Do not invent story events.",
    ),
    "audio_story_scene_negative_prompt_refine_button": (
        "audio_story_scene_negative_prompt_edit",
        "Negative Prompt",
        "Refine this into concise negative-prompt wording that excludes visual mistakes, off-style results, wrong subjects, bad anatomy, text artifacts, logos, and continuity errors.",
    ),
    "unnamed_qpushbutton_refine": (
        "unnamed_qlineedit_qlineedit",
        "Realistic Style Prompt",
        "Expand this into a polished reusable visual style prompt describing medium, line quality, palette, lighting, camera, texture, mood, and rendering approach.",
    ),
    "unnamed_qpushbutton_refine#2": (
        "unnamed_qlineedit_qlineedit#2",
        "Cartoon Style Prompt",
        "Expand this into a polished reusable visual style prompt describing medium, line quality, palette, lighting, camera, texture, mood, and rendering approach.",
    ),
    "unnamed_qpushbutton_refine#3": (
        "unnamed_qlineedit_qlineedit#3",
        "Retro Style Prompt",
        "Expand this into a polished reusable visual style prompt describing medium, line quality, palette, lighting, camera, texture, mood, and rendering approach.",
    ),
    "unnamed_qpushbutton_refine#4": (
        "unnamed_qlineedit_qlineedit#4",
        "Cyberpunk Style Prompt",
        "Expand this into a polished reusable visual style prompt describing medium, line quality, palette, lighting, camera, texture, mood, and rendering approach.",
    ),
}


def _payload_value(payload: Any) -> Any:
    if isinstance(payload, Mapping) and "payload" in payload:
        return payload.get("payload")
    return payload


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


def _selected_chapter_id(controller: Any) -> str:
    return str(getattr(controller, "_current_story_chapter_id", "") or "").strip()


def _require_current_project(controller: Any) -> str:
    selected = _selected_project_id(controller)
    current = str(controller.current_story_project_id or "").strip()
    if not current or (selected and selected != current):
        raise ValueError("Open the selected Audio Story project before changing it.")
    return current


def _input_text(payload: Any) -> str:
    return str(_payload_value(payload) or "").strip()


def _refine(controller: Any, action_id: str) -> None:
    control_id, label, guidance = _REFINE_CONTROLS[action_id]
    original = str(native_control_state(controller)["values"].get(control_id) or "").strip()
    if not original:
        raise ValueError(f"Enter {label.lower()} text before refining it.")
    service = getattr(controller, "prompt_refinement", None)
    if service is None or not hasattr(service, "refine"):
        raise RuntimeError("Prompt refinement is unavailable.")
    controller._set_status(f"Refining {label}...")
    result = str(service.refine(original, label=label, guidance=guidance) or "").strip()
    if not result:
        raise RuntimeError(f"{label} refinement returned no text.")
    native_update_control(controller, control_id, result)
    controller._set_status(f"Refined {label}.")


def _apply_scene_override(controller: Any) -> None:
    controller._scene_override_refresh_after_change(refresh_visuals=True)


def _novel_selection(controller: Any) -> tuple[str, str]:
    panel = controller.audio_story_novel_panel
    scene_id = str(panel.selected_scene_id() or "").strip()
    if scene_id:
        return "scene", scene_id
    chapter_id = str(panel.selected_chapter_id() or "").strip()
    if chapter_id:
        return "chapter", chapter_id
    raise ValueError("Choose a chapter or scene outline item first.")


def _save_preset(controller: Any, payload: Any) -> None:
    name = _input_text(payload) or str(
        getattr(controller, "_native_selected_settings_preset", "") or ""
    ).strip()
    if not name:
        raise ValueError("Enter a name for the Audio Story settings preset.")
    path = Path(controller._audio_story_settings_preset_path(name))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(controller._audio_story_settings_preset_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)
    controller._native_selected_settings_preset = path.stem
    controller._set_status(f"Saved Audio Story preset: {path.stem}")


def _load_preset(controller: Any) -> None:
    name = str(getattr(controller, "_native_selected_settings_preset", "") or "").strip()
    if not name:
        raise ValueError("Choose an Audio Story settings preset to load.")
    path = Path(controller._audio_story_settings_preset_path(name))
    if not path.is_file():
        raise FileNotFoundError(f"Audio Story preset not found: {name}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("Audio Story preset must contain a JSON object.")
    controller._apply_audio_story_settings_preset_payload(payload, rebuild_story=True)
    controller._set_status(f"Loaded Audio Story preset: {name}")


def _mutate_project(controller: Any, operation: str, callback: Any) -> None:
    _require_current_project(controller)
    controller._run_story_project_mutation(operation, callback)


def native_control_action(controller: Any, control_id: str, payload: Any = None) -> dict[str, Any]:
    """Dispatch one exact legacy action ID without constructing a widget."""

    key = str(control_id or "").strip()
    if key not in _ACTION_IDS:
        raise KeyError(f"Unknown Audio Story action {control_id!r}.")
    request = dict(payload or {}) if isinstance(payload, Mapping) else {"payload": payload}

    if key in _DIRECT_ACTIONS:
        action = _DIRECT_ACTIONS[key]
        action_payload: dict[str, Any] = {}
        if key in {
            "audio_story_tts_clear_cache_button",
            "audio_story_cast_install_button",
            "unnamed_qpushbutton_approve_and_generate",
        }:
            action_payload["confirmed"] = _confirmed(request)
        if key == "unnamed_qpushbutton_assemble_partial_preview":
            action_payload["allow_partial"] = True
        controller.native_action(action, action_payload)
    elif key in _REFINE_CONTROLS:
        _refine(controller, key)
    elif key in {
        "audio_story_scene_anchor_apply_button",
        "audio_story_scene_negative_prompt_apply_button",
    }:
        _apply_scene_override(controller)
    elif key == "unnamed_qpushbutton_new_novel_project":
        controller.native_action(
            "new_novel_project",
            {
                "name": str(getattr(controller, "_native_novel_project_name", "") or ""),
                "source_kind": str(
                    controller.audio_story_novel_panel.snapshot().get("source_kind")
                    or "chatlog_json"
                ),
            },
        )
    elif key in {"unnamed_qpushbutton_choose_chatlog_json", "unnamed_qpushbutton_choose_markdown"}:
        paths = _paths(request)
        if not paths:
            raise ValueError("Choose a Novel Workshop source file.")
        controller.native_action("inspect_novel_source", {"path": paths[0]})
    elif key == "unnamed_qpushbutton_inspect_with_this_mapping":
        preview = dict(controller.audio_story_novel_panel.snapshot().get("preview") or {})
        path = str(preview.get("source_path") or "").strip()
        if not path:
            raise ValueError("Choose a Novel Workshop source file first.")
        controller.native_action(
            "inspect_novel_source",
            {"path": path, "field_map": dict(preview.get("field_map") or {})},
        )
    elif key in {
        "unnamed_qpushbutton_move_up",
        "unnamed_qpushbutton_move_down",
        "unnamed_qpushbutton_split_selected",
        "unnamed_qpushbutton_merge_with_next",
    }:
        kind, identifier = _novel_selection(controller)
        if key in {"unnamed_qpushbutton_move_up", "unnamed_qpushbutton_move_down"}:
            controller.native_action(
                "move_novel_outline_item",
                {"kind": kind, "identifier": identifier, "direction": -1 if key.endswith("move_up") else 1},
            )
        else:
            controller.native_action(
                "split_novel_outline_item" if key.endswith("split_selected") else "merge_novel_outline_item",
                {"kind": kind, "identifier": identifier},
            )
    elif key == "audio_story_import_button":
        paths = _paths(request)
        if not paths:
            raise ValueError("Choose one or more audio files to import.")
        controller._set_imported_audio_paths(paths, clear_story=True)
    elif key in {"audio_story_source_move_up_button", "audio_story_source_move_down_button"}:
        paths = list(controller.imported_audio_paths or [])
        index = int(getattr(controller, "_native_selected_source_index", 0) or 0)
        target = index + (-1 if key.endswith("move_up_button") else 1)
        if not (0 <= index < len(paths) and 0 <= target < len(paths)):
            raise ValueError("Choose an audio source that can move in that direction.")
        paths[index], paths[target] = paths[target], paths[index]
        controller._native_selected_source_index = target
        controller._set_imported_audio_paths(paths, clear_story=True)
    elif key == "audio_story_source_remove_button":
        paths = list(controller.imported_audio_paths or [])
        index = int(getattr(controller, "_native_selected_source_index", 0) or 0)
        if not 0 <= index < len(paths):
            raise ValueError("Choose an audio source to remove.")
        paths.pop(index)
        controller._native_selected_source_index = min(index, max(0, len(paths) - 1))
        controller._set_imported_audio_paths(paths, clear_story=True)
    elif key == "audio_story_settings_preset_save_button":
        _save_preset(controller, request)
    elif key == "audio_story_settings_preset_load_button":
        _load_preset(controller)
    elif key == "audio_story_transcription_console_copy_button":
        pass
    elif key == "audio_story_project_new_button":
        controller.native_action("new_project", {"name": _input_text(request)})
    elif key == "audio_story_project_open_button":
        controller.native_action("open_project", {"project_id": _selected_project_id(controller)})
    elif key == "audio_story_project_delete_button":
        controller.native_action(
            "delete_project",
            {"project_id": _selected_project_id(controller), "confirmed": _confirmed(request)},
        )
    elif key == "audio_story_project_rename_button":
        name = _input_text(request)
        if not name:
            raise ValueError("Enter a new project name.")
        _mutate_project(controller, "rename", lambda: controller._story_project_manager.rename(name))
    elif key == "audio_story_project_add_audio_button":
        _require_current_project(controller)
        paths = _paths(request)
        if not paths:
            raise ValueError("Choose one or more chapter audio files.")
        controller._import_story_project_audio_paths(paths)
    elif key == "audio_story_project_chapter_rename_button":
        chapter_id = _selected_chapter_id(controller)
        name = _input_text(request)
        if not chapter_id or not name:
            raise ValueError("Choose a chapter and enter its new name.")
        _mutate_project(
            controller,
            "chapter-rename",
            lambda: controller._story_project_manager.rename_chapter(chapter_id, name),
        )
    elif key in {"audio_story_project_chapter_move_up_button", "audio_story_project_chapter_move_down_button"}:
        chapter_id = _selected_chapter_id(controller)
        order = list(dict(controller._current_story_project or {}).get("chapter_order") or [])
        if chapter_id not in order:
            raise ValueError("Choose an active chapter to move.")
        index = order.index(chapter_id)
        target = index + (-1 if key.endswith("move_up_button") else 1)
        if target < 0 or target >= len(order):
            raise ValueError("The selected chapter cannot move farther in that direction.")
        order[index], order[target] = order[target], order[index]
        _mutate_project(
            controller,
            "chapter-reorder",
            lambda: controller._story_project_manager.reorder_chapters(order),
        )
    elif key == "audio_story_project_relink_button":
        chapter_id = _selected_chapter_id(controller)
        paths = _paths(request)
        if not chapter_id or not paths:
            raise ValueError("Choose a chapter and its replacement audio file.")
        _mutate_project(
            controller,
            "relink",
            lambda: controller._story_project_manager.relink_chapter(chapter_id, paths[0]),
        )
    elif key in {"audio_story_project_archive_button", "audio_story_project_restore_button"}:
        chapter_id = _selected_chapter_id(controller)
        if not chapter_id:
            raise ValueError("Choose a chapter first.")
        operation = "archive" if key.endswith("archive_button") else "restore"
        callback = (
            lambda: controller._story_project_manager.archive_chapter(chapter_id)
            if operation == "archive"
            else controller._story_project_manager.restore_chapter(chapter_id)
        )
        _mutate_project(controller, operation, callback)
    elif key == "audio_story_project_retry_button":
        chapter_id = _selected_chapter_id(controller)
        plan = list(controller._build_story_project_resume_plan()) if hasattr(controller, "_build_story_project_resume_plan") else []
        if not plan:
            from addons.audio_story_mode import checkpointing

            plan = checkpointing.build_resume_plan(dict(controller._current_story_project or {}))
        item = next((entry for entry in plan if not chapter_id or str(entry.get("chapter_id") or "") == chapter_id), None)
        if not item:
            raise ValueError("The selected chapter has no retryable work.")
        controller._retry_story_project_item(dict(item))
    elif key == "audio_story_project_save_current_button":
        controller.native_action("save_current_project", {"name": _input_text(request)})
    else:
        raise KeyError(f"Audio Story action {key!r} has no native dispatcher.")

    snapshot = controller.native_snapshot()
    if key == "audio_story_transcription_console_copy_button":
        snapshot["presentation"] = {
            "clipboard_suggestion": str(
                getattr(controller, "_transcription_console_text", "") or ""
            )
        }
    return snapshot


def unsupported_action_ids() -> tuple[str, ...]:
    special = set(_REFINE_CONTROLS) | {
        "audio_story_scene_anchor_apply_button",
        "audio_story_scene_negative_prompt_apply_button",
        "unnamed_qpushbutton_new_novel_project",
        "unnamed_qpushbutton_choose_chatlog_json",
        "unnamed_qpushbutton_choose_markdown",
        "unnamed_qpushbutton_inspect_with_this_mapping",
        "unnamed_qpushbutton_move_up",
        "unnamed_qpushbutton_move_down",
        "unnamed_qpushbutton_split_selected",
        "unnamed_qpushbutton_merge_with_next",
        "audio_story_import_button",
        "audio_story_source_move_up_button",
        "audio_story_source_move_down_button",
        "audio_story_source_remove_button",
        "audio_story_settings_preset_save_button",
        "audio_story_settings_preset_load_button",
        "audio_story_transcription_console_copy_button",
        "audio_story_project_new_button",
        "audio_story_project_open_button",
        "audio_story_project_rename_button",
        "audio_story_project_delete_button",
        "audio_story_project_add_audio_button",
        "audio_story_project_chapter_rename_button",
        "audio_story_project_chapter_move_up_button",
        "audio_story_project_chapter_move_down_button",
        "audio_story_project_relink_button",
        "audio_story_project_archive_button",
        "audio_story_project_restore_button",
        "audio_story_project_retry_button",
        "audio_story_project_save_current_button",
    }
    return tuple(sorted(_ACTION_IDS - set(_DIRECT_ACTIONS) - special))


__all__ = ["native_control_action", "unsupported_action_ids"]
