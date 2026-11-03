"""Concrete production ownership for chat providers and LM Studio models."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from core import chat_providers, lmstudio_runtime
from core.runtime.config import (
    RuntimeConfigChanged,
    RuntimeConfigService,
)
from core.runtime.identifiers import WorkLease
from core.runtime.lifecycle import WorkerSupervisor
from core.runtime.providers import (
    ProviderSelection,
    ProviderService,
)
from core.runtime_chat import ChatProviderRuntime
from core.runtime_contracts import RuntimeStatus


DEFAULT_LMSTUDIO_BASE_URL = "http://127.0.0.1:1234/v1"
_MODEL_CATALOG_PLACEHOLDERS = frozenset(
    {"scanning...", "no models", "no vision models"}
)


class ProductionProviderOwner:
    """Own the finite production provider/model surface outside ``engine.py``."""

    def __init__(
        self,
        config: RuntimeConfigService,
        *,
        workers: WorkerSupervisor | None = None,
        worker_lease: Callable[[], WorkLease] | None = None,
        lmstudio_base_url: str = DEFAULT_LMSTUDIO_BASE_URL,
        logger: Callable[[str], object] = print,
    ) -> None:
        if not isinstance(config, RuntimeConfigService):
            raise TypeError(
                "Production provider ownership requires RuntimeConfigService."
            )
        self._config = config
        self._logger = logger
        self._lmstudio_base_url = (
            str(lmstudio_base_url or "").strip() or DEFAULT_LMSTUDIO_BASE_URL
        )
        self._runtime = ChatProviderRuntime(config.snapshot)
        self._service = ProviderService(
            self._runtime,
            workers=workers,
            worker_lease=worker_lease,
            model_unload=self._unload_lmstudio_models,
            model_load=self._load_lmstudio_model,
            preserved_model_load=self._load_pinned_lmstudio_model,
            preserved_chat_model_load=self._load_lmstudio_model,
            model_inspect=self._list_loaded_lmstudio_models,
            resource_model_inspect=lambda endpoint: lmstudio_runtime.inspect_loaded_model_instances(base_url=endpoint),
            model_unload_one=self._unload_one_lmstudio_model,
            resource_model_unload_one=lambda identifier, endpoint: lmstudio_runtime.unload_model(
                identifier, base_url=endpoint, logger=self._logger, allow_cli_fallback=False),
            auxiliary_model_unload=self._unload_auxiliary_lmstudio_models,
            auxiliary_model_load=self._load_auxiliary_lmstudio_model,
            is_model_placeholder=self.is_model_catalog_placeholder,
            main_chat_context_length=self._lmstudio_context_length,
        )
        self._apply_provider_settings(config.snapshot().values)
        self._config_subscription = config.subscribe(self._on_config_changed)

    @property
    def service(self) -> ProviderService:
        """Return the provider service shared with the rest of the runtime graph."""

        return self._service

    @property
    def runtime(self) -> ChatProviderRuntime:
        return self._runtime

    def close(self) -> None:
        self._config_subscription.close()

    def current_provider(self, provider: str | None = None) -> str:
        return self._runtime.current_provider(provider)

    def provider_label(self, provider: str | None = None) -> str:
        return self._runtime.provider_label(provider)

    def provider_api_key(self, provider: str | None = None) -> str:
        return self._runtime.provider_api_key(provider)

    def provider_base_url(self, provider: str | None = None) -> str:
        return self._runtime.provider_base_url(provider)

    def provider_model_error(self, provider: str | None = None) -> str:
        return self._runtime.provider_model_error(provider)

    def create_client(self, provider: str | None = None) -> Any:
        return self._runtime.create_client(provider)

    def generation_settings(
        self,
        provider: str | None = None,
        *,
        selection: ProviderSelection | None = None,
    ) -> dict[str, Any]:
        """Return settings from live config or an explicitly frozen selection."""

        if selection is None:
            return self._runtime.generation_settings(provider)
        if not isinstance(selection, ProviderSelection):
            raise TypeError("Frozen generation settings require ProviderSelection.")
        provider_id = self.current_provider(provider or selection.provider_id)
        settings_map = selection.config.values.get(
            "chat_provider_generation_settings", {}
        )
        if not isinstance(settings_map, Mapping):
            return {}
        settings = settings_map.get(provider_id, {})
        return dict(settings) if isinstance(settings, Mapping) else {}

    def capture_selection(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> ProviderSelection:
        return self._service.capture_selection(
            self._config.snapshot(),
            provider_id=provider,
            model_id=model,
        )

    def apply_generation_fields(
        self,
        selection: ProviderSelection,
        params: dict[str, Any],
        additional_params: dict[str, Any],
    ) -> None:
        """Normalize generation fields from one accepted immutable selection."""

        self._service.apply_generation_fields(selection, params, additional_params)

    def apply_current_generation_fields(
        self,
        params: dict[str, Any],
        additional_params: dict[str, Any],
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> ProviderSelection:
        selection = self.capture_selection(provider=provider, model=model)
        self.apply_generation_fields(selection, params, additional_params)
        return selection

    def list_models(
        self,
        provider: str | None = None,
        *,
        quiet: bool = False,
    ) -> tuple[object, ...]:
        provider_id = self.current_provider(provider)
        return self._service.list_models(provider_id, quiet=quiet)

    @staticmethod
    def is_model_catalog_placeholder(model_name: object) -> bool:
        value = str(model_name or "").strip()
        lowered = value.lower()
        return (
            not value
            or lowered in _MODEL_CATALOG_PLACEHOLDERS
            or lowered.startswith("error: check ")
        )

    def prepare_lmstudio_chat_model(
        self,
        provider: str | None = None,
        model: str | None = None,
        *,
        reason: str = "LM Studio chat model",
        force_unload: bool = False,
    ) -> bool:
        selection = self.capture_selection(provider=provider, model=model)
        return self._service.prepare_model(
            selection,
            reason=reason,
            force_unload=force_unload,
        )

    def ensure_model_ready(self, provider: str, model: str) -> bool:
        provider_id = self.current_provider(provider)
        model_id = str(model or "").strip()
        if (
            provider_id != "lmstudio"
            or not model_id
            or self.is_model_catalog_placeholder(model_id)
        ):
            return True
        return self.prepare_lmstudio_chat_model(
            provider_id,
            model_id,
            reason="LM Studio model switch",
        )

    def complete(
        self,
        params: dict[str, Any],
        additional_params: dict[str, Any] | None = None,
        *,
        stream: bool = False,
    ) -> Any:
        model = str(
            params.get("model") or self._config.get("model_name", "") or ""
        ).strip()
        provider = self.current_provider()
        if model:
            self.ensure_model_ready(provider, model)
        if stream:
            return self._service.stream_legacy(params, additional_params)
        return self._service.complete_legacy(params, additional_params)

    def connection_status(self, provider: str | None = None) -> RuntimeStatus:
        return self._runtime.check_connection(self.current_provider(provider))

    def check_connection(self, provider: str | None = None) -> bool:
        provider_id = self.current_provider(provider)
        label = self.provider_label(provider_id)
        if provider_id == "lmstudio":
            self._log(f"Checking {label} at {self.active_lmstudio_base_url()}...")
            self._log(
                "LM Studio note: open Developer -> Local Server and make sure "
                "Status is Running."
            )
        else:
            self._log(f"Checking {label} connectivity...")
        status = self.connection_status(provider_id)
        self._log(("✓ " if status.ok else "✗ ") + status.message)
        return bool(status.ok)

    def active_lmstudio_base_url(
        self,
        selection: ProviderSelection | None = None,
    ) -> str:
        if selection is not None:
            if not isinstance(selection, ProviderSelection):
                raise TypeError(
                    "LM Studio endpoint selection requires ProviderSelection."
                )
            if selection.endpoint:
                return selection.endpoint
        return (
            str(
                self.provider_base_url("lmstudio")
                or chat_providers.get_provider_setting("lmstudio", "base_url")
                or self._lmstudio_base_url
            ).strip()
            or self._lmstudio_base_url
        )

    def unload_lmstudio_models(
        self,
        reason: str = "MuseTalk warmup",
        *,
        endpoint: str = "",
    ) -> object:
        return self._service.unload_lmstudio_models(
            reason,
            endpoint=str(endpoint or "").strip() or self.active_lmstudio_base_url(),
        )

    def load_lmstudio_model(
        self,
        model: str,
        *,
        endpoint: str = "",
    ) -> object:
        return self._service.load_lmstudio_model(
            model,
            endpoint=str(endpoint or "").strip() or self.active_lmstudio_base_url(),
        )

    def lmstudio_sdk(self) -> Any:
        return lmstudio_runtime.get_sdk()

    def lmstudio_sdk_host(self, endpoint: str = "") -> str:
        return lmstudio_runtime.sdk_host(
            str(endpoint or "").strip() or self.active_lmstudio_base_url()
        )

    def lmstudio_sdk_client(self, sdk: Any, endpoint: str = "") -> Any:
        return lmstudio_runtime.sdk_client(
            sdk,
            str(endpoint or "").strip() or self.active_lmstudio_base_url(),
        )

    @staticmethod
    def run_lms_cli(
        args: Iterable[str],
        *,
        timeout: float = 300,
    ) -> tuple[bool, str]:
        return lmstudio_runtime.run_lms_cli(list(args), timeout=timeout)

    def _unload_lmstudio_models(self, reason: str, endpoint: str) -> bool:
        return lmstudio_runtime.unload_models(
            base_url=str(endpoint or "").strip() or self.active_lmstudio_base_url(),
            logger=self._logger,
            reason=reason,
        )

    def _lmstudio_context_length(self) -> int | None:
        settings = self._config.snapshot().values.get("chat_provider_settings", {})
        provider_settings = (
            settings.get("lmstudio", {}) if isinstance(settings, Mapping) else {}
        )
        value = (
            provider_settings.get("context_length")
            if isinstance(provider_settings, Mapping) else None
        )
        return lmstudio_runtime.configured_chat_context_length(value)

    def _load_lmstudio_model(self, model: str, endpoint: str) -> bool:
        return lmstudio_runtime.load_model(
            model,
            base_url=str(endpoint or "").strip() or self.active_lmstudio_base_url(),
            is_placeholder=self.is_model_catalog_placeholder,
            logger=self._logger,
            ttl_seconds=None,
            preserve_existing_models=True,
            load_config=lmstudio_runtime.main_chat_load_config(
                self._lmstudio_context_length()
            ),
            parallel_predictions=lmstudio_runtime.DEFAULT_PARALLEL_PREDICTIONS,
        )

    def _load_pinned_lmstudio_model(self, model: str, endpoint: str) -> bool:
        selected_main_model = str(
            self._config.snapshot().values.get("model_name") or ""
        ).strip()
        load_config = (
            lmstudio_runtime.main_chat_load_config(self._lmstudio_context_length())
            if selected_main_model.casefold() == str(model or "").strip().casefold()
            else lmstudio_runtime.VISION_LOAD_CONFIG
        )
        return lmstudio_runtime.load_model(
            model,
            base_url=str(endpoint or "").strip() or self.active_lmstudio_base_url(),
            is_placeholder=self.is_model_catalog_placeholder,
            logger=self._logger,
            ttl_seconds=None,
            preserve_existing_models=True,
            load_config=load_config,
            parallel_predictions=lmstudio_runtime.DEFAULT_PARALLEL_PREDICTIONS,
        )

    def _list_loaded_lmstudio_models(
        self,
        endpoint: str,
    ) -> tuple[lmstudio_runtime.LoadedModelInstance, ...]:
        return lmstudio_runtime.list_loaded_model_instances(
            base_url=str(endpoint or "").strip() or self.active_lmstudio_base_url(),
            logger=self._logger,
            prefer_native_api=True,
        )

    def _unload_one_lmstudio_model(
        self,
        identifier: str,
        endpoint: str,
    ) -> bool:
        return lmstudio_runtime.unload_model(
            identifier,
            base_url=str(endpoint or "").strip() or self.active_lmstudio_base_url(),
            logger=self._logger,
        )

    def _unload_auxiliary_lmstudio_models(
        self,
        reason: str,
        endpoint: str,
    ) -> bool:
        return lmstudio_runtime.unload_models(
            base_url=str(endpoint or "").strip(),
            logger=self._logger,
            reason=reason,
            allow_cli_fallback=False,
        )

    def _load_auxiliary_lmstudio_model(
        self,
        model: str,
        endpoint: str,
    ) -> bool:
        return lmstudio_runtime.load_model(
            model,
            base_url=str(endpoint or "").strip(),
            is_placeholder=self.is_model_catalog_placeholder,
            logger=self._logger,
            allow_cli_fallback=False,
            load_config=lmstudio_runtime.VISION_LOAD_CONFIG,
            parallel_predictions=lmstudio_runtime.DEFAULT_PARALLEL_PREDICTIONS,
        )

    def _on_config_changed(self, event: RuntimeConfigChanged) -> None:
        if "chat_provider_settings" in event.changed_keys:
            self._apply_provider_settings(event.values)

    @staticmethod
    def _apply_provider_settings(values: Mapping[str, object]) -> None:
        raw_settings = values.get("chat_provider_settings", {})
        settings = (
            {
                str(provider_id): dict(provider_settings)
                for provider_id, provider_settings in raw_settings.items()
                if isinstance(provider_settings, Mapping)
            }
            if isinstance(raw_settings, Mapping)
            else {}
        )
        chat_providers.set_provider_settings(settings)

    def _log(self, message: str) -> None:
        self._logger(str(message))


__all__ = [
    "DEFAULT_LMSTUDIO_BASE_URL",
    "ProductionProviderOwner",
]
