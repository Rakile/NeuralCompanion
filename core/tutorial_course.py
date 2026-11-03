"""Compose explicitly authored chapters without executing application actions."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from core.tutorial_scope import is_scoped, step_route, validate_tutorial


def prepare_tutorial(selected: dict[str, Any], loader: Callable[[str], Any]) -> tuple[dict[str, Any], int]:
    """Resolve a stable shortcut; legacy/First Chat payloads pass through unchanged."""
    if not is_scoped(selected) or selected.get("kind") == "workflow":
        return selected, 0
    root_id = str(selected.get("redirect_to") or selected.get("course_id") or "")
    root = loader(root_id) if root_id else selected
    if not isinstance(root, Mapping):
        raise ValueError("The tutorial course is unavailable.")
    if not isinstance(root.get("id"), str) or not root["id"].strip():
        raise ValueError("The tutorial course has no ID.")
    if "course_chapters" not in root:
        return dict(root), 0
    ids = root.get("course_chapters")
    if not isinstance(ids, list) or any(not isinstance(key, str) for key in ids):
        raise ValueError("Invalid course chapters.")
    chapters = [dict(root)]
    seen = {str(root["id"])}
    for key in ids:
        if key in seen:
            continue
        chapter = loader(key)
        if not isinstance(chapter, Mapping) or chapter.get("id") == "first_run":
            raise ValueError(f"Chapter unavailable: {key}")
        chapters.append(dict(chapter))
        seen.add(key)
    # Optional chapters can be entered directly without joining the normal sequence.
    if selected.get("id") not in seen and not selected.get("redirect_to"):
        chapters = [selected]
    steps, routes, chapter_items = [], [], []
    start_index = 0
    for chapter in chapters:
        errors = validate_tutorial(chapter)
        if errors or not is_scoped(chapter):
            raise ValueError(errors[0] if errors else "Invalid course chapter.")
        if chapter["id"] == selected["id"]:
            start_index = len(steps)
        chapter_items.append(dict(id=chapter["id"], title=chapter["title"], step_index=len(steps)))
        for source in chapter["steps"]:
            route = step_route(chapter, source)
            if route not in routes:
                routes.append(route)
            steps.append({**source, **route, "chapter_id": chapter["id"],
                          "chapter_title": chapter["title"],
                          "advance_mode": source.get("advance_mode", "continue" if source.get("try_action")
                              or chapter.get("kind") == "workflow" else "audio_finish")})
    result = {**root, "kind": "workflow", "scope": {}, "allowed_routes": routes,
              "continuous_course": True, "chapters": chapter_items, "steps": steps,
              "course_chapters": [item["id"] for item in chapter_items[1:]],
              "children": [key for key in root.get("optional_chapters") or [] if key != selected["id"]]}
    errors = validate_tutorial(result)
    if errors:
        raise ValueError(errors[0])
    return result, start_index
