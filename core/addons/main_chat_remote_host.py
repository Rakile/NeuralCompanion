"""Generation-bound immutable snapshot subscriptions for Main Chat Remote."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import logging
from pathlib import Path
import threading
from types import MappingProxyType
from core.runtime.phone_reply_controls import PhoneReplyControlPort


_MISSING = object()


def _freeze_snapshot(value):
    if value is None or isinstance(value, (str, bytes, int, float, bool, Path)):
        return value
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                _freeze_snapshot(key): _freeze_snapshot(item)
                for key, item in value.items()
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_snapshot(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_snapshot(item) for item in value)
    raise TypeError(
        f"Main Chat Remote snapshots cannot expose {type(value).__name__}."
    )


@dataclass(slots=True)
class _SubscriptionRecord:
    token: int
    kind: str
    addon_id: str
    generation: int
    owner_is_open: Callable[[], bool]
    callback: Callable[[object], None]
    active: bool = True


class MainChatRemoteSubscription:
    """Idempotent teardown handle for one immutable snapshot subscription."""

    def __init__(self, service: "MainChatRemoteHostService", token: int) -> None:
        self._service = service
        self._token = int(token)

    @property
    def closed(self) -> bool:
        return not self._service._subscription_active(self._token)

    def close(self) -> None:
        self._service._unsubscribe(self._token)


class MainChatRemoteHostPort:
    """Exact named host operations bound to one addon generation."""

    def __init__(
        self,
        service: "MainChatRemoteHostService",
        *,
        addon_id: str,
        generation: int,
        owner_is_open: Callable[[], bool],
    ) -> None:
        self._service = service
        self._addon_id = str(addon_id)
        self._generation = int(generation)
        self._owner_is_open = owner_is_open
        self._closed = False
        self._phone_subscriptions = []

    def status_snapshot(self):
        self._ensure_open()
        return self._service.status_snapshot()

    def history_snapshot(self):
        self._ensure_open()
        return self._service.history_snapshot()

    def portrait_playback_snapshot(self):
        self._ensure_open()
        return self._service.portrait_playback_snapshot()

    def subscribe_status(self, callback) -> MainChatRemoteSubscription:
        self._ensure_open()
        return self._service._subscribe(
            "status",
            callback,
            addon_id=self._addon_id,
            generation=self._generation,
            owner_is_open=self._owner_is_open,
        )

    def subscribe_history(self, callback) -> MainChatRemoteSubscription:
        self._ensure_open()
        return self._service._subscribe(
            "history",
            callback,
            addon_id=self._addon_id,
            generation=self._generation,
            owner_is_open=self._owner_is_open,
        )

    def close(self) -> None:
        self._closed = True
        for unsubscribe in self._phone_subscriptions:
            unsubscribe()
        self._phone_subscriptions.clear()
        self._service._unsubscribe_owner(self._addon_id, self._generation)

    def phone_reply_controls(self) -> PhoneReplyControlPort | None:
        self._ensure_open()
        port = self._service.phone_reply_controls()
        return (port._for_generation(lambda: not self._closed and self._owner_is_open(),
                            self._phone_subscriptions.append) if port is not None else None)

    @property
    def conditional_input_available(self) -> bool:
        return not self._closed and self._owner_is_open() and callable(self._service._conditional_input)

    def submit_if_current_and_idle(self, text: str, **kwargs):
        self._ensure_open()
        if not self.conditional_input_available:
            return {"status": "unavailable"}
        return self._service._conditional_input(text, **kwargs)

    def stage_continuous_next(self, proposed_user, binding, cancellation):
        self._ensure_open()
        callback = self._service._stage_continuous_next
        return callback(proposed_user, binding, cancellation) if callable(callback) else None

    def user_speech_runtime(self):
        self._ensure_open()
        if self._service._user_speech_runtime is None:
            raise RuntimeError("Desktop user speech is unavailable. Restart NC.")
        return self._service._user_speech_runtime

    def _ensure_open(self) -> None:
        if self._closed or not self._owner_is_open():
            raise RuntimeError(
                f"Main Chat Remote host generation {self._generation} is closed."
            )


class MainChatRemoteHostService:
    """Publishes immutable status/history without owning a polling loop."""

    def __init__(
        self,
        *,
        status_snapshot: Callable[[], object],
        history_snapshot: Callable[[], object],
        phone_reply_controls: Callable[[], PhoneReplyControlPort | None] | None = None,
        portrait_playback_snapshot: Callable[[], object] | None = None,
        conditional_input: Callable | None = None,
        stage_continuous_next: Callable | None = None,
        user_speech_runtime: object | None = None,
    ) -> None:
        self._status_snapshot = status_snapshot
        self._history_snapshot = history_snapshot
        self._phone_reply_controls = phone_reply_controls
        self._portrait_playback_snapshot = portrait_playback_snapshot
        self._conditional_input = conditional_input
        self._stage_continuous_next = stage_continuous_next
        self._user_speech_runtime = user_speech_runtime
        self._lock = threading.RLock()
        self._next_token = 1
        self._subscriptions: dict[int, _SubscriptionRecord] = {}

    def bind(
        self,
        *,
        addon_id: str,
        generation: int,
        owner_is_open: Callable[[], bool],
    ) -> MainChatRemoteHostPort:
        normalized = str(addon_id or "").strip()
        if normalized != "nc.main_chat_remote":
            raise PermissionError(
                f"Main Chat Remote host rejected addon '{normalized}'."
            )
        return MainChatRemoteHostPort(
            self,
            addon_id=normalized,
            generation=int(generation),
            owner_is_open=owner_is_open,
        )

    def status_snapshot(self):
        return _freeze_snapshot(self._status_snapshot())

    def phone_reply_controls(self) -> PhoneReplyControlPort | None:
        return self._phone_reply_controls() if self._phone_reply_controls is not None else None

    def history_snapshot(self):
        return _freeze_snapshot(self._history_snapshot())

    def portrait_playback_snapshot(self):
        return _freeze_snapshot(self._portrait_playback_snapshot() if self._portrait_playback_snapshot else {})

    def publish_status(self, snapshot=_MISSING) -> None:
        self._publish(
            "status",
            self.status_snapshot() if snapshot is _MISSING else _freeze_snapshot(snapshot),
        )

    def publish_history(self, snapshot=_MISSING) -> None:
        self._publish(
            "history",
            self.history_snapshot() if snapshot is _MISSING else _freeze_snapshot(snapshot),
        )

    def _subscribe(
        self,
        kind: str,
        callback,
        *,
        addon_id: str,
        generation: int,
        owner_is_open: Callable[[], bool],
    ) -> MainChatRemoteSubscription:
        if not callable(callback):
            raise TypeError("Snapshot subscriber must be callable.")
        with self._lock:
            token = self._next_token
            self._next_token += 1
            self._subscriptions[token] = _SubscriptionRecord(
                token=token,
                kind=str(kind),
                addon_id=str(addon_id),
                generation=int(generation),
                owner_is_open=owner_is_open,
                callback=callback,
            )
        return MainChatRemoteSubscription(self, token)

    def _publish(self, kind: str, snapshot) -> None:
        with self._lock:
            subscriptions = tuple(
                record
                for record in self._subscriptions.values()
                if record.active and record.kind == kind
            )
        for record in subscriptions:
            if not record.owner_is_open():
                self._unsubscribe(record.token)
                continue
            try:
                record.callback(snapshot)
            except Exception:
                logging.getLogger("nc.addons.main_chat_remote_host").exception(
                    "Main Chat Remote %s subscriber failed.",
                    kind,
                )

    def _subscription_active(self, token: int) -> bool:
        with self._lock:
            record = self._subscriptions.get(int(token))
            return bool(record is not None and record.active)

    def _unsubscribe(self, token: int) -> None:
        with self._lock:
            record = self._subscriptions.pop(int(token), None)
            if record is not None:
                record.active = False

    def _unsubscribe_owner(self, addon_id: str, generation: int) -> None:
        with self._lock:
            tokens = tuple(
                token
                for token, record in self._subscriptions.items()
                if record.addon_id == str(addon_id)
                and record.generation == int(generation)
            )
        for token in tokens:
            self._unsubscribe(token)


__all__ = [
    "MainChatRemoteHostPort",
    "MainChatRemoteHostService",
    "MainChatRemoteSubscription",
]
