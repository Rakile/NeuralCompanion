from __future__ import annotations

import importlib.util
import json
import logging
import sys
from pathlib import Path

_MODULE_CACHE = {}
_ADDON_FOLDER_CACHE = {}
_PRIMARY_APP_ROOT = Path(__file__).resolve().parents[2]

# These are the base-HEAD bootstrap calls that construct or query stateless
# compatibility values before the manager owns enabled addon contexts.
_FROZEN_STATELESS_CAPABILITIES = {
    "nc.visual_reply": frozenset({"runtime.host_capabilities"}),
    "nc.musetalk_avatar": frozenset(
        {
            "runtime.normalize_enabled_pack_emotions",
            "runtime.enabled_pack_emotions",
            "runtime.available_pack_emotion_names",
            "runtime.pack_catalog",
            "runtime.select_pack",
            "runtime.preview.estimate_displayed_frames",
            "runtime.preview.current_source_index",
        }
    ),
}


class RuntimeConfigSnapshotSource:
    """Typed bootstrap reader that keeps the engine callback inside core."""

    def __init__(self, read_snapshot):
        self._read_snapshot = read_snapshot

    def snapshot(self):
        return dict(self._read_snapshot() or {})


class VisualReplyPublicationGate:
    """Typed bootstrap publication gate for Visual Reply completion."""

    def __init__(self, allow_publication):
        self._allow_publication = allow_publication

    def allow(self, payload):
        return self._allow_publication(dict(payload or {}))


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


def _bootstrap_addon_is_enabled(addon_id: str, *, app_root=None) -> bool:
    target = str(addon_id or "").strip()
    if not target:
        return False
    manifest = None
    for manifest_path in sorted(_addons_root(app_root).glob("*/addon.json")):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(payload.get("id") or "").strip() == target:
            manifest = payload
            break
    if manifest is None or not bool(manifest.get("enabled", True)):
        return False
    registry_path = _addons_root(app_root).parent / "runtime" / "addons" / "addon_registry.json"
    if not registry_path.exists():
        return True
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(registry, dict):
        return False
    addons = registry.get("addons")
    if isinstance(addons, dict) and target in addons and not bool(addons[target]):
        return False
    category = str(manifest.get("category") or "other").strip().lower() or "other"
    categories = registry.get("categories")
    return not (
        isinstance(categories, dict)
        and category in categories
        and not bool(categories[category])
    )


def _uses_primary_app_root(app_root) -> bool:
    if app_root is None:
        return True
    try:
        return Path(app_root).resolve() == _PRIMARY_APP_ROOT
    except OSError:
        return False


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
    target = str(addon_id or "").strip()
    requested = str(capability or "").strip()
    if requested not in _FROZEN_STATELESS_CAPABILITIES.get(target, ()):
        return default
    if not _bootstrap_addon_is_enabled(target, app_root=app_root):
        return default
    if (
        target == "nc.visual_reply"
        and requested == "runtime.host_capabilities"
        and _uses_primary_app_root(app_root)
    ):
        from addons.visual_reply.runtime_capabilities import (
            create_runtime_capabilities,
        )

        values = dict(payload or {})
        try:
            return create_runtime_capabilities(
                RuntimeConfigSnapshotSource(values["config_getter"]),
                environ=values.get("environ"),
                output_dir=values.get("output_dir"),
                publication_gate=VisualReplyPublicationGate(values["before_publish"]),
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "Visual Reply bootstrap capability construction failed"
            )
            return default
    module = load_addon_module(target, app_root=app_root)
    addon_cls = getattr(module, "Addon", None) if module is not None else None
    if addon_cls is None:
        return default
    try:
        addon = addon_cls()
        result = addon.invoke_capability(requested, payload or {})
    except Exception:
        logging.getLogger(__name__).exception("Addon capability failed: %s/%s", addon_id, capability)
        return default
    return default if result is None else result
