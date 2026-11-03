"""Private, bounded phone operations. No runtime callback runs under our lock."""
from __future__ import annotations

from concurrent.futures import Future, TimeoutError
from dataclasses import dataclass, field
import secrets
import hashlib
import json
import logging
import threading
import time

from addons.main_chat_remote.phone_reply_receipts import PhoneReplyRegistry, PhoneReplyRejected
from core.runtime.phone_reply_controls import PhoneReplyControlPort, PhoneReplyScope, PhoneReplyResult


MAX_CONTROL_BODY_BYTES = 256 * 1024
MAX_OPERATIONS = 1024
MAX_STT_JOBS = 16
_LOG = logging.getLogger(__name__)


def identifier(value):
    if type(value) is not str or not value or len(value) > 128:
        raise PhoneReplyRejected("invalid_request")
    return value


def wire_result(result: PhoneReplyResult) -> dict:
    return {"status": result.status, "phone_request_id": result.phone_request_id,
            "next_phone_request_id": result.next_phone_request_id}


@dataclass(repr=False)
class PhoneOperation:
    kind: str
    scope: PhoneReplyScope
    operation_id: str
    deadline: float
    chunks: tuple[str, ...] = ()
    future: Future = field(default_factory=Future)
    runtime: Future | None = None
    next_request_id: str | None = None
    settled_at: float | None = None


@dataclass(repr=False)
class PhoneSubmission:
    fingerprint: bytes
    deadline: float
    future: Future = field(default_factory=Future)
    claimed: bool = False
    request_id: str = ""
    settled_at: float | None = None
    text_bytes: int = 0


class PhoneReplyProtocol:
    def __init__(self, controls, media, *, clock=time.monotonic, on_registered=None):
        self.controls = controls
        self.media = media
        self.clock = clock
        self._on_registered = on_registered
        self.registry = PhoneReplyRegistry(clock)
        self._lock = threading.RLock()
        self._operations = {}
        self._pending = {}
        self._expired_continuations = {}
        self._submissions = {}
        self._progressive_audio_owners = {}
        self._submission_text_bytes = 0
        self._uploads = threading.BoundedSemaphore(MAX_STT_JOBS)
        self._unsubscribe = controls.subscribe(self._event) if isinstance(controls, PhoneReplyControlPort) else None

    @property
    def available(self):
        return isinstance(self.controls, PhoneReplyControlPort) and self.controls.available and self._unsubscribe is not None

    def diagnostic_snapshot(self):
        with self._lock:
            operations = [{'reply_id': op.scope.phone_request_id, 'kind': op.kind,
                           'settled': op.future.done(), 'runtime_settled': op.runtime.done() if op.runtime else None}
                          for op in list(self._operations.values())[-32:]]
            pending = len(self._pending)
        return {'pending_count': pending, 'operations': operations, **self.registry.diagnostic_snapshot()}

    def runtime_change_busy(self) -> bool:
        """Provider changes must wait for submissions and existing phone owners."""
        with self._lock:
            pending = bool(self._pending) or any(not op.future.done() for op in self._submissions.values())
        # Never hold the protocol lock while taking the registry lock.
        return pending or self.registry.runtime_change_busy()

    def require_available(self):
        if not self.available:
            raise PhoneReplyRejected("unavailable")

    @property
    def conversation_actions_available(self):
        return self.available and getattr(self.controls, 'conversation_actions', None) is not None

    def conversation_actions_snapshot(self, *, include_history=False, include_preview=False):
        if not self.conversation_actions_available:
            return {}
        options = {"include_history": include_history}
        if include_preview:
            options["include_preview"] = True
        return self.controls.conversation_actions.snapshot(**options)

    def conversation_action(self, auth, body):
        from core.runtime.conversation_actions import ConversationActionRequest, ConversationActionTarget
        from core.runtime.reply_delivery import ReplyDelivery
        self.authenticate(auth)
        if not self.conversation_actions_available or not self.registry.shared_queue_enabled(auth):
            raise PhoneReplyRejected('unavailable')
        if type(body) is not dict or set(body) != {'kind', 'operation_id', 'target'}:
            raise PhoneReplyRejected('invalid_request')
        try:
            if type(body['target']) is not dict or set(body['target']) != {'message_id', 'revision', 'session_generation'}:
                raise ValueError('target')
            target = ConversationActionTarget(**body['target'])
            # Validate kind and operation identity before reserving any output.
            ConversationActionRequest(body['operation_id'], body['kind'], target)
        except (TypeError, ValueError):
            raise PhoneReplyRejected('invalid_request') from None
        fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).digest()
        op, first = self.begin_submission(auth, body['operation_id'], fingerprint, namespace='conversation_action')
        if first:
            def guard():
                try:
                    self.authenticate(auth)
                    return True
                except PhoneReplyRejected:
                    return False
            try:
                if body['kind'] != 'retry':
                    op.request_id = self.register(auth)
                delivery = ReplyDelivery('phone', op.request_id, True) if op.request_id else ReplyDelivery()
                request = ConversationActionRequest(secrets.token_hex(16), body['kind'], target, delivery, 'phone')
                op.claimed = True
                future = self.controls.conversation_actions.submit(request, guard=guard)
                def settled(done):
                    try:
                        result = done.result()
                        response = dict(status=result.status, phone_request_id=result.phone_request_id, reason=result.reason)
                    except Exception:
                        response = dict(status='unavailable', phone_request_id=None, reason='owner_unavailable')
                    if response['status'] != 'accepted' and op.request_id:
                        self.cancel(op.request_id)
                    self.finish_submission(op, response)
                future.add_done_callback(settled)
            except Exception:
                if op.request_id:
                    self.cancel(op.request_id)
                self.finish_submission(op, dict(status='unavailable', phone_request_id=None, reason='owner_unavailable'))
        try:
            return op.future.result(timeout=2.0 if first else 0.0)
        except TimeoutError:
            # An uncertain acknowledgement is not permission to execute again.
            raise PhoneReplyRejected('pending') from None

    def authenticate(self, auth):
        # Authentication is deliberately independent of public runtime status.
        epoch = self.registry.authenticate(auth)
        self.require_available()
        return epoch

    def new_client(self, *, shared_queue=False, continuation=False):
        self.require_available()
        self.maintain()
        return self.registry.new_client(shared_queue=shared_queue, continuation=continuation)

    def set_progressive_audio_mode(self, auth, enabled):
        epoch = self.authenticate(auth)
        if type(enabled) is not bool:
            raise PhoneReplyRejected('invalid_request')
        with self._lock:
            if enabled:
                # Capability choices are bounded, and never grant authentication.
                if len(self._progressive_audio_owners) >= 64 and epoch not in self._progressive_audio_owners:
                    self._progressive_audio_owners.pop(next(iter(self._progressive_audio_owners)))
                self._progressive_audio_owners[epoch] = True
            else:
                self._progressive_audio_owners.pop(epoch, None)
        return dict(version=1, enabled=enabled)

    def continuation_status(self, auth, request_id, body):
        self.authenticate(auth)
        status = self.registry.status(auth, request_id)  # owner validation first
        if not self.registry.continuation_enabled(auth):
            raise PhoneReplyRejected("unavailable")
        if (type(body) is not dict or set(body) != {"version", "cursor", "completed_sequence_index"}
                or type(body["version"]) is not int or body["version"] != 1
                or type(body["cursor"]) is not int or not 0 <= body["cursor"] <= 2048
                or type(body["completed_sequence_index"]) is not int or not -1 <= body["completed_sequence_index"] < 2048):
            raise PhoneReplyRejected("invalid_request")
        try:
            status["continuation"] = self.media.reply_continuation(request_id, body["cursor"], body["completed_sequence_index"])
        except ValueError:
            raise PhoneReplyRejected("invalid_request") from None
        return status

    def register(self, auth):
        epoch = self.authenticate(auth)
        request_id = secrets.token_urlsafe(18)
        self.registry.register(auth, request_id)
        # A negotiated manual turn may legitimately wait for long phone audio.
        # Its submission has a separate admission deadline; the accepted slot
        # retires on replacement/binding/session loss, never on elapsed speech.
        deadline = None if self.registry.shared_queue_enabled(auth) else self.clock() + 120
        with self._lock:
            self._pending[request_id] = deadline
            progressive = self._progressive_audio_owners.get(epoch, False)
        try:
            if self.registry.continuation_enabled(auth):
                self.media.register_phone_reply(request_id, self.registry, continuation=True,
                    **({'progressive': True} if progressive else {}))
            else:
                self.media.register_phone_reply(request_id, self.registry,
                    **({'progressive': True} if progressive else {}))
            if self._on_registered is not None:
                self._on_registered(auth, request_id)
        except Exception:
            self.cancel(request_id)
            raise
        return request_id

    def _event(self, event):
        try:
            if event.playback_stop_requested:
                self.registry.request_playback_stop(event.scope.phone_request_id)
            if event.kind == "superseded":
                if self.registry.supersede_pending(event.scope.phone_request_id):
                    with self._lock:
                        self._pending.pop(event.scope.phone_request_id, None)
                    self.media.finish_phone_reply(event.scope.phone_request_id)
            elif event.kind == "bound":
                self.registry.bind(event.scope.phone_request_id, event.scope)
                with self._lock:
                    self._pending.pop(event.scope.phone_request_id, None)
            elif event.kind in {"producer_finished", "cancelled"}:
                self.registry.bind(event.scope.phone_request_id, event.scope)
                self.media.finish_phone_reply(event.scope.phone_request_id, cancelled=event.kind == "cancelled")
        except PhoneReplyRejected:
            pass  # A replay may precede this addon's private admission lifetime.

    def cancel(self, request_id):
        with self._lock:
            self._pending.pop(request_id, None)
        self.media.finish_phone_reply(request_id, cancelled=True)
        self.registry.cancel(request_id)

    def stop_for_recovery(self, owner_epoch, request_id, operation_id, *, wait_for_stop=True):
        scope = self.registry.recovery_stop_scope(owner_epoch,request_id)
        if scope is None:
            self.cancel(request_id)
            return
        op, first = self._operation('skip',scope,operation_id,self.clock()+120)
        if first:
            self.media.suppress_phone_reply(request_id)
            self._attach(op,self.controls.skip(scope,operation_id))
        try:
            # Peer recovery polls its idempotent prepare operation rather than
            # holding a request while the runtime owner drains Stop. Explicit
            # backend Stop retains its existing first-call wait policy.
            result = self.wait(op,retry=not first or not wait_for_stop)
        except PhoneReplyRejected as error:
            if error.reason != 'pending': raise
            raise ValueError('ordered_recovery_stop_pending') from None
        if result.status not in {'accepted','duplicate'}: raise ValueError('ordered_recovery_stop_pending')
        self.cancel(request_id)

    def maintain(self):
        now = self.clock()
        available = self.available
        with self._lock:
            pending = tuple(request_id for request_id, deadline in self._pending.items() if not available or (deadline is not None and now >= deadline))
        for request_id in pending:
            self.cancel(request_id)
        maintain_media = getattr(self.media, "maintain_reply_continuations", None)
        for request_id in maintain_media() if maintain_media else ():
            scope = self.registry.expire_continuation(request_id)
            if scope is None:
                self.cancel(request_id)
                continue
            self.media.suppress_phone_reply(request_id)
            with self._lock:
                # At most the registry's 256 unacknowledged reply records.
                self._expired_continuations.setdefault(request_id, scope)
        with self._lock:
            expired = tuple(self._expired_continuations.items())
        for request_id, scope in expired:
            # _operation serializes concurrent maintenance and keeps the same ID.
            op, first = self._expiry_operation(scope)
            if not first:
                continue
            try:
                future = self.controls.skip(scope, "continuation-expired")
            except Exception:
                with self._lock:
                    op.runtime = None
                continue
            def settled(done, request_id=request_id, op=op):
                try:
                    status = done.result().status
                except Exception:
                    status = "unavailable"
                if status in {"accepted", "duplicate"}:
                    self.registry.confirm_playback_suppressed(request_id)
                elif status == "stale":
                    self.registry.cancel(request_id)
                with self._lock:
                    if status in {"accepted", "duplicate", "stale"}:
                        self._expired_continuations.pop(request_id, None)
                        self._operations.pop((request_id, "expiry", "continuation-expired"), None)
                    else:
                        op.runtime = None  # retry transient mailbox/owner failure
            future.add_done_callback(settled)
        # Media clear/cancellation removes the phone's ability to acknowledge
        # playback. Release the exact owner binding through its mailbox, never
        # from a media/registry lock and never by inventing a heard receipt.
        for scope in self.registry.pending_runtime_cancellations():
            op, first = self._expiry_operation(scope, "reply-cancelled")
            if not first:
                continue
            try:
                future = self.controls.skip(scope, "reply-cancelled")
            except Exception:
                with self._lock:
                    op.runtime = None
                continue
            def cancelled(done, scope=scope, op=op):
                try:
                    result = done.result()
                    status = result.status
                except Exception:
                    result = PhoneReplyResult("unavailable", scope.phone_request_id)
                    status = result.status
                if status in {"accepted", "duplicate", "stale"}:
                    self.registry.confirm_runtime_cancellation(scope)
                    _LOG.info("Cancelled phone playback release request=%s result=%s", scope.phone_request_id, status)
                    settled_at = self.clock()
                    with self._lock:
                        op.runtime = done
                        op.settled_at = settled_at
                    op.future.set_result(result)
                else:
                    with self._lock:
                        op.runtime = None  # retry a busy/unavailable owner
            future.add_done_callback(cancelled)
        notices = self.registry.drain_expired()
        for scope, interruption_id in notices:
            if self.controls is not None:
                self.controls.abandon(scope, interruption_id)
        with self._lock:
            for key, op in tuple(self._operations.items()):
                if op.settled_at is not None and now - op.settled_at >= 900:
                    del self._operations[key]
            for key, op in tuple(self._submissions.items()):
                if op.settled_at is not None and now - op.settled_at >= 900:
                    self._submission_text_bytes -= op.text_bytes
                    del self._submissions[key]

    @property
    def continuation_maintenance_needed(self):
        with self._lock:
            pending = bool(self._expired_continuations)
        return (pending or bool(self.registry.pending_runtime_cancellations())
                or getattr(self.media, "continuation_maintenance_needed", False))

    def _expiry_operation(self, scope, operation_id="continuation-expired"):
        # Unlike _operation this must not recursively call maintain().
        kind = "cancel" if operation_id == "reply-cancelled" else "expiry"
        key = (scope.phone_request_id, kind, operation_id)
        with self._lock:
            op = self._operations.get(key)
            if op is None:
                if len(self._operations) >= MAX_OPERATIONS:
                    return None, False
                op = PhoneOperation(kind, scope, operation_id, self.clock() + 120)
                self._operations[key] = op
            if op.runtime is not None:
                return op, False
            op.runtime = Future()  # claim before leaving the lock
            return op, True

    def begin_submission(self, auth, submission_id, fingerprint, *, deadline=None, acquire_upload=False, namespace=''):
        epoch = self.authenticate(auth)
        submission_id = identifier(submission_id)
        self.maintain()
        now = self.clock()
        with self._lock:
            key = (epoch, namespace, submission_id) if namespace else (epoch, submission_id)
            op = self._submissions.get(key)
            if op is not None:
                if op.fingerprint != fingerprint:
                    raise PhoneReplyRejected("conflicting_operation")
                return op, False
            # Control acknowledgements must not consume the ordinary typed/STT
            # submission quota. Each bounded namespace has its own replay cache.
            if sum((key[1] if len(key) == 3 else '') == namespace for key in self._submissions) >= 256:
                raise PhoneReplyRejected("capacity")
            op = PhoneSubmission(fingerprint, now + 120 if deadline is None else deadline)
            if acquire_upload and not self._uploads.acquire(blocking=False):
                raise PhoneReplyRejected("capacity")
            self._submissions[key] = op
            return op, True

    def reserve_submission_text(self, op, text):
        size = len(text.encode("utf-8"))
        with self._lock:
            if size > 64 * 1024 or self._submission_text_bytes + size > 8 * 1024 * 1024:
                raise PhoneReplyRejected("capacity")
            op.text_bytes = size
            self._submission_text_bytes += size

    def claim_submission(self, op):
        now = self.clock()
        with self._lock:
            if op.settled_at is not None or op.claimed or now >= op.deadline:
                return False
            op.claimed = True
            return True

    def finish_submission(self, op, result):
        now = self.clock()
        with self._lock:
            if op.settled_at is not None:
                return
            op.settled_at = now
        op.future.set_result(result)

    def timeout_submission(self, op):
        now = self.clock()
        with self._lock:
            if op.settled_at is not None or op.claimed:
                return
            op.settled_at = now
        if op.request_id:
            self.cancel(op.request_id)
        op.future.set_result({"status": "stale", "phone_request_id": op.request_id, "next_phone_request_id": None})

    def fail_submission(self, op, reason):
        now = self.clock()
        with self._lock:
            if op.settled_at is not None or op.claimed:
                return
            op.settled_at = now
        if op.request_id:
            self.cancel(op.request_id)
        op.future.set_exception(PhoneReplyRejected(reason))

    def wait_submission(self, op, *, retry=False):
        if retry and not op.future.done():
            raise PhoneReplyRejected("pending")
        try:
            return op.future.result(timeout=max(0.0, op.deadline - self.clock()))
        except TimeoutError:
            self.timeout_submission(op)
            if op.future.done():
                return op.future.result()
            raise PhoneReplyRejected("pending") from None

    def _operation(self, kind, scope, operation_id, deadline, chunks=()):
        self.maintain()
        key = (scope.phone_request_id, kind, operation_id)
        with self._lock:
            existing = self._operations.get(key)
            if existing is not None:
                return existing, False
            if len(self._operations) >= MAX_OPERATIONS:
                raise PhoneReplyRejected("capacity")
            op = PhoneOperation(kind, scope, operation_id, deadline, chunks)
            self._operations[key] = op
            return op, True

    def _finish(self, op, result):
        if op.kind == "stt":
            try:
                self.registry.resolve(op.scope.phone_request_id, op.operation_id, result)
            except PhoneReplyRejected:
                result = self.registry.outcome(op.scope.phone_request_id, op.operation_id) or result
            if op.next_request_id and result.next_phone_request_id != op.next_request_id:
                self.cancel(op.next_request_id)
        if result.status in {"stale", "unavailable"} and op.kind != "stt":
            self.cancel(op.scope.phone_request_id)
        now = self.clock()
        with self._lock:
            if op.settled_at is not None:
                return
            op.settled_at = now
            op.chunks = ()
        # Future callbacks can reenter; do not hold the operation lock here.
        op.future.set_result(result)

    def _attach(self, op, future):
        with self._lock:
            op.runtime = future
        def settled(done):
            try:
                result = done.result()
            except Exception:
                result = PhoneReplyResult("unavailable", op.scope.phone_request_id)
            if op.kind in {"skip", "hold"} and result.status in {"accepted", "duplicate"}:
                # Ordered playback replacement observes authenticated status.
                # Phone-origin Skip/Hold do not emit Desktop's stop-request event;
                # publish only after the exact runtime control acknowledges it.
                self.registry.request_playback_stop(op.scope.phone_request_id)
                # Hold retains producer finality and the frozen receipt needed
                # by subsequent interruption STT; it only confirms output stop.
                if op.kind == "skip":
                    self.media.finish_phone_reply(op.scope.phone_request_id)
            if op.kind in {"skip", "hold"} and result.status in {"accepted", "duplicate"}:
                self.registry.confirm_playback_suppressed(op.scope.phone_request_id)
            self._finish(op, result)
        future.add_done_callback(settled)

    def wait(self, op, *, retry=False):
        if retry and not op.future.done():
            raise PhoneReplyRejected("pending")
        try:
            return op.future.result(timeout=max(0.0, op.deadline - self.clock()))
        except TimeoutError:
            self.timeout(op)
            if op.future.done():
                return op.future.result()
            # This is an uncertain ACK; retry retrieves the authoritative Future.
            raise PhoneReplyRejected("pending") from None

    def timeout(self, op):
        if op.future.done():
            return
        if op.kind == "stt":
            expired = self.registry.expire_resolution(op.scope.phone_request_id, op.operation_id)
            if expired:
                if op.runtime is not None:
                    op.runtime.cancel()
                self._finish(op, self.registry.outcome(op.scope.phone_request_id, op.operation_id))
        elif op.runtime is not None:
            op.runtime.cancel()
        self.maintain()

    def action(self, auth, action):
        self.authenticate(auth)
        if type(action) is not dict:
            raise PhoneReplyRejected("invalid_request")
        kind = action.get("kind")
        if kind == "playback_finished":
            request_id = identifier(action.get("phone_request_id"))
            operation_id = identifier(action.get("operation_id"))
            if not self.registry.shared_queue_enabled(auth):
                raise PhoneReplyRejected("unavailable")
            status = self.registry.status(auth, request_id)
            if status["phase"] != "complete" and status.get("playback_stop_requested") is not True:
                raise PhoneReplyRejected("invalid_completion")
            scope = self.registry.scope(auth, request_id)
            op, first = self._operation(kind, scope, operation_id, self.clock() + 120)
            if first:
                self._attach(op, self.controls.playback_finished(scope, operation_id))
            result = self.wait(op, retry=not first)
            if result.status in {"accepted", "duplicate"}:
                self.registry.acknowledge_playback(auth, request_id)
                release = getattr(self.media, "release_reply_continuation", None)
                if release:
                    release(request_id)
            return result
        if kind == "onset":
            receipt = action.get("receipt")
            scope, chunks, operation_id, deadline = self.receipt(auth, receipt)
            op, first = self._operation("hold", scope, operation_id, deadline)
            if first:
                self.media.suppress_phone_reply(scope.phone_request_id)
                self._attach(op, self.controls.hold(scope, operation_id))
        elif kind in {"skip", "abandon"}:
            request_id = identifier(action.get("phone_request_id"))
            operation_id = identifier(action.get("operation_id" if kind == "skip" else "interruption_id"))
            if kind == "skip" and self.registry.shared_queue_enabled(auth):
                # The phone has already suppressed its local output. Keep the
                # same stop retryable until this queued request is bound; it
                # cannot yet authorize a control against the active reply.
                phase = self.registry.status(auth, request_id)["phase"]
                if phase == "pending":
                    raise PhoneReplyRejected("pending")
                if phase == "superseded":
                    return PhoneReplyResult("duplicate", request_id)
            scope = self.registry.scope(auth, request_id)
            if kind == "abandon":
                result = self.registry.abandon(auth, request_id, operation_id)
                if result.status == "busy":
                    return result
            else:
                result = self.registry.mark_skipped(auth, request_id, operation_id)
            op, first = self._operation(kind, scope, operation_id, self.clock() + 120)
            if first:
                if result.status not in {"accepted", "duplicate"}:
                    self._finish(op, result)
                else:
                    self.media.suppress_phone_reply(request_id)
                    self._attach(op, getattr(self.controls, kind)(scope, operation_id))
        else:
            raise PhoneReplyRejected("invalid_request")
        return self.wait(op, retry=not first)

    def receipt(self, auth, receipt):
        self.authenticate(auth)
        # Registry validates ownership before any diagnostic about chunk IDs.
        scope, chunks = self.registry.freeze(auth, receipt)
        operation_id = identifier(receipt["interruption_id"])
        return scope, chunks, operation_id, self.registry.deadline(auth, scope.phone_request_id, operation_id)

    def begin_stt(self, auth, receipt):
        scope, chunks, operation_id, deadline = self.receipt(auth, receipt)
        outcome = self.registry.outcome(scope.phone_request_id, operation_id)
        # A pending onset ACK must not reserve an upload that no worker owns.
        result = outcome if outcome is not None else self.action(auth, {"kind": "onset", "receipt": receipt})
        op, first = self._operation("stt", scope, operation_id, deadline, chunks)
        if first:
            if outcome is not None:
                self._finish(op, outcome)
                return op, False
            if result.status not in {"accepted", "duplicate"}:
                self._finish(op, result)
                return op, False
        return op, first

    def complete_stt(self, op, auth, transcript, *, send_to_chat=True):
        if op.future.done():
            return
        if self.clock() >= op.deadline:
            self.timeout(op)
            return
        text = str(transcript or "").strip()
        if not text or not send_to_chat:
            # The same claim latch also arbitrates empty/abandoned completion.
            if not self.registry.claim_resolution(op.scope.phone_request_id, op.operation_id):
                self._finish(op, self.registry.outcome(op.scope.phone_request_id, op.operation_id) or PhoneReplyResult("stale", op.scope.phone_request_id))
                return
            self._attach(op, self.controls.abandon(op.scope, op.operation_id))
            return
        next_id = self.register(auth)
        op.next_request_id = next_id
        metadata = {"remote_capture_id": next_id, "phone_reply_control": True}
        if self.registry.shared_queue_enabled(auth):
            metadata["phone_shared_queue"] = True
        future = self.controls.resolve(op.scope, op.operation_id, op.chunks, text, next_id, metadata,
                 claim=lambda: self.registry.claim_resolution(op.scope.phone_request_id, op.operation_id))
        self._attach(op, future)

    def close(self):
        unsubscribe, self._unsubscribe = self._unsubscribe, None
        if unsubscribe is not None:
            unsubscribe()
        with self._lock:
            operations = tuple(self._operations.values())
            submissions = tuple(self._submissions.values())
        for op in operations:
            self.timeout(op)
        for op in submissions:
            self.timeout_submission(op)
