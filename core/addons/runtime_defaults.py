from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AddonRuntimeDefaultDeclaration:
    addon_id: str
    config_key: str
    default_value: Any
    manifest_path: Path


RUNTIME_DEFAULT_OWNER_OVERRIDES = {
    "ua_companion_orb_send_musetalk_face_mask": "nc.ua_companion_orb_overlay",
}


def addon_runtime_defaults(app_root: str | Path, *, environ=None) -> dict[str, Any]:
    """Collect runtime defaults declared by effectively enabled addon manifests."""

    winners: dict[str, AddonRuntimeDefaultDeclaration] = {}
    for declaration in addon_runtime_default_declarations(app_root, environ=environ):
        winner = winners.get(declaration.config_key)
        if winner is None:
            winners[declaration.config_key] = declaration
            continue
        override_owner = RUNTIME_DEFAULT_OWNER_OVERRIDES.get(declaration.config_key)
        if override_owner == declaration.addon_id:
            winners[declaration.config_key] = declaration
            continue
        if override_owner == winner.addon_id:
            continue
        winners[declaration.config_key] = declaration
    return {key: value.default_value for key, value in winners.items()}


def addon_runtime_default_declarations(
    app_root: str | Path,
    *,
    environ=None,
) -> tuple[AddonRuntimeDefaultDeclaration, ...]:
    app_root = Path(app_root)
    addons_root = app_root / "addons"
    if not addons_root.exists():
        return ()
    registry_state = _addon_registry_state(app_root)
    env = environ or {}
    declarations: list[AddonRuntimeDefaultDeclaration] = []
    for manifest_path in sorted(addons_root.glob("*/addon.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(manifest, dict):
            continue
        if not _manifest_effectively_enabled(manifest, registry_state):
            continue
        addon_id = str(manifest.get("id") or "").strip()
        if not addon_id:
            continue
        runtime_defaults = manifest.get("runtime_defaults")
        if not isinstance(runtime_defaults, dict):
            runtime_defaults = {}
        default_values = {str(key): value for key, value in runtime_defaults.items()}
        env_overrides = manifest.get("runtime_env_overrides")
        if isinstance(env_overrides, dict):
            for key, env_name in env_overrides.items():
                normalized_key = str(key)
                env_value = env.get(str(env_name or ""))
                if env_value is not None:
                    default_values[normalized_key] = _coerce_env_value(
                        default_values.get(normalized_key),
                        env_value,
                    )
        for key, value in default_values.items():
            declarations.append(
                AddonRuntimeDefaultDeclaration(
                    addon_id=addon_id,
                    config_key=key,
                    default_value=value,
                    manifest_path=manifest_path,
                )
            )
    return tuple(declarations)


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


__all__ = [
    "AddonRuntimeDefaultDeclaration",
    "RUNTIME_DEFAULT_OWNER_OVERRIDES",
    "addon_runtime_default_declarations",
    "addon_runtime_defaults",
]
