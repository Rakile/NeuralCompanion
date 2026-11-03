"""Explicit state transitions and production conversation orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import queue
import threading
import time
from types import MappingProxyType
from typing import Any, Protocol
from uuid import uuid4

from core import companion_orb_vision_debug, runtime_hotkeys
from core.runtime.assistant_directives import AssistantFocusDirective
from core.runtime.contracts import CommandResult
from core.runtime.conversation_actions import ConversationActionRequest, ConversationActionTarget
from core.runtime.identifiers import TurnId, WorkLease
from core.runtime.phone_reply_controls import PhoneReplyControls, PhoneReplyScope, PhoneReplySpeechBinding
from core.runtime.interaction import (
    InteractionCommand,
    InteractionCommandCapabilities,
    InteractionDispatch,
    InteractionEffectResult,
    InteractionFlow,
    InteractionIntent,
    InteractionPhase,
    InteractionService,
)
from core.runtime.proactive import ProactiveService
from core.runtime.replay import ReplayReceipt, ReplayService
from core.runtime.sensory import SensoryService
from core.runtime.speech_input import FinalTranscript
from core.runtime.turns import TurnSnapshot, TurnTerminalStatus
from core.runtime.visual import (
    VISUAL_REPLY_REQUEST_TEXT_CONFIG_KEY,
    VISUAL_REPLY_SOURCE_IMAGE_CONFIG_KEY,
)


class ConversationPhase(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    PAUSED = "paused"
    STOPPED = "stopped"


class ConversationEventType(str, Enum):
    START = "start"
    STOP_REQUESTED = "stop_requested"
    INTERACTION_STATUS = "interaction_status"
    USER_TEXT_CAPTURED = "user_text_captured"
    USER_TEXT_EMPTY = "user_text_empty"
    PROACTIVE_TIMEOUT = "proactive_timeout"
    REGENERATE_REQUESTED = "regenerate_requested"
    RETRY_REQUESTED = "retry_requested"
    THINKING_STARTED = "thinking_started"
    ASSISTANT_REPLY_READY = "assistant_reply_ready"
    ASSISTANT_REPLY_EMPTY = "assistant_reply_empty"
    STREAM_REPLY_STARTED = "stream_reply_started"
    SPEAKING_STARTED = "speaking_started"
    SPEAKING_FINISHED = "speaking_finished"
    BARGE_IN_CAPTURED = "barge_in_captured"
    PAUSE_TOGGLED = "pause_toggled"
    ERROR = "error"


class ConversationActionType(str, Enum):
    ENTER_LISTENING = "enter_listening"
    ENTER_THINKING = "enter_thinking"
    ENTER_SPEAKING = "enter_speaking"
    ENTER_PAUSED = "enter_paused"
    CAPTURE_VOICE = "capture_voice"
    CAPTURE_PUSH_TO_TALK = "capture_push_to_talk"
    GENERATE_PROACTIVE_TURN = "generate_proactive_turn"
    APPEND_HISTORY = "append_history"
    POP_LAST_HISTORY = "pop_last_history"
    START_LLM_REQUEST = "start_llm_request"
    START_LLM_STREAM = "start_llm_stream"
    START_TTS = "start_tts"
    STOP_TTS = "stop_tts"
    STOP_STREAM = "stop_stream"
    FINALIZE_REPLY = "finalize_reply"
    RESET_SILENCE_TIMER = "reset_silence_timer"
    MARK_ERROR = "mark_error"
    NOOP = "noop"


@dataclass(slots=True)
class ConversationPolicy:
    allow_proactive_replies: bool = True
    require_first_user_before_proactive: bool = False
    proactive_delay_seconds: float = 10.0
    interaction_poll_seconds: float = 0.05
    microphone_timeout_seconds: float = 0.6
    stream_mode: bool = False
    input_message_role: str = "user"
    max_history_messages: int = 40

    @classmethod
    def from_runtime_config(cls, runtime_config: Mapping[str, object]) -> "ConversationPolicy":
        input_role = str(runtime_config.get("input_message_role", "user") or "user").lower()
        if input_role not in {"user", "system", "assistant"}:
            input_role = "user"
        return cls(
            allow_proactive_replies=bool(runtime_config.get("allow_proactive_replies", True)),
            require_first_user_before_proactive=bool(runtime_config.get("require_first_user_before_proactive", False)),
            proactive_delay_seconds=max(0.5, float(runtime_config.get("proactive_delay_seconds", 10.0) or 10.0)),
            interaction_poll_seconds=0.05,
            microphone_timeout_seconds=0.6,
            stream_mode=bool(runtime_config.get("stream_mode", False)),
            input_message_role=input_role,
            max_history_messages=max(4, int(runtime_config.get("max_history_messages", 40) or 40)),
        )


@dataclass(frozen=True, slots=True)
class TurnExecutionPolicy:
    """Per-turn decisions derived only from the accepted immutable snapshot."""

    config: Mapping[str, object]
    assistant_reply_config: Mapping[str, object]
    stream_mode: bool
    tts_backend: str
    input_message_role: str

    @classmethod
    def from_snapshot(cls, snapshot: TurnSnapshot) -> "TurnExecutionPolicy":
        config = snapshot.config.values
        accepted_message = getattr(snapshot.accepted_turn, "message", None)
        accepted_metadata = getattr(accepted_message, "metadata", {})
        guarded_orb_turn = bool(
            isinstance(accepted_metadata, Mapping)
            and accepted_metadata.get("companion_orb_response_guidance")
        )
        input_role = str(config.get("input_message_role", "user") or "user").lower()
        if input_role not in {"user", "system", "assistant"}:
            input_role = "user"
        assistant_reply_config = dict(config)
        assistant_reply_config[VISUAL_REPLY_REQUEST_TEXT_CONFIG_KEY] = str(
            getattr(accepted_message, "content", "") or ""
        )
        assistant_reply_config[VISUAL_REPLY_SOURCE_IMAGE_CONFIG_KEY] = ""
        if isinstance(accepted_metadata, Mapping) and getattr(accepted_message, "role", "user") == "user":
            assistant_reply_config[VISUAL_REPLY_SOURCE_IMAGE_CONFIG_KEY] = str(
                accepted_metadata.get("attachment_image_path", "") or ""
            )
        return cls(
            config=config,
            assistant_reply_config=MappingProxyType(assistant_reply_config),
            # Guarded Orb turns must validate the complete Main Chat response
            # before committing it or sending any part of it to TTS.
            stream_mode=bool(config.get("stream_mode", False))
            and not guarded_orb_turn,
            tts_backend=str(config.get("tts_backend", "") or ""),
            input_message_role=input_role,
        )


@dataclass(frozen=True, slots=True)
class PreparedAssistantReply:
    text: str
    visual_prompt: str = ""
    finalize_duration_ms: float = 0.0
    orb_focus: AssistantFocusDirective | None = None
    visual_inputs: tuple[Path, ...] = ()
    visual_reference_strength: float | None = None
    visual_uses_persona_identity: bool = False
    visual_uses_user_identity: bool = False
    visual_edits_source_image: bool = False
    visual_source_edit_error: str = ""
    visual_source_edit_config: Mapping[str, object] | None = None


def _trim_assistant_continuation_history_prefix(
    history: list[Mapping[str, object]] | tuple[Mapping[str, object], ...],
    text: str,
) -> str:
    candidate = str(text or "").strip()
    if not history:
        return candidate
    tail = history[-1]
    if str(tail.get("role", "") or "").strip().lower() != "assistant":
        return candidate

    def without_leading_control_tags(value: object) -> str:
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

    visible_candidate = without_leading_control_tags(candidate)
    visible_tail = without_leading_control_tags(tail.get("content", ""))
    if not visible_candidate or not visible_tail:
        return candidate
    if visible_candidate.casefold().startswith(visible_tail.casefold()):
        return visible_candidate[len(visible_tail) :].lstrip()
    if (
        " ".join(visible_candidate.split()).casefold()
        == " ".join(visible_tail.split()).casefold()
    ):
        return ""
    return candidate


@dataclass(frozen=True, slots=True)
class SpeechControlEvents:
    stop: threading.Event
    listening: threading.Event
    microphone: threading.Event
    audio_playing: threading.Event
    stop_playback: threading.Event
    manual_pause: threading.Event
    pause_after_chunk: threading.Event
    playback_paused: threading.Event


@dataclass(frozen=True, slots=True)
class ProductionRunOptions:
    start_sensory_worker: bool = True
    max_loop_iterations: int | None = None


class TurnCoordinatorPort(Protocol):
    def snapshot(self, turn_id: TurnId) -> TurnSnapshot | None: ...

    def committed_effect_lease_is_valid(self, lease: WorkLease) -> bool: ...

    def finish(
        self,
        turn_id: TurnId,
        status: TurnTerminalStatus,
        *,
        lease: WorkLease,
    ) -> CommandResult[None]: ...


InputTurn = dict[str, object]
RequestContext = dict[str, object]
ReplySourceMetadata = dict[str, object]
AddonCommand = dict[str, object]


class WaitFlagPort(Protocol):
    def is_set(self) -> bool: ...
    def set(self) -> None: ...
    def clear(self) -> None: ...
    def wait(self, timeout: float | None = None) -> bool: ...


class TTSControlPort(Protocol):
    done: WaitFlagPort
    audio_started: WaitFlagPort

    def get_spoken_text(self) -> str: ...
    def pause(self) -> bool: ...
    def resume(self) -> bool: ...


class StreamReplyPort(Protocol):
    done: WaitFlagPort
    cancel_requested: WaitFlagPort
    full_text: str
    error: BaseException | None


class RecordInterruptedAssistantOperation(Protocol):
    def __call__(
        self,
        request: RequestContext | None,
        text: str,
        *,
        hidden_proactive: bool = False,
    ) -> bool: ...


class ArmUserImageOperation(Protocol):
    def __call__(self, turn: InputTurn, *, is_placeholder: bool = False) -> object: ...


class AttachUserImageOperation(Protocol):
    def __call__(self, turn: InputTurn, *, is_placeholder: bool = False) -> InputTurn: ...


class BeginTransactionOperation(Protocol):
    def __call__(
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
    ) -> InputTurn: ...


class FreezeRequestOperation(Protocol):
    def __call__(
        self,
        accepted_input_turn: Mapping[str, object] | None = None,
        *,
        request_only_continue_cue: bool = False,
        require_existing_transaction: bool = False,
        regenerate_route: bool = False,
    ) -> RequestContext: ...


class ReplySourceMetadataOperation(Protocol):
    def __call__(
        self,
        request: RequestContext,
        *,
        hidden_proactive: bool = False,
    ) -> ReplySourceMetadata: ...


class CompleteTransactionOperation(Protocol):
    def __call__(
        self,
        request: RequestContext | None = None,
        *,
        turn_id: str = "",
        discard_binding: bool = False,
    ) -> None: ...


class AppendAssistantOperation(Protocol):
    def __call__(
        self,
        text: str,
        *,
        identity_relay: object = None,
        expected_session_generation: int | None = None,
        expected_turn_id: str | None = None,
        hidden_proactive: bool = False,
    ) -> InputTurn | None: ...


class ListenOperation(Protocol):
    def __call__(
        self,
        source: object,
        *,
        timeout: float | None = None,
        lease: WorkLease | None = None,
    ) -> CommandResult[FinalTranscript]: ...


class BeginDryRunOperation(Protocol):
    def __call__(
        self,
        config: Mapping[str, object],
        *,
        streamed: bool,
        proactive: bool,
    ) -> str | None: ...


class UserAddonCommandOperation(Protocol):
    def __call__(
        self,
        text: str,
        *,
        input_role: str,
    ) -> AddonCommand | None: ...


class BuddyAddonCommandOperation(Protocol):
    def __call__(self, payload: object) -> AddonCommand | None: ...


class PrepareCompletedSegmentsOperation(Protocol):
    def __call__(
        self,
        text: str,
        *,
        runtime_config: Mapping[str, object],
    ) -> object: ...


class PrepareAssistantReplyOperation(Protocol):
    def __call__(
        self,
        text: str,
        *,
        runtime_config: Mapping[str, object],
    ) -> PreparedAssistantReply: ...


class PublishAssistantReplyOperation(Protocol):
    def __call__(
        self,
        prepared: PreparedAssistantReply,
        *,
        lease: WorkLease,
    ) -> bool: ...


class ChatReplyOperation(Protocol):
    def __call__(self, request: RequestContext) -> str | None: ...


class StartStreamOperation(Protocol):
    def __call__(
        self,
        text_queue: object,
        *,
        dry_run_reply_id: str | None,
        request_context: RequestContext,
        preserve_voice_labels: bool,
        show_preview: bool = True,
    ) -> StreamReplyPort: ...


class SpeakOperation(Protocol):
    def __call__(
        self,
        text: str,
        *,
        text_iterable: object = None,
        dry_run_reply_id: str | None = None,
        voice_path_override: str | None = None,
        preserve_text_iterable_chunks: bool = False,
        reply_source_meta: Mapping[str, object] | None = None,
        runtime_config: Mapping[str, object] | None = None,
        turn_lease: WorkLease | None = None,
    ) -> TTSControlPort: ...


class SpeakStreamOperation(Protocol):
    def __call__(
        self,
        text_queue: object,
        *,
        dry_run_reply_id: str | None = None,
        requires_full_text: bool | None = None,
        reply_source_meta: Mapping[str, object] | None = None,
        runtime_config: Mapping[str, object] | None = None,
        turn_lease: WorkLease | None = None,
    ) -> TTSControlPort: ...


@dataclass(slots=True)
class ConversationEvent:
    type: ConversationEventType
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConversationAction:
    type: ConversationActionType
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConversationState:
    phase: ConversationPhase = ConversationPhase.IDLE
    started_at: float | None = None
    silence_started_at: float | None = None
    last_transition_at: float | None = None
    pending_user_text: str | None = None
    pending_assistant_text: str | None = None
    active_reply_id: Any = None
    assistant_history_added: bool = False
    discard_assistant_history: bool = False
    stream_active: bool = False
    was_barge_in: bool = False
    is_proactive_turn: bool = False
    proactive_placeholder_role: str | None = None
    preserve_proactive_placeholder: bool = False
    skip_input_history_append: bool = False
    has_real_user_turn: bool = False
    last_error: str | None = None
    last_status: str | None = None

    def copy(self) -> "ConversationState":
        return ConversationState(**self.__dict__)


class ConversationRuntime(Protocol):
    def now(self) -> float: ...
    def should_stop(self) -> bool: ...
    def log(self, message: str) -> None: ...


class ConversationSessionOwner(Protocol):
    """Own session identity, configuration, and loaded-turn continuity."""

    def live_config(self) -> Mapping[str, object]: ...
    def session_generation(self) -> int: ...
    def session_lease(self) -> WorkLease: ...
    def consume_pending_loaded_input_turn(self) -> InputTurn | None: ...
    def discard_pending_loaded_input_turn(self, *, expected_session_generation: int) -> None: ...
    def reconstruct_input_turn(self, turn: Mapping[str, object] | None) -> InputTurn | None: ...
    def request_chat_view_rebuild(self) -> None: ...
    def prune_normal_chat_transactions(self) -> None: ...
    def display_input_turn_content(self, turn: Mapping[str, object]) -> str: ...


class ConversationHistoryOwner(Protocol):
    """Own persisted conversation history and its memory side effects."""

    @property
    def request_only_continuation_cue(self) -> str: ...

    def history_snapshot(self) -> tuple[InputTurn, ...]: ...
    def history_has_role(self, role: str) -> bool: ...
    def discard_last_exchange_for_retry(self) -> bool: ...
    def prepare_regeneration_turn(self, in_history: bool) -> tuple[InputTurn | None, bool]: ...
    def record_interrupted_assistant(
        self,
        request: RequestContext | None,
        text: str,
        *,
        hidden_proactive: bool = False,
    ) -> bool: ...
    def append_assistant_history_turn(
        self,
        text: str,
        *,
        identity_relay: object = None,
        expected_session_generation: int | None = None,
        expected_turn_id: str | None = None,
        hidden_proactive: bool = False,
        assistant_persona: object = None,
    ) -> InputTurn | None: ...
    def apply_stored_chat_history_limit(self) -> None: ...
    def pop_last_proactive_placeholder(self, content: str) -> bool: ...
    def maybe_start_continuity_memory_auto_update(self) -> None: ...
    def maybe_start_long_term_memory_auto_archive(self) -> None: ...


class UserImageOwner(Protocol):
    """Own pending user-image attachment state for accepted turns."""

    def pending_user_image_attachment(self) -> bool: ...
    def maybe_arm_screen_image_for_user_turn(
        self,
        turn: InputTurn,
        *,
        is_placeholder: bool = False,
    ) -> object: ...
    def attach_pending_user_image_to_turn(
        self,
        turn: InputTurn,
        *,
        is_placeholder: bool = False,
    ) -> InputTurn: ...
    def clear_pending_user_image_attachment(self) -> None: ...


class NormalChatApplicationPort(Protocol):
    """Loop-facing bridge onto the independently owned normal-chat runtime."""

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
    ) -> InputTurn: ...
    def freeze_request(
        self,
        accepted_input_turn: Mapping[str, object] | None = None,
        *,
        request_only_continue_cue: bool = False,
        require_existing_transaction: bool = False,
        regenerate_route: bool = False,
    ) -> RequestContext: ...
    def ensure_ready(self, request: RequestContext) -> object: ...
    def reply_source_metadata(
        self,
        request: RequestContext,
        *,
        hidden_proactive: bool = False,
    ) -> ReplySourceMetadata: ...
    def cancel_request(self, request: object) -> bool: ...
    def complete(
        self,
        request: RequestContext | None = None,
        *,
        turn_id: str = "",
        discard_binding: bool = False,
    ) -> None: ...
    def transaction_for_request(self, request: object) -> RequestContext | None: ...
    def reply(self, request: RequestContext) -> str | None: ...
    def start_stream(
        self,
        text_queue: object,
        *,
        dry_run_reply_id: str | None,
        request_context: RequestContext,
        preserve_voice_labels: bool,
    ) -> StreamReplyPort: ...


class ConversationLoopControlOwner(Protocol):
    """Own run cancellation and interaction controls for the conversation loop."""

    @property
    def controls(self) -> SpeechControlEvents: ...

    @property
    def continue_assistant_sentinel(self) -> str: ...

    @property
    def blocked_error(self) -> type[BaseException]: ...

    def prepare_run(self) -> None: ...
    def request_stop(self) -> None: ...
    def check_interaction_status(self, source: object) -> InteractionCommand | str | None: ...
    def set_last_resume_requested_at(self, timestamp: float) -> None: ...


class SpeechInputOwner(Protocol):
    """Own final-transcript capture and freshness validation."""

    def listen_for_speech(
        self,
        source: object,
        *,
        timeout: float | None = None,
        lease: WorkLease | None = None,
    ) -> CommandResult[FinalTranscript]: ...
    def listen_for_speech_push_to_talk(
        self,
        source: object,
        *,
        timeout: float | None = None,
        lease: WorkLease | None = None,
    ) -> CommandResult[FinalTranscript]: ...
    def transcript_is_current(self, transcript: FinalTranscript) -> bool: ...


class SpeechOutputOwner(Protocol):
    """Own assistant reply preparation, publication, and speech playback."""

    def prepare_low_latency_completed_tts_segments(
        self,
        text: str,
        *,
        runtime_config: Mapping[str, object],
    ) -> object: ...
    def prepare_assistant_reply(
        self,
        text: str,
        *,
        runtime_config: Mapping[str, object],
    ) -> PreparedAssistantReply: ...
    def publish_assistant_reply_effects(
        self,
        prepared: PreparedAssistantReply,
        *,
        lease: WorkLease,
    ) -> bool: ...
    def speak_async(
        self,
        text: str,
        *,
        text_iterable: object = None,
        dry_run_reply_id: str | None = None,
        voice_path_override: str | None = None,
        preserve_text_iterable_chunks: bool = False,
        reply_source_meta: Mapping[str, object] | None = None,
        runtime_config: Mapping[str, object] | None = None,
        turn_lease: WorkLease | None = None,
    ) -> TTSControlPort: ...
    def speak_async_stream(
        self,
        text_queue: object,
        *,
        dry_run_reply_id: str | None = None,
        requires_full_text: bool | None = None,
        reply_source_meta: Mapping[str, object] | None = None,
        runtime_config: Mapping[str, object] | None = None,
        turn_lease: WorkLease | None = None,
    ) -> TTSControlPort: ...


class DryRunReplyOwner(Protocol):
    """Own deterministic dry-run reply selection and accounting."""

    def dry_run_auto_replies_enabled(self) -> bool: ...
    def next_dry_run_auto_reply(self) -> str | None: ...
    def begin_dry_run_reply(
        self,
        config: Mapping[str, object],
        *,
        streamed: bool,
        proactive: bool,
    ) -> str | None: ...
    def finalize_dry_run_reply(self, reply_id: str | None) -> None: ...
    def set_seed(self, seed: int) -> None: ...


class ConversationAddonOwner(Protocol):
    """Own addon commands that participate in a production conversation turn."""

    def maybe_handle_addon_user_text_command(
        self,
        text: str,
        *,
        input_role: str,
        accepted_input_turn: Mapping[str, object] | None = None,
    ) -> AddonCommand | None: ...
    def maybe_handle_buddy_contextual_reply(self, payload: object) -> AddonCommand | None: ...
    def addon_voice_segments_stream_policy(
        self,
        config: Mapping[str, object],
    ) -> dict[str, object]: ...


class AvatarPresenceOwner(Protocol):
    """Own the avatar presence state driven by conversation phases."""

    def set_state(self, state: str) -> None: ...
    def set_audio_level(self, level: float) -> None: ...


@dataclass(frozen=True, slots=True)
class ProductionConversationServices:
    """Complete, domain-owned service graph required by the production loop."""

    session: ConversationSessionOwner
    history: ConversationHistoryOwner
    user_images: UserImageOwner
    normal_chat: NormalChatApplicationPort
    control: ConversationLoopControlOwner
    speech_input: SpeechInputOwner
    speech_output: SpeechOutputOwner
    dry_run: DryRunReplyOwner
    addons: ConversationAddonOwner
    presence: AvatarPresenceOwner
    sensory: SensoryService
    proactive: ProactiveService
    interaction: InteractionService
    replay: ReplayService
    phone_reply_controls: "PhoneReplyControls | None" = None
    conversation_actions: object | None = None

    def missing_domains(self) -> tuple[str, ...]:
        domains = (
            ("session", self.session),
            ("history", self.history),
            ("user_images", self.user_images),
            ("normal_chat", self.normal_chat),
            ("control", self.control),
            ("speech_input", self.speech_input),
            ("speech_output", self.speech_output),
            ("dry_run", self.dry_run),
            ("addons", self.addons),
            ("presence", self.presence),
            ("sensory", self.sensory),
            ("proactive", self.proactive),
            ("interaction", self.interaction),
            ("replay", self.replay),
        )
        return tuple(name for name, owner in domains if owner is None)


def _with_phone_reply_owner(operation):
    """Tie mailbox admission and invalidation to the actual loop lifetime."""
    from functools import wraps

    @wraps(operation)
    def run(self, source, *, services=None, options=None):
        production = services or self.production_services
        phone_controls = production.phone_reply_controls if production is not None else None
        conversation_actions = production.conversation_actions if production is not None else None
        if conversation_actions is not None:
            conversation_actions.start()
        if phone_controls is not None:
            phone_controls.start()
        try:
            return operation(self, source, services=services, options=options)
        finally:
            if conversation_actions is not None:
                conversation_actions.stop()
            if phone_controls is not None:
                phone_controls.stop()
    return run


@dataclass(frozen=True, slots=True)
class LegacyMemoryEffects:
    live_config: Callable[[], Mapping[str, object]]
    history_snapshot: Callable[[], tuple[InputTurn, ...]]
    history_has_role: Callable[[str], bool]
    discard_last_exchange_for_retry: Callable[[], bool]
    prepare_regeneration_turn: Callable[[bool], tuple[InputTurn | None, bool]]
    request_only_continuation_cue: str
    pending_user_image_attachment: Callable[[], bool]
    record_interrupted_assistant: RecordInterruptedAssistantOperation
    session_generation: Callable[[], int]
    session_lease: Callable[[], WorkLease]
    consume_pending_loaded_input_turn: Callable[[], InputTurn | None]
    reconstruct_input_turn: Callable[[Mapping[str, object] | None], InputTurn | None]
    request_chat_view_rebuild: Callable[[], None]
    prune_normal_chat_transactions: Callable[[], None]
    maybe_arm_screen_image_for_user_turn: ArmUserImageOperation
    attach_pending_user_image_to_turn: AttachUserImageOperation
    clear_pending_user_image_attachment: Callable[[], None]
    begin_normal_chat_transaction: BeginTransactionOperation
    freeze_normal_chat_request: FreezeRequestOperation
    ensure_normal_chat_transaction_ready: Callable[[RequestContext], object]
    normal_chat_reply_source_meta: ReplySourceMetadataOperation
    cancel_normal_chat_request: Callable[[object], bool]
    complete_normal_chat_transaction: CompleteTransactionOperation
    normal_chat_transaction_for_request: Callable[[object], RequestContext | None]
    append_assistant_history_turn: AppendAssistantOperation
    apply_stored_chat_history_limit: Callable[[], None]
    pop_last_proactive_placeholder: Callable[[str], bool]
    display_input_turn_content: Callable[[Mapping[str, object]], str]
    maybe_start_continuity_memory_auto_update: Callable[[], None]
    maybe_start_long_term_memory_auto_archive: Callable[[], None]

    def discard_pending_loaded_input_turn(self, *, expected_session_generation: int) -> None:
        if self.session_generation() != expected_session_generation:
            return
        pending = self.consume_pending_loaded_input_turn()
        if pending and pending.get("normal_chat_transaction_id"):
            self.cancel_normal_chat_request(pending)


@dataclass(frozen=True, slots=True)
class LegacySpeechEffects:
    controls: SpeechControlEvents
    continue_assistant_sentinel: str
    check_interaction_status: Callable[[object], InteractionCommand | str | None]
    listen_for_speech: ListenOperation
    listen_for_speech_push_to_talk: ListenOperation
    transcript_is_current: Callable[[FinalTranscript], bool]
    dry_run_auto_replies_enabled: Callable[[], bool]
    next_dry_run_auto_reply: Callable[[], str | None]
    begin_dry_run_reply: BeginDryRunOperation
    finalize_dry_run_reply: Callable[[str | None], None]
    maybe_handle_addon_user_text_command: UserAddonCommandOperation
    maybe_handle_buddy_contextual_reply: BuddyAddonCommandOperation
    addon_voice_segments_stream_policy: Callable[[Mapping[str, object]], dict[str, object]]
    prepare_low_latency_completed_tts_segments: PrepareCompletedSegmentsOperation
    prepare_assistant_reply: PrepareAssistantReplyOperation
    publish_assistant_reply_effects: PublishAssistantReplyOperation
    chat_with_llm: ChatReplyOperation
    start_streamed_llm_reply: StartStreamOperation
    speak_async: SpeakOperation
    speak_async_stream: SpeakStreamOperation
    set_seed: Callable[[int], None]
    set_last_resume_requested_at: Callable[[float], None]
    blocked_error: type[BaseException]


@dataclass(frozen=True, slots=True)
class LegacyAvatarEffects:
    set_state: Callable[[str], None]
    set_audio_level: Callable[[float], None]


@dataclass(frozen=True, slots=True)
class _LegacyNormalChatApplicationPort:
    memory: LegacyMemoryEffects
    speech: LegacySpeechEffects

    def begin(self, turn, **kwargs):
        return self.memory.begin_normal_chat_transaction(turn, **kwargs)

    def freeze_request(self, accepted_input_turn=None, **kwargs):
        return self.memory.freeze_normal_chat_request(accepted_input_turn, **kwargs)

    def ensure_ready(self, request):
        return self.memory.ensure_normal_chat_transaction_ready(request)

    def reply_source_metadata(self, request, **kwargs):
        return self.memory.normal_chat_reply_source_meta(request, **kwargs)

    def cancel_request(self, request):
        return self.memory.cancel_normal_chat_request(request)

    def complete(self, request=None, **kwargs):
        return self.memory.complete_normal_chat_transaction(request, **kwargs)

    def transaction_for_request(self, request):
        return self.memory.normal_chat_transaction_for_request(request)

    def reply(self, request):
        return self.speech.chat_with_llm(request)

    def start_stream(self, text_queue, **kwargs):
        return self.speech.start_streamed_llm_reply(text_queue, **kwargs)


@dataclass(frozen=True, slots=True)
class _LegacyConversationLoopControl:
    speech: LegacySpeechEffects

    @property
    def controls(self) -> SpeechControlEvents:
        return self.speech.controls

    @property
    def continue_assistant_sentinel(self) -> str:
        return self.speech.continue_assistant_sentinel

    @property
    def blocked_error(self) -> type[BaseException]:
        return self.speech.blocked_error

    def prepare_run(self) -> None:
        self.controls.stop.clear()

    def request_stop(self) -> None:
        self.controls.stop.set()

    def check_interaction_status(self, source):
        return self.speech.check_interaction_status(source)

    def set_last_resume_requested_at(self, timestamp: float) -> None:
        self.speech.set_last_resume_requested_at(timestamp)


def _legacy_production_services(
    *,
    memory: LegacyMemoryEffects | None,
    speech: LegacySpeechEffects | None,
    avatar: LegacyAvatarEffects | None,
    sensory: SensoryService | None,
    proactive: ProactiveService | None,
    interaction: InteractionService | None,
    replay: ReplayService | None,
) -> ProductionConversationServices | None:
    if (
        memory is None
        or speech is None
        or avatar is None
        or sensory is None
        or proactive is None
        or interaction is None
        or replay is None
    ):
        return None
    return ProductionConversationServices(
        session=memory,
        history=memory,
        user_images=memory,
        normal_chat=_LegacyNormalChatApplicationPort(memory, speech),
        control=_LegacyConversationLoopControl(speech),
        speech_input=speech,
        speech_output=speech,
        dry_run=speech,
        addons=speech,
        presence=avatar,
        sensory=sensory,
        proactive=proactive,
        interaction=interaction,
        replay=replay,
    )


@dataclass(slots=True)
class SystemClockRuntime:
    stop_requested: Callable[[], bool] = lambda: False
    logger: Callable[[str], None] = print
    clock: Callable[[], float] | None = None

    def now(self) -> float:
        import time
        return float(self.clock() if self.clock is not None else time.time())

    def should_stop(self) -> bool:
        return bool(self.stop_requested())

    def log(self, message: str) -> None:
        self.logger(message)


class ConversationStateMachine:
    """Pure transition logic.

    The reducer returns explicit actions so orchestration can stay out of the state
    mutation rules. This is the core piece we eventually want the runtime loop to use.
    """

    def __init__(self, policy: ConversationPolicy):
        self.policy = policy

    def _transition(self, state: ConversationState, phase: ConversationPhase, now: float | None) -> None:
        state.phase = phase
        state.last_transition_at = now

    def proactive_allowed(self, state: ConversationState) -> bool:
        if not self.policy.allow_proactive_replies:
            return False
        if self.policy.require_first_user_before_proactive and not state.has_real_user_turn:
            return False
        return True

    def proactive_due(self, state: ConversationState, now: float) -> bool:
        if state.silence_started_at is None:
            return False
        if not self.proactive_allowed(state):
            return False
        return (now - state.silence_started_at) >= self.policy.proactive_delay_seconds

    def dispatch(self, state: ConversationState, event: ConversationEvent, now: float | None = None) -> list[ConversationAction]:
        actions: list[ConversationAction] = []

        if event.type is ConversationEventType.START:
            state.started_at = now
            state.silence_started_at = now
            self._transition(state, ConversationPhase.LISTENING, now)
            actions.append(ConversationAction(ConversationActionType.ENTER_LISTENING))
            return actions

        if event.type is ConversationEventType.STOP_REQUESTED:
            self._transition(state, ConversationPhase.STOPPED, now)
            actions.append(ConversationAction(ConversationActionType.STOP_TTS))
            actions.append(ConversationAction(ConversationActionType.STOP_STREAM))
            return actions

        if state.phase is ConversationPhase.LISTENING:
            if event.type is ConversationEventType.INTERACTION_STATUS:
                status = str(event.payload.get("status", "") or "")
                state.last_status = status or None
                if status == "push_to_talk":
                    actions.append(ConversationAction(ConversationActionType.CAPTURE_PUSH_TO_TALK))
                elif status == "barge_in":
                    actions.append(ConversationAction(ConversationActionType.CAPTURE_VOICE))
                elif status == "skip_speech":
                    state.is_proactive_turn = True
                    state.skip_input_history_append = False
                    state.pending_user_text = "You continue speaking."
                    self._transition(state, ConversationPhase.THINKING, now)
                    actions.append(ConversationAction(ConversationActionType.GENERATE_PROACTIVE_TURN))
                    actions.append(ConversationAction(ConversationActionType.ENTER_THINKING, {"proactive": True}))
                elif status == "skip_user_reply":
                    state.is_proactive_turn = False
                    state.proactive_placeholder_role = None
                    state.preserve_proactive_placeholder = False
                    state.skip_input_history_append = True
                    state.pending_user_text = ""
                    self._transition(state, ConversationPhase.THINKING, now)
                    actions.append(ConversationAction(ConversationActionType.ENTER_THINKING, {"proactive": False, "assistant_continuation": True}))
                elif status == "regenerate_response":
                    actions.append(ConversationAction(ConversationActionType.POP_LAST_HISTORY, {"assistant_only": True}))
                elif status == "retry_user_input":
                    state.silence_started_at = now
                    actions.append(ConversationAction(ConversationActionType.RESET_SILENCE_TIMER))
                elif status == "pause_speech":
                    self._transition(state, ConversationPhase.PAUSED, now)
                    actions.append(ConversationAction(ConversationActionType.ENTER_PAUSED))
                return actions

            if event.type is ConversationEventType.USER_TEXT_CAPTURED:
                text = str(event.payload.get("text", "") or "").strip()
                if not text:
                    state.silence_started_at = now
                    actions.append(ConversationAction(ConversationActionType.RESET_SILENCE_TIMER))
                    return actions
                state.pending_user_text = text
                state.is_proactive_turn = False
                state.skip_input_history_append = False
                state.has_real_user_turn = True
                self._transition(state, ConversationPhase.THINKING, now)
                actions.append(ConversationAction(ConversationActionType.ENTER_THINKING, {"proactive": False, "text": text}))
                return actions

            if event.type is ConversationEventType.PROACTIVE_TIMEOUT:
                if self.proactive_allowed(state):
                    state.pending_user_text = "You continue speaking."
                    state.is_proactive_turn = True
                    state.skip_input_history_append = False
                    self._transition(state, ConversationPhase.THINKING, now)
                    actions.append(ConversationAction(ConversationActionType.GENERATE_PROACTIVE_TURN))
                    actions.append(ConversationAction(ConversationActionType.ENTER_THINKING, {"proactive": True}))
                return actions

        if state.phase is ConversationPhase.THINKING:
            if event.type is ConversationEventType.THINKING_STARTED:
                user_text = str(state.pending_user_text or "").strip()
                if state.is_proactive_turn:
                    state.proactive_placeholder_role = "user"
                    state.preserve_proactive_placeholder = True
                elif not state.skip_input_history_append:
                    actions.append(ConversationAction(ConversationActionType.APPEND_HISTORY, {"role": self.policy.input_message_role, "content": user_text}))
                if self.policy.stream_mode:
                    state.stream_active = True
                    actions.append(ConversationAction(ConversationActionType.START_LLM_STREAM, {"text": user_text, "proactive": state.is_proactive_turn}))
                else:
                    actions.append(ConversationAction(ConversationActionType.START_LLM_REQUEST, {"text": user_text, "proactive": state.is_proactive_turn}))
                return actions

            if event.type is ConversationEventType.STREAM_REPLY_STARTED:
                state.stream_active = True
                self._transition(state, ConversationPhase.SPEAKING, now)
                actions.append(ConversationAction(ConversationActionType.ENTER_SPEAKING, {"text": "", "stream": True}))
                return actions

            if event.type is ConversationEventType.ASSISTANT_REPLY_READY:
                text = str(event.payload.get("text", "") or "").strip()
                state.pending_assistant_text = text or None
                self._transition(state, ConversationPhase.SPEAKING, now)
                actions.append(ConversationAction(ConversationActionType.ENTER_SPEAKING, {"text": text, "stream": state.stream_active}))
                actions.append(ConversationAction(ConversationActionType.START_TTS, {"text": text, "stream": state.stream_active}))
                if state.is_proactive_turn and not state.preserve_proactive_placeholder:
                    actions.append(ConversationAction(ConversationActionType.POP_LAST_HISTORY, {"content": state.pending_user_text}))
                return actions

            if event.type is ConversationEventType.ASSISTANT_REPLY_EMPTY:
                state.pending_user_text = None
                state.pending_assistant_text = None
                state.stream_active = False
                state.skip_input_history_append = False
                self._transition(state, ConversationPhase.LISTENING, now)
                state.silence_started_at = now
                actions.append(ConversationAction(ConversationActionType.RESET_SILENCE_TIMER))
                actions.append(ConversationAction(ConversationActionType.ENTER_LISTENING))
                return actions

        # A whole-response skip/cancel can finish speech while still paused.
        # Finalize that turn normally so subsequent input/regeneration is admitted.
        if state.phase is ConversationPhase.SPEAKING or (
            state.phase is ConversationPhase.PAUSED
            and event.type is ConversationEventType.SPEAKING_FINISHED
        ):
            if event.type is ConversationEventType.ASSISTANT_REPLY_READY:
                text = str(event.payload.get("text", "") or "").strip()
                state.pending_assistant_text = text or state.pending_assistant_text
                if state.is_proactive_turn and not state.preserve_proactive_placeholder:
                    actions.append(ConversationAction(ConversationActionType.POP_LAST_HISTORY, {"content": state.pending_user_text}))
                return actions

            if event.type is ConversationEventType.SPEAKING_FINISHED:
                state.pending_user_text = None
                state.pending_assistant_text = None
                state.stream_active = False
                state.assistant_history_added = False
                state.discard_assistant_history = False
                state.skip_input_history_append = False
                self._transition(state, ConversationPhase.LISTENING, now)
                state.silence_started_at = now
                actions.append(ConversationAction(ConversationActionType.FINALIZE_REPLY))
                actions.append(ConversationAction(ConversationActionType.RESET_SILENCE_TIMER))
                actions.append(ConversationAction(ConversationActionType.ENTER_LISTENING))
                return actions

            if event.type is ConversationEventType.BARGE_IN_CAPTURED:
                text = str(event.payload.get("text", "") or "").strip()
                state.was_barge_in = True
                state.pending_user_text = text or None
                state.is_proactive_turn = False
                state.proactive_placeholder_role = None
                state.preserve_proactive_placeholder = False
                state.stream_active = False
                state.discard_assistant_history = True
                state.skip_input_history_append = False
                self._transition(state, ConversationPhase.THINKING, now)
                actions.append(ConversationAction(ConversationActionType.STOP_TTS))
                actions.append(ConversationAction(ConversationActionType.STOP_STREAM))
                actions.append(ConversationAction(ConversationActionType.ENTER_THINKING, {"proactive": False, "text": text, "barge_in": True}))
                return actions

            if event.type is ConversationEventType.PAUSE_TOGGLED:
                self._transition(state, ConversationPhase.PAUSED, now)
                actions.append(ConversationAction(ConversationActionType.ENTER_PAUSED))
                return actions

        if state.phase is ConversationPhase.PAUSED:
            if event.type is ConversationEventType.PAUSE_TOGGLED:
                prior = ConversationPhase.SPEAKING if state.pending_assistant_text else ConversationPhase.LISTENING
                self._transition(state, prior, now)
                actions.append(ConversationAction(ConversationActionType.NOOP, {"resumed_to": prior.value}))
                return actions

        if event.type is ConversationEventType.ERROR:
            state.last_error = str(event.payload.get("error", "") or "Unknown error")
            actions.append(ConversationAction(ConversationActionType.MARK_ERROR, {"error": state.last_error}))
            return actions

        actions.append(ConversationAction(ConversationActionType.NOOP))
        return actions


@dataclass(slots=True)
class ConversationController:
    """State-machine owner and the sole production conversation orchestrator."""

    policy: ConversationPolicy
    runtime: ConversationRuntime
    turns: TurnCoordinatorPort | None = None
    memory: LegacyMemoryEffects | None = None
    speech: LegacySpeechEffects | None = None
    avatar: LegacyAvatarEffects | None = None
    sensory: SensoryService | None = None
    proactive: ProactiveService | None = None
    interaction: InteractionService | None = None
    replay: ReplayService | None = None
    production_services: ProductionConversationServices | None = None
    state: ConversationState = field(default_factory=ConversationState)
    machine: ConversationStateMachine = field(init=False)

    def __post_init__(self) -> None:
        self.machine = ConversationStateMachine(self.policy)

    def start(self) -> list[ConversationAction]:
        now = self.runtime.now()
        return self.machine.dispatch(self.state, ConversationEvent(ConversationEventType.START), now=now)

    def stop(self) -> list[ConversationAction]:
        now = self.runtime.now()
        return self.machine.dispatch(self.state, ConversationEvent(ConversationEventType.STOP_REQUESTED), now=now)

    def on_interaction_status(self, status: str) -> list[ConversationAction]:
        now = self.runtime.now()
        return self.machine.dispatch(
            self.state,
            ConversationEvent(ConversationEventType.INTERACTION_STATUS, {"status": status}),
            now=now,
        )

    def on_user_text(self, text: str | None) -> list[ConversationAction]:
        now = self.runtime.now()
        event_type = ConversationEventType.USER_TEXT_CAPTURED if (text and str(text).strip()) else ConversationEventType.USER_TEXT_EMPTY
        return self.machine.dispatch(self.state, ConversationEvent(event_type, {"text": text or ""}), now=now)

    def on_proactive_timeout(self) -> list[ConversationAction]:
        now = self.runtime.now()
        return self.machine.dispatch(self.state, ConversationEvent(ConversationEventType.PROACTIVE_TIMEOUT), now=now)

    def on_thinking_started(self) -> list[ConversationAction]:
        now = self.runtime.now()
        return self.machine.dispatch(self.state, ConversationEvent(ConversationEventType.THINKING_STARTED), now=now)

    def on_stream_started(self) -> list[ConversationAction]:
        now = self.runtime.now()
        return self.machine.dispatch(self.state, ConversationEvent(ConversationEventType.STREAM_REPLY_STARTED), now=now)

    def on_assistant_reply(self, text: str | None) -> list[ConversationAction]:
        now = self.runtime.now()
        if text and str(text).strip():
            return self.machine.dispatch(
                self.state,
                ConversationEvent(ConversationEventType.ASSISTANT_REPLY_READY, {"text": text}),
                now=now,
            )
        return self.machine.dispatch(self.state, ConversationEvent(ConversationEventType.ASSISTANT_REPLY_EMPTY), now=now)

    def on_speaking_finished(self) -> list[ConversationAction]:
        now = self.runtime.now()
        return self.machine.dispatch(self.state, ConversationEvent(ConversationEventType.SPEAKING_FINISHED), now=now)

    def on_barge_in_text(self, text: str | None) -> list[ConversationAction]:
        now = self.runtime.now()
        return self.machine.dispatch(
            self.state,
            ConversationEvent(ConversationEventType.BARGE_IN_CAPTURED, {"text": text or ""}),
            now=now,
        )

    def on_pause_toggled(self) -> list[ConversationAction]:
        now = self.runtime.now()
        return self.machine.dispatch(self.state, ConversationEvent(ConversationEventType.PAUSE_TOGGLED), now=now)

    def tick(self) -> list[ConversationAction]:
        """Future timing seam.

        For now this only checks whether proactive timeout is due while listening.
        The legacy loop can call this opportunistically once we start shadowing it.
        """
        now = self.runtime.now()
        if self.state.phase is ConversationPhase.LISTENING and self.machine.proactive_due(self.state, now):
            return self.on_proactive_timeout()
        return [ConversationAction(ConversationActionType.NOOP)]

    @_with_phone_reply_owner
    def run_production(
        self,
        source,
        *,
        services: ProductionConversationServices | None = None,
        options: ProductionRunOptions | None = None,
    ):
        production = services or self.production_services
        if production is None:
            production = _legacy_production_services(
                memory=self.memory,
                speech=self.speech,
                avatar=self.avatar,
                sensory=self.sensory,
                proactive=self.proactive,
                interaction=self.interaction,
                replay=self.replay,
            )
        if production is None or production.missing_domains():
            raise RuntimeError("Production conversation services are not completely composed.")

        session = production.session
        history = production.history
        user_images = production.user_images
        normal_chat = production.normal_chat
        control = production.control
        speech_input = production.speech_input
        speech_output = production.speech_output
        dry_run = production.dry_run
        addons = production.addons
        presence = production.presence
        sensory = production.sensory
        proactive = production.proactive
        interaction = production.interaction
        replay = production.replay
        phone_controls = production.phone_reply_controls
        phone_scope = None
        phone_speech = None
        phone_input_pending = False
        phone_acceptance_serial = phone_controls.accepted_turn_serial if phone_controls is not None else 0
        scoped_actions = production.conversation_actions
        scoped_action = None
        scoped_prepared = None
        phone_retry_waiting = False

        def _drain_phone_controls():
            nonlocal phone_input_pending, phone_acceptance_serial
            if phone_controls is not None:
                phone_controls.drain()
                if phone_controls.accepted_turn_serial != phone_acceptance_serial:
                    phone_acceptance_serial = phone_controls.accepted_turn_serial
                    phone_input_pending = True

        def _phone_held():
            return phone_controls is not None and phone_controls.is_held(phone_scope)

        def _phone_interrupted():
            return phone_controls is not None and phone_controls.is_interrupted(phone_scope)

        def _phone_playback_pending():
            return phone_controls is not None and phone_controls.is_playback_pending(phone_scope)

        def _drain_phone_finalizer(*, producer_done=None):
            _drain_phone_controls()
            # A hold admitted at the terminal boundary keeps the captured full
            # result alive until transcript/abandon/lease expiry settles it.
            while (_phone_held() or _phone_playback_pending()) and not stop_flag.is_set():
                if producer_done is not None and producer_done():
                    phone_controls.producer_finished(phone_scope)
                _drain_phone_controls()
                if not (_phone_held() or _phone_playback_pending()):
                    break

                def _stop_remote_playback(_dispatch):
                    phone_controls.request_playback_stop(phone_scope)
                    return InteractionEffectResult()

                _dispatch_interaction(
                    check_interaction_status(source),
                    InteractionPhase.SPEAKING,
                    effects=InteractionCommandCapabilities(
                        skip_speech=_stop_remote_playback,
                    ),
                )
                time.sleep(0.02)

        _live_config = session.live_config
        _history_snapshot = history.history_snapshot
        _history_has_role = history.history_has_role
        _discard_last_exchange_for_retry = history.discard_last_exchange_for_retry
        _prepare_regeneration_turn = history.prepare_regeneration_turn
        REQUEST_ONLY_CONTINUATION_CUE = history.request_only_continuation_cue
        _pending_user_image_attachment = user_images.pending_user_image_attachment
        _record_interrupted_assistant = history.record_interrupted_assistant
        _session_lease = session.session_lease
        _consume_pending_loaded_input_turn = session.consume_pending_loaded_input_turn
        _reconstruct_input_turn = session.reconstruct_input_turn
        _request_chat_view_rebuild = session.request_chat_view_rebuild
        _prune_normal_chat_transactions = session.prune_normal_chat_transactions
        _maybe_arm_screen_image_for_user_turn = user_images.maybe_arm_screen_image_for_user_turn
        _attach_pending_user_image_to_turn = user_images.attach_pending_user_image_to_turn
        clear_pending_user_image_attachment = user_images.clear_pending_user_image_attachment
        _begin_normal_chat_transaction = normal_chat.begin
        _freeze_normal_chat_request = normal_chat.freeze_request
        _ensure_normal_chat_transaction_ready = normal_chat.ensure_ready
        _normal_chat_reply_source_meta = normal_chat.reply_source_metadata
        _cancel_normal_chat_request = normal_chat.cancel_request
        _complete_normal_chat_transaction = normal_chat.complete
        _normal_chat_transaction_for_request = normal_chat.transaction_for_request
        _append_assistant_history_turn = history.append_assistant_history_turn
        _apply_stored_chat_history_limit = history.apply_stored_chat_history_limit
        _pop_last_proactive_placeholder = history.pop_last_proactive_placeholder
        _display_input_turn_content = session.display_input_turn_content
        maybe_start_continuity_memory_auto_update = history.maybe_start_continuity_memory_auto_update
        maybe_start_long_term_memory_auto_archive = history.maybe_start_long_term_memory_auto_archive

        controls = control.controls
        stop_flag = controls.stop
        CONTINUE_ASSISTANT_SENTINEL = control.continue_assistant_sentinel
        check_interaction_status = control.check_interaction_status
        listen_for_speech = speech_input.listen_for_speech
        listen_for_speech_push_to_talk = speech_input.listen_for_speech_push_to_talk
        suppress_barge_in_until_quiet = getattr(
            speech_input, "suppress_barge_in_until_quiet", None
        )
        suppress_push_to_talk_until_release = getattr(
            interaction, "suppress_push_to_talk_until_release", None
        )
        transcript_is_current = speech_input.transcript_is_current
        _dry_run_auto_replies_enabled = dry_run.dry_run_auto_replies_enabled
        _next_dry_run_auto_reply = dry_run.next_dry_run_auto_reply
        _begin_dry_run_reply = dry_run.begin_dry_run_reply
        _finalize_dry_run_reply = dry_run.finalize_dry_run_reply
        _maybe_handle_addon_user_text_command = addons.maybe_handle_addon_user_text_command
        _maybe_handle_buddy_contextual_reply = addons.maybe_handle_buddy_contextual_reply
        _addon_voice_segments_stream_policy = addons.addon_voice_segments_stream_policy
        _prepare_low_latency_completed_tts_segments = speech_output.prepare_low_latency_completed_tts_segments
        prepare_assistant_reply = speech_output.prepare_assistant_reply
        publish_assistant_reply_effects = speech_output.publish_assistant_reply_effects
        chat_with_llm = normal_chat.reply
        start_streamed_llm_reply = normal_chat.start_stream
        speak_async = speech_output.speak_async
        speak_async_stream = speech_output.speak_async_stream
        set_seed = dry_run.set_seed
        listening_active = controls.listening
        microphone_active = controls.microphone
        audio_playing = controls.audio_playing
        stop_playback = controls.stop_playback
        manual_pause_active = controls.manual_pause
        pause_after_chunk = controls.pause_after_chunk
        playback_paused = controls.playback_paused
        NormalChatTurnBlocked = control.blocked_error

        def _published_speech_transcript(result) -> FinalTranscript | None:
            if isinstance(result, CommandResult):
                if not result.accepted:
                    return None
                result = result.value
            if result is None:
                return None
            if not isinstance(result, FinalTranscript):
                return None
            if not transcript_is_current(result):
                return None
            return result

        def _dispatch_interaction(
            value,
            phase: InteractionPhase,
            *,
            effects: InteractionCommandCapabilities | None = None,
        ) -> InteractionDispatch | None:
            nonlocal scoped_action, phone_retry_waiting
            if value is None:
                return None
            command = value
            if not isinstance(command, InteractionCommand):
                try:
                    command = InteractionCommand(
                        str(value or "").strip(),
                        source="conversation_compatibility",
                    )
                except ValueError:
                    return None
            if (command.action == 'regenerate_response'
                    and phase is InteractionPhase.SPEAKING
                    and scoped_actions is not None and _phone_playback_pending()):
                # The local stop flag cannot retire a phone speaker. Use the
                # same exact-target/ACK handoff as mobile conversation actions,
                # with the default local destination for this PC request.
                target = scoped_actions.snapshot().get('regenerate')
                if target is not None:
                    scoped_actions.submit(ConversationActionRequest(
                        uuid4().hex, 'regenerate', ConversationActionTarget(**target)))
                return InteractionDispatch(InteractionIntent.REGENERATE, command, phase,
                    InteractionEffectResult())
            if command.action == 'conversation_action':
                if scoped_actions is None:
                    return None
                if phase is InteractionPhase.REPLAY:
                    scoped_actions.set_phase('replay')
                claimed = scoped_actions.claim(command.payload.get('operation_id'))
                if claimed is not None:
                    scoped_action = claimed
                    if phone_scope is not None and phone_controls is not None:
                        phone_controls.request_playback_stop(phone_scope)
                return InteractionDispatch(InteractionIntent.CONVERSATION_ACTION, command, phase,
                    InteractionEffectResult(InteractionFlow.BREAK if claimed is not None and phase is InteractionPhase.LISTENING else InteractionFlow.STAY))
            if phone_retry_waiting and command.action in {'barge_in', 'hidden_proactive_reply', 'proactive_timeout'}:
                return None
            if command.action == 'push_to_talk':
                phone_retry_waiting = False
            dispatched = interaction.dispatch(
                command,
                phase=phase,
                effects=effects,
            )
            if not dispatched.accepted:
                failure = dispatched.failure
                print(
                    "[Interaction] Handler dispatch failed: "
                    + (
                        failure.message
                        if failure is not None
                        else command.action
                    )
                )
                return None
            return (
                dispatched.value
                if isinstance(dispatched.value, InteractionDispatch)
                else None
            )

        def _schedule_proactive(
            *,
            action="proactive_timeout",
            silence_seconds=0.0,
            metadata=None,
        ):
            current = proactive.current_candidate()
            if (
                current is not None
                and current.lease == _session_lease()
                and current.action == action
            ):
                return CommandResult(True, current)
            return proactive.schedule(
                _session_lease(),
                silence_seconds=silence_seconds,
                metadata=dict(metadata or {}),
                action=action,
            )

        def _accept_proactive(command, *, action, metadata=None):
            candidate_id = ""
            if isinstance(command, InteractionCommand):
                candidate_id = str(command.payload.get("candidate_id", "") or "")
            if not candidate_id:
                scheduled = proactive.schedule(
                    _session_lease(),
                    silence_seconds=0.0,
                    metadata=dict(metadata or {}),
                    action=action,
                )
                if not scheduled.accepted or scheduled.value is None:
                    return CommandResult(False, failure=scheduled.failure)
                fired = proactive.fire(scheduled.value.candidate_id)
                if not fired.accepted:
                    return CommandResult(False, failure=fired.failure)
                candidate_id = scheduled.value.candidate_id
            return proactive.accept(candidate_id)

        _presence_set_state = presence.set_state
        _presence_set_audio_level = presence.set_audio_level

        _hidden_sensory_proactive_speech_allowed = sensory.hidden_proactive_speech_allowed
        _current_pending_hidden_proactive_candidate = sensory.current_pending_proactive_candidate
        _consume_hidden_proactive_candidate = sensory.consume_hidden_proactive_candidate
        _clear_pending_hidden_proactive_candidate = sensory.clear_pending_hidden_proactive_candidate
        _clear_active_hidden_proactive_candidate = sensory.clear_active_hidden_proactive_candidate
        _buddy_contextual_payload_from_hidden_proactive = sensory.buddy_contextual_payload_from_hidden_proactive
        _log_companion_orb_debug_event = sensory.log_companion_orb_debug_event
        live_config = _live_config()
        print(f"🧠 Brain Loaded: {live_config['model_name']}")

        user_text = None
        speech_transcript = None
        resumed_loaded_turn = None
        response_text = None
        active_replay_id = ""
        stream_state = None
        active_ctrl = None
        assistant_history_added = False
        discard_assistant_history = False
        accepted_proactive_turn = None
        regenerating = False
        regeneration_attempt = False
        regeneration_rebuild_pending = False
        proactive_request_pending = False
        request_only_continue_cue_pending = False
        regeneration_target_in_history = False
        regeneration_accepted_input = None
        regeneration_reuses_edited_input = False
        conversation_controller = self
        conversation_controller.policy = ConversationPolicy.from_runtime_config(
            live_config
        )
        conversation_controller.machine = ConversationStateMachine(
            conversation_controller.policy
        )
        conversation_controller.start()
        conversation_controller.state.has_real_user_turn = any(
            str(item.get("role", "") or "") == "user"
            for item in _history_snapshot()
        )
        known_chat_session_state_generation = int(session.session_generation() or 0)
        generation_handoff_turn: tuple[int, InputTurn] | None = None

        def _start_replay_action(
            action,
            *,
            defer=False,
        ) -> CommandResult[ReplayReceipt]:
            if action == "replay_last_assistant":
                result = (
                    replay.stage_latest_assistant()
                    if defer
                    else replay.replay_latest_assistant()
                )
                if result.accepted:
                    print("\n🔁 Replaying latest assistant reply...")
                else:
                    print("\n⚠️ No assistant reply available to replay yet.")
                return result
            start_index = 1 if action == "replay_chat_session" else (
                runtime_hotkeys.parse_replay_chat_session_start_index(action)
            )
            if start_index is None:
                return CommandResult(False)
            result = (
                replay.stage_chat_session(start_index=start_index)
                if defer
                else replay.replay_chat_session(start_index=start_index)
            )
            if not result.accepted or result.value is None:
                print("\n⚠️ No replayable chat messages are available in the current chat context.")
                return result
            first = result.value.replay_indices[0]
            total = result.value.replay_indices[-1]
            if first <= 1:
                print(f"\n🔁 Replaying chat session ({total} message(s))...")
            else:
                print(f"\n🔁 Replaying chat session from message {first}/{total}...")
            return result

        def _plan_phase2_actions(current_user_text, input_role_override=None, *, proactive_request=False):
            current_config = _live_config()
            conversation_controller.policy = conversation_controller.machine.policy = ConversationPolicy.from_runtime_config(current_config)
            override_role = str(input_role_override or "").strip().lower()
            if override_role in {"user", "system", "assistant"}:
                conversation_controller.policy.input_message_role = override_role
                conversation_controller.machine.policy.input_message_role = override_role
            if str(current_user_text or "") == CONTINUE_ASSISTANT_SENTINEL:
                actions = conversation_controller.on_interaction_status("skip_user_reply")
            elif bool(proactive_request):
                actions = conversation_controller.on_interaction_status("skip_speech")
            else:
                actions = conversation_controller.on_user_text(current_user_text)
            actions.extend(conversation_controller.on_thinking_started())
            return actions

        def _normalize_assistant_continuation(text: str | None) -> str:
            candidate = str(text or "").strip()
            if user_text != CONTINUE_ASSISTANT_SENTINEL:
                return candidate
            normalized = _trim_assistant_continuation_history_prefix(
                    _history_snapshot(),
                    candidate,
                )
            if candidate and not normalized:
                print(
                    "⚠️ [Normal Chat] Ignored assistant continuation that "
                    "exactly repeated the current assistant message."
                )
            elif normalized != candidate:
                print(
                    "ℹ️ [Normal Chat] Removed the repeated assistant-context "
                    "prefix from the continuation."
                )
            return normalized

        def _resume_generation_handoff(
            handoff: tuple[int, InputTurn] | None,
            current_generation: int,
        ) -> InputTurn | None:
            if handoff is None or handoff[0] != current_generation:
                return None
            turn = handoff[1]
            transaction_id = str(
                turn.get("normal_chat_transaction_id", "") or ""
            )
            if not transaction_id:
                return turn
            transaction = _normal_chat_transaction_for_request(turn)
            transaction_generation = None
            if isinstance(transaction, Mapping):
                raw_generation = transaction.get("session_generation")
                if raw_generation is None:
                    snapshot = transaction.get("turn_snapshot")
                    lease = getattr(snapshot, "lease", None)
                    raw_generation = getattr(
                        getattr(lease, "session_generation", None),
                        "value",
                        None,
                    )
                if raw_generation is not None:
                    transaction_generation = int(raw_generation)
            if transaction_generation == current_generation:
                return turn

            # The UI can submit immediately after announcing a reset while the
            # runtime reset is still advancing its generation. Re-accept that
            # exact input in the new generation instead of reviving its stale
            # transaction or silently dropping the user's text.
            replacement = dict(turn)
            replacement.pop("normal_chat_transaction_id", None)
            return _begin_normal_chat_transaction(replacement)

        resumed_loaded_turn = _consume_pending_loaded_input_turn()
        if resumed_loaded_turn:
            consumed_turn_generation = int(session.session_generation() or 0)
            if consumed_turn_generation != known_chat_session_state_generation:
                generation_handoff_turn = (
                    consumed_turn_generation,
                    resumed_loaded_turn,
                )
                resumed_loaded_turn = None
        if resumed_loaded_turn:
            user_text = str(resumed_loaded_turn.get("content", "") or "")
            proactive_request_pending = False
            request_only_continue_cue_pending = False
            print("📚 [Session] Resuming loaded input turn immediately...")

        run_options = options or ProductionRunOptions()

        loop_iterations = 0
        while not stop_flag.is_set():
            if (
                run_options.max_loop_iterations is not None
                and loop_iterations >= run_options.max_loop_iterations
            ):
                break
            loop_iterations += 1
            current_chat_session_state_generation = int(session.session_generation() or 0)
            _drain_phone_controls()
            if current_chat_session_state_generation != known_chat_session_state_generation:
                live_config = _live_config()
                conversation_controller.policy = ConversationPolicy.from_runtime_config(
                    live_config
                )
                conversation_controller.state = ConversationState()
                conversation_controller.machine = ConversationStateMachine(
                    conversation_controller.policy
                )
                conversation_controller.start()
                conversation_controller.state.has_real_user_turn = any(
                    str(item.get("role", "") or "") == "user"
                    for item in _history_snapshot()
                )
                known_chat_session_state_generation = current_chat_session_state_generation
                regenerating = False
                regeneration_attempt = False
                regeneration_rebuild_pending = False
                proactive_request_pending = False
                request_only_continue_cue_pending = False
                regeneration_target_in_history = False
                regeneration_accepted_input = None
                regeneration_reuses_edited_input = False
                user_text = None
                speech_transcript = None
                response_text = None
                if active_replay_id:
                    replay.cancel(active_replay_id, reason="session_reset")
                    active_replay_id = ""
                proactive.cancel("session_reset")
                accepted_proactive_turn = None
                stream_state = None
                stream_reply_finalized = False
                active_ctrl = None
                assistant_history_added = False
                discard_assistant_history = False
                handoff = generation_handoff_turn
                generation_handoff_turn = None
                resumed_loaded_turn = _resume_generation_handoff(
                    handoff,
                    current_chat_session_state_generation,
                )
                if resumed_loaded_turn is None:
                    resumed_loaded_turn = _consume_pending_loaded_input_turn()
                if resumed_loaded_turn:
                    user_text = str(resumed_loaded_turn.get("content", "") or "")
                    proactive_request_pending = False
                    request_only_continue_cue_pending = False
                    print("📚 [Session] Resuming loaded input turn immediately...")
            dry_run_reply_id = None
            normal_chat_request = None
            phone_scope = None
            phone_speech = None
            response_capture_id = ""
            reply_source_meta = {}
            turn_execution_policy = None
            prepared_reply = None
            hidden_proactive_request = None

            if scoped_action is not None and scoped_actions is not None:
                scoped_actions.set_phase('idle')
                pending_action = scoped_action
                scoped_action = None
                # The previous speech route kept these locals for legacy
                # regeneration. Scoped Retry/rejection must never resend them.
                user_text = None
                response_text = None
                resumed_loaded_turn = None
                speech_transcript = None
                scoped_prepared = scoped_actions.execute(pending_action)
                regenerating = False
                if scoped_prepared is not None:
                    resumed_loaded_turn, _request = scoped_prepared
                    user_text = str(resumed_loaded_turn.get('content') or 'Please respond to the image I just sent you.')
                    request_only_continue_cue_pending = False
                    proactive_request_pending = False
                elif pending_action.kind == 'retry' and scoped_actions.accepted(pending_action.operation_id):
                    phone_retry_waiting = pending_action.input_owner == 'phone'

            # =================================================================================
            # PHASE 1: LISTENING
            # =================================================================================
            if not user_text and not regenerating and not response_text and not active_replay_id:
                if scoped_actions is not None:
                    scoped_actions.set_phase('idle')
                live_config = _live_config()
                if bool(live_config.get("offline_replay_only", False)) and interaction.pending_count() == 0:
                    print("🔁 Offline replay complete.")
                    stop_flag.set()
                    break
                allow_proactive_replies = bool(live_config.get("allow_proactive_replies", False)) and not phone_retry_waiting
                require_first_user_before_proactive = bool(live_config.get("require_first_user_before_proactive", False))
                hidden_proactive_request = _current_pending_hidden_proactive_candidate()
                if not phone_retry_waiting and hidden_proactive_request and _hidden_sensory_proactive_speech_allowed():
                    if not require_first_user_before_proactive or _history_has_role("user"):
                        scheduled = _schedule_proactive(
                            action="hidden_proactive_reply",
                            silence_seconds=0.0,
                            metadata=dict(hidden_proactive_request),
                        )
                        if scheduled.accepted and scheduled.value is not None:
                            proactive.fire(scheduled.value.candidate_id)
                if _dry_run_auto_replies_enabled():
                    generated_prompt = _next_dry_run_auto_reply()
                    if generated_prompt:
                        print(f"🧪 [DryRun] Auto prompt: {generated_prompt}")
                        user_text = generated_prompt
                        proactive_request_pending = False
                        request_only_continue_cue_pending = False
                        listening_active.clear()
                        proactive.cancel("dry_run_input")
                        continue
                listening_active.set()
                print("👂 Waiting for voice...")
                listen_idle_window_seconds = max(0.5, float(live_config.get("listen_idle_window_seconds", 5.0) or 5.0))
                proactive_delay_seconds = max(0.5, float(live_config.get("proactive_delay_seconds", 10.0) or 10.0))
                if allow_proactive_replies and (
                    not require_first_user_before_proactive or _history_has_role("user")
                ):
                    _schedule_proactive(silence_seconds=proactive_delay_seconds)
                else:
                    proactive.cancel("proactive_disabled")
                start_wait = time.time()
                started_talking = False
                capture_push_to_talk = False
                force_proactive_reply = False
                session_generation_handoff = False

                while time.time() - start_wait < listen_idle_window_seconds:
                    if stop_flag.is_set():
                        break
                    if (
                        int(session.session_generation() or 0)
                        != known_chat_session_state_generation
                    ):
                        session_generation_handoff = True
                        break
                    _drain_phone_controls()
                    queued_loaded_turn = _consume_pending_loaded_input_turn()
                    if queued_loaded_turn:
                        phone_retry_waiting = False
                        phone_input_pending = False
                        if (
                            int(session.session_generation() or 0)
                            != known_chat_session_state_generation
                        ):
                            generation_handoff_turn = (
                                int(session.session_generation() or 0),
                                queued_loaded_turn,
                            )
                            session_generation_handoff = True
                            break
                        print("\n📋 [Session] Immediate queued input turn detected. Processing now...")
                        user_text = str(queued_loaded_turn.get("content", "") or "")
                        resumed_loaded_turn = queued_loaded_turn
                        proactive_request_pending = False
                        request_only_continue_cue_pending = False
                        proactive.cancel("queued_user_input")
                        listening_active.clear()
                        break
                    hidden_proactive_request = _current_pending_hidden_proactive_candidate()
                    if not phone_retry_waiting and hidden_proactive_request and _hidden_sensory_proactive_speech_allowed():
                        if not require_first_user_before_proactive or _history_has_role("user"):
                            scheduled = _schedule_proactive(
                                action="hidden_proactive_reply",
                                silence_seconds=0.0,
                                metadata=dict(hidden_proactive_request),
                            )
                            if scheduled.accepted and scheduled.value is not None:
                                proactive.fire(scheduled.value.candidate_id)
                    def _queue_assistant_continuation(message):
                        nonlocal user_text, proactive_request_pending
                        nonlocal request_only_continue_cue_pending
                        print(message)
                        user_text = CONTINUE_ASSISTANT_SENTINEL
                        proactive_request_pending = False
                        request_only_continue_cue_pending = False
                        proactive.cancel("assistant_continuation")
                        return InteractionEffectResult(InteractionFlow.BREAK)

                    def _regenerate(_dispatch):
                        nonlocal regeneration_target_in_history, regenerating
                        history = _history_snapshot()
                        tail = history[-1] if history else {}
                        tail_role = str(tail.get("role", "") or "").strip().lower()
                        if tail_role == "user":
                            return _queue_assistant_continuation(
                                "\n⏭️ Regenerate on user-ended context "
                                "(Assistant continuation)..."
                            )
                        proactive.cancel("regenerate")
                        print("\n🎲 Regenerating last response...")
                        regeneration_target_in_history = True
                        regenerating = True
                        return InteractionEffectResult(InteractionFlow.BREAK)

                    def _accept_listening_proactive(dispatch):
                        nonlocal hidden_proactive_request, user_text
                        nonlocal accepted_proactive_turn, proactive_request_pending
                        nonlocal request_only_continue_cue_pending
                        if dispatch.action == "hidden_proactive_reply":
                            hidden_proactive_request = _consume_hidden_proactive_candidate()
                            if not hidden_proactive_request:
                                # Cancellation can invalidate an already queued wake-up.
                                # Do not create a continuation turn without its evidence.
                                proactive.cancel("stale_hidden_proactive")
                                return InteractionEffectResult(InteractionFlow.CONTINUE)
                            accepted = _accept_proactive(
                                dispatch.command,
                                action="hidden_proactive_reply",
                                metadata=dict(hidden_proactive_request or {}),
                            )
                            if accepted.accepted and accepted.value is not None:
                                print("\n[Sensory] Hidden PONG wake-up consumed.")
                                user_text = "You continue speaking."
                                accepted_proactive_turn = accepted.value
                                proactive_request_pending = True
                                request_only_continue_cue_pending = True
                                listening_active.clear()
                                _log_companion_orb_debug_event(
                                    "engine_hidden_proactive_wake_consumed",
                                    trace_id=str(hidden_proactive_request.get("trace_id") or ""),
                                    candidate=str(hidden_proactive_request.get("candidate") or "")[:220],
                                    source=str(hidden_proactive_request.get("source") or ""),
                                )
                                return InteractionEffectResult(InteractionFlow.BREAK)
                            return InteractionEffectResult(InteractionFlow.CONTINUE)
                        accepted = _accept_proactive(
                            dispatch.command,
                            action="proactive_timeout",
                        )
                        if accepted.accepted and accepted.value is not None:
                            print("\n🤖 AI Decided to speak first...")
                            user_text = "You continue speaking."
                            accepted_proactive_turn = accepted.value
                            proactive_request_pending = True
                            request_only_continue_cue_pending = True
                            listening_active.clear()
                            return InteractionEffectResult(InteractionFlow.BREAK)
                        return InteractionEffectResult(InteractionFlow.CONTINUE)

                    def _retry_input(_dispatch):
                        nonlocal start_wait
                        proactive.cancel("retry_user_input")
                        if _discard_last_exchange_for_retry():
                            print("\nscrapped last input, listening again...")
                        else:
                            print("\n↺ Retrying listening...")
                        start_wait = time.time()
                        return InteractionEffectResult(InteractionFlow.CONTINUE)

                    def _capture_input(_dispatch, *, push_to_talk):
                        nonlocal started_talking, capture_push_to_talk
                        proactive.cancel("voice_input")
                        if scoped_actions is not None:
                            scoped_actions.set_phase('capture')
                        started_talking = True
                        capture_push_to_talk = bool(push_to_talk)
                        return InteractionEffectResult(InteractionFlow.BREAK)

                    def _force_proactive(dispatch):
                        nonlocal accepted_proactive_turn, force_proactive_reply
                        nonlocal proactive_request_pending, request_only_continue_cue_pending
                        print("\n⏭️ Skipping wait (Force Proactive)...")
                        accepted = _accept_proactive(
                            dispatch.command,
                            action="proactive_timeout",
                            metadata={"forced": True},
                        )
                        if accepted.accepted and accepted.value is not None:
                            accepted_proactive_turn = accepted.value
                            force_proactive_reply = True
                            proactive_request_pending = True
                            request_only_continue_cue_pending = True
                            return InteractionEffectResult(InteractionFlow.BREAK)
                        return InteractionEffectResult(InteractionFlow.CONTINUE)

                    def _continue_assistant(_dispatch):
                        return _queue_assistant_continuation(
                            "\n⏭️ Skipping user reply (Assistant continuation)..."
                        )

                    def _start_listening_replay(dispatch):
                        nonlocal active_replay_id, start_wait
                        started = _start_replay_action(dispatch.action)
                        if started.accepted and started.value is not None:
                            active_replay_id = started.value.replay_id
                            proactive.cancel("replay_started")
                            return InteractionEffectResult(InteractionFlow.BREAK)
                        start_wait = time.time()
                        return InteractionEffectResult(InteractionFlow.CONTINUE)

                    def _pause_listening(_dispatch):
                        nonlocal start_wait
                        listening_active.clear()
                        manual_pause_active.set()
                        print("- - - PAUSED - - -")

                        def _resume_listening(_paused_dispatch):
                            nonlocal start_wait
                            manual_pause_active.clear()
                            listening_active.set()
                            start_wait = time.time() + 3
                            print("- - - UNPAUSED - - -")
                            return InteractionEffectResult(InteractionFlow.BREAK)

                        while True:
                            time.sleep(1.0)
                            _drain_phone_controls()
                            paused_dispatch = _dispatch_interaction(
                                check_interaction_status(source),
                                InteractionPhase.LISTENING,
                                effects=InteractionCommandCapabilities(
                                    pause_listening=_resume_listening,
                                ),
                            )
                            if (
                                paused_dispatch is not None
                                and paused_dispatch.effect.flow
                                is InteractionFlow.BREAK
                            ):
                                break
                            time.sleep(0.2)
                        return InteractionEffectResult()

                    dispatched = _dispatch_interaction(
                        check_interaction_status(source),
                        InteractionPhase.LISTENING,
                        effects=InteractionCommandCapabilities(
                            regenerate=_regenerate,
                            retry_input=_retry_input,
                            pause_listening=_pause_listening,
                            force_proactive=_force_proactive,
                            continue_assistant=_continue_assistant,
                            start_replay=_start_listening_replay,
                            capture_voice=lambda dispatch: _capture_input(
                                dispatch,
                                push_to_talk=False,
                            ),
                            capture_push_to_talk=lambda dispatch: _capture_input(
                                dispatch,
                                push_to_talk=True,
                            ),
                            accept_proactive=_accept_listening_proactive,
                        ),
                    )
                    effect = (
                        dispatched.effect
                        if dispatched is not None
                        else InteractionEffectResult()
                    )
                    if effect.flow is InteractionFlow.BREAK:
                        break
                    if effect.flow is InteractionFlow.CONTINUE:
                        continue

                    if stop_flag.wait(0.05):
                        break

                if (
                    int(session.session_generation() or 0)
                    != known_chat_session_state_generation
                ):
                    if resumed_loaded_turn and user_text:
                        generation_handoff_turn = (
                            int(session.session_generation() or 0),
                            resumed_loaded_turn,
                        )
                    session_generation_handoff = True
                if session_generation_handoff:
                    listening_active.clear()
                    user_text = None
                    resumed_loaded_turn = None
                    continue

                if regenerating:
                    listening_active.clear()
                    pass
                elif started_talking:
                    listening_active.clear()
                    if capture_push_to_talk:
                        print("\n🎙️ Push-to-talk active. Recording...")
                        speech_transcript = _published_speech_transcript(
                            listen_for_speech_push_to_talk(source)
                        )
                    else:
                        print("\n🎤 Voice detected! Recording...")
                        speech_transcript = _published_speech_transcript(
                            listen_for_speech(source, timeout=0.6)
                        )
                    user_text = (
                        speech_transcript.text
                        if speech_transcript is not None
                        else None
                    )
                    proactive_request_pending = False
                    request_only_continue_cue_pending = False
                    proactive.cancel("voice_input")
                    if not user_text or not user_text.strip():
                        print("... False alarm")
                        user_text = None
                        speech_transcript = None
                        continue
                    _clear_pending_hidden_proactive_candidate()
                    _clear_active_hidden_proactive_candidate()
                elif (
                    user_text == CONTINUE_ASSISTANT_SENTINEL
                    or active_replay_id
                    or proactive_request_pending
                ):
                    listening_active.clear()
                    if proactive_request_pending and force_proactive_reply and not user_text:
                        print("\n🤖 Forced proactive reply...")
                        user_text = "You continue speaking."
                else:
                    listening_active.clear()
                    if force_proactive_reply:
                        print("\n🤖 Forced proactive reply...")
                        user_text = "You continue speaking."
                    else:
                        continue

            if regenerating:
                speech_transcript = None
                regeneration_history = _history_snapshot()
                regenerate_as_assistant_continuation = bool(
                    regeneration_target_in_history
                    and len(regeneration_history) >= 2
                    and str(
                        regeneration_history[-1].get("role", "") or ""
                    ).strip().lower()
                    == "assistant"
                    and str(
                        regeneration_history[-2].get("role", "") or ""
                    ).strip().lower()
                    == "assistant"
                )
                resumed_loaded_turn, _removed_target = _prepare_regeneration_turn(
                    regeneration_target_in_history
                )
                if (
                    resumed_loaded_turn is None
                    and regeneration_accepted_input is not None
                    and regeneration_accepted_input[0] == session.session_generation()
                ):
                    resumed_loaded_turn = regeneration_accepted_input[1]
                regeneration_accepted_input = None
                if regenerate_as_assistant_continuation and resumed_loaded_turn:
                    resumed_loaded_turn = dict(resumed_loaded_turn)
                    resumed_loaded_turn.update(
                        {
                            "role": "user",
                            "content": CONTINUE_ASSISTANT_SENTINEL,
                            "origin": "input",
                        }
                    )
                regeneration_transaction_id = str(
                    (resumed_loaded_turn or {}).get("normal_chat_transaction_id")
                    or ""
                ).strip()
                regeneration_attempt = bool(regeneration_transaction_id)
                regeneration_reuses_edited_input = bool(
                    _removed_target
                    and resumed_loaded_turn
                    and not regeneration_attempt
                )
                regeneration_target_in_history = False
                request_only_continue_cue_pending = not (
                    regenerate_as_assistant_continuation
                )
                if resumed_loaded_turn:
                    user_text = str(resumed_loaded_turn.get("content", "") or "")
                    proactive_request_pending = False
                elif regenerate_as_assistant_continuation:
                    user_text = CONTINUE_ASSISTANT_SENTINEL
                    proactive_request_pending = False
                else:
                    user_text = REQUEST_ONLY_CONTINUATION_CUE
                    proactive_request_pending = True
                regeneration_rebuild_pending = True
                regenerating = False

            # =================================================================================
            # PHASE 2: THINKING
            # =================================================================================
            if user_text:
                if scoped_actions is not None:
                    scoped_actions.set_phase('thinking')
                _drain_phone_controls()
                if phone_input_pending:
                    phone_input_pending = False
                    replacement_input = _consume_pending_loaded_input_turn()
                    if replacement_input is not None:
                        resumed_loaded_turn = replacement_input
                        user_text = str(replacement_input.get("content", "") or "")
                stream_state = None
                stream_reply_finalized = False
                active_ctrl = None
                assistant_history_added = False
                discard_assistant_history = False
                input_role_override = None
                if isinstance(resumed_loaded_turn, dict):
                    input_role_override = str(resumed_loaded_turn.get("role", "") or "").strip().lower()
                thinking_actions = _plan_phase2_actions(
                    user_text,
                    input_role_override=input_role_override,
                    proactive_request=proactive_request_pending,
                )
                request_only_continue_cue = bool(request_only_continue_cue_pending)
                proactive_request_pending = False
                request_only_continue_cue_pending = False
                is_proactive = bool(conversation_controller.state.is_proactive_turn)
                reply_source_meta = {
                    "remote_capture_id": "",
                    "hidden_proactive": bool(is_proactive),
                }
                preserve_proactive_placeholder = bool(conversation_controller.state.preserve_proactive_placeholder)
                input_role_for_addon_commands = input_role_override if input_role_override in {"user", "system", "assistant"} else "user"
                accepted_input_turn = _reconstruct_input_turn(resumed_loaded_turn)
                prepared_input_turn = None
                prepared_input_turn_reuses_history = False
                prepared_input_turn_is_placeholder = False
                acceptance_error = None
                for action in thinking_actions:
                    if action.type != ConversationActionType.APPEND_HISTORY:
                        continue
                    if scoped_prepared is not None:
                        prepared_input_turn = scoped_prepared[0]
                        accepted_input_turn = prepared_input_turn
                        prepared_input_turn_reuses_history = True
                        resumed_loaded_turn = None
                        break
                    role = str(action.payload.get("role", "user") or "user")
                    content = str(action.payload.get("content", user_text) or user_text)
                    is_placeholder = bool(action.payload.get("placeholder", False))
                    if role != "user" and not is_placeholder and _pending_user_image_attachment():
                        clear_pending_user_image_attachment()
                    if resumed_loaded_turn and not is_placeholder:
                        resumed_role = str(resumed_loaded_turn.get("role", "") or "").strip().lower()
                        resumed_content = str(resumed_loaded_turn.get("content", "") or "")
                        if role == resumed_role and content == resumed_content:
                            prepared_input_turn = resumed_loaded_turn
                            prepared_input_turn_reuses_history = True
                            accepted_input_turn = resumed_loaded_turn
                            break
                    resumed_loaded_turn = None
                    prepared_input_turn = {"role": role, "content": content, "origin": "input"}
                    _maybe_arm_screen_image_for_user_turn(
                        prepared_input_turn,
                        is_placeholder=is_placeholder,
                    )
                    prepared_input_turn = _attach_pending_user_image_to_turn(
                        prepared_input_turn,
                        is_placeholder=is_placeholder,
                    )
                    prepared_input_turn_is_placeholder = is_placeholder
                    if not is_placeholder:
                        try:
                            prepared_input_turn = _begin_normal_chat_transaction(
                                prepared_input_turn,
                                source_lease=(
                                    speech_transcript.lease
                                    if speech_transcript is not None
                                    else None
                                ),
                            )
                        except NormalChatTurnBlocked as exc:
                            acceptance_error = exc
                        else:
                            accepted_input_turn = prepared_input_turn
                    break
                if (
                    acceptance_error is None
                    and regeneration_reuses_edited_input
                    and prepared_input_turn_reuses_history
                    and accepted_input_turn is not None
                ):
                    try:
                        accepted_input_turn = _begin_normal_chat_transaction(
                            accepted_input_turn,
                            persist_user_turn=False,
                        )
                    except NormalChatTurnBlocked as exc:
                        acceptance_error = exc
                if (
                    acceptance_error is None
                    and hidden_proactive_request
                    and not regeneration_attempt
                ):
                    try:
                        accepted_input_turn = _begin_normal_chat_transaction(
                            {
                                "role": input_role_for_addon_commands,
                                "content": str(user_text),
                                "origin": "input",
                                "hidden_proactive_request": dict(
                                    hidden_proactive_request
                                ),
                            },
                            persist_user_turn=False,
                            accepted_turn_snapshot=accepted_proactive_turn,
                        )
                    except NormalChatTurnBlocked as exc:
                        acceptance_error = exc
                    else:
                        print(
                            "👁️ [Sensory] Attached targeted proactive cue to "
                            "the Normal Chat request."
                        )
                elif (
                    acceptance_error is None
                    and accepted_input_turn is None
                    and not regeneration_attempt
                ):
                    transient_turn = {
                        "role": input_role_for_addon_commands,
                        "content": str(user_text),
                        "origin": "input",
                    }
                    try:
                        accepted_input_turn = _begin_normal_chat_transaction(
                            transient_turn,
                            persist_user_turn=False,
                            source_lease=(
                                speech_transcript.lease
                                if speech_transcript is not None
                                else None
                            ),
                            accepted_turn_snapshot=accepted_proactive_turn,
                        )
                    except NormalChatTurnBlocked as exc:
                        acceptance_error = exc
                speech_transcript = None
                _drain_phone_controls()
                if phone_input_pending:
                    phone_input_pending = False
                    replacement_input = _consume_pending_loaded_input_turn()
                    if replacement_input is not None:
                        resumed_loaded_turn = replacement_input
                        user_text = str(replacement_input.get("content", "") or "")
                        response_text = None
                        continue
                try:
                    if acceptance_error is not None:
                        raise acceptance_error
                    normal_chat_request = scoped_prepared[1] if scoped_prepared is not None else _freeze_normal_chat_request(
                        accepted_input_turn,
                        request_only_continue_cue=request_only_continue_cue,
                        require_existing_transaction=regeneration_attempt,
                        regenerate_route=regeneration_attempt,
                    )
                    scoped_prepared = None
                    regeneration_reuses_edited_input = False
                    accepted_proactive_turn = None
                    transaction = _normal_chat_transaction_for_request(
                        normal_chat_request
                    )
                    turn_snapshot = (
                        transaction.get("turn_snapshot")
                        if isinstance(transaction, dict)
                        else None
                    )
                    if not isinstance(turn_snapshot, TurnSnapshot):
                        raise NormalChatTurnBlocked(
                            "Accepted Normal Chat turn lost its frozen execution policy."
                        )
                    active_turn_generation = int(
                        turn_snapshot.lease.session_generation.value
                    )
                    turn_execution_policy = TurnExecutionPolicy.from_snapshot(
                        turn_snapshot
                    )
                except NormalChatTurnBlocked as exc:
                    regeneration_attempt = False
                    conversation_controller.on_assistant_reply(None)
                    if phone_controls is not None:
                        phone_controls.reject_unbound_input(accepted_input_turn)
                    regeneration_reuses_edited_input = False
                    blocked_config = _live_config()
                    blocked_reply_id = _begin_dry_run_reply(
                        blocked_config,
                        streamed=bool(blocked_config.get("stream_mode", False)),
                        proactive=is_proactive,
                    )
                    _finalize_dry_run_reply(blocked_reply_id)
                    if regeneration_rebuild_pending:
                        _request_chat_view_rebuild()
                        regeneration_rebuild_pending = False
                    print(f"⚠️ [Identity Relay/Normal Chat] {exc}")
                    if normal_chat_request is not None:
                        _cancel_normal_chat_request(normal_chat_request)
                    _prune_normal_chat_transactions()
                    _presence_set_state("idle")
                    _presence_set_audio_level(0.0)
                    user_text = None
                    speech_transcript = None
                    resumed_loaded_turn = None
                    response_text = None
                    normal_chat_request = None
                    continue
                if regeneration_rebuild_pending:
                    _request_chat_view_rebuild()
                    regeneration_rebuild_pending = False
                regeneration_attempt = False
                for action in thinking_actions:
                    if action.type in {
                        ConversationActionType.START_LLM_REQUEST,
                        ConversationActionType.START_LLM_STREAM,
                    }:
                        action.type = (
                            ConversationActionType.START_LLM_STREAM
                            if turn_execution_policy.stream_mode
                            else ConversationActionType.START_LLM_REQUEST
                        )
                input_role_for_addon_commands = (
                    input_role_override
                    if input_role_override in {"user", "system", "assistant"}
                    else turn_execution_policy.input_message_role
                )
                _presence_set_state("thinking")
                _presence_set_audio_level(0.0)
                addon_user_text_command = None
                addon_user_text_command_consumed = False
                addon_user_text_command_uses_llm = False
                addon_user_text_command_prefers_low_latency_tts = False
                if not is_proactive:
                    addon_user_text_command = _maybe_handle_addon_user_text_command(
                        user_text,
                        input_role=input_role_for_addon_commands,
                        accepted_input_turn=accepted_input_turn,
                    )
                    addon_user_text_command_uses_llm = bool(
                        isinstance(addon_user_text_command, dict)
                        and addon_user_text_command.get("use_llm_response")
                    )
                elif hidden_proactive_request:
                    buddy_contextual_payload = _buddy_contextual_payload_from_hidden_proactive(hidden_proactive_request)
                    if buddy_contextual_payload:
                        addon_user_text_command = _maybe_handle_buddy_contextual_reply(buddy_contextual_payload)
                addon_user_text_command_prefers_low_latency_tts = bool(
                    isinstance(addon_user_text_command, dict)
                    and addon_user_text_command.get("prefer_low_latency_tts")
                )
                dry_run_reply_id = _begin_dry_run_reply(
                    turn_execution_policy.config,
                    streamed=turn_execution_policy.stream_mode,
                    proactive=is_proactive,
                )

                def _normal_chat_request_allows_handoff():
                    nonlocal normal_chat_request, regeneration_attempt
                    nonlocal phone_scope, phone_speech
                    nonlocal user_text, speech_transcript, resumed_loaded_turn, response_text
                    try:
                        if normal_chat_request is None:
                            return False
                        _ensure_normal_chat_transaction_ready(normal_chat_request)
                        if prepared_input_turn_reuses_history:
                            # Typed turns are published by request preparation, after
                            # their initial UI rebuild request. Rebuild again at the
                            # publication boundary so the first turn is visible
                            # without waiting for a later message to refresh the view.
                            _request_chat_view_rebuild()
                        reply_source_meta.clear()
                        reply_source_meta.update(
                            _normal_chat_reply_source_meta(
                                normal_chat_request,
                                hidden_proactive=is_proactive,
                            )
                        )
                        if (phone_controls is not None and phone_scope is None
                                and normal_chat_request.get("phone_reply_control") is True):
                            phone_scope = PhoneReplyScope(
                                normal_chat_request["remote_capture_id"],
                                normal_chat_request["normal_chat_transaction_id"],
                                normal_chat_request["session_generation"],
                            )
                            phone_speech = PhoneReplySpeechBinding()
                            phone_controls.bind(phone_scope, normal_chat_request,
                                                phone_speech.skip_audio, phone_speech.cancel_provider,
                                                require_playback_completion=normal_chat_request.get("phone_shared_queue") is True)
                    except NormalChatTurnBlocked as exc:
                        print(f"⚠️ [Identity Relay/Normal Chat] {exc}")
                        conversation_controller.on_assistant_reply(None)
                        if phone_controls is not None:
                            phone_controls.reject_unbound_input(accepted_input_turn)
                        if normal_chat_request is not None:
                            _cancel_normal_chat_request(normal_chat_request)
                        _prune_normal_chat_transactions()
                        _presence_set_state("idle")
                        _presence_set_audio_level(0.0)
                        _finalize_dry_run_reply(dry_run_reply_id)
                        user_text = None
                        speech_transcript = None
                        resumed_loaded_turn = None
                        response_text = None
                        normal_chat_request = None
                        return False
                    else:
                        return True

                for action in thinking_actions:
                    if action.type == ConversationActionType.APPEND_HISTORY:
                        input_turn = dict(prepared_input_turn or {})
                        role = str((input_turn or {}).get("role", "user") or "user")
                        is_placeholder = prepared_input_turn_is_placeholder
                        if is_proactive:
                            input_turn["hidden_proactive"] = True
                        if is_placeholder:
                            prepared_input_turn = None
                            resumed_loaded_turn = None
                            continue
                        if prepared_input_turn_reuses_history:
                            prepared_input_turn = None
                            resumed_loaded_turn = None
                            continue
                        prepared_input_turn = None
                        resumed_loaded_turn = None
                        if not input_turn:
                            continue
                        display_content = _display_input_turn_content(input_turn)
                        if role == "system":
                            print(f"💬 You (system): {display_content}")
                        elif role == "assistant":
                            print(f"💬 You (assistant): {display_content}")
                        else:
                            print(f"💬 You: {display_content}")

                    elif action.type == ConversationActionType.START_LLM_STREAM:
                        if not _normal_chat_request_allows_handoff():
                            break
                        if addon_user_text_command and not addon_user_text_command_uses_llm and not addon_user_text_command_consumed:
                            prepared_reply = prepare_assistant_reply(
                                str(addon_user_text_command.get("response_text") or ""),
                                runtime_config=(
                                    turn_execution_policy.assistant_reply_config
                                ),
                            )
                            response_text = prepared_reply.text
                            addon_user_text_command_consumed = True
                            reply_actions = conversation_controller.on_assistant_reply(response_text)
                            for reply_action in reply_actions:
                                if reply_action.type == ConversationActionType.POP_LAST_HISTORY:
                                    _pop_last_proactive_placeholder(user_text)
                            if response_text:
                                assistant_history_added = _append_assistant_history_turn(
                                    response_text,
                                    identity_relay=normal_chat_request.get("identity_relay_metadata"),
                                    expected_session_generation=normal_chat_request.get("session_generation"),
                                    expected_turn_id=normal_chat_request.get("normal_chat_transaction_id"),
                                    hidden_proactive=is_proactive,
                                    assistant_persona=normal_chat_request.get("assistant_persona"),
                                ) is not None
                                if assistant_history_added:
                                    publish_assistant_reply_effects(
                                        prepared_reply,
                                        lease=turn_snapshot.lease,
                                    )
                                    _apply_stored_chat_history_limit()
                                    maybe_start_continuity_memory_auto_update()
                                    maybe_start_long_term_memory_auto_archive()
                                else:
                                    response_text = None
                            else:
                                _complete_normal_chat_transaction(
                                    normal_chat_request,
                                    discard_binding=True,
                                )
                            _clear_active_hidden_proactive_candidate()
                            continue
                        print("⚡ Stream mode enabled...")
                        # Terminal cleanup leaves this compatibility signal set.
                        # Clear it before providers prepare a replacement stream.
                        stop_playback.clear()
                        from core.streaming_deadlines import TextStreamChannel
                        stream_text_queue = TextStreamChannel()
                        buddy_voice_policy = _addon_voice_segments_stream_policy(
                            {
                                "tts_backend": turn_execution_policy.tts_backend,
                                "streaming": True,
                            }
                        )
                        stream_state = start_streamed_llm_reply(
                            stream_text_queue,
                            dry_run_reply_id=dry_run_reply_id,
                            request_context=normal_chat_request,
                            preserve_voice_labels=bool(buddy_voice_policy.get("preserve_voice_labels", False)),
                            show_preview=not is_proactive,
                        )
                        if phone_speech is not None:
                            phone_speech.stream = stream_state
                        active_ctrl = speak_async_stream(
                            stream_text_queue,
                            dry_run_reply_id=dry_run_reply_id,
                            requires_full_text=bool(buddy_voice_policy.get("requires_full_text", False)),
                            reply_source_meta=reply_source_meta,
                            runtime_config=turn_execution_policy.config,
                            turn_lease=turn_snapshot.lease,
                        )
                        if phone_speech is not None:
                            phone_speech.attach_route(active_ctrl)
                        companion_orb_vision_debug.record_event(
                            str(
                                (normal_chat_request or {}).get(
                                    "companion_orb_debug_trace_id"
                                )
                                or ""
                            ),
                            "tts_stream_submission",
                            tts_backend=turn_execution_policy.tts_backend,
                            streaming=True,
                        )
                        conversation_controller.on_stream_started()
                        response_text = None

                    elif action.type == ConversationActionType.START_LLM_REQUEST:
                        if not _normal_chat_request_allows_handoff():
                            break
                        try:
                            if addon_user_text_command and not addon_user_text_command_uses_llm and not addon_user_text_command_consumed:
                                prepared_reply = prepare_assistant_reply(
                                    str(addon_user_text_command.get("response_text") or ""),
                                    runtime_config=(
                                        turn_execution_policy.assistant_reply_config
                                    ),
                                )
                                addon_user_text_command_consumed = True
                            else:
                                prepared_reply = prepare_assistant_reply(
                                    chat_with_llm(normal_chat_request) or "",
                                    runtime_config=(
                                        turn_execution_policy.assistant_reply_config
                                    ),
                                )
                            response_text = _normalize_assistant_continuation(
                                prepared_reply.text
                            )
                        except NormalChatTurnBlocked as exc:
                            if user_text == CONTINUE_ASSISTANT_SENTINEL:
                                print(
                                    "⚠️ [Normal Chat] Assistant continuation produced "
                                    f"no reply: {exc}"
                                )
                            else:
                                print(
                                    "⚠️ [Normal Chat] Provider request failed; "
                                    f"the session remains active: {exc}"
                                )
                            prepared_reply = prepare_assistant_reply(
                                "",
                                runtime_config=(
                                    turn_execution_policy.assistant_reply_config
                                ),
                            )
                            response_text = prepared_reply.text
                        except Exception:
                            _presence_set_state("idle")
                            _presence_set_audio_level(0.0)
                            raise
                        reply_actions = conversation_controller.on_assistant_reply(response_text)
                        for reply_action in reply_actions:
                            if reply_action.type == ConversationActionType.POP_LAST_HISTORY:
                                _pop_last_proactive_placeholder(user_text)

                        if not response_text:
                            _complete_normal_chat_transaction(
                                normal_chat_request,
                                discard_binding=True,
                            )
                            if phone_controls is not None and phone_scope is not None:
                                phone_controls.producer_finished(phone_scope)
                                _drain_phone_controls()
                                _drain_phone_finalizer()
                            # Empty assistant continuations publish no history.
                            # Reconcile the transcript from canonical history so
                            # a delayed pre-retry assistant render cannot reappear.
                            _request_chat_view_rebuild()
                            _clear_active_hidden_proactive_candidate()
                            _presence_set_state("idle")
                            _presence_set_audio_level(0.0)
                            _finalize_dry_run_reply(dry_run_reply_id)
                            user_text = None
                            speech_transcript = None
                            continue

                        assistant_history_added = _append_assistant_history_turn(
                            response_text,
                            identity_relay=normal_chat_request.get("identity_relay_metadata"),
                            expected_session_generation=normal_chat_request.get("session_generation"),
                            expected_turn_id=normal_chat_request.get("normal_chat_transaction_id"),
                            hidden_proactive=is_proactive,
                            assistant_persona=normal_chat_request.get("assistant_persona"),
                        ) is not None
                        if assistant_history_added:
                            publish_assistant_reply_effects(
                                prepared_reply,
                                lease=turn_snapshot.lease,
                            )
                            _apply_stored_chat_history_limit()
                            maybe_start_continuity_memory_auto_update()
                            maybe_start_long_term_memory_auto_archive()
                        else:
                            response_text = None
                            _presence_set_state("idle")
                            _presence_set_audio_level(0.0)
                            _finalize_dry_run_reply(dry_run_reply_id)
                            user_text = None
                            speech_transcript = None
                            continue
                        _clear_active_hidden_proactive_candidate()

                        if is_proactive:
                            user_text = None
                            speech_transcript = None

            # =================================================================================
            # PHASE 3: SPEAKING (TTS PLAYBACK)
            # =================================================================================
            if active_replay_id:
                listening_active.clear()
                microphone_active.clear()
                started_replay = replay.start_replay(active_replay_id)
                if not started_replay.accepted:
                    replay.cancel(active_replay_id, reason="replay_start_failed")
                    active_replay_id = ""
                    listening_active.clear()
                    continue
                while not replay.is_done(active_replay_id) and not stop_flag.is_set():
                    _drain_phone_controls()
                    def _ignore_replay(dispatch):
                        print(
                            "\n[Replay] Ignored unavailable replay action: "
                            f"{dispatch.action}"
                        )
                        return InteractionEffectResult()

                    def _skip_replay(_dispatch):
                        print("\n⏭️ Skipping replay message...")
                        replay.skip_current_message(active_replay_id)
                        return InteractionEffectResult()

                    def _replace_replay(dispatch):
                        nonlocal active_replay_id
                        replay.cancel(active_replay_id, reason="replay_replaced")
                        started = _start_replay_action(dispatch.action)
                        active_replay_id = (
                            started.value.replay_id
                            if started.accepted and started.value is not None
                            else ""
                        )
                        return InteractionEffectResult(
                            InteractionFlow.STAY
                            if active_replay_id
                            else InteractionFlow.BREAK
                        )

                    def _pause_replay(_dispatch):
                        conversation_controller.on_pause_toggled()
                        if playback_paused.is_set():
                            resumed = replay.resume(active_replay_id)
                            if resumed.accepted:
                                manual_pause_active.clear()
                                playback_paused.clear()
                                control.set_last_resume_requested_at(time.time())
                                print("- - - RESUME REQUESTED - - -")
                        elif pause_after_chunk.is_set():
                            resumed = replay.resume(active_replay_id)
                            if resumed.accepted:
                                manual_pause_active.clear()
                                pause_after_chunk.clear()
                                print("- - - PAUSE AFTER CHUNK CANCELED - - -")
                        else:
                            paused = replay.pause(active_replay_id)
                            if paused.accepted:
                                manual_pause_active.set()
                                pause_after_chunk.set()
                                print("- - - WILL PAUSE AFTER CURRENT CHUNK - - -")
                        return InteractionEffectResult()

                    dispatched = _dispatch_interaction(
                        check_interaction_status(source),
                        InteractionPhase.REPLAY,
                        effects=InteractionCommandCapabilities(
                            pause_replay=_pause_replay,
                            skip_replay=_skip_replay,
                            start_replay=_replace_replay,
                            ignore=_ignore_replay,
                        ),
                    )
                    if (
                        dispatched is not None
                        and dispatched.effect.flow is InteractionFlow.BREAK
                    ):
                        break
                    replay.wait(active_replay_id, timeout=0.02)
                if active_replay_id:
                    if stop_flag.is_set():
                        replay.cancel(active_replay_id, reason="runtime_shutdown")
                    else:
                        replay.finish(active_replay_id)
                active_replay_id = ""
                listening_active.clear()
                continue

            if response_text or active_ctrl:
                listening_active.set()
                microphone_active.clear()
                ctrl = active_ctrl
                if response_text:
                    speech_runtime_config = (
                        turn_execution_policy.config
                        if turn_execution_policy is not None
                        else _live_config()
                    )
                    speech_turn_lease = (
                        turn_snapshot.lease
                        if turn_execution_policy is not None
                        else None
                    )
                    print(f"🤖 Assistant: {response_text}")
                    print("------------------------------------------------------------------------------------------------------")
                    print("------------------------------------------------------------------------------------------------------")
                    stop_playback.clear()
                    set_seed(3918375115)
                    companion_orb_vision_debug.record_event(
                        str(
                            (normal_chat_request or {}).get(
                                "companion_orb_debug_trace_id"
                            )
                            or ""
                        ),
                        "tts_submission",
                        text=response_text,
                        character_count=len(response_text),
                        degenerate=companion_orb_vision_debug.looks_degenerate(
                            response_text
                        ),
                        tts_backend=str(
                            speech_runtime_config.get("tts_backend", "") or ""
                        ),
                        streaming=False,
                    )
                    if (
                        turn_execution_policy is not None
                        and turn_execution_policy.stream_mode
                        and addon_user_text_command_consumed
                        and addon_user_text_command_prefers_low_latency_tts
                    ):
                        ctrl = speak_async(
                            "",
                            text_iterable=_prepare_low_latency_completed_tts_segments(
                                response_text,
                                runtime_config=speech_runtime_config,
                            ),
                            dry_run_reply_id=dry_run_reply_id,
                            preserve_text_iterable_chunks=True,
                            reply_source_meta=reply_source_meta,
                            runtime_config=speech_runtime_config,
                            turn_lease=speech_turn_lease,
                        )
                    else:
                        ctrl = speak_async(
                            response_text,
                            dry_run_reply_id=dry_run_reply_id,
                            reply_source_meta=reply_source_meta,
                            runtime_config=speech_runtime_config,
                            turn_lease=speech_turn_lease,
                        )

                was_barge_in = False
                scoped_route_lease = turn_snapshot.lease if turn_snapshot is not None else None
                if scoped_actions is not None:
                    scoped_actions.set_phase('speaking')
                if phone_speech is not None and response_text:
                    phone_speech.attach_route(ctrl)
                _drain_phone_controls()

                while (
                    (audio_playing.is_set() or not ctrl.done.is_set() or (stream_state is not None and not stream_state.done.is_set()) or _phone_held() or _phone_playback_pending())
                    and not stop_flag.is_set()
                ):
                    # Production may finish long before phone playback. Publish
                    # that boundary while still pumping controls for the final
                    # phone acknowledgement; waiting until loop exit deadlocks.
                    if (phone_controls is not None and phone_scope is not None
                            and ctrl.done.is_set() and (stream_state is None or stream_state.done.is_set())):
                        phone_controls.producer_finished(phone_scope)
                    _drain_phone_controls()
                    if scoped_action is not None and scoped_actions is not None:
                        rejected = scoped_actions.validate(scoped_action)
                        if rejected is not None:
                            scoped_actions.finish(scoped_action.operation_id, rejected)
                            scoped_action = None
                        elif not _phone_playback_pending():
                            # No history mutation or replacement begins until
                            # BOTH the real route and producer have retired.
                            ctrl.cancel('conversation_action')
                            if stream_state is not None:
                                stream_state.cancel_requested.set()
                            discard_assistant_history = True
                            regenerating = True
                            while not stop_flag.is_set() and (not ctrl.playback_retired()
                                    or (stream_state is not None and not stream_state.done.is_set())):
                                _drain_phone_controls()
                                stop_flag.wait(.02)
                            break
                    if (
                        stream_state is not None
                        and stream_state.done.is_set()
                        and not assistant_history_added
                        and not stream_reply_finalized
                        and not _phone_held()
                        and not _phone_interrupted()
                    ):
                        prepared_reply = prepare_assistant_reply(
                            (stream_state.full_text or "").strip(),
                            runtime_config=(
                                turn_execution_policy.assistant_reply_config
                            ),
                        )
                        response_text = _normalize_assistant_continuation(
                            prepared_reply.text
                        )
                        if stream_state.error and not response_text:
                            if user_text == CONTINUE_ASSISTANT_SENTINEL:
                                print(
                                    "⚠️ [Normal Chat] Assistant continuation stream "
                                    f"produced no reply: {stream_state.error}"
                                )
                            else:
                                prepared_reply = prepare_assistant_reply(
                                    "I'm having trouble thinking right now.",
                                    runtime_config=(
                                        turn_execution_policy.assistant_reply_config
                                    ),
                                )
                                response_text = prepared_reply.text
                        reply_actions = conversation_controller.on_assistant_reply(response_text)
                        for reply_action in reply_actions:
                            if reply_action.type == ConversationActionType.POP_LAST_HISTORY:
                                _pop_last_proactive_placeholder(user_text)
                        if response_text:
                            assistant_turn = _append_assistant_history_turn(
                                response_text,
                                identity_relay=(normal_chat_request or {}).get("identity_relay_metadata"),
                                expected_session_generation=(normal_chat_request or {}).get("session_generation"),
                                expected_turn_id=(normal_chat_request or {}).get("normal_chat_transaction_id"),
                                hidden_proactive=is_proactive,
                                assistant_persona=(normal_chat_request or {}).get("assistant_persona"),
                            )
                            if assistant_turn is not None:
                                publish_assistant_reply_effects(
                                    prepared_reply,
                                    lease=turn_snapshot.lease,
                                )
                                _apply_stored_chat_history_limit()
                                assistant_history_added = True
                                print(f"🤖 Assistant: {response_text}")
                                print("------------------------------------------------------------------------------------------------------")
                                print("------------------------------------------------------------------------------------------------------")
                                maybe_start_continuity_memory_auto_update()
                                maybe_start_long_term_memory_auto_archive()
                            else:
                                response_text = None
                        else:
                            _request_chat_view_rebuild()
                        stream_reply_finalized = True
                        _clear_active_hidden_proactive_candidate()
                        if is_proactive:
                            user_text = None
                            speech_transcript = None
                    def _skip_speech(_dispatch):
                        print("\n⏭️ Skipping speech...")
                        if phone_scope is not None and phone_controls is not None and phone_controls.request_playback_stop(phone_scope):
                            # Publishing stopped is not evidence the remote speaker
                            # stopped. Keep draining its exact acknowledgement.
                            return InteractionEffectResult()
                        if not (
                            hasattr(ctrl, "request_playback_skip")
                            and ctrl.request_playback_skip()
                        ):
                            stop_playback.set()
                        # We don't mark as interrupted for history purposes on skip.
                        if stream_state is None:
                            return InteractionEffectResult(InteractionFlow.BREAK)
                        return InteractionEffectResult()

                    def _regenerate_speech(_dispatch):
                        nonlocal discard_assistant_history
                        nonlocal regeneration_target_in_history, regenerating
                        nonlocal regeneration_accepted_input
                        print("\n🎲 Cutting speech to regenerate...")
                        stop_playback.set()
                        if stream_state is not None:
                            stream_state.cancel_requested.set()
                        discard_assistant_history = True
                        regeneration_target_in_history = bool(assistant_history_added)
                        regeneration_accepted_input = (
                            (
                                (normal_chat_request or {}).get("session_generation"),
                                dict(accepted_input_turn),
                            )
                            if not assistant_history_added
                            and accepted_input_turn
                            and accepted_input_turn.get("normal_chat_transaction_id")
                            else None
                        )
                        regenerating = True
                        return InteractionEffectResult(InteractionFlow.BREAK)

                    def _retry_speech_input(_dispatch):
                        nonlocal discard_assistant_history, user_text
                        nonlocal speech_transcript, response_text
                        print("\nscrapped last input, listening again...")
                        stop_playback.set()
                        if stream_state is not None:
                            stream_state.cancel_requested.set()
                        discard_assistant_history = True
                        _discard_last_exchange_for_retry()
                        user_text = None
                        speech_transcript = None
                        response_text = None
                        return InteractionEffectResult(InteractionFlow.BREAK)

                    def _start_speaking_replay(dispatch):
                        nonlocal active_replay_id
                        started = _start_replay_action(
                            dispatch.action,
                            defer=True,
                        )
                        if started.accepted and started.value is not None:
                            active_replay_id = started.value.replay_id
                            stop_playback.set()
                            if stream_state is not None:
                                stream_state.cancel_requested.set()
                            return InteractionEffectResult(InteractionFlow.BREAK)
                        return InteractionEffectResult()

                    def _cancel_speech_and_capture_delivered_text(reason: str) -> str:
                        stop_playback.set()
                        cancel_speech = getattr(ctrl, "cancel", None)
                        if callable(cancel_speech):
                            cancel_speech(str(reason or "speech_interrupted"))
                        done = getattr(ctrl, "done", None)
                        wait_done = getattr(done, "wait", None)
                        if callable(wait_done):
                            wait_done(timeout=0.5)
                        get_spoken_text = getattr(ctrl, "get_spoken_text", None)
                        if not callable(get_spoken_text):
                            return ""
                        return str(get_spoken_text() or "").strip()

                    def _capture_speaking_input(_dispatch, *, push_to_talk, audio_start_admitted):
                        nonlocal was_barge_in, assistant_history_added
                        nonlocal discard_assistant_history, user_text
                        nonlocal speech_transcript, proactive_request_pending
                        nonlocal request_only_continue_cue_pending, response_text
                        if not audio_start_admitted:
                            # The detector keeps draining small PCM blocks until quiet;
                            # do not begin a blocking STT capture before real playback.
                            if not push_to_talk and callable(suppress_barge_in_until_quiet):
                                suppress_barge_in_until_quiet()
                            if push_to_talk and callable(suppress_push_to_talk_until_release):
                                suppress_push_to_talk_until_release()
                            return InteractionEffectResult()
                        if push_to_talk:
                            print("\n🎙️ Push-to-talk interruption...")
                        else:
                            print(f"\n🛑 Barge-in! Listening...")
                        # 1. Capture what was spoken BEFORE we process the new input
                        # Cancel the exact speech route first so production playback
                        # publishes its delivered-chunk receipt.  Do not cancel the
                        # provider stream until the accepted interruption has revised
                        # history; otherwise its transaction can disappear during STT.
                        spoken_so_far = _cancel_speech_and_capture_delivered_text(
                            "speech_interrupted"
                        )

                        was_barge_in = True

                        # 2. Listen for the interruption
                        if push_to_talk:
                            potential_transcript = _published_speech_transcript(
                                listen_for_speech_push_to_talk(
                                    source,
                                    lease=turn_snapshot.lease,
                                )
                            )
                        else:
                            potential_transcript = _published_speech_transcript(
                                listen_for_speech(
                                    source,
                                    timeout=0.6,
                                    lease=turn_snapshot.lease,
                                )
                            )
                        potential_text = (
                            potential_transcript.text
                            if potential_transcript is not None
                            else None
                        )

                        if potential_text:
                            print(f"⚡ Interrupted with: '{potential_text}'")
                            # A real interruption supersedes earlier manual input.
                            # Empty/stale capture must not discard the pending slot.
                            session.discard_pending_loaded_input_turn(
                                expected_session_generation=active_turn_generation,
                            )

                            # 3. Update History using YOUR Logic
                            final_assistant = (
                                spoken_so_far + " ... (user interrupted)"
                                if spoken_so_far else ""
                            )
                            appended_interrupted_assistant = (
                                _record_interrupted_assistant(
                                    normal_chat_request,
                                    final_assistant,
                                    hidden_proactive=is_proactive,
                                )
                            )
                            assistant_history_added = (
                                assistant_history_added
                                or appended_interrupted_assistant
                            )
                            if appended_interrupted_assistant:
                                maybe_start_continuity_memory_auto_update()
                                maybe_start_long_term_memory_auto_archive()

                            discard_assistant_history = True
                            conversation_controller.on_barge_in_text(potential_text)
                            user_text = potential_text
                            speech_transcript = potential_transcript
                            proactive_request_pending = False
                            request_only_continue_cue_pending = False
                            response_text = None
                        else:
                            was_barge_in = False
                            listening_active.set()
                        if stream_state is not None:
                            stream_state.cancel_requested.set()
                        return InteractionEffectResult(InteractionFlow.BREAK)

                    def _pause_speech(_dispatch):
                        conversation_controller.on_pause_toggled()
                        if playback_paused.is_set():
                            if ctrl.resume():
                                manual_pause_active.clear()
                                pause_after_chunk.clear()
                                playback_paused.clear()
                                control.set_last_resume_requested_at(time.time())
                                print("- - - RESUME REQUESTED - - -")
                        elif pause_after_chunk.is_set():
                            if ctrl.resume():
                                manual_pause_active.clear()
                                pause_after_chunk.clear()
                                playback_paused.clear()
                                print("- - - PAUSE AFTER CHUNK CANCELED - - -")
                        else:
                            if ctrl.pause():
                                manual_pause_active.set()
                                pause_after_chunk.set()
                                playback_paused.set()
                                print("- - - WILL PAUSE AFTER CURRENT CHUNK - - -")
                        return InteractionEffectResult()

                    playback_started = getattr(ctrl, "audio_started", None)
                    audio_start_admitted = not (
                        playback_started is not None
                        and callable(getattr(playback_started, "is_set", None))
                        and not playback_started.is_set()
                    )
                    if not audio_start_admitted:
                        if callable(suppress_barge_in_until_quiet):
                            suppress_barge_in_until_quiet()
                        if callable(suppress_push_to_talk_until_release):
                            suppress_push_to_talk_until_release()
                    dispatched = _dispatch_interaction(
                        check_interaction_status(source),
                        InteractionPhase.SPEAKING,
                        effects=InteractionCommandCapabilities(
                            regenerate=_regenerate_speech,
                            retry_input=_retry_speech_input,
                            pause_speech=_pause_speech,
                            skip_speech=_skip_speech,
                            start_replay=_start_speaking_replay,
                            capture_voice=lambda dispatch: _capture_speaking_input(
                                dispatch,
                                push_to_talk=False,
                                audio_start_admitted=audio_start_admitted,
                            ),
                            capture_push_to_talk=lambda dispatch: _capture_speaking_input(
                                dispatch,
                                push_to_talk=True,
                                audio_start_admitted=audio_start_admitted,
                            ),
                        ),
                    )
                    if (
                        dispatched is not None
                        and dispatched.effect.flow is InteractionFlow.BREAK
                    ):
                        break

                    time.sleep(0.02)

                _drain_phone_finalizer(
                    producer_done=lambda: (
                        ctrl.done.is_set()
                        and (stream_state is None or stream_state.done.is_set())
                    )
                )
                if stop_flag.is_set() and phone_scope is None:
                    spoken_before_shutdown = (
                        _cancel_speech_and_capture_delivered_text(
                            "runtime_shutdown"
                        )
                    )
                    appended_interrupted_assistant = (
                        _record_interrupted_assistant(
                            normal_chat_request,
                            (
                                spoken_before_shutdown + " ... (user interrupted)"
                                if spoken_before_shutdown else ""
                            ),
                            hidden_proactive=is_proactive,
                        )
                    )
                    assistant_history_added = (
                        assistant_history_added or appended_interrupted_assistant
                    )
                    discard_assistant_history = True

                ctrl.done.wait(timeout=0.5)
                vision_debug_trace_id = str(
                    (normal_chat_request or {}).get(
                        "companion_orb_debug_trace_id"
                    )
                    or ""
                )
                if vision_debug_trace_id:
                    get_spoken_text = getattr(ctrl, "get_spoken_text", None)
                    try:
                        spoken_text = (
                            str(get_spoken_text() or "")
                            if callable(get_spoken_text)
                            else ""
                        )
                    except Exception:
                        spoken_text = ""
                    companion_orb_vision_debug.finish_trace(
                        vision_debug_trace_id,
                        status=(
                            "interrupted"
                            if was_barge_in
                            else "cancelled"
                            if stop_flag.is_set()
                            else "completed"
                        ),
                        tts_requested_text=str(response_text or ""),
                        tts_spoken_text=spoken_text,
                        spoken_degenerate=companion_orb_vision_debug.looks_degenerate(
                            spoken_text
                        ),
                    )
                manual_pause_active.clear()
                pause_after_chunk.clear()
                playback_paused.clear()
                stop_playback.set()
                if stream_state is not None:
                    stream_state.cancel_requested.set()
                    stream_state.done.wait(timeout=1.0)
                    _drain_phone_finalizer(
                        producer_done=lambda: (
                            ctrl.done.is_set() and stream_state.done.is_set()
                        )
                    )
                    if (
                        not assistant_history_added
                        and not discard_assistant_history
                        and not stream_reply_finalized
                        and not _phone_held()
                        and not _phone_interrupted()
                    ):
                        prepared_reply = prepare_assistant_reply(
                            (stream_state.full_text or "").strip(),
                            runtime_config=(
                                turn_execution_policy.assistant_reply_config
                            ),
                        )
                        response_text = _normalize_assistant_continuation(
                            prepared_reply.text
                        )
                        if stream_state.error and not response_text:
                            if user_text == CONTINUE_ASSISTANT_SENTINEL:
                                print(
                                    "⚠️ [Normal Chat] Assistant continuation stream "
                                    f"produced no reply: {stream_state.error}"
                                )
                            else:
                                prepared_reply = prepare_assistant_reply(
                                    "I'm having trouble thinking right now.",
                                    runtime_config=(
                                        turn_execution_policy.assistant_reply_config
                                    ),
                                )
                                response_text = prepared_reply.text
                        reply_actions = conversation_controller.on_assistant_reply(response_text)
                        for reply_action in reply_actions:
                            if reply_action.type == ConversationActionType.POP_LAST_HISTORY:
                                _pop_last_proactive_placeholder(user_text)
                        if response_text:
                            assistant_turn = _append_assistant_history_turn(
                                response_text,
                                identity_relay=(normal_chat_request or {}).get("identity_relay_metadata"),
                                expected_session_generation=(normal_chat_request or {}).get("session_generation"),
                                expected_turn_id=(normal_chat_request or {}).get("normal_chat_transaction_id"),
                                hidden_proactive=is_proactive,
                                assistant_persona=(normal_chat_request or {}).get("assistant_persona"),
                            )
                            if assistant_turn is not None:
                                publish_assistant_reply_effects(
                                    prepared_reply,
                                    lease=turn_snapshot.lease,
                                )
                                _apply_stored_chat_history_limit()
                                assistant_history_added = True
                                print(f"🤖 Assistant: {response_text}")
                                print("------------------------------------------------------------------------------------------------------")
                                print("------------------------------------------------------------------------------------------------------")
                                maybe_start_continuity_memory_auto_update()
                                maybe_start_long_term_memory_auto_archive()
                            else:
                                response_text = None
                        else:
                            _request_chat_view_rebuild()
                        stream_reply_finalized = True

                    if (not assistant_history_added and not regenerating and not was_barge_in
                            and not _phone_held() and not _phone_interrupted()):
                        _complete_normal_chat_transaction(
                            normal_chat_request,
                            discard_binding=True,
                        )

                conversation_controller.on_speaking_finished()
                if (
                    assistant_history_added
                    and not stop_flag.is_set()
                    and not was_barge_in
                    and not regenerating
                    and not discard_assistant_history
                    and not _phone_held()
                    and not _phone_interrupted()
                ):
                    # Assistant history is published before playback so UI/addon
                    # effects can observe it, but the accepted turn must remain
                    # live until its speech route is terminal.
                    _complete_normal_chat_transaction(normal_chat_request)
                transaction = _normal_chat_transaction_for_request(
                    normal_chat_request
                )
                turn_snapshot = (
                    transaction.get("turn_snapshot")
                    if isinstance(transaction, dict)
                    else None
                )
                if (
                    self.turns is not None
                    and turn_snapshot is not None
                    and self.turns.snapshot(
                        turn_snapshot.accepted_turn.turn_id
                    ) is turn_snapshot
                ):
                    if stop_flag.is_set():
                        terminal_status = TurnTerminalStatus.CANCELED
                    elif was_barge_in or _phone_interrupted():
                        terminal_status = TurnTerminalStatus.INTERRUPTED
                    elif regenerating or discard_assistant_history:
                        terminal_status = TurnTerminalStatus.SUPERSEDED
                    else:
                        terminal_status = TurnTerminalStatus.COMPLETED
                    self.turns.finish(
                        turn_snapshot.accepted_turn.turn_id,
                        terminal_status,
                        lease=turn_snapshot.lease,
                    )
                if (phone_controls is not None and phone_scope is not None
                        and ctrl.done.is_set()
                        and (stream_state is None or stream_state.done.is_set())):
                    phone_controls.producer_finished(phone_scope)
                    _drain_phone_controls()
                _finalize_dry_run_reply(dry_run_reply_id)

                # FINALLY: Clear state
                if scoped_action is not None and scoped_actions is not None:
                    scoped_action = scoped_actions.after_retirement(scoped_action, scoped_route_lease)
                if regenerating:
                    response_text = None
                elif was_barge_in and user_text:
                    response_text = None
                else:
                    user_text = None
                    speech_transcript = None
                    response_text = None
                listening_active.clear()
                active_ctrl = None
                stream_state = None

        proactive.cancel("conversation_stopped")
        if active_replay_id:
            replay.cancel(active_replay_id, reason="conversation_stopped")


def build_experimental_controller(runtime_config: dict[str, Any], runtime: ConversationRuntime | None = None) -> ConversationController:
    policy = ConversationPolicy.from_runtime_config(runtime_config)
    controller_runtime = runtime or SystemClockRuntime()
    return ConversationController(policy=policy, runtime=controller_runtime)


def summarize_controller(controller: ConversationController) -> dict[str, Any]:
    state = controller.state
    return {
        "phase": state.phase.value,
        "has_real_user_turn": bool(state.has_real_user_turn),
        "is_proactive_turn": bool(state.is_proactive_turn),
        "pending_user_text": state.pending_user_text or "",
        "pending_assistant_text": state.pending_assistant_text or "",
        "stream_active": bool(state.stream_active),
        "last_error": state.last_error or "",
        "proactive_allowed": controller.machine.proactive_allowed(state),
    }
