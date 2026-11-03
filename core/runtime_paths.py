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

