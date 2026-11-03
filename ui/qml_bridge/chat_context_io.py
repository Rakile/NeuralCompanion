"""Shared, atomic chat-context file operations for desktop and phone controls."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
import json
import os
from pathlib import Path
from typing import Any

from core import chat_context_assets


def _plain(value: Any) -> Any:
    if hasattr(value, "toVariant"):
        try:
            value = value.toVariant()
        except (AttributeError, RuntimeError, TypeError):
            return None
    if is_dataclass(value):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_plain(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def write_chat_context(application: Any, target: Path, *, on_saved=None) -> str:
    path, _report = write_chat_context_with_report(application, target, on_saved=on_saved)
    return path


def write_chat_context_with_report(application: Any, target: Path, *, on_saved=None) -> tuple[str, dict[str, int]]:
    """Private variant for saves that require every referenced image."""
    from core.chat_context_safety import export_session_with_history_receipt, history_signature
    result, saved_signature = export_session_with_history_receipt(application.chat)
    if not bool(getattr(result, "accepted", False)):
        failure = getattr(result, "failure", None)
        raise RuntimeError(str(getattr(failure, "message", "Could not export the current chat session.")))
    original = _plain(getattr(result, "value", {}) or {})
    if saved_signature is None:
        saved_signature = history_signature(original.get('conversation_history', ()))
    previous_images = chat_context_assets.saved_context_for_image_cleanup(target)
    payload, asset_report = chat_context_assets.preserve_chat_context_image_assets(
        original, target,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    history_guard = getattr(application.chat, 'with_history_snapshot', None)
    if history_guard is None:
        history = getattr(application.chat, 'history', None)
        history_guard = (lambda effect: effect(history())) if history is not None else (lambda effect: False)
    chat_context_assets.prune_removed_chat_context_images(previous_images, payload, target, history_guard=history_guard)
    if on_saved is not None:
        on_saved(saved_signature)
    return str(target), asset_report


def load_chat_context(application: Any, target: Path, *, on_loaded=None) -> str:
    payload = json.loads(target.read_text(encoding="utf-8"))
    return load_chat_context_payload(application, payload, target, on_loaded=on_loaded)


def load_chat_context_payload(application: Any, payload: Mapping[str, Any], target: Path, *, on_loaded=None) -> str:
    """Import a transformed chat while resolving images against its saved version."""
    if not isinstance(payload, Mapping):
        raise ValueError("The quick chat context is not a JSON object.")
    resolved = chat_context_assets.resolve_chat_context_image_assets(payload, target)
    result = application.chat.import_session(resolved)
    if not bool(getattr(result, "accepted", False)):
        failure = getattr(result, "failure", None)
        raise RuntimeError(str(getattr(failure, "message", "Could not import the quick chat context.")))
    summary = _plain(getattr(result, "value", {}) or {})
    if on_loaded is not None:
        from core.chat_context_safety import history_signature
        on_loaded(dict(summary).get('history_signature') or history_signature(resolved.get('conversation_history', ())))
    turns = int(dict(summary).get("conversation_turns", 0) or 0)
    return f"{turns} turn(s) restored" if turns else "Chat context restored"
