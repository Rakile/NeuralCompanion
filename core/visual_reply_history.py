"""Helpers for connecting generated visual replies to chat history turns."""

from __future__ import annotations

from pathlib import Path
from typing import MutableMapping, MutableSequence


VISUAL_REPLY_IMAGE_FIELDS = (
    "generated_image_path",
    "visual_reply_image_path",
    "assistant_visual_reply_image_path",
    "generated_image_paths",
    "visual_reply_image_paths",
    "assistant_visual_reply_image_paths",
)

VISUAL_REPLY_METADATA_FIELDS = (
    "visual_reply_request_id",
    "visual_reply_prompt",
)


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def preserve_visual_reply_image_fields(turn: MutableMapping, source: MutableMapping) -> MutableMapping:
    """Preserve generated-image metadata while sanitizing chat turns."""
    if not isinstance(turn, MutableMapping) or not isinstance(source, MutableMapping):
        return turn
    for field_name in VISUAL_REPLY_IMAGE_FIELDS:
        value = source.get(field_name)
        if isinstance(value, (list, tuple)):
            clean_values = [str(item or "").strip() for item in value if str(item or "").strip()]
            if clean_values:
                turn[field_name] = clean_values
        elif _normalize_text(value):
            turn[field_name] = _normalize_text(value)
        source_key = f"{field_name}_source"
        source_value = _normalize_text(source.get(source_key))
        if source_value:
            turn[source_key] = source_value
    for field_name in VISUAL_REPLY_METADATA_FIELDS:
        value = _normalize_text(source.get(field_name))
        if value:
            turn[field_name] = value
    return turn


def attach_visual_reply_image_to_assistant_history(
    history: MutableSequence,
    request_id: str,
    image_path: str,
    *,
    source_text: str = "",
    prompt_text: str = "",
) -> bool:
    """Attach a generated visual reply image to the matching assistant turn."""
    request_text = _normalize_text(request_id)
    image_text = _normalize_text(image_path)
    if not image_text:
        return False

    resolved_path = Path(image_text).expanduser()
    if not resolved_path.exists() or not resolved_path.is_file():
        return False
    resolved_text = str(resolved_path.resolve())

    source = _normalize_text(source_text)
    prompt = _normalize_text(prompt_text)
    target_index = None

    for index in range(len(history) - 1, -1, -1):
        turn = history[index]
        if not isinstance(turn, dict) or str(turn.get("role", "")).lower() != "assistant":
            continue
        if request_text and _normalize_text(turn.get("visual_reply_request_id")) == request_text:
            target_index = index
            break
        if turn.get("visual_reply_image_path"):
            continue
        if source and _normalize_text(turn.get("content")) == source:
            target_index = index
            break

    if target_index is None:
        return False

    turn = dict(history[target_index])
    turn["visual_reply_image_path"] = resolved_text
    turn["visual_reply_image_path_source"] = "generated_image"
    if request_text:
        turn["visual_reply_request_id"] = request_text
    if prompt:
        turn["visual_reply_prompt"] = prompt
    history[target_index] = turn
    return True


def reconcile_pending_visual_reply_image_links(
    history: MutableSequence,
    pending_links: MutableSequence,
) -> dict:
    """Retry generated-image links that completed before their assistant turn existed."""
    linked_count = 0
    remaining = []
    for item in list(pending_links or []):
        if not isinstance(item, MutableMapping):
            continue
        if attach_visual_reply_image_to_assistant_history(
            history,
            item.get("request_id", ""),
            item.get("image_path", ""),
            source_text=item.get("source_text", ""),
            prompt_text=item.get("prompt_text", ""),
        ):
            linked_count += 1
        else:
            remaining.append(dict(item))
    return {"linked": linked_count, "pending": remaining}
