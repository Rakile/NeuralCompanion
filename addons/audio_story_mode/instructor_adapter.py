from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from addons.audio_story_mode import structured_models


@dataclass(frozen=True)
class InstructorAvailability:
    available: bool
    reason: str = ""
    module_version: str = ""


def instructor_availability() -> InstructorAvailability:
    try:
        import instructor  # type: ignore
    except Exception as exc:
        return InstructorAvailability(False, f"Instructor is unavailable: {exc}")
    if not structured_models.PYDANTIC_AVAILABLE:
        return InstructorAvailability(False, "Pydantic is unavailable.")
    return InstructorAvailability(
        True,
        "",
        str(getattr(instructor, "__version__", "") or ""),
    )


def _request_kwargs(params: dict[str, Any]) -> dict[str, Any]:
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
    return {
        key: deepcopy(value)
        for key, value in dict(params or {}).items()
        if key in allowed and value is not None
    }


def _create(wrapped_client: Any, kwargs: dict[str, Any]) -> Any:
    create = getattr(wrapped_client, "create", None)
    if callable(create):
        return create(**kwargs)
    chat = getattr(wrapped_client, "chat", None)
    completions = getattr(chat, "completions", None) if chat is not None else None
    create = getattr(completions, "create", None) if completions is not None else None
    if not callable(create):
        raise RuntimeError("Instructor client has no supported create method.")
    return create(**kwargs)


def generate_story_beats(
    *,
    provider: str,
    params: dict[str, Any],
    provider_execution: Any,
    logger: Any = None,
) -> dict[str, Any] | None:
    availability = instructor_availability()
    if (
        not availability.available
        or structured_models.StoryBeatAnalysis is None
    ):
        return None
    try:
        if provider_execution is None:
            return None
    except Exception as exc:
        _log_debug(logger, "Audio Story Instructor client unavailable: %s", exc)
        return None
    kwargs = _request_kwargs(params)
    if not kwargs.get("model") or not kwargs.get("messages"):
        return None
    kwargs["response_format"] = {"type": "json_object"}
    try:
        return provider_execution.structured_complete(
            kwargs,
            structured_models.StoryBeatAnalysis,
            provider_id=str(provider or "").strip(),
            model_id=str(kwargs.get("model") or ""),
        )
    except Exception as exc:
        _log_debug(logger, "Audio Story structured request failed: %s", exc)
        return None


def _log_debug(logger: Any, message: str, *args: Any) -> None:
    if logger is None:
        return
    writer = getattr(logger, "debug", None)
    if callable(writer):
        try:
            writer(message, *args)
        except Exception:
            pass


__all__ = [
    "InstructorAvailability",
    "generate_story_beats",
    "instructor_availability",
]
