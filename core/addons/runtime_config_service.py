from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable


RuntimeOperation = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class AddonRuntimeOperations:
    """Exact host-owned operations needed by addon-facing Qt services."""

    provider_config_snapshot: RuntimeOperation
    provider_capture_selection: RuntimeOperation
    provider_prepare: RuntimeOperation
    provider_complete: RuntimeOperation
    ensure_chat_provider_model_ready: RuntimeOperation
    conversation_history_snapshot: RuntimeOperation
    collect_addon_chat_contexts: RuntimeOperation
    submit_accepted_turn: RuntimeOperation
    speech_snapshot: RuntimeOperation
    set_speech_paused: RuntimeOperation
    interrupt_speech: RuntimeOperation
    ensure_speech_ready: RuntimeOperation
    speak: RuntimeOperation
    orb_busy_snapshot: RuntimeOperation
    orb_extract_selected_text: RuntimeOperation
    orb_ground_region: RuntimeOperation
    orb_generate_visual_guidance: RuntimeOperation
    orb_release_vision_model: RuntimeOperation
    orb_ephemeral_comment: RuntimeOperation
    orb_submit_proactive: RuntimeOperation
    orb_run_sensory_cycle: RuntimeOperation
    orb_generate_drop_guidance: RuntimeOperation
    orb_format_drop_guidance: RuntimeOperation
    text_chunk_limits: RuntimeOperation
    chunk_text: RuntimeOperation
    set_seed: RuntimeOperation
    generate_tts: RuntimeOperation
    save_wav: RuntimeOperation
    safe_delete: RuntimeOperation
    tts_sample_rate: RuntimeOperation
    push_to_talk_hotkey: RuntimeOperation
    set_push_to_talk_hold: RuntimeOperation
    snapshot_chat_session: RuntimeOperation
    replayable_chat_entries: RuntimeOperation
    replayable_chat_messages: RuntimeOperation
    replayable_assistant_entries: RuntimeOperation
    replayable_assistant_messages: RuntimeOperation
    build_replay_session_action: RuntimeOperation
    transcribe_file: RuntimeOperation
    runtime_config_snapshot: RuntimeOperation
    update_runtime_config: RuntimeOperation
    avatar_adapter: RuntimeOperation
    refresh_avatar_emotions: RuntimeOperation
    tts_device: RuntimeOperation
    request_visual_reply_generation: RuntimeOperation
    refine_instruction: RuntimeOperation
    provider_stream: RuntimeOperation | None = None
    provider_apply_generation_fields: RuntimeOperation | None = None
    orb_ensure_vision_model: RuntimeOperation | None = None
    orb_observe_visual: RuntimeOperation | None = None
    orb_conversation_scope: RuntimeOperation | None = None
    orb_interpret_watch_intent: RuntimeOperation | None = None
    orb_observe_watch: RuntimeOperation | None = None
    orb_record_communication: RuntimeOperation | None = None
    prepare_transcription: RuntimeOperation | None = None


def addon_runtime_operations(window) -> AddonRuntimeOperations:
    operations = window._addon_runtime_operations
    if not isinstance(operations, AddonRuntimeOperations):
        raise TypeError("Host did not install finite addon runtime operations.")
    return operations


class RuntimeConfigService:
    """Presentation-neutral addon runtime configuration capabilities."""

    __slots__ = (
        "__snapshot",
        "__update",
        "__avatar_adapter",
        "__refresh_avatar_emotions",
        "__tts_device",
        "__request_visual_reply_generation",
    )

    def __init__(self, window) -> None:
        operations = addon_runtime_operations(window)
        self.__snapshot = operations.runtime_config_snapshot
        self.__update = operations.update_runtime_config
        self.__avatar_adapter = operations.avatar_adapter
        self.__refresh_avatar_emotions = operations.refresh_avatar_emotions
        self.__tts_device = operations.tts_device
        self.__request_visual_reply_generation = operations.request_visual_reply_generation

    def snapshot(self) -> dict:
        return dict(self.__snapshot() or {})

    def get(self, key, default=None):
        return self.snapshot().get(str(key), default)

    def set(self, key, value):
        return self.update(str(key), value)

    def update(self, key, value):
        return self.__update(str(key), value)

    def avatar_adapter(self):
        return self.__avatar_adapter()

    def refresh_avatar_emotions(self) -> None:
        self.__refresh_avatar_emotions()

    def tts_device(self) -> str:
        return str(self.__tts_device() or "cpu")

    def request_visual_reply_generation(
        self,
        prompt: str,
        *,
        inputs=(),
        source_text: str = "",
        request_id: str | None = None,
        runtime_config=None,
        asset_metadata: Mapping[str, object] | None = None,
    ) -> bool:
        request_kwargs = {
            "source_text": str(source_text or ""),
            "request_id": request_id,
            "runtime_config_override": dict(runtime_config or {}),
        }
        if inputs:
            request_kwargs["inputs"] = tuple(inputs)
        if asset_metadata:
            request_kwargs["asset_metadata"] = dict(asset_metadata)
        return bool(
            self.__request_visual_reply_generation(
                str(prompt or ""),
                **request_kwargs,
            )
        )


# Transitional source compatibility for non-production callers. Production
# native-QML code imports RuntimeConfigService directly.
QtRuntimeConfigService = RuntimeConfigService
