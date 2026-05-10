from __future__ import annotations

import importlib.util
import json
import logging
import sys
from pathlib import Path


_MODULE_CACHE = {}
_ADDON_FOLDER_CACHE = {}


def _addons_root(app_root=None) -> Path:
    return Path(app_root).resolve() / "addons" if app_root is not None else Path(__file__).resolve().parents[2] / "addons"


def _addon_folder_for_id(addon_id: str, *, app_root=None) -> str:
    target = str(addon_id or "").strip()
    if not target:
        return ""
    cache_key = (str(_addons_root(app_root)), target)
    if cache_key in _ADDON_FOLDER_CACHE:
        return _ADDON_FOLDER_CACHE[cache_key]
    for manifest_path in sorted(_addons_root(app_root).glob("*/addon.json")):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(payload.get("id") or "").strip() == target:
            folder = manifest_path.parent.name
            _ADDON_FOLDER_CACHE[cache_key] = folder
            return folder
    _ADDON_FOLDER_CACHE[cache_key] = ""
    return ""


def load_addon_module(addon_id: str, *, app_root=None):
    folder = _addon_folder_for_id(addon_id, app_root=app_root)
    if not folder:
        return None
    module_path = _addons_root(app_root) / folder / "main.py"
    if not module_path.exists():
        return None
    cache_key = (str(module_path.resolve()), str(addon_id or "").strip())
    if cache_key in _MODULE_CACHE:
        return _MODULE_CACHE[cache_key]
    module_name = f"_nc_bootstrap_addon_{str(addon_id).replace('.', '_').replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    _MODULE_CACHE[cache_key] = module
    return module


def invoke_addon_capability(addon_id: str, capability: str, payload=None, *, app_root=None, default=None):
    module = load_addon_module(addon_id, app_root=app_root)
    addon_cls = getattr(module, "Addon", None) if module is not None else None
    if addon_cls is None:
        return default
    try:
        addon = addon_cls()
        result = addon.invoke_capability(str(capability or ""), payload or {})
    except Exception:
        logging.getLogger(__name__).exception("Addon capability failed: %s/%s", addon_id, capability)
        return default
    return default if result is None else result
