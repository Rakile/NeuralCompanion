"""Shell-preview addon service bootstrap helpers.

The read-only shell is intentionally lighter than the live addon manager, but
it still should not import addon implementation classes directly. These helpers
ask addon entrypoints for shell services through capability names.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


_ADDON_ENTRY_BY_ID = {}
_ADDON_ID_BY_UI_ROLE = {}


def _iter_addon_manifests():
    addons_root = Path(__file__).resolve().parents[2] / "addons"
    for manifest_path in sorted(addons_root.glob("*/addon.json")):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        yield manifest_path, payload


def _addon_entry_path(addon_id):
    addon_id = str(addon_id or "").strip()
    if not addon_id:
        return None
    if addon_id in _ADDON_ENTRY_BY_ID:
        return _ADDON_ENTRY_BY_ID[addon_id]
    for manifest_path, payload in _iter_addon_manifests():
        if str(payload.get("id") or "").strip() != addon_id:
            continue
        entry_point = str(payload.get("entry_point") or "main.py").strip() or "main.py"
        entry_path = manifest_path.parent / entry_point
        _ADDON_ENTRY_BY_ID[addon_id] = entry_path
        return entry_path
    _ADDON_ENTRY_BY_ID[addon_id] = None
    return None


def addon_id_for_ui_role(role):
    role = str(role or "").strip().lower()
    if not role:
        return ""
    if role in _ADDON_ID_BY_UI_ROLE:
        return _ADDON_ID_BY_UI_ROLE[role]
    for _manifest_path, payload in _iter_addon_manifests():
        addon_id = str(payload.get("id") or "").strip()
        if not addon_id:
            continue
        for entry in list(payload.get("ui") or []):
            if not isinstance(entry, dict):
                continue
            metadata = dict(entry.get("metadata") or {})
            if str(metadata.get("runtime_role") or "").strip().lower() == role:
                _ADDON_ID_BY_UI_ROLE[role] = addon_id
                return addon_id
    _ADDON_ID_BY_UI_ROLE[role] = ""
    return ""


def create_shell_addon_service(addon_id, capability, payload=None, default=None):
    entry_path = _addon_entry_path(addon_id)
    if entry_path is None or not entry_path.exists():
        return default
    try:
        module_name = "nc_shell_service_" + str(addon_id or "addon").replace(".", "_")
        spec = importlib.util.spec_from_file_location(module_name, entry_path)
        if spec is None or spec.loader is None:
            return default
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        addon_cls = getattr(module, "Addon", None)
        addon = addon_cls() if callable(addon_cls) else None
        invoker = getattr(addon, "invoke_capability", None)
        if not callable(invoker):
            return default
        result = invoker(str(capability), dict(payload or {}))
        return default if result is None else result
    except Exception:
        return default


def create_shell_addon_service_for_ui_role(role, capability, payload=None, default=None):
    return create_shell_addon_service(
        addon_id_for_ui_role(role),
        capability,
        payload=payload,
        default=default,
    )
