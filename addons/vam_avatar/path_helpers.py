"""VaM path detection and normalization helpers owned by the VaM addon."""

from __future__ import annotations

import os
from pathlib import Path

from core.runtime_paths import normalized_abs_path, path_endswith_parts


def detect_default_root(*, app_root: Path, environ=None) -> str:
    env = environ if environ is not None else os.environ
    env_root = str(env.get("NC_VAM_ROOT", "") or "").strip()
    if env_root:
        return normalized_abs_path(env_root)

    root = Path(app_root)
    candidates = [
        root.parent / "VaM 1.20.0.6",
        root.parent / "VaM",
    ]
    for candidate in candidates:
        try:
            if candidate.exists():
                return str(candidate.resolve())
        except Exception:
            continue
    return ""


def derive_bridge_root(vam_root, *, app_root: Path) -> str:
    normalized_root = normalized_abs_path(vam_root) if str(vam_root or "").strip() else ""
    if not normalized_root:
        return normalized_abs_path(Path(app_root) / "runtime" / "vam_bridge")
    return normalized_abs_path(Path(normalized_root) / "Custom" / "PluginData" / "NeuralCompanionBridge")


def derive_plugin_dir(vam_root) -> str:
    normalized_root = normalized_abs_path(vam_root) if str(vam_root or "").strip() else ""
    if not normalized_root:
        return ""
    return normalized_abs_path(Path(normalized_root) / "Custom" / "Scripts" / "NeuralCompanionBridge")


def legacy_bridge_roots(*, app_root: Path) -> tuple[str, ...]:
    root = Path(app_root)
    return tuple(
        dict.fromkeys(
            [
                normalized_abs_path(root.parent / "VaM 1.20.0.6" / "Custom" / "PluginData" / "NeuralCompanionBridge"),
                normalized_abs_path(root.parent / "VaM" / "Custom" / "PluginData" / "NeuralCompanionBridge"),
                normalized_abs_path(root / "runtime" / "vam_bridge"),
            ]
        )
    )


def normalize_root(raw_value=None, *, default_root: str = "", legacy_roots: tuple[str, ...] = (), migrate_legacy=True) -> str:
    value = str(raw_value or "").strip()
    if not value:
        return default_root
    normalized = normalized_abs_path(value)
    if path_endswith_parts(normalized, "Custom", "PluginData", "NeuralCompanionBridge"):
        return normalized_abs_path(Path(normalized).parent.parent.parent)
    if path_endswith_parts(normalized, "Custom", "Scripts", "NeuralCompanionBridge"):
        return normalized_abs_path(Path(normalized).parent.parent.parent)
    if migrate_legacy and normalized in set(legacy_roots or ()):
        return default_root
    return normalized


def normalize_bridge_root(raw_value=None, *, app_root: Path, default_root: str = "", legacy_roots: tuple[str, ...] = (), migrate_legacy=True) -> str:
    return derive_bridge_root(
        normalize_root(
            raw_value,
            default_root=default_root,
            legacy_roots=legacy_roots,
            migrate_legacy=migrate_legacy,
        ),
        app_root=app_root,
    )
