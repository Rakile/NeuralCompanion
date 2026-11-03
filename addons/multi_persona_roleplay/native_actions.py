"""Finite native-QML action boundary for Multi Persona Roleplay.

The legacy workspace exposed a large number of buttons.  This module keeps
that public action contract while routing each command to the existing MPRC
models and services.  It deliberately contains no QWidget or Designer logic.
"""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from addons.multi_persona_roleplay.audio_prompts import AUDIO_TYPES, create_audio_prompt
from addons.multi_persona_roleplay.models import (
    AR_MODE,
    PersonaConfig,
    RoleplaySessionState,
    normalize_persona_id,
    personas_from_payload,
    unique_persona_id,
)
from addons.multi_persona_roleplay.native_contract import MPRC_ACTION_SPECS, MPRC_CONTROL_SPECS


ActionHandler = Callable[[Any, dict[str, Any]], dict[str, Any] | None]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _raw_payload(request: dict[str, Any]) -> Any:
    return request.get("payload")


def _first_payload_value(request: dict[str, Any]) -> Any:
    value = _raw_payload(request)
    if isinstance(value, (list, tuple)):
        return value[0] if value else ""
    return value


def _path_from_request(request: dict[str, Any], *, required: bool = True) -> Path | None:
    raw = str(_first_payload_value(request) or "").strip()
    if not raw:
        if required:
            raise ValueError("Choose a file or folder before running this action.")
        return None
    parsed = urlparse(raw)
    if parsed.scheme.lower() == "file":
        value = unquote(parsed.path or "")
        if parsed.netloc:
            value = f"//{parsed.netloc}{value}"
        elif re.match(r"^/[A-Za-z]:/", value):
            value = value[1:]
        raw = value
    return Path(raw)


def _require_confirmation(request: dict[str, Any]) -> None:
    if not bool(request.get("confirmed")):
        raise ValueError("This destructive action requires explicit confirmation.")


def _require_story_deletion_idle(controller: Any, story_id: str) -> None:
    play = getattr(controller, "_scenario_play", None)
    if play is None:
        return
    with play._queue_lock:
        pending = play._running or bool(play._queue)
        active = play._active
    if not active and not pending:
        return
    checkpoint = play.runtime._cp
    owned_ids = {checkpoint.story_id} if checkpoint is not None else set()
    # Queued/running operations capture their story before settings can change.
    # Wait for the existing writer lane to drain rather than guess its ownership
    # from mutable settings, even after Stop invalidates the active session.
    if pending or controller.storage.story_id(story_id) in {
        controller.storage.story_id(value) for value in owned_ids
    }:
        raise ValueError(
            "Stop the scenario first, then wait for its current work to finish before deleting this story. "
            "The scenario is still active or saving progress and could recreate deleted files."
        )


def _selected_persona(controller: Any) -> PersonaConfig | None:
    selected_id = normalize_persona_id(
        controller.settings.get("native_selected_persona_id")
        or controller.session.active_persona_id
        or controller.session.current_speaker_id
    )
    return controller.persona_by_id(selected_id) or controller.active_persona()


def _selected_story_id(controller: Any) -> str:
    selected = controller.storage.story_id(
        controller.settings.get("native_selected_story_id")
        or controller.settings.get("last_master_story_id")
        or ""
    )
    if selected:
        return selected
    index = controller.storage.load_story_index()
    return str(index[0].get("id") or "") if index else ""


def _selected_index(controller: Any, key: str, count: int) -> int:
    try:
        index = int(controller.settings.get(key, -1))
    except (TypeError, ValueError):
        index = -1
    return index if 0 <= index < count else -1


def _save(controller: Any) -> None:
    controller.storage.save_settings(controller.settings)
    controller.save_state()
    controller.refresh_ui()


def _result(message: str, **details: Any) -> dict[str, Any]:
    return {"accepted": True, "message": str(message or ""), **details}


def _copy_text(controller: Any, text: Any, message: str = "Ready to copy.") -> dict[str, Any]:
    controller._native_clipboard_suggestion = str(text or "")
    return _result(message, characters=len(controller._native_clipboard_suggestion))


def _quick_change_avatar(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    persona = _selected_persona(controller)
    if persona is None:
        raise ValueError("No persona is selected.")
    path = _path_from_request(request)
    if path is None or not path.is_file():
        raise ValueError("The selected avatar image does not exist.")
    persona.character_image_path = str(path.resolve())
    _save(controller)
    return _result(f"Avatar image updated for {persona.display_name}.", persona_id=persona.id)


def _quick_save_persona(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    persona = _selected_persona(controller)
    _save(controller)
    return _result(f"Saved {persona.display_name if persona else 'persona settings'}.")


def _import_personas(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    path = _path_from_request(request)
    personas = controller.storage.import_personas_from_path(path)
    controller.personas = personas
    controller.session.active_persona_id = personas[0].id
    controller.session.current_speaker_id = personas[0].id
    controller.settings["native_selected_persona_id"] = personas[0].id
    _save(controller)
    return _result(f"Imported {len(personas)} persona(s).", count=len(personas))


def _export_personas(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    path = _path_from_request(request)
    controller.storage.export_personas_to_path(path, controller.personas)
    return _result(f"Exported {len(controller.personas)} persona(s) to {path}.", path=str(path))


def _duplicate_persona(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    source = _selected_persona(controller)
    if source is None:
        raise ValueError("No persona is selected.")
    payload = source.to_dict()
    payload["id"] = unique_persona_id(source.id + "_copy", {item.id for item in controller.personas})
    payload["display_name"] = source.display_name + " Copy"
    persona = PersonaConfig.from_dict(payload)
    controller.personas.append(persona)
    controller.session.active_persona_id = persona.id
    controller.session.current_speaker_id = persona.id
    controller.settings["native_selected_persona_id"] = persona.id
    _save(controller)
    return _result(f"Duplicated {source.display_name} as {persona.display_name}.", persona_id=persona.id)


def _edit_persona(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    persona = _selected_persona(controller)
    if persona is None:
        raise ValueError("No persona is selected.")
    controller._native_requested_section = "Editor"
    return _result(f"Opened the editor for {persona.display_name}.", persona_id=persona.id, section="Editor")


def _add_persona(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    persona_id = unique_persona_id("new_persona", {item.id for item in controller.personas})
    persona = PersonaConfig(id=persona_id, display_name=persona_id.replace("_", " ").title())
    controller.personas.append(persona)
    controller.session.active_persona_id = persona.id
    controller.session.current_speaker_id = persona.id
    controller.settings["native_selected_persona_id"] = persona.id
    _save(controller)
    return _result(f"Added {persona.display_name}.", persona_id=persona.id)


def _delete_persona(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    _require_confirmation(request)
    persona = _selected_persona(controller)
    if persona is None:
        raise ValueError("No persona is selected.")
    if len(controller.personas) <= 1:
        raise ValueError("At least one persona must remain.")
    controller.personas = [item for item in controller.personas if item.id != persona.id]
    replacement = controller.personas[0]
    controller.session.active_persona_id = replacement.id
    controller.session.current_speaker_id = replacement.id
    controller.settings["native_selected_persona_id"] = replacement.id
    _save(controller)
    return _result(f"Deleted {persona.display_name}.", persona_id=persona.id)


def _reset_personas(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    _require_confirmation(request)
    defaults = personas_from_payload(controller.storage._default_json("personas.json", []))
    if not defaults:
        raise RuntimeError("The safe default persona catalog is unavailable.")
    controller.personas = defaults
    controller.session.active_persona_id = defaults[0].id
    controller.session.current_speaker_id = defaults[0].id
    controller.settings["native_selected_persona_id"] = defaults[0].id
    _save(controller)
    return _result(f"Restored {len(defaults)} safe default personas.", count=len(defaults))


def _debug_copy(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    source = str(request.get("source") or "")
    values = {
        "prompt": controller._debug_prompt,
        "visual": controller._debug_visual_prompt,
        "voice": controller._debug_voice,
        "state": json.dumps(controller.session.to_dict(), indent=2, ensure_ascii=False),
        "visual_calls": controller._visual_debug_log_text(),
    }
    return _copy_text(controller, values.get(source, ""))


def _clear_debug(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    _require_confirmation(request)
    controller._clear_debug()
    return _result("Cleared MPRC troubleshooting output.")


def _clear_visual_debug(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    _require_confirmation(request)
    controller._clear_visual_debug_log()
    return _result("Cleared the Visual Reply request log.")


def _create_test_audio(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    specs = controller._test_audiofx_specs()
    base_dir = controller.context.storage.resolve("test_audio")
    base_dir.mkdir(parents=True, exist_ok=True)
    items = [item for item in controller._audiofx_items() if not str(item.get("id") or "").startswith("mprc_test_")]
    stamp = _now()
    for spec in specs:
        path = base_dir / spec["file_name"]
        controller._write_test_audio_file(path, spec["profile"])
        items.append({
            "id": spec["id"], "type": spec["type"], "description": spec["description"],
            "prompt": spec["prompt"], "file_path": str(path), "created_at": stamp, "updated_at": stamp,
        })
    controller.settings["audiofx_test_mode"] = True
    controller.settings["story_sounds_enabled"] = True
    controller._save_audiofx_items(items)
    controller._populate_audiofx_items()
    controller.storage.save_settings(controller.settings)
    return _result(f"Created {len(specs)} test sounds.", folder=str(base_dir))


def _play_test_audio(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    if not any(str(item.get("id") or "").startswith("mprc_test_") for item in controller._audiofx_items()):
        _create_test_audio(controller, request)
    controller.settings["story_sounds_enabled"] = True
    controller.storage.save_settings(controller.settings)
    controller._trigger_story_audio_cues("pub ambient", warn_unmatched=True)
    return _result("Playing the test ambience cue.")


def _create_audio_prompt(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    description = str(controller.settings.get("audio_prompt_description") or "").strip()
    if not description:
        raise ValueError("Add a Sound Description first.")
    audio_type = str(controller.settings.get("audio_prompt_type") or "Auto").strip()
    if audio_type not in AUDIO_TYPES:
        audio_type = "Auto"
    variant = str(request.get("variant") or "").strip()
    prompt = create_audio_prompt(description, audio_type, variant=variant)
    controller.settings["audio_prompt_output"] = prompt
    controller.storage.save_settings(controller.settings)
    return _result("Created an audio prompt.", prompt=prompt)


def _save_audio_prompt(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    prompt = str(controller.settings.get("audio_prompt_output") or "").strip()
    if not prompt:
        raise ValueError("Create or enter an audio prompt before saving.")
    saved = [dict(item) for item in list(controller.settings.get("saved_audio_prompts") or []) if isinstance(item, dict)]
    saved.append({
        "created_at": _now(),
        "type": str(controller.settings.get("audio_prompt_type") or "Auto"),
        "description": str(controller.settings.get("audio_prompt_description") or ""),
        "prompt": prompt,
    })
    controller.settings["saved_audio_prompts"] = saved[-100:]
    controller.settings["native_audio_prompt_index"] = len(controller.settings["saved_audio_prompts"]) - 1
    controller.storage.save_settings(controller.settings)
    controller._populate_audio_saved_prompts()
    return _result("Saved the audio prompt.")


def _load_audio_prompt(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    prompts = controller._saved_audio_prompts()
    index = _selected_index(controller, "native_audio_prompt_index", len(prompts))
    if index < 0:
        raise ValueError("Select a saved audio prompt first.")
    item = prompts[index]
    controller.settings["audio_prompt_type"] = str(item.get("type") or "Auto")
    controller.settings["audio_prompt_description"] = str(item.get("description") or "")
    controller.settings["audio_prompt_output"] = str(item.get("prompt") or "")
    controller.storage.save_settings(controller.settings)
    return _result(f"Loaded saved audio prompt {index + 1}.", index=index)


def _delete_audio_prompt(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    _require_confirmation(request)
    prompts = controller._saved_audio_prompts()
    index = _selected_index(controller, "native_audio_prompt_index", len(prompts))
    if index < 0:
        raise ValueError("Select a saved audio prompt first.")
    prompts.pop(index)
    controller.settings["saved_audio_prompts"] = prompts
    controller.settings["native_audio_prompt_index"] = min(index, len(prompts) - 1)
    controller.storage.save_settings(controller.settings)
    controller._populate_audio_saved_prompts()
    return _result("Deleted the selected saved audio prompt.")


def _audio_builder_payload(controller: Any) -> dict[str, str]:
    audio_type = str(controller.settings.get("audio_prompt_type") or "Auto")
    if audio_type not in AUDIO_TYPES:
        audio_type = "Auto"
    description = str(controller.settings.get("audio_prompt_description") or "").strip()
    prompt = str(controller.settings.get("audio_prompt_output") or "").strip()
    if description and not prompt:
        prompt = create_audio_prompt(description, audio_type)
        controller.settings["audio_prompt_output"] = prompt
    if prompt and not description:
        description = prompt[:120]
    return {"type": audio_type, "description": description, "prompt": prompt}


def _create_audiofx(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    payload = _audio_builder_payload(controller)
    if not payload["description"] and not payload["prompt"]:
        raise ValueError("Add a Sound Description or choose a saved prompt first.")
    items = controller._audiofx_items()
    item = {
        "id": controller._new_audiofx_id(items), **payload, "file_path": "",
        "created_at": _now(), "updated_at": _now(),
    }
    items.append(item)
    controller._save_audiofx_items(items)
    controller.settings["native_audiofx_index"] = len(items) - 1
    controller.storage.save_settings(controller.settings)
    controller._populate_audiofx_items()
    return _result("Created a story sound item.", audiofx_id=item["id"])


def _import_audio_pack(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    path = _path_from_request(request)
    added, updated, skipped = controller._import_audio_pack_from_path(path)
    return _result(
        f"Imported audio pack: {added} added, {updated} updated, {skipped} skipped.",
        added=added, updated=updated, skipped=skipped,
    )


def _add_audiofx_file(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    path = _path_from_request(request)
    if path is None or not path.is_file():
        raise ValueError("The selected sound file does not exist.")
    items = controller._audiofx_items()
    index = _selected_index(controller, "native_audiofx_index", len(items))
    if index < 0:
        _create_audiofx(controller, {})
        items = controller._audiofx_items()
        index = _selected_index(controller, "native_audiofx_index", len(items))
    items[index]["file_path"] = str(path.resolve())
    items[index]["updated_at"] = _now()
    controller._save_audiofx_items(items)
    controller._populate_audiofx_items()
    return _result("Attached the selected sound file.", path=str(path))


def _load_audiofx(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    items = controller._audiofx_items()
    index = _selected_index(controller, "native_audiofx_index", len(items))
    if index < 0:
        raise ValueError("Select a story sound first.")
    item = items[index]
    controller.settings["audio_prompt_type"] = str(item.get("type") or "Auto")
    controller.settings["audio_prompt_description"] = str(item.get("description") or "")
    controller.settings["audio_prompt_output"] = str(item.get("prompt") or "")
    controller.storage.save_settings(controller.settings)
    return _result("Loaded the selected story sound description.", audiofx_id=item.get("id"))


def _delete_audiofx(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    _require_confirmation(request)
    items = controller._audiofx_items()
    index = _selected_index(controller, "native_audiofx_index", len(items))
    if index < 0:
        raise ValueError("Select a story sound first.")
    removed = items.pop(index)
    controller._save_audiofx_items(items)
    controller.settings["native_audiofx_index"] = min(index, len(items) - 1)
    controller.storage.save_settings(controller.settings)
    controller._populate_audiofx_items()
    return _result("Deleted the selected story sound.", audiofx_id=removed.get("id"))


def _play_audiofx(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    items = controller._audiofx_items()
    index = _selected_index(controller, "native_audiofx_index", len(items))
    if index < 0:
        raise ValueError("Select a story sound first.")
    item = items[index]
    path = Path(str(item.get("file_path") or ""))
    if not path.is_file():
        raise ValueError("Attach a valid local sound file before playing this item.")
    controller._play_story_audio_entry(item)
    return _result("Playing the selected story sound.", audiofx_id=item.get("id"))


def _save_audio_item_description(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    prompt = str(controller.settings.get("audio_prompt_output") or "").strip()
    if not prompt:
        raise ValueError("Create or enter an audio prompt first.")
    controller.settings["audio_item_description"] = prompt
    controller.storage.save_settings(controller.settings)
    items = controller._audiofx_items()
    index = _selected_index(controller, "native_audiofx_index", len(items))
    if index >= 0:
        items[index].update(_audio_builder_payload(controller))
        items[index]["updated_at"] = _now()
        controller._save_audiofx_items(items)
        controller._populate_audiofx_items()
    return _result("Saved the prompt as the AudioFX item description.")


def _clear_audio_builder(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    _require_confirmation(request)
    controller.settings.update({"audio_prompt_type": "Auto", "audio_prompt_description": "", "audio_prompt_output": ""})
    controller.storage.save_settings(controller.settings)
    return _result("Cleared the audio prompt builder.")


def _selected_story(controller: Any) -> tuple[str, dict[str, Any]]:
    story_id = _selected_story_id(controller)
    payload = controller.storage.load_story(story_id) if story_id else {}
    return story_id, payload


def _load_story(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    story_id, payload = _selected_story(controller)
    if not story_id or not payload:
        raise ValueError("Select a saved story first.")
    from .scenario_transfer import preflight_story_extension
    preflight_story_extension(payload)
    current = controller.storage.story_id(controller.settings.get("last_master_story_id") or "")
    if current and current != story_id:
        controller.save_active_story_memory_snapshot()
    payload, removed = controller._compact_legacy_registry_story_snapshot(payload)
    payload = controller._normalize_master_story_payload(payload)
    controller._master_story_draft = copy.deepcopy(payload)
    controller._set_master_story_creator_context_from_payload(payload)
    controller._set_master_story_visual_direction(payload.get("avatar_visual_direction"))
    controller._set_master_story_sfw_from_payload(payload)
    apply_result = controller._apply_master_story_payload(
        payload,
        apply_plan={"clear_memory": True, "persist_memory_snapshot": False},
    )
    restored = controller._restore_story_memory_snapshot(story_id)
    if restored:
        controller._restrict_restored_story_memory_to_cast(apply_result.get("linked") or [])
    controller.settings["native_selected_story_id"] = story_id
    _save(controller)
    return _result(f"Loaded story '{payload.get('title') or story_id}'.", story_id=story_id, removed_legacy_personas=removed)


def _delete_story(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    _require_confirmation(request)
    story_id = _selected_story_id(controller)
    if not story_id:
        raise ValueError("Select a saved story first.")
    _require_story_deletion_idle(controller, story_id)
    controller.storage.delete_story(story_id)
    controller.settings["native_selected_story_id"] = ""
    controller.storage.save_settings(controller.settings)
    controller.refresh_ui()
    return _result(f"Deleted story {story_id}.", story_id=story_id)


def _export_story_package(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    path = _path_from_request(request)
    if path is None:
        raise ValueError("Choose an export path.")
    if not str(path).lower().endswith((".mprcstory.zip", ".storypackage.zip", ".zip")):
        path = Path(str(path) + ".mprcstory.zip")
    sections = [
        str(item) for item in list(controller.settings.get("native_story_export_sections") or [])
        if str(item or "").strip()
    ] or None
    manifest, warnings = controller._write_story_package(path, sections)
    return _result(
        f"Exported '{manifest.get('story_title') or manifest.get('story_id')}' to {path}.",
        path=str(path), warnings=warnings,
    )


def _import_story_package(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    path = _path_from_request(request)
    manifest, warnings = controller._read_story_package_manifest(path)
    result = controller._apply_story_package(path, manifest=manifest)
    controller._native_story_import_review = {
        "title": str(manifest.get("story_title") or manifest.get("story_id") or "Untitled"),
        "included_sections": list(manifest.get("included_sections") or []),
        "asset_count": len(dict(manifest.get("asset_file_map") or {})),
        "warnings": list(warnings) + list(result.get("warnings") or []),
    }
    controller.refresh_ui()
    return _result(f"Imported story package '{result.get('story_title') or result.get('story_id')}'.", **result)


def _preview_story_package(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    controller._preview_story_package_contents()
    return _result("Prepared the story package preview.")


def _save_master_story(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(controller._master_story_draft or controller._current_master_story_snapshot())
    if not payload:
        raise ValueError("Create or load a Master Story draft first.")
    payload = controller._sanitize_master_story_overrides_for_options(payload)
    payload["narrator_persona_id"] = controller.selected_narrator_persona_id()
    payload["narrator_persona_mode"] = controller._narrator_selection_mode()
    payload["updated_at"] = _now()
    story_id = controller.storage.save_story(payload)
    controller._master_story_draft = payload
    controller.settings["native_selected_story_id"] = story_id
    controller.settings["last_master_story_id"] = story_id
    controller.settings["last_master_story_title"] = str(payload.get("title") or story_id)
    _save(controller)
    return _result(f"Saved story '{payload.get('title') or story_id}'.", story_id=story_id)


def _apply_master_story(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(controller._master_story_draft)
    if not payload:
        raise ValueError("Generate, paste, or load a Master Story draft first.")
    plan = {
        "clear_memory": bool(controller.settings.get("master_story_clear_memory", True)),
        "auto_create": bool(controller.settings.get("master_story_auto_create", True)),
    }
    result = controller._apply_master_story_payload(payload, apply_plan=plan)
    controller.refresh_ui()
    return _result("Applied the Master Story draft.", apply_result=result)


def _restart_story(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    _require_confirmation(request)
    controller._restart_master_story(confirmed=True)
    return _result("Cleared the active Master Story runtime state.")


def _generate_master_story(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    prompt = str(controller.settings.get("master_story_prompt") or "").strip()
    if not prompt:
        raise ValueError("Add a Master Story prompt first.")
    return controller.native_generate_master_story(prompt)


def _reset_scene(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    _require_confirmation(request)
    active_id = controller.session.active_persona_id
    controller.session = RoleplaySessionState(
        mode=controller.session.mode,
        active_persona_id=active_id,
        current_speaker_id=active_id,
        ar_pacing=controller.session.ar_pacing,
        ar_interaction_frequency=controller.session.ar_interaction_frequency,
        ar_dialogue_density=controller.session.ar_dialogue_density,
    )
    if controller.session.mode == AR_MODE:
        controller.ensure_ar_state()
    _save(controller)
    return _result("Reset the current scene.")


def _export_session(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    path = _path_from_request(request)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(controller.session.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return _result(f"Exported the roleplay session to {path}.", path=str(path))


def _import_session(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    path = _path_from_request(request)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("The session file must contain a JSON object.")
    controller.session = RoleplaySessionState.from_dict(payload)
    controller._ensure_session_persona()
    _save(controller)
    return _result(f"Imported the roleplay session from {path}.", path=str(path))


def _voice_test(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    persona = controller._selected_voice_persona() or _selected_persona(controller)
    if persona is None:
        raise ValueError("No voice persona is selected.")
    route = controller.voice_router.effective_voice_config({
        "persona_id": persona.id,
        "tts_backend": controller.current_tts_backend(),
        "text": f"[CHARACTER: {persona.display_name}]\nVoice preview.",
    })
    sample = str(route.get("sample_path") or persona.voice.sample_path or "").strip()
    if not sample:
        raise ValueError(str(route.get("warning") or f"{persona.display_name} has no usable voice sample."))
    if not controller._preview_voice_sample(sample, f"[CHARACTER: {persona.display_name}]\n{controller._default_voice_preview_text()}"):
        raise RuntimeError("Could not start the voice preview.")
    controller._native_voice_status = f"Voice preview queued for {persona.display_name}."
    return _result(controller._native_voice_status, persona_id=persona.id)


def _voice_browse(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    persona = controller._selected_voice_persona() or _selected_persona(controller)
    if persona is None:
        raise ValueError("No voice persona is selected.")
    path = _path_from_request(request)
    if path is None or not path.is_file():
        raise ValueError("The selected voice sample does not exist.")
    persona.voice.sample_path = str(path.resolve())
    persona.voice.enabled = True
    _save(controller)
    return _result(f"Voice sample updated for {persona.display_name}.", path=str(path))


def _voice_clear(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    _require_confirmation(request)
    persona = controller._selected_voice_persona() or _selected_persona(controller)
    if persona is None:
        raise ValueError("No voice persona is selected.")
    persona.voice.sample_path = ""
    persona.voice.preset_name = ""
    persona.voice.enabled = False
    _save(controller)
    return _result(f"Cleared voice settings for {persona.display_name}.")


def _character_image_browse(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    return _quick_change_avatar(controller, request)


def _character_image_generate(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    persona = _selected_persona(controller)
    if persona is None:
        raise ValueError("No persona is selected.")
    result = controller._request_character_image_generation(persona)
    return _result("Character portrait generation was queued.", persona_id=persona.id, result=result)


def _character_image_clear(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    _require_confirmation(request)
    persona = _selected_persona(controller)
    if persona is None:
        raise ValueError("No persona is selected.")
    persona.character_image_path = ""
    _save(controller)
    return _result(f"Cleared the character picture for {persona.display_name}.")


def _export_story_bundle(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    path = _path_from_request(request)
    bundle = controller._build_story_bundle()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8")
    return _result(f"Exported the story bundle to {path}.", path=str(path))


def _import_story_bundle(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    path = _path_from_request(request)
    bundle = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(bundle, dict) or str(bundle.get("bundle_type") or "") != "mprc_story_bundle":
        raise ValueError("This file is not an MPRC story bundle.")
    return controller.native_import_story_bundle(bundle, source_path=str(path))


def _story_first_run(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    if not controller._current_story_id():
        controller.native_load_demo_story()
    validation = controller.validate_story_setup()
    controller._native_story_inspector = json.dumps(validation, indent=2, ensure_ascii=False)
    return _result("Demo/validation path completed.", validation=validation)


def _story_template(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    template_id = str(controller.settings.get("native_story_template_id") or "").strip()
    if not template_id:
        choices = controller._story_template_choices()
        template_id = str(choices[0][0] if choices else "")
    if not template_id:
        raise ValueError("No story template is available.")
    controller.native_load_story_template(template_id)
    return _result(f"Loaded story template {template_id}.", template_id=template_id)


def _story_status(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    controller.refresh_ui()
    validation = controller.validate_story_setup()
    controller._native_story_inspector = json.dumps(validation, indent=2, ensure_ascii=False)
    return _result("Story health refreshed.", validation=validation)


def _story_validate(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    validation = controller.validate_story_setup()
    controller._native_story_inspector = json.dumps(validation, indent=2, ensure_ascii=False)
    return _result("Story setup validation completed.", validation=validation)


def _story_restore_backup(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    if not controller._last_pre_apply_backup_exists():
        raise ValueError("No usable pre-apply backup is available.")
    controller._restore_last_pre_apply_backup()
    return _result("Restored the last pre-apply backup.")


def _story_reset_only(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    _require_confirmation(request)
    reset_result = controller._reset_current_story_only(confirmed=True)
    if not bool((reset_result or {}).get("accepted", False)):
        raise RuntimeError("The active story could not be reset.")
    return _result("Reset the active story while keeping saved personas and story files.")


def _story_demo(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    controller.native_load_demo_story()
    return _result("Loaded the MPRC demo story.")


def _repair_voice(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    return _voice_browse(controller, request)


def _repair_image(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    return _quick_change_avatar(controller, request)


def _memory_save_pins(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    raw = str(controller.settings.get("native_story_pinned_facts") or "")
    lines = [line.strip() for line in raw.splitlines() if line.strip()][:80]
    payload = controller._memory_payload()
    payload["pinned_facts"] = lines
    controller.long_memory.save(payload)
    controller.save_active_story_memory_snapshot()
    controller._refresh_memory_browser()
    return _result(f"Saved {len(lines)} pinned fact(s).", count=len(lines))


def _memory_delete(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    _require_confirmation(request)
    event_id = str(controller.settings.get("native_story_memory_event_id") or "").strip()
    if not event_id:
        raise ValueError("Select a memory item first.")
    payload = controller._memory_payload()
    events = [item for item in list(payload.get("events") or []) if str((item or {}).get("id") or "") != event_id]
    payload["events"] = events
    payload["chapters"] = controller.long_memory._build_chapters(events)
    payload["character_memory"] = controller.long_memory._build_character_memory(events, controller.story_prompt_personas())
    payload["location_memory"] = controller.long_memory._build_location_memory(events)
    controller.long_memory.save(payload)
    controller.save_active_story_memory_snapshot()
    controller._refresh_memory_browser()
    return _result(f"Deleted memory event {event_id}.", event_id=event_id)


def _story_preview_next(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    controller._native_story_inspector = controller._next_ar_request_text()
    return _result("Prepared the next AR request preview.")


def _story_explain_next(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    controller._native_story_inspector = controller._next_routing_explanation_text()
    return _result("Prepared the next routing explanation.")


def _story_clear_log(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    _require_confirmation(request)
    controller._clear_story_event_log()
    return _result("Cleared story notes.")


def _guide_texts() -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for control_id, label, kind, section, value, _options, _read_only, _secret, _metadata in MPRC_CONTROL_SPECS:
        if str(section) == "Guide" and str(kind) in {"display", "multiline"} and str(value or "").strip():
            result.append((str(label or control_id), str(value)))
    return result


def _guide_read(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    index = request.get("index")
    texts = _guide_texts()
    if index == "all":
        title = "Multi Persona Roleplay Guide"
        text = "\n\n".join(value for _label, value in texts)
    else:
        try:
            item = texts[int(index)]
        except (IndexError, TypeError, ValueError):
            raise ValueError("The requested guide section is unavailable.")
        title, text = item
    controller._speak_guide_section(title, text)
    return _result(f"Reading {title}.")


def _load_default_scenario(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    controller._load_default_scenario()
    return _result("Loaded the default saved scenario.")


def _chat_director(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    action = str(request.get("director_action") or "advance")
    prompts = {
        "advance": "Advance the current scene naturally.",
        "summarize": "Summarize the current story state and important unresolved threads.",
        "repair": "Repair continuity problems in the current story and continue coherently.",
    }
    result = controller.remote_send(
        prompts.get(action, prompts["advance"]),
        intent=action.title(),
        speaker_id=str(controller.settings.get("native_chat_speaker_id") or ""),
    )
    return _result(f"Queued the {action} director turn.", remote=result)


def _chat_send(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    text = str(controller.settings.get("native_chat_input") or "").strip()
    if not text:
        raise ValueError("Enter a player action or message first.")
    result = controller.remote_send(
        text,
        intent=str(controller.settings.get("native_chat_intent") or "Auto"),
        speaker_id=str(controller.settings.get("native_chat_speaker_id") or ""),
    )
    return _result("Queued the MPRC chat turn.", remote=result)


def _structured_export(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    path = _path_from_request(request)
    cast = controller._mprc_structured_output_cast()
    controller._queue_mprc_structured_output_export(
        str(path),
        cast,
        controller._mprc_chat_should_offer_choices(),
    )
    return _result("Structured-output export queued.", path=str(path))


def _remote_install(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    controller.settings["remote_server_installed"] = True
    controller.settings["remote_enabled"] = False
    controller._ensure_remote_settings_defaults(installed=True)
    controller.storage.save_settings(controller.settings)
    controller._refresh_remote_controls()
    return _result("Installed MPRC Remote controls. Enable LAN Remote when needed.")


def _remote_regenerate(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    from addons.multi_persona_roleplay.remote_backend import generate_remote_code

    controller.settings["remote_code"] = generate_remote_code()
    controller.settings.pop("remote_token", None)
    controller.storage.save_settings(controller.settings)
    controller._sync_remote_backend_from_settings()
    return _result("Changed the MPRC Remote pairing code.", code=controller.settings["remote_code"])


def _cast(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    action = str(request.get("cast_action") or "refresh")
    device = str(controller.settings.get("chromecast_device_name") or "").strip()
    payload: dict[str, Any] = {"action": action}
    if device:
        payload["device_name"] = device
    result = controller.remote_chromecast_action(payload)
    if not bool(result.get("accepted", False)):
        raise RuntimeError(str(result.get("message") or result.get("error") or "Chromecast action failed."))
    controller._refresh_chromecast_controls()
    return _result(str(result.get("message") or f"Chromecast {action} completed."), cast=result)


def _chat_start(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    controller.session.enabled = True
    controller._mprc_play_active = True
    controller.settings["mprc_play_isolated_active"] = True
    _save(controller)
    from .scenario_play import start_if_enabled
    start_if_enabled(controller)
    return _result("MPRC Play started.")


def _chat_pause(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    controller._stop_mprc_chat_playback()
    controller._mprc_play_active = False
    controller.settings["mprc_play_isolated_active"] = False
    _save(controller)
    return _result("MPRC Play stopped.")


def _chat_restart(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    controller._stop_mprc_chat_playback()
    controller._reset_mprc_chat_history()
    controller._clear_story_memory_preserving_pins()
    controller.session.turn_index = 0
    controller.session.recent_events = []
    _save(controller)
    from .scenario_play import start_if_enabled
    start_if_enabled(controller, restart=True)
    return _result("Restarted the active story play session.")


def _chat_clear(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    _require_confirmation(request)
    controller._reset_mprc_chat_history()
    return _result("Cleared the isolated MPRC chat feed.")


def _chat_float(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    controller._native_window_request = {"workspace": "Play", "mode": "float"}
    return _result("Requested a floating Play workspace.", window_request=controller._native_window_request)


def _set_voice_volume(controller: Any, _request: dict[str, Any]) -> dict[str, Any]:
    volume = max(0, min(100, int(controller.settings.get("mprc_chat_voice_volume", 100) or 100)))
    return _result(f"Voice playback volume is {volume}%.", volume=volume)


def _method(method_name: str, message: str, *, confirmed: bool = False) -> ActionHandler:
    def run(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
        if confirmed:
            _require_confirmation(request)
        method = getattr(controller, method_name)
        method()
        return _result(message)

    return run


def _scenario_builder(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    from .scenario_workbench import handle_native_command
    payload = _raw_payload(request)
    if payload is not None and not isinstance(payload, dict):
        raise ValueError("Invalid scenario editor command")
    handle_native_command(controller, payload or {})
    return _result("Scenarios & Lore editor updated.")


def _story_brief(controller: Any, request: dict[str, Any]) -> dict[str, Any]:
    from .story_brief import get_brief
    payload = _raw_payload(request)
    if payload is not None and not isinstance(payload, dict):
        raise ValueError("Invalid story-refiner command.")
    get_brief(controller).command(payload or {})
    return _result("Story-refiner updated.")


_HANDLERS: dict[str, ActionHandler] = {
    "mprc_story_brief": _story_brief,
    "mprc_scenario_builder": _scenario_builder,
    "mprc_scenario_play_panel": _scenario_builder,
    "mprc_quick_change_avatar": _quick_change_avatar,
    "mprc_quick_save_persona": _quick_save_persona,
    "mprc_quick_import_persona": _import_personas,
    "mprc_quick_export_personas": _export_personas,
    "mprc_quick_duplicate_persona": _duplicate_persona,
    "mprc_quick_edit_persona": _edit_persona,
    "unnamed_qpushbutton_copy": lambda c, r: _debug_copy(c, {**r, "source": "prompt"}),
    "unnamed_qpushbutton_copy#2": lambda c, r: _debug_copy(c, {**r, "source": "visual"}),
    "unnamed_qpushbutton_copy#3": lambda c, r: _debug_copy(c, {**r, "source": "voice"}),
    "unnamed_qpushbutton_copy#4": lambda c, r: _debug_copy(c, {**r, "source": "state"}),
    "mprc_debug_visual_calls_copy": lambda c, r: _debug_copy(c, {**r, "source": "visual_calls"}),
    "mprc_debug_visual_calls_clear": _clear_visual_debug,
    "mprc_debug_clear": _clear_debug,
    "mprc_visual_generate": _method("_generate_visual_reply", "Visual Reply request queued."),
    "mprc_visual_preview": _method("_preview_visual_prompt", "Prepared the Visual Reply prompt preview."),
    "mprc_audiofx_create_test_sounds": _create_test_audio,
    "mprc_audiofx_play_test_tag": _play_test_audio,
    "mprc_audio_create_prompt": _create_audio_prompt,
    "mprc_audio_variation_ambience": lambda c, r: _create_audio_prompt(c, {**r, "variant": "ambience"}),
    "mprc_audio_variation_horror": lambda c, r: _create_audio_prompt(c, {**r, "variant": "horror"}),
    "mprc_audio_variation_calm": lambda c, r: _create_audio_prompt(c, {**r, "variant": "calm"}),
    "mprc_audio_variation_action": lambda c, r: _create_audio_prompt(c, {**r, "variant": "action"}),
    "mprc_audio_copy_prompt": lambda c, r: _copy_text(c, c.settings.get("audio_prompt_output")),
    "mprc_audio_save_prompt": _save_audio_prompt,
    "mprc_audio_save_item_description": _save_audio_item_description,
    "mprc_audio_clear_prompt": _clear_audio_builder,
    "mprc_audio_load_saved": _load_audio_prompt,
    "mprc_audio_delete_saved": _delete_audio_prompt,
    "mprc_audiofx_create": _create_audiofx,
    "mprc_audiofx_import_pack": _import_audio_pack,
    "mprc_audiofx_add_file": _add_audiofx_file,
    "mprc_audiofx_play": _play_audiofx,
    "mprc_audiofx_load": _load_audiofx,
    "mprc_audiofx_delete": _delete_audiofx,
    "mprc_master_story_load": _load_story,
    "mprc_master_story_delete": _delete_story,
    "mprc_story_export_button": _export_story_package,
    "mprc_story_import_button": _import_story_package,
    "mprc_story_export_preview": _preview_story_package,
    "mprc_master_story_generate": _generate_master_story,
    "mprc_master_story_apply": _apply_master_story,
    "mprc_master_story_save": _save_master_story,
    "mprc_master_story_restart": _restart_story,
    "mprc_ar_seed": _method("_seed_ar_state_from_session", "Seeded AR state from the current session."),
    "mprc_ar_fill_profiles": _method("_fill_ar_persona_profiles", "Filled missing AR persona prompts."),
    "mprc_ar_clear": _method("_clear_ar_state", "Cleared AR state.", confirmed=True),
    "mprc_reset_scene": _reset_scene,
    "mprc_export_session": _export_session,
    "mprc_import_session": _import_session,
    "mprc_voice_test": _voice_test,
    "mprc_voice_browse": _voice_browse,
    "mprc_voice_clear": _voice_clear,
    "mprc_character_image_browse": _character_image_browse,
    "mprc_character_image_generate": _character_image_generate,
    "mprc_character_image_clear": _character_image_clear,
    "mprc_add_persona": _add_persona,
    "mprc_duplicate_persona": _duplicate_persona,
    "mprc_delete_persona": _delete_persona,
    "mprc_import_personas": _import_personas,
    "mprc_export_personas": _export_personas,
    "mprc_reset_defaults": _reset_personas,
    "mprc_story_first_run": _story_first_run,
    "mprc_story_load_template": _story_template,
    "mprc_story_export_bundle": _export_story_bundle,
    "mprc_story_import_bundle": _import_story_bundle,
    "mprc_story_status_refresh": _story_status,
    "mprc_story_validate": _story_validate,
    "mprc_story_restore_backup": _story_restore_backup,
    "mprc_story_reset_only": _story_reset_only,
    "mprc_story_demo": _story_demo,
    "mprc_story_test_narrator_voice": _method("_test_narrator_voice_from_status", "Narrator voice test queued."),
    "mprc_story_test_character_voice": _method("_test_selected_character_voice_from_status", "Character voice test queued."),
    "mprc_story_test_visual": _method("_test_visual_reply_from_status", "Visual Reply test queued."),
    "mprc_story_test_audio": _method("_test_audiofx_from_status", "Story sound test queued."),
    "mprc_story_repair_narrator": _method("_repair_choose_narrator", "Selected a narrator for the active story."),
    "mprc_story_repair_voice": _repair_voice,
    "mprc_story_repair_audio": _method("_repair_disable_missing_audiofx", "Disabled missing story sounds."),
    "mprc_story_repair_image": _repair_image,
    "mprc_story_repair_memory": _method("_repair_create_memory_snapshot", "Created a story memory snapshot."),
    "mprc_story_repair_personas": _method("_repair_relink_personas", "Relinked the active story personas."),
    "mprc_story_repair_overrides": _method("_repair_reset_invalid_overrides", "Reset invalid persona overrides.", confirmed=True),
    "mprc_story_preview_next": _story_preview_next,
    "mprc_story_explain_next": _story_explain_next,
    "mprc_story_memory_refresh": _method("_refresh_memory_browser", "Refreshed story memory."),
    "mprc_story_memory_save_pins": _memory_save_pins,
    "mprc_story_memory_delete": _memory_delete,
    "mprc_story_memory_reset_character": _method("_reset_character_memory_only", "Reset character memory.", confirmed=True),
    "mprc_story_memory_reset_story": _method("_reset_story_memory_only", "Reset story memory.", confirmed=True),
    "mprc_story_clear_log": _story_clear_log,
    "mprc_guide_read_all": lambda c, r: _guide_read(c, {**r, "index": "all"}),
    "mprc_guide_stop_speech": _method("_stop_guide_speech", "Stopped guide speech."),
    "mprc_guide_read_quick_start": lambda c, r: _guide_read(c, {**r, "index": 0}),
    "mprc_guide_read_story_health": lambda c, r: _guide_read(c, {**r, "index": 10}),
    "mprc_guide_read_alternativereality_mode": lambda c, r: _guide_read(c, {**r, "index": 11}),
    "mprc_guide_read_master_story_builder": lambda c, r: _guide_read(c, {**r, "index": 12}),
    "mprc_guide_read_visual_reply_story_images": lambda c, r: _guide_read(c, {**r, "index": 13}),
    "mprc_guide_read_audio_tab_and_story_sounds": lambda c, r: _guide_read(c, {**r, "index": 14}),
    "mprc_guide_read_which_tab_to_use": lambda c, r: _guide_read(c, {**r, "index": 15}),
    "mprc_guide_read_troubleshooting": lambda c, r: _guide_read(c, {**r, "index": 16}),
    "mprc_guide_read_default_saved_scenario": lambda c, r: _guide_read(c, {**r, "index": 17}),
    "mprc_load_default_scenario": _load_default_scenario,
    "mprc_chat_advance_scene_button": lambda c, r: _chat_director(c, {**r, "director_action": "advance"}),
    "mprc_chat_summarize_button": lambda c, r: _chat_director(c, {**r, "director_action": "summarize"}),
    "mprc_chat_repair_button": lambda c, r: _chat_director(c, {**r, "director_action": "repair"}),
    "mprc_chat_send_button": _chat_send,
    "mprc_chat_voice_volume_popout_button": _set_voice_volume,
    "mprc_chat_export_structured_output_button": _structured_export,
    "mprc_chat_remote_install_button": _remote_install,
    "mprc_chat_remote_regenerate_token_button": _remote_regenerate,
    "mprc_chat_chromecast_refresh_button": lambda c, r: _cast(c, {**r, "cast_action": "refresh"}),
    "mprc_chat_chromecast_install_button": lambda c, r: _cast(c, {**r, "cast_action": "install"}),
    "mprc_chat_chromecast_start_button": lambda c, r: _cast(c, {**r, "cast_action": "start"}),
    "mprc_chat_chromecast_stop_button": lambda c, r: _cast(c, {**r, "cast_action": "stop"}),
    "mprc_chat_start_button": _chat_start,
    "mprc_chat_pause_button": _chat_pause,
    "mprc_chat_restart_button": _chat_restart,
    "mprc_chat_clear_button": _chat_clear,
    "mprc_chat_float_button": _chat_float,
}


_EXPECTED_ACTIONS = frozenset(str(item[0]) for item in MPRC_ACTION_SPECS)
_MISSING_ACTIONS = _EXPECTED_ACTIONS.difference(_HANDLERS)
_EXTRA_ACTIONS = frozenset(_HANDLERS).difference(_EXPECTED_ACTIONS)
if _MISSING_ACTIONS or _EXTRA_ACTIONS:
    raise RuntimeError(
        "MPRC native action contract is inconsistent: "
        f"missing={sorted(_MISSING_ACTIONS)!r}, extra={sorted(_EXTRA_ACTIONS)!r}"
    )


def dispatch_native_action(
    controller: Any,
    action: str,
    request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Dispatch one reviewed MPRC action without widget discovery or clicks."""

    action_id = str(action or "").strip().lower()
    handler = _HANDLERS.get(action_id)
    if handler is None:
        raise KeyError(f"Unknown MPRC native action: {action_id!r}")
    return dict(handler(controller, dict(request or {})) or _result("Action completed."))


def supported_native_actions() -> frozenset[str]:
    return _EXPECTED_ACTIONS


__all__ = ["dispatch_native_action", "supported_native_actions"]
