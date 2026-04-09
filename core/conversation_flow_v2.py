from __future__ import annotations

"""Experimental conversation-flow v2.

This module is intentionally built in parallel with ``engine.run_conversation_flow``.
It does not replace the current runtime loop yet. The goal is to make the
conversation lifecycle explicit, inspectable, and eventually swappable.

Design goals:
- Separate conversation policy from control flow.
- Model conversation as explicit phases and events.
- Keep the old engine callable through a thin adapter seam later.
- Make future tests possible without importing the entire engine runtime.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Protocol


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
    def from_runtime_config(cls, runtime_config: dict[str, Any]) -> "ConversationPolicy":
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


@dataclass(slots=True)
class LegacyEngineAdapter:
    """Thin seam describing what the future migration will need from engine.py.

    This is deliberately only a callable registry for now. The v2 controller can be
    developed and tested against fake adapters before the old loop is replaced.
    """

    check_interaction_status: Callable[..., Optional[str]]
    listen_for_speech: Callable[..., Optional[str]]
    listen_for_speech_push_to_talk: Callable[..., Optional[str]]
    chat_with_llm: Callable[[], Optional[str]]
    start_streamed_llm_reply: Callable[..., Any]
    speak_async: Callable[..., Any]
    speak_async_stream: Callable[..., Any]
    sanitize_assistant_text_for_speech: Callable[[str], str]
    proactive_placeholder_role: Callable[[], str]
    pop_last_proactive_placeholder: Callable[[str], bool]
    begin_dry_run_reply: Optional[Callable[..., Any]] = None
    finalize_dry_run_reply: Optional[Callable[..., Any]] = None

    @classmethod
    def from_engine_namespace(cls, namespace: Any) -> "LegacyEngineAdapter":
        return cls(
            check_interaction_status=getattr(namespace, "check_interaction_status"),
            listen_for_speech=getattr(namespace, "listen_for_speech"),
            listen_for_speech_push_to_talk=getattr(namespace, "listen_for_speech_push_to_talk"),
            chat_with_llm=getattr(namespace, "chat_with_llm"),
            start_streamed_llm_reply=getattr(namespace, "start_streamed_llm_reply"),
            speak_async=getattr(namespace, "speak_async"),
            speak_async_stream=getattr(namespace, "speak_async_stream"),
            sanitize_assistant_text_for_speech=getattr(namespace, "sanitize_assistant_text_for_speech"),
            proactive_placeholder_role=getattr(namespace, "_proactive_placeholder_role"),
            pop_last_proactive_placeholder=getattr(namespace, "_pop_last_proactive_placeholder"),
            begin_dry_run_reply=getattr(getattr(namespace, "dry_run", None), "begin_reply", None),
            finalize_dry_run_reply=getattr(getattr(namespace, "dry_run", None), "finalize_reply", None),
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
                    placeholder_role = "user"
                    state.proactive_placeholder_role = placeholder_role
                    state.preserve_proactive_placeholder = True
                    actions.append(ConversationAction(ConversationActionType.APPEND_HISTORY, {"role": placeholder_role, "content": user_text, "placeholder": True}))
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

        if state.phase is ConversationPhase.SPEAKING:
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
    """Thin orchestrator around the pure state machine.

    This remains intentionally lightweight in v1. The old engine loop is still the
    production path. This controller is the parallel architecture target.
    """

    policy: ConversationPolicy
    runtime: ConversationRuntime
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
