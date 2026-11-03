"""Concrete production owners for the finite addon extension boundary."""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast
from urllib.parse import urlsplit, urlunsplit

from core import orb_reading as reading_actions
from core import (
    companion_orb_vision_debug,
    lmstudio_runtime,
    runtime_files,
    runtime_hotkeys,
    text_chunking,
)
from core.runtime.production_addon_extensions import (
    ProductionAddonRuntimeExtensionOwners,
)
from core.runtime.prompt_tasks import (
    PromptTaskService,
    format_companion_orb_drop_guidance,
    format_companion_orb_visual_guidance,
)
from core.runtime.turns import TurnTerminalStatus, UserInput
from core.runtime.phone_reply_controls import PhoneReplyControlPort
from core.runtime.identifiers import WorkLease

if TYPE_CHECKING:
    from core.conversation_flow_v2 import WaitFlagPort
    from core.runtime.avatar import AvatarService
    from core.runtime.config import RuntimeConfigService
    from core.runtime.conversation import ConversationService
    from core.runtime.conversation_owners import (
        ConversationSessionRuntimeOwner,
        UserImageRuntimeOwner,
    )
    from core.runtime.normal_chat import NormalChatApplicationAdapter
    from core.runtime.playback import PlaybackReceipt, PlaybackService
    from core.runtime.production_speech import ProductionSpeechOutputOwner
    from core.runtime.providers import ProviderService
    from core.runtime.sensory import SensoryService
    from core.runtime.speech_input import SpeechInputService
    from core.runtime.turns import TurnCoordinator, TurnSnapshot
    from core.runtime.visual import VisualService


class AddonChatContextCollector(Protocol):
    """Collect normalized addon prompt contributions for one chat window."""

    def collect_addon_contexts(
        self,
        history: list[Mapping[str, object]],
        *,
        request_kind: str | None = None,
        excluded_addon_ids: Sequence[str] = (),
        document_memory: bool | None = None,
        document_package_id: str | None = None,
    ) -> object: ...


class ChatSessionSnapshotOwner(Protocol):
    def snapshot_session(self) -> Mapping[str, object]: ...


class SpeechModelResource(Protocol):
    def ready(self) -> bool: ...

    def ensure_ready(self) -> bool: ...


class AddonSpeechControl(Protocol):
    """Completion surface required to release a transient addon-speech turn."""

    done: WaitFlagPort

    def playback_receipt(self) -> PlaybackReceipt | None: ...


class PushToTalkHoldOwner(Protocol):
    def set_hold(self, active: bool) -> object: ...


class ProviderActivityOwner(Protocol):
    def active(self) -> bool: ...

    def begin_request(self) -> None: ...

    def end_request(self) -> None: ...


class CompanionOrbContextualReplyOwner(Protocol):
    """Typed Buddy/Orb handoff without exposing addon capability dispatch."""

    def maybe_reply(
        self,
        payload: Mapping[str, object],
    ) -> Mapping[str, object] | None: ...

    def record_reply(self, text: str, *, source: str) -> None: ...


class AudioStoryTtsResourceOwner(Protocol):
    """Finite access to the selected TTS adapter and WAV persistence."""

    def set_seed(self, seed: int) -> object: ...

    def generate(self, text: str, **settings: object) -> object: ...

    def save_wav(self, path: str, wav: object, sample_rate: int) -> object: ...

    def sample_rate(self, default: int) -> int: ...


class AvatarEmotionResourceOwner(Protocol):
    def refresh_emotions(self) -> object: ...

    def tts_device(self) -> str: ...


class _ProviderPromptRunner:
    __slots__ = ("_config", "_prompt_tasks", "_providers")

    def __init__(
        self,
        *,
        config: RuntimeConfigService,
        providers: ProviderService,
        prompt_tasks: PromptTaskService,
    ) -> None:
        self._config = config
        self._providers = providers
        self._prompt_tasks = prompt_tasks

    @property
    def tasks(self) -> PromptTaskService:
        return self._prompt_tasks

    def capture(
        self,
        *,
        provider_id: str | None = None,
        model_id: str | None = None,
        base_url: str = "",
    ):
        snapshot = self._config.snapshot()
        normalized_base_url = str(base_url or "").strip()
        selection = self._providers.capture_selection(
            snapshot,
            provider_id=provider_id,
            model_id=model_id,
            provider_config_override=(
                {
                    "base_url": normalized_base_url,
                    "provider_is_remote": not lmstudio_runtime.is_local_base_url(
                        normalized_base_url
                    ),
                }
                if normalized_base_url
                else None
            ),
        )
        return selection, self._providers.readiness(selection)

    def generation_fields(self, selection):
        def apply(
            params: dict[str, object],
            additional_params: dict[str, object],
        ) -> None:
            self._providers.apply_generation_fields(
                selection,
                params,
                additional_params,
            )

        return apply

    def catalog_supports_images(self, selection) -> bool | None:
        """Return the provider catalog's explicit image capability when available."""

        try:
            catalog = self._providers.list_models(
                str(selection.provider_id or ""),
                quiet=True,
            )
        except Exception:
            return None
        selected_model = str(selection.model_id or "").strip()
        for item in catalog:
            if isinstance(item, Mapping):
                model_id = str(
                    item.get("id") or item.get("model") or item.get("name") or ""
                ).strip()
                if model_id != selected_model:
                    continue
                if "supports_images" not in item:
                    return None
                return bool(item.get("supports_images"))
            if str(item or "").strip() == selected_model:
                return None
        return None

    def complete(
        self,
        selection,
        request,
        *,
        reason: str,
        prepare_model: bool = True,
        require_frozen_execution: bool = False,
        timeout_seconds: float | None = None,
        cancel_token: object | None = None,
    ) -> str:
        execution_options: dict[str, object] = {}
        if timeout_seconds is not None:
            execution_options["timeout_seconds"] = float(timeout_seconds)
        if cancel_token is not None:
            execution_options["token"] = cancel_token
        return str(
            self._providers.complete_prompt_request(
                selection,
                request,
                reason=str(reason),
                prepare_model=bool(prepare_model),
                prefer_frozen_execution=bool(require_frozen_execution),
                allow_legacy_fallback=not bool(require_frozen_execution),
                **execution_options,
            )
            or ""
        )

    def stream(
        self,
        selection,
        request,
        *,
        reason: str,
        timeout_seconds: float,
        cancel_token: object,
    ):
        return self._providers.stream_prompt_request(
            selection,
            request,
            cancel_token,
            reason=str(reason),
            timeout_seconds=float(timeout_seconds),
            prefer_frozen_execution=True,
            allow_legacy_fallback=False,
            prepare_model=False,
        )

    def preserved_snapshot(self, selection, *, owner: str) -> Mapping[str, object]:
        return self._providers.preserved_auxiliary_selection_snapshot(
            selection,
            owner=str(owner or ""),
        )

    def residency_snapshot(self, selection) -> Mapping[str, object]:
        return self._providers.model_residency_snapshot(selection)

    def adopt_loaded_auxiliary(self, selection, *, owner: str) -> bool:
        return bool(
            self._providers.adopt_loaded_auxiliary_selection_model(
                selection,
                owner=str(owner or ""),
            )
        )

    def prepare_auxiliary(
        self,
        selection,
        *,
        reason: str,
        model_handling: str,
        owner: str = "",
    ) -> bool:
        return bool(
            self._providers.prepare_auxiliary_selection_model(
                selection,
                reason=str(reason),
                model_handling=str(model_handling or ""),
                owner=str(owner or ""),
            )
        )

    def release_auxiliary(
        self,
        selection,
        *,
        reason: str,
        owner: str,
    ) -> bool:
        return bool(
            self._providers.release_preserved_auxiliary_selection_model(
                selection,
                reason=str(reason),
                owner=str(owner or ""),
            )
        )

    def ensure_ready(self, selection, *, reason: str) -> bool:
        return bool(
            self._providers.ensure_selection_model_ready(
                selection,
                reason=str(reason),
            )
        )


class ProductionChatContextRuntimeExtensionOwner:
    """Own addon chat queries and the production typed-input queue."""

    __slots__ = (
        "_addon_contexts",
        "_config",
        "_conversation",
        "_normal_chat",
        "_providers",
        "_session",
        "_session_exporter",
        "_user_images",
        "_phone_reply_controls",
        "_conditional_input",
    )

    def __init__(
        self,
        *,
        config: RuntimeConfigService,
        providers: ProviderService,
        conversation: ConversationService,
        normal_chat: NormalChatApplicationAdapter,
        session: ConversationSessionRuntimeOwner,
        user_images: UserImageRuntimeOwner,
        addon_contexts: AddonChatContextCollector,
        session_exporter: ChatSessionSnapshotOwner,
    ) -> None:
        self._config = config
        self._providers = providers
        self._conversation = conversation
        self._normal_chat = normal_chat
        self._session = session
        self._user_images = user_images
        self._addon_contexts = addon_contexts
        self._session_exporter = session_exporter
        self._phone_reply_controls = None
        from core.runtime.conditional_input import ConditionalInputAdmission
        self._conditional_input = ConditionalInputAdmission(conversation, session, normal_chat)

    def submit_if_current_and_idle(self, text: str, **kwargs) -> Mapping[str, object]:
        return self._conditional_input.submit(text, **kwargs)

    def stage_continuous_next(self, proposed_user, binding, cancellation) -> str | None:
        from core.runtime.continuous_next_reply import ContinuousStageBinding
        try:
            frozen = ContinuousStageBinding(**dict(binding))
        except (TypeError, ValueError, KeyError):
            return None
        stage = self._normal_chat.stage_continuous_next(
            dict(proposed_user), frozen, cancellation)
        return stage.stage_id if stage is not None else None

    def bind_phone_reply_controls(self, port: PhoneReplyControlPort) -> None:
        self._phone_reply_controls = port

    def phone_reply_controls(self) -> PhoneReplyControlPort | None:
        return self._phone_reply_controls

    def ensure_model_ready(self, provider_name: str, model_name: str) -> object:
        selection = self._providers.capture_selection(
            self._config.snapshot(),
            provider_id=str(provider_name or ""),
            model_id=str(model_name or ""),
        )
        return self._providers.ensure_selection_model_ready(
            selection,
            reason="addon chat provider request",
        )

    def history_snapshot(self) -> Sequence[Mapping[str, object]]:
        return tuple(
            dict(message)
            for message in self._conversation.message_mappings()
            if isinstance(message, Mapping)
        )

    def collect_addon_contexts(
        self,
        history: list[Mapping[str, object]],
        *,
        request_kind: str | None = None,
        excluded_addon_ids: Sequence[str] = (),
        document_memory: bool | None = None,
        document_package_id: str | None = None,
    ) -> object:
        return self._addon_contexts.collect_addon_contexts(
            [dict(message) for message in history],
            request_kind=request_kind,
            excluded_addon_ids=tuple(excluded_addon_ids or ()),
            **({"document_memory": document_memory} if document_memory is not None else {}),
            **({"document_package_id": document_package_id} if document_package_id else {}),
        )

    def submit_accepted_turn(
        self,
        text: str,
        role: str | None = None,
        metadata: Mapping[str, object] | None = None,
        *,
        expected_history_revision: int | None = None,
        source_lease: WorkLease | None = None,
    ) -> Mapping[str, object]:
        content = str(text or "").strip()
        if not content:
            return {"queued": False, "reason": "empty"}
        configured_role = self._config.snapshot().values.get(
            "input_message_role",
            "user",
        )
        input_role = str(role or configured_role or "user").strip().lower()
        if input_role not in {"user", "system", "assistant"}:
            input_role = "user"
        turn: dict[str, object] = {
            "role": input_role,
            "content": content,
            "origin": "input",
        }
        turn_metadata = dict(metadata or {})
        capture_id = _remote_capture_id(turn_metadata.get("remote_capture_id"))
        if capture_id:
            turn["remote_capture_id"] = capture_id
        if turn_metadata.get("phone_reply_control") is True:
            turn["phone_reply_control"] = True
            if capture_id and turn_metadata.get("phone_shared_queue") is True:
                turn["phone_shared_queue"] = True
        raw_output_token_cap = turn_metadata.get("normal_chat_output_token_cap")
        if raw_output_token_cap is not None and not isinstance(
            raw_output_token_cap,
            bool,
        ):
            try:
                output_token_cap = int(raw_output_token_cap)
            except (TypeError, ValueError, OverflowError):
                output_token_cap = 0
            if output_token_cap > 0:
                turn["normal_chat_output_token_cap"] = min(
                    output_token_cap,
                    131_072,
                )
        response_guidance = str(
            turn_metadata.get("companion_orb_response_guidance", "") or ""
        ).strip()
        if response_guidance:
            turn["companion_orb_response_guidance"] = response_guidance[:1400]
        debug_trace_id = _remote_capture_id(
            turn_metadata.get("companion_orb_debug_trace_id")
        )
        if debug_trace_id:
            turn["companion_orb_debug_trace_id"] = debug_trace_id
        skip_image_attachment = bool(
            turn_metadata.get("nc_skip_image_attachment", False)
        )
        if expected_history_revision is not None:
            # Phone resolution has no new image acquisition. A failed CAS must
            # not consume or clear desktop pending user images.
            try:
                turn = dict(self._normal_chat.begin(
                    turn, expected_history_revision=expected_history_revision,
                    source_lease=source_lease))
            except RuntimeError:
                return {"queued": False, "reason": "stale"}
            self._session.stage_pending_loaded_input_turn(turn)
            self._session.request_chat_view_rebuild()
            return {"queued": True, "role": input_role, "content": content}
        if (
            input_role != "user"
            and self._user_images.pending_user_image_attachment()
        ):
            self._user_images.clear_pending_user_image_attachment()
        if not skip_image_attachment:
            self._user_images.maybe_arm_screen_image_for_user_turn(turn)
            turn = dict(self._user_images.attach_pending_user_image_to_turn(turn))
        turn = dict(self._normal_chat.begin(turn))
        self._session.stage_pending_loaded_input_turn(turn)
        self._session.request_chat_view_rebuild()
        return {"queued": True, "role": input_role, "content": content}

    def snapshot_session(self) -> Mapping[str, object]:
        return dict(self._session_exporter.snapshot_session())


class ProductionSpeechRuntimeExtensionOwner:
    """Project playback state and route controls through typed speech owners."""

    __slots__ = ("_playback", "_speech_model", "_speech_output", "_turns")

    def __init__(
        self,
        *,
        playback: PlaybackService,
        turns: TurnCoordinator,
        speech_model: SpeechModelResource,
        speech_output: ProductionSpeechOutputOwner,
    ) -> None:
        self._playback = playback
        self._turns = turns
        self._speech_model = speech_model
        self._speech_output = speech_output

    def snapshot(self) -> Mapping[str, object]:
        playback = self._playback.snapshot()
        return {
            "speech_playing": playback.current is not None,
            "speech_paused": bool(playback.paused),
            "ready": bool(self._speech_model.ready()),
        }

    def set_paused(self, paused: bool) -> bool:
        result = self._playback.pause() if paused else self._playback.resume()
        return bool(result.accepted)

    def interrupt(
        self,
        *,
        reason: str = "",
        cancel_llm_streams: bool = False,
    ) -> Mapping[str, object]:
        resolved_reason = str(reason or "interrupt_response")
        invalidated = self._turns.invalidate(
            reason=resolved_reason,
            status=TurnTerminalStatus.CANCELED,
        )
        invalidated_count = (
            len(tuple(invalidated.value or ())) if invalidated.accepted else 0
        )
        if not invalidated_count:
            self._playback.skip()
        del cancel_llm_streams
        return {
            "cancelled_controllers": 0,
            "cancelled_streams": 0,
            "invalidated_turns": invalidated_count,
            "reason": str(reason or ""),
        }

    def ensure_ready(self) -> bool:
        return bool(self._speech_model.ensure_ready())

    def speak(
        self,
        text: str,
        text_iterable: Sequence[str] | None = None,
        voice_path_override: str | None = None,
        runtime_config_override: Mapping[str, object] | None = None,
        *,
        chess_low_priority: bool = False,
    ) -> object:
        content = str(text or "").strip()
        accepted = self._turns.accept(
            UserInput.completed(
                content or "Addon speech output",
                role="system",
                metadata={"transient_effect": "addon_speech"},
                source="addon_speech",
                persist=False,
            )
        )
        if not accepted.accepted or accepted.value is None:
            failure = accepted.failure
            detail = failure.message if failure is not None else "unknown turn failure"
            raise RuntimeError(f"Addon speech turn was not accepted: {detail}")

        snapshot = accepted.value
        try:
            control = cast(
                AddonSpeechControl,
                self._speech_output.speak_async(
                    content,
                    text_iterable=(
                        None
                        if text_iterable is None
                        else tuple(str(item or "") for item in text_iterable)
                    ),
                    voice_path_override=voice_path_override,
                    reply_source_meta={"source": "addon_speech", **({'chess_low_priority': True} if chess_low_priority else {})},
                    runtime_config=(
                        None
                        if runtime_config_override is None
                        else dict(runtime_config_override)
                    ),
                    turn_lease=snapshot.lease,
                ),
            )
        except BaseException:
            self._turns.cancel(
                snapshot.accepted_turn.turn_id,
                "addon_speech_setup_failed",
                lease=snapshot.lease,
            )
            raise

        threading.Thread(
            target=self._finish_transient_speech,
            args=(control, snapshot),
            name="nc-addon-speech-turn",
            daemon=True,
        ).start()
        return control

    def _finish_transient_speech(
        self,
        control: AddonSpeechControl,
        snapshot: TurnSnapshot,
    ) -> None:
        control.done.wait()
        receipt = control.playback_receipt()
        status = (
            TurnTerminalStatus.COMPLETED
            if receipt is not None and receipt.terminal_reason == "completed"
            else TurnTerminalStatus.CANCELED
        )
        self._turns.finish(
            snapshot.accepted_turn.turn_id,
            status,
            lease=snapshot.lease,
        )


class ProductionPushToTalkRuntimeExtensionOwner:
    __slots__ = ("_config", "_hold")

    def __init__(
        self,
        *,
        config: RuntimeConfigService,
        hold: PushToTalkHoldOwner,
    ) -> None:
        self._config = config
        self._hold = hold

    def hotkey(self) -> str:
        values = self._config.snapshot().values
        settings = runtime_hotkeys.normalize_hotkey_settings(
            dict(values.get("hotkeys", {}) or {}),
            legacy_push_to_talk=values.get("push_to_talk_hotkey"),
            legacy_manual=values.get("manual_action_hotkeys"),
            legacy_ui=values.get("ui_action_hotkeys"),
        )
        return str(
            settings.get(
                "push_to_talk",
                runtime_hotkeys.DEFAULT_PUSH_TO_TALK_HOTKEY,
            )
            or runtime_hotkeys.DEFAULT_PUSH_TO_TALK_HOTKEY
        )

    def set_hold(self, active: bool) -> object:
        return self._hold.set_hold(bool(active))


class ProductionOrbRuntimeExtensionOwner:
    """Own synchronous Orb prompts and typed sensory commands."""

    __slots__ = (
        "_clock",
        "_contextual_replies",
        "_conversation",
        "_playback",
        "_prompts",
        "_provider_activity",
        "_sensory",
        "_speech_input",
    )

    def __init__(
        self,
        *,
        config: RuntimeConfigService,
        providers: ProviderService,
        prompt_tasks: PromptTaskService,
        conversation: ConversationService,
        playback: PlaybackService,
        speech_input: SpeechInputService,
        sensory: SensoryService,
        provider_activity: ProviderActivityOwner,
        contextual_replies: CompanionOrbContextualReplyOwner,
        clock=time.time,
    ) -> None:
        self._prompts = _ProviderPromptRunner(
            config=config,
            providers=providers,
            prompt_tasks=prompt_tasks,
        )
        self._conversation = conversation
        self._playback = playback
        self._speech_input = speech_input
        self._sensory = sensory
        self._provider_activity = provider_activity
        self._contextual_replies = contextual_replies
        self._clock = clock

    def conversation_scope(self) -> dict:
        return dict(self._conversation.latest_user_turn_scope())

    def record_communication(self, *, stage, payload, correlation):
        from core.communication_trace import record_to
        try:
            trace = self._provider_activity.communication_trace
        except AttributeError:
            # Older finite host implementations do not expose optional recording.
            return False
        return record_to(trace,stage,payload,correlation)

    def _complete_watch(self, selection, request, *, timeout_seconds, cancel_token, prepare_model):
        if selection.provider_id in {'lmstudio', 'openai'}:
            extra = request.additional_params_copy()
            extra[f'_{selection.provider_id}_structured_output'] = True
            request = type(request).from_payload(request.params_copy(), extra)
        self._provider_activity.begin_request()
        try:
            return self._prompts.complete(selection, request, reason='Companion Orb watch',
                prepare_model=prepare_model, require_frozen_execution=True,
                timeout_seconds=max(1., min(60., float(timeout_seconds))), cancel_token=cancel_token)
        finally:
            self._provider_activity.end_request()

    def interpret_watch_intent(self, *, user_text, recent_dialogue, active_task,
                               timeout_seconds, cancel_token=None) -> dict:
        from addons.companion_orb_overlay.companion_orb.watch_intent import parse_watch_intent, watch_intent_input
        selection, readiness = self._prompts.capture()
        _require_model(readiness, 'interpreting an Orb watch')
        request = self._prompts.tasks.build_companion_orb_watch_intent_request(
            model_id=selection.model_id,
            payload=watch_intent_input(user_text, recent_dialogue, active_task),
            apply_generation_fields=self._prompts.generation_fields(selection))
        from core.communication_trace import correlation_scope, current_correlation
        correlation=dict(current_correlation(),session_key=active_task.get('session_key',''),kind='orb_watch_intent')
        with correlation_scope(correlation):
            raw = self._complete_watch(selection, request, timeout_seconds=timeout_seconds,
                                       cancel_token=cancel_token, prepare_model=True)
        parsed=parse_watch_intent(raw)
        self.record_communication(stage='watch.intent_proposal',payload=parsed,correlation=correlation)
        return parsed

    def observe_watch(self, *, image_path, capture_bounds, task, previous_observation,
                      provider_id, model_id, base_url='', model_handling='auto_load',
                      timeout_seconds=11., cancel_token=None) -> dict:
        from addons.companion_orb_overlay.companion_orb.watch_evidence import normalize_watch_observation
        path = _required_image(image_path, 'Orb watch')
        selection, readiness = self._prompts.capture(provider_id=provider_id,
            model_id=model_id, base_url=_companion_orb_http_base_url(base_url))
        _require_model(readiness, 'observing an Orb watch', require_images=True)
        handling = _companion_orb_model_handling(model_handling)
        if handling != 'already_loaded' and not self._prompts.prepare_auxiliary(selection,
                reason='Companion Orb watch', model_handling=handling,
                owner='companion_orb_vision' if handling == 'parallel_pinned' else ''):
            raise RuntimeError('Orb watch vision model is unavailable.')
        image_content = ()
        if selection.provider_id == 'openai':
            from addons.companion_orb_overlay.companion_orb.watch_images import split_watch_image
            image_content = split_watch_image(path)
        request = self._prompts.tasks.build_companion_orb_watch_observation_request(
            model_id=selection.model_id, image_data_url='' if image_content else _vision_data_url(path),
            image_content=image_content,
            payload=dict(task=task, previous_observation=previous_observation,
                         capture_bounds=list(capture_bounds)),
            apply_generation_fields=self._prompts.generation_fields(selection))
        if selection.provider_id == 'lmstudio' and any(
                row.get('spec', {}).get('version') == 3 for row in task.get('watches', [])):
            # Current-frame observation has its own tested sampling profile; it
            # must not inherit conversational Thinking from the selected model.
            extra = request.additional_params_copy()
            extra['_lmstudio_reasoning_override'] = 'off'
            request = type(request).from_payload(request.params_copy(), extra)
        from core.communication_trace import correlation_scope, current_correlation
        correlation=dict(current_correlation(),session_key=task.get('session_key',''),kind='orb_watch_observation',
            capture_id=task.get('capture_id',''),watch_ids=[r['id'] for r in task.get('watches',[])])
        with correlation_scope(correlation):
            raw = self._complete_watch(selection, request, timeout_seconds=timeout_seconds,
                                       cancel_token=cancel_token, prepare_model=False)
        parsed=normalize_watch_observation(raw, task if task.get('schema_version') == 2 else None)
        self.record_communication(stage='watch.observation',payload=parsed,correlation=correlation)
        return parsed

    def busy_snapshot(self) -> Mapping[str, object]:
        playback = self._playback.snapshot()
        speech_input = self._speech_input.snapshot()
        result = {
            "_llm_request_active": bool(self._provider_activity.active()),
            "audio_playing": playback.current is not None,
            "microphone_active": bool(
                speech_input.active_captures or speech_input.push_to_talk
            ),
        }
        # A bounded, read-only receipt lets the Orb finish its own drop without
        # treating an unrelated global idle/TTS signal as response completion.
        messages = self._conversation.snapshot().messages[-64:]
        completed = {str(m.metadata.get('normal_chat_transaction_id') or '')
                     for m in messages if m.role == 'assistant'} - {''}
        receipts = []
        for message in messages:
            metadata = message.metadata
            if message.role != 'user' or str(metadata.get('normal_chat_transaction_id') or '') not in completed:
                continue
            trace = str(metadata.get('companion_orb_debug_trace_id') or '')
            image = (str(metadata.get('attachment_image_path') or '')
                     if metadata.get('attachment_source') == 'companion_orb' else '')
            if trace or image:
                receipts.append({'trace_id': trace, 'image_path': image})
        if receipts:
            result['orb_completed_responses'] = receipts
        return result

    def extract_selected_text(
        self,
        *,
        image_path: str,
        screen_bounds: Sequence[object] | None = None,
    ) -> str:
        path = _required_image(image_path, "selected-text extraction")
        selection, readiness = self._prompts.capture()
        if not readiness.model_selected:
            return ""
        if (
            not readiness.supports_images
            and self._prompts.catalog_supports_images(selection) is not True
        ):
            return ""
        image_data_url = _data_url(path)
        request = self._prompts.tasks.build_image_text_extraction_request(
            model_id=selection.model_id,
            image_data_url=image_data_url,
            screen_bounds=screen_bounds,
            apply_generation_fields=self._prompts.generation_fields(selection),
        )
        response = self._complete_prompt(
            selection,
            request,
            reason="Companion Orb selected-text extraction",
        )
        return self._prompts.tasks.shape_image_text_extraction_response(response)

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
    ) -> Mapping[str, object]:
        path = _required_image(image_path, "vision grounding")
        normalized_base_url = _companion_orb_http_base_url(base_url)
        handling = _companion_orb_model_handling(model_handling)
        main_selection = None
        if normalized_base_url and handling != "already_loaded":
            main_selection, _main_readiness = self._prompts.capture()
        selection, readiness = self._prompts.capture(
            provider_id=str(provider_id or "").strip(),
            model_id=str(model_id or "").strip(),
            base_url=normalized_base_url,
        )
        _reject_companion_orb_endpoint_collision(
            main_selection,
            selection,
            custom_endpoint=normalized_base_url,
            model_handling=handling,
        )
        _require_model(readiness, "grounding the Companion Orb view")
        if (
            not readiness.supports_images
            and self._prompts.catalog_supports_images(selection) is not True
        ):
            raise RuntimeError(
                "The selected Companion Orb vision model does not support image messages."
            )
        request = self._prompts.tasks.build_companion_orb_grounding_request(
            model_id=selection.model_id,
            image_data_url=_vision_data_url(path),
            capture_bounds=capture_bounds,
            gaze_point=gaze_point,
            apply_generation_fields=self._prompts.generation_fields(selection),
        )
        if (
            normalized_base_url or handling == "parallel_pinned"
        ) and not self._prompts.prepare_auxiliary(
            selection,
            reason="Companion Orb vision grounding",
            model_handling=handling,
            owner=(
                "companion_orb_vision"
                if handling == "parallel_pinned"
                else ""
            ),
        ):
            raise RuntimeError("The Companion Orb vision model could not be prepared.")
        response = self._complete_companion_orb_vision_prompt(
            selection,
            request,
            reason="Companion Orb vision grounding",
            custom_endpoint=bool(normalized_base_url),
            model_handling=handling,
        )
        return self._prompts.tasks.shape_companion_orb_grounding_response(response)

    def ensure_vision_model(
        self,
        *,
        provider_id: str,
        model_id: str,
        base_url: str = "",
        model_handling: str = "parallel_pinned",
    ) -> Mapping[str, object]:
        normalized_base_url = _companion_orb_http_base_url(base_url)
        handling = _companion_orb_model_handling(model_handling)
        selection, readiness = self._prompts.capture(
            provider_id=str(provider_id or "").strip(),
            model_id=str(model_id or "").strip(),
            base_url=normalized_base_url,
        )
        _require_model(readiness, "preparing Companion Orb vision", require_images=True)
        ready = (
            self._prompts.adopt_loaded_auxiliary(
                selection,
                owner="companion_orb_vision",
            )
            if handling == "already_loaded"
            else self._prompts.prepare_auxiliary(
                selection,
                reason="ensure Companion Orb vision model",
                model_handling=handling,
                owner="companion_orb_vision",
            )
        )
        result: dict[str, object] = {
            "ready": bool(ready),
            "endpoint": str(selection.endpoint or ""),
            "model_id": str(selection.model_id or ""),
            "resolved_model_key": "",
            "identifier": "",
            "owned": False,
        }
        if ready and handling in {"parallel_pinned", "already_loaded"}:
            result.update(
                dict(
                    self._prompts.preserved_snapshot(
                        selection,
                        owner="companion_orb_vision",
                    )
                )
            )
            result["ready"] = bool(result.get("identifier"))
        return result

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
    ) -> Mapping[str, object]:
        from addons.companion_orb_overlay.companion_orb.visual_observation import (
            ObservationStreamAccumulator,
            VisualObservationKey,
            cancel_visual_request,
            format_visual_observation_evidence,
            is_degenerate_visual_output,
            normalize_plain_visual_observation,
            normalize_visual_observation,
        )

        path = _required_image(image_path, "visual observation")
        normalized_base_url = _companion_orb_http_base_url(base_url)
        handling = _companion_orb_model_handling(model_handling)
        selection, readiness = self._prompts.capture(
            provider_id=str(provider_id or "").strip(),
            model_id=str(model_id or "").strip(),
            base_url=normalized_base_url,
        )
        _require_model(readiness, "observing the Companion Orb view", require_images=True)
        bounds = tuple(capture_bounds or ())
        if len(bounds) != 4:
            bounds = (0, 0, 1000, 1000)
        requested_mode = str(capability_mode or "auto").strip().lower()
        if requested_mode not in {
            "auto",
            "structured_regions",
            "description",
            "ocr",
            "question",
            "conversation",
        }:
            requested_mode = "auto"
        structured_output = (
            selection.provider_id == "lmstudio"
            and requested_mode in {"auto", "structured_regions"}
        )
        request = self._prompts.tasks.build_companion_orb_visual_observation_request(
            model_id=selection.model_id,
            image_data_url=(
                _data_url(path)
                if str(reaction_scope or "").strip().lower() in {"scan", "diagnostic"}
                else _vision_data_url(path)
            ),
            capture_bounds=bounds,
            reaction_scope=reaction_scope,
            capability_mode=requested_mode,
            target_text=target_text,
            question_text=question_text,
            structured_output=structured_output,
            apply_generation_fields=self._prompts.generation_fields(selection),
        )
        if structured_output:
            extras = request.additional_params_copy()
            # Opt in only this auxiliary request; ordinary chat keeps Responses.
            extras["_lmstudio_structured_output"] = True
            request = type(request).from_payload(request.params_copy(), extras)
        companion_orb_vision_debug.record_event(
            trace_id,
            "lfm_provider_request",
            provider_id=str(selection.provider_id or ""),
            model_id=str(selection.model_id or ""),
            endpoint=str(selection.endpoint or normalized_base_url or ""),
            model_handling=handling,
            capability_mode=requested_mode,
            timeout_seconds=max(1.0, min(60.0, float(timeout_seconds))),
            request=companion_orb_vision_debug.serialize_provider_request(request),
        )
        if trace_id:
            companion_orb_vision_debug.record_event(
                trace_id,
                "lfm_model_residency_before_request",
                snapshot=self._prompts.residency_snapshot(selection),
            )
        token = cancel_token if cancel_token is not None else threading.Event()
        accumulator = (
            ObservationStreamAccumulator(
                cancel_token=None if structured_output else token, max_chars=12000
            )
            if requested_mode in {"auto", "structured_regions"}
            else None
        )
        completed = None
        raw_chunks: list[str] = []
        self._provider_activity.begin_request()
        try:
            stream = self._prompts.stream(
                selection,
                request,
                reason="Companion Orb visual observation",
                timeout_seconds=max(1.0, min(60.0, float(timeout_seconds))),
                cancel_token=token,
            )
            for chunk in stream:
                raw_chunks.append(str(chunk or ""))
                raw_text = "".join(raw_chunks)
                if len(raw_text) > 12000:
                    cancel_visual_request(token)
                    raise RuntimeError(
                        "Visual observation exceeded its bounded response size."
                    )
                if is_degenerate_visual_output(raw_text):
                    cancel_visual_request(token)
                    raise RuntimeError(
                        "Vision model returned degenerate repeated-token output."
                    )
                completed = accumulator.feed(chunk) if accumulator is not None else None
                if completed is not None and not structured_output:
                    break
        except BaseException as exc:
            companion_orb_vision_debug.record_event(
                trace_id,
                "lfm_provider_error",
                error_type=type(exc).__name__,
                error=str(exc),
                partial_raw_response="".join(raw_chunks),
                provider_chunk_count=len(raw_chunks),
            )
            raise
        finally:
            self._provider_activity.end_request()
        raw_response = "".join(raw_chunks).strip() if structured_output else completed or "".join(raw_chunks).strip()
        if not raw_response:
            companion_orb_vision_debug.record_event(
                trace_id,
                "lfm_provider_error",
                error="The vision model returned no complete visual observation.",
                partial_raw_response="".join(raw_chunks),
                provider_chunk_count=len(raw_chunks),
            )
            raise RuntimeError("The vision model returned an empty visual observation.")
        if requested_mode == "structured_regions" and completed is None:
            raise RuntimeError(
                "The structured vision mode requires one complete JSON observation."
            )
        if structured_output and (completed is None or completed != raw_response):
            raise RuntimeError("The structured vision request did not return exactly one JSON observation.")
        try:
            normalized_bounds = tuple(int(value) for value in bounds)
        except (TypeError, ValueError):
            normalized_bounds = (0, 0, 1000, 1000)
        key = VisualObservationKey(
            fingerprint=hashlib.sha256(path.read_bytes()).hexdigest(),
            # Captures use x/y/width/height; observation keys use edge coordinates.
            capture_bounds=(
                normalized_bounds[0],
                normalized_bounds[1],
                normalized_bounds[0] + normalized_bounds[2],
                normalized_bounds[1] + normalized_bounds[3],
            ),
            endpoint=str(selection.endpoint or normalized_base_url or "local"),
            model_id=str(selection.model_id or ""),
            generation=0,
            capability_mode=requested_mode,
        )
        if completed is not None:
            payload = self._prompts.tasks.shape_companion_orb_visual_observation_response(
                completed
            )
            observation = normalize_visual_observation(payload, key=key)
            response_mode = "structured_regions"
        else:
            response_mode = (
                "question" if requested_mode == "question"
                else "ocr" if requested_mode == "ocr" else "description"
            )
            observation = normalize_plain_visual_observation(
                raw_response,
                key=key,
                capability_mode="description" if response_mode == "question" else response_mode,
            )
        observation_payload = {
            "scene_summary": observation.scene_summary,
            "user_focus": observation.user_focus,
            "visible_evidence": list(observation.visible_evidence),
            "suggested_topics": list(observation.suggested_topics),
            "regions": [
                {
                    "label": region.label,
                    "kind": region.kind,
                    "bbox": list(region.bbox),
                    "confidence": region.confidence,
                    "action_hint": region.action_hint,
                }
                for region in observation.regions
            ],
            "limitations": observation.limitations,
        }
        companion_orb_vision_debug.record_event(
            trace_id,
            "lfm_provider_response",
            raw_response=raw_response,
            shaped_response=observation_payload,
            capability_mode=requested_mode,
            response_mode=response_mode,
            raw_character_count=len(raw_response),
            provider_chunk_count=len(raw_chunks),
            degenerate=companion_orb_vision_debug.looks_degenerate(raw_response),
        )
        if trace_id:
            companion_orb_vision_debug.record_event(
                trace_id,
                "lfm_model_residency_after_response",
                snapshot=self._prompts.residency_snapshot(selection),
            )
        response = {
            "observation": observation_payload,
            "text": format_visual_observation_evidence(observation),
            "model_id": str(selection.model_id or ""),
            "endpoint": str(selection.endpoint or ""),
            "model_handling": handling,
            "capability_mode": requested_mode,
            "response_mode": response_mode,
        }
        if requested_mode == "question":
            response["answer_text"] = raw_response.strip()
        elif requested_mode == "conversation":
            response["evidence_text"] = raw_response.strip()
        if str(reaction_scope or "").strip().lower() in {"scan", "diagnostic"}:
            response["diagnostic_response_excerpt"] = raw_response[:600]
            response["diagnostic_response_chars"] = len(raw_response)
            response["provider_region_count"] = len(observation_payload["regions"])
        return response

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
    ) -> Mapping[str, object]:
        path = _required_image(image_path, "visual guidance")
        normalized_base_url = _companion_orb_http_base_url(base_url)
        handling = _companion_orb_model_handling(model_handling)
        main_selection = None
        if restore_main_model or (
            normalized_base_url and handling != "already_loaded"
        ):
            main_selection, _main_readiness = self._prompts.capture()
        selection, readiness = self._prompts.capture(
            provider_id=str(provider_id or "").strip(),
            model_id=str(model_id or "").strip(),
            base_url=normalized_base_url,
        )
        _reject_companion_orb_endpoint_collision(
            main_selection,
            selection,
            custom_endpoint=normalized_base_url,
            model_handling=handling,
        )
        _require_model(
            readiness,
            "generating Companion Orb visual guidance",
            require_images=True,
        )
        request = self._prompts.tasks.build_companion_orb_visual_guidance_request(
            model_id=selection.model_id,
            image_data_url=_vision_data_url(path),
            reaction_scope=reaction_scope,
            apply_generation_fields=self._prompts.generation_fields(selection),
        )
        try:
            if (
                normalized_base_url or handling == "parallel_pinned"
            ) and not self._prompts.prepare_auxiliary(
                selection,
                reason="Companion Orb visual guidance",
                model_handling=handling,
                owner=(
                    "companion_orb_vision"
                    if handling == "parallel_pinned"
                    else ""
                ),
            ):
                raise RuntimeError(
                    "The Companion Orb visual guidance model could not be prepared."
                )
            response = self._complete_companion_orb_vision_prompt(
                selection,
                request,
                reason="Companion Orb visual guidance",
                custom_endpoint=bool(normalized_base_url),
                model_handling=handling,
            )
            guidance = (
                self._prompts.tasks.shape_companion_orb_visual_guidance_response(
                    response
                )
            )
            return {
                "guidance": guidance,
                "text": format_companion_orb_visual_guidance(guidance),
            }
        finally:
            if (
                restore_main_model
                and main_selection is not None
                and str(main_selection.provider_id or "").strip().lower()
                == "lmstudio"
                and _companion_orb_endpoints_match(main_selection, selection)
            ):
                self._prompts.ensure_ready(
                    main_selection,
                    reason="restore Main Chat after Orb guidance",
                )

    def release_vision_model(
        self,
        *,
        provider_id: str,
        model_id: str,
        base_url: str = "",
        model_handling: str = "parallel_pinned",
    ) -> bool:
        handling = _companion_orb_model_handling(model_handling)
        if handling not in {"parallel_pinned", "already_loaded"}:
            return True
        normalized_base_url = _companion_orb_http_base_url(base_url)
        selection, _readiness = self._prompts.capture(
            provider_id=str(provider_id or "").strip(),
            model_id=str(model_id or "").strip(),
            base_url=normalized_base_url,
        )
        return self._prompts.release_auxiliary(
            selection,
            reason="release Companion Orb vision model",
            owner="companion_orb_vision",
        )

    def ephemeral_comment(
        self,
        *,
        selected_text: str,
        behavior_prompt: str,
        response_style_label: str = "Very friendly",
        exclude_from_memory: bool = True,
        mode: str = "select_area_comment",
    ) -> str:
        text = reading_actions.clean_readable_text(selected_text)
        if not text:
            raise ValueError("Selected text is empty.")
        contextual_payload = {
            "text": "Give a short natural spoken comment about the Companion Orb selection.",
            "source": "companion_orb",
            "context": (
                "Companion Orb selected text:\n"
                + text
                + "\n\nRequested comment behavior:\n"
                + str(behavior_prompt or "").strip()
                + f"\nReply style: {str(response_style_label or 'Very friendly').strip()}."
            ),
        }
        contextual = self._contextual_replies.maybe_reply(contextual_payload)
        if contextual is not None:
            response = str(contextual.get("response_text") or "").strip()
            if response:
                self._contextual_replies.record_reply(
                    response,
                    source="companion_orb",
                )
                return response

        selection, readiness = self._prompts.capture()
        _require_model(readiness, "asking the Companion Orb to comment")
        messages = reading_actions.build_comment_messages(
            selected_text=text,
            behavior_prompt=str(behavior_prompt or ""),
            response_style_label=str(response_style_label or "Very friendly"),
            exclude_from_memory=bool(exclude_from_memory),
            mode=str(mode or "select_area_comment"),
        )
        request = self._prompts.tasks.build_plain_text_request(
            model_id=selection.model_id,
            messages=messages,
            apply_generation_fields=self._prompts.generation_fields(selection),
            max_tokens=260,
        )
        response = self._prompts.tasks.require_text(
            self._complete_prompt(
                selection,
                request,
                reason="Companion Orb ephemeral comment",
            ),
            empty_error="The provider returned an empty Companion Orb comment.",
        )
        self._contextual_replies.record_reply(response, source="companion_orb")
        return response

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
    ) -> object:
        return self._sensory.queue_proactive(
            {
                "candidate": candidate,
                "summary": summary,
                "attention": attention,
                "emotion": emotion,
                "source": source,
                "created_at": float(self._clock()),
                "allow_repeated_candidate": bool(allow_repeated_candidate),
                "focus_bounds": focus_bounds,
                "focus_label": focus_label,
                "focus_text": focus_text,
                "focus_duration_seconds": float(focus_duration_seconds),
                "trace_id": trace_id,
            },
            self._conversation.session_lease(),
        )

    def run_sensory_cycle(
        self,
        force: bool = False,
        snapshots_override: object = None,
        priority: bool = False,
        priority_source: str = "",
        trace_id: str = "",
    ) -> object:
        return self._sensory.run_cycle(
            force=bool(force),
            snapshots_override=snapshots_override,
            priority=bool(priority),
            priority_source=str(priority_source or ""),
            trace_id=str(trace_id or ""),
            lease=self._conversation.session_lease(),
        )

    def generate_drop_guidance(
        self,
        *,
        image_path: str,
        snapshot_metadata: Mapping[str, object] | None = None,
        response_style_label: str = "Very friendly",
    ) -> Mapping[str, object]:
        path = _required_image(image_path, "drop guidance")
        selection, readiness = self._prompts.capture()
        _require_model(
            readiness,
            "using Companion Orb smart drop guidance",
            require_images=True,
        )
        request = self._prompts.tasks.build_companion_orb_drop_guidance_request(
            model_id=selection.model_id,
            image_data_url=_data_url(path),
            snapshot_metadata=snapshot_metadata,
            response_style_label=response_style_label,
            apply_generation_fields=self._prompts.generation_fields(selection),
        )
        response = self._complete_prompt(
            selection,
            request,
            reason="Companion Orb drop guidance",
        )
        return self._prompts.tasks.shape_companion_orb_drop_guidance_response(
            response
        )

    def format_drop_guidance(self, guidance: Mapping[str, object]) -> str:
        return format_companion_orb_drop_guidance(guidance)

    def _complete_prompt(
        self,
        selection,
        request,
        *,
        reason: str,
        prepare_model: bool = True,
        require_frozen_execution: bool = False,
    ) -> str:
        self._provider_activity.begin_request()
        try:
            return self._prompts.complete(
                selection,
                request,
                reason=reason,
                prepare_model=prepare_model,
                require_frozen_execution=require_frozen_execution,
            )
        finally:
            self._provider_activity.end_request()

    def _complete_companion_orb_vision_prompt(
        self,
        selection,
        request,
        *,
        reason: str,
        custom_endpoint: bool,
        model_handling: str,
    ) -> str:
        handling = _companion_orb_model_handling(model_handling)
        direct_frozen = bool(
            custom_endpoint
            or handling in {"already_loaded", "parallel_pinned"}
        )
        if not custom_endpoint and handling == "auto_with_fallback":
            try:
                self._prompts.ensure_ready(selection, reason=reason)
            except Exception:
                pass
            direct_frozen = True
        return self._complete_prompt(
            selection,
            request,
            reason=reason,
            prepare_model=not direct_frozen,
            require_frozen_execution=direct_frozen,
        )


class ProductionAudioStoryTtsRuntimeExtensionOwner:
    """Own Audio Story chunk policy and its finite TTS resource operations."""

    __slots__ = ("_avatar", "_config", "_resources")

    _STANDARD_TARGET = 100
    _STANDARD_MAXIMUM = 200
    _MUSETALK_TARGET = 110
    _MUSETALK_MAXIMUM = 220
    _MUSETALK_QUICKSTART = ((170, 320), (130, 240))

    def __init__(
        self,
        *,
        config: RuntimeConfigService,
        avatar: AvatarService,
        resources: AudioStoryTtsResourceOwner,
    ) -> None:
        self._config = config
        self._avatar = avatar
        self._resources = resources

    def text_chunk_limits(
        self,
        runtime_config: Mapping[str, object] | None = None,
    ) -> tuple[int, int]:
        values = (
            dict(runtime_config)
            if isinstance(runtime_config, Mapping)
            else dict(self._config.snapshot().values)
        )
        if str(values.get("avatar_mode", "vseeface") or "vseeface").lower() == "musetalk":
            return tuple(
                self._avatar.chunk_limits_for_index(
                    2,
                    values,
                    quickstart=self._MUSETALK_QUICKSTART,
                    target=self._MUSETALK_TARGET,
                    maximum=self._MUSETALK_MAXIMUM,
                )
            )
        return (
            int(values.get("chunk_target_chars", self._STANDARD_TARGET) or self._STANDARD_TARGET),
            int(values.get("chunk_max_chars", self._STANDARD_MAXIMUM) or self._STANDARD_MAXIMUM),
        )

    def chunk_text(
        self,
        text: str,
        target_length: int,
        maximum_length: int,
    ) -> Sequence[str]:
        return tuple(
            text_chunking.chunk_text(
                str(text or ""),
                int(target_length),
                int(maximum_length),
                min_chunk_size=10,
                logger=_ignore_message,
            )
        )

    def set_seed(self, seed: int) -> object:
        return self._resources.set_seed(int(seed))

    def generate(self, text: str, **settings: object) -> object:
        return self._resources.generate(str(text), **dict(settings))

    def save_wav(self, path: str, wav: object, sample_rate: int) -> object:
        return self._resources.save_wav(str(path), wav, int(sample_rate))

    def safe_delete(self, path: str) -> object:
        return runtime_files.safe_delete(str(path), logger=_ignore_message)

    def sample_rate(self, default: int) -> int:
        return int(self._resources.sample_rate(int(default)))


class ProductionAvatarResourceRuntimeExtensionOwner:
    __slots__ = ("_resources",)

    def __init__(self, *, resources: AvatarEmotionResourceOwner) -> None:
        self._resources = resources

    def refresh_emotions(self) -> object:
        return self._resources.refresh_emotions()

    def tts_device(self) -> str:
        return str(self._resources.tts_device() or "cpu")


class ProductionVisualRequestRuntimeExtensionOwner:
    __slots__ = ("_config", "_conversation", "_visual")

    def __init__(
        self,
        *,
        config: RuntimeConfigService,
        conversation: ConversationService,
        visual: VisualService,
    ) -> None:
        self._config = config
        self._conversation = conversation
        self._visual = visual

    def request_generation(
        self,
        prompt: str,
        *,
        inputs: Sequence[object] = (),
        source_text: str = "",
        request_id: str | None = None,
        runtime_config_override: Mapping[str, object] | None = None,
        asset_metadata: Mapping[str, object] | None = None,
    ) -> object:
        prompt_text = str(prompt or "").strip()
        if not prompt_text:
            return False
        runtime_config = (
            dict(runtime_config_override)
            if isinstance(runtime_config_override, Mapping)
            else dict(self._config.snapshot().values)
        )
        requested = self._visual.request_generation(
            self._conversation.session_lease(),
            prompt=prompt_text,
            inputs=tuple(Path(item) for item in tuple(inputs or ())),
            source_text=str(source_text or ""),
            request_id=request_id,
            runtime_config=runtime_config,
            asset_metadata=asset_metadata,
        )
        return bool(requested.accepted)


class ProductionPromptRefinementRuntimeExtensionOwner:
    __slots__ = ("_prompts",)

    def __init__(
        self,
        *,
        config: RuntimeConfigService,
        providers: ProviderService,
        prompt_tasks: PromptTaskService,
    ) -> None:
        self._prompts = _ProviderPromptRunner(
            config=config,
            providers=providers,
            prompt_tasks=prompt_tasks,
        )

    def refine_persona(
        self, draft: Mapping[str, object], *, provider_id: str, model_id: str,
        regenerate: bool = False, cancel_token: object | None = None,
    ) -> str:
        from core.persona_prompt_builder import build_refiner_messages, clean_candidate

        selection, readiness = self._prompts.capture(provider_id=provider_id, model_id=model_id)
        _require_model(readiness, "refining the persona prompt")
        messages = build_refiner_messages(
            draft, provider_policy="hosted" if readiness.hosted_runtime else "local",
            regenerate=regenerate,
        )
        request = self._prompts.tasks.build_plain_text_request(
            model_id=selection.model_id, messages=messages,
            apply_generation_fields=self._prompts.generation_fields(selection), max_tokens=1600,
        )
        return clean_candidate(self._prompts.complete(
            selection, request, reason="refine persona prompt", require_frozen_execution=True,
            timeout_seconds=120.0, cancel_token=cancel_token,
        ))

    def refine(
        self,
        text: str,
        *,
        label: str = "Instruction",
        guidance: str = "",
    ) -> str:
        selection, readiness = self._prompts.capture()
        field_label = str(label or "Instruction").strip() or "Instruction"
        _require_model(readiness, f"refining {field_label}")
        request = self._prompts.tasks.build_instruction_refinement_request(
            text,
            model_id=selection.model_id,
            label=field_label,
            guidance=guidance,
            apply_generation_fields=self._prompts.generation_fields(selection),
        )
        return self._prompts.tasks.require_text(
            self._prompts.complete(
                selection,
                request,
                reason=f"refine {field_label}",
            ),
            empty_error="The provider returned empty refined text.",
        )


def build_production_addon_runtime_extension_owners(
    *,
    chat_context_owner: ProductionChatContextRuntimeExtensionOwner,
    speech_owner: ProductionSpeechRuntimeExtensionOwner,
    push_to_talk_owner: ProductionPushToTalkRuntimeExtensionOwner,
    orb_owner: ProductionOrbRuntimeExtensionOwner,
    audio_story_tts_owner: ProductionAudioStoryTtsRuntimeExtensionOwner,
    avatar_resource_owner: ProductionAvatarResourceRuntimeExtensionOwner,
    visual_request_owner: ProductionVisualRequestRuntimeExtensionOwner,
    prompt_refinement_owner: ProductionPromptRefinementRuntimeExtensionOwner,
) -> ProductionAddonRuntimeExtensionOwners:
    """Retain the eight concrete owners in the production composition record."""

    return ProductionAddonRuntimeExtensionOwners(
        chat_context_owner=chat_context_owner,
        speech_owner=speech_owner,
        push_to_talk_owner=push_to_talk_owner,
        orb_owner=orb_owner,
        audio_story_tts_owner=audio_story_tts_owner,
        avatar_resource_owner=avatar_resource_owner,
        visual_request_owner=visual_request_owner,
        prompt_refinement_owner=prompt_refinement_owner,
    )


def _remote_capture_id(value: object) -> str:
    return "".join(
        character
        for character in str(value or "")
        if character.isalnum() or character in {"_", "-"}
    )[:96]


def _required_image(value: object, operation: str) -> Path:
    path = Path(str(value or "").strip()).expanduser()
    if not str(value or "").strip() or not path.is_file():
        raise ValueError(
            f"Companion Orb {operation} needs an existing image file."
        )
    return path


def _data_url(path: Path) -> str:
    mime_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    if not payload:
        raise ValueError("Could not read the Companion Orb image.")
    return f"data:{mime_type};base64,{payload}"


def _vision_data_url(path: Path) -> str:
    """Send the saved Orb capture without resizing or re-encoding it."""

    return _data_url(path)


def _companion_orb_http_base_url(value: object) -> str:
    raw_value = str(value or "").strip()
    if not raw_value:
        return ""
    parsed = urlsplit(raw_value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError(
            "The Companion Orb vision server URL must use http or https."
        )
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(
            "The Companion Orb vision server URL must not include credentials."
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("The Companion Orb vision server URL has an invalid port.") from exc
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower()
    host = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 80 if scheme == "http" else 443
    netloc = host if port in {None, default_port} else f"{host}:{port}"
    return urlunsplit((scheme, netloc, "/v1", "", ""))


def _companion_orb_model_handling(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in {
        "auto_load",
        "already_loaded",
        "auto_with_fallback",
        "parallel_pinned",
    }:
        return "auto_load"
    return normalized


def _companion_orb_endpoints_match(first, second) -> bool:
    try:
        first_endpoint = _companion_orb_http_base_url(first.endpoint)
        second_endpoint = _companion_orb_http_base_url(second.endpoint)
    except (AttributeError, ValueError):
        return False
    if not first_endpoint or not second_endpoint:
        return False
    first_parsed = urlsplit(first_endpoint)
    second_parsed = urlsplit(second_endpoint)
    first_host = str(first_parsed.hostname or "").lower()
    second_host = str(second_parsed.hostname or "").lower()
    loopback_hosts = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
    if first_host in loopback_hosts:
        first_host = "loopback"
    if second_host in loopback_hosts:
        second_host = "loopback"
    first_port = first_parsed.port or (80 if first_parsed.scheme == "http" else 443)
    second_port = second_parsed.port or (80 if second_parsed.scheme == "http" else 443)
    return (
        first_parsed.scheme == second_parsed.scheme
        and first_host == second_host
        and first_port == second_port
    )


def _reject_companion_orb_endpoint_collision(
    main_selection,
    vision_selection,
    *,
    custom_endpoint: str,
    model_handling: str,
) -> None:
    if (
        custom_endpoint
        and model_handling != "already_loaded"
        and main_selection is not None
        and str(main_selection.provider_id or "").strip().lower() == "lmstudio"
        and _companion_orb_endpoints_match(main_selection, vision_selection)
    ):
        raise RuntimeError(
            "Companion Orb cannot auto-load a custom LFM endpoint that is also "
            "used by Main Chat. Choose the primary server mode or already-loaded mode."
        )


def _require_model(
    readiness,
    operation: str,
    *,
    require_images: bool = False,
) -> None:
    if readiness.hosted_runtime and not readiness.api_key_available:
        environment_hint = (
            " or set " + " / ".join(readiness.api_key_environment_names)
            if readiness.api_key_environment_names
            else ""
        )
        raise RuntimeError(
            f"{readiness.label} API key is required. Add it in Chat Provider "
            f"settings{environment_hint}."
        )
    if not readiness.model_selected:
        raise RuntimeError(f"Choose a chat model before {operation}.")
    if require_images and not readiness.supports_images:
        raise RuntimeError("The active chat model does not support image messages.")


def _ignore_message(_message: str) -> None:
    return None


__all__ = [
    "AddonChatContextCollector",
    "AudioStoryTtsResourceOwner",
    "AvatarEmotionResourceOwner",
    "ChatSessionSnapshotOwner",
    "CompanionOrbContextualReplyOwner",
    "ProductionAudioStoryTtsRuntimeExtensionOwner",
    "ProductionAvatarResourceRuntimeExtensionOwner",
    "ProductionChatContextRuntimeExtensionOwner",
    "ProductionOrbRuntimeExtensionOwner",
    "ProductionPromptRefinementRuntimeExtensionOwner",
    "ProductionPushToTalkRuntimeExtensionOwner",
    "ProductionSpeechRuntimeExtensionOwner",
    "ProductionVisualRequestRuntimeExtensionOwner",
    "ProviderActivityOwner",
    "PushToTalkHoldOwner",
    "SpeechModelResource",
    "build_production_addon_runtime_extension_owners",
]
