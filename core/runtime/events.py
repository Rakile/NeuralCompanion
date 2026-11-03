"""Low-frequency runtime event notifications."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence, Set
from dataclasses import dataclass, fields, is_dataclass
import logging
import threading
from types import FunctionType, MethodType
from typing import Generic, Protocol, TypeVar

from core.runtime.identifiers import WorkLease


T = TypeVar("T")
_LOGGER = logging.getLogger(__name__)

_PROHIBITED_PAYLOAD_TYPE_NAMES = frozenset(
    {
        "amplitudesample",
        "audiochunk",
        "audiosample",
        "imagebytes",
        "imagedata",
        "imagepayload",
        "providertoken",
        "streamingtoken",
        "texttospeechchunk",
        "ttschunk",
    }
)
_PROHIBITED_BINARY_PAYLOAD_TYPES = (bytes, bytearray, memoryview)


@dataclass(frozen=True, slots=True)
class RuntimeEvent(Generic[T]):
    """One typed, lease-scoped low-frequency runtime notification."""

    name: str
    payload: T
    lease: WorkLease


class RuntimeSubscription(Protocol):
    """A disposable runtime-event subscription."""

    def close(self) -> None:
        """Stop receiving future event snapshots."""


class HotPathEventPayload:
    """Marker for payload classes that must never use ``RuntimeEventBus``."""


class _RuntimeEventSubscription:
    def __init__(
        self,
        bus: RuntimeEventBus,
        event_name: str,
        callback: Callable[[RuntimeEvent[object]], None],
    ) -> None:
        self._bus = bus
        self._event_name = event_name
        self._callback = callback
        self._closed = False

    def close(self) -> None:
        self._bus._close_subscription(self)


class RuntimeEventBus:
    """Thread-safe event fanout that never invokes callbacks under its lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscriptions: dict[str, list[_RuntimeEventSubscription]] = {}

    def subscribe(
        self,
        event_name: str,
        callback: Callable[[RuntimeEvent[object]], None],
    ) -> RuntimeSubscription:
        subscription = _RuntimeEventSubscription(self, event_name, callback)
        with self._lock:
            self._subscriptions.setdefault(event_name, []).append(subscription)
        return subscription

    def publish(self, event: RuntimeEvent[object]) -> None:
        """Deliver an event to the current subscriber snapshot in registration order."""

        _reject_hot_path_payload(event.payload)
        with self._lock:
            subscriptions = tuple(self._subscriptions.get(event.name, ()))
        for subscription in subscriptions:
            try:
                subscription._callback(event)
            except Exception as error:
                # Exception messages and tracebacks may contain private payload data.
                _LOGGER.error(
                    "Runtime event subscriber failed: event=%s subscriber=%s exception=%s",
                    event.name,
                    _subscriber_name(subscription._callback),
                    type.__getattribute__(type(error), "__name__"),
                )

    def subscriber_count(self, event_name: str) -> int:
        """Return the number of active subscriptions for an event name."""

        with self._lock:
            return len(self._subscriptions.get(event_name, ()))

    def _close_subscription(self, subscription: _RuntimeEventSubscription) -> None:
        with self._lock:
            if subscription._closed:
                return
            subscription._closed = True
            subscriptions = self._subscriptions.get(subscription._event_name)
            if subscriptions is None:
                return
            subscriptions.remove(subscription)
            if not subscriptions:
                del self._subscriptions[subscription._event_name]


def _subscriber_name(callback: Callable[[RuntimeEvent[object]], None]) -> str:
    if type(callback) is MethodType:
        callback = callback.__func__
    if type(callback) is FunctionType:
        return callback.__qualname__
    return type.__getattribute__(type(callback), "__qualname__")


def _reject_hot_path_payload(payload: object) -> None:
    _validate_event_payload(payload)


def _validate_event_payload(payload: object) -> None:
    pending = [payload]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if isinstance(current, _PROHIBITED_BINARY_PAYLOAD_TYPES):
            raise ValueError("Binary media payloads must not use RuntimeEventBus")
        if _exports_buffer(current):
            raise ValueError("Buffer payloads must not use RuntimeEventBus")
        if isinstance(current, HotPathEventPayload) or _has_prohibited_type_name(current):
            raise ValueError("Hot-path payloads must not use RuntimeEventBus")
        if not _is_supported_event_container(current):
            continue

        current_id = id(current)
        if current_id in visited:
            continue
        visited.add(current_id)

        if isinstance(current, Mapping):
            for key, value in current.items():
                pending.append(key)
                pending.append(value)
        if isinstance(current, (Sequence, Set)) and not isinstance(current, str):
            pending.extend(current)
        if is_dataclass(current) and not isinstance(current, type):
            pending.extend(getattr(current, field.name) for field in fields(current))


def _has_prohibited_type_name(payload: object) -> bool:
    return any(
        _normalized_type_name(payload_type.__name__) in _PROHIBITED_PAYLOAD_TYPE_NAMES
        for payload_type in type(payload).__mro__
    )


def _is_supported_event_container(payload: object) -> bool:
    return (
        isinstance(payload, Mapping)
        or (
            isinstance(payload, (Sequence, Set))
            and not isinstance(payload, (str, *_PROHIBITED_BINARY_PAYLOAD_TYPES))
        )
        or (is_dataclass(payload) and not isinstance(payload, type))
    )


def _exports_buffer(payload: object) -> bool:
    try:
        buffer_view = memoryview(payload)
    except (BufferError, TypeError, ValueError):
        return False
    try:
        return True
    finally:
        buffer_view.release()


def _normalized_type_name(name: str) -> str:
    return "".join(character for character in name if character.isalnum()).lower()


__all__ = [
    "HotPathEventPayload",
    "RuntimeEvent",
    "RuntimeEventBus",
    "RuntimeSubscription",
]
