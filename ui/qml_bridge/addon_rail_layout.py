"""Persistent presentation state for the Addons workspace rail."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


ADDON_RAIL_LAYOUT_SCHEMA_VERSION = 1


def _unique_ids(values: Iterable[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        identifier = str(value or "").strip()
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        result.append(identifier)
    return result


class AddonRailLayoutStore:
    """Atomically save addon-rail order and hidden entries by contribution ID."""

    def __init__(self, app_root: Path | None = None, *, path: Path | None = None) -> None:
        if path is None and app_root is None:
            raise ValueError("An app root or explicit addon-rail layout path is required.")
        self.path = Path(
            path or (Path(app_root) / "runtime" / "qml_addon_rail_layout.json")
        )
        self._lock = threading.RLock()

    def _read(self) -> dict[str, Any]:
        raw: object = {}
        if self.path.is_file():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, TypeError, ValueError):
                raw = {}
        payload = dict(raw) if isinstance(raw, Mapping) else {}
        return {
            "schema_version": ADDON_RAIL_LAYOUT_SCHEMA_VERSION,
            "order": _unique_ids(payload.get("order") or []),
            "hidden": _unique_ids(payload.get("hidden") or []),
        }

    def _write(self, payload: Mapping[str, object]) -> None:
        # Edits describe the currently available icons only. Keep preferences
        # for unavailable addons so enabling them again restores their layout.
        previous = self._read()
        active_order = _unique_ids(payload.get("order") or [])
        active_ids = set(active_order)
        replacements = iter(active_order)
        order = [
            next(replacements) if identifier in active_ids else identifier
            for identifier in previous["order"]
        ]
        order.extend(replacements)
        hidden = [identifier for identifier in previous["hidden"] if identifier not in active_ids]
        hidden.extend(_unique_ids(payload.get("hidden") or []))
        normalized = {
            "schema_version": ADDON_RAIL_LAYOUT_SCHEMA_VERSION,
            "order": _unique_ids(order),
            "hidden": _unique_ids(hidden),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(
            f"{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        temporary.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    def resolve(self, available_ids: Iterable[object]) -> dict[str, list[str]]:
        available = _unique_ids(available_ids)
        available_set = set(available)
        with self._lock:
            payload = self._read()
        order = [identifier for identifier in payload["order"] if identifier in available_set]
        order.extend(identifier for identifier in available if identifier not in order)
        hidden_set = {
            identifier for identifier in payload["hidden"] if identifier in available_set
        }
        hidden = [identifier for identifier in order if identifier in hidden_set]
        visible = [identifier for identifier in order if identifier not in hidden_set]
        return {"order": order, "visible": visible, "hidden": hidden}

    def set_hidden(
        self,
        addon_id: str,
        hidden: bool,
        available_ids: Iterable[object],
    ) -> dict[str, list[str]]:
        identifier = str(addon_id or "").strip()
        available = _unique_ids(available_ids)
        state = self.resolve(available)
        if identifier not in state["order"]:
            return state
        hidden_ids = list(state["hidden"])
        if hidden and identifier not in hidden_ids:
            hidden_ids.append(identifier)
        elif not hidden:
            hidden_ids = [item for item in hidden_ids if item != identifier]
        with self._lock:
            self._write({"order": state["order"], "hidden": hidden_ids})
        return self.resolve(available)

    def move_visible(
        self,
        addon_id: str,
        target_index: int,
        available_ids: Iterable[object],
    ) -> dict[str, list[str]]:
        identifier = str(addon_id or "").strip()
        available = _unique_ids(available_ids)
        state = self.resolve(available)
        if identifier not in state["visible"]:
            return state

        order = [item for item in state["order"] if item != identifier]
        visible_without = [item for item in state["visible"] if item != identifier]
        destination = max(0, min(int(target_index), len(visible_without)))
        if destination < len(visible_without):
            insert_at = order.index(visible_without[destination])
        elif visible_without:
            insert_at = order.index(visible_without[-1]) + 1
        else:
            insert_at = 0
        order.insert(insert_at, identifier)
        with self._lock:
            self._write({"order": order, "hidden": state["hidden"]})
        return self.resolve(available)


__all__ = ["AddonRailLayoutStore"]
