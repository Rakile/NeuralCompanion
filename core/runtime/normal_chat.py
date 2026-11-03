"""Explicit preparation and provider-execution ownership for Normal Chat."""

from __future__ import annotations

import hashlib
import json
import logging

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from types import MappingProxyType
import threading
import time
import uuid
from typing import Protocol

from core import companion_orb_vision_debug, streaming_text, text_tags
from core.streaming_deadlines import StreamingDeadlinePublisher, SubscribableEvent
from core.orb_watch_capture import retain_watch_capture, retain_watch_captures
from core.communication_trace import record_to, lease_correlation, correlation_scope
from core.conversation_tools import TOOL_OPTION, ToolOutcome, decode_tool_round
from core.runtime.conversation_tools import run_tool_conversation
from core.runtime import assistant_directives
from core.runtime.chat_transactions import (
    NormalChatAcceptance,
    NormalChatCommitReceipt,
    NormalChatConversationPort,
    NormalChatIdentityRelayPort,
    NormalChatPersonaSnapshot,
    NormalChatPreparationSnapshot,
    NormalChatProviderPort,
    NormalChatRequestAssembler,
    NormalChatRequestSnapshot,
    NormalChatTerminalReceipt,
    NormalChatTransactionService,
    NormalChatTransactionSnapshot,
    NormalChatTransactionStatus,
    NormalChatTurnPort,
    PreparedNormalChatRequest,
)
from core.runtime.contracts import CancellationToken, CommandResult, RuntimeFailure
from core.runtime.continuous_next_reply import (
    ContinuousStageBinding, StagedAssistantReply, character_voice_fingerprint,
    request_fingerprint,
    voice_settings_fingerprint,
)
from core.runtime.identifiers import TurnId, WorkLease
from core.runtime.reply_delivery import ReplyDelivery, apply_reply_delivery
from core.runtime.lifecycle import WorkerHandle, WorkerSupervisor
from core.runtime.prompt_assembly import (
    PromptAssemblyService,
    PromptInputs,
    PromptRequest,
)
from core.runtime.providers import FrozenTurnRequest, ProviderSelection
from core.runtime.turns import TurnSnapshot, TurnTerminalStatus


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    if isinstance(value, bytearray):
        return bytes(value)
    return value


def _freeze_mapping(value: Mapping[str, object] | None) -> Mapping[str, object]:
    return _freeze(dict(value or {}))  # type: ignore[return-value]


def _plain_mapping(value: Mapping[str, object] | None) -> dict[str, object] | None:
    if value is None:
        return None

    def thaw(item: object) -> object:
        if isinstance(item, Mapping):
            return {str(key): thaw(child) for key, child in item.items()}
        if isinstance(item, (tuple, list)):
            return [thaw(child) for child in item]
        if isinstance(item, (set, frozenset)):
            return [thaw(child) for child in item]
        return item

    return thaw(value)  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class NormalChatPromptPlan:
    """Typed prompt inputs plus the exact provider request options to apply."""

    inputs: PromptInputs
    model_id: str | None = None
    parameters: Mapping[str, object] = field(default_factory=dict)
    additional_parameters: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.inputs, PromptInputs):
            raise TypeError("Normal Chat prompt plans require PromptInputs.")
        if self.model_id is not None:
            object.__setattr__(self, "model_id", str(self.model_id))
        object.__setattr__(self, "parameters", _freeze_mapping(self.parameters))
        object.__setattr__(
            self,
            "additional_parameters",
            _freeze_mapping(self.additional_parameters),
        )


class NormalChatPromptPlanBuilder(Protocol):
    """Capture engine-specific prompt contributions as one immutable plan."""

    def capture(self, state: NormalChatPreparationSnapshot) -> NormalChatPromptPlan: ...


@dataclass(frozen=True, slots=True)
class PromptAssemblyNormalChatRequestAssembler:
    """Narrow composed adapter from a prompt plan to a provider-neutral request."""

    prompts: PromptAssemblyService
    plans: NormalChatPromptPlanBuilder

    def build(self, state: NormalChatPreparationSnapshot) -> PromptRequest:
        plan = self.plans.capture(state)
        if not isinstance(plan, NormalChatPromptPlan):
            raise TypeError("Normal Chat prompt capture returned an invalid plan.")
        request = self.prompts.build(plan.inputs)
        return request.with_options(
            model_id=plan.model_id,
            parameters=plan.parameters,
            additional_parameters=plan.additional_parameters,
        )


class NormalChatExecutionProvider(Protocol):
    def frozen_execution_available(
        self,
        selection: ProviderSelection,
        *,
        stream: bool = False,
    ) -> bool: ...

    def complete(
        self,
        request: FrozenTurnRequest,
        token: object,
    ) -> CommandResult[str]: ...

    def stream(
        self,
        request: FrozenTurnRequest,
        token: object,
    ) -> Iterable[str]: ...


class NormalChatHistory(Protocol):
    def message_mappings(self) -> tuple[dict[str, object], ...]: ...


class NormalChatConversationServices(
    NormalChatConversationPort,
    NormalChatHistory,
    Protocol,
):
    pass


class NormalChatProviderServices(
    NormalChatProviderPort,
    NormalChatExecutionProvider,
    Protocol,
):
    pass


@dataclass(frozen=True, slots=True)
class PreparedNormalChatTurn:
    transaction: NormalChatTransactionSnapshot
    request: NormalChatRequestSnapshot
    provider_request: PreparedNormalChatRequest
    trace: tuple[str, ...] = ("accepted", "request_frozen", "prepared")

    @property
    def lease(self) -> WorkLease:
        return self.request.lease

    @property
    def transaction_id(self) -> str:
        return self.request.transaction_id


@dataclass(frozen=True, slots=True)
class NormalChatStreamChunk:
    transaction_id: str
    request_id: str
    lease: WorkLease
    sequence: int
    text: str


class NormalChatStreamSink(Protocol):
    """External stream boundary; implementations must honor the supplied lease."""

    def publish(self, chunk: NormalChatStreamChunk) -> bool: ...


@dataclass(frozen=True, slots=True)
class NormalChatExecutionResult:
    prepared: PreparedNormalChatTurn
    text: str
    terminal: NormalChatTerminalReceipt
    commit: NormalChatCommitReceipt | None
    streamed: bool
    fallback_used: bool
    trace: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NormalChatExecutionSnapshot:
    prepared: PreparedNormalChatTurn
    done: bool
    result: NormalChatExecutionResult | None
    failure: RuntimeFailure | None
    trace: tuple[str, ...]


@dataclass(slots=True)
class NormalChatApplicationStream:
    """Controller-facing state for one uncommitted streamed provider reply."""

    done: threading.Event = field(default_factory=threading.Event)
    cancel_requested: threading.Event = field(default_factory=SubscribableEvent)
    full_text: str = ""
    error: BaseException | None = None


@dataclass(slots=True)
class _StreamPreview:
    request_id: str
    transaction_id: str
    session_generation: int
    state: NormalChatApplicationStream
    parts: list[str] = field(default_factory=list)


class NormalChatApplicationBlocked(RuntimeError):
    """Raised when the controller requests a stale or invalid chat route."""


class _ObsoleteOrbWatchOutput(Exception):
    """Quietly discard a hidden reply superseded before output admission."""


class NormalChatApplicationAdapter:
    """Adapt the typed transaction runtime to ConversationController's loop port.

    The controller still publishes assistant history after speech preparation. This
    adapter owns that exact transaction commit as well as provider dispatch and
    terminal cancellation.
    """

    def __init__(
        self,
        runtime: "NormalChatRuntime",
        *,
        blocked_error: type[BaseException] = NormalChatApplicationBlocked,
        memory_work_context: Callable[[], object] | None = None,
        visual_tail_filter: Callable[[str], tuple[str, str | None]] | None = None,
        visual_prefix_checker: Callable[[str], bool] | None = None,
        hidden_request_guard: Callable[[Mapping[str, object]], bool] | None = None,
        hidden_reply_delivered: Callable[[Mapping[str, object]], object] | None = None,
        hidden_reply_publication: Callable | None = None,
        conversation_tools: Callable[[str, dict], dict] | None = None,
        mcp_conversation_tools: Callable[[str, dict], dict] | None = None,
        mcp_model_notice: Callable[[NormalChatRequestSnapshot, str], None] | None = None,
        character_voice_turns=None,
        continuous_audio_stage: Callable[[StagedAssistantReply], bool] | None = None,
        continuous_audio_activate: Callable[[str], None] | None = None,
        continuous_audio_discard: Callable[[str], None] | None = None,
    ) -> None:
        self._runtime = runtime
        self._blocked_error = blocked_error
        self._memory_work_context = memory_work_context
        self._visual_tail_filter = visual_tail_filter
        self._visual_prefix_checker = visual_prefix_checker
        self._hidden_request_guard = hidden_request_guard
        self._hidden_reply_delivered = hidden_reply_delivered
        self._hidden_reply_publication = hidden_reply_publication
        self._mcp_conversation_tools = mcp_conversation_tools
        self._mcp_model_notice = mcp_model_notice
        self._mcp_model_reminders = set()
        if mcp_conversation_tools is not None:
            from core.runtime.conversation_tool_router import ConversationToolRouter
            self._conversation_tools = ConversationToolRouter(conversation_tools, mcp_conversation_tools)
        else:
            self._conversation_tools = conversation_tools
        self._character_voice_turns = character_voice_turns
        self._continuous_audio_stage = continuous_audio_stage
        self._continuous_audio_activate = continuous_audio_activate
        self._continuous_audio_discard = continuous_audio_discard
        self._tool_results = {}
        self._lock = threading.RLock()
        self._transactions: dict[str, NormalChatTransactionSnapshot] = {}
        self._requests: dict[str, NormalChatRequestSnapshot] = {}
        self._prepared: dict[str, PreparedNormalChatRequest] = {}
        self._continuous_stages: dict[str, StagedAssistantReply] = {}
        self._continuous_permits: dict[str, tuple[str, Mapping[str, object]]] = {}
        self._continuous_active_audio: dict[str, StagedAssistantReply] = {}
        self._stream_preview: _StreamPreview | None = None

    def stream_preview_snapshot(self) -> dict[str, object] | None:
        """Return only the current uncommitted stream text for phone display."""
        with self._lock:
            preview = self._stream_preview
            if preview is None:
                return None
            state = preview.state
            if state.cancel_requested.is_set() or state.error is not None:
                return None
            content = "".join(preview.parts)
            if self._visual_tail_filter is not None:
                content, _ = self._visual_tail_filter(content)
            if self._visual_prefix_checker is not None:
                open_marker = content.rfind("[")
                if open_marker > content.rfind("]") and self._visual_prefix_checker(
                    content[open_marker + 1 :]
                ):
                    content = content[:open_marker]
            if not content.strip():
                return None
            return {
                "normal_chat_transaction_id": preview.transaction_id,
                "session_generation": preview.session_generation,
                "content": content,
                "generation_complete": state.done.is_set() and state.error is None
                and not state.cancel_requested.is_set(),
            }

    def stage_continuous_next(
        self,
        proposed_user: Mapping[str, object],
        binding: ContinuousStageBinding,
        cancellation: CancellationToken,
    ) -> StagedAssistantReply | None:
        """Complete one private successor without accepting a conversation turn."""
        if cancellation.cancelled:
            return None
        stage_id = uuid.uuid4().hex
        proposed_user = dict(proposed_user, created_at=time.time())
        try:
            prepared = self._runtime.transactions.prepare_detached(
                proposed_user, binding, cancellation, stage_id=stage_id,
                memory_work_context=self._capture_memory_work_context())
            if prepared is None or cancellation.cancelled:
                return None
            if TOOL_OPTION in prepared.request.additional_params:
                return None  # Tool calls require a real accepted transaction.
            request = prepared.select_for_dispatch()
            result = self._runtime._providers.complete(request, cancellation)
            if not result.accepted or cancellation.cancelled:
                return None
            raw = str(result.value or '')
            context = self._character_voice_turns.get(stage_id) if self._character_voice_turns else None
            segments = ()
            text = raw
            if context is not None:
                from core.runtime.structured_character_voice import CharacterVoiceStream
                parsed = CharacterVoiceStream(context)
                parsed.feed(raw)
                parsed.finish()
                text, segments = parsed.text, tuple(parsed.parts)
            if not text.strip():
                return None
            stage = StagedAssistantReply(stage_id, binding, text,
                request_fingerprint(request), segments, (), cancellation,
                time.monotonic(), raw_response=raw,
                character_voice_fingerprint=character_voice_fingerprint(context),
                user_content=str(proposed_user.get('content') or '').strip(),
                user_created_at=proposed_user['created_at'])
            retired_stages: list[StagedAssistantReply] = []
            with self._lock:
                for key, old in tuple(self._continuous_stages.items()):
                    if old.token.cancelled or time.monotonic() - old.created_at >= 300:
                        retired_stages.append(self._continuous_stages.pop(key))
                self._continuous_stages[stage_id] = stage
                while len(self._continuous_stages) > 4:
                    oldest_id = next(iter(self._continuous_stages))
                    retired_stages.append(self._continuous_stages.pop(oldest_id))
            for retired in retired_stages:
                retired.token.cancel('continuous_stage_retired')
                self._run_continuous_audio_callback(
                    self._continuous_audio_discard, retired.stage_id)
            if self._continuous_audio_stage is not None:
                threading.Thread(target=lambda: self._run_continuous_audio_callback(
                    self._continuous_audio_stage, stage),
                    name='nc-continuous-next-tts', daemon=True).start()
            return stage
        except Exception:
            return None
        finally:
            if self._character_voice_turns is not None:
                self._character_voice_turns.retire(stage_id)

    def consume_continuous_next(
        self, stage: StagedAssistantReply,
        accepted_request: Mapping[str, object],
    ) -> bool:
        binding = accepted_request.get('binding')
        request = accepted_request.get('provider_request')
        if not isinstance(stage, StagedAssistantReply) or not isinstance(binding, ContinuousStageBinding):
            return False
        try:
            return stage.consume(binding, request, now=time.monotonic())
        except (TypeError, ValueError):
            return False

    def _take_continuous_stage(
        self, request: NormalChatRequestSnapshot, prepared: PreparedNormalChatRequest,
    ) -> StagedAssistantReply | None:
        with self._lock:
            permit = self._continuous_permits.pop(request.transaction_id, None)
        if permit is None:
            return None
        stage_id, binding_values = permit
        if not isinstance(stage_id, str) or not isinstance(binding_values, Mapping):
            return None
        with self._lock:
            stage = self._continuous_stages.pop(stage_id, None)
        if stage is None:
            self._run_continuous_audio_callback(self._continuous_audio_discard, stage_id)
            return None
        outcome = 'binding_changed'
        try:
            binding = ContinuousStageBinding(**binding_values)
            config = prepared.provider.config.values
            persona = {key: config.get(key) for key in (
                'active_quick_persona_name', 'system_prompt', 'persona_prompt_type',
                'emotional_instructions', 'chat_character_conversation_id')}
            persona_id = hashlib.sha256(json.dumps(persona, sort_keys=True).encode()).hexdigest()
            if (binding.session_generation != request.lease.session_generation.value
                    or binding.persona_id != persona_id
                    or binding.provider_id != prepared.provider.provider_id
                    or binding.model_id != prepared.provider.model_id
                    or binding.voice_fingerprint != voice_settings_fingerprint(config)
                    or stage.character_voice_fingerprint != character_voice_fingerprint(
                        self._character_voice_turns.get(request.request_id)
                        if self._character_voice_turns is not None else None)):
                return None
            accepted_request = {'binding': binding, 'provider_request': prepared.request}
            outcome = 'request_changed_or_expired'
            if not self.consume_continuous_next(stage, accepted_request):
                return None
            with self._lock:
                self._continuous_active_audio[request.transaction_id] = stage
            self._run_continuous_audio_callback(self._continuous_audio_activate, stage_id)
            outcome = 'reused'
            return stage
        except (TypeError, ValueError, KeyError):
            return None
        finally:
            logging.getLogger(__name__).info(
                'Continuous stage handoff stage=%s transaction=%s outcome=%s age_seconds=%.3f',
                stage_id, request.transaction_id, outcome, time.monotonic() - stage.created_at)
            self._communication('continuous.stage_handoff', dict(stage_id=stage_id, outcome=outcome),
                request.lease, turn_id=request.transaction_id)
            with self._lock:
                promoted = self._continuous_active_audio.get(request.transaction_id) is stage
            if not promoted:
                self._run_continuous_audio_callback(self._continuous_audio_discard, stage_id)

    @staticmethod
    def _run_continuous_audio_callback(callback, value) -> None:
        if callback is not None:
            try:
                callback(value)
            except Exception:
                pass  # Private lookahead must not affect a normal reply.

    def discard_continuous_stage(self, transaction_id: str) -> None:
        with self._lock:
            permit = self._continuous_permits.pop(str(transaction_id or ''), None)
            stage = self._continuous_stages.pop(permit[0], None) if permit else None
            active_stage = self._continuous_active_audio.pop(str(transaction_id or ''), None)
        if stage is not None:
            stage.token.cancel('continuous_turn_discarded')
        if active_stage is not None:
            active_stage.token.cancel('continuous_turn_retired')
        for stage_id in {permit[0] if permit else None,
                         active_stage.stage_id if active_stage else None} - {None}:
            self._run_continuous_audio_callback(self._continuous_audio_discard, stage_id)

    def _communication(self, stage, payload, lease, **correlation):
        record_to(getattr(self._runtime._providers,'communication_trace',None),stage,payload,
            lease_correlation(lease,**correlation))

    def begin(
        self,
        turn: Mapping[str, object],
        *,
        is_placeholder: bool = False,
        persist_user_turn: bool = True,
        restored_relay_snapshot: object = None,
        identity_relay_mode: str = "current",
        coordinated_regenerate: bool = False,
        source_lease: WorkLease | None = None,
        accepted_turn_snapshot: TurnSnapshot | None = None,
        expected_history_revision: int | None = None,
    ) -> dict[str, object]:
        item = dict(turn or {})
        stage_id = item.pop('continuous_stage_id', None)
        stage_binding = item.pop('continuous_stage_binding', None)
        transaction_id = str(item.get("normal_chat_transaction_id") or "")
        with self._lock:
            if transaction_id in self._transactions:
                return item
            staged = self._continuous_stages.get(stage_id) if isinstance(stage_id, str) else None
            if (staged is not None and not staged.token.cancelled
                    and staged.user_created_at is not None
                    and staged.user_content == str(item.get('content') or '').strip()
                    and isinstance(stage_binding, Mapping)
                    and dict(stage_binding) == asdict(staged.binding)):
                # Timestamped prompts must describe the same proposed user turn
                # during staging and admission; do not drop timestamps from the
                # request fingerprint or accept an unrelated staged message.
                item['created_at'] = staged.user_created_at
        if "created_at" not in item:
            item["created_at"] = time.time()
        if is_placeholder:
            persist_user_turn = False
        metadata = {
            str(key): value
            for key, value in item.items()
            if key not in {"role", "content", "normal_chat_transaction_id"}
        }
        watch_capture = retain_watch_capture(metadata.get('hidden_proactive_request'))
        if watch_capture is not None:
            metadata['orb_watch_capture'] = watch_capture
        watch_captures = retain_watch_captures(metadata.get('hidden_proactive_request'))
        if watch_captures:
            metadata['orb_watch_captures'] = watch_captures
        memory_work_context = self._capture_memory_work_context()
        acceptance = NormalChatAcceptance(
            str(item.get("content") or ""),
            role=str(item.get("role") or "user"),
            metadata=metadata,
            source=str(item.get("origin") or "legacy"),
            persist_user_turn=bool(persist_user_turn),
            source_lease=source_lease,
            expected_history_revision=expected_history_revision,
            memory_work_context=memory_work_context,
            restored_relay_snapshot=(
                restored_relay_snapshot
                if isinstance(restored_relay_snapshot, Mapping)
                else None
            ),
            identity_relay_mode=str(identity_relay_mode or "current"),
        )
        if coordinated_regenerate and transaction_id:
            result = self._runtime.transactions.regenerate(
                transaction_id,
                memory_work_context=memory_work_context,
            )
        else:
            result = self._runtime.transactions.begin(
                acceptance,
                accepted_turn=accepted_turn_snapshot,
            )
        snapshot = self._require(result, "Normal Chat turn acceptance failed.")
        self._communication('input.accepted',dict(text=acceptance.text if hasattr(acceptance,'text') else item.get('content',''),
            role=item.get('role','user'),persist_user_turn=persist_user_turn,
            synthetic=not persist_user_turn or (isinstance(item.get('content'),str) and item['content'] in {'__CONTINUE_ASSISTANT__','You continue speaking.'}),
            metadata=metadata),snapshot.lease,turn_id=snapshot.transaction_id)
        item["normal_chat_transaction_id"] = snapshot.transaction_id
        with self._lock:
            self._transactions[snapshot.transaction_id] = snapshot
            if isinstance(stage_id, str) and isinstance(stage_binding, Mapping):
                self._continuous_permits[snapshot.transaction_id] = (stage_id, dict(stage_binding))
        return item

    def accepted_input_lease(self, turn: Mapping[str, object]) -> WorkLease | None:
        """Exact lease for an accepted input that has not been published yet."""
        with self._lock:
            transaction = self._transactions.get(str(turn.get("normal_chat_transaction_id") or ""))
        return transaction.lease if transaction is not None else None

    def freeze_request(
        self,
        accepted_input_turn: Mapping[str, object] | None = None,
        *,
        request_only_continue_cue: bool = False,
        require_existing_transaction: bool = False,
        regenerate_route: bool = False,
        reply_delivery: ReplyDelivery | None = None,
        expected_target=None,
    ) -> dict[str, object]:
        item = dict(accepted_input_turn or {})
        transaction_id = str(item.get("normal_chat_transaction_id") or "")
        history = self._runtime._history(None)
        with self._lock:
            transaction = self._transactions.get(transaction_id)
        if regenerate_route:
            if not transaction_id:
                self._raise("Regeneration has no accepted Normal Chat transaction.")
            history_anchor_index = next(
                (
                    index
                    for index in range(len(history) - 1, -1, -1)
                    if str(
                        history[index].get("normal_chat_transaction_id") or ""
                    )
                    == transaction_id
                ),
                None,
            )
            regenerated = self._runtime.transactions.regenerate(
                transaction_id,
                memory_work_context=self._capture_memory_work_context(),
                history_anchor_index=history_anchor_index,
                expected_target=expected_target,
            )
            transaction = self._require(
                regenerated,
                "Normal Chat regeneration could not freeze a replacement turn.",
            )
            # Regeneration removes the target assistant turn atomically while
            # accepting its exact source.  Freeze the request from that updated
            # history, not from the pre-acceptance snapshot that still contains
            # the reply being replaced.
            history = self._runtime._history(None)
            transaction_id = transaction.transaction_id
            with self._lock:
                self._transactions[transaction_id] = transaction
        elif transaction is None:
            if require_existing_transaction:
                self._raise("Regeneration has no accepted Normal Chat transaction.")
            if not item:
                item = {
                    "role": "user",
                    "content": "Continue the current conversation.",
                    "origin": "input",
                }
            item = self.begin(item, persist_user_turn=bool(accepted_input_turn))
            transaction_id = str(item["normal_chat_transaction_id"])
            with self._lock:
                transaction = self._transactions[transaction_id]
        frozen = self._runtime.transactions.freeze_request(
            transaction,
            history,
            request_only_continue_cue=bool(request_only_continue_cue),
        )
        request = self._require(frozen, "Normal Chat request freeze failed.")
        context = self._request_context(transaction, request)
        if regenerate_route or reply_delivery is not None:
            context = apply_reply_delivery(context, reply_delivery or ReplyDelivery())
        current = self._runtime.transactions.snapshot(request) or transaction
        with self._lock:
            self._requests[request.request_id] = request
            self._transactions[transaction_id] = current
        return context

    def prepare_conversation_action(self, target, delivery):
        """Resume a canonical input without copying client text or adding a cue.

        The mutation boundary repeats the exact-target check; an input accepted
        between this snapshot and regeneration therefore wins without being lost.
        """
        conversation = self._runtime._conversation
        snapshot = conversation.snapshot()
        if (snapshot.revision != target.revision
                or snapshot.session_generation.value != target.session_generation
                or not snapshot.messages or snapshot.messages[-1].message_id != target.message_id):
            self._raise('The conversation action target changed.')
        index = len(snapshot.messages) - 1
        if snapshot.messages[index].role.lower() == 'assistant':
            index -= 1
        if index < 0 or snapshot.messages[index].role.lower() != 'user':
            self._raise('No user input is available for this action.')
        message = snapshot.messages[index]
        source = dict(message.metadata, role=message.role, content=message.content)
        transaction_id = str(source.get('normal_chat_transaction_id') or '')
        if transaction_id and (self._runtime.transactions.snapshot(transaction_id) is not None
                or self._runtime.transactions.regeneration_source(transaction_id) is not None):
            request = self.freeze_request(source, regenerate_route=True,
                reply_delivery=delivery, expected_target=target)
        else:
            # Imported history has a canonical message but no retained runtime
            # transaction. Adopt a fresh attempt of that SAME turn, not a new input.
            source.pop('normal_chat_transaction_id', None)
            turn = self._require(self._runtime.transactions._turns.regenerate(
                source_turn_id=TurnId(message.message_id), expected_target=target),
                'The restored input is no longer available.')
            source = self.begin(source, accepted_turn_snapshot=turn)
            request = self.freeze_request(source, reply_delivery=delivery)
        source['normal_chat_transaction_id'] = request['normal_chat_transaction_id']
        return source, request

    def ensure_ready(self, request: Mapping[str, object]) -> object:
        snapshot = self._request_snapshot(request)
        with correlation_scope(lease_correlation(snapshot.lease,turn_id=snapshot.transaction_id,
                normal_request_id=snapshot.request_id,kind='normal_chat_prepare')):
            ready = self._runtime.transactions.ensure_ready(snapshot)
        prepared = self._require(ready, "Normal Chat request preparation failed.")
        transaction = self._runtime.transactions.snapshot(snapshot)
        with self._lock:
            self._prepared[snapshot.request_id] = prepared
            if transaction is not None:
                self._transactions[snapshot.transaction_id] = transaction
        self._refresh_context(request, snapshot, prepared)
        trace_id = str(request.get("companion_orb_debug_trace_id") or "")
        companion_orb_vision_debug.record_event(
            trace_id,
            "main_chat_provider_request",
            request_id=snapshot.request_id,
            transaction_id=snapshot.transaction_id,
            provider=prepared.provider,
            request=companion_orb_vision_debug.serialize_provider_request(
                prepared.request
            ),
        )
        residency_snapshot = getattr(
            self._runtime._providers,
            "model_residency_snapshot",
            None,
        )
        if trace_id and callable(residency_snapshot):
            companion_orb_vision_debug.record_event(
                trace_id,
                "main_chat_model_residency_before_request",
                snapshot=residency_snapshot(prepared.provider),
            )
        return self.transaction_for_request(request)

    def reply_source_metadata(
        self,
        request: Mapping[str, object],
        *,
        hidden_proactive: bool = False,
    ) -> dict[str, object]:
        raw_capture_id = str(request.get("remote_capture_id") or "")
        capture_id = "".join(
            character
            for character in raw_capture_id
            if character.isalnum() or character in {"_", "-"}
        )[:96]
        with self._lock:
            permit = self._continuous_permits.get(str(request.get('normal_chat_transaction_id') or ''))
        return {
            "remote_capture_id": capture_id,
            "normal_chat_request_id": self._request_snapshot(request).request_id,
            "normal_chat_transaction_id": str(request.get("normal_chat_transaction_id") or ""),
            "phone_reply_control": request.get("phone_reply_control") is True,
            **({"continuous_stage_id": permit[0]} if permit else {}),
            "hidden_proactive": bool(hidden_proactive),
            "companion_orb_response": bool(
                str(request.get("companion_orb_response_guidance") or "").strip()
            ),
            "companion_orb_debug_trace_id": str(
                request.get("companion_orb_debug_trace_id") or ""
            ),
        }

    def cancel_request(self, request: object) -> bool:
        try:
            snapshot = self._request_snapshot(request)
        except BaseException:
            return False
        result = self._runtime.transactions.cancel(snapshot, reason="cancelled")
        self._retire(snapshot)
        return bool(result.accepted)

    def complete(
        self,
        request: Mapping[str, object] | None = None,
        *,
        turn_id: str = "",
        discard_binding: bool = False,
    ) -> None:
        snapshot = None
        if request is not None:
            try:
                snapshot = self._request_snapshot(request)
            except BaseException:
                return
        elif turn_id:
            with self._lock:
                transaction = self._transactions.get(str(turn_id))
                snapshot = transaction.request if transaction is not None else None
        if snapshot is None:
            return
        if discard_binding:
            self._runtime.transactions.cancel(snapshot, reason="discarded")
            self._retire(snapshot)
            return
        finished = self._runtime.transactions.finish(
            snapshot,
            TurnTerminalStatus.COMPLETED,
        )
        if finished.accepted:
            self._retire(snapshot)

    def commit(
        self,
        text: str,
        *,
        metadata: Mapping[str, object],
        expected_session_generation: int | None,
        expected_turn_id: str | None,
    ) -> dict[str, object] | None:
        """Commit assistant history through one exact accepted transaction."""

        transaction_id = str(expected_turn_id or "").strip()
        if not transaction_id:
            return None
        with self._lock:
            transaction = self._transactions.get(transaction_id)
        request = transaction.request if transaction is not None else None
        if request is None:
            return None
        if (
            expected_session_generation is not None
            and request.lease.session_generation.value
            != int(expected_session_generation)
        ):
            return None
        reply_metadata = dict(metadata or {})
        tool_result = self._tool_results.get(request.request_id)
        if tool_result is not None:
            reply_metadata['orb_action_receipts'] = list(tool_result['receipts'])
        watch_payload = self._watch_reply_payload(request)
        batch_watch = bool(watch_payload and watch_payload.get('orb_watch', {}).get('schema_version') == 2)
        if batch_watch and not self._watch_reply_current(watch_payload):
            return None
        capture = transaction.accepted.metadata.get('orb_watch_capture')
        if isinstance(capture, Mapping):
            reply_metadata['orb_watch_capture'] = _plain_mapping(capture)
        captures = transaction.accepted.metadata.get('orb_watch_captures')
        if isinstance(captures, (tuple,list)):
            reply_metadata['orb_watch_captures'] = [_plain_mapping(c) for c in captures]
        def publish():
            return self._runtime.transactions.publish_assistant(request,str(text or ""),metadata=reply_metadata)
        if batch_watch and self._hidden_reply_publication is not None:
            with correlation_scope(lease_correlation(request.lease,turn_id=transaction_id,normal_request_id=request.request_id)):
                committed=self._hidden_reply_publication(watch_payload,publish)
        else:
            committed=self._publish_conversation_result(request, publish)
        if committed is None or not committed.accepted or committed.value is None:
            return None
        if batch_watch and self._hidden_reply_publication is None:
            self._watch_reply_delivered(watch_payload)
        message = committed.value.message
        self._communication('assistant.visible',dict(text=message.content,metadata=reply_metadata),request.lease,
            turn_id=transaction_id,normal_request_id=request.request_id)
        result = {
            "role": message.role,
            "content": message.content,
        }
        result.update(_plain_mapping(message.metadata) or {})
        return result

    def transaction_for_request(self, request: object) -> dict[str, object] | None:
        try:
            request_snapshot = self._request_snapshot(request)
        except BaseException:
            return None
        transaction = self._runtime.transactions.snapshot(request_snapshot)
        if transaction is None:
            return None
        prepared = transaction.prepared
        persona_values = dict(transaction.accepted.persona.values)
        assistant_persona = {
            "name": str(
                persona_values.get("active_quick_persona_name", "") or ""
            ).strip(),
            "avatar_path": str(
                persona_values.get("persona_visual_reference_path", "") or ""
            ).strip(),
        }
        assistant_persona = {
            key: value for key, value in assistant_persona.items() if value
        }
        if persona_values.get("persona_mood_tags"):
            assistant_persona["mood_tags"] = dict(persona_values["persona_mood_tags"])
        return {
            "turn_id": transaction.transaction_id,
            "normal_chat_transaction_id": transaction.transaction_id,
            "turn_snapshot": transaction.accepted.turn,
            "session_lease": transaction.lease,
            "session_generation": transaction.lease.session_generation.value,
            "cancel_event": self._runtime.transactions.cancellation_token(transaction),
            "status": transaction.status.value,
            "prepared_provider_request": (
                prepared.request if prepared is not None else None
            ),
            "identity_relay_metadata": _plain_mapping(transaction.relay_metadata),
            "identity_relay_snapshot": _plain_mapping(transaction.relay_snapshot),
            "assistant_persona": assistant_persona,
        }

    def _watch_reply_payload(self, request):
        transaction = self._runtime.transactions.snapshot(request)
        payload = transaction.accepted.metadata.get('hidden_proactive_request') if transaction else None
        return payload if isinstance(payload, Mapping) and 'orb_watch' in payload else None

    def _watch_reply_current(self, payload):
        return payload is None or self._hidden_request_guard is None or bool(self._hidden_request_guard(payload))

    def _watch_reply_delivered(self, payload):
        if payload is not None and self._hidden_reply_delivered is not None:
            self._hidden_reply_delivered(payload)

    def _publish_conversation_result(self, request, publish):
        result = self._tool_results.get(request.request_id)
        if result is None or not result.get('ticket'):
            return publish()
        return self._conversation_tools('publish', {'ticket': result['ticket'], 'publish': publish})

    def _remind_mcp_model_unsupported(self, request, context):
        key = (request.lease.run_id.value, request.lease.session_generation.value,
               context.provider_name, context.model_name)
        with self._lock:
            if key in self._mcp_model_reminders:
                return
            self._mcp_model_reminders.add(key)
        message = ('The selected model does not support tool calling. MCP tools are disabled for this model. '
                   'Choose a tool-capable model to use them; your saved tool permissions are unchanged.')
        print('[MCP] ' + message)
        if self._mcp_model_notice is not None:
            try:
                self._mcp_model_notice(request, message)
            except Exception:
                # A notification must never prevent an ordinary text reply.
                pass

    def _run_conversation_tools(self, request, prepared, token, *, on_started=None, on_text=None):
        transaction = self._runtime.transactions.snapshot(request)
        if self._conversation_tools is None or transaction is None:
            return None
        accepted = transaction.accepted
        regular_user_reply = bool(accepted.persist_user_turn and not request.request_only_continue_cue
            and accepted.content.strip() not in {'PING', 'PONG', '__CONTINUE_ASSISTANT__', 'You continue speaking.'})
        # An explicit regeneration has a fresh canonical turn attempt. It may
        # replace a continuation without a persisted user message of its own.
        route_generation = accepted.lease.route_generation
        mcp_regeneration = bool(self._mcp_conversation_tools is not None
            and route_generation is not None and route_generation.value > 0)
        if ((not accepted.config.values.get('companion_orb_enabled') and self._mcp_conversation_tools is None)
                or accepted.metadata.get('hidden_proactive_request') or accepted.metadata.get('hidden_proactive')
                or accepted.role != 'user' or not (regular_user_reply or mcp_regeneration)):
            return None
        if not isinstance(prepared.request, FrozenTurnRequest):
            return None
        protocol = prepared.request.context.native_tool_protocol
        if not protocol:
            return None
        cancellation = _CombinedCancellation(token)
        offered = self._conversation_tools('offer', dict(
            model_supports_tools=prepared.request.context.native_tool_support,
            orb_enabled=bool(accepted.config.values.get('companion_orb_enabled') and regular_user_reply),
            persona_id=str(accepted.persona.values.get('active_quick_persona_id') or ''),
            history=[dict(_plain_mapping(accepted.message_mapping()), message_id=accepted.transaction_id)],
            session_key=f'{request.lease.run_id.value}/{request.lease.session_generation.value}',
            turn_key=accepted.transaction_id, is_current=lambda: not cancellation.cancelled))
        if offered and offered.get('mcp_model_unsupported') and not cancellation.cancelled:
            self._remind_mcp_model_unsupported(request, prepared.request.context)
        if not offered or not offered.get('available'):
            return None
        if on_started is not None:
            on_started()
        ticket = offered['ticket']
        self._tool_results[request.request_id] = dict(ticket=ticket,receipts=[])
        streamed_text=[]
        def current():
            return not cancellation.cancelled and bool((self._conversation_tools('current', {'ticket': ticket}) or {}).get('current'))
        def execute(call):
            value = self._conversation_tools('execute', {'ticket': ticket, 'call': asdict(call)})
            return ToolOutcome(**value)
        def complete_round(params, additional, *, allow_stream=True):
            followup = FrozenTurnRequest(prepared.request.context, params, additional)
            with correlation_scope(lease_correlation(request.lease, turn_id=request.transaction_id,
                    normal_request_id=request.request_id, kind='orb_conversation_tool_round')):
                if allow_stream and on_text is not None and prepared.request.context.native_tool_streaming:
                    from core.native_tool_stream import decode_event, AnswerPrefixFilter
                    from core.conversation_tools import ToolRound
                    terminal=None
                    round_text=[]
                    prefix_filter=AnswerPrefixFilter()
                    def deliver_text(value):
                        value=prefix_filter.feed(value)
                        if not value: return
                        if not round_text and streamed_text:
                            streamed_text.append('\n\n');on_text('\n\n')
                        round_text.append(value)
                        streamed_text.append(value)
                        on_text(value)
                    source=self._runtime._providers.stream(followup,token)
                    try:
                        for raw in source:
                            if not current(): return ToolRound('',(),())
                            kind,value=decode_event(raw)
                            if terminal is not None: raise ValueError('Data after native stream completion.')
                            if kind=='round': terminal=value
                            elif value:
                                deliver_text(value)
                    finally:
                        close=getattr(source,'close',None)
                        if callable(close): close()
                    if terminal is None: raise ValueError('Native stream ended without a completed round.')
                    if terminal.text and not round_text: deliver_text(terminal.text)
                    return terminal
                response = self._runtime._providers.complete(followup, token)
            if not response.accepted:
                from core.provider_limits import limit_message
                limit=limit_message(response.failure.cause) if response.failure is not None and response.failure.cause else ''
                if limit: self._raise(limit)
                self._raise(response.failure.message if response.failure else 'Conversational provider round failed.')
            return decode_tool_round(response.value)
        def request_round(items, final_only=False, select_question=False, answer_question=''):
            params = prepared.request.params_copy()
            additional = prepared.request.additional_params_copy()
            from core.native_tool_calls import prompt_payload, add_instruction
            payload, messages, wire_protocol = prompt_payload(params, protocol)
            from core.runtime.conversation_tools import apply_orb_conversation_profile
            if offered.get('orb', True):
                apply_orb_conversation_profile(payload)
            if select_question or answer_question:
                # Failure-only recovery: never replay an action request to the
                # answering model, and never dispatch a recovery function as an action.
                if not current():
                    self._raise('The tool conversation changed before recovery.')
                tools = []
                if select_question:
                    instruction = ('Select a self-contained general-knowledge question from this message, verbatim. '
                        'Exclude action requests, their results, and questions needing desktop evidence. '
                        'Call remaining_question with that question, or an empty string if none.')
                    text = accepted.content
                    tools = [dict(type='function', name='remaining_question',
                        description='Select the independent informational question; performs no action.',
                        parameters=dict(type='object', properties={'question': {'type':'string'}},
                            required=['question'], additionalProperties=False))]
                else:
                    instruction = 'Answer this informational question concisely.'
                    text = answer_question
                add_instruction(payload, messages, instruction, wire_protocol, replace=True, user_text=text)
                additional[TOOL_OPTION] = dict(tools=tools, input=[], final_only=not select_question)
                return complete_round(params, additional, allow_stream=not select_question)
            context = offered['context']
            if final_only:
                context += '\nAn operation failed. Its receipt is authoritative. Answer any remaining question without claiming unconfirmed actions or inventing unavailable evidence; no further actions.'
            from core.runtime.conversation_tools import strip_display_receipts
            strip_display_receipts(messages, self._runtime._history(None))
            application_state=self._conversation_tools('current', {'ticket':ticket}) or {}
            if not application_state.get('current'):
                self._raise('The tool conversation changed before the model round.')
            if offered.get('orb', True):
                watches = application_state.get('watches', [])
                state_text = 'Current application watch state (data, not a request): ' + json.dumps({
                    'active_watches':[w for w in watches if w.get('status') in {'watching','matched_pending'}],
                    'finished_watches':[w for w in watches if w.get('status') not in {'watching','matched_pending'}]}, ensure_ascii=False)
                for message in reversed(messages):
                    if message.get('role') == 'user':
                        content = message.get('content')
                        if isinstance(content, str):
                            message['content'] = content + '\n\n' + state_text
                        elif isinstance(content, list):
                            content.append({'type':'input_text','text':state_text})
                        break
            add_instruction(payload, messages, context, wire_protocol)
            additional[TOOL_OPTION] = {'tools': offered['tools'], 'input': items,
                                      'final_only': final_only or not offered['tools']}
            return complete_round(params, additional)
        with correlation_scope(lease_correlation(request.lease, turn_id=request.transaction_id,
                normal_request_id=request.request_id)):
            result = run_tool_conversation(request_round=request_round, execute=execute, current=current,
                original_request=accepted.content, max_rounds=12 if offered.get('mcp') else 5)
        if streamed_text and not result['cancelled']:
            # Preserve every part of the user's answer, including an ordinary
            # question answered before a later tool request in the same turn.
            from core.runtime.assistant_directives import extract_companion_orb_focus
            result['text']=extract_companion_orb_focus(''.join(streamed_text).strip())[0]
        self._tool_results[request.request_id] = dict(result, ticket=ticket)
        self._communication('orb.conversation.result', result, request.lease,
            turn_id=request.transaction_id, normal_request_id=request.request_id)
        if result['cancelled']:
            return ''
        if on_text is not None and prepared.request.context.native_tool_streaming:
            if not streamed_text and result['text']: on_text(result['text'])
            if result['receipts']: on_text('\n\n'+'\n\n'.join(result['receipts']))
        return '\n\n'.join([*result['receipts'], result['text']]).strip()

    def reply(self, request: Mapping[str, object]) -> str | None:
        trace_id = str(request.get("companion_orb_debug_trace_id") or "")
        request_snapshot, prepared = self._prepared_request(request)
        watch_payload = self._watch_reply_payload(request_snapshot)
        if not self._watch_reply_current(watch_payload):
            return None
        claim = self._runtime.transactions.claim_dispatch(
            request_snapshot,
            prepared.request,
            kind="completion",
        )
        self._require(claim, "Normal Chat provider dispatch was rejected.")
        selected = getattr(claim.value, "selected_request", None) or prepared.request
        admitted_prepared = replace(prepared, request=selected)
        token = self._runtime.transactions.cancellation_token(request_snapshot)
        tool_reply = self._run_conversation_tools(request_snapshot, admitted_prepared, token)
        if tool_reply is not None:
            context = self._character_voice_turns.get(request_snapshot.request_id) if self._character_voice_turns else None
            if context is not None:
                from core.runtime.structured_character_voice import CharacterVoiceStream
                parsed = CharacterVoiceStream(context)
                parsed.feed(tool_reply); parsed.finish()
                self._character_voice_turns.complete(request_snapshot.request_id, parsed)
                self._communication('character_voice.validation', parsed.routing_diagnostics(),
                    request_snapshot.lease, turn_id=request_snapshot.transaction_id,
                    normal_request_id=request_snapshot.request_id)
                if not parsed.text:
                    self._raise('Character voice reply contained no readable segments. Retry or turn off Character voices.')
                return parsed.text
            return tool_reply
        staged = self._take_continuous_stage(request_snapshot, admitted_prepared)
        for attempt in (1, 2):
            if attempt > 1:
                retry_claim = self._runtime.transactions.claim_dispatch(request_snapshot, prepared.request, kind="completion_retry")
                self._require(retry_claim, "Normal Chat retry dispatch was rejected.")
                selected = getattr(retry_claim.value, "selected_request", None) or prepared.request
            with correlation_scope(lease_correlation(request_snapshot.lease,turn_id=request_snapshot.transaction_id,
                    normal_request_id=request_snapshot.request_id,kind='normal_chat',attempt=attempt)):
                result = (CommandResult(True, staged.raw_response)
                          if staged is not None and attempt == 1
                          else self._runtime._providers.complete(selected, token))
            if not result.accepted:
                companion_orb_vision_debug.record_event(
                    trace_id,
                    "main_chat_provider_error",
                    attempt=attempt,
                    failure=result.failure,
                )
                self._raise(
                    result.failure.message
                    if result.failure is not None
                    else "Normal Chat provider completion failed."
                )
            response_text = str(result.value or "")
            voice_context = self._character_voice_turns.get(request_snapshot.request_id) if self._character_voice_turns else None
            if voice_context is not None:
                from core.runtime.structured_character_voice import CharacterVoiceStream
                parsed = CharacterVoiceStream(voice_context)
                parsed.feed(response_text); parsed.finish()
                if token is not None and token.cancelled:
                    return None
                self._character_voice_turns.complete(request_snapshot.request_id, parsed)
                self._communication('character_voice.validation', parsed.routing_diagnostics(),
                    request_snapshot.lease, turn_id=request_snapshot.transaction_id,
                    normal_request_id=request_snapshot.request_id)
                if not parsed.text:
                    self._raise('Character voice reply contained no readable segments. Retry or turn off Character voices.')
                return parsed.text

            degenerate = companion_orb_vision_debug.looks_degenerate(
                response_text
            )
            companion_orb_vision_debug.record_event(
                trace_id,
                "main_chat_provider_response",
                attempt=attempt,
                response_text=response_text,
                character_count=len(response_text),
                degenerate=degenerate,
                streamed=False,
            )
            if trace_id:
                companion_orb_vision_debug.record_event(
                    trace_id,
                    "main_chat_model_residency_after_response",
                    attempt=attempt,
                    snapshot=self._runtime._providers.model_residency_snapshot(
                        prepared.provider
                    ),
                )
            if not trace_id or not degenerate:
                if not self._watch_reply_current(watch_payload):
                    return None
                if response_text and not (watch_payload and watch_payload.get('orb_watch', {}).get('schema_version') == 2):
                    self._watch_reply_delivered(watch_payload)
                return response_text
            companion_orb_vision_debug.record_event(
                trace_id,
                "main_chat_degenerate_rejected",
                attempt=attempt,
                character_count=len(response_text),
            )
            if attempt == 2:
                self._raise(
                    "Main Chat returned unusable repeated output twice; "
                    "the response was blocked before history and speech."
                )
            provider_id = str(prepared.provider.provider_id or "").strip().lower()
            if provider_id == "lmstudio":
                reload_exact = getattr(
                    self._runtime._providers,
                    "reload_selection_model_exact",
                    None,
                )
                reloaded = bool(
                    callable(reload_exact)
                    and reload_exact(
                        prepared.provider,
                        reason="recover Main Chat after degenerate Orb response",
                    )
                )
                residency_snapshot = getattr(
                    self._runtime._providers,
                    "model_residency_snapshot",
                    None,
                )
                companion_orb_vision_debug.record_event(
                    trace_id,
                    "main_chat_model_reload",
                    success=reloaded,
                    snapshot=(
                        residency_snapshot(prepared.provider)
                        if callable(residency_snapshot)
                        else {}
                    ),
                )
                if not reloaded:
                    self._raise(
                        "Main Chat returned unusable repeated output and its "
                        "exact LM Studio model instance could not be reloaded."
                    )
        return ""

    def start_stream(
        self,
        text_queue: object,
        *,
        dry_run_reply_id: str | None,
        request_context: Mapping[str, object],
        preserve_voice_labels: bool,
        show_preview: bool = True,
    ) -> NormalChatApplicationStream:
        del dry_run_reply_id, preserve_voice_labels
        if not hasattr(text_queue, "put"):
            raise TypeError("Normal Chat streaming requires a queue-like output.")
        request, prepared = self._prepared_request(request_context)
        watch_payload = self._watch_reply_payload(request)
        if not self._watch_reply_current(watch_payload):
            state = NormalChatApplicationStream()
            text_queue.put(None)
            state.done.set()
            return state
        trace_id = str(
            request_context.get("companion_orb_debug_trace_id") or ""
        )
        claim = self._runtime.transactions.claim_dispatch(
            request,
            prepared.request,
            kind="stream",
        )
        self._require(claim, "Normal Chat stream dispatch was rejected.")
        selected = getattr(claim.value, "selected_request", None) or prepared.request
        admitted_prepared = replace(prepared, request=selected)
        state = NormalChatApplicationStream()
        preview: _StreamPreview | None = None
        if show_preview and watch_payload is None:
            preview = _StreamPreview(
                request_id=request.request_id,
                transaction_id=request.transaction_id,
                session_generation=request.lease.session_generation.value,
                state=state,
            )
        with self._lock:
            self._stream_preview = preview

        def publish_preview(text: str) -> None:
            if not text or preview is None:
                return
            with self._lock:
                if self._stream_preview is preview and not state.cancel_requested.is_set():
                    preview.parts.append(text)

        transaction_token = self._runtime.transactions.cancellation_token(request)
        transaction = self._runtime.transactions.snapshot(request)
        allow_stream_fallback = bool(
            transaction is not None
            and (
                transaction.accepted.persist_user_turn
                or request.request_only_continue_cue
            )
        )
        continuation_tail = ""
        if not allow_stream_fallback and request.history:
            tail = request.history[-1]
            if str(tail.get("role", "") or "").strip().lower() == "assistant":
                continuation_tail = _without_leading_control_tags(
                    tail.get("content", "")
                )
        config_values = prepared.provider.config.values
        stream_target_chars = int(
            config_values.get("stream_chunk_target_chars", 80) or 80
        )
        stream_max_chars = int(
            config_values.get("stream_chunk_max_chars", 185) or 185
        )

        def worker(supervisor_token: object) -> None:
            cancellation = _CombinedCancellation(
                transaction_token,
                supervisor_token,
                state.cancel_requested,
            )
            chunks: list[str] = []
            speech_chunks: list[str] = []
            preview_segment_count = 0

            def publish_segment_preview(text: str) -> None:
                nonlocal preview_segment_count
                publish_preview(("\n\n" if preview_segment_count else "") + text)
                preview_segment_count += 1

            admitted = False
            tool_attempted = False
            voice_context = self._character_voice_turns.get(request.request_id) if self._character_voice_turns else None
            structured = None
            deadline_publisher = None
            if voice_context is not None:
                from core.runtime.structured_character_voice import CharacterVoiceStream
                structured = CharacterVoiceStream(voice_context)

            def tools_started():
                nonlocal tool_attempted
                tool_attempted = True

            def publish_speech(text):
                nonlocal admitted
                if cancellation.cancelled:
                    return
                batch_watch = bool(watch_payload and watch_payload.get('orb_watch', {}).get('schema_version') == 2)
                if (batch_watch or not admitted) and not self._watch_reply_current(watch_payload):
                    raise _ObsoleteOrbWatchOutput()
                def enqueue():
                    text_queue.put(text)
                    return True
                if not self._publish_conversation_result(request, enqueue):
                    raise _ObsoleteOrbWatchOutput()
                self._communication('speech.submitted',dict(text=text,note='Queued for TTS, not proof of audible playback.'),
                    request.lease,turn_id=request.transaction_id,normal_request_id=request.request_id)
                if not admitted:
                    admitted = True
                    if not batch_watch:
                        self._watch_reply_delivered(watch_payload)
            try:
                try:
                    assembler = streaming_text.StreamingChunkAssembler(
                        stream_target_chars,
                        stream_max_chars,
                        config_getter=lambda key, default=None: config_values.get(
                            key,
                            default,
                        ),
                        control_prefix_checker=text_tags.looks_like_control_tag_prefix,
                        visual_tail_filter=self._visual_tail_filter,
                        visual_prefix_checker=self._visual_prefix_checker,
                    )
                    def publish_chunk_info(chunk_info):
                        speech_chunk = str(chunk_info.get("text", "") or "")
                        if speech_chunk:
                            speech_chunks.append(speech_chunk)
                            publish_speech(speech_chunk)

                    if structured is None:
                        deadline_publisher = StreamingDeadlinePublisher(
                            assembler, publish_chunk_info, cancellation=cancellation)
                    orb_directive_filter = (
                        assistant_directives.CompanionOrbDirectiveStreamFilter()
                        if bool(config_values.get("companion_orb_vision_enabled", False))
                        and bool(
                            config_values.get(
                                "companion_orb_spatial_conversational_focus_enabled",
                                True,
                            )
                        )
                        else None
                    )
                    pending_prefix = ""
                    prefix_resolved = not bool(continuation_tail)

                    def speech_delta(value: object, *, final: bool = False) -> str:
                        nonlocal pending_prefix, prefix_resolved
                        chunk_value = str(value or "")
                        if prefix_resolved:
                            return chunk_value
                        pending_prefix += chunk_value
                        visible = _without_leading_control_tags(pending_prefix)
                        visible_folded = visible.casefold()
                        tail_folded = continuation_tail.casefold()
                        if visible_folded.startswith(tail_folded):
                            prefix_resolved = True
                            pending_prefix = ""
                            return visible[len(continuation_tail) :].lstrip()
                        if tail_folded.startswith(visible_folded):
                            if final:
                                prefix_resolved = True
                                pending_prefix = ""
                            return ""
                        prefix_resolved = True
                        released = pending_prefix
                        pending_prefix = ""
                        return released

                    def accept_chunk(raw_chunk):
                        if cancellation.cancelled: return
                        chunk = str(raw_chunk or "")
                        if not chunk:
                            return
                        if structured is not None:
                            for part in structured.feed(chunk):
                                if cancellation.cancelled:
                                    break
                                publish_segment_preview(part.text)
                                speech_chunks.append(part.text)
                                publish_speech(part)
                            return
                        chunks.append(chunk)
                        filtered_chunk = speech_delta(chunk)
                        if orb_directive_filter is not None:
                            filtered_chunk = orb_directive_filter.feed(filtered_chunk)
                        publish_preview(filtered_chunk)
                        deadline_publisher.feed(filtered_chunk)
                    native_deltas=[]
                    def accept_tool_text(text):
                        native_deltas.append(text)
                        accept_chunk(text)
                    if not self._watch_reply_current(watch_payload):
                        raise _ObsoleteOrbWatchOutput()
                    with correlation_scope(lease_correlation(request.lease,turn_id=request.transaction_id,
                            normal_request_id=request.request_id,kind='normal_chat_stream')):
                        tool_reply = self._run_conversation_tools(request, admitted_prepared, cancellation,
                            on_started=tools_started,on_text=accept_tool_text)
                        staged = self._take_continuous_stage(request, admitted_prepared) if tool_reply is None else None
                        stream = (iter(()) if native_deltas else iter((tool_reply,))) if tool_reply is not None else (
                            iter((staged.raw_response,)) if staged is not None else self._runtime._providers.stream(selected,cancellation))
                    for raw_chunk in stream:
                        if cancellation.cancelled: break
                        accept_chunk(raw_chunk)
                    if native_deltas and tool_reply is not None:
                        chunks[:] = [tool_reply]
                    if structured is not None and not cancellation.cancelled:
                        for part in structured.finish():
                            publish_segment_preview(part.text)
                            speech_chunks.append(part.text)
                            publish_speech(part)
                        chunks[:] = [structured.text]
                        if not cancellation.cancelled:
                            self._character_voice_turns.complete(request.request_id, structured)
                    if not cancellation.cancelled and structured is None:
                        filtered_final = speech_delta("", final=True)
                        if orb_directive_filter is not None:
                            filtered_final = (
                                orb_directive_filter.feed(filtered_final)
                                + orb_directive_filter.finish()
                            )
                        if filtered_final:
                            publish_preview(filtered_final)
                            deadline_publisher.feed(filtered_final)
                        deadline_publisher.finish()
                except _ObsoleteOrbWatchOutput:
                    if deadline_publisher is not None:
                        deadline_publisher.close()
                    raise
                except BaseException:
                    if deadline_publisher is not None:
                        deadline_publisher.close()
                    if cancellation.cancelled:
                        raise
                    if not allow_stream_fallback or (structured is not None and admitted):
                        raise
                    if tool_attempted:
                        raise  # Never replay mutations or fabricate an acknowledgement via plain fallback.
                    fallback_claim = self._runtime.transactions.claim_dispatch(
                        request,
                        prepared.request,
                        kind="stream_fallback_completion",
                    )
                    self._require(
                        fallback_claim,
                        "Normal Chat stream fallback was rejected.",
                    )
                    with correlation_scope(lease_correlation(request.lease,turn_id=request.transaction_id,
                            normal_request_id=request.request_id,kind='normal_chat_stream_fallback')):
                        fallback_request = getattr(fallback_claim.value, "selected_request", None) or prepared.request
                        fallback = self._runtime._providers.complete(fallback_request,cancellation)
                    if not fallback.accepted:
                        self._raise(
                            fallback.failure.message
                            if fallback.failure is not None
                            else "Normal Chat stream fallback failed."
                        )
                    if preview is not None:
                        with self._lock:
                            if self._stream_preview is preview:
                                preview.parts.clear()
                    chunk = str(fallback.value or "")
                    if structured is not None:
                        structured = CharacterVoiceStream(voice_context)
                        preview_segment_count = 0
                        parts = structured.feed(chunk) + structured.finish()
                        for part in parts:
                            publish_segment_preview(part.text)
                            speech_chunks.append(part.text)
                            publish_speech(part)
                        chunks[:] = [structured.text]
                        if not cancellation.cancelled:
                            self._character_voice_turns.complete(request.request_id, structured)
                        chunk = ''
                    if chunk:
                        chunks.append(chunk)
                        publish_preview(chunk)
                        if bool(config_values.get("companion_orb_vision_enabled", False)) and bool(
                            config_values.get(
                                "companion_orb_spatial_conversational_focus_enabled",
                                True,
                            )
                        ):
                            chunk, _directive = (
                                assistant_directives.extract_companion_orb_focus(chunk)
                            )
                        if chunk:
                            speech_chunks.append(chunk)
                            publish_speech(chunk)
                state.full_text = "".join(chunks)
                if structured is not None and not cancellation.cancelled and not state.full_text:
                    self._raise('Character voice reply contained no readable segments. Retry or turn off Character voices.')
                companion_orb_vision_debug.record_event(
                    trace_id,
                    "main_chat_provider_response",
                    response_text=state.full_text,
                    character_count=len(state.full_text),
                    degenerate=companion_orb_vision_debug.looks_degenerate(
                        state.full_text
                    ),
                    streamed=True,
                    provider_chunk_count=len(chunks),
                    tts_queue_chunks=speech_chunks,
                )
            except _ObsoleteOrbWatchOutput:
                state.full_text = ''
            except BaseException as exc:
                if not cancellation.cancelled:
                    state.error = exc
                companion_orb_vision_debug.record_event(
                    trace_id,
                    "main_chat_provider_error",
                    error_type=type(exc).__name__,
                    error=str(exc),
                    cancelled=bool(cancellation.cancelled),
                    partial_response="".join(chunks),
                    tts_queue_chunks=speech_chunks,
                )
            finally:
                if deadline_publisher is not None:
                    deadline_publisher.close()
                if structured is not None:
                    self._communication('character_voice.validation',
                        structured.routing_diagnostics(),
                        request.lease,turn_id=request.transaction_id,normal_request_id=request.request_id)
                    structured.close()
                text_queue.put(None)
                state.done.set()

        try:
            self._runtime._workers.spawn(
                name="nc-normal-chat-stream",
                lease=request.lease,
                target=worker,
                on_cancel=lambda _reason: state.cancel_requested.set(),
                identity=(
                    "normal_chat_stream",
                    request.transaction_id,
                    request.request_id,
                ),
                owner_token=self,
            )
        except BaseException as exc:
            state.error = exc
            text_queue.put(None)
            state.done.set()
        return state

    def _prepared_request(
        self,
        context: Mapping[str, object],
    ) -> tuple[NormalChatRequestSnapshot, PreparedNormalChatRequest]:
        request = self._request_snapshot(context)
        with self._lock:
            prepared = self._prepared.get(request.request_id)
        if prepared is None:
            self.ensure_ready(context)
            with self._lock:
                prepared = self._prepared.get(request.request_id)
        if prepared is None:
            self._raise("Normal Chat request did not publish a prepared provider request.")
        return request, prepared

    def _request_snapshot(self, request: object) -> NormalChatRequestSnapshot:
        if not isinstance(request, Mapping):
            self._raise("Normal Chat request context is invalid.")
        request_id = str(request.get("request_id") or "")
        with self._lock:
            snapshot = self._requests.get(request_id)
        if snapshot is None:
            self._raise("Normal Chat request context is stale or unknown.")
        return snapshot

    def _capture_memory_work_context(self) -> object:
        if self._memory_work_context is None:
            return None
        return self._memory_work_context()

    def _request_context(
        self,
        transaction: NormalChatTransactionSnapshot,
        request: NormalChatRequestSnapshot,
    ) -> dict[str, object]:
        context = {
            "kind": "normal_chat",
            "request_id": request.request_id,
            "normal_chat_transaction_id": request.transaction_id,
            "session_generation": request.lease.session_generation.value,
        }
        context.update(dict(transaction.accepted.metadata))
        persona_values = dict(transaction.accepted.persona.values)
        assistant_persona = {
            "name": str(
                persona_values.get("active_quick_persona_name", "") or ""
            ).strip(),
            "avatar_path": str(
                persona_values.get("persona_visual_reference_path", "") or ""
            ).strip(),
        }
        context["assistant_persona"] = {
            key: value for key, value in assistant_persona.items() if value
        }
        if persona_values.get("persona_mood_tags"):
            context["assistant_persona"]["mood_tags"] = dict(persona_values["persona_mood_tags"])
        return context

    def _refresh_context(
        self,
        context: Mapping[str, object],
        request: NormalChatRequestSnapshot,
        prepared: PreparedNormalChatRequest,
    ) -> None:
        if not isinstance(context, dict):
            return
        transaction = self._runtime.transactions.snapshot(request)
        context["prepared_provider_request"] = prepared.request
        if transaction is not None:
            context["identity_relay_metadata"] = _plain_mapping(
                transaction.relay_metadata
            )
            context["identity_relay_snapshot"] = _plain_mapping(
                transaction.relay_snapshot
            )

    def _retire(self, request: NormalChatRequestSnapshot) -> None:
        if self._character_voice_turns is not None:
            self._character_voice_turns.retire(request.request_id)
        self.discard_continuous_stage(request.transaction_id)
        with self._lock:
            if self._stream_preview is not None and self._stream_preview.request_id == request.request_id:
                self._stream_preview = None
            self._requests.pop(request.request_id, None)
            self._prepared.pop(request.request_id, None)
            self._tool_results.pop(request.request_id, None)
            self._transactions.pop(request.transaction_id, None)

    def _require(self, result: CommandResult, fallback: str):
        if result.accepted and result.value is not None:
            return result.value
        self._raise(
            result.failure.message
            if result.failure is not None
            else fallback
        )

    def _raise(self, message: str):
        raise self._blocked_error(str(message or "Normal Chat operation failed."))


@dataclass(slots=True)
class _ExecutionState:
    prepared: PreparedNormalChatTurn
    done: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    result: NormalChatExecutionResult | None = None
    failure: RuntimeFailure | None = None
    trace: list[str] = field(default_factory=list)
    worker: WorkerHandle | None = None

    def append_trace(self, event: str) -> None:
        with self.lock:
            self.trace.append(str(event))

    def publish(
        self,
        *,
        result: NormalChatExecutionResult | None = None,
        failure: RuntimeFailure | None = None,
    ) -> bool:
        with self.lock:
            if self.done.is_set():
                return False
            self.result = result
            self.failure = failure
            self.done.set()
            return True

    def snapshot(self) -> NormalChatExecutionSnapshot:
        with self.lock:
            return NormalChatExecutionSnapshot(
                self.prepared,
                self.done.is_set(),
                self.result,
                self.failure,
                tuple(self.trace),
            )


@dataclass(frozen=True, slots=True)
class NormalChatExecutionHandle:
    transaction_id: str
    request_id: str
    lease: WorkLease
    _owner: "NormalChatRuntime" = field(repr=False, compare=False)
    _state: _ExecutionState = field(repr=False, compare=False)

    def wait(
        self,
        timeout: float | None = None,
    ) -> CommandResult[NormalChatExecutionResult]:
        if not self._state.done.wait(timeout):
            return _failure(
                "normal_chat_execution_timeout",
                "Normal Chat execution did not finish before the deadline.",
            )
        snapshot = self._state.snapshot()
        if snapshot.result is not None:
            return CommandResult(True, snapshot.result)
        return CommandResult(
            False,
            failure=snapshot.failure
            or RuntimeFailure(
                "normal_chat_execution_failed",
                "Normal Chat execution failed without a result.",
            ),
        )

    def cancel(self, reason: str = "cancelled") -> CommandResult[None]:
        return self._owner.cancel(self, reason=reason)

    def snapshot(self) -> NormalChatExecutionSnapshot:
        return self._state.snapshot()


class _CombinedCancellation:
    def __init__(self, *tokens: object) -> None:
        self._tokens = tuple(token for token in tokens if token is not None)

    @property
    def cancelled(self) -> bool:
        return any(
            bool(getattr(token, "cancelled", False))
            or (isinstance(token, threading.Event) and token.is_set())
            for token in self._tokens
        )

    @property
    def reason(self) -> str:
        for token in self._tokens:
            reason = str(getattr(token, "reason", "") or "")
            if bool(getattr(token, "cancelled", False)) and reason:
                return reason
        return "cancelled"

    def subscribe(self, callback):
        unsubscribers = []
        for token in self._tokens:
            subscribe = getattr(token, "subscribe", None)
            if callable(subscribe):
                unsubscribers.append(subscribe(callback))
        if self.cancelled:
            callback()
        def unsubscribe():
            for remove in unsubscribers:
                remove()
        return unsubscribe

    def is_set(self) -> bool:
        return self.cancelled


class _ExecutionRejected(RuntimeError):
    def __init__(self, failure: RuntimeFailure) -> None:
        self.failure = failure
        super().__init__(failure.message)


class NormalChatRuntime:
    """Own accepted-turn preparation, dispatch, commit, and terminal cleanup."""

    def __init__(
        self,
        *,
        transactions: NormalChatTransactionService,
        conversation: NormalChatConversationServices,
        providers: NormalChatExecutionProvider,
        workers: WorkerSupervisor,
    ) -> None:
        self._transactions = transactions
        self._conversation = conversation
        self._providers = providers
        self._workers = workers
        self._lock = threading.Lock()
        self._active: dict[str, NormalChatExecutionHandle] = {}

    @classmethod
    def compose(
        cls,
        *,
        conversation: NormalChatConversationServices,
        turns: NormalChatTurnPort,
        providers: NormalChatProviderServices,
        identity_relay: NormalChatIdentityRelayPort,
        workers: WorkerSupervisor,
        assembler: NormalChatRequestAssembler,
    ) -> "NormalChatRuntime":
        transactions = NormalChatTransactionService(
            conversation=conversation,
            turns=turns,
            providers=providers,
            identity_relay=identity_relay,
            workers=workers,
            assembler=assembler,
        )
        return cls(
            transactions=transactions,
            conversation=conversation,
            providers=providers,
            workers=workers,
        )

    @property
    def transactions(self) -> NormalChatTransactionService:
        return self._transactions

    def prepare(
        self,
        acceptance: NormalChatAcceptance,
        *,
        history: Sequence[Mapping[str, object]] | None = None,
        accepted_turn: TurnSnapshot | None = None,
        request_only_continue_cue: bool = False,
        relay_query: Mapping[str, object] | None = None,
        timeout: float | None = None,
    ) -> CommandResult[PreparedNormalChatTurn]:
        begun = self._transactions.begin(
            acceptance,
            accepted_turn=accepted_turn,
        )
        if not begun.accepted or begun.value is None:
            return CommandResult(False, failure=begun.failure)
        return self._prepare_transaction(
            begun.value,
            self._history(history),
            request_only_continue_cue=request_only_continue_cue,
            relay_query=relay_query,
            timeout=timeout,
        )

    def prepare_regeneration(
        self,
        source_transaction_id: str,
        *,
        history: Sequence[Mapping[str, object]] | None = None,
        request_only_continue_cue: bool = True,
        relay_query: Mapping[str, object] | None = None,
        timeout: float | None = None,
        persona: NormalChatPersonaSnapshot | None = None,
        persona_overrides: Mapping[str, object] | None = None,
        relay_query_state: Mapping[str, object] | None = None,
        memory_work_context: object = None,
        history_anchor_index: int | None = None,
    ) -> CommandResult[PreparedNormalChatTurn]:
        regenerated = self._transactions.regenerate(
            source_transaction_id,
            persona=persona,
            persona_overrides=persona_overrides,
            relay_query_state=relay_query_state,
            memory_work_context=memory_work_context,
            history_anchor_index=history_anchor_index,
        )
        if not regenerated.accepted or regenerated.value is None:
            return CommandResult(False, failure=regenerated.failure)
        return self._prepare_transaction(
            regenerated.value,
            self._history(history),
            request_only_continue_cue=request_only_continue_cue,
            relay_query=relay_query,
            timeout=timeout,
        )

    def dispatch(
        self,
        prepared: PreparedNormalChatTurn,
        *,
        stream: bool = False,
        stream_sink: NormalChatStreamSink | None = None,
        assistant_metadata: Mapping[str, object] | None = None,
    ) -> CommandResult[NormalChatExecutionHandle]:
        failure = self._prepared_failure(prepared)
        if failure is not None:
            return CommandResult(False, failure=failure)
        state = _ExecutionState(prepared)
        handle = NormalChatExecutionHandle(
            prepared.transaction_id,
            prepared.request.request_id,
            prepared.lease,
            self,
            state,
        )
        with self._lock:
            existing = self._active.get(prepared.request.request_id)
            if existing is not None:
                return CommandResult(True, existing)
            self._active[prepared.request.request_id] = handle
        transaction_token = self._transactions.cancellation_token(prepared.request)
        try:
            worker = self._workers.spawn(
                name="nc-normal-chat-execution",
                lease=prepared.lease,
                target=lambda supervisor_token: self._execute_worker(
                    state,
                    supervisor_token,
                    transaction_token,
                    stream=bool(stream),
                    stream_sink=stream_sink,
                    assistant_metadata=assistant_metadata,
                ),
                on_cancel=(
                    None
                    if transaction_token is None
                    else lambda reason: transaction_token.cancel(reason)
                ),
                identity=(
                    "normal_chat_execution",
                    prepared.transaction_id,
                    prepared.request.request_id,
                ),
                owner_token=self,
            )
        except BaseException as exc:
            with self._lock:
                self._active.pop(prepared.request.request_id, None)
            self._transactions.cancel(prepared.request, reason="worker_start_failed")
            return _failure(
                "normal_chat_worker_start_failed",
                str(exc) or "Normal Chat execution worker could not start.",
                exc,
            )
        state.worker = worker
        return CommandResult(True, handle)

    def execute(
        self,
        prepared: PreparedNormalChatTurn,
        *,
        stream: bool = False,
        stream_sink: NormalChatStreamSink | None = None,
        assistant_metadata: Mapping[str, object] | None = None,
        timeout: float | None = None,
    ) -> CommandResult[NormalChatExecutionResult]:
        dispatched = self.dispatch(
            prepared,
            stream=stream,
            stream_sink=stream_sink,
            assistant_metadata=assistant_metadata,
        )
        if not dispatched.accepted or dispatched.value is None:
            return CommandResult(False, failure=dispatched.failure)
        return dispatched.value.wait(timeout)

    def cancel(
        self,
        execution: NormalChatExecutionHandle | PreparedNormalChatTurn,
        *,
        reason: str = "cancelled",
    ) -> CommandResult[None]:
        request = (
            execution._state.prepared.request
            if isinstance(execution, NormalChatExecutionHandle)
            else execution.request
        )
        with self._lock:
            handle = self._active.get(request.request_id)
        if handle is not None and handle._state.done.is_set():
            return _failure(
                "normal_chat_execution_terminal",
                "The Normal Chat execution is already terminal.",
            )
        cancelled = self._transactions.cancel(
            request, reason=str(reason or "cancelled")
        )
        if not cancelled.accepted:
            return CommandResult(False, failure=cancelled.failure)
        if handle is not None:
            worker = handle._state.worker
            if worker is not None:
                self._workers.cancel_handles((worker,), str(reason or "cancelled"))
            handle._state.append_trace("cancelled")
            handle._state.publish(
                failure=RuntimeFailure(
                    "normal_chat_cancelled",
                    str(reason or "Normal Chat execution was cancelled."),
                )
            )
            self._retire(handle)
        return CommandResult(True)

    def invalidate_all(self, reason: str) -> tuple[NormalChatTerminalReceipt, ...]:
        with self._lock:
            handles = tuple(self._active.values())
        receipts: list[NormalChatTerminalReceipt] = []
        for handle in handles:
            self.cancel(handle, reason=reason)
            receipt = self._transactions.terminal_receipt(handle.transaction_id)
            if receipt is not None:
                receipts.append(receipt)
        known = {receipt.transaction_id for receipt in receipts}
        receipts.extend(
            receipt
            for receipt in self._transactions.invalidate_all(reason)
            if receipt.transaction_id not in known
        )
        return tuple(receipts)

    def _prepare_transaction(
        self,
        transaction: NormalChatTransactionSnapshot,
        history: Sequence[Mapping[str, object]],
        *,
        request_only_continue_cue: bool,
        relay_query: Mapping[str, object] | None,
        timeout: float | None,
    ) -> CommandResult[PreparedNormalChatTurn]:
        frozen = self._transactions.freeze_request(
            transaction,
            history,
            request_only_continue_cue=request_only_continue_cue,
            relay_query=relay_query,
        )
        if not frozen.accepted or frozen.value is None:
            self._transactions.cancel(
                transaction,
                reason=_failure_category(frozen.failure, "request_freeze_failed"),
            )
            return CommandResult(False, failure=frozen.failure)
        ready = self._transactions.ensure_ready(frozen.value, timeout=timeout)
        if not ready.accepted or ready.value is None:
            self._transactions.cancel(
                frozen.value,
                reason=_failure_category(ready.failure, "request_prepare_failed"),
            )
            return CommandResult(False, failure=ready.failure)
        current = self._transactions.snapshot(frozen.value)
        if current is None or current.status is not NormalChatTransactionStatus.READY:
            self._transactions.cancel(frozen.value, reason="prepared_route_stale")
            return _failure(
                "prepared_route_stale",
                "The Normal Chat route changed before prepared request handoff.",
            )
        return CommandResult(
            True,
            PreparedNormalChatTurn(current, frozen.value, ready.value),
        )

    def _history(
        self,
        override: Sequence[Mapping[str, object]] | None,
    ) -> tuple[Mapping[str, object], ...]:
        source = self._conversation.message_mappings() if override is None else override
        return tuple(_freeze_mapping(item) for item in source)

    def _execute_worker(
        self,
        state: _ExecutionState,
        supervisor_token: CancellationToken,
        transaction_token: CancellationToken | None,
        *,
        stream: bool,
        stream_sink: NormalChatStreamSink | None,
        assistant_metadata: Mapping[str, object] | None,
    ) -> None:
        prepared = state.prepared
        cancellation = _CombinedCancellation(supervisor_token, transaction_token)
        state.append_trace("execution_started")
        fallback_used = False
        try:
            self._raise_if_cancelled(cancellation)
            if stream:
                text, fallback_used = self._stream_or_fallback(
                    state,
                    cancellation,
                    stream_sink,
                )
            else:
                text = self._complete(state, cancellation, kind="completion")
            self._raise_if_cancelled(cancellation)
            if not text:
                terminal = self._transactions.cancel(
                    prepared.request,
                    reason="empty_provider_reply",
                )
                if not terminal.accepted or terminal.value is None:
                    raise _ExecutionRejected(
                        terminal.failure
                        or RuntimeFailure(
                            "empty_reply_cleanup_failed",
                            "The empty Normal Chat reply could not be cleaned up.",
                        )
                    )
                trace = self._trace_with(state, "empty_reply", "transaction_cleaned")
                result = NormalChatExecutionResult(
                    prepared,
                    "",
                    terminal.value,
                    None,
                    bool(stream),
                    fallback_used,
                    trace,
                )
                state.publish(result=result)
                return
            metadata = dict(assistant_metadata or {})
            metadata.setdefault("origin", "assistant_reply")
            metadata["normal_chat_transaction_id"] = prepared.transaction_id
            relay_metadata = prepared.transaction.relay_metadata
            if relay_metadata is not None:
                metadata["identity_relay"] = dict(relay_metadata)
            state.append_trace("assistant_commit_started")
            committed = self._transactions.commit_assistant(
                prepared.request,
                text,
                metadata=metadata,
            )
            if not committed.accepted or committed.value is None:
                raise _ExecutionRejected(
                    committed.failure
                    or RuntimeFailure(
                        "assistant_commit_failed",
                        "The Normal Chat assistant commit was rejected.",
                    )
                )
            trace = self._trace_with(
                state,
                "assistant_committed",
                "transaction_cleaned",
            )
            result = NormalChatExecutionResult(
                prepared,
                text,
                committed.value.terminal,
                committed.value,
                bool(stream),
                fallback_used,
                trace,
            )
            state.publish(result=result)
        except _ExecutionRejected as exc:
            self._finish_rejected(prepared.request, exc.failure)
            state.append_trace("execution_rejected")
            state.publish(failure=exc.failure)
        except BaseException as exc:
            failure = RuntimeFailure(
                "normal_chat_execution_failed",
                str(exc) or "Normal Chat execution failed.",
                exc,
            )
            self._finish_failed(prepared.request, failure)
            state.append_trace("execution_failed")
            state.publish(failure=failure)
        finally:
            self._retire_state(state)

    def _stream_or_fallback(
        self,
        state: _ExecutionState,
        cancellation: _CombinedCancellation,
        sink: NormalChatStreamSink | None,
    ) -> tuple[str, bool]:
        prepared = state.prepared
        provider = prepared.provider_request.provider
        if not self._providers.frozen_execution_available(provider, stream=True):
            state.append_trace("stream_unavailable")
            text = self._complete(state, cancellation, kind="fallback_completion")
            self._publish_fallback_chunk(state, sink, text)
            return text, True
        selected_request = self._claim(state, "stream")
        state.append_trace("stream_dispatched")
        chunks: list[str] = []
        received_content = False
        try:
            stream = self._providers.stream(
                selected_request,
                cancellation,
            )
            for value in stream:
                self._raise_if_cancelled(cancellation)
                self._raise_if_stale(prepared)
                text = str(value or "")
                if not text:
                    continue
                received_content = True
                chunks.append(text)
                state.append_trace("stream_chunk")
                if sink is not None:
                    accepted = sink.publish(
                        NormalChatStreamChunk(
                            prepared.transaction_id,
                            prepared.request.request_id,
                            prepared.lease,
                            len(chunks),
                            text,
                        )
                    )
                    if accepted is False:
                        raise _ExecutionRejected(
                            RuntimeFailure(
                                "stream_publication_rejected",
                                "The Normal Chat stream sink rejected its exact lease.",
                            )
                        )
            self._raise_if_cancelled(cancellation)
            self._raise_if_stale(prepared)
            state.append_trace("stream_completed")
            return "".join(chunks), False
        except _ExecutionRejected:
            raise
        except BaseException as exc:
            if received_content:
                raise _ExecutionRejected(
                    RuntimeFailure(
                        "provider_stream_failed",
                        str(exc) or "Normal Chat provider streaming failed.",
                        exc,
                    )
                ) from exc
            state.append_trace("stream_start_failed")
            text = self._complete(state, cancellation, kind="fallback_completion")
            self._publish_fallback_chunk(state, sink, text)
            return text, True

    def _complete(
        self,
        state: _ExecutionState,
        cancellation: _CombinedCancellation,
        *,
        kind: str,
    ) -> str:
        self._raise_if_cancelled(cancellation)
        selected_request = self._claim(state, kind)
        state.append_trace(f"{kind}_dispatched")
        result = self._providers.complete(
            selected_request,
            cancellation,
        )
        if not result.accepted:
            self._raise_if_cancelled(cancellation)
            raise _ExecutionRejected(
                result.failure
                or RuntimeFailure(
                    "provider_execution_failed",
                    "Normal Chat provider completion failed.",
                )
            )
        self._raise_if_cancelled(cancellation)
        self._raise_if_stale(state.prepared)
        state.append_trace(f"{kind}_completed")
        return str(result.value or "")

    def _claim(self, state: _ExecutionState, kind: str) -> FrozenTurnRequest:
        prepared = state.prepared
        claimed = self._transactions.claim_dispatch(
            prepared.request,
            prepared.provider_request.request,
            kind=kind,
        )
        if not claimed.accepted:
            raise _ExecutionRejected(
                claimed.failure
                or RuntimeFailure(
                    "provider_dispatch_rejected",
                    "The Normal Chat provider dispatch was rejected.",
                )
            )
        return getattr(claimed.value, "selected_request", None) or prepared.provider_request.request

    def _publish_fallback_chunk(
        self,
        state: _ExecutionState,
        sink: NormalChatStreamSink | None,
        text: str,
    ) -> None:
        if sink is None or not text:
            return
        prepared = state.prepared
        self._raise_if_stale(prepared)
        if (
            sink.publish(
                NormalChatStreamChunk(
                    prepared.transaction_id,
                    prepared.request.request_id,
                    prepared.lease,
                    1,
                    text,
                )
            )
            is False
        ):
            raise _ExecutionRejected(
                RuntimeFailure(
                    "stream_publication_rejected",
                    "The Normal Chat stream sink rejected fallback publication.",
                )
            )
        state.append_trace("fallback_chunk")

    def _prepared_failure(
        self,
        prepared: PreparedNormalChatTurn,
    ) -> RuntimeFailure | None:
        if not isinstance(prepared, PreparedNormalChatTurn):
            return RuntimeFailure(
                "prepared_turn_invalid",
                "Normal Chat dispatch requires PreparedNormalChatTurn.",
            )
        current = self._transactions.snapshot(prepared.request)
        if (
            current is None
            or current.status is not NormalChatTransactionStatus.READY
            or current.request != prepared.request
            or current.prepared is None
            or current.prepared.request is not prepared.provider_request.request
        ):
            return RuntimeFailure(
                "prepared_route_stale",
                "The prepared Normal Chat request no longer owns its route.",
            )
        return None

    def _raise_if_stale(self, prepared: PreparedNormalChatTurn) -> None:
        failure = self._prepared_failure(prepared)
        if failure is not None:
            raise _ExecutionRejected(failure)

    @staticmethod
    def _raise_if_cancelled(cancellation: _CombinedCancellation) -> None:
        if cancellation.cancelled:
            raise _ExecutionRejected(
                RuntimeFailure(
                    "normal_chat_cancelled",
                    cancellation.reason or "Normal Chat execution was cancelled.",
                )
            )

    def _finish_rejected(
        self,
        request: NormalChatRequestSnapshot,
        failure: RuntimeFailure,
    ) -> None:
        current = self._transactions.snapshot(request)
        if current is None:
            return
        if failure.category == "normal_chat_cancelled":
            self._transactions.cancel(request, reason=failure.category)
            return
        self._transactions.finish(
            request,
            TurnTerminalStatus.FAILED,
            reason=failure.category,
        )

    @staticmethod
    def _trace_with(state: _ExecutionState, *events: str) -> tuple[str, ...]:
        for event in events:
            state.append_trace(event)
        return state.prepared.trace + state.snapshot().trace

    def _retire(self, handle: NormalChatExecutionHandle) -> None:
        with self._lock:
            if self._active.get(handle.request_id) is handle:
                self._active.pop(handle.request_id, None)

    def _retire_state(self, state: _ExecutionState) -> None:
        with self._lock:
            handle = self._active.get(state.prepared.request.request_id)
            if handle is not None and handle._state is state:
                self._active.pop(state.prepared.request.request_id, None)


def _without_leading_control_tags(value: object) -> str:
    normalized = str(value or "").strip()
    while normalized.startswith("["):
        close = normalized.find("]")
        if close <= 1:
            break
        tag = normalized[1:close].strip()
        if not tag or not all(
            character.isalnum() or character in {"_", "-"}
            for character in tag
        ):
            break
        normalized = normalized[close + 1 :].lstrip()
    return normalized


def _failure(
    category: str,
    message: str,
    cause: BaseException | None = None,
) -> CommandResult:
    return CommandResult(False, failure=RuntimeFailure(category, message, cause))


def _failure_category(failure: RuntimeFailure | None, fallback: str) -> str:
    return failure.category if failure is not None else str(fallback)


__all__ = [
    "NormalChatApplicationAdapter",
    "NormalChatApplicationBlocked",
    "NormalChatApplicationStream",
    "NormalChatExecutionHandle",
    "NormalChatExecutionProvider",
    "NormalChatExecutionResult",
    "NormalChatExecutionSnapshot",
    "NormalChatPromptPlan",
    "NormalChatPromptPlanBuilder",
    "NormalChatRuntime",
    "NormalChatHistory",
    "NormalChatConversationServices",
    "NormalChatProviderServices",
    "NormalChatStreamChunk",
    "NormalChatStreamSink",
    "PreparedNormalChatTurn",
    "PromptAssemblyNormalChatRequestAssembler",
]
