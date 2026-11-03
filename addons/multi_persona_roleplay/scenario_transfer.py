"""Portable authored definitions; execution checkpoints never travel in a story."""

from __future__ import annotations
from collections.abc import Mapping
from uuid import uuid4
from .scenario_models import (
    ScenarioDefinition,
    MAX_BYTES,
    ScenarioValidationError,
    parse_scenario,
    validate_story_extension,
)


def export_extension(definition: ScenarioDefinition) -> dict:
    return definition.payload()


def preflight_story_extension(
    story: Mapping, *, encoded_size: int = 0
) -> ScenarioDefinition | None:
    if encoded_size > MAX_BYTES:
        raise ScenarioValidationError("Scenario definition exceeds 5 MiB")
    return validate_story_extension(story)


def clone_story_extension(
    story: dict,
    persona_id_map: Mapping[str, str] | None = None,
    *,
    content_id_map: dict[str, str] | None = None,
) -> dict:
    """Call before importing mutations; never includes progress from the exporter."""
    import copy

    result = copy.deepcopy(story)
    definition = preflight_story_extension(result)
    if definition is not None:
        ids = content_id_map if content_id_map is not None else {}
        identifier = ids.setdefault(definition.id, uuid4().hex)
        result["scenario_extension"] = remap_extension(
            definition,
            persona_id_map=persona_id_map or {},
            new_extension_id=identifier,
            content_id_map=ids,
        ).payload()
    return result


def preflight_scenario_apply(
    controller, story: dict, plan: dict, *, prospective_personas=None
) -> None:
    """Validate role admission before the legacy apply path mutates personas or memory."""
    from .models import PersonaConfig, normalize_persona_id
    from .scenario_storage import ScenarioRepository

    definition = preflight_story_extension(story)
    if definition is None:
        return
    ScenarioRepository(
        controller.context.storage.resolve("scenario_progress")
    ).check_definition_revision(story["id"], definition)
    required = {r["persona_id"] for r in definition.payload()["roles"]}
    if not required:
        return
    auto_create = bool(
        plan.get(
            "auto_create", controller.settings.get("master_story_auto_create", True)
        )
    )
    allow_exceed = bool(
        plan.get(
            "allow_exceed_max_created_characters",
            controller._master_story_allow_exceed_max_created_characters(),
        )
    )
    maximum = controller._control_int_value(
        "master_story_max_created_characters", 8, 1, 40
    )
    created = 0
    admitted = set()
    roster = (
        controller.personas if prospective_personas is None else prospective_personas
    )
    choices = plan.get("persona_choices") or {}
    rows = plan.get("persona_choices_by_row") or {}
    actions = plan.get("persona_actions_by_row") or {}
    for row, item in enumerate(story.get("personas", [])):
        identifier = normalize_persona_id(
            item.get("id") or item.get("display_name") or ""
        )
        choice = str(rows.get(str(row), choices.get(identifier, "")) or "").strip()
        action = str(actions.get(str(row), "") or "").strip()
        create = action == "__create__" or choice == "__create__"
        match = None if create else next((p for p in roster if p.id == choice), None)
        if not create and match is None and choice:
            continue
        if match is None and not create:
            match = controller._find_persona_for_story(item, personas=roster)
        if match is not None:
            admitted.add(identifier)
            continue
        if not (auto_create or create):
            continue
        narrator = controller._persona_looks_like_narrator(
            PersonaConfig.from_dict(item)
        )
        if not narrator and not allow_exceed and created >= maximum:
            continue
        if not narrator:
            created += 1
        admitted.add(identifier)
    if required - admitted:
        raise ScenarioValidationError(
            "Scenario roles cannot be linked with this Apply plan: "
            + ", ".join(sorted(required - admitted))
            + ". Allow creation/reuse or remove the role before applying."
        )


def remap_extension(
    definition: ScenarioDefinition,
    *,
    persona_id_map: Mapping[str, str],
    new_extension_id: str,
    content_id_map: dict[str, str] | None = None,
) -> ScenarioDefinition:
    raw = definition.payload()
    ids = content_id_map if content_id_map is not None else {}

    def collect(value):
        if isinstance(value, dict):
            if "id" in value:
                ids.setdefault(value["id"], uuid4().hex)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(raw)
    ids[raw["id"]] = new_extension_id

    def rewrite(value):
        if isinstance(value, dict):
            for key, child in list(value.items()):
                if key == "persona_id":
                    value[key] = persona_id_map.get(child, child)
                elif key in ("id", "initial_scene_id", "scene_id", "variable_id"):
                    value[key] = ids.get(child, child)
                elif key == "scene_ids":
                    value[key] = [ids.get(item, item) for item in child]
                else:
                    rewrite(child)
        elif isinstance(value, list):
            for child in value:
                rewrite(child)

    rewrite(raw)
    raw["revision"] = 1
    return parse_scenario(
        raw, persona_ids=frozenset(r["persona_id"] for r in raw["roles"])
    )
