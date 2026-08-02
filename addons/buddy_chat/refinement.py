from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any

from .models import BuddyBehaviorProfile
from .setup_models import BuddySetupPreview, GroupBehavior


ALLOWED_PERSONA_FIELDS = {
    "display_name",
    "role",
    "description",
    "system_prompt",
    "speaking_style",
    "behavior",
}
ALLOWED_BEHAVIOR_FIELDS = {
    "helpfulness",
    "warmth",
    "humor",
    "expressiveness",
    "initiative",
    "directness",
    "disagreement",
    "flirtation",
    "reply_length",
    "participation_weight",
}
ALLOWED_GROUP_BEHAVIOR_FIELDS = {
    "max_speakers",
    "allow_buddy_to_buddy",
    "natural_second_speaker_every",
    "forced_buddy_every",
}
ALLOWED_PROMPT_FIELDS = {
    "system_override_prompt",
    "normal_intimacy_prompt",
    "adult_nsfw_prompt",
}
_ALLOWED_TOP_LEVEL_FIELDS = {
    "personas",
    "group_behavior",
    *ALLOWED_PROMPT_FIELDS,
}
_STRING_LIMITS = {
    "display_name": 80,
    "role": 240,
    "description": 1500,
    "system_prompt": 6000,
    "speaking_style": 500,
    "system_override_prompt": 6000,
    "normal_intimacy_prompt": 1600,
    "adult_nsfw_prompt": 2000,
}


@dataclass
class RefinementRequest:
    scope: str
    instruction: str
    preview: BuddySetupPreview
    persona_id: str = ""
    field_name: str = ""


@dataclass
class RefinementPatch:
    personas: dict[str, dict[str, Any]] = field(default_factory=dict)
    group_behavior: dict[str, Any] = field(default_factory=dict)
    prompt_layers: dict[str, str] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not (
            self.personas
            or self.group_behavior
            or self.prompt_layers
        )


@dataclass(frozen=True)
class RefinementDifference:
    path: str
    label: str
    before: str
    after: str


def _safe_persona_payload(persona: Any) -> dict[str, Any]:
    payload = {
        "id": str(persona.id or ""),
        "display_name": str(persona.display_name or ""),
        "role": str(persona.role or ""),
        "description": str(persona.description or ""),
        "system_prompt": str(persona.system_prompt or ""),
        "speaking_style": str(persona.speaking_style or ""),
    }
    if persona.behavior is not None:
        payload["behavior"] = {
            key: value
            for key, value in persona.behavior.to_dict().items()
            if key in ALLOWED_BEHAVIOR_FIELDS
        }
    return payload


def build_refinement_messages(
    request: RefinementRequest,
) -> list[dict[str, str]]:
    scope = str(request.scope or "").strip().lower()
    known_ids = [str(item.id or "") for item in request.preview.personas]
    safe_preview = {
        "personas": [
            _safe_persona_payload(persona)
            for persona in request.preview.personas
        ],
        "group_behavior": {
            "max_speakers": int(
                request.preview.group_behavior.max_speakers
            ),
            "allow_buddy_to_buddy": bool(
                request.preview.group_behavior.allow_buddy_to_buddy
            ),
            "natural_second_speaker_every": int(
                request.preview.group_behavior.natural_second_speaker_every
            ),
            "forced_buddy_every": int(
                request.preview.group_behavior.forced_buddy_every
            ),
        },
        "system_override_prompt": str(
            request.preview.system_override_prompt or ""
        ),
        "normal_intimacy_prompt": str(
            request.preview.normal_intimacy_prompt or ""
        ),
        "adult_nsfw_prompt": str(
            request.preview.adult_nsfw_prompt or ""
        ),
    }
    schema = {
        "personas": [
            {
                "id": "one known id",
                "display_name": "optional string",
                "role": "optional string",
                "description": "optional string",
                "system_prompt": "optional string",
                "speaking_style": "optional string",
                "behavior": {
                    "helpfulness": "optional 0-100 integer",
                    "warmth": "optional 0-100 integer",
                    "humor": "optional 0-100 integer",
                    "expressiveness": "optional 0-100 integer",
                    "initiative": "optional 0-100 integer",
                    "directness": "optional 0-100 integer",
                    "disagreement": "optional 0-100 integer",
                    "flirtation": "optional 0-100 integer",
                    "reply_length": (
                        "optional short, balanced, or detailed"
                    ),
                    "participation_weight": "optional 0-100 integer",
                },
            }
        ],
        "group_behavior": {
            "max_speakers": "optional 1-3 integer",
            "allow_buddy_to_buddy": "optional boolean",
            "natural_second_speaker_every": "optional 0-100 integer",
            "forced_buddy_every": "optional 0-100 integer",
        },
        "system_override_prompt": "optional string",
        "normal_intimacy_prompt": "optional string",
        "adult_nsfw_prompt": "optional string",
    }
    system = (
        "Refine only the requested Buddy Chat fields. Return one JSON object "
        "and no commentary. Use only known persona IDs and only keys from the "
        "provided schema. Do not add provider, credential, voice, avatar, "
        "media-path, or speaker-label protocol fields. Persona IDs must remain "
        "unchanged. All Adult / NSFW personas and participants must be adults."
    )
    user_payload = {
        "scope": scope,
        "persona_id": str(request.persona_id or ""),
        "field_name": str(request.field_name or ""),
        "instruction": str(request.instruction or "").strip()[:2000],
        "known_persona_ids": known_ids,
        "current_preview": safe_preview,
        "allowed_response_schema": schema,
    }
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(user_payload, ensure_ascii=False),
        },
    ]


def _decode_json_object(text: str) -> dict[str, Any] | None:
    value = str(text or "").strip()
    fenced = re.fullmatch(
        r"```(?:json)?\s*(.*?)\s*```",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fenced is not None:
        value = fenced.group(1).strip()
    try:
        payload = json.loads(value)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _clean_string(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip()[: max(1, int(limit))]


def _normalize_behavior(
    payload: Any,
) -> dict[str, int | str] | None:
    if not isinstance(payload, dict):
        return None
    if set(payload) - ALLOWED_BEHAVIOR_FIELDS:
        return None
    normalized: dict[str, int | str] = {}
    for key, value in payload.items():
        profile = BuddyBehaviorProfile.from_dict({key: value})
        normalized[key] = getattr(profile, key)
    return normalized


def _normalize_persona_patch(
    payload: Any,
    known_ids: set[str],
) -> tuple[str, dict[str, Any]] | None:
    if not isinstance(payload, dict):
        return None
    if set(payload) - (ALLOWED_PERSONA_FIELDS | {"id"}):
        return None
    persona_id = str(payload.get("id") or "").strip()
    if persona_id not in known_ids:
        return None
    normalized: dict[str, Any] = {}
    for key, value in payload.items():
        if key == "id":
            continue
        if key == "behavior":
            behavior = _normalize_behavior(value)
            if behavior is None:
                return None
            if behavior:
                normalized[key] = behavior
            continue
        clean = _clean_string(value, _STRING_LIMITS[key])
        if clean is None or (key == "display_name" and not clean):
            return None
        normalized[key] = clean
    return persona_id, normalized


def _normalize_group_behavior(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    if set(payload) - ALLOWED_GROUP_BEHAVIOR_FIELDS:
        return None
    normalized: dict[str, Any] = {}
    for key, value in payload.items():
        if key == "allow_buddy_to_buddy":
            if not isinstance(value, bool):
                return None
            normalized[key] = value
            continue
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            return None
        if key == "max_speakers":
            normalized[key] = max(1, min(3, numeric))
        else:
            normalized[key] = max(0, min(100, numeric))
    return normalized


def _patch_paths(patch: RefinementPatch) -> set[str]:
    paths: set[str] = set()
    for persona_id, values in patch.personas.items():
        for key, value in values.items():
            if key == "behavior" and isinstance(value, dict):
                paths.update(
                    f"{persona_id}.behavior.{behavior_key}"
                    for behavior_key in value
                )
            else:
                paths.add(f"{persona_id}.{key}")
    paths.update(
        f"group_behavior.{key}" for key in patch.group_behavior
    )
    paths.update(patch.prompt_layers)
    return paths


def parse_refinement_result(
    text: str,
    request: RefinementRequest,
) -> RefinementPatch | None:
    payload = _decode_json_object(text)
    if payload is None or set(payload) - _ALLOWED_TOP_LEVEL_FIELDS:
        return None
    scope = str(request.scope or "").strip().lower()
    if scope not in {"group", "persona", "field"}:
        return None
    known_ids = {
        str(persona.id or "").strip()
        for persona in request.preview.personas
        if str(persona.id or "").strip()
    }
    patch = RefinementPatch()
    personas_payload = payload.get("personas", [])
    if not isinstance(personas_payload, list):
        return None
    seen_persona_ids: set[str] = set()
    for item in personas_payload:
        normalized = _normalize_persona_patch(item, known_ids)
        if normalized is None:
            return None
        persona_id, values = normalized
        if persona_id in seen_persona_ids:
            return None
        seen_persona_ids.add(persona_id)
        if scope in {"persona", "field"} and (
            persona_id != str(request.persona_id or "").strip()
        ):
            return None
        if values:
            patch.personas[persona_id] = values

    if "group_behavior" in payload:
        if scope != "group":
            return None
        group_behavior = _normalize_group_behavior(
            payload.get("group_behavior")
        )
        if group_behavior is None:
            return None
        patch.group_behavior = group_behavior

    for key in ALLOWED_PROMPT_FIELDS:
        if key not in payload:
            continue
        if scope != "group":
            return None
        clean = _clean_string(payload.get(key), _STRING_LIMITS[key])
        if clean is None:
            return None
        patch.prompt_layers[key] = clean

    if patch.is_empty():
        return None
    if scope == "field":
        field_name = str(request.field_name or "").strip()
        expected = (
            f"{str(request.persona_id or '').strip()}.{field_name}"
            if request.persona_id
            else field_name
        )
        if not expected or _patch_paths(patch) != {expected}:
            return None
    return patch


def _selected(path: str, selected_fields: set[str] | None) -> bool:
    return selected_fields is None or path in selected_fields


def apply_refinement_patch(
    preview: BuddySetupPreview,
    patch: RefinementPatch,
    selected_fields: set[str] | None = None,
) -> BuddySetupPreview:
    updated = copy.deepcopy(preview)
    selected = (
        {str(item or "").strip() for item in selected_fields}
        if selected_fields is not None
        else None
    )
    for persona in updated.personas:
        values = patch.personas.get(str(persona.id or ""))
        if not values:
            continue
        for key, value in values.items():
            if key == "behavior":
                selected_behavior = {
                    behavior_key: behavior_value
                    for behavior_key, behavior_value in dict(value).items()
                    if _selected(
                        f"{persona.id}.behavior.{behavior_key}",
                        selected,
                    )
                }
                if not selected_behavior:
                    continue
                current = persona.behavior or BuddyBehaviorProfile()
                behavior_payload = current.to_dict()
                behavior_payload.update(selected_behavior)
                persona.behavior = BuddyBehaviorProfile.from_dict(
                    behavior_payload
                )
                continue
            path = f"{persona.id}.{key}"
            if _selected(path, selected):
                setattr(persona, key, value)

    group_payload = {
        "max_speakers": updated.group_behavior.max_speakers,
        "allow_buddy_to_buddy": (
            updated.group_behavior.allow_buddy_to_buddy
        ),
        "natural_second_speaker_every": (
            updated.group_behavior.natural_second_speaker_every
        ),
        "forced_buddy_every": (
            updated.group_behavior.forced_buddy_every
        ),
    }
    for key, value in patch.group_behavior.items():
        if _selected(f"group_behavior.{key}", selected):
            group_payload[key] = value
    updated.group_behavior = GroupBehavior(**group_payload)

    for key, value in patch.prompt_layers.items():
        if _selected(key, selected):
            setattr(updated, key, value)
    return updated


def refinement_differences(
    before: BuddySetupPreview,
    after: BuddySetupPreview,
) -> list[RefinementDifference]:
    differences: list[RefinementDifference] = []
    before_by_id = {persona.id: persona for persona in before.personas}
    for after_persona in after.personas:
        before_persona = before_by_id.get(after_persona.id)
        if before_persona is None:
            continue
        for key in ALLOWED_PERSONA_FIELDS - {"behavior"}:
            old_value = getattr(before_persona, key)
            new_value = getattr(after_persona, key)
            if old_value != new_value:
                differences.append(
                    RefinementDifference(
                        f"{after_persona.id}.{key}",
                        f"{after_persona.display_name}: "
                        f"{key.replace('_', ' ').title()}",
                        str(old_value or ""),
                        str(new_value or ""),
                    )
                )
        old_behavior = (
            before_persona.behavior or BuddyBehaviorProfile()
        )
        new_behavior = after_persona.behavior or BuddyBehaviorProfile()
        for key in ALLOWED_BEHAVIOR_FIELDS:
            old_value = getattr(old_behavior, key)
            new_value = getattr(new_behavior, key)
            if old_value != new_value:
                differences.append(
                    RefinementDifference(
                        f"{after_persona.id}.behavior.{key}",
                        f"{after_persona.display_name}: "
                        f"{key.replace('_', ' ').title()}",
                        str(old_value),
                        str(new_value),
                    )
                )
    for key in ALLOWED_GROUP_BEHAVIOR_FIELDS:
        old_value = getattr(before.group_behavior, key)
        new_value = getattr(after.group_behavior, key)
        if old_value != new_value:
            differences.append(
                RefinementDifference(
                    f"group_behavior.{key}",
                    key.replace("_", " ").title(),
                    str(old_value),
                    str(new_value),
                )
            )
    for key in ALLOWED_PROMPT_FIELDS:
        old_value = getattr(before, key)
        new_value = getattr(after, key)
        if old_value != new_value:
            differences.append(
                RefinementDifference(
                    key,
                    key.replace("_", " ").title(),
                    str(old_value or ""),
                    str(new_value or ""),
                )
            )
    return differences


__all__ = [
    "ALLOWED_BEHAVIOR_FIELDS",
    "ALLOWED_GROUP_BEHAVIOR_FIELDS",
    "ALLOWED_PERSONA_FIELDS",
    "ALLOWED_PROMPT_FIELDS",
    "RefinementDifference",
    "RefinementPatch",
    "RefinementRequest",
    "apply_refinement_patch",
    "build_refinement_messages",
    "parse_refinement_result",
    "refinement_differences",
]
