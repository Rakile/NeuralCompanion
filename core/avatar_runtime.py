"""Avatar runtime contracts, provider registry, and shared math helpers."""

from __future__ import annotations

import abc
import inspect
import math
import threading
from dataclasses import dataclass, field
from typing import Any, Callable


AvatarFactory = Callable[..., "AvatarAdapter | None"]


@dataclass
class AvatarRuntimeContext:
    """Host/runtime hooks passed to avatar provider factories at creation time."""

    runtime_config: dict[str, Any]
    dependencies: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.dependencies.get(key, default)


@dataclass
class AvatarProvider:
    """Registered avatar engine provider exposed by core or addons."""

    id: str
    label: str
    factory: AvatarFactory
    description: str = ""
    order: int = 1000
    addon_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "order": self.order,
            "addon_id": self.addon_id,
            "metadata": dict(self.metadata or {}),
        }


class AvatarAdapter(abc.ABC):
    """Shared interface implemented by all avatar engines."""

    @abc.abstractmethod
    def start(self):
        pass

    @abc.abstractmethod
    def stop(self):
        pass

    @abc.abstractmethod
    def set_emotion(self, emotion_name: str):
        pass

    @abc.abstractmethod
    def set_speaking_state(self, is_speaking: bool):
        pass

    @abc.abstractmethod
    def process_audio_chunk(self, audio_path: str, text: str, output_filename: str, dry_run_reply_id=None):
        pass


_provider_lock = threading.RLock()
_providers: dict[str, AvatarProvider] = {}


def normalize_provider_id(provider_id: str | None, fallback: str = "vseeface") -> str:
    value = str(provider_id or "").strip().lower()
    return value or str(fallback or "vseeface").strip().lower()


def adapter_provider_id(adapter: Any, fallback: str = "") -> str:
    """Return the normalized provider id advertised by an adapter instance."""

    return normalize_provider_id(getattr(adapter, "avatar_provider_id", ""), fallback=fallback)


def adapter_matches_provider(adapter: Any, provider_id: str) -> bool:
    """Check an adapter identity without importing provider-specific classes."""

    expected = normalize_provider_id(provider_id, fallback="")
    return bool(expected and adapter_provider_id(adapter, fallback="") == expected)


def register_provider(
    *,
    provider_id: str,
    label: str,
    factory: AvatarFactory,
    description: str = "",
    order: int = 1000,
    addon_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> AvatarProvider:
    """Register an avatar provider factory.

    Addons should register factories here; engine startup then asks the registry
    to create the selected adapter without knowing provider-specific details.
    """

    normalized = normalize_provider_id(provider_id, fallback="")
    if not normalized:
        raise ValueError("Avatar provider id is required.")
    if not callable(factory):
        raise TypeError("Avatar provider factory must be callable.")
    provider = AvatarProvider(
        id=normalized,
        label=str(label or normalized).strip() or normalized,
        factory=factory,
        description=str(description or ""),
        order=int(order),
        addon_id=str(addon_id or "").strip(),
        metadata=dict(metadata or {}),
    )
    with _provider_lock:
        _providers[normalized] = provider
    return provider


def unregister_provider(provider_id: str) -> bool:
    normalized = normalize_provider_id(provider_id, fallback="")
    if not normalized:
        return False
    with _provider_lock:
        return _providers.pop(normalized, None) is not None


def get_provider(provider_id: str | None) -> AvatarProvider | None:
    normalized = normalize_provider_id(provider_id, fallback="")
    if not normalized:
        return None
    with _provider_lock:
        return _providers.get(normalized)


def list_providers() -> list[AvatarProvider]:
    with _provider_lock:
        providers = list(_providers.values())
    return sorted(providers, key=lambda provider: (provider.order, provider.label.lower(), provider.id))


def _factory_accepts_runtime_context(factory: AvatarFactory) -> bool:
    try:
        signature = inspect.signature(factory)
    except (TypeError, ValueError):
        return False
    for parameter in signature.parameters.values():
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            return True
        if parameter.name == "runtime_context":
            return True
    return False


def create_avatar_adapter(provider_id: str | None, runtime_context: AvatarRuntimeContext | None = None) -> AvatarAdapter | None:
    provider = get_provider(provider_id)
    if provider is None:
        return None
    if runtime_context is not None and _factory_accepts_runtime_context(provider.factory):
        adapter = provider.factory(runtime_context=runtime_context)
    else:
        adapter = provider.factory()
    if adapter is not None and not isinstance(adapter, AvatarAdapter):
        raise TypeError(f"Avatar provider '{provider.id}' returned {type(adapter).__name__}, expected AvatarAdapter.")
    return adapter


def euler_to_quaternion(roll, pitch, yaw):
    rx = math.radians(roll) / 2
    ry = math.radians(pitch) / 2
    rz = math.radians(yaw) / 2

    cx = math.cos(rx)
    sx = math.sin(rx)
    cy = math.cos(ry)
    sy = math.sin(ry)
    cz = math.cos(rz)
    sz = math.sin(rz)

    return [
        sx * cy * cz - cx * sy * sz,
        cx * sy * cz + sx * cy * sz,
        cx * cy * sz - sx * sy * cz,
        cx * cy * cz + sx * sy * sz,
    ]
