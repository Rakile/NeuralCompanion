"""Strict, addon-local authored scenario definitions. No Qt or runtime imports."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeAlias

JSONValue: TypeAlias = (
    None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
)
VariableValue: TypeAlias = bool | int | float | str
MAX_BYTES = 5 * 1024 * 1024
ACTIONS = frozenset(
    {"mprc.scenario.set_state", "mprc.scenario.change_scene", "mprc.story.narrate"}
)
TRIGGERS = (
    "session_started",
    "user_turn_completed",
    "choice_clicked",
    "action_completed",
)


class ScenarioValidationError(ValueError):
    pass


class UnsupportedScenarioVersion(ScenarioValidationError):
    pass


def _bad(path: str, message: str) -> None:
    raise ScenarioValidationError(f"{path}: {message}")


def decode_scenario_json(text: str) -> dict[str, JSONValue]:
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_BYTES:
        _bad("scenario", "JSON must be no larger than 5 MiB")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _bad(key, "duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(
            text,
            object_pairs_hook=pairs,
            parse_constant=lambda value: _bad("JSON", f"non-finite {value}"),
        )
    except (ValueError, RecursionError) as exc:
        raise ScenarioValidationError(str(exc)) from exc
    if not isinstance(value, dict):
        _bad("scenario", "expected an object")
    return value


def _obj(value, keys: set[str], path: str) -> dict:
    if not isinstance(value, dict):
        _bad(path, "expected an object")
    if set(value) != keys:
        _bad(path, f"fields must be {', '.join(sorted(keys))}")
    return value


def _text(value, path: str, limit: int = 16384, *, required: bool = False) -> str:
    if (
        not isinstance(value, str)
        or len(value) > limit
        or (required and not value.strip())
    ):
        _bad(
            path,
            f"expected {'non-empty ' if required else ''}text up to {limit} characters",
        )
    return value


def _id(value, path: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", value):
        _bad(path, "invalid ID")
    return value


def _bool(value, path: str) -> bool:
    if type(value) is not bool:
        _bad(path, "expected true or false")
    return value


def _integer(value, path: str, minimum: int = -1000000, maximum: int = 1000000) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _bad(path, f"expected integer {minimum}..{maximum}")
    return value


def _list(value, path: str, limit: int) -> list:
    if not isinstance(value, list) or len(value) > limit:
        _bad(path, f"expected at most {limit} items")
    return value


def validate_variable(value: object, variable: Mapping[str, object]) -> VariableValue:
    kind = variable["type"]
    path = f"variable {variable['id']}"
    valid = (
        (kind == "boolean" and type(value) is bool)
        or (kind == "integer" and type(value) is int)
        or (kind == "number" and type(value) in (int, float) and math.isfinite(value))
        or (kind == "string" and isinstance(value, str) and len(value) <= 4096)
    )
    if not valid:
        _bad(path, f"expected {kind}")
    if variable.get("enum") and not any(
        type(value) is type(item) and value == item for item in variable["enum"]
    ):
        _bad(path, "value is outside the allowed options")
    return value


@dataclass(frozen=True)
class ScenarioDefinition:
    """Immutable serialized snapshot; payload copies never alias the definition."""

    id: str
    revision: int
    enabled: bool
    opening: str
    instructions: str
    initial_scene_id: str
    _json: str

    def payload(self) -> dict[str, JSONValue]:
        return json.loads(self._json)


def scenario_to_dict(definition: ScenarioDefinition) -> dict[str, JSONValue]:
    return definition.payload()


def validate_condition(
    condition: object,
    variables: Mapping[str, dict],
    *,
    depth: int = 0,
    count: list[int] | None = None,
) -> None:
    if condition is None:
        return
    count = [0] if count is None else count
    count[0] += 1
    if depth > 8 or count[0] > 64:
        _bad("condition", "condition tree is too large")
    if not isinstance(condition, dict):
        _bad("condition", "expected a comparison or all/any group")
    op = condition.get("op")
    if op in ("all", "any"):
        _obj(condition, {"op", "children"}, "condition")
        children = _list(condition["children"], "condition.children", 64)
        if not children:
            _bad("condition", "empty groups are not allowed")
        for child in children:
            if child is None:
                _bad("condition", "empty child is not allowed")
            validate_condition(child, variables, depth=depth + 1, count=count)
    else:
        _obj(condition, {"op", "variable_id", "value"}, "condition")
        var = (
            variables.get(condition["variable_id"])
            if isinstance(condition["variable_id"], str)
            else None
        )
        if var is None:
            _bad("condition", "unknown variable")
        if op not in ("eq", "ne", "lt", "le", "gt", "ge"):
            _bad("condition", "unsupported comparison")
        if op not in ("eq", "ne") and var["type"] not in ("integer", "number"):
            _bad("condition", "ordered comparison requires a number")
        validate_variable(condition["value"], var)


def validate_action(
    action_id: str, arguments: object, payload: Mapping[str, object]
) -> None:
    if (
        not isinstance(action_id, str)
        or action_id not in ACTIONS
        or action_id not in payload["allowed_actions"]
    ):
        _bad("action", "action is not allowed")
    if action_id == "mprc.scenario.set_state":
        args = _obj(arguments, {"variable_id", "value"}, "arguments")
        var = next(
            (v for v in payload["variables"] if v["id"] == args["variable_id"]), None
        )
        if var is None:
            _bad("arguments.variable_id", "unknown variable")
        validate_variable(args["value"], var)
    elif action_id == "mprc.scenario.change_scene":
        args = _obj(arguments, {"scene_id"}, "arguments")
        if not isinstance(args["scene_id"], str) or args["scene_id"] not in {
            s["id"] for s in payload["scenes"]
        }:
            _bad("arguments.scene_id", "unknown scene")
    else:
        args = _obj(arguments, {"text"}, "arguments")
        _text(args["text"], "arguments.text", required=True)


def parse_scenario(
    value: object, *, persona_ids: frozenset[str] = frozenset()
) -> ScenarioDefinition:
    if not isinstance(value, dict):
        _bad("scenario_extension", "expected an object")
    version = value.get("schema_version")
    if type(version) is not int:
        _bad("schema_version", "expected integer")
    if version != 1:
        raise UnsupportedScenarioVersion(f"Unsupported scenario version: {version}")
    # JSON round-trip also rejects non-JSON inputs and prevents aliasing.
    try:
        raw = decode_scenario_json(
            json.dumps(value, ensure_ascii=False, allow_nan=False)
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise ScenarioValidationError(str(exc)) from exc
    _obj(
        raw,
        {
            "schema_version",
            "id",
            "revision",
            "enabled",
            "opening",
            "instructions",
            "initial_scene_id",
            "roles",
            "scenes",
            "lorebooks",
            "variables",
            "allowed_actions",
            "events",
            "choices",
        },
        "scenario",
    )
    _id(raw["id"], "id")
    _integer(raw["revision"], "revision", 1, 2147483647)
    _bool(raw["enabled"], "enabled")
    _text(raw["opening"], "opening")
    _text(raw["instructions"], "instructions")
    ids: set[str] = set()

    def record(item, keys, path):
        _obj(item, set(keys.split()), path)
        identifier = _id(item["id"], path + ".id")
        if identifier in ids:
            _bad(path, "duplicate content ID")
        ids.add(identifier)

    scenes = _list(raw["scenes"], "scenes", 64)
    for scene in scenes:
        record(scene, "id title description location effects", "scene")
        _text(scene["title"], "scene.title", 240, required=True)
        _text(scene["description"], "scene.description")
        _text(scene["location"], "scene.location", 240)
    scene_ids = {s["id"] for s in scenes}
    if (
        not isinstance(raw["initial_scene_id"], str)
        or raw["initial_scene_id"] not in scene_ids
    ):
        _bad("initial_scene_id", "unknown scene")
    variables = {}
    for var in _list(raw["variables"], "variables", 64):
        record(var, "id type initial enum", "variable")
        if var["type"] not in ("boolean", "integer", "number", "string"):
            _bad("variable.type", "unsupported type")
        _list(var["enum"], "variable.enum", 64)
        for item in var["enum"]:
            validate_variable(item, {**var, "enum": []})
        validate_variable(var["initial"], var)
        variables[var["id"]] = var
    for role in _list(raw["roles"], "roles", 64):
        record(role, "id persona_id instructions", "role")
        _id(role["persona_id"], "role.persona_id")
        if role["persona_id"] not in persona_ids:
            _bad("role.persona_id", "unknown story persona")
        _text(role["instructions"], "role.instructions")
    actions = _list(raw["allowed_actions"], "allowed_actions", 3)
    if any(not isinstance(a, str) or a not in ACTIONS for a in actions) or len(
        set(actions)
    ) != len(actions):
        _bad("allowed_actions", "unknown or duplicated action")

    def effect(item):
        record(item, "id action_id arguments", "effect")
        if not isinstance(item["action_id"], str):
            _bad("effect.action_id", "expected action ID")
        validate_action(item["action_id"], item["arguments"], raw)

    for scene in scenes:
        for item in _list(scene["effects"], "scene.effects", 16):
            effect(item)
    entry_count = 0
    for book in _list(raw["lorebooks"], "lorebooks", 32):
        record(book, "id title enabled entries", "lorebook")
        _text(book["title"], "lorebook.title", 240, required=True)
        _bool(book["enabled"], "lorebook.enabled")
        for entry in _list(book["entries"], "entries", 512):
            entry_count += 1
            if entry_count > 512:
                _bad("entries", "at most 512 total entries")
            record(
                entry,
                "id title text keywords enabled pinned priority order scene_ids",
                "entry",
            )
            _text(entry["title"], "entry.title", 240)
            _text(entry["text"], "entry.text", required=True)
            for key in ("enabled", "pinned"):
                _bool(entry[key], f"entry.{key}")
            for key in ("priority", "order"):
                _integer(entry[key], f"entry.{key}")
            for keyword in _list(entry["keywords"], "keywords", 32):
                _text(keyword, "keyword", 120, required=True)
            for scene_id in _list(entry["scene_ids"], "scene_ids", 64):
                if not isinstance(scene_id, str) or scene_id not in scene_ids:
                    _bad("entry.scene_ids", "unknown scene")
    for event in _list(raw["events"], "events", 128):
        record(event, "id title trigger condition effects once", "event")
        _text(event["title"], "event.title", 240)
        if event["trigger"] not in TRIGGERS:
            _bad("event.trigger", "unknown trigger")
        _bool(event["once"], "event.once")
        validate_condition(event["condition"], variables)
        for item in _list(event["effects"], "event.effects", 16):
            effect(item)
    for choice in _list(raw["choices"], "choices", 64):
        record(choice, "id label condition effect", "choice")
        _text(choice["label"], "choice.label", 240, required=True)
        validate_condition(choice["condition"], variables)
        effect(choice["effect"])
    return ScenarioDefinition(
        raw["id"],
        raw["revision"],
        raw["enabled"],
        raw["opening"],
        raw["instructions"],
        raw["initial_scene_id"],
        json.dumps(raw, ensure_ascii=False, allow_nan=False),
    )


def validate_story_extension(story: Mapping[str, object]) -> ScenarioDefinition | None:
    if "scenario_extension" not in story:
        return None
    personas = story.get("personas", [])
    if not isinstance(personas, list):
        _bad("personas", "expected a list")
    persona_ids = frozenset(
        p["id"]
        for p in personas
        if isinstance(p, dict) and isinstance(p.get("id"), str)
    )
    return parse_scenario(story["scenario_extension"], persona_ids=persona_ids)
