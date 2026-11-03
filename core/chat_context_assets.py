from __future__ import annotations

from core.image_attachments import image_paths, set_image_paths

import copy
import hashlib
import json
import logging
import re
import shutil
from collections.abc import Mapping
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


def _mutable_payload_copy(value: Any) -> Any:
    """Copy frozen runtime snapshot containers into saved-data containers."""

    if isinstance(value, Mapping):
        return {
            copy.deepcopy(key): _mutable_payload_copy(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_mutable_payload_copy(item) for item in value]
    return copy.deepcopy(value)


def _image_entries(history):
    for turn in history:
        if not isinstance(turn, dict):
            continue
        paths = image_paths(turn)
        if len(paths) > 1:
            updated_paths = []
            missing = False
            for path in paths:
                entry = {'path': path}
                for key in ('attachment_missing_on_save', 'attachment_preservation_error'):
                    if key in turn:
                        entry[key] = turn[key]
                yield entry, 'path', 'attachment'
                updated_paths.append(entry['path'])
                missing = missing or bool(entry.get('attachment_missing_on_save'))
            set_image_paths(turn, updated_paths)
            if missing:
                turn['attachment_missing_on_save'] = True
                turn['attachment_preservation_error'] = 'missing_file'
            else:
                turn.pop('attachment_missing_on_save', None)
                turn.pop('attachment_preservation_error', None)
        else:
            yield turn, 'attachment_image_path', 'attachment'
        capture = turn.get('orb_watch_capture')
        if isinstance(capture, dict):
            yield capture, 'image_path', 'capture'
        for capture in turn.get('orb_watch_captures') or []:
            if isinstance(capture,dict):
                yield capture,'image_path','capture'


def preserve_chat_context_image_assets(payload: Mapping[str, Any], context_path: Any) -> tuple[dict[str, Any], dict[str, int]]:
    """Copy chat-turn image attachments beside a saved chat context.

    The saved JSON uses paths relative to the context file when possible, so the
    context file and its sibling asset folder can move together.
    """

    target = _context_path(context_path)
    asset_dir = _assets_image_dir(target)
    preserved = _mutable_payload_copy(payload or {})
    report = {"copied": 0, "reused": 0, "missing": 0}
    history = preserved.get("conversation_history")
    if not isinstance(history, list):
        return preserved, report

    for turn, path_key, error_prefix in _image_entries(history):
        raw_path = str(turn.get(path_key, "") or "").strip()
        if not raw_path:
            continue
        source_path = _resolve_attachment_path(raw_path, target)
        if not source_path.is_file():
            turn[f"{error_prefix}_missing_on_save"] = True
            turn[f"{error_prefix}_preservation_error"] = "missing_file"
            report["missing"] += 1
            continue

        resolved_source = source_path.resolve()
        resolved_asset_dir = asset_dir.resolve()
        if _is_relative_to(resolved_source, resolved_asset_dir):
            turn[path_key] = _relative_attachment_path(resolved_source, target)
            turn.pop(f"{error_prefix}_missing_on_save", None)
            turn.pop(f"{error_prefix}_preservation_error", None)
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
        turn[path_key] = _relative_attachment_path(destination, target)
        turn.pop(f"{error_prefix}_missing_on_save", None)
        turn.pop(f"{error_prefix}_preservation_error", None)

    return preserved, report


def resolve_chat_context_image_assets(payload: Mapping[str, Any], context_path: Any) -> dict[str, Any]:
    resolved = _mutable_payload_copy(payload or {})
    target = _context_path(context_path)
    history = resolved.get("conversation_history")
    if not isinstance(history, list):
        return resolved
    for turn, path_key, _error_prefix in _image_entries(history):
        raw_path = str(turn.get(path_key, "") or "").strip()
        if not raw_path:
            continue
        path = Path(raw_path).expanduser()
        if path.is_absolute():
            continue
        candidate = (target.parent / path).resolve()
        if candidate.exists():
            turn[path_key] = str(candidate)
    return resolved


def saved_context_for_image_cleanup(context_path: Any) -> dict[str, Any] | None:
    """A failed/legacy read disables cleanup rather than guessing references."""
    try:
        payload = json.loads(_context_path(context_path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _referenced_image_paths(payload, target):
    history = _mutable_payload_copy(payload.get('conversation_history') or [])
    if not isinstance(history, list):
        return None
    paths = set()
    from core import long_term_memory
    try:
        for turn in history:
            if not isinstance(turn, Mapping):
                continue
            raw = dict(turn.get('metadata') or {})
            raw.update(turn)
            for asset in long_term_memory._image_assets_from_turn(raw, str(raw.get('role') or 'user')):
                paths.add(_resolve_attachment_path(asset['path'], target).resolve())
        for turn, key, _ in _image_entries(history):
            if turn.get(key):
                paths.add(_resolve_attachment_path(turn[key], target).resolve())
    except (OSError, ValueError, TypeError):
        return None
    return paths


def prune_removed_chat_context_images(previous, current, context_path, *, history_guard=None):
    """Best-effort cleanup after the chat itself has committed successfully."""
    try:
        return _prune_removed_chat_context_images(previous, current, context_path, history_guard=history_guard)
    except (OSError, ValueError, TypeError, RuntimeError) as error:
        logging.getLogger(__name__).warning('Unused chat image cleanup skipped: %s', error)
        return dict(removed=0, failed=1)


def _prune_removed_chat_context_images(previous, current, context_path, *, history_guard=None):
    """Remove only known, unused managed copies after an atomic chat save.

    External originals, other saved chats, and files still referenced by the
    previous on-disk version are protected. Never sweep an entire asset folder.
    """
    report = dict(removed=0, failed=0)
    target = _context_path(context_path)
    if not isinstance(previous, dict) or saved_context_for_image_cleanup(target) != current:
        return report
    managed = _assets_image_dir(target)
    if (managed.is_symlink() or managed.parent.is_symlink()
            or not _is_relative_to(managed.resolve(), target.parent)):
        return report
    old_paths = _referenced_image_paths(previous, target)
    new_paths = _referenced_image_paths(current, target)
    if old_paths is None or new_paths is None:
        return report
    candidates = old_paths-new_paths
    candidates = {path for path in candidates if _is_relative_to(path, managed.resolve())
                  and re.fullmatch(r'sha256_[0-9a-f]{64}\.(png|jpg|jpeg|webp|gif|bmp|img)', path.name)}
    if not candidates:
        return report
    # Save As and legacy files may reference another chat's managed copy.
    for neighbor in target.parent.glob('*.json'):
        if neighbor.resolve() == target:
            continue
        payload = saved_context_for_image_cleanup(neighbor)
        if payload is None:
            return report
        referenced = _referenced_image_paths(payload, neighbor)
        if referenced is None:
            return report
        candidates.difference_update(referenced)
    for path in candidates:
        try:
            def remove_if_unused(live_history):
                live_paths = _referenced_image_paths({'conversation_history': list(live_history)}, target)
                if live_paths is None or path in live_paths:
                    return False
                if path.is_file() and not path.is_symlink():
                    path.unlink()
                    return True
                return False
            removed = (history_guard(remove_if_unused) if history_guard is not None
                       else remove_if_unused(current.get('conversation_history') or []))
            if removed:
                report['removed'] += 1
        except OSError:
            report['failed'] += 1
            logging.getLogger(__name__).warning('Could not remove unused managed chat image: %s', path)
    return report


__all__ = [
    "preserve_chat_context_image_assets",
    "resolve_chat_context_image_assets",
]
