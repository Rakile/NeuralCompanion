"""Avatar lifecycle state synchronized to admitted playback."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import threading
import wave
from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from core.continuous_audio import AudioClockSample

from core.runtime.avatar_visual import (
    AvatarVisualCoordinator,
    AvatarVisualSnapshot,
)
from core.runtime.avatar_providers import AvatarProviderOperations
from core.runtime.config import RuntimeConfigSnapshot
from core.runtime.contracts import CancellationToken, CommandResult, RuntimeFailure
from core.runtime.controllers import RouteEffectOwner
from core.runtime.identifiers import WorkLease
from core.runtime.playback import DeliveredChunk, PlaybackReceipt


LeaseCheck = Callable[[WorkLease], bool]
EffectCommit = Callable[[WorkLease, Callable[[], object]], CommandResult[object]]


class AvatarAdapter(Protocol):
    """The existing provider adapter surface used by ``AvatarService``."""

    def start(self) -> object: ...

    def stop(self) -> object: ...

    def set_emotion(self, expression: str) -> object: ...

    def set_speaking_state(self, speaking: bool) -> object: ...


@dataclass(frozen=True, slots=True)
class PortraitPlaybackState:
    """Presentation-only mood tied to an admitted audio segment."""

    expression: str
    lease: WorkLease
    transaction_id: str = ""
    message_id: str = ""


@dataclass(frozen=True, slots=True)
class AvatarSnapshot:
    running: bool
    provider_id: str
    expression: str
    speaking: bool
    delivered_chunk: DeliveredChunk | None
    terminal_reason: str
    portrait_playback: PortraitPlaybackState | None = None


def _uses_chunk_buffer(adapter, result):
    return (isinstance(result, Mapping) and result.get("kind") == getattr(adapter, "avatar_provider_id", None)
            and (getattr(adapter, "avatar_provider_id", None) == "musetalk"
                 or bool(getattr(adapter, "supports_frame_buffer", False))))


class AvatarService:
    """Own adapter lifecycle and admit visible changes from playback receipts."""

    name = "avatar"

    def __init__(
        self,
        *,
        adapter: AvatarAdapter | None = None,
        lease_is_current: LeaseCheck | None = None,
        visual_coordinator: AvatarVisualCoordinator | None = None,
        provider_operations: AvatarProviderOperations | None = None,
        commit_effect: EffectCommit | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._adapter = adapter
        self._lease_is_current = lease_is_current or (lambda _lease: True)
        self._visual = visual_coordinator
        self._provider_operations = provider_operations
        self._commit_effect = commit_effect or self._commit_if_current
        self._running = False
        self._stop_pending = False
        self._expression = "neutral"
        self._speaking = False
        self._delivered_chunk: DeliveredChunk | None = None
        self._delivered_progressive_audio = False
        self._terminal_reason = ""
        self._portrait_playback: PortraitPlaybackState | None = None
        self._portrait_pending: PortraitPlaybackState | None = None
        self._prepared: dict[tuple[WorkLease, int], object] = {}
        self._prepared_results: dict[tuple[WorkLease, int], object] = {}
        # Phone audio admission consumes _prepared_results before asynchronous
        # MuseTalk work finishes. Keep completion handles until route retirement.
        self._remote_render_events: dict[tuple[WorkLease, int], object] = {}
        self._prepared_pending: dict[WorkLease, dict[int, object]] = {}
        self._prepared_next_index: dict[WorkLease, int] = {}
        self._prepared_draining: set[WorkLease] = set()
        self._waiting_owner: tuple[WorkLease, int] | None = None

    def attach(self, adapter: AvatarAdapter | None) -> CommandResult[None]:
        """Install one stopped adapter without calling provider code under lock."""

        with self._lock:
            if (self._running or self._stop_pending) and self._adapter is not adapter:
                return _failure(
                    "avatar_running",
                    "Stop the active avatar before replacing its adapter",
                )
            self._adapter = adapter
        return CommandResult(True)

    def adapter(self) -> AvatarAdapter | None:
        with self._lock:
            return self._adapter

    def attach_visual_coordinator(
        self,
        coordinator: AvatarVisualCoordinator | None,
    ) -> CommandResult[None]:
        """Install visual authority while the provider lifecycle is stopped."""

        with self._lock:
            if self._running and self._visual is not coordinator:
                return _failure(
                    "avatar_running",
                    "Stop the active avatar before replacing its visual coordinator",
                )
            self._visual = coordinator
        return CommandResult(True)

    def visual_coordinator(self) -> AvatarVisualCoordinator | None:
        with self._lock:
            return self._visual

    def attach_provider_operations(
        self,
        operations: AvatarProviderOperations | None,
    ) -> CommandResult[None]:
        with self._lock:
            if self._running and self._provider_operations is not operations:
                return _failure(
                    "avatar_running",
                    "Stop the active avatar before replacing provider operations",
                )
            self._provider_operations = operations
        return CommandResult(True)

    def start(
        self,
        config: RuntimeConfigSnapshot | None = None,
    ) -> CommandResult[None]:
        del config
        with self._lock:
            if self._running:
                return CommandResult(True)
            if self._stop_pending:
                return _failure("avatar_cleanup_pending", "Complete avatar cleanup before starting again")
            adapter = self._adapter
            self._stop_pending = adapter is not None
        try:
            if adapter is not None:
                adapter.start()
            if self._visual is not None:
                visual_started = self._visual.start()
                if not visual_started.accepted:
                    raise RuntimeError(
                        visual_started.failure.message
                        if visual_started.failure is not None
                        else "Avatar visual runtime could not start"
                    )
        except BaseException as exc:
            self.stop()
            return _failure("avatar_start_failed", f"Could not start avatar: {exc}", exc)
        with self._lock:
            if self._adapter is not adapter:
                displaced = True
            else:
                displaced = False
                self._running = True
                self._terminal_reason = ""
        if displaced:
            if self._visual is not None:
                self._visual.stop()
            try:
                if adapter is not None:
                    adapter.stop()
            except BaseException:
                pass
            return _failure(
                "avatar_adapter_replaced",
                "Avatar adapter changed while startup was in progress",
            )
        return CommandResult(True)

    def on_audio_prepared(self, prepared_chunk: object) -> None:
        """Start provider preparation in source order without changing visible state."""

        lease = _prepared_value(prepared_chunk, "lease")
        index = _prepared_index(prepared_chunk)
        if not isinstance(lease, WorkLease) or index is None:
            return
        key = (lease, index)
        metadata = _prepared_value(prepared_chunk, "source_metadata")
        with self._lock:
            if key in self._prepared:
                return
            self._prepared[key] = prepared_chunk
            # Streamed replies start at zero across all preparation groups.
            # Non-streaming/standalone callers may intentionally start elsewhere.
            if isinstance(metadata, Mapping) and bool(metadata.get("speech_route_streaming", False)):
                self._prepared_next_index.setdefault(lease, 0)
            pending = self._prepared_pending.setdefault(lease, {})
            pending[index] = prepared_chunk
            if lease in self._prepared_draining:
                return
            self._prepared_draining.add(lease)

        while True:
            with self._lock:
                pending = self._prepared_pending.get(lease)
                if not pending:
                    self._prepared_pending.pop(lease, None)
                    self._prepared_draining.discard(lease)
                    return
                expected = self._prepared_next_index.get(lease)
                if expected is None:
                    expected = min(pending)
                    self._prepared_next_index[lease] = expected
                current = pending.pop(expected, None)
                if current is None:
                    self._prepared_draining.discard(lease)
                    return

            prepared_result = self._prepare_audio_chunk(current)

            with self._lock:
                current_key = (lease, expected)
                if (
                    prepared_result is not None
                    and self._prepared.get(current_key) is current
                ):
                    self._prepared_results[current_key] = prepared_result
                    metadata = _prepared_value(current, "source_metadata")
                    holder = prepared_result.get("result_holder") if isinstance(prepared_result, Mapping) else None
                    if isinstance(holder, dict):
                        # Provider-owned playback snapshots need the same speech identity
                        # as the shared TTS pipeline; preparation alone never starts it.
                        speech_metadata = metadata if isinstance(metadata, Mapping) else {}
                        holder.update(
                            speech_session_generation=lease.session_generation.value if lease.session_generation is not None else None,
                            speech_transaction_id=str(speech_metadata.get("normal_chat_transaction_id") or ""),
                            speech_message_id=str(speech_metadata.get("replay_message_id") or ""),
                            speech_hidden=bool(speech_metadata.get("companion_orb_response") or speech_metadata.get("hidden_proactive")),
                        )
                    if (isinstance(metadata, Mapping)
                            and metadata.get("skip_local_playback")
                            and metadata.get("remote_capture_id")
                            and isinstance(prepared_result, Mapping)
                            and prepared_result.get("kind") == "musetalk"):
                        event = prepared_result.get("ready_event")
                        if callable(getattr(event, "is_set", None)):
                            self._remote_render_events[current_key] = event
                if self._prepared_next_index.get(lease) == expected:
                    self._prepared_next_index[lease] = expected + 1

    def has_pending_remote_renders(self, lease: WorkLease) -> bool:
        """Poll completion without delaying phone audio or admitting stale work."""
        if not self._lease_is_current(lease):
            self.release_remote_renders(lease)
            return False
        with self._lock:
            pending = False
            for key, event in tuple(self._remote_render_events.items()):
                if key[0] == lease:
                    if event.is_set():
                        self._remote_render_events.pop(key, None)
                    else:
                        pending = True
            return self._running and pending

    def release_remote_renders(self, lease: WorkLease) -> None:
        """Drop this route's completion handles; worker cancellation stays owned."""
        with self._lock:
            self._remote_render_events = {
                key: event for key, event in self._remote_render_events.items()
                if key[0] != lease
            }

    def _prepare_audio_chunk(self, prepared_chunk: object) -> object | None:
        lease = _prepared_value(prepared_chunk, "lease")
        if not isinstance(lease, WorkLease):
            return None
        source = _prepared_value(prepared_chunk, 'audio_source')
        if source is not None:
            with self._lock:
                adapter = self._adapter
            if adapter is None:
                return None  # No Avatar retains its existing progressive path.
            callback = getattr(adapter, 'process_audio_stream', None)
            try:
                if not getattr(adapter, 'supports_progressive_audio', False) or not callable(callback):
                    raise RuntimeError('The active avatar does not accept progressive audio.')
                if not self._lease_is_current(lease):
                    source.cancel('avatar_stale_lease')
                    return None
                return callback(source, str(_prepared_value(prepared_chunk, 'text') or ''),
                    work_lease=lease,
                    emotion_name=str(_prepared_value(prepared_chunk, 'expression') or 'neutral'),
                    chunk_index=_prepared_index(prepared_chunk),
                    cancel_check=lambda: not self._lease_is_current(lease))
            except Exception as error:
                source.fail(error)
                return {'ok':False, 'kind':getattr(adapter, 'avatar_provider_id', ''),
                        'result_holder':{'ok':False, 'error':str(error)}}
        audio_path = str(_prepared_value(prepared_chunk, "audio_path") or "").strip()
        if not audio_path:
            return None
        # Optional provider-local staging: never start playback from preparation.
        with self._lock:
            adapter = self._adapter
        stage = getattr(adapter, "on_audio_prepared", None)
        if callable(stage) and self._lease_is_current(lease):
            try:
                stage(prepared_chunk)
            except Exception as exc:
                print(f"[Avatar] Optional speech staging failed: {exc}")
        metadata = _prepared_value(prepared_chunk, "source_metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        prepared = self.process_audio_chunk(
            lease,
            audio_path=audio_path,
            text=str(_prepared_value(prepared_chunk, "text") or ""),
            expression=str(_prepared_value(prepared_chunk, "expression") or "").strip(),
            output_filename=Path(audio_path).name,
            dry_run_reply_id=str(metadata.get("dry_run_reply_id") or "") or None,
            remote_output_reply_id=(str(metadata.get('remote_capture_id') or '') or None)
                if metadata.get('phone_reply_control') and metadata.get('skip_local_playback') else None,
            remote_output_sequence_index=_prepared_value(prepared_chunk, 'index')
                if metadata.get('phone_reply_control') and metadata.get('skip_local_playback') else None,
            cancel_check=lambda: not self._lease_is_current(lease),
            chunk_index=_prepared_index(prepared_chunk),
        )
        if not prepared.accepted or prepared.value is None:
            return None
        return prepared.value

    def wait_until_audio_ready(
        self,
        prepared_chunk: object,
        cancellation: CancellationToken,
        *,
        route_owner: RouteEffectOwner | None = None,
        on_waiting: Callable[[], object] | None = None,
    ) -> CommandResult[bool]:
        """Gate local audio until an attached visual provider has initial frames."""

        lease = _prepared_value(prepared_chunk, "lease")
        index = _prepared_index(prepared_chunk)
        if not isinstance(lease, WorkLease) or index is None:
            return CommandResult(True, True)
        with self._lock:
            result = self._prepared_results.get((lease, index))
            visual = self._visual
        if visual is None or not isinstance(result, Mapping):
            return CommandResult(True, True)
        if not _uses_chunk_buffer(self.adapter(), result):
            return CommandResult(True, True)
        admitted_event = result.get("playback_admitted_event")
        if hasattr(admitted_event, "set"):
            admitted_event.set()
        metadata = _prepared_value(prepared_chunk, "source_metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        return visual.wait_for_chunk_buffer(
            result,
            lease,
            streaming=bool(metadata.get("speech_route_streaming", False)),
            cancellation=cancellation,
            route_owner=route_owner,
            on_waiting=on_waiting,
        )

    def preflight_audio_ready(
        self, prepared_chunk: object, cancellation: CancellationToken, *,
        route_owner: RouteEffectOwner | None = None,
    ) -> CommandResult[bool]:
        """Buffer future visuals without publishing or admitting their idle planner."""
        lease = _prepared_value(prepared_chunk, "lease")
        index = _prepared_index(prepared_chunk)
        with self._lock:
            result = self._prepared_results.get((lease, index))
            visual = self._visual
            adapter = self._adapter
        if str(getattr(adapter, "avatar_provider_id", "")).lower() != "musetalk" and not getattr(adapter, "supports_frame_buffer", False):
            return CommandResult(True, True)
        if (not isinstance(lease, WorkLease) or index is None or visual is None
                or not _uses_chunk_buffer(adapter, result)):
            return _failure("avatar_visual_chunk_missing", "MuseTalk preparation produced no visual result")
        if result.get("ok") is False:
            return _failure("avatar_visual_chunk_failed", "MuseTalk preparation failed")
        metadata = _prepared_value(prepared_chunk, "source_metadata")
        return visual.wait_for_chunk_buffer(result, lease,
            streaming=bool(isinstance(metadata, Mapping) and metadata.get("speech_route_streaming", False)),
            cancellation=cancellation, route_owner=route_owner)

    def on_playback_started(
        self,
        chunk: DeliveredChunk,
        *,
        route_owner: RouteEffectOwner | None = None,
    ) -> None:
        """Advance the adapter only after playback's final delivery admission."""

        if not self._lease_is_current(chunk.lease):
            return
        with self._lock:
            if not self._running:
                return
            adapter = self._adapter
            key = (chunk.lease, chunk.index)
            prepared = self._prepared.pop(key, None)
            prepared_result = self._prepared_results.pop(key, None)
            expression = str(
                _prepared_value(prepared, "expression") or ""
            ).strip()
            metadata = _prepared_value(prepared, "source_metadata")
            metadata = metadata if isinstance(metadata, Mapping) else {}
            portrait = PortraitPlaybackState(
                expression=expression or "neutral", lease=chunk.lease,
                transaction_id=str(metadata.get("normal_chat_transaction_id") or ""),
                message_id=str(metadata.get("replay_message_id") or ""),
            )
            self._portrait_pending = portrait if chunk.audio_start_pending else None
            if not chunk.audio_start_pending:
                self._portrait_playback = portrait
            prepared_admitted_event = _prepared_value(
                prepared,
                "playback_admitted_event",
            )
            result_admitted_event = _prepared_value(
                prepared_result,
                "playback_admitted_event",
            )
            visual = self._visual
            self._speaking = True
            self._delivered_chunk = chunk
            self._delivered_progressive_audio = bool(
                isinstance(prepared_result, Mapping) and prepared_result.get("progressive_audio", False)
            )
            self._waiting_owner = None
            self._terminal_reason = ""
        continuous = chunk.audio_started_monotonic is not None
        if not continuous:
            for admitted_event in (prepared_admitted_event, result_admitted_event):
                if hasattr(admitted_event, "set"):
                    admitted_event.set()
        if (
            visual is not None
            and isinstance(prepared_result, Mapping)
            and str(prepared_result.get("kind") or "").strip().lower() == "musetalk"
        ):
            sample = chunk.audio_clock_sample
            if sample is not None and sample.key != chunk.index:
                sample = None
            if sample is not None:
                from core.continuous_audio import continuous_media_seconds
                if continuous_media_seconds(dict(audio_media_seconds=sample.media_seconds,
                        audio_clock_monotonic=sample.sampled_monotonic,
                        audio_scheduled_through_seconds=sample.scheduled_through_seconds,
                        audio_clock_running=sample.running), sample.sampled_monotonic) is None:
                    sample = None
            audio = _prepared_value(prepared, "playback_audio")
            pcm = getattr(audio, "decoded_pcm", None)
            duration = (pcm.shape[0] / audio.sample_rate if continuous and pcm is not None
                        else _wav_duration_seconds(str(_prepared_value(prepared, "audio_path") or "")))
            visual.begin_chunk_playback(
                prepared_result,
                chunk.lease,
                text=str(_prepared_value(prepared, "text") or chunk.text or ""),
                audio_duration_seconds=duration,
                route_owner=route_owner,
                audio_start_pending=bool(
                    getattr(chunk, "audio_start_pending", False) or (continuous and sample is None)
                ),
                **({"audio_clock_sample": sample, "continuous": True,
                    "audio_chunk_index": chunk.index} if continuous else {}),
            )
        if continuous:
            # A waiting first-chunk planner must observe speech before waking;
            # otherwise its old idle snapshot can overwrite this admission.
            for admitted_event in (prepared_admitted_event, result_admitted_event):
                if hasattr(admitted_event, "set"):
                    admitted_event.set()
        if adapter is None:
            return
        if expression:
            try:
                adapter.set_emotion(expression)
            except BaseException:
                pass
            else:
                with self._lock:
                    if self._adapter is adapter and self._running:
                        self._expression = expression
        callback = getattr(adapter, "on_playback_started", None)
        try:
            if callable(callback):
                callback(chunk)
            else:
                adapter.set_speaking_state(True)
        except BaseException:
            return

    def on_audio_started(
        self,
        chunk: DeliveredChunk,
        *,
        route_owner: RouteEffectOwner | None = None,
    ) -> None:
        """Synchronize a pending MuseTalk clock with the admitted device start."""

        if not self._lease_is_current(chunk.lease):
            return
        with self._lock:
            delivered = self._delivered_chunk
            if (
                not self._running
                or not self._speaking
                or delivered is None
                or delivered.lease != chunk.lease
                or delivered.index != chunk.index
                or delivered.owner_generation != chunk.owner_generation
            ):
                return
            adapter = self._adapter
            visual = self._visual
            if self._portrait_pending is not None:
                self._portrait_playback = self._portrait_pending
                self._portrait_pending = None
            provider_id = str(
                getattr(adapter, "avatar_provider_id", "") or ""
            ).strip().lower()
        if visual is not None and provider_id == "musetalk":
            visual.synchronize_audio_start(chunk.lease, route_owner=route_owner)
        callback = getattr(adapter, "on_audio_started", None)
        if callable(callback):
            callback(chunk)

    def on_audio_progress(self, chunk: DeliveredChunk, sample: AudioClockSample, *,
                          route_owner: RouteEffectOwner | None = None) -> None:
        """Only the exact currently delivered chunk may advance transient media."""
        if not self._lease_is_current(chunk.lease) or sample.key != chunk.index:
            return
        with self._lock:
            current = self._delivered_chunk
            adapter = self._adapter
            visual = self._visual
            if (not self._running or not self._speaking or current is None
                    or (current.lease, current.owner_generation, current.index) !=
                       (chunk.lease, chunk.owner_generation, chunk.index)):
                return
        if visual is not None:
            visual.update_audio_progress(chunk.lease, chunk.index, sample, route_owner=route_owner)
        callback = getattr(adapter, "on_audio_progress", None)
        if callable(callback):
            callback(chunk, sample)

    def on_playback_waiting(
        self,
        owner,
        *,
        route_owner: RouteEffectOwner | None = None,
    ) -> None:
        """Show local idle only during a genuine streamed between-chunk wait."""

        with self._lock:
            delivered = self._delivered_chunk
            if (
                not self._running
                or not self._speaking
                or delivered is None
                or owner.lease != delivered.lease
                or owner.generation != delivered.owner_generation
            ):
                return
            waiting_owner = (owner.lease, owner.generation)
            if self._waiting_owner == waiting_owner:
                return
            adapter = self._adapter
            visual = self._visual
            provider_id = str(
                getattr(adapter, "avatar_provider_id", "") or ""
            ).strip().lower()
            self._waiting_owner = waiting_owner
            progressive_audio = self._delivered_progressive_audio
        if visual is not None and provider_id == "musetalk" and not progressive_audio:
            visual.transition_to_local_idle(
                owner.lease,
                advance_to_next_frame=True,
                route_owner=route_owner,
            )
        callback = getattr(adapter, "on_playback_waiting", None)
        if callable(callback):
            callback(owner)

    def on_playback_finished(
        self,
        receipt: PlaybackReceipt,
        *,
        route_owner: RouteEffectOwner | None = None,
    ) -> None:
        """Publish terminal speaking state from the playback-owned receipt."""

        owner = receipt.owner
        with self._lock:
            if not self._running:
                return
            delivered = self._delivered_chunk
            if (
                owner is not None
                and delivered is not None
                and (
                    owner.lease != delivered.lease
                    or owner.generation != delivered.owner_generation
                )
            ):
                return
            adapter = self._adapter
            visual = self._visual
            provider_id = str(
                getattr(adapter, "avatar_provider_id", "") or ""
            ).strip().lower()
            self._speaking = False
            self._delivered_progressive_audio = False
            self._waiting_owner = None
            self._terminal_reason = str(receipt.terminal_reason or "")
            if owner is not None:
                self._prepared = {
                    key: value
                    for key, value in self._prepared.items()
                    if key[0] != owner.lease
                }
                self._prepared_results = {
                    key: value
                    for key, value in self._prepared_results.items()
                    if key[0] != owner.lease
                }
        if visual is not None and provider_id == "musetalk":
            idle_lease = owner.lease if owner is not None else (
                delivered.lease if delivered is not None else None
            )
            if isinstance(idle_lease, WorkLease):
                if route_owner is not None:
                    visual.transition_to_terminal_idle(
                        idle_lease,
                        route_owner=route_owner,
                    )
                else:
                    visual.transition_to_local_idle(idle_lease)
        if adapter is None:
            return
        callback = getattr(adapter, "on_playback_finished", None)
        try:
            if callable(callback):
                callback(receipt)
            else:
                adapter.set_speaking_state(False)
        except BaseException:
            return

    def on_playback_paused(
        self,
        owner,
        *,
        route_owner: RouteEffectOwner | None = None,
    ) -> None:
        """Return the active avatar to idle at an admitted chunk boundary."""

        with self._lock:
            if not self._running:
                return
            delivered = self._delivered_chunk
            if (
                delivered is None
                or owner.lease != delivered.lease
                or owner.generation != delivered.owner_generation
            ):
                return
            adapter = self._adapter
            visual = self._visual
            provider_id = str(
                getattr(adapter, "avatar_provider_id", "") or ""
            ).strip().lower()
            self._speaking = False
            self._waiting_owner = None
        if visual is not None and provider_id == "musetalk":
            visual.transition_to_local_idle(
                owner.lease,
                advance_to_next_frame=True,
                route_owner=route_owner,
            )
        if adapter is None:
            return
        try:
            callback = getattr(adapter, "on_playback_paused", None)
            if callable(callback):
                callback(owner)
            else:
                adapter.set_speaking_state(False)
        except BaseException:
            return

    def set_expression(
        self,
        expression: str,
        lease: WorkLease,
    ) -> CommandResult[None]:
        value = str(expression or "neutral").strip() or "neutral"
        def publish() -> None:
            with self._lock:
                if not self._running:
                    raise _AvatarStopped()
                adapter = self._adapter
            if adapter is not None:
                adapter.set_emotion(value)
            with self._lock:
                if self._adapter is adapter and self._running:
                    self._expression = value

        try:
            committed = self._commit_effect(lease, publish)
        except _AvatarStopped:
            return _failure("avatar_stopped", "Avatar service is not running")
        except BaseException as exc:
            return _failure(
                "avatar_expression_failed",
                f"Could not set avatar expression: {exc}",
                exc,
            )
        if not committed.accepted:
            return CommandResult(False, failure=committed.failure)
        return CommandResult(True)

    def matches_provider(self, provider_id: str) -> bool:
        with self._lock:
            adapter = self._adapter
        actual = str(getattr(adapter, "avatar_provider_id", "") or "").strip().lower()
        return bool(actual and actual == str(provider_id or "").strip().lower())

    def current_expression(self, default: str = "neutral") -> str:
        with self._lock:
            adapter = self._adapter
            service_expression = self._expression
        tag = str(getattr(adapter, "current_tag", "") or "").strip().lower()
        fallback = str(service_expression or default or "neutral").strip().lower()
        return tag or fallback or "neutral"

    def active_vram_mode(
        self,
        runtime_config: Mapping[str, object],
        default: str = "quality",
    ) -> str:
        operations = self._provider_operations
        if operations is None:
            fallback = str(default or "quality").strip().lower() or "quality"
            return str(
                runtime_config.get(
                    "avatar_vram_mode",
                    runtime_config.get("vram_mode", fallback),
                )
                or fallback
            ).strip().lower()
        return operations.active_vram_mode(runtime_config, default)

    def chunk_limits_for_index(
        self,
        chunk_index: int,
        runtime_config: Mapping[str, object],
        *,
        quickstart: Sequence[Sequence[int]],
        target: int,
        maximum: int,
    ) -> tuple[int, int]:
        operations = self._provider_operations
        if operations is None:
            return (max(1, int(target)), max(1, int(maximum)))
        return operations.chunk_limits_for_index(
            chunk_index,
            runtime_config,
            quickstart=quickstart,
            target=target,
            maximum=maximum,
        )

    def normalize_musetalk_enabled_emotions(
        self,
        value: object,
    ) -> Mapping[str, object]:
        operations = self._provider_operations
        return operations.normalize_musetalk_enabled_emotions(value) if operations else {}

    def musetalk_enabled_emotions(
        self,
        runtime_config: Mapping[str, object],
        pack_id: str,
    ) -> tuple[str, ...] | None:
        operations = self._provider_operations
        if operations is None:
            return None
        return operations.musetalk_enabled_emotions(runtime_config, pack_id)

    def musetalk_pack_catalog(
        self,
        runtime_config: Mapping[str, object],
    ) -> tuple[Mapping[str, object], ...]:
        operations = self._provider_operations
        return operations.musetalk_pack_catalog(runtime_config) if operations else ()

    def select_musetalk_pack(
        self,
        runtime_config: Mapping[str, object],
        pack_id: str,
        lease: WorkLease,
    ) -> CommandResult[str]:
        operations = self._provider_operations
        if operations is None:
            return CommandResult(
                False,
                failure=RuntimeFailure(
                    "avatar_provider_operations_unavailable",
                    "Avatar provider operations are unavailable",
                ),
            )
        return operations.select_musetalk_pack(runtime_config, pack_id, lease)

    def begin_reply(self) -> CommandResult[None]:
        with self._lock:
            if not self._running:
                return _failure("avatar_stopped", "Avatar service is not running")
            adapter = self._adapter
            self._prepared_pending.clear()
            self._prepared_next_index.clear()
            self._prepared_draining.clear()
        callback = getattr(adapter, "begin_reply", None)
        try:
            if callable(callback):
                callback()
        except BaseException as exc:
            return _failure(
                "avatar_begin_reply_failed",
                f"Could not begin avatar reply: {exc}",
                exc,
            )
        return CommandResult(True)

    def warm_up(self) -> CommandResult[None]:
        with self._lock:
            if not self._running:
                return _failure("avatar_stopped", "Avatar service is not running")
            adapter = self._adapter
        callback = getattr(adapter, "warm_up", None)
        try:
            if callable(callback):
                callback()
        except BaseException as exc:
            return _failure(
                "avatar_warmup_failed",
                f"Could not warm up avatar: {exc}",
                exc,
            )
        return CommandResult(True)

    def prepare_expression(
        self,
        expression: str,
        lease: WorkLease,
    ) -> CommandResult[None]:
        if not self._lease_is_current(lease):
            return _failure("avatar_stale_lease", "Avatar preparation lease is stale")
        with self._lock:
            if not self._running:
                return _failure("avatar_stopped", "Avatar service is not running")
            adapter = self._adapter
        callback = getattr(adapter, "prepare_emotion", None)
        try:
            if callable(callback):
                callback(str(expression or "neutral").strip() or "neutral")
        except BaseException as exc:
            return _failure(
                "avatar_prepare_expression_failed",
                f"Could not prepare avatar expression: {exc}",
                exc,
            )
        if not self._lease_is_current(lease):
            return _failure("avatar_stale_lease", "Avatar preparation lease became stale")
        return CommandResult(True)

    def process_audio_chunk(
        self,
        lease: WorkLease,
        *,
        audio_path: str,
        text: str,
        expression: str = "",
        output_filename: str,
        dry_run_reply_id: str | None = None,
        remote_output_reply_id: str | None = None,
        remote_output_sequence_index: int | None = None,
        chunk_index: int | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> CommandResult[object]:
        if not self._lease_is_current(lease):
            return _failure("avatar_stale_lease", "Avatar audio preparation lease is stale")
        with self._lock:
            if not self._running:
                return _failure("avatar_stopped", "Avatar service is not running")
            adapter = self._adapter
        callback = getattr(adapter, "process_audio_chunk", None)
        if not callable(callback):
            return _failure(
                "avatar_audio_unsupported",
                "The active avatar does not process audio chunks",
            )
        try:
            provider_id = str(
                getattr(adapter, "avatar_provider_id", "") or ""
            ).strip().lower()
            provider_options = (
                {
                    "work_lease": lease,
                    "emotion_name": str(expression or "").strip() or "neutral",
                    **({'remote_output_reply_id': remote_output_reply_id,
                        'remote_output_sequence_index': remote_output_sequence_index} if remote_output_reply_id else {}),
                }
                if provider_id == "musetalk" or getattr(adapter, "supports_frame_buffer", False)
                else {}
            )
            if getattr(adapter, "supports_frame_buffer", False):
                provider_options["chunk_index"] = chunk_index
            result = callback(
                str(audio_path),
                str(text or ""),
                str(output_filename),
                dry_run_reply_id=dry_run_reply_id,
                cancel_check=cancel_check,
                **provider_options,
            )
        except BaseException as exc:
            return _failure(
                "avatar_audio_processing_failed",
                f"Could not process avatar audio chunk: {exc}",
                exc,
            )
        try:
            cancelled = bool(cancel_check is not None and cancel_check())
        except BaseException:
            cancelled = False
        if not self._lease_is_current(lease) or cancelled:
            return _failure(
                "avatar_stale_lease",
                "Avatar audio result no longer owns its preparation lease",
            )
        return CommandResult(True, result)

    def begin_chunk_playback(
        self,
        chunk_result: object,
        lease: WorkLease,
    ) -> CommandResult[object]:
        def publish() -> object:
            with self._lock:
                if not self._running:
                    raise _AvatarStopped()
                adapter = self._adapter
            callback = getattr(adapter, "begin_chunk_playback", None)
            return callback(chunk_result) if callable(callback) else None

        try:
            committed = self._commit_effect(lease, publish)
        except _AvatarStopped:
            return _failure("avatar_stopped", "Avatar service is not running")
        except BaseException as exc:
            return _failure(
                "avatar_chunk_playback_failed",
                f"Could not begin avatar chunk playback: {exc}",
                exc,
            )
        if not committed.accepted:
            return CommandResult(False, failure=committed.failure)
        return CommandResult(True, committed.value)

    def select_attached_musetalk_pack(self, pack_id: str) -> CommandResult[str]:
        """Invoke the active adapter hook after policy/config admission."""

        selected = str(pack_id or "").strip()
        if not selected:
            return _failure("avatar_pack_required", "An avatar pack id is required")
        with self._lock:
            adapter = self._adapter
            is_musetalk = (
                str(getattr(adapter, "avatar_provider_id", "") or "")
                .strip()
                .lower()
                == "musetalk"
            )
            if not self._running or not is_musetalk:
                return _failure("avatar_musetalk_inactive", "MuseTalk is not active")
        callback = getattr(adapter, "select_avatar_pack", None)
        if not callable(callback):
            return _failure("avatar_pack_unsupported", "Avatar pack selection is unavailable")
        try:
            callback(selected)
        except BaseException as exc:
            return _failure(
                "avatar_pack_selection_failed",
                f"Could not select avatar pack: {exc}",
                exc,
            )
        return CommandResult(True, selected)

    def default_avatar_id(self) -> str:
        with self._lock:
            adapter = self._adapter
        return str(getattr(adapter, "default_avatar_id", "") or "").strip()

    def resolve_asset_path(self, path: str | Path) -> Path:
        candidate = Path(path).expanduser()
        if candidate.is_absolute():
            return candidate.resolve()
        with self._lock:
            adapter = self._adapter
        root_text = str(getattr(adapter, "root_dir", "") or "").strip()
        return (
            (Path(root_text).expanduser() / candidate).resolve()
            if root_text
            else candidate.resolve()
        )

    def visual_snapshot(self) -> AvatarVisualSnapshot | None:
        return self._visual.snapshot() if self._visual is not None else None

    def clear_visual_state(self, lease: WorkLease) -> CommandResult[bool]:
        if self._visual is None:
            return _failure("avatar_visual_unavailable", "Avatar visual runtime is unavailable")
        return self._visual.clear(lease)

    def set_musetalk_idle_state(
        self,
        lease: WorkLease,
        *,
        route_owner: RouteEffectOwner | None = None,
    ) -> CommandResult[bool]:
        if self._visual is None:
            return _failure("avatar_visual_unavailable", "Avatar visual runtime is unavailable")
        return self._visual.set_idle(lease, route_owner=route_owner)

    def set_musetalk_idle_state_for_avatar(
        self,
        avatar_id: str,
        lease: WorkLease,
        *,
        route_owner: RouteEffectOwner | None = None,
    ) -> CommandResult[bool]:
        if self._visual is None:
            return _failure("avatar_visual_unavailable", "Avatar visual runtime is unavailable")
        return self._visual.set_idle_for_avatar(
            avatar_id,
            lease,
            route_owner=route_owner,
        )

    def reset_session_presentation(self, lease: WorkLease) -> CommandResult[bool]:
        """Return an interrupted current session to idle outside a retired route."""

        if not self._lease_is_current(lease):
            return _failure("avatar_stale_lease", "Avatar session presentation lease is stale")
        with self._lock:
            if not self._running:
                return CommandResult(True, False)
            adapter = self._adapter
            visual = self._visual
            provider_id = str(
                getattr(adapter, "avatar_provider_id", "") or ""
            ).strip().lower()
            self._speaking = False
            self._waiting_owner = None
            self._terminal_reason = "session_reset"
        if visual is not None and provider_id == "musetalk":
            return visual.transition_to_local_idle(
                lease,
                advance_to_next_frame=True,
            )
        if adapter is not None:
            try:
                adapter.set_speaking_state(False)
            except BaseException:
                pass
        return CommandResult(True, False)

    def transition_musetalk_to_local_idle(
        self,
        lease: WorkLease,
        *,
        advance_to_next_frame: bool = True,
        route_owner: RouteEffectOwner | None = None,
    ) -> CommandResult[bool]:
        if self._visual is None:
            return _failure("avatar_visual_unavailable", "Avatar visual runtime is unavailable")
        return self._visual.transition_to_local_idle(
            lease,
            advance_to_next_frame=advance_to_next_frame,
            route_owner=route_owner,
        )

    def play_musetalk_transition(
        self,
        from_avatar_id: str,
        to_avatar_id: str,
        lease: WorkLease,
        *,
        route_owner: RouteEffectOwner,
    ) -> CommandResult[float]:
        if self._visual is None:
            return _failure("avatar_visual_unavailable", "Avatar visual runtime is unavailable")
        return self._visual.play_transition(
            from_avatar_id,
            to_avatar_id,
            lease,
            route_owner=route_owner,
        )

    def maybe_transition_musetalk_to_default(
        self,
        current_avatar_id: str,
        lease: WorkLease,
        *,
        route_owner: RouteEffectOwner,
    ) -> CommandResult[bool]:
        if self._visual is None:
            return _failure("avatar_visual_unavailable", "Avatar visual runtime is unavailable")
        return self._visual.maybe_transition_to_default(
            current_avatar_id,
            lease,
            route_owner=route_owner,
        )

    def loop_current_musetalk_state(
        self,
        lease: WorkLease,
        *,
        route_owner: RouteEffectOwner,
    ) -> CommandResult[bool]:
        if self._visual is None:
            return _failure("avatar_visual_unavailable", "Avatar visual runtime is unavailable")
        return self._visual.loop_current(lease, route_owner=route_owner)

    def freeze_current_musetalk_frame(
        self,
        lease: WorkLease,
        *,
        route_owner: RouteEffectOwner,
    ) -> CommandResult[bool]:
        if self._visual is None:
            return _failure("avatar_visual_unavailable", "Avatar visual runtime is unavailable")
        return self._visual.freeze_current(lease, route_owner=route_owner)

    def transition_musetalk_after_interrupt(
        self,
        lease: WorkLease,
        *,
        route_owner: RouteEffectOwner,
        delay_seconds: float = 0.35,
    ) -> CommandResult[bool]:
        if self._visual is None:
            return _failure("avatar_visual_unavailable", "Avatar visual runtime is unavailable")
        return self._visual.transition_after_interrupt(
            lease,
            route_owner=route_owner,
            delay_seconds=delay_seconds,
        )

    def snapshot(self) -> AvatarSnapshot:
        with self._lock:
            adapter = self._adapter
            return AvatarSnapshot(
                running=self._running,
                provider_id=str(getattr(adapter, "avatar_provider_id", "") or ""),
                expression=self._expression,
                speaking=self._speaking,
                delivered_chunk=self._delivered_chunk,
                terminal_reason=self._terminal_reason,
                portrait_playback=self._portrait_playback,
            )

    def stop(self) -> CommandResult[None]:
        with self._lock:
            adapter = self._adapter
            needs_stop = self._running or self._stop_pending
            self._stop_pending = needs_stop and adapter is not None
            self._running = False
            self._speaking = False
            self._delivered_progressive_audio = False
            self._prepared.clear()
            self._prepared_results.clear()
            self._remote_render_events.clear()
            self._prepared_pending.clear()
            self._prepared_next_index.clear()
            self._prepared_draining.clear()
        visual_failure = None
        if self._visual is not None:
            try:
                visual_stopped = self._visual.stop()
                visual_failure = visual_stopped.failure if not visual_stopped.accepted else None
            except BaseException as exc:
                visual_failure = RuntimeFailure("avatar_visual_stop_failed", str(exc), exc)
        try:
            if needs_stop and adapter is not None:
                stopper = getattr(adapter, "stop_strict", None) or adapter.stop
                stopped = stopper()
                if isinstance(stopped, CommandResult) and not stopped.accepted:
                    return stopped
                if stopped is False:
                    return _failure("avatar_stop_failed", "Avatar rejected cleanup")
        except BaseException as exc:
            return _failure("avatar_stop_failed", f"Could not stop avatar: {exc}", exc)
        if visual_failure is not None:
            return CommandResult(False, failure=visual_failure)
        with self._lock:
            self._stop_pending = False
        return CommandResult(True)

    def _commit_if_current(
        self,
        lease: WorkLease,
        effect: Callable[[], object],
    ) -> CommandResult[object]:
        if not self._lease_is_current(lease):
            return _failure("avatar_stale_lease", "Avatar effect lease is stale")
        return CommandResult(True, effect())


class _AvatarStopped(RuntimeError):
    pass


def _prepared_value(prepared: object, name: str) -> object:
    if isinstance(prepared, Mapping):
        return prepared.get(name)
    return getattr(prepared, name, None)


def _prepared_index(prepared: object) -> int | None:
    try:
        value = _prepared_value(prepared, "index")
        return int(value)
    except (TypeError, ValueError):
        return None


def _wav_duration_seconds(path: str) -> float:
    candidate = str(path or "").strip()
    if not candidate:
        return 0.0
    try:
        with wave.open(candidate, "rb") as audio:
            rate = int(audio.getframerate() or 0)
            return float(audio.getnframes()) / rate if rate > 0 else 0.0
    except (OSError, EOFError, wave.Error):
        return 0.0


def _failure(
    category: str,
    message: str,
    cause: BaseException | None = None,
) -> CommandResult[None]:
    return CommandResult(False, failure=RuntimeFailure(category, message, cause))


__all__ = ["AvatarService", "AvatarSnapshot"]
