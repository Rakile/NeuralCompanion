from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from . import structured_models


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


def generate_structured_output(
    *,
    engine: Any,
    params: dict[str, Any],
    response_model: Any,
    max_retries: int = 2,
    logger: Any = None,
) -> dict[str, Any] | None:
    """Run an optional Instructor non-streaming request through NC's active chat client."""
    availability = instructor_availability()
    if not availability.available:
        _log_debug(logger, "MPRC Instructor unavailable: %s", availability.reason)
        return None
    if response_model is None:
        _log_debug(logger, "MPRC Instructor skipped: response model unavailable.")
        return None
    try:
        import instructor  # type: ignore

        client_factory = getattr(engine, "_chat_client", None)
        if not callable(client_factory):
            _log_debug(logger, "MPRC Instructor skipped: active engine chat client is unavailable.")
            return None
        client = client_factory()
        if client is None:
            _log_debug(logger, "MPRC Instructor skipped: active engine chat client returned None.")
            return None
        instructor_client = _wrap_client(instructor, client)
        if instructor_client is None:
            _log_debug(logger, "MPRC Instructor skipped: Instructor could not wrap the active chat client.")
            return None
        kwargs = _create_kwargs(params)
        if not kwargs.get("model") or not kwargs.get("messages"):
            _log_debug(logger, "MPRC Instructor skipped: missing model or messages.")
            return None
        kwargs["response_model"] = response_model
        kwargs["max_retries"] = max(0, min(3, int(max_retries)))
        result = _call_instructor_client(instructor_client, kwargs)
        payload = structured_models.model_to_dict(result)
        return payload if payload else None
    except Exception as exc:
        _log_debug(logger, "MPRC Instructor structured request skipped: %s", exc)
        return None


def _wrap_client(instructor_module: Any, client: Any) -> Any:
    mode_type = getattr(instructor_module, "Mode", None)
    compatibility_mode = getattr(mode_type, "MD_JSON", None)
    if compatibility_mode is None:
        return None
    for name in ("from_openai", "patch"):
        wrapper = getattr(instructor_module, name, None)
        if not callable(wrapper):
            continue
        try:
            return wrapper(client, mode=compatibility_mode)
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
    if "messages" in kwargs:
        kwargs["messages"] = deepcopy(kwargs["messages"])
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
    "generate_structured_output",
    "instructor_availability",
]
