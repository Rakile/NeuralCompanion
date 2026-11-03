"""Frozen provider adapter used by production conversation memory."""

from __future__ import annotations

from collections.abc import Mapping

from core.runtime.memory import MemoryWorkContext
from core.runtime.production_provider import ProductionProviderOwner
from core.runtime.providers import infer_model_supports_images


class ProductionMemoryProviderAdapter:
    """Execute memory-only requests against one immutable provider capture."""

    __slots__ = ("_providers",)

    def __init__(self, providers: ProductionProviderOwner) -> None:
        if not isinstance(providers, ProductionProviderOwner):
            raise TypeError(
                "Production memory provider requires ProductionProviderOwner."
            )
        self._providers = providers

    def capture(self, context: MemoryWorkContext) -> object:
        if not isinstance(context, MemoryWorkContext):
            raise TypeError("Memory provider capture requires MemoryWorkContext.")
        values = context.config.values
        provider = str(values.get("chat_provider", "") or "").strip()
        model = str(values.get("model_name", "") or "").strip()
        self._providers.ensure_model_ready(provider, model)
        return self._providers.runtime.capture_frozen_context(
            provider=provider or None,
            model=model,
            runtime_config=values,
        )

    def complete(
        self,
        captured: object,
        params: Mapping[str, object],
        additional_params: Mapping[str, object] | None = None,
    ) -> object:
        request = self._providers.runtime.prepare_frozen_request(
            captured,
            dict(params),
            dict(additional_params or {}),
        )
        return self._providers.runtime.complete_frozen(request)

    def model_is_placeholder(self, model_name: object) -> bool:
        return self._providers.is_model_catalog_placeholder(model_name)

    @staticmethod
    def model_supports_images(config: Mapping[str, object]) -> bool:
        explicit = config.get("model_supports_images")
        if explicit is not None:
            return bool(explicit)
        return infer_model_supports_images(config.get("model_name", ""))


__all__ = ["ProductionMemoryProviderAdapter"]
