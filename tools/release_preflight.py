#!/usr/bin/env python3
"""Public release preflight checks.

This helper is intentionally conservative. It checks the repository state that
is easy to verify without launching the full GUI or loading models.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "README.md",
    "LICENSE",
    "CONTRIBUTING.md",
    "requirements.txt",
    "requirements.companion.txt",
    "requirements.musetalk.txt",
    "docs/install.md",
    "docs/release_checklist.md",
    "docs/release_asset_policy.md",
    "docs/third_party_and_assets.md",
    "docs/known_limitations.md",
    "docs/troubleshooting.md",
    "docs/avatar_packs.md",
]

FORBIDDEN_TRACKED_PREFIXES = (
    "runtime/",
    "MuseTalk/runtime/",
    ".venv/",
    "venv/",
    "__pycache__/",
)

FORBIDDEN_TRACKED_PARTS = (
    "/__pycache__/",
    "/.venv/",
    "/venv/",
    "/crash_dumps/",
)

FORBIDDEN_TRACKED_SUFFIXES = (
    ".7z",
    ".zip",
    ".rar",
    ".tar",
    ".gz",
    ".wav",
    ".mp3",
    ".mp4",
    ".mov",
    ".avi",
    ".npy",
    ".npz",
    ".pt",
    ".pth",
    ".safetensors",
    ".ckpt",
    ".log",
    ".pyc",
)

ALLOWED_TRACKED_ASSET_PATHS = {
    "avatar_packs/.gitkeep",
    "avatar_packs/README.md",
    "Installer_Music/Circuit_Saffron.mp3",
    "MuseTalk/musetalk/whisper/whisper/assets/mel_filters.npz",
    "voices/.gitkeep",
    "voices/README.md",
}

ALLOWED_TRACKED_SUFFIXES = (
    ".png",
    ".ico",
    ".svg",
)

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"xai-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"ANTHROPIC_API_KEY\s*=\s*[^\\s\"']+", re.IGNORECASE),
    re.compile(r"OPENAI_API_KEY\s*=\s*[^\\s\"']+", re.IGNORECASE),
]

BINARY_SUFFIXES = {
    ".7z",
    ".zip",
    ".rar",
    ".tar",
    ".gz",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".wav",
    ".mp3",
    ".mp4",
    ".dll",
    ".exe",
    ".pyd",
    ".pyc",
}


def _run_git(app_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(app_root), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _git_available(app_root: Path) -> bool:
    result = _run_git(app_root, ["rev-parse", "--is-inside-work-tree"])
    return result.returncode == 0 and result.stdout.strip() == "true"


def _tracked_files(app_root: Path) -> list[str]:
    result = _run_git(app_root, ["ls-files"])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git ls-files failed")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _is_forbidden_tracked_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized in ALLOWED_TRACKED_ASSET_PATHS:
        return ""
    if normalized.startswith("avatar_packs/") or normalized.startswith("voices/"):
        return "voice/avatar pack content must stay outside the main repo"
    if any(normalized.startswith(prefix) for prefix in FORBIDDEN_TRACKED_PREFIXES):
        return "runtime/cache/local environment path must not be tracked"
    if any(part in f"/{normalized}" for part in FORBIDDEN_TRACKED_PARTS):
        return "runtime/cache/local environment path must not be tracked"
    suffix = Path(normalized).suffix.lower()
    if suffix in FORBIDDEN_TRACKED_SUFFIXES and suffix not in ALLOWED_TRACKED_SUFFIXES:
        return f"tracked forbidden release asset suffix {suffix}"
    return ""


def _read_text(path: Path) -> str | None:
    if path.suffix.lower() in BINARY_SUFFIXES:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def check_required_files(app_root: Path) -> list[str]:
    missing = [relative for relative in REQUIRED_FILES if not (app_root / relative).exists()]
    return [f"missing required release file: {relative}" for relative in missing]


def check_git_clean(app_root: Path) -> list[str]:
    if not _git_available(app_root):
        return ["not a git worktree; run this in the sync/release checkout before tagging"]
    result = _run_git(app_root, ["status", "--short"])
    if result.returncode != 0:
        return [result.stderr.strip() or "git status failed"]
    dirty = result.stdout.strip()
    return [] if not dirty else ["git status is not clean:\n" + dirty]


def check_tracked_assets(app_root: Path) -> list[str]:
    if not _git_available(app_root):
        return []
    failures = []
    for relative in _tracked_files(app_root):
        reason = _is_forbidden_tracked_path(relative)
        if reason:
            failures.append(f"{relative}: {reason}")
    return failures


def check_tracked_secrets(app_root: Path) -> list[str]:
    if not _git_available(app_root):
        return []
    failures = []
    for relative in _tracked_files(app_root):
        text = _read_text(app_root / relative)
        if text is None:
            continue
        for index, line in enumerate(text.splitlines(), start=1):
            for pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    failures.append(f"{relative}:{index}: possible secret value")
                    break
    return failures


def check_local_release_debris(app_root: Path) -> list[str]:
    warnings = []
    debris_roots = ["runtime", "MuseTalk/runtime", "avatar_packs", "voices"]
    for relative in debris_roots:
        root = app_root / relative
        if not root.exists():
            continue
        visible = [
            child
            for child in root.iterdir()
            if child.name not in {".gitkeep", "README.md"} and not child.name.startswith(".")
        ]
        if visible:
            warnings.append(f"{relative}/ contains local release-excluded files ({len(visible)} item(s))")
    return warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run public release preflight checks.")
    parser.add_argument("--app-root", default=str(APP_ROOT), help="Repository root to check.")
    parser.add_argument("--allow-dirty", action="store_true", help="Do not fail on dirty git status.")
    args = parser.parse_args(argv)

    app_root = Path(args.app_root).resolve()
    failures: list[str] = []
    warnings: list[str] = []

    failures.extend(check_required_files(app_root))
    if args.allow_dirty:
        warnings.extend(check_git_clean(app_root))
    else:
        failures.extend(check_git_clean(app_root))
    failures.extend(check_tracked_assets(app_root))
    failures.extend(check_tracked_secrets(app_root))
    warnings.extend(check_local_release_debris(app_root))

    if warnings:
        print("release-preflight warnings:")
        for item in warnings:
            print(f"  - {item}")
    if failures:
        print("release-preflight failed:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("release-preflight: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
