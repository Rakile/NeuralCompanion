"""Production composition for the finite addon-runtime extension boundary."""

from __future__ import annotations

from dataclasses import dataclass

from core.runtime.addon_extensions import (
    AddonRuntimeExtensions,
    AudioStoryTtsRuntimeExtensionOwner,
    AvatarResourceRuntimeExtensionOwner,
    ChatContextRuntimeExtensionOwner,
    OrbRuntimeExtensionOwner,
    PromptRefinementRuntimeExtensionOwner,
    PushToTalkRuntimeExtensionOwner,
    SpeechRuntimeExtensionOwner,
    VisualRequestRuntimeExtensionOwner,
    build_addon_runtime_extensions,
)


@dataclass(frozen=True, slots=True)
class ProductionAddonRuntimeExtensionOwners:
    """Named production owners for addon capabilities outside RuntimeContext."""

    chat_context_owner: ChatContextRuntimeExtensionOwner
    speech_owner: SpeechRuntimeExtensionOwner
    push_to_talk_owner: PushToTalkRuntimeExtensionOwner
    orb_owner: OrbRuntimeExtensionOwner
    audio_story_tts_owner: AudioStoryTtsRuntimeExtensionOwner
    avatar_resource_owner: AvatarResourceRuntimeExtensionOwner
    visual_request_owner: VisualRequestRuntimeExtensionOwner
    prompt_refinement_owner: PromptRefinementRuntimeExtensionOwner


def build_production_addon_runtime_extensions(
    owners: ProductionAddonRuntimeExtensionOwners,
) -> AddonRuntimeExtensions:
    """Compose the production addon boundary from explicit domain owners."""

    if not isinstance(owners, ProductionAddonRuntimeExtensionOwners):
        raise TypeError(
            "Production addon extension composition requires "
            "ProductionAddonRuntimeExtensionOwners."
        )
    return build_addon_runtime_extensions(
        chat_context_owner=owners.chat_context_owner,
        speech_owner=owners.speech_owner,
        push_to_talk_owner=owners.push_to_talk_owner,
        orb_owner=owners.orb_owner,
        audio_story_tts_owner=owners.audio_story_tts_owner,
        avatar_resource_owner=owners.avatar_resource_owner,
        visual_request_owner=owners.visual_request_owner,
        prompt_refinement_owner=owners.prompt_refinement_owner,
    )


__all__ = [
    "ProductionAddonRuntimeExtensionOwners",
    "build_production_addon_runtime_extensions",
]
