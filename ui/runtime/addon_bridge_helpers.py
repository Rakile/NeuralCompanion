"""Small bridge-discovery helpers for addon-owned runtime hooks.

The Qt backend still owns the application lifecycle, but addon-specific UI
bridges should be discovered from registered addon metadata wherever possible.
Fallback maps keep legacy/internal providers working while the addon UI surface
continues moving out of qt_app.py.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Iterable

from core import avatar_runtime


_TTS_BRIDGE_FALLBACKS = {
    "chatterbox": "addons.chatterbox_tts.real_ui_bridge",
    "pockettts": "addons.pockettts.real_ui_bridge",
}

_AVATAR_BRIDGE_FALLBACKS = {
    "musetalk": "addons.musetalk_avatar.real_ui_bridge",
    "vam": "addons.vam_avatar.real_ui_bridge",
    "vseeface": "addons.vseeface_avatar.real_ui_bridge",
    "none": "addons.no_avatar.real_ui_bridge",
}

_ADDON_BRIDGE_FALLBACKS = {
    "nc.visual_reply": "addons.visual_reply.real_ui_bridge",
    "visual_reply": "addons.visual_reply.real_ui_bridge",
}


def _import_bridge_module(module_name):
    name = str(module_name or "").strip()
    if not name:
        return None
    try:
        return importlib.import_module(name)
    except Exception:
        return None


def _unique_modules(module_names: Iterable[str]):
    seen = set()
    modules = []
    for module_name in module_names:
        name = str(module_name or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        module = _import_bridge_module(name)
        if module is not None:
            modules.append(module)
    return modules


def _service_entries(backend):
    manager = getattr(backend, "_addon_manager", None)
    if manager is None:
        return []
    try:
        return list(manager.list_registered_services() or [])
    except Exception:
        return []


def _loaded_addon_ids(backend):
    manager = getattr(backend, "_addon_manager", None)
    if manager is None:
        return []
    try:
        records = list(manager.get_loaded_addons() or [])
    except Exception:
        return []
    addon_ids = []
    for record in records:
        if str(getattr(record, "state", "") or "") != "initialized":
            continue
        manifest = getattr(record, "manifest", None)
        addon_id = str(getattr(manifest, "id", "") or "").strip()
        if addon_id:
            addon_ids.append(addon_id)
    return addon_ids


def _addon_manifest_bridge_modules(backend, addon_id):
    manager = getattr(backend, "_addon_manager", None)
    if manager is None:
        return []
    try:
        record = manager.get_addon_record(str(addon_id or "").strip())
    except Exception:
        record = None
    if record is None or str(getattr(record, "state", "") or "") != "initialized":
        return []
    manifest = getattr(record, "manifest", None)
    module_names = []
    for entry in list(getattr(manifest, "ui", []) or []):
        if not isinstance(entry, dict):
            continue
        metadata = dict(entry.get("metadata") or {})
        module_name = (
            metadata.get("real_ui_bridge_module")
            or metadata.get("ui_bridge_module")
            or entry.get("real_ui_bridge_module")
            or entry.get("ui_bridge_module")
            or ""
        )
        if module_name:
            module_names.append(module_name)
    return module_names


def tts_bridge_modules(backend):
    module_names = []
    for entry in _service_entries(backend):
        metadata = dict(entry.get("metadata") or {})
        kind = str(metadata.get("kind") or "").strip().lower()
        if kind not in {"tts", "tts_backend", "text_to_speech"}:
            continue
        backend_id = str(metadata.get("backend_id") or entry.get("name") or "").strip().lower()
        module_name = metadata.get("real_ui_bridge_module") or metadata.get("ui_bridge_module") or ""
        if module_name:
            module_names.append(module_name)
        elif getattr(backend, "_addon_manager", None) is None:
            module_names.append(_TTS_BRIDGE_FALLBACKS.get(backend_id, ""))
    if not module_names and getattr(backend, "_addon_manager", None) is None:
        module_names.extend(_TTS_BRIDGE_FALLBACKS.values())
    return _unique_modules(module_names)


def avatar_bridge_modules(backend):
    module_names = []
    for provider in avatar_runtime.list_providers():
        summary = provider.to_summary()
        metadata = dict(summary.get("metadata") or {})
        provider_id = str(summary.get("id") or "").strip().lower()
        module_name = metadata.get("real_ui_bridge_module") or metadata.get("ui_bridge_module") or ""
        if module_name:
            module_names.append(module_name)
        elif getattr(backend, "_addon_manager", None) is None:
            module_names.append(_AVATAR_BRIDGE_FALLBACKS.get(provider_id, ""))
    if not module_names and getattr(backend, "_addon_manager", None) is None:
        module_names.extend(_AVATAR_BRIDGE_FALLBACKS.values())
    return _unique_modules(module_names)


def avatar_bridge_module_for_provider(provider_id):
    selected = str(provider_id or "").strip().lower()
    if not selected:
        return None
    provider = avatar_runtime.get_provider(selected)
    module_name = ""
    if provider is not None:
        summary = provider.to_summary()
        metadata = dict(summary.get("metadata") or {})
        module_name = str(metadata.get("real_ui_bridge_module") or metadata.get("ui_bridge_module") or "").strip()
    if not module_name:
        module_name = _AVATAR_BRIDGE_FALLBACKS.get(selected, "")
    return _import_bridge_module(module_name)


def tts_bridge_module_for_backend(backend, tts_backend):
    selected = str(tts_backend or "").strip().lower()
    if not selected:
        return None
    for entry in _service_entries(backend):
        metadata = dict(entry.get("metadata") or {})
        backend_id = str(metadata.get("backend_id") or entry.get("name") or "").strip().lower()
        if backend_id != selected:
            continue
        module_name = str(metadata.get("real_ui_bridge_module") or metadata.get("ui_bridge_module") or "").strip()
        if not module_name and getattr(backend, "_addon_manager", None) is None:
            module_name = _TTS_BRIDGE_FALLBACKS.get(selected, "")
        return _import_bridge_module(module_name)
    if getattr(backend, "_addon_manager", None) is None:
        return _import_bridge_module(_TTS_BRIDGE_FALLBACKS.get(selected, ""))
    return None


def named_addon_bridge_modules(backend, addon_ids):
    loaded = {str(addon_id or "").strip() for addon_id in _loaded_addon_ids(backend)}
    module_names = []
    for addon_id in addon_ids:
        normalized = str(addon_id or "").strip()
        if not normalized:
            continue
        if loaded and normalized not in loaded:
            continue
        manifest_modules = _addon_manifest_bridge_modules(backend, normalized)
        if manifest_modules:
            module_names.extend(manifest_modules)
        else:
            module_names.append(_ADDON_BRIDGE_FALLBACKS.get(normalized, ""))
    if not loaded and getattr(backend, "_addon_manager", None) is None:
        for addon_id in addon_ids:
            module_names.append(_ADDON_BRIDGE_FALLBACKS.get(str(addon_id or "").strip(), ""))
    return _unique_modules(module_names)


def call_bridge_hook(module, hook_name, *args, **kwargs):
    hook = getattr(module, str(hook_name or ""), None)
    if not callable(hook):
        return None
    try:
        signature = inspect.signature(hook)
    except (TypeError, ValueError):
        return hook(*args, **kwargs)
    parameters = signature.parameters
    accepts_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    accepts_args = any(
        parameter.kind == inspect.Parameter.VAR_POSITIONAL
        for parameter in parameters.values()
    )
    if accepts_args:
        positional_args = args
    else:
        positional_parameters = [
            parameter
            for parameter in parameters.values()
            if parameter.kind in {
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            }
        ]
        positional_args = args[: len(positional_parameters)]
    if accepts_kwargs:
        return hook(*positional_args, **kwargs)
    filtered = {
        key: value
        for key, value in kwargs.items()
        if key in parameters
    }
    return hook(*positional_args, **filtered)


def merge_bridge_dicts(modules, hook_name, *args, **kwargs):
    payload = {}
    for module in modules:
        result = call_bridge_hook(module, hook_name, *args, **kwargs)
        if isinstance(result, dict):
            payload.update(result)
    return payload


def collect_bridge_items(modules, hook_name, *args, **kwargs):
    items = []
    for module in modules:
        result = call_bridge_hook(module, hook_name, *args, **kwargs)
        if result:
            items.extend(list(result))
    return items
