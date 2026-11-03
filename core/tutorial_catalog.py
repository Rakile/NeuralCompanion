"""Presentation-neutral access to NeuralCompanion tutorial definitions."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from collections.abc import Iterator
from typing import Any

from core.tutorial_scope import normalize_route, validate_tutorial
from core.tutorial_course import prepare_tutorial


TUTORIALS_DIR = Path(__file__).resolve().parents[1] / "tutorials"


def ensure_tutorials_dir() -> None:
    TUTORIALS_DIR.mkdir(parents=True, exist_ok=True)


def _definitions() -> Iterator[tuple[Path, dict[str, Any]]]:
    """Read legacy files and authored page-guide bundles without addon imports."""
    paths = sorted(TUTORIALS_DIR.glob("*.json")) + sorted((TUTORIALS_DIR / "scoped").glob("*.json"))
    for path in paths:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        if not isinstance(document, dict):
            continue
        definitions = document.get("guides", []) if "guides" in document else [document]
        if not isinstance(definitions, list):
            continue
        for payload in definitions:
            if isinstance(payload, dict) and payload.get("id") and isinstance(payload.get("steps"), list):
                yield path, payload


def _tutorial_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    try:
        order = int(item.get("order"))
    except (TypeError, ValueError):
        order = 9999
    return order, str(item.get("title") or item.get("id") or "").lower()


_WORKSPACE_LABELS = {
    "addons": "Addon workspace",
    "conversation": "Conversation",
    "musetalk": "MuseTalk",
    "runtime": "Runtime settings",
    "visuals": "Visuals",
}


def _clean_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _step_location(step: dict[str, Any]) -> str:
    section = str(step.get("section") or "").strip()
    if section:
        return section
    runtime_section = str(step.get("runtime_section") or "").strip()
    if runtime_section:
        return runtime_section.replace("_", " ").title()
    workspace = str(step.get("workspace") or "").strip().lower()
    return _WORKSPACE_LABELS.get(workspace, workspace.replace("_", " ").title())


def _preview_fields(payload: dict[str, Any]) -> dict[str, Any]:
    steps = [step for step in payload.get("steps") or [] if isinstance(step, dict)]
    first_workspace = str(steps[0].get("workspace") or "").strip().lower() if steps else ""
    step_preview = [
        {
            "number": index,
            "title": str(step.get("title") or f"Step {index}"),
            "location": _step_location(step),
        }
        for index, step in enumerate(steps, start=1)
    ]
    destinations = list(dict.fromkeys(
        location for location in (str(step["location"]).strip() for step in step_preview)
        if location
    ))
    learning_outcomes = _clean_string_list(payload.get("learning_outcomes"))
    if not learning_outcomes:
        learning_outcomes = [str(step["title"]) for step in step_preview[:3]]
    before_you_start = str(payload.get("before_you_start") or "").strip()
    if not before_you_start:
        before_you_start = (
            "You can review this guide without changing settings. "
            "Any step that requires a configured service explains it when you arrive."
        )
    estimated_minutes = payload.get("estimated_minutes")
    try:
        estimated_minutes = max(2, int(estimated_minutes))
    except (TypeError, ValueError):
        estimated_minutes = max(2, math.ceil(len(steps) * 0.8))
    category = str(payload.get("category") or "").strip()
    if not category:
        category = _WORKSPACE_LABELS.get(
            first_workspace,
            first_workspace.replace("_", " ").title() or "NeuralCompanion",
        )
    return {
        "audience": "remote" if payload.get("audience") == "remote" else "desktop",
        "category": category,
        "estimated_minutes": estimated_minutes,
        "learning_outcomes": learning_outcomes,
        "before_you_start": before_you_start,
        "destinations": destinations,
        "primary_destination": destinations[0] if destinations else category,
        "step_preview": step_preview,
    }


def remote_step_view(step: dict[str, Any]) -> dict[str, Any]:
    """Resolve only bundled screenshots; definitions cannot load arbitrary files/URLs."""
    assets = (TUTORIALS_DIR / "assets" / "remote").resolve()
    screenshot = ''
    try:
        image = (assets / str(step.get("screenshot") or "")).resolve()
        if image.is_relative_to(assets) and image.is_file() and image.suffix.lower() == '.png':
            screenshot = image.as_uri()
    except (OSError, ValueError):
        pass
    highlight = step.get('highlight', [])
    if (not isinstance(highlight, list) or len(highlight) != 4
            or any(not isinstance(n, (int, float)) or not math.isfinite(n) or not 0 <= n <= 1 for n in highlight)
            or highlight[0] + highlight[2] > 1 or highlight[1] + highlight[3] > 1):
        highlight = []
    return dict(screenshot=screenshot, highlight=highlight,
                **{key: str(step.get(key) or '') for key in ('device', 'expected', 'recovery', 'caption', 'gesture')})


def list_tutorials() -> list[dict[str, Any]]:
    ensure_tutorials_dir()
    items: list[dict[str, Any]] = []
    definitions = list(_definitions())
    by_id = {str(payload["id"]): payload for _, payload in definitions}
    for path, payload in definitions:
        preview = payload
        composition_errors: list[str] = []
        if "course_chapters" in payload:
            try:
                preview, _ = prepare_tutorial(payload, by_id.get)
            except ValueError as error:
                composition_errors.append(str(error))
        item = {
                "id": str(payload.get("id") or path.stem),
                "title": str(payload.get("title") or path.stem.replace("_", " ").title()),
                "description": str(payload.get("description") or ""),
                "order": payload.get("order"),
                "path": str(path),
                "step_count": len(preview.get("steps") or []),
        }
        item["display_title"] = str(payload.get("display_title") or re.sub(r"^\s*\d+\.\s+", "", item["title"]))
        item["hidden"] = bool(payload.get("hidden") or payload.get("redirect_to"))
        item["course_id"] = str(payload.get("course_id") or "")
        item["course_chapters"] = list(payload.get("course_chapters") or [])
        item["optional_chapters"] = list(payload.get("optional_chapters") or [])
        if item["course_id"]:
            item["display_title"] = "Chapter · " + item["display_title"]
        if payload.get("kind") == "workflow":
            item["display_title"] = "Workflow · " + item["display_title"]
        item.update(kind=str(payload.get("kind") or ""), scope=normalize_route(payload.get("scope")),
                    children=list(payload.get("children") or []),
                    validation_errors=validate_tutorial(payload) + composition_errors)
        item.update(_preview_fields(preview))
        items.append(item)
    return sorted(items, key=_tutorial_sort_key)


def load_tutorial(tutorial_id: str) -> dict[str, Any] | None:
    ensure_tutorials_dir()
    normalized = str(tutorial_id or "").strip()
    if not normalized:
        return None
    # Keep the original direct-file path for First Chat and legacy entry points.
    # Only a basename is accepted; bundle IDs are resolved below.
    if normalized == Path(normalized).name and "/" not in normalized and "\\" not in normalized:
        path = TUTORIALS_DIR / (normalized if normalized.endswith(".json") else f"{normalized}.json")
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, TypeError):
                return None
            if isinstance(payload, dict) and "guides" not in payload:
                payload.setdefault("id", path.stem)
                payload.setdefault("title", path.stem.replace("_", " ").title())
                payload.setdefault("steps", [])
                return payload
    # IDs remain the public contract; never treat an ID as an arbitrary path.
    filename = normalized
    for path, payload in _definitions():
        if str(payload.get("id")) == normalized or (path.name == filename and path.stem == str(payload.get("id"))):
            return dict(payload)
    return None


__all__ = ["TUTORIALS_DIR", "ensure_tutorials_dir", "list_tutorials", "load_tutorial"]
