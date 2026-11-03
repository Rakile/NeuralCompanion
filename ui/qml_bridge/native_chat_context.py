"""Named chat-context persistence through the composed application facades.

The caller owns worker lifetime and optional post-save memory flushing. No model
work is scheduled here, and live context identity changes only after file commit.
"""
from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from core import chat_context_assets, continuity_memory, long_term_memory


def _check_current(is_current: Callable[[], bool]) -> None:
    if not is_current():
        raise RuntimeError("Chat context operation cancelled.")


def _accepted(result: Any, message: str) -> Any:
    if not bool(getattr(result, "accepted", False)):
        failure = getattr(result, "failure", None)
        raise RuntimeError(str(getattr(failure, "message", message)))
    return getattr(result, "value", None)


def _bounded(value: Any, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value or default)))
    except (TypeError, ValueError, OverflowError):
        return default


def _memory_settings(data: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    """Restore the former named-load memory options without resetting other UI state."""
    settings = {
        "continuity_memory_enabled": bool(data.get("continuity_memory_enabled", data.get("long_term_memory_enabled", False))),
        "continuity_memory_auto_summarize": bool(data.get("continuity_memory_auto_summarize", data.get("continuity_memory_update_on_save", data.get("long_term_memory_update_on_save", False)))),
        "continuity_memory_inject": bool(data.get("continuity_memory_inject", data.get("long_term_memory_inject", False))),
    }
    from core.runtime.embedding_provider import provider_id
    settings['long_term_memory_embedding_provider'] = provider_id(data.get('long_term_memory_embedding_provider'))
    for key in ("long_term_memory_retrieval_enabled", "long_term_memory_embedding_enabled", "long_term_memory_auto_archive_enabled"):
        settings[key] = bool(data.get(key, False))
    if "long_term_memory_image_review_enabled" in data:
        settings["long_term_memory_image_review_enabled"] = bool(data["long_term_memory_image_review_enabled"])
    for key, default, low, high in (
        ("continuity_memory_auto_turns", 120, 1, 10000),
        ("continuity_memory_max_chars", 3000, 500, 20000),
        ("long_term_memory_retrieval_max_items", 6, 1, 12),
        ("long_term_memory_archive_batch_turns", long_term_memory.DEFAULT_EXTRACTION_TURNS, 1, 10000),
        ("long_term_memory_embedding_context_length", 8192, 512, 262144),
    ):
        fallback = current.get(key, default)
        if key == "continuity_memory_max_chars":
            fallback = data.get("long_term_memory_max_chars", fallback)
        settings[key] = _bounded(data.get(key, fallback), default, low, high)
    for key, default, normalize in (
        ("long_term_memory_recall_text_budget", -1, long_term_memory.normalize_recall_text_budget),
        ("long_term_memory_recall_image_limit", 1, long_term_memory.normalize_image_recall_limit),
        ("long_term_memory_image_context_max_output_tokens", long_term_memory.DEFAULT_IMAGE_CONTEXT_MAX_OUTPUT_TOKENS, long_term_memory.normalize_image_context_max_output_tokens),
    ):
        settings[key] = normalize(data.get(key, current.get(key, default)), default=default)
    for key, default in (
        ("long_term_memory_embedding_model", "text-embedding-bge-m3"),
        ("long_term_memory_embedding_base_url", "http://127.0.0.1:1234/v1"),
    ):
        settings[key] = str(data.get(key, current.get(key, default)) or default)
    # Synchronize aliases explicitly, including configurations without effects binding.
    for alias, canonical in (
        ("long_term_memory_enabled", "continuity_memory_enabled"),
        ("long_term_memory_update_on_save", "continuity_memory_auto_summarize"),
        ("continuity_memory_update_on_save", "continuity_memory_auto_summarize"),
        ("long_term_memory_inject", "continuity_memory_inject"),
        ("long_term_memory_max_chars", "continuity_memory_max_chars"),
    ):
        settings[alias] = settings[canonical]
    return settings


def save_chat_context(application: Any, path: Any, *, is_current: Callable[[], bool] = lambda: True) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if target.suffix.lower() != ".json":
        target = target.with_suffix(".json")
    _check_current(is_current)
    from core.chat_context_safety import export_session_with_history_receipt, history_signature
    result, saved_signature = export_session_with_history_receipt(application.chat)
    exported = _accepted(result, "Could not export the current chat session.")
    if not isinstance(exported, Mapping):
        raise ValueError("The exported chat context is not a JSON object.")
    current = dict(application.config.snapshot().values)
    if saved_signature is None:
        saved_signature = history_signature(exported.get('conversation_history', ()))
    previous = str(current.get("active_chat_context_path", "") or "").strip()
    same_path = bool(previous) and Path(previous).expanduser().resolve() == target
    memory_id = str(exported.get("continuity_memory_id", current.get("continuity_memory_id", "")) or "").strip()
    if not same_path or not memory_id or memory_id == "chat_context_quick_save":
        memory_id = continuity_memory.memory_id_from_label(target.stem)
    payload = dict(exported)
    payload["continuity_memory_id"] = memory_id
    previous_images = chat_context_assets.saved_context_for_image_cleanup(target)
    _check_current(is_current)
    payload, _report = chat_context_assets.preserve_chat_context_image_assets(payload, target)
    serialized = json.dumps(payload, indent=2, ensure_ascii=False)
    _check_current(is_current)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(serialized)
        _check_current(is_current)
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    _check_current(is_current)
    history_guard = getattr(application.chat, 'with_history_snapshot', None)
    if history_guard is None:
        history = getattr(application.chat, 'history', None)
        history_guard = (lambda effect: effect(history())) if history is not None else (lambda effect: False)
    chat_context_assets.prune_removed_chat_context_images(previous_images, payload, target, history_guard=history_guard)
    _accepted(application.memory.set_identity(memory_id), "Could not set chat context memory identity.")
    _check_current(is_current)
    _accepted(application.memory.set_context_path(str(target)), "Could not remember chat context path.")
    resolved = chat_context_assets.resolve_chat_context_image_assets(payload, target)
    return {"path": str(target), "history": list(resolved.get("conversation_history", []) or []), "contextPath": str(target), "contextName": target.stem,
            "saved_history_signature": saved_signature}


def load_chat_context(
    application: Any,
    path: Any,
    *,
    is_current: Callable[[], bool] = lambda: True,
    on_imported: Callable[[Any, Any], None] | None = None,
) -> dict[str, Any]:
    """Load a document, allowing the controller to acknowledge its own transition.

    When supplied, ``on_imported`` must validate the generations surrounding the
    accepted import and advance the controller's expected generation only for
    that transition. It runs before any post-import live settings are changed;
    ``is_current`` remains authoritative before every subsequent mutation.
    """
    target = Path(path).expanduser().resolve()
    _check_current(is_current)
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("The chat context is not a JSON object.")
    payload = dict(payload)
    memory_id = str(payload.get("continuity_memory_id", "") or "").strip()
    if not memory_id or memory_id == "chat_context_quick_save":
        payload["continuity_memory_id"] = target.stem
    resolved = chat_context_assets.resolve_chat_context_image_assets(payload, target)
    settings = _memory_settings(resolved, application.config.snapshot().values)
    baseline_model = str(resolved.get("long_term_memory_embedding_session_model", settings["long_term_memory_embedding_model"]) or settings["long_term_memory_embedding_model"])
    baseline_length = _bounded(resolved.get("long_term_memory_embedding_session_context_length", settings["long_term_memory_embedding_context_length"]), settings["long_term_memory_embedding_context_length"], 512, 262144)
    before_import = application.chat.snapshot().session_generation if on_imported is not None else None
    _check_current(is_current)
    result = _accepted(application.chat.import_session(resolved), "Could not import the chat context.")
    from core.chat_context_safety import history_signature
    loaded_signature = dict(result or {}).get('history_signature') or history_signature(resolved.get('conversation_history', ()))
    if on_imported is not None:
        on_imported(before_import, application.chat.snapshot().session_generation)
    _check_current(is_current)
    _accepted(application.memory.set_context_path(str(target)), "Could not remember chat context path.")
    _check_current(is_current)
    _accepted(application.config.update_many(settings), "Could not restore chat context memory settings.")
    _check_current(is_current)
    _accepted(application.memory.set_embedding_baseline(baseline_model, baseline_length), "Could not restore memory embedding baseline.")
    return {**dict(result or {}), "path": str(target), "contextPath": str(target), "contextName": target.stem,
            "history": list(resolved.get('conversation_history', ())), 'saved_history_signature': loaded_signature}
