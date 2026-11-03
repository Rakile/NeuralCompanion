"""Typed domain owners for addon-runtime extension operations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol
from core.runtime.phone_reply_controls import PhoneReplyControlPort


class ChatContextRuntimeExtensionOwner(Protocol):
    def submit_if_current_and_idle(self, text: str, **kwargs) -> Mapping[str, object]: ...

    def phone_reply_controls(self) -> PhoneReplyControlPort | None: ...

    def ensure_model_ready(self, provider_name: str, model_name: str) -> object: ...

    def history_snapshot(self) -> Sequence[Mapping[str, object]]: ...

    def collect_addon_contexts(
        self,
        history: list[Mapping[str, object]],
        *,
        request_kind: str | None = None,
        excluded_addon_ids: Sequence[str] = (),
        document_memory: bool | None = None,
        document_package_id: str | None = None,
    ) -> object: ...

    def submit_accepted_turn(
        self,
        text: str,
        role: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]: ...

    def snapshot_session(self) -> Mapping[str, object]: ...


class SpeechRuntimeExtensionOwner(Protocol):
    def snapshot(self) -> Mapping[str, object]: ...

    def set_paused(self, paused: bool) -> bool: ...

    def interrupt(
        self,
        *,
        reason: str = "",
        cancel_llm_streams: bool = False,
    ) -> Mapping[str, object]: ...

    def ensure_ready(self) -> bool: ...

    def speak(
        self,
        text: str,
        text_iterable: Sequence[str] | None = None,
        voice_path_override: str | None = None,
        runtime_config_override: Mapping[str, object] | None = None,
        *,
        chess_low_priority: bool = False,
    ) -> object: ...


class PushToTalkRuntimeExtensionOwner(Protocol):
    def hotkey(self) -> str: ...

    def set_hold(self, active: bool) -> object: ...


class OrbRuntimeExtensionOwner(Protocol):
    def conversation_scope(self) -> Mapping[str, object]: ...

    def interpret_watch_intent(self, **kwargs) -> Mapping[str, object]: ...

    def observe_watch(self, **kwargs) -> Mapping[str, object]: ...
    def record_communication(self, **kwargs) -> object: ...

    def busy_snapshot(self) -> Mapping[str, object]: ...

    def extract_selected_text(
        self,
        *,
        image_path: str,
        screen_bounds: Sequence[object] | None = None,
    ) -> str: ...

    def ground_region(
        self,
        *,
        image_path: str,
        provider_id: str,
        model_id: str,
        base_url: str = "",
        model_handling: str = "auto_load",
        capture_bounds: Sequence[object] | None = None,
        gaze_point: Sequence[object] | None = None,
    ) -> Mapping[str, object]: ...

    def generate_visual_guidance(
        self,
        *,
        image_path: str,
        provider_id: str,
        model_id: str,
        base_url: str = "",
        model_handling: str = "auto_load",
        restore_main_model: bool = False,
        reaction_scope: str = "gaze",
    ) -> Mapping[str, object]: ...

    def ensure_vision_model(
        self,
        *,
        provider_id: str,
        model_id: str,
        base_url: str = "",
        model_handling: str = "parallel_pinned",
    ) -> Mapping[str, object]: ...

    def observe_visual(
        self,
        *,
        image_path: str,
        provider_id: str,
        model_id: str,
        base_url: str = "",
        model_handling: str = "parallel_pinned",
        capture_bounds: Sequence[object] | None = None,
        reaction_scope: str = "gaze",
        capability_mode: str = "auto",
        target_text: str = "",
        question_text: str = "",
        timeout_seconds: float = 15.0,
        cancel_token: object | None = None,
        trace_id: str = "",
    ) -> Mapping[str, object]: ...

    def release_vision_model(
        self,
        *,
        provider_id: str,
        model_id: str,
        base_url: str = "",
        model_handling: str = "parallel_pinned",
    ) -> bool: ...

    def ephemeral_comment(
        self,
        *,
        selected_text: str,
        behavior_prompt: str,
        response_style_label: str = "Very friendly",
        exclude_from_memory: bool = True,
        mode: str = "select_area_comment",
    ) -> str: ...

    def submit_proactive(
        self,
        candidate: str,
        *,
        summary: str = "",
        attention: str = "",
        emotion: str = "",
        source: str = "sensory",
        allow_repeated_candidate: bool = False,
        focus_bounds: object = None,
        focus_label: str = "",
        focus_text: str = "",
        focus_duration_seconds: float = 14.0,
        trace_id: str = "",
    ) -> object: ...

    def run_sensory_cycle(
        self,
        force: bool = False,
        snapshots_override: object = None,
        priority: bool = False,
        priority_source: str = "",
        trace_id: str = "",
    ) -> object: ...

    def generate_drop_guidance(
        self,
        *,
        image_path: str,
        snapshot_metadata: Mapping[str, object] | None = None,
        response_style_label: str = "Very friendly",
    ) -> Mapping[str, object]: ...

    def format_drop_guidance(self, guidance: Mapping[str, object]) -> str: ...


class AudioStoryTtsRuntimeExtensionOwner(Protocol):
    def text_chunk_limits(
        self,
        runtime_config: Mapping[str, object] | None = None,
    ) -> tuple[int, int]: ...

    def chunk_text(
        self,
        text: str,
        target_length: int,
        maximum_length: int,
    ) -> Sequence[str]: ...

    def set_seed(self, seed: int) -> object: ...

    def generate(self, text: str, **settings: object) -> object: ...

    def save_wav(self, path: str, wav: object, sample_rate: int) -> object: ...

    def safe_delete(self, path: str) -> object: ...

    def sample_rate(self, default: int) -> int: ...


class AvatarResourceRuntimeExtensionOwner(Protocol):
    def refresh_emotions(self) -> object: ...

    def tts_device(self) -> str: ...


class VisualRequestRuntimeExtensionOwner(Protocol):
    def request_generation(
        self,
        prompt: str,
        *,
        inputs: Sequence[object] = (),
        source_text: str = "",
        request_id: str | None = None,
        runtime_config_override: Mapping[str, object] | None = None,
        asset_metadata: Mapping[str, object] | None = None,
    ) -> object: ...


class PromptRefinementRuntimeExtensionOwner(Protocol):
    def refine_persona(
        self, draft: Mapping[str, object], *, provider_id: str, model_id: str,
        regenerate: bool = False, cancel_token: object | None = None,
    ) -> str: ...

    def refine(
        self,
        text: str,
        *,
        label: str = "Instruction",
        guidance: str = "",
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class AddonRuntimeExtensions:
    """Finite owner set for runtime behavior not yet held by RuntimeContext."""

    chat_contexts: ChatContextRuntimeExtensionOwner
    speech: SpeechRuntimeExtensionOwner
    push_to_talk: PushToTalkRuntimeExtensionOwner
    orb: OrbRuntimeExtensionOwner
    audio_story_tts: AudioStoryTtsRuntimeExtensionOwner
    avatar_resources: AvatarResourceRuntimeExtensionOwner
    visual_request: VisualRequestRuntimeExtensionOwner
    prompt_refinement: PromptRefinementRuntimeExtensionOwner


def build_addon_runtime_extensions(
    *,
    chat_context_owner: ChatContextRuntimeExtensionOwner,
    speech_owner: SpeechRuntimeExtensionOwner,
    push_to_talk_owner: PushToTalkRuntimeExtensionOwner,
    orb_owner: OrbRuntimeExtensionOwner,
    audio_story_tts_owner: AudioStoryTtsRuntimeExtensionOwner,
    avatar_resource_owner: AvatarResourceRuntimeExtensionOwner,
    visual_request_owner: VisualRequestRuntimeExtensionOwner,
    prompt_refinement_owner: PromptRefinementRuntimeExtensionOwner,
) -> AddonRuntimeExtensions:
    """Build the extension boundary from explicit, domain-specific owners."""

    return AddonRuntimeExtensions(
        chat_contexts=chat_context_owner,
        speech=speech_owner,
        push_to_talk=push_to_talk_owner,
        orb=orb_owner,
        audio_story_tts=audio_story_tts_owner,
        avatar_resources=avatar_resource_owner,
        visual_request=visual_request_owner,
        prompt_refinement=prompt_refinement_owner,
    )


__all__ = [
    "AddonRuntimeExtensions",
    "AudioStoryTtsRuntimeExtensionOwner",
    "AvatarResourceRuntimeExtensionOwner",
    "ChatContextRuntimeExtensionOwner",
    "OrbRuntimeExtensionOwner",
    "PromptRefinementRuntimeExtensionOwner",
    "PushToTalkRuntimeExtensionOwner",
    "SpeechRuntimeExtensionOwner",
    "VisualRequestRuntimeExtensionOwner",
    "build_addon_runtime_extensions",
]
