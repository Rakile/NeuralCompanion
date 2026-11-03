"""Immutable phone-reply control contracts shared with remote addons."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal
from collections import deque
from collections.abc import Callable, Mapping
from concurrent.futures import Future
import copy
import hashlib
import logging
import threading
import time
from types import MappingProxyType

from core.runtime.identifiers import WorkLease

_LOG = logging.getLogger(__name__)

if TYPE_CHECKING:
    from core.runtime.conversation import ConversationService
    from core.runtime.conversation_owners import ConversationHistoryRuntimeOwner
    from core.runtime.normal_chat import NormalChatApplicationAdapter


@dataclass(frozen=True, slots=True)
class PhoneReplyScope:
    phone_request_id: str
    normal_chat_transaction_id: str
    session_generation: int


@dataclass(frozen=True, slots=True)
class PhoneReplyResult:
    status: Literal["accepted", "duplicate", "stale", "unavailable", "busy"]
    phone_request_id: str
    next_phone_request_id: str | None = None


def assistant_interruption_text(delivered_chunks: tuple[str, ...]) -> str:
    prefix = " ".join(text.strip() for text in delivered_chunks if text.strip())
    return prefix + " ... (user interrupted)" if prefix else ""


@dataclass(frozen=True, slots=True)
class PhoneReplyEvent:
    scope: PhoneReplyScope
    kind: Literal["bound", "producer_finished", "cancelled", "superseded", "playback_stop_requested"]
    producer_complete: bool = False
    playback_stop_requested: bool = False


class PhoneReplySpeechBinding:
    """One captured request's route; early suppression survives route creation."""
    def __init__(self):
        self.route = None
        self.stream = None
        self.suppressed = False

    def attach_route(self, route):
        self.route = route
        if self.suppressed:
            route.request_playback_skip()

    def skip_audio(self):
        self.suppressed = True
        if self.route is not None:
            self.route.request_playback_skip()

    def cancel_provider(self):
        if self.stream is not None:
            self.stream.cancel_requested.set()


class PhoneReplyControlPort:
    """Submission-only capability. Owner attachment/history are never exported."""
    __slots__ = ("__submit", "__subscribe", "__available", "conversation_actions")

    def __init__(self, submit, subscribe, available, conversation_actions=None):
        self.__submit = submit
        self.__subscribe = subscribe
        self.__available = available
        self.conversation_actions = conversation_actions

    @property
    def available(self) -> bool:
        return bool(self.__available())

    def skip(self, scope: PhoneReplyScope, operation_id: str) -> Future[PhoneReplyResult]:
        return self.__submit("skip", scope, operation_id, ())

    def playback_finished(self, scope: PhoneReplyScope, operation_id: str) -> Future[PhoneReplyResult]:
        return self.__submit("playback_finished", scope, operation_id, ())

    def hold(self, scope: PhoneReplyScope, interruption_id: str) -> Future[PhoneReplyResult]:
        return self.__submit("hold", scope, interruption_id, ())

    def resolve(self, scope: PhoneReplyScope, interruption_id: str, delivered_chunks: tuple[str, ...],
                transcript: str, next_request_id: str, next_metadata: Mapping[str, object], *,
                claim: Callable[[], bool] | None = None) -> Future[PhoneReplyResult]:
        return self.__submit("resolve", scope, interruption_id,
                             (delivered_chunks, transcript, next_request_id, next_metadata, claim))

    def abandon(self, scope: PhoneReplyScope, interruption_id: str) -> Future[PhoneReplyResult]:
        return self.__submit("abandon", scope, interruption_id, ())

    def subscribe(self, listener: Callable[[PhoneReplyEvent], None]) -> Callable[[], None]:
        return self.__subscribe(listener)

    def _for_generation(self, is_open: Callable[[], bool], on_subscribe=None) -> PhoneReplyControlPort:
        """Re-check addon generation both on submission and owner execution."""
        def submit(kind, scope, operation_id, payload, guard=lambda: True):
            if not is_open() or not guard():
                return _finished(PhoneReplyResult("unavailable", scope.phone_request_id))
            return self.__submit(kind, scope, operation_id, payload, lambda: is_open() and guard())
        def subscribe(listener):
            if not is_open():
                return lambda: None
            unsubscribe = self.__subscribe(lambda event: listener(event) if is_open() else None)
            if on_subscribe is not None:
                on_subscribe(unsubscribe)
            return unsubscribe
        actions = self.conversation_actions
        return PhoneReplyControlPort(submit, subscribe, lambda: is_open() and self.available,
            actions.for_generation(is_open) if actions is not None else None)


@dataclass(slots=True)
class _Binding:
    scope: PhoneReplyScope
    context: Mapping[str, object]
    lease: WorkLease
    initial: _HistoryAnchor
    skip_audio: Callable[[], None]
    cancel_provider: Callable[[], None]
    held: str = ""
    deadline: float = 0.0
    interrupted: bool = False
    skipped: bool = False
    finished_at: float | None = None
    terminal_id: str = ""
    result: PhoneReplyResult | None = None
    resolving: Future | None = None
    requires_playback_completion: bool = False
    playback_finished_at: float | None = None
    playback_stop_requested: bool = False


@dataclass(frozen=True, slots=True)
class _HistoryAnchor:
    revision: int
    count: int
    fingerprint: bytes


def _fingerprint(messages):
    digest = hashlib.sha256()
    for message in messages:
        digest.update(repr(message).encode("utf-8"))
        digest.update(b"\0")
    return digest.digest()


@dataclass(frozen=True, slots=True)
class _Command:
    kind: str
    scope: PhoneReplyScope
    operation_id: str
    payload: tuple
    future: Future
    deadline: float
    is_open: Callable[[], bool]
    text_bytes: int


@dataclass(slots=True)
class _Subscriber:
    listener: Callable[[PhoneReplyEvent], None]
    pending: deque
    active: bool = True
    delivering: bool = False


def _finished(result):
    future = Future()
    future.set_result(result)
    return future


class PhoneReplyControls:
    """Bounded mailbox; only the conversation loop may drain or write history."""
    MAX_RECORDS = 256
    MAX_COMMANDS = 256
    LEASE_SECONDS = 120.0
    RETENTION_SECONDS = 900.0

    def __init__(self, conversation: ConversationService, history: ConversationHistoryRuntimeOwner,
                 normal_chat: NormalChatApplicationAdapter,
                 submit_accepted_turn: Callable[..., Mapping[str, object]], *,
                 clock: Callable[[], float] = time.monotonic):
        self._conversation = conversation
        self._history = history
        self._normal_chat = normal_chat
        self._accept = submit_accepted_turn
        self._clock = clock
        self._lock = threading.Lock()
        self._commands = deque()
        self._queued_text_bytes = 0
        self._producer_notifications = set()
        self._bindings = {}
        self._listeners = {}
        self._events = {}
        self._next_listener = 0
        self._running = False
        self.accepted_turn_serial = 0
        self._owner_thread = None
        self._port = PhoneReplyControlPort(self._submit, self.subscribe, self._available)

    def port(self) -> PhoneReplyControlPort:
        return self._port

    def _available(self):
        with self._lock:
            return self._running

    def start(self) -> None:
        self._owner_thread = threading.get_ident()
        with self._lock:
            self._running = True

    def _assert_owner(self):
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError("Phone reply attachment/drain requires the conversation owner thread.")

    def stop(self) -> None:
        self._assert_owner()
        with self._lock:
            self._running = False
            commands = tuple(self._commands)
            self._commands.clear()
            self._queued_text_bytes -= sum(command.text_bytes for command in commands)
            self._producer_notifications.clear()
        for command in commands:
            self._finish(command, "unavailable")
        for binding in tuple(self._bindings.values()):
            self._publish(PhoneReplyEvent(binding.scope, "cancelled"))
        self._bindings.clear()
        with self._lock:
            self._events.clear()

    def bind(self, scope, request_context, skip_audio, cancel_provider, *, require_playback_completion=False) -> None:
        self._assert_owner()
        if not self._valid_scope(scope) or request_context.get("phone_reply_control") is not True:
            return
        if scope in self._bindings:
            return
        self._expire()
        if len(self._bindings) >= self.MAX_RECORDS:
            return
        transaction = self._normal_chat.transaction_for_request(request_context)
        turn = transaction.get("turn_snapshot") if transaction else None
        if (turn is None or request_context.get("remote_capture_id") != scope.phone_request_id
                or request_context.get("normal_chat_transaction_id") != scope.normal_chat_transaction_id
                or turn.lease.session_generation.value != scope.session_generation):
            return
        initial = self._conversation.snapshot()
        if not initial.messages or initial.messages[-1].metadata.get("normal_chat_transaction_id") != scope.normal_chat_transaction_id:
            return
        context = MappingProxyType(copy.deepcopy({key: request_context[key] for key in (
            "normal_chat_transaction_id", "session_generation", "identity_relay_metadata", "assistant_persona"
        ) if key in request_context}))
        anchor = _HistoryAnchor(initial.revision, len(initial.messages), _fingerprint(initial.messages))
        self._bindings[scope] = _Binding(scope, context, turn.lease, anchor, skip_audio, cancel_provider,
                                         requires_playback_completion=require_playback_completion is True)
        self._publish(PhoneReplyEvent(scope, "bound"))

    @staticmethod
    def _valid_scope(scope):
        return (type(scope) is PhoneReplyScope and type(scope.phone_request_id) is str
                and type(scope.normal_chat_transaction_id) is str and type(scope.session_generation) is int)

    def _submit(self, kind, scope, operation_id, payload, is_open=lambda: True):
        text_bytes = 0
        if not self._valid_scope(scope):
            return _finished(PhoneReplyResult("unavailable", ""))
        if type(operation_id) is not str or not 1 <= len(operation_id) <= 128:
            return _finished(PhoneReplyResult("unavailable", scope.phone_request_id))
        if kind == "resolve":
            chunks, transcript, next_id, metadata, claim = payload
            if (type(chunks) is not tuple or len(chunks) > 2048
                    or any(type(item) is not str for item in chunks)
                    or sum(len(item.encode("utf-8")) for item in chunks) > 1024 * 1024
                    or type(transcript) is not str or len(transcript) > 1024 * 1024
                    or type(next_id) is not str or not 1 <= len(next_id) <= 128
                    or not isinstance(metadata, Mapping) or (claim is not None and not callable(claim))):
                return _finished(PhoneReplyResult("unavailable", scope.phone_request_id))
            # Only the existing server-built resolution options cross this seam.
            metadata = {key: value for key, value in metadata.items() if key in (
                "phone_reply_control", "phone_shared_queue", "normal_chat_output_token_cap", "nc_skip_image_attachment")
                and type(value) in (bool, int)}
            payload = (chunks, transcript, next_id, MappingProxyType(metadata), claim)
            text_bytes = sum(len(item.encode("utf-8")) for item in chunks) + len(transcript.encode("utf-8"))
        future = Future()
        command = _Command(kind, scope, operation_id, payload, future,
                           self._clock() + self.LEASE_SECONDS, is_open, text_bytes)
        with self._lock:
            status = ("unavailable" if not self._running or self._queued_text_bytes + text_bytes > 8 * 1024 * 1024
                      else "busy" if len(self._commands) >= self.MAX_COMMANDS else None)
            if status is None:
                self._commands.append(command)
                self._queued_text_bytes += text_bytes
        if status:
            future.set_result(PhoneReplyResult(status, scope.phone_request_id))
        return future

    def skip(self, scope, operation_id):
        return self._port.skip(scope, operation_id)

    def hold(self, scope, interruption_id):
        return self._port.hold(scope, interruption_id)

    def resolve(self, scope, interruption_id, delivered_chunks, transcript, next_request_id, next_metadata, *, claim=None):
        return self._port.resolve(scope, interruption_id, delivered_chunks, transcript, next_request_id, next_metadata, claim=claim)

    def abandon(self, scope, interruption_id):
        return self._port.abandon(scope, interruption_id)

    def is_held(self, scope) -> bool:
        binding = self._bindings.get(scope)
        return bool(binding and binding.held)

    def is_interrupted(self, scope) -> bool:
        binding = self._bindings.get(scope)
        return bool(binding and binding.interrupted)

    def is_playback_pending(self, scope) -> bool:
        binding = self._bindings.get(scope)
        return bool(binding and binding.requires_playback_completion and binding.playback_finished_at is None)

    def request_playback_stop(self, scope) -> bool:
        """Desktop Skip requests remote suppression; only its ACK releases it."""
        self._assert_owner()
        binding = self._bindings.get(scope)
        if not binding or not self.is_playback_pending(scope):
            return False
        if not binding.playback_stop_requested:
            binding.playback_stop_requested = True
            binding.skip_audio()
            self._publish(PhoneReplyEvent(scope, "playback_stop_requested"))
        return True

    def producer_finished(self, scope) -> None:
        # Notification may originate from a producer; drain performs the event.
        if not self._valid_scope(scope):
            return
        with self._lock:
            if self._running and scope in self._events:
                self._producer_notifications.add(scope)

    def pending_replaced(self, request_id: str, transaction_id: str) -> None:
        # The pending-input owner calls this after replacing its slot, outside
        # its lock. It does not touch a bound reply or conversation history.
        if not self._available():
            return
        scope = PhoneReplyScope(request_id, transaction_id,
                                self._conversation.snapshot().session_generation.value)
        self._publish(PhoneReplyEvent(scope, "superseded"))

    def reject_unbound_input(self, turn: Mapping[str, object] | None) -> None:
        """Retire an admitted phone input that failed before provider handoff."""
        self._assert_owner()
        # Pending-input reconstruction retains the capture/transaction identity,
        # while the phone-control flag lives in the accepted transaction itself.
        if not isinstance(turn, Mapping):
            return
        request_id = turn.get("remote_capture_id")
        transaction_id = turn.get("normal_chat_transaction_id")
        if not isinstance(request_id, str) or not request_id or not isinstance(transaction_id, str) or not transaction_id:
            return
        scope = PhoneReplyScope(request_id, transaction_id,
                                self._conversation.snapshot().session_generation.value)
        if scope not in self._bindings:
            self._publish(PhoneReplyEvent(scope, "cancelled"))

    def invalidate_generation(self, generation: int) -> None:
        self._assert_owner()
        for scope in tuple(self._bindings):
            binding = self._bindings[scope]
            if scope.session_generation != generation or not self._conversation.session_lease_is_current(binding.lease):
                self._bindings.pop(scope)
                self._publish(PhoneReplyEvent(scope, "cancelled"))

    def _current_revision(self, binding):
        if not self._conversation.session_lease_is_current(binding.lease):
            return None
        snapshot = self._conversation.snapshot()
        expected_count = binding.initial.count
        expected_revision = binding.initial.revision
        committed = self._conversation.assistant_commit_for(binding.lease)
        if committed is not None:
            expected_count += 1
            expected_revision += 1
            # Closing the accepted route increments revision without editing its
            # persisted source/reply. All additional edits still fail equality.
            if not self._conversation.turn_lease_is_current(binding.lease):
                expected_revision += 1
        # Shared pending-turn acceptance changes revision without editing the
        # active exchange. Exact history/commit equality still guards the write;
        # the returned current revision is used by the interruption CAS.
        if (len(snapshot.messages) != expected_count
                or (snapshot.revision != expected_revision and not binding.requires_playback_completion)
                or _fingerprint(snapshot.messages[:binding.initial.count]) != binding.initial.fingerprint
                or (committed is not None and snapshot.messages[-1] != committed.message)):
            return None
        return snapshot.revision

    def drain(self) -> None:
        self._assert_owner()
        self.invalidate_generation(self._conversation.snapshot().session_generation.value)
        self._expire()
        with self._lock:
            finished = tuple(self._producer_notifications)
            self._producer_notifications.clear()
        for scope in finished:
            binding = self._bindings.get(scope)
            if binding is not None and binding.finished_at is None:
                binding.finished_at = self._clock()
                self._publish(PhoneReplyEvent(scope, "producer_finished"))
        with self._lock:
            commands = tuple(self._commands)
            self._commands.clear()
        for command in commands:
            if not command.future.set_running_or_notify_cancel():
                with self._lock:
                    self._queued_text_bytes -= command.text_bytes
                continue
            try:
                if not command.is_open():
                    self._finish(command, "unavailable")
                    continue
                self._execute(command)
            except Exception:
                # Keep the fixed public failure free of provider/context details.
                binding = self._bindings.get(command.scope)
                if binding and binding.held == command.operation_id:
                    binding.held = ""
                    binding.terminal_id = command.operation_id
                    binding.result = PhoneReplyResult("unavailable", command.scope.phone_request_id)
                self._finish(command, "unavailable")
            finally:
                with self._lock:
                    self._queued_text_bytes -= command.text_bytes

    def _finish(self, command, status, next_id=None):
        if not command.future.done():
            _LOG.info("Phone reply control kind=%s result=%s request=%s transaction=%s generation=%s",
                      command.kind, status, command.scope.phone_request_id,
                      command.scope.normal_chat_transaction_id, command.scope.session_generation)
            command.future.set_result(PhoneReplyResult(status, command.scope.phone_request_id, next_id))

    def _execute(self, command):
        if not self._available():
            self._finish(command, "unavailable")
            return
        binding = self._bindings.get(command.scope)
        if binding is None:
            self._finish(command, "stale")
            return
        if command.deadline <= self._clock():
            if binding.held == command.operation_id:
                self._release(binding, "stale")
            self._finish(command, "stale")
            return
        if command.kind == "playback_finished":
            if not binding.requires_playback_completion:
                self._finish(command, "unavailable")
            elif binding.playback_finished_at is not None:
                self._finish(command, "duplicate")
            elif binding.finished_at is None and not binding.playback_stop_requested:
                self._finish(command, "busy")
            else:
                # This releases playback only; it does not rewrite history.
                # Pending-input acceptance/replacement may change revision
                # without changing this authenticated reply/session identity.
                # drain() already invalidated non-current session leases.
                binding.playback_finished_at = self._clock()
                self._finish(command, "accepted")
            return
        if command.kind == "skip":
            if binding.requires_playback_completion and binding.playback_finished_at is not None:
                self._finish(command, "duplicate")
                return
            # Shared-queue Stop speech retires only this exact output binding,
            # just like playback_finished. It never rewrites conversation text.
            # A newer history revision must not strand the old playback gate;
            # drain() already invalidated other session generations.
            if not binding.requires_playback_completion and self._current_revision(binding) is None:
                self._finish(command, "stale")
                return
            status = "duplicate" if binding.skipped else "accepted"
            if not binding.skipped:
                binding.skipped = True
                binding.skip_audio()
            # The owning phone or gateway has already suppressed this output.
            if binding.requires_playback_completion:
                binding.playback_finished_at = self._clock()
            self._finish(command, status)
            return
        if binding.resolving is not None and not binding.resolving.done():
            if binding.terminal_id == command.operation_id:
                binding.resolving.add_done_callback(
                    lambda completed, target=command.future: target.set_result(completed.result()))
            else:
                self._finish(command, "busy")
            return
        if binding.result is not None:
            result = binding.result
            if binding.terminal_id == command.operation_id:
                self._finish(command, result.status, result.next_phone_request_id)
            else:
                self._finish(command, "stale")
            return
        if command.kind == "abandon":
            if binding.held == command.operation_id:
                self._release(binding, "accepted")
                self._finish(command, "accepted")
            else:
                self._finish(command, "stale")
            return
        revision = self._current_revision(binding)
        if revision is None:
            if binding.held == command.operation_id:
                self._release(binding, "stale")
            self._finish(command, "stale")
            return
        if command.kind == "hold":
            if binding.held:
                self._finish(command, "duplicate" if binding.held == command.operation_id else "busy")
                return
            binding.held = command.operation_id
            binding.deadline = self._clock() + self.LEASE_SECONDS
            if not binding.skipped:
                binding.skipped = True
                binding.skip_audio()
            if binding.requires_playback_completion:
                binding.playback_finished_at = self._clock()
            self._finish(command, "accepted")
            return
        if binding.held != command.operation_id:
            self._finish(command, "stale")
            return
        chunks, transcript, next_id, metadata, claim = command.payload
        if not transcript.strip():
            self._release(binding, "accepted")
            self._finish(command, "accepted")
            return
        # Claim is external code too: reentrant retries must wait on this exact
        # operation before it can claim, reject, or raise. Keep the hold active
        # until claim settles so rejection still releases the same identity.
        binding.terminal_id = command.operation_id
        binding.resolving = command.future
        if claim is not None and not claim():
            self._release(binding, "stale")
            self._finish(command, "stale")
            return
        if not self._available() or self._bindings.get(command.scope) is not binding:
            self._finish(command, "unavailable")
            return
        # Latch before reentrant history rebuilds, cancellation or acceptance.
        binding.interrupted = True
        binding.held = ""
        binding.result = PhoneReplyResult("unavailable", binding.scope.phone_request_id)
        outcome = self._history.record_interrupted_assistant(
            binding.context, assistant_interruption_text(chunks), expected_revision=revision)
        if not outcome.accepted:
            binding.result = PhoneReplyResult("stale", binding.scope.phone_request_id)
        else:
            binding.cancel_provider()
            if not self._available() or self._bindings.get(command.scope) is not binding:
                self._finish(command, "unavailable")
                return
            accepted = self._accept(
                transcript.strip(), role="user",
                metadata={**metadata, "remote_capture_id": next_id, "phone_reply_control": True,
                          "nc_skip_image_attachment": True},
                expected_history_revision=outcome.revision,
                source_lease=WorkLease(run_id=binding.lease.run_id,
                                       session_generation=binding.lease.session_generation))
            binding.result = PhoneReplyResult("accepted" if accepted.get("queued") else "stale",
                                             binding.scope.phone_request_id,
                                             next_id if accepted.get("queued") else None)
            if accepted.get("queued"):
                self.accepted_turn_serial += 1
        self._finish(command, binding.result.status, binding.result.next_phone_request_id)

    def _release(self, binding, status):
        if self._current_revision(binding) is None:
            binding.interrupted = True
        binding.terminal_id = binding.held
        binding.held = ""
        binding.result = PhoneReplyResult(status, binding.scope.phone_request_id)

    def _expire(self):
        now = self._clock()
        for scope, binding in tuple(self._bindings.items()):
            if binding.held and binding.deadline <= now:
                self._release(binding, "stale")
            retained_at = max(binding.finished_at or 0.0, binding.playback_finished_at or 0.0)
            if (binding.finished_at is not None and not binding.held and not self.is_playback_pending(scope)
                    and now - retained_at >= self.RETENTION_SECONDS):
                self._bindings.pop(scope)
                with self._lock:
                    self._events.pop(scope, None)

    def subscribe(self, listener):
        with self._lock:
            if len(self._listeners) >= 64:
                raise RuntimeError("Phone reply subscription capacity exhausted.")
            self._next_listener += 1
            token = self._next_listener
            record = _Subscriber(listener, deque())
            for event in self._events.values():
                record.pending.append(PhoneReplyEvent(event.scope, "bound"))
                if event.kind != "bound":
                    record.pending.append(event)
            self._listeners[token] = record
        self._deliver(record)
        def unsubscribe():
            with self._lock:
                self._listeners.pop(token, None)
                record.active = False
                record.pending.clear()
        return unsubscribe

    def _publish(self, event):
        _LOG.info("Phone reply lifecycle event=%s request=%s transaction=%s generation=%s",
                  event.kind, event.scope.phone_request_id,
                  event.scope.normal_chat_transaction_id, event.scope.session_generation)
        if event.kind != "superseded":
            binding = self._bindings.get(event.scope)
            if binding is not None:
                event = replace(event, producer_complete=binding.finished_at is not None,
                                playback_stop_requested=binding.playback_stop_requested)
        with self._lock:
            if event.kind in {"cancelled", "superseded"}:
                self._events.pop(event.scope, None)
            else:
                self._events[event.scope] = event
            listeners = tuple(self._listeners.items())
            for token, record in listeners:
                if len(record.pending) >= 1024:
                    # A subscriber that cannot keep up must reconnect/replay;
                    # never retain an unbounded queue behind a slow callback.
                    record.active = False
                    record.pending.clear()
                    self._listeners.pop(token, None)
                else:
                    record.pending.append(event)
        for _token, record in listeners:
            self._deliver(record)

    def _deliver(self, record):
        with self._lock:
            if record.delivering or not record.active:
                return
            record.delivering = True
        while True:
            with self._lock:
                if not record.active or not record.pending:
                    record.delivering = False
                    return
                event = record.pending.popleft()
            try:
                record.listener(event)
            except Exception:
                pass


__all__ = [
    "PhoneReplyControls",
    "PhoneReplyControlPort",
    "PhoneReplyEvent",
    "PhoneReplyResult",
    "PhoneReplyScope",
    "assistant_interruption_text",
]
