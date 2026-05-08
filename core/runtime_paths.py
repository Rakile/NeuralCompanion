"""Runtime path normalization helpers."""

from __future__ import annotations

import os
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = APP_ROOT / "runtime"
RUNTIME_TEMP_DIR = RUNTIME_DIR / "temp"


def normalized_abs_path(raw_path) -> str:
    return os.path.abspath(os.path.expanduser(str(raw_path or "").strip()))


def runtime_temp_dir(*parts, create: bool = True) -> Path:
    """Return an app-local transient directory instead of the OS temp folder."""
    path = RUNTIME_TEMP_DIR
    for part in parts:
        clean = str(part or "").strip()
        if clean:
            path = path / clean
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def runtime_temp_file(filename: str, *parts, create_parent: bool = True) -> Path:
    clean_name = str(filename or "").strip()
    if not clean_name:
        raise ValueError("runtime temp filename is required")
    return runtime_temp_dir(*parts, create=create_parent) / clean_name


def path_endswith_parts(path_value, *parts) -> bool:
    try:
        normalized = Path(normalized_abs_path(path_value))
    except Exception:
        return False
    expected = tuple(str(part).lower() for part in parts)
    actual = tuple(part.lower() for part in normalized.parts[-len(expected):])
    return bool(expected) and actual == expected


def detect_default_vam_root(*, app_root: Path, environ=None) -> str:
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


def derive_vam_bridge_root(vam_root, *, app_root: Path) -> str:
    normalized_root = normalized_abs_path(vam_root) if str(vam_root or "").strip() else ""
    if not normalized_root:
        return normalized_abs_path(Path(app_root) / "runtime" / "vam_bridge")
    return normalized_abs_path(Path(normalized_root) / "Custom" / "PluginData" / "NeuralCompanionBridge")


def derive_vam_plugin_dir(vam_root) -> str:
    normalized_root = normalized_abs_path(vam_root) if str(vam_root or "").strip() else ""
    if not normalized_root:
        return ""
    return normalized_abs_path(Path(normalized_root) / "Custom" / "Scripts" / "NeuralCompanionBridge")


def legacy_vam_bridge_roots(*, app_root: Path) -> tuple[str, ...]:
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


def normalize_vam_root(raw_value=None, *, default_vam_root: str = "", legacy_roots: tuple[str, ...] = (), migrate_legacy=True) -> str:
    value = str(raw_value or "").strip()
    if not value:
        return default_vam_root
    normalized = normalized_abs_path(value)
    if path_endswith_parts(normalized, "Custom", "PluginData", "NeuralCompanionBridge"):
        return normalized_abs_path(Path(normalized).parent.parent.parent)
    if path_endswith_parts(normalized, "Custom", "Scripts", "NeuralCompanionBridge"):
        return normalized_abs_path(Path(normalized).parent.parent.parent)
    if migrate_legacy and normalized in set(legacy_roots or ()):
        return default_vam_root
    return normalized


def normalize_vam_bridge_root(raw_value=None, *, app_root: Path, default_vam_root: str = "", legacy_roots: tuple[str, ...] = (), migrate_legacy=True) -> str:
    return derive_vam_bridge_root(
        normalize_vam_root(
            raw_value,
            default_vam_root=default_vam_root,
            legacy_roots=legacy_roots,
            migrate_legacy=migrate_legacy,
        ),
        app_root=app_root,
    )
