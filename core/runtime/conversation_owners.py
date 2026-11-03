"""Production conversation owners backed by the canonical conversation service."""

from __future__ import annotations

import copy
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from core import conversation_history as conversation_history_runtime
from core import user_image_turns
from core.runtime import chat_sessions
from core.runtime.conversation import ConversationService
from core.runtime.identifiers import WorkLease


InputTurn = dict[str, object]
RequestContext = dict[str, object]


class RuntimeConfigReader(Protocol):
    def current(self) -> Mapping[str, object]: ...


class ChatViewPublisher(Protocol):
    def request_rebuild(self) -> None: ...


class ConversationTransactionMaintenance(Protocol):
    def prune(self) -> None: ...
    def discard(self, transaction_id: str) -> None: ...
    def is_current(
        self,
        transaction_id: str,
        *,
        session_generation: int | None = None,
    ) -> bool: ...


class ConversationMemoryTriggers(Protocol):
    def maybe_update_continuity(self) -> None: ...
    def maybe_archive_long_term(self) -> None: ...


class AssistantHistoryCommitter(Protocol):
    """Commit an assistant result through the exact accepted-turn route."""

    def commit(
        self,
        text: str,
        *,
        metadata: Mapping[str, object],
        expected_session_generation: int | None,
        expected_turn_id: str | None,
    ) -> InputTurn | None: ...


class ScreenImageCapture(Protocol):
    def capture(self) -> Mapping[str, object] | None: ...


class UserImagePolicy(Protocol):
    def auto_attach_screen(self) -> bool: ...
    def source_enabled(self, source: str) -> bool: ...


class RelayMetadataSanitizer(Protocol):
    def sanitize(self, value: object) -> Mapping[str, object] | None: ...


@dataclass(frozen=True, slots=True)
class MappingRuntimeConfig:
    values: Mapping[str, object]

    def current(self) -> Mapping[str, object]:
        return self.values


@dataclass(frozen=True, slots=True)
class PermissiveUserImagePolicy:
    screen_auto_attach: bool = False

    def auto_attach_screen(self) -> bool:
        return self.screen_auto_attach

    def source_enabled(self, source: str) -> bool:
        del source
        return True


class ConversationSessionRuntimeOwner:
    """Own session continuity and one pending loaded input turn."""

    def __init__(
        self,
        conversation: ConversationService,
        config: RuntimeConfigReader,
        *,
        relay_metadata: RelayMetadataSanitizer,
        chat_view: ChatViewPublisher,
        transactions: ConversationTransactionMaintenance,
    ) -> None:
        self._conversation = conversation
        self._config = config
        self._relay_metadata = relay_metadata
        self._chat_view = chat_view
        self._transactions = transactions
        self._pending_lock = threading.RLock()
        self._pending_epoch = 0
        self._pending_loaded_input_turn: InputTurn | None = None
        self._pending_replacement_listener: Callable[[str, str], None] | None = None

    def set_pending_replacement_listener(self, listener: Callable[[str, str], None]) -> None:
        """Connect the runtime's retirement owner during composition."""
        self._pending_replacement_listener = listener

    def live_config(self) -> Mapping[str, object]:
        return self._config.current()

    def session_generation(self) -> int:
        return self._conversation.snapshot().session_generation.value

    def session_lease(self) -> WorkLease:
        return self._conversation.session_lease()

    def stage_pending_loaded_input_turn(
        self, turn: Mapping[str, object] | None
    ) -> None:
        replacement = self.reconstruct_input_turn(turn)
        replacement_id = str(
            (replacement or {}).get("normal_chat_transaction_id") or ""
        )
        with self._pending_lock:
            displaced_request = str((self._pending_loaded_input_turn or {}).get("remote_capture_id") or "")
            displaced_id = str(
                (self._pending_loaded_input_turn or {}).get(
                    "normal_chat_transaction_id"
                )
                or ""
            )
            self._pending_loaded_input_turn = replacement
            self._pending_epoch += 1
        if displaced_id and displaced_id != replacement_id:
            self._transactions.discard(displaced_id)
            if displaced_request and self._pending_replacement_listener is not None:
                # No external callback runs under the pending slot lock. A
                # consumed active reply is never a displaced pending turn.
                self._pending_replacement_listener(displaced_request, displaced_id)

    def consume_pending_loaded_input_turn(self) -> InputTurn | None:
        with self._pending_lock:
            pending = self._pending_loaded_input_turn
            self._pending_loaded_input_turn = None
            if pending is not None:
                self._pending_epoch += 1
        return self.reconstruct_input_turn(pending)

    def discard_pending_loaded_input_turn(self, *, expected_session_generation: int) -> None:
        """An accepted interruption replaces pending intent in this chat only."""
        with self._pending_lock:
            if self.session_generation() != expected_session_generation:
                return
            pending = self._pending_loaded_input_turn
            self._pending_loaded_input_turn = None
            self._pending_epoch += 1
        transaction_id = str((pending or {}).get("normal_chat_transaction_id") or "")
        request_id = str((pending or {}).get("remote_capture_id") or "")
        if transaction_id:
            self._transactions.discard(transaction_id)
            if request_id and self._pending_replacement_listener is not None:
                self._pending_replacement_listener(request_id, transaction_id)

    def pending_loaded_input_turn(self) -> InputTurn | None:
        """Return a stable copy without consuming the staged input turn."""

        with self._pending_lock:
            pending = self._pending_loaded_input_turn
        return copy.deepcopy(pending) if pending is not None else None

    def conditional_input_epoch(self) -> int | None:
        with self._pending_lock:
            return self._pending_epoch if self._pending_loaded_input_turn is None else None

    def stage_conditional_input(self, turn, *, epoch: int, before, lease) -> bool:
        replacement = self.reconstruct_input_turn(turn)
        with self._pending_lock:
            if self._pending_epoch != epoch or self._pending_loaded_input_turn is not None:
                return False
            def publish() -> None:
                self._pending_loaded_input_turn = replacement
                self._pending_epoch += 1
            return self._conversation.publish_conditional_input(before, lease, publish)

    def discard_unpublished_input(self, turn) -> None:
        self._transactions.discard(str(turn.get("normal_chat_transaction_id") or ""))

    def reconstruct_input_turn(
        self, turn: Mapping[str, object] | None
    ) -> InputTurn | None:
        return chat_sessions.reconstruct_input_turn(
            turn,
            sanitize_relay_metadata=self._relay_metadata.sanitize,
        )

    def request_chat_view_rebuild(self) -> None:
        self._chat_view.request_rebuild()

    def prune_normal_chat_transactions(self) -> None:
        self._transactions.prune()

    def display_input_turn_content(self, turn: Mapping[str, object]) -> str:
        content = str(turn.get("content", "") or "").strip()
        if str(turn.get("attachment_image_path", "") or "").strip():
            content = (
                content or "Please respond to the image I just sent you."
            ) + " [Image attached]"
        return content


@dataclass(frozen=True, slots=True)
class InterruptedAssistantOutcome:
    accepted: bool
    revision: int | None = None


class ConversationHistoryRuntimeOwner:
    """Own persisted history mutations and their explicit side effects."""

    request_only_continuation_cue = (
        conversation_history_runtime.REQUEST_ONLY_CONTINUATION_CUE
    )

    def __init__(
        self,
        conversation: ConversationService,
        config: RuntimeConfigReader,
        *,
        relay_metadata: RelayMetadataSanitizer,
        committer: AssistantHistoryCommitter,
        chat_view: ChatViewPublisher,
        transactions: ConversationTransactionMaintenance,
        memory: ConversationMemoryTriggers,
        clock=time.time,
    ) -> None:
        self._conversation = conversation
        self._config = config
        self._relay_metadata = relay_metadata
        self._committer = committer
        self._chat_view = chat_view
        self._transactions = transactions
        self._memory = memory
        self._clock = clock

    def history_snapshot(self) -> tuple[InputTurn, ...]:
        return tuple(
            _public_turn(item) for item in self._conversation.message_mappings()
        )

    def history_has_role(self, role: str) -> bool:
        wanted = str(role or "").strip().lower()
        return any(
            str(item.get("role", "") or "").strip().lower() == wanted
            for item in self.history_snapshot()
        )

    def discard_last_exchange_for_retry(self) -> bool:
        history = list(self.history_snapshot())
        original_count = len(history)
        if history and _role(history[-1]) == "assistant":
            history.pop()
        if history and _role(history[-1]) in self._input_roles():
            history.pop()
        if len(history) == original_count:
            return False
        self._replace_history(history, rebuild=True)
        return True

    def prepare_regeneration_turn(
        self, in_history: bool
    ) -> tuple[InputTurn | None, bool]:
        history = list(self.history_snapshot())
        resumed, removed = conversation_history_runtime.prepare_regeneration_turn(
            history,
            target_in_history=bool(in_history),
            input_roles=self._input_roles(),
        )
        transaction_id = str(
            (resumed or {}).get("normal_chat_transaction_id") or ""
        )
        transaction_is_current = bool(
            transaction_id
            and self._transactions.is_current(
                transaction_id,
                session_generation=(
                    self._conversation.snapshot().session_generation.value
                ),
            )
        )
        # A completed Normal Chat transaction is no longer current, but it may
        # still own the retained regeneration source.  Leave its assistant
        # message in place until coordinated regeneration accepts the exact
        # source and removes that message atomically.  Replacing history here
        # would also discard the transient source used by proactive replies.
        # Untagged legacy history still needs the eager compatibility mutation.
        if removed and not transaction_is_current and not transaction_id:
            self._replace_history(history, rebuild=True)
        return (
            copy.deepcopy(dict(resumed)) if isinstance(resumed, Mapping) else None,
            bool(removed),
        )

    def record_interrupted_assistant(
        self,
        request: RequestContext | None,
        text: str,
        *,
        hidden_proactive: bool = False,
        expected_revision: int | None = None,
    ) -> bool | InterruptedAssistantOutcome:
        if expected_revision is not None:
            return self._record_interrupted_if_revision(
                request, text, expected_revision=expected_revision,
                hidden_proactive=hidden_proactive,
            )
        final_text = str(text or "").strip()
        request_context = dict(request or {})
        revision = self._conversation.snapshot().revision
        expected_generation = _optional_int(
            request_context.get("session_generation")
        )
        if (
            expected_generation is not None
            and self._conversation.snapshot().session_generation.value
            != expected_generation
        ):
            return False
        transaction_id = str(
            request_context.get("normal_chat_transaction_id") or ""
        )
        history = list(self.history_snapshot())
        if not final_text:
            # Generated history may be visible before the first audible sample.
            # Only its exact transaction may withdraw that unheard assistant;
            # never overwrite a concurrent edit, reset, or replacement turn.
            if (
                expected_generation is not None
                and transaction_id
                and history
                and _role(history[-1]) == "assistant"
                and history[-1].get("origin") == "assistant_reply"
                and str(history[-1].get("normal_chat_transaction_id") or "")
                == transaction_id
            ):
                removed = self._conversation.replace_messages_if_revision(
                    history[:-1], expected_revision=revision
                )
                if removed is not None:
                    self._transactions.prune()
                    self._chat_view.request_rebuild()
            return False
        if history and _role(history[-1]) == "assistant":
            tail_transaction_id = str(
                history[-1].get("normal_chat_transaction_id") or ""
            )
            if transaction_id and tail_transaction_id != transaction_id:
                return False
        # Accepted input can itself have role=assistant and the same transaction.
        # Tagged input needs a new response commit, not an in-place replacement.
        if (
            history
            and _role(history[-1]) == "assistant"
            and (
                not transaction_id
                or history[-1].get("origin") == "assistant_reply"
            )
        ):
            interrupted = dict(history[-1])
            interrupted["content"] = final_text
            relay = self._relay_metadata.sanitize(
                request_context.get("identity_relay_metadata")
            )
            if relay is not None:
                interrupted["identity_relay"] = copy.deepcopy(dict(relay))
            persona = self._assistant_persona_attribution(
                request_context.get("assistant_persona")
            )
            if persona is not None and not isinstance(
                interrupted.get("quick_persona"), Mapping
            ):
                interrupted["quick_persona"] = persona
            history[-1] = interrupted
            self._replace_history(history, rebuild=True)
            return False
        appended = self.append_assistant_history_turn(
            final_text,
            identity_relay=request_context.get("identity_relay_metadata"),
            expected_session_generation=expected_generation,
            expected_turn_id=transaction_id or None,
            hidden_proactive=bool(hidden_proactive),
            assistant_persona=request_context.get("assistant_persona"),
        )
        if appended is None:
            return False
        self._chat_view.request_rebuild()
        return True

    def _record_interrupted_if_revision(
        self, request, text, *, expected_revision, hidden_proactive,
    ) -> InterruptedAssistantOutcome:
        """Phone-only CAS; callbacks cannot change the returned commit revision."""
        context = dict(request or {})
        snapshot = self._conversation.snapshot()
        transaction_id = str(context.get("normal_chat_transaction_id") or "")
        if (snapshot.revision != expected_revision or not transaction_id
                or snapshot.session_generation.value != context.get("session_generation")):
            return InterruptedAssistantOutcome(False)
        history = list(self.history_snapshot())
        if not history or history[-1].get("normal_chat_transaction_id") != transaction_id:
            return InterruptedAssistantOutcome(False)
        final_text = str(text or "").strip()
        has_reply = history[-1].get("origin") == "assistant_reply" and _role(history[-1]) == "assistant"
        if has_reply:
            if final_text:
                history[-1] = dict(history[-1], content=final_text)
            else:
                history.pop()
        elif final_text:
            assistant = {
                "role": "assistant", "content": final_text, "origin": "assistant_reply",
                "created_at": float(self._clock()), "normal_chat_transaction_id": transaction_id,
            }
            relay = self._relay_metadata.sanitize(context.get("identity_relay_metadata"))
            if relay is not None:
                assistant["identity_relay"] = copy.deepcopy(dict(relay))
            persona = self._assistant_persona_attribution(context.get("assistant_persona"))
            if persona is not None:
                assistant["quick_persona"] = persona
            if hidden_proactive:
                assistant["hidden_proactive"] = True
            history.append(assistant)
        # Even the unheard/no-assistant case crosses the CAS boundary, obtaining
        # an authoritative revision for conditional acceptance.
        committed = self._conversation.replace_messages_if_revision(
            history, expected_revision=expected_revision)
        if committed is None:
            return InterruptedAssistantOutcome(False)
        outcome = InterruptedAssistantOutcome(True, committed.revision)
        self._transactions.prune()
        self._chat_view.request_rebuild()
        return outcome

    def append_assistant_history_turn(
        self,
        text: str,
        *,
        identity_relay: object = None,
        expected_session_generation: int | None = None,
        expected_turn_id: str | None = None,
        hidden_proactive: bool = False,
        assistant_persona: object = None,
    ) -> InputTurn | None:
        if (
            expected_session_generation is not None
            and self._conversation.snapshot().session_generation.value
            != int(expected_session_generation)
        ):
            return None
        metadata: dict[str, object] = {
            "origin": "assistant_reply",
            "created_at": float(self._clock()),
        }
        if hidden_proactive:
            metadata["hidden_proactive"] = True
        persona = self._assistant_persona_attribution(assistant_persona)
        if persona is not None:
            metadata["quick_persona"] = persona
        relay = self._relay_metadata.sanitize(identity_relay)
        if relay is None:
            history = self.history_snapshot()
            if history:
                relay = self._relay_metadata.sanitize(
                    history[-1].get("identity_relay")
                )
        if relay is not None:
            metadata["identity_relay"] = copy.deepcopy(dict(relay))
        transaction_id = str(expected_turn_id or "").strip()
        if transaction_id:
            metadata["normal_chat_transaction_id"] = transaction_id
            committed = self._committer.commit(
                str(text or ""),
                metadata=metadata,
                expected_session_generation=expected_session_generation,
                expected_turn_id=transaction_id,
            )
            return copy.deepcopy(dict(committed)) if committed is not None else None
        turn: InputTurn = {
            "role": "assistant",
            "content": str(text or ""),
            **metadata,
        }
        self._conversation.append_message(turn)
        return turn

    def _assistant_persona_attribution(
        self,
        value: object,
    ) -> dict[str, object] | None:
        raw = dict(value) if isinstance(value, Mapping) else {}
        if not raw:
            config = self._config.current()
            raw = {
                "name": config.get("active_quick_persona_name", ""),
                "avatar_path": config.get("persona_visual_reference_path", ""),
                "mood_tags": config.get("persona_mood_tags", {}),
            }
        result = {
            "name": str(raw.get("name", "") or "").strip(),
            "avatar_path": str(raw.get("avatar_path", "") or "").strip(),
        }
        result = {key: item for key, item in result.items() if item}
        if result and isinstance(raw.get("mood_tags"), Mapping) and raw["mood_tags"]:
            result["mood_tags"] = dict(raw["mood_tags"])
        return result or None

    def apply_stored_chat_history_limit(self) -> None:
        values = self._config.current()
        limit = conversation_history_runtime.stored_chat_history_limit(values)
        history = list(self.history_snapshot())
        limited = conversation_history_runtime.apply_stored_chat_history_limit(
            history, limit
        )
        if limited != history:
            self._replace_history(limited, rebuild=False)
        else:
            self._transactions.prune()

    def pop_last_proactive_placeholder(self, content: str) -> bool:
        history = list(self.history_snapshot())
        if not history:
            return False
        last = history[-1]
        if (
            str(last.get("content", "") or "") != str(content or "")
            or _role(last) not in {"user", "system"}
        ):
            return False
        history.pop()
        self._replace_history(history, rebuild=False)
        return True

    def maybe_start_continuity_memory_auto_update(self) -> None:
        self._memory.maybe_update_continuity()

    def maybe_start_long_term_memory_auto_archive(self) -> None:
        self._memory.maybe_archive_long_term()

    def _replace_history(
        self, history: list[Mapping[str, object]], *, rebuild: bool
    ) -> None:
        self._conversation.replace_messages(history)
        self._transactions.prune()
        if rebuild:
            self._chat_view.request_rebuild()

    def _input_roles(self) -> set[str]:
        role = str(
            self._config.current().get("input_message_role", "user") or "user"
        ).strip().lower()
        return {"user", "system", role if role in {"user", "system", "assistant"} else "user"}


class UserImageRuntimeOwner:
    """Own pending image consumption while capture remains an edge capability."""

    def __init__(
        self,
        *,
        policy: UserImagePolicy,
        screen_capture: ScreenImageCapture | None = None,
        logger=print,
    ) -> None:
        self._policy = policy
        self._screen_capture = screen_capture
        self._logger = logger

    def pending_user_image_attachment(self) -> bool:
        return bool(user_image_turns.pending_attachment())

    def maybe_arm_screen_image_for_user_turn(
        self,
        turn: InputTurn,
        *,
        is_placeholder: bool = False,
    ) -> object:
        if _role(turn) != "user" or is_placeholder:
            return None
        if user_image_turns.pending_attachment():
            return None
        if not self._policy.auto_attach_screen() or not self._policy.source_enabled("screen"):
            return None
        if self._screen_capture is None:
            return None
        try:
            snapshot = self._screen_capture.capture() or {}
            path = str(snapshot.get("image_path", "") or "").strip()
            if not path:
                return None
            return user_image_turns.set_pending_attachment(path, source="screen")
        except Exception as exc:
            self._logger(
                f"⚠️ [ScreenSource] Could not capture screen attachment for user turn: {exc}"
            )
            return None

    def attach_pending_user_image_to_turn(
        self,
        turn: InputTurn,
        *,
        is_placeholder: bool = False,
    ) -> InputTurn:
        item = dict(turn or {})
        pending = user_image_turns.consume_pending_attachment()
        if _role(item) != "user" or is_placeholder or not pending:
            return item
        source = str(pending.get("attachment_source", "image") or "image").strip().lower()
        path = str(pending.get("attachment_image_path", "") or "").strip()
        if not self._policy.source_enabled(source):
            return item
        if path:
            item["attachment_image_path"] = path
            item["attachment_source"] = source
        return item

    def clear_pending_user_image_attachment(self) -> None:
        user_image_turns.clear_pending_attachment()


def _public_turn(item: Mapping[str, object]) -> InputTurn:
    turn = dict(item)
    turn.pop("message_id", None)
    return turn


def _role(turn: Mapping[str, object]) -> str:
    return str(turn.get("role", "") or "").strip().lower()


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


__all__ = [
    "AssistantHistoryCommitter",
    "ChatViewPublisher",
    "ConversationHistoryRuntimeOwner",
    "ConversationMemoryTriggers",
    "ConversationSessionRuntimeOwner",
    "ConversationTransactionMaintenance",
    "MappingRuntimeConfig",
    "PermissiveUserImagePolicy",
    "RelayMetadataSanitizer",
    "RuntimeConfigReader",
    "ScreenImageCapture",
    "UserImagePolicy",
    "UserImageRuntimeOwner",
]
