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
    session_lease=None,
    turn_lease=None,
    binding_id: str = "",
    target_request_id: str = "",
    target_index: int | None = None,
    append_image: bool = False,
    session_resources=None,
    turn_lease_is_current=None,
    exact_binding_is_current=None,
) -> bool:
    """Attach a generated visual reply image to the matching assistant turn."""
    request_text = _normalize_text(request_id)
    target_request_text = _normalize_text(target_request_id)
    binding_text = _normalize_text(binding_id)
    exact_turn_lease = turn_lease or session_lease
    if callable(turn_lease_is_current) and exact_turn_lease is not None:
        if not turn_lease_is_current(exact_turn_lease):
            return False
    if callable(exact_binding_is_current):
        if not exact_binding_is_current(
            session_lease,
            exact_turn_lease,
            request_text,
            binding_text,
        ):
            return False
    if session_lease is not None and session_resources is not None:
        result = session_resources.link_visual_result(
            session_lease,
            lambda: attach_visual_reply_image_to_assistant_history(
                history,
                request_id,
                image_path,
                source_text=source_text,
                prompt_text=prompt_text,
                session_lease=session_lease,
                turn_lease=exact_turn_lease,
                binding_id=binding_text,
                target_request_id=target_request_text,
                target_index=target_index,
                append_image=append_image,
                turn_lease_is_current=turn_lease_is_current,
                exact_binding_is_current=exact_binding_is_current,
            ),
        )
        return bool(result.accepted and result.value)
    image_text = _normalize_text(image_path)
    if not image_text:
        return False

    resolved_path = Path(image_text).expanduser()
    if not resolved_path.exists() or not resolved_path.is_file():
        return False
    resolved_text = str(resolved_path.resolve())

    source = _normalize_text(source_text)
    prompt = _normalize_text(prompt_text)
    if target_index is not None and (
        not 0 <= target_index < len(history)
        or not isinstance(history[target_index], dict)
        or str(history[target_index].get("role", "")).lower() != "assistant"
    ):
        return False
    candidate_indexes = range(len(history) - 1, -1, -1) if target_index is None else ()
    for index in candidate_indexes:
        turn = history[index]
        if not isinstance(turn, dict) or str(turn.get("role", "")).lower() != "assistant":
            continue
        turn_request_id = _normalize_text(turn.get("visual_reply_request_id"))
        if target_request_text and turn_request_id == target_request_text:
            target_index = index
            break
        if request_text and turn_request_id == request_text:
            target_index = index
            break
        if turn.get("visual_reply_image_path") and not append_image:
            continue
        if source and _normalize_text(turn.get("content")) == source:
            target_index = index
            break

    if target_index is None:
        return False

    turn = dict(history[target_index])
    if append_image:
        existing_paths: list[str] = []
        for field_name in VISUAL_REPLY_IMAGE_FIELDS:
            value = turn.get(field_name)
            values = value if isinstance(value, (list, tuple)) else (value,)
            for item in values:
                item_text = _normalize_text(item)
                if item_text and item_text not in existing_paths:
                    existing_paths.append(item_text)
        if resolved_text not in existing_paths:
            existing_paths.append(resolved_text)
        turn["visual_reply_image_paths"] = existing_paths
        turn["visual_reply_image_paths_source"] = "generated_image"
        if not _normalize_text(turn.get("visual_reply_image_path")):
            turn["visual_reply_image_path"] = resolved_text
            turn["visual_reply_image_path_source"] = "generated_image"
    else:
        turn["visual_reply_image_path"] = resolved_text
        turn["visual_reply_image_path_source"] = "generated_image"
    if request_text and (not append_image or not _normalize_text(turn.get("visual_reply_request_id"))):
        turn["visual_reply_request_id"] = request_text
    if prompt:
        turn["visual_reply_prompt"] = prompt
    history[target_index] = turn
    return True


def reconcile_pending_visual_reply_image_links(
    history: MutableSequence,
    pending_links: MutableSequence,
    *,
    session_resources=None,
    turn_lease_is_current=None,
    exact_binding_is_current=None,
) -> dict:
    """Retry generated-image links that completed before their assistant turn existed."""
    linked_count = 0
    linked_items = []
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
            session_lease=item.get("session_lease"),
            turn_lease=item.get("turn_lease"),
            binding_id=item.get("binding_id", ""),
            session_resources=session_resources,
            turn_lease_is_current=turn_lease_is_current,
            exact_binding_is_current=exact_binding_is_current,
        ):
            linked_count += 1
            linked_items.append(item)
        else:
            remaining.append(dict(item))
    return {
        "linked": linked_count,
        "linked_items": linked_items,
        "pending": remaining,
    }
