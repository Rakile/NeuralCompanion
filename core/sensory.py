from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable


SensoryCaptureHandler = Callable[[dict[str, Any] | None], dict[str, Any] | None]


@dataclass
class SensoryProvider:
    id: str
    label: str
    instruction: str = ""
    description: str = ""
    order: int = 1000
    capture_handler: SensoryCaptureHandler | None = None
    metadata: dict[str, Any] | None = None

    def to_summary(self) -> dict[str, Any]:
        return {
            "id": str(self.id or "").strip(),
            "label": str(self.label or "").strip(),
            "instruction": str(self.instruction or "").strip(),
            "description": str(self.description or "").strip(),
            "order": int(self.order),
            "metadata": dict(self.metadata or {}),
        }


@dataclass
class SensoryPromptContributor:
    id: str
    source_id: str
    label: str
    prompt: str = ""
    order: int = 1000
    metadata: dict[str, Any] | None = None

    def to_summary(self) -> dict[str, Any]:
        return {
            "id": str(self.id or "").strip(),
            "source_id": str(self.source_id or "").strip(),
            "label": str(self.label or "").strip(),
            "prompt": str(self.prompt or "").strip(),
            "order": int(self.order),
            "metadata": dict(self.metadata or {}),
        }


class SensoryRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._providers: dict[str, SensoryProvider] = {}
        self._prompt_contributors: dict[str, SensoryPromptContributor] = {}

    def register_provider(
        self,
        *,
        provider_id: str,
        label: str,
        instruction: str = "",
        description: str = "",
        order: int = 1000,
        capture_handler: SensoryCaptureHandler | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SensoryProvider:
        provider = SensoryProvider(
            id=str(provider_id or "").strip(),
            label=str(label or "").strip(),
            instruction=str(instruction or "").strip(),
            description=str(description or "").strip(),
            order=int(order),
            capture_handler=capture_handler,
            metadata=dict(metadata or {}),
        )
        if not provider.id:
            raise ValueError("Sensory provider id is required.")
        if not provider.label:
            raise ValueError(f"Sensory provider '{provider.id}' is missing a label.")
        with self._lock:
            self._providers[provider.id] = provider
        return provider

    def unregister_provider(self, provider_id: str) -> bool:
        provider_key = str(provider_id or "").strip()
        if not provider_key:
            return False
        with self._lock:
            return self._providers.pop(provider_key, None) is not None

    def get_provider(self, provider_id: str) -> SensoryProvider | None:
        provider_key = str(provider_id or "").strip()
        if not provider_key:
            return None
        with self._lock:
            return self._providers.get(provider_key)

    def list_providers(self) -> list[SensoryProvider]:
        with self._lock:
            providers = list(self._providers.values())
        return sorted(providers, key=lambda item: (int(item.order), str(item.label or "").lower(), str(item.id or "").lower()))

    def capture_snapshot(self, provider_id: str, context: dict[str, Any] | None = None) -> dict[str, Any] | None:
        provider = self.get_provider(provider_id)
        if provider is None or provider.capture_handler is None:
            return None
        payload = provider.capture_handler(dict(context or {}))
        if not isinstance(payload, dict):
            return None
        snapshot = dict(payload)
        snapshot.setdefault("source", provider.id)
        snapshot.setdefault("label", provider.label)
        snapshot.setdefault("provider_id", provider.id)
        return snapshot


    def register_prompt_contributor(
        self,
        *,
        contributor_id: str,
        source_id: str,
        label: str,
        prompt: str = "",
        order: int = 1000,
        metadata: dict[str, Any] | None = None,
    ) -> SensoryPromptContributor:
        contributor = SensoryPromptContributor(
            id=str(contributor_id or "").strip(),
            source_id=str(source_id or "").strip(),
            label=str(label or "").strip(),
            prompt=str(prompt or "").strip(),
            order=int(order),
            metadata=dict(metadata or {}),
        )
        if not contributor.id:
            raise ValueError("Sensory prompt contributor id is required.")
        if not contributor.source_id:
            raise ValueError(f"Sensory prompt contributor '{contributor.id}' is missing a source id.")
        if not contributor.label:
            raise ValueError(f"Sensory prompt contributor '{contributor.id}' is missing a label.")
        with self._lock:
            self._prompt_contributors[contributor.id] = contributor
        return contributor

    def unregister_prompt_contributor(self, contributor_id: str) -> bool:
        contributor_key = str(contributor_id or "").strip()
        if not contributor_key:
            return False
        with self._lock:
            return self._prompt_contributors.pop(contributor_key, None) is not None

    def list_prompt_contributors(self, source_id: str | None = None) -> list[SensoryPromptContributor]:
        source_key = str(source_id or "").strip()
        with self._lock:
            contributors = list(self._prompt_contributors.values())
        if source_key:
            contributors = [item for item in contributors if str(item.source_id or "").strip() == source_key]
        return sorted(contributors, key=lambda item: (int(item.order), str(item.label or "").lower(), str(item.id or "").lower()))


_REGISTRY = SensoryRegistry()


def register_provider(**kwargs) -> SensoryProvider:
    return _REGISTRY.register_provider(**kwargs)


def unregister_provider(provider_id: str) -> bool:
    return _REGISTRY.unregister_provider(provider_id)


def get_provider(provider_id: str) -> SensoryProvider | None:
    return _REGISTRY.get_provider(provider_id)


def list_providers() -> list[SensoryProvider]:
    return _REGISTRY.list_providers()


def capture_snapshot(provider_id: str, context: dict[str, Any] | None = None) -> dict[str, Any] | None:
    return _REGISTRY.capture_snapshot(provider_id, context)


def register_prompt_contributor(**kwargs) -> SensoryPromptContributor:
    return _REGISTRY.register_prompt_contributor(**kwargs)


def unregister_prompt_contributor(contributor_id: str) -> bool:
    return _REGISTRY.unregister_prompt_contributor(contributor_id)


def list_prompt_contributors(source_id: str | None = None) -> list[SensoryPromptContributor]:
    return _REGISTRY.list_prompt_contributors(source_id)
