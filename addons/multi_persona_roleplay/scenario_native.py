"""Detached Master Story editing and discoverable typed refinement targets."""

from __future__ import annotations
import copy
from dataclasses import dataclass
from uuid import uuid4
from .scenario_models import (
    JSONValue,
    ACTIONS,
    TRIGGERS,
    validate_story_extension,
    ScenarioValidationError,
)


@dataclass(frozen=True)
class DraftSnapshot:
    story_id: str
    revision: int
    story: dict[str, JSONValue]
    options: dict[str, JSONValue]


@dataclass(frozen=True)
class RefinementTarget:
    id: str
    label: str
    value: JSONValue
    value_schema: dict[str, JSONValue]
    help_text: str


HELP = {
    "opening": "Text narrated once when a new scenario starts. Resuming does not repeat it.",
    "instructions": "Additional story direction. This does not grant permission to execute actions.",
    "initial_scene_id": "The declared scene where a newly started scenario begins.",
    "keywords": "One keyword or phrase per line. Whole words match; art does not match party.",
    "scene_ids": "One scene ID per line. Leave empty to make this lore eligible in every scene.",
    "pinned": "Include this fact even without a keyword match, if it fits the context budget.",
    "priority": "Higher values are selected first when equally relevant lore competes for space.",
    "order": "Display order after lore selection. Lower values appear first.",
    "once": "Run this event only once per scenario session, after all its effects succeed.",
    "trigger": "The event that evaluates this rule. User turn completed means its reply was committed.",
    "allowed_actions": "One supported action ID per line. Only these actions may run in this story.",
    "enabled": "Enable this item. Scenario changes remain draft-only until applied.",
    "condition": "A typed condition evaluated against scenario variables. Empty means always eligible.",
    "effect": "A validated action, never code. It runs only through the scenario dispatcher.",
    "role": "Story-local role description; applying this editor does not rewrite the original persona.",
    "master_story_include_scenario": "Include authored scenes, lorebooks and choices in the next Master Story generation. Uses your current main model.",
    "master_story_scenario_context_limit": "Your main model context capacity in tokens. Set 0 if unknown: lore is then omitted. Estimates include the full request and reserve space for the reply.",
    "master_story_scenario_reply_reserve": "Tokens to keep available for the reply before selecting lore. The default is 1024. This does not change the main model settings.",
}


def empty_extension() -> dict:
    return {
        "schema_version": 1,
        "id": uuid4().hex,
        "revision": 1,
        "enabled": False,
        "opening": "",
        "instructions": "",
        "initial_scene_id": "scene_start",
        "roles": [],
        "scenes": [
            {
                "id": "scene_start",
                "title": "Opening scene",
                "description": "",
                "location": "",
                "effects": [],
            }
        ],
        "lorebooks": [],
        "variables": [],
        "allowed_actions": sorted(ACTIONS),
        "events": [],
        "choices": [],
    }


def _schema(value, key: str, story: dict) -> dict:
    from .native_contract import MPRC_CONTROL_SPECS

    ext = story.get("scenario_extension", {})
    enums = {
        "trigger": list(TRIGGERS),
        "action_id": sorted(ACTIONS),
        "type": ["boolean", "integer", "number", "string"],
        "op": ["eq", "ne", "lt", "le", "gt", "ge", "all", "any"],
        "initial_scene_id": [s["id"] for s in ext.get("scenes", [])],
        "scene_id": [s["id"] for s in ext.get("scenes", [])],
        "variable_id": [v["id"] for v in ext.get("variables", [])],
        "persona_id": [p["id"] for p in story.get("personas", [])],
    }
    for role_key in ("active_persona_id", "current_speaker_id", "narrator_persona_id"):
        enums[role_key] = [""] + [p["id"] for p in story.get("personas", [])]
    kind = (
        "boolean"
        if type(value) is bool
        else "integer"
        if type(value) is int
        else "number"
        if type(value) is float
        else "array"
        if isinstance(value, list)
        else "object"
        if isinstance(value, dict)
        else "string"
    )
    result = {"type": kind}
    if key in enums:
        result["enum"] = enums[key]
    if key.startswith("master_story_"):
        spec = next(
            (
                s
                for s in MPRC_CONTROL_SPECS
                if s[0] in ("mprc_" + key, "mprc_" + key + "_combo")
            ),
            None,
        )
        if spec and spec[5]:
            result["enum"] = [option[0] for option in spec[5]]
    return result


def refinement_targets(snapshot: DraftSnapshot) -> tuple[RefinementTarget, ...]:
    result = []
    forbidden = {
        "id",
        "revision",
        "schema_version",
        "updated_at",
        "character_image_path",
        "sample_path",
        "backend",
        "provider",
        "model",
        "generation",
        "selected_narrator_id",
    }

    def walk(value, path, label):
        if isinstance(value, dict):
            if path:
                result.append(
                    RefinementTarget(
                        path,
                        label + " (whole section)",
                        copy.deepcopy(value),
                        {"type": "object"},
                        "Propose changes to this section. Review before applying; no live story action is executed.",
                    )
                )
            for key, child in value.items():
                if key in forbidden or key.endswith("_path"):
                    continue
                walk(child, path + "/" + key, label + " / " + key.replace("_", " "))
        elif isinstance(value, list) and any(isinstance(v, dict) for v in value):
            result.append(
                RefinementTarget(
                    path,
                    label + " (whole collection)",
                    copy.deepcopy(value),
                    {"type": "array"},
                    "Refine this collection while preserving existing record IDs. Review before applying.",
                )
            )
            for index, child in enumerate(value):
                walk(
                    child,
                    path + "/" + str(index),
                    label
                    + " / "
                    + str(
                        child.get("title")
                        or child.get("label")
                        or child.get("id")
                        or index
                    ),
                )
        elif value is not None:
            key = path.rsplit("/", 1)[-1]
            help_text = HELP.get(
                key,
                f"Edit {key.replace('_', ' ')} in this story draft. Refine uses the current main LLM; Apply accepts the preview without running an action.",
            )
            result.append(
                RefinementTarget(
                    path,
                    label,
                    copy.deepcopy(value),
                    _schema(value, key, snapshot.story),
                    help_text,
                )
            )

    walk(snapshot.story, "/story", "Story")
    walk(snapshot.options, "/options", "Builder options")
    return tuple(result)


def _container(root, parts):
    current = root
    for part in parts:
        current = current[int(part)] if isinstance(current, list) else current[part]
    return current


class ScenarioDraftEditor:
    def __init__(self, snapshot: DraftSnapshot):
        self._snapshot = copy.deepcopy(snapshot)

    def snapshot(self) -> DraftSnapshot:
        return copy.deepcopy(self._snapshot)

    def validate(self):
        return validate_story_extension(self._snapshot.story)

    def _accept(self, story: dict, options: dict | None = None) -> DraftSnapshot:
        self._snapshot = DraftSnapshot(
            self._snapshot.story_id,
            self._snapshot.revision + 1,
            story,
            copy.deepcopy(self._snapshot.options if options is None else options),
        )
        return self.snapshot()

    def set_value(self, target: str, value: JSONValue) -> DraftSnapshot:
        selected = next(
            (t for t in refinement_targets(self._snapshot) if t.id == target), None
        )
        if selected is None:
            raise ScenarioValidationError("Unknown or protected draft field")
        schema = selected.value_schema
        kind = schema["type"]
        valid = {
            "boolean": type(value) is bool,
            "integer": type(value) is int,
            "number": type(value) in (int, float),
            "string": isinstance(value, str),
            "array": isinstance(value, list),
            "object": isinstance(value, dict),
        }[kind]
        if not valid or ("enum" in schema and value not in schema["enum"]):
            raise ScenarioValidationError(
                "Value does not match this field type or available options"
            )
        root = {
            "story": copy.deepcopy(self._snapshot.story),
            "options": copy.deepcopy(self._snapshot.options),
        }
        parts = target.strip("/").split("/")
        parent = _container(root, parts[:-1])
        key = int(parts[-1]) if isinstance(parent, list) else parts[-1]
        parent[key] = copy.deepcopy(value)
        return self._accept(root["story"], root["options"])

    def _collection(self, story, kind, parent_id=None):
        ext = story.setdefault("scenario_extension", empty_extension())
        if kind in ("scenes", "lorebooks", "variables", "events", "choices", "roles"):
            return ext[kind]
        parents = (
            ext["lorebooks"]
            if kind == "entries"
            else ext["scenes"] + ext["events"]
            if kind == "effects"
            else []
        )
        parent = next((p for p in parents if p["id"] == parent_id), None)
        if parent is None:
            raise ScenarioValidationError("Select a parent book, scene or event first")
        return parent[kind]

    def create(self, kind: str, parent_id: str | None = None) -> DraftSnapshot:
        story = copy.deepcopy(self._snapshot.story)
        collection = self._collection(story, kind, parent_id)
        identifier = uuid4().hex
        effect = {
            "id": uuid4().hex,
            "action_id": "mprc.story.narrate",
            "arguments": {"text": "Describe the next moment."},
        }
        templates = {
            "scenes": {
                "title": "New scene",
                "description": "",
                "location": "",
                "effects": [],
            },
            "lorebooks": {"title": "New lorebook", "enabled": True, "entries": []},
            "entries": {
                "title": "New fact",
                "text": "Write a story fact here.",
                "keywords": [],
                "enabled": True,
                "pinned": False,
                "priority": 0,
                "order": len(collection),
                "scene_ids": [],
            },
            "variables": {"type": "boolean", "initial": False, "enum": []},
            "events": {
                "title": "New event",
                "trigger": "choice_clicked",
                "condition": None,
                "effects": [],
                "once": True,
            },
            "choices": {"label": "New choice", "condition": None, "effect": effect},
            "roles": {
                "persona_id": next((p["id"] for p in story.get("personas", [])), ""),
                "instructions": "",
            },
            "effects": effect,
        }
        if kind not in templates:
            raise ScenarioValidationError("Unknown record kind")
        collection.append({**templates[kind], "id": identifier})
        return self._accept(story)

    def duplicate(
        self, kind: str, item_id: str, parent_id: str | None = None
    ) -> DraftSnapshot:
        story = copy.deepcopy(self._snapshot.story)
        items = self._collection(story, kind, parent_id)
        item = next((i for i in items if i["id"] == item_id), None)
        if item is None:
            raise ScenarioValidationError("Select a record to duplicate")
        clone = copy.deepcopy(item)

        def remap(value):
            if isinstance(value, dict):
                if "id" in value:
                    value["id"] = uuid4().hex
                for child in value.values():
                    remap(child)
            elif isinstance(value, list):
                for child in value:
                    remap(child)

        remap(clone)
        items.append(clone)
        validate_story_extension(story)
        return self._accept(story)

    def remove(
        self, kind: str, item_id: str, parent_id: str | None = None
    ) -> DraftSnapshot:
        story = copy.deepcopy(self._snapshot.story)
        items = self._collection(story, kind, parent_id)
        items[:] = [i for i in items if i["id"] != item_id]
        validate_story_extension(story)
        return self._accept(story)

    def set_condition(
        self,
        kind: str,
        item_id: str,
        variable_id: str,
        operator: str,
        value: JSONValue,
        *,
        group: str = "replace",
    ) -> DraftSnapshot:
        story = copy.deepcopy(self._snapshot.story)
        items = self._collection(story, kind)
        item = next((i for i in items if i["id"] == item_id), None)
        if kind not in ("events", "choices") or item is None:
            raise ScenarioValidationError("Choose an event or choice")
        comparison = {"op": operator, "variable_id": variable_id, "value": value}
        if group == "clear":
            item["condition"] = None
        elif group in ("all", "any") and item.get("condition"):
            item["condition"] = {
                "op": group,
                "children": [item["condition"], comparison],
            }
        else:
            item["condition"] = comparison
        validate_story_extension(story)
        return self._accept(story)
