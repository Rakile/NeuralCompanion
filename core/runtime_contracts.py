"""Shared runtime contracts for NeuralCompanion core subsystems.

These contracts are intentionally small and behavior-neutral. They give the
runtime a modular object model while existing procedural entry points migrate
behind the scenes one subsystem at a time.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol, runtime_checkable


@dataclass(frozen=True)
class RuntimeCapability:
    """A named capability exposed by a runtime service or provider."""

    id: str
    label: str = ""
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeField:
    """Declarative user-configurable field metadata."""

    id: str
    label: str
    kind: str = "text"
    default: Any = None
    description: str = ""
    required: bool = False
    secret: bool = False
    choices: tuple[Any, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeStatus:
    """Small status payload returned by services/providers."""

    ok: bool
    label: str = ""
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderDescriptor:
    """Stable metadata for a pluggable provider/backend."""

    id: str
    label: str
    description: str = ""
    capabilities: tuple[RuntimeCapability, ...] = ()
    config_fields: tuple[RuntimeField, ...] = ()
    generation_fields: tuple[RuntimeField, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class RuntimeService(ABC):
    """Base lifecycle shape for reusable runtime services."""

    @property
    @abstractmethod
    def service_id(self) -> str:
        raise NotImplementedError

    def start(self) -> RuntimeStatus:
        return RuntimeStatus(ok=True, label=self.service_id)

    def stop(self) -> RuntimeStatus:
        return RuntimeStatus(ok=True, label=self.service_id)

    def reset(self) -> RuntimeStatus:
        return RuntimeStatus(ok=True, label=self.service_id)

    def export_session_state(self) -> dict[str, Any]:
        return {}

    def import_session_state(self, state: dict[str, Any] | None) -> None:
        return None


class ProviderAdapter(ABC):
    """Base shape for chat, TTS, STT, visual, and avatar providers."""

    @property
    @abstractmethod
    def descriptor(self) -> ProviderDescriptor:
        raise NotImplementedError

    def check_connection(self) -> RuntimeStatus:
        return RuntimeStatus(ok=True, label=self.descriptor.label)

    def close(self) -> None:
        return None


class ChatProviderAdapter(ProviderAdapter):
    @abstractmethod
    def list_models(self, *, quiet: bool = False) -> list[Any]:
        raise NotImplementedError

    @abstractmethod
    def complete(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None) -> Any:
        raise NotImplementedError

    @abstractmethod
    def stream(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None) -> Iterable[str]:
        raise NotImplementedError


class TTSBackendAdapter(ProviderAdapter):
    @abstractmethod
    def generate(self, text: str, **kwargs: Any) -> Any:
        raise NotImplementedError


class STTBackendAdapter(ProviderAdapter):
    @abstractmethod
    def transcribe(self, audio: Any, **kwargs: Any) -> str:
        raise NotImplementedError


class VisualImageProviderAdapter(ProviderAdapter):
    @abstractmethod
    def generate_image(self, prompt: str, **kwargs: Any) -> Any:
        raise NotImplementedError

    def edit_image(self, prompt: str, image: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("This visual provider does not support image editing.")

    def edit_with_references(self, prompt: str, images: list[Any], **kwargs: Any) -> Any:
        raise NotImplementedError("This visual provider does not support multi-reference image editing.")


class AvatarEngineAdapter(ProviderAdapter):
    @abstractmethod
    def start(self) -> RuntimeStatus:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> RuntimeStatus:
        raise NotImplementedError

    @abstractmethod
    def set_emotion(self, emotion_name: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_speaking_state(self, is_speaking: bool) -> None:
        raise NotImplementedError

    @abstractmethod
    def process_audio_chunk(self, audio_path: str, text: str, output_filename: str, **kwargs: Any) -> Any:
        raise NotImplementedError


@runtime_checkable
class SessionSerializable(Protocol):
    def export_session_state(self) -> dict[str, Any]:
        ...

    def import_session_state(self, state: dict[str, Any] | None) -> None:
        ...


@runtime_checkable
class PresetSerializable(Protocol):
    def export_preset_state(self) -> dict[str, Any]:
        ...

    def import_preset_state(self, state: dict[str, Any] | None) -> None:
        ...
