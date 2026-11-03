"""Persistent dock/workspace layout model for the native QML shell."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Mapping


# Keep the former combined workspace key for existing Visual Reply positions.
WORKSPACE_KEYS = ("runtime", "addons", "conversation", "visuals", "musetalk")
MAIN_DOCK_ZONES = ("left", "top", "center", "bottom", "right")
WORKSPACE_LAYOUT_SCHEMA_VERSION = 2


def _default_main_panes() -> dict[str, dict[str, Any]]:
    return {
        "left": {"workspaces": [], "active": ""},
        "top": {"workspaces": [], "active": ""},
        "center": {"workspaces": list(WORKSPACE_KEYS), "active": "runtime"},
        "bottom": {"workspaces": [], "active": ""},
        "right": {"workspaces": [], "active": ""},
    }


def _default_main_splits() -> dict[str, int]:
    return {
        "left_width": 360,
        "right_width": 520,
        "top_height": 300,
        "bottom_height": 300,
    }


def _coerce_int(value: object, default: int, *, minimum: int, maximum: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default
    return min(max(normalized, minimum), maximum)


def _default_main_window() -> dict[str, Any]:
    return {
        "x": None,
        "y": None,
        "width": 1480,
        "height": 920,
        "maximized": False,
        "active": "runtime",
        "persona_shortcuts_height": 328,
        "panes": _default_main_panes(),
        "splits": _default_main_splits(),
    }


def _default_floating_geometry(workspace_key: str) -> dict[str, int]:
    try:
        offset = WORKSPACE_KEYS.index(workspace_key) * 44
    except ValueError:
        offset = 0
    return {
        "x": 140 + offset,
        "y": 120 + offset,
        "width": 1180,
        "height": 780,
    }


def _normalize_geometry(
    value: object, *, workspace_key: str = "runtime", avatar_only: bool = False
) -> dict[str, int]:
    raw = dict(value or {}) if isinstance(value, Mapping) else {}
    defaults = _default_floating_geometry(workspace_key)
    return {
        "x": _coerce_int(raw.get("x"), defaults["x"], minimum=-32_768, maximum=32_768),
        "y": _coerce_int(raw.get("y"), defaults["y"], minimum=-32_768, maximum=32_768),
        "width": _coerce_int(raw.get("width"), defaults["width"], minimum=160 if avatar_only else 760, maximum=7_680),
        "height": _coerce_int(raw.get("height"), defaults["height"], minimum=160 if avatar_only else 560, maximum=4_320),
    }


class QmlWorkspaceLayoutStore:
    """Atomic persistence for redesigned QML workspace docking and geometry."""

    def __init__(self, app_root: Path, *, path: Path | None = None) -> None:
        self.path = Path(path or (Path(app_root) / "runtime" / "qml_workspace_layout.json"))
        self._lock = threading.RLock()

    def _normalize(self, value: object) -> dict[str, Any]:
        raw = dict(value or {}) if isinstance(value, Mapping) else {}
        raw_main = dict(raw.get("main_window") or {})
        default_main = _default_main_window()
        main_window: dict[str, Any] = {
            "x": raw_main.get("x") if isinstance(raw_main.get("x"), int) else None,
            "y": raw_main.get("y") if isinstance(raw_main.get("y"), int) else None,
            "width": _coerce_int(raw_main.get("width"), default_main["width"], minimum=1_120, maximum=7_680),
            "height": _coerce_int(raw_main.get("height"), default_main["height"], minimum=720, maximum=4_320),
            "maximized": bool(raw_main.get("maximized", False)),
            "active": (
                str(raw_main.get("active") or "runtime").strip().lower()
                if str(raw_main.get("active") or "runtime").strip().lower() in WORKSPACE_KEYS
                else "runtime"
            ),
            "persona_shortcuts_height": _coerce_int(
                raw_main.get("persona_shortcuts_height"),
                default_main["persona_shortcuts_height"],
                minimum=0,
                maximum=2_160,
            ),
        }

        floating_workspaces: set[str] = set()
        groups: dict[str, dict[str, Any]] = {}
        raw_groups = raw.get("groups")
        if isinstance(raw_groups, Mapping):
            for raw_group_id, raw_group in raw_groups.items():
                group_id = str(raw_group_id or "").strip()
                if not group_id or not isinstance(raw_group, Mapping):
                    continue
                workspaces = []
                for workspace in list(raw_group.get("workspaces") or []):
                    key = str(workspace or "").strip().lower()
                    if key not in WORKSPACE_KEYS or key in floating_workspaces:
                        continue
                    floating_workspaces.add(key)
                    workspaces.append(key)
                if not workspaces:
                    continue
                active = str(raw_group.get("active") or "").strip().lower()
                active = active if active in workspaces else workspaces[0]
                avatar_only = raw_group.get("avatar_only") is True and active == "musetalk"
                groups[group_id] = {
                    "id": group_id,
                    "workspaces": workspaces,
                    "active": active,
                    "avatar_only": avatar_only,
                    "always_on_top": raw_group.get("always_on_top") is True,
                    "geometry": _normalize_geometry(
                        raw_group.get("geometry"),
                        workspace_key=workspaces[0],
                        avatar_only=avatar_only,
                    ),
                }

        raw_panes = raw_main.get("panes")
        panes: dict[str, dict[str, Any]] = {}
        main_workspaces: set[str] = set()
        if isinstance(raw_panes, Mapping):
            for zone in MAIN_DOCK_ZONES:
                raw_pane = raw_panes.get(zone)
                raw_pane = dict(raw_pane or {}) if isinstance(raw_pane, Mapping) else {}
                workspaces: list[str] = []
                for workspace in list(raw_pane.get("workspaces") or []):
                    key = str(workspace or "").strip().lower()
                    if (
                        key not in WORKSPACE_KEYS
                        or key in floating_workspaces
                        or key in main_workspaces
                    ):
                        continue
                    main_workspaces.add(key)
                    workspaces.append(key)
                active = str(raw_pane.get("active") or "").strip().lower()
                panes[zone] = {
                    "workspaces": workspaces,
                    "active": active if active in workspaces else (workspaces[0] if workspaces else ""),
                }
        else:
            panes = _default_main_panes()
            panes["center"]["workspaces"] = [
                key for key in WORKSPACE_KEYS if key not in floating_workspaces
            ]
            panes["center"]["active"] = (
                main_window["active"]
                if main_window["active"] in panes["center"]["workspaces"]
                else (panes["center"]["workspaces"][0] if panes["center"]["workspaces"] else "")
            )
            main_workspaces.update(panes["center"]["workspaces"])

        for key in WORKSPACE_KEYS:
            if key not in floating_workspaces and key not in main_workspaces:
                panes["center"]["workspaces"].append(key)
                main_workspaces.add(key)
        if panes["center"]["workspaces"] and not panes["center"]["active"]:
            panes["center"]["active"] = panes["center"]["workspaces"][0]

        raw_splits = raw_main.get("splits")
        raw_splits = dict(raw_splits or {}) if isinstance(raw_splits, Mapping) else {}
        default_splits = _default_main_splits()
        splits = {
            "left_width": _coerce_int(
                raw_splits.get("left_width"), default_splits["left_width"], minimum=240, maximum=3_840
            ),
            "right_width": _coerce_int(
                raw_splits.get("right_width"), default_splits["right_width"], minimum=240, maximum=3_840
            ),
            "top_height": _coerce_int(
                raw_splits.get("top_height"), default_splits["top_height"], minimum=200, maximum=2_160
            ),
            "bottom_height": _coerce_int(
                raw_splits.get("bottom_height"), default_splits["bottom_height"], minimum=200, maximum=2_160
            ),
        }
        if main_window["active"] not in main_workspaces:
            main_window["active"] = next(
                (
                    str(panes[zone]["active"])
                    for zone in MAIN_DOCK_ZONES
                    if panes[zone]["active"]
                ),
                "",
            )
        main_window["panes"] = panes
        main_window["splits"] = splits
        hidden_tabs = raw.get("hidden_main_tabs", [])
        if not isinstance(hidden_tabs, list):
            hidden_tabs = []
        raw_navigation = raw.get("navigation", {})
        navigation = {
            key: selection for key, selection in raw_navigation.items()
            if isinstance(key, str) and key.strip()
            and isinstance(selection, str) and selection.strip()
        } if isinstance(raw_navigation, Mapping) else {}
        return {
            "schema_version": WORKSPACE_LAYOUT_SCHEMA_VERSION,
            "main_window": main_window,
            "groups": groups,
            "hidden_main_tabs": [key for key in WORKSPACE_KEYS if key in hidden_tabs],
            "panel_positions_locked": raw.get("panel_positions_locked") is True,
            "navigation": navigation,
        }

    def load(self) -> dict[str, Any]:
        with self._lock:
            raw: object = {}
            if self.path.is_file():
                try:
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, TypeError, ValueError):
                    raw = {}
            return self._normalize(raw)

    def _write(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        normalized = self._normalize(payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(
            f"{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        temporary.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
        return normalized

    def set_navigation_selection(self, key: str, selection: str) -> dict[str, Any]:
        if not isinstance(key, str) or not key.strip() or not isinstance(selection, str) or not selection.strip():
            raise ValueError("Navigation keys and selections must be nonempty strings.")
        with self._lock:
            payload = self.load()
            if payload["navigation"].get(key) == selection:
                return payload
            payload["navigation"][key] = selection
            return self._write(payload)

    @staticmethod
    def _remove_workspace(payload: dict[str, Any], workspace_key: str) -> None:
        empty_groups = []
        for group_id, group in dict(payload["groups"]).items():
            workspaces = [key for key in group["workspaces"] if key != workspace_key]
            if not workspaces:
                empty_groups.append(group_id)
                continue
            group["workspaces"] = workspaces
            if group["active"] not in workspaces:
                group["active"] = workspaces[0]
        for group_id in empty_groups:
            payload["groups"].pop(group_id, None)
        for pane in payload["main_window"]["panes"].values():
            workspaces = [key for key in pane["workspaces"] if key != workspace_key]
            pane["workspaces"] = workspaces
            if pane["active"] not in workspaces:
                pane["active"] = workspaces[0] if workspaces else ""

    def workspace_host(self, workspace_key: str) -> str:
        key = str(workspace_key or "").strip().lower()
        payload = self.load()
        for group_id, group in payload["groups"].items():
            if key in group["workspaces"]:
                return str(group_id)
        return "main"

    def main_workspace_zone(self, workspace_key: str) -> str:
        key = str(workspace_key or "").strip().lower()
        payload = self.load()
        for zone in MAIN_DOCK_ZONES:
            if key in payload["main_window"]["panes"][zone]["workspaces"]:
                return zone
        return ""

    def detach_workspace(self, workspace_key: str) -> dict[str, Any]:
        key = str(workspace_key or "").strip().lower()
        if key not in WORKSPACE_KEYS:
            raise ValueError("Unknown workspace.")
        with self._lock:
            payload = self.load()
            self._remove_workspace(payload, key)
            group_id = f"float-{key}-{time.time_ns()}"
            payload["groups"][group_id] = {
                "id": group_id,
                "workspaces": [key],
                "active": key,
                "geometry": _default_floating_geometry(key),
            }
            return self._write(payload)

    def dock_workspace_to_main(
        self,
        workspace_key: str,
        zone: str = "center",
    ) -> dict[str, Any]:
        key = str(workspace_key or "").strip().lower()
        if key not in WORKSPACE_KEYS:
            raise ValueError("Unknown workspace.")
        normalized_zone = str(zone or "center").strip().lower()
        if normalized_zone not in MAIN_DOCK_ZONES:
            raise ValueError("Unknown main-window dock zone.")
        with self._lock:
            payload = self.load()
            self._remove_workspace(payload, key)
            pane = payload["main_window"]["panes"][normalized_zone]
            pane["workspaces"].append(key)
            pane["active"] = key
            payload["main_window"]["active"] = key
            return self._write(payload)

    def dock_workspace_with_group(self, workspace_key: str, target_group_id: str) -> dict[str, Any]:
        key = str(workspace_key or "").strip().lower()
        group_id = str(target_group_id or "").strip()
        if key not in WORKSPACE_KEYS:
            raise ValueError("Unknown workspace.")
        with self._lock:
            payload = self.load()
            target = payload["groups"].get(group_id)
            if target is None:
                raise ValueError("The target floating window is no longer available.")
            target_geometry = dict(target["geometry"])
            self._remove_workspace(payload, key)
            target = payload["groups"].get(group_id)
            if target is None:
                payload["groups"][group_id] = {
                    "id": group_id,
                    "workspaces": [key],
                    "active": key,
                    "geometry": target_geometry,
                }
            else:
                if key not in target["workspaces"]:
                    target["workspaces"].append(key)
                target["active"] = key
            return self._write(payload)

    def dock_group_to_main(self, group_id: str) -> dict[str, Any]:
        with self._lock:
            payload = self.load()
            group = payload["groups"].pop(str(group_id or "").strip(), None)
            if group:
                pane = payload["main_window"]["panes"]["center"]
                for key in group["workspaces"]:
                    if key not in pane["workspaces"]:
                        pane["workspaces"].append(key)
                pane["active"] = (
                    group["active"] if group["active"] in pane["workspaces"] else pane["workspaces"][0]
                )
                payload["main_window"]["active"] = pane["active"]
            return self._write(payload)

    def set_main_pane_active(self, zone: str, workspace_key: str) -> dict[str, Any]:
        normalized_zone = str(zone or "").strip().lower()
        key = str(workspace_key or "").strip().lower()
        if normalized_zone not in MAIN_DOCK_ZONES:
            raise ValueError("Unknown main-window dock zone.")
        with self._lock:
            payload = self.load()
            pane = payload["main_window"]["panes"][normalized_zone]
            if key not in pane["workspaces"]:
                return payload
            pane["active"] = key
            payload["main_window"]["active"] = key
            return self._write(payload)

    def update_main_splits(
        self,
        *,
        left_width: int,
        right_width: int,
        top_height: int,
        bottom_height: int,
    ) -> dict[str, Any]:
        with self._lock:
            payload = self.load()
            defaults = _default_main_splits()
            payload["main_window"]["splits"] = {
                "left_width": _coerce_int(left_width, defaults["left_width"], minimum=240, maximum=3_840),
                "right_width": _coerce_int(right_width, defaults["right_width"], minimum=240, maximum=3_840),
                "top_height": _coerce_int(top_height, defaults["top_height"], minimum=200, maximum=2_160),
                "bottom_height": _coerce_int(bottom_height, defaults["bottom_height"], minimum=200, maximum=2_160),
            }
            return self._write(payload)

    def update_persona_shortcuts_height(self, height: int) -> dict[str, Any]:
        with self._lock:
            payload = self.load()
            payload["main_window"]["persona_shortcuts_height"] = _coerce_int(
                height,
                _default_main_window()["persona_shortcuts_height"],
                minimum=0,
                maximum=2_160,
            )
            return self._write(payload)

    def set_group_active(self, group_id: str, workspace_key: str) -> dict[str, Any]:
        with self._lock:
            payload = self.load()
            group = payload["groups"].get(str(group_id or "").strip())
            key = str(workspace_key or "").strip().lower()
            if group is None or key not in group["workspaces"]:
                return payload
            group["active"] = key
            return self._write(payload)

    def set_group_always_on_top(self, group_id: str, enabled: bool) -> dict[str, Any]:
        with self._lock:
            payload = self.load()
            group = payload["groups"].get(str(group_id or "").strip())
            if group is None:
                raise ValueError("Unknown floating window.")
            group["always_on_top"] = bool(enabled)
            return self._write(payload)

    def update_group_geometry(
        self,
        group_id: str,
        *,
        x: int,
        y: int,
        width: int,
        height: int,
        avatar_only: bool | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            payload = self.load()
            group = payload["groups"].get(str(group_id or "").strip())
            if group is None:
                return payload
            if avatar_only is not None:
                group["avatar_only"] = bool(avatar_only) and group["active"] == "musetalk"
            group["geometry"] = _normalize_geometry(
                {"x": x, "y": y, "width": width, "height": height},
                workspace_key=group["workspaces"][0],
                avatar_only=bool(group.get("avatar_only", False)),
            )
            return self._write(payload)

    def update_main_window(
        self,
        *,
        x: int,
        y: int,
        width: int,
        height: int,
        maximized: bool,
    ) -> dict[str, Any]:
        with self._lock:
            payload = self.load()
            payload["main_window"].update(
                {
                    "x": _coerce_int(x, 0, minimum=-32_768, maximum=32_768),
                    "y": _coerce_int(y, 0, minimum=-32_768, maximum=32_768),
                    "width": _coerce_int(width, 1480, minimum=1_120, maximum=7_680),
                    "height": _coerce_int(height, 920, minimum=720, maximum=4_320),
                    "maximized": bool(maximized),
                }
            )
            return self._write(payload)

    def set_main_active(self, workspace_key: str) -> dict[str, Any]:
        key = str(workspace_key or "").strip().lower()
        if key not in WORKSPACE_KEYS:
            raise ValueError("Unknown workspace.")
        with self._lock:
            payload = self.load()
            if any(key in group["workspaces"] for group in payload["groups"].values()):
                return payload
            for zone in MAIN_DOCK_ZONES:
                pane = payload["main_window"]["panes"][zone]
                if key in pane["workspaces"]:
                    pane["active"] = key
                    payload["main_window"]["active"] = key
                    return self._write(payload)
            return payload

    def set_main_tab_visible(self, workspace_key: str, visible: bool) -> dict[str, Any]:
        if workspace_key not in WORKSPACE_KEYS:
            raise ValueError("Unknown workspace.")
        with self._lock:
            payload = self.load()
            hidden = set(payload["hidden_main_tabs"])
            if visible:
                hidden.discard(workspace_key)
            else:
                hidden.add(workspace_key)
            payload["hidden_main_tabs"] = [key for key in WORKSPACE_KEYS if key in hidden]
            return self._write(payload)

    def set_all_main_tabs_visible(self, visible: bool) -> dict[str, Any]:
        with self._lock:
            payload = self.load()
            payload["hidden_main_tabs"] = [] if visible else list(WORKSPACE_KEYS)
            return self._write(payload)

    def set_panel_positions_locked(self, locked: bool) -> dict[str, Any]:
        with self._lock:
            payload = self.load()
            payload["panel_positions_locked"] = bool(locked)
            return self._write(payload)

    def reset_docking(self) -> dict[str, Any]:
        with self._lock:
            payload = self.load()
            payload["groups"] = {}
            payload["hidden_main_tabs"] = []
            payload["panel_positions_locked"] = False
            payload["main_window"]["splits"] = _default_main_splits()
            payload["main_window"]["panes"] = _default_main_panes()
            payload["main_window"]["panes"]["center"]["active"] = (
                payload["main_window"]["active"]
                if payload["main_window"]["active"] in WORKSPACE_KEYS
                else "runtime"
            )
            return self._write(payload)


__all__ = ["MAIN_DOCK_ZONES", "QmlWorkspaceLayoutStore", "WORKSPACE_KEYS"]
