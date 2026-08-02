from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .models import (
    DEFAULT_ADULT_NSFW_PROMPT,
    DEFAULT_NORMAL_INTIMACY_PROMPT,
    DEFAULT_SYSTEM_OVERRIDE_PROMPT,
    BuddyPersona,
    BuddySettings,
)


PARTICIPATION_MODES = ("focused", "balanced", "lively")
WIZARD_TRAITS = (
    "practical",
    "warm",
    "playful",
    "expressive",
    "honest",
    "creative",
    "flirtatious",
)


@dataclass(frozen=True)
class GroupBehavior:
    max_speakers: int
    allow_buddy_to_buddy: bool
    natural_second_speaker_every: int
    forced_buddy_every: int = 0


@dataclass
class BuddySetupPreview:
    setup_id: str
    title: str
    summary: str
    personas: list[BuddyPersona] = field(default_factory=list)
    group_behavior: GroupBehavior = field(
        default_factory=lambda: GroupBehavior(1, True, 0)
    )
    adult_ready: bool = False
    system_override_prompt: str | None = None
    normal_intimacy_prompt: str | None = None
    adult_nsfw_prompt: str | None = None


@dataclass(frozen=True)
class WizardChoices:
    buddy_count: int
    participation: str
    traits: tuple[str, ...]

    def normalized(self) -> "WizardChoices":
        count = max(1, min(3, int(self.buddy_count or 1)))
        participation = (
            self.participation
            if self.participation in PARTICIPATION_MODES
            else "balanced"
        )
        traits = tuple(
            item for item in self.traits if item in WIZARD_TRAITS
        )
        return WizardChoices(
            count,
            participation,
            tuple(dict.fromkeys(traits)),
        )


def apply_setup_preview(
    current: BuddySettings,
    preview: BuddySetupPreview,
) -> BuddySettings:
    updated = BuddySettings.from_dict(copy.deepcopy(current.to_dict()))
    updated.personas = [
        BuddyPersona.from_dict(copy.deepcopy(persona.to_dict()))
        for persona in preview.personas
    ]
    updated.max_speakers = int(preview.group_behavior.max_speakers)
    updated.allow_buddy_to_buddy = bool(
        preview.group_behavior.allow_buddy_to_buddy
    )
    updated.natural_second_speaker_every = int(
        preview.group_behavior.natural_second_speaker_every
    )
    updated.forced_buddy_every = int(
        preview.group_behavior.forced_buddy_every
    )
    updated.active_setup_id = str(preview.setup_id or "").strip()
    if preview.system_override_prompt is not None:
        updated.system_override_prompt = (
            str(preview.system_override_prompt or "").strip()
            or DEFAULT_SYSTEM_OVERRIDE_PROMPT
        )
    if preview.normal_intimacy_prompt is not None:
        updated.normal_intimacy_prompt = (
            str(preview.normal_intimacy_prompt or "").strip()
            or DEFAULT_NORMAL_INTIMACY_PROMPT
        )
    if preview.adult_nsfw_prompt is not None:
        updated.adult_nsfw_prompt = (
            str(preview.adult_nsfw_prompt or "").strip()
            or DEFAULT_ADULT_NSFW_PROMPT
        )
    return updated


__all__ = [
    "apply_setup_preview",
    "BuddySetupPreview",
    "GroupBehavior",
    "PARTICIPATION_MODES",
    "WIZARD_TRAITS",
    "WizardChoices",
]
