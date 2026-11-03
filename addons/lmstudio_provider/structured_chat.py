"""Opt-in schema-constrained chat; auxiliary requests retain bounded output."""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Iterable

from addons.lmstudio_provider.responses import map_reasoning_effort


STRUCTURED_PROTOCOL = "lmstudio-structured-chat-v1"


def chat_completions_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/chat/completions"


def is_structured_chat_payload(payload: dict[str, Any]) -> bool:
    return "messages" in payload and isinstance(payload.get("response_format"), dict)


def build_structured_chat_payload(
    source, extras, metadata, *, allow_unbounded_output: bool = False,
) -> dict[str, Any]:
    response_format = source.get("response_format")
    if not isinstance(response_format, dict) or response_format.get("type") != "json_schema":
        raise ValueError("LM Studio structured auxiliary requests require a JSON schema.")
    schema = response_format.get("json_schema")
    if not isinstance(schema, dict) or not isinstance(schema.get("schema"), dict):
        raise ValueError("LM Studio structured auxiliary request has an invalid schema.")
    payload = {"model": source["model"], "messages": deepcopy(source.get("messages", [])),
               "response_format": deepcopy(response_format), "stream": False}
    for key in ("temperature", "top_p"):
        if source.get(key) is not None:
            payload[key] = source[key]
    raw_budget = source.get("max_tokens", source.get("max_completion_tokens", 4096))
    # Main Chat can leave the limit unset or use its explicit -1 no-cap setting.
    # Auxiliary analysis keeps a positive budget unless its caller opts in.
    if raw_budget is None:
        if not allow_unbounded_output:
            raise ValueError("LM Studio structured auxiliary requests require a positive output budget.")
    else:
        budget = int(raw_budget)
        if budget <= 0 and not (allow_unbounded_output and budget == -1):
            raise ValueError("LM Studio structured auxiliary requests require a positive output budget.")
        payload["max_tokens"] = budget
    for key in ("top_k", "repeat_penalty", "min_p"):
        if extras.get(key) is not None:
            payload[key] = extras[key]
    effort = map_reasoning_effort(extras.get("reasoning"), metadata)
    if effort is not None:
        payload["reasoning_effort"] = effort
    return payload


def _choice(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        raise RuntimeError("LM Studio structured chat response was not an object.")
    if payload.get("error"):
        error = payload["error"]
        raise RuntimeError(str(error.get("message") if isinstance(error, dict) else error))
    choices = payload.get("choices")
    if choices == []:  # Optional streaming usage event.
        return None
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise RuntimeError("LM Studio structured chat response contained no single choice.")
    choice = choices[0]
    reason = choice.get("finish_reason")
    if reason not in (None, "stop"):
        raise RuntimeError(f"LM Studio structured chat did not finish normally: {reason}.")
    return choice


def _content(message: Any) -> str:
    if not isinstance(message, dict):
        raise RuntimeError("LM Studio structured chat content was malformed.")
    if message.get("refusal") or message.get("tool_calls"):
        raise RuntimeError("LM Studio structured chat refused or returned a tool call instead of evidence.")
    value = message.get("content")
    if value is None:
        return ""  # Never expose reasoning_content as visual evidence.
    if not isinstance(value, str):
        raise RuntimeError("LM Studio structured chat content was not text.")
    return value


def extract_chat_text(payload: Any) -> str:
    choice = _choice(payload)
    if choice is None or choice.get("finish_reason") != "stop":
        raise RuntimeError("LM Studio structured chat response did not complete successfully.")
    text = _content(choice.get("message")) if choice else ""
    if not text.strip():
        raise RuntimeError("LM Studio structured chat returned no evidence text.")
    return text


def iter_chat_sse(lines: Iterable[bytes | str]) -> Iterable[str]:
    finished = False
    for raw in lines:
        line = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        if not data:
            continue
        try:
            event = json.loads(data)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Malformed LM Studio structured chat stream event.") from exc
        choice = _choice(event)
        if choice is None:
            continue
        text = _content(choice.get("delta", {}))
        if text:
            yield text
        finished = choice.get("finish_reason") == "stop" or finished
    if not finished:
        raise RuntimeError("LM Studio structured chat stream ended before completion.")
