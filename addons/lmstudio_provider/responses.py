from __future__ import annotations

import json
import re
import urllib.error
from typing import Any, Iterable


class ResponsesProtocolError(RuntimeError):
    pass


def decode_http_text(raw: bytes, charset: str | None = None) -> str:
    encodings: list[str] = []
    if charset:
        encodings.append(str(charset))
    encodings.extend(["utf-8", "cp1252"])

    seen: set[str] = set()
    fallback = ""
    for encoding in encodings:
        normalized = encoding.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        try:
            text = raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
        if "\ufffd" not in text:
            return text
        if not fallback:
            fallback = text
    return fallback or raw.decode("utf-8", errors="replace")


def response_charset(response: Any) -> str | None:
    headers = getattr(response, "headers", None)
    getter = getattr(headers, "get_content_charset", None)
    if not callable(getter):
        return None
    try:
        return getter()
    except Exception:
        return None


def http_error_text(exc: urllib.error.HTTPError) -> str:
    try:
        body = decode_http_text(exc.read(), response_charset(exc))
    except Exception:
        body = ""
    return body[:4000] or str(exc)


def responses_url(base_url: str) -> str:
    return f"{str(base_url or '').rstrip('/')}/responses"


def map_reasoning_effort(requested: Any, model_metadata: dict[str, Any] | None) -> str | None:
    metadata = dict(model_metadata or {})
    if not bool(metadata.get("supports_reasoning")):
        return None

    options = {
        str(value).strip().lower()
        for value in metadata.get("reasoning_options", [])
        if str(value).strip()
    }
    if requested is True:
        value = "on"
    elif requested is False:
        value = "off"
    else:
        value = str(requested or "").strip().lower()

    if {"off", "on"}.issubset(options):
        return "none" if value in {"", "off", "none", "false", "0"} else "low"
    if value in {"off", "none", "false", "0"}:
        return "none" if "none" in options else None
    if value in options:
        return value
    if value == "on":
        default = str(metadata.get("reasoning_default") or "").strip().lower()
        if default in options and default != "none":
            return default
        for candidate in ("minimal", "low", "medium", "high", "xhigh"):
            if candidate in options:
                return candidate
    return None


def _message_content(content: Any) -> str | list[dict[str, Any]]:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content or "")

    converted: list[dict[str, Any]] = []
    for item in content:
        if isinstance(item, str):
            converted.append({"type": "input_text", "text": item})
            continue
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip().lower()
        if item_type == "text":
            converted.append({"type": "input_text", "text": str(item.get("text") or "")})
        elif item_type == "image_url":
            image_url = item.get("image_url")
            url = image_url.get("url") if isinstance(image_url, dict) else image_url
            if str(url or "").strip():
                converted.append({"type": "input_image", "image_url": str(url).strip()})
    return converted


def map_response_format(response_format: Any) -> dict[str, Any] | None:
    if response_format is None:
        return None
    if not isinstance(response_format, dict):
        raise ValueError("Unsupported LM Studio Responses format: expected an object")

    kind = str(response_format.get("type") or "").strip().lower()
    if kind == "json_object":
        return {
            "tools": [
                {
                    "type": "function",
                    "name": "json_response",
                    "description": "Return the requested JSON object.",
                    "parameters": {"type": "object", "properties": {}, "additionalProperties": True},
                    "strict": False,
                }
            ],
            "tool_choice": "required",
        }
    if kind == "json_schema" and isinstance(response_format.get("json_schema"), dict):
        schema = dict(response_format["json_schema"])
        name = re.sub(r"[^A-Za-z0-9_-]", "_", str(schema.get("name") or "structured_response"))[:64]
        return {
            "tools": [
                {
                    "type": "function",
                    "name": name or "structured_response",
                    "description": "Return the requested structured response.",
                    "parameters": dict(schema.get("schema") or {}),
                    "strict": bool(schema.get("strict", False)),
                }
            ],
            "tool_choice": "required",
        }
    raise ValueError(f"Unsupported LM Studio Responses format: {kind or 'missing type'}")


def build_responses_payload(
    params: dict[str, Any],
    additional_params: dict[str, Any] | None,
    model_metadata: dict[str, Any] | None,
    *,
    stream: bool,
) -> dict[str, Any]:
    source = dict(params or {})
    extras = dict(additional_params or {})
    input_items: list[dict[str, Any]] = []

    for message in source.get("messages", []):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").strip().lower()
        if role not in {"system", "user", "assistant"}:
            raise ValueError(f"Unsupported LM Studio Responses role: {role}")
        input_items.append({"role": role, "content": _message_content(message.get("content"))})

    payload: dict[str, Any] = {
        "model": str(source.get("model") or "").strip(),
        "input": input_items,
        "store": False,
        "stream": bool(stream),
    }
    for key in ("temperature", "top_p"):
        if source.get(key) is not None:
            payload[key] = source[key]

    max_output_tokens = source.get("max_tokens", source.get("max_completion_tokens"))
    try:
        max_output_tokens = int(max_output_tokens)
    except (TypeError, ValueError):
        max_output_tokens = None
    if max_output_tokens is not None and max_output_tokens > 0:
        payload["max_output_tokens"] = max_output_tokens

    for key in ("top_k", "repeat_penalty", "min_p"):
        if extras.get(key) is not None:
            payload[key] = extras[key]

    structured_output = map_response_format(source.get("response_format"))
    if structured_output is not None:
        payload.update(structured_output)

    effort = map_reasoning_effort(extras.get("reasoning"), model_metadata)
    if effort is not None:
        payload["reasoning"] = {"effort": effort}
    return payload


def extract_response_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise ResponsesProtocolError("LM Studio Responses payload was not an object.")

    parts: list[str] = []
    for item in payload.get("output", []):
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip().lower()
        if item_type == "function_call" and str(item.get("arguments") or ""):
            parts.append(str(item.get("arguments") or ""))
            continue
        if item_type != "message":
            continue
        content_items = item.get("content")
        if not isinstance(content_items, list):
            continue
        for content in content_items:
            if not isinstance(content, dict):
                continue
            if str(content.get("type") or "").strip().lower() == "output_text":
                parts.append(str(content.get("text") or ""))

    if not parts:
        raise ResponsesProtocolError("LM Studio Responses payload contained no output text.")
    return "".join(parts).strip()


def iter_response_sse(lines: Iterable[bytes | str]) -> Iterable[str]:
    function_argument_delta_seen = False
    for raw_line in lines:
        line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else str(raw_line)
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            event = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ResponsesProtocolError(f"Malformed LM Studio Responses stream event: {exc}") from exc

        event_type = str(event.get("type") or "").strip()
        if event_type == "response.output_text.delta":
            delta = str(event.get("delta") or "")
            if delta:
                yield delta
        elif event_type == "response.function_call_arguments.delta":
            delta = str(event.get("delta") or "")
            if delta:
                function_argument_delta_seen = True
                yield delta
        elif event_type == "response.function_call_arguments.done" and not function_argument_delta_seen:
            arguments = str(event.get("arguments") or "")
            if arguments:
                yield arguments
        elif event_type in {"error", "response.failed"}:
            error = event.get("error") if isinstance(event.get("error"), dict) else {}
            response = event.get("response") if isinstance(event.get("response"), dict) else {}
            response_error = response.get("error") if isinstance(response.get("error"), dict) else {}
            message = str(
                error.get("message")
                or response_error.get("message")
                or event.get("message")
                or "LM Studio Responses request failed."
            )
            raise ResponsesProtocolError(message)
