"""Conversation history windowing and LLM message conversion."""

from __future__ import annotations

import time


class ChatContextLimitReached(RuntimeError):
    pass


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
    attachment_image_path = str(turn.get("attachment_image_path", "") or "").strip()
    if bool(include_timestamp) and (content_text or attachment_image_path):
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
