from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TUTORIALS_DIR = ROOT / "tutorials"

TEXT_EXTENSIONS = {
    ".json",
    ".py",
    ".qml",
    ".qss",
    ".ts",
    ".tsx",
    ".ui",
}

ROOT_SKIP_DIRS = {
    ".git",
    ".idea",
    ".venv",
    ".venvs",
    "node_modules",
    "runtime",
}

ACTION_TYPES = {
    "focus",
    "highlight_ui",
    "load_preset",
    "load_profile",
    "open_tab",
    "reset_to_safe_state",
    "set_checkbox",
    "set_combo_text",
    "set_spin_value",
    "set_tab",
    "show_dock",
}

TARGETED_ACTION_TYPES = {
    "focus",
    "highlight_ui",
    "set_checkbox",
    "set_combo_text",
    "set_spin_value",
    "show_dock",
}

TAB_ACTION_TYPES = {
    "open_tab",
    "set_tab",
}

KNOWN_VIRTUAL_TARGETS = {
    "SystemShapingDock",
    "WorkspaceTabsDock",
    "VisualReplyDock",
}


def _quoted_key_exists(key: str, corpus: str) -> bool:
    return f'"{key}"' in corpus or f"'{key}'" in corpus


def _repo_text() -> str:
    parts: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        rel_parts = path.relative_to(ROOT).parts
        if "tutorials" in rel_parts or "__pycache__" in rel_parts:
            continue
        if rel_parts and rel_parts[0] in ROOT_SKIP_DIRS:
            continue
        try:
            parts.append(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    return "\n".join(parts)


def _load_tutorial(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - printed by smoke script
        raise AssertionError(f"{path.name}: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise AssertionError(f"{path.name}: top-level payload must be an object")
    return payload


def _target_exists(target: str, corpus: str) -> bool:
    if target in KNOWN_VIRTUAL_TARGETS:
        return True
    if target in corpus:
        return True
    if target.startswith("spotify_sense_"):
        # Spotify Sense creates checkbox/spinbox object names from setting keys.
        return _quoted_key_exists(target.removeprefix("spotify_sense_"), corpus)
    if target.startswith("mprc_"):
        # MPRC assigns mprc_<control_key> object names after controls are built.
        return _quoted_key_exists(target.removeprefix("mprc_"), corpus)
    return False


def main() -> int:
    errors: list[str] = []
    corpus = _repo_text()
    seen_ids: dict[str, str] = {}
    seen_orders: dict[int, str] = {}

    for path in sorted(TUTORIALS_DIR.glob("*.json")):
        payload = _load_tutorial(path)
        tutorial_id = str(payload.get("id") or "").strip()
        title = str(payload.get("title") or "").strip()
        steps = payload.get("steps")

        if not tutorial_id:
            errors.append(f"{path.name}: missing id")
        elif tutorial_id in seen_ids:
            errors.append(f"{path.name}: duplicate id '{tutorial_id}' already used by {seen_ids[tutorial_id]}")
        else:
            seen_ids[tutorial_id] = path.name

        if not title:
            errors.append(f"{path.name}: missing title")

        order = payload.get("order")
        if isinstance(order, int):
            if order in seen_orders:
                errors.append(f"{path.name}: duplicate order {order} already used by {seen_orders[order]}")
            else:
                seen_orders[order] = path.name

        if not isinstance(steps, list) or not steps:
            errors.append(f"{path.name}: steps must be a non-empty list")
            continue

        for index, raw_step in enumerate(steps, start=1):
            if not isinstance(raw_step, dict):
                errors.append(f"{path.name} step {index}: step must be an object")
                continue
            step_title = str(raw_step.get("title") or "").strip()
            body = str(raw_step.get("body") or "").strip()
            target = str(raw_step.get("target") or "").strip()
            actions = raw_step.get("actions") or []

            if not step_title:
                errors.append(f"{path.name} step {index}: missing title")
            if not body:
                errors.append(f"{path.name} step {index}: missing body")
            if not target:
                errors.append(f"{path.name} step {index}: missing target")
            elif target == "main_window":
                errors.append(f"{path.name} step {index}: target must be a real UI object, not main_window")
            elif not _target_exists(target, corpus):
                errors.append(f"{path.name} step {index}: target '{target}' was not found in UI/code sources")

            if not isinstance(actions, list):
                errors.append(f"{path.name} step {index}: actions must be a list when present")
                continue
            for action_index, raw_action in enumerate(actions, start=1):
                if not isinstance(raw_action, dict):
                    errors.append(f"{path.name} step {index} action {action_index}: action must be an object")
                    continue
                action_type = str(raw_action.get("type") or "").strip()
                if action_type and action_type not in ACTION_TYPES:
                    errors.append(f"{path.name} step {index} action {action_index}: unsupported action type '{action_type}'")
                    continue
                if action_type in TARGETED_ACTION_TYPES:
                    action_target = str(raw_action.get("target") or raw_action.get("value") or "").strip()
                    if not action_target:
                        errors.append(f"{path.name} step {index} action {action_index}: action '{action_type}' missing target")
                    elif not _target_exists(action_target, corpus):
                        errors.append(
                            f"{path.name} step {index} action {action_index}: "
                            f"action target '{action_target}' was not found in UI/code sources"
                        )
                elif action_type in TAB_ACTION_TYPES:
                    tab_widget = str(raw_action.get("tab_widget") or "left_tabs").strip()
                    if tab_widget and not _target_exists(tab_widget, corpus):
                        errors.append(
                            f"{path.name} step {index} action {action_index}: "
                            f"tab widget '{tab_widget}' was not found in UI/code sources"
                        )

    if errors:
        print("Tutorial smoke check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"Tutorial smoke check passed for {len(seen_ids)} tutorial(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
