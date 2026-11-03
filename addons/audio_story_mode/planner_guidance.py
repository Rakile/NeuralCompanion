from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol


class InstructorAvailabilityLike(Protocol):
    available: bool
    module_version: str


_PROVIDER_LABELS = {
    "openai": "OpenAI",
    "runware": "Runware",
    "xai": "xAI / Grok",
}


def instructor_status_text(availability: InstructorAvailabilityLike) -> str:
    """Describe validation availability without implying planner failure."""

    if bool(availability.available):
        version = str(availability.module_version or "").strip()
        version_text = f" {version}" if version else ""
        return (
            f"Instructor{version_text} validation is available. "
            "The selected LLM performs the story reasoning."
        )
    return (
        "Normal LLM scene analysis is active. "
        "Instructor validation is unavailable."
    )


def image_provider_continuity_text(generation_info: Mapping) -> str:
    """Describe the active provider's Audio Story continuity capability."""

    provider = str(generation_info.get("provider") or "").strip().lower()
    if not provider:
        return (
            "No active image provider detected. Configure Visual Reply before "
            "generating story images."
        )

    label = _PROVIDER_LABELS.get(provider, provider.replace("_", " ").title())
    if not bool(generation_info.get("generation_available")):
        return (
            f"Active image provider: {label}, but image generation is unavailable. "
            "Check the Visual Reply provider configuration."
        )
    if provider == "openai":
        return (
            "Active image provider: OpenAI. Reference-image continuity is available "
            "for recurring characters and locations."
        )
    return (
        f"Active image provider: {label}. Audio Story generates each image fresh "
        "with this provider. Story Bible and the master prompt improve consistency, "
        "but exact identity reuse is unavailable."
    )
