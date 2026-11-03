"""Exact, immutable identities for conversation controls (never client text)."""
from dataclasses import dataclass, replace
from concurrent.futures import Future, InvalidStateError
from typing import Callable, Literal
import threading
import logging

from core.runtime.reply_delivery import ReplyDelivery
from core.runtime.interaction import InteractionCommand


@dataclass(frozen=True, slots=True)
class ConversationActionTarget:
    message_id: str
    revision: int
    session_generation: int

    def __post_init__(self):
        if (type(self.message_id) is not str or not 1 <= len(self.message_id) <= 128
                or any(ord(c) < 32 for c in self.message_id)
                or type(self.revision) is not int or self.revision < 0
                or type(self.session_generation) is not int or self.session_generation < 0):
            raise ValueError('Invalid conversation action target')


@dataclass(frozen=True, slots=True)
class ConversationActionRequest:
    operation_id: str
    kind: Literal['regenerate', 'retry', 'end_waiting']
    target: ConversationActionTarget
    delivery: ReplyDelivery = ReplyDelivery()
    input_owner: Literal['local', 'phone'] = 'local'

    def __post_init__(self):
        if (type(self.operation_id) is not str or not 1 <= len(self.operation_id) <= 128
                or any(ord(c) < 32 for c in self.operation_id)
                or self.kind not in ('regenerate', 'retry', 'end_waiting')
                or not isinstance(self.target, ConversationActionTarget)
                or not isinstance(self.delivery, ReplyDelivery)
                or self.input_owner not in ('local', 'phone')):
            raise ValueError('Invalid conversation action')


@dataclass(frozen=True, slots=True)
class _AuthorizedTarget(ConversationActionTarget):
    # Internal only. The transport can supply identity, never this authority.
    is_current: Callable[[], bool]


@dataclass(frozen=True, slots=True)
class ConversationActionResult:
    status: Literal['accepted', 'stale', 'busy', 'unavailable']
    phone_request_id: str | None = None
    reason: str = ''


@dataclass(frozen=True, slots=True)
class ConversationActionPort:
    submit: object
    snapshot: object

    def for_generation(self, is_open):
        return ConversationActionPort(
            lambda request, guard=lambda: True: self.submit(request, guard=lambda: is_open() and guard()),
            lambda **kwargs: self.snapshot(**kwargs) if is_open() else {'disabled_reason': 'runtime_stopped'})


class ConversationActionOwner:
    def __init__(self, conversation, interaction, normal_chat, session):
        self.conversation, self.interaction = conversation, interaction
        self.normal_chat, self.session = normal_chat, session
        self._lock = threading.RLock()
        self._records = {}
        self._running = False
        self._owner_thread = None
        self._phase = 'idle'
        self._inflight = None
        self._last_accepted = None

    def start(self):
        with self._lock:
            self._running = True
            self._owner_thread = threading.get_ident()

    def stop(self):
        with self._lock:
            self._running = False
            unresolved = [key for key, record in self._records.items() if record[2] is None]
        for key in unresolved:
            self.finish(key, ConversationActionResult('unavailable', reason='runtime_stopped'))

    def set_phase(self, phase):
        with self._lock:
            self._phase = phase

    def snapshot(self, *, include_history=False, include_preview=False):
        if include_history:
            snapshot, retired_revision = self.conversation.snapshot_with_retirement()
        else:
            snapshot = self.conversation.snapshot()
        with self._lock:
            running, phase, inflight = self._running, self._phase, self._inflight
        reason = ('runtime_stopped' if not running else 'action_pending' if inflight
            else 'manual_input_pending' if self.session.pending_loaded_input_turn() is not None
            else phase if phase not in ('idle', 'speaking') else '')
        result = dict(revision=snapshot.revision, session_generation=snapshot.session_generation.value,
            regenerate=None, retry=None, end_waiting=None, disabled_reason=reason)
        if include_history:
            # Internal projection: the bridge removes this before publishing
            # controls. Feed identities and target eligibility share ONE snapshot.
            result['_history'] = [dict(message.metadata, role=message.role,
                content=message.content, id=message.message_id) for message in snapshot.messages]
            result['_retired_revision'] = retired_revision
        if include_preview:
            preview_callback = getattr(self.normal_chat, 'stream_preview_snapshot', None)
            preview = preview_callback() if callable(preview_callback) else None
            last = snapshot.messages[-1] if snapshot.messages else None
            if (isinstance(preview, dict) and last is not None and last.role.lower() == 'user'
                    and preview.get('session_generation') == snapshot.session_generation.value
                    and preview.get('normal_chat_transaction_id') == last.metadata.get('normal_chat_transaction_id')):
                result['_stream_preview'] = preview
        if reason or not snapshot.messages:
            return result
        last = snapshot.messages[-1]
        target = dict(message_id=last.message_id, revision=snapshot.revision,
            session_generation=snapshot.session_generation.value)
        if last.role.lower() == 'assistant' and len(snapshot.messages) >= 2 and snapshot.messages[-2].role.lower() == 'user':
            result.update(regenerate=target, retry=target)
        elif last.role.lower() == 'user':
            result['retry'] = target
            result['end_waiting' if phase == 'idle' else 'regenerate'] = target
        return result

    def _caller_current(self, request):
        with self._lock:
            record = self._records.get(request.operation_id)
            guard = record[4] if record is not None else lambda: True
        try:
            current = guard()
        except Exception:
            current = False
        return bool(current)

    def validate(self, request):
        if not self._caller_current(request):
            return ConversationActionResult('unavailable', reason='caller_retired')
        target, snapshot = self.conversation.snapshot_for_action(request.target)
        if (snapshot.revision != target.revision
                or snapshot.session_generation.value != target.session_generation
                or not snapshot.messages or snapshot.messages[-1].message_id != target.message_id):
            return ConversationActionResult('stale', reason='conversation_changed')
        with self._lock:
            running, phase = self._running, self._phase
        if not running:
            return ConversationActionResult('unavailable', reason='runtime_stopped')
        if self.session.pending_loaded_input_turn() is not None:
            return ConversationActionResult('busy', reason='manual_input_pending')
        if phase not in ('idle', 'speaking') or (request.kind == 'end_waiting' and phase != 'idle'):
            return ConversationActionResult('busy', reason='conversation_active')
        if request.kind == 'end_waiting' and snapshot.messages[-1].role.lower() != 'user':
            return ConversationActionResult('stale', reason='not_final_user')
        return None

    def submit(self, request, *, guard=lambda: True):
        if not isinstance(request, ConversationActionRequest):
            raise ValueError('A typed conversation action is required')
        future = Future()
        # Keep the original request in the dedup record. Only its checked target
        # may advance across the one known, history-preserving playback close.
        # Mutation guards take conversation -> owner locks. Never invert that
        # order while deciding which completed records can be reclaimed.
        target, snapshot = self.conversation.snapshot_for_action(request.target)
        with self._lock:
            record = self._records.get(request.operation_id)
            if record is not None and record[0] == request:
                return record[1]
            if len(self._records) >= 256:
                for key, completed in tuple(self._records.items()):
                    completed_target = completed[0].target
                    obsolete = (completed_target.session_generation < snapshot.session_generation.value
                        or (completed_target.session_generation == snapshot.session_generation.value
                            and completed_target.revision < snapshot.revision))
                    if (completed[2] is not None and completed[1].done()
                            and key != self._last_accepted
                            and (completed[2].status != 'accepted' or obsolete)):
                        del self._records[key]
            rejected = (ConversationActionResult('stale', reason='operation_conflict') if record is not None
                else ConversationActionResult('unavailable', reason='runtime_stopped') if not self._running
                else ConversationActionResult('stale', reason='conversation_changed')
                    if (target.revision != snapshot.revision
                        or target.session_generation != snapshot.session_generation.value
                        or not snapshot.messages or target.message_id != snapshot.messages[-1].message_id)
                else ConversationActionResult('busy', reason='operation_capacity') if len(self._records) >= 256
                else None)
            if rejected is None:
                # Unresolved actions stay deduplicated. Completed successes can
                # be reclaimed only when their original target is obsolete.
                self._records[request.operation_id] = [request, future, None, False, guard]
        if rejected is not None:
            future.set_result(rejected)
            return future
        admission = self.interaction.submit(InteractionCommand('conversation_action',
            payload={'operation_id': request.operation_id}, source='conversation_action'))
        if not admission.accepted:
            self.finish(request.operation_id, ConversationActionResult('unavailable', reason='command_not_admitted'))
        return future

    def claim(self, operation_id):
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError('Conversation actions execute on the conversation owner thread')
        with self._lock:
            record = self._records.get(operation_id)
            if record is None or record[2] is not None or record[3]:
                return None
            record[3] = True
            request = record[0]
            busy = self._inflight is not None
            if not busy:
                self._inflight = operation_id
        rejected = ConversationActionResult('busy', reason='action_pending') if busy else self.validate(request)
        if rejected:
            self.finish(operation_id, rejected)
            return None
        request = self.after_retirement(request)
        logging.getLogger(__name__).info('Conversation action admitted kind=%s operation=%s target=%s destination=%s reply=%s phase=%s',
            request.kind, operation_id, request.target.message_id, request.delivery.destination,
            request.delivery.phone_request_id, self._phase)
        return request

    def finish(self, operation_id, result):
        with self._lock:
            record = self._records.get(operation_id)
            if record is None or record[2] is not None:
                return
            record[2] = result
            if result.status == 'accepted':
                # execute()'s caller still observes this result to enter phone
                # Retry's waiting state. Concurrent submissions cannot evict it.
                self._last_accepted = operation_id
            if self._inflight == operation_id:
                self._inflight = None
            request, future = record[:2]
        logging.getLogger(__name__).info('Conversation action kind=%s operation=%s target=%s destination=%s reply=%s status=%s reason=%s',
            request.kind, operation_id, request.target.message_id, request.delivery.destination,
            request.delivery.phone_request_id, result.status, result.reason)
        try:
            future.set_result(result)
        except InvalidStateError:
            pass  # A cancelled observer does not cancel the admitted action.

    def execute(self, request):
        """Called after the old route and remote playback have actually retired."""
        request = self.after_retirement(request)
        rejected = self.validate(request)
        if rejected:
            self.finish(request.operation_id, rejected)
            return None
        try:
            target = _AuthorizedTarget(request.target.message_id, request.target.revision,
                request.target.session_generation, lambda: self._caller_current(request))
            if request.kind == 'retry':
                self.conversation.retry_exchange_if_current(target)
                self.session.prune_normal_chat_transactions()
                prepared = None
            else:
                prepared = self.normal_chat.prepare_conversation_action(target, request.delivery)
                self.set_phase('thinking')
            self.session.request_chat_view_rebuild()
        except RuntimeError:
            self.finish(request.operation_id, ConversationActionResult('stale', reason='target_no_longer_available'))
            return None
        self.finish(request.operation_id, ConversationActionResult('accepted', request.delivery.phone_request_id))
        return prepared

    def after_retirement(self, request, lease=None):
        try:
            target = self.conversation.target_after_route_retirement(request.target, lease)
            return replace(request, target=target)
        except RuntimeError:
            return request  # execute will return stale without mutating history.

    def port(self):
        return ConversationActionPort(self.submit, self.snapshot)

    def accepted(self, operation_id):
        with self._lock:
            record = self._records.get(operation_id)
            return bool(record and record[2] and record[2].status == 'accepted')
