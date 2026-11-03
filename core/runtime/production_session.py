"""Concrete production ownership for persisted chat-session state."""

from __future__ import annotations

from core.image_attachments import image_paths, set_image_paths

import copy
import json
import re
import threading
import uuid
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from core.runtime import chat_sessions
from core.runtime.contracts import CommandResult
from core.runtime.identity_relay import IdentityRelaySnapshotRegistry

if TYPE_CHECKING:
    from core.runtime.config import RuntimeConfigService
    from core.runtime.conversation import ConversationService
    from core.runtime.conversation_owners import (
        ConversationHistoryRuntimeOwner,
        ConversationSessionRuntimeOwner,
        UserImageRuntimeOwner,
    )
    from core.runtime.memory import MemoryService
    from core.runtime.normal_chat import NormalChatApplicationAdapter
    from core.runtime.proactive import ProactiveService
    from core.runtime.replay import ReplayService
    from core.runtime.sensory import SensoryService
    from core.runtime.visual import VisualService
    from core.runtime.identifiers import WorkLease


InputTurn = dict[str, object]


class IdentityRelaySessionCompatibility(Protocol):
    """Persist the addon-owned Relay session payload beside snapshot records."""

    def reset_session(self) -> None: ...

    def export_session(self) -> Mapping[str, object] | None: ...

    def import_session(self, payload: Mapping[str, object]) -> None: ...


class SessionMemoryCompatibility(Protocol):
    """Own compatibility settings surrounding the typed memory service."""

    def new_memory_id(self) -> str: ...

    def activate_memory(self, memory_id: str) -> str: ...

    def set_embedding_baseline(self, model: str, context_length: int) -> None: ...

    def reconcile_history_edit(
        self,
        previous_history: Sequence[Mapping[str, object]],
        replacement_history: Sequence[Mapping[str, object]],
    ) -> Mapping[str, object]: ...

    def pending_content_migration_report(self) -> Mapping[str, object]: ...

    def reconcile_message_deletion(
        self,
        previous_history: Sequence[Mapping[str, object]],
        replacement_history: Sequence[Mapping[str, object]],
        *, message_index: int, remove_memories: bool,
    ) -> Mapping[str, object]: ...


class SensoryHistorySanitizer(Protocol):
    def sanitize(self, entry: object) -> Mapping[str, object] | None: ...


class AssistantMemoryState:
    """Own the JSON-compatible assistant-memory document for one chat session."""

    def __init__(self, default: Mapping[str, object] | None = None) -> None:
        base = default or {"preferences": {}, "recent_context": []}
        self._default = _json_mapping(base)
        self._lock = threading.RLock()
        self._value = copy.deepcopy(self._default)

    def default_snapshot(self) -> dict[str, object]:
        return copy.deepcopy(self._default)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return copy.deepcopy(self._value)

    def restore(self, value: Mapping[str, object]) -> None:
        replacement = _json_mapping(value)
        replacement.setdefault("preferences", {})
        replacement.setdefault("recent_context", [])
        with self._lock:
            self._value = replacement

    def reset(self) -> None:
        with self._lock:
            self._value = copy.deepcopy(self._default)


class ProductionChatSessionOwner:
    """Own typed queue staging and complete production session transitions.

    The owner deliberately receives finite domain collaborators. It does not expose
    lookup or delegation APIs, and no collaborator imports the legacy engine.
    """

    __slots__ = (
        "_assistant_memory",
        "_clock",
        "_config",
        "_conversation",
        "_history",
        "_identity_relay",
        "_lock",
        "_logger",
        "_memory",
        "_normal_chat",
        "_passthrough",
        "_proactive",
        "_relay_snapshot_session",
        "_relay_snapshots",
        "_replay",
        "_restore_avatar_presentation",
        "_sensory",
        "_sensory_history",
        "_session",
        "_session_memory",
        "_user_images",
        "_visual",
    )

    def __init__(
        self,
        *,
        config: RuntimeConfigService,
        conversation: ConversationService,
        session: ConversationSessionRuntimeOwner,
        history: ConversationHistoryRuntimeOwner,
        user_images: UserImageRuntimeOwner,
        normal_chat: NormalChatApplicationAdapter,
        assistant_memory: AssistantMemoryState,
        memory: MemoryService,
        session_memory: SessionMemoryCompatibility,
        identity_relay: IdentityRelaySessionCompatibility,
        relay_snapshots: IdentityRelaySnapshotRegistry,
        sensory: SensoryService,
        sensory_history: SensoryHistorySanitizer,
        proactive: ProactiveService,
        replay: ReplayService,
        visual: VisualService,
        restore_avatar_presentation: Callable[[WorkLease], CommandResult[bool]] | None = None,
        clock: Callable[[], float] = time.time,
        logger: Callable[[str], object] = print,
    ) -> None:
        self._config = config
        self._conversation = conversation
        self._session = session
        self._history = history
        self._user_images = user_images
        self._normal_chat = normal_chat
        self._assistant_memory = assistant_memory
        self._memory = memory
        self._session_memory = session_memory
        self._identity_relay = identity_relay
        self._relay_snapshots = relay_snapshots
        self._sensory = sensory
        self._sensory_history = sensory_history
        self._proactive = proactive
        self._replay = replay
        self._visual = visual
        self._restore_avatar_presentation = restore_avatar_presentation
        self._clock = clock
        self._logger = logger
        self._lock = threading.RLock()
        self._passthrough: dict[str, object] = {}
        self._config.update("chat_character_conversation_id", uuid.uuid4().hex)
        self._relay_snapshot_session = self._relay_snapshots.begin_session(
            self._conversation.session_lease()
        )

    def queue_typed_chat_message(
        self,
        text: str,
        role: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        """Stage one typed message through image and transaction ownership."""

        content = str(text or "").strip()
        if not content:
            return {"queued": False, "reason": "empty"}
        values = self._config.snapshot().values
        input_role = str(
            role or values.get("input_message_role", "user") or "user"
        ).strip().lower()
        if input_role not in {"user", "system", "assistant"}:
            input_role = "user"
        turn: InputTurn = {
            "role": input_role,
            "content": content,
            "origin": "input",
        }
        turn_metadata = dict(metadata or {})
        capture_id = _remote_capture_id(turn_metadata.get("remote_capture_id"))
        if capture_id:
            turn["remote_capture_id"] = capture_id
            if turn_metadata.get("phone_reply_control") is True:
                turn["phone_reply_control"] = True
                if turn_metadata.get("phone_shared_queue") is True:
                    turn["phone_shared_queue"] = True
        raw_output_token_cap = turn_metadata.get("normal_chat_output_token_cap")
        if raw_output_token_cap is not None and not isinstance(
            raw_output_token_cap,
            bool,
        ):
            try:
                output_token_cap = int(raw_output_token_cap)
            except (TypeError, ValueError, OverflowError):
                output_token_cap = 0
            if output_token_cap > 0:
                turn["normal_chat_output_token_cap"] = min(
                    output_token_cap,
                    131_072,
                )
        response_guidance = str(
            turn_metadata.get("companion_orb_response_guidance", "") or ""
        ).strip()
        if response_guidance:
            turn["companion_orb_response_guidance"] = response_guidance[:1400]
        debug_trace_id = _remote_capture_id(
            turn_metadata.get("companion_orb_debug_trace_id")
        )
        if debug_trace_id:
            turn["companion_orb_debug_trace_id"] = debug_trace_id
        attachments = image_paths(turn_metadata)
        if attachments:
            if input_role != "user":
                raise ValueError("Image input turns must use the user role.")
            resolved_paths = [Path(path).expanduser().resolve() for path in attachments]
            if any(not path.is_file() for path in resolved_paths):
                raise ValueError("An attached image path does not exist.")
            self._user_images.clear_pending_user_image_attachment()
            set_image_paths(turn, [str(path) for path in resolved_paths])
            turn["attachment_source"] = (
                str(turn_metadata.get("attachment_source", "image") or "image")
                .strip()
                .lower()
                or "image"
            )
        else:
            if input_role != "user" and self._user_images.pending_user_image_attachment():
                self._user_images.clear_pending_user_image_attachment()
            self._user_images.maybe_arm_screen_image_for_user_turn(turn)
            turn = dict(self._user_images.attach_pending_user_image_to_turn(turn))
        cancel_replays = getattr(self._replay, "cancel_all", None)
        if callable(cancel_replays):
            cancelled_replay = cancel_replays("typed_input")
            if not cancelled_replay.accepted:
                failure = getattr(cancelled_replay, "failure", None)
                raise RuntimeError(
                    str(
                        getattr(failure, "message", "")
                        or "Could not stop active replay."
                    )
                )
        turn = dict(self._normal_chat.begin(turn))
        self._session.stage_pending_loaded_input_turn(turn)
        self._session.request_chat_view_rebuild()
        return {"queued": True, "role": input_role, "content": content}

    def delete_chat_message(self, message_id: str, *, expected_revision: int,
                            expected_session: int, remove_memories: bool,
                            is_busy: Callable[[], bool]) -> CommandResult:
        with self._lock:
            def reconcile(previous, replacement, position):
                result = self._session_memory.reconcile_message_deletion(previous, replacement,
                    message_index=position, remove_memories=remove_memories)
                if position == len(previous) and previous[-1].get('role') == 'user':
                    self._session.stage_pending_loaded_input_turn(None)
                return result
            return self._conversation.delete_message_if_current(message_id,
                expected_revision=expected_revision, expected_session=expected_session,
                is_busy=is_busy, reconcile=reconcile)

    def consume_pending_loaded_input_turn(self) -> InputTurn | None:
        return self._session.consume_pending_loaded_input_turn()

    def replace_chat_conversation_history(
        self,
        raw_history: list[Mapping[str, object]],
        *,
        allow_pending_loaded_user: bool = False,
        expected_history: list[Mapping[str, object]] | None = None,
        reconcile_long_term_memory_archive: bool = False,
    ) -> Mapping[str, object]:
        """Compare and replace visible history without accepting stale editors."""

        if not isinstance(raw_history, list):
            raise ValueError("conversation_history must be a list")
        with self._lock:
            before = self._conversation.snapshot()
            current = self._history_list()
            if expected_history is not None and current != _copy_history(
                expected_history
            ):
                return {
                    "replaced": False,
                    "reason": "history_changed",
                    "conversation_turns": len(current),
                }
            replacement = self._sanitize_history(raw_history)
            from core.chat_context_safety import history_signature
            from core.conversation_history import apply_stored_chat_history_limit, stored_chat_history_limit
            imported_signature = history_signature(apply_stored_chat_history_limit(
                replacement, stored_chat_history_limit(self._config.snapshot().values)))
            if self._conversation.snapshot().revision != before.revision:
                current = self._history_list()
                return {
                    "replaced": False,
                    "reason": "history_changed",
                    "conversation_turns": len(current),
                }
            self._conversation.replace_messages(replacement)
            self._history.apply_stored_chat_history_limit()
            final_history = self._history_list()
            pending = self._loaded_user_turn(final_history, allow_pending_loaded_user)
            self._session.stage_pending_loaded_input_turn(pending)
            result: dict[str, object] = {
                "replaced": True,
                "conversation_turns": len(final_history),
                "history_signature": imported_signature,
            }
            if reconcile_long_term_memory_archive:
                result["long_term_memory_reconciliation"] = dict(
                    self._session_memory.reconcile_history_edit(
                        current,
                        final_history,
                    )
                )
            return result

    def reset_session_state(self) -> None:
        """Advance generation and reset all chat-session-owned production state."""

        with self._lock:
            self._proactive.cancel("session_reset")
            self._replay.cancel_all("session_reset")
            previous_generation = self._conversation.snapshot().session_generation
            self._conversation.reset()
            restore_avatar_presentation = self._restore_avatar_presentation
            if restore_avatar_presentation is not None:
                try:
                    restored = restore_avatar_presentation(
                        self._conversation.session_lease()
                    )
                    if not restored.accepted:
                        self._log_result_failure(
                            "Avatar session presentation reset incomplete",
                            restored,
                        )
                except BaseException as exc:
                    self._logger(
                        "Avatar session presentation reset failed: " + str(exc)
                    )
            self._visual.cancel_session(previous_generation, "session_reset")
            self._memory.release_session(previous_generation)
            self._clear_transient_session_state()
            self._assistant_memory.reset()
            self._passthrough = {}
            self._config.update("chat_character_conversation_id", uuid.uuid4().hex)
            memory_id = self._session_memory.activate_memory(
                self._session_memory.new_memory_id()
            )
            self._config.update_many(
                {
                    "continuity_memory_id": memory_id,
                    "active_chat_context_path": "",
                    "active_chat_context_name": "",
                    "continuity_memory_auto_baseline_turn_count": 0,
                }
            )
            reset = self._sensory.reset_session()
            if not reset.accepted:
                self._log_result_failure("Sensory session reset incomplete", reset)
                return
            if not self._sensory.snapshot_state().running:
                return
            restarted = self._sensory.start_hidden_loop(
                self._conversation.session_lease()
            )
            if not restarted.accepted:
                self._log_result_failure("Sensory hidden-loop restart failed", restarted)

    def export_chat_session_state(self) -> Mapping[str, object]:
        """Freeze a version-1 payload compatible with legacy saved chats."""

        with self._lock:
            lease = self._conversation.session_lease()
            self._visual.reconcile_history(lease)
            relay_session = self._identity_relay.export_session()
            relay_snapshots = self._export_relay_snapshots()
            history = self._sanitize_history(self._history_list())
            sensory_history = tuple(
                item
                for item in (
                    self._sensory_history.sanitize(entry)
                    for entry in self._sensory.hidden_history_snapshot()
                )
                if item is not None
            )
            return chat_sessions.build_chat_session_payload(
                chat_sessions.ChatSessionExportData(
                    saved_at=float(self._clock()),
                    passthrough=copy.deepcopy(self._passthrough),
                    config=dict(self._config.snapshot().values),
                    history=history,
                    assistant_memory=self._assistant_memory.snapshot(),
                    sensory_hidden_history=sensory_history,
                    relay_session=(
                        dict(relay_session)
                        if isinstance(relay_session, Mapping)
                        else {}
                    ),
                    relay_snapshots=relay_snapshots,
                )
            )

    def import_chat_session_state(
        self,
        payload: Mapping[str, object],
    ) -> Mapping[str, object]:
        """Validate first, then replace the complete persisted session state."""

        values = self._config.snapshot().values
        plan = chat_sessions.plan_chat_session_import(
            payload,
            sanitize_relay_registry=_copy_relay_registry,
            sanitize_sensory_event=self._sensory_history.sanitize,
            default_assistant_memory=self._assistant_memory.default_snapshot,
            fallback_embedding_model=str(
                values.get(
                    "long_term_memory_embedding_model",
                    "text-embedding-bge-m3",
                )
                or "text-embedding-bge-m3"
            ),
            fallback_embedding_context_length=int(
                values.get("long_term_memory_embedding_context_length", 8192)
                or 8192
            ),
        )
        with self._lock:
            self._proactive.cancel("session_import")
            self._replay.cancel_all("session_import")
            previous_generation = self._conversation.snapshot().session_generation
            self._conversation.load_messages(())
            self._memory.release_session(previous_generation)
            self._visual.cancel_session(previous_generation, "session_import")
            self._clear_transient_session_state()
            self._passthrough = copy.deepcopy(dict(plan.passthrough))
            character_scope = str(payload.get("chat_character_conversation_id", ""))
            if not re.fullmatch(r"[a-f0-9]{32}", character_scope):
                character_scope = uuid.uuid4().hex
            self._config.update("chat_character_conversation_id", character_scope)
            self._restore_relay_snapshots(plan.relay_snapshots)
            self._session_memory.set_embedding_baseline(
                plan.embedding_model,
                plan.embedding_context_length,
            )
            configured_memory_id = str(
                values.get("continuity_memory_id", "") or ""
            )
            memory_id = self._session_memory.activate_memory(
                plan.continuity_memory_id or configured_memory_id
            )
            self._config.update("continuity_memory_id", memory_id)
            self._sensory.restore_hidden_history(plan.sensory_hidden_history)
            self._sensory.prune_hidden_history()
            history_result = self.replace_chat_conversation_history(
                list(plan.history),
                # Loading restores history only; even a trailing user turn is
                # not a fresh Send/Regenerate request.
                allow_pending_loaded_user=False,
            )
            self._identity_relay.import_session(plan.relay_session)
            conversation_turns = int(history_result["conversation_turns"])
            self._config.update(
                "continuity_memory_auto_baseline_turn_count",
                conversation_turns,
            )
            self._assistant_memory.restore(plan.assistant_memory)
            return {
                "conversation_turns": conversation_turns,
                "history_signature": history_result['history_signature'],
                "assistant_memory_keys": sorted(
                    str(key) for key in self._assistant_memory.snapshot()
                ),
                "continuity_memory_id": memory_id,
                "conversation_content_migration": dict(
                    plan.conversation_migration
                ),
                "long_term_memory_content_migration": dict(
                    self._session_memory.pending_content_migration_report()
                ),
            }

    def snapshot_session(self) -> Mapping[str, object]:
        return self.export_chat_session_state()

    def _clear_transient_session_state(self) -> None:
        self._session.stage_pending_loaded_input_turn(None)
        self._session.prune_normal_chat_transactions()
        self._user_images.clear_pending_user_image_attachment()
        self._identity_relay.reset_session()
        self._relay_snapshot_session = self._relay_snapshots.begin_session(
            self._conversation.session_lease()
        )

    def _sanitize_history(
        self,
        raw_history: Sequence[Mapping[str, object]],
    ) -> list[InputTurn]:
        return [
            turn
            for turn in (
                chat_sessions.sanitize_chat_turn(
                    item,
                    sanitize_relay_metadata=_sanitize_relay_metadata,
                )
                for item in raw_history
            )
            if turn is not None
        ]

    def _history_list(self) -> list[InputTurn]:
        return [dict(item) for item in self._conversation.message_mappings()]

    @staticmethod
    def _loaded_user_turn(
        history: Sequence[Mapping[str, object]],
        allowed: bool,
    ) -> Mapping[str, object] | None:
        if not allowed or not history:
            return None
        last = history[-1]
        if str(last.get("role", "") or "").strip().lower() != "user":
            return None
        return last

    def _export_relay_snapshots(self) -> Mapping[str, Mapping[str, object]]:
        result = self._relay_snapshots.export_session(
            self._relay_snapshot_session
        )
        if not result.accepted:
            raise RuntimeError(_result_failure_message(result))
        return {
            str(key): copy.deepcopy(dict(value))
            for key, value in dict(result.value or {}).items()
        }

    def _restore_relay_snapshots(self, snapshots: object) -> None:
        restored = self._relay_snapshots.restore_session(
            self._relay_snapshot_session,
            snapshots,
        )
        if not restored.accepted:
            raise RuntimeError(_result_failure_message(restored))

    def _log_result_failure(self, label: str, result: object) -> None:
        self._logger(f"{label}: {_result_failure_message(result)}")


def _copy_history(
    history: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    return [copy.deepcopy(dict(item)) for item in history]


def _copy_relay_registry(
    value: object,
) -> Mapping[str, Mapping[str, object]]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): copy.deepcopy(dict(item))
        for key, item in value.items()
        if isinstance(item, Mapping)
    }


def _sanitize_relay_metadata(value: object) -> Mapping[str, object] | None:
    metadata = IdentityRelaySnapshotRegistry.sanitize_metadata(value)
    return metadata.as_mapping() if metadata is not None else None


def _json_mapping(value: Mapping[str, object]) -> dict[str, object]:
    return json.loads(json.dumps(dict(value)))


def _remote_capture_id(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "", str(value or ""))[:96]


def _result_failure_message(result: object) -> str:
    failure = getattr(result, "failure", None)
    return str(getattr(failure, "message", "") or "unknown runtime error")


__all__ = [
    "AssistantMemoryState",
    "IdentityRelaySessionCompatibility",
    "ProductionChatSessionOwner",
    "SensoryHistorySanitizer",
    "SessionMemoryCompatibility",
]
