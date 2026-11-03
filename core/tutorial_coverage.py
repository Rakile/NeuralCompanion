"""Pure checks that full walkthroughs remain reachable from their context."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.tutorial_scope import normalize_route, step_route

_AREA_KEYS = ("workspace", "addon", "runtime_section", "runtime_responsibility", "provider_kind", "provider_id")


def audit_detailed_guides(payloads: Mapping[str, Mapping[str, Any]]) -> list[str]:
    errors: list[str] = []
    for key, workflow in payloads.items():
        if key == "first_run" or workflow.get("audience") == "remote" or workflow.get("kind") != "workflow":
            continue
        parents = workflow.get("contextual_guides")
        if (not isinstance(parents, list) or not parents
                or any(not isinstance(parent, str) or not parent.strip() for parent in parents)):
            errors.append(f"{key}: full walkthrough has no contextual guides")
            continue
        if len(parents) != len(set(parents)):
            errors.append(f"{key}: duplicate contextual guides")
        for parent_id in parents:
            parent = payloads.get(parent_id)
            if (not parent or parent.get("kind") not in {"overview", "section"}
                    or parent.get("hidden") or parent.get("redirect_to") or parent.get("audience") == "remote"):
                errors.append(f"{key}: invalid contextual entry {parent_id}")
                continue
            chapters = parent.get("course_chapters") or []
            follow_ups = parent.get("optional_chapters") or []
            if key not in chapters and key not in follow_ups:
                errors.append(f"{parent_id}: full walkthrough {key} is disconnected")
            if key in chapters and key in follow_ups:
                errors.append(f"{parent_id}: full walkthrough {key} is both primary and optional")
            if key in chapters:
                owner = {name: value for name, value in normalize_route(parent.get("scope")).items()
                         if name in _AREA_KEYS}
                if any(not isinstance(step, Mapping)
                       or not all(step_route(workflow, step).get(name) == value for name, value in owner.items())
                       for step in workflow.get("steps") or []):
                    errors.append(f"{parent_id}: cross-area workflow {key} must be an optional follow-up")
    for parent_id, parent in payloads.items():
        if parent_id == "first_run" or parent.get("audience") == "remote":
            continue
        course_id = parent.get("course_id")
        if course_id and not parent.get("redirect_to"):
            owner = payloads.get(str(course_id))
            if not owner or parent_id not in [*(owner.get("course_chapters") or []), *(owner.get("optional_chapters") or [])]:
                errors.append(f"{parent_id}: focused guide is disconnected from {course_id}")
        for field in ("course_chapters", "optional_chapters"):
            links = parent.get(field, [])
            if not isinstance(links, list) or any(not isinstance(key, str) for key in links):
                errors.append(f"{parent_id}: invalid {field}")
                continue
            if len(links) != len(set(links)):
                errors.append(f"{parent_id}: duplicate {field}")
            for key in links:
                linked = payloads.get(key)
                if not linked or key == "first_run" or linked.get("audience") == "remote":
                    errors.append(f"{parent_id}: invalid linked guide {key}")
                elif linked.get("kind") == "workflow" and parent_id not in (linked.get("contextual_guides") or []):
                    errors.append(f"{parent_id}: {key} has no matching contextual declaration")
    return errors
