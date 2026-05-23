"""User-image turn helpers for clipboard and other image-input sources."""

from __future__ import annotations

import os
from typing import Any, Callable


_pending_next_user_attachment: dict[str, str] | None = None
_sanitize_chat_turn: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None
_append_chat_turn: Callable[[dict[str, Any]], None] | None = None
_apply_stored_chat_history_limit: Callable[[], None] | None = None
_set_pending_loaded_input_turn: Callable[[dict[str, Any]], None] | None = None
_request_chat_view_rebuild: Callable[[], None] | None = None


def _resolve_existing_image_path(image_path) -> str:
    path = os.path.abspath(str(image_path or "").strip())
    if not path or not os.path.isfile(path):
        raise ValueError("Image path does not exist.")
    return path


def set_pending_attachment(image_path, *, source: str = "clipboard") -> dict[str, str]:
    global _pending_next_user_attachment
    path = _resolve_existing_image_path(image_path)
    _pending_next_user_attachment = {
        "attachment_image_path": path,
        "attachment_source": str(source or "image").strip().lower() or "image",
    }
    print(f"📋 [Clipboard] Pending image attachment armed for next user turn: {path}")
    return dict(_pending_next_user_attachment)


def pending_attachment() -> dict[str, str] | None:
    return dict(_pending_next_user_attachment) if _pending_next_user_attachment else None


def consume_pending_attachment() -> dict[str, str] | None:
    global _pending_next_user_attachment
    pending = dict(_pending_next_user_attachment) if _pending_next_user_attachment else None
    _pending_next_user_attachment = None
    return pending


def clear_pending_attachment() -> None:
    global _pending_next_user_attachment
    _pending_next_user_attachment = None


def configure_queue_runtime(
    *,
    sanitize_chat_turn: Callable[[dict[str, Any]], dict[str, Any] | None],
    append_chat_turn: Callable[[dict[str, Any]], None],
    apply_stored_chat_history_limit: Callable[[], None],
    set_pending_loaded_input_turn: Callable[[dict[str, Any]], None],
    request_chat_view_rebuild: Callable[[], None],
) -> None:
    global _sanitize_chat_turn
    global _append_chat_turn
    global _apply_stored_chat_history_limit
    global _set_pending_loaded_input_turn
    global _request_chat_view_rebuild
    _sanitize_chat_turn = sanitize_chat_turn
    _append_chat_turn = append_chat_turn
    _apply_stored_chat_history_limit = apply_stored_chat_history_limit
    _set_pending_loaded_input_turn = set_pending_loaded_input_turn
    _request_chat_view_rebuild = request_chat_view_rebuild


def queue_image_turn(
    image_path,
    *,
    content: str | None = None,
    source: str = "clipboard",
    sanitize_chat_turn: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
    append_chat_turn: Callable[[dict[str, Any]], None] | None = None,
    apply_stored_chat_history_limit: Callable[[], None] | None = None,
    set_pending_loaded_input_turn: Callable[[dict[str, Any]], None] | None = None,
    request_chat_view_rebuild: Callable[[], None] | None = None,
) -> dict[str, Any]:
    sanitize = sanitize_chat_turn or _sanitize_chat_turn
    append_turn = append_chat_turn or _append_chat_turn
    apply_limit = apply_stored_chat_history_limit or _apply_stored_chat_history_limit
    set_pending = set_pending_loaded_input_turn or _set_pending_loaded_input_turn
    rebuild = request_chat_view_rebuild or _request_chat_view_rebuild
    if not all(callable(item) for item in (sanitize, append_turn, apply_limit, set_pending, rebuild)):
        raise RuntimeError("User image turn runtime is not configured.")
    path = _resolve_existing_image_path(image_path)
    turn = sanitize(
        {
            "role": "user",
            "content": str(content or "").strip() or "Please respond to the image I just sent you.",
            "origin": "input",
            "attachment_image_path": path,
            "attachment_source": str(source or "image").strip().lower() or "image",
        }
    )
    if not turn:
        raise ValueError("Could not prepare image input turn.")
    clear_pending_attachment()
    append_turn(dict(turn))
    apply_limit()
    set_pending(dict(turn))
    print(f"📋 [Clipboard] Queued image input for next model request: {path}")
    rebuild()
    return dict(turn)
