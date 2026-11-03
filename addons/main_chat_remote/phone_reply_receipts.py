"""Authenticated ownership registry for phone playback receipts.

The registry deliberately owns no runtime callbacks.  Expired holds are exposed
as immutable notifications for the gateway to drain after leaving this lock.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import hmac
import secrets
import threading
from typing import Literal

from core.runtime.phone_reply_controls import PhoneReplyResult, PhoneReplyScope


_MAX_CLIENTS = 64
_MAX_RECORDS = 256
_MAX_PENDING_INTERRUPTION_HOLDS = 2
_MAX_CHUNKS = 2048
_MAX_REPLY_TEXT_BYTES = 1024 * 1024
_MAX_TOTAL_TEXT_BYTES = 8 * 1024 * 1024
_INTERRUPTION_LEASE_SECONDS = 120.0
_COMPLETED_RETENTION_SECONDS = 15.0 * 60.0
_MAX_EXPIRY_NOTICES = _MAX_RECORDS
_RESULT_STATUSES = frozenset({"accepted", "duplicate", "stale", "unavailable", "busy"})


class PhoneReplyRejected(RuntimeError):
    """A sanitized registry rejection suitable for mapping to a wire error."""

    def __init__(self, reason: str) -> None:
        self.reason = str(reason)
        super().__init__(f"Phone reply request rejected: {self.reason}.")


@dataclass(slots=True, repr=False)
class _Client:
    key_digest: bytes = field(repr=False)
    last_active: float
    shared_queue: bool = False
    continuation: bool = False


@dataclass(frozen=True, slots=True, repr=False)
class _Chunk:
    chunk_id: str
    sequence_index: int
    text: str = field(repr=False)
    text_bytes: int


@dataclass(frozen=True, slots=True, repr=False)
class _FrozenReceipt:
    interruption_id: str
    chunk_ids: tuple[str, ...]
    texts: tuple[str, ...] = field(repr=False)
    deadline: float


@dataclass(slots=True, repr=False)
class _Reply:
    owner_epoch: str
    created_at: float
    scope: PhoneReplyScope | None = None
    phase: Literal["pending", "generating", "complete", "cancelled", "superseded"] = "pending"
    shared_queue: bool = False
    playback_acknowledged: bool = False
    playback_stop_requested: bool = False
    runtime_cancel_pending: bool = False
    chunks: dict[str, _Chunk] = field(default_factory=dict, repr=False)
    sequence_ids: list[str] = field(default_factory=list, repr=False)
    text_bytes: int = 0
    receipt_unavailable: bool = False
    receipt: _FrozenReceipt | None = field(default=None, repr=False)
    hold_active: bool = False
    receipt_expired: bool = False
    skipped_operation_id: str | None = None
    abandoned: bool = False
    resolution: PhoneReplyResult | None = None
    resolution_claimed: bool = False
    completed_at: float | None = None
    final_sequence_index: int | None = None


class PhoneReplyRegistry:
    """Bounded registry for one server's authenticated phone reply ownership."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._clients: dict[str, _Client] = {}
        self._replies: dict[str, _Reply] = {}
        self._total_text_bytes = 0
        self._expired: list[tuple[PhoneReplyScope, str]] = []

    def _now(self) -> float:
        # The injected clock is caller-owned and therefore invoked outside locks.
        return float(self._clock())

    def diagnostic_snapshot(self) -> dict:
        """Read-only bounded ownership state; no capabilities or dialogue."""
        with self._lock:
            records = list(self._replies.items())[-32:]
            return {'total': len(self._replies), 'replies': [
                {'reply_id': identity, 'phase': row.phase, 'bound': row.scope is not None,
                 'acknowledged': row.playback_acknowledged, 'stop_requested': row.playback_stop_requested,
                 'runtime_cancel_pending': row.runtime_cancel_pending,
                 'hold_active': row.hold_active, 'chunks': len(row.chunks),
                 'final_sequence': row.final_sequence_index}
                for identity, row in records]}

    def runtime_change_busy(self) -> bool:
        """Read ownership without retiring receipts or altering any playback state."""
        with self._lock:
            return any(row.phase in {"pending", "generating"} or row.hold_active
                       or row.runtime_cancel_pending
                       or (row.shared_queue and not row.playback_acknowledged)
                       for row in self._replies.values())

    def request_for_transaction(self, transaction_id: str, session_generation: int) -> str | None:
        """Internal correlation only; never exposes a phone capability or auth."""
        if not transaction_id or type(session_generation) is not int:
            return None
        with self._lock:
            for request_id, reply in reversed(tuple(self._replies.items())):
                scope = reply.scope
                if (scope is not None and reply.phase not in {'cancelled', 'superseded'}
                        and not reply.playback_stop_requested
                        and scope.normal_chat_transaction_id == transaction_id
                        and scope.session_generation == session_generation):
                    return request_id
        return None

    @staticmethod
    def _auth_material(auth: Mapping[str, str]) -> tuple[str, bytes]:
        try:
            epoch_value = auth.get("connection_epoch", "")
            key_value = auth.get("client_key", "")
        except Exception:
            raise PhoneReplyRejected("authentication") from None
        epoch = epoch_value if type(epoch_value) is str else ""
        key = key_value if type(key_value) is str else ""
        return epoch, hashlib.sha256(key.encode("utf-8")).digest()

    def _authenticate_locked(self, epoch: str, supplied_digest: bytes) -> None:
        client = self._clients.get(epoch)
        expected = client.key_digest if client is not None else bytes(32)
        matches = hmac.compare_digest(expected, supplied_digest)
        if client is None or not matches:
            raise PhoneReplyRejected("authentication")

    def _authenticate(self, epoch: str, supplied_digest: bytes) -> None:
        with self._lock:
            self._authenticate_locked(epoch, supplied_digest)

    def _authenticate_and_touch_locked(
        self,
        epoch: str,
        supplied_digest: bytes,
        now: float,
    ) -> None:
        self._authenticate_locked(epoch, supplied_digest)
        self._clients[epoch].last_active = now

    def _maintain_locked(self, now: float) -> None:
        for request_id, reply in tuple(self._replies.items()):
            receipt = reply.receipt
            if (
                reply.hold_active
                and not reply.resolution_claimed
                and receipt is not None
                and now >= receipt.deadline
            ):
                reply.hold_active = False
                reply.receipt_expired = True
                reply.resolution = PhoneReplyResult("stale", request_id)
                if reply.scope is not None:
                    self._expired.append((reply.scope, receipt.interruption_id))

        for request_id, reply in tuple(self._replies.items()):
            if (
                reply.completed_at is not None
                and not reply.hold_active
                and not (reply.shared_queue and not reply.playback_acknowledged)
                and not (reply.runtime_cancel_pending and reply.scope is not None)
                and now - reply.completed_at >= _COMPLETED_RETENTION_SECONDS
            ):
                self._total_text_bytes -= reply.text_bytes
                del self._replies[request_id]

        active_owners = {
            reply.owner_epoch
            for reply in self._replies.values()
            if reply.phase in {"pending", "generating"} or reply.hold_active
            or (reply.shared_queue and not reply.playback_acknowledged)
            or (reply.runtime_cancel_pending and reply.scope is not None)
        }
        for epoch, client in tuple(self._clients.items()):
            if (
                epoch not in active_owners
                and now - client.last_active >= _COMPLETED_RETENTION_SECONDS
            ):
                del self._clients[epoch]

    @staticmethod
    def _request_id(value: object) -> str:
        if type(value) is not str or not value or len(value) > 128:
            raise PhoneReplyRejected("invalid_request")
        return value

    def _owned_reply_locked(self, epoch: str, request_id: str) -> _Reply:
        reply = self._replies.get(request_id)
        if reply is None or reply.owner_epoch != epoch:
            raise PhoneReplyRejected("ownership")
        return reply

    @staticmethod
    def _current_scope_locked(reply: _Reply) -> PhoneReplyScope:
        if reply.scope is None:
            raise PhoneReplyRejected("stale_scope")
        return reply.scope

    @staticmethod
    def _canonical_scope(scope: PhoneReplyScope) -> PhoneReplyScope:
        if type(scope) is not PhoneReplyScope:
            raise PhoneReplyRejected("stale_scope")
        request_id = scope.phone_request_id
        transaction_id = scope.normal_chat_transaction_id
        generation = scope.session_generation
        if (
            type(request_id) is not str
            or not request_id
            or type(transaction_id) is not str
            or not transaction_id
            or type(generation) is not int
            or generation < 0
        ):
            raise PhoneReplyRejected("stale_scope")
        return PhoneReplyScope(request_id, transaction_id, generation)

    @staticmethod
    def _canonical_result(result: PhoneReplyResult) -> PhoneReplyResult:
        if type(result) is not PhoneReplyResult:
            raise PhoneReplyRejected("conflicting_resolution")
        status = result.status
        request_id = result.phone_request_id
        next_request_id = result.next_phone_request_id
        if (
            type(status) is not str
            or status not in _RESULT_STATUSES
            or type(request_id) is not str
            or not request_id
            or (
                next_request_id is not None
                and (type(next_request_id) is not str or not next_request_id)
            )
        ):
            raise PhoneReplyRejected("conflicting_resolution")
        return PhoneReplyResult(status, request_id, next_request_id)

    def new_client(self, *, shared_queue: bool = False, continuation: bool = False) -> dict[str, object]:
        if continuation and not shared_queue:
            raise PhoneReplyRejected("invalid_request")
        now = self._now()
        with self._lock:
            self._maintain_locked(now)
            if len(self._clients) >= _MAX_CLIENTS:
                raise PhoneReplyRejected("capacity")
            while True:
                epoch = secrets.token_urlsafe(18)
                if epoch not in self._clients:
                    break
            client_key = secrets.token_urlsafe(32)
            digest = hashlib.sha256(client_key.encode("utf-8")).digest()
            self._clients[epoch] = _Client(key_digest=digest, last_active=now, shared_queue=shared_queue is True, continuation=continuation is True)
        return {"client_key": client_key, "connection_epoch": epoch,
                **({"shared_queue_version": 1} if shared_queue is True else {}),
                **({"reply_continuation_version": 1} if continuation is True else {})}

    def continuation_enabled(self, auth) -> bool:
        epoch, digest = self._auth_material(auth)
        with self._lock:
            self._authenticate_locked(epoch, digest)
            return self._clients[epoch].continuation

    def expire_continuation(self, request_id):
        """Internal retention expiry; releases output only, never conversation text."""
        with self._lock:
            reply = self._replies.get(request_id)
            if reply is None or reply.playback_acknowledged:
                return None
            reply.playback_stop_requested = True
            return reply.scope

    def shared_queue_enabled(self, auth: Mapping[str, str]) -> bool:
        epoch, digest = self._auth_material(auth)
        with self._lock:
            self._authenticate_locked(epoch, digest)
            return self._clients[epoch].shared_queue

    def authenticate(self, auth: Mapping[str, str]) -> str:
        """Validate a private capability before expensive admission work."""
        epoch, digest = self._auth_material(auth)
        now = self._now()
        with self._lock:
            self._maintain_locked(now)
            self._authenticate_and_touch_locked(epoch, digest, now)
        return epoch

    def cleanup_owner_exists(self, epoch: str) -> bool:
        """Inspect existing cleanup authority without renewing it or acknowledging media."""
        now = self._now()
        with self._lock:
            self._maintain_locked(now)
            return epoch in self._clients

    def register(self, auth: Mapping[str, str], request_id: str) -> None:
        epoch, digest = self._auth_material(auth)
        self._authenticate(epoch, digest)
        request_key = self._request_id(request_id)
        now = self._now()
        with self._lock:
            self._authenticate_and_touch_locked(epoch, digest, now)
            self._maintain_locked(now)
            existing = self._replies.get(request_key)
            if existing is not None:
                if existing.owner_epoch != epoch:
                    raise PhoneReplyRejected("ownership")
                return
            if len(self._replies) >= _MAX_RECORDS:
                raise PhoneReplyRejected("capacity")
            self._replies[request_key] = _Reply(
                owner_epoch=epoch,
                created_at=now,
                shared_queue=self._clients[epoch].shared_queue,
            )

    def supersede_pending(self, request_id: str) -> bool:
        request_key = self._request_id(request_id)
        now = self._now()
        with self._lock:
            reply = self._replies.get(request_key)
            if reply is None or not reply.shared_queue or reply.scope is not None or reply.phase != "pending":
                return False
            reply.phase = "superseded"
            reply.playback_acknowledged = True
            reply.completed_at = now
            return True

    def request_playback_stop(self, request_id: str) -> None:
        with self._lock:
            reply = self._replies.get(request_id)
            if reply is not None and reply.shared_queue and reply.scope is not None:
                reply.playback_stop_requested = True

    def confirm_playback_suppressed(self, request_id: str) -> None:
        """Internal receipt from an accepted owner hold/skip, not a wire claim."""
        now = self._now()
        with self._lock:
            reply = self._replies.get(request_id)
            if reply is not None and reply.shared_queue and not reply.playback_acknowledged:
                reply.playback_acknowledged = True
                if reply.completed_at is not None:
                    reply.completed_at = now

    def acknowledge_playback(self, auth: Mapping[str, str], request_id: str) -> None:
        epoch, digest = self._auth_material(auth)
        request_key = self._request_id(request_id)
        now = self._now()
        with self._lock:
            self._authenticate_and_touch_locked(epoch, digest, now)
            reply = self._owned_reply_locked(epoch, request_key)
            if not reply.shared_queue or (reply.phase != "complete" and not reply.skipped_operation_id and not reply.playback_stop_requested):
                raise PhoneReplyRejected("invalid_completion")
            if not reply.playback_acknowledged:
                reply.playback_acknowledged = True
                if reply.completed_at is not None:
                    reply.completed_at = now

    def bind(self, request_id: str, scope: PhoneReplyScope) -> None:
        request_key = self._request_id(request_id)
        canonical_scope = self._canonical_scope(scope)
        now = self._now()
        with self._lock:
            self._maintain_locked(now)
            reply = self._replies.get(request_key)
            if reply is None:
                raise PhoneReplyRejected("stale_scope")
            if canonical_scope.phone_request_id != request_key:
                raise PhoneReplyRejected("stale_scope")
            if reply.scope is not None:
                if reply.scope != canonical_scope:
                    raise PhoneReplyRejected("stale_scope")
                return
            if reply.phase in {"complete", "cancelled", "superseded"}:
                if reply.phase == "cancelled" and reply.runtime_cancel_pending:
                    # Admission cancellation can race owner binding. Remember
                    # its identity only to release it; never revive the reply.
                    reply.scope = canonical_scope
                    return
                raise PhoneReplyRejected("stale_scope")
            reply.scope = canonical_scope
            reply.phase = "generating"

    def pending_recovery_replies(self, owner_epoch, request_ids):
        """Internal exact-owner lookup, independent of producer completion.

        Unacknowledged shared replies cannot be evicted by maintenance. Missing
        records therefore carry no outstanding playback obligation here.
        """
        with self._lock:
            pending = []
            for request_id in request_ids:
                reply = self._replies.get(request_id)
                if reply is None:
                    continue
                if reply.owner_epoch != owner_epoch:
                    raise PhoneReplyRejected('ownership')
                if reply.shared_queue and not reply.playback_acknowledged:
                    pending.append(request_id)
            return tuple(pending)

    def recovery_stop_scope(self, owner_epoch, request_id):
        """Internal exact-owner stop; caller must already verify recovery proof."""
        with self._lock:
            reply = self._replies.get(request_id)
            if reply is None: return None
            if reply.owner_epoch != owner_epoch: raise PhoneReplyRejected('ownership')
            reply.playback_stop_requested = True
            if reply.scope is None:
                reply.phase = 'cancelled'
                return None
            return reply.scope

    def scope(self, auth: Mapping[str, str], request_id: str) -> PhoneReplyScope:
        epoch, digest = self._auth_material(auth)
        self._authenticate(epoch, digest)
        request_key = self._request_id(request_id)
        now = self._now()
        with self._lock:
            self._authenticate_and_touch_locked(epoch, digest, now)
            self._maintain_locked(now)
            reply = self._owned_reply_locked(epoch, request_key)
            return self._current_scope_locked(reply)

    def add_chunk(
        self,
        request_id: str,
        chunk_id: str,
        sequence_index: int,
        text: str,
    ) -> None:
        request_key = self._request_id(request_id)
        chunk_key = self._request_id(chunk_id)
        if (
            type(sequence_index) is not int
            or sequence_index < 0
            or type(text) is not str
        ):
            raise PhoneReplyRejected("invalid_chunk")
        encoded_size = len(text.encode("utf-8"))
        now = self._now()
        with self._lock:
            self._maintain_locked(now)
            reply = self._replies.get(request_key)
            if reply is None:
                raise PhoneReplyRejected("stale_scope")
            existing = reply.chunks.get(chunk_key)
            if existing is not None:
                if existing.sequence_index == sequence_index and existing.text == text:
                    return
                raise PhoneReplyRejected("conflicting_chunk")
            if reply.receipt_unavailable:
                raise PhoneReplyRejected("unavailable")
            if reply.phase in {"complete", "cancelled"}:
                raise PhoneReplyRejected("stale_scope")
            if sequence_index != len(reply.sequence_ids):
                raise PhoneReplyRejected("conflicting_chunk")
            if len(reply.sequence_ids) >= _MAX_CHUNKS:
                reply.receipt_unavailable = True
                raise PhoneReplyRejected("unavailable")
            if (
                reply.text_bytes + encoded_size > _MAX_REPLY_TEXT_BYTES
                or self._total_text_bytes + encoded_size > _MAX_TOTAL_TEXT_BYTES
            ):
                reply.receipt_unavailable = True
                raise PhoneReplyRejected("unavailable")
            reply.chunks[chunk_key] = _Chunk(
                chunk_id=chunk_key,
                sequence_index=sequence_index,
                text=text,
                text_bytes=encoded_size,
            )
            reply.sequence_ids.append(chunk_key)
            reply.text_bytes += encoded_size
            self._total_text_bytes += encoded_size

    @staticmethod
    def _receipt_request_id(receipt: Mapping[str, object]) -> str:
        if not isinstance(receipt, Mapping):
            raise PhoneReplyRejected("invalid_receipt")
        try:
            request_id = receipt.get("phone_request_id")
        except Exception:
            raise PhoneReplyRejected("invalid_receipt") from None
        if type(request_id) is not str or not request_id:
            raise PhoneReplyRejected("invalid_receipt")
        return request_id

    @staticmethod
    def _receipt_material(
        receipt: Mapping[str, object],
    ) -> tuple[str, str, tuple[str, ...]]:
        if not isinstance(receipt, Mapping):
            raise PhoneReplyRejected("invalid_receipt")
        if "text" in receipt:
            raise PhoneReplyRejected("invalid_receipt")
        request_id = receipt.get("phone_request_id")
        interruption_id = receipt.get("interruption_id")
        started = receipt.get("started_chunk_ids")
        if (
            type(request_id) is not str
            or not request_id
            or len(request_id) > 128
            or type(interruption_id) is not str
            or not interruption_id
            or len(interruption_id) > 128
            or not isinstance(started, Sequence)
            or isinstance(started, (str, bytes, bytearray))
        ):
            raise PhoneReplyRejected("invalid_receipt")
        if len(started) > _MAX_CHUNKS:
            raise PhoneReplyRejected("capacity")
        chunk_ids = tuple(started)
        if any(type(chunk_id) is not str or not chunk_id or len(chunk_id) > 128 for chunk_id in chunk_ids):
            raise PhoneReplyRejected("invalid_receipt")
        if len(set(chunk_ids)) != len(chunk_ids):
            raise PhoneReplyRejected("invalid_receipt")
        return request_id, interruption_id, chunk_ids

    def freeze(
        self,
        auth: Mapping[str, str],
        receipt: Mapping[str, object],
    ) -> tuple[PhoneReplyScope, tuple[str, ...]]:
        epoch, digest = self._auth_material(auth)
        self._authenticate(epoch, digest)
        request_id = self._receipt_request_id(receipt)
        now = self._now()
        with self._lock:
            self._authenticate_and_touch_locked(epoch, digest, now)
            self._maintain_locked(now)
            reply = self._owned_reply_locked(epoch, request_id)
            self._current_scope_locked(reply)

        # Receipt mappings and sequences are caller-owned.  Normalize them only
        # after ownership/scope checks and never while the registry lock is held.
        parsed_request_id, interruption_id, chunk_ids = self._receipt_material(receipt)
        if parsed_request_id != request_id:
            raise PhoneReplyRejected("invalid_receipt")

        with self._lock:
            self._authenticate_and_touch_locked(epoch, digest, now)
            self._maintain_locked(now)
            reply = self._owned_reply_locked(epoch, request_id)
            scope = self._current_scope_locked(reply)
            chunks: list[_Chunk] = []
            previous_index = -1
            for chunk_id in chunk_ids:
                chunk = reply.chunks.get(chunk_id)
                if chunk is None:
                    raise PhoneReplyRejected("unknown_chunk")
                if chunk.sequence_index <= previous_index:
                    raise PhoneReplyRejected("invalid_receipt")
                chunks.append(chunk)
                previous_index = chunk.sequence_index

            existing = reply.receipt
            if existing is not None:
                if (
                    existing.interruption_id != interruption_id
                    or existing.chunk_ids != chunk_ids
                ):
                    raise PhoneReplyRejected("conflicting_receipt")
                return scope, existing.texts

            if reply.receipt_unavailable:
                raise PhoneReplyRejected("unavailable")
            if reply.skipped_operation_id is not None or reply.phase == "cancelled":
                raise PhoneReplyRejected("stale_scope")
            pending = sum(
                1
                for candidate in self._replies.values()
                if candidate.owner_epoch == epoch and candidate.hold_active
            )
            if pending >= _MAX_PENDING_INTERRUPTION_HOLDS:
                raise PhoneReplyRejected("capacity")
            active_holds = sum(
                1 for candidate in self._replies.values() if candidate.hold_active
            )
            if len(self._expired) + active_holds >= _MAX_EXPIRY_NOTICES:
                raise PhoneReplyRejected("capacity")
            texts = tuple(chunk.text for chunk in chunks)
            reply.receipt = _FrozenReceipt(
                interruption_id=interruption_id,
                chunk_ids=chunk_ids,
                texts=texts,
                deadline=now + _INTERRUPTION_LEASE_SECONDS,
            )
            reply.hold_active = True
            return scope, texts

    def mark_skipped(
        self,
        auth: Mapping[str, str],
        request_id: str,
        operation_id: str,
    ) -> PhoneReplyResult:
        epoch, digest = self._auth_material(auth)
        self._authenticate(epoch, digest)
        request_key = self._request_id(request_id)
        now = self._now()
        with self._lock:
            self._authenticate_and_touch_locked(epoch, digest, now)
            self._maintain_locked(now)
            reply = self._owned_reply_locked(epoch, request_key)
            if reply.scope is None or reply.phase == "cancelled":
                return PhoneReplyResult("stale", request_key)

        operation_key = self._request_id(operation_id)
        with self._lock:
            self._authenticate_and_touch_locked(epoch, digest, now)
            self._maintain_locked(now)
            reply = self._owned_reply_locked(epoch, request_key)
            if reply.scope is None or reply.phase == "cancelled":
                return PhoneReplyResult("stale", request_key)
            if reply.skipped_operation_id is not None:
                if reply.skipped_operation_id == operation_key:
                    return PhoneReplyResult("duplicate", request_key)
                raise PhoneReplyRejected("conflicting_operation")
            if reply.receipt is not None:
                status = "busy" if reply.hold_active else "stale"
                return PhoneReplyResult(status, request_key)
            if reply.receipt_unavailable:
                return PhoneReplyResult("unavailable", request_key)
            reply.skipped_operation_id = operation_key
            return PhoneReplyResult("accepted", request_key)

    def complete(self, request_id: str, final_sequence_index: int | None) -> None:
        request_key = self._request_id(request_id)
        if final_sequence_index is not None and (
            type(final_sequence_index) is not int
            or final_sequence_index < 0
        ):
            raise PhoneReplyRejected("invalid_completion")
        now = self._now()
        with self._lock:
            self._maintain_locked(now)
            reply = self._replies.get(request_key)
            if reply is None:
                raise PhoneReplyRejected("stale_scope")
            if reply.completed_at is not None:
                if reply.final_sequence_index != final_sequence_index:
                    raise PhoneReplyRejected("conflicting_operation")
                return
            last_sequence = len(reply.sequence_ids) - 1
            expected = last_sequence if last_sequence >= 0 else None
            if final_sequence_index != expected:
                raise PhoneReplyRejected("invalid_completion")
            reply.phase = "complete"
            reply.final_sequence_index = final_sequence_index
            reply.completed_at = now
            client = self._clients.get(reply.owner_epoch)
            if client is not None:
                client.last_active = now

    def status(
        self,
        auth: Mapping[str, str],
        request_id: str,
    ) -> dict[str, object]:
        epoch, digest = self._auth_material(auth)
        self._authenticate(epoch, digest)
        request_key = self._request_id(request_id)
        now = self._now()
        with self._lock:
            self._authenticate_and_touch_locked(epoch, digest, now)
            self._maintain_locked(now)
            reply = self._owned_reply_locked(epoch, request_key)
            if reply.completed_at is not None:
                last_sequence = reply.final_sequence_index
            elif reply.sequence_ids:
                last_sequence = len(reply.sequence_ids) - 1
            else:
                last_sequence = None
            return {
                "phone_request_id": request_key,
                "phase": reply.phase,
                "last_sequence_index": last_sequence,
                **({"playback_stop_requested": True} if reply.shared_queue and reply.playback_stop_requested else {}),
            }

    def abandon(
        self,
        auth: Mapping[str, str],
        request_id: str,
        interruption_id: str,
    ) -> PhoneReplyResult:
        epoch, digest = self._auth_material(auth)
        self._authenticate(epoch, digest)
        request_key = self._request_id(request_id)
        now = self._now()
        with self._lock:
            self._authenticate_and_touch_locked(epoch, digest, now)
            self._maintain_locked(now)
            reply = self._owned_reply_locked(epoch, request_key)
            self._current_scope_locked(reply)

        interruption_key = self._request_id(interruption_id)
        with self._lock:
            self._authenticate_and_touch_locked(epoch, digest, now)
            self._maintain_locked(now)
            reply = self._owned_reply_locked(epoch, request_key)
            self._current_scope_locked(reply)
            receipt = reply.receipt
            if receipt is None or receipt.interruption_id != interruption_key:
                raise PhoneReplyRejected("conflicting_receipt")
            if reply.resolution_claimed and reply.resolution is None:
                return PhoneReplyResult("busy", request_key)
            if reply.resolution is not None or reply.abandoned:
                return PhoneReplyResult("duplicate", request_key)
            if reply.receipt_expired:
                return PhoneReplyResult("stale", request_key)
            reply.hold_active = False
            reply.abandoned = True
            reply.resolution = PhoneReplyResult("accepted", request_key)
            return reply.resolution

    def resolution(self, auth, request_id: str, interruption_id: str) -> PhoneReplyResult | None:
        epoch = self.authenticate(auth)
        request_key = self._request_id(request_id)
        interruption_key = self._request_id(interruption_id)
        with self._lock:
            reply = self._owned_reply_locked(epoch, request_key)
            if reply.receipt is None or reply.receipt.interruption_id != interruption_key:
                raise PhoneReplyRejected("conflicting_receipt")
            return reply.resolution

    def deadline(self, auth, request_id: str, interruption_id: str) -> float:
        epoch = self.authenticate(auth)
        request_key = self._request_id(request_id)
        interruption_key = self._request_id(interruption_id)
        with self._lock:
            reply = self._owned_reply_locked(epoch, request_key)
            if reply.receipt is None or reply.receipt.interruption_id != interruption_key:
                raise PhoneReplyRejected("conflicting_receipt")
            return reply.receipt.deadline

    def claim_resolution(self, request_id: str, interruption_id: str) -> bool:
        """The runtime calls this once immediately before its conditional write."""
        request_key = self._request_id(request_id)
        interruption_key = self._request_id(interruption_id)
        now = self._now()
        with self._lock:
            self._maintain_locked(now)
            reply = self._replies.get(request_key)
            if (reply is None or reply.receipt is None
                    or reply.receipt.interruption_id != interruption_key
                    or not reply.hold_active or reply.resolution is not None
                    or reply.resolution_claimed or reply.phase == "cancelled"):
                return False
            reply.resolution_claimed = True
            return True

    def outcome(self, request_id: str, interruption_id: str) -> PhoneReplyResult | None:
        request_key = self._request_id(request_id)
        interruption_key = self._request_id(interruption_id)
        now = self._now()
        with self._lock:
            self._maintain_locked(now)
            reply = self._replies.get(request_key)
            if reply is None or reply.receipt is None or reply.receipt.interruption_id != interruption_key:
                raise PhoneReplyRejected("stale_scope")
            return reply.resolution

    def expire_resolution(self, request_id: str, interruption_id: str) -> bool:
        """End an unclaimed request budget, never reverse a runtime claim."""
        request_key = self._request_id(request_id)
        interruption_key = self._request_id(interruption_id)
        now = self._now()
        with self._lock:
            self._maintain_locked(now)
            reply = self._replies.get(request_key)
            if reply is None or reply.receipt is None or reply.receipt.interruption_id != interruption_key:
                return False
            if reply.resolution_claimed:
                return False
            if reply.resolution is None:
                reply.resolution = PhoneReplyResult("stale", request_key)
                reply.hold_active = False
                reply.receipt_expired = True
                if reply.scope is not None:
                    self._expired.append((reply.scope, interruption_key))
            return True

    def cancel(self, request_id: str) -> None:
        """Terminate failed admission or a replaced scope, preserving won results."""
        request_key = self._request_id(request_id)
        now = self._now()
        with self._lock:
            self._maintain_locked(now)
            reply = self._replies.get(request_key)
            if reply is None:
                return
            if reply.phase != "cancelled":
                reply.runtime_cancel_pending = reply.shared_queue and not reply.playback_acknowledged
            reply.phase = "cancelled"
            reply.playback_acknowledged = True
            reply.final_sequence_index = len(reply.sequence_ids) - 1 if reply.sequence_ids else None
            reply.completed_at = now
            if reply.hold_active and not reply.resolution_claimed:
                reply.hold_active = False
                reply.resolution = PhoneReplyResult("stale", request_key)
                if reply.scope is not None and reply.receipt is not None:
                    self._expired.append((reply.scope, reply.receipt.interruption_id))
            client = self._clients.get(reply.owner_epoch)
            if client is not None:
                client.last_active = now

    def pending_runtime_cancellations(self) -> tuple[PhoneReplyScope, ...]:
        """Internal owner work, retained until the mailbox confirms release."""
        with self._lock:
            return tuple(reply.scope for reply in self._replies.values()
                         if reply.runtime_cancel_pending and reply.scope is not None)

    def confirm_runtime_cancellation(self, scope: PhoneReplyScope) -> None:
        with self._lock:
            reply = self._replies.get(scope.phone_request_id)
            if reply is not None and reply.scope == scope:
                reply.runtime_cancel_pending = False

    def resolve(
        self,
        request_id: str,
        interruption_id: str,
        result: PhoneReplyResult,
    ) -> None:
        request_key = self._request_id(request_id)
        interruption_key = self._request_id(interruption_id)
        canonical_result = self._canonical_result(result)
        if canonical_result.phone_request_id != request_key:
            raise PhoneReplyRejected("conflicting_resolution")
        now = self._now()
        with self._lock:
            self._maintain_locked(now)
            reply = self._replies.get(request_key)
            if reply is None or reply.receipt is None:
                raise PhoneReplyRejected("stale_scope")
            if reply.receipt.interruption_id != interruption_key:
                raise PhoneReplyRejected("conflicting_receipt")
            if reply.resolution is not None:
                if reply.resolution != canonical_result:
                    raise PhoneReplyRejected("conflicting_resolution")
                return
            reply.resolution = canonical_result
            reply.hold_active = False
            client = self._clients.get(reply.owner_epoch)
            if client is not None:
                client.last_active = now

    def drain_expired(self) -> tuple[tuple[PhoneReplyScope, str], ...]:
        """Return each expired hold once, without invoking registry-external code."""

        now = self._now()
        with self._lock:
            self._maintain_locked(now)
            pending = tuple(self._expired)
            self._expired.clear()
            return pending


__all__ = ["PhoneReplyRegistry", "PhoneReplyRejected"]
