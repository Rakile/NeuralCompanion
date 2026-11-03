"""Resolve playback moods to exact conversation rows without modifying history."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from core.runtime.avatar import PortraitPlaybackState
from core.runtime.conversation import ConversationSnapshot


def portrait_message_id(state: PortraitPlaybackState | None, conversation: ConversationSnapshot) -> str:
    if state is None or state.lease.session_generation != conversation.session_generation:
        return ""
    for message in conversation.messages:
        if message.role != "assistant":
            continue
        if state.message_id:
            if message.message_id == state.message_id:
                return message.message_id
        elif state.transaction_id and str(message.metadata.get("normal_chat_transaction_id") or "") == state.transaction_id:
            return message.message_id
    return ""


def portrait_generation_moods(record: Mapping[str, Any], scope: str, selected: str) -> list[str]:
    images = dict(record.get("mood_images") or {})
    names = list(dict.fromkeys(("neutral", "happy", "sad", "angry", "curious", *images)))
    if scope == "selected":
        if selected not in names:
            raise ValueError("Save the selected mood before generating its portrait.")
        return [selected]
    if scope == "missing":
        return [name for name in names if not (record.get("avatar_path") if name == "neutral" else images.get(name))]
    if scope == "all":
        return names
    raise ValueError("Choose which portraits to generate.")
