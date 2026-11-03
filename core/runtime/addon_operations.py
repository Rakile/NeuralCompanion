"""Finite addon-runtime operations composed from owned services and legacy ports."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from core.addons.runtime_config_service import (
    AddonRuntimeOperations as _AddonRuntimeOperationsContract,
)
from core.runtime.addon_extensions import AddonRuntimeExtensions
from core.runtime.context import RuntimeContext
from core.runtime_hotkeys import build_replay_chat_session_from_action


class _CollectChatContexts(Protocol):
    def __call__(
        self,
        history: list[Mapping[str, object]],
        *,
        request_kind: str | None = None,
        excluded_addon_ids: Sequence[str] = (),
        document_memory: bool | None = None,
        document_package_id: str | None = None,
    ) -> object: ...


class _SubmitAcceptedTurn(Protocol):
    def __call__(
        self,
        text: str,
        role: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]: ...


class _InterruptSpeech(Protocol):
    def __call__(
        self,
        *,
        reason: str = "",
        cancel_llm_streams: bool = False,
    ) -> Mapping[str, object]: ...


class _Speak(Protocol):
    def __call__(
        self,
        text: str,
        text_iterable: Sequence[str] | None = None,
        voice_path_override: str | None = None,
        runtime_config_override: Mapping[str, object] | None = None,
    ) -> object: ...


class _OrbSelectedText(Protocol):
    def __call__(
        self,
        *,
        image_path: str,
        screen_bounds: Sequence[object] | None = None,
    ) -> str: ...


class _OrbGroundRegion(Protocol):
    def __call__(
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


class _OrbVisualGuidance(Protocol):
    def __call__(
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


class _OrbReleaseVisionModel(Protocol):
    def __call__(
        self,
        *,
        provider_id: str,
        model_id: str,
        base_url: str = "",
        model_handling: str = "parallel_pinned",
    ) -> bool: ...


class _OrbEnsureVisionModel(Protocol):
    def __call__(
        self,
        *,
        provider_id: str,
        model_id: str,
        base_url: str = "",
        model_handling: str = "parallel_pinned",
    ) -> Mapping[str, object]: ...


class _OrbObserveVisual(Protocol):
    def __call__(
        self,
        *,
        image_path: str,
        provider_id: str,
        model_id: str,
        base_url: str = "",
        model_handling: str = "parallel_pinned",
        capture_bounds: Sequence[object] | None = None,
        reaction_scope: str = "gaze",
        target_text: str = "",
        timeout_seconds: float = 15.0,
        cancel_token: object | None = None,
    ) -> Mapping[str, object]: ...


class _OrbEphemeralComment(Protocol):
    def __call__(
        self,
        *,
        selected_text: str,
        behavior_prompt: str,
        response_style_label: str = "Very friendly",
        exclude_from_memory: bool = True,
        mode: str = "select_area_comment",
    ) -> str: ...


class _OrbSubmitProactive(Protocol):
    def __call__(
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


class _OrbSensoryCycle(Protocol):
    def __call__(
        self,
        force: bool = False,
        snapshots_override: object = None,
        priority: bool = False,
        priority_source: str = "",
        trace_id: str = "",
    ) -> object: ...


class _OrbDropGuidance(Protocol):
    def __call__(
        self,
        *,
        image_path: str,
        snapshot_metadata: Mapping[str, object] | None = None,
        response_style_label: str = "Very friendly",
    ) -> Mapping[str, object]: ...


class _GenerateTts(Protocol):
    def __call__(self, text: str, **settings: object) -> object: ...


class _TextChunkLimits(Protocol):
    def __call__(
        self,
        runtime_config: Mapping[str, object] | None = None,
    ) -> tuple[int, int]: ...


class _VisualRequest(Protocol):
    def __call__(
        self,
        prompt: str,
        *,
        source_text: str = "",
        request_id: str | None = None,
        runtime_config_override: Mapping[str, object] | None = None,
        asset_metadata: Mapping[str, object] | None = None,
    ) -> object: ...


class _RefineInstruction(Protocol):
    def __call__(
        self,
        text: str,
        *,
        label: str = "Instruction",
        guidance: str = "",
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class ChatContextRuntimeExtensions:
    ensure_model_ready: Callable[[str, str], object]
    history_snapshot: Callable[[], Sequence[Mapping[str, object]]]
    collect_addon_contexts: _CollectChatContexts
    submit_accepted_turn: _SubmitAcceptedTurn
    snapshot_session: Callable[[], Mapping[str, object]]


@dataclass(frozen=True, slots=True)
class SpeechRuntimeExtensions:
    snapshot: Callable[[], Mapping[str, object]]
    set_paused: Callable[[bool], bool]
    interrupt: _InterruptSpeech
    ensure_ready: Callable[[], bool]
    speak: _Speak


@dataclass(frozen=True, slots=True)
class PushToTalkRuntimeExtensions:
    hotkey: Callable[[], str]
    set_hold: Callable[[bool], object]


@dataclass(frozen=True, slots=True)
class OrbRuntimeExtensions:
    busy_snapshot: Callable[[], Mapping[str, object]]
    extract_selected_text: _OrbSelectedText
    ground_region: _OrbGroundRegion
    generate_visual_guidance: _OrbVisualGuidance
    release_vision_model: _OrbReleaseVisionModel
    ephemeral_comment: _OrbEphemeralComment
    submit_proactive: _OrbSubmitProactive
    run_sensory_cycle: _OrbSensoryCycle
    generate_drop_guidance: _OrbDropGuidance
    format_drop_guidance: Callable[[Mapping[str, object]], str]
    ensure_vision_model: _OrbEnsureVisionModel | None = None
    observe_visual: _OrbObserveVisual | None = None


@dataclass(frozen=True, slots=True)
class AudioStoryTtsRuntimeExtensions:
    text_chunk_limits: _TextChunkLimits
    chunk_text: Callable[[str, int, int], Sequence[str]]
    set_seed: Callable[[int], object]
    generate: _GenerateTts
    save_wav: Callable[[str, object, int], object]
    safe_delete: Callable[[str], object]
    sample_rate: Callable[[int], int]


@dataclass(frozen=True, slots=True)
class AvatarResourceRuntimeExtensions:
    refresh_emotions: Callable[[], object]
    tts_device: Callable[[], str]


@dataclass(frozen=True, slots=True)
class VisualRequestRuntimeExtensions:
    request_generation: _VisualRequest


@dataclass(frozen=True, slots=True)
class PromptRefinementRuntimeExtensions:
    refine: _RefineInstruction


@dataclass(frozen=True, slots=True)
class AddonRuntimeOperations(_AddonRuntimeOperationsContract):
    """Core-owned implementation of the established addon operation contract."""


def _require_accepted(result, operation: str):
    if result.accepted:
        return result.value
    failure = result.failure
    cause = getattr(failure, "cause", None)
    if isinstance(cause, BaseException):
        raise cause
    raise RuntimeError(
        getattr(failure, "message", None)
        or f"Addon runtime operation '{operation}' failed."
    )

def build_addon_runtime_operations(
    context: RuntimeContext,
    extensions: AddonRuntimeExtensions,
) -> AddonRuntimeOperations:
    """Compose the finite addon boundary without exposing either input to UI."""

    if not isinstance(context, RuntimeContext):
        raise TypeError("Addon runtime operations require RuntimeContext.")
    if not isinstance(extensions, AddonRuntimeExtensions):
        raise TypeError("Addon runtime operations require AddonRuntimeExtensions.")

    def update_runtime_config(key, value):
        _require_accepted(
            context.facade.config.update(str(key), value),
            "update_runtime_config",
        )
        return None

    def transcribe_file(path, *, language=None):
        return context.speech_input.transcribe_file(
            str(path),
            language=language,
            raw=True,
            config=context.config.snapshot(),
        )

    def prepare_transcription():
        _require_accepted(context.speech_input.initialize_backend(context.config.snapshot()), "prepare_transcription")
        return True

    return AddonRuntimeOperations(
        provider_config_snapshot=context.config.snapshot,
        provider_capture_selection=context.providers.capture_selection,
        provider_prepare=context.providers.prepare,
        provider_complete=context.providers.complete,
        provider_stream=context.providers.stream,
        provider_apply_generation_fields=context.providers.apply_generation_fields,
        ensure_chat_provider_model_ready=extensions.chat_contexts.ensure_model_ready,
        conversation_history_snapshot=extensions.chat_contexts.history_snapshot,
        collect_addon_chat_contexts=extensions.chat_contexts.collect_addon_contexts,
        submit_accepted_turn=extensions.chat_contexts.submit_accepted_turn,
        speech_snapshot=extensions.speech.snapshot,
        set_speech_paused=extensions.speech.set_paused,
        interrupt_speech=extensions.speech.interrupt,
        ensure_speech_ready=extensions.speech.ensure_ready,
        speak=extensions.speech.speak,
        orb_busy_snapshot=extensions.orb.busy_snapshot,
        orb_extract_selected_text=extensions.orb.extract_selected_text,
        orb_ground_region=extensions.orb.ground_region,
        orb_generate_visual_guidance=extensions.orb.generate_visual_guidance,
        orb_release_vision_model=extensions.orb.release_vision_model,
        orb_ensure_vision_model=extensions.orb.ensure_vision_model,
        orb_observe_visual=extensions.orb.observe_visual,
        orb_conversation_scope=getattr(extensions.orb, 'conversation_scope', None),
        orb_interpret_watch_intent=getattr(extensions.orb, 'interpret_watch_intent', None),
        orb_observe_watch=getattr(extensions.orb, 'observe_watch', None),
        orb_record_communication=getattr(extensions.orb, 'record_communication', None),
        orb_ephemeral_comment=extensions.orb.ephemeral_comment,
        orb_submit_proactive=extensions.orb.submit_proactive,
        orb_run_sensory_cycle=extensions.orb.run_sensory_cycle,
        orb_generate_drop_guidance=extensions.orb.generate_drop_guidance,
        orb_format_drop_guidance=extensions.orb.format_drop_guidance,
        text_chunk_limits=extensions.audio_story_tts.text_chunk_limits,
        chunk_text=extensions.audio_story_tts.chunk_text,
        set_seed=extensions.audio_story_tts.set_seed,
        generate_tts=extensions.audio_story_tts.generate,
        save_wav=extensions.audio_story_tts.save_wav,
        safe_delete=extensions.audio_story_tts.safe_delete,
        tts_sample_rate=extensions.audio_story_tts.sample_rate,
        push_to_talk_hotkey=extensions.push_to_talk.hotkey,
        set_push_to_talk_hold=extensions.push_to_talk.set_hold,
        snapshot_chat_session=extensions.chat_contexts.snapshot_session,
        replayable_chat_entries=context.replay.collect_replayable_chat_entries,
        replayable_chat_messages=context.replay.collect_replayable_chat_messages,
        replayable_assistant_entries=context.replay.collect_replayable_assistant_entries,
        replayable_assistant_messages=context.replay.collect_replayable_assistant_messages,
        build_replay_session_action=build_replay_chat_session_from_action,
        transcribe_file=transcribe_file,
        prepare_transcription=prepare_transcription,
        runtime_config_snapshot=context.config.to_dict,
        update_runtime_config=update_runtime_config,
        avatar_adapter=context.avatar.adapter,
        refresh_avatar_emotions=extensions.avatar_resources.refresh_emotions,
        tts_device=extensions.avatar_resources.tts_device,
        request_visual_reply_generation=extensions.visual_request.request_generation,
        refine_instruction=extensions.prompt_refinement.refine,
    )


__all__ = [
    "AddonRuntimeExtensions",
    "AddonRuntimeOperations",
    "AudioStoryTtsRuntimeExtensions",
    "AvatarResourceRuntimeExtensions",
    "ChatContextRuntimeExtensions",
    "OrbRuntimeExtensions",
    "PromptRefinementRuntimeExtensions",
    "PushToTalkRuntimeExtensions",
    "SpeechRuntimeExtensions",
    "VisualRequestRuntimeExtensions",
    "build_addon_runtime_operations",
]
