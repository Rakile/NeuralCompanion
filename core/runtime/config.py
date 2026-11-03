"""Revisioned, immutable runtime configuration snapshots."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterator, Mapping, MutableMapping
from dataclasses import dataclass
import enum
from enum import Enum
import math
from pathlib import Path
import threading
from types import FunctionType, MappingProxyType, MethodType

from core.runtime.contracts import RuntimeFailure
from core.runtime.events import RuntimeSubscription


ConfigCallback = Callable[["RuntimeConfigChanged"], None]
_SUBSCRIBER_NAME_FALLBACK = "<subscriber>"
_EXCEPTION_NAME_FALLBACK = "<exception>"
_EXCEPTION_DETAIL_FALLBACK = "<unprintable>"
_FAILURE_MESSAGE_FALLBACK = "Runtime config subscriber failure"
_BASE_EXCEPTION_ARGS_DESCRIPTOR = BaseException.__dict__["args"]


class _FrozenList(tuple):
    """Immutable snapshot storage that retains list schema."""

    __slots__ = ()


class _FrozenSet(frozenset):
    """Immutable snapshot storage that retains set schema."""

    __slots__ = ()


def _safe_object_text(value: object, attribute: str, fallback: str) -> str:
    try:
        text = object.__getattribute__(value, attribute)
    except BaseException:
        return fallback
    return text if type(text) is str else fallback


def _safe_type_text(value_type: type, attribute: str, fallback: str) -> str:
    try:
        text = type.__getattribute__(value_type, attribute)
    except BaseException:
        return fallback
    return text if type(text) is str else fallback


def _subscriber_name(callback: ConfigCallback) -> str:
    if type(callback) is FunctionType:
        return _safe_object_text(callback, "__name__", _SUBSCRIBER_NAME_FALLBACK)
    if type(callback) is MethodType:
        try:
            function = object.__getattribute__(callback, "__func__")
        except BaseException:
            return _SUBSCRIBER_NAME_FALLBACK
        return _safe_object_text(function, "__name__", _SUBSCRIBER_NAME_FALLBACK)
    callback_type = callback if isinstance(callback, type) else type(callback)
    return _safe_type_text(
        callback_type,
        "__qualname__",
        _SUBSCRIBER_NAME_FALLBACK,
    )


def _exception_name(error: BaseException) -> str:
    return _safe_type_text(type(error), "__name__", _EXCEPTION_NAME_FALLBACK)


def _exception_detail(error: BaseException) -> str:
    try:
        arguments = _BASE_EXCEPTION_ARGS_DESCRIPTOR.__get__(error, BaseException)
    except BaseException:
        return _EXCEPTION_DETAIL_FALLBACK
    if type(arguments) is not tuple:
        return _EXCEPTION_DETAIL_FALLBACK
    if not arguments:
        return ""
    if len(arguments) == 1 and type(arguments[0]) is str:
        return arguments[0]
    return _EXCEPTION_DETAIL_FALLBACK


def _subscriber_failure_message(
    subscriber_name: str,
    event_revision: int,
    error: BaseException,
) -> str:
    try:
        message = (
            "Runtime config subscriber '"
            + subscriber_name
            + "' failed for revision "
            + str(event_revision)
            + ": "
            + _exception_name(error)
        )
        error_detail = _exception_detail(error)
        if error_detail:
            message = message + ": " + error_detail
        return message
    except BaseException:
        return _FAILURE_MESSAGE_FALLBACK


@dataclass(frozen=True, slots=True)
class RuntimeConfigSnapshot:
    """An immutable view of one accepted runtime configuration revision."""

    revision: int
    values: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class RuntimeConfigChanged:
    """A typed notification for an accepted runtime configuration revision."""

    snapshot: RuntimeConfigSnapshot
    changed_keys: tuple[str, ...]

    @property
    def revision(self) -> int:
        return self.snapshot.revision

    @property
    def values(self) -> Mapping[str, object]:
        return self.snapshot.values


@dataclass(frozen=True, slots=True)
class RuntimeConfigSubscriberFailure:
    """One immutable, ordered runtime-config subscriber failure."""

    sequence: int
    event_revision: int
    subscriber_sequence: int
    subscriber_name: str
    failure: RuntimeFailure


class _RuntimeConfigSubscription:
    def __init__(
        self,
        service: "RuntimeConfigService",
        callback: ConfigCallback,
        sequence: int,
        name: str,
    ) -> None:
        self._service = service
        self._callback = callback
        self._sequence = sequence
        self._name = name
        self._closed = False

    def close(self) -> None:
        self._service._close_subscription(self)


class RuntimeConfigService:
    """Own mutable runtime settings behind revisioned immutable snapshots."""

    def __init__(self, values: Mapping[str, object]) -> None:
        self._lock = threading.Lock()
        self._subscriptions: list[_RuntimeConfigSubscription] = []
        self._pending_events: deque[RuntimeConfigChanged] = deque()
        self._dispatching = False
        self._subscriber_failures: list[RuntimeConfigSubscriberFailure] = []
        self._next_subscription_sequence = 1
        self._next_failure_sequence = 1
        self._revision = 0
        self._values = _freeze_mapping(values)
        self._snapshot = RuntimeConfigSnapshot(self._revision, self._values)

    def snapshot(self) -> RuntimeConfigSnapshot:
        with self._lock:
            return self._snapshot

    def get(self, key: str, default: object = None) -> object:
        with self._lock:
            if key not in self._values:
                return _thaw(default)
            return _thaw(self._values[key])

    def to_dict(self) -> dict[str, object]:
        with self._lock:
            return _thaw_mapping(self._values)

    def subscriber_failures(self) -> tuple[RuntimeConfigSubscriberFailure, ...]:
        with self._lock:
            return tuple(self._subscriber_failures)

    def update(self, key: str, value: object) -> RuntimeConfigChanged:
        return self.update_many({key: value})

    def update_many(self, values: Mapping[str, object]) -> RuntimeConfigChanged:
        prepared = _freeze_mapping(values)
        with self._lock:
            changed_keys = tuple(
                key
                for key, value in prepared.items()
                if key not in self._values
                or not _frozen_values_equivalent(self._values[key], value)
            )
            if not changed_keys:
                return RuntimeConfigChanged(self._snapshot, ())
            merged = dict(self._values)
            merged.update(prepared)
            event, dispatch = self._commit_locked(merged, changed_keys)
        if dispatch:
            self._dispatch_events()
        return event

    def remove(self, key: str) -> RuntimeConfigChanged:
        with self._lock:
            if key not in self._values:
                raise KeyError(key)
            remaining = dict(self._values)
            del remaining[key]
            event, dispatch = self._commit_locked(remaining, (key,))
        if dispatch:
            self._dispatch_events()
        return event

    def clear(self) -> RuntimeConfigChanged | None:
        with self._lock:
            if not self._values:
                return None
            event, dispatch = self._commit_locked({}, tuple(self._values))
        if dispatch:
            self._dispatch_events()
        return event

    def subscribe(self, callback: ConfigCallback) -> RuntimeSubscription:
        with self._lock:
            subscription = _RuntimeConfigSubscription(
                self,
                callback,
                self._next_subscription_sequence,
                _subscriber_name(callback),
            )
            self._next_subscription_sequence += 1
            self._subscriptions.append(subscription)
        return subscription

    def _commit_locked(
        self,
        values: Mapping[str, object],
        changed_keys: tuple[str, ...],
    ) -> tuple[RuntimeConfigChanged, bool]:
        frozen_values = _freeze_mapping(values)
        self._revision += 1
        self._values = frozen_values
        self._snapshot = RuntimeConfigSnapshot(self._revision, self._values)
        event = RuntimeConfigChanged(self._snapshot, changed_keys)
        self._pending_events.append(event)
        dispatch = not self._dispatching
        self._dispatching = True
        return event, dispatch

    def _close_subscription(self, subscription: _RuntimeConfigSubscription) -> None:
        with self._lock:
            if subscription._closed:
                return
            subscription._closed = True
            self._subscriptions.remove(subscription)

    def _dispatch_events(self) -> None:
        pending_base_exception: BaseException | None = None
        while True:
            with self._lock:
                if not self._pending_events:
                    self._dispatching = False
                    break
                event = self._pending_events.popleft()
                subscriptions = tuple(
                    subscription
                    for subscription in self._subscriptions
                    if not subscription._closed
                )
            for subscription in subscriptions:
                try:
                    subscription._callback(event)
                except BaseException as error:
                    self._record_subscriber_failure(subscription, event, error)
                    if not isinstance(error, Exception) and pending_base_exception is None:
                        pending_base_exception = error
                    continue
        if pending_base_exception is not None:
            raise pending_base_exception

    def _record_subscriber_failure(
        self,
        subscription: _RuntimeConfigSubscription,
        event: RuntimeConfigChanged,
        error: BaseException,
    ) -> RuntimeConfigSubscriberFailure:
        message = _subscriber_failure_message(
            subscription._name,
            event.revision,
            error,
        )
        with self._lock:
            snapshot = RuntimeConfigSubscriberFailure(
                sequence=self._next_failure_sequence,
                event_revision=event.revision,
                subscriber_sequence=subscription._sequence,
                subscriber_name=subscription._name,
                failure=RuntimeFailure(
                    category="runtime_config_subscriber",
                    message=message,
                    cause=error,
                ),
            )
            self._next_failure_sequence += 1
            self._subscriber_failures.append(snapshot)
        return snapshot


class RuntimeConfigMappingView(MutableMapping[str, object]):
    """A service-backed compatibility facade for the legacy config mapping."""

    def __init__(self, service: RuntimeConfigService) -> None:
        self._service = service

    def __getitem__(self, key: str) -> object:
        snapshot = self._service.snapshot()
        try:
            return _thaw(snapshot.values[key])
        except KeyError:
            raise KeyError(key) from None

    def __setitem__(self, key: str, value: object) -> None:
        self._service.update(key, value)

    def __delitem__(self, key: str) -> None:
        self._service.remove(key)

    def __iter__(self) -> Iterator[str]:
        return iter(self._service.snapshot().values)

    def __len__(self) -> int:
        return len(self._service.snapshot().values)

    def clear(self) -> None:
        self._service.clear()

    def update(self, other=(), /, **kwargs) -> None:
        values: dict[object, object] = {}
        if hasattr(other, "keys"):
            for key in other.keys():
                values[key] = other[key]
        else:
            for key, value in other:
                values[key] = value
        values.update(kwargs)
        self._service.update_many(values)


def _freeze_mapping(values: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(values, Mapping):
        raise TypeError("Runtime configuration values must be a mapping")
    return MappingProxyType({str(key): _freeze(value) for key, value in values.items()})


def _freeze(value: object) -> object:
    if isinstance(value, Enum):
        return _freeze_enum(value)
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if type(value) is _FrozenList:
        return _FrozenList(_freeze(item) for item in value)
    if isinstance(value, list):
        return _FrozenList(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if type(value) is _FrozenSet:
        return _FrozenSet(_freeze(item) for item in value)
    if isinstance(value, set):
        return _FrozenSet(_freeze(item) for item in value)
    if isinstance(value, frozenset):
        return frozenset(_freeze(item) for item in value)
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, Path):
        return Path(str(value))
    if isinstance(value, str):
        return str(value)
    if isinstance(value, bytes):
        return bytes(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if value is None:
        return None
    raise TypeError(
        "Runtime configuration only accepts scalar, path, enum, and collection values; "
        f"got {type(value).__name__}"
    )


def _frozen_values_equivalent(left: object, right: object) -> bool:
    if left is right:
        return True
    if type(left) is not type(right):
        return False
    if type(left) is float:
        return (math.isnan(left) and math.isnan(right)) or left == right
    if isinstance(left, Mapping):
        return (
            len(left) == len(right)
            and left.keys() == right.keys()
            and all(
                _frozen_values_equivalent(left[key], right[key])
                for key in left
            )
        )
    if type(left) in {_FrozenList, tuple}:
        return len(left) == len(right) and all(
            _frozen_values_equivalent(left_item, right_item)
            for left_item, right_item in zip(left, right)
        )
    if type(left) in {_FrozenSet, frozenset}:
        return _frozen_set_values_equivalent(left, right)
    if isinstance(left, Enum):
        return False
    return left == right


_ENUM_MEMBER_INTERNAL_ATTRIBUTE_NAMES = frozenset(
    {"_value_", "_name_", "__objclass__", "_sort_order_"}
)
_ENUM_CLASS_INTERNAL_ATTRIBUTE_NAMES = frozenset(
    {
        "_generate_next_value_",
        "_member_map_",
        "_member_names_",
        "_member_type_",
        "_new_member_",
        "_unhashable_values_",
        "_unhashable_values_map_",
        "_use_args_",
        "_value2member_map_",
        "_value_repr_",
        "__dict__",
        "__doc__",
        "__firstlineno__",
        "__format__",
        "__module__",
        "__new__",
        "__repr__",
        "__static_attributes__",
        "__str__",
        "__weakref__",
    }
)
_ENUM_TYPE = getattr(enum, "EnumType", enum.EnumMeta)
_STANDARD_ENUM_BASES = frozenset(
    [Enum, object, str, int]
    + [
        getattr(enum, name)
        for name in ("IntEnum", "ReprEnum", "StrEnum")
        if hasattr(enum, name)
    ]
)
_STR_ENUM = getattr(enum, "StrEnum", None)
_STR_ENUM_NAMESPACE = vars(_STR_ENUM) if _STR_ENUM is not None else {}
_ALLOWED_ENUM_DESCRIPTOR_IDENTITIES = {
    "_generate_next_value_": tuple(
        value
        for value in (
            Enum._generate_next_value_,
            _STR_ENUM_NAMESPACE.get("_generate_next_value_"),
        )
        if value is not None
    ),
    "_new_member_": tuple(
        value
        for value in (_STR_ENUM_NAMESPACE.get("_new_member_"),)
        if value is not None
    ),
    "_value_repr_": (str.__repr__, int.__repr__),
    "__new__": (Enum.__new__,),
    "__repr__": (Enum.__repr__,),
    "__str__": (Enum.__str__, str.__str__),
    "__format__": (Enum.__format__, str.__format__, int.__format__),
}
_MISSING = object()


def _freeze_enum(member: Enum) -> Enum:
    enum_type = type(member)
    type_name = type.__getattribute__(enum_type, "__name__")

    if type(enum_type) is not _ENUM_TYPE:
        raise TypeError(
            f"Runtime configuration enum {type_name} is not immutable: "
            "custom enum metaclass"
        )
    namespace = type.__getattribute__(enum_type, "__dict__")
    custom_bases = tuple(
        base.__qualname__
        for base in type.__getattribute__(enum_type, "__mro__")[1:]
        if base not in _STANDARD_ENUM_BASES
    )
    if custom_bases:
        raise TypeError(
            f"Runtime configuration enum {type_name} is not immutable: "
            f"custom enum bases: {', '.join(custom_bases)}"
        )
    custom_slots = _enum_custom_slot_names(namespace)
    if custom_slots:
        raise TypeError(
            f"Runtime configuration enum {type_name} is not immutable: "
            f"custom slots: {', '.join(custom_slots)}"
        )
    custom_descriptors = _enum_custom_descriptor_names(enum_type, namespace)
    if custom_descriptors:
        raise TypeError(
            f"Runtime configuration enum {type_name} is not immutable: "
            f"custom descriptors: {', '.join(custom_descriptors)}"
        )
    custom_class_attributes = _enum_custom_class_attribute_names(namespace)
    if custom_class_attributes:
        raise TypeError(
            f"Runtime configuration enum {type_name} is not immutable: "
            f"custom class attributes: {', '.join(custom_class_attributes)}"
        )

    member_state = object.__getattribute__(member, "__dict__")
    if type(member_state) is not dict:
        raise TypeError(
            f"Runtime configuration enum {type_name} is not immutable: "
            "invalid member state"
        )
    custom_attributes = tuple(
        sorted(set(member_state).difference(_ENUM_MEMBER_INTERNAL_ATTRIBUTE_NAMES))
    )
    if custom_attributes:
        raw_name = member_state.get("_name_")
        label = f"{type_name}.{raw_name}" if type(raw_name) is str else type_name
        raise TypeError(
            f"Runtime configuration enum {label} is not immutable: "
            f"custom member attributes: {', '.join(custom_attributes)}"
        )

    raw_name = member_state.get("_name_", _MISSING)
    member_map = namespace.get("_member_map_")
    if (
        type(raw_name) is not str
        or type(member_map) is not dict
        or member_map.get(raw_name) is not member
        or namespace.get(raw_name) is not member
    ):
        raise TypeError(
            f"Runtime configuration enum {type_name} is not immutable: "
            "invalid _name_ invariant"
        )
    label = f"{type_name}.{raw_name}"

    if member_state.get("__objclass__", _MISSING) is not enum_type:
        raise TypeError(
            f"Runtime configuration enum {label} is not immutable: "
            "invalid __objclass__ invariant"
        )
    if type(member_state.get("_sort_order_", _MISSING)) is not int:
        raise TypeError(
            f"Runtime configuration enum {label} is not immutable: "
            "invalid _sort_order_ invariant"
        )

    raw_value = member_state.get("_value_", _MISSING)
    unsupported_payload = _unsupported_enum_payload(raw_value)
    if unsupported_payload is not None:
        path, payload_type_name = unsupported_payload
        raise TypeError(
            f"Runtime configuration enum {label} is not immutable: "
            f"value payload at {path} has unsupported type {payload_type_name}"
        )
    value_map = namespace.get("_value2member_map_")
    try:
        mapped_member = value_map.get(raw_value, _MISSING)
    except (AttributeError, TypeError):
        mapped_member = _MISSING
    if mapped_member is not member:
        raise TypeError(
            f"Runtime configuration enum {label} is not immutable: "
            "invalid _value_ invariant"
        )
    return member


def _enum_custom_slot_names(namespace: Mapping[str, object]) -> tuple[str, ...]:
    slots = namespace.get("__slots__", ())
    if isinstance(slots, str):
        slots = (slots,)
    return tuple(sorted(str(name) for name in slots))


def _enum_custom_descriptor_names(
    enum_type: type[Enum],
    namespace: Mapping[str, object],
) -> tuple[str, ...]:
    names = []
    for name, value in namespace.items():
        if not _is_descriptor(value):
            continue
        allowed = _ALLOWED_ENUM_DESCRIPTOR_IDENTITIES.get(name, ())
        if any(value is expected for expected in allowed):
            continue
        if name in {"__dict__", "__weakref__"} and (
            getattr(value, "__objclass__", None) is enum_type
        ):
            continue
        names.append(name)
    return tuple(sorted(names))


def _enum_custom_class_attribute_names(
    namespace: Mapping[str, object],
) -> tuple[str, ...]:
    member_map = namespace.get("_member_map_", {})
    member_names = set(member_map) if type(member_map) is dict else set()
    return tuple(
        sorted(
            set(namespace)
            .difference(_ENUM_CLASS_INTERNAL_ATTRIBUTE_NAMES)
            .difference(member_names)
        )
    )


def _is_descriptor(value: object) -> bool:
    return any(
        method_name in descriptor_type.__dict__
        for descriptor_type in type(value).__mro__
        for method_name in ("__get__", "__set__", "__delete__")
    )


def _unsupported_enum_payload(
    value: object,
    path: str = "value",
) -> tuple[str, str] | None:
    if type(value) in {str, bytes, int, float, bool, type(None)}:
        return None
    if isinstance(value, Path):
        if type(value) is type(Path(".")):
            return None
        return path, type(value).__name__
    if type(value) is tuple:
        for index, item in enumerate(value):
            unsupported = _unsupported_enum_payload(item, f"{path}[{index}]")
            if unsupported is not None:
                return unsupported
        return None
    if type(value) is frozenset:
        for item in value:
            unsupported = _unsupported_enum_payload(item, f"{path} item")
            if unsupported is not None:
                return unsupported
        return None
    return path, type(value).__name__


def _frozen_set_values_equivalent(
    left: frozenset[object],
    right: frozenset[object],
) -> bool:
    if len(left) != len(right):
        return False
    unmatched = list(right)
    for left_item in left:
        for index, right_item in enumerate(unmatched):
            if _frozen_values_equivalent(left_item, right_item):
                del unmatched[index]
                break
        else:
            return False
    return True


def _thaw_mapping(values: Mapping[str, object]) -> dict[str, object]:
    return {key: _thaw(value) for key, value in values.items()}


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return _thaw_mapping(value)
    if type(value) is _FrozenList:
        return [_thaw(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_thaw(item) for item in value)
    if type(value) is _FrozenSet:
        return {_thaw(item) for item in value}
    if isinstance(value, frozenset):
        return frozenset(_thaw(item) for item in value)
    return value


__all__ = [
    "RuntimeConfigChanged",
    "RuntimeConfigMappingView",
    "RuntimeConfigService",
    "RuntimeConfigSnapshot",
    "RuntimeConfigSubscriberFailure",
]
