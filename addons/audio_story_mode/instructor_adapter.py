from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

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
    client_factory: Callable[[str], Any],
    logger: Any = None,
) -> dict[str, Any] | None:
    availability = instructor_availability()
    if (
        not availability.available
        or structured_models.StoryBeatAnalysis is None
    ):
        return None
    try:
        import instructor  # type: ignore

        base_client = client_factory(str(provider or "").strip())
    except Exception as exc:
        _log_debug(logger, "Audio Story Instructor client unavailable: %s", exc)
        return None
    kwargs = _request_kwargs(params)
    if not kwargs.get("model") or not kwargs.get("messages"):
        return None
    kwargs["response_model"] = structured_models.StoryBeatAnalysis
    kwargs["max_retries"] = 2
    mode_type = getattr(instructor, "Mode", None)
    for mode_name in ("JSON", "MD_JSON"):
        mode = getattr(mode_type, mode_name, None)
        if mode is None:
            continue
        wrapper = getattr(instructor, "from_openai", None)
        if not callable(wrapper):
            wrapper = getattr(instructor, "patch", None)
        if not callable(wrapper):
            continue
        try:
            wrapped_client = wrapper(base_client, mode=mode)
            result = _create(wrapped_client, kwargs)
            payload = structured_models.model_to_dict(result)
            if payload:
                return payload
        except Exception as exc:
            _log_debug(
                logger,
                "Audio Story Instructor %s mode failed: %s",
                mode_name,
                exc,
            )
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
