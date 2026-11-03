"""Immutable conversation replay orchestration over speech and playback owners."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import threading
import time
from types import MappingProxyType
import uuid

from core.runtime.config import RuntimeConfigService, RuntimeConfigSnapshot
from core.runtime.contracts import CancellationToken, CommandResult, RuntimeFailure
from core.runtime.controllers import (
    ControllerCancellationSignal,
    ControllerSetupFailure,
    ControllerSetupLease,
    ControllerSetupRegistry,
    RouteEffectOwner,
)
from core.runtime.conversation import ConversationMessage, ConversationService
from core.runtime.identifiers import RouteGeneration, TurnId, WorkLease
from core.runtime.playback import (
    PlaybackReceipt,
    PlaybackService,
    ReplayPlaybackPreparation,
    ReplayPlaybackPipeline,
    ReplayPlaybackPipelineCapabilities,
    ReplayPlaybackRuntime,
)
from core.runtime.lifecycle import WorkerSupervisor
from core.runtime.speech_output import SpeechOutputService, SpeechOutputStream, SpeechPlan


VoiceResolver = Callable[[object], str]
Trace = Callable[[str, Mapping[str, object]], object]


def normalize_chat_replay_role_voices(value) -> dict[str, str]:
    """Return the legacy fixed-shape replay voice mapping."""
    raw = dict(value or {}) if isinstance(value, dict) else {}
    return {
        role: str(raw.get(role, "") or "").strip()
        for role in ("assistant", "user", "system")
    }


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class ReplayMessage:
    message_id: str
    role: str
    text: str
    metadata: Mapping[str, object]
    replay_index: int
    history_index: int
    voice_path: str
    label: str


@dataclass(frozen=True, slots=True)
class ReplayRequest:
    replay_id: str
    lease: WorkLease
    config: RuntimeConfigSnapshot
    messages: tuple[ReplayMessage, ...]
    kind: str
    replay_total: int


@dataclass(frozen=True, slots=True)
class ReplayReceipt:
    replay_id: str
    lease: WorkLease
    message_ids: tuple[str, ...]
    replay_indices: tuple[int, ...]
    speech_id: str
    playback_position: str
    cancellation_reason: str = ""
    playback_receipt: PlaybackReceipt | None = None
    kind: str = "assistant"


@dataclass(slots=True)
class _ReplayState:
    request: ReplayRequest
    token: CancellationToken
    stream: "_ReplayPreparedStream" | None = None
    receipt: ReplayReceipt | None = None
    starting: bool = False
    cancel_requested: bool = False
    setup: ControllerSetupLease | None = None
    route_owner: RouteEffectOwner | None = None


class _ReplayLookaheadGate:
    def __init__(self, replay_id: str, trace: Trace) -> None:
        self._replay_id = str(replay_id)
        self._trace = trace
        self._condition = threading.Condition()
        self._current_replay_index = 0
        self._seen: set[int] = set()

    def before_chunk(self, chunk, token: CancellationToken) -> None:
        metadata = getattr(chunk, "source_metadata", {}) or {}
        replay_index = int(metadata.get("replay_index", 0) or 0)
        if replay_index <= 0:
            return
        with self._condition:
            if replay_index in self._seen:
                return
            self._seen.add(replay_index)
            if not self._current_replay_index and int(
                metadata.get("replay_source_offset", 0) or 0
            ) == 0:
                self._current_replay_index = max(0, replay_index - 1)
        started_at = time.perf_counter()
        iterations = 0
        with self._condition:
            while (
                replay_index > max(1, self._current_replay_index + 1)
                and not token.cancelled
            ):
                iterations += 1
                self._condition.wait(0.05)
        self._trace_safely(
            "replay_lookahead_wait",
            {
                "trace_id": self._replay_id,
                "source_offset": int(metadata.get("replay_source_offset", 0) or 0),
                "replay_index": replay_index,
                "duration_ms": round(
                    max(0.0, (time.perf_counter() - started_at) * 1000.0),
                    3,
                ),
                "iterations": iterations,
                "blocked": bool(iterations),
            },
        )

    def advance(self, replay_index: int) -> None:
        value = int(replay_index or 0)
        if value <= 0:
            return
        with self._condition:
            if value > self._current_replay_index:
                self._current_replay_index = value
                self._condition.notify_all()

    def cancel(self) -> None:
        with self._condition:
            self._condition.notify_all()

    def _trace_safely(self, event: str, fields: Mapping[str, object]) -> None:
        try:
            self._trace(str(event), dict(fields))
        except BaseException:
            pass


class _ReplayPreparedStream:
    """Exact replay controls over one owned SpeechOutputStream."""

    @property
    def playback_callback_consumes_stream(self) -> bool:
        return bool(
            getattr(
                self._source,
                "playback_callback_consumes_stream",
                False,
            )
        )

    def __init__(
        self,
        source: SpeechOutputStream,
        lookahead: _ReplayLookaheadGate | None = None,
    ) -> None:
        self._source = source
        self._lookahead = lookahead
        self._lock = threading.Lock()
        self._current_replay_index = 0
        self._skip_through_index = 0

    @property
    def speech_id(self) -> str:
        return self._source.speech_id

    @property
    def lease(self) -> WorkLease:
        return self._source.lease

    @property
    def done(self) -> bool:
        return self._source.done

    @property
    def cancelled(self) -> bool:
        return self._source.cancelled

    @property
    def failure(self):
        return self._source.failure

    @property
    def playback_callback(self):
        return getattr(self._source, "playback_callback", None)

    def next_ready(self, timeout=None, *, admit_lease=None):
        while True:
            handoff = self._source.next_ready(timeout, admit_lease=admit_lease)
            if handoff is None:
                return None
            prepared = getattr(handoff, "chunk", handoff)
            metadata = getattr(prepared, "source_metadata", {}) or {}
            replay_index = int(metadata.get("replay_index", 0) or 0)
            with self._lock:
                skipped = replay_index > 0 and replay_index <= self._skip_through_index
                if not skipped:
                    self._current_replay_index = replay_index
            if not skipped and self._lookahead is not None:
                self._lookahead.advance(replay_index)
            if not skipped:
                return handoff
            self._source.discard_ready(prepared)

    def cancel(self, reason: str = "speech_cancelled") -> None:
        if self._lookahead is not None:
            self._lookahead.cancel()
        self._source.cancel(reason)

    def close(self) -> None:
        self._source.close()

    def mark_done(self) -> None:
        callback = getattr(self._source, "mark_done", None)
        if callable(callback):
            callback()

    def skip_current_message(self) -> bool:
        with self._lock:
            replay_index = self._current_replay_index
            if replay_index <= 0:
                return False
            self._skip_through_index = max(self._skip_through_index, replay_index)
        callback = getattr(self._source, "request_skip_current_message", None)
        if callable(callback):
            callback()
        return True

    @property
    def playback_callback_consumes_route(self) -> bool:
        return self.playback_callback_consumes_stream

    def current_replay_index(self) -> int:
        with self._lock:
            return self._current_replay_index

    def has_ready_message_after(self, index: int) -> bool:
        wanted = int(index)
        for prepared in self._source.ready_chunks():
            metadata = getattr(prepared, "source_metadata", {}) or {}
            if int(metadata.get("replay_index", 0) or 0) > wanted:
                return True
        return False

    def discard_ready(self, prepared: object) -> None:
        self._source.discard_ready(prepared)


class ReplayService:
    """Resolve current immutable messages, prepare speech, and submit playback."""

    name = "replay"

    def __init__(
        self,
        *,
        conversation: ConversationService,
        config: RuntimeConfigService,
        speech_output: SpeechOutputService,
        playback: PlaybackService,
        controllers: ControllerSetupRegistry,
        playback_pipeline: ReplayPlaybackPipeline | None = None,
        resolve_voice: VoiceResolver | None = None,
        replay_id_factory: Callable[[], str] | None = None,
        trace: Trace | None = None,
    ) -> None:
        self._conversation = conversation
        self._config = config
        self._speech_output = speech_output
        self._playback = playback
        self._controllers = controllers
        self._playback_pipeline = playback_pipeline
        self._resolve_voice = resolve_voice or (lambda value: str(value or "").strip())
        self._replay_id_factory = replay_id_factory or (lambda: uuid.uuid4().hex)
        self._trace = trace or (lambda _event, _fields: None)
        self._lock = threading.Lock()
        self._submission_lock = threading.RLock()
        self._active: dict[str, _ReplayState] = {}
        self._accepting = True

    def start(self) -> CommandResult[None]:
        with self._lock:
            self._accepting = True
        return CommandResult(True)

    def install_playback_pipeline(
        self,
        *,
        workers: WorkerSupervisor,
        capabilities: ReplayPlaybackPipelineCapabilities,
    ) -> CommandResult[None]:
        """Install the exact production replay pipeline before replay admission."""

        if not isinstance(workers, WorkerSupervisor):
            raise TypeError("Replay pipeline installation requires WorkerSupervisor.")
        if not isinstance(capabilities, ReplayPlaybackPipelineCapabilities):
            raise TypeError(
                "Replay pipeline installation requires "
                "ReplayPlaybackPipelineCapabilities."
            )
        pipeline = ReplayPlaybackPipeline(
            workers=workers,
            capabilities=capabilities,
        )
        with self._lock:
            if self._playback_pipeline is not None:
                return _failure(
                    "replay_pipeline_already_bound",
                    "The production replay pipeline is already installed.",
                )
            if self._active:
                return _failure(
                    "replay_pipeline_bind_busy",
                    "The production replay pipeline cannot change while replay is active.",
                )
            self._playback_pipeline = pipeline
            self._trace = capabilities.trace
        return CommandResult(True)

    def stop(self) -> CommandResult[None]:
        with self._lock:
            self._accepting = False
        cancelled = self.cancel_all("runtime_shutdown")
        if not cancelled.accepted:
            return CommandResult(False, failure=cancelled.failure)
        return CommandResult(True)

    def cancel_all(self, reason: str = "replay_cancelled") -> CommandResult[int]:
        with self._lock:
            replay_ids = tuple(self._active)
        failures = []
        for replay_id in replay_ids:
            cancelled = self.cancel(replay_id, reason=reason)
            if not cancelled.accepted and cancelled.failure is not None:
                failures.append(cancelled.failure)
        if failures:
            return CommandResult(False, failure=failures[0])
        return CommandResult(True, len(replay_ids))

    def replay_assistant_message(
        self,
        message_id: str,
        *,
        voice: str | None = None,
    ) -> CommandResult[ReplayReceipt]:
        frozen = self._freeze_current(
            selector=lambda messages: self._assistant_by_id(messages, message_id),
            explicit_voice=voice,
            session_mode=False,
            kind="assistant",
        )
        if not frozen.accepted or frozen.value is None:
            return CommandResult(False, failure=frozen.failure)
        return self._submit(frozen.value)

    def replay_assistant_at_history_index(
        self,
        history_index: int,
        *,
        voice: str | None = None,
    ) -> CommandResult[ReplayReceipt]:
        position = int(history_index)
        frozen = self._freeze_current(
            selector=lambda messages: self._assistant_at_index(messages, position),
            explicit_voice=voice,
            session_mode=False,
            kind="assistant",
        )
        if not frozen.accepted or frozen.value is None:
            return CommandResult(False, failure=frozen.failure)
        return self._submit(frozen.value)

    def replay_latest_assistant(
        self,
        *,
        voice: str | None = None,
    ) -> CommandResult[ReplayReceipt]:
        frozen = self._freeze_current(
            selector=self._latest_assistant,
            explicit_voice=voice,
            session_mode=False,
            kind="assistant",
        )
        if not frozen.accepted or frozen.value is None:
            return CommandResult(False, failure=frozen.failure)
        return self._submit(frozen.value)

    def stage_latest_assistant(
        self,
        *,
        voice: str | None = None,
    ) -> CommandResult[ReplayReceipt]:
        frozen = self._freeze_current(
            selector=self._latest_assistant,
            explicit_voice=voice,
            session_mode=False,
            kind="assistant",
        )
        if not frozen.accepted or frozen.value is None:
            return CommandResult(False, failure=frozen.failure)
        return self._stage(frozen.value)

    def replay_chat_session(
        self,
        *,
        start_index: int = 1,
    ) -> CommandResult[ReplayReceipt]:
        frozen = self._freeze_chat_session(start_index)
        if not frozen.accepted or frozen.value is None:
            return CommandResult(False, failure=frozen.failure)
        return self._submit(frozen.value)

    def stage_chat_session(
        self,
        *,
        start_index: int = 1,
    ) -> CommandResult[ReplayReceipt]:
        frozen = self._freeze_chat_session(start_index)
        if not frozen.accepted or frozen.value is None:
            return CommandResult(False, failure=frozen.failure)
        return self._stage(frozen.value)

    def start_replay(self, replay_id: str) -> CommandResult[ReplayReceipt]:
        key = str(replay_id or "").strip()
        with self._lock:
            state = self._active.get(key)
            if state is None:
                return _failure("replay_not_found", "The exact replay is not active.")
            if state.starting:
                return _failure("replay_start_in_progress", "The exact replay is already starting.")
            if state.stream is not None:
                return CommandResult(True, state.receipt)
            state.starting = True
        return self._execute(state)

    def cancel(
        self,
        replay_id: str,
        *,
        reason: str = "replay_cancelled",
    ) -> CommandResult[ReplayReceipt]:
        key = str(replay_id or "").strip()
        with self._lock:
            state = self._active.get(key)
            already_cancelling = bool(state is not None and state.cancel_requested)
            if state is not None and not already_cancelling:
                state.cancel_requested = True
                self._active.pop(key, None)
            stream = state.stream if state is not None else None
            setup = state.setup if state is not None else None
            route_owner = state.route_owner if state is not None else None
        if state is None:
            return _failure("replay_not_found", "The exact replay is not active.")
        if already_cancelling:
            return _failure("replay_cancel_in_progress", "The exact replay is already cancelling.")
        resolved_reason = str(reason or "replay_cancelled")
        state.token.cancel(resolved_reason)
        setup_cancellation = (
            self._controllers.cancel_setup(setup, resolved_reason)
            if setup is not None
            else CommandResult(True)
        )
        playback_receipt = None
        if stream is not None:
            cancelled_playback = self._playback.cancel_stream(
                stream,
                resolved_reason,
            )
            if cancelled_playback.accepted:
                playback_receipt = cancelled_playback.value
            else:
                stream.cancel(resolved_reason)
        route_invalidation = (
            self._controllers.invalidate_binding(
                state.request.lease,
                resolved_reason,
            )
            if route_owner is not None
            else CommandResult(True)
        )
        base = state.receipt or ReplayReceipt(
            replay_id=state.request.replay_id,
            lease=state.request.lease,
            message_ids=tuple(message.message_id for message in state.request.messages),
            replay_indices=tuple(message.replay_index for message in state.request.messages),
            speech_id=(stream.speech_id if stream is not None else ""),
            playback_position="",
            kind=state.request.kind,
        )
        receipt = ReplayReceipt(
            replay_id=base.replay_id,
            lease=base.lease,
            message_ids=base.message_ids,
            replay_indices=base.replay_indices,
            speech_id=base.speech_id,
            playback_position=base.playback_position,
            cancellation_reason=resolved_reason,
            playback_receipt=playback_receipt,
            kind=base.kind,
        )
        if not setup_cancellation.accepted:
            return CommandResult(False, receipt, setup_cancellation.failure)
        if not route_invalidation.accepted:
            return CommandResult(False, receipt, route_invalidation.failure)
        return CommandResult(True, receipt)

    def active_receipts(self) -> tuple[ReplayReceipt, ...]:
        self._reap_finished()
        with self._lock:
            return tuple(
                state.receipt
                for state in self._active.values()
                if state.receipt is not None
            )

    def is_active(self, replay_id: str) -> bool:
        key = str(replay_id or "").strip()
        with self._lock:
            return key in self._active

    def lease_is_current(self, lease: WorkLease) -> bool:
        with self._lock:
            owns_exact_replay = any(
                state.request.lease == lease
                and not state.cancel_requested
                and not state.token.cancelled
                for state in self._active.values()
            )
        return bool(
            owns_exact_replay
            and self._conversation.session_lease_is_current(lease)
        )

    def is_done(self, replay_id: str) -> bool:
        key = str(replay_id or "").strip()
        with self._lock:
            state = self._active.get(key)
        return state is None or self._state_done(state)

    def wait(self, replay_id: str, timeout: float | None = None) -> bool:
        key = str(replay_id or "").strip()
        deadline = None if timeout is None else time.monotonic() + max(0.0, float(timeout))
        while True:
            with self._lock:
                state = self._active.get(key)
            if state is None or self._state_done(state):
                return True
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(0.01)

    def finish(self, replay_id: str) -> CommandResult[ReplayReceipt]:
        key = str(replay_id or "").strip()
        with self._lock:
            state = self._active.get(key)
        if state is None:
            return _failure("replay_not_found", "The exact replay is not active.")
        if not self._state_done(state):
            return _failure("replay_still_active", "The exact replay has not finished.")
        with self._lock:
            if self._active.get(key) is not state:
                return _failure("replay_not_found", "The exact replay is no longer active.")
            self._active.pop(key, None)
        return CommandResult(True, state.receipt)

    def skip_current_message(self, replay_id: str) -> CommandResult[bool]:
        stream = self._prepared_stream(replay_id)
        if not stream.accepted or stream.value is None:
            return CommandResult(False, failure=stream.failure)
        try:
            skipped = bool(stream.value.skip_current_message())
            if not skipped:
                return CommandResult(True, False)
            if stream.value.playback_callback_consumes_route:
                return CommandResult(True, True)
            stopped = self._playback.skip_stream_chunk(stream.value)
            if not stopped.accepted:
                return CommandResult(False, failure=stopped.failure)
            return CommandResult(True, True)
        except BaseException as exc:
            return _failure("replay_skip_failed", str(exc) or "Replay skip failed.", exc)

    def skip_active_message(self) -> CommandResult[bool]:
        """Stop a response replay, or advance one message in a session replay."""

        with self._lock:
            replay_ids = tuple(self._active)
        if not replay_ids:
            return CommandResult(True, False)
        replay_id = replay_ids[-1]
        with self._lock:
            state = self._active.get(replay_id)
        if state is not None and state.request.kind == "assistant":
            cancelled = self.cancel(replay_id, reason="replay_skipped")
            return CommandResult(cancelled.accepted, cancelled.accepted, cancelled.failure)
        return self.skip_current_message(replay_id)

    def current_replay_index(self, replay_id: str) -> CommandResult[int]:
        stream = self._prepared_stream(replay_id)
        if not stream.accepted or stream.value is None:
            return CommandResult(False, failure=stream.failure)
        try:
            return CommandResult(True, stream.value.current_replay_index())
        except BaseException as exc:
            return _failure("replay_position_failed", str(exc) or "Replay position failed.", exc)

    def has_ready_message_after(self, replay_id: str, index: int) -> CommandResult[bool]:
        stream = self._prepared_stream(replay_id)
        if not stream.accepted or stream.value is None:
            return CommandResult(False, failure=stream.failure)
        try:
            return CommandResult(
                True,
                stream.value.has_ready_message_after(int(index)),
            )
        except BaseException as exc:
            return _failure("replay_lookahead_failed", str(exc) or "Replay lookahead failed.", exc)

    def pause(self, replay_id: str) -> CommandResult[None]:
        stream = self._prepared_stream(replay_id)
        if not stream.accepted or stream.value is None:
            return CommandResult(False, failure=stream.failure)
        return self._playback.pause_stream(stream.value)

    def resume(self, replay_id: str) -> CommandResult[None]:
        stream = self._prepared_stream(replay_id)
        if not stream.accepted or stream.value is None:
            return CommandResult(False, failure=stream.failure)
        return self._playback.resume_stream(stream.value)

    def collect_replayable_chat_entries(
        self,
        history: Sequence[Mapping[str, object]] | None = None,
    ) -> list[dict[str, object]]:
        messages = self._collection_messages(history)
        config = self._config.snapshot()
        entries = []
        replay_index = 0
        for history_index, message in enumerate(messages):
            content = str(message.content or "").strip()
            if not content:
                continue
            replay_index += 1
            label = _role_label(message)
            spoken = f"{label}: {content}" if label else content
            preview = " ".join((f"{label}: {content}" if label else content).split())
            entries.append(
                {
                    "replay_index": replay_index,
                    "history_index": history_index,
                    "message_id": message.message_id,
                    "role": message.role,
                    "origin": str(message.metadata.get("origin", "") or ""),
                    "label": label,
                    "content": content,
                    "spoken_text": spoken,
                    "voice_path": self._select_voice(message, config, None),
                    "preview": preview[:140] + ("..." if len(preview) > 140 else ""),
                }
            )
        return entries

    def collect_replayable_chat_messages(
        self,
        history: Sequence[Mapping[str, object]] | None = None,
    ) -> list[str]:
        return [
            str(item.get("spoken_text", "") or "")
            for item in self.collect_replayable_chat_entries(history)
        ]

    def collect_replayable_assistant_entries(
        self,
        history: Sequence[Mapping[str, object]] | None = None,
    ) -> list[dict[str, object]]:
        entries = []
        replay_index = 0
        for history_index, message in enumerate(self._collection_messages(history)):
            if not _is_assistant_reply(message):
                continue
            content = str(message.content or "").strip()
            if not content:
                continue
            replay_index += 1
            preview = " ".join(content.split())
            entries.append(
                {
                    "replay_index": replay_index,
                    "history_index": history_index,
                    "message_id": message.message_id,
                    "content": content,
                    "preview": preview[:140] + ("..." if len(preview) > 140 else ""),
                }
            )
        return entries

    def collect_replayable_assistant_messages(
        self,
        history: Sequence[Mapping[str, object]] | None = None,
    ) -> list[str]:
        return [
            str(item.get("content", "") or "")
            for item in self.collect_replayable_assistant_entries(history)
        ]

    def _collection_messages(
        self,
        history: Sequence[Mapping[str, object]] | None,
    ) -> tuple[ConversationMessage, ...]:
        if history is None:
            return self._conversation.snapshot().messages
        messages = []
        for index, item in enumerate(tuple(history or ())):
            if isinstance(item, ConversationMessage):
                messages.append(item)
                continue
            if not isinstance(item, Mapping):
                continue
            role = str(item.get("role", "") or "").strip().lower()
            content = str(item.get("content", "") or "")
            if not role or not content.strip():
                continue
            metadata = {
                str(key): _freeze(value)
                for key, value in item.items()
                if key not in {"role", "content", "message_id"}
            }
            messages.append(
                ConversationMessage(
                    message_id=str(item.get("message_id", "") or f"compat:{index}"),
                    role=role,
                    content=content,
                    metadata=MappingProxyType(metadata),
                )
            )
        return tuple(messages)

    def _freeze_current(
        self,
        *,
        selector,
        explicit_voice: str | None,
        session_mode: bool,
        replay_index_offset: int = 0,
        kind: str,
        requested_start_index: int | None = None,
    ) -> CommandResult[ReplayRequest]:
        with self._lock:
            if not self._accepting:
                return _failure("replay_stopped", "Replay is not accepting work.")
        session_lease = self._conversation.session_lease()
        admission = self._conversation.admit_session_effect(session_lease)
        if admission is None:
            return _failure("replay_stale_session", "The replay session changed before capture.")
        try:
            snapshot = self._conversation.snapshot()
            config = self._config.snapshot()
            selected = selector(snapshot.messages)
            normalized = _normalize_selection(selected, snapshot.messages)
            if not normalized:
                return _failure("replay_message_not_found", "No replayable message exists in the current session.")
            replay_total = len(normalized)
            if requested_start_index is not None:
                resolved_start = max(1, min(int(requested_start_index), replay_total))
                replay_index_offset = resolved_start - 1
                normalized = normalized[replay_index_offset:]
            replay_id = str(self._replay_id_factory() or "").strip()
            if not replay_id:
                return _failure("replay_invalid_identity", "Replay identity is empty.")
            lease = WorkLease(
                session_lease.run_id,
                session_lease.session_generation,
                TurnId(f"replay:{replay_id}"),
                RouteGeneration(1),
            )
            messages = []
            for offset, (history_index, message) in enumerate(normalized, start=1):
                content = str(message.content or "").strip()
                label = _role_label(message)
                text = f"{label}: {content}" if session_mode and label else content
                messages.append(
                    ReplayMessage(
                        message_id=str(message.message_id),
                        role=str(message.role or ""),
                        text=text,
                        metadata=_freeze(dict(message.metadata)),
                        replay_index=replay_index_offset + offset,
                        history_index=history_index,
                        voice_path=self._select_voice(message, config, explicit_voice),
                        label=label,
                    )
                )
            return CommandResult(
                True,
                ReplayRequest(
                    replay_id=replay_id,
                    lease=lease,
                    config=config,
                    messages=tuple(messages),
                    kind=str(kind or "assistant"),
                    replay_total=(replay_total if session_mode else len(messages)),
                ),
            )
        finally:
            self._conversation.release_session_effect(admission)

    def _freeze_chat_session(self, start_index: int) -> CommandResult[ReplayRequest]:
        try:
            requested_start = max(1, int(start_index or 1))
        except (TypeError, ValueError):
            requested_start = 1

        def select(messages: tuple[ConversationMessage, ...]):
            return tuple(
                (history_index, message)
                for history_index, message in enumerate(messages)
                if str(message.content or "").strip()
            )

        return self._freeze_current(
            selector=select,
            explicit_voice=None,
            session_mode=True,
            kind="session",
            requested_start_index=requested_start,
        )

    def _stage(self, request: ReplayRequest) -> CommandResult[ReplayReceipt]:
        # Serialize replacement admission, but leave the state lock free while
        # exact stream/controller cancellation invokes external callbacks.
        with self._submission_lock:
            with self._lock:
                if not self._accepting:
                    return _failure("replay_stopped", "Replay is not accepting work.")
                if request.replay_id in self._active:
                    return _failure("replay_invalid_identity", "Replay identity is already active.")
            cancelled = self.cancel_all("replay_replaced")
            if not cancelled.accepted:
                return CommandResult(False, failure=cancelled.failure)
            return self._stage_replacement(request)

    def _stage_replacement(self, request: ReplayRequest) -> CommandResult[ReplayReceipt]:
        receipt = ReplayReceipt(
            replay_id=request.replay_id,
            lease=request.lease,
            message_ids=tuple(message.message_id for message in request.messages),
            replay_indices=tuple(message.replay_index for message in request.messages),
            speech_id="",
            playback_position="pending",
            kind=request.kind,
        )
        with self._lock:
            if not self._accepting:
                return _failure("replay_stopped", "Replay is not accepting work.")
            if request.replay_id in self._active:
                return _failure(
                    "replay_invalid_identity",
                    "Replay identity is already active.",
                )
            token = CancellationToken()
            setup = self._controllers.begin(
                request.lease,
                ControllerCancellationSignal.from_token(token),
            )
            if not setup.accepted or setup.value is None:
                return CommandResult(False, failure=setup.failure)
            state = _ReplayState(
                request=request,
                token=token,
                receipt=receipt,
                setup=setup.value,
            )
            self._active[request.replay_id] = state
        return CommandResult(True, receipt)

    def _submit(self, request: ReplayRequest) -> CommandResult[ReplayReceipt]:
        staged = self._stage(request)
        if not staged.accepted:
            return staged
        return self.start_replay(request.replay_id)

    def _execute(self, state: _ReplayState) -> CommandResult[ReplayReceipt]:
        request = state.request
        token = state.token
        setup = state.setup
        source_stream: SpeechOutputStream | None = None
        stream: _ReplayPreparedStream | None = None
        pipeline_preparation: ReplayPlaybackPreparation | None = None
        playback_owner = None
        route_owner = None
        replay_indices = tuple(message.replay_index for message in request.messages)
        self._trace_safely(
            "replay_service_start",
            {
                "trace_id": request.replay_id,
                "item_count": len(request.messages),
                "first_index": replay_indices[0] if replay_indices else 0,
                "last_index": replay_indices[-1] if replay_indices else 0,
                "kind": request.kind,
            },
        )
        try:
            warmed = self._speech_output.warm_voice_paths(
                request.config,
                request.lease,
                tuple(message.voice_path for message in request.messages),
                token,
            )
            if token.cancelled:
                return _failure(
                    "replay_cancelled",
                    token.reason or "Replay was cancelled during voice warmup.",
                )
            if not warmed.accepted and warmed.failure is not None:
                if warmed.failure.category == "replay_voice_warmup_timeout":
                    token.cancel("replay_voice_warmup_timeout")
                    with self._lock:
                        if self._active.get(request.replay_id) is state:
                            self._active.pop(request.replay_id, None)
                    return CommandResult(False, failure=warmed.failure)
            plan = self._plan(request)
            lookahead = _ReplayLookaheadGate(request.replay_id, self._trace)
            source_stream = self._speech_output.prepare(
                plan,
                request.lease,
                token,
                before_chunk=lookahead.before_chunk,
                start=self._playback_pipeline is None,
            )
            playback_stream = source_stream
            if self._playback_pipeline is not None:
                if setup is None:
                    return _failure(
                        "controller_setup_stale",
                        "Replay setup ownership was not published before preparation.",
                    )
                started_at = time.monotonic()
                if plan.chunks:
                    started_at = float(
                        plan.chunks[0].source_metadata.get(
                            "tts_pipeline_started_at",
                            started_at,
                        )
                        or started_at
                    )
                pipeline_preparation = self._playback_pipeline.prepare(
                    source_stream,
                    ReplayPlaybackRuntime(
                        replay_id=request.replay_id,
                        lease=request.lease,
                        config=request.config.values,
                        source_text=plan.source_text,
                        started_at=started_at,
                        controller_registry=self._controllers,
                        setup=setup,
                    ),
                    token,
                )
                playback_stream = pipeline_preparation.stream
            stream = _ReplayPreparedStream(playback_stream, lookahead)
            with self._lock:
                current = self._active.get(request.replay_id)
                stale_before_enqueue = (
                    current is not state
                    or state.cancel_requested
                    or token.cancelled
                )
            if stale_before_enqueue:
                if setup is not None:
                    self._controllers.cancel_setup(
                        setup,
                        token.reason or "replay_cancelled",
                    )
                stream.cancel(token.reason or "replay_cancelled")
                stream.close()
                return _failure(
                    "replay_cancelled",
                    "Replay was cancelled before playback submission.",
                )
            if pipeline_preparation is not None:
                reserved = self._playback.reserve_owner(request.lease)
                if not reserved.accepted or reserved.value is None:
                    return CommandResult(False, failure=reserved.failure)
                playback_owner = reserved.value
                setup_publication = self._controllers.publish_transfer(
                    setup,
                    pipeline_preparation.registration,
                )
                if not setup_publication.accepted:
                    self._playback.release_owner(playback_owner)
                    raise ControllerSetupFailure(
                        setup_publication.failure
                        or RuntimeFailure(
                            "controller_setup_stale",
                            "Replay setup ownership could not be published.",
                        )
                    )
                route_activation = self._controllers.activate_route(
                    pipeline_preparation.registration,
                    playback_owner,
                )
                if not route_activation.accepted or route_activation.value is None:
                    self._playback.release_owner(playback_owner)
                    raise ControllerSetupFailure(
                        route_activation.failure
                        or RuntimeFailure(
                            "route_effect_stale",
                            "Replay route lost exact effect authority.",
                        )
                    )
                route_owner = route_activation.value
                with self._lock:
                    current = self._active.get(request.replay_id)
                    stale_before_enqueue = (
                        current is not state
                        or state.cancel_requested
                        or token.cancelled
                    )
                    if not stale_before_enqueue:
                        state.stream = stream
                        state.setup = None
                        state.route_owner = route_owner
                if stale_before_enqueue:
                    self._controllers.invalidate_binding(
                        request.lease,
                        token.reason or "replay_cancelled",
                    )
                    stream.cancel(token.reason or "replay_cancelled")
                    stream.close()
                    return _failure(
                        "replay_cancelled",
                        "Replay was cancelled before worker start.",
                    )
                speech_started = self._speech_output.start_preparation(
                    source_stream,
                    plan,
                    before_chunk=lookahead.before_chunk,
                    route_effect_owner=route_owner,
                )
                pipeline_started = pipeline_preparation.start(route_owner)
                if not speech_started.accepted or not pipeline_started.accepted:
                    failure = speech_started.failure or pipeline_started.failure
                    stream.cancel("replay_pipeline_start_failed")
                    stream.close()
                    return CommandResult(False, failure=failure)
            else:
                if setup is None:
                    return _failure(
                        "controller_setup_stale",
                        "Replay setup ownership is missing.",
                    )
                setup_publication = self._controllers.retire_setup(setup)
                if not setup_publication.accepted:
                    raise ControllerSetupFailure(
                        setup_publication.failure
                        or RuntimeFailure(
                            "controller_setup_stale",
                            "Replay setup ownership could not be retired.",
                        )
                    )
                with self._lock:
                    current = self._active.get(request.replay_id)
                    stale_before_enqueue = (
                        current is not state
                        or state.cancel_requested
                        or token.cancelled
                    )
                    if not stale_before_enqueue:
                        state.stream = stream
                        state.setup = None
                if stale_before_enqueue:
                    stream.cancel(token.reason or "replay_cancelled")
                    stream.close()
                    return _failure(
                        "replay_cancelled",
                        "Replay was cancelled before playback submission.",
                    )
            if token.cancelled:
                stream.cancel(token.reason or "replay_cancelled")
                stream.close()
                return _failure(
                    "replay_cancelled",
                    "Replay was cancelled before playback submission.",
                )
            offered = self._playback.enqueue(
                stream,
                request.lease,
                owner=playback_owner,
                route_effect_owner=route_owner,
            )
            if not offered.accepted:
                stream.cancel("replay_playback_rejected")
                stream.close()
                with self._lock:
                    if self._active.get(request.replay_id) is state:
                        self._active.pop(request.replay_id, None)
                return CommandResult(False, failure=offered.failure)
            receipt = ReplayReceipt(
                replay_id=request.replay_id,
                lease=request.lease,
                message_ids=tuple(message.message_id for message in request.messages),
                replay_indices=tuple(message.replay_index for message in request.messages),
                speech_id=stream.speech_id,
                playback_position=str(offered.value or ""),
                kind=request.kind,
            )
            with self._lock:
                current = self._active.get(request.replay_id)
                stale_after_enqueue = (
                    current is not state
                    or state.cancel_requested
                    or token.cancelled
                )
                if not stale_after_enqueue:
                    state.receipt = receipt
            if stale_after_enqueue:
                self._playback.cancel_stream(
                    stream,
                    token.reason or "replay_cancelled",
                )
                return _failure(
                    "replay_cancelled",
                    "Replay was cancelled during playback submission.",
                )
            return CommandResult(True, receipt)
        except BaseException as exc:
            token.cancel("replay_submit_failed")
            if stream is not None:
                try:
                    stream.cancel("replay_submit_failed")
                except BaseException:
                    pass
                try:
                    stream.close()
                except BaseException:
                    pass
            elif source_stream is not None and not source_stream.closed:
                try:
                    source_stream.cancel("replay_submit_failed")
                except BaseException:
                    pass
                try:
                    source_stream.close()
                except BaseException:
                    pass
            with self._lock:
                if self._active.get(request.replay_id) is state:
                    self._active.pop(request.replay_id, None)
            if isinstance(exc, ControllerSetupFailure):
                return CommandResult(False, failure=exc.failure)
            return _failure("replay_submit_failed", str(exc) or "Replay submission failed.", exc)
        finally:
            pending_setup = state.setup
            if pending_setup is not None:
                self._controllers.cancel_setup(
                    pending_setup,
                    token.reason or "replay_setup_retired",
                )
            with self._lock:
                current = self._active.get(request.replay_id)
                if current is state:
                    state.starting = False

    def _trace_safely(self, event: str, fields: Mapping[str, object]) -> None:
        try:
            self._trace(str(event), dict(fields))
        except BaseException:
            pass

    def _prepared_stream(self, replay_id: str) -> CommandResult[_ReplayPreparedStream]:
        key = str(replay_id or "").strip()
        with self._lock:
            state = self._active.get(key)
            stream = state.stream if state is not None else None
        if state is None:
            return _failure("replay_not_found", "The exact replay is not active.")
        if stream is None:
            return _failure("replay_control_unavailable", "This replay route has no runtime controls.")
        return CommandResult(True, stream)

    def _state_done(self, state: _ReplayState) -> bool:
        if state.token.cancelled:
            return True
        stream = state.stream
        if stream is None or not stream.done:
            return False
        snapshot = self._playback.snapshot()
        return not any(
            route is not None and getattr(route, "stream", None) is stream
            for route in (snapshot.current, snapshot.next)
        )

    def _reap_finished(self) -> None:
        with self._lock:
            candidates = tuple(self._active.items())
        finished = tuple(
            (replay_id, state)
            for replay_id, state in candidates
            if self._state_done(state)
        )
        with self._lock:
            for replay_id, state in finished:
                if self._active.get(replay_id) is state:
                    self._active.pop(replay_id, None)

    def _plan(self, request: ReplayRequest) -> SpeechPlan:
        chunks = []
        next_index = 0
        terminal_expression = "neutral"
        pipeline_started_at = time.monotonic()
        for source_offset, message in enumerate(request.messages):
            source_metadata = dict(message.metadata)
            source_metadata.update(
                {
                    "replay_id": request.replay_id,
                    "replay_message_id": message.message_id,
                    "replay_index": message.replay_index,
                    "replay_source_offset": source_offset,
                    "replay_total": request.replay_total,
                    "replay_label": message.label,
                    "replay": True,
                    "tts_replay": True,
                    "tts_trace_id": request.replay_id,
                    "tts_pipeline_started_at": pipeline_started_at,
                    "publish_tts_addon_events": True,
                }
            )
            # Each replayed response retains its author's registered moods even
            # when a different quick persona is active now.
            persona = message.metadata.get("quick_persona")
            mood_tags = persona.get("mood_tags") if isinstance(persona, Mapping) else None
            message_config = request.config
            if isinstance(mood_tags, Mapping):
                message_config = RuntimeConfigSnapshot(request.config.revision,
                    _freeze({**dict(request.config.values), "persona_mood_tags": dict(mood_tags)}))
            plan = self._speech_output.plan(
                message.text,
                message_config,
                start_index=next_index,
                initial_expression=terminal_expression,
                voice_path=message.voice_path,
                source_metadata=source_metadata,
            )
            chunks.extend(plan.chunks)
            if plan.chunks:
                next_index = plan.chunks[-1].index + 1
            terminal_expression = plan.terminal_expression
        return SpeechPlan(
            source_text="\n".join(message.text for message in request.messages),
            chunks=tuple(chunks),
            config=request.config,
            terminal_expression=terminal_expression,
        )

    def _select_voice(
        self,
        message: ConversationMessage,
        config: RuntimeConfigSnapshot,
        explicit_voice: str | None,
    ) -> str:
        metadata = message.metadata
        stored = (
            metadata.get("replay_voice_path")
            or metadata.get("voice_path")
            or metadata.get("tts_voice_path")
            or ""
        )
        role = str(message.role or "").strip().lower()
        origin = str(metadata.get("origin", "") or "").strip().lower()
        key = "assistant" if role == "assistant" and origin == "assistant_reply" else (
            "system" if role == "system" else "user"
        )
        role_voices = config.values.get("chat_replay_role_voices", {})
        role_voices = role_voices if isinstance(role_voices, Mapping) else {}
        configured = role_voices.get(key, "")
        if key == "system" and not configured:
            configured = role_voices.get("assistant", "")
        current = config.values.get("voice_path") or config.values.get("voice_file") or ""
        candidates = []
        explicit = str(explicit_voice or "").strip()
        if explicit and explicit.lower() != "stored":
            candidates.append(explicit)
        candidates.extend((stored, configured, current))
        for candidate in candidates:
            try:
                resolved = str(self._resolve_voice(candidate) or "").strip()
            except BaseException:
                resolved = ""
            if resolved:
                return resolved
        return ""

    @staticmethod
    def _assistant_by_id(messages: Sequence[ConversationMessage], message_id: str):
        wanted = str(message_id or "").strip()
        for index, message in enumerate(messages):
            if message.message_id == wanted and _is_assistant_reply(message):
                return index, message
        return None

    @staticmethod
    def _assistant_at_index(
        messages: Sequence[ConversationMessage],
        history_index: int,
    ):
        position = int(history_index)
        if position < 0 or position >= len(messages):
            return None
        message = messages[position]
        if not _is_assistant_reply(message):
            return None
        return position, message

    @staticmethod
    def _latest_assistant(messages: Sequence[ConversationMessage]):
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if _is_assistant_reply(message) and str(message.content or "").strip():
                return index, message
        return None


def _normalize_selection(selected, messages):
    if selected is None:
        return ()
    if (
        isinstance(selected, tuple)
        and len(selected) == 2
        and isinstance(selected[0], int)
        and isinstance(selected[1], ConversationMessage)
    ):
        return (selected,)
    normalized = []
    for item in tuple(selected or ()):
        if (
            isinstance(item, tuple)
            and len(item) == 2
            and isinstance(item[0], int)
            and isinstance(item[1], ConversationMessage)
        ):
            normalized.append(item)
        elif isinstance(item, ConversationMessage):
            normalized.append((messages.index(item), item))
    return tuple(normalized)


def _is_assistant_reply(message: ConversationMessage) -> bool:
    return (
        str(message.role or "").strip().lower() == "assistant"
        and str(message.metadata.get("origin", "") or "").strip().lower()
        == "assistant_reply"
        and bool(str(message.content or "").strip())
    )


def _role_label(message: ConversationMessage) -> str:
    role = str(message.role or "").strip().lower()
    origin = str(message.metadata.get("origin", "") or "").strip().lower()
    if role == "assistant" and origin == "assistant_reply":
        return "Assistant"
    if role == "assistant":
        return "User as assistant"
    if role == "system":
        return "System"
    if role == "tool":
        return "Tool"
    return "User"


def _failure(category: str, message: str, cause: BaseException | None = None):
    return CommandResult(False, failure=RuntimeFailure(category, message, cause))


__all__ = [
    "ReplayMessage",
    "ReplayReceipt",
    "ReplayRequest",
    "ReplayService",
    "normalize_chat_replay_role_voices",
]
