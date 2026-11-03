"""Bounded manual interaction commands and hotkey polling ownership."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum, auto
import threading
import time
from types import MappingProxyType

from core import runtime_hotkeys
from core.runtime.config import RuntimeConfigSnapshot
from core.runtime.contracts import CommandResult, RuntimeFailure


InteractionHandler = Callable[["InteractionCommand"], object]
_RegisteredInteractionHandler = Callable[
    ["InteractionCommand", "InteractionPhase"],
    object,
]


class InteractionPhase(Enum):
    LISTENING = auto()
    REPLAY = auto()
    SPEAKING = auto()


class InteractionIntent(Enum):
    REGENERATE = auto()
    RETRY_INPUT = auto()
    PAUSE_LISTENING = auto()
    PAUSE_REPLAY = auto()
    PAUSE_SPEECH = auto()
    FORCE_PROACTIVE = auto()
    SKIP_REPLAY = auto()
    SKIP_SPEECH = auto()
    CONTINUE_ASSISTANT = auto()
    START_REPLAY = auto()
    CAPTURE_VOICE = auto()
    CAPTURE_PUSH_TO_TALK = auto()
    ACCEPT_PROACTIVE = auto()
    IGNORE = auto()
    CONVERSATION_ACTION = auto()


class InteractionFlow(Enum):
    STAY = auto()
    CONTINUE = auto()
    BREAK = auto()


@dataclass(frozen=True, slots=True)
class InteractionEffectResult:
    """Typed production-flow outcome returned by one explicit command effect."""

    flow: InteractionFlow = InteractionFlow.STAY
    value: object | None = None


_MANUAL_ACTIONS = frozenset(runtime_hotkeys.DEFAULT_MANUAL_ACTION_HOTKEYS)
_INTERNAL_ACTIONS = frozenset(
    {
        "barge_in",
        "hidden_proactive_reply",
        "proactive_timeout",
        "push_to_talk",
    }
)


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class InteractionCommand:
    """One immutable action submitted by a human or leased runtime source."""

    action: str
    payload: Mapping[str, object] = field(default_factory=dict)
    source: str = "manual"

    def __post_init__(self) -> None:
        action = str(self.action or "").strip()
        if not action:
            raise ValueError("InteractionCommand action must be non-empty")
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "source", str(self.source or "manual").strip() or "manual")
        object.__setattr__(self, "payload", _freeze(dict(self.payload or {})))


@dataclass(frozen=True, slots=True)
class InteractionDispatch:
    """Semantic result returned only by an explicitly registered handler."""

    intent: InteractionIntent
    command: InteractionCommand
    phase: InteractionPhase
    effect: InteractionEffectResult = InteractionEffectResult()

    @property
    def action(self) -> str:
        return self.command.action


InteractionEffect = Callable[[InteractionDispatch], InteractionEffectResult | None]


@dataclass(frozen=True, slots=True)
class InteractionCommandCapabilities:
    """Explicit phase-command effects supplied by the production coordinator."""

    regenerate: InteractionEffect | None = None
    retry_input: InteractionEffect | None = None
    pause_listening: InteractionEffect | None = None
    pause_replay: InteractionEffect | None = None
    pause_speech: InteractionEffect | None = None
    force_proactive: InteractionEffect | None = None
    skip_replay: InteractionEffect | None = None
    skip_speech: InteractionEffect | None = None
    continue_assistant: InteractionEffect | None = None
    start_replay: InteractionEffect | None = None
    capture_voice: InteractionEffect | None = None
    capture_push_to_talk: InteractionEffect | None = None
    accept_proactive: InteractionEffect | None = None
    ignore: InteractionEffect | None = None
    conversation_action: InteractionEffect | None = None


@dataclass(frozen=True, slots=True)
class InteractionBindings:
    generation: int
    bound: bool
    config_revision: int
    push_to_talk: str
    manual_actions: Mapping[str, str]
    ui_actions: Mapping[str, str]
    input_mode: str
    offline_replay_only: bool


@dataclass(frozen=True, slots=True)
class InteractionCapabilities:
    clock: Callable[[], float] = time.monotonic
    is_hotkey_pressed: Callable[[str], bool] = runtime_hotkeys.is_hotkey_binding_pressed
    dry_run_active: Callable[[], bool] = lambda: False
    push_to_talk_gui_held: Callable[[], bool] = lambda: False
    check_barge_in: Callable[[object], bool] = lambda _source: False
    bind_hotkeys: Callable[[], object] = lambda: None
    unbind_hotkeys: Callable[[], object] = lambda: None
    logger: Callable[[str], None] = lambda _message: None


def _empty_bindings(generation: int = 0) -> InteractionBindings:
    return InteractionBindings(
        generation=max(0, int(generation)),
        bound=False,
        config_revision=0,
        push_to_talk=runtime_hotkeys.DEFAULT_PUSH_TO_TALK_HOTKEY,
        manual_actions=MappingProxyType({}),
        ui_actions=MappingProxyType({}),
        input_mode="voice_activation",
        offline_replay_only=False,
    )


class InteractionService:
    """Own a bounded FIFO, hotkey bindings, debounce, and explicit handlers."""

    name = "interaction"

    def __init__(
        self,
        *,
        max_queue_size: int = 32,
        debounce_seconds: float = 0.5,
        capabilities: InteractionCapabilities | None = None,
        config_snapshot: Callable[[], RuntimeConfigSnapshot] | None = None,
    ) -> None:
        self._max_queue_size = max(1, min(1024, int(max_queue_size or 32)))
        self._debounce_seconds = max(0.0, float(debounce_seconds or 0.0))
        self._capabilities = capabilities or InteractionCapabilities()
        self._config_snapshot = config_snapshot
        self._lock = threading.Lock()
        self._binding_lock = threading.Lock()
        self._queue: deque[InteractionCommand] = deque()
        self._handlers: dict[str, _RegisteredInteractionHandler] = {}
        self._bindings = _empty_bindings()
        self._last_triggered_at = float("-inf")
        self._push_to_talk_suppressed_until_release = False
        self._accepting = True
        for action in _DEFAULT_ACTIONS:
            self._handlers[action] = _intent_handler(action)
        self._handlers["replay_chat_session_from"] = _intent_handler(
            "replay_chat_session"
        )

    def start(self) -> CommandResult[None]:
        with self._lock:
            self._accepting = True
        if self._config_snapshot is not None:
            try:
                return self.bind_hotkeys(self._config_snapshot())
            except BaseException as exc:
                return _failure(
                    "interaction_bind_failed",
                    str(exc) or "Interaction hotkeys could not be bound.",
                    exc,
                )
        return CommandResult(True)

    def stop(self) -> CommandResult[None]:
        with self._lock:
            self._accepting = False
            self._queue.clear()
        return self.unbind_hotkeys()

    def register_handler(
        self,
        action: str,
        handler: InteractionHandler,
    ) -> CommandResult[None]:
        key = str(action or "").strip()
        if not key or not callable(handler):
            return _failure("interaction_invalid_handler", "A named callable handler is required.")
        with self._lock:
            self._handlers[key] = lambda command, _phase: handler(command)
        return CommandResult(True)

    def submit(self, command: InteractionCommand) -> CommandResult[InteractionCommand]:
        return self._enqueue(command, require_accepting=True)

    def stage(self, command: InteractionCommand) -> CommandResult[InteractionCommand]:
        """Stage one bounded pre-start command for offline replay bootstrap."""

        action = str(getattr(command, "action", "") or "").strip()
        if action not in {"replay_last_assistant", "replay_chat_session"} and (
            runtime_hotkeys.parse_replay_chat_session_start_index(action) is None
        ):
            return _failure(
                "interaction_stage_unavailable",
                "Only replay controls may be staged before runtime start.",
            )
        return self._enqueue(command, require_accepting=False)

    def _enqueue(
        self,
        command: InteractionCommand,
        *,
        require_accepting: bool,
    ) -> CommandResult[InteractionCommand]:
        if not isinstance(command, InteractionCommand):
            return _failure("interaction_invalid_command", "Interaction commands must be typed.")
        with self._lock:
            if require_accepting and not self._accepting:
                return _failure("interaction_stopped", "Interaction commands are not accepting work.")
            if not self._known_action_locked(command.action):
                return _failure(
                    "interaction_unknown_action",
                    f"Unknown interaction action: {command.action}",
                )
            if len(self._queue) >= self._max_queue_size:
                return _failure(
                    "interaction_queue_full",
                    f"Interaction queue is full ({self._max_queue_size}).",
                )
            self._queue.append(command)
            self._last_triggered_at = float("-inf")
        return CommandResult(True, command)

    def next_command(self) -> CommandResult[InteractionCommand | None]:
        with self._lock:
            command = self._queue.popleft() if self._queue else None
        return CommandResult(True, command)

    def dispatch(
        self,
        command: InteractionCommand,
        *,
        phase: InteractionPhase = InteractionPhase.LISTENING,
        effects: InteractionCommandCapabilities | None = None,
    ) -> CommandResult[object]:
        if not isinstance(command, InteractionCommand):
            return _failure("interaction_invalid_command", "Interaction commands must be typed.")
        expected_phases = command.payload.get("expected_phases")
        if expected_phases:
            if isinstance(expected_phases, str):
                expected_phases = (expected_phases,)
            allowed_phases = {
                str(item or "").strip().lower()
                for item in expected_phases
                if str(item or "").strip()
            }
            if allowed_phases and phase.name.lower() not in allowed_phases:
                return CommandResult(
                    True,
                    InteractionDispatch(InteractionIntent.IGNORE, command, phase),
                )
        with self._lock:
            handler = self._handlers.get(command.action)
            if (
                handler is None
                and runtime_hotkeys.parse_replay_chat_session_start_index(
                    command.action
                )
                is not None
            ):
                handler = self._handlers.get("replay_chat_session_from")
        if handler is None:
            return _failure(
                "interaction_handler_missing",
                f"No handler is registered for {command.action}.",
            )
        try:
            dispatched = handler(command, phase)
            if not isinstance(dispatched, InteractionDispatch) or effects is None:
                return CommandResult(True, dispatched)
            effect_callback = getattr(
                effects,
                _EFFECT_BY_INTENT[dispatched.intent],
            )
            effect = (
                effect_callback(dispatched)
                if effect_callback is not None
                else InteractionEffectResult()
            )
            if effect is None:
                effect = InteractionEffectResult()
            if not isinstance(effect, InteractionEffectResult):
                raise TypeError("Interaction effects must return InteractionEffectResult")
            return CommandResult(
                True,
                InteractionDispatch(
                    dispatched.intent,
                    dispatched.command,
                    dispatched.phase,
                    effect,
                ),
            )
        except BaseException as exc:
            return _failure(
                "interaction_handler_failed",
                str(exc) or f"Interaction handler failed for {command.action}.",
                exc,
            )

    def bind_hotkeys(self, config: RuntimeConfigSnapshot) -> CommandResult[None]:
        values = config.values
        normalized = runtime_hotkeys.normalize_hotkey_settings(
            values.get("hotkeys"),
            legacy_push_to_talk=values.get("push_to_talk_hotkey"),
            legacy_manual=values.get("manual_action_hotkeys"),
            legacy_ui=values.get("ui_action_hotkeys"),
        )
        with self._binding_lock:
            with self._lock:
                if not self._accepting:
                    return _failure(
                        "interaction_stopped",
                        "Interaction hotkeys cannot bind while the service is stopped.",
                    )
            try:
                self._capabilities.bind_hotkeys()
            except BaseException as exc:
                return _failure("interaction_bind_failed", str(exc) or "Hotkey binding failed.", exc)
            with self._lock:
                stopped_during_bind = not self._accepting
                if not stopped_during_bind:
                    generation = self._bindings.generation + 1
                    self._bindings = InteractionBindings(
                        generation=generation,
                        bound=True,
                        config_revision=int(config.revision),
                        push_to_talk=str(normalized["push_to_talk"]),
                        manual_actions=MappingProxyType(dict(normalized["manual_actions"])),
                        ui_actions=MappingProxyType(dict(normalized["ui_actions"])),
                        input_mode=str(values.get("input_mode", "voice_activation") or "voice_activation").strip().lower(),
                        offline_replay_only=bool(values.get("offline_replay_only", False)),
                    )
                    self._last_triggered_at = float("-inf")
            if stopped_during_bind:
                try:
                    self._capabilities.unbind_hotkeys()
                except BaseException:
                    pass
                return _failure(
                    "interaction_stopped",
                    "Interaction stopped while hotkeys were binding.",
                )
        return CommandResult(True)

    def unbind_hotkeys(self) -> CommandResult[None]:
        with self._binding_lock:
            with self._lock:
                self._bindings = _empty_bindings(self._bindings.generation + 1)
                self._last_triggered_at = float("-inf")
            try:
                self._capabilities.unbind_hotkeys()
            except BaseException as exc:
                return _failure("interaction_unbind_failed", str(exc) or "Hotkey unbind failed.", exc)
        return CommandResult(True)

    def bindings(self) -> InteractionBindings:
        with self._lock:
            return self._bindings

    def pending_count(self) -> int:
        with self._lock:
            return len(self._queue)

    def suppress_push_to_talk_until_release(self) -> None:
        with self._lock:
            self._push_to_talk_suppressed_until_release = True

    def poll(self, source: object | None) -> CommandResult[InteractionCommand | None]:
        try:
            now = float(self._capabilities.clock())
        except BaseException as exc:
            return _failure("interaction_clock_failed", str(exc) or "Interaction clock failed.", exc)
        if self._safe_bool(self._capabilities.dry_run_active):
            return CommandResult(True)
        with self._lock:
            bindings = self._bindings
            if now - self._last_triggered_at < self._debounce_seconds:
                return CommandResult(True)
            queued = self._queue.popleft() if self._queue else None
        if queued is not None:
            if bindings.offline_replay_only and not _allowed_during_replay(queued.action):
                self._log(f"[Replay] Ignored unavailable replay action: {queued.action}")
                return CommandResult(True)
            self._mark_triggered(now)
            return CommandResult(True, queued)
        if bindings.bound:
            for action, binding in bindings.manual_actions.items():
                if not binding or not self._pressed(binding):
                    continue
                if bindings.offline_replay_only and not _allowed_during_replay(action):
                    self._log(f"[Replay] Ignored unavailable replay hotkey: {action}")
                    return CommandResult(True)
                self._mark_triggered(now)
                return CommandResult(True, InteractionCommand(action, source="hotkey"))
            push_to_talk_held = (
                self._safe_bool(self._capabilities.push_to_talk_gui_held)
                or self._pressed(bindings.push_to_talk)
            )
            if bindings.input_mode == "push_to_talk" and not push_to_talk_held:
                with self._lock:
                    self._push_to_talk_suppressed_until_release = False
            if source is not None and bindings.input_mode == "push_to_talk" and push_to_talk_held:
                with self._lock:
                    suppressed = self._push_to_talk_suppressed_until_release
                if suppressed:
                    return CommandResult(True)
                self._mark_triggered(now)
                return CommandResult(True, InteractionCommand("push_to_talk", source="hotkey"))
            if bindings.input_mode == "text_only":
                return CommandResult(True)
            if (
                source is not None
                and bindings.input_mode != "push_to_talk"
                and self._barge_in(source)
            ):
                return CommandResult(True, InteractionCommand("barge_in", source="speech"))
        return CommandResult(True)

    def _known_action_locked(self, action: str) -> bool:
        return (
            action in _MANUAL_ACTIONS
            or action in _INTERNAL_ACTIONS
            or action in self._handlers
            or runtime_hotkeys.parse_replay_chat_session_start_index(action) is not None
        )

    def _mark_triggered(self, now: float) -> None:
        with self._lock:
            self._last_triggered_at = float(now)

    def _pressed(self, binding: str) -> bool:
        try:
            return bool(self._capabilities.is_hotkey_pressed(str(binding or "")))
        except BaseException:
            return False

    def _barge_in(self, source: object) -> bool:
        try:
            return bool(self._capabilities.check_barge_in(source))
        except BaseException:
            return False

    @staticmethod
    def _safe_bool(callback: Callable[[], bool]) -> bool:
        try:
            return bool(callback())
        except BaseException:
            return False

    def _log(self, message: str) -> None:
        try:
            self._capabilities.logger(str(message))
        except BaseException:
            pass


def _allowed_during_replay(action: str) -> bool:
    return runtime_hotkeys.manual_action_allowed_during_replay(action)


_DEFAULT_ACTIONS = frozenset(
    {
        "conversation_action",
        "regenerate_response",
        "retry_user_input",
        "pause_speech",
        "skip_speech",
        "skip_user_reply",
        "replay_last_assistant",
        "replay_chat_session",
        "barge_in",
        "push_to_talk",
        "hidden_proactive_reply",
        "proactive_timeout",
    }
)

_LISTENING_INTENTS = {
    "conversation_action": InteractionIntent.CONVERSATION_ACTION,
    "regenerate_response": InteractionIntent.REGENERATE,
    "retry_user_input": InteractionIntent.RETRY_INPUT,
    "pause_speech": InteractionIntent.PAUSE_LISTENING,
    "skip_speech": InteractionIntent.FORCE_PROACTIVE,
    "skip_user_reply": InteractionIntent.CONTINUE_ASSISTANT,
    "replay_last_assistant": InteractionIntent.START_REPLAY,
    "replay_chat_session": InteractionIntent.START_REPLAY,
    "barge_in": InteractionIntent.CAPTURE_VOICE,
    "push_to_talk": InteractionIntent.CAPTURE_PUSH_TO_TALK,
    "hidden_proactive_reply": InteractionIntent.ACCEPT_PROACTIVE,
    "proactive_timeout": InteractionIntent.ACCEPT_PROACTIVE,
}

_REPLAY_INTENTS = {
    **{action: InteractionIntent.IGNORE for action in _DEFAULT_ACTIONS},
    "pause_speech": InteractionIntent.PAUSE_REPLAY,
    "skip_speech": InteractionIntent.SKIP_REPLAY,
    "replay_last_assistant": InteractionIntent.START_REPLAY,
    "replay_chat_session": InteractionIntent.START_REPLAY,
}

_SPEAKING_INTENTS = {
    **_LISTENING_INTENTS,
    "pause_speech": InteractionIntent.PAUSE_SPEECH,
    "skip_speech": InteractionIntent.SKIP_SPEECH,
    "skip_user_reply": InteractionIntent.IGNORE,
    "hidden_proactive_reply": InteractionIntent.IGNORE,
    "proactive_timeout": InteractionIntent.IGNORE,
}

_PHASE_INTENTS = {
    InteractionPhase.LISTENING: _LISTENING_INTENTS,
    InteractionPhase.REPLAY: _REPLAY_INTENTS,
    InteractionPhase.SPEAKING: _SPEAKING_INTENTS,
}

_EFFECT_BY_INTENT = {
    InteractionIntent.CONVERSATION_ACTION: "conversation_action",
    InteractionIntent.REGENERATE: "regenerate",
    InteractionIntent.RETRY_INPUT: "retry_input",
    InteractionIntent.PAUSE_LISTENING: "pause_listening",
    InteractionIntent.PAUSE_REPLAY: "pause_replay",
    InteractionIntent.PAUSE_SPEECH: "pause_speech",
    InteractionIntent.FORCE_PROACTIVE: "force_proactive",
    InteractionIntent.SKIP_REPLAY: "skip_replay",
    InteractionIntent.SKIP_SPEECH: "skip_speech",
    InteractionIntent.CONTINUE_ASSISTANT: "continue_assistant",
    InteractionIntent.START_REPLAY: "start_replay",
    InteractionIntent.CAPTURE_VOICE: "capture_voice",
    InteractionIntent.CAPTURE_PUSH_TO_TALK: "capture_push_to_talk",
    InteractionIntent.ACCEPT_PROACTIVE: "accept_proactive",
    InteractionIntent.IGNORE: "ignore",
}


def _intent_handler(action: str) -> _RegisteredInteractionHandler:
    def dispatch(
        command: InteractionCommand,
        phase: InteractionPhase,
    ) -> InteractionDispatch:
        intent = _PHASE_INTENTS.get(phase, _LISTENING_INTENTS).get(
            action,
            InteractionIntent.IGNORE,
        )
        return InteractionDispatch(intent, command, phase)

    return dispatch


def _failure(category: str, message: str, cause: BaseException | None = None):
    return CommandResult(False, failure=RuntimeFailure(category, message, cause))


__all__ = [
    "InteractionBindings",
    "InteractionCapabilities",
    "InteractionCommand",
    "InteractionCommandCapabilities",
    "InteractionDispatch",
    "InteractionEffectResult",
    "InteractionFlow",
    "InteractionIntent",
    "InteractionPhase",
    "InteractionService",
]
