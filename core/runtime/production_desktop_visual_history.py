"""Conversation-owned Visual Reply history mutations for the desktop graph."""

from __future__ import annotations

from typing import Protocol

from core import visual_reply_history
from core.runtime.conversation import ConversationService
from core.runtime.visual import VisualHistoryLink


class VisualHistoryAuthority(Protocol):
    def lease_is_current(self, lease: object) -> bool: ...

    def history_link_is_current(
        self,
        session_lease: object,
        turn_lease: object,
        request_id: str,
        binding_id: str,
    ) -> bool: ...


class VisualHistoryMemory(Protocol):
    def refresh_history_assets(self, lease: object) -> int: ...


class ProductionDesktopVisualHistoryOwner:
    """Attach completed visuals without exposing mutable conversation history."""

    __slots__ = ("_conversation", "_memory", "_visual")

    def __init__(
        self,
        *,
        conversation: ConversationService,
        visual: VisualHistoryAuthority,
        memory: VisualHistoryMemory,
    ) -> None:
        if not isinstance(conversation, ConversationService):
            raise TypeError("Visual history requires ConversationService.")
        if not all(
            callable(getattr(visual, method, None))
            for method in ("lease_is_current", "history_link_is_current")
        ):
            raise TypeError("Visual history requires a visual lease authority.")
        if not callable(getattr(memory, "refresh_history_assets", None)):
            raise TypeError("Visual history requires a memory asset owner.")
        self._conversation = conversation
        self._visual = visual
        self._memory = memory

    def attach_history(self, link: object) -> bool:
        if not isinstance(link, VisualHistoryLink):
            return False
        before = self._conversation.snapshot()
        history = [
            dict(message)
            for message in self._conversation.message_mappings()
        ]
        original_history = list(history)
        link_metadata = dict(link.asset_metadata or {})
        target_turn_id = str(link_metadata.get("target_turn_id") or "").strip()
        target_transaction = str(link_metadata.get("normal_chat_transaction_id") or "").strip()
        target_index = None
        standalone_added = False
        if link_metadata.get("standalone_visual_reply") is True:
            # Explicit image commands have no LLM assistant turn to attach to.
            # Build their image-only message locally; publish only after normal
            # output/binding validation, guarded by the captured history revision.
            matches = [index for index, message in enumerate(history)
                       if message.get("role") == "assistant"
                       and message.get("visual_reply_request_id") == link.request_id]
            if len(matches) > 1:
                return False
            if matches:
                target_index = matches[0]
            else:
                target_index = len(history)
                history.append({"role": "assistant", "content": "", "origin": "visual_reply",
                                "visual_reply_request_id": link.request_id})
                standalone_added = True
        elif target_turn_id or target_transaction:
            matches = [
                index for index, message in enumerate(before.messages)
                if message.role.strip().lower() == "assistant"
                and (not target_turn_id or target_turn_id in {
                    message.message_id,
                    str(message.metadata.get("id") or ""),
                    str(message.metadata.get("turn_id") or ""),
                })
                and (not target_transaction or target_transaction == str(
                    message.metadata.get("normal_chat_transaction_id") or ""
                ))
            ]
            if len(matches) != 1:
                return False
            target_index = matches[0]
        linked = visual_reply_history.attach_visual_reply_image_to_assistant_history(
            history,
            link.request_id,
            str(link.output),
            source_text=link.source_text,
            prompt_text=link.prompt,
            session_lease=link.session_lease,
            turn_lease=link.turn_lease,
            binding_id=link.binding_id,
            target_request_id=str(
                link_metadata.get("variation_of_request_id") or ""
            ),
            target_index=target_index,
            append_image=bool(link_metadata.get("append_visual_variation", False)),
            turn_lease_is_current=self._visual.lease_is_current,
            exact_binding_is_current=self._visual.history_link_is_current,
        )
        if not linked:
            return False
        if standalone_added:
            return self._conversation.replace_messages_if_revision(
                history, expected_revision=before.revision,
            ) is not None
        changed_index = next(
            (index for index, turn in enumerate(history) if turn != original_history[index]),
            None,
        )
        if changed_index is None:
            return self._conversation.snapshot().revision == before.revision
        return self._conversation.replace_message_at(
            changed_index,
            history[changed_index],
            expected_revision=before.revision,
        ) is not None

    def refresh_history(self, lease: object) -> int:
        return self._memory.refresh_history_assets(lease)


__all__ = [
    "ProductionDesktopVisualHistoryOwner",
    "VisualHistoryAuthority",
    "VisualHistoryMemory",
]
