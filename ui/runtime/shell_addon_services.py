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


def _addon_entry_path(addon_id):
    addon_id = str(addon_id or "").strip()
    if not addon_id:
        return None
    if addon_id in _ADDON_ENTRY_BY_ID:
        return _ADDON_ENTRY_BY_ID[addon_id]
    addons_root = Path(__file__).resolve().parents[2] / "addons"
    for manifest_path in sorted(addons_root.glob("*/addon.json")):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(payload.get("id") or "").strip() != addon_id:
            continue
        entry_point = str(payload.get("entry_point") or "main.py").strip() or "main.py"
        entry_path = manifest_path.parent / entry_point
        _ADDON_ENTRY_BY_ID[addon_id] = entry_path
        return entry_path
    _ADDON_ENTRY_BY_ID[addon_id] = None
    return None


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
