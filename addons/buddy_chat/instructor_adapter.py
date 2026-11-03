from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from addons.buddy_chat import structured_models
from addons.buddy_chat.llm_runtime import BuddyProviderRuntime, ProviderCallConfig
from addons.buddy_chat.models import BuddyPersona, BuddySettings


@dataclass(frozen=True)
class InstructorAvailability:
    available: bool
    reason: str = ""
    module_version: str = ""


def instructor_availability() -> InstructorAvailability:
    try:
        import instructor  # type: ignore
    except Exception as exc:
        return InstructorAvailability(False, f"instructor import failed: {exc}")
    if not structured_models.PYDANTIC_AVAILABLE:
        return InstructorAvailability(False, "pydantic is unavailable")
    version = str(getattr(instructor, "__version__", "") or "")
    return InstructorAvailability(True, "", version)


def generate_buddy_structured_reply(
    *,
    llm_runtime: BuddyProviderRuntime,
    persona: BuddyPersona,
    settings: BuddySettings,
    messages: list[dict[str, Any]],
    fallback_model: str = "",
    max_retries: int = 2,
    logger: Any = None,
) -> dict[str, Any] | None:
    """Run an optional Instructor request through Buddy Chat's selected provider."""
    availability = instructor_availability()
    if not availability.available:
        _log_debug(logger, "Buddy Chat Instructor unavailable: %s", availability.reason)
        return None
    if structured_models.StructuredBuddyReply is None:
        _log_debug(logger, "Buddy Chat Instructor skipped: response model unavailable.")
        return None
    try:
        config = llm_runtime.resolve_call_config(persona=persona, settings=settings, fallback_model=fallback_model)
        if not config.model:
            config.model = llm_runtime._current_main_model()  # type: ignore[attr-defined]
        if not config.model:
            _log_debug(logger, "Buddy Chat Instructor skipped: missing model.")
            return None
        params: dict[str, Any] = {
            "model": config.model,
            "messages": _structured_messages(messages, persona),
            "response_format": {"type": "json_object"},
        }
        payload = llm_runtime.structured_complete(
            config,
            params,
            structured_models.StructuredBuddyReply,
        )
        return payload if payload else None
    except Exception as exc:
        _log_debug(logger, "Buddy Chat Instructor structured request skipped: %s", exc)
        return None


def _structured_messages(messages: list[dict[str, Any]], persona: BuddyPersona) -> list[dict[str, str]]:
    clean: list[dict[str, str]] = []
    for item in list(messages or []):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role in {"system", "user", "assistant"} and content:
            clean.append({"role": role, "content": content})
    persona_id = str(persona.id or "").strip()
    display_name = str(persona.display_name or persona.id or "Buddy").strip() or "Buddy"
    clean.append(
        {
            "role": "system",
            "content": "\n".join(
                [
                    "Buddy Chat structured reply contract:",
                    f"Return exactly one spoken segment for persona_id '{persona_id}' and display_name '{display_name}'.",
                    "Put only the buddy's spoken words in text.",
                    "Set should_speak to false and text to an empty string when this persona has no useful, natural addition.",
                    "Do not include narrator text, stage directions, memory notes, voice paths, provider settings, or arbitrary instructions.",
                    "If you include a speaker label in text, it must match the same buddy exactly.",
                ]
            ),
        }
    )
    return clean


def _client_for_config(config: ProviderCallConfig) -> Any:
    if bool(config.uses_main_runtime):
        return None
    default_base_urls = {
        "lmstudio": "http://127.0.0.1:1234/v1",
        "ollama": "http://127.0.0.1:11434/v1",
        "xai": "https://api.x.ai/v1",
        "deepseek": "https://api.deepseek.com",
    }
    provider_id = str(config.provider_id or "").strip().lower()
    if provider_id not in {"lmstudio", "ollama", "openai", "xai", "deepseek"} and not (config.base_url or config.api_key):
        return None
    client_kwargs: dict[str, Any] = {}
    base_url = str(config.base_url or default_base_urls.get(provider_id, "")).strip()
    api_key = str(config.api_key or ("lm-studio" if provider_id in {"lmstudio", "ollama"} else "")).strip()
    if base_url:
        client_kwargs["base_url"] = base_url
    if api_key:
        client_kwargs["api_key"] = api_key
    return OpenAI(**client_kwargs)


def _wrap_client(instructor_module: Any, client: Any) -> Any:
    for name in ("from_openai", "patch"):
        wrapper = getattr(instructor_module, name, None)
        if not callable(wrapper):
            continue
        try:
            return wrapper(client)
        except Exception:
            continue
    return None


def _call_instructor_client(instructor_client: Any, kwargs: dict[str, Any]) -> Any:
    create = getattr(instructor_client, "create", None)
    if callable(create):
        return create(**kwargs)
    chat = getattr(instructor_client, "chat", None)
    completions = getattr(chat, "completions", None) if chat is not None else None
    create = getattr(completions, "create", None) if completions is not None else None
    if callable(create):
        return create(**kwargs)
    raise RuntimeError("Instructor client does not expose create() or chat.completions.create().")


def _create_kwargs(params: dict[str, Any]) -> dict[str, Any]:
    source = dict(params or {})
    allowed = {
        "model",
        "messages",
        "temperature",
        "top_p",
        "max_tokens",
        "max_completion_tokens",
        "presence_penalty",
        "frequency_penalty",
        "timeout",
    }
    kwargs = {key: value for key, value in source.items() if key in allowed and value is not None}
    kwargs.pop("response_format", None)
    kwargs.pop("stream", None)
    return kwargs


def _log_debug(logger: Any, message: str, *args: Any) -> None:
    if logger is None:
        return
    for name in ("debug", "info"):
        writer = getattr(logger, name, None)
        if callable(writer):
            try:
                writer(message, *args)
            except Exception:
                pass
            return


__all__ = [
    "InstructorAvailability",
    "generate_buddy_structured_reply",
    "instructor_availability",
]
