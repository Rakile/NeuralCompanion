"""Production owner for assistant reply publication and normal speech routes."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from queue import Empty
from threading import Event
from types import MappingProxyType
from typing import Protocol
import time

from core import conversation_history, streaming_text, text_tags
from core.streaming_deadlines import TextStreamChannel
from core.conversation_flow_v2 import PreparedAssistantReply, TTSControlPort
from core.runtime.assistant_directives import (
    AssistantFocusDirective,
    extract_companion_orb_focus,
)
from core.runtime.config import RuntimeConfigService, RuntimeConfigSnapshot
from core.runtime.identifiers import WorkLease
from core.runtime.speech_output import SpeechOutputService, SpeechPlan
from core.runtime.speech_routes import (
    NormalSpeechRoute,
    NormalSpeechRouteCoordinator,
    SpeechRouteRequest,
    VoiceSegment,
)
from core.runtime.visual import (
    VisualService,
    persona_visual_request_config,
    plan_persona_visual_request,
)


_CHATTERBOX_BACKENDS = {"chatterbox", "chatterbox_multilingual"}
_TERMINAL_SPEECH_PUNCTUATION = frozenset(".!?…")
_TRAILING_SPEECH_CLOSERS = "\"'”’)]}"


def _stabilize_companion_orb_speech(
    text: str,
    *,
    source_metadata: Mapping[str, object],
    runtime_config: Mapping[str, object],
) -> str:
    """Give an unfinished Orb fragment a reliable Chatterbox end boundary."""

    value = str(text or "")
    if not bool(source_metadata.get("companion_orb_response", False)):
        return value
    backend = (
        str(runtime_config.get("tts_backend", "") or "")
        .strip()
        .lower()
        .replace("-", "_")
    )
    stripped = value.rstrip()
    terminal_probe = stripped.rstrip(_TRAILING_SPEECH_CLOSERS)
    if (
        not terminal_probe
        or backend not in _CHATTERBOX_BACKENDS
        or terminal_probe[-1] in _TERMINAL_SPEECH_PUNCTUATION
    ):
        return value
    return f"{stripped}."


class SpeechLeaseProvider(Protocol):
    """Supply an explicit lease when a non-turn caller requests speech."""

    def current_speech_lease(self) -> WorkLease: ...


class ReplyEffectAdmission(Protocol):
    """Admit reply effects only while the committed turn remains current."""

    def committed_effect_lease_is_valid(self, lease: WorkLease) -> bool: ...


class AssistantReplyNotifier(Protocol):
    """Publish the finalized visible reply to addon observers."""

    def notify_assistant_reply(self, text: str) -> None: ...

    def notify_companion_orb_focus(
        self,
        directive: AssistantFocusDirective,
    ) -> None: ...


class SpeechLatencyRecorder(Protocol):
    """Record low-frequency speech preparation telemetry."""

    def record_assistant_finalize(
        self,
        *,
        duration_ms: float,
        reply_chars: int,
    ) -> None: ...


class _NoopReplyNotifier:
    def notify_assistant_reply(self, text: str) -> None:
        del text

    def notify_companion_orb_focus(
        self,
        directive: AssistantFocusDirective,
    ) -> None:
        del directive


class _NoopLatencyRecorder:
    def record_assistant_finalize(
        self,
        *,
        duration_ms: float,
        reply_chars: int,
    ) -> None:
        del duration_ms, reply_chars


class _RouteDoneFlag:
    """Expose route completion through the legacy event-shaped read API."""

    def __init__(self, route: NormalSpeechRoute) -> None:
        self._route = route

    def is_set(self) -> bool:
        return self._route.done

    def wait(self, timeout: float | None = None) -> bool:
        return self._route.wait(timeout)

    def set(self) -> None:
        # Route completion is owned by playback; callers cannot forge it.
        return None

    def clear(self) -> None:
        # A completed exact route cannot be reused.
        return None


class SpeechRouteControl:
    """Controller-compatible view of one exact normal speech route."""

    def __init__(self, route: NormalSpeechRoute, communication_trace=None) -> None:
        self._route = route
        self._communication_trace = communication_trace
        self.done = _RouteDoneFlag(route)
        self.audio_started = route.audio_started

    def get_spoken_text(self) -> str:
        receipt = self._route.receipt
        if receipt is None:
            return ""
        return " ".join(
            str(chunk.text or "").strip()
            for chunk in receipt.delivered_chunks
            if str(chunk.text or "").strip()
        ).strip()

    def playback_receipt(self):
        """Return the terminal receipt without exposing the owned route."""

        return self._route.receipt

    def playback_retired(self) -> bool:
        return self._route.playback_retired()

    def request_playback_skip(self) -> bool:
        if self._route.done:
            return False
        return self.cancel("speech_skipped")

    def pause(self) -> bool:
        if self._route.done:
            return False
        return bool(self._route.pause().accepted)

    def resume(self) -> bool:
        if self._route.done:
            return False
        return bool(self._route.resume().accepted)

    def cancel(self, reason: str = "speech_cancelled") -> bool:
        from core.communication_trace import record_to, lease_correlation
        record_to(self._communication_trace,'speech.interruption_requested',dict(reason=reason),
            lease_correlation(self._route.lease,route_id=self._route.route_id))
        return bool(self._route.cancel(reason).accepted)


class ProductionSpeechOutputOwner:
    """Join finalized replies, visual effects, TTS preparation, and playback."""

    def __init__(
        self,
        *,
        speech_output: SpeechOutputService,
        routes: NormalSpeechRouteCoordinator,
        visual: VisualService,
        config: RuntimeConfigService,
        leases: SpeechLeaseProvider,
        effect_admission: ReplyEffectAdmission,
        notifier: AssistantReplyNotifier | None = None,
        latency: SpeechLatencyRecorder | None = None,
        available_emotions: Callable[[], object] | None = None,
        supported_sound_tags: Callable[[], object] | None = None,
        communication_trace=None,
        character_voice_turns=None,
    ) -> None:
        self._speech_output = speech_output
        self._routes = routes
        self._visual = visual
        self._config = config
        self._leases = leases
        self._effect_admission = effect_admission
        self._notifier = notifier or _NoopReplyNotifier()
        self._latency = latency or _NoopLatencyRecorder()
        self._available_emotions = available_emotions or tuple
        self._supported_sound_tags = supported_sound_tags or tuple
        self._communication_trace = communication_trace
        self._character_voice_turns = character_voice_turns

    def prepare_low_latency_completed_tts_segments(
        self,
        text: str,
        *,
        runtime_config: Mapping[str, object],
    ) -> tuple[str, ...]:
        plan = self._speech_output.plan(
            str(text or ""),
            self._snapshot(runtime_config),
        )
        return tuple(chunk.text for chunk in plan.chunks if chunk.text)

    def prepare_assistant_reply(
        self,
        text: str,
        *,
        runtime_config: Mapping[str, object],
    ) -> PreparedAssistantReply:
        started_at = time.perf_counter()
        visible_text, orb_focus = extract_companion_orb_focus(str(text or ""))
        cleaned, visual_prompt = self._visual.extract_prompt(visible_text)
        visual_plan = plan_persona_visual_request(visual_prompt, runtime_config)
        cleaned = str(cleaned or "").strip()
        if not cleaned and orb_focus is not None:
            # A directive-only answer still needs a visible turn: empty replies
            # are discarded before their committed action effects are published.
            cleaned = "I'll look for that on the screen."
        if bool(runtime_config.get("chat_message_timestamps_enabled", False)):
            cleaned = conversation_history.strip_leading_turn_timestamps(cleaned).strip()
        return PreparedAssistantReply(
            text=cleaned,
            visual_prompt=visual_plan.prompt,
            finalize_duration_ms=round(
                max(0.0, (time.perf_counter() - started_at) * 1000.0),
                3,
            ),
            orb_focus=orb_focus,
            visual_inputs=visual_plan.inputs,
            visual_reference_strength=visual_plan.reference_strength,
            visual_uses_persona_identity=visual_plan.uses_persona_identity,
            visual_uses_user_identity=visual_plan.uses_user_identity,
            visual_edits_source_image=visual_plan.edits_source_image,
            visual_source_edit_error=visual_plan.source_edit_error,
            visual_source_edit_config=MappingProxyType(dict(runtime_config)) if visual_plan.edits_source_image else None,
        )

    def publish_assistant_reply_effects(
        self,
        prepared: PreparedAssistantReply,
        *,
        lease: WorkLease,
    ) -> bool:
        if not isinstance(prepared, PreparedAssistantReply):
            raise TypeError("Assistant reply effects require PreparedAssistantReply.")
        if not self._effect_admission.committed_effect_lease_is_valid(lease):
            return False
        live_config = self._config.snapshot().values
        if prepared.visual_prompt and self._visual.enabled(live_config):
            visual_config = persona_visual_request_config(
                prepared.visual_source_edit_config if prepared.visual_source_edit_config is not None else live_config,
                reference_strength=prepared.visual_reference_strength,
                reference_count=len(prepared.visual_inputs),
                edits_source_image=prepared.visual_edits_source_image,
                source_edit_error=prepared.visual_source_edit_error,
            )
            self._visual.request_generation(
                lease,
                prompt=prepared.visual_prompt,
                inputs=prepared.visual_inputs,
                source_text=prepared.text,
                runtime_config=visual_config,
                asset_metadata={
                    "persona_identity": prepared.visual_uses_persona_identity,
                    "user_identity": prepared.visual_uses_user_identity,
                },
            )
        if not self._effect_admission.committed_effect_lease_is_valid(lease):
            return False
        self._notifier.notify_assistant_reply(prepared.text)
        notify_orb = getattr(self._notifier, "notify_companion_orb_focus", None)
        if prepared.orb_focus is not None and callable(notify_orb):
            notify_orb(prepared.orb_focus)
        self._latency.record_assistant_finalize(
            duration_ms=prepared.finalize_duration_ms,
            reply_chars=len(prepared.text),
        )
        return True

    def stage_continuous_audio(self, stage) -> bool:
        """Warm the first two phone TTS chunks without publishing a speech route."""
        from core.phone_narration import split_phone_speech_clauses
        if stage.token.cancelled:
            return False
        config = self._snapshot(None)
        pieces = tuple(stage.voice_segments)
        if not pieces:
            values = config.values
            assembler = streaming_text.StreamingChunkAssembler(
                int(values.get('stream_chunk_target_chars', 80) or 80),
                int(values.get('stream_chunk_max_chars', 185) or 185),
                config_getter=lambda key, default=None: values.get(key, default))
            chunks = list(assembler.feed(stage.raw_response))
            chunks.extend(assembler.feed('', final=True))
            pieces = tuple(VoiceSegment(str(item.get('text') or '')) for item in chunks
                           if str(item.get('text') or '').strip())
        prepared_chunks = []
        next_index = 0
        # Phone-owned routes split clauses after streamed/character segmentation.
        # Private preparation must use those same text boundaries for cache reuse.
        pieces = tuple(VoiceSegment(phrase, piece.voice_path, piece.voice_language,
                                    piece.source_metadata)
                       for piece in pieces
                       for phrase in split_phone_speech_clauses(
                           piece.text, tts_backend=str(config.values.get('tts_backend') or '')))
        for piece in pieces:
            if stage.token.cancelled or len(prepared_chunks) >= 2:
                break
            metadata = dict(piece.source_metadata)
            metadata.update(remote_capture_id='continuous-private',
                            continuous_stage_id=stage.stage_id)
            plan = self._speech_output.plan(piece.text, config, start_index=next_index,
                preserve_input_chunk=True, voice_path=piece.voice_path,
                voice_language=piece.voice_language, source_metadata=metadata)
            prepared_chunks.extend(plan.chunks[:max(0, 2 - len(prepared_chunks))])
            if plan.chunks:
                next_index = plan.chunks[-1].index + 1
        if not prepared_chunks or stage.token.cancelled:
            return False
        private = SpeechPlan(stage.text, tuple(prepared_chunks), config,
                             prepared_chunks[-1].expression)
        return self._speech_output.prepare_private_continuous(
            stage.stage_id, private, stage.token)

    def activate_continuous_audio(self, stage_id: str) -> None:
        self._speech_output.activate_private_continuous(stage_id)

    def discard_continuous_audio(self, stage_id: str) -> None:
        self._speech_output.discard_private_continuous(stage_id)

    def speak_async(
        self,
        text: str,
        *,
        text_iterable: object = None,
        dry_run_reply_id: str | None = None,
        voice_path_override: str | None = None,
        preserve_text_iterable_chunks: bool = False,
        reply_source_meta: Mapping[str, object] | None = None,
        runtime_config: Mapping[str, object] | None = None,
        turn_lease: WorkLease | None = None,
    ) -> TTSControlPort:
        del dry_run_reply_id
        config = self._snapshot(runtime_config)
        lease = turn_lease or self._leases.current_speech_lease()
        captured_metadata = dict(reply_source_meta or {})
        if captured_metadata.get("normal_chat_transaction_id"):
            captured_metadata.setdefault("chat_character_conversation_id",
                                         str(config.values.get("chat_character_conversation_id", "") or ""))
        source_metadata = MappingProxyType(captured_metadata)
        from core.communication_trace import record_to, lease_correlation
        correlation=lease_correlation(lease,turn_id=str(lease.turn_id.value) if lease.turn_id else '')
        record_to(self._communication_trace,'speech.route_submitted',dict(text=text,
            streamed=text_iterable is not None,source_metadata=source_metadata,
            note='Submitted for synthesis; not proof of audible playback.'),correlation)
        request = SpeechRouteRequest(
            lease=lease,
            config=config,
            source_metadata=source_metadata,
            voice_path=str(voice_path_override or "").strip(),
            preserve_input_chunks=bool(preserve_text_iterable_chunks),
        )
        if text_iterable is None and self._character_voice_turns is not None:
            frozen_parts = self._character_voice_turns.completed(str(captured_metadata.get('normal_chat_request_id','')))
            if frozen_parts is not None:
                text_iterable = frozen_parts
        if text_iterable is None:
            speech_text = _stabilize_companion_orb_speech(
                str(text or ""),
                source_metadata=source_metadata,
                runtime_config=config.values,
            )
            opened = self._routes.speak_complete(speech_text, request)
        else:
            opened = self._routes.speak_stream(
                self._record_stream(self._iter_text(text_iterable),correlation),
                request,
            )
        if not opened.accepted or opened.value is None:
            failure = opened.failure
            detail = failure.message if failure is not None else "unknown speech route failure"
            raise RuntimeError(detail)
        return SpeechRouteControl(opened.value,self._communication_trace)

    def _record_stream(self, chunks, correlation):
        return _RecordingTextStream(_CleanCharacterTextStream(chunks, self._visual),self._communication_trace,correlation)

    def speak_async_stream(
        self,
        text_queue: object,
        *,
        dry_run_reply_id: str | None = None,
        requires_full_text: bool | None = None,
        reply_source_meta: Mapping[str, object] | None = None,
        runtime_config: Mapping[str, object] | None = None,
        turn_lease: WorkLease | None = None,
    ) -> TTSControlPort:
        del requires_full_text
        return self.speak_async(
            "",
            text_iterable=self._iter_text_queue(text_queue),
            dry_run_reply_id=dry_run_reply_id,
            preserve_text_iterable_chunks=True,
            reply_source_meta=reply_source_meta,
            runtime_config=runtime_config,
            turn_lease=turn_lease,
        )

    def _snapshot(
        self,
        runtime_config: Mapping[str, object] | None,
    ) -> RuntimeConfigSnapshot:
        current = self._config.snapshot()
        values = dict(
            current.values if runtime_config is None else runtime_config
        )
        values["speech_available_emotion_names"] = tuple(
            sorted({str(item) for item in (self._available_emotions() or ())}
                   | text_tags.persona_mood_names(values))
        )
        values["speech_supported_sound_tag_names"] = tuple(
            sorted(str(item) for item in (self._supported_sound_tags() or ()))
        )
        values.setdefault("speech_min_chunk_size", 10)
        values.setdefault("musetalk_min_leading_segment_chars", 60)
        return RuntimeConfigSnapshot(
            current.revision,
            MappingProxyType(values),
        )

    @staticmethod
    def _iter_text(value: object) -> Iterable[str]:
        if isinstance(value, str):
            return (value,)
        if isinstance(value, Iterable):
            return _StringifyingTextStream(value)
        raise TypeError("Speech text iterable must be iterable.")

    @staticmethod
    def _iter_text_queue(text_queue: object) -> Iterable[str]:
        if isinstance(text_queue, Iterable):
            return _StringifyingTextStream(text_queue)
        get = getattr(text_queue, "get", None)
        if not callable(get):
            raise TypeError("Speech stream source must be iterable or queue-like.")
        return _QueueTextStream(get)


class _QueueTextStream:
    """Interruptible iterator that never consumes queued text after close."""

    def __init__(self, get) -> None:
        self._get = get
        source = getattr(get, "__self__", None)
        self._close_source = source.close if isinstance(source, TextStreamChannel) else None
        self._closed = Event()

    def __iter__(self):
        return self

    def __next__(self) -> str | VoiceSegment:
        while not self._closed.is_set():
            try:
                # The production channel wakes blocked get() on close. Keep
                # legacy raw queues compatible with their existing timeout.
                item = self._get() if callable(self._close_source) else self._get(timeout=0.05)
            except Empty:
                continue
            if self._closed.is_set():
                put_back = getattr(getattr(self._get, "__self__", None), "put", None)
                if item is not None and callable(put_back):
                    put_back(item)
                raise StopIteration
            if item is None:
                raise StopIteration
            value = item if isinstance(item, VoiceSegment) else str(item or "")
            if value:
                return value
        raise StopIteration

    def close(self) -> None:
        self._closed.set()
        if callable(self._close_source):
            self._close_source()


class _StringifyingTextStream:
    """Preserve close propagation while normalizing iterable text values."""

    def __init__(self, source: Iterable[object]) -> None:
        self._source = source
        self._iterator = iter(source)

    def __iter__(self):
        return self

    def __next__(self) -> str | VoiceSegment:
        item = next(self._iterator)
        return item if isinstance(item, VoiceSegment) else str(item or "")

    def close(self) -> None:
        close = getattr(self._source, "close", None)
        if callable(close):
            close()


class _CleanCharacterTextStream(_StringifyingTextStream):
    """Use existing directive extraction before a typed segment reaches synthesis."""
    def __init__(self, source, visual):
        super().__init__(source)
        self._visual = visual

    def __next__(self):
        from dataclasses import replace
        while True:
            item = super().__next__()
            if not isinstance(item, VoiceSegment):
                return item
            visible, _ = extract_companion_orb_focus(item.text)
            cleaned, _ = self._visual.extract_prompt(visible)
            if cleaned.strip():
                return replace(item, text=cleaned.strip())


class _RecordingTextStream(_StringifyingTextStream):
    """Observe text without losing close propagation to a blocked queue reader."""
    def __init__(self, source, trace, correlation):
        super().__init__(source)
        self._trace, self._correlation = trace, correlation

    def __next__(self):
        from core.communication_trace import record_to
        value = super().__next__()
        record_to(self._trace,'speech.route_chunk',dict(text=value),self._correlation)
        return value

    def close(self):
        from core.communication_trace import record_to
        record_to(self._trace,'speech.source_closed',{},self._correlation)
        super().close()


__all__ = [
    "AssistantReplyNotifier",
    "ProductionSpeechOutputOwner",
    "ReplyEffectAdmission",
    "SpeechLatencyRecorder",
    "SpeechLeaseProvider",
    "SpeechRouteControl",
]
