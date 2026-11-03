"""Typed ownership for conversation-loop controls and dry-run reply state."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import random
import threading
from typing import Protocol

from core.conversation_flow_v2 import SpeechControlEvents
from core.runtime.config import RuntimeConfigSnapshot
from core.runtime.contracts import CommandResult
from core.runtime.interaction import InteractionBindings, InteractionCommand
from core.runtime.normal_chat import NormalChatApplicationBlocked


class InteractionRuntime(Protocol):
    """Narrow interaction surface used by the conversation loop."""

    def bindings(self) -> InteractionBindings: ...

    def bind_hotkeys(self, config: RuntimeConfigSnapshot) -> CommandResult[None]: ...

    def poll(
        self,
        source: object | None,
    ) -> CommandResult[InteractionCommand | None]: ...


class RuntimeConfigSnapshots(Protocol):
    def snapshot(self) -> RuntimeConfigSnapshot: ...


class PlaybackResumeRuntime(Protocol):
    def note_resume_requested(self, value: float) -> None: ...


class DryRunRuntime(Protocol):
    """Persistent dry-run session backend used by the reply owner."""

    def auto_replies_enabled(self) -> bool: ...

    def next_auto_reply(self) -> str | None: ...

    def begin_reply(
        self,
        runtime_config: Mapping[str, object],
        streamed: bool = False,
        proactive: bool = False,
    ) -> str | None: ...

    def finalize_reply(self, reply_id: str | None) -> object: ...


class TorchSeedRuntime(Protocol):
    class CudaRuntime(Protocol):
        def is_available(self) -> bool: ...
        def manual_seed(self, seed: int) -> None: ...
        def manual_seed_all(self, seed: int) -> None: ...

    cuda: CudaRuntime

    def manual_seed(self, seed: int) -> None: ...


class NumpySeedRuntime(Protocol):
    class RandomRuntime(Protocol):
        def seed(self, seed: int) -> None: ...

    random: RandomRuntime


@dataclass(frozen=True, slots=True)
class ConversationLoopControlSnapshot:
    stop_requested: bool
    listening: bool
    microphone_active: bool
    audio_playing: bool
    playback_stopping: bool
    manual_pause: bool
    pause_after_chunk: bool
    playback_paused: bool
    last_resume_requested_at: float


class ConversationLoopControlOwner:
    """Own the mutable control state consumed by the production loop."""

    def __init__(
        self,
        *,
        interaction: InteractionRuntime,
        config: RuntimeConfigSnapshots,
        playback: PlaybackResumeRuntime,
        continue_assistant_sentinel: str = "__CONTINUE_ASSISTANT__",
        blocked_error: type[BaseException] = NormalChatApplicationBlocked,
        logger: Callable[[str], None] = print,
    ) -> None:
        if not str(continue_assistant_sentinel or ""):
            raise ValueError("The continue-assistant sentinel cannot be empty.")
        if not isinstance(blocked_error, type) or not issubclass(
            blocked_error,
            BaseException,
        ):
            raise TypeError("blocked_error must be an exception type.")
        self._interaction = interaction
        self._config = config
        self._playback = playback
        self._continue_assistant_sentinel = str(continue_assistant_sentinel)
        self._blocked_error = blocked_error
        self._logger = logger
        self._controls = SpeechControlEvents(
            stop=threading.Event(),
            listening=threading.Event(),
            microphone=threading.Event(),
            audio_playing=threading.Event(),
            stop_playback=threading.Event(),
            manual_pause=threading.Event(),
            pause_after_chunk=threading.Event(),
            playback_paused=threading.Event(),
        )
        self._state_lock = threading.Lock()
        self._last_resume_requested_at = 0.0

    @property
    def controls(self) -> SpeechControlEvents:
        return self._controls

    @property
    def continue_assistant_sentinel(self) -> str:
        return self._continue_assistant_sentinel

    @property
    def blocked_error(self) -> type[BaseException]:
        return self._blocked_error

    @property
    def last_resume_requested_at(self) -> float:
        with self._state_lock:
            return self._last_resume_requested_at

    def snapshot(self) -> ConversationLoopControlSnapshot:
        with self._state_lock:
            last_resume_requested_at = self._last_resume_requested_at
        controls = self._controls
        return ConversationLoopControlSnapshot(
            stop_requested=controls.stop.is_set(),
            listening=controls.listening.is_set(),
            microphone_active=controls.microphone.is_set(),
            audio_playing=controls.audio_playing.is_set(),
            playback_stopping=controls.stop_playback.is_set(),
            manual_pause=controls.manual_pause.is_set(),
            pause_after_chunk=controls.pause_after_chunk.is_set(),
            playback_paused=controls.playback_paused.is_set(),
            last_resume_requested_at=last_resume_requested_at,
        )

    def prepare_run(self) -> None:
        # Legacy startup only reopened the stop gate. Other event state belongs to
        # the active speech/playback routes and must not be silently reset here.
        self._controls.stop.clear()

    def request_stop(self) -> None:
        from core.runtime.stop_diagnostics import record_runtime_event
        record_runtime_event("loop_stop_requested", caller=True)
        self._controls.stop.set()

    def check_interaction_status(
        self,
        source: object,
    ) -> InteractionCommand | str | None:
        snapshot = self._config.snapshot()
        if self._interaction.bindings().config_revision != snapshot.revision:
            rebound = self._interaction.bind_hotkeys(snapshot)
            if not rebound.accepted:
                message = (
                    rebound.failure.message
                    if rebound.failure is not None
                    else "unknown error"
                )
                self._logger(f"⚠️ [Interaction] Hotkey rebind failed: {message}")
        result = self._interaction.poll(source)
        if not result.accepted:
            message = (
                result.failure.message
                if result.failure is not None
                else "unknown error"
            )
            self._logger(f"⚠️ [Interaction] Poll failed: {message}")
            return None
        return result.value

    def set_last_resume_requested_at(self, timestamp: float) -> None:
        value = float(timestamp)
        with self._state_lock:
            self._last_resume_requested_at = value
        self._playback.note_resume_requested(value)


@dataclass(frozen=True, slots=True)
class DryRunReplySnapshot:
    auto_replies_enabled: bool
    replies_selected: int
    last_seed: int | None


class DryRunReplyOwner:
    """Serialize dry-run reply selection, accounting, and process RNG seeding."""

    def __init__(
        self,
        backend: DryRunRuntime,
        *,
        torch_runtime: TorchSeedRuntime | None = None,
        numpy_runtime: NumpySeedRuntime | None = None,
    ) -> None:
        self._backend = backend
        self._torch_runtime = torch_runtime
        self._numpy_runtime = numpy_runtime
        self._lock = threading.RLock()
        self._replies_selected = 0
        self._last_seed: int | None = None

    def dry_run_auto_replies_enabled(self) -> bool:
        with self._lock:
            return bool(self._backend.auto_replies_enabled())

    def next_dry_run_auto_reply(self) -> str | None:
        with self._lock:
            prompt = self._backend.next_auto_reply()
            if prompt is not None:
                self._replies_selected += 1
            return prompt

    def begin_dry_run_reply(
        self,
        config: Mapping[str, object],
        *,
        streamed: bool,
        proactive: bool,
    ) -> str | None:
        with self._lock:
            return self._backend.begin_reply(
                config,
                streamed=bool(streamed),
                proactive=bool(proactive),
            )

    def finalize_dry_run_reply(self, reply_id: str | None) -> None:
        with self._lock:
            self._backend.finalize_reply(reply_id)

    def set_seed(self, seed: int) -> None:
        value = int(seed)
        if not 0 <= value <= 2**32 - 1:
            raise ValueError(
                f"Seed must be between 0 and 2**32 - 1, got {value}"
            )
        with self._lock:
            from core.tts_seed_context import apply_seed
            apply_seed(value, torch_runtime=self._torch_runtime,
                       numpy_runtime=self._numpy_runtime)
            self._last_seed = value

    def snapshot(self) -> DryRunReplySnapshot:
        with self._lock:
            return DryRunReplySnapshot(
                auto_replies_enabled=bool(
                    self._backend.auto_replies_enabled()
                ),
                replies_selected=self._replies_selected,
                last_seed=self._last_seed,
            )


__all__ = [
    "ConversationLoopControlOwner",
    "ConversationLoopControlSnapshot",
    "DryRunReplyOwner",
    "DryRunReplySnapshot",
]
