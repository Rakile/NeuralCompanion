"""Crash and debugging bundle helpers for Neural Companion.

The functions here avoid importing the main engine so they are safe to call
from early startup, exception hooks, and simple smoke tests.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import threading
import time
import traceback
import zipfile
from collections import deque
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parent.parent
_CONSOLE_TAIL_MAX_CHARS = 240_000
_TEXT_FILE_TAIL_BYTES = 220_000
_RECENT_FILE_COUNT = 5
_CONSOLE_TAIL: deque[str] = deque()
_CONSOLE_TAIL_CHARS = 0
_CONSOLE_LOCK = threading.RLock()
_BUNDLE_LOCK = threading.RLock()
_BUNDLE_IN_PROGRESS = False

_SECRET_KEY_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "auth_token",
    "bearer",
    "bridge_token",
    "client_secret",
    "cookie",
    "key",
    "password",
    "pairing_code",
    "secret",
    "token",
)
_REDACTED = "[REDACTED]"


def record_console_text(text: Any) -> None:
    """Keep an in-memory tail of console text for crash bundles."""
    global _CONSOLE_TAIL_CHARS
    value = str(text or "")
    if not value:
        return
    with _CONSOLE_LOCK:
        _CONSOLE_TAIL.append(value)
        _CONSOLE_TAIL_CHARS += len(value)
        while _CONSOLE_TAIL and _CONSOLE_TAIL_CHARS > _CONSOLE_TAIL_MAX_CHARS:
            removed = _CONSOLE_TAIL.popleft()
            _CONSOLE_TAIL_CHARS -= len(removed)


def console_tail() -> str:
    with _CONSOLE_LOCK:
        return "".join(_CONSOLE_TAIL)


def _safe_reason(value: str) -> str:
    text = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or "manual").strip())
    text = "_".join(part for part in text.split("_") if part)
    return text[:48] or "manual"


def _json_default(value: Any) -> str:
    try:
        return str(value)
    except Exception:
        return "<unprintable>"


def _is_secret_key(key: Any) -> bool:
    lowered = str(key or "").strip().lower()
    if not lowered:
        return False
    return any(marker in lowered for marker in _SECRET_KEY_MARKERS)


def redact_secrets(value: Any, *, parent_key: str = "") -> Any:
    """Recursively redact values under secret-looking keys."""
    if _is_secret_key(parent_key):
        if value in (None, "", [], {}):
            return value
        return _REDACTED
    if isinstance(value, dict):
        return {str(key): redact_secrets(item, parent_key=str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_secrets(item, parent_key=parent_key) for item in value]
    if isinstance(value, tuple):
        return [redact_secrets(item, parent_key=parent_key) for item in value]
    return value


def redact_text(text: str) -> str:
    """Best-effort redaction for copied log text."""
    result = str(text or "")
    replacements = (
        "api_key",
        "apikey",
        "authorization",
        "bridge_token",
        "password",
        "secret",
        "token",
    )
    for key in replacements:
        result = _redact_assignment_text(result, key)
    return result


def _redact_assignment_text(text: str, key: str) -> str:
    import re

    pattern = re.compile(rf'({re.escape(key)}["\']?\s*[:=]\s*["\']?)([^"\'\s,}}]+)', re.IGNORECASE)
    return pattern.sub(rf"\1{_REDACTED}", text)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(redact_secrets(payload), indent=2, ensure_ascii=False, default=_json_default) + "\n",
        encoding="utf-8",
    )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(redact_text(str(text or "")), encoding="utf-8", errors="replace")


def _tail_text_file(path: Path, *, max_bytes: int = _TEXT_FILE_TAIL_BYTES) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(max(0, size - max_bytes))
                raw = handle.read(max_bytes)
                prefix = f"[CrashDiag] File tail only; original_size={size} bytes\n"
            else:
                raw = handle.read()
                prefix = ""
    except Exception as exc:
        return f"[CrashDiag] Could not read {path}: {exc}\n"
    return prefix + raw.decode("utf-8", errors="replace")


def _copy_tail_file(source: Path, destination: Path) -> bool:
    try:
        if not source.exists() or not source.is_file():
            return False
        _write_text(destination, _tail_text_file(source))
        return True
    except Exception:
        return False


def _recent_files(directory: Path, pattern: str = "*", *, count: int = _RECENT_FILE_COUNT) -> list[Path]:
    try:
        files = [path for path in directory.glob(pattern) if path.is_file()]
    except Exception:
        return []
    return sorted(files, key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)[:count]


def _package_version(package: str) -> str:
    try:
        return importlib_metadata.version(package)
    except Exception:
        return ""


def _git_head(app_root: Path) -> dict[str, str]:
    git_dir = app_root / ".git"
    result = {"head": "", "ref": "", "commit": ""}
    try:
        head_text = (git_dir / "HEAD").read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return result
    result["head"] = head_text
    if head_text.startswith("ref:"):
        ref = head_text.split(":", 1)[1].strip()
        result["ref"] = ref
        try:
            result["commit"] = (git_dir / ref).read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            result["commit"] = ""
    else:
        result["commit"] = head_text
    return result


def _environment_payload(app_root: Path, reason: str) -> dict[str, Any]:
    return {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "reason": reason,
        "pid": os.getpid(),
        "cwd": os.getcwd(),
        "argv": list(sys.argv),
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "app_root": str(app_root),
        "packages": {
            "PySide6": _package_version("PySide6"),
            "openai": _package_version("openai"),
            "requests": _package_version("requests"),
        },
        "git": _git_head(app_root),
    }


def _thread_dump_text() -> str:
    lines = [f"Thread dump captured {time.strftime('%Y-%m-%d %H:%M:%S')}"]
    current_frames = sys._current_frames()
    for thread in threading.enumerate():
        lines.append("")
        lines.append(f"Thread name={thread.name!r} ident={thread.ident} daemon={thread.daemon}")
        frame = current_frames.get(thread.ident)
        if frame is None:
            lines.append("  <no Python frame>")
            continue
        lines.extend(traceback.format_stack(frame))
    return "\n".join(lines)


def _addon_payload(app_root: Path) -> list[dict[str, Any]]:
    addons_dir = app_root / "addons"
    result = []
    try:
        manifests = sorted(addons_dir.glob("*/addon.json"))
    except Exception:
        return result
    for manifest in manifests:
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
        except Exception as exc:
            payload = {"error": str(exc)}
        if isinstance(payload, dict):
            payload.setdefault("folder", manifest.parent.name)
            result.append(redact_secrets(payload))
    return result


def _read_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        return {"error": f"Could not read {path.name}: {exc}"}


def _write_recent_runtime_files(app_root: Path, bundle_dir: Path, manifest: dict[str, Any]) -> None:
    runtime_dir = app_root / "runtime"
    files_root = bundle_dir / "files"
    for path in _recent_files(runtime_dir / "logs", "*", count=4):
        destination = files_root / "runtime_logs" / path.name
        if _copy_tail_file(path, destination):
            manifest.setdefault("included_files", []).append(str(destination.relative_to(bundle_dir)))
    for path in _recent_files(runtime_dir / "crash_dumps", "nc_crash_*.log", count=3):
        destination = files_root / "recent_crash_logs" / path.name
        if _copy_tail_file(path, destination):
            manifest.setdefault("included_files", []).append(str(destination.relative_to(bundle_dir)))
    companion_debug = runtime_dir / "companion_orb" / "debug" / "companion_orb_debug.log"
    if _copy_tail_file(companion_debug, files_root / "companion_orb_debug_tail.log"):
        manifest.setdefault("included_files", []).append("files/companion_orb_debug_tail.log")
    latency_trace = runtime_dir / "logs" / "tts_addon_latency.jsonl"
    if _copy_tail_file(latency_trace, files_root / "tts_addon_latency_tail.jsonl"):
        manifest.setdefault("included_files", []).append("files/tts_addon_latency_tail.jsonl")


def _zip_directory(source_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file() and path != zip_path:
                archive.write(path, path.relative_to(source_dir).as_posix())


def create_debug_bundle(
    *,
    app_root: Path | str | None = None,
    reason: str = "manual",
    crash_log_path: Path | str | None = None,
    runtime_config: dict[str, Any] | None = None,
    extra_context: dict[str, Any] | None = None,
    zip_bundle: bool = True,
) -> Path:
    """Create a Codex-friendly debug bundle and return the zip or folder path."""
    global _BUNDLE_IN_PROGRESS
    root = Path(app_root or APP_ROOT).resolve()
    safe_reason = _safe_reason(reason)
    with _BUNDLE_LOCK:
        if _BUNDLE_IN_PROGRESS:
            raise RuntimeError("Debug bundle creation is already in progress")
        _BUNDLE_IN_PROGRESS = True
    try:
        bundle_root = root / "runtime" / "debug_bundles"
        bundle_root.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        bundle_dir = bundle_root / f"nc_debug_{stamp}_{safe_reason}"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        manifest: dict[str, Any] = {
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "reason": reason,
            "bundle_dir": str(bundle_dir),
            "crash_log_path": str(crash_log_path or ""),
            "included_files": [],
        }

        _write_text(
            bundle_dir / "README_FOR_CODEX.txt",
            "\n".join(
                [
                    "Neural Companion Codex Debug Bundle",
                    "",
                    f"Reason: {reason}",
                    "",
                    "Send or attach this zip/folder when asking Codex to debug a crash or runtime problem.",
                    "Start with manifest.json, environment.json, latest_crash.log, console_tail.txt,",
                    "runtime_config_redacted.json, qt_session_redacted.json, and thread_dump.txt.",
                    "",
                    "Secrets are redacted from JSON/config files and copied text tails on a best-effort basis.",
                ]
            )
            + "\n",
        )
        _write_json(bundle_dir / "environment.json", _environment_payload(root, reason))
        _write_json(bundle_dir / "addons.json", _addon_payload(root))
        _write_json(bundle_dir / "runtime_config_redacted.json", runtime_config or {})
        _write_json(bundle_dir / "extra_context.json", extra_context or {})
        _write_text(bundle_dir / "console_tail.txt", console_tail() or "[CrashDiag] No console tail captured.\n")
        _write_text(bundle_dir / "thread_dump.txt", _thread_dump_text())

        session_path = root / "qt_session.json"
        if session_path.exists():
            _write_json(bundle_dir / "qt_session_redacted.json", _read_json_file(session_path))
        else:
            _write_json(bundle_dir / "qt_session_redacted.json", {"missing": str(session_path)})

        crash_path = Path(crash_log_path) if crash_log_path else None
        if crash_path is not None and crash_path.exists():
            if _copy_tail_file(crash_path, bundle_dir / "files" / "latest_crash.log"):
                manifest["included_files"].append("files/latest_crash.log")
        _write_recent_runtime_files(root, bundle_dir, manifest)
        _write_json(bundle_dir / "manifest.json", manifest)

        if not zip_bundle:
            return bundle_dir
        zip_path = bundle_dir.with_suffix(".zip")
        _zip_directory(bundle_dir, zip_path)
        return zip_path
    finally:
        with _BUNDLE_LOCK:
            _BUNDLE_IN_PROGRESS = False


def create_manual_debug_bundle(app_root: Path | str | None = None) -> Path:
    return create_debug_bundle(app_root=app_root, reason="manual")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]).resolve() if args else APP_ROOT
    bundle = create_manual_debug_bundle(root)
    print(f"Codex debug bundle created: {bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
