from __future__ import annotations

import os
from typing import Any, Iterable, Mapping

from openai import OpenAI

from core.addons.base import BaseAddon
from core import chat_providers


PROVIDER_ID = "openai"

_OFFICIAL_OPENAI_BASE_URL = "https://api.openai.com/v1"
_PROVIDER_DEFAULT_SAMPLING_MODEL_PREFIXES = ("gpt-5.6",)


def _extract_text(response: Any) -> str:
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
                continue
            text_value = getattr(item, "text", None)
            if text_value:
                parts.append(str(text_value))
                continue
            if isinstance(item, dict):
                dict_text = item.get("text")
                if dict_text:
                    parts.append(str(dict_text))
        return "".join(parts).strip()
    return str(content or "").strip()


def _stream_text(stream: Iterable[Any]):
    for event in stream:
        choices = getattr(event, "choices", None) or []
        if not choices:
            continue
        delta = getattr(choices[0], "delta", None)
        content = getattr(delta, "content", None) if delta is not None else None
        if isinstance(content, list):
            for item in content:
                if isinstance(item, str) and item:
                    yield item
                    continue
                text_value = getattr(item, "text", None)
                if text_value:
                    yield str(text_value)
                    continue
                if isinstance(item, dict):
                    dict_text = item.get("text")
                    if dict_text:
                        yield str(dict_text)
        elif content:
            yield str(content)


def _should_retry_with_max_completion_tokens(exc: Exception) -> bool:
    text = str(exc or "").lower()
    return (
        "unsupported parameter" in text
        and "max_tokens" in text
        and "max_completion_tokens" in text
    )


def _params_with_max_completion_tokens(params: dict[str, Any]) -> dict[str, Any]:
    updated = dict(params or {})
    if "max_tokens" in updated and "max_completion_tokens" not in updated:
        updated["max_completion_tokens"] = updated.pop("max_tokens")
    return updated


def _uses_provider_default_sampling(model_name: Any) -> bool:
    normalized = str(model_name or "").strip().lower()
    return any(
        normalized == prefix or normalized.startswith(f"{prefix}-")
        for prefix in _PROVIDER_DEFAULT_SAMPLING_MODEL_PREFIXES
    )


def _structured_openai_error(exc: Exception) -> Mapping[str, Any]:
    body = getattr(exc, "body", None)
    if not isinstance(body, Mapping):
        return {}
    nested = body.get("error")
    return nested if isinstance(nested, Mapping) else body


def _unsupported_sampling_parameter(exc: Exception) -> str:
    body = _structured_openai_error(exc)
    parameter = str(
        getattr(exc, "param", None) or body.get("param") or ""
    ).strip().lower()
    if parameter not in {"temperature", "top_p"}:
        return ""
    message = str(body.get("message") or exc or "").strip().lower()
    code = str(getattr(exc, "code", None) or body.get("code") or "").strip().lower()
    if "unsupported" not in message and "unsupported" not in code:
        return ""
    return parameter


def _safe_openai_error_detail(exc: Exception) -> str:
    body = _structured_openai_error(exc)
    message = str(body.get("message") or "").strip()
    if not message:
        return f"{type(exc).__name__} without structured provider details."
    parameter = str(
        getattr(exc, "param", None) or body.get("param") or ""
    ).strip()
    code = str(getattr(exc, "code", None) or body.get("code") or "").strip()
    attributes = []
    if parameter:
        attributes.append(f"param={parameter}")
    if code:
        attributes.append(f"code={code}")
    suffix = f" ({', '.join(attributes)})" if attributes else ""
    return f"{message}{suffix}"


def _create_responses_with_sampling_fallback(create, params: Mapping[str, Any]):
    request = dict(params or {})
    for _attempt in range(3):
        try:
            return create(**request)
        except Exception as exc:
            parameter = _unsupported_sampling_parameter(exc)
            if not parameter or parameter not in request:
                raise
            model_name = str(request.get("model") or "").strip() or "selected model"
            print(
                f"⚠️ [OpenAI] {model_name} rejected {parameter}; "
                "retrying with the provider default."
            )
            request.pop(parameter, None)
    raise RuntimeError("OpenAI sampling compatibility retry limit was exceeded.")


def _create_frozen_responses(client, params: Mapping[str, Any]):
    try:
        return _create_responses_with_sampling_fallback(
            client.responses.create,
            params,
        )
    except chat_providers.FrozenChatProviderExecutionError:
        raise
    except Exception as exc:
        raise chat_providers.FrozenChatProviderExecutionError(
            f"OpenAI request failed: {_safe_openai_error_detail(exc)}"
        ) from None


def _coerce_frozen_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        return min(maximum, max(minimum, float(value)))
    except Exception:
        return default


def _coerce_frozen_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        return min(maximum, max(minimum, int(float(value))))
    except Exception:
        return default


def _frozen_request_params(
    binding,
    params: dict[str, Any],
    *,
    output_budget_override: Any = None,
) -> dict[str, Any]:
    request = dict(params or {})
    generation = binding._generation_fields_copy()
    request["model"] = binding.model_name
    if "temperature" in generation:
        request["temperature"] = _coerce_frozen_float(
            generation["temperature"], 1.0, 0.0, 2.0
        )
    if "top_p" in generation:
        request["top_p"] = _coerce_frozen_float(generation["top_p"], 0.9, 0.0, 1.0)
    if output_budget_override is not None:
        request["max_tokens"] = _coerce_frozen_int(
            output_budget_override, -1, -1, 131072
        )
    elif "max_tokens" in generation:
        request.pop("max_tokens", None)
        max_tokens = _coerce_frozen_int(generation["max_tokens"], -1, -1, 131072)
        if max_tokens != -1:
            request["max_tokens"] = max_tokens
    return request


def _is_official_openai_base_url(value: Any) -> bool:
    normalized = str(value or "").strip().rstrip("/").lower()
    return not normalized or normalized == _OFFICIAL_OPENAI_BASE_URL


def _responses_content(content: Any) -> str | list[dict[str, Any]]:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        raise TypeError("OpenAI Responses message content must be text or a content list.")

    converted: list[dict[str, Any]] = []
    for item in content:
        if isinstance(item, str):
            converted.append({"type": "input_text", "text": item})
            continue
        if not isinstance(item, Mapping):
            raise TypeError("OpenAI Responses content items must be mappings.")
        item_type = str(item.get("type") or "").strip().lower()
        if item_type in {"text", "input_text"}:
            converted.append(
                {"type": "input_text", "text": str(item.get("text") or "")}
            )
            continue
        if item_type in {"image_url", "input_image"}:
            raw_image = item.get("image_url")
            if isinstance(raw_image, Mapping):
                image_url = str(raw_image.get("url") or "").strip()
                detail = str(raw_image.get("detail") or "").strip()
            else:
                image_url = str(raw_image or "").strip()
                detail = str(item.get("detail") or "").strip()
            if not image_url:
                raise ValueError("OpenAI Responses image content requires an image URL.")
            converted_item = {"type": "input_image", "image_url": image_url}
            if detail:
                converted_item["detail"] = detail
            converted.append(converted_item)
            continue
        raise ValueError(f"Unsupported OpenAI Responses content type: {item_type!r}.")
    return converted


def _responses_input(messages: Any) -> list[dict[str, Any]]:
    if not isinstance(messages, (list, tuple)):
        raise TypeError("OpenAI Responses input requires a message sequence.")
    converted: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, Mapping):
            raise TypeError("OpenAI Responses messages must be mappings.")
        role = str(message.get("role") or "").strip().lower()
        if role not in {"system", "user", "assistant"}:
            raise ValueError(f"Unsupported OpenAI Responses role: {role!r}.")
        converted.append(
            {"role": role, "content": _responses_content(message.get("content"))}
        )
    return converted


def _frozen_responses_params(
    binding,
    params: dict[str, Any],
    *,
    output_budget_override: Any = None,
) -> dict[str, Any]:
    source = dict(params or {})
    generation = binding._generation_fields_copy()
    request: dict[str, Any] = {
        "model": binding.model_name,
        "input": _responses_input(source.get("messages") or []),
        "store": False,
    }
    if not _uses_provider_default_sampling(binding.model_name):
        for key, default, minimum, maximum in (
            ("temperature", 1.0, 0.0, 2.0),
            ("top_p", 0.9, 0.0, 1.0),
        ):
            value = generation.get(key, source.get(key))
            if value is not None:
                request[key] = _coerce_frozen_float(value, default, minimum, maximum)
    max_tokens = (
        output_budget_override
        if output_budget_override is not None
        else generation.get(
            "max_tokens",
            source.get(
                "max_output_tokens",
                source.get("max_completion_tokens", source.get("max_tokens", -1)),
            ),
        )
    )
    max_tokens = _coerce_frozen_int(max_tokens, -1, -1, 131072)
    if max_tokens > 0:
        request["max_output_tokens"] = max_tokens
    return request


def _extract_responses_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text:
        return output_text.strip()
    parts: list[str] = []
    for item in list(getattr(response, "output", None) or []):
        if str(getattr(item, "type", "") or "").strip() != "message":
            continue
        for content in list(getattr(item, "content", None) or []):
            if str(getattr(content, "type", "") or "").strip() != "output_text":
                continue
            text = getattr(content, "text", None)
            if text:
                parts.append(str(text))
    return "".join(parts).strip()


def _stream_responses_text(stream: Iterable[Any]):
    for event in stream:
        event_type = (
            str(event.get("type") or "")
            if isinstance(event, Mapping)
            else str(getattr(event, "type", "") or "")
        ).strip()
        if event_type != "response.output_text.delta":
            continue
        delta = (
            event.get("delta")
            if isinstance(event, Mapping)
            else getattr(event, "delta", None)
        )
        if delta:
            yield str(delta)


def _frozen_client_for_binding(binding):
    config = binding._provider_config_copy()
    api_key = str(config.get("api_key") or "").strip()
    base_url = str(config.get("base_url") or "").strip()
    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url)
    return OpenAI(api_key=api_key)


def _frozen_client(request):
    binding = getattr(request.context, "_binding", None)
    if binding is None or binding.provider_name != PROVIDER_ID:
        raise RuntimeError("OpenAI frozen request binding is unavailable.")
    return _frozen_client_for_binding(binding)


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self._chat_service = context.get_service("qt.chat_providers")
        if self._chat_service is None:
            context.logger.warning("OpenAI provider addon could not find qt.chat_providers service.")
            return None

        self._chat_service.register_provider(
            provider_id=PROVIDER_ID,
            label="OpenAI",
            description="Hosted OpenAI models.",
            order=200,
            client_factory=self._client,
            model_list_handler=self._list_models,
            completion_handler=self._complete_chat,
            stream_handler=self._stream_chat,
            connection_check_handler=self._check_connection,
            api_key_getter=self._api_key,
            base_url_getter=self._base_url,
            frozen_execution_version=1,
            frozen_prepare_handler=self._prepare_frozen_chat,
            frozen_completion_handler=self._complete_frozen_chat,
            frozen_stream_handler=self._stream_frozen_chat,
            model_capabilities_handler=self._frozen_model_capabilities,
            frozen_private_config_getter=self._frozen_private_config,
            frozen_public_config_fields=("base_url", "provider_is_remote"),
            metadata={
                "config_fields": [
                    {"id": "api_key", "label": "API Key", "env": ["NC_CHAT_OPENAI_API_KEY", "OPENAI_API_KEY"]},
                    {"id": "base_url", "label": "Base URL", "env": ["NC_CHAT_OPENAI_BASE_URL"]},
                ],
                "generation_fields": [
                    {"id": "temperature", "label": "Temperature", "kind": "float", "min": 0.0, "max": 2.0, "step": 0.01, "decimals": 2, "default": 1.0, "request_location": "params"},
                    {"id": "top_p", "label": "Top P", "kind": "float", "min": 0.0, "max": 1.0, "step": 0.01, "decimals": 2, "default": 0.9, "request_location": "params"},
                    {
                        "id": "max_tokens",
                        "label": "Max Tokens (-1 = provider default)",
                        "kind": "int",
                        "min": -1,
                        "max": 131072,
                        "step": 1,
                        "default": -1,
                        "omit_if": [-1, "-1"],
                        "request_location": "params",
                        "description": "Use -1 to omit max_tokens and let the provider/model choose its own response cap.",
                    },
                ],
                "hint": "Hosted OpenAI provider. API key is required.",
                "supports_hosted_runtime": True,
            },
        )
        context.logger.info("OpenAI chat provider addon initialized.")
        return None

    def shutdown(self):
        chat_service = getattr(self, "_chat_service", None)
        if chat_service is not None:
            try:
                chat_service.unregister_provider(PROVIDER_ID)
            except Exception:
                pass
        return None

    def _setting(self, field_id: str) -> str:
        chat_service = getattr(self, "_chat_service", None)
        getter = getattr(chat_service, "get_provider_setting", None)
        if callable(getter):
            try:
                return str(getter(PROVIDER_ID, field_id) or "").strip()
            except Exception:
                return ""
        return ""

    def _api_key(self) -> str:
        return self._setting("api_key") or str(os.environ.get("NC_CHAT_OPENAI_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "") or "").strip()

    def _base_url(self) -> str:
        return self._setting("base_url") or str(os.environ.get("NC_CHAT_OPENAI_BASE_URL", "") or "").strip()

    def _frozen_private_config(self) -> dict[str, bool]:
        return {"provider_is_remote": True}

    def _client(self) -> OpenAI:
        base_url = self._base_url()
        api_key = self._api_key()
        if base_url:
            return OpenAI(api_key=api_key, base_url=base_url)
        return OpenAI(api_key=api_key)

    def _list_models(self, quiet: bool = False):
        try:
            client = self._client()
            payload = client.models.list()
            ids = sorted(
                {
                    str(getattr(model, "id", "") or "").strip()
                    for model in list(getattr(payload, "data", []) or [])
                    if str(getattr(model, "id", "") or "").strip()
                }
            )
            return ids
        except Exception as exc:
            if not quiet:
                print(f"Error fetching OpenAI models: {exc}")
            return []

    def _check_connection(self):
        if not self._api_key():
            return {"ok": False, "detail": "OpenAI API key is required."}
        try:
            client = self._client()
            payload = client.models.list()
            count = len(list(getattr(payload, "data", []) or []))
            return {
                "ok": True,
                "detail": f"Connected to OpenAI ({count} model(s) available)",
                "model_count": count,
            }
        except Exception as exc:
            return {"ok": False, "detail": str(exc)}

    def _complete_chat(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None) -> str:
        client = self._client()
        request = dict(params or {})
        try:
            response = client.chat.completions.create(**request)
        except Exception as exc:
            if not _should_retry_with_max_completion_tokens(exc):
                raise
            response = client.chat.completions.create(**_params_with_max_completion_tokens(request))
        return _extract_text(response)

    def _stream_chat(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None):
        def _iter_stream():
            client = self._client()
            request = {**dict(params or {}), "stream": True}
            try:
                stream = client.chat.completions.create(**request)
            except Exception as exc:
                if not _should_retry_with_max_completion_tokens(exc):
                    raise
                stream = client.chat.completions.create(**_params_with_max_completion_tokens(request))
            yield from _stream_text(stream)

        return _iter_stream()

    def _prepare_frozen_chat(self, binding, params, additional_params):
        config = binding._provider_config_copy()
        extras = dict(additional_params or {})
        output_budget_override = extras.pop(
            chat_providers.FROZEN_OUTPUT_TOKEN_BUDGET_OVERRIDE,
            None,
        )
        if _is_official_openai_base_url(config.get("base_url")):
            return (
                _frozen_responses_params(
                    binding,
                    params,
                    output_budget_override=output_budget_override,
                ),
                extras,
            )
        return (
            _frozen_request_params(
                binding,
                params,
                output_budget_override=output_budget_override,
            ),
            extras,
        )

    def _frozen_model_capabilities(self, binding):
        config = binding._provider_config_copy()
        if not _is_official_openai_base_url(config.get("base_url")):
            return None
        model_name = str(binding.model_name or "").strip()
        if not model_name:
            return None
        execution_identity = binding.execution_identity

        def exact_token_counter(messages) -> int:
            client = _frozen_client_for_binding(binding)
            response = client.responses.input_tokens.count(
                model=model_name,
                input=list(messages),
            )
            count = getattr(response, "input_tokens", None)
            if type(count) is not int or count < 0:
                raise RuntimeError("OpenAI returned an invalid input token count.")
            return count

        return {
            "context_limit": None,
            "token_counter": exact_token_counter,
            "capability_identity": execution_identity,
            "token_counter_identity": execution_identity,
        }

    def _complete_frozen_chat(self, request, *, timeout=None, cancel_token=None) -> str:
        del cancel_token
        client = _frozen_client(request)
        request_params = request.params_copy()
        if timeout is not None:
            request_params["timeout"] = timeout
        if "input" in request_params:
            response = _create_frozen_responses(client, request_params)
            return _extract_responses_text(response)
        try:
            response = client.chat.completions.create(**request_params)
        except Exception as exc:
            if not _should_retry_with_max_completion_tokens(exc):
                raise
            response = client.chat.completions.create(
                **_params_with_max_completion_tokens(request_params)
            )
        return _extract_text(response)

    def _stream_frozen_chat(self, request, *, timeout=None, cancel_token=None):
        del cancel_token

        def _iter_stream():
            client = _frozen_client(request)
            request_params = {**request.params_copy(), "stream": True}
            if timeout is not None:
                request_params["timeout"] = timeout
            if "input" in request_params:
                yield from _stream_responses_text(
                    _create_frozen_responses(client, request_params)
                )
                return
            try:
                stream = client.chat.completions.create(**request_params)
            except Exception as exc:
                if not _should_retry_with_max_completion_tokens(exc):
                    raise
                stream = client.chat.completions.create(
                    **_params_with_max_completion_tokens(request_params)
                )
            yield from _stream_text(stream)

        return _iter_stream()
