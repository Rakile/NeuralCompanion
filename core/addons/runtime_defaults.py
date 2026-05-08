from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def addon_runtime_defaults(app_root: str | Path, *, environ=None) -> dict[str, Any]:
    """Collect runtime defaults declared by effectively enabled addon manifests."""

    app_root = Path(app_root)
    addons_root = app_root / "addons"
    if not addons_root.exists():
        return {}
    registry_state = _addon_registry_state(app_root)
    defaults: dict[str, Any] = {}
    for manifest_path in sorted(addons_root.glob("*/addon.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(manifest, dict):
            continue
        if not _manifest_effectively_enabled(manifest, registry_state):
            continue
        runtime_defaults = manifest.get("runtime_defaults")
        if isinstance(runtime_defaults, dict):
            defaults.update({str(key): value for key, value in runtime_defaults.items()})
        env_overrides = manifest.get("runtime_env_overrides")
        if isinstance(env_overrides, dict):
            env = environ or {}
            for key, env_name in env_overrides.items():
                env_value = env.get(str(env_name or ""))
                if env_value is not None:
                    defaults[str(key)] = _coerce_env_value(defaults.get(str(key)), env_value)
    return defaults


def _addon_registry_state(app_root: Path) -> dict[str, Any]:
    registry_path = app_root / "runtime" / "addons" / "addon_registry.json"
    try:
        if registry_path.exists():
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
    except Exception:
        return {}
    return {}


def _manifest_effectively_enabled(manifest: dict[str, Any], registry_state: dict[str, Any]) -> bool:
    addon_id = str(manifest.get("id") or "").strip()
    category = str(manifest.get("category") or "other").strip().lower() or "other"
    manifest_enabled = bool(manifest.get("enabled", True))
    categories = dict((registry_state or {}).get("categories", {}) or {})
    addons = dict((registry_state or {}).get("addons", {}) or {})
    category_enabled = bool(categories.get(category, True))
    addon_enabled = bool(addons.get(addon_id, manifest_enabled))
    return bool(category_enabled and addon_enabled)


def _coerce_env_value(default_value: Any, raw_value: Any) -> Any:
    if isinstance(default_value, bool):
        return str(raw_value or "").strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(default_value, int) and not isinstance(default_value, bool):
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            return default_value
    if isinstance(default_value, float):
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            return default_value
    if isinstance(default_value, (dict, list)):
        try:
            return json.loads(raw_value)
        except Exception:
            return default_value
    return raw_value
