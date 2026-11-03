"""Presentation-only ownership and validation for contextual tutorials.

No Qt, addon imports, service calls or settings writes belong in this module.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

ROUTE_KEYS = ("workspace", "addon", "owner_addon", "runtime_section", "runtime_responsibility",
              "provider_kind", "provider_id", "section", "subsection", "persona_tab",
              "remote_tab", "document_section", "sensory_tab", "chat_tab", "persona_override")
GUIDE_KINDS = frozenset({"overview", "section", "workflow"})


@dataclass
class TutorialNavigation:
    """Track presentation independently of the narration/player lifecycle."""

    route: dict[str, str]
    token: int
    ready: bool = False
    paused: bool = False
    unmatched_reports: int = 0
    elsewhere: bool = False

    def observe(self, current: Any, token: int) -> bool:
        if token != self.token:
            return False
        previous = self.elsewhere
        if presentation_matches(self.route, current):
            self.ready = True
            self.unmatched_reports = 0
            self.elsewhere = False
        else:
            self.unmatched_reports += 1
            # Bound presentation retries if a destination cannot be mounted.
            if self.ready or self.unmatched_reports >= 10:
                self.elsewhere = True
        return previous != self.elsewhere


def normalize_route(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {key: value[key].strip() for key in ROUTE_KEYS
            if isinstance(value.get(key), str) and value[key].strip()}


def is_scoped(payload: Any) -> bool:
    return bool(isinstance(payload, Mapping) and payload.get("id") != "first_run"
                and payload.get("audience") != "remote" and isinstance(payload.get("kind"), str)
                and payload.get("kind") in GUIDE_KINDS)


def route_matches(expected: Any, current: Any) -> bool:
    actual = normalize_route(current)
    return all(actual.get(key) == value for key, value in normalize_route(expected).items())


def presentation_matches(expected: Any, current: Any) -> bool:
    route = normalize_route(expected)
    route.pop("owner_addon", None)  # Provenance is checked by the coverage inventory.
    return route_matches(route, current)


def step_route(payload: Mapping[str, Any], step: Mapping[str, Any]) -> dict[str, str]:
    route = {**normalize_route(payload.get("scope")), **normalize_route(step)}
    if isinstance(step.get("vision_provider"), str) and step["vision_provider"]:
        route.update(provider_kind="vision", provider_id=step["vision_provider"])
    return route


def validate_tutorial(payload: Any) -> list[str]:
    if not isinstance(payload, Mapping):
        return ["Tutorial must be an object"]
    if payload.get("id") == "first_run" or payload.get("audience") == "remote":
        return []
    kind = payload.get("kind")
    if kind is None:  # Legacy entry points remain loadable during migration.
        return []
    errors: list[str] = []
    if not isinstance(kind, str) or kind not in GUIDE_KINDS:
        errors.append("Unknown tutorial kind")
    owner = normalize_route(payload.get("scope"))
    if kind != "workflow" and not owner.get("workspace"):
        errors.append("Overview and section guides require an owning workspace")
    raw_scope = payload.get("scope", {})
    if not isinstance(raw_scope, Mapping) or any(
        key not in ROUTE_KEYS or not isinstance(value, str) or not value.strip()
        for key, value in (raw_scope.items() if isinstance(raw_scope, Mapping) else [])
    ):
        errors.append("Invalid scope fields")
    allowed = payload.get("allowed_routes")
    global_targets = payload.get("global_targets", [])
    if not isinstance(global_targets, list) or any(not isinstance(target, str) or not target.strip()
                                                   for target in global_targets):
        errors.append("Global targets require an explicit list of objectName strings")
    if kind == "workflow" and (not isinstance(allowed, list) or not allowed
                               or any(not normalize_route(item).get("workspace") for item in allowed)):
        errors.append("Workflow requires explicit allowed routes")
    steps = payload.get("steps")
    if not isinstance(steps, list) or not steps:
        return errors + ["Tutorial requires readable steps"]
    for index, step in enumerate(steps):
        if not isinstance(step, Mapping):
            errors.append(f"Step {index + 1} must be an object")
            continue
        if not isinstance(step.get("title"), str) or not step["title"].strip():
            errors.append(f"Step {index + 1} requires a title")
        if "target" in step and not isinstance(step["target"], str):
            errors.append(f"Step {index + 1} target must be an objectName string")
        if any(key in step and not isinstance(step[key], str) for key in ROUTE_KEYS):
            errors.append(f"Step {index + 1} has invalid route fields")
        route = step_route(payload, step)
        if route.get("workspace") not in {"runtime", "addons", "conversation", "visuals", "musetalk"}:
            errors.append(f"Step {index + 1} has an unknown workspace")
        if route.get("addon") and route.get("workspace") != "addons":
            errors.append(f"Step {index + 1} addon must belong to the Addons workspace")
        if route.get("provider_kind") and route.get("workspace") != "runtime":
            errors.append(f"Step {index + 1} provider must belong to Runtime")
        if kind == "workflow":
            if not isinstance(allowed, list) or route not in [normalize_route(item) for item in allowed]:
                errors.append(f"Step {index + 1} is outside allowed routes")
        elif route != owner:
            errors.append(f"Step {index + 1} leaves its owning page")
    return errors


def guides_for_route(items: Iterable[Any] | None, context: Any,
                     include_children: bool = True) -> list[dict[str, Any]]:
    requested = normalize_route(context)
    if not requested:
        return []
    source = list(items or ())
    results = []
    for item in source:
        if (not isinstance(item, Mapping) or not is_scoped(item)
                or item.get("kind") == "workflow" or item.get("hidden")):
            continue
        owner = normalize_route(item.get("scope"))
        # A page menu includes its parent guide as well as provider/subtab guides.
        # Structural keys (workspace/addon/runtime page) must still be explicit.
        compatible = all(owner.get(key) == value or
                         (key in {"provider_kind", "provider_id", "subsection", "sensory_tab",
                                  "document_section", "persona_tab", "remote_tab", "chat_tab", "persona_override"}
                          and key not in owner)
                         for key, value in requested.items())
        if compatible and (include_children or requested == owner):
            results.append(dict(item))
    # Broader exercises are explicitly linked, never inferred from similar names.
    # Keep the local course first and label these entries as workflows.
    optional_ids = {key for item in results if isinstance(item.get("optional_chapters"), list)
                    for key in item["optional_chapters"] if isinstance(key, str)}
    follow_ups = [dict(item) for item in source if isinstance(item, Mapping)
                  and item.get("id") in optional_ids and item.get("kind") == "workflow"
                  and is_scoped(item) and not item.get("hidden")]
    return sorted(results, key=_guide_sort_key) + sorted(follow_ups, key=_guide_sort_key)


def _guide_sort_key(item: Mapping[str, Any]) -> tuple[int, bool, str]:
    try:
        order = int(item.get("order"))
    except (TypeError, ValueError):
        order = 9999
    return order, item.get("kind") != "overview", str(item.get("title", ""))
