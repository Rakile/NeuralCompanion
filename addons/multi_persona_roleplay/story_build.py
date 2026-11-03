"""Draft-only staged authoring, reusing the existing Master Story contract."""
from __future__ import annotations

import copy
import json
import re
from typing import Any

from .scenario_models import decode_scenario_json, validate_story_extension


def decode_response(text: str) -> dict:
    fenced = re.fullmatch(r"```(?:json)?[ \t]*\r?\n(.*)\r?\n```", text.strip(), re.DOTALL | re.IGNORECASE)
    return decode_scenario_json(fenced.group(1) if fenced else text)


def build_master(backend: Any, source: dict, brief: dict, provider: str, model: str, cancel: Any) -> dict:
    c = backend.controller
    fields = brief["fields"]
    prompt = fields["master_story_prompt"]
    constraints = {**source["constraints"], "sfw_mode": source["sfw"]}
    context = {key: fields["master_story_" + key] for key in ("scene_title", "location", "time_of_day", "mood")}
    snapshot = {
        "prompt": prompt, "safe_prompt": c._master_story_safety_normalized_prompt(prompt, sfw=source["sfw"]),
        "visual_direction": fields["master_story_visual_direction"], "constraints": constraints,
        "generation_notes": c._master_story_generation_constraints_text(constraints),
        "content_safety": c._master_story_content_safety_payload(source["sfw"]),
        "mode": source["mode"], "scene_context": context,
        "roster": copy.deepcopy(source["existing_cast"]), "include_scenario": False, "model": model,
    }
    count = source["constraints"]["native_personas_to_draft"]
    messages: list[dict[str, str]] = []

    def request(params: dict, extra: dict) -> str:
        nonlocal messages
        messages = copy.deepcopy(params["messages"])
        if count > 0:
            # The legacy generator allows a smaller cast. Complete builds have
            # already approved an exact cast plan, so use a consistent contract.
            messages[0]["content"] = messages[0]["content"].replace(
                "Follow the requested persona count exactly when possible, ",
                "Follow the requested persona count exactly, ").replace(
                "and respect the configured character creation limit.",
                "and leave the new-character creation limit to Apply Draft.")
            data = json.loads(messages[1]["content"])
            data["generation_notes"] = data["generation_notes"].replace(
                " when possible.", ".").replace(
                "If you cannot safely reach that count, return the closest complete cast and note the reason in the summary instead of adding weak filler.",
                "Return one complete persona object for each approved cast member.")
            data["persona_count_contract"] = {
                "requested_story_native_personas": count,
                "exact_personas_array_length": count,
                "include_reused_characters_in_personas_array": True,
                "creation_limit_is_enforced_only_when_applying": True,
            }
            data["approved_cast_plan"] = copy.deepcopy(brief["cast"])
            data["task"] += (
                f" Return exactly {count} complete entries in personas, matching the approved cast plan. "
                "Mentioning a character in summary or persona_overrides does not count. "
                "The new-character creation limit must not shorten this draft.")
            messages[1]["content"] = json.dumps(data, ensure_ascii=False)
        return backend.complete_messages(messages, provider, model, cancel)

    text = c._generate_master_story_payload(snapshot, request=request)
    for attempt in range(2):
        raw = decode_response(text)
        raw, errors = c._canonical_master_story_payload(raw)
        raw, structured_errors = c._structured_master_story_validation_payload(raw)
        errors += structured_errors + c._validate_master_story_payload(raw)
        actual = len(raw.get("personas", []))
        mismatch = count > 0 and actual != count
        if mismatch:
            count_error = f"Expected {count} cast profiles in the Master draft; model returned {actual}."
            errors.append(count_error)
        if not errors:
            break
        if not mismatch or attempt == 1:
            raise ValueError(" ".join(errors))
        if cancel.cancelled:
            raise ValueError("Cancelled.")
        with c._state_lock:
            if cancel.cancelled:
                raise ValueError("Cancelled.")
            backend.status = (
                f"Step 2 of 3: model returned {actual} of {count} cast profiles. "
                "Correcting the cast (one automatic attempt)...")
        repair = messages + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": (
                "Correct the previous draft and return the complete canonical story JSON, not a patch. "
                + " ".join(errors) +
                " Use every approved cast member. Preserve the story and valid profiles; add missing profiles "
                "or remove only unplanned extras. Repair all persona ID references. "
                "Do not change the requested count, mode or SFW setting.")},
        ]
        text = backend.complete_messages(repair, provider, model, cancel)
    raw["content_safety"] = snapshot["content_safety"]
    raw["avatar_visual_direction"] = snapshot["visual_direction"]
    raw["generation"] = {
        "source": "master_story_creator", "requested_story_native_personas": count,
        **constraints,
    }
    if not constraints["use_existing_personas"]:
        raw.pop("persona_overrides", None)
    result = c._normalize_master_story_payload(raw, mode_override=source["mode"])
    return c._apply_master_story_creator_context(result, context, mode=source["mode"])


def build_scenarios(backend: Any, source: dict, brief: dict, master: dict,
                    provider: str, model: str, cancel: Any) -> dict:
    from .scenario_demo import generation_guidance, lighthouse_example
    messages = [
        {"role": "system", "content": "Create story-specific scenes and lore for the supplied campaign. "
         "Return only the scenario_extension object as JSON. " + generation_guidance() +
         " Create multiple connected scenes and relevant lore entries covering characters, places, factions and history. "
         "Use the actual Master cast IDs. Preserve the opening scene, mode, SFW setting and player agency. "
         "The example is a schema reference only: replace ALL example story content. "
         "Optional variables, events and choices may be empty when unnecessary. Do not execute anything."},
        {"role": "user", "content": json.dumps({"refined_story": brief, "master_draft": master,
         "sfw": source["sfw"], "schema_example": lighthouse_example()}, ensure_ascii=False)},
    ]
    extension = decode_response(backend.complete_messages(messages, provider, model, cancel))
    result = {**copy.deepcopy(master), "scenario_extension": extension}
    validate_story_extension(result)
    if not extension.get("scenes") or not any(book.get("entries") for book in extension.get("lorebooks", [])):
        raise ValueError("The model returned no scenes or lore entries. Retry this stage.")
    return result
