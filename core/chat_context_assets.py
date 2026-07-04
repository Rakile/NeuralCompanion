from __future__ import annotations

import copy
import hashlib
import shutil
from pathlib import Path
from typing import Any


_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def _context_path(path: Any) -> Path:
    return Path(str(path or "")).expanduser().resolve()


def _assets_image_dir(context_path: Path) -> Path:
    return context_path.parent / f"{context_path.stem}_assets" / "images"


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _resolve_attachment_path(raw_path: Any, context_path: Path) -> Path:
    path = Path(str(raw_path or "")).expanduser()
    if path.is_absolute():
        return path
    return context_path.parent / path


def _relative_attachment_path(path: Path, context_path: Path) -> str:
    try:
        return path.resolve().relative_to(context_path.parent.resolve()).as_posix()
    except Exception:
        return str(path.resolve())


def _image_extension(path: Path) -> str:
    suffix = path.suffix.lower()
    return suffix if suffix in _IMAGE_EXTENSIONS else ".img"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def preserve_chat_context_image_assets(payload: dict[str, Any], context_path: Any) -> tuple[dict[str, Any], dict[str, int]]:
    """Copy chat-turn image attachments beside a saved chat context.

    The saved JSON uses paths relative to the context file when possible, so the
    context file and its sibling asset folder can move together.
    """

    target = _context_path(context_path)
    asset_dir = _assets_image_dir(target)
    preserved = copy.deepcopy(dict(payload or {}))
    report = {"copied": 0, "reused": 0, "missing": 0}
    history = preserved.get("conversation_history")
    if not isinstance(history, list):
        return preserved, report

    for turn in history:
        if not isinstance(turn, dict):
            continue
        raw_path = str(turn.get("attachment_image_path", "") or "").strip()
        if not raw_path:
            continue
        source_path = _resolve_attachment_path(raw_path, target)
        if not source_path.is_file():
            turn["attachment_missing_on_save"] = True
            turn["attachment_preservation_error"] = "missing_file"
            report["missing"] += 1
            continue

        resolved_source = source_path.resolve()
        resolved_asset_dir = asset_dir.resolve()
        if _is_relative_to(resolved_source, resolved_asset_dir):
            turn["attachment_image_path"] = _relative_attachment_path(resolved_source, target)
            turn.pop("attachment_missing_on_save", None)
            turn.pop("attachment_preservation_error", None)
            report["reused"] += 1
            continue

        digest = _file_sha256(resolved_source)
        destination = asset_dir / f"sha256_{digest}{_image_extension(resolved_source)}"
        if destination.exists():
            report["reused"] += 1
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(resolved_source, destination)
            report["copied"] += 1
        turn["attachment_image_path"] = _relative_attachment_path(destination, target)
        turn.pop("attachment_missing_on_save", None)
        turn.pop("attachment_preservation_error", None)

    return preserved, report


def resolve_chat_context_image_assets(payload: dict[str, Any], context_path: Any) -> dict[str, Any]:
    resolved = copy.deepcopy(dict(payload or {}))
    target = _context_path(context_path)
    history = resolved.get("conversation_history")
    if not isinstance(history, list):
        return resolved
    for turn in history:
        if not isinstance(turn, dict):
            continue
        raw_path = str(turn.get("attachment_image_path", "") or "").strip()
        if not raw_path:
            continue
        path = Path(raw_path).expanduser()
        if path.is_absolute():
            continue
        candidate = (target.parent / path).resolve()
        if candidate.exists():
            turn["attachment_image_path"] = str(candidate)
    return resolved


__all__ = [
    "preserve_chat_context_image_assets",
    "resolve_chat_context_image_assets",
]
