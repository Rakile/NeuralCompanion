from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib.request import Request, urlopen

from openai import OpenAI

from .models import BuddyPersona, BuddySettings, ProviderOverride


CompletionHandler = Callable[["ProviderCallConfig", dict[str, Any], dict[str, Any]], str]
JsonFetcher = Callable[[str, str, float], dict[str, Any]]
DEFAULT_LMSTUDIO_BASE_URL = "http://127.0.0.1:1234/v1"


@dataclass
class ProviderCallConfig:
    provider_id: str
    model: str
    base_url: str = ""
    api_key: str = ""
    persona_id: str = ""
    persona_name: str = ""
    uses_main_runtime: bool = False


def _normalize_openai_base_url(base_url: str | None) -> str:
    url = str(base_url or "").strip().rstrip("/")
    if not url:
        return ""
    if url.endswith("/v1"):
        return url
    if "://" not in url:
        return url
    path_start = url.find("/", url.find("://") + 3)
    if path_start < 0:
        return f"{url}/v1"
    path = url[path_start:].strip("/")
    if not path:
        return f"{url[:path_start]}/v1"
    return url


def _lmstudio_native_base_url(base_url: str | None) -> str:
    openai_url = _normalize_openai_base_url(base_url or DEFAULT_LMSTUDIO_BASE_URL) or DEFAULT_LMSTUDIO_BASE_URL
    native = openai_url.rstrip("/")
    if native.endswith("/v1"):
        native = native[:-3]
    return native.rstrip("/") or "http://127.0.0.1:1234"


def _fetch_json_with_bearer(url: str, api_key: str, timeout: float) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    token = str(api_key or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(str(url), headers=headers, method="GET")
    with urlopen(request, timeout=float(timeout)) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _native_lmstudio_model_ids(payload: dict[str, Any]) -> list[str]:
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return []
    ids: set[str] = set()
    for model in models:
        if not isinstance(model, dict):
            continue
        model_type = str(model.get("type") or "").strip().lower()
        if model_type not in {"", "llm"}:
            continue
        model_id = str(model.get("key") or model.get("id") or "").strip()
        if model_id:
            ids.add(model_id)
    return sorted(ids, key=str.lower)


def _openai_model_ids(payload: dict[str, Any]) -> list[str]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return []
    ids = {
        str(model.get("id") or "").strip()
        for model in data
        if isinstance(model, dict) and str(model.get("id") or "").strip()
    }
    return sorted(ids, key=str.lower)


def list_lmstudio_models_for_base_url(
    base_url: str | None = "",
    *,
    api_key: str = "",
    timeout: float = 5.0,
    fetch_json: JsonFetcher | None = None,
) -> list[str]:
    fetcher = fetch_json or _fetch_json_with_bearer
    native_url = f"{_lmstudio_native_base_url(base_url)}/api/v1/models"
    last_error: Exception | None = None
    try:
        native_models = _native_lmstudio_model_ids(fetcher(native_url, api_key, timeout))
        if native_models:
            return native_models
    except Exception as exc:
        last_error = exc

    openai_base = _normalize_openai_base_url(base_url or DEFAULT_LMSTUDIO_BASE_URL) or DEFAULT_LMSTUDIO_BASE_URL
    openai_url = f"{openai_base.rstrip('/')}/models"
    try:
        return _openai_model_ids(fetcher(openai_url, api_key, timeout))
    except Exception as exc:
        last_error = exc
    if last_error is not None:
        raise RuntimeError(f"Could not fetch LM Studio models from {base_url or DEFAULT_LMSTUDIO_BASE_URL}: {last_error}")
    return []


def _extract_completion_text(response: Any) -> str:
    if isinstance(response, str):
        return str(response)
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None) if message is not None else None
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("text"):
                parts.append(str(item.get("text") or ""))
            elif getattr(item, "text", None):
                parts.append(str(getattr(item, "text")))
        return "".join(parts).strip()
    return str(content or "").strip()


class BuddyProviderRuntime:
    """Runs Buddy Chat LLM calls without mutating NC's active provider settings."""

    def __init__(self, completion_handler: CompletionHandler | None = None) -> None:
        self._completion_handler = completion_handler

    def resolve_call_config(
        self,
        *,
        persona: BuddyPersona,
        settings: BuddySettings,
        fallback_model: str = "",
    ) -> ProviderCallConfig:
        override = self._selected_override(persona=persona, settings=settings)
        provider_id = str(override.provider_id or "inherit").strip().lower()
        model = str(override.model or fallback_model or "").strip()
        if provider_id in {"", "inherit", "main"}:
            return ProviderCallConfig(
                provider_id="main",
                model=model,
                persona_id=persona.id,
                persona_name=persona.display_name,
                uses_main_runtime=True,
            )
        return ProviderCallConfig(
            provider_id=provider_id,
            model=model,
            base_url=_normalize_openai_base_url(override.base_url),
            api_key=str(override.api_key or "").strip(),
            persona_id=persona.id,
            persona_name=persona.display_name,
            uses_main_runtime=False,
        )

    def complete_for_persona(
        self,
        *,
        persona: BuddyPersona,
        settings: BuddySettings,
        messages: list[dict[str, Any]],
        fallback_model: str = "",
        additional_params: dict[str, Any] | None = None,
    ) -> str:
        config = self.resolve_call_config(persona=persona, settings=settings, fallback_model=fallback_model)
        if not config.model:
            config.model = self._current_main_model()
        params: dict[str, Any] = {
            "model": config.model,
            "messages": list(messages or []),
        }
        additional = dict(additional_params or {})
        if self._completion_handler is not None:
            return str(self._completion_handler(config, params, additional) or "").strip()
        if config.uses_main_runtime:
            return self._complete_with_main_runtime(params, additional)
        if config.provider_id == "lmstudio" or config.base_url or config.api_key:
            return self._complete_openai_compatible(config, params, additional)
        return self._complete_with_registered_provider(config.provider_id, params, additional)

    @staticmethod
    def _selected_override(*, persona: BuddyPersona, settings: BuddySettings) -> ProviderOverride:
        if settings.llm_mode == "per_persona":
            provider = getattr(persona, "provider", ProviderOverride())
            persona_provider_id = str(provider.provider_id or "inherit").strip().lower()
            if persona_provider_id not in {"", "inherit", "main"}:
                return provider
            if persona_provider_id == "main":
                return ProviderOverride(provider_id="main")
            buddy_provider = getattr(settings, "buddy_provider", ProviderOverride())
            if str(buddy_provider.provider_id or "inherit").strip().lower() not in {"", "inherit", "main"}:
                return buddy_provider
        if settings.llm_mode == "buddy":
            provider = getattr(settings, "buddy_provider", ProviderOverride())
            if str(provider.provider_id or "inherit").strip().lower() not in {"", "inherit", "main"}:
                return provider
        return ProviderOverride(provider_id="main")

    @staticmethod
    def _current_main_model() -> str:
        try:
            import engine

            return str(engine.RUNTIME_CONFIG.get("model_name", "") or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _complete_with_main_runtime(params: dict[str, Any], additional: dict[str, Any]) -> str:
        import engine

        applier = getattr(engine, "_apply_chat_provider_generation_fields", None)
        if callable(applier):
            try:
                applier(params, additional)
            except Exception:
                pass
        create = getattr(engine, "_chat_completion_create", None)
        if not callable(create):
            raise RuntimeError("NC main LLM runtime is unavailable.")
        return str(create(params, additional) or "").strip()

    @staticmethod
    def _complete_openai_compatible(config: ProviderCallConfig, params: dict[str, Any], additional: dict[str, Any]) -> str:
        default_base_urls = {
            "lmstudio": "http://127.0.0.1:1234/v1",
            "ollama": "http://127.0.0.1:11434/v1",
            "xai": "https://api.x.ai/v1",
            "deepseek": "https://api.deepseek.com",
        }
        base_url = config.base_url or default_base_urls.get(config.provider_id, "")
        api_key = config.api_key or ("lm-studio" if config.provider_id in {"lmstudio", "ollama"} else "")
        client_kwargs: dict[str, Any] = {}
        if base_url:
            client_kwargs["base_url"] = base_url
        if api_key:
            client_kwargs["api_key"] = api_key
        client = OpenAI(**client_kwargs)
        request_kwargs = dict(params or {})
        if additional:
            request_kwargs["extra_body"] = dict(additional or {})
        response = client.chat.completions.create(**request_kwargs)
        return _extract_completion_text(response)

    @staticmethod
    def _complete_with_registered_provider(provider_id: str, params: dict[str, Any], additional: dict[str, Any]) -> str:
        from core import chat_providers

        return str(chat_providers.complete_chat(provider_id, params, additional) or "").strip()
