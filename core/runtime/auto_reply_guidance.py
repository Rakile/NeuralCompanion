"""Validated, turn-local Auto-Reply direction; never persona or history content."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def guidance_strength_instruction(strength: int) -> str:
    """Instruction priority, not sampling temperature or a compliance guarantee."""
    if strength == 0:
        policy = "Story led: ignore custom direction; follow the current scene and story plan."
    elif strength <= 25:
        policy = "Gentle: introduce the user's direction gradually when it fits the current beat."
    elif strength <= 60:
        policy = "Balanced: apply the user's direction in the next reply while keeping the current beat on track."
    elif strength < 100:
        policy = "Strong: prioritize the user's direction in the next reply; adapt conflicting planned events."
    else:
        policy = "Director: follow the user's direction immediately; adapt conflicting story beats and pacing."
    return (f"Guidance strength: {strength}%. {policy} Preserve established facts, character identity, "
            "and higher-priority system instructions. Do not wait for a beat change to apply new direction.")


def normalize_auto_reply_guidance(value: object) -> dict[str, Any] | None:
    required = {"guidance", "example_response"}
    if (not isinstance(value, Mapping) or not required <= set(value)
            or set(value) - required - {"strength", "user_guidance"}):
        return None
    result: dict[str, Any] = {}
    for field, limit in (("guidance", 2000), ("example_response", 4000)):
        text = value.get(field)
        if type(text) is not str or not 1 <= len(text.strip()) <= limit:
            return None
        result[field] = text.strip()
    if "strength" in value:
        strength = value["strength"]
        if type(strength) is not int or not 0 <= strength <= 100:
            return None
        result["strength"] = strength
    if "user_guidance" in value:
        text = value["user_guidance"]
        if type(text) is not str or len(text) > 8000:
            return None
        result["user_guidance"] = text.strip()
    return result


def auto_reply_prompt_text(value: object) -> str:
    direction = normalize_auto_reply_guidance(value)
    if direction is None:
        return ""
    priority = ""
    if "strength" in direction:
        priority = guidance_strength_instruction(direction["strength"]) + "\n\n"
        if direction["strength"] > 0 and direction.get("user_guidance"):
            priority += "Latest user direction:\n" + direction["user_guidance"] + "\n\n"
    return (
        "Auto-Reply direction for this response only. Apply it to the following user message, "
        "while following the active persona and system instructions. "
        "The example is an illustrative possible assistant answer, not established events "
        "or dialogue that already happened. Adapt it to the conversation; do not repeat "
        "these labels or discuss the guidance in your reply.\n\n"
        "Continue from the latest established event. Respond to the user's contribution with "
        "a new action, consequence or answer; do not paraphrase it back as the main scene. "
        "Do not replay completed actions or repackage earlier reflections in new wording. "
        "If the example or planned beat repeats an established event, use its consequences "
        "instead, while respecting the user's requested pacing.\n\n"
        + priority + "Guidance:\n" + direction["guidance"] + "\n\n"
        "Example response (illustrative):\n" + direction["example_response"]
    )
