"""Conversation history windowing and LLM message conversion."""

from __future__ import annotations

import copy
from difflib import SequenceMatcher
import re
import time


CONVERSATION_FORMAT_VERSION = 1
REQUEST_ONLY_CONTINUATION_CUE = "You continue speaking."


class ChatContextLimitReached(RuntimeError):
    pass


def prepare_request_history_messages(messages, *, cue_eligible=False):
    prepared = copy.deepcopy(list(messages or []))
    if not bool(cue_eligible):
        return prepared
    if not prepared:
        prepared.append({"role": "user", "content": REQUEST_ONLY_CONTINUATION_CUE})
        return prepared
    final = prepared[-1]
    final_role = str((final or {}).get("role", "") or "").strip().lower() if isinstance(final, dict) else ""
    if final_role == "assistant":
        prepared.append({"role": "user", "content": REQUEST_ONLY_CONTINUATION_CUE})
    return prepared


def prepare_regeneration_turn(history, *, target_in_history, input_roles):
    removed_target = False
    removed_target_turn = None
    if bool(target_in_history) and history:
        last = history[-1] if isinstance(history[-1], dict) else {}
        role = str(last.get("role", "") or "").strip().lower()
        origin = str(last.get("origin", "") or "").strip().lower()
        if role == "assistant" and origin != "input":
            removed_target_turn = history.pop()
            removed_target = True

    def detached_continuation_turn():
        transaction_id = str((removed_target_turn or {}).get("normal_chat_transaction_id") or "").strip()
        if not re.fullmatch(r"[0-9a-f]{32}", transaction_id):
            return None
        return {
            "role": "user",
            "content": REQUEST_ONLY_CONTINUATION_CUE,
            "origin": "input",
            "normal_chat_transaction_id": transaction_id,
        }

    normalized_input_roles = {
        str(role or "").strip().lower()
        for role in set(input_roles or set())
        if str(role or "").strip()
    }
    if not history or not isinstance(history[-1], dict):
        return detached_continuation_turn(), removed_target
    existing = dict(history[-1])
    role = str(existing.get("role", "") or "").strip().lower()
    if role not in normalized_input_roles:
        return detached_continuation_turn(), removed_target
    resumed = copy.deepcopy(existing)
    resumed["role"] = role or "user"
    resumed["content"] = str(existing.get("content", "") or "")
    resumed["origin"] = str(existing.get("origin", "input") or "input")
    return resumed, removed_target


def chat_context_window_messages(runtime_config):
    try:
        return max(4, int(runtime_config.get("chat_context_window_messages", 20) or 20))
    except Exception:
        return 20


def stored_chat_history_limit(runtime_config):
    try:
        return max(0, int(runtime_config.get("stored_chat_history_limit", 0) or 0))
    except Exception:
        return 0


def chat_context_overflow_policy(runtime_config):
    policy = str(runtime_config.get("chat_context_overflow_policy", "rolling_window") or "rolling_window").strip().lower()
    if policy not in {"rolling_window", "truncate_middle", "stop_at_limit"}:
        policy = "rolling_window"
    return policy


def apply_stored_chat_history_limit(conversation_history, limit):
    history = list(conversation_history or [])
    if int(limit or 0) <= 0:
        return history
    if len(history) > limit:
        return history[-limit:]
    return history


def merge_edited_history_metadata(original_history, original_display_entries, edited_entries, *, created_at=None):
    """Apply visible chat edits without discarding metadata from surviving turns."""
    originals = [dict(item) for item in list(original_history or []) if isinstance(item, dict)]
    displayed = [dict(item) for item in list(original_display_entries or []) if isinstance(item, dict)]
    edited = [dict(item) for item in list(edited_entries or []) if isinstance(item, dict)]

    def signature(item):
        return (
            str(item.get("role", "") or "").strip().lower(),
            str(item.get("origin", "") or "").strip().lower(),
            str(item.get("content", "") or "").strip(),
        )

    mapped_original_by_edited = {}
    matcher = SequenceMatcher(
        a=[signature(item) for item in displayed],
        b=[signature(item) for item in edited],
        autojunk=False,
    )
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(old_end - old_start):
                mapped_original_by_edited[new_start + offset] = old_start + offset
            continue
        if tag != "replace" or (old_end - old_start) != (new_end - new_start):
            continue
        for offset in range(old_end - old_start):
            old_index = old_start + offset
            new_index = new_start + offset
            old_role, old_origin, _old_content = signature(displayed[old_index])
            new_role, new_origin, _new_content = signature(edited[new_index])
            if (old_role, old_origin) == (new_role, new_origin):
                mapped_original_by_edited[new_index] = old_index

    new_created_at = float(created_at) if created_at is not None else time.time()
    merged_history = []
    for edited_index, edited_item in enumerate(edited):
        clean_edit = {
            key: value
            for key, value in edited_item.items()
            if not str(key).startswith("_")
        }
        original_index = mapped_original_by_edited.get(edited_index)
        if original_index is None or original_index >= len(originals):
            clean_edit.setdefault("created_at", new_created_at)
            merged_history.append(clean_edit)
            continue

        original = dict(originals[original_index])
        original_display = displayed[original_index] if original_index < len(displayed) else {}
        edited_content = str(clean_edit.get("content", "") or "").strip()
        if original.get("attachment_image_path"):
            marker = " [Image attached]"
            if edited_content == str(original_display.get("content", "") or "").strip():
                edited_content = str(original.get("content", "") or "").strip()
            elif edited_content.endswith(marker):
                edited_content = edited_content[:-len(marker)].rstrip()
        original.update(clean_edit)
        original["content"] = edited_content
        merged_history.append(original)
    return merged_history


def apply_overflow_policy_to_history(history, limit, policy):
    history = list(history or [])
    limit = max(1, int(limit or 1))
    if len(history) <= limit:
        return history
    if policy == "stop_at_limit":
        raise ChatContextLimitReached(
            f"Chat context window limit reached ({limit} messages). Increase the context window, switch overflow policy, quick-save the chat, or reset chat memory."
        )
    if policy == "truncate_middle":
        head_count = max(1, min(4, limit // 3 if limit >= 3 else 1))
        tail_count = max(0, limit - head_count)
        indexed = list(enumerate(history))
        kept = indexed[:head_count]
        if tail_count > 0:
            kept.extend(indexed[-tail_count:])
        deduped = []
        seen = set()
        for index, item in kept:
            if index in seen:
                continue
            seen.add(index)
            deduped.append((index, item))
        deduped.sort(key=lambda pair: pair[0])
        return [item for _, item in deduped]
    return history[-limit:]


def blank_user_anchor():
    return {"role": "user", "content": "", "origin": "synthetic_anchor"}


def coerce_turn_created_at(value):
    try:
        created_at = float(value)
    except Exception:
        return None
    if created_at <= 0:
        return None
    return created_at


def format_turn_timestamp(turn):
    if not isinstance(turn, dict):
        return ""
    created_at = coerce_turn_created_at(turn.get("created_at"))
    if created_at is None:
        return ""
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(created_at))
    except Exception:
        return ""


def content_with_timestamp(turn, content_text):
    stamp = format_turn_timestamp(turn)
    text = str(content_text or "")
    if not stamp:
        return text
    return f"[{stamp}] {text}"


_LEADING_TURN_TIMESTAMPS_RE = re.compile(
    r"^(?:\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]\s*)+"
)


def strip_leading_turn_timestamps(content_text):
    return _LEADING_TURN_TIMESTAMPS_RE.sub("", str(content_text or ""), count=1)


def migrate_conversation_history_content(history, *, source_version=0):
    try:
        normalized_source_version = max(0, int(source_version or 0))
    except Exception:
        normalized_source_version = 0
    migrated_history = [dict(item) if isinstance(item, dict) else item for item in list(history or [])]
    should_migrate = normalized_source_version < CONVERSATION_FORMAT_VERSION
    cleaned_assistant_turns = 0
    if should_migrate:
        for item in migrated_history:
            if not isinstance(item, dict):
                continue
            if str(item.get("role", "") or "").strip().lower() != "assistant":
                continue
            original_content = str(item.get("content", "") or "")
            cleaned_content = strip_leading_turn_timestamps(original_content)
            if cleaned_content != original_content:
                item["content"] = cleaned_content
                cleaned_assistant_turns += 1
    return migrated_history, {
        "source_version": normalized_source_version,
        "target_version": CONVERSATION_FORMAT_VERSION,
        "migrated": should_migrate,
        "cleaned_assistant_turns": cleaned_assistant_turns,
    }


def repair_model_history_window(history, *, policy, assistant_prefix_anchor_threshold=5):
    repaired = [dict(item) for item in list(history or []) if isinstance(item, dict)]
    if not repaired:
        return repaired
    policy = str(policy or "rolling_window").strip().lower()
    first_non_system_index = next(
        (i for i, item in enumerate(repaired) if str(item.get("role", "") or "").strip().lower() != "system"),
        None,
    )
    if first_non_system_index is None:
        return [blank_user_anchor()]
    first_non_system_role = str(repaired[first_non_system_index].get("role", "") or "").strip().lower()
    if first_non_system_role == "user":
        return repaired
    first_user_index = next(
        (i for i, item in enumerate(repaired) if str(item.get("role", "") or "").strip().lower() == "user"),
        None,
    )
    if first_user_index is None:
        return repaired[:first_non_system_index] + [blank_user_anchor()] + repaired[first_non_system_index:]
    prefix_length = max(0, int(first_user_index - first_non_system_index))
    if policy == "rolling_window" and prefix_length > assistant_prefix_anchor_threshold:
        return repaired[:first_non_system_index] + [blank_user_anchor()] + repaired[first_non_system_index:]
    return repaired[:first_non_system_index] + repaired[first_user_index:]


def build_model_history_window(conversation_history, *, limit, policy, assistant_prefix_anchor_threshold=5):
    selected = apply_overflow_policy_to_history(conversation_history, limit, policy)
    return repair_model_history_window(
        selected,
        policy=policy,
        assistant_prefix_anchor_threshold=assistant_prefix_anchor_threshold,
    )


def build_chat_message_from_turn(turn, *, data_url_for_local_image, include_timestamp=False):
    if not isinstance(turn, dict):
        return None
    role = str(turn.get("role", "user") or "user").strip().lower() or "user"
    if role not in {"user", "system", "assistant"}:
        role = "user"
    content_text = str(turn.get("content", "") or "").strip()
    if role == "assistant":
        # Assistant timestamps are display metadata. Keeping them inside an
        # assistant-role message teaches some models to emit another timestamp
        # on every reply, which then accumulates in saved conversation content.
        content_text = strip_leading_turn_timestamps(content_text)
    attachment_image_path = str(turn.get("attachment_image_path", "") or "").strip()
    if bool(include_timestamp) and role != "assistant" and (content_text or attachment_image_path):
        content_text = content_with_timestamp(turn, content_text)
    if attachment_image_path:
        data_url = data_url_for_local_image(attachment_image_path)
        if data_url:
            return {
                "role": role,
                "content": [
                    {
                        "type": "text",
                        "text": content_text or "Please respond to the attached image.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    },
                ],
            }
    if not content_text:
        return None
    return {"role": role, "content": content_text}
